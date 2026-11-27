/* Network LABS guest agent: the --vrrp mode: VRRP version 2 (RFC 3768) by keepalived.
 * Part of agent.c, which includes it: the agent is one compilation unit. */
/* VRRP (IOS « vrrp »): keepalived speaks VRRP on a router's LAN ports; this agent's --vrrp mode writes its configuration,
 * starts it and reads its state back for « show vrrp ». Each argument: IFACE/VRID/VIP/PRIORITY/PREEMPT/ADVERT/AUTH, AUTH
 * in hex (simple text authentication) or - for none. As IOS does: adverts every ADVERT seconds from the virtual MAC
 * 0000.5e00.01NN, which the master holds on a macvlan device (keepalived's use_vmac) with the virtual address; the port
 * itself does not answer ARP for it (arp_ignore), so the hosts keep the virtual MAC. The router whose own address is the
 * virtual one owns the group: priority 255, master at once, adverts from its port. State: VRRP_RUN/IFACE.VRID, in the
 * format VRRP_SHOW lists. SIGTERM stops keepalived, which resigns (adverts of priority 0) and removes its addresses and
 * devices; SIGUSR1 leaves keepalived running for the next instance (a configuration change), which reloads it (SIGHUP): the
 * groups keep their state. */
#ifndef VRRP_RUN
#define VRRP_RUN "/run/vrrp"  /* tests build the agent with their own folder */
#endif
#define VRRP_DAEMON VRRP_RUN "/.keepalived"  /* keepalived's files (VRRP_SHOW skips names starting with a dot) */
#define VRRP_GROUPS 16
enum { VR_INIT = 0, VR_BACKUP = 1, VR_MASTER = 2 };
struct vrrp { char iface[IFACE_SIZE], vdev[IFNAMSIZ], master[16]; int vrid, priority, preempt, advert, authtype, owner, state;
              int master_priority; unsigned changes; struct in_addr vip, self; unsigned char auth[8];
              double since, down_at, next_advert, transition; };
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
    memset(v, 0, sizeof(*v));
    snprintf(v->iface, sizeof(v->iface), "%s", fields[0]);
    v->vrid = atoi(fields[1]); v->priority = atoi(fields[3]); v->advert = atoi(fields[5]);
    if (v->vrid < 1 || v->vrid > 255 || v->priority < 1 || v->priority > 255 || v->advert < 1 || v->advert > 255
        || inet_pton(AF_INET, fields[2], &v->vip) != 1 || strlen(fields[4]) != 1 || !strchr("yn", fields[4][0])) return 0;
    if (strcmp(fields[6], "-")) {
        size_t hex = strlen(fields[6]);
        if (hex < 2 || hex > 16 || hex % 2 || strspn(fields[6], "0123456789abcdef") != hex) return 0;
        for (size_t i = 0; i < hex / 2; i++) { unsigned value; sscanf(fields[6] + 2 * i, "%2x", &value); v->auth[i] = (unsigned char)value; }
        for (size_t i = 0; i < hex / 2; i++)  /* the text keepalived's configuration quotes: printable, no quote or backslash */
            if (v->auth[i] < 33 || v->auth[i] > 126 || v->auth[i] == '"' || v->auth[i] == '\\') return 0;
        v->authtype = 1;
    }
    v->preempt = fields[4][0] == 'y';
    return 1;
}
/* The port's primary address (none: 0.0.0.0) and whether this router owns the group (its address is the virtual one). */
static void vrrp_port(struct vrrp *v) {
    struct ifreq query; memset(&query, 0, sizeof(query));
    snprintf(query.ifr_name, sizeof(query.ifr_name), "%s", v->iface);
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    v->self.s_addr = 0;
    if (fd >= 0 && ioctl(fd, SIOCGIFADDR, &query) == 0) v->self = ((struct sockaddr_in *)&query.ifr_addr)->sin_addr;
    if (fd >= 0) close(fd);
    v->owner = v->self.s_addr && v->self.s_addr == v->vip.s_addr;
    snprintf(v->vdev, sizeof(v->vdev), "vrrp%u-%d", if_nametoindex(v->iface), v->vrid);
}
/* keepalived's configuration for GROUPS, from the checked fields only: 0, or -1 when it does not fit. */
static int keepalived_config(const struct vrrp *groups, int count, char *out, size_t room) {
    size_t used = (size_t)snprintf(out, room, "global_defs {\n    router_id network-labs\n    vrrp_version 2\n}\n");
    for (int i = 0; i < count && used < room; i++) {
        const struct vrrp *v = &groups[i];
        char vip[16], self[16];
        inet_ntop(AF_INET, &v->vip, vip, sizeof(vip));
        inet_ntop(AF_INET, &v->self, self, sizeof(self));
        used += (size_t)snprintf(out + used, room - used,
            "vrrp_instance %.10s.%d {\n    state %s\n    interface %.10s\n    virtual_router_id %d\n    priority %d\n    advert_int %d\n",
            v->iface, v->vrid, v->owner ? "MASTER" : "BACKUP", v->iface, v->vrid, v->owner ? 255 : v->priority, v->advert);
        if (used >= room) break;
        if (v->owner) {  /* keepalived sees its own address as the virtual one only: it sends from it */
            used += (size_t)snprintf(out + used, room - used, "    mcast_src_ip %s\n", self);
        } else {
            used += (size_t)snprintf(out + used, room - used, "    use_vmac %s\n", v->vdev);
            if (!v->preempt && used < room) used += (size_t)snprintf(out + used, room - used, "    nopreempt\n");
        }
        if (v->authtype && used < room)
            used += (size_t)snprintf(out + used, room - used, "    authentication {\n        auth_type PASS\n        auth_pass \"%.8s\"\n    }\n",
                                     (const char *)v->auth);
        if (used < room) used += (size_t)snprintf(out + used, room - used, "    virtual_ipaddress {\n        %s/32\n    }\n}\n", vip);
    }
    return used < room ? 0 : -1;
}
static void vrrp_save(const struct vrrp *v) {
    char path[256], text[640], vip[16], auth[17] = "-";
    snprintf(path, sizeof(path), VRRP_RUN "/%.10s.%d", v->iface, v->vrid);
    inet_ntop(AF_INET, &v->vip, vip, sizeof(vip));
    if (v->authtype) for (int i = 0; i < 8; i++) snprintf(auth + 2 * i, 3, "%02x", v->auth[i]);
    static const char *names[3] = {"init", "backup", "master"};
    int master = v->state == VR_MASTER, macvlan = master && !v->owner;
    snprintf(text, sizeof(text),
        "interface %.10s\ngroup %d\nvip %.15s\nvdev %.15s\nmacvlan %d\nstate %s\npriority %d\npreempt %c\nadvert %d\nauth %.16s\nchanges %u\n"
        "since %.1f\nmaster %.15s %d %d\ndown %.1f\nnext %.1f\ntransition %.6f\n",
        v->iface, v->vrid, vip, macvlan ? v->vdev : "-", macvlan, names[v->state], v->owner ? 255 : v->priority, v->preempt ? 'y' : 'n',
        v->advert, auth, v->changes, v->since, master ? "local" : v->state == VR_BACKUP && v->master[0] ? v->master : "-",
        master ? (v->owner ? 255 : v->priority) : v->master_priority, v->advert, v->state == VR_BACKUP ? v->down_at : 0.0,
        master ? v->next_advert : 0.0, v->transition);
    write_file(path, text, 0644);
}
/* A previous instance's count of changes, kept across a hand-over. */
static void vrrp_resume(struct vrrp *v) {
    char path[256], text[640];
    snprintf(path, sizeof(path), VRRP_RUN "/%.10s.%d", v->iface, v->vrid);
    if (!read_state_file(path, text, sizeof(text))) return;
    char state[16] = "";
    sscanf(state_field(text, "state"), "%15s", state);
    v->state = !strcmp(state, "master") ? VR_MASTER : !strcmp(state, "backup") ? VR_BACKUP : VR_INIT;
    v->changes = (unsigned)atol(state_field(text, "changes"));
    v->since = atof(state_field(text, "since"));
    v->transition = atof(state_field(text, "transition"));
}
/* A group's state as keepalived's dump shows it (SEEN, entered at the wall-clock time SEEN_AT): a change counts when the
 * state differs, not when only the time does (keepalived's reload restarts its clock without a change). */
static void vrrp_seen(struct vrrp *v, int seen, double seen_at, double offset) {
    if (!v || seen == v->state) return;
    v->state = seen; v->changes++;
    v->transition = seen_at;
    v->since = seen_at > 0 ? seen_at + offset : monotonic_now();
}
/* The state of GROUPS from keepalived's data dump (SIGUSR1 to its VRRP process writes VRRP_DAEMON/keepalived.data):
 * 1 once read. Its times are wall-clock ones; the state files hold the agent's monotonic ones, as VRRP_SHOW's « now ». */
static int vrrp_dump(struct vrrp *groups, int count) {
    pid_t worker = pidfile_alive(VRRP_DAEMON "/vrrp.pid");
    struct stat before;
    if (!worker) return 0;
    if (stat(VRRP_DAEMON "/keepalived.data", &before)) before.st_mtim.tv_sec = 0;
    if (kill(worker, SIGUSR1)) return 0;
    struct stat after;
    for (int tries = 0; tries < 20; tries++) {
        pause_for(.025);
        if (!stat(VRRP_DAEMON "/keepalived.data", &after)
            && (after.st_mtim.tv_sec != before.st_mtim.tv_sec || after.st_mtim.tv_nsec != before.st_mtim.tv_nsec)) break;
    }
    pause_for(.02);  /* the rest of the dump */
    FILE *dump = fopen(VRRP_DAEMON "/keepalived.data", "re");
    if (!dump) return 0;
    double offset = monotonic_now() - wall_now(), seen_at = 0;  /* OFFSET: wall-clock times to monotonic ones */
    char line[256], name[32], value[128];
    struct vrrp *v = NULL;
    int seen = VR_INIT;
    while (fgets(line, sizeof(line), dump)) {
        if (sscanf(line, " VRRP Instance = %31s", name) == 1) {
            vrrp_seen(v, seen, seen_at, offset);
            v = NULL;
            for (int i = 0; i < count; i++) {
                char wanted[32]; snprintf(wanted, sizeof(wanted), "%.10s.%d", groups[i].iface, groups[i].vrid);
                if (!strcmp(wanted, name)) v = &groups[i];
            }
            if (v) { v->master[0] = 0; v->master_priority = 0; seen = VR_INIT; seen_at = 0; }
            continue;
        }
        if (!strncmp(line, "------<", 7)) { vrrp_seen(v, seen, seen_at, offset); v = NULL; }  /* the next section of the dump */
        if (!v || sscanf(line, " %31[^=]= %127[^\n]", name, value) != 2) continue;
        for (size_t end = strlen(name); end && name[end - 1] == ' '; end--) name[end - 1] = 0;
        if (!strcmp(name, "State")) {
            seen = !strcmp(value, "MASTER") ? VR_MASTER : !strcmp(value, "BACKUP") ? VR_BACKUP : VR_INIT;  /* FAULT, STOP: Init */
        } else if (!strcmp(name, "Master router")) {
            struct in_addr check;
            if (inet_pton(AF_INET, value, &check) == 1) inet_ntop(AF_INET, &check, v->master, sizeof(v->master));
        } else if (!strcmp(name, "Master priority")) {
            v->master_priority = atoi(value);
        } else if (!strcmp(name, "Last transition")) {
            seen_at = atof(value);
        } else if (!strcmp(name, "Read timeout")) {
            v->down_at = atof(value) + offset;
        } else if (!strcmp(name, "Last advert sent")) {
            v->next_advert = atof(value) + offset + v->advert;
        }
    }
    vrrp_seen(v, seen, seen_at, offset);
    fclose(dump);
    return 1;
}
/* keepalived running with VRRP_DAEMON/keepalived.conf: reloaded when it already runs (a hand-over), else started. */
static int keepalived_run(void) {
    pid_t running = pidfile_alive(VRRP_DAEMON "/keepalived.pid");
    if (running) return kill(running, SIGHUP);
    char *const argv[] = {"keepalived", "--vrrp", "--dont-fork", "--log-console", "--no-syslog", "--use-file=" VRRP_DAEMON "/keepalived.conf",
                          "--pid=" VRRP_DAEMON "/keepalived.pid", "--vrrp_pid=" VRRP_DAEMON "/vrrp.pid", NULL};
    char *const env[] = {"PATH=/bin:/sbin:/usr/bin:/usr/sbin", "LC_ALL=C", "TMPDIR=" VRRP_DAEMON, NULL};  /* where it dumps its data */
    if (spawn_daemon(KEEPALIVED_PROGRAM, argv, env)) return -1;
    for (int tries = 0; tries < 60 && !pidfile_alive(VRRP_DAEMON "/vrrp.pid"); tries++) pause_for(.05);
    return pidfile_alive(VRRP_DAEMON "/vrrp.pid") ? 0 : -1;
}
/* What a stopped or vanished instance left: keepalived stopped (it resigns its groups and removes their addresses and
 * devices) and the state files of the groups not in GROUPS removed. */
static void vrrp_tidy(struct vrrp *groups, int count) {
    if (!count) stop_daemon(pidfile_alive(VRRP_DAEMON "/keepalived.pid"), 1.5);
    DIR *folder = opendir(VRRP_RUN); struct dirent *entry;
    while (folder && (entry = readdir(folder))) {
        if (entry->d_name[0] == '.' || strstr(entry->d_name, ".new")) continue;
        int kept = 0;
        for (int i = 0; i < count && !kept; i++) {
            char name[24]; snprintf(name, sizeof(name), "%.10s.%d", groups[i].iface, groups[i].vrid);
            kept = !strcmp(name, entry->d_name);
        }
        if (kept) continue;
        char path[300]; snprintf(path, sizeof(path), VRRP_RUN "/%.200s", entry->d_name);
        unlink(path);
    }
    if (folder) closedir(folder);
}
static int vrrp(int count, char **specs) {
    static struct vrrp groups[VRRP_GROUPS];
    static char config[16384];
    if (count < 1 || count > VRRP_GROUPS) return 2;
    for (int i = 0; i < count; i++) {
        if (!vrrp_parse(specs[i], &groups[i])) return 2;
        for (int j = 0; j < i; j++)
            if (!strcmp(groups[i].iface, groups[j].iface) && groups[i].vrid == groups[j].vrid) return 2;
    }
    mkdir(VRRP_RUN, 0755);
    mkdir(VRRP_DAEMON, 0700);
    struct sigaction caught; memset(&caught, 0, sizeof(caught)); caught.sa_handler = vrrp_caught;
    sigaction(SIGTERM, &caught, NULL); sigaction(SIGUSR1, &caught, NULL);
    vrrp_tidy(groups, count);
    for (int i = 0; i < count; i++) { vrrp_port(&groups[i]); vrrp_resume(&groups[i]); }
    for (;;) {  /* (re)configured: at the start, and when a port's address changes who owns a group */
        for (int i = 0; i < count; i++) {
            if (!groups[i].owner) {
                device_sysctl(groups[i].iface, "arp_ignore", "1");  /* the port itself does not answer for the virtual address */
                device_sysctl(groups[i].iface, "arp_announce", "2");  /* nor asks with it as sender: the hosts keep the virtual MAC */
            }
        }
        if (keepalived_config(groups, count, config, sizeof(config)) || write_file(VRRP_DAEMON "/keepalived.conf", config, 0600)
            || keepalived_run()) return 1;
        double saved = 0;
        int reconfigure = 0;
        while (!reconfigure) {
            if (vrrp_signal == SIGUSR1) return 0;  /* the next instance reloads keepalived */
            if (vrrp_signal == SIGTERM) {
                stop_daemon(pidfile_alive(VRRP_DAEMON "/keepalived.pid"), 1.5);
                for (int i = 0; i < count; i++) {
                    device_sysctl(groups[i].iface, "arp_ignore", "0"); device_sysctl(groups[i].iface, "arp_announce", "0");
                    char path[256]; snprintf(path, sizeof(path), VRRP_RUN "/%.10s.%d", groups[i].iface, groups[i].vrid); unlink(path);
                }
                return 0;
            }
            if (monotonic_now() - saved >= 1) {
                if (!pidfile_alive(VRRP_DAEMON "/keepalived.pid") && keepalived_run()) return 1;  /* keepalived ended: again */
                for (int i = 0; i < count; i++) {
                    int owner = groups[i].owner; struct in_addr self = groups[i].self;
                    vrrp_port(&groups[i]);
                    if (groups[i].owner != owner || (groups[i].owner && groups[i].self.s_addr != self.s_addr)) reconfigure = 1;
                }
                if (vrrp_dump(groups, count)) for (int i = 0; i < count; i++) vrrp_save(&groups[i]);
                saved = monotonic_now();
            }
            pause_for(.1);
        }
    }
}
