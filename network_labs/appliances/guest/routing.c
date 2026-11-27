/* Network LABS guest agent: BIRD (OSPF, RIP) and FRR (BGP, EIGRP) configuration rendered from typed fields.
 * Part of agent.c, which includes it: the agent is one compilation unit. */
/* OSPFv2 area 0 with BIRD 2. The daemon configuration is written here, from typed fields only:
   "ROUTER_ID HELLO DEAD PORT:COST:STUB:TYPE:PRIORITY[,...]" with STUB y|n and TYPE p (point-to-point) or b (broadcast). */
/* eBGP with FRR (zebra and bgpd). The configuration is written here from typed fields only:
   "ASN ROUTER_ID ADDRESS:REMOTE_AS[,...] PREFIX[,...]|-". The networks are announced only if they are in the
   routing table (FRR's import check), as on a real router. */
static int valid_asn(const char *value) {
    if (!value[0] || value[0] == '0' || strspn(value, "0123456789") != strlen(value) || strlen(value) > 10) return 0;
    unsigned long long number = strtoull(value, NULL, 10); return number >= 1 && number <= 4294967295ULL;
}
static int bgp_render(const char *fields, char *out, size_t size) {
    char asn[11], rid[16], peers[120], networks[160], extra;
    if (sscanf(fields, "%10s %15s %119s %159s %c", asn, rid, peers, networks, &extra) != 4) return -1;
    if (!valid_asn(asn) || !valid_ipv4(rid)) return -1;
    int n = snprintf(out, size, "frr defaults traditional\nrouter bgp %s\n bgp router-id %s\n no bgp ebgp-requires-policy\n", asn, rid);
    int count = 0;
    for (char *item = strtok(peers, ","); item; item = strtok(NULL, ",")) {
        char address[16], remote[11], tail;
        if (++count > 4 || sscanf(item, "%15[^:]:%10[0-9]%c", address, remote, &tail) != 2) return -1;
        if (!valid_ipv4(address) || !valid_asn(remote) || !strcmp(remote, asn)) return -1;
        n += snprintf(out + n, size - (size_t)n, " neighbor %s remote-as %s\n neighbor %s timers 3 9\n neighbor %s timers connect 5\n",
                      address, remote, address, address);
        if (n >= (int)size - 64) return -1;
    }
    if (!count) return -1;
    n += snprintf(out + n, size - (size_t)n, " address-family ipv4 unicast\n");
    if (strcmp(networks, "-")) {
        int announced = 0;
        for (char *item = strtok(networks, ","); item; item = strtok(NULL, ",")) {
            if (++announced > 8 || !valid_cidr(item)) return -1;
            n += snprintf(out + n, size - (size_t)n, "  network %s\n", item);
            if (n >= (int)size - 64) return -1;
        }
    }
    n += snprintf(out + n, size - (size_t)n, " exit-address-family\n");
    return n;
}
/* EIGRP with FRR (zebra and eigrpd), from typed fields only: "AS ROUTER_ID NET[,NET...] PORT[,PORT...]|-". */
static int eigrp_render(const char *fields, char *out, size_t size) {
    char asn[6], rid[16], networks[160], passive[100], extra;
    if (sscanf(fields, "%5s %15s %159s %99s %c", asn, rid, networks, passive, &extra) != 4) return -1;
    if (!valid_asn(asn) || atol(asn) > 65535 || !valid_ipv4(rid)) return -1;
    int n = snprintf(out, size, "frr defaults traditional\nrouter eigrp %s\n eigrp router-id %s\n", asn, rid);
    int count = 0;
    for (char *item = strtok(networks, ","); item; item = strtok(NULL, ",")) {
        if (++count > 8 || !valid_cidr(item)) return -1;
        n += snprintf(out + n, size - (size_t)n, " network %s\n", item);
        if (n >= (int)size - 64) return -1;
    }
    if (!count) return -1;
    if (strcmp(passive, "-")) {
        int ports = 0;
        for (char *item = strtok(passive, ","); item; item = strtok(NULL, ",")) {
            if (++ports > MAX_PORTS || !valid_port(item)) return -1;
            n += snprintf(out + n, size - (size_t)n, " passive-interface %s\n", item);
        }
    }
    return n;
}
static int ospf_render(const char *fields, char *out, size_t size) {
    char rid[16], list[400], extra; unsigned hello, dead;
    if (sscanf(fields, "%15s %u %u %399s %c", rid, &hello, &dead, list, &extra) != 4) return -1;
    if (!valid_ipv4(rid) || hello < 1 || hello > 60 || dead < 2 || dead > 240 || dead <= hello) return -1;
    int n = snprintf(out, size, "router id %s;\nlog stderr all;\nprotocol device { scan time 1; }\n"
                     "protocol kernel kernel4 { scan time 1; ipv4 { import none; export where source = RTS_OSPF; }; }\n"
                     "protocol ospf v2 ospf4 {\n  ipv4 { import where source = RTS_OSPF; export none; };\n"
                     "  ecmp no;\n  area 0.0.0.0 {\n", rid);
    int count = 0, active = 0; char seen[MAX_PORTS] = {0};
    for (char *item = strtok(list, ","); item; item = strtok(NULL, ",")) {
        char port[PORT_SIZE], stub, type, tail; unsigned cost, priority;
        if (++count > MAX_PORTS || sscanf(item, "%5[^:]:%u:%c:%c:%u%c", port, &cost, &stub, &type, &priority, &tail) != 5) return -1;
        if (!valid_port(port) || seen[atoi(port + 3)]++ || cost < 1 || cost > 65535 || (stub != 'y' && stub != 'n')) return -1;
        if ((type != 'p' && type != 'b') || priority > 255 || (type == 'p' && priority != 1)) return -1;
        active += stub == 'n';
        n += snprintf(out + n, size - (size_t)n, "    interface \"%s\" { type %s; cost %u; stub %s; hello %u; dead %u;",
                      port, type == 'b' ? "broadcast" : "ptp", cost, stub == 'y' ? "yes" : "no", hello, dead);
        if (type == 'b') n += snprintf(out + n, size - (size_t)n, " priority %u; wait %u;", priority, dead);
        n += snprintf(out + n, size - (size_t)n, " };\n");
        if (n >= (int)size - 16) return -1;
    }
    if (!count || !active) return -1;
    n += snprintf(out + n, size - (size_t)n, "  };\n}\n");
    return n;
}
/* RIP with BIRD 2 (shares BIRD's files with OSPF; a router runs one or the other). From typed fields only:
   "ROUTER_ID VERSION PORT:a|p[,...]": the ports RIP runs on, a(ctive) or p(assive: announced, no updates sent). */
static int rip_render(const char *fields, char *out, size_t size) {
    char rid[16], list[160], copy[160], extra; unsigned version;
    if (sscanf(fields, "%15s %u %159s %c", rid, &version, list, &extra) != 3) return -1;
    if (!valid_ipv4(rid) || (version != 1 && version != 2)) return -1;
    memcpy(copy, list, sizeof(copy));
    char names[MAX_PORTS][PORT_SIZE]; char modes[MAX_PORTS]; int count = 0;
    for (char *item = strtok(copy, ","); item; item = strtok(NULL, ",")) {
        char port[PORT_SIZE], mode, tail;
        if (count >= MAX_PORTS || sscanf(item, "%5[^:]:%c%c", port, &mode, &tail) != 2) return -1;
        if (!valid_port(port) || (mode != 'a' && mode != 'p')) return -1;
        for (int i = 0; i < count; i++) if (!strcmp(names[i], port)) return -1;
        memcpy(names[count], port, PORT_SIZE); modes[count++] = mode;
    }
    if (!count) return -1;
    int n = snprintf(out, size, "router id %s;\nlog stderr all;\nprotocol device { scan time 1; }\n"
                     "protocol direct direct4 { ipv4; interface ", rid);
    for (int i = 0; i < count; i++) n += snprintf(out + n, size - (size_t)n, "%s\"%s\"", i ? ", " : "", names[i]);
    n += snprintf(out + n, size - (size_t)n, "; }\n"
                  "protocol kernel kernel4 { scan time 1; ipv4 { import none; export where source = RTS_RIP; }; }\n"
                  "protocol rip rip4 {\n  ipv4 { import all; export where source = RTS_DEVICE || source = RTS_RIP; };\n");
    for (int i = 0; i < count; i++) {
        n += snprintf(out + n, size - (size_t)n, "  interface \"%s\" { version %u; mode %s; update time 5; timeout time 30; "
                      "garbage time 20; passive %s; };\n", names[i], version, version == 1 ? "broadcast" : "multicast",
                      modes[i] == 'p' ? "yes" : "no");
        if (n >= (int)size - 16) return -1;
    }
    n += snprintf(out + n, size - (size_t)n, "}\n");
    return n;
}
