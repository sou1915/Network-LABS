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
#include <linux/neighbour.h>
#include <linux/if_vlan.h>
#include <linux/ethtool.h>
#include <linux/if_packet.h>
#include <poll.h>
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
#include <ctype.h>

#define LIMIT 32768
#define MAX_PORTS 16   /* eth0..eth15: Firecracker's MMIO interrupts hold 16 network devices beside the disk and vsock */
#define PORT_SIZE 6    /* "eth15" */
#define IFACE_SIZE 11  /* "eth15.4094" */
#define RELAY_PORTS MAX_PORTS
static int valid_port(const char *value) {
    size_t n = strlen(value);
    if ((n != 4 && n != 5) || strncmp(value, "eth", 3) || value[3] < '0' || value[3] > '9') return 0;
    if (n == 5 && (value[3] == '0' || value[4] < '0' || value[4] > '9')) return 0;
    return atoi(value + 3) < MAX_PORTS;
}
/* An EtherChannel (IOS Port-channel N): the 802.3ad bond bond1 .. bond8. */
static int valid_bond(const char *value) {
    return strlen(value) == 5 && !strncmp(value, "bond", 4) && value[4] >= '1' && value[4] <= '8';
}
/* A port of a switch guest's bridge: a physical port or a bond. */
static int valid_member(const char *value) { return valid_port(value) || valid_bond(value); }
/* A guest port eth0..eth15, one of its 802.1Q subinterfaces eth0.1 .. eth15.4094, or the bridge br0 and its VLANs. */
static int valid_interface(const char *value) {
    if (!strcmp(value, "br0") || valid_bond(value)) return 1;  /* the bridge (interface vlan N), or a bond (link up/down) */
    const char *dot = strchr(value, '.');
    if (!dot) return valid_port(value);
    if ((size_t)(dot - value) >= PORT_SIZE) return 0;
    char base[PORT_SIZE]; memcpy(base, value, (size_t)(dot - value)); base[dot - value] = 0;
    const char *vid = dot + 1;  /* br0.1 .. br0.4094: a routing switch's SVI; ethN.1 .. ethN.4094: a subinterface */
    if (strcmp(base, "br0") && !valid_port(base)) return 0;
    if (!vid[0] || vid[0] == '0' || strlen(vid) > 4 || strspn(vid, "0123456789") != strlen(vid)) return 0;
    long number = atol(vid); return number >= 1 && number <= 4094;
}
/* A port at 1 Gb/s full duplex: a virtio port reports neither, and 802.3ad bonding runs LACP on full-duplex ports only
 * (an unknown duplex leaves each member individual). Through the ethtool ioctl, as « ethtool -s PORT speed 1000 duplex
 * full autoneg off » does. */
static int full_duplex(const char *port) {
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return errno;
    struct ethtool_cmd settings; memset(&settings, 0, sizeof(settings)); settings.cmd = ETHTOOL_GSET;
    struct ifreq change; memset(&change, 0, sizeof(change)); strncpy(change.ifr_name, port, IFNAMSIZ - 1);
    change.ifr_data = (char *)&settings;
    int failure = ioctl(fd, SIOCETHTOOL, &change) < 0 ? errno : 0;
    if (!failure) {
        settings.cmd = ETHTOOL_SSET; ethtool_cmd_speed_set(&settings, SPEED_1000);
        settings.duplex = DUPLEX_FULL; settings.autoneg = AUTONEG_DISABLE;
        if (ioctl(fd, SIOCETHTOOL, &change) < 0) failure = errno;
    }
    close(fd);
    return failure;
}
/* Write one value to a sysfs file: 0, or the errno. */
static int sysfs_write(const char *path, const char *value) {
    int fd = open(path, O_WRONLY | O_CLOEXEC);
    if (fd < 0) return errno;
    char text[64]; int length = snprintf(text, sizeof(text), "%s\n", value);
    ssize_t n = write(fd, text, (size_t)length);
    int failure = n == length ? 0 : (n < 0 ? errno : EIO);
    close(fd);
    return failure;
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
static int spawn_detached_pid(const char *program, char *const argv[], const char *pidfile) {
    pid_t first = fork();
    if (first < 0) return -1;
    if (first == 0) {
        setsid();
        pid_t second = fork();
        if (second == 0) {
            int null = open("/dev/null", O_RDWR);
            if (null < 0 || dup2(null, 0) < 0 || dup2(null, 1) < 0 || dup2(null, 2) < 0) _exit(126);
            if (pidfile) { /* for a daemon that writes none (dhcprelay): exec keeps this pid */
                char text[16]; int n = snprintf(text, sizeof(text), "%d\n", (int)getpid());
                int fd = open(pidfile, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
                if (fd < 0 || write(fd, text, (size_t)n) != n) _exit(125);
                close(fd);
            }
            char *const env[] = {"PATH=/bin", "LC_ALL=C", NULL};
            execve(program, argv, env); _exit(127);
        }
        _exit(second < 0 ? 1 : 0);
    }
    int status;
    while (waitpid(first, &status, 0) < 0) if (errno != EINTR) return -1;
    return WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : -1;
}
static int spawn_detached(const char *program, char *const argv[]) { return spawn_detached_pid(program, argv, NULL); }
/* One VLAN on one bridge port, through rtnetlink as `bridge vlan add|del` does (BusyBox has no bridge tool). */
static int bridge_vlan(int command, const char *port, unsigned vid, unsigned short flags) {
    int self = !strcmp(port, "br0");  /* the bridge's own VLAN membership (where its management address listens) */
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
    if (self) {
        entry->rta_type = IFLA_BRIDGE_FLAGS; entry->rta_len = RTA_LENGTH(sizeof(__u16));
        __u16 bridge_flags = BRIDGE_FLAGS_SELF; memcpy(RTA_DATA(entry), &bridge_flags, sizeof(bridge_flags));
        entry = (struct rtattr *)((char *)entry + RTA_ALIGN(entry->rta_len));
    }
    entry->rta_type = IFLA_BRIDGE_VLAN_INFO;
    entry->rta_len = RTA_LENGTH(sizeof(struct bridge_vlan_info));
    struct bridge_vlan_info info = {.flags = flags, .vid = (unsigned short)vid};
    memcpy(RTA_DATA(entry), &info, sizeof(info));
    spec->rta_len = (unsigned short)((char *)entry + RTA_ALIGN(entry->rta_len) - (char *)spec);
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
/* The switch bridge's learned MAC addresses as "port mac vlan" lines (IOS show mac address-table), from an AF_BRIDGE
 * neighbour dump; the bridge's own (permanent) entries are left out, as they are not learned. */
static size_t bridge_fdb(char *out, size_t room, int *failure) {
    struct { struct nlmsghdr header; struct ndmsg neighbour; } query;
    memset(&query, 0, sizeof(query));
    query.header.nlmsg_len = sizeof(query);
    query.header.nlmsg_type = RTM_GETNEIGH;
    query.header.nlmsg_flags = NLM_F_REQUEST | NLM_F_DUMP;
    query.neighbour.ndm_family = AF_BRIDGE;
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
            if (header->nlmsg_type != RTM_NEWNEIGH) continue;
            struct ndmsg *entry = NLMSG_DATA(header);
            char name[IF_NAMESIZE] = "";
            if ((entry->ndm_state & NUD_PERMANENT) || !if_indextoname((unsigned)entry->ndm_ifindex, name) || !valid_member(name)) continue;
            unsigned char *mac = NULL; unsigned vlan = 0;
            int length = (int)(header->nlmsg_len - NLMSG_LENGTH(sizeof(struct ndmsg)));
            for (struct rtattr *attribute = (struct rtattr *)((char *)entry + NLMSG_ALIGN(sizeof(struct ndmsg)));
                 RTA_OK(attribute, length); attribute = RTA_NEXT(attribute, length)) {
                if (attribute->rta_type == NDA_LLADDR && RTA_PAYLOAD(attribute) == 6) mac = RTA_DATA(attribute);
                if (attribute->rta_type == NDA_VLAN && RTA_PAYLOAD(attribute) >= sizeof(__u16)) vlan = *(__u16 *)RTA_DATA(attribute);
            }
            if (!mac || (mac[0] & 1)) continue;  /* multicast entries are not learned stations */
            int written = snprintf(out + used, room - used, "%s %02x:%02x:%02x:%02x:%02x:%02x %u\n", name,
                                   mac[0], mac[1], mac[2], mac[3], mac[4], mac[5], vlan);
            if (written < 0 || (size_t)written >= room - used) { *failure = ENOSPC; close(fd); return used; }
            used += (size_t)written;
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
/* EIGRP with FRR (zebra and eigrpd), from typed fields only: "AS ROUTER_ID NET[,NET...] PORT[,PORT...]|-". */
static int eigrp_render(const char *fields, char *out, size_t size) {
    char asn[6], rid[16], networks[160], passive[100], extra;
    if (sscanf(fields, "%5s %15s %159s %99s %c", asn, rid, networks, passive, &extra) != 4) return -1;
    if (!valid_asn(asn) || atol(asn) > 65535 || !valid_ipv4(rid)) return -1;
    int n = snprintf(out, size, "frr defaults traditional\nrouter eigrp %s\n eigrp router-id %s\n", asn, rid);
    int count = 0;
    for (char *item = strtok(networks, ","); item; item = strtok(NULL, ",")) {
        if (++count > 8 || !valid_cidr(item)) return -1;
        n += snprintf(out + n, size - (size_t)n, " network %s\n", item);
        if (n >= (int)size - 64) return -1;
    }
    if (!count) return -1;
    if (strcmp(passive, "-")) {
        int ports = 0;
        for (char *item = strtok(passive, ","); item; item = strtok(NULL, ",")) {
            if (++ports > MAX_PORTS || !valid_port(item)) return -1;
            n += snprintf(out + n, size - (size_t)n, " passive-interface %s\n", item);
        }
    }
    return n;
}
static int ospf_render(const char *fields, char *out, size_t size) {
    char rid[16], list[400], extra; unsigned hello, dead;
    if (sscanf(fields, "%15s %u %u %399s %c", rid, &hello, &dead, list, &extra) != 4) return -1;
    if (!valid_ipv4(rid) || hello < 1 || hello > 60 || dead < 2 || dead > 240 || dead <= hello) return -1;
    int n = snprintf(out, size, "router id %s;\nlog stderr all;\nprotocol device { scan time 1; }\n"
                     "protocol kernel kernel4 { scan time 1; ipv4 { import none; export where source = RTS_OSPF; }; }\n"
                     "protocol ospf v2 ospf4 {\n  ipv4 { import where source = RTS_OSPF; export none; };\n"
                     "  ecmp no;\n  area 0.0.0.0 {\n", rid);
    int count = 0, active = 0; char seen[MAX_PORTS] = {0};
    for (char *item = strtok(list, ","); item; item = strtok(NULL, ",")) {
        char port[PORT_SIZE], stub, type, tail; unsigned cost, priority;
        if (++count > MAX_PORTS || sscanf(item, "%5[^:]:%u:%c:%c:%u%c", port, &cost, &stub, &type, &priority, &tail) != 5) return -1;
        if (!valid_port(port) || seen[atoi(port + 3)]++ || cost < 1 || cost > 65535 || (stub != 'y' && stub != 'n')) return -1;
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
    char rid[16], list[160], copy[160], extra; unsigned version;
    if (sscanf(fields, "%15s %u %159s %c", rid, &version, list, &extra) != 3) return -1;
    if (!valid_ipv4(rid) || (version != 1 && version != 2)) return -1;
    memcpy(copy, list, sizeof(copy));
    char names[MAX_PORTS][PORT_SIZE]; char modes[MAX_PORTS]; int count = 0;
    for (char *item = strtok(copy, ","); item; item = strtok(NULL, ",")) {
        char port[PORT_SIZE], mode, tail;
        if (count >= MAX_PORTS || sscanf(item, "%5[^:]:%c%c", port, &mode, &tail) != 2) return -1;
        if (!valid_port(port) || (mode != 'a' && mode != 'p')) return -1;
        for (int i = 0; i < count; i++) if (!strcmp(names[i], port)) return -1;
        memcpy(names[count], port, PORT_SIZE); modes[count++] = mode;
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
/* Port security and BPDU guard (IOS « switchport port-security », « spanning-tree bpduguard enable »): this agent's
 * --port-guard mode watches each guarded port's incoming frames. Each argument: PORT/MAX/MODE/STICKY/BPDU/VID/MACS, MODE
 * s(hutdown) r(estrict) p(rotect) or n (no port security, BPDU guard only), MACS the secure addresses (hex, '+' between)
 * or '-'. A source address beyond MAX is a violation: shutdown err-disables the port (link down); restrict and protect
 * pin the address on the bridge as local, so nothing is forwarded to it any more. A BPDU on a BPDU-guard port
 * err-disables it. State: /run/port-guard/PORT (kept across restarts: an err-disabled port stays so until cleared). */
#define GUARD_MACS 64
struct guard { char port[PORT_SIZE]; int fd, max, sticky, bpdu, vid; char mode; unsigned char macs[GUARD_MACS][6];
               char kinds[GUARD_MACS]; int count; unsigned violations; unsigned char last[6]; int disabled; char reason[24]; };
static int hex_mac(const char *text, unsigned char *mac) {
    if (strlen(text) != 12 || strspn(text, "0123456789abcdef") != 12) return 0;
    for (int i = 0; i < 6; i++) { unsigned value; sscanf(text + 2 * i, "%2x", &value); mac[i] = (unsigned char)value; }
    return 1;
}
static void guard_save(struct guard *g) {
    char path[48], temporary[56], text[2048]; size_t used = 0;
    snprintf(path, sizeof(path), "/run/port-guard/%.5s", g->port); snprintf(temporary, sizeof(temporary), "%.47s.new", path);
    used += (size_t)snprintf(text + used, sizeof(text) - used, "state %s\nreason %s\nviolations %u\nlast ",
                             g->disabled ? "err-disabled" : "secure", g->reason[0] ? g->reason : "-", g->violations);
    if (g->violations) for (int i = 0; i < 6; i++) used += (size_t)snprintf(text + used, sizeof(text) - used, "%02x", g->last[i]);
    else used += (size_t)snprintf(text + used, sizeof(text) - used, "-");
    used += (size_t)snprintf(text + used, sizeof(text) - used, "\nmacs");
    for (int m = 0; m < g->count && used < sizeof(text) - 20; m++) {
        used += (size_t)snprintf(text + used, sizeof(text) - used, " ");
        for (int i = 0; i < 6; i++) used += (size_t)snprintf(text + used, sizeof(text) - used, "%02x", g->macs[m][i]);
        used += (size_t)snprintf(text + used, sizeof(text) - used, ":%c", g->kinds[m]);
    }
    used += (size_t)snprintf(text + used, sizeof(text) - used, "\n");
    int fd = open(temporary, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (fd < 0) return;
    ssize_t n = write(fd, text, used); close(fd);
    if (n == (ssize_t)used) rename(temporary, path);
}
static void guard_disable(struct guard *g, const char *reason) {
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    struct ifreq change; memset(&change, 0, sizeof(change)); strncpy(change.ifr_name, g->port, IFNAMSIZ - 1);
    if (fd >= 0 && ioctl(fd, SIOCGIFFLAGS, &change) == 0) { change.ifr_flags &= ~IFF_UP; ioctl(fd, SIOCSIFFLAGS, &change); }
    if (fd >= 0) close(fd);
    g->disabled = 1; snprintf(g->reason, sizeof(g->reason), "%s", reason);
    if (g->fd >= 0) { close(g->fd); g->fd = -1; }
    guard_save(g);
}
/* restrict / protect: the violating address as a local entry of the bridge, in the port's VLAN (nothing goes to it). */
static void guard_pin(struct guard *g, const unsigned char *mac) {
    struct { struct nlmsghdr header; struct ndmsg neighbour; char attributes[64]; } message;
    memset(&message, 0, sizeof(message));
    message.header.nlmsg_len = NLMSG_LENGTH(sizeof(struct ndmsg));
    message.header.nlmsg_type = RTM_NEWNEIGH; message.header.nlmsg_flags = NLM_F_REQUEST | NLM_F_CREATE | NLM_F_REPLACE;
    message.neighbour.ndm_family = AF_BRIDGE; message.neighbour.ndm_state = NUD_PERMANENT; message.neighbour.ndm_flags = NTF_MASTER;
    message.neighbour.ndm_ifindex = (int)if_nametoindex(g->port);
    struct rtattr *attribute = (struct rtattr *)((char *)&message + NLMSG_ALIGN(message.header.nlmsg_len));
    attribute->rta_type = NDA_LLADDR; attribute->rta_len = RTA_LENGTH(6); memcpy(RTA_DATA(attribute), mac, 6);
    message.header.nlmsg_len = NLMSG_ALIGN(message.header.nlmsg_len) + RTA_ALIGN(attribute->rta_len);
    if (g->vid) {
        attribute = (struct rtattr *)((char *)&message + message.header.nlmsg_len);
        attribute->rta_type = NDA_VLAN; attribute->rta_len = RTA_LENGTH(sizeof(__u16));
        __u16 vid = (__u16)g->vid; memcpy(RTA_DATA(attribute), &vid, sizeof(vid));
        message.header.nlmsg_len += RTA_ALIGN(attribute->rta_len);
    }
    int fd = socket(AF_NETLINK, SOCK_RAW | SOCK_CLOEXEC, NETLINK_ROUTE);
    if (fd < 0) return;
    send(fd, &message, message.header.nlmsg_len, 0);
    char answer[256]; recv(fd, answer, sizeof(answer), MSG_DONTWAIT);
    close(fd);
}
static int guard_parse(const char *text, struct guard *g) {
    char copy[1024], *fields[7], *rest = NULL; int n = 0;  /* strtok_r: the request loop splits with strtok */
    if (strlen(text) >= sizeof(copy)) return 0;
    strcpy(copy, text);
    for (char *item = strtok_r(copy, "/", &rest); item && n < 7; item = strtok_r(NULL, "/", &rest)) fields[n++] = item;
    if (n != 7 || !valid_port(fields[0]) || strspn(fields[1], "0123456789") != strlen(fields[1]) || !strchr("srpn", fields[2][0])
        || strlen(fields[2]) != 1 || strlen(fields[3]) != 1 || !strchr("yn", fields[3][0]) || strlen(fields[4]) != 1
        || !strchr("yn", fields[4][0]) || strspn(fields[5], "0123456789") != strlen(fields[5])) return 0;
    memset(g, 0, sizeof(*g)); g->fd = -1;
    snprintf(g->port, sizeof(g->port), "%s", fields[0]);
    g->max = atoi(fields[1]); g->mode = fields[2][0]; g->sticky = fields[3][0] == 'y'; g->bpdu = fields[4][0] == 'y';
    g->vid = atoi(fields[5]);
    if (g->max > GUARD_MACS || g->vid > 4094 || (g->mode != 'n' && g->max < 1)) return 0;
    if (strcmp(fields[6], "-")) {
        for (char *item = strtok_r(fields[6], "+", &rest); item; item = strtok_r(NULL, "+", &rest)) {
            if (g->count >= g->max || !hex_mac(item, g->macs[g->count])) return 0;
            g->kinds[g->count++] = 's';  /* configured: static or sticky in the running configuration */
        }
    }
    return 1;
}
static int port_guard(int count, char **specs) {
    struct guard guards[MAX_PORTS]; struct pollfd waits[MAX_PORTS];
    if (count < 1 || count > MAX_PORTS) return 2;
    mkdir("/run/port-guard", 0755);
    for (int i = 0; i < count; i++) {
        if (!guard_parse(specs[i], &guards[i])) return 2;
        char path[48], text[64] = {0}; snprintf(path, sizeof(path), "/run/port-guard/%.5s", guards[i].port);
        int fd = open(path, O_RDONLY | O_CLOEXEC);  /* an err-disabled port stays so until its state is cleared */
        if (fd >= 0) {
            ssize_t n = read(fd, text, sizeof(text) - 1); close(fd);
            if (n > 0 && !strncmp(text, "state err-disabled", 18)) {
                char *reason = strstr(text, "reason ");
                guards[i].disabled = 1;
                if (reason) sscanf(reason + 7, "%23s", guards[i].reason);
                continue;
            }
        }
        int sock = socket(AF_PACKET, SOCK_RAW | SOCK_CLOEXEC, htons(ETH_P_ALL));
        struct sockaddr_ll where; memset(&where, 0, sizeof(where));
        where.sll_family = AF_PACKET; where.sll_protocol = htons(ETH_P_ALL); where.sll_ifindex = (int)if_nametoindex(guards[i].port);
        if (sock < 0 || !where.sll_ifindex || bind(sock, (struct sockaddr *)&where, sizeof(where))) return 1;
        guards[i].fd = sock;
        guard_save(&guards[i]);
    }
    static const unsigned char bpdu[6] = {0x01, 0x80, 0xc2, 0x00, 0x00, 0x00};
    for (;;) {
        for (int i = 0; i < count; i++) { waits[i].fd = guards[i].fd; waits[i].events = POLLIN; waits[i].revents = 0; }
        if (poll(waits, (nfds_t)count, -1) < 0) { if (errno == EINTR) continue; return 1; }
        for (int i = 0; i < count; i++) {
            struct guard *g = &guards[i];
            if (g->fd < 0 || !(waits[i].revents & POLLIN)) continue;
            unsigned char frame[2048]; struct sockaddr_ll from; socklen_t size = sizeof(from);
            ssize_t n = recvfrom(g->fd, frame, sizeof(frame), 0, (struct sockaddr *)&from, &size);
            if (n < 14 || from.sll_pkttype == PACKET_OUTGOING) continue;
            if (g->bpdu && !memcmp(frame, bpdu, 6)) { guard_disable(g, "bpduguard"); continue; }
            if (g->mode == 'n' || (frame[6] & 1)) continue;
            int known = 0;
            for (int m = 0; m < g->count && !known; m++) known = !memcmp(g->macs[m], frame + 6, 6);
            if (known) continue;
            if (g->count < g->max) {
                memcpy(g->macs[g->count], frame + 6, 6); g->kinds[g->count++] = g->sticky ? 'k' : 'd';
                guard_save(g); continue;
            }
            int repeated = g->violations && !memcmp(g->last, frame + 6, 6);
            g->violations++; memcpy(g->last, frame + 6, 6);
            if (g->mode == 's') { guard_disable(g, "psecure-violation"); continue; }
            if (!repeated) guard_pin(g, frame + 6);
            guard_save(g);
        }
    }
}
/* HSRP (IOS « standby »): this agent's --hsrp mode speaks HSRP on a router's LAN ports, version 1 (UDP 1985 to
 * 224.0.0.2, RFC 2281) or version 2 (224.0.0.102, TLVs). Each argument: IFACE/GROUP/VERSION/VIP/PRIORITY/PREEMPT/HELLO/
 * HOLD/AUTH, AUTH in hex. The routers of a group elect an active router (highest priority, then highest address; with
 * preempt a higher priority takes over by a coup) and a standby that takes over when the active one falls silent for the
 * hold time. The active router holds the virtual address on a macvlan device carrying the group's virtual MAC
 * (0000.0c07.acNN, version 2 0000.0c9f.fNNN): the hosts' gateway keeps its MAC across a failover, and a gratuitous ARP
 * moves it in the switches. A guest kernel without macvlan gets the address on the port itself. State:
 * /run/hsrp/IFACE.GROUP. SIGTERM resigns and removes everything; SIGUSR1 leaves it to the next instance (a configuration
 * change), which takes the groups back in their state. */
#define HSRP_GROUPS 16
enum { HS_INIT = 0, HS_LISTEN = 2, HS_SPEAK = 4, HS_STANDBY = 8, HS_ACTIVE = 16 };
struct hsrp { char iface[IFACE_SIZE], vdev[IFNAMSIZ]; int group, version, priority, preempt, hello, hold, fd, state, macvlan;
              unsigned changes; struct in_addr vip, self, active, standby, speaker; int active_priority, standby_priority;
              unsigned char auth[8], mac[6], vmac[6]; double since, entered, next_hello, active_until, standby_until, speaker_until; };
static volatile sig_atomic_t hsrp_signal;
static void hsrp_caught(int number) { hsrp_signal = number; }
static double hsrp_now(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}
static int nl_talk(void *message, unsigned length) {
    int fd = socket(AF_NETLINK, SOCK_RAW | SOCK_CLOEXEC, NETLINK_ROUTE);
    if (fd < 0) return errno;
    int result = EIO; char answer[512];
    if (send(fd, message, length, 0) == (ssize_t)length) {
        ssize_t n = recv(fd, answer, sizeof(answer), 0);
        struct nlmsghdr *header = (struct nlmsghdr *)answer;
        if (n >= (ssize_t)NLMSG_LENGTH(sizeof(struct nlmsgerr)) && header->nlmsg_type == NLMSG_ERROR)
            result = -((struct nlmsgerr *)NLMSG_DATA(header))->error;
    }
    close(fd);
    return result;
}
static struct rtattr *nl_put(struct nlmsghdr *header, unsigned short type, const void *data, unsigned size) {
    struct rtattr *attribute = (struct rtattr *)((char *)header + NLMSG_ALIGN(header->nlmsg_len));
    attribute->rta_type = type; attribute->rta_len = (unsigned short)RTA_LENGTH(size);
    if (size) memcpy(RTA_DATA(attribute), data, size);
    header->nlmsg_len = NLMSG_ALIGN(header->nlmsg_len) + RTA_ALIGN(attribute->rta_len);
    return attribute;
}
static void nl_close(struct nlmsghdr *header, struct rtattr *nest) {
    nest->rta_len = (unsigned short)((char *)header + header->nlmsg_len - (char *)nest);
}
/* A macvlan device NAME on port LOWER with MAC, up (`ip link add NAME link PORT address MAC type macvlan mode private`). */
static int hsrp_vdev(const char *name, int lower, const unsigned char *mac) {
    struct { struct nlmsghdr header; struct ifinfomsg link; char attributes[256]; } message;
    memset(&message, 0, sizeof(message));
    message.header.nlmsg_len = NLMSG_LENGTH(sizeof(struct ifinfomsg)); message.header.nlmsg_type = RTM_NEWLINK;
    message.header.nlmsg_flags = NLM_F_REQUEST | NLM_F_ACK | NLM_F_CREATE | NLM_F_EXCL;
    message.link.ifi_family = AF_UNSPEC; message.link.ifi_flags = IFF_UP; message.link.ifi_change = IFF_UP;
    __u32 link = (__u32)lower, mode = MACVLAN_MODE_PRIVATE;
    nl_put(&message.header, IFLA_LINK, &link, sizeof(link));
    nl_put(&message.header, IFLA_IFNAME, name, (unsigned)strlen(name) + 1);
    nl_put(&message.header, IFLA_ADDRESS, mac, 6);
    struct rtattr *info = nl_put(&message.header, IFLA_LINKINFO, NULL, 0);
    nl_put(&message.header, IFLA_INFO_KIND, "macvlan", 8);
    struct rtattr *data = nl_put(&message.header, IFLA_INFO_DATA, NULL, 0);
    nl_put(&message.header, IFLA_MACVLAN_MODE, &mode, sizeof(mode));
    nl_close(&message.header, data);
    nl_close(&message.header, info);
    return nl_talk(&message, message.header.nlmsg_len);
}
static int hsrp_link_delete(const char *name) {
    struct { struct nlmsghdr header; struct ifinfomsg link; } message;
    memset(&message, 0, sizeof(message));
    message.header.nlmsg_len = sizeof(message); message.header.nlmsg_type = RTM_DELLINK;
    message.header.nlmsg_flags = NLM_F_REQUEST | NLM_F_ACK;
    message.link.ifi_family = AF_UNSPEC; message.link.ifi_index = (int)if_nametoindex(name);
    return message.link.ifi_index ? nl_talk(&message, sizeof(message)) : ENODEV;
}
static int hsrp_address(int command, int index, struct in_addr address) {  /* ADDRESS/32 on (or off) a device */
    struct { struct nlmsghdr header; struct ifaddrmsg address; char attributes[32]; } message;
    memset(&message, 0, sizeof(message));
    message.header.nlmsg_len = NLMSG_LENGTH(sizeof(struct ifaddrmsg)); message.header.nlmsg_type = (unsigned short)command;
    message.header.nlmsg_flags = NLM_F_REQUEST | NLM_F_ACK | (command == RTM_NEWADDR ? NLM_F_CREATE | NLM_F_REPLACE : 0);
    message.address.ifa_family = AF_INET; message.address.ifa_prefixlen = 32; message.address.ifa_index = (unsigned)index;
    nl_put(&message.header, IFA_LOCAL, &address, 4);
    nl_put(&message.header, IFA_ADDRESS, &address, 4);
    return index ? nl_talk(&message, message.header.nlmsg_len) : ENODEV;
}
static void hsrp_sysctl(const char *device, const char *key, const char *value) {
    char path[96]; snprintf(path, sizeof(path), "/proc/sys/net/ipv4/conf/%.15s/%s", device, key);
    int fd = open(path, O_WRONLY | O_CLOEXEC);
    if (fd < 0) return;
    ssize_t n = write(fd, value, strlen(value)); (void)n;
    close(fd);
}
static int hsrp_parse(const char *text, struct hsrp *h) {
    char copy[160], *fields[9], *rest = NULL; int n = 0;  /* strtok_r: the request loop splits with strtok */
    if (strlen(text) >= sizeof(copy)) return 0;
    strcpy(copy, text);
    char *item = strtok_r(copy, "/", &rest);
    while (item && n < 9) { fields[n++] = item; item = strtok_r(NULL, "/", &rest); }
    if (n != 9 || item || !valid_interface(fields[0]) || strncmp(fields[0], "eth", 3)) return 0;
    static const int numeric[] = {1, 2, 4, 6, 7};
    for (int i = 0; i < 5; i++) {
        const char *field = fields[numeric[i]];
        if (!field[0] || strlen(field) > 4 || strspn(field, "0123456789") != strlen(field)) return 0;
    }
    memset(h, 0, sizeof(*h)); h->fd = -1;
    snprintf(h->iface, sizeof(h->iface), "%s", fields[0]);
    h->group = atoi(fields[1]); h->version = atoi(fields[2]); h->priority = atoi(fields[4]);
    h->hello = atoi(fields[6]); h->hold = atoi(fields[7]);
    if ((h->version != 1 && h->version != 2) || h->group > (h->version == 1 ? 255 : 4095) || h->priority > 255
        || inet_pton(AF_INET, fields[3], &h->vip) != 1 || strlen(fields[5]) != 1 || !strchr("yn", fields[5][0])
        || h->hello < 1 || h->hello > 254 || h->hold <= h->hello || h->hold > 255) return 0;
    size_t hex = strlen(fields[8]);
    if (hex < 2 || hex > 16 || hex % 2 || strspn(fields[8], "0123456789abcdef") != hex) return 0;
    for (size_t i = 0; i < hex / 2; i++) { unsigned value; sscanf(fields[8] + 2 * i, "%2x", &value); h->auth[i] = (unsigned char)value; }
    h->preempt = fields[5][0] == 'y';
    unsigned char vmac[6] = {0x00, 0x00, 0x0c, 0x07, 0xac, (unsigned char)h->group};
    if (h->version == 2) { vmac[3] = 0x9f; vmac[4] = (unsigned char)(0xf0 | (h->group >> 8)); vmac[5] = (unsigned char)(h->group & 0xff); }
    memcpy(h->vmac, vmac, 6);
    return 1;
}
/* 1 when the port is up with an address: its MAC and address are refreshed. */
static int hsrp_port(struct hsrp *h) {
    struct ifreq query; memset(&query, 0, sizeof(query)); snprintf(query.ifr_name, sizeof(query.ifr_name), "%s", h->iface);
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0), up = 0;
    if (fd < 0) return 0;
    if (ioctl(fd, SIOCGIFFLAGS, &query) == 0 && (query.ifr_flags & IFF_UP) && (query.ifr_flags & IFF_RUNNING)
        && ioctl(fd, SIOCGIFHWADDR, &query) == 0) {
        memcpy(h->mac, query.ifr_hwaddr.sa_data, 6);
        up = ioctl(fd, SIOCGIFADDR, &query) == 0;
        if (up) h->self = ((struct sockaddr_in *)&query.ifr_addr)->sin_addr;
    }
    close(fd);
    return up;
}
static void hsrp_open(struct hsrp *h) {
    if (h->fd >= 0) return;
    int sock = socket(AF_PACKET, SOCK_RAW | SOCK_CLOEXEC, htons(ETH_P_IP));
    struct sockaddr_ll where; memset(&where, 0, sizeof(where));
    where.sll_family = AF_PACKET; where.sll_protocol = htons(ETH_P_IP); where.sll_ifindex = (int)if_nametoindex(h->iface);
    if (sock >= 0 && where.sll_ifindex && !bind(sock, (struct sockaddr *)&where, sizeof(where))) { h->fd = sock; return; }
    if (sock >= 0) close(sock);
}
static unsigned short hsrp_sum(const unsigned char *data, size_t size, unsigned long sum) {
    for (size_t i = 0; i + 1 < size; i += 2) sum += (unsigned long)(data[i] << 8 | data[i + 1]);
    if (size & 1) sum += (unsigned long)data[size - 1] << 8;
    while (sum >> 16) sum = (sum & 0xffff) + (sum >> 16);
    return (unsigned short)~sum;
}
static void hsrp_frame(struct hsrp *h, const unsigned char *frame, size_t size, unsigned short protocol) {
    struct sockaddr_ll to; memset(&to, 0, sizeof(to));
    to.sll_family = AF_PACKET; to.sll_protocol = htons(protocol); to.sll_ifindex = (int)if_nametoindex(h->iface);
    to.sll_halen = 6; memcpy(to.sll_addr, frame, 6);
    if (h->fd >= 0 && to.sll_ifindex) sendto(h->fd, frame, size, 0, (struct sockaddr *)&to, sizeof(to));
}
/* One HSRP message: OP 0 hello, 1 coup, 2 resign; from the virtual MAC while active (the switches learn where it is). */
static void hsrp_send(struct hsrp *h, int op) {
    unsigned char frame[128]; memset(frame, 0, sizeof(frame));
    size_t payload = h->version == 1 ? 20 : 52;
    unsigned char *ip = frame + 14, *udp = ip + 20, *p = udp + 8;
    static const unsigned char all_routers[6] = {0x01, 0x00, 0x5e, 0x00, 0x00, 0x02}, v2[6] = {0x01, 0x00, 0x5e, 0x00, 0x00, 0x66};
    memcpy(frame, h->version == 1 ? all_routers : v2, 6);
    memcpy(frame + 6, h->state == HS_ACTIVE && h->macvlan ? h->vmac : h->mac, 6);
    frame[12] = 0x08;
    struct in_addr group; inet_pton(AF_INET, h->version == 1 ? "224.0.0.2" : "224.0.0.102", &group);
    if (h->version == 1) {
        p[1] = (unsigned char)op; p[2] = (unsigned char)h->state; p[3] = (unsigned char)h->hello; p[4] = (unsigned char)h->hold;
        p[5] = (unsigned char)h->priority; p[6] = (unsigned char)h->group; memcpy(p + 8, h->auth, 8); memcpy(p + 16, &h->vip, 4);
    } else {
        static const unsigned char codes[17] = {[HS_INIT] = 1, [HS_LISTEN] = 3, [HS_SPEAK] = 4, [HS_STANDBY] = 5, [HS_ACTIVE] = 6};
        p[0] = 1; p[1] = 40; p[2] = 2; p[3] = (unsigned char)op; p[4] = codes[h->state]; p[5] = 4;
        p[6] = (unsigned char)(h->group >> 8); p[7] = (unsigned char)h->group; memcpy(p + 8, h->mac, 6);
        unsigned long values[3] = {(unsigned long)h->priority, (unsigned long)h->hello * 1000, (unsigned long)h->hold * 1000};
        for (int v = 0; v < 3; v++)
            for (int b = 0; b < 4; b++) p[14 + 4 * v + b] = (unsigned char)(values[v] >> (24 - 8 * b));
        memcpy(p + 26, &h->vip, 4); p[42] = 3; p[43] = 8; memcpy(p + 44, h->auth, 8);
    }
    size_t udp_size = 8 + payload, total = 20 + udp_size;
    ip[0] = 0x45; ip[1] = 0xc0; ip[2] = (unsigned char)(total >> 8); ip[3] = (unsigned char)total; ip[8] = 1; ip[9] = 17;
    memcpy(ip + 12, &h->self, 4); memcpy(ip + 16, &group, 4);
    unsigned short sum = hsrp_sum(ip, 20, 0);
    ip[10] = (unsigned char)(sum >> 8); ip[11] = (unsigned char)sum;
    udp[0] = 0x07; udp[1] = 0xc1; udp[2] = 0x07; udp[3] = 0xc1; udp[4] = (unsigned char)(udp_size >> 8); udp[5] = (unsigned char)udp_size;
    unsigned long pseudo = 17 + udp_size;
    for (int i = 12; i < 20; i += 2) pseudo += (unsigned long)(ip[i] << 8 | ip[i + 1]);
    sum = hsrp_sum(udp, udp_size, pseudo);
    if (!sum) sum = 0xffff;
    udp[6] = (unsigned char)(sum >> 8); udp[7] = (unsigned char)sum;
    hsrp_frame(h, frame, 14 + total, ETH_P_IP);
}
static void hsrp_garp(struct hsrp *h) {  /* "VIP is at MAC": the hosts and the switches learn it */
    unsigned char frame[42], *arp = frame + 14;
    const unsigned char *mac = h->macvlan ? h->vmac : h->mac;
    memset(frame, 0xff, 6); memcpy(frame + 6, mac, 6); frame[12] = 0x08; frame[13] = 0x06;
    static const unsigned char head[8] = {0, 1, 8, 0, 6, 4, 0, 1};
    memcpy(arp, head, 8); memcpy(arp + 8, mac, 6); memcpy(arp + 14, &h->vip, 4); memset(arp + 18, 0, 6); memcpy(arp + 24, &h->vip, 4);
    hsrp_frame(h, frame, sizeof(frame), ETH_P_ARP);
}
static void hsrp_claim(struct hsrp *h) {
    int lower = (int)if_nametoindex(h->iface);
    snprintf(h->vdev, sizeof(h->vdev), "hsrp%d-%d", lower, h->group);
    if (if_nametoindex(h->vdev) || !hsrp_vdev(h->vdev, lower, h->vmac)) {  /* taken back from the previous instance, or made */
        h->macvlan = 1;
        hsrp_sysctl(h->vdev, "rp_filter", "0");
        hsrp_sysctl(h->iface, "arp_ignore", "1");  /* the port itself does not answer for the virtual address */
        hsrp_sysctl(h->iface, "arp_announce", "2");  /* nor asks with it as sender: the hosts keep the virtual MAC */
        hsrp_address(RTM_NEWADDR, (int)if_nametoindex(h->vdev), h->vip);
    } else {
        h->macvlan = 0; snprintf(h->vdev, sizeof(h->vdev), "-");
        hsrp_address(RTM_NEWADDR, lower, h->vip);
    }
    hsrp_garp(h); hsrp_garp(h);
}
static void hsrp_release(struct hsrp *h) {
    if (h->macvlan) hsrp_link_delete(h->vdev);
    else hsrp_address(RTM_DELADDR, (int)if_nametoindex(h->iface), h->vip);
    h->macvlan = 0;
}
static const char *hsrp_state_name(int state) {
    return state == HS_ACTIVE ? "active" : state == HS_STANDBY ? "standby" : state == HS_SPEAK ? "speak"
         : state == HS_LISTEN ? "listen" : "init";
}
static void hsrp_save(struct hsrp *h, double now) {
    char path[48], temporary[56], text[1024], vip[16], active[16] = "-", standby[16] = "-", auth[17];
    snprintf(path, sizeof(path), "/run/hsrp/%.10s.%d", h->iface, h->group);
    snprintf(temporary, sizeof(temporary), "%.47s.new", path);
    inet_ntop(AF_INET, &h->vip, vip, sizeof(vip));
    if (h->state == HS_ACTIVE) strcpy(active, "local");
    else if (now < h->active_until) inet_ntop(AF_INET, &h->active, active, sizeof(active));
    if (h->state == HS_STANDBY) strcpy(standby, "local");
    else if (now < h->standby_until) inet_ntop(AF_INET, &h->standby, standby, sizeof(standby));
    for (int i = 0; i < 8; i++) snprintf(auth + 2 * i, 3, "%02x", h->auth[i]);
    int n = snprintf(text, sizeof(text),
        "interface %s\ngroup %d\nversion %d\nvip %s\nvdev %s\nmacvlan %d\nstate %s\npriority %d\npreempt %c\nhello %d\nhold %d\n"
        "auth %s\nchanges %u\nsince %.1f\nactive %s %d %.1f\nstandby %s %d %.1f\nnext %.1f\n",
        h->iface, h->group, h->version, vip, h->state == HS_ACTIVE ? h->vdev : "-", h->macvlan, hsrp_state_name(h->state),
        h->priority, h->preempt ? 'y' : 'n', h->hello, h->hold, auth, h->changes, h->since,
        active, h->state == HS_ACTIVE ? h->priority : h->active_priority, h->active_until,
        standby, h->state == HS_STANDBY ? h->priority : h->standby_priority, h->standby_until, h->next_hello);
    int fd = open(temporary, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (fd < 0 || n <= 0) { if (fd >= 0) close(fd); return; }
    ssize_t written = write(fd, text, (size_t)n); close(fd);
    if (written == n) rename(temporary, path);
}
static void hsrp_to(struct hsrp *h, int state, double now) {
    if (h->state == state) return;
    if (h->state == HS_ACTIVE) hsrp_release(h);
    h->state = state; h->entered = now; h->since = now; h->changes++;
    if (state == HS_ACTIVE) { hsrp_claim(h); h->active = h->self; h->active_priority = h->priority; }
    if (state >= HS_SPEAK) h->next_hello = now;  /* say it at once */
    hsrp_save(h, now);
}
static int hsrp_beats(struct hsrp *h, int priority, struct in_addr address) {  /* that router outranks this one */
    return priority > h->priority || (priority == h->priority && ntohl(address.s_addr) > ntohl(h->self.s_addr));
}
static void hsrp_receive(struct hsrp *h, double now) {
    unsigned char frame[1600]; struct sockaddr_ll from; socklen_t size = sizeof(from);
    ssize_t n = recvfrom(h->fd, frame, sizeof(frame), 0, (struct sockaddr *)&from, &size);
    if (n < 14 + 20 + 8 + 20 || from.sll_pkttype == PACKET_OUTGOING) return;
    const unsigned char *ip = frame + 14;
    size_t header = (size_t)(ip[0] & 0x0f) * 4;
    if ((ip[0] >> 4) != 4 || header < 20 || ip[9] != 17 || (size_t)n < 14 + header + 8 + 20) return;
    const unsigned char *udp = ip + header, *p = udp + 8;
    if (udp[2] != 0x07 || udp[3] != 0xc1) return;
    struct in_addr source; memcpy(&source, ip + 12, 4);
    if (source.s_addr == h->self.s_addr) return;
    size_t room = (size_t)n - 14 - header - 8;
    int op, state, priority, group; unsigned char auth[8];
    if (h->version == 1) {
        if (p[0] != 0) return;
        op = p[1]; state = p[2]; priority = p[5]; group = p[6]; memcpy(auth, p + 8, 8);
    } else {
        static const int states[7] = {HS_INIT, HS_INIT, HS_INIT, HS_LISTEN, HS_SPEAK, HS_STANDBY, HS_ACTIVE};
        if (room < 42 || p[0] != 1 || p[1] != 40 || p[2] != 2 || p[5] != 4 || p[4] > 6) return;
        op = p[3]; state = states[p[4]]; group = p[6] << 8 | p[7]; priority = (p[14] | p[15] | p[16]) ? 255 : p[17];
        memcpy(auth, "cisco\0\0\0", 8);
        if (room >= 52 && p[42] == 3 && p[43] == 8) memcpy(auth, p + 44, 8);
    }
    if (group != h->group || memcmp(auth, h->auth, 8)) return;
    int better = hsrp_beats(h, priority, source);
    if (op == 2) {  /* resign: the active router leaves the group */
        if (h->active.s_addr == source.s_addr) h->active_until = 0;
        return;
    }
    if (op == 1) {  /* coup: a router of higher priority takes over */
        if (h->state == HS_ACTIVE && priority > h->priority) hsrp_to(h, HS_SPEAK, now);
        if (h->state != HS_ACTIVE) { h->active = source; h->active_priority = priority; h->active_until = now + h->hold; }
        return;
    }
    if (state == HS_ACTIVE) {
        h->active = source; h->active_priority = priority; h->active_until = now + h->hold;
        if (h->standby.s_addr == source.s_addr) h->standby_until = 0;
        if (h->state == HS_ACTIVE && better) hsrp_to(h, HS_SPEAK, now);
    } else if (state == HS_STANDBY) {
        h->standby = source; h->standby_priority = priority; h->standby_until = now + h->hold;
        if (h->active.s_addr == source.s_addr) h->active_until = 0;
        if (h->state == HS_STANDBY && better) hsrp_to(h, HS_LISTEN, now);
    } else if (state == HS_SPEAK) {
        if (h->active.s_addr == source.s_addr) h->active_until = 0;
        if (better) { h->speaker = source; h->speaker_until = now + h->hold; }
        if ((h->state == HS_SPEAK || h->state == HS_STANDBY) && better) hsrp_to(h, HS_LISTEN, now);
    }
}
static void hsrp_tick(struct hsrp *h, double now) {
    if (!hsrp_port(h)) {  /* port down or without its address: Init, as IOS shows it */
        hsrp_to(h, HS_INIT, now);
        if (h->fd >= 0) { close(h->fd); h->fd = -1; }
        return;
    }
    hsrp_open(h);
    if (h->fd < 0) return;
    if (h->state == HS_INIT) { h->active_until = h->standby_until = h->speaker_until = 0; hsrp_to(h, HS_LISTEN, now); }
    int active_seen = now < h->active_until, standby_seen = now < h->standby_until, outranked = now < h->speaker_until;
    if (h->preempt && h->state != HS_ACTIVE && active_seen && h->priority > h->active_priority) {
        hsrp_send(h, 1);  /* coup */
        hsrp_to(h, HS_ACTIVE, now);
    } else if (h->state == HS_LISTEN) {  /* a hold time to learn who is there, then speak when a role is free (or weaker) */
        if (now - h->entered >= h->hold && !outranked
            && (!active_seen || !standby_seen || !hsrp_beats(h, h->standby_priority, h->standby)))
            hsrp_to(h, HS_SPEAK, now);
    } else if (h->state == HS_SPEAK) {
        if (now - h->entered >= h->hold) hsrp_to(h, HS_STANDBY, now);
    } else if (h->state == HS_STANDBY && !active_seen) {
        hsrp_to(h, HS_ACTIVE, now);
    }
    if (h->state >= HS_SPEAK && now >= h->next_hello) {
        hsrp_send(h, 0);
        h->next_hello = now + h->hello;
    }
}
static int hsrp_read_state(const char *path, char *text, size_t room) {
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 0;
    ssize_t n = read(fd, text, room - 1); close(fd);
    if (n <= 0) return 0;
    text[n] = 0;
    return 1;
}
static const char *hsrp_field(const char *text, const char *key) {  /* the value after "\nKEY " (or at the start) */
    size_t size = strlen(key);
    for (const char *at = text; at && *at; at = strchr(at, '\n') ? strchr(at, '\n') + 1 : NULL)
        if (!strncmp(at, key, size) && at[size] == ' ') return at + size + 1;
    return "";
}
/* A group of the previous instance: taken back in its state when it is still configured alike, else let go. */
static void hsrp_resume(struct hsrp *h, double now) {
    char path[48], text[1024], vip[16] = "", state[16] = "", vdev[IFNAMSIZ] = "";
    snprintf(path, sizeof(path), "/run/hsrp/%.10s.%d", h->iface, h->group);
    if (!hsrp_read_state(path, text, sizeof(text))) return;
    struct in_addr previous = h->vip;
    sscanf(hsrp_field(text, "vip"), "%15s", vip); sscanf(hsrp_field(text, "state"), "%15s", state);
    sscanf(hsrp_field(text, "vdev"), "%15s", vdev);
    h->changes = (unsigned)atol(hsrp_field(text, "changes")); h->since = atof(hsrp_field(text, "since"));
    int alike = atoi(hsrp_field(text, "version")) == h->version && inet_pton(AF_INET, vip, &previous) == 1
                && previous.s_addr == h->vip.s_addr;
    if (!strcmp(state, "active")) {
        h->macvlan = atoi(hsrp_field(text, "macvlan")); snprintf(h->vdev, sizeof(h->vdev), "%s", vdev);
        if (!alike) { struct hsrp old = *h; old.vip = previous; hsrp_release(&old); h->macvlan = 0; return; }
        h->state = HS_ACTIVE; h->active = h->self; h->active_priority = h->priority;
    } else if (!strcmp(state, "standby") && alike) {
        h->state = HS_STANDBY; h->active_until = now + h->hold;
    } else {
        return;
    }
    h->entered = now; h->next_hello = now;
}
/* State files of groups no longer configured: their address let go (with a resign when they were active), the file gone. */
static void hsrp_tidy(struct hsrp *groups, int count) {
    DIR *folder = opendir("/run/hsrp"); struct dirent *entry;
    while (folder && (entry = readdir(folder))) {
        if (entry->d_name[0] == '.' || strstr(entry->d_name, ".new")) continue;
        int kept = 0;
        for (int i = 0; i < count && !kept; i++) {
            char name[24]; snprintf(name, sizeof(name), "%.10s.%d", groups[i].iface, groups[i].group);
            kept = !strcmp(name, entry->d_name);
        }
        if (kept) continue;
        char path[300], text[1024], state[16] = "", vip[16] = "", auth[17] = "", spec[160];
        snprintf(path, sizeof(path), "/run/hsrp/%.200s", entry->d_name);
        if (hsrp_read_state(path, text, sizeof(text))) {
            struct hsrp old; char iface[IFACE_SIZE] = "";
            sscanf(hsrp_field(text, "interface"), "%10s", iface); sscanf(hsrp_field(text, "state"), "%15s", state);
            sscanf(hsrp_field(text, "vip"), "%15s", vip); sscanf(hsrp_field(text, "auth"), "%16s", auth);
            snprintf(spec, sizeof(spec), "%s/%d/%d/%s/%d/n/3/10/%s", iface, atoi(hsrp_field(text, "group")),
                     atoi(hsrp_field(text, "version")), vip, atoi(hsrp_field(text, "priority")), auth);
            if (!strcmp(state, "active") && hsrp_parse(spec, &old)) {
                old.macvlan = atoi(hsrp_field(text, "macvlan"));
                sscanf(hsrp_field(text, "vdev"), "%15s", old.vdev);
                if (hsrp_port(&old)) { hsrp_open(&old); old.state = HS_ACTIVE; hsrp_send(&old, 2); }
                hsrp_release(&old);
                if (old.fd >= 0) close(old.fd);
            }
        }
        unlink(path);
    }
    if (folder) closedir(folder);
}
static int hsrp(int count, char **specs) {
    static struct hsrp groups[HSRP_GROUPS]; struct pollfd waits[HSRP_GROUPS];
    if (count < 1 || count > HSRP_GROUPS) return 2;
    for (int i = 0; i < count; i++) {
        if (!hsrp_parse(specs[i], &groups[i])) return 2;
        for (int j = 0; j < i; j++)
            if (!strcmp(groups[i].iface, groups[j].iface) && groups[i].group == groups[j].group) return 2;
    }
    mkdir("/run/hsrp", 0755);
    struct sigaction caught; memset(&caught, 0, sizeof(caught)); caught.sa_handler = hsrp_caught;
    sigaction(SIGTERM, &caught, NULL); sigaction(SIGUSR1, &caught, NULL);
    hsrp_tidy(groups, count);
    double now = hsrp_now(), saved = 0;
    for (int i = 0; i < count; i++) { hsrp_port(&groups[i]); hsrp_resume(&groups[i], now); }
    for (;;) {
        if (hsrp_signal == SIGUSR1) return 0;  /* the next instance takes the groups back */
        if (hsrp_signal == SIGTERM) {
            for (int i = 0; i < count; i++) {
                struct hsrp *h = &groups[i];
                if (h->state == HS_ACTIVE) { hsrp_send(h, 2); hsrp_release(h); }
                hsrp_sysctl(h->iface, "arp_ignore", "0"); hsrp_sysctl(h->iface, "arp_announce", "0");
                char path[48]; snprintf(path, sizeof(path), "/run/hsrp/%.10s.%d", h->iface, h->group); unlink(path);
            }
            return 0;
        }
        now = hsrp_now();
        for (int i = 0; i < count; i++) hsrp_tick(&groups[i], now);
        if (now - saved >= 1) { for (int i = 0; i < count; i++) hsrp_save(&groups[i], now); saved = now; }
        for (int i = 0; i < count; i++) { waits[i].fd = groups[i].fd; waits[i].events = POLLIN; waits[i].revents = 0; }
        if (poll(waits, (nfds_t)count, 100) < 0) { if (errno == EINTR) continue; return 1; }
        for (int i = 0; i < count; i++)
            if (groups[i].fd >= 0 && (waits[i].revents & POLLIN)) hsrp_receive(&groups[i], hsrp_now());
    }
}
/* VRRP (IOS « vrrp », RFC 3768: VRRP version 2): this agent's --vrrp mode speaks VRRP on a router's LAN ports. Each argument:
 * IFACE/VRID/VIP/PRIORITY/PREEMPT/ADVERT/AUTH, AUTH in hex (simple text authentication) or - for none. Adverts are IP
 * protocol 112 to 224.0.0.18 with TTL 255, sent every ADVERT seconds by the master, from the virtual MAC 0000.5e00.01NN.
 * The master (highest priority, then highest address; 255 for the router whose own address is the virtual one) holds the
 * virtual address on a macvlan device carrying the virtual MAC, as the HSRP speaker does; a backup takes over when the
 * master down timer (three adverts and a skew of (256 - priority) / 256 s) runs out, or after the skew alone when the master
 * resigns with an advert of priority 0. With preemption (IOS's default) a backup of higher priority ignores a weaker
 * master's adverts and so takes over. State: VRRP_RUN/IFACE.VRID. SIGTERM resigns and removes everything; SIGUSR1 leaves it
 * to the next instance (a configuration change), which takes the groups back in their state. */
#ifndef VRRP_RUN
#define VRRP_RUN "/run/vrrp"  /* tests build the agent with their own folder */
#endif
#define VRRP_GROUPS 16
enum { VR_INIT = 0, VR_BACKUP = 1, VR_MASTER = 2 };
struct vrrp { char iface[IFACE_SIZE], vdev[IFNAMSIZ]; int vrid, priority, preempt, advert, authtype, fd, state, macvlan, owner;
              unsigned changes; struct in_addr vip, self, master; int master_priority, master_advert;
              unsigned char auth[8], mac[6], vmac[6]; double since, next_advert, down_at; };
static volatile sig_atomic_t vrrp_signal;
static void vrrp_caught(int number) { vrrp_signal = number; }
static int vrrp_parse(const char *text, struct vrrp *v) {
    char copy[96], *fields[7], *rest = NULL; int n = 0;  /* strtok_r: the request loop splits with strtok */
    if (strlen(text) >= sizeof(copy)) return 0;
    strcpy(copy, text);
    char *item = strtok_r(copy, "/", &rest);
    while (item && n < 7) { fields[n++] = item; item = strtok_r(NULL, "/", &rest); }
    if (n != 7 || item || !valid_interface(fields[0]) || strncmp(fields[0], "eth", 3)) return 0;
    static const int numeric[] = {1, 3, 5};
    for (int i = 0; i < 3; i++) {
        const char *field = fields[numeric[i]];
        if (!field[0] || strlen(field) > 3 || strspn(field, "0123456789") != strlen(field)) return 0;
    }
    memset(v, 0, sizeof(*v)); v->fd = -1;
    snprintf(v->iface, sizeof(v->iface), "%s", fields[0]);
    v->vrid = atoi(fields[1]); v->priority = atoi(fields[3]); v->advert = atoi(fields[5]);
    if (v->vrid < 1 || v->vrid > 255 || v->priority < 1 || v->priority > 255 || v->advert < 1 || v->advert > 255
        || inet_pton(AF_INET, fields[2], &v->vip) != 1 || strlen(fields[4]) != 1 || !strchr("yn", fields[4][0])) return 0;
    if (strcmp(fields[6], "-")) {
        size_t hex = strlen(fields[6]);
        if (hex < 2 || hex > 16 || hex % 2 || strspn(fields[6], "0123456789abcdef") != hex) return 0;
        for (size_t i = 0; i < hex / 2; i++) { unsigned value; sscanf(fields[6] + 2 * i, "%2x", &value); v->auth[i] = (unsigned char)value; }
        v->authtype = 1;
    }
    v->preempt = fields[4][0] == 'y';
    unsigned char vmac[6] = {0x00, 0x00, 0x5e, 0x00, 0x01, (unsigned char)v->vrid};
    memcpy(v->vmac, vmac, 6);
    v->master_advert = v->advert;
    return 1;
}
/* 1 when the port is up with an address: its MAC and primary address are refreshed. */
static int vrrp_port(struct vrrp *v) {
    struct ifreq query; memset(&query, 0, sizeof(query)); snprintf(query.ifr_name, sizeof(query.ifr_name), "%s", v->iface);
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0), up = 0;
    if (fd < 0) return 0;
    if (ioctl(fd, SIOCGIFFLAGS, &query) == 0 && (query.ifr_flags & IFF_UP) && (query.ifr_flags & IFF_RUNNING)
        && ioctl(fd, SIOCGIFHWADDR, &query) == 0) {
        memcpy(v->mac, query.ifr_hwaddr.sa_data, 6);
        up = ioctl(fd, SIOCGIFADDR, &query) == 0;
        if (up) v->self = ((struct sockaddr_in *)&query.ifr_addr)->sin_addr;
    }
    close(fd);
    v->owner = up && v->self.s_addr == v->vip.s_addr;
    return up;
}
/* Every frame of the port, VRRP's group (01:00:5e:00:00:12) let in. ETH_P_ALL, not ETH_P_IP: while this router is master its
 * macvlan device holds the virtual MAC, and macvlan takes a multicast frame from that MAC (another master's advert) as its
 * own coming back, so an IP-only socket never sees it and two masters would never hear each other. */
static void vrrp_open(struct vrrp *v) {
    if (v->fd >= 0) return;
    int sock = socket(AF_PACKET, SOCK_RAW | SOCK_CLOEXEC, htons(ETH_P_ALL));
    struct sockaddr_ll where; memset(&where, 0, sizeof(where));
    where.sll_family = AF_PACKET; where.sll_protocol = htons(ETH_P_ALL); where.sll_ifindex = (int)if_nametoindex(v->iface);
    if (sock < 0 || !where.sll_ifindex || bind(sock, (struct sockaddr *)&where, sizeof(where))) { if (sock >= 0) close(sock); return; }
    struct packet_mreq group; memset(&group, 0, sizeof(group));
    static const unsigned char all_vrrp[6] = {0x01, 0x00, 0x5e, 0x00, 0x00, 0x12};
    group.mr_ifindex = where.sll_ifindex; group.mr_type = PACKET_MR_MULTICAST; group.mr_alen = 6; memcpy(group.mr_address, all_vrrp, 6);
    setsockopt(sock, SOL_PACKET, PACKET_ADD_MEMBERSHIP, &group, sizeof(group));
    v->fd = sock;
}
static void vrrp_frame(struct vrrp *v, const unsigned char *frame, size_t size, unsigned short protocol) {
    struct sockaddr_ll to; memset(&to, 0, sizeof(to));
    to.sll_family = AF_PACKET; to.sll_protocol = htons(protocol); to.sll_ifindex = (int)if_nametoindex(v->iface);
    to.sll_halen = 6; memcpy(to.sll_addr, frame, 6);
    if (v->fd >= 0 && to.sll_ifindex) sendto(v->fd, frame, size, 0, (struct sockaddr *)&to, sizeof(to));
}
/* One advert at PRIORITY (0: the master resigns), from the virtual MAC while master (the switches learn where it is). */
static void vrrp_send(struct vrrp *v, int priority) {
    unsigned char frame[14 + 20 + 20]; memset(frame, 0, sizeof(frame));
    unsigned char *ip = frame + 14, *p = ip + 20;
    static const unsigned char all_vrrp[6] = {0x01, 0x00, 0x5e, 0x00, 0x00, 0x12};
    memcpy(frame, all_vrrp, 6);
    memcpy(frame + 6, v->state == VR_MASTER && !v->owner ? v->vmac : v->mac, 6);
    frame[12] = 0x08;
    struct in_addr group; inet_pton(AF_INET, "224.0.0.18", &group);
    p[0] = 0x21; p[1] = (unsigned char)v->vrid; p[2] = (unsigned char)priority; p[3] = 1; p[4] = (unsigned char)v->authtype;
    p[5] = (unsigned char)v->advert; memcpy(p + 8, &v->vip, 4);
    if (v->authtype) memcpy(p + 12, v->auth, 8);
    unsigned short sum = hsrp_sum(p, 20, 0);
    p[6] = (unsigned char)(sum >> 8); p[7] = (unsigned char)sum;
    ip[0] = 0x45; ip[1] = 0xc0; ip[3] = 40; ip[8] = 255; ip[9] = 112;
    memcpy(ip + 12, &v->self, 4); memcpy(ip + 16, &group, 4);
    sum = hsrp_sum(ip, 20, 0);
    ip[10] = (unsigned char)(sum >> 8); ip[11] = (unsigned char)sum;
    vrrp_frame(v, frame, sizeof(frame), ETH_P_IP);
}
static void vrrp_garp(struct vrrp *v) {  /* "VIP is at MAC": the hosts and the switches learn it */
    unsigned char frame[42], *arp = frame + 14;
    const unsigned char *mac = v->macvlan ? v->vmac : v->mac;
    memset(frame, 0xff, 6); memcpy(frame + 6, mac, 6); frame[12] = 0x08; frame[13] = 0x06;
    static const unsigned char head[8] = {0, 1, 8, 0, 6, 4, 0, 1};
    memcpy(arp, head, 8); memcpy(arp + 8, mac, 6); memcpy(arp + 14, &v->vip, 4); memset(arp + 18, 0, 6); memcpy(arp + 24, &v->vip, 4);
    vrrp_frame(v, frame, sizeof(frame), ETH_P_ARP);
}
static void vrrp_claim(struct vrrp *v) {
    int lower = (int)if_nametoindex(v->iface);
    v->macvlan = 0; snprintf(v->vdev, sizeof(v->vdev), "-");
    if (!v->owner) {  /* the owner already holds the address on its port */
        snprintf(v->vdev, sizeof(v->vdev), "vrrp%d-%d", lower, v->vrid);
        if (if_nametoindex(v->vdev) || !hsrp_vdev(v->vdev, lower, v->vmac)) {  /* taken back from the previous instance, or made */
            v->macvlan = 1;
            hsrp_sysctl(v->vdev, "rp_filter", "0");
            hsrp_sysctl(v->iface, "arp_ignore", "1");  /* the port itself does not answer for the virtual address */
            hsrp_sysctl(v->iface, "arp_announce", "2");  /* nor asks with it as sender: the hosts keep the virtual MAC */
            hsrp_address(RTM_NEWADDR, (int)if_nametoindex(v->vdev), v->vip);
        } else {
            snprintf(v->vdev, sizeof(v->vdev), "-");
            hsrp_address(RTM_NEWADDR, lower, v->vip);
        }
    }
    vrrp_garp(v); vrrp_garp(v);
}
static void vrrp_release(struct vrrp *v) {
    if (v->macvlan) hsrp_link_delete(v->vdev);
    else if (!v->owner) hsrp_address(RTM_DELADDR, (int)if_nametoindex(v->iface), v->vip);
    v->macvlan = 0;
}
static double vrrp_skew(struct vrrp *v) { return (256.0 - v->priority) / 256.0; }
static double vrrp_down(struct vrrp *v) { return 3.0 * v->master_advert + vrrp_skew(v); }
static void vrrp_save(struct vrrp *v) {
    char path[256], temporary[264], text[512], vip[16], master[16] = "-", auth[17] = "-";
    snprintf(path, sizeof(path), VRRP_RUN "/%.10s.%d", v->iface, v->vrid);
    snprintf(temporary, sizeof(temporary), "%.255s.new", path);
    inet_ntop(AF_INET, &v->vip, vip, sizeof(vip));
    if (v->state == VR_MASTER) strcpy(master, "local");
    else if (v->state == VR_BACKUP && v->master.s_addr) inet_ntop(AF_INET, &v->master, master, sizeof(master));
    if (v->authtype) for (int i = 0; i < 8; i++) snprintf(auth + 2 * i, 3, "%02x", v->auth[i]);
    static const char *names[3] = {"init", "backup", "master"};
    int n = snprintf(text, sizeof(text),
        "interface %s\ngroup %d\nvip %s\nvdev %s\nmacvlan %d\nstate %s\npriority %d\npreempt %c\nadvert %d\nauth %s\nchanges %u\n"
        "since %.1f\nmaster %s %d %d\ndown %.1f\nnext %.1f\n",
        v->iface, v->vrid, vip, v->state == VR_MASTER ? v->vdev : "-", v->macvlan, names[v->state], v->priority, v->preempt ? 'y' : 'n',
        v->advert, auth, v->changes, v->since, master, v->state == VR_MASTER ? v->priority : v->master_priority,
        v->state == VR_MASTER ? v->advert : v->master_advert, v->state == VR_BACKUP ? v->down_at : 0.0, v->next_advert);
    int fd = open(temporary, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (fd < 0 || n <= 0) { if (fd >= 0) close(fd); return; }
    ssize_t written = write(fd, text, (size_t)n); close(fd);
    if (written == n) rename(temporary, path);
}
static void vrrp_to(struct vrrp *v, int state, double now) {
    if (v->state == state) return;
    if (v->state == VR_MASTER) vrrp_release(v);
    v->state = state; v->since = now; v->changes++;
    if (state == VR_MASTER) { vrrp_claim(v); v->next_advert = now; }  /* the first advert at once */
    if (state == VR_BACKUP) v->down_at = now + vrrp_down(v);
    if (state != VR_BACKUP) v->master.s_addr = 0;
    vrrp_save(v);
}
static void vrrp_receive(struct vrrp *v, double now) {
    unsigned char frame[1600]; struct sockaddr_ll from; socklen_t size = sizeof(from);
    ssize_t n = recvfrom(v->fd, frame, sizeof(frame), 0, (struct sockaddr *)&from, &size);
    if (n < 14 + 20 + 20 || from.sll_pkttype == PACKET_OUTGOING || frame[12] != 0x08 || frame[13] != 0x00) return;
    const unsigned char *ip = frame + 14;
    size_t header = (size_t)(ip[0] & 0x0f) * 4;
    if ((ip[0] >> 4) != 4 || header < 20 || ip[9] != 112 || ip[8] != 255 || (size_t)n < 14 + header + 20) return;  /* TTL 255 only */
    struct in_addr source; memcpy(&source, ip + 12, 4);
    if (source.s_addr == v->self.s_addr) return;
    const unsigned char *p = ip + header;
    size_t message = 8 + 4 * (size_t)p[3] + 8;
    if (p[0] != 0x21 || p[1] != v->vrid || p[3] < 1 || (size_t)n < 14 + header + message || hsrp_sum(p, message, 0)) return;
    if (p[4] != v->authtype || (v->authtype && memcmp(p + 8 + 4 * p[3], v->auth, 8))) return;  /* another group's password */
    int priority = p[2];
    double skew = vrrp_skew(v);
    if (v->state == VR_BACKUP) {
        if (priority == 0) { v->down_at = now + skew; return; }  /* the master resigned: take over after the skew */
        if (!v->preempt || priority >= v->priority) {
            v->master = source; v->master_priority = priority; v->master_advert = p[5] ? p[5] : v->advert;
            v->down_at = now + vrrp_down(v);
        }  /* else a weaker master: with preemption its adverts are ignored, and the timer runs out */
    } else if (v->state == VR_MASTER) {
        if (priority == 0) { vrrp_send(v, v->priority); v->next_advert = now + v->advert; return; }
        if (priority > v->priority || (priority == v->priority && ntohl(source.s_addr) > ntohl(v->self.s_addr))) {
            vrrp_to(v, VR_BACKUP, now);
            v->master = source; v->master_priority = priority; v->master_advert = p[5] ? p[5] : v->advert;
            v->down_at = now + vrrp_down(v);
        }
    }
}
static void vrrp_tick(struct vrrp *v, double now) {
    if (!vrrp_port(v)) {  /* port down or without its address: Init, as IOS shows it */
        vrrp_to(v, VR_INIT, now);
        if (v->fd >= 0) { close(v->fd); v->fd = -1; }
        return;
    }
    vrrp_open(v);
    if (v->fd < 0) return;
    if (v->owner) v->priority = 255;
    if (v->state == VR_INIT) {
        v->master_advert = v->advert;
        vrrp_to(v, v->priority == 255 ? VR_MASTER : VR_BACKUP, now);
    } else if (v->state == VR_BACKUP && now >= v->down_at) {
        vrrp_to(v, VR_MASTER, now);
    }
    if (v->state == VR_MASTER && now >= v->next_advert) {
        vrrp_send(v, v->priority);
        v->next_advert = now + v->advert;
    }
}
/* A group of the previous instance: taken back in its state when it is still configured alike, else let go. */
static void vrrp_resume(struct vrrp *v, double now) {
    char path[256], text[512], vip[16] = "", state[16] = "", vdev[IFNAMSIZ] = "";
    snprintf(path, sizeof(path), VRRP_RUN "/%.10s.%d", v->iface, v->vrid);
    if (!hsrp_read_state(path, text, sizeof(text))) return;
    struct in_addr previous = v->vip;
    sscanf(hsrp_field(text, "vip"), "%15s", vip); sscanf(hsrp_field(text, "state"), "%15s", state);
    sscanf(hsrp_field(text, "vdev"), "%15s", vdev);
    v->changes = (unsigned)atol(hsrp_field(text, "changes")); v->since = atof(hsrp_field(text, "since"));
    int alike = inet_pton(AF_INET, vip, &previous) == 1 && previous.s_addr == v->vip.s_addr;
    if (!strcmp(state, "master")) {
        v->macvlan = atoi(hsrp_field(text, "macvlan")); snprintf(v->vdev, sizeof(v->vdev), "%s", vdev);
        if (!alike) { struct vrrp old = *v; old.vip = previous; vrrp_release(&old); v->macvlan = 0; return; }
        v->state = VR_MASTER; v->next_advert = now;
    } else if (!strcmp(state, "backup") && alike) {
        v->state = VR_BACKUP; v->down_at = now + vrrp_down(v);
    }
}
/* State files of groups no longer configured: their address let go (with a priority-0 advert when they were master). */
static void vrrp_tidy(struct vrrp *groups, int count) {
    DIR *folder = opendir(VRRP_RUN); struct dirent *entry;
    while (folder && (entry = readdir(folder))) {
        if (entry->d_name[0] == '.' || strstr(entry->d_name, ".new")) continue;
        int kept = 0;
        for (int i = 0; i < count && !kept; i++) {
            char name[24]; snprintf(name, sizeof(name), "%.10s.%d", groups[i].iface, groups[i].vrid);
            kept = !strcmp(name, entry->d_name);
        }
        if (kept) continue;
        char path[300], text[512], state[16] = "", vip[16] = "", auth[17] = "", spec[96];
        snprintf(path, sizeof(path), VRRP_RUN "/%.200s", entry->d_name);
        if (hsrp_read_state(path, text, sizeof(text))) {
            struct vrrp old; char iface[IFACE_SIZE] = "";
            sscanf(hsrp_field(text, "interface"), "%10s", iface); sscanf(hsrp_field(text, "state"), "%15s", state);
            sscanf(hsrp_field(text, "vip"), "%15s", vip); sscanf(hsrp_field(text, "auth"), "%16s", auth);
            snprintf(spec, sizeof(spec), "%s/%d/%s/%d/n/%d/%s", iface, atoi(hsrp_field(text, "group")), vip,
                     atoi(hsrp_field(text, "priority")), atoi(hsrp_field(text, "advert")) ? atoi(hsrp_field(text, "advert")) : 1, auth);
            if (!strcmp(state, "master") && vrrp_parse(spec, &old)) {
                old.macvlan = atoi(hsrp_field(text, "macvlan"));
                sscanf(hsrp_field(text, "vdev"), "%15s", old.vdev);
                if (vrrp_port(&old)) { vrrp_open(&old); old.state = VR_MASTER; vrrp_send(&old, 0); }
                vrrp_release(&old);
                if (old.fd >= 0) close(old.fd);
            }
        }
        unlink(path);
    }
    if (folder) closedir(folder);
}
static int vrrp(int count, char **specs) {
    static struct vrrp groups[VRRP_GROUPS]; struct pollfd waits[VRRP_GROUPS];
    if (count < 1 || count > VRRP_GROUPS) return 2;
    for (int i = 0; i < count; i++) {
        if (!vrrp_parse(specs[i], &groups[i])) return 2;
        for (int j = 0; j < i; j++)
            if (!strcmp(groups[i].iface, groups[j].iface) && groups[i].vrid == groups[j].vrid) return 2;
    }
    mkdir(VRRP_RUN, 0755);
    struct sigaction caught; memset(&caught, 0, sizeof(caught)); caught.sa_handler = vrrp_caught;
    sigaction(SIGTERM, &caught, NULL); sigaction(SIGUSR1, &caught, NULL);
    vrrp_tidy(groups, count);
    double now = hsrp_now(), saved = 0;
    for (int i = 0; i < count; i++) { vrrp_port(&groups[i]); vrrp_resume(&groups[i], now); }
    for (;;) {
        if (vrrp_signal == SIGUSR1) return 0;  /* the next instance takes the groups back */
        if (vrrp_signal == SIGTERM) {
            for (int i = 0; i < count; i++) {
                struct vrrp *v = &groups[i];
                if (v->state == VR_MASTER) { vrrp_send(v, 0); vrrp_release(v); }
                hsrp_sysctl(v->iface, "arp_ignore", "0"); hsrp_sysctl(v->iface, "arp_announce", "0");
                char path[256]; snprintf(path, sizeof(path), VRRP_RUN "/%.10s.%d", v->iface, v->vrid); unlink(path);
            }
            return 0;
        }
        now = hsrp_now();
        for (int i = 0; i < count; i++) vrrp_tick(&groups[i], now);
        if (now - saved >= 1) { for (int i = 0; i < count; i++) vrrp_save(&groups[i]); saved = now; }
        for (int i = 0; i < count; i++) { waits[i].fd = groups[i].fd; waits[i].events = POLLIN; waits[i].revents = 0; }
        if (poll(waits, (nfds_t)count, 100) < 0) { if (errno == EINTR) continue; return 1; }
        for (int i = 0; i < count; i++)
            if (groups[i].fd >= 0 && (waits[i].revents & POLLIN)) vrrp_receive(&groups[i], hsrp_now());
    }
}
/* Server services of a host or router guest (one --services daemon): an authoritative DNS server for the lab's own
 * names (A and CNAME records, PTR from the A records), an NTP server (SNTP replies at a given stratum, as IOS « ntp
 * master » or a server's NTP service), a Syslog collector (UDP 514, the last messages kept), and an NTP client that
 * keeps the offset to one server (IOS « ntp server »). The guest clock is never set: the guest already runs the host's
 * time; the client measures and reports the association. State in /run/services.state, messages in /run/syslog.log. */
#ifndef SERVICES_RUN
#define SERVICES_RUN "/run"  /* tests build the agent with their own folder */
#endif
#ifndef AGENT_PROGRAM
#define AGENT_PROGRAM "/sbin/network-labs-agent"
#endif
#define SERVICE_RECORDS 64
#define SYSLOG_KEEP 100
struct service_record { char name[96], value[96]; int cname; };
struct services { int dns, ntp, syslog, tftp, records; struct service_record record[SERVICE_RECORDS]; struct in_addr sync; };
static volatile sig_atomic_t services_signal;
static void services_caught(int number) { services_signal = number; }
static int valid_dns_name(const char *name) {
    size_t length = strlen(name), label = 0;
    if (!length || length > 90 || name[0] == '.' || name[0] == '-' || name[length - 1] == '.' || name[length - 1] == '-') return 0;
    for (size_t i = 0; i < length; i++) {
        char c = name[i];
        if (c == '.') { if (!label) return 0; label = 0; continue; }
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' || c == '_')) return 0;
        if (++label > 63) return 0;
    }
    return 1;
}
/* Tokens: dns, a:NAME=IPV4, cname:ALIAS=NAME, ntp:STRATUM (1..15), syslog, sync:IPV4 (the NTP client's server). */
static int services_parse(int count, char **tokens, struct services *s) {
    memset(s, 0, sizeof(*s));
    for (int i = 0; i < count; i++) {
        const char *t = tokens[i];
        if (!strcmp(t, "dns")) { s->dns = 1; continue; }
        if (!strcmp(t, "syslog")) { s->syslog = 1; continue; }
        if (!strcmp(t, "tftp")) { s->tftp = 1; continue; }
        if (!strncmp(t, "ntp:", 4)) {
            const char *v = t + 4;
            if (!v[0] || strspn(v, "0123456789") != strlen(v) || strlen(v) > 2 || atoi(v) < 1 || atoi(v) > 15) return 0;
            s->ntp = atoi(v); continue;
        }
        if (!strncmp(t, "sync:", 5)) { if (inet_pton(AF_INET, t + 5, &s->sync) != 1) return 0; continue; }
        int cname = !strncmp(t, "cname:", 6);
        if (!cname && strncmp(t, "a:", 2)) return 0;
        const char *body = t + (cname ? 6 : 2), *equals = strchr(body, '=');
        if (!equals || s->records >= SERVICE_RECORDS || (size_t)(equals - body) >= sizeof(s->record[0].name)
            || strlen(equals + 1) >= sizeof(s->record[0].value)) return 0;
        struct service_record *r = &s->record[s->records];
        memcpy(r->name, body, (size_t)(equals - body)); r->name[equals - body] = 0;
        snprintf(r->value, sizeof(r->value), "%s", equals + 1);
        struct in_addr check;
        if (!valid_dns_name(r->name) || (cname ? !valid_dns_name(r->value) : inet_pton(AF_INET, r->value, &check) != 1)) return 0;
        r->cname = cname; s->records++;
    }
    return s->dns || s->ntp || s->syslog || s->tftp || s->sync.s_addr;
}
/* TFTP (RFC 1350): files of SERVICES_RUN/tftp, 64 KiB at most, plain names; one child per transfer, as tftpd does. */
#define TFTP_LIMIT 65536
static int valid_file(const char *name) {
    size_t length = strlen(name);
    return length >= 1 && length <= 64 && name[0] != '.' && strspn(name, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-") == length;
}
static void tftp_error(int fd, int code, const char *text) {
    unsigned char packet[128] = {0, 5, 0, (unsigned char)code}; size_t length = strlen(text) < 100 ? strlen(text) : 100;
    memcpy(packet + 4, text, length); packet[4 + length] = 0;
    (void)send(fd, packet, 5 + length, 0);
}
/* Wait for a packet of OPCODE (and block) on a connected socket: its length, or -1 after the retries. */
static ssize_t tftp_wait(int fd, unsigned char *in, size_t room, int opcode, unsigned block, const unsigned char *resend, size_t resend_size) {
    for (int attempt = 0; attempt < 5; attempt++) {
        struct pollfd wait = {fd, POLLIN, 0};
        while (poll(&wait, 1, 1000) > 0) {
            ssize_t n = recv(fd, in, room, 0);
            if (n >= 4 && in[1] == 5) return -1;  /* the peer's ERROR */
            if (n >= 4 && in[0] == 0 && in[1] == opcode && ((unsigned)in[2] << 8 | in[3]) == (block & 0xffff)) return n;
        }
        if (resend && send(fd, resend, resend_size, 0) < 0) return -1;
    }
    return -1;
}
static void tftp_serve(const unsigned char *request, size_t size, struct sockaddr_in peer) {
    if (fork() != 0) return;
    char name[80] = {0}, mode[16] = {0}; size_t at = 2, used = 0;
    while (at < size && request[at] && used < sizeof(name) - 1) name[used++] = (char)request[at++];
    at++; used = 0;
    while (at < size && request[at] && used < sizeof(mode) - 1) mode[used++] = (char)tolower(request[at++]);
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    if (fd < 0 || connect(fd, (struct sockaddr *)&peer, sizeof(peer))) _exit(1);
    if (!valid_file(name) || (strcmp(mode, "octet") && strcmp(mode, "netascii"))) { tftp_error(fd, 2, "Access violation"); _exit(0); }
    char path[300]; snprintf(path, sizeof(path), SERVICES_RUN "/tftp/%.64s", name);
    unsigned char in[600], out[516];
    if (request[1] == 1) {  /* RRQ: the file, 512 bytes a block */
        int file = open(path, O_RDONLY | O_CLOEXEC);
        if (file < 0) { tftp_error(fd, 1, "File not found"); _exit(0); }
        for (unsigned block = 1;; block++) {
            ssize_t n = read(file, out + 4, 512);
            if (n < 0) { tftp_error(fd, 0, "Read error"); _exit(1); }
            out[0] = 0; out[1] = 3; out[2] = (unsigned char)(block >> 8); out[3] = (unsigned char)block;
            if (send(fd, out, (size_t)n + 4, 0) < 0 || tftp_wait(fd, in, sizeof(in), 4, block, out, (size_t)n + 4) < 0) _exit(1);
            if (n < 512) _exit(0);
        }
    }
    /* WRQ: ACK 0, then the blocks into NAME.part, renamed once complete */
    char part[320]; snprintf(part, sizeof(part), "%s.part", path);
    int file = open(part, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (file < 0) { tftp_error(fd, 2, "Access violation"); _exit(0); }
    unsigned char ack[4] = {0, 4, 0, 0}; size_t total = 0;
    if (send(fd, ack, 4, 0) < 0) _exit(1);
    for (unsigned block = 1;; block++) {
        ssize_t n = tftp_wait(fd, in, sizeof(in), 3, block, ack, 4);
        if (n < 0) { unlink(part); _exit(1); }
        total += (size_t)n - 4;
        if (total > TFTP_LIMIT) { tftp_error(fd, 3, "Disk full or allocation exceeded"); unlink(part); _exit(0); }
        if (write(file, in + 4, (size_t)n - 4) != n - 4) { tftp_error(fd, 3, "Disk full or allocation exceeded"); unlink(part); _exit(0); }
        ack[2] = (unsigned char)(block >> 8); ack[3] = (unsigned char)block;
        if (send(fd, ack, 4, 0) < 0) _exit(1);
        if (n - 4 < 512) { close(file); rename(part, path); _exit(0); }
    }
}
static double ntp_unix(const unsigned char *p) {  /* an NTP timestamp (seconds since 1900) as Unix seconds */
    unsigned long seconds = ((unsigned long)p[0] << 24) | ((unsigned long)p[1] << 16) | ((unsigned long)p[2] << 8) | p[3];
    unsigned long fraction = ((unsigned long)p[4] << 24) | ((unsigned long)p[5] << 16) | ((unsigned long)p[6] << 8) | p[7];
    return (double)seconds - 2208988800.0 + (double)fraction / 4294967296.0;
}
static void ntp_stamp(unsigned char *p, double unix_seconds) {
    double ntp = unix_seconds + 2208988800.0;
    unsigned long seconds = (unsigned long)ntp, fraction = (unsigned long)((ntp - (double)seconds) * 4294967296.0);
    for (int i = 0; i < 4; i++) { p[i] = (unsigned char)(seconds >> (24 - 8 * i)); p[4 + i] = (unsigned char)(fraction >> (24 - 8 * i)); }
}
static double wall_now(void) { struct timespec t; clock_gettime(CLOCK_REALTIME, &t); return (double)t.tv_sec + (double)t.tv_nsec / 1e9; }
static int udp_bound(unsigned short port) {
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0), on = 1;
    struct sockaddr_in local = {.sin_family = AF_INET, .sin_port = htons(port), .sin_addr.s_addr = htonl(INADDR_ANY)};
    if (fd < 0) return -1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on));
    if (bind(fd, (struct sockaddr *)&local, sizeof(local))) { close(fd); return -1; }
    return fd;
}
/* A query name read from a DNS message (labels, no compression in a question), lower case, dotted. */
static int dns_qname(const unsigned char *m, size_t size, size_t *at, char *out, size_t room) {
    size_t used = 0;
    while (*at < size) {
        unsigned length = m[(*at)++];
        if (!length) { out[used] = 0; return used > 0; }
        if (length > 63 || *at + length > size || used + length + 2 > room) return 0;
        if (used) out[used++] = '.';
        for (unsigned i = 0; i < length; i++) { char c = (char)m[(*at)++]; out[used++] = (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c; }
    }
    return 0;
}
static size_t dns_put_name(unsigned char *out, size_t used, size_t room, const char *name) {
    const char *label = name;
    while (*label) {
        const char *dot = strchr(label, '.'); size_t length = dot ? (size_t)(dot - label) : strlen(label);
        if (used + length + 2 > room) return 0;
        out[used++] = (unsigned char)length; memcpy(out + used, label, length); used += length;
        label += length + (dot ? 1 : 0);
    }
    out[used++] = 0; return used;
}
static int same_name(const char *a, const char *b) { return !strcasecmp(a, b); }
static size_t dns_answer(const struct services *s, const unsigned char *query, size_t size, unsigned char *out, size_t room) {
    if (size < 17 || (query[2] & 0x80) || (query[2] & 0x78) || query[4] || query[5] != 1) return 0;
    size_t at = 12; char name[256];
    if (!dns_qname(query, size, &at, name, sizeof(name)) || at + 4 > size) return 0;
    unsigned qtype = ((unsigned)query[at] << 8) | query[at + 1], qclass = ((unsigned)query[at + 2] << 8) | query[at + 3];
    at += 4;
    memcpy(out, query, at); memset(out + 4, 0, 8); out[5] = 1;
    out[2] = 0x84 | (query[2] & 0x01); out[3] = 0;  /* response, authoritative, recursion desired copied; no recursion */
    size_t used = at; int answers = 0, known = 0;
    char target[256]; snprintf(target, sizeof(target), "%s", name);
    /* An alias first: its CNAME, then the target's addresses when they are local. */
    for (int i = 0; i < s->records; i++) if (s->record[i].cname && same_name(s->record[i].name, name)) {
        known = 1;
        if (qtype == 5 || qtype == 1 || qtype == 255) {
            unsigned char head[10] = {0, 5, 0, 1, 0, 0, 0x0e, 0x10, 0, 0};
            if (used + 12 + 100 > room) break;
            out[used++] = 0xc0; out[used++] = 12; memcpy(out + used, head, 10); used += 10;
            size_t start = used; used = dns_put_name(out, used, room, s->record[i].value);
            if (!used) return 0;
            out[start - 2] = (unsigned char)((used - start) >> 8); out[start - 1] = (unsigned char)(used - start);
            answers++;
        }
        snprintf(target, sizeof(target), "%s", s->record[i].value);
        break;
    }
    for (int i = 0; i < s->records; i++) if (!s->record[i].cname && same_name(s->record[i].name, target)) {
        known = 1;
        if ((qtype == 1 || qtype == 255) && qclass == 1 && used + 16 <= room) {
            unsigned char head[10] = {0, 1, 0, 1, 0, 0, 0x0e, 0x10, 0, 4};
            out[used++] = 0xc0; out[used++] = 12; memcpy(out + used, head, 10); used += 10;
            struct in_addr address; inet_pton(AF_INET, s->record[i].value, &address);
            memcpy(out + used, &address, 4); used += 4; answers++;
        }
    }
    /* d.c.b.a.in-addr.arpa: the names whose A record holds a.b.c.d. */
    unsigned a, b, c, d; char tail[32];
    if (!known && sscanf(name, "%u.%u.%u.%u.%31s", &d, &c, &b, &a, tail) == 5 && !strcmp(tail, "in-addr.arpa") && a < 256 && b < 256 && c < 256 && d < 256) {
        char address[16]; snprintf(address, sizeof(address), "%u.%u.%u.%u", a, b, c, d);
        for (int i = 0; i < s->records; i++) if (!s->record[i].cname && !strcmp(s->record[i].value, address)) {
            known = 1;
            if (qtype != 12 && qtype != 255) continue;
            unsigned char head[10] = {0, 12, 0, 1, 0, 0, 0x0e, 0x10, 0, 0};
            if (used + 12 + 100 > room) break;
            out[used++] = 0xc0; out[used++] = 12; memcpy(out + used, head, 10); used += 10;
            size_t start = used; used = dns_put_name(out, used, room, s->record[i].name);
            if (!used) return 0;
            out[start - 2] = (unsigned char)((used - start) >> 8); out[start - 1] = (unsigned char)(used - start);
            answers++;
        }
    }
    if (!known) out[3] = 3;  /* NXDOMAIN */
    out[6] = (unsigned char)(answers >> 8); out[7] = (unsigned char)answers;
    return used;
}
struct service_counts { unsigned long dns, ntp, syslog, tftp; int synced, sync_stratum; double offset, delay, synced_at; char refid[16]; };
static char syslog_ring[SYSLOG_KEEP][300]; static int syslog_next, syslog_kept;
static void services_save(const struct services *s, const struct service_counts *k) {
    char text[1024]; int n = snprintf(text, sizeof(text), "dns %d records %d queries %lu\nntp %d requests %lu\nsyslog %d messages %lu\ntftp %d transfers %lu\n",
                                      s->dns, s->records, k->dns, s->ntp, k->ntp, s->syslog, k->syslog, s->tftp, k->tftp);
    if (s->sync.s_addr) {
        char server[16]; inet_ntop(AF_INET, &s->sync, server, sizeof(server));
        n += snprintf(text + n, sizeof(text) - (size_t)n, "sync %s synced %d stratum %d offset %.6f delay %.6f refid %s age %.0f\n", server,
                      k->synced, k->sync_stratum, k->offset, k->delay, k->refid[0] ? k->refid : "-", k->synced ? wall_now() - k->synced_at : -1.0);
    }
    int fd = open(SERVICES_RUN "/services.state.new", O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (fd < 0) return;
    if (write(fd, text, (size_t)n) == n) { close(fd); rename(SERVICES_RUN "/services.state.new", SERVICES_RUN "/services.state"); } else close(fd);
}
static void syslog_keep(const char *source, const unsigned char *data, size_t size) {
    char message[240]; size_t used = 0;
    for (size_t i = 0; i < size && used < sizeof(message) - 1; i++) {
        unsigned char c = data[i];
        if (c == '\n' || c == '\r' || c == 0) continue;
        message[used++] = (c < 32 || c > 126) ? '?' : (char)c;
    }
    message[used] = 0;
    snprintf(syslog_ring[syslog_next], sizeof(syslog_ring[0]), "%.0f %s %s", wall_now(), source, message);
    syslog_next = (syslog_next + 1) % SYSLOG_KEEP; if (syslog_kept < SYSLOG_KEEP) syslog_kept++;
    int fd = open(SERVICES_RUN "/syslog.log.new", O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (fd < 0) return;
    for (int i = 0; i < syslog_kept; i++) {
        const char *line = syslog_ring[(syslog_next - syslog_kept + i + SYSLOG_KEEP) % SYSLOG_KEEP];
        if (write(fd, line, strlen(line)) < 0 || write(fd, "\n", 1) < 0) break;
    }
    close(fd); rename(SERVICES_RUN "/syslog.log.new", SERVICES_RUN "/syslog.log");
}
static void ntp_request(int fd, struct in_addr server, double *sent, unsigned char *stamp) {
    unsigned char packet[48] = {0x23};  /* version 4, mode 3 (client) */
    *sent = wall_now(); ntp_stamp(packet + 40, *sent); memcpy(stamp, packet + 40, 8);
    struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = htons(123), .sin_addr = server};
    (void)sendto(fd, packet, sizeof(packet), 0, (struct sockaddr *)&to, sizeof(to));
}
static int services(int count, char **tokens) {
    static struct services s; struct service_counts k; memset(&k, 0, sizeof(k));
    if (!services_parse(count, tokens, &s)) return 2;
    struct sigaction caught; memset(&caught, 0, sizeof(caught)); caught.sa_handler = services_caught;
    sigaction(SIGTERM, &caught, NULL);
    int dns = s.dns ? udp_bound(53) : -1, ntp = s.ntp ? udp_bound(123) : -1, logs = s.syslog ? udp_bound(514) : -1;
    int tftp = s.tftp ? udp_bound(69) : -1;
    if (s.tftp) { mkdir(SERVICES_RUN "/tftp", 0755); signal(SIGCHLD, SIG_IGN); }  /* transfers: children, reaped by the kernel */
    int client = s.sync.s_addr ? socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0) : -1;
    if ((s.dns && dns < 0) || (s.ntp && ntp < 0) || (s.syslog && logs < 0) || (s.tftp && tftp < 0)) return 1;
    unlink(SERVICES_RUN "/syslog.log");
    double next_poll = wall_now() + 1, sent = 0, last_reply = 0, saved = 0; unsigned char stamp[8] = {0};
    for (;;) {
        if (services_signal == SIGTERM) { unlink(SERVICES_RUN "/services.state"); return 0; }
        double now = wall_now();
        if (client >= 0 && now >= next_poll) {
            ntp_request(client, s.sync, &sent, stamp);
            next_poll = now + (k.synced ? 16 : 4);
            if (k.synced && now - last_reply > 64) k.synced = 0;
        }
        if (now - saved >= 1) { services_save(&s, &k); saved = now; }
        struct pollfd waits[5] = {{dns, POLLIN, 0}, {ntp, POLLIN, 0}, {logs, POLLIN, 0}, {client, POLLIN, 0}, {tftp, POLLIN, 0}};
        if (poll(waits, 5, 200) < 0) { if (errno == EINTR) continue; return 1; }
        unsigned char in[1500], out[1500]; struct sockaddr_in from; socklen_t size = sizeof(from);
        if (waits[0].revents & POLLIN) {
            ssize_t n = recvfrom(dns, in, sizeof(in), 0, (struct sockaddr *)&from, &size);
            size_t length = n > 0 ? dns_answer(&s, in, (size_t)n, out, sizeof(out)) : 0;
            if (length) { (void)sendto(dns, out, length, 0, (struct sockaddr *)&from, size); k.dns++; }
        }
        size = sizeof(from);
        if (waits[1].revents & POLLIN) {
            double received = wall_now();
            ssize_t n = recvfrom(ntp, in, sizeof(in), 0, (struct sockaddr *)&from, &size);
            if (n >= 48 && (in[0] & 7) == 3) {
                memset(out, 0, 48);
                out[0] = (unsigned char)((in[0] & 0x38) | 4); out[1] = (unsigned char)s.ntp; out[2] = in[2]; out[3] = (unsigned char)-20;
                out[9] = 1;  /* root dispersion: 1/65536 s */
                if (s.ntp == 1) memcpy(out + 12, "LOCL", 4); else { out[12] = 127; out[13] = 127; out[14] = 1; out[15] = 0; }
                ntp_stamp(out + 16, received); memcpy(out + 24, in + 40, 8); ntp_stamp(out + 32, received); ntp_stamp(out + 40, wall_now());
                (void)sendto(ntp, out, 48, 0, (struct sockaddr *)&from, size); k.ntp++;
            }
        }
        size = sizeof(from);
        if (waits[2].revents & POLLIN) {
            ssize_t n = recvfrom(logs, in, sizeof(in) - 1, 0, (struct sockaddr *)&from, &size);
            if (n > 0) { char source[16]; inet_ntop(AF_INET, &from.sin_addr, source, sizeof(source)); syslog_keep(source, in, (size_t)n); k.syslog++; }
        }
        size = sizeof(from);
        if (waits[4].revents & POLLIN) {
            ssize_t n = recvfrom(tftp, in, sizeof(in), 0, (struct sockaddr *)&from, &size);
            if (n >= 4 && in[0] == 0 && (in[1] == 1 || in[1] == 2)) { tftp_serve(in, (size_t)n, from); k.tftp++; }
        }
        size = sizeof(from);
        if (waits[3].revents & POLLIN) {
            double arrived = wall_now();
            ssize_t n = recvfrom(client, in, sizeof(in), 0, (struct sockaddr *)&from, &size);
            if (n >= 48 && from.sin_addr.s_addr == s.sync.s_addr && (in[0] & 7) == 4 && in[1] >= 1 && in[1] <= 15
                && !memcmp(in + 24, stamp, 8)) {
                double t1 = sent, t2 = ntp_unix(in + 32), t3 = ntp_unix(in + 40), t4 = arrived;
                k.offset = ((t2 - t1) + (t3 - t4)) / 2; k.delay = (t4 - t1) - (t3 - t2); k.sync_stratum = in[1];
                if (in[1] == 1) snprintf(k.refid, sizeof(k.refid), "%.4s", (const char *)in + 12);
                else inet_ntop(AF_INET, in + 12, k.refid, sizeof(k.refid));
                k.synced = 1; k.synced_at = last_reply = arrived; next_poll = arrived + 16;
            }
        }
    }
}
/* One DNS query from this guest (A, or PTR for an address), as nslookup asks: "A a.b.c.d" / "CNAME name" / "PTR name"
 * lines, or code 1 with "NXDOMAIN", "SERVFAIL"... or "timeout". */
static void resolve(int output, const char *server_text, const char *name) {
    struct in_addr server, as_address; char qname[128];
    if (inet_pton(AF_INET, name, &as_address) == 1) {
        unsigned char *o = (unsigned char *)&as_address;
        snprintf(qname, sizeof(qname), "%u.%u.%u.%u.in-addr.arpa", o[3], o[2], o[1], o[0]);
    } else snprintf(qname, sizeof(qname), "%s", name);
    if (inet_pton(AF_INET, server_text, &server) != 1 || !valid_dns_name(qname)) { reply(output, 2, "invalid resolve", 15); return; }
    int ptr = strstr(qname, ".in-addr.arpa") != NULL;
    unsigned char query[300] = {0}; unsigned short id = (unsigned short)(getpid() ^ (int)(wall_now() * 1000));
    query[0] = (unsigned char)(id >> 8); query[1] = (unsigned char)id; query[2] = 1; query[5] = 1;
    size_t used = dns_put_name(query, 12, sizeof(query) - 4, qname);
    query[used++] = 0; query[used++] = ptr ? 12 : 1; query[used++] = 0; query[used++] = 1;
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = htons(53), .sin_addr = server};
    if (fd < 0 || connect(fd, (struct sockaddr *)&to, sizeof(to))) { if (fd >= 0) close(fd); reply(output, 1, "unreachable", 11); return; }
    unsigned char answer[1500]; ssize_t n = -1;
    for (int attempt = 0; attempt < 2 && n < 12; attempt++) {
        if (send(fd, query, used, 0) < 0) break;
        struct pollfd wait = {fd, POLLIN, 0};
        while (poll(&wait, 1, 1500) > 0) {
            n = recv(fd, answer, sizeof(answer), 0);
            if (n >= 12 && answer[0] == query[0] && answer[1] == query[1]) break;
            n = -1;
        }
    }
    close(fd);
    if (n < 12) { reply(output, 1, "timeout", 7); return; }
    int rcode = answer[3] & 15;
    if (rcode) { const char *names[] = {"NOERROR", "FORMERR", "SERVFAIL", "NXDOMAIN", "NOTIMP", "REFUSED"};
        const char *text = rcode < 6 ? names[rcode] : "ERROR"; reply(output, 1, text, strlen(text)); return; }
    size_t at = 12; char skip[256];
    for (int q = 0; q < ((answer[4] << 8) | answer[5]); q++) { if (!dns_qname(answer, (size_t)n, &at, skip, sizeof(skip))) { reply(output, 1, "FORMERR", 7); return; } at += 4; }
    char text[2048]; size_t length = 0; int count = (answer[6] << 8) | answer[7];
    for (int i = 0; i < count && at + 12 <= (size_t)n; i++) {
        if ((answer[at] & 0xc0) == 0xc0) at += 2; else if (!dns_qname(answer, (size_t)n, &at, skip, sizeof(skip))) break;
        if (at + 10 > (size_t)n) break;
        unsigned type = ((unsigned)answer[at] << 8) | answer[at + 1], rdlength = ((unsigned)answer[at + 8] << 8) | answer[at + 9];
        at += 10;
        if (at + rdlength > (size_t)n) break;
        if (type == 1 && rdlength == 4) {
            char address[16]; inet_ntop(AF_INET, answer + at, address, sizeof(address));
            length += (size_t)snprintf(text + length, sizeof(text) - length, "A %s\n", address);
        } else if (type == 5 || type == 12) {
            size_t inner = at; char target[256] = {0}, part[256];
            /* a name in the record data: labels, possibly ending with a pointer into the message */
            size_t used_name = 0;
            for (int guard = 0; guard < 32 && inner < (size_t)n; guard++) {
                unsigned label = answer[inner];
                if (!label) break;
                if ((label & 0xc0) == 0xc0) { inner = ((label & 0x3f) << 8) | answer[inner + 1]; continue; }
                if (label > 63 || inner + 1 + label > (size_t)n || used_name + label + 2 >= sizeof(target)) break;
                memcpy(part, answer + inner + 1, label); part[label] = 0;
                used_name += (size_t)snprintf(target + used_name, sizeof(target) - used_name, "%s%s", used_name ? "." : "", part);
                inner += 1 + label;
            }
            length += (size_t)snprintf(text + length, sizeof(text) - length, "%s %s\n", type == 5 ? "CNAME" : "PTR", target);
        }
        at += rdlength;
        if (length > sizeof(text) - 300) break;
    }
    if (!length) { reply(output, 1, "NODATA", 6); return; }
    reply(output, 0, text, length);
}
/* One SNTP exchange with a server: "stratum N offset S delay S refid R". */
static void ntp_query(int output, const char *server_text) {
    struct in_addr server;
    if (inet_pton(AF_INET, server_text, &server) != 1) { reply(output, 2, "invalid ntp query", 17); return; }
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = htons(123), .sin_addr = server};
    if (fd < 0 || connect(fd, (struct sockaddr *)&to, sizeof(to))) { if (fd >= 0) close(fd); reply(output, 1, "unreachable", 11); return; }
    unsigned char in[128]; double sent = 0; ssize_t n = -1; double arrived = 0;
    for (int attempt = 0; attempt < 2 && n < 48; attempt++) {
        unsigned char packet[48] = {0x23}; sent = wall_now(); ntp_stamp(packet + 40, sent);
        if (send(fd, packet, sizeof(packet), 0) < 0) break;
        struct pollfd wait = {fd, POLLIN, 0};
        if (poll(&wait, 1, 1500) > 0) { n = recv(fd, in, sizeof(in), 0); arrived = wall_now(); }
    }
    close(fd);
    if (n < 48 || (in[0] & 7) != 4) { reply(output, 1, "timeout", 7); return; }
    double t2 = ntp_unix(in + 32), t3 = ntp_unix(in + 40);
    char refid[16]; if (in[1] == 1) snprintf(refid, sizeof(refid), "%.4s", (const char *)in + 12); else inet_ntop(AF_INET, in + 12, refid, sizeof(refid));
    char text[160]; int length = snprintf(text, sizeof(text), "stratum %u offset %.6f delay %.6f refid %s\n", in[1],
                                          ((t2 - sent) + (t3 - arrived)) / 2, (arrived - sent) - (t3 - t2), refid);
    reply(output, 0, text, (size_t)length);
}
static int hex_bytes(const char *hex, unsigned char *out, size_t room) {  /* length, or -1 */
    size_t length = strlen(hex);
    if (length % 2 || length / 2 > room) return -1;
    for (size_t i = 0; i < length / 2; i++) {
        unsigned value; if (sscanf(hex + 2 * i, "%2x", &value) != 1 || !strchr("0123456789abcdefABCDEF", hex[2 * i + 1])) return -1;
        out[i] = (unsigned char)value;
    }
    return (int)(length / 2);
}
/* One syslog datagram from this guest to a collector (the text, with its <PRI>, made by the router's CLI). */
static void syslog_send(int output, const char *server_text, const char *hex) {
    struct in_addr server; unsigned char message[1024]; int length = hex_bytes(hex, message, sizeof(message));
    if (inet_pton(AF_INET, server_text, &server) != 1 || length < 4 || message[0] != '<') { reply(output, 2, "invalid syslog", 14); return; }
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = htons(514), .sin_addr = server};
    ssize_t n = fd < 0 ? -1 : sendto(fd, message, (size_t)length, 0, (struct sockaddr *)&to, sizeof(to));
    if (fd >= 0) close(fd);
    if (n != length) { reply(output, 1, "send failed", 11); return; }
    reply(output, 0, "", 0);
}
/* An HTTP/1.0 GET from this guest, as a browser would: the status line, the headers and up to 24 KiB of body. */
static void http_get(int output, const char *server_text, const char *port_text, const char *path) {
    struct in_addr server;
    if (inet_pton(AF_INET, server_text, &server) != 1 || !valid_port_number(port_text) || path[0] != '/' || strlen(path) > 100
        || strspn(path, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._-") != strlen(path) || strstr(path, "..")) {
        reply(output, 2, "invalid http get", 16); return;
    }
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = htons((unsigned short)atoi(port_text)), .sin_addr = server};
    if (fd < 0) { reply(output, 3, "socket failed", 13); return; }
    if (connect(fd, (struct sockaddr *)&to, sizeof(to)) && errno != EINPROGRESS) { close(fd); reply(output, 1, "connection refused", 18); return; }
    struct pollfd wait = {fd, POLLOUT, 0}; int problem = 0; socklen_t size = sizeof(problem);
    if (poll(&wait, 1, 2500) <= 0) { close(fd); reply(output, 1, "timeout", 7); return; }
    getsockopt(fd, SOL_SOCKET, SO_ERROR, &problem, &size);
    if (problem) { close(fd); const char *text = problem == ECONNREFUSED ? "connection refused" : "unreachable"; reply(output, 1, text, strlen(text)); return; }
    char request[256]; int length = snprintf(request, sizeof(request), "GET %s HTTP/1.0\r\nHost: %s\r\nUser-Agent: Network-LABS\r\n\r\n", path, server_text);
    if (send_all(fd, request, (size_t)length)) { close(fd); reply(output, 1, "send failed", 11); return; }
    static char body[24576]; size_t used = 0;
    while (used < sizeof(body)) {
        struct pollfd more = {fd, POLLIN, 0};
        if (poll(&more, 1, 2500) <= 0) break;
        ssize_t n = read(fd, body + used, sizeof(body) - used);
        if (n < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        if (n <= 0) break;
        used += (size_t)n;
    }
    close(fd);
    if (!used) { reply(output, 1, "empty reply", 11); return; }
    reply(output, 0, body, used);
}
/* TFTP client: put a staged file (SERVICES_RUN/out/NAME) to a server, or get one (its content as the reply). */
static int tftp_client(const char *server_text, int write_mode, const char *name, char *reply_text, size_t *reply_size, size_t room) {
    struct in_addr server;
    if (inet_pton(AF_INET, server_text, &server) != 1 || !valid_file(name)) return 2;
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = htons(69), .sin_addr = server}, from; socklen_t size = sizeof(from);
    if (fd < 0) return 3;
    unsigned char request[100] = {0, (unsigned char)(write_mode ? 2 : 1)}; size_t length = 2;
    length += (size_t)snprintf((char *)request + 2, sizeof(request) - 2, "%s", name) + 1;
    length += (size_t)snprintf((char *)request + length, sizeof(request) - length, "octet") + 1;
    unsigned char in[600], out[516]; int file = -1; *reply_size = 0;
    if (write_mode) {
        char path[300]; snprintf(path, sizeof(path), SERVICES_RUN "/out/%.64s", name);
        if ((file = open(path, O_RDONLY | O_CLOEXEC)) < 0) { close(fd); return 2; }
    }
    /* the first answer comes from the server's transfer port: connect to it */
    ssize_t n = -1;
    for (int attempt = 0; attempt < 3 && n < 4; attempt++) {
        if (sendto(fd, request, length, 0, (struct sockaddr *)&to, sizeof(to)) < 0) break;
        struct pollfd wait = {fd, POLLIN, 0};
        if (poll(&wait, 1, 1000) > 0) n = recvfrom(fd, in, sizeof(in), 0, (struct sockaddr *)&from, &size);
    }
    if (n < 4 || from.sin_addr.s_addr != server.s_addr || connect(fd, (struct sockaddr *)&from, sizeof(from))) {
        if (file >= 0) close(file);
        close(fd); *reply_size = (size_t)snprintf(reply_text, room, "Timed out"); return 1;
    }
    if (in[1] == 5) {
        if (file >= 0) close(file);
        close(fd); *reply_size = (size_t)snprintf(reply_text, room, "%.*s", (int)(n > 4 ? n - 5 : 0), (char *)in + 4); return 1;
    }
    if (write_mode) {  /* got ACK 0: send the blocks */
        if (in[1] != 4 || in[2] || in[3]) { close(file); close(fd); *reply_size = (size_t)snprintf(reply_text, room, "Illegal TFTP operation"); return 1; }
        size_t total = 0;
        for (unsigned block = 1;; block++) {
            ssize_t got = read(file, out + 4, 512);
            if (got < 0) break;
            out[0] = 0; out[1] = 3; out[2] = (unsigned char)(block >> 8); out[3] = (unsigned char)block;
            if (send(fd, out, (size_t)got + 4, 0) < 0 || tftp_wait(fd, in, sizeof(in), 4, block, out, (size_t)got + 4) < 0) {
                close(file); close(fd); *reply_size = (size_t)snprintf(reply_text, room, "Timed out"); return 1;
            }
            total += (size_t)got;
            if (got < 512) break;
        }
        close(file); close(fd);
        *reply_size = (size_t)snprintf(reply_text, room, "%zu", total); return 0;
    }
    for (unsigned block = 1;; block++) {  /* RRQ: the first DATA is in hand */
        if (block > 1 && (n = tftp_wait(fd, in, sizeof(in), 3, block, out, 4)) < 0) {
            close(fd); *reply_size = (size_t)snprintf(reply_text, room, "Timed out"); return 1;
        }
        if (in[1] != 3 || ((unsigned)in[2] << 8 | in[3]) != (block & 0xffff)) { close(fd); *reply_size = (size_t)snprintf(reply_text, room, "Illegal TFTP operation"); return 1; }
        size_t got = (size_t)n - 4;
        if (*reply_size + got > room) { tftp_error(fd, 3, "Disk full or allocation exceeded"); close(fd); *reply_size = (size_t)snprintf(reply_text, room, "File too large"); return 1; }
        memcpy(reply_text + *reply_size, in + 4, got); *reply_size += got;
        out[0] = 0; out[1] = 4; out[2] = in[2]; out[3] = in[3];
        if (send(fd, out, 4, 0) < 0) break;
        if (got < 512) break;
    }
    close(fd); return 0;
}
static int valid_page(const char *name) {  /* a page of the web server: name.html, .htm, .txt or .css */
    size_t length = strlen(name); const char *dot = strrchr(name, '.');
    if (!length || length > 40 || !dot || dot == name || strspn(name, "abcdefghijklmnopqrstuvwxyz0123456789_.-") != length || strchr(name, '.') != dot) return 0;
    return !strcmp(dot, ".html") || !strcmp(dot, ".htm") || !strcmp(dot, ".txt") || !strcmp(dot, ".css");
}
static void serve(int input, int output, int mutations) {
    char request[4096]; size_t used = 0;
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
    /* Proxy ARP on one port (IOS « ip proxy-arp », on by default): the port answers ARP for an address the router
     * reaches through another port. Read back as "port value" lines. */
    char proxy_port[IFACE_SIZE], proxy_state[4], proxy_extra;
    if (mutations && sscanf(request, "NL1 PROXY_ARP %10s %3s %c", proxy_port, proxy_state, &proxy_extra) == 2 &&
        valid_interface(proxy_port) && strcmp(proxy_port, "br0") && (!strcmp(proxy_state, "on") || !strcmp(proxy_state, "off"))) {
        char path[64]; snprintf(path, sizeof(path), "/proc/sys/net/ipv4/conf/%s/proxy_arp", proxy_port);
        int fd = open(path, O_WRONLY | O_CLOEXEC);
        ssize_t n = fd < 0 ? -1 : write(fd, strcmp(proxy_state, "on") ? "0\n" : "1\n", 2);
        if (fd >= 0) close(fd);
        if (n != 2) { reply(output, 1, "proxy arp change failed", 23); return; }
        reply(output, 0, "", 0); return;
    }
    if (!strcmp(request, "NL1 PROXY_ARPS")) {
        char listing[256]; size_t used = 0;
        for (int i = 0; i < MAX_PORTS; i++) {
            char path[64], value[4] = {0}; snprintf(path, sizeof(path), "/proc/sys/net/ipv4/conf/eth%d/proxy_arp", i);
            int fd = open(path, O_RDONLY | O_CLOEXEC);
            ssize_t n = fd < 0 ? -1 : read(fd, value, sizeof(value) - 1);
            if (fd >= 0) close(fd);
            if (n > 0) used += (size_t)snprintf(listing + used, sizeof(listing) - used, "eth%d %c\n", i, value[0]);
        }
        reply(output, 0, listing, used); return;
    }
    /* EtherChannel: an 802.3ad bond (fast LACP, link monitoring, layer 2+3 hashing) and its member ports, through the
     * bonding sysfs files (no ifenslave applet). BOND_SHOW: each bond's /proc/net/bonding file after a "== bondN" line. */
    char bond_name[PORT_SIZE], bond_port[PORT_SIZE], bond_extra;
    if (mutations && sscanf(request, "NL1 BOND_ADD %5s %c", bond_name, &bond_extra) == 1 && valid_bond(bond_name)) {
        char line[16]; snprintf(line, sizeof(line), "+%s", bond_name);
        int failure = sysfs_write("/sys/class/net/bonding_masters", line);
        const char *settings[][2] = {{"mode", "802.3ad"}, {"lacp_rate", "fast"}, {"miimon", "100"}, {"xmit_hash_policy", "layer2+3"}};
        for (int i = 0; i < 4 && !failure; i++) {
            char path[80]; snprintf(path, sizeof(path), "/sys/class/net/%s/bonding/%s", bond_name, settings[i][0]);
            failure = sysfs_write(path, settings[i][1]);
        }
        if (failure) {
            char text[96]; int n = snprintf(text, sizeof(text), "bond change failed: %s", strerror(failure));
            reply(output, 1, text, (size_t)n); return;
        }
        reply(output, 0, "", 0); return;
    }
    int bond_slave = sscanf(request, "NL1 BOND_SLAVE %5s %5s %c", bond_name, bond_port, &bond_extra) == 2;
    int bond_release = !bond_slave && sscanf(request, "NL1 BOND_RELEASE %5s %5s %c", bond_name, bond_port, &bond_extra) == 2;
    if (mutations && (bond_slave || bond_release) && valid_bond(bond_name) && valid_port(bond_port)) {
        char path[80], line[16];
        snprintf(path, sizeof(path), "/sys/class/net/%s/bonding/slaves", bond_name);
        snprintf(line, sizeof(line), "%c%s", bond_slave ? '+' : '-', bond_port);
        if (bond_slave) full_duplex(bond_port);  /* best effort: without it the member stays individual (show etherchannel) */
        int failure = sysfs_write(path, line);
        if (failure) {
            char text[96]; int n = snprintf(text, sizeof(text), "bond member change failed: %s", strerror(failure));
            reply(output, 1, text, (size_t)n); return;
        }
        reply(output, 0, "", 0); return;
    }
    if (mutations && sscanf(request, "NL1 BOND_DEL %5s %c", bond_name, &bond_extra) == 1 && valid_bond(bond_name)) {
        char line[16]; snprintf(line, sizeof(line), "-%s", bond_name);
        int failure = sysfs_write("/sys/class/net/bonding_masters", line);
        if (failure) {
            char text[96]; int n = snprintf(text, sizeof(text), "bond change failed: %s", strerror(failure));
            reply(output, 1, text, (size_t)n); return;
        }
        reply(output, 0, "", 0); return;
    }
    if (!strcmp(request, "NL1 BOND_SHOW")) {
        static char listing[LIMIT]; size_t used = 0;
        for (int b = 1; b <= 8; b++) {
            char path[40]; snprintf(path, sizeof(path), "/proc/net/bonding/bond%d", b);
            int fd = open(path, O_RDONLY | O_CLOEXEC);
            if (fd < 0) continue;
            used += (size_t)snprintf(listing + used, sizeof(listing) - used, "== bond%d\n", b);
            ssize_t n = read(fd, listing + used, sizeof(listing) - used - 1);
            close(fd);
            if (n > 0) used += (size_t)n;
        }
        reply(output, 0, listing, used); return;
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
    if (!strcmp(request, "NL1 BRIDGE_FDB")) {
        static char table[LIMIT]; int failure;
        size_t size = bridge_fdb(table, sizeof(table), &failure);
        if (failure) {
            char text[96]; int n = snprintf(text, sizeof(text), "bridge fdb listing failed: %s", strerror(failure));
            reply(output, 1, text, (size_t)n); return;
        }
        reply(output, 0, table, size); return;
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
    char vlan_port[PORT_SIZE], vlan_mode[8], vlan_extra; unsigned vlan_id;
    int vlan_fields = sscanf(request, "NL1 BRIDGE_VLAN_ADD %5s %u %7s %c", vlan_port, &vlan_id, vlan_mode, &vlan_extra);
    int vlan_add = vlan_fields == 3 && (!strcmp(vlan_mode, "pvid") || !strcmp(vlan_mode, "tagged"));
    int vlan_delete = !vlan_add && sscanf(request, "NL1 BRIDGE_VLAN_DEL %5s %u %c", vlan_port, &vlan_id, &vlan_extra) == 2;
    if (mutations && (vlan_add || vlan_delete) && (valid_member(vlan_port) || !strcmp(vlan_port, "br0")) && vlan_id >= 1 && vlan_id <= 4094) {
        unsigned short flags = vlan_add && !strcmp(vlan_mode, "pvid") ? BRIDGE_VLAN_INFO_PVID | BRIDGE_VLAN_INFO_UNTAGGED : 0;
        int failure = bridge_vlan(vlan_add ? RTM_SETLINK : RTM_DELLINK, vlan_port, vlan_id, flags);
        if (failure) {
            char text[96]; int n = snprintf(text, sizeof(text), "bridge vlan change failed: %s", strerror(failure));
            reply(output, 1, text, (size_t)n); return;
        }
        reply(output, 0, "", 0); return;
    }
    char bridge_port[PORT_SIZE], bridge_extra;
    if (mutations && sscanf(request, "NL1 BRIDGE_ADD %5s %c", bridge_port, &bridge_extra) == 1 && valid_member(bridge_port)) {
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
    /* Spanning tree on the switch bridge (the kernel's IEEE 802.1D engine), from typed numbers only:
     * BRIDGE_STP PRIORITY HELLO MAX_AGE FORWARD_DELAY (seconds), BRIDGE_STP_PORT PORT COST PRIORITY, BRIDGE_STP_OFF,
     * and BRIDGE_STP_SHOW: "bridge KEY VALUE" and "PORT KEY VALUE" lines read from sysfs. */
    unsigned stp_priority, stp_hello, stp_age, stp_delay, stp_cost, stp_port_priority; char stp_port[PORT_SIZE], stp_extra;
    if (mutations && sscanf(request, "NL1 BRIDGE_STP %u %u %u %u %c", &stp_priority, &stp_hello, &stp_age, &stp_delay, &stp_extra) == 4 &&
        stp_priority <= 61440 && stp_priority % 4096 == 0 && stp_hello >= 1 && stp_hello <= 10 && stp_age >= 6 && stp_age <= 40 &&
        stp_delay >= 4 && stp_delay <= 30) {
        const char *names[] = {"forward_delay", "hello_time", "max_age", "priority", "stp_state"};
        unsigned values[] = {stp_delay * 100, stp_hello * 100, stp_age * 100, stp_priority, 1};
        for (int i = 0; i < 5; i++) {
            char path[64], text[16]; snprintf(path, sizeof(path), "/sys/class/net/br0/bridge/%s", names[i]);
            int length = snprintf(text, sizeof(text), "%u\n", values[i]), fd = open(path, O_WRONLY | O_CLOEXEC);
            ssize_t n = fd < 0 ? -1 : write(fd, text, (size_t)length);
            if (fd >= 0) close(fd);
            if (n != length) { reply(output, 1, "spanning tree change failed", 27); return; }
        }
        reply(output, 0, "", 0); return;
    }
    if (mutations && sscanf(request, "NL1 BRIDGE_STP_PORT %5s %u %u %c", stp_port, &stp_cost, &stp_port_priority, &stp_extra) == 3 &&
        valid_member(stp_port) && stp_cost >= 1 && stp_cost <= 65535 && stp_port_priority <= 240 && stp_port_priority % 16 == 0) {
        const char *names[] = {"path_cost", "priority"};
        unsigned values[] = {stp_cost, stp_port_priority / 16};  /* the kernel keeps the port priority's upper four bits */
        for (int i = 0; i < 2; i++) {
            char path[80], text[16]; snprintf(path, sizeof(path), "/sys/class/net/br0/brif/%s/%s", stp_port, names[i]);
            int length = snprintf(text, sizeof(text), "%u\n", values[i]), fd = open(path, O_WRONLY | O_CLOEXEC);
            ssize_t n = fd < 0 ? -1 : write(fd, text, (size_t)length);
            if (fd >= 0) close(fd);
            if (n != length) { reply(output, 1, "spanning tree port change failed", 32); return; }
        }
        reply(output, 0, "", 0); return;
    }
    if (mutations && !strcmp(request, "NL1 BRIDGE_STP_OFF")) {
        int fd = open("/sys/class/net/br0/bridge/stp_state", O_WRONLY | O_CLOEXEC);
        ssize_t n = fd < 0 ? -1 : write(fd, "0\n", 2);
        if (fd >= 0) close(fd);
        if (n != 2) { reply(output, 1, "spanning tree change failed", 27); return; }
        reply(output, 0, "", 0); return;
    }
    if (!strcmp(request, "NL1 BRIDGE_STP_SHOW")) {
        static char listing[8192]; size_t used = 0;
        const char *bridge_keys[] = {"stp_state", "bridge_id", "root_id", "root_port", "root_path_cost", "priority", "hello_time",
                                     "max_age", "forward_delay"};
        const char *port_keys[] = {"port_no", "state", "path_cost", "priority", "designated_bridge", "designated_root"};
        for (int i = 0; i < 9; i++) {
            char path[64], value[64] = {0}; snprintf(path, sizeof(path), "/sys/class/net/br0/bridge/%s", bridge_keys[i]);
            int fd = open(path, O_RDONLY | O_CLOEXEC);
            ssize_t n = fd < 0 ? -1 : read(fd, value, sizeof(value) - 1);
            if (fd >= 0) close(fd);
            if (n <= 0) { reply(output, 1, "no bridge", 9); return; }
            value[strcspn(value, "\n")] = 0;
            used += (size_t)snprintf(listing + used, sizeof(listing) - used, "bridge %s %s\n", bridge_keys[i], value);
        }
        for (int p = 0; p < MAX_PORTS + 8; p++) {  /* eth0..eth15, then bond1..bond8 */
            char member[PORT_SIZE]; snprintf(member, sizeof(member), p < MAX_PORTS ? "eth%d" : "bond%d", p < MAX_PORTS ? p : p - MAX_PORTS + 1);
            for (int i = 0; i < 6; i++) {
                char path[80], value[64] = {0}; snprintf(path, sizeof(path), "/sys/class/net/br0/brif/%s/%s", member, port_keys[i]);
                int fd = open(path, O_RDONLY | O_CLOEXEC);
                ssize_t n = fd < 0 ? -1 : read(fd, value, sizeof(value) - 1);
                if (fd >= 0) close(fd);
                if (n <= 0) break;
                value[strcspn(value, "\n")] = 0;
                used += (size_t)snprintf(listing + used, sizeof(listing) - used, "%s %s %s\n", member, port_keys[i], value);
            }
        }
        reply(output, 0, listing, used); return;
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
    char ospf_config[8192];
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
    /* EIGRP: render (read-only), start zebra then eigrpd under /run/frr, stop, and fixed vtysh views. */
    char eigrp_config[4096];
    if (!strncmp(request, "NL1 EIGRP_RENDER ", 17)) {
        int n = eigrp_render(request + 17, eigrp_config, sizeof(eigrp_config));
        if (n < 0) { reply(output, 2, "unsupported operation", 21); return; }
        reply(output, 0, eigrp_config, (size_t)n); return;
    }
    if (mutations && !strncmp(request, "NL1 EIGRP_START ", 16)) {
        int n = eigrp_render(request + 16, eigrp_config, sizeof(eigrp_config));
        if (n < 0) { reply(output, 2, "unsupported operation", 21); return; }
        const char *missing = "the guest image has no FRR eigrpd; rebuild it with --with-routing";
        if (access("/usr/lib/frr/eigrpd", X_OK) || access("/usr/lib/frr/zebra", X_OK)) { reply(output, 1, missing, strlen(missing)); return; }
        if (pidfile_alive("/run/frr/eigrpd.pid")) { reply(output, 1, "eigrp already running", 21); return; }
        mkdir("/run/frr", 0755);
        int fd = open("/run/frr/eigrpd.conf", O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
        int written = fd >= 0 && write(fd, eigrp_config, (size_t)n) == n;
        if (fd >= 0) close(fd);
        fd = open("/run/frr/zebra.conf", O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0600);
        if (fd >= 0) close(fd);
        char *const zebra[] = {"zebra", "-u", "root", "-g", "root", "-i", "/run/frr/zebra.pid", "-z", "/run/frr/zserv.api",
                               "--vty_socket", "/run/frr", "-f", "/run/frr/zebra.conf", NULL};
        char *const eigrpd[] = {"eigrpd", "-u", "root", "-g", "root", "-i", "/run/frr/eigrpd.pid", "-z", "/run/frr/zserv.api",
                                "--vty_socket", "/run/frr", "-f", "/run/frr/eigrpd.conf", NULL};
        if (!written || fd < 0 || (!pidfile_alive("/run/frr/zebra.pid") && spawn_detached("/usr/lib/frr/zebra", zebra))) {
            reply(output, 3, "eigrp start failed", 18); return;
        }
        for (int tries = 0; tries < 40 && access("/run/frr/zserv.api", F_OK); tries++) {
            struct timespec pause = {0, 50 * 1000 * 1000}; nanosleep(&pause, NULL);
        }
        if (spawn_detached("/usr/lib/frr/eigrpd", eigrpd)) { reply(output, 3, "eigrp start failed", 18); return; }
        reply(output, 0, "", 0); return;
    }
    if (mutations && !strcmp(request, "NL1 EIGRP_STOP")) {
        /* eigrpd first: zebra withdraws its routes when it goes away; zebra stays if bgpd still uses it. */
        const char *pids[] = {"/run/frr/eigrpd.pid", "/run/frr/zebra.pid"};
        for (int i = 0; i < 2; i++) {
            pid_t daemon = pidfile_alive(pids[i]);
            if (!daemon || (i == 1 && pidfile_alive("/run/frr/bgpd.pid"))) continue;
            kill(daemon, SIGTERM);
            for (int tries = 0; tries < 60 && kill(daemon, 0) == 0; tries++) {
                struct timespec pause = {0, 50 * 1000 * 1000}; nanosleep(&pause, NULL);
            }
            if (kill(daemon, 0) == 0) { reply(output, 3, "eigrp stop failed", 17); return; }
            unlink(pids[i]);
        }
        unlink("/run/frr/eigrpd.conf");
        reply(output, 0, "", 0); return;
    }
    if (!strcmp(request, "NL1 EIGRP_SHOW config")) {
        int fd = open("/run/frr/eigrpd.conf", O_RDONLY | O_CLOEXEC);
        if (fd < 0 || !pidfile_alive("/run/frr/eigrpd.pid")) {
            if (fd >= 0) close(fd);
            reply(output, 1, "eigrp not running", 17); return;
        }
        ssize_t n = read(fd, eigrp_config, sizeof(eigrp_config)); close(fd);
        reply(output, n < 0 ? 3 : 0, eigrp_config, n < 0 ? 0 : (size_t)n); return;
    }
    char *const eigrp_neighbors[] = {"vtysh", "--vty_socket", "/run/frr", "-c", "show ip eigrp neighbors", NULL};
    char *const eigrp_topology[] = {"vtysh", "--vty_socket", "/run/frr", "-c", "show ip eigrp topology", NULL};
    char *const *eigrp_show = !strcmp(request, "NL1 EIGRP_SHOW neighbors") ? eigrp_neighbors
                            : !strcmp(request, "NL1 EIGRP_SHOW topology") ? eigrp_topology : NULL;
    /* Port security and BPDU guard: this agent's --port-guard mode (see port_guard), restarted with each new policy. */
    if (mutations && !strncmp(request, "NL1 PORT_GUARD_START ", 21)) {
        static char copy[4096]; char *specs[MAX_PORTS + 3]; int count = 0; struct guard check;
        snprintf(copy, sizeof(copy), "%s", request + 21);
        specs[count++] = "network-labs-agent"; specs[count++] = "--port-guard";
        for (char *item = strtok(copy, " "); item; item = strtok(NULL, " ")) {
            if (count >= MAX_PORTS + 2 || !guard_parse(item, &check)) { reply(output, 2, "invalid port guard", 18); return; }
            specs[count++] = item;
        }
        specs[count] = NULL;
        if (count < 3) { reply(output, 2, "invalid port guard", 18); return; }
        pid_t running = pidfile_alive("/run/port-guard.pid");
        if (running) { kill(running, SIGTERM); for (int t = 0; t < 40 && kill(running, 0) == 0; t++) { struct timespec pause = {0, 50000000}; nanosleep(&pause, NULL); } }
        if (spawn_detached_pid("/sbin/network-labs-agent", specs, "/run/port-guard.pid")) { reply(output, 3, "port guard start failed", 23); return; }
        reply(output, 0, "", 0); return;
    }
    if (mutations && !strcmp(request, "NL1 PORT_GUARD_STOP")) {
        pid_t running = pidfile_alive("/run/port-guard.pid");
        if (running) { kill(running, SIGTERM); for (int t = 0; t < 40 && kill(running, 0) == 0; t++) { struct timespec pause = {0, 50000000}; nanosleep(&pause, NULL); } }
        unlink("/run/port-guard.pid");
        reply(output, 0, "", 0); return;
    }
    char guard_port[PORT_SIZE], guard_extra;
    if (mutations && sscanf(request, "NL1 PORT_GUARD_CLEAR %5s %c", guard_port, &guard_extra) == 1 && valid_port(guard_port)) {
        char path[48]; snprintf(path, sizeof(path), "/run/port-guard/%.5s", guard_port);
        if (unlink(path) && errno != ENOENT) { reply(output, 1, "port guard clear failed", 23); return; }
        reply(output, 0, "", 0); return;
    }
    if (!strcmp(request, "NL1 PORT_GUARD_SHOW")) {  /* "== PORT" then its state file, for each guarded port */
        static char listing[LIMIT]; size_t used = 0;
        for (int p = 0; p < MAX_PORTS; p++) {
            char path[48]; snprintf(path, sizeof(path), "/run/port-guard/eth%d", p);
            int fd = open(path, O_RDONLY | O_CLOEXEC);
            if (fd < 0) continue;
            used += (size_t)snprintf(listing + used, sizeof(listing) - used, "== eth%d\n", p);
            ssize_t n = read(fd, listing + used, sizeof(listing) - used - 1); close(fd);
            if (n > 0) used += (size_t)n;
        }
        reply(output, 0, listing, used); return;
    }
    /* HSRP (IOS « standby »): this agent's --hsrp mode (see hsrp), handed over to a new instance at each change. */
    if (mutations && !strncmp(request, "NL1 HSRP_START ", 15)) {
        static char copy[4096]; char *specs[HSRP_GROUPS + 3]; int count = 0; struct hsrp check;
        snprintf(copy, sizeof(copy), "%s", request + 15);
        specs[count++] = "network-labs-agent"; specs[count++] = "--hsrp";
        for (char *item = strtok(copy, " "); item; item = strtok(NULL, " ")) {
            if (count >= HSRP_GROUPS + 2 || !hsrp_parse(item, &check)) { reply(output, 2, "invalid hsrp group", 18); return; }
            specs[count++] = item;
        }
        specs[count] = NULL;
        if (count < 3) { reply(output, 2, "invalid hsrp group", 18); return; }
        pid_t running = pidfile_alive("/run/hsrp.pid");
        if (running) {
            kill(running, SIGUSR1);
            for (int t = 0; t < 40 && kill(running, 0) == 0; t++) { struct timespec pause = {0, 50000000}; nanosleep(&pause, NULL); }
        }
        if (spawn_detached_pid("/sbin/network-labs-agent", specs, "/run/hsrp.pid")) { reply(output, 3, "hsrp start failed", 17); return; }
        reply(output, 0, "", 0); return;
    }
    if (mutations && !strcmp(request, "NL1 HSRP_STOP")) {
        pid_t running = pidfile_alive("/run/hsrp.pid");
        if (running) {
            kill(running, SIGTERM);
            for (int t = 0; t < 40 && kill(running, 0) == 0; t++) { struct timespec pause = {0, 50000000}; nanosleep(&pause, NULL); }
        }
        unlink("/run/hsrp.pid");
        hsrp_tidy(NULL, 0);  /* what an instance that died left behind */
        reply(output, 0, "", 0); return;
    }
    if (!strcmp(request, "NL1 HSRP_SHOW")) {  /* "now SECONDS", then "== IFACE.GROUP" and its state file, for each group */
        static char listing[LIMIT]; size_t used = (size_t)snprintf(listing, sizeof(listing), "now %.1f\n", hsrp_now());
        DIR *folder = opendir("/run/hsrp"); struct dirent *entry;
        while (folder && (entry = readdir(folder)) && used < sizeof(listing) - 2048) {
            if (entry->d_name[0] == '.' || strstr(entry->d_name, ".new")) continue;
            char path[300], text[1024]; snprintf(path, sizeof(path), "/run/hsrp/%.200s", entry->d_name);
            if (hsrp_read_state(path, text, sizeof(text)))
                used += (size_t)snprintf(listing + used, sizeof(listing) - used, "== %s\n%s", entry->d_name, text);
        }
        if (folder) closedir(folder);
        reply(output, 0, listing, used); return;
    }
    /* VRRP (IOS « vrrp »): this agent's --vrrp mode (see vrrp), handed over to a new instance at each change. */
    if (mutations && !strncmp(request, "NL1 VRRP_START ", 15)) {
        static char copy[4096]; char *specs[VRRP_GROUPS + 3]; int count = 0; struct vrrp check;
        snprintf(copy, sizeof(copy), "%s", request + 15);
        specs[count++] = "network-labs-agent"; specs[count++] = "--vrrp";
        for (char *item = strtok(copy, " "); item; item = strtok(NULL, " ")) {
            if (count >= VRRP_GROUPS + 2 || !vrrp_parse(item, &check)) { reply(output, 2, "invalid vrrp group", 18); return; }
            specs[count++] = item;
        }
        specs[count] = NULL;
        if (count < 3) { reply(output, 2, "invalid vrrp group", 18); return; }
        pid_t running = pidfile_alive(VRRP_RUN ".pid");
        if (running) {
            kill(running, SIGUSR1);
            for (int t = 0; t < 40 && kill(running, 0) == 0; t++) { struct timespec pause = {0, 50000000}; nanosleep(&pause, NULL); }
        }
        if (spawn_detached_pid(AGENT_PROGRAM, specs, VRRP_RUN ".pid")) { reply(output, 3, "vrrp start failed", 17); return; }
        reply(output, 0, "", 0); return;
    }
    if (mutations && !strcmp(request, "NL1 VRRP_STOP")) {
        pid_t running = pidfile_alive(VRRP_RUN ".pid");
        if (running) {
            kill(running, SIGTERM);
            for (int t = 0; t < 40 && kill(running, 0) == 0; t++) { struct timespec pause = {0, 50000000}; nanosleep(&pause, NULL); }
        }
        unlink(VRRP_RUN ".pid");
        vrrp_tidy(NULL, 0);  /* what an instance that died left behind */
        reply(output, 0, "", 0); return;
    }
    if (!strcmp(request, "NL1 VRRP_SHOW")) {  /* "now SECONDS", then "== IFACE.VRID" and its state file, for each group */
        static char listing[LIMIT]; size_t used = (size_t)snprintf(listing, sizeof(listing), "now %.1f\n", hsrp_now());
        DIR *folder = opendir(VRRP_RUN); struct dirent *entry;
        while (folder && (entry = readdir(folder)) && used < sizeof(listing) - 1024) {
            if (entry->d_name[0] == '.' || strstr(entry->d_name, ".new")) continue;
            char path[300], text[512]; snprintf(path, sizeof(path), VRRP_RUN "/%.200s", entry->d_name);
            if (hsrp_read_state(path, text, sizeof(text)))
                used += (size_t)snprintf(listing + used, sizeof(listing) - used, "== %s\n%s", entry->d_name, text);
        }
        if (folder) closedir(folder);
        reply(output, 0, listing, used); return;
    }
    /* DHCP relay (IOS « ip helper-address »): this agent's --dhcp-relay mode, one per guest. */
    char relay_server[16], relay_clients[200], relay_extra;
    if (mutations && sscanf(request, "NL1 DHCP_RELAY_START %15s %199s %c", relay_server, relay_clients, &relay_extra) == 2) {
        struct in_addr server_address;
        int ok = inet_pton(AF_INET, relay_server, &server_address) == 1, ports = 0;
        char copy[200]; strcpy(copy, relay_clients);
        for (char *item = strtok(copy, ","); item && ok; item = strtok(NULL, ",")) ok = valid_interface(item) && ++ports <= RELAY_PORTS;
        if (!ok) { reply(output, 2, "invalid dhcp relay", 18); return; }
        if (pidfile_alive("/run/dhcprelay.pid")) { reply(output, 1, "dhcp relay already running", 26); return; }
        char *const relay[] = {"network-labs-agent", "--dhcp-relay", relay_server, relay_clients, NULL};
        if (spawn_detached_pid("/sbin/network-labs-agent", relay, "/run/dhcprelay.pid")) {
            reply(output, 3, "dhcp relay start failed", 23); return;
        }
        reply(output, 0, "", 0); return;
    }
    if (mutations && !strcmp(request, "NL1 DHCP_RELAY_STOP")) {
        pid_t relay = pidfile_alive("/run/dhcprelay.pid");
        if (relay) {
            kill(relay, SIGTERM);
            for (int tries = 0; tries < 40 && kill(relay, 0) == 0; tries++) {
                struct timespec pause = {0, 50 * 1000 * 1000}; nanosleep(&pause, NULL);
            }
            if (kill(relay, 0) == 0) { reply(output, 3, "dhcp relay stop failed", 22); return; }
        }
        unlink("/run/dhcprelay.pid");
        reply(output, 0, "", 0); return;
    }
    if (!strcmp(request, "NL1 DHCP_RELAY_SHOW")) { /* the running relay's command line, words separated by spaces */
        pid_t relay = pidfile_alive("/run/dhcprelay.pid");
        if (!relay) { reply(output, 1, "dhcp relay not running", 22); return; }
        char path[40], line[160]; snprintf(path, sizeof(path), "/proc/%d/cmdline", (int)relay);
        int fd = open(path, O_RDONLY | O_CLOEXEC);
        ssize_t n = fd < 0 ? -1 : read(fd, line, sizeof(line) - 1);
        if (fd >= 0) close(fd);
        if (n <= 0) { reply(output, 3, "dhcp relay unreadable", 21); return; }
        for (ssize_t i = 0; i < n; i++) if (!line[i]) line[i] = ' ';
        while (n > 0 && line[n - 1] == ' ') n--;
        reply(output, 0, line, (size_t)n); return;
    }
    /* DHCP with BusyBox: one server or client per port, configured only from typed fields. */
    char dhcp_port[IFACE_SIZE], dhcp_start[16], dhcp_end[16], dhcp_mask[16], dhcp_router[16], dhcp_lease[7], dhcp_dns[48], dhcp_extra;
    char dhcp_conf[40], dhcp_pid[40], dhcp_leases[40];
    /* An optional 8th field « relayed »: the pool serves a remote LAN through a relay. udhcpd then skips its ARP check of
     * each address (-a 0): on the port toward the relay, the relay router answers ARP for that LAN by proxy (IOS's
     * default), so every address would look taken; an IOS server checks with a ping through the routes instead. */
    char dhcp_flag[8] = "";
    int dhcp_fields = sscanf(request, "NL1 DHCP_SERVE %10s %15s %15s %15s %15s %6s %47s %7s %c", dhcp_port, dhcp_start, dhcp_end,
                             dhcp_mask, dhcp_router, dhcp_lease, dhcp_dns, dhcp_flag, &dhcp_extra);
    int dhcp_relayed = dhcp_fields == 8 && !strcmp(dhcp_flag, "relayed");
    if (mutations && !strncmp(request, "NL1 DHCP_SERVE ", 15) && (dhcp_fields == 7 || dhcp_relayed)) {
        struct in_addr first, last;
        /* a port or a router-on-a-stick subinterface (eth0.10): one pool, one udhcpd, per interface */
        int ok = valid_interface(dhcp_port) && strcmp(dhcp_port, "br0") && inet_pton(AF_INET, dhcp_start, &first) == 1 && inet_pton(AF_INET, dhcp_end, &last) == 1 &&
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
        char *const serve_relayed[] = {"busybox", "udhcpd", "-f", "-a", "0", dhcp_conf, NULL};
        if (!written || spawn_detached("/bin/busybox", dhcp_relayed ? serve_relayed : serve)) {
            reply(output, 3, "dhcp server start failed", 24); return;
        }
        reply(output, 0, "", 0); return;
    }
    if (mutations && sscanf(request, "NL1 DHCP_CLIENT %5s %c", dhcp_port, &dhcp_extra) == 1 && valid_port(dhcp_port)) {
        snprintf(dhcp_pid, sizeof(dhcp_pid), "/run/udhcpc.%s.pid", dhcp_port);
        if (pidfile_alive(dhcp_pid)) { reply(output, 1, "dhcp client already running", 27); return; }
        char *const client[] = {"busybox", "udhcpc", "-f", "-i", dhcp_port, "-s", "/etc/network-labs/dhcp-client.sh", "-p", dhcp_pid,
                                "-T", "1", "-A", "2", NULL};
        if (spawn_detached("/bin/busybox", client)) { reply(output, 3, "dhcp client start failed", 24); return; }
        reply(output, 0, "", 0); return;
    }
    /* « no ip dhcp pool » or a changed pool on a running router: its udhcpd stops (writing its leases first); the lease
     * file stays, as IOS keeps its bindings, so a restarted pool gives the same clients their addresses back. */
    if (mutations && sscanf(request, "NL1 DHCP_STOP %10s %c", dhcp_port, &dhcp_extra) == 1 && valid_interface(dhcp_port) && strcmp(dhcp_port, "br0")) {
        snprintf(dhcp_pid, sizeof(dhcp_pid), "/run/udhcpd.%s.pid", dhcp_port);
        pid_t server = pidfile_alive(dhcp_pid);
        if (server) {
            kill(server, SIGTERM);
            for (int t = 0; t < 40 && kill(server, 0) == 0; t++) { struct timespec pause = {0, 50000000}; nanosleep(&pause, NULL); }
        }
        unlink(dhcp_pid);
        reply(output, 0, "", 0); return;
    }
    char *const lease_list[] = {"busybox", "dumpleases", "-f", dhcp_leases, NULL};
    char *const *lease_args = NULL;
    if (sscanf(request, "NL1 DHCP_LEASES %10s %c", dhcp_port, &dhcp_extra) == 1 && valid_interface(dhcp_port) && strcmp(dhcp_port, "br0")) {
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
    /* Server services (--services: DNS, NTP, Syslog collector, NTP client), the web server (BusyBox httpd on /run/www) and
     * the clients a PC or a router uses toward them (a DNS query, an SNTP exchange, a syslog datagram, an HTTP GET). */
    if (mutations && !strncmp(request, "NL1 SERVICES_START ", 19)) {
        static char copy[4096]; char *specs[SERVICE_RECORDS + 12]; int count = 0; static struct services check;
        snprintf(copy, sizeof(copy), "%s", request + 19);
        specs[count++] = "network-labs-agent"; specs[count++] = "--services";
        for (char *item = strtok(copy, " "); item; item = strtok(NULL, " ")) {
            if (count >= SERVICE_RECORDS + 10) { reply(output, 2, "invalid services", 16); return; }
            specs[count++] = item;
        }
        specs[count] = NULL;
        if (!services_parse(count - 2, specs + 2, &check)) { reply(output, 2, "invalid services", 16); return; }
        pid_t running = pidfile_alive(SERVICES_RUN "/services.pid");
        if (running) {
            kill(running, SIGTERM);
            for (int t = 0; t < 40 && kill(running, 0) == 0; t++) { struct timespec pause = {0, 50000000}; nanosleep(&pause, NULL); }
        }
        unlink(SERVICES_RUN "/services.state");
        if (spawn_detached_pid(AGENT_PROGRAM, specs, SERVICES_RUN "/services.pid")) { reply(output, 3, "services start failed", 21); return; }
        for (int t = 0; t < 40 && access(SERVICES_RUN "/services.state", F_OK); t++) { struct timespec pause = {0, 50000000}; nanosleep(&pause, NULL); }
        if (access(SERVICES_RUN "/services.state", F_OK)) { reply(output, 1, "services did not start (port in use?)", 37); return; }
        reply(output, 0, "", 0); return;
    }
    if (mutations && !strcmp(request, "NL1 SERVICES_STOP")) {
        pid_t running = pidfile_alive(SERVICES_RUN "/services.pid");
        if (running) {
            kill(running, SIGTERM);
            for (int t = 0; t < 40 && kill(running, 0) == 0; t++) { struct timespec pause = {0, 50000000}; nanosleep(&pause, NULL); }
        }
        unlink(SERVICES_RUN "/services.pid"); unlink(SERVICES_RUN "/services.state");
        reply(output, 0, "", 0); return;
    }
    if (!strcmp(request, "NL1 SERVICES_SHOW") || !strcmp(request, "NL1 SYSLOG_READ")) {
        static char listing[LIMIT]; size_t used = 0;
        int fd = open(request[4] == 'S' && request[5] == 'E' ? SERVICES_RUN "/services.state" : SERVICES_RUN "/syslog.log", O_RDONLY | O_CLOEXEC);
        if (fd >= 0) { ssize_t n = read(fd, listing, sizeof(listing) - 1); close(fd); if (n > 0) used = (size_t)n; }
        if (pidfile_alive(SERVICES_RUN "/httpd.pid") && request[5] == 'E') used += (size_t)snprintf(listing + used, sizeof(listing) - used, "http 1\n");
        reply(output, 0, listing, used); return;
    }
    char service_a[128], service_b[2100], service_c[128], service_extra;
    if (sscanf(request, "NL1 RESOLVE %15s %127s %c", service_a, service_b, &service_extra) == 2) { resolve(output, service_a, service_b); return; }
    if (sscanf(request, "NL1 NTP_QUERY %15s %c", service_a, &service_extra) == 1) { ntp_query(output, service_a); return; }
    if (sscanf(request, "NL1 SYSLOG_SEND %15s %2048s %c", service_a, service_b, &service_extra) == 2) { syslog_send(output, service_a, service_b); return; }
    if (sscanf(request, "NL1 HTTP_GET %15s %5s %100s %c", service_a, service_c, service_b, &service_extra) == 3) {
        http_get(output, service_a, service_c, service_b); return;
    }
    char file_area[8], file_name[80];
    if (mutations && sscanf(request, "NL1 FILE_PUT %7s %79s %2048s %c", file_area, file_name, service_b, &service_extra) == 3) {
        /* a file staged for TFTP: « out » (what this device sends) or « tftp » (what its TFTP server holds); appended */
        static unsigned char content[1024]; int length = hex_bytes(service_b, content, sizeof(content));
        if ((strcmp(file_area, "out") && strcmp(file_area, "tftp")) || !valid_file(file_name) || length < 0) { reply(output, 2, "invalid file", 12); return; }
        char path[300]; snprintf(path, sizeof(path), SERVICES_RUN "/%.7s", file_area); mkdir(path, 0755);
        snprintf(path, sizeof(path), SERVICES_RUN "/%.7s/%.64s", file_area, file_name);
        struct stat before;
        if (!stat(path, &before) && before.st_size + length > TFTP_LIMIT) { reply(output, 1, "file too large", 14); return; }
        int fd = open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
        if (fd < 0 || (length && write(fd, content, (size_t)length) != length)) { if (fd >= 0) close(fd); reply(output, 1, "file write failed", 17); return; }
        close(fd); reply(output, 0, "", 0); return;
    }
    if (mutations && sscanf(request, "NL1 FILE_DEL %7s %79s %c", file_area, file_name, &service_extra) == 2) {
        if ((strcmp(file_area, "out") && strcmp(file_area, "tftp")) || !valid_file(file_name)) { reply(output, 2, "invalid file", 12); return; }
        char path[300]; snprintf(path, sizeof(path), SERVICES_RUN "/%.7s/%.64s", file_area, file_name);
        if (unlink(path) && errno != ENOENT) { reply(output, 1, "file delete failed", 18); return; }
        reply(output, 0, "", 0); return;
    }
    if (!strcmp(request, "NL1 TFTP_FILES")) {  /* "NAME SIZE" lines: what the TFTP server holds */
        static char listing[4096]; size_t used = 0;
        DIR *folder = opendir(SERVICES_RUN "/tftp"); struct dirent *entry;
        while (folder && (entry = readdir(folder)) && used < sizeof(listing) - 100) {
            if (!valid_file(entry->d_name) || strstr(entry->d_name, ".part")) continue;
            char path[300]; struct stat info; snprintf(path, sizeof(path), SERVICES_RUN "/tftp/%.200s", entry->d_name);
            if (!stat(path, &info)) used += (size_t)snprintf(listing + used, sizeof(listing) - used, "%s %ld\n", entry->d_name, (long)info.st_size);
        }
        if (folder) closedir(folder);
        reply(output, 0, listing, used); return;
    }
    if (sscanf(request, "NL1 TFTP_READ %79s %c", file_name, &service_extra) == 1) {
        if (!valid_file(file_name)) { reply(output, 2, "invalid file", 12); return; }
        static char content[TFTP_LIMIT]; char path[300]; snprintf(path, sizeof(path), SERVICES_RUN "/tftp/%.64s", file_name);
        int fd = open(path, O_RDONLY | O_CLOEXEC); ssize_t n = fd < 0 ? -1 : read(fd, content, sizeof(content));
        if (fd >= 0) close(fd);
        if (n < 0) { reply(output, 1, "no such file", 12); return; }
        reply(output, 0, content, n > 32768 ? 32768 : (size_t)n); return;
    }
    int tftp_put = !strncmp(request, "NL1 TFTP_PUT ", 13);
    if ((tftp_put || !strncmp(request, "NL1 TFTP_GET ", 13)) && sscanf(request + 13, "%15s %79s %c", service_a, file_name, &service_extra) == 2) {
        static char received[32768]; size_t length = 0;
        int code = tftp_client(service_a, tftp_put, file_name, received, &length, sizeof(received));
        if (code == 2) { reply(output, 2, "invalid tftp transfer", 21); return; }
        reply(output, code, received, length); return;
    }
    if (mutations && !strcmp(request, "NL1 HTTP_START")) {
        mkdir(SERVICES_RUN "/www", 0755);
        if (!pidfile_alive(SERVICES_RUN "/httpd.pid")) {
            char *const httpd[] = {"busybox", "httpd", "-f", "-p", "80", "-h", SERVICES_RUN "/www", NULL};
            if (spawn_detached_pid("/bin/busybox", httpd, SERVICES_RUN "/httpd.pid")) { reply(output, 3, "http start failed", 17); return; }
        }
        reply(output, 0, "", 0); return;
    }
    if (mutations && !strcmp(request, "NL1 HTTP_STOP")) {
        pid_t running = pidfile_alive(SERVICES_RUN "/httpd.pid");
        if (running) {
            kill(running, SIGTERM);
            for (int t = 0; t < 40 && kill(running, 0) == 0; t++) { struct timespec pause = {0, 50000000}; nanosleep(&pause, NULL); }
        }
        unlink(SERVICES_RUN "/httpd.pid");
        reply(output, 0, "", 0); return;
    }
    int page_append = !strncmp(request, "NL1 HTTP_PAGE_ADD ", 18);
    if (mutations && (page_append || !strncmp(request, "NL1 HTTP_PAGE ", 14)) && sscanf(request + (page_append ? 18 : 14), "%40s %2048s %c", service_c, service_b, &service_extra) == 2) {
        static unsigned char content[1024]; int length = hex_bytes(service_b, content, sizeof(content));
        if (!valid_page(service_c) || length < 0) { reply(output, 2, "invalid page", 12); return; }
        char path[300]; snprintf(path, sizeof(path), SERVICES_RUN "/www/%.40s", service_c);
        mkdir(SERVICES_RUN "/www", 0755);
        struct stat before;
        if (page_append && !stat(path, &before) && before.st_size + length > 65536) { reply(output, 1, "page too large", 14); return; }
        int fd = open(path, O_WRONLY | O_CREAT | O_CLOEXEC | (page_append ? O_APPEND : O_TRUNC), 0644);
        if (fd < 0 || (length && write(fd, content, (size_t)length) != length)) { if (fd >= 0) close(fd); reply(output, 1, "page write failed", 17); return; }
        close(fd); reply(output, 0, "", 0); return;
    }
    if (mutations && sscanf(request, "NL1 HTTP_PAGE_DEL %40s %c", service_c, &service_extra) == 1) {
        if (!valid_page(service_c)) { reply(output, 2, "invalid page", 12); return; }
        char path[300]; snprintf(path, sizeof(path), SERVICES_RUN "/www/%.40s", service_c);
        if (unlink(path) && errno != ENOENT) { reply(output, 1, "page delete failed", 18); return; }
        reply(output, 0, "", 0); return;
    }
    if (!strcmp(request, "NL1 HTTP_PAGES")) {  /* "NAME SIZE" lines */
        static char listing[4096]; size_t used = 0;
        DIR *folder = opendir(SERVICES_RUN "/www"); struct dirent *entry;
        while (folder && (entry = readdir(folder)) && used < sizeof(listing) - 80) {
            if (!valid_page(entry->d_name)) continue;
            char path[300]; struct stat info; snprintf(path, sizeof(path), SERVICES_RUN "/www/%.200s", entry->d_name);
            if (!stat(path, &info)) used += (size_t)snprintf(listing + used, sizeof(listing) - used, "%s %ld\n", entry->d_name, (long)info.st_size);
        }
        if (folder) closedir(folder);
        reply(output, 0, listing, used); return;
    }
    if (!strncmp(request, "NL1 PING ", 9) && inet_pton(AF_INET, request + 9, &destination) == 1)
        args = ping;
    if (!strcmp(request, "NL1 ADDRESSES")) args = addresses;
    if (!strcmp(request, "NL1 ROUTES")) args = routes;
    char *const neighbors[] = {"busybox", "ip", "neigh", "show", NULL};  /* the ARP table (show arp, arp -a) */
    if (!strcmp(request, "NL1 NEIGHBORS")) args = neighbors;
    char port[IFACE_SIZE], action[5], cidr[20], extra;
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
    /* 802.1Q subinterfaces, named ethN.VID (br0.VID: a routing switch's SVI), through the kernel's VLAN ioctl as vconfig does. */
    unsigned subinterface_vid;
    int subinterface_add = sscanf(request, "NL1 VLAN_ADD %5s %u %c", port, &subinterface_vid, &extra) == 2;
    int subinterface_delete = !subinterface_add && sscanf(request, "NL1 VLAN_DEL %10s %c", port, &extra) == 1;
    if (mutations && ((subinterface_add && (valid_port(port) || !strcmp(port, "br0")) && subinterface_vid >= 1 && subinterface_vid <= 4094) ||
                      (subinterface_delete && valid_interface(port) && strchr(port, '.')))) {
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
    if (mutations && sscanf(request, "NL1 LINK %10s %4s %c", port, action, &extra) == 2 &&
        valid_interface(port) && (!strcmp(action, "up") || !strcmp(action, "down"))) args = link_args;
    char *const address_add[] = {"busybox", "ip", "address", "add", request + 13, "dev", "eth0", NULL};
    char *const address_delete[] = {"busybox", "ip", "address", "del", request + 13, "dev", "eth0", NULL};
    if (mutations && !strncmp(request, "NL1 ADDR_ADD ", 13) && valid_cidr(request + 13)) args = address_add;
    if (mutations && !strncmp(request, "NL1 ADDR_DEL ", 13) && valid_cidr(request + 13)) args = address_delete;
    char *const iface_add[] = {"busybox", "ip", "address", "add", cidr, "dev", port, NULL};
    char *const iface_delete[] = {"busybox", "ip", "address", "del", cidr, "dev", port, NULL};
    if (mutations && sscanf(request, "NL1 IF_ADD %10s %19s %c", port, cidr, &extra) == 2 && valid_interface(port) && valid_cidr(cidr))
        args = iface_add;
    if (mutations && sscanf(request, "NL1 IF_DEL %10s %19s %c", port, cidr, &extra) == 2 && valid_interface(port) && valid_cidr(cidr))
        args = iface_delete;
    char via_network[20], via_gateway[16];
    char *const iface_route_add[] = {"busybox", "ip", "route", "add", via_network, "via", via_gateway, "dev", port, NULL};
    char *const iface_route_delete[] = {"busybox", "ip", "route", "del", via_network, "via", via_gateway, "dev", port, NULL};
    if (mutations && sscanf(request, "NL1 IF_ROUTE_ADD %10s %19s %15s %c", port, via_network, via_gateway, &extra) == 3 &&
        valid_interface(port) && valid_cidr(via_network) && inet_pton(AF_INET, via_gateway, &destination) == 1) args = iface_route_add;
    /* A route through a port with no next hop (IOS « ip route NET MASK PORT »): the port's neighbours answer ARP. */
    char *const dev_route_add[] = {"busybox", "ip", "route", "add", via_network, "dev", port, NULL};
    char *const dev_route_delete[] = {"busybox", "ip", "route", "del", via_network, "dev", port, NULL};
    if (mutations && sscanf(request, "NL1 DEV_ROUTE_ADD %10s %19s %c", port, via_network, &extra) == 2 &&
        valid_interface(port) && valid_cidr(via_network)) args = dev_route_add;
    if (mutations && sscanf(request, "NL1 DEV_ROUTE_DEL %10s %19s %c", port, via_network, &extra) == 2 &&
        valid_interface(port) && valid_cidr(via_network)) args = dev_route_delete;
    if (mutations && sscanf(request, "NL1 IF_ROUTE_DEL %10s %19s %15s %c", port, via_network, via_gateway, &extra) == 3 &&
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
    char fw_action[7], fw_in[PORT_SIZE], fw_out[PORT_SIZE], fw_proto[5], fw_source[20], fw_destination[20], fw_port[6];
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
    else if (mutations && sscanf(request, "NL1 FW_NAT %10s %5s %5s %4s %19s %19s %5s %31s %5s %c", nat_kind, fw_in, fw_out, fw_proto,
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
    } else if (mutations && sscanf(request, "NL1 FW_RULE %6s %5s %5s %4s %19s %19s %5s %c", fw_action, fw_in, fw_out,
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
    if (eigrp_show) { args = eigrp_show; program = "/usr/bin/vtysh"; }
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
static int port_address(const char *name, struct in_addr *address) {
    struct ifreq request; memset(&request, 0, sizeof(request));
    snprintf(request.ifr_name, sizeof(request.ifr_name), "%s", name);
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    int failed = fd < 0 || ioctl(fd, SIOCGIFADDR, &request) < 0;
    if (fd >= 0) close(fd);
    if (!failed) *address = ((struct sockaddr_in *)&request.ifr_addr)->sin_addr;
    return failed;
}
/* DHCP relay (RFC 1542), as IOS « ip helper-address » relays: a request broadcast on a helper port goes to the server
 * with giaddr set to that port's address (the server picks the pool by it and answers to it); a reply to one of those
 * addresses goes back out its port, broadcast, since the client has no address yet. The kernel routes to the server. */
static int dhcp_relay(const char *server_text, const char *clients_text) {
    struct in_addr server;
    char names[RELAY_PORTS][IFNAMSIZ]; unsigned indexes[RELAY_PORTS]; int count = 0;
    if (inet_pton(AF_INET, server_text, &server) != 1 || strlen(clients_text) >= 200) return 2;
    char copy[200]; strcpy(copy, clients_text);
    for (char *item = strtok(copy, ","); item; item = strtok(NULL, ",")) {
        if (count == RELAY_PORTS || !valid_interface(item)) return 2;
        snprintf(names[count], IFNAMSIZ, "%s", item);
        if (!(indexes[count] = if_nametoindex(item))) return 1;
        count++;
    }
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0), on = 1;
    struct sockaddr_in local = {.sin_family = AF_INET, .sin_port = htons(67), .sin_addr.s_addr = htonl(INADDR_ANY)};
    if (!count || fd < 0 || setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on)) ||
        setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &on, sizeof(on)) || setsockopt(fd, IPPROTO_IP, IP_PKTINFO, &on, sizeof(on)) ||
        bind(fd, (struct sockaddr *)&local, sizeof(local))) return 1;
    for (;;) {
        unsigned char packet[1500]; char control[CMSG_SPACE(sizeof(struct in_pktinfo))];
        struct sockaddr_in from; struct iovec io = {packet, sizeof(packet)};
        struct msghdr message = {.msg_name = &from, .msg_namelen = sizeof(from), .msg_iov = &io, .msg_iovlen = 1,
                                 .msg_control = control, .msg_controllen = sizeof(control)};
        ssize_t n = recvmsg(fd, &message, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) return 1;
        static const unsigned char cookie[4] = {99, 130, 83, 99};
        if (n < 240 || memcmp(packet + 236, cookie, 4)) continue;
        unsigned arrived = 0;
        for (struct cmsghdr *c = CMSG_FIRSTHDR(&message); c; c = CMSG_NXTHDR(&message, c))
            if (c->cmsg_level == IPPROTO_IP && c->cmsg_type == IP_PKTINFO) arrived = ((struct in_pktinfo *)CMSG_DATA(c))->ipi_ifindex;
        struct in_addr gateway, address; memcpy(&gateway, packet + 24, 4);
        if (packet[0] == 1) {  /* BOOTREQUEST: only from a client on a helper port */
            int port = -1;
            for (int i = 0; i < count; i++) if (indexes[i] == arrived) port = i;
            if (port < 0 || packet[3] >= 16) continue;
            packet[3]++;
            if (!gateway.s_addr) {
                if (port_address(names[port], &address)) continue;
                memcpy(packet + 24, &address, 4);
            }
            struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = htons(67), .sin_addr = server};
            (void)sendto(fd, packet, (size_t)n, 0, (struct sockaddr *)&to, sizeof(to));
        } else if (packet[0] == 2) {  /* BOOTREPLY: to the helper port whose address is its giaddr */
            for (int i = 0; i < count; i++) {
                if (port_address(names[i], &address) || address.s_addr != gateway.s_addr) continue;
                struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = htons(68), .sin_addr.s_addr = htonl(INADDR_BROADCAST)};
                char out[CMSG_SPACE(sizeof(struct in_pktinfo))]; memset(out, 0, sizeof(out));
                struct iovec body = {packet, (size_t)n};
                struct msghdr reply_message = {.msg_name = &to, .msg_namelen = sizeof(to), .msg_iov = &body, .msg_iovlen = 1,
                                               .msg_control = out, .msg_controllen = sizeof(out)};
                struct cmsghdr *c = CMSG_FIRSTHDR(&reply_message);
                c->cmsg_level = IPPROTO_IP; c->cmsg_type = IP_PKTINFO; c->cmsg_len = CMSG_LEN(sizeof(struct in_pktinfo));
                struct in_pktinfo *info = (struct in_pktinfo *)CMSG_DATA(c);
                info->ipi_ifindex = (int)indexes[i]; info->ipi_spec_dst = address;
                (void)sendmsg(fd, &reply_message, 0);
                break;
            }
        }
    }
}
int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);
    if (argc == 2 && !strcmp(argv[1], "--stdio")) { serve(0, 1, 0); return 0; }
    if (argc == 4 && !strcmp(argv[1], "--dhcp-relay")) return dhcp_relay(argv[2], argv[3]);
    if (argc >= 3 && !strcmp(argv[1], "--port-guard")) return port_guard(argc - 2, argv + 2);
    if (argc >= 3 && !strcmp(argv[1], "--hsrp")) return hsrp(argc - 2, argv + 2);
    if (argc >= 3 && !strcmp(argv[1], "--vrrp")) return vrrp(argc - 2, argv + 2);
    if (argc >= 3 && !strcmp(argv[1], "--services")) return services(argc - 2, argv + 2);
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
