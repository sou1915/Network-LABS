/* Network LABS guest agent: the --dhcp-relay mode: DHCP relay (RFC 1542), as IOS « ip helper-address », by dnsmasq.
 * Part of agent.c, which includes it: the agent is one compilation unit. */
#ifndef DHCP_RELAY_RUN
#define DHCP_RELAY_RUN "/run"  /* tests build the agent with their own folder */
#endif
static int port_address(const char *name, struct in_addr *address) {
    struct ifreq request; memset(&request, 0, sizeof(request));
    snprintf(request.ifr_name, sizeof(request.ifr_name), "%.15s", name);
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    int failed = fd < 0 || ioctl(fd, SIOCGIFADDR, &request) < 0;
    if (fd >= 0) close(fd);
    if (!failed) *address = ((struct sockaddr_in *)&request.ifr_addr)->sin_addr;
    return failed;
}
static volatile sig_atomic_t relay_signal;
static void relay_caught(int number) { relay_signal = number; }
/* DHCP relay (RFC 1542), as IOS « ip helper-address » relays: dnsmasq takes a request broadcast on a helper port to the
 * server with giaddr set to that port's address (the server picks the pool by it and answers to it), and the reply back
 * out of that port. This agent keeps this command line (DHCP_RELAY_SHOW reads it), writes dnsmasq's configuration from the
 * helper ports' addresses, and starts dnsmasq again when one of them changes. bind-dynamic: dnsmasq shares port 67 with a
 * udhcpd pool of the same router, bound to its own port. */
static int dhcp_relay(const char *server_text, const char *clients_text) {
    struct in_addr server;
    char names[RELAY_PORTS][IFNAMSIZ]; int count = 0;
    if (inet_pton(AF_INET, server_text, &server) != 1 || strlen(clients_text) >= 200) return 2;
    char copy[200]; strcpy(copy, clients_text);
    for (char *item = strtok(copy, ","); item; item = strtok(NULL, ",")) {
        if (count == RELAY_PORTS || !valid_interface(item)) return 2;
        snprintf(names[count], IFNAMSIZ, "%s", item);
        if (!if_nametoindex(item)) return 1;
        count++;
    }
    if (!count) return 2;
    struct sigaction caught; memset(&caught, 0, sizeof(caught)); caught.sa_handler = relay_caught;
    sigaction(SIGTERM, &caught, NULL);
    static char running[2048];
    char config[2048], wanted[2048];
    pid_t relay = 0;
    for (;;) {
        if (relay_signal == SIGTERM) { stop_child(relay, 2); return 0; }
        size_t used = (size_t)snprintf(wanted, sizeof(wanted), "port=0\nbind-dynamic\nlog-facility=-\nuser=root\ngroup=root\npid-file=\n");
        int ports = 0;
        for (int i = 0; i < count; i++) {
            struct in_addr address; char local[16];
            if (port_address(names[i], &address)) continue;  /* a helper port without its address relays nothing yet */
            inet_ntop(AF_INET, &address, local, sizeof(local));
            used += (size_t)snprintf(wanted + used, sizeof(wanted) - used, "interface=%s\ndhcp-relay=%s,%s\n", names[i], local, server_text);
            ports++;
        }
        if (!child_running(relay)) relay = 0;
        if (strcmp(wanted, running) || (ports && !relay)) {
            stop_child(relay, 2);
            relay = 0;
            snprintf(config, sizeof(config), "%s", wanted);
            if (ports && !write_file(DHCP_RELAY_RUN "/dhcp-relay.conf", config, 0644)) {
                char *const argv[] = {"dnsmasq", "--keep-in-foreground", "--conf-file=" DHCP_RELAY_RUN "/dhcp-relay.conf", NULL};
                relay = spawn_child(DNSMASQ_PROGRAM, argv, -1, NULL);
                if (relay < 0) relay = 0;
            }
            snprintf(running, sizeof(running), "%s", wanted);
        }
        pause_for(1);
    }
}
