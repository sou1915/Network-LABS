/* Network LABS guest protocol v1. No shell, arbitrary argv or TCP listener. */
#define _GNU_SOURCE
#include <sys/socket.h>
#include <arpa/inet.h>
#include <linux/vm_sockets.h>
#include <sys/wait.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <linux/sockios.h>
#include <linux/if_bridge.h>
#include <linux/netlink.h>
#include <linux/netfilter/nfnetlink.h>
#include <linux/netfilter/nf_tables.h>
#include <sys/time.h>
#include <net/if.h>
#include <dirent.h>
#include <signal.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LIMIT 32768
static int valid_port(const char *value) {
    return strlen(value) == 4 && !strncmp(value, "eth", 3) && value[3] >= '0' && value[3] <= '3';
}
static int valid_cidr(const char *value) {
    char ip[16]; const char *slash = strchr(value, '/');
    if (!slash || slash == value || slash - value >= (int)sizeof(ip)) return 0;
    size_t length = (size_t)(slash - value);
    memcpy(ip, value, length); ip[length] = 0;
    struct in_addr address;
    if (inet_pton(AF_INET, ip, &address) != 1) return 0;
    const char *prefix = slash + 1; size_t digits = strlen(prefix);
    if (digits < 1 || digits > 2 || (digits > 1 && prefix[0] == '0')) return 0;
    for (size_t i = 0; i < digits; i++) if (prefix[i] < '0' || prefix[i] > '9') return 0;
    return atoi(prefix) <= 32;
}
static int valid_port_number(const char *value) {
    if (!value[0] || value[0] == '0' || strspn(value, "0123456789") != strlen(value) || strlen(value) > 5) return 0;
    long number = atol(value); return number >= 1 && number <= 65535;
}
/* Ask nf_tables for its generation: a read-only request that only an nf_tables kernel answers. */
static int has_nftables(void) {
    int fd = socket(AF_NETLINK, SOCK_RAW | SOCK_CLOEXEC, NETLINK_NETFILTER);
    if (fd < 0) return 0;
    struct { struct nlmsghdr header; struct nfgenmsg generic; } query;
    memset(&query, 0, sizeof(query));
    query.header.nlmsg_len = sizeof(query);
    query.header.nlmsg_type = (NFNL_SUBSYS_NFTABLES << 8) | NFT_MSG_GETGEN;
    query.header.nlmsg_flags = NLM_F_REQUEST | NLM_F_ACK;
    query.generic.version = NFNETLINK_V0;
    struct timeval limit = {1, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &limit, sizeof(limit));
    char answer[512]; int present = 0;
    if (send(fd, &query, sizeof(query), 0) == (ssize_t)sizeof(query)) {
        ssize_t n = recv(fd, answer, sizeof(answer), 0);
        if (n >= (ssize_t)sizeof(struct nlmsghdr)) {
            struct nlmsghdr *header = (struct nlmsghdr *)answer;
            if (header->nlmsg_type != NLMSG_ERROR) present = 1;
            else if (n >= (ssize_t)(sizeof(struct nlmsghdr) + sizeof(struct nlmsgerr)))
                present = ((struct nlmsgerr *)NLMSG_DATA(header))->error == 0;
        }
    }
    close(fd);
    return present;
}
static int send_all(int fd, const char *data, size_t size) {
    while (size) {
        ssize_t n = write(fd, data, size);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        data += n; size -= (size_t)n;
    }
    return 0;
}
static void reply(int fd, int code, const char *data, size_t size) {
    char header[64];
    int n = snprintf(header, sizeof(header), "NL1 %d %zu\n", code, size);
    if (!send_all(fd, header, (size_t)n)) (void)send_all(fd, data, size);
}
static void serve(int input, int output, int mutations) {
    char request[160]; size_t used = 0;
    alarm(5); /* Includes partial requests, child execution and slow readers. */
    while (used < sizeof(request) - 1) {
        char c; ssize_t n = read(input, &c, 1);
        if (n < 0 && errno == EINTR) continue;
        if (n != 1 || c == '\0') { reply(output, 2, "invalid request", 15); return; }
        if (c == '\n') break;
        request[used++] = c;
    }
    if (used == sizeof(request) - 1) { reply(output, 2, "request too long", 16); return; }
    request[used] = 0;
    if (!strcmp(request, "NL1 READY")) {
        const char *ready = "{\"protocol\":1,\"agent_ready\":true,\"network_verified\":false}";
        reply(output, 0, ready, strlen(ready)); return;
    }
    if (!strcmp(request, "NL1 KERNEL")) {
        /* What this guest kernel can do, probed without changing anything. */
        unsigned long version[3] = {BRCTL_GET_VERSION, 0, 0};
        int probe = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
        int bridge = probe >= 0 && ioctl(probe, SIOCGIFBR, version) >= 0;
        if (probe >= 0) close(probe);
        char report[256];
        int n = snprintf(report, sizeof(report),
            "bridge=%d\nvlan=%d\niptables=%d\nnftables=%d\nconntrack=%d\nipv6_forwarding=%d\n",
            bridge, !access("/proc/net/vlan", F_OK), !access("/proc/net/ip_tables_names", F_OK),
            has_nftables(),
            !access("/proc/sys/net/netfilter/nf_conntrack_max", F_OK),
            !access("/proc/sys/net/ipv6/conf/all/forwarding", F_OK));
        reply(output, 0, report, (size_t)n); return;
    }
    /* IPv4 forwarding is one kernel switch: read or write it directly, never through a command line. */
    const char *forward_path = "/proc/sys/net/ipv4/ip_forward";
    if (!strcmp(request, "NL1 FORWARDING")) {
        char value[4]; int fd = open(forward_path, O_RDONLY | O_CLOEXEC);
        ssize_t n = fd < 0 ? -1 : read(fd, value, sizeof(value));
        if (fd >= 0) close(fd);
        if (n < 1) { reply(output, 1, "forwarding state unavailable", 28); return; }
        reply(output, 0, value, (size_t)n); return;
    }
    int forward_on = !strcmp(request, "NL1 FORWARD on"), forward_off = !strcmp(request, "NL1 FORWARD off");
    if (mutations && (forward_on || forward_off)) {
        int fd = open(forward_path, O_WRONLY | O_CLOEXEC);
        ssize_t n = fd < 0 ? -1 : write(fd, forward_on ? "1\n" : "0\n", 2);
        if (fd >= 0) close(fd);
        if (n != 2) { reply(output, 1, "forwarding change failed", 24); return; }
        reply(output, 0, "", 0); return;
    }
    /* One untagged learning bridge (the guest kernel has no 802.1Q): typed ioctls, no brctl applet. */
    if (!strcmp(request, "NL1 BRIDGE_PORTS")) {
        DIR *directory = opendir("/sys/class/net/br0/brif");
        if (!directory) { reply(output, 1, "no bridge", 9); return; }
        char list[256]; size_t size = 0; struct dirent *entry;
        while ((entry = readdir(directory))) {
            if (entry->d_name[0] == '.') continue;
            int n = snprintf(list + size, sizeof(list) - size, "%s\n", entry->d_name);
            if (n < 0 || (size_t)n >= sizeof(list) - size) { closedir(directory); reply(output, 3, "too many bridge ports", 21); return; }
            size += (size_t)n;
        }
        closedir(directory);
        reply(output, 0, list, size); return;
    }
    char bridge_port[5], bridge_extra;
    if (mutations && sscanf(request, "NL1 BRIDGE_ADD %4s %c", bridge_port, &bridge_extra) == 1 && valid_port(bridge_port)) {
        int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0), failure = fd < 0 ? errno : 0;
        if (!failure && ioctl(fd, SIOCBRADDBR, "br0") < 0 && errno != EEXIST) failure = errno;
        struct ifreq change;
        memset(&change, 0, sizeof(change)); strncpy(change.ifr_name, "br0", IFNAMSIZ - 1);
        change.ifr_ifindex = (int)if_nametoindex(bridge_port);
        if (!failure && (!change.ifr_ifindex || ioctl(fd, SIOCBRADDIF, &change) < 0)) failure = change.ifr_ifindex ? errno : ENODEV;
        memset(&change, 0, sizeof(change)); strncpy(change.ifr_name, "br0", IFNAMSIZ - 1);
        if (!failure && ioctl(fd, SIOCGIFFLAGS, &change) < 0) failure = errno;
        change.ifr_flags |= IFF_UP;
        if (!failure && ioctl(fd, SIOCSIFFLAGS, &change) < 0) failure = errno;
        if (fd >= 0) close(fd);
        if (failure) {
            char text[96]; int n = snprintf(text, sizeof(text), "bridge change failed: %s", strerror(failure));
            reply(output, 1, text, (size_t)n); return;
        }
        reply(output, 0, "", 0); return;
    }
    /* Connection tracking table, read directly: needs a guest kernel with conntrack procfs. */
    if (!strcmp(request, "NL1 FW_SESSIONS")) {
        int fd = open("/proc/net/nf_conntrack", O_RDONLY | O_CLOEXEC);
        if (fd < 0) { reply(output, 1, "no conntrack listing in this guest kernel", 41); return; }
        char table[LIMIT]; size_t size = 0;
        while (size < sizeof(table)) {
            ssize_t n = read(fd, table + size, sizeof(table) - size);
            if (n < 0 && errno == EINTR) continue;
            if (n <= 0) break;
            size += (size_t)n;
        }
        close(fd);
        reply(output, size == sizeof(table) ? 3 : 0, table, size); return;
    }
    char *const addresses[] = {"busybox", "ip", "address", "show", NULL};
    char *const routes[] = {"busybox", "ip", "route", "show", NULL};
    char *const *args = NULL;
    char *const ping[] = {"busybox", "ping", "-c", "1", "-W", "1", request + 9, NULL};
    struct in_addr destination;
    if (!strncmp(request, "NL1 PING ", 9) && inet_pton(AF_INET, request + 9, &destination) == 1)
        args = ping;
    if (!strcmp(request, "NL1 ADDRESSES")) args = addresses;
    if (!strcmp(request, "NL1 ROUTES")) args = routes;
    char port[5], action[5], cidr[20], extra;
    char *const link_args[] = {"busybox", "ip", "link", "set", "dev", port, action, NULL};
    if (mutations && sscanf(request, "NL1 LINK %4s %4s %c", port, action, &extra) == 2 &&
        valid_port(port) && (!strcmp(action, "up") || !strcmp(action, "down"))) args = link_args;
    char *const address_add[] = {"busybox", "ip", "address", "add", request + 13, "dev", "eth0", NULL};
    char *const address_delete[] = {"busybox", "ip", "address", "del", request + 13, "dev", "eth0", NULL};
    if (mutations && !strncmp(request, "NL1 ADDR_ADD ", 13) && valid_cidr(request + 13)) args = address_add;
    if (mutations && !strncmp(request, "NL1 ADDR_DEL ", 13) && valid_cidr(request + 13)) args = address_delete;
    char *const iface_add[] = {"busybox", "ip", "address", "add", cidr, "dev", port, NULL};
    char *const iface_delete[] = {"busybox", "ip", "address", "del", cidr, "dev", port, NULL};
    if (mutations && sscanf(request, "NL1 IF_ADD %4s %19s %c", port, cidr, &extra) == 2 && valid_port(port) && valid_cidr(cidr)) args = iface_add;
    if (mutations && sscanf(request, "NL1 IF_DEL %4s %19s %c", port, cidr, &extra) == 2 && valid_port(port) && valid_cidr(cidr)) args = iface_delete;
    char via_network[20], via_gateway[16];
    char *const iface_route_add[] = {"busybox", "ip", "route", "add", via_network, "via", via_gateway, "dev", port, NULL};
    char *const iface_route_delete[] = {"busybox", "ip", "route", "del", via_network, "via", via_gateway, "dev", port, NULL};
    if (mutations && sscanf(request, "NL1 IF_ROUTE_ADD %4s %19s %15s %c", port, via_network, via_gateway, &extra) == 3 &&
        valid_port(port) && valid_cidr(via_network) && inet_pton(AF_INET, via_gateway, &destination) == 1) args = iface_route_add;
    if (mutations && sscanf(request, "NL1 IF_ROUTE_DEL %4s %19s %15s %c", port, via_network, via_gateway, &extra) == 3 &&
        valid_port(port) && valid_cidr(via_network) && inet_pton(AF_INET, via_gateway, &destination) == 1) args = iface_route_delete;
    char *route_network = request + 14;
    char *route_gateway = NULL;
    int route_add = !strncmp(request, "NL1 ROUTE_ADD ", 14);
    int route_delete = !strncmp(request, "NL1 ROUTE_DEL ", 14);
    if (mutations && (route_add || route_delete)) {
        route_gateway = strchr(route_network, ' ');
        if (route_gateway) {
            *route_gateway++ = 0;
            if (!valid_cidr(route_network) || inet_pton(AF_INET, route_gateway, &destination) != 1)
                route_gateway = NULL;
        }
    }
    char *const route_insert[] = {"busybox", "ip", "route", "add", route_network, "via", route_gateway, "dev", "eth0", NULL};
    char *const route_remove[] = {"busybox", "ip", "route", "del", route_network, "via", route_gateway, "dev", "eth0", NULL};
    if (route_gateway && route_add) args = route_insert;
    if (route_gateway && route_delete) args = route_remove;
    /* IPv4 forward filtering through the image's iptables; every argument is typed and validated here. */
    const char *program = "/bin/busybox";
    char fw_action[7], fw_in[5], fw_out[5], fw_proto[5], fw_source[20], fw_destination[20], fw_port[6];
    char nat_kind[11], nat_to[16], nat_to_port[6], nat_target[24]; struct in_addr nat_address;
    char *firewall[24]; int count = 0;
    #define FW(word) firewall[count++] = (char *)(word)
    FW("iptables"); FW("-w");
    int fw_ready = 0;
    if (!strcmp(request, "NL1 FW_LIST")) { FW("-S"); FW("FORWARD"); fw_ready = 1; }
    else if (mutations && !strcmp(request, "NL1 FW_FLUSH")) { FW("-F"); FW("FORWARD"); fw_ready = 1; }
    /* Address translation in the nat table: destination NAT before routing, source NAT after it. */
    else if (!strcmp(request, "NL1 FW_NAT_LIST")) { FW("-t"); FW("nat"); FW("-S"); fw_ready = 1; }
    else if (mutations && !strcmp(request, "NL1 FW_NAT_FLUSH")) { FW("-t"); FW("nat"); FW("-F"); fw_ready = 1; }
    else if (mutations && sscanf(request, "NL1 FW_NAT %10s %4s %4s %4s %19s %19s %5s %15s %5s %c", nat_kind, fw_in, fw_out, fw_proto,
                                 fw_source, fw_destination, fw_port, nat_to, nat_to_port, &extra) == 9) {
        int dnat = !strcmp(nat_kind, "dnat"), snat = !strcmp(nat_kind, "snat"), masquerade = !strcmp(nat_kind, "masquerade");
        int tcp = !strcmp(fw_proto, "tcp"), udp = !strcmp(fw_proto, "udp");
        int has_port = strcmp(fw_port, "-") != 0, has_to_port = strcmp(nat_to_port, "-") != 0;
        int has_in = strcmp(fw_in, "-") != 0, has_out = strcmp(fw_out, "-") != 0;
        int to_ok = masquerade ? !strcmp(nat_to, "-") : inet_pton(AF_INET, nat_to, &nat_address) == 1;
        if ((dnat || snat || masquerade) && to_ok &&
            (dnat ? has_in && !has_out : has_out && !has_in) &&
            (!has_in || valid_port(fw_in)) && (!has_out || valid_port(fw_out)) &&
            (tcp || udp || !strcmp(fw_proto, "icmp") || !strcmp(fw_proto, "any")) &&
            (!has_port || ((tcp || udp) && valid_port_number(fw_port))) &&
            (!has_to_port || (dnat && has_port && valid_port_number(nat_to_port))) &&
            (!strcmp(fw_source, "-") || valid_cidr(fw_source)) && (!strcmp(fw_destination, "-") || valid_cidr(fw_destination))) {
            FW("-t"); FW("nat"); FW("-A"); FW(dnat ? "PREROUTING" : "POSTROUTING");
            if (has_in) { FW("-i"); FW(fw_in); }
            if (has_out) { FW("-o"); FW(fw_out); }
            if (strcmp(fw_proto, "any")) { FW("-p"); FW(fw_proto); }
            if (strcmp(fw_source, "-")) { FW("-s"); FW(fw_source); }
            if (strcmp(fw_destination, "-")) { FW("-d"); FW(fw_destination); }
            if (has_port) { FW("--dport"); FW(fw_port); }
            FW("-j"); FW(dnat ? "DNAT" : snat ? "SNAT" : "MASQUERADE");
            if (!masquerade) {
                snprintf(nat_target, sizeof(nat_target), "%s%s%s", nat_to, has_to_port ? ":" : "", has_to_port ? nat_to_port : "");
                FW(dnat ? "--to-destination" : "--to-source"); FW(nat_target);
            }
            fw_ready = 1;
        }
    }
    else if (mutations && (!strcmp(request, "NL1 FW_POLICY accept") || !strcmp(request, "NL1 FW_POLICY drop"))) {
        FW("-P"); FW("FORWARD"); FW(request[14] == 'a' ? "ACCEPT" : "DROP"); fw_ready = 1;
    } else if (mutations && (!strcmp(request, "NL1 FW_STATE invalid") || !strcmp(request, "NL1 FW_STATE established"))) {
        int invalid = request[13] == 'i';
        FW("-A"); FW("FORWARD"); FW("-m"); FW("conntrack"); FW("--ctstate");
        FW(invalid ? "INVALID" : "RELATED,ESTABLISHED"); FW("-j"); FW(invalid ? "DROP" : "ACCEPT"); fw_ready = 1;
    } else if (mutations && sscanf(request, "NL1 FW_RULE %6s %4s %4s %4s %19s %19s %5s %c", fw_action, fw_in, fw_out,
                                   fw_proto, fw_source, fw_destination, fw_port, &extra) == 7) {
        int accept = !strcmp(fw_action, "accept"), tcp = !strcmp(fw_proto, "tcp"), udp = !strcmp(fw_proto, "udp");
        int has_port = strcmp(fw_port, "-") != 0, port_ok = !has_port;
        if (has_port && (tcp || udp) && fw_port[0] != '0' && strspn(fw_port, "0123456789") == strlen(fw_port)) {
            long value = atol(fw_port); port_ok = value >= 1 && value <= 65535;
        }
        if ((accept || !strcmp(fw_action, "drop")) && port_ok &&
            (!strcmp(fw_in, "-") || valid_port(fw_in)) && (!strcmp(fw_out, "-") || valid_port(fw_out)) &&
            (tcp || udp || !strcmp(fw_proto, "icmp") || !strcmp(fw_proto, "any")) &&
            (!strcmp(fw_source, "-") || valid_cidr(fw_source)) && (!strcmp(fw_destination, "-") || valid_cidr(fw_destination))) {
            FW("-A"); FW("FORWARD");
            if (strcmp(fw_in, "-")) { FW("-i"); FW(fw_in); }
            if (strcmp(fw_out, "-")) { FW("-o"); FW(fw_out); }
            if (strcmp(fw_proto, "any")) { FW("-p"); FW(fw_proto); }
            if (strcmp(fw_source, "-")) { FW("-s"); FW(fw_source); }
            if (strcmp(fw_destination, "-")) { FW("-d"); FW(fw_destination); }
            if (has_port) { FW("--dport"); FW(fw_port); }
            FW("-j"); FW(accept ? "ACCEPT" : "DROP"); fw_ready = 1;
        }
    }
    #undef FW
    if (fw_ready) { firewall[count] = NULL; args = firewall; program = "/sbin/xtables-legacy-multi"; }
    if (!args) { reply(output, 2, "unsupported operation", 21); return; }
    int pipes[2];
    if (pipe(pipes)) { reply(output, 3, "pipe failed", 11); return; }
    pid_t child = fork();
    if (child == 0) {
        alarm(3);
        close(pipes[0]);
        if (dup2(pipes[1], 1) < 0 || dup2(pipes[1], 2) < 0) _exit(126);
        close(pipes[1]);
        char *const env[] = {"PATH=/bin", "LC_ALL=C", NULL};
        execve(program, args, env); _exit(127);
    }
    close(pipes[1]);
    if (child < 0) { close(pipes[0]); reply(output, 3, "fork failed", 11); return; }
    char buffer[LIMIT]; size_t length = 0; int overflow = 0;
    while (length < sizeof(buffer)) {
        ssize_t n = read(pipes[0], buffer + length, sizeof(buffer) - length);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        length += (size_t)n;
    }
    if (length == sizeof(buffer)) { overflow = 1; kill(child, SIGKILL); }
    close(pipes[0]);
    int status;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) return;
    int code = overflow ? 3 : (WIFEXITED(status) ? WEXITSTATUS(status) : 3);
    reply(output, code, buffer, length);
}
int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);
    if (argc == 2 && !strcmp(argv[1], "--stdio")) { serve(0, 1, 0); return 0; }
    if (argc != 1) return 2;
    int server = socket(AF_VSOCK, SOCK_STREAM | SOCK_CLOEXEC, 0);
    struct sockaddr_vm address = {.svm_family=AF_VSOCK, .svm_cid=VMADDR_CID_ANY, .svm_port=19001};
    if (server < 0 || bind(server, (struct sockaddr *)&address, sizeof(address)) || listen(server, 4)) {
        perror("guest vsock"); return 1;
    }
    for (;;) {
        struct sockaddr_vm peer; socklen_t size = sizeof(peer);
        int client = accept4(server, (struct sockaddr *)&peer, &size, SOCK_CLOEXEC);
        if (client < 0) { if (errno == EINTR) continue; return 1; }
        if (peer.svm_cid != VMADDR_CID_HOST) { close(client); continue; }
        pid_t worker = fork();
        if (worker == 0) { close(server); serve(client, client, 1); close(client); _exit(0); }
        close(client);
        if (worker > 0) while (waitpid(worker, NULL, 0) < 0 && errno == EINTR) {}
    }
}
