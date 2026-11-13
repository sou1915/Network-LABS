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
static void serve(int input, int output) {
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
    if (argc == 2 && !strcmp(argv[1], "--stdio")) { serve(0, 1); return 0; }
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
        if (worker == 0) { close(server); serve(client, client); close(client); _exit(0); }
        close(client);
        if (worker > 0) while (waitpid(worker, NULL, 0) < 0 && errno == EINTR) {}
    }
}
