/* Network LABS guest agent: the --dhcp-relay mode: DHCP relay (RFC 1542), as IOS « ip helper-address ».
 * Part of agent.c, which includes it: the agent is one compilation unit. */
static int port_address(const char *name, struct in_addr *address) {
    struct ifreq request; memset(&request, 0, sizeof(request));
    snprintf(request.ifr_name, sizeof(request.ifr_name), "%s", name);
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    int failed = fd < 0 || ioctl(fd, SIOCGIFADDR, &request) < 0;
    if (fd >= 0) close(fd);
    if (!failed) *address = ((struct sockaddr_in *)&request.ifr_addr)->sin_addr;
    return failed;
}
/* DHCP relay (RFC 1542), as IOS « ip helper-address » relays: a request broadcast on a helper port goes to the server
 * with giaddr set to that port's address (the server picks the pool by it and answers to it); a reply to one of those
 * addresses goes back out its port, broadcast, since the client has no address yet. The kernel routes to the server. */
static int dhcp_relay(const char *server_text, const char *clients_text) {
    struct in_addr server;
    char names[RELAY_PORTS][IFNAMSIZ]; unsigned indexes[RELAY_PORTS]; int count = 0;
    if (inet_pton(AF_INET, server_text, &server) != 1 || strlen(clients_text) >= 200) return 2;
    char copy[200]; strcpy(copy, clients_text);
    for (char *item = strtok(copy, ","); item; item = strtok(NULL, ",")) {
        if (count == RELAY_PORTS || !valid_interface(item)) return 2;
        snprintf(names[count], IFNAMSIZ, "%s", item);
        if (!(indexes[count] = if_nametoindex(item))) return 1;
        count++;
    }
    int fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0), on = 1;
    struct sockaddr_in local = {.sin_family = AF_INET, .sin_port = htons(67), .sin_addr.s_addr = htonl(INADDR_ANY)};
    if (!count || fd < 0 || setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on)) ||
        setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &on, sizeof(on)) || setsockopt(fd, IPPROTO_IP, IP_PKTINFO, &on, sizeof(on)) ||
        bind(fd, (struct sockaddr *)&local, sizeof(local))) return 1;
    for (;;) {
        unsigned char packet[1500]; char control[CMSG_SPACE(sizeof(struct in_pktinfo))];
        struct sockaddr_in from; struct iovec io = {packet, sizeof(packet)};
        struct msghdr message = {.msg_name = &from, .msg_namelen = sizeof(from), .msg_iov = &io, .msg_iovlen = 1,
                                 .msg_control = control, .msg_controllen = sizeof(control)};
        ssize_t n = recvmsg(fd, &message, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) return 1;
        static const unsigned char cookie[4] = {99, 130, 83, 99};
        if (n < 240 || memcmp(packet + 236, cookie, 4)) continue;
        unsigned arrived = 0;
        for (struct cmsghdr *c = CMSG_FIRSTHDR(&message); c; c = CMSG_NXTHDR(&message, c))
            if (c->cmsg_level == IPPROTO_IP && c->cmsg_type == IP_PKTINFO) arrived = ((struct in_pktinfo *)CMSG_DATA(c))->ipi_ifindex;
        struct in_addr gateway, address; memcpy(&gateway, packet + 24, 4);
        if (packet[0] == 1) {  /* BOOTREQUEST: only from a client on a helper port */
            int port = -1;
            for (int i = 0; i < count; i++) if (indexes[i] == arrived) port = i;
            if (port < 0 || packet[3] >= 16) continue;
            packet[3]++;
            if (!gateway.s_addr) {
                if (port_address(names[port], &address)) continue;
                memcpy(packet + 24, &address, 4);
            }
            struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = htons(67), .sin_addr = server};
            (void)sendto(fd, packet, (size_t)n, 0, (struct sockaddr *)&to, sizeof(to));
        } else if (packet[0] == 2) {  /* BOOTREPLY: to the helper port whose address is its giaddr */
            for (int i = 0; i < count; i++) {
                if (port_address(names[i], &address) || address.s_addr != gateway.s_addr) continue;
                struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = htons(68), .sin_addr.s_addr = htonl(INADDR_BROADCAST)};
                char out[CMSG_SPACE(sizeof(struct in_pktinfo))]; memset(out, 0, sizeof(out));
                struct iovec body = {packet, (size_t)n};
                struct msghdr reply_message = {.msg_name = &to, .msg_namelen = sizeof(to), .msg_iov = &body, .msg_iovlen = 1,
                                               .msg_control = out, .msg_controllen = sizeof(out)};
                struct cmsghdr *c = CMSG_FIRSTHDR(&reply_message);
                c->cmsg_level = IPPROTO_IP; c->cmsg_type = IP_PKTINFO; c->cmsg_len = CMSG_LEN(sizeof(struct in_pktinfo));
                struct in_pktinfo *info = (struct in_pktinfo *)CMSG_DATA(c);
                info->ipi_ifindex = (int)indexes[i]; info->ipi_spec_dst = address;
                (void)sendmsg(fd, &reply_message, 0);
                break;
            }
        }
    }
}
