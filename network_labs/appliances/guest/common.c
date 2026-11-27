/* Network LABS guest agent: shared checks (port, interface, address names) and helpers: sysfs, detached daemons, bridge VLANs and FDB, replies.
 * Part of agent.c, which includes it: the agent is one compilation unit. */
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
/* 1 while PID runs: it exists and is not a zombie (an ended daemon its parent, or init, has not reaped yet). */
static int process_alive(pid_t pid) {
    if (pid <= 1 || kill(pid, 0) != 0) return 0;
    char path[32], stat[256] = {0}; snprintf(path, sizeof(path), "/proc/%d/stat", (int)pid);
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 1;  /* no /proc: kill's answer */
    ssize_t n = read(fd, stat, sizeof(stat) - 1); close(fd);
    const char *state = n > 0 ? strrchr(stat, ')') : NULL;  /* "PID (NAME) STATE ...", NAME may hold spaces */
    return !(state && state[1] == ' ' && state[2] == 'Z');
}
static pid_t pidfile_alive(const char *path) {
    char text[16] = {0}; int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 0;
    ssize_t n = read(fd, text, sizeof(text) - 1); close(fd);
    long pid = n > 0 ? atol(text) : 0;
    return process_alive((pid_t)pid) ? (pid_t)pid : 0;
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
