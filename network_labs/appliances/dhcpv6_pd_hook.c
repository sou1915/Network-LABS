/* Finite single-/64 PD gateway installation inside the requesting router. */
#include <arpa/inet.h>
#include <ctype.h>
#include <errno.h>
#include <ifaddrs.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#ifndef NL_PD_POLICY
#define NL_PD_POLICY "/lab/dhcpv6-pd.policy"
#endif
#ifndef NL_BUSYBOX
#define NL_BUSYBOX "/bin/busybox"
#endif
static int number(const char *s, unsigned long *v) {
    if (!s || !*s) return -1;
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) if (!isdigit(*p)) return -1;
    char *end; errno = 0; *v = strtoul(s, &end, 10);
    return errno || *end ? -1 : 0;
}
static int line(FILE *f, char *out, size_t size) {
    if (!fgets(out, (int)size, f)) return -1;
    char *end = strchr(out, '\n'); if (!end) return -1;
    *end = 0; return 0;
}
static int prefix(const char *s, struct in6_addr *out) {
    char text[80]; size_t n = s ? strlen(s) : 0;
    if (n < 4 || n >= sizeof(text) || strcmp(s + n - 3, "/64")) return -1;
    memcpy(text, s, n - 3); text[n - 3] = 0;
    if (inet_pton(AF_INET6, text, out) != 1) return -1;
    for (size_t i = 8; i < 16; i++) if (out->s6_addr[i]) return -1;
    return 0;
}
int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--version")) { puts("Network LABS DHCPv6 PD hook 1"); return 0; }
    if (argc != 2) return 64;
    int remove = !strcmp(argv[1], "deconfig");
    if (!remove && strcmp(argv[1], "bound") && strcmp(argv[1], "renew")) return 64;
    char port[16], network[80], maximum[16]; struct in6_addr expected, received;
    FILE *f = fopen(NL_PD_POLICY, "r"); if (!f) return 126;
    int bad = line(f, port, sizeof(port)) || line(f, network, sizeof(network)) || line(f, maximum, sizeof(maximum));
    int extra = fgetc(f); fclose(f);
    if (bad || extra != EOF || strncmp(port, "eth", 3) || strlen(port) < 4 || strlen(port) > 5) return 126;
    for (size_t i = 3; port[i]; i++) if (!isdigit((unsigned char)port[i])) return 126;
    unsigned long limit, lease = 0;
    if (number(maximum, &limit) || limit < 10 || limit > 3600 || prefix(network, &expected)) return 126;
    if (!remove) {
        if (prefix(getenv("ipv6prefix"), &received) || memcmp(&expected, &received, sizeof(expected)) ||
            number(getenv("ipv6prefix_lease"), &lease) || lease > limit) return 126;
        remove = lease == 0;
    }
    expected.s6_addr[15] = 1;
    char address[INET6_ADDRSTRLEN], cidr[80], lifetime[16];
    if (!inet_ntop(AF_INET6, &expected, address, sizeof(address))) return 126;
    snprintf(cidr, sizeof(cidr), "%s/64", address);
    snprintf(lifetime, sizeof(lifetime), "%lu", lease);
    if (remove) {
        struct ifaddrs *interfaces, *entry;
        int present = 0;
        if (getifaddrs(&interfaces)) return 125;
        for (entry = interfaces; entry; entry = entry->ifa_next) {
            if (entry->ifa_addr && entry->ifa_addr->sa_family == AF_INET6 && !strcmp(entry->ifa_name, port) &&
                !memcmp(&((struct sockaddr_in6 *)entry->ifa_addr)->sin6_addr, &expected, sizeof(expected))) {
                present = 1; break;
            }
        }
        freeifaddrs(interfaces);
        if (!present) return 0;
        char *args[] = {NL_BUSYBOX, "ip", "-6", "addr", "del", cidr, "dev", port, NULL};
        execv(NL_BUSYBOX, args);
    } else {
        char *args[] = {NL_BUSYBOX, "ip", "-6", "addr", "replace", cidr, "dev", port,
                        "valid_lft", lifetime, "preferred_lft", lifetime, NULL};
        execv(NL_BUSYBOX, args);
    }
    return 125;
}
