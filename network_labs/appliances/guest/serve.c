/* Network LABS guest agent: serve(): one typed request from the host (NL1 ...), checked, then done directly or by a fixed argv.
 * Part of agent.c, which includes it: the agent is one compilation unit. */
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
        char path[256]; snprintf(path, sizeof(path), GUARD_RUN "/%.5s", guard_port);
        if (unlink(path) && errno != ENOENT) { reply(output, 1, "port guard clear failed", 23); return; }
        reply(output, 0, "", 0); return;
    }
    if (!strcmp(request, "NL1 PORT_GUARD_SHOW")) {  /* "== PORT" then its state file, for each guarded port */
        static char listing[LIMIT]; size_t used = 0;
        for (int p = 0; p < MAX_PORTS; p++) {
            char path[256]; snprintf(path, sizeof(path), GUARD_RUN "/eth%d", p);
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
        static char listing[LIMIT]; size_t used = (size_t)snprintf(listing, sizeof(listing), "now %.1f\n", monotonic_now());
        DIR *folder = opendir(HSRP_RUN); struct dirent *entry;
        while (folder && (entry = readdir(folder)) && used < sizeof(listing) - 2048) {
            if (entry->d_name[0] == '.' || strstr(entry->d_name, ".new")) continue;
            char path[300], text[1024]; snprintf(path, sizeof(path), HSRP_RUN "/%.200s", entry->d_name);
            if (read_state_file(path, text, sizeof(text)))
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
        static char listing[LIMIT]; size_t used = (size_t)snprintf(listing, sizeof(listing), "now %.1f\n", monotonic_now());
        DIR *folder = opendir(VRRP_RUN); struct dirent *entry;
        while (folder && (entry = readdir(folder)) && used < sizeof(listing) - 1024) {
            if (entry->d_name[0] == '.' || strstr(entry->d_name, ".new")) continue;
            char path[300], text[512]; snprintf(path, sizeof(path), VRRP_RUN "/%.200s", entry->d_name);
            if (read_state_file(path, text, sizeof(text)))
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
