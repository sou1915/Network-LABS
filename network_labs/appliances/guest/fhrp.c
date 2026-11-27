/* Network LABS guest agent: what HSRP and VRRP share: a monotonic clock, rtnetlink (macvlan devices, addresses), sysctls, the IP checksum and state files.
 * Part of agent.c, which includes it: the agent is one compilation unit. */
static double monotonic_now(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}
static int nl_talk(void *message, unsigned length) {
    int fd = socket(AF_NETLINK, SOCK_RAW | SOCK_CLOEXEC, NETLINK_ROUTE);
    if (fd < 0) return errno;
    int result = EIO; char answer[512];
    if (send(fd, message, length, 0) == (ssize_t)length) {
        ssize_t n = recv(fd, answer, sizeof(answer), 0);
        struct nlmsghdr *header = (struct nlmsghdr *)answer;
        if (n >= (ssize_t)NLMSG_LENGTH(sizeof(struct nlmsgerr)) && header->nlmsg_type == NLMSG_ERROR)
            result = -((struct nlmsgerr *)NLMSG_DATA(header))->error;
    }
    close(fd);
    return result;
}
static struct rtattr *nl_put(struct nlmsghdr *header, unsigned short type, const void *data, unsigned size) {
    struct rtattr *attribute = (struct rtattr *)((char *)header + NLMSG_ALIGN(header->nlmsg_len));
    attribute->rta_type = type; attribute->rta_len = (unsigned short)RTA_LENGTH(size);
    if (size) memcpy(RTA_DATA(attribute), data, size);
    header->nlmsg_len = NLMSG_ALIGN(header->nlmsg_len) + RTA_ALIGN(attribute->rta_len);
    return attribute;
}
static void nl_close(struct nlmsghdr *header, struct rtattr *nest) {
    nest->rta_len = (unsigned short)((char *)header + header->nlmsg_len - (char *)nest);
}
/* A macvlan device NAME on port LOWER with MAC, up (`ip link add NAME link PORT address MAC type macvlan mode private`). */
static int macvlan_add(const char *name, int lower, const unsigned char *mac) {
    struct { struct nlmsghdr header; struct ifinfomsg link; char attributes[256]; } message;
    memset(&message, 0, sizeof(message));
    message.header.nlmsg_len = NLMSG_LENGTH(sizeof(struct ifinfomsg)); message.header.nlmsg_type = RTM_NEWLINK;
    message.header.nlmsg_flags = NLM_F_REQUEST | NLM_F_ACK | NLM_F_CREATE | NLM_F_EXCL;
    message.link.ifi_family = AF_UNSPEC; message.link.ifi_flags = IFF_UP; message.link.ifi_change = IFF_UP;
    __u32 link = (__u32)lower, mode = MACVLAN_MODE_PRIVATE;
    nl_put(&message.header, IFLA_LINK, &link, sizeof(link));
    nl_put(&message.header, IFLA_IFNAME, name, (unsigned)strlen(name) + 1);
    nl_put(&message.header, IFLA_ADDRESS, mac, 6);
    struct rtattr *info = nl_put(&message.header, IFLA_LINKINFO, NULL, 0);
    nl_put(&message.header, IFLA_INFO_KIND, "macvlan", 8);
    struct rtattr *data = nl_put(&message.header, IFLA_INFO_DATA, NULL, 0);
    nl_put(&message.header, IFLA_MACVLAN_MODE, &mode, sizeof(mode));
    nl_close(&message.header, data);
    nl_close(&message.header, info);
    return nl_talk(&message, message.header.nlmsg_len);
}
static int link_delete(const char *name) {
    struct { struct nlmsghdr header; struct ifinfomsg link; } message;
    memset(&message, 0, sizeof(message));
    message.header.nlmsg_len = sizeof(message); message.header.nlmsg_type = RTM_DELLINK;
    message.header.nlmsg_flags = NLM_F_REQUEST | NLM_F_ACK;
    message.link.ifi_family = AF_UNSPEC; message.link.ifi_index = (int)if_nametoindex(name);
    return message.link.ifi_index ? nl_talk(&message, sizeof(message)) : ENODEV;
}
static int host_address(int command, int index, struct in_addr address) {  /* ADDRESS/32 on (or off) a device */
    struct { struct nlmsghdr header; struct ifaddrmsg address; char attributes[32]; } message;
    memset(&message, 0, sizeof(message));
    message.header.nlmsg_len = NLMSG_LENGTH(sizeof(struct ifaddrmsg)); message.header.nlmsg_type = (unsigned short)command;
    message.header.nlmsg_flags = NLM_F_REQUEST | NLM_F_ACK | (command == RTM_NEWADDR ? NLM_F_CREATE | NLM_F_REPLACE : 0);
    message.address.ifa_family = AF_INET; message.address.ifa_prefixlen = 32; message.address.ifa_index = (unsigned)index;
    nl_put(&message.header, IFA_LOCAL, &address, 4);
    nl_put(&message.header, IFA_ADDRESS, &address, 4);
    return index ? nl_talk(&message, message.header.nlmsg_len) : ENODEV;
}
static void device_sysctl(const char *device, const char *key, const char *value) {
    char path[96]; snprintf(path, sizeof(path), "/proc/sys/net/ipv4/conf/%.15s/%s", device, key);
    int fd = open(path, O_WRONLY | O_CLOEXEC);
    if (fd < 0) return;
    ssize_t n = write(fd, value, strlen(value)); (void)n;
    close(fd);
}
static unsigned short ip_checksum(const unsigned char *data, size_t size, unsigned long sum) {
    for (size_t i = 0; i + 1 < size; i += 2) sum += (unsigned long)(data[i] << 8 | data[i + 1]);
    if (size & 1) sum += (unsigned long)data[size - 1] << 8;
    while (sum >> 16) sum = (sum & 0xffff) + (sum >> 16);
    return (unsigned short)~sum;
}
static int read_state_file(const char *path, char *text, size_t room) {
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 0;
    ssize_t n = read(fd, text, room - 1); close(fd);
    if (n <= 0) return 0;
    text[n] = 0;
    return 1;
}
static const char *state_field(const char *text, const char *key) {  /* the value after "\nKEY " (or at the start) */
    size_t size = strlen(key);
    for (const char *at = text; at && *at; at = strchr(at, '\n') ? strchr(at, '\n') + 1 : NULL)
        if (!strncmp(at, key, size) && at[size] == ' ') return at + size + 1;
    return "";
}
