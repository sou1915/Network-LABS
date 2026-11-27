/* Network LABS guest protocol v1. No shell, arbitrary argv or TCP listener. */
#define _GNU_SOURCE
#include <sys/socket.h>
#include <arpa/inet.h>
#include <linux/vm_sockets.h>
#include <sys/wait.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <linux/sockios.h>
#include <linux/if_bridge.h>
#include <linux/netlink.h>
#include <linux/netfilter/nfnetlink.h>
#include <linux/rtnetlink.h>
#include <linux/neighbour.h>
#include <linux/if_vlan.h>
#include <linux/ethtool.h>
#include <linux/if_packet.h>
#include <poll.h>
#include <linux/netfilter/nf_tables.h>
#include <sys/time.h>
#include <net/if.h>
#include <dirent.h>
#include <sys/stat.h>
#include <time.h>
#include <signal.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#define LIMIT 32768
#define MAX_PORTS 16   /* eth0..eth15: Firecracker's MMIO interrupts hold 16 network devices beside the disk and vsock */
#define PORT_SIZE 6    /* "eth15" */
#define IFACE_SIZE 11  /* "eth15.4094" */
#define RELAY_PORTS MAX_PORTS

/* The agent is one compilation unit, one file per part (static functions, one gcc command, the tests include
 * this file to reach them). Each part may use what the parts before it define. */
#include "common.c"
#include "routing.c"
#include "port_guard.c"
#include "fhrp.c"
#include "hsrp.c"
#include "vrrp.c"
#include "services.c"
#include "clients.c"
#include "serve.c"
#include "dhcp_relay.c"

int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);
    if (argc == 2 && !strcmp(argv[1], "--stdio")) { serve(0, 1, 0); return 0; }
    if (argc == 4 && !strcmp(argv[1], "--dhcp-relay")) return dhcp_relay(argv[2], argv[3]);
    if (argc >= 3 && !strcmp(argv[1], "--port-guard")) return port_guard(argc - 2, argv + 2);
    if (argc >= 3 && !strcmp(argv[1], "--hsrp")) return hsrp(argc - 2, argv + 2);
    if (argc >= 3 && !strcmp(argv[1], "--vrrp")) return vrrp(argc - 2, argv + 2);
    if (argc >= 3 && !strcmp(argv[1], "--services")) return services(argc - 2, argv + 2);
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
