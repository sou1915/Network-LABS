/* Network LABS guest agent: the --hsrp mode: Cisco HSRP version 1 and 2 groups (hello, coup, resign) on raw sockets.
 * Part of agent.c, which includes it: the agent is one compilation unit. */
/* HSRP (IOS « standby »): this agent's --hsrp mode speaks HSRP on a router's LAN ports, version 1 (UDP 1985 to
 * 224.0.0.2, RFC 2281) or version 2 (224.0.0.102, TLVs). Each argument: IFACE/GROUP/VERSION/VIP/PRIORITY/PREEMPT/HELLO/
 * HOLD/AUTH, AUTH in hex. The routers of a group elect an active router (highest priority, then highest address; with
 * preempt a higher priority takes over by a coup) and a standby that takes over when the active one falls silent for the
 * hold time. The active router holds the virtual address on a macvlan device carrying the group's virtual MAC
 * (0000.0c07.acNN, version 2 0000.0c9f.fNNN): the hosts' gateway keeps its MAC across a failover, and a gratuitous ARP
 * moves it in the switches. A guest kernel without macvlan gets the address on the port itself. State:
 * HSRP_RUN/IFACE.GROUP. SIGTERM resigns and removes everything; SIGUSR1 leaves it to the next instance (a configuration
 * change), which takes the groups back in their state. */
#define HSRP_GROUPS 16
enum { HS_INIT = 0, HS_LISTEN = 2, HS_SPEAK = 4, HS_STANDBY = 8, HS_ACTIVE = 16 };
#ifndef HSRP_RUN
#define HSRP_RUN "/run/hsrp"  /* tests and the fuzzer build the agent with their own folder */
#endif
struct hsrp { char iface[IFACE_SIZE], vdev[IFNAMSIZ]; int group, version, priority, preempt, hello, hold, fd, state, macvlan;
              unsigned changes; struct in_addr vip, self, active, standby, speaker; int active_priority, standby_priority;
              unsigned char auth[8], mac[6], vmac[6]; double since, entered, next_hello, active_until, standby_until, speaker_until; };
static volatile sig_atomic_t hsrp_signal;
static void hsrp_caught(int number) { hsrp_signal = number; }
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
    unsigned short sum = ip_checksum(ip, 20, 0);
    ip[10] = (unsigned char)(sum >> 8); ip[11] = (unsigned char)sum;
    udp[0] = 0x07; udp[1] = 0xc1; udp[2] = 0x07; udp[3] = 0xc1; udp[4] = (unsigned char)(udp_size >> 8); udp[5] = (unsigned char)udp_size;
    unsigned long pseudo = 17 + udp_size;
    for (int i = 12; i < 20; i += 2) pseudo += (unsigned long)(ip[i] << 8 | ip[i + 1]);
    sum = ip_checksum(udp, udp_size, pseudo);
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
    if (if_nametoindex(h->vdev) || !macvlan_add(h->vdev, lower, h->vmac)) {  /* taken back from the previous instance, or made */
        h->macvlan = 1;
        device_sysctl(h->vdev, "rp_filter", "0");
        device_sysctl(h->iface, "arp_ignore", "1");  /* the port itself does not answer for the virtual address */
        device_sysctl(h->iface, "arp_announce", "2");  /* nor asks with it as sender: the hosts keep the virtual MAC */
        host_address(RTM_NEWADDR, (int)if_nametoindex(h->vdev), h->vip);
    } else {
        h->macvlan = 0; snprintf(h->vdev, sizeof(h->vdev), "-");
        host_address(RTM_NEWADDR, lower, h->vip);
    }
    hsrp_garp(h); hsrp_garp(h);
}
static void hsrp_release(struct hsrp *h) {
    if (h->macvlan) link_delete(h->vdev);
    else host_address(RTM_DELADDR, (int)if_nametoindex(h->iface), h->vip);
    h->macvlan = 0;
}
static const char *hsrp_state_name(int state) {
    return state == HS_ACTIVE ? "active" : state == HS_STANDBY ? "standby" : state == HS_SPEAK ? "speak"
         : state == HS_LISTEN ? "listen" : "init";
}
static void hsrp_save(struct hsrp *h, double now) {
    char path[256], temporary[264], text[1024], vip[16], active[16] = "-", standby[16] = "-", auth[17];
    snprintf(path, sizeof(path), HSRP_RUN "/%.10s.%d", h->iface, h->group);
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
/* One frame from the port (N bytes, whatever a peer sent): an HSRP message of this group moves the state machine. */
static void hsrp_packet(struct hsrp *h, const unsigned char *frame, size_t n, double now) {
    if (n < 14 + 20 + 8 + 20) return;
    const unsigned char *ip = frame + 14;
    size_t header = (size_t)(ip[0] & 0x0f) * 4;
    if ((ip[0] >> 4) != 4 || header < 20 || ip[9] != 17 || n < 14 + header + 8 + 20) return;
    const unsigned char *udp = ip + header, *p = udp + 8;
    if (udp[2] != 0x07 || udp[3] != 0xc1) return;
    struct in_addr source; memcpy(&source, ip + 12, 4);
    if (source.s_addr == h->self.s_addr) return;
    size_t room = n - 14 - header - 8;
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
static void hsrp_receive(struct hsrp *h, double now) {
    unsigned char frame[1600]; struct sockaddr_ll from; socklen_t size = sizeof(from);
    ssize_t n = recvfrom(h->fd, frame, sizeof(frame), 0, (struct sockaddr *)&from, &size);
    if (n > 0 && from.sll_pkttype != PACKET_OUTGOING) hsrp_packet(h, frame, (size_t)n, now);
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
/* A group of the previous instance: taken back in its state when it is still configured alike, else let go. */
static void hsrp_resume(struct hsrp *h, double now) {
    char path[256], text[1024], vip[16] = "", state[16] = "", vdev[IFNAMSIZ] = "";
    snprintf(path, sizeof(path), HSRP_RUN "/%.10s.%d", h->iface, h->group);
    if (!read_state_file(path, text, sizeof(text))) return;
    struct in_addr previous = h->vip;
    sscanf(state_field(text, "vip"), "%15s", vip); sscanf(state_field(text, "state"), "%15s", state);
    sscanf(state_field(text, "vdev"), "%15s", vdev);
    h->changes = (unsigned)atol(state_field(text, "changes")); h->since = atof(state_field(text, "since"));
    int alike = atoi(state_field(text, "version")) == h->version && inet_pton(AF_INET, vip, &previous) == 1
                && previous.s_addr == h->vip.s_addr;
    if (!strcmp(state, "active")) {
        h->macvlan = atoi(state_field(text, "macvlan")); snprintf(h->vdev, sizeof(h->vdev), "%s", vdev);
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
    DIR *folder = opendir(HSRP_RUN); struct dirent *entry;
    while (folder && (entry = readdir(folder))) {
        if (entry->d_name[0] == '.' || strstr(entry->d_name, ".new")) continue;
        int kept = 0;
        for (int i = 0; i < count && !kept; i++) {
            char name[24]; snprintf(name, sizeof(name), "%.10s.%d", groups[i].iface, groups[i].group);
            kept = !strcmp(name, entry->d_name);
        }
        if (kept) continue;
        char path[300], text[1024], state[16] = "", vip[16] = "", auth[17] = "", spec[160];
        snprintf(path, sizeof(path), HSRP_RUN "/%.200s", entry->d_name);
        if (read_state_file(path, text, sizeof(text))) {
            struct hsrp old; char iface[IFACE_SIZE] = "";
            sscanf(state_field(text, "interface"), "%10s", iface); sscanf(state_field(text, "state"), "%15s", state);
            sscanf(state_field(text, "vip"), "%15s", vip); sscanf(state_field(text, "auth"), "%16s", auth);
            snprintf(spec, sizeof(spec), "%s/%d/%d/%s/%d/n/3/10/%s", iface, atoi(state_field(text, "group")),
                     atoi(state_field(text, "version")), vip, atoi(state_field(text, "priority")), auth);
            if (!strcmp(state, "active") && hsrp_parse(spec, &old)) {
                old.macvlan = atoi(state_field(text, "macvlan"));
                sscanf(state_field(text, "vdev"), "%15s", old.vdev);
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
    mkdir(HSRP_RUN, 0755);
    struct sigaction caught; memset(&caught, 0, sizeof(caught)); caught.sa_handler = hsrp_caught;
    sigaction(SIGTERM, &caught, NULL); sigaction(SIGUSR1, &caught, NULL);
    hsrp_tidy(groups, count);
    double now = monotonic_now(), saved = 0;
    for (int i = 0; i < count; i++) { hsrp_port(&groups[i]); hsrp_resume(&groups[i], now); }
    for (;;) {
        if (hsrp_signal == SIGUSR1) return 0;  /* the next instance takes the groups back */
        if (hsrp_signal == SIGTERM) {
            for (int i = 0; i < count; i++) {
                struct hsrp *h = &groups[i];
                if (h->state == HS_ACTIVE) { hsrp_send(h, 2); hsrp_release(h); }
                device_sysctl(h->iface, "arp_ignore", "0"); device_sysctl(h->iface, "arp_announce", "0");
                char path[256]; snprintf(path, sizeof(path), HSRP_RUN "/%.10s.%d", h->iface, h->group); unlink(path);
            }
            return 0;
        }
        now = monotonic_now();
        for (int i = 0; i < count; i++) hsrp_tick(&groups[i], now);
        if (now - saved >= 1) { for (int i = 0; i < count; i++) hsrp_save(&groups[i], now); saved = now; }
        for (int i = 0; i < count; i++) { waits[i].fd = groups[i].fd; waits[i].events = POLLIN; waits[i].revents = 0; }
        if (poll(waits, (nfds_t)count, 100) < 0) { if (errno == EINTR) continue; return 1; }
        for (int i = 0; i < count; i++)
            if (groups[i].fd >= 0 && (waits[i].revents & POLLIN)) hsrp_receive(&groups[i], monotonic_now());
    }
}
