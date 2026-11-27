/* Network LABS guest agent: the --services mode: DNS by dnsmasq, NTP by chrony, and the Syslog collector and TFTP server
 * the agent keeps itself. Part of agent.c, which includes it: the agent is one compilation unit. */
/* Server services of a host or router guest, one --services process (this agent) for all of them:
 * - DNS: dnsmasq, an authoritative server for the lab's own names (A and CNAME records, PTR from the A records; any
 *   other name NXDOMAIN, no upstream server); the agent counts the queries dnsmasq logs.
 * - NTP: chrony. « ntp master N » or a server's NTP service: its local reference at stratum N; « ntp server A.B.C.D »:
 *   chrony keeps the association, read back with chronyc. The guest clock is never set (chronyd -x): the guest already
 *   runs the host's time; the association is measured and reported, as IOS's « show ntp » shows it.
 * - Syslog: the agent's collector (UDP 514, the last messages kept): it parses nothing, it keeps the printable text.
 * - TFTP: the agent's server (RFC 1350, reads and writes of plain names, 64 KiB at most): the standard servers either
 *   take no writes (dnsmasq) or come as a service of the host machine (tftpd-hpa), and the lab copies configurations up.
 * State in SERVICES_RUN/services.state, messages in SERVICES_RUN/syslog.log, dnsmasq's configuration beside them and
 * chrony's files in SERVICES_RUN/chrony (chronyd wants its command socket's folder private). */
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
/* The file name and mode of a read or write request (SIZE bytes from a peer), cut to fit NAME[80] and MODE[16]. */
static void tftp_request(const unsigned char *request, size_t size, char *name, char *mode) {
    size_t at = 2, used = 0;
    while (at < size && request[at] && used < 79) name[used++] = (char)request[at++];
    name[used] = 0; at++; used = 0;
    while (at < size && request[at] && used < 15) mode[used++] = (char)tolower(request[at++]);
    mode[used] = 0;
}
static void tftp_serve(const unsigned char *request, size_t size, struct sockaddr_in peer) {
    if (fork() != 0) return;
    char name[80], mode[16];
    tftp_request(request, size, name, mode);
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
/* dnsmasq's configuration for the DNS service: the lab's names only, answered with authority; any other name NXDOMAIN
 * (local=/#/: no upstream server); every query logged to standard error, where the agent counts them. The names and
 * addresses were checked by services_parse (valid_dns_name, inet_pton): nothing else reaches the file. */
static void dnsmasq_config(const struct services *s, char *out, size_t room) {
    size_t used = (size_t)snprintf(out, room, "port=53\nno-resolv\nno-hosts\nno-poll\nlocal=/#/\nlog-queries\nlog-facility=-\n"
                                   "user=root\ngroup=root\npid-file=\n");
    for (int i = 0; i < s->records && used < room; i++) {
        const struct service_record *r = &s->record[i];
        used += (size_t)snprintf(out + used, room - used, "%s=%s,%s\n", r->cname ? "cname" : "host-record", r->name, r->value);
    }
}
/* The lines dnsmasq wrote on FD (non-blocking): its queries counted into QUERIES, STARTED set once it says so. 0 at the
 * end of its output (dnsmasq has ended), else 1. */
static int dnsmasq_read(int fd, unsigned long *queries, int *started) {
    static char line[512];
    static size_t used;
    char chunk[1024];
    ssize_t n;
    while ((n = read(fd, chunk, sizeof(chunk))) > 0) {
        for (ssize_t i = 0; i < n; i++) {
            if (chunk[i] != '\n') {
                if (used < sizeof(line) - 1) {
                    line[used++] = chunk[i];
                }
                continue;
            }
            line[used] = 0;
            if (strstr(line, ": query[")) {
                (*queries)++;
            }
            if (strstr(line, ": started, version")) {
                *started = 1;
            }
            used = 0;
        }
    }
    return n != 0;
}
/* dnsmasq started for S, its output on *OUTPUT: its pid once it has started, or -1 (a port in use, a daemon missing). */
static pid_t dnsmasq_start(const struct services *s, int *output, unsigned long *queries) {
    static char config[16384];
    dnsmasq_config(s, config, sizeof(config));
    int pipes[2];
    if (write_file(SERVICES_RUN "/dnsmasq.conf", config, 0644) || pipe2(pipes, O_CLOEXEC)) {
        return -1;
    }
    char *const argv[] = {"dnsmasq", "--keep-in-foreground", "--conf-file=" SERVICES_RUN "/dnsmasq.conf", NULL};
    pid_t pid = spawn_child(DNSMASQ_PROGRAM, argv, pipes[1], NULL);
    close(pipes[1]);
    fcntl(pipes[0], F_SETFL, O_NONBLOCK);
    int started = 0;
    double deadline = monotonic_now() + 3;
    while (pid > 0 && !started && monotonic_now() < deadline) {
        struct pollfd wait = {pipes[0], POLLIN, 0};
        poll(&wait, 1, 100);
        if (!dnsmasq_read(pipes[0], queries, &started) && !started) {
            break;  /* dnsmasq ended before it started */
        }
    }
    if (!started) {
        stop_child(pid, 1);
        close(pipes[0]);
        return -1;
    }
    *output = pipes[0];
    return pid;
}
#define CHRONY_RUN SERVICES_RUN "/chrony"
/* chrony's configuration: « ntp master N »: its local reference at stratum N, served to everyone; « ntp server »: that
 * server, polled at once (iburst). Its command socket in CHRONY_RUN; no command port on the network. */
static void chrony_config(const struct services *s, char *out, size_t room) {
    size_t used = (size_t)snprintf(out, room, "bindcmdaddress " CHRONY_RUN "/chronyd.sock\npidfile " CHRONY_RUN "/chronyd.pid\n"
                                   "cmdport 0\n");
    if (s->ntp) {
        used += (size_t)snprintf(out + used, room - used, "local stratum %d\nallow\n", s->ntp);
    }
    if (s->sync.s_addr) {
        char server[16];
        inet_ntop(AF_INET, &s->sync, server, sizeof(server));
        snprintf(out + used, room - used, "server %s iburst\n", server);
    }
}
/* chronyd started for S, never setting the clock (-x): its pid once its command socket is there, or -1. */
static pid_t chronyd_start(const struct services *s) {
    char config[256];
    chrony_config(s, config, sizeof(config));
    mkdir(CHRONY_RUN, 0700);
    chmod(CHRONY_RUN, 0700);
    unlink(CHRONY_RUN "/chronyd.sock");
    if (write_file(CHRONY_RUN "/chrony.conf", config, 0600)) {
        return -1;
    }
    char *const argv[] = {"chronyd", "-x", "-d", "-u", "root", "-f", CHRONY_RUN "/chrony.conf", NULL};
    pid_t pid = spawn_child(CHRONYD_PROGRAM, argv, -1, NULL);
    double deadline = monotonic_now() + 3;
    while (child_running(pid) && access(CHRONY_RUN "/chronyd.sock", F_OK) && monotonic_now() < deadline) {
        pause_for(.05);
    }
    if (access(CHRONY_RUN "/chronyd.sock", F_OK)) {
        stop_child(pid, 1);
        return -1;
    }
    return pid;
}
/* A reference id of chronyc (8 hex digits) as IOS shows it: the four letters of a stratum 1 server (LOCL for chrony's
 * local reference, 7F7F0101), else an address. */
static void refid_text(const char *hex, int stratum, char *out, size_t room) {
    unsigned long value = strtoul(hex, NULL, 16);
    unsigned char bytes[4] = {(unsigned char)(value >> 24), (unsigned char)(value >> 16), (unsigned char)(value >> 8), (unsigned char)value};
    if (stratum == 1 && value == 0x7F7F0101UL) {
        snprintf(out, room, "LOCL");
    } else if (stratum == 1) {
        size_t used = 0;
        for (int i = 0; i < 4 && used < room - 1; i++) {
            if (bytes[i] > 32 && bytes[i] < 127) {
                out[used++] = (char)bytes[i];
            }
        }
        out[used] = 0;
        if (!used) {
            snprintf(out, room, "-");
        }
    } else {
        snprintf(out, room, "%u.%u.%u.%u", bytes[0], bytes[1], bytes[2], bytes[3]);
    }
}
/* What chronyc says now: the requests served (serverstats) and the association with « ntp server » (tracking, sources,
 * ntpdata), into K. Unchanged when chronyc does not answer. */
static void chrony_read(const struct services *s, struct service_counts *k) {
    char server[16] = "", ntpdata[32] = "", out[4096], field[64];
    char *argv[10] = {"chronyc", "-h", CHRONY_RUN "/chronyd.sock", "-c", "-n", "-m"};
    int count = 6;
    if (s->ntp) {
        argv[count++] = "serverstats";
    }
    if (s->sync.s_addr) {
        inet_ntop(AF_INET, &s->sync, server, sizeof(server));
        snprintf(ntpdata, sizeof(ntpdata), "ntpdata %s", server);
        argv[count++] = "tracking";
        argv[count++] = "sources";
        argv[count++] = ntpdata;
    }
    argv[count] = NULL;
    if (run_capture(CHRONYC_PROGRAM, argv, out, sizeof(out), 2) < 0) {
        return;
    }
    for (const char *line = out; *line; line = strchr(line, '\n') ? strchr(line, '\n') + 1 : line + strlen(line)) {
        if (s->ntp && strcspn(line, "\n") == strspn(line, "0123456789,") && csv_field(line, 16, field, sizeof(field))) {
            csv_field(line, 0, field, sizeof(field));  /* serverstats: NTP packets received first */
            k->ntp = strtoul(field, NULL, 10);
        }
    }
    if (!s->sync.s_addr) {
        return;
    }
    char name[32] = "", leap[32] = "";
    const char *tracking = NULL, *data = csv_line(out, server), *source = NULL;
    for (const char *line = out; *line; line = strchr(line, '\n') ? strchr(line, '\n') + 1 : line + strlen(line)) {
        if (csv_field(line, 13, leap, sizeof(leap)) && !csv_field(line, 14, field, sizeof(field)) && strlen(line) > 8
            && strspn(line, "0123456789ABCDEF") == 8 && line[8] == ',') {
            tracking = line;
        }
        if (strchr("^=#", line[0]) && line[1] == ',' && csv_field(line, 2, field, sizeof(field)) && !strcmp(field, server)) {
            source = line;
        }
    }
    k->synced = 0;
    if (tracking) {
        csv_field(tracking, 1, name, sizeof(name));
        csv_field(tracking, 13, leap, sizeof(leap));
        k->synced = !strcmp(name, server) && strcmp(leap, "Not synchronised") != 0;
    }
    if (data && csv_field(data, 19, field, sizeof(field))) {  /* ntpdata: stratum 8, reference 15, offset 18, delay 19 */
        csv_field(data, 8, field, sizeof(field));
        k->sync_stratum = atoi(field);
        csv_field(data, 15, field, sizeof(field));
        refid_text(field, k->sync_stratum, k->refid, sizeof(k->refid));
        csv_field(data, 18, field, sizeof(field));
        k->offset = atof(field);
        csv_field(data, 19, field, sizeof(field));
        k->delay = atof(field);
    }
    if (source && csv_field(source, 6, field, sizeof(field))) {
        k->synced_at = wall_now() - atof(field);
    }
}
static int services(int count, char **tokens) {
    static struct services s;
    struct service_counts k;
    memset(&k, 0, sizeof(k));
    if (!services_parse(count, tokens, &s)) {
        return 2;
    }
    struct sigaction caught;
    memset(&caught, 0, sizeof(caught));
    caught.sa_handler = services_caught;
    sigaction(SIGTERM, &caught, NULL);
    int logs = s.syslog ? udp_bound(514) : -1;
    int tftp = s.tftp ? udp_bound(69) : -1;
    if ((s.syslog && logs < 0) || (s.tftp && tftp < 0)) {
        return 1;
    }
    if (s.tftp) {
        mkdir(SERVICES_RUN "/tftp", 0755);
    }
    int dns_output = -1, timekeeping = s.ntp || s.sync.s_addr;
    pid_t dns = s.dns ? dnsmasq_start(&s, &dns_output, &k.dns) : 0;
    pid_t chrony = timekeeping ? chronyd_start(&s) : 0;
    if (dns < 0 || chrony < 0) {
        stop_child(dns, 2);
        stop_child(chrony, 2);
        return 1;
    }
    unlink(SERVICES_RUN "/syslog.log");
    double saved = 0;
    for (;;) {
        if (services_signal == SIGTERM) {
            stop_child(dns, 2);
            stop_child(chrony, 2);
            unlink(SERVICES_RUN "/services.state");
            return 0;
        }
        pid_t ended;
        while ((ended = waitpid(-1, NULL, WNOHANG)) > 0) {  /* the TFTP transfers, and a daemon that ended */
            if (ended == dns) {
                dns = 0;
            }
            if (ended == chrony) {
                chrony = 0;
            }
        }
        double now = wall_now();
        if (now - saved >= 1) {
            if (s.dns && dns <= 0) {  /* a daemon that ended starts again */
                if (dns_output >= 0) {
                    close(dns_output);
                }
                dns_output = -1;
                dns = dnsmasq_start(&s, &dns_output, &k.dns);
            }
            if (timekeeping && chrony <= 0) {
                chrony = chronyd_start(&s);
            }
            if (chrony > 0) {
                chrony_read(&s, &k);
            }
            services_save(&s, &k);
            saved = now;
        }
        struct pollfd waits[3] = {{logs, POLLIN, 0}, {tftp, POLLIN, 0}, {dns_output, POLLIN, 0}};
        if (poll(waits, 3, 200) < 0) {
            if (errno == EINTR) {
                continue;
            }
            return 1;
        }
        unsigned char in[1500];
        struct sockaddr_in from;
        socklen_t size = sizeof(from);
        if (waits[0].revents & POLLIN) {
            ssize_t n = recvfrom(logs, in, sizeof(in) - 1, 0, (struct sockaddr *)&from, &size);
            if (n > 0) {
                char source[16];
                inet_ntop(AF_INET, &from.sin_addr, source, sizeof(source));
                syslog_keep(source, in, (size_t)n);
                k.syslog++;
            }
        }
        size = sizeof(from);
        if (waits[1].revents & POLLIN) {
            ssize_t n = recvfrom(tftp, in, sizeof(in), 0, (struct sockaddr *)&from, &size);
            if (n >= 4 && in[0] == 0 && (in[1] == 1 || in[1] == 2)) {
                tftp_serve(in, (size_t)n, from);
                k.tftp++;
            }
        }
        if (waits[2].revents & (POLLIN | POLLHUP)) {
            int started = 1;
            if (!dnsmasq_read(dns_output, &k.dns, &started)) {
                close(dns_output);
                dns_output = -1;
            }
        }
    }
}
