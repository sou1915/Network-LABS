/* Network LABS guest agent: one-shot clients run for the host: DNS lookup, NTP query, Syslog send, HTTP GET, TFTP get and put.
 * Part of agent.c, which includes it: the agent is one compilation unit. */
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
