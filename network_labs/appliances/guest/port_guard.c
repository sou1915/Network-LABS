/* Network LABS guest agent: the --port-guard mode: port security (MAC limits, sticky, violations) and BPDU guard.
 * Part of agent.c, which includes it: the agent is one compilation unit. */
/* Port security and BPDU guard (IOS « switchport port-security », « spanning-tree bpduguard enable »): this agent's
 * --port-guard mode watches each guarded port's incoming frames. Each argument: PORT/MAX/MODE/STICKY/BPDU/VID/MACS, MODE
 * s(hutdown) r(estrict) p(rotect) or n (no port security, BPDU guard only), MACS the secure addresses (hex, '+' between)
 * or '-'. A source address beyond MAX is a violation: shutdown err-disables the port (link down); restrict and protect
 * pin the address on the bridge as local, so nothing is forwarded to it any more. A BPDU on a BPDU-guard port
 * err-disables it. State: GUARD_RUN/PORT (kept across restarts: an err-disabled port stays so until cleared). */
#define GUARD_MACS 64
#ifndef GUARD_RUN
#define GUARD_RUN "/run/port-guard"  /* tests and the fuzzer build the agent with their own folder */
#endif
struct guard { char port[PORT_SIZE]; int fd, max, sticky, bpdu, vid; char mode; unsigned char macs[GUARD_MACS][6];
               char kinds[GUARD_MACS]; int count; unsigned violations; unsigned char last[6]; int disabled; char reason[24]; };
static int hex_mac(const char *text, unsigned char *mac) {
    if (strlen(text) != 12 || strspn(text, "0123456789abcdef") != 12) return 0;
    for (int i = 0; i < 6; i++) { unsigned value; sscanf(text + 2 * i, "%2x", &value); mac[i] = (unsigned char)value; }
    return 1;
}
static void guard_save(struct guard *g) {
    char path[256], temporary[264], text[2048]; size_t used = 0;
    snprintf(path, sizeof(path), GUARD_RUN "/%.5s", g->port); snprintf(temporary, sizeof(temporary), "%.255s.new", path);
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
/* One frame that came in on the port (N bytes, whatever a peer sent): a BPDU, a new MAC address or a violation. */
static void guard_frame(struct guard *g, const unsigned char *frame, size_t n) {
    static const unsigned char bpdu[6] = {0x01, 0x80, 0xc2, 0x00, 0x00, 0x00};
    if (n < 14) return;
    if (g->bpdu && !memcmp(frame, bpdu, 6)) { guard_disable(g, "bpduguard"); return; }
    if (g->mode == 'n' || (frame[6] & 1)) return;
    for (int m = 0; m < g->count; m++) if (!memcmp(g->macs[m], frame + 6, 6)) return;  /* a known address */
    if (g->count < g->max) {
        memcpy(g->macs[g->count], frame + 6, 6); g->kinds[g->count++] = g->sticky ? 'k' : 'd';
        guard_save(g); return;
    }
    int repeated = g->violations && !memcmp(g->last, frame + 6, 6);
    g->violations++; memcpy(g->last, frame + 6, 6);
    if (g->mode == 's') { guard_disable(g, "psecure-violation"); return; }
    if (!repeated) guard_pin(g, frame + 6);
    guard_save(g);
}
static int port_guard(int count, char **specs) {
    struct guard guards[MAX_PORTS]; struct pollfd waits[MAX_PORTS];
    if (count < 1 || count > MAX_PORTS) return 2;
    mkdir(GUARD_RUN, 0755);
    for (int i = 0; i < count; i++) {
        if (!guard_parse(specs[i], &guards[i])) return 2;
        char path[256], text[64] = {0}; snprintf(path, sizeof(path), GUARD_RUN "/%.5s", guards[i].port);
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
    for (;;) {
        for (int i = 0; i < count; i++) { waits[i].fd = guards[i].fd; waits[i].events = POLLIN; waits[i].revents = 0; }
        if (poll(waits, (nfds_t)count, -1) < 0) { if (errno == EINTR) continue; return 1; }
        for (int i = 0; i < count; i++) {
            struct guard *g = &guards[i];
            if (g->fd < 0 || !(waits[i].revents & POLLIN)) continue;
            unsigned char frame[2048]; struct sockaddr_ll from; socklen_t size = sizeof(from);
            ssize_t n = recvfrom(g->fd, frame, sizeof(frame), 0, (struct sockaddr *)&from, &size);
            if (n > 0 && from.sll_pkttype != PACKET_OUTGOING) guard_frame(g, frame, (size_t)n);
        }
    }
}
