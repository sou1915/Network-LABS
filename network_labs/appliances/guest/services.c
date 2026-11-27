/* Network LABS guest agent: the --services mode: DNS, NTP, Syslog and TFTP servers, and the NTP client.
 * Part of agent.c, which includes it: the agent is one compilation unit. */
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
