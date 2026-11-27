/* Network LABS guest agent: the --vrrp mode: VRRP version 2 (RFC 3768) groups on raw sockets.
 * Part of agent.c, which includes it: the agent is one compilation unit. */
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
    unsigned short sum = ip_checksum(p, 20, 0);
    p[6] = (unsigned char)(sum >> 8); p[7] = (unsigned char)sum;
    ip[0] = 0x45; ip[1] = 0xc0; ip[3] = 40; ip[8] = 255; ip[9] = 112;
    memcpy(ip + 12, &v->self, 4); memcpy(ip + 16, &group, 4);
    sum = ip_checksum(ip, 20, 0);
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
        if (if_nametoindex(v->vdev) || !macvlan_add(v->vdev, lower, v->vmac)) {  /* taken back from the previous instance, or made */
            v->macvlan = 1;
            device_sysctl(v->vdev, "rp_filter", "0");
            device_sysctl(v->iface, "arp_ignore", "1");  /* the port itself does not answer for the virtual address */
            device_sysctl(v->iface, "arp_announce", "2");  /* nor asks with it as sender: the hosts keep the virtual MAC */
            host_address(RTM_NEWADDR, (int)if_nametoindex(v->vdev), v->vip);
        } else {
            snprintf(v->vdev, sizeof(v->vdev), "-");
            host_address(RTM_NEWADDR, lower, v->vip);
        }
    }
    vrrp_garp(v); vrrp_garp(v);
}
static void vrrp_release(struct vrrp *v) {
    if (v->macvlan) link_delete(v->vdev);
    else if (!v->owner) host_address(RTM_DELADDR, (int)if_nametoindex(v->iface), v->vip);
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
/* One frame from the port (N bytes, whatever a peer sent): an advert of this group moves the state machine. */
static void vrrp_packet(struct vrrp *v, const unsigned char *frame, size_t n, double now) {
    if (n < 14 + 20 + 20 || frame[12] != 0x08 || frame[13] != 0x00) return;
    const unsigned char *ip = frame + 14;
    size_t header = (size_t)(ip[0] & 0x0f) * 4;
    if ((ip[0] >> 4) != 4 || header < 20 || ip[9] != 112 || ip[8] != 255 || n < 14 + header + 20) return;  /* TTL 255 only */
    struct in_addr source; memcpy(&source, ip + 12, 4);
    if (source.s_addr == v->self.s_addr) return;
    const unsigned char *p = ip + header;
    size_t message = 8 + 4 * (size_t)p[3] + 8;
    if (p[0] != 0x21 || p[1] != v->vrid || p[3] < 1 || n < 14 + header + message || ip_checksum(p, message, 0)) return;
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
static void vrrp_receive(struct vrrp *v, double now) {
    unsigned char frame[1600]; struct sockaddr_ll from; socklen_t size = sizeof(from);
    ssize_t n = recvfrom(v->fd, frame, sizeof(frame), 0, (struct sockaddr *)&from, &size);
    if (n > 0 && from.sll_pkttype != PACKET_OUTGOING) vrrp_packet(v, frame, (size_t)n, now);
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
    if (!read_state_file(path, text, sizeof(text))) return;
    struct in_addr previous = v->vip;
    sscanf(state_field(text, "vip"), "%15s", vip); sscanf(state_field(text, "state"), "%15s", state);
    sscanf(state_field(text, "vdev"), "%15s", vdev);
    v->changes = (unsigned)atol(state_field(text, "changes")); v->since = atof(state_field(text, "since"));
    int alike = inet_pton(AF_INET, vip, &previous) == 1 && previous.s_addr == v->vip.s_addr;
    if (!strcmp(state, "master")) {
        v->macvlan = atoi(state_field(text, "macvlan")); snprintf(v->vdev, sizeof(v->vdev), "%s", vdev);
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
        if (read_state_file(path, text, sizeof(text))) {
            struct vrrp old; char iface[IFACE_SIZE] = "";
            sscanf(state_field(text, "interface"), "%10s", iface); sscanf(state_field(text, "state"), "%15s", state);
            sscanf(state_field(text, "vip"), "%15s", vip); sscanf(state_field(text, "auth"), "%16s", auth);
            snprintf(spec, sizeof(spec), "%s/%d/%s/%d/n/%d/%s", iface, atoi(state_field(text, "group")), vip,
                     atoi(state_field(text, "priority")), atoi(state_field(text, "advert")) ? atoi(state_field(text, "advert")) : 1, auth);
            if (!strcmp(state, "master") && vrrp_parse(spec, &old)) {
                old.macvlan = atoi(state_field(text, "macvlan"));
                sscanf(state_field(text, "vdev"), "%15s", old.vdev);
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
    double now = monotonic_now(), saved = 0;
    for (int i = 0; i < count; i++) { vrrp_port(&groups[i]); vrrp_resume(&groups[i], now); }
    for (;;) {
        if (vrrp_signal == SIGUSR1) return 0;  /* the next instance takes the groups back */
        if (vrrp_signal == SIGTERM) {
            for (int i = 0; i < count; i++) {
                struct vrrp *v = &groups[i];
                if (v->state == VR_MASTER) { vrrp_send(v, 0); vrrp_release(v); }
                device_sysctl(v->iface, "arp_ignore", "0"); device_sysctl(v->iface, "arp_announce", "0");
                char path[256]; snprintf(path, sizeof(path), VRRP_RUN "/%.10s.%d", v->iface, v->vrid); unlink(path);
            }
            return 0;
        }
        now = monotonic_now();
        for (int i = 0; i < count; i++) vrrp_tick(&groups[i], now);
        if (now - saved >= 1) { for (int i = 0; i < count; i++) vrrp_save(&groups[i]); saved = now; }
        for (int i = 0; i < count; i++) { waits[i].fd = groups[i].fd; waits[i].events = POLLIN; waits[i].revents = 0; }
        if (poll(waits, (nfds_t)count, 100) < 0) { if (errno == EINTR) continue; return 1; }
        for (int i = 0; i < count; i++)
            if (groups[i].fd >= 0 && (waits[i].revents & POLLIN)) vrrp_receive(&groups[i], monotonic_now());
    }
}
