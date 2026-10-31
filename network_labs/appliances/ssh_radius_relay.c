/* Bounded unprivileged SSH transport. Authentication/execution stay on host. */
#define _DEFAULT_SOURCE
#include <arpa/inet.h>
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>
#ifndef NL_BRIDGE_PORT
#define NL_BRIDGE_PORT 813
#endif
static volatile sig_atomic_t interrupted;
static double deadline;
static int tty_saved, flags0 = -1, flags1 = -1;
static struct termios original;
static void stop(int sig) { interrupted = sig; }
static double now(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) return 1e30;
    return ts.tv_sec + ts.tv_nsec / 1e9;
}
static int ready(int fd, int writing) {
    for (;;) {
        double left = deadline - now();
        if (interrupted || left <= 0 || fd >= FD_SETSIZE) return -1;
        struct timeval tv = {(long)left, (long)((left - (long)left) * 1e6)};
        fd_set fds; FD_ZERO(&fds); FD_SET(fd, &fds);
        int n = select(fd + 1, writing ? NULL : &fds, writing ? &fds : NULL, NULL, &tv);
        if (n > 0) return 0;
        if (n < 0 && errno == EINTR) continue;
        return -1;
    }
}
static int write_all(int fd, const void *data, size_t size) {
    const unsigned char *p = data;
    while (size) {
        if (ready(fd, 1)) return -1;
        ssize_t n = write(fd, p, size);
        if (n < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        if (n <= 0) return -1;
        p += n; size -= (size_t)n;
    }
    return 0;
}
static int line(int fd, char *out, size_t limit) {
    size_t n = 0;
    for (;;) {
        unsigned char c;
        if (ready(fd, 0)) return -1;
        ssize_t size = read(fd, &c, 1);
        if (size < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        if (size != 1) return -1;
        if (c == '\n') { out[n] = 0; return 0; }
        if (!c || c == '\r' || n >= limit) return -1;
        out[n++] = (char)c;
    }
}
static int value(unsigned char c) {
    if (c >= 'A' && c <= 'Z') return c - 'A';
    if (c >= 'a' && c <= 'z') return c - 'a' + 26;
    if (c >= '0' && c <= '9') return c - '0' + 52;
    if (c == '+') return 62;
    if (c == '/') return 63;
    return -1;
}
static int data_record(const char *text, size_t size) {
    unsigned char decoded[3072]; size_t used = 0;
    if (size % 4 || size > 4096) return -1;
    for (size_t i = 0; i < size; i += 4) {
        int a = value((unsigned char)text[i]), b = value((unsigned char)text[i + 1]);
        int c = text[i + 2] == '=' ? -2 : value((unsigned char)text[i + 2]);
        int d = text[i + 3] == '=' ? -2 : value((unsigned char)text[i + 3]);
        if (a < 0 || b < 0 || c == -1 || d == -1 || (c == -2 && d != -2) ||
            ((c == -2 || d == -2) && i + 4 != size)) return -1;
        decoded[used++] = (unsigned char)((a << 2) | (b >> 4));
        if (c >= 0) {
            decoded[used++] = (unsigned char)((b << 4) | (c >> 2));
            if (d >= 0) decoded[used++] = (unsigned char)((c << 6) | d);
        }
    }
    return write_all(STDOUT_FILENO, decoded, used);
}
static int terminal_stream(int fd) {
    unsigned char pending[8192], bytes[4096]; size_t length = 0, offset = 0, used = 0;
    char record[4097]; int input_eof = 0, half_closed = 0;
    for (;;) {
        double left = deadline - now();
        if (interrupted || left <= 0) return 125;
        if (input_eof && offset == length && !half_closed) {
            shutdown(fd, SHUT_WR); half_closed = 1;
        }
        fd_set reads, writes; FD_ZERO(&reads); FD_ZERO(&writes); FD_SET(fd, &reads);
        if (!input_eof && offset == length) FD_SET(STDIN_FILENO, &reads);
        if (offset < length) FD_SET(fd, &writes);
        struct timeval tv = {(long)left, (long)((left - (long)left) * 1e6)};
        int count = select(fd + 1, &reads, &writes, NULL, &tv);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) return 125;
        if (FD_ISSET(fd, &reads)) {
            ssize_t n = read(fd, bytes, sizeof(bytes));
            if (n == 0) return 125; /* No final status: never claim success. */
            if (n < 0 && errno != EINTR && errno != EAGAIN) return 125;
            for (ssize_t i = 0; i < n; i++) {
                if (bytes[i] != '\n') {
                    if (!bytes[i] || used == sizeof(record) - 1) return 125;
                    record[used++] = (char)bytes[i]; continue;
                }
                record[used] = 0;
                if (used && record[0] == 'D') {
                    if (data_record(record + 1, used - 1)) return 125;
                } else if (used >= 2 && used <= 4 && record[0] == 'E') {
                    unsigned code = 0;
                    for (size_t j = 1; j < used; j++) {
                        if (!isdigit((unsigned char)record[j])) return 125;
                        code = code * 10 + (unsigned)(record[j] - '0');
                    }
                    return code <= 255 ? (int)code : 125;
                } else return 125;
                used = 0;
            }
        }
        if (FD_ISSET(STDIN_FILENO, &reads)) {
            ssize_t n = read(STDIN_FILENO, pending, sizeof(pending));
            if (n > 0) { length = (size_t)n; offset = 0; }
            else if (n == 0) input_eof = 1;
            else if (errno != EINTR && errno != EAGAIN) return 125;
        }
        if (FD_ISSET(fd, &writes) && offset < length) {
            ssize_t n = write(fd, pending + offset, length - offset);
            if (n > 0) offset += (size_t)n;
            else if (n < 0 && errno != EINTR && errno != EAGAIN) return 125;
        }
    }
}
static int run(const char *action, unsigned seconds) {
    char username[65], password[129], header[256], status[33]; int result = 126, fd = -1;
    deadline = now() + seconds;
    struct sigaction sa; memset(&sa, 0, sizeof(sa)); sa.sa_handler = stop;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL); sigaction(SIGHUP, &sa, NULL); sigaction(SIGINT, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);
    if (isatty(STDIN_FILENO)) {
        if (tcgetattr(STDIN_FILENO, &original)) return 125;
        tty_saved = 1; struct termios hidden = original; hidden.c_lflag &= ~(ECHO | ECHONL);
        if (tcsetattr(STDIN_FILENO, TCSANOW, &hidden)) { result = 125; goto done; }
        if (write_all(STDERR_FILENO, "RADIUS username: ", 17)) goto done;
    }
    if (line(STDIN_FILENO, username, 64)) goto done;
    if (tty_saved && write_all(STDERR_FILENO, "\nRADIUS password: ", 18)) goto done;
    if (line(STDIN_FILENO, password, 128) || !*username || !*password) goto done;
    if (tty_saved && write_all(STDERR_FILENO, "\n", 1)) goto done;
    for (const unsigned char *p = (unsigned char *)username; *p; p++) {
        if (!isalnum(*p) && !strchr("_.@-", *p)) goto done;
    }
    fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0 || fd >= FD_SETSIZE || fcntl(fd, F_SETFL, O_NONBLOCK)) goto done;
    struct sockaddr_in peer; memset(&peer, 0, sizeof(peer)); peer.sin_family = AF_INET;
    peer.sin_port = htons(NL_BRIDGE_PORT); peer.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    int connected = connect(fd, (struct sockaddr *)&peer, sizeof(peer));
    if (connected && errno != EINPROGRESS) goto done;
    if (connected) {
        int error; socklen_t size = sizeof(error);
        if (ready(fd, 1) || getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &size) || error) goto done;
    }
    int size = snprintf(header, sizeof(header), "NLSSH1\n%s\n%s\n%s\n",
                        tty_saved && !strcmp(action, "shell") ? "shell-tty" : action, username, password);
    if (size < 0 || (size_t)size >= sizeof(header) || write_all(fd, header, (size_t)size)) goto done;
    memset(password, 0, sizeof(password)); memset(header, 0, sizeof(header));
    if (line(fd, status, 32)) goto done;
    if (!strcmp(status, "OK") && strcmp(action, "shell")) {
        unsigned char data[4096]; size_t total = 0;
        for (;;) {
            if (ready(fd, 0)) { result = 125; break; }
            ssize_t n = read(fd, data, sizeof(data));
            if (!n) { result = 0; break; }
            if (n < 0 && (errno == EINTR || errno == EAGAIN)) continue;
            if (n < 0 || total + (size_t)n > 4096 || write_all(STDOUT_FILENO, data, (size_t)n)) { result = 125; break; }
            total += (size_t)n;
        }
    } else if (!strcmp(status, "SHELL") && !strcmp(action, "shell")) {
        if (tty_saved) {
            struct termios raw = original; cfmakeraw(&raw);
            if (tcsetattr(STDIN_FILENO, TCSANOW, &raw)) { result = 125; goto done; }
        }
        flags0 = fcntl(STDIN_FILENO, F_GETFL); flags1 = fcntl(STDOUT_FILENO, F_GETFL);
        if (flags0 < 0 || flags1 < 0 || fcntl(STDIN_FILENO, F_SETFL, flags0 | O_NONBLOCK) ||
            fcntl(STDOUT_FILENO, F_SETFL, flags1 | O_NONBLOCK)) { result = 125; goto done; }
        result = terminal_stream(fd);
    }
done:
    if (fd >= 0) close(fd);
    if (flags0 >= 0) fcntl(STDIN_FILENO, F_SETFL, flags0);
    if (flags1 >= 0) fcntl(STDOUT_FILENO, F_SETFL, flags1);
    if (tty_saved) tcsetattr(STDIN_FILENO, TCSANOW, &original);
    if (interrupted) return 130;
    if (result == 126) fputs("SSH RADIUS request denied or unavailable.\n", stderr);
    return result;
}
int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--version")) { puts("Network LABS SSH relay 1"); return 0; }
    if (argc != 3 || (strcmp(argv[1], "shell") && strcmp(argv[1], "identity") &&
        strcmp(argv[1], "hostname") && strcmp(argv[1], "security-context"))) return 64;
    char *end; errno = 0; unsigned long seconds = strtoul(argv[2], &end, 10);
    if (errno || !*argv[2] || *end || seconds < 1 || seconds > 3615) return 64;
    return run(argv[1], (unsigned)seconds);
}
