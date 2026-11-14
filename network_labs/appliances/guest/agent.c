/* Network LABS guest protocol v1. No shell, arbitrary argv or TCP listener. */
#define _GNU_SOURCE
#include <sys/socket.h>
#include <arpa/inet.h>
#include <linux/vm_sockets.h>
#include <sys/wait.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LIMIT 32768
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
static void serve(int input, int output, int mutations) {
    char request[64]; size_t used = 0;
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
    char *const addresses[] = {"busybox", "ip", "address", "show", NULL};
    char *const routes[] = {"busybox", "ip", "route", "show", NULL};
    char *const *args = NULL;
    char *const ping[] = {"busybox", "ping", "-c", "1", "-W", "1", request + 9, NULL};
    struct in_addr destination;
    if (!strncmp(request, "NL1 PING ", 9) && inet_pton(AF_INET, request + 9, &destination) == 1)
        args = ping;
    if (!strcmp(request, "NL1 ADDRESSES")) args = addresses;
    if (!strcmp(request, "NL1 ROUTES")) args = routes;
    char *const link_up[] = {"busybox", "ip", "link", "set", "dev", "eth0", "up", NULL};
    char *const link_down[] = {"busybox", "ip", "link", "set", "dev", "eth0", "down", NULL};
    /* Only the vsock daemon may change the guest; diagnostic stdio stays read-only. */
    if (mutations && !strcmp(request, "NL1 LINK eth0 up")) args = link_up;
    if (mutations && !strcmp(request, "NL1 LINK eth0 down")) args = link_down;
    char *const address_add[] = {"busybox", "ip", "address", "add", request + 13, "dev", "eth0", NULL};
    char *const address_delete[] = {"busybox", "ip", "address", "del", request + 13, "dev", "eth0", NULL};
    if (mutations && !strncmp(request, "NL1 ADDR_ADD ", 13) && valid_cidr(request + 13)) args = address_add;
    if (mutations && !strncmp(request, "NL1 ADDR_DEL ", 13) && valid_cidr(request + 13)) args = address_delete;
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
        execve("/bin/busybox", args, env); _exit(127);
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
int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);
    if (argc == 2 && !strcmp(argv[1], "--stdio")) { serve(0, 1, 0); return 0; }
    if (argc != 1) return 2;
    int server = socket(AF_VSOCK, SOCK_STREAM | SOCK_CLOEXEC, 0);
    struct sockaddr_vm address = {.svm_family=AF_VSOCK, .svm_cid=VMADDR_CID_ANY, .svm_port=19001};
    if (server < 0 || bind(server, (struct sockaddr *)&address, sizeof(address)) || listen(server, 4)) {
        perror("guest vsock"); return 1;
    }
    for (;;) {
        struct sockaddr_vm peer; socklen_t size = sizeof(peer);
        int client = accept4(server, (struct sockaddr *)&peer, &size, SOCK_CLOEXEC);
        if (client < 0) { if (errno == EINTR) continue; return 1; }
        if (peer.svm_cid != VMADDR_CID_HOST) { close(client); continue; }
        pid_t worker = fork();
        if (worker == 0) { close(server); serve(client, client, 1); close(client); _exit(0); }
        close(client);
        if (worker > 0) while (waitpid(worker, NULL, 0) < 0 && errno == EINTR) {}
    }
}
