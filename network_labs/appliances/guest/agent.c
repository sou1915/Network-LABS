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
#include <linux/rtnetlink.h>
#include <linux/if_vlan.h>
#include <linux/netfilter/nf_tables.h>
#include <sys/time.h>
#include <net/if.h>
#include <dirent.h>
#include <sys/stat.h>
#include <time.h>
#include <signal.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LIMIT 32768
static int valid_port(const char *value) {
    return strlen(value) == 4 && !strncmp(value, "eth", 3) && value[3] >= '0' && value[3] <= '3';
}
/* A guest port eth0..eth3, or one of its 802.1Q subinterfaces eth0.1 .. eth3.4094. */
static int valid_interface(const char *value) {
    if (strlen(value) == 4) return valid_port(value);
    if (strlen(value) < 6 || strlen(value) > 9 || value[4] != '.') return 0;
    char base[5]; memcpy(base, value, 4); base[4] = 0;
    const char *vid = value + 5;
    if (!valid_port(base) || vid[0] == '0' || strspn(vid, "0123456789") != strlen(vid)) return 0;
    long number = atol(vid); return number >= 1 && number <= 4094;
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
/* A running daemon is identified by its pid file and a live process. */
static pid_t pidfile_alive(const char *path) {
    char text[16] = {0}; int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 0;
    ssize_t n = read(fd, text, sizeof(text) - 1); close(fd);
    long pid = n > 0 ? atol(text) : 0;
    return pid > 1 && kill((pid_t)pid, 0) == 0 ? (pid_t)pid : 0;
}
/* Start a long-lived service outside this request: own session, no inherited output, reparented to init. */
static int spawn_detached(const char *program, char *const argv[]) {
    pid_t first = fork();
    if (first < 0) return -1;
    if (first == 0) {
        setsid();
        pid_t second = fork();
        if (second == 0) {
            int null = open("/dev/null", O_RDWR);
            if (null < 0 || dup2(null, 0) < 0 || dup2(null, 1) < 0 || dup2(null, 2) < 0) _exit(126);
            char *const env[] = {"PATH=/bin", "LC_ALL=C", NULL};
            execve(program, argv, env); _exit(127);
        }
        _exit(second < 0 ? 1 : 0);
    }
    int status;
    while (waitpid(first, &status, 0) < 0) if (errno != EINTR) return -1;
    return WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : -1;
}
/* One VLAN on one bridge port, through rtnetlink as `bridge vlan add|del` does (BusyBox has no bridge tool). */
static int bridge_vlan(int command, const char *port, unsigned vid, unsigned short flags) {
    struct { struct nlmsghdr header; struct ifinfomsg link; char attributes[64]; } message;
    memset(&message, 0, sizeof(message));
    message.header.nlmsg_len = NLMSG_LENGTH(sizeof(struct ifinfomsg));
    message.header.nlmsg_type = (unsigned short)command;
    message.header.nlmsg_flags = NLM_F_REQUEST | NLM_F_ACK;
    message.link.ifi_family = AF_BRIDGE;
    message.link.ifi_index = (int)if_nametoindex(port);
    if (!message.link.ifi_index) return ENODEV;
    struct rtattr *spec = (struct rtattr *)((char *)&message + NLMSG_ALIGN(message.header.nlmsg_len));
    spec->rta_type = IFLA_AF_SPEC;
    struct rtattr *entry = (struct rtattr *)RTA_DATA(spec);
    entry->rta_type = IFLA_BRIDGE_VLAN_INFO;
    entry->rta_len = RTA_LENGTH(sizeof(struct bridge_vlan_info));
    struct bridge_vlan_info info = {.flags = flags, .vid = (unsigned short)vid};
    memcpy(RTA_DATA(entry), &info, sizeof(info));
    spec->rta_len = RTA_LENGTH(RTA_ALIGN(entry->rta_len));
    message.header.nlmsg_len = NLMSG_ALIGN(message.header.nlmsg_len) + RTA_ALIGN(spec->rta_len);
    int fd = socket(AF_NETLINK, SOCK_RAW | SOCK_CLOEXEC, NETLINK_ROUTE);
    if (fd < 0) return errno;
    int result = EIO; char answer[512];
    if (send(fd, &message, message.header.nlmsg_len, 0) == (ssize_t)message.header.nlmsg_len) {
        ssize_t n = recv(fd, answer, sizeof(answer), 0);
        struct nlmsghdr *reply_header = (struct nlmsghdr *)answer;
        if (n >= (ssize_t)NLMSG_LENGTH(sizeof(struct nlmsgerr)) && reply_header->nlmsg_type == NLMSG_ERROR)
            result = -((struct nlmsgerr *)NLMSG_DATA(reply_header))->error;
    }
    close(fd);
    return result;
}
/* Every bridge VLAN entry as "port vid [pvid] [untagged]" lines, from an AF_BRIDGE link dump. */
static size_t bridge_vlans(char *out, size_t room, int *failure) {
    struct { struct nlmsghdr header; struct ifinfomsg link; struct rtattr mask_header; __u32 mask; } query;
    memset(&query, 0, sizeof(query));
    query.header.nlmsg_len = sizeof(query);
    query.header.nlmsg_type = RTM_GETLINK;
    query.header.nlmsg_flags = NLM_F_REQUEST | NLM_F_DUMP;
    query.link.ifi_family = AF_BRIDGE;
    query.mask_header.rta_type = IFLA_EXT_MASK;
    query.mask_header.rta_len = RTA_LENGTH(sizeof(__u32));
    query.mask = RTEXT_FILTER_BRVLAN;
    size_t used = 0; *failure = 0;
    int fd = socket(AF_NETLINK, SOCK_RAW | SOCK_CLOEXEC, NETLINK_ROUTE);
    if (fd < 0 || send(fd, &query, sizeof(query), 0) != (ssize_t)sizeof(query)) { *failure = errno ? errno : EIO; if (fd >= 0) close(fd); return 0; }
    static char buffer[16384];
    for (int done = 0; !done;) {
        ssize_t n = recv(fd, buffer, sizeof(buffer), 0);
        if (n <= 0) { *failure = EIO; break; }
        for (struct nlmsghdr *header = (struct nlmsghdr *)buffer; NLMSG_OK(header, (unsigned)n); header = NLMSG_NEXT(header, n)) {
            if (header->nlmsg_type == NLMSG_DONE) { done = 1; break; }
            if (header->nlmsg_type == NLMSG_ERROR) { *failure = -((struct nlmsgerr *)NLMSG_DATA(header))->error; done = 1; break; }
            if (header->nlmsg_type != RTM_NEWLINK) continue;
            struct ifinfomsg *link = NLMSG_DATA(header);
            char name[IF_NAMESIZE] = "";
            if (!if_indextoname((unsigned)link->ifi_index, name)) continue;
            int length = (int)IFLA_PAYLOAD(header);
            for (struct rtattr *attribute = IFLA_RTA(link); RTA_OK(attribute, length); attribute = RTA_NEXT(attribute, length)) {
                if ((attribute->rta_type & NLA_TYPE_MASK) != IFLA_AF_SPEC) continue;
                int inner = (int)RTA_PAYLOAD(attribute);
                for (struct rtattr *entry = RTA_DATA(attribute); RTA_OK(entry, inner); entry = RTA_NEXT(entry, inner)) {
                    if (entry->rta_type != IFLA_BRIDGE_VLAN_INFO || RTA_PAYLOAD(entry) < sizeof(struct bridge_vlan_info)) continue;
                    struct bridge_vlan_info *info = RTA_DATA(entry);
                    int written = snprintf(out + used, room - used, "%s %u%s%s\n", name, info->vid,
                                           info->flags & BRIDGE_VLAN_INFO_PVID ? " pvid" : "",
                                           info->flags & BRIDGE_VLAN_INFO_UNTAGGED ? " untagged" : "");
                    if (written < 0 || (size_t)written >= room - used) { *failure = ENOSPC; close(fd); return used; }
                    used += (size_t)written;
                }
            }
        }
    }
    close(fd);
    return used;
}
static int valid_ipv4(const char *value) { struct in_addr address; return inet_pton(AF_INET, value, &address) == 1; }
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
/* OSPFv2 area 0 with BIRD 2. The daemon configuration is written here, from typed fields only:
   "ROUTER_ID HELLO DEAD PORT:COST:STUB:TYPE:PRIORITY[,...]" with STUB y|n and TYPE p (point-to-point) or b (broadcast). */
/* eBGP with FRR (zebra and bgpd). The configuration is written here from typed fields only:
   "ASN ROUTER_ID ADDRESS:REMOTE_AS[,...] PREFIX[,...]|-". The networks are announced only if they are in the
   routing table (FRR's import check), as on a real router. */
static int valid_asn(const char *value) {
    if (!value[0] || value[0] == '0' || strspn(value, "0123456789") != strlen(value) || strlen(value) > 10) return 0;
    unsigned long long number = strtoull(value, NULL, 10); return number >= 1 && number <= 4294967295ULL;
}
static int bgp_render(const char *fields, char *out, size_t size) {
    char asn[11], rid[16], peers[120], networks[160], extra;
    if (sscanf(fields, "%10s %15s %119s %159s %c", asn, rid, peers, networks, &extra) != 4) return -1;
    if (!valid_asn(asn) || !valid_ipv4(rid)) return -1;
    int n = snprintf(out, size, "frr defaults traditional\nrouter bgp %s\n bgp router-id %s\n no bgp ebgp-requires-policy\n", asn, rid);
    int count = 0;
    for (char *item = strtok(peers, ","); item; item = strtok(NULL, ",")) {
        char address[16], remote[11], tail;
        if (++count > 4 || sscanf(item, "%15[^:]:%10[0-9]%c", address, remote, &tail) != 2) return -1;
        if (!valid_ipv4(address) || !valid_asn(remote) || !strcmp(remote, asn)) return -1;
        n += snprintf(out + n, size - (size_t)n, " neighbor %s remote-as %s\n neighbor %s timers 3 9\n neighbor %s timers connect 5\n",
                      address, remote, address, address);
        if (n >= (int)size - 64) return -1;
    }
    if (!count) return -1;
    n += snprintf(out + n, size - (size_t)n, " address-family ipv4 unicast\n");
    if (strcmp(networks, "-")) {
        int announced = 0;
        for (char *item = strtok(networks, ","); item; item = strtok(NULL, ",")) {
            if (++announced > 8 || !valid_cidr(item)) return -1;
            n += snprintf(out + n, size - (size_t)n, "  network %s\n", item);
            if (n >= (int)size - 64) return -1;
        }
    }
    n += snprintf(out + n, size - (size_t)n, " exit-address-family\n");
    return n;
}
static int ospf_render(const char *fields, char *out, size_t size) {
    char rid[16], list[100], extra; unsigned hello, dead;
    if (sscanf(fields, "%15s %u %u %99s %c", rid, &hello, &dead, list, &extra) != 4) return -1;
    if (!valid_ipv4(rid) || hello < 1 || hello > 60 || dead < 2 || dead > 240 || dead <= hello) return -1;
    int n = snprintf(out, size, "router id %s;\nlog stderr all;\nprotocol device { scan time 1; }\n"
                     "protocol kernel kernel4 { scan time 1; ipv4 { import none; export where source = RTS_OSPF; }; }\n"
                     "protocol ospf v2 ospf4 {\n  ipv4 { import where source = RTS_OSPF; export none; };\n"
                     "  ecmp no;\n  area 0.0.0.0 {\n", rid);
    int count = 0, active = 0; char seen[4] = {0};
    for (char *item = strtok(list, ","); item; item = strtok(NULL, ",")) {
        char port[5], stub, type, tail; unsigned cost, priority;
        if (++count > 4 || sscanf(item, "%4[^:]:%u:%c:%c:%u%c", port, &cost, &stub, &type, &priority, &tail) != 5) return -1;
        if (!valid_port(port) || seen[port[3] - '0']++ || cost < 1 || cost > 65535 || (stub != 'y' && stub != 'n')) return -1;
        if ((type != 'p' && type != 'b') || priority > 255 || (type == 'p' && priority != 1)) return -1;
        active += stub == 'n';
        n += snprintf(out + n, size - (size_t)n, "    interface \"%s\" { type %s; cost %u; stub %s; hello %u; dead %u;",
                      port, type == 'b' ? "broadcast" : "ptp", cost, stub == 'y' ? "yes" : "no", hello, dead);
        if (type == 'b') n += snprintf(out + n, size - (size_t)n, " priority %u; wait %u;", priority, dead);
        n += snprintf(out + n, size - (size_t)n, " };\n");
        if (n >= (int)size - 16) return -1;
    }
    if (!count || !active) return -1;
    n += snprintf(out + n, size - (size_t)n, "  };\n}\n");
    return n;
}
/* RIP with BIRD 2 (shares BIRD's files with OSPF; a router runs one or the other). From typed fields only:
   "ROUTER_ID VERSION PORT:a|p[,...]": the ports RIP runs on, a(ctive) or p(assive: announced, no updates sent). */
static int rip_render(const char *fields, char *out, size_t size) {
    char rid[16], list[64], copy[64], extra; unsigned version;
    if (sscanf(fields, "%15s %u %63s %c", rid, &version, list, &extra) != 3) return -1;
    if (!valid_ipv4(rid) || (version != 1 && version != 2)) return -1;
    memcpy(copy, list, sizeof(copy));
    char names[4][5]; char modes[4]; int count = 0;
    for (char *item = strtok(copy, ","); item; item = strtok(NULL, ",")) {
        char port[5], mode, tail;
        if (count >= 4 || sscanf(item, "%4[^:]:%c%c", port, &mode, &tail) != 2) return -1;
        if (!valid_port(port) || (mode != 'a' && mode != 'p')) return -1;
        for (int i = 0; i < count; i++) if (!strcmp(names[i], port)) return -1;
        memcpy(names[count], port, 5); modes[count++] = mode;
    }
    if (!count) return -1;
    int n = snprintf(out, size, "router id %s;\nlog stderr all;\nprotocol device { scan time 1; }\n"
                     "protocol direct direct4 { ipv4; interface ", rid);
    for (int i = 0; i < count; i++) n += snprintf(out + n, size - (size_t)n, "%s\"%s\"", i ? ", " : "", names[i]);
    n += snprintf(out + n, size - (size_t)n, "; }\n"
                  "protocol kernel kernel4 { scan time 1; ipv4 { import none; export where source = RTS_RIP; }; }\n"
                  "protocol rip rip4 {\n  ipv4 { import all; export where source = RTS_DEVICE || source = RTS_RIP; };\n");
    for (int i = 0; i < count; i++) {
        n += snprintf(out + n, size - (size_t)n, "  interface \"%s\" { version %u; mode %s; update time 5; timeout time 30; "
                      "garbage time 20; passive %s; };\n", names[i], version, version == 1 ? "broadcast" : "multicast",
                      modes[i] == 'p' ? "yes" : "no");
        if (n >= (int)size - 16) return -1;
    }
    n += snprintf(out + n, size - (size_t)n, "}\n");
    return n;
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
    char request[320]; size_t used = 0;
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
    /* VLANs on the switch bridge: filtering on, per-port membership, and a read-only listing. */
    if (!strcmp(request, "NL1 BRIDGE_VLANS")) {
        static char listing[LIMIT]; int failure;
        size_t size = bridge_vlans(listing, sizeof(listing), &failure);
        if (failure) {
            char text[96]; int n = snprintf(text, sizeof(text), "bridge vlan listing failed: %s", strerror(failure));
            reply(output, 1, text, (size_t)n); return;
        }
        reply(output, 0, listing, size); return;
    }
    if (mutations && !strcmp(request, "NL1 BRIDGE_VLAN_FILTERING")) {
        int fd = open("/sys/class/net/br0/bridge/vlan_filtering", O_WRONLY | O_CLOEXEC);
        if (fd < 0) { reply(output, 1, "no bridge vlan filtering in this guest kernel", 45); return; }
        ssize_t n = write(fd, "1\n", 2); close(fd);
        if (n != 2) { reply(output, 1, "bridge vlan filtering change failed", 35); return; }
        reply(output, 0, "", 0); return;
    }
    char vlan_port[5], vlan_mode[8], vlan_extra; unsigned vlan_id;
    int vlan_fields = sscanf(request, "NL1 BRIDGE_VLAN_ADD %4s %u %7s %c", vlan_port, &vlan_id, vlan_mode, &vlan_extra);
    int vlan_add = vlan_fields == 3 && (!strcmp(vlan_mode, "pvid") || !strcmp(vlan_mode, "tagged"));
    int vlan_delete = !vlan_add && sscanf(request, "NL1 BRIDGE_VLAN_DEL %4s %u %c", vlan_port, &vlan_id, &vlan_extra) == 2;
    if (mutations && (vlan_add || vlan_delete) && valid_port(vlan_port) && vlan_id >= 1 && vlan_id <= 4094) {
        unsigned short flags = vlan_add && !strcmp(vlan_mode, "pvid") ? BRIDGE_VLAN_INFO_PVID | BRIDGE_VLAN_INFO_UNTAGGED : 0;
        int failure = bridge_vlan(vlan_add ? RTM_SETLINK : RTM_DELLINK, vlan_port, vlan_id, flags);
        if (failure) {
            char text[96]; int n = snprintf(text, sizeof(text), "bridge vlan change failed: %s", strerror(failure));
            reply(output, 1, text, (size_t)n); return;
        }
        reply(output, 0, "", 0); return;
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
    /* OSPF: render (read-only, for conformity checks), start, stop, and fixed BIRD show commands. */
    char ospf_config[1024];
    if (!strncmp(request, "NL1 OSPF_RENDER ", 16)) {
        int n = ospf_render(request + 16, ospf_config, sizeof(ospf_config));
        if (n < 0) { reply(output, 2, "unsupported operation", 21); return; }
        reply(output, 0, ospf_config, (size_t)n); return;
    }
    if (mutations && !strncmp(request, "NL1 OSPF_START ", 15)) {
        int n = ospf_render(request + 15, ospf_config, sizeof(ospf_config));
        if (n < 0) { reply(output, 2, "unsupported operation", 21); return; }
        const char *missing = "the guest image has no BIRD; rebuild it with --with-routing";
        if (access("/usr/sbin/bird", X_OK)) { reply(output, 1, missing, strlen(missing)); return; }
        if (pidfile_alive("/run/bird.pid")) { reply(output, 1, "ospf already running", 20); return; }
        int fd = open("/run/bird.conf", O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
        int written = fd >= 0 && write(fd, ospf_config, (size_t)n) == n;
        if (fd >= 0) close(fd);
        char *const bird[] = {"bird", "-f", "-c", "/run/bird.conf", "-s", "/run/bird.ctl", "-P", "/run/bird.pid", NULL};
        if (!written || spawn_detached("/usr/sbin/bird", bird)) { reply(output, 3, "ospf start failed", 17); return; }
        reply(output, 0, "", 0); return;
    }
    if (mutations && !strcmp(request, "NL1 OSPF_STOP")) {
        pid_t bird = pidfile_alive("/run/bird.pid");
        if (bird) {
            kill(bird, SIGTERM);
            for (int tries = 0; tries < 40 && kill(bird, 0) == 0; tries++) {
                struct timespec pause = {0, 50 * 1000 * 1000}; nanosleep(&pause, NULL);
            }
            if (kill(bird, 0) == 0) { reply(output, 3, "ospf stop failed", 16); return; }
        }
        unlink("/run/bird.pid"); unlink("/run/bird.conf");
        reply(output, 0, "", 0); return;
    }
    if (!strcmp(request, "NL1 OSPF_SHOW config")) {
        int fd = open("/run/bird.conf", O_RDONLY | O_CLOEXEC);
        if (fd < 0 || !pidfile_alive("/run/bird.pid")) {
            if (fd >= 0) close(fd);
            reply(output, 1, "ospf not running", 16); return;
        }
        ssize_t n = read(fd, ospf_config, sizeof(ospf_config)); close(fd);
        reply(output, n < 0 ? 3 : 0, ospf_config, n < 0 ? 0 : (size_t)n); return;
    }
    /* RIP: the same BIRD daemon and files as OSPF (never both): render, start, stop, configuration and routes. */
    if (!strncmp(request, "NL1 RIP_RENDER ", 15)) {
        int n = rip_render(request + 15, ospf_config, sizeof(ospf_config));
        if (n < 0) { reply(output, 2, "unsupported operation", 21); return; }
        reply(output, 0, ospf_config, (size_t)n); return;
    }
    if (mutations && !strncmp(request, "NL1 RIP_START ", 14)) {
        int n = rip_render(request + 14, ospf_config, sizeof(ospf_config));
        if (n < 0) { reply(output, 2, "unsupported operation", 21); return; }
        const char *missing = "the guest image has no BIRD; rebuild it with --with-routing";
        if (access("/usr/sbin/bird", X_OK)) { reply(output, 1, missing, strlen(missing)); return; }
        if (pidfile_alive("/run/bird.pid")) { reply(output, 1, "rip already running", 19); return; }
        int fd = open("/run/bird.conf", O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
        int written = fd >= 0 && write(fd, ospf_config, (size_t)n) == n;
        if (fd >= 0) close(fd);
        char *const bird[] = {"bird", "-f", "-c", "/run/bird.conf", "-s", "/run/bird.ctl", "-P", "/run/bird.pid", NULL};
        if (!written || spawn_detached("/usr/sbin/bird", bird)) { reply(output, 3, "rip start failed", 16); return; }
        reply(output, 0, "", 0); return;
    }
    if (mutations && !strcmp(request, "NL1 RIP_STOP")) {
        pid_t bird = pidfile_alive("/run/bird.pid");
        if (bird) {
            kill(bird, SIGTERM);
            for (int tries = 0; tries < 40 && kill(bird, 0) == 0; tries++) {
                struct timespec pause = {0, 50 * 1000 * 1000}; nanosleep(&pause, NULL);
            }
            if (kill(bird, 0) == 0) { reply(output, 3, "rip stop failed", 15); return; }
        }
        unlink("/run/bird.pid"); unlink("/run/bird.conf");
        reply(output, 0, "", 0); return;
    }
    if (!strcmp(request, "NL1 RIP_SHOW config")) {
        int fd = open("/run/bird.conf", O_RDONLY | O_CLOEXEC);
        if (fd < 0 || !pidfile_alive("/run/bird.pid")) {
            if (fd >= 0) close(fd);
            reply(output, 1, "rip not running", 15); return;
        }
        ssize_t n = read(fd, ospf_config, sizeof(ospf_config)); close(fd);
        reply(output, n < 0 ? 3 : 0, ospf_config, n < 0 ? 0 : (size_t)n); return;
    }
    char *const rip_routes[] = {"birdc", "-r", "-s", "/run/bird.ctl", "show", "route", "protocol", "rip4", NULL};
    char *const ospf_neighbors[] = {"birdc", "-r", "-s", "/run/bird.ctl", "show", "ospf", "neighbors", "ospf4", NULL};
    char *const ospf_interfaces[] = {"birdc", "-r", "-s", "/run/bird.ctl", "show", "ospf", "interface", "ospf4", NULL};
    char *const ospf_routes[] = {"birdc", "-r", "-s", "/run/bird.ctl", "show", "route", "protocol", "ospf4", NULL};
    char *const *ospf_show = !strcmp(request, "NL1 OSPF_SHOW neighbors") ? ospf_neighbors
                           : !strcmp(request, "NL1 OSPF_SHOW interfaces") ? ospf_interfaces
                           : !strcmp(request, "NL1 OSPF_SHOW routes") ? ospf_routes
                           : !strcmp(request, "NL1 RIP_SHOW routes") ? rip_routes : NULL;
    /* BGP: render (read-only), start zebra then bgpd as root under /run/frr, stop, and fixed vtysh JSON views. */
    char bgp_config[2048];
    if (!strncmp(request, "NL1 BGP_RENDER ", 15)) {
        int n = bgp_render(request + 15, bgp_config, sizeof(bgp_config));
        if (n < 0) { reply(output, 2, "unsupported operation", 21); return; }
        reply(output, 0, bgp_config, (size_t)n); return;
    }
    if (mutations && !strncmp(request, "NL1 BGP_START ", 14)) {
        int n = bgp_render(request + 14, bgp_config, sizeof(bgp_config));
        if (n < 0) { reply(output, 2, "unsupported operation", 21); return; }
        const char *missing = "the guest image has no FRR; rebuild it with --with-routing";
        if (access("/usr/lib/frr/bgpd", X_OK) || access("/usr/lib/frr/zebra", X_OK)) { reply(output, 1, missing, strlen(missing)); return; }
        if (pidfile_alive("/run/frr/bgpd.pid")) { reply(output, 1, "bgp already running", 19); return; }
        mkdir("/run/frr", 0755);
        int fd = open("/run/frr/bgpd.conf", O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
        int written = fd >= 0 && write(fd, bgp_config, (size_t)n) == n;
        if (fd >= 0) close(fd);
        fd = open("/run/frr/zebra.conf", O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
        if (fd >= 0) close(fd);
        char *const zebra[] = {"zebra", "-u", "root", "-g", "root", "-i", "/run/frr/zebra.pid", "-z", "/run/frr/zserv.api",
                               "--vty_socket", "/run/frr", "-f", "/run/frr/zebra.conf", NULL};
        char *const bgpd[] = {"bgpd", "-u", "root", "-g", "root", "-i", "/run/frr/bgpd.pid", "-z", "/run/frr/zserv.api",
                              "--vty_socket", "/run/frr", "-f", "/run/frr/bgpd.conf", NULL};
        if (!written || fd < 0 || (!pidfile_alive("/run/frr/zebra.pid") && spawn_detached("/usr/lib/frr/zebra", zebra))) {
            reply(output, 3, "bgp start failed", 16); return;
        }
        /* bgpd connects to zebra's socket as soon as it exists (it also retries on its own). */
        for (int tries = 0; tries < 40 && access("/run/frr/zserv.api", F_OK); tries++) {
            struct timespec pause = {0, 50 * 1000 * 1000}; nanosleep(&pause, NULL);
        }
        if (spawn_detached("/usr/lib/frr/bgpd", bgpd)) { reply(output, 3, "bgp start failed", 16); return; }
        reply(output, 0, "", 0); return;
    }
    if (mutations && !strcmp(request, "NL1 BGP_STOP")) {
        /* bgpd first: zebra withdraws the routes BGP installed when bgpd goes away. */
        const char *pids[] = {"/run/frr/bgpd.pid", "/run/frr/zebra.pid"};
        for (int i = 0; i < 2; i++) {
            pid_t daemon = pidfile_alive(pids[i]);
            if (!daemon) continue;
            kill(daemon, SIGTERM);
            for (int tries = 0; tries < 60 && kill(daemon, 0) == 0; tries++) {
                struct timespec pause = {0, 50 * 1000 * 1000}; nanosleep(&pause, NULL);
            }
            if (kill(daemon, 0) == 0) { reply(output, 3, "bgp stop failed", 15); return; }
            unlink(pids[i]);
        }
        unlink("/run/frr/bgpd.conf");
        reply(output, 0, "", 0); return;
    }
    if (!strcmp(request, "NL1 BGP_SHOW config")) {
        int fd = open("/run/frr/bgpd.conf", O_RDONLY | O_CLOEXEC);
        if (fd < 0 || !pidfile_alive("/run/frr/bgpd.pid")) {
            if (fd >= 0) close(fd);
            reply(output, 1, "bgp not running", 15); return;
        }
        ssize_t n = read(fd, bgp_config, sizeof(bgp_config)); close(fd);
        reply(output, n < 0 ? 3 : 0, bgp_config, n < 0 ? 0 : (size_t)n); return;
    }
    char *const bgp_summary[] = {"vtysh", "--vty_socket", "/run/frr", "-c", "show ip bgp summary json", NULL};
    char *const bgp_routes[] = {"vtysh", "--vty_socket", "/run/frr", "-c", "show ip bgp json", NULL};
    char *const *bgp_show = !strcmp(request, "NL1 BGP_SHOW summary") ? bgp_summary
                          : !strcmp(request, "NL1 BGP_SHOW routes") ? bgp_routes : NULL;
    /* DHCP with BusyBox: one server or client per port, configured only from typed fields. */
    char dhcp_port[5], dhcp_start[16], dhcp_end[16], dhcp_mask[16], dhcp_router[16], dhcp_lease[7], dhcp_dns[48], dhcp_extra;
    char dhcp_conf[40], dhcp_pid[40], dhcp_leases[40];
    if (mutations && sscanf(request, "NL1 DHCP_SERVE %4s %15s %15s %15s %15s %6s %47s %c", dhcp_port, dhcp_start, dhcp_end, dhcp_mask,
                            dhcp_router, dhcp_lease, dhcp_dns, &dhcp_extra) == 7) {
        struct in_addr first, last;
        int ok = valid_port(dhcp_port) && inet_pton(AF_INET, dhcp_start, &first) == 1 && inet_pton(AF_INET, dhcp_end, &last) == 1 &&
                 ntohl(first.s_addr) <= ntohl(last.s_addr) && ntohl(last.s_addr) - ntohl(first.s_addr) < 256 &&
                 valid_ipv4(dhcp_mask) && (!strcmp(dhcp_router, "-") || valid_ipv4(dhcp_router)) &&
                 strspn(dhcp_lease, "0123456789") == strlen(dhcp_lease) && atol(dhcp_lease) >= 60 && atol(dhcp_lease) <= 604800;
        char dns_words[48] = ""; int servers = 0;
        if (ok && strcmp(dhcp_dns, "-")) {
            char copy[48]; strcpy(copy, dhcp_dns);
            for (char *item = strtok(copy, ","); item && ok; item = strtok(NULL, ",")) {
                ok = valid_ipv4(item) && ++servers <= 3;
                if (ok) { strcat(dns_words, servers > 1 ? " " : ""); strcat(dns_words, item); }
            }
        }
        if (!ok) { reply(output, 2, "unsupported operation", 21); return; }
        snprintf(dhcp_conf, sizeof(dhcp_conf), "/run/udhcpd.%s.conf", dhcp_port);
        snprintf(dhcp_pid, sizeof(dhcp_pid), "/run/udhcpd.%s.pid", dhcp_port);
        snprintf(dhcp_leases, sizeof(dhcp_leases), "/run/udhcpd.%s.leases", dhcp_port);
        if (pidfile_alive(dhcp_pid)) { reply(output, 1, "dhcp server already running", 27); return; }
        char config[768];
        int n = snprintf(config, sizeof(config),
            "interface %s\nstart %s\nend %s\nmax_leases %lu\nremaining yes\nauto_time 10\nlease_file %s\npidfile %s\n"
            "option subnet %s\noption lease %s\n%s%s%s%s%s%s",
            dhcp_port, dhcp_start, dhcp_end, (unsigned long)(ntohl(last.s_addr) - ntohl(first.s_addr) + 1), dhcp_leases, dhcp_pid,
            dhcp_mask, dhcp_lease, strcmp(dhcp_router, "-") ? "option router " : "", strcmp(dhcp_router, "-") ? dhcp_router : "",
            strcmp(dhcp_router, "-") ? "\n" : "", servers ? "option dns " : "", dns_words, servers ? "\n" : "");
        int fd = open(dhcp_conf, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
        int written = fd >= 0 && n > 0 && write(fd, config, (size_t)n) == n;
        if (fd >= 0) close(fd);
        char *const serve[] = {"busybox", "udhcpd", "-f", dhcp_conf, NULL};
        if (!written || spawn_detached("/bin/busybox", serve)) { reply(output, 3, "dhcp server start failed", 24); return; }
        reply(output, 0, "", 0); return;
    }
    if (mutations && sscanf(request, "NL1 DHCP_CLIENT %4s %c", dhcp_port, &dhcp_extra) == 1 && valid_port(dhcp_port)) {
        snprintf(dhcp_pid, sizeof(dhcp_pid), "/run/udhcpc.%s.pid", dhcp_port);
        if (pidfile_alive(dhcp_pid)) { reply(output, 1, "dhcp client already running", 27); return; }
        char *const client[] = {"busybox", "udhcpc", "-f", "-i", dhcp_port, "-s", "/etc/network-labs/dhcp-client.sh", "-p", dhcp_pid,
                                "-T", "1", "-A", "2", NULL};
        if (spawn_detached("/bin/busybox", client)) { reply(output, 3, "dhcp client start failed", 24); return; }
        reply(output, 0, "", 0); return;
    }
    char *const lease_list[] = {"busybox", "dumpleases", "-f", dhcp_leases, NULL};
    char *const *lease_args = NULL;
    if (sscanf(request, "NL1 DHCP_LEASES %4s %c", dhcp_port, &dhcp_extra) == 1 && valid_port(dhcp_port)) {
        snprintf(dhcp_pid, sizeof(dhcp_pid), "/run/udhcpd.%s.pid", dhcp_port);
        snprintf(dhcp_leases, sizeof(dhcp_leases), "/run/udhcpd.%s.leases", dhcp_port);
        pid_t server = pidfile_alive(dhcp_pid);
        if (!server) { reply(output, 1, "dhcp server not running", 23); return; }
        /* udhcpd writes its lease file only every auto_time seconds or on SIGUSR1: ask for a fresh one. */
        struct stat before; long long previous = stat(dhcp_leases, &before) ? -1 : (long long)before.st_mtim.tv_sec * 1000000000LL + before.st_mtim.tv_nsec;
        kill(server, SIGUSR1);
        for (int tries = 0; tries < 20; tries++) {
            struct stat now;
            if (!stat(dhcp_leases, &now) && (long long)now.st_mtim.tv_sec * 1000000000LL + now.st_mtim.tv_nsec != previous) break;
            struct timespec pause = {0, 50 * 1000 * 1000}; nanosleep(&pause, NULL);
        }
        if (access(dhcp_leases, F_OK)) { reply(output, 0, "", 0); return; }
        lease_args = lease_list;
    }
    char *const addresses[] = {"busybox", "ip", "address", "show", NULL};
    char *const routes[] = {"busybox", "ip", "route", "show", NULL};
    char *const *args = lease_args;
    char *const ping[] = {"busybox", "ping", "-c", "1", "-W", "1", request + 9, NULL};
    struct in_addr destination;
    if (!strncmp(request, "NL1 PING ", 9) && inet_pton(AF_INET, request + 9, &destination) == 1)
        args = ping;
    if (!strcmp(request, "NL1 ADDRESSES")) args = addresses;
    if (!strcmp(request, "NL1 ROUTES")) args = routes;
    char port[10], action[5], cidr[20], extra;
    /* One traceroute hop (one UDP probe at TTL, 1 s wait): the host loops TTLs, as it loops ping's echoes. */
    char trace_ttl[4], trace_destination[16];
    unsigned ttl;
    char *const trace[] = {"busybox", "traceroute", "-n", "-q", "1", "-w", "1", "-f", trace_ttl, "-m", trace_ttl,
                           trace_destination, NULL};
    if (sscanf(request, "NL1 TRACE %u %15s %c", &ttl, trace_destination, &extra) == 2 && ttl >= 1 && ttl <= 30 &&
        inet_pton(AF_INET, trace_destination, &destination) == 1) {
        snprintf(trace_ttl, sizeof(trace_ttl), "%u", ttl);
        args = trace;
    }
    /* 802.1Q subinterfaces, named ethN.VID, through the kernel's VLAN ioctl as vconfig does. */
    unsigned subinterface_vid;
    int subinterface_add = sscanf(request, "NL1 VLAN_ADD %4s %u %c", port, &subinterface_vid, &extra) == 2;
    int subinterface_delete = !subinterface_add && sscanf(request, "NL1 VLAN_DEL %9s %c", port, &extra) == 1;
    if (mutations && ((subinterface_add && valid_port(port) && subinterface_vid >= 1 && subinterface_vid <= 4094) ||
                      (subinterface_delete && valid_interface(port) && strlen(port) > 4))) {
        int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0), failure = fd < 0 ? errno : 0;
        struct vlan_ioctl_args vlan;
        if (!failure && subinterface_add) {
            memset(&vlan, 0, sizeof(vlan));
            vlan.cmd = SET_VLAN_NAME_TYPE_CMD; vlan.u.name_type = VLAN_NAME_TYPE_RAW_PLUS_VID_NO_PAD;
            if (ioctl(fd, SIOCSIFVLAN, &vlan) < 0) failure = errno;
        }
        if (!failure) {
            memset(&vlan, 0, sizeof(vlan));
            vlan.cmd = subinterface_add ? ADD_VLAN_CMD : DEL_VLAN_CMD;
            strncpy(vlan.device1, port, sizeof(vlan.device1) - 1);
            if (subinterface_add) vlan.u.VID = (int)subinterface_vid;
            if (ioctl(fd, SIOCSIFVLAN, &vlan) < 0) failure = errno;
        }
        if (fd >= 0) close(fd);
        if (failure) {
            char text[96]; int n = snprintf(text, sizeof(text), "vlan interface change failed: %s", strerror(failure));
            reply(output, 1, text, (size_t)n); return;
        }
        reply(output, 0, "", 0); return;
    }
    char *const link_args[] = {"busybox", "ip", "link", "set", "dev", port, action, NULL};
    if (mutations && sscanf(request, "NL1 LINK %9s %4s %c", port, action, &extra) == 2 &&
        valid_interface(port) && (!strcmp(action, "up") || !strcmp(action, "down"))) args = link_args;
    char *const address_add[] = {"busybox", "ip", "address", "add", request + 13, "dev", "eth0", NULL};
    char *const address_delete[] = {"busybox", "ip", "address", "del", request + 13, "dev", "eth0", NULL};
    if (mutations && !strncmp(request, "NL1 ADDR_ADD ", 13) && valid_cidr(request + 13)) args = address_add;
    if (mutations && !strncmp(request, "NL1 ADDR_DEL ", 13) && valid_cidr(request + 13)) args = address_delete;
    char *const iface_add[] = {"busybox", "ip", "address", "add", cidr, "dev", port, NULL};
    char *const iface_delete[] = {"busybox", "ip", "address", "del", cidr, "dev", port, NULL};
    if (mutations && sscanf(request, "NL1 IF_ADD %9s %19s %c", port, cidr, &extra) == 2 && valid_interface(port) && valid_cidr(cidr))
        args = iface_add;
    if (mutations && sscanf(request, "NL1 IF_DEL %9s %19s %c", port, cidr, &extra) == 2 && valid_interface(port) && valid_cidr(cidr))
        args = iface_delete;
    char via_network[20], via_gateway[16];
    char *const iface_route_add[] = {"busybox", "ip", "route", "add", via_network, "via", via_gateway, "dev", port, NULL};
    char *const iface_route_delete[] = {"busybox", "ip", "route", "del", via_network, "via", via_gateway, "dev", port, NULL};
    if (mutations && sscanf(request, "NL1 IF_ROUTE_ADD %9s %19s %15s %c", port, via_network, via_gateway, &extra) == 3 &&
        valid_interface(port) && valid_cidr(via_network) && inet_pton(AF_INET, via_gateway, &destination) == 1) args = iface_route_add;
    if (mutations && sscanf(request, "NL1 IF_ROUTE_DEL %9s %19s %15s %c", port, via_network, via_gateway, &extra) == 3 &&
        valid_interface(port) && valid_cidr(via_network) && inet_pton(AF_INET, via_gateway, &destination) == 1) args = iface_route_delete;
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
    char nat_kind[11], nat_to[32], nat_to_port[6], nat_target[40]; struct in_addr nat_address, nat_last;
    char *firewall[24]; int count = 0;
    #define FW(word) firewall[count++] = (char *)(word)
    FW("iptables"); FW("-w");
    int fw_ready = 0;
    if (!strcmp(request, "NL1 FW_LIST")) { FW("-S"); FW("FORWARD"); fw_ready = 1; }
    else if (mutations && !strcmp(request, "NL1 FW_FLUSH")) { FW("-F"); FW("FORWARD"); fw_ready = 1; }
    /* Address translation in the nat table: destination NAT before routing, source NAT after it. */
    else if (!strcmp(request, "NL1 FW_NAT_LIST")) { FW("-t"); FW("nat"); FW("-S"); fw_ready = 1; }
    else if (mutations && !strcmp(request, "NL1 FW_NAT_FLUSH")) { FW("-t"); FW("nat"); FW("-F"); fw_ready = 1; }
    else if (mutations && sscanf(request, "NL1 FW_NAT %10s %4s %4s %4s %19s %19s %5s %31s %5s %c", nat_kind, fw_in, fw_out, fw_proto,
                                 fw_source, fw_destination, fw_port, nat_to, nat_to_port, &extra) == 9) {
        int dnat = !strcmp(nat_kind, "dnat"), snat = !strcmp(nat_kind, "snat"), masquerade = !strcmp(nat_kind, "masquerade");
        int tcp = !strcmp(fw_proto, "tcp"), udp = !strcmp(fw_proto, "udp");
        int has_port = strcmp(fw_port, "-") != 0, has_to_port = strcmp(nat_to_port, "-") != 0;
        int has_in = strcmp(fw_in, "-") != 0, has_out = strcmp(fw_out, "-") != 0;
        /* Source NAT may take an ascending address range A-B (an IOS NAT pool without overload). */
        char *range = snat ? strchr(nat_to, '-') : NULL;
        if (range) *range = '\0';
        int to_ok = masquerade ? !strcmp(nat_to, "-") : inet_pton(AF_INET, nat_to, &nat_address) == 1 &&
                    (!range || (inet_pton(AF_INET, range + 1, &nat_last) == 1 && ntohl(nat_last.s_addr) > ntohl(nat_address.s_addr)));
        if (range) *range = '-';
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
    if (ospf_show) { args = ospf_show; program = "/usr/sbin/birdc"; }
    if (bgp_show) { args = bgp_show; program = "/usr/bin/vtysh"; }
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
