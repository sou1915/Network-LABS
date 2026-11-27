/* libFuzzer target for the guest agent: everything it reads from the network, and the typed fields it parses.
 *
 * The first byte picks the handler, the rest is its input: HSRP v1 and v2 frames, frames on a security port, Syslog
 * messages, TFTP requests, and the --hsrp, --vrrp, --port-guard, --services and routing fields the host sends, with the
 * keepalived, dnsmasq and chrony configurations written from them (no field may add a line of its own). DNS, NTP and
 * VRRP packets are no longer the agent's: dnsmasq, chrony and keepalived read them. Each input starts from the same
 * configured groups, so a crash replays alone. tests/test_agent_fuzz.py builds it with clang (-fsanitize=fuzzer,address,undefined), with
 * HSRP_RUN, VRRP_RUN, GUARD_RUN and SERVICES_RUN in a temporary folder, and runs it in its own network namespace:
 * the groups name port eth15, which the fuzzer's namespace does not have, so nothing on the machine changes. */
#define main agent_main
#include "../../network_labs/appliances/guest/agent.c"
#undef main
#include <stdint.h>

static struct hsrp hsrp_v1, hsrp_v2;
static struct guard guard_shutdown, guard_restrict;

static void prepare(void) {
    static int ready;
    if (ready) return;
    ready = 1;
    if (!hsrp_parse("eth15/1/1/192.168.1.1/110/y/3/10/636973636f", &hsrp_v1)) abort();
    if (!hsrp_parse("eth15.10/4095/2/10.0.0.1/100/n/1/4/6c6162", &hsrp_v2)) abort();
    if (!guard_parse("eth15/2/s/y/y/0/-", &guard_shutdown)) abort();
    if (!guard_parse("eth15/1/r/n/n/0/020000000001", &guard_restrict)) abort();
    hsrp_v1.fd = hsrp_v2.fd = guard_shutdown.fd = guard_restrict.fd = -1;
    inet_pton(AF_INET, "192.168.1.2", &hsrp_v1.self); inet_pton(AF_INET, "10.0.0.2", &hsrp_v2.self);
}

/* DATA as a NUL-terminated string (at most ROOM - 1 bytes). */
static char *text_of(const uint8_t *data, size_t size, char *room, size_t limit) {
    size_t n = size < limit - 1 ? size : limit - 1;
    memcpy(room, data, n); room[n] = 0;
    return room;
}

/* A configuration the agent wrote for a daemon from checked fields: every line one of the directives it writes (ALLOWED,
 * each a prefix), so that no field can add a line of its own (a newline, an upstream server, a script). */
static void only_directives(const char *config, const char *const *allowed) {
    for (const char *line = config; *line; line = strchr(line, '\n') ? strchr(line, '\n') + 1 : line + strlen(line)) {
        size_t length = strcspn(line, "\n"), indent = strspn(line, " ");
        int known = indent >= length;  /* an empty line, or one blanked out by the caller */
        for (int i = 0; allowed[i] && !known; i++) known = !strncmp(line + indent, allowed[i], strlen(allowed[i]));
        for (size_t i = 0; i < length; i++) if ((unsigned char)line[i] < 32 || (unsigned char)line[i] > 126) known = 0;
        if (!known) abort();
    }
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    prepare();
    if (size < 2) return 0;
    unsigned pick = data[0] % 9, state = data[1];
    const uint8_t *in = data + 2; size_t n = size - 2;
    unsigned char frame[1600]; char text[2048], out[16384];
    if (pick <= 2) {  /* frames: as large as the receive buffers */
        n = n < sizeof(frame) ? n : sizeof(frame);
        memcpy(frame, in, n);
    }
    switch (pick) {
    case 0: case 1: {
        static const int states[5] = {HS_INIT, HS_LISTEN, HS_SPEAK, HS_STANDBY, HS_ACTIVE};
        struct hsrp h = pick ? hsrp_v2 : hsrp_v1;
        h.state = states[state % 5]; h.active_until = h.standby_until = h.speaker_until = 50;
        hsrp_packet(&h, frame, n, 100.0);
        break;
    }
    case 2: {
        struct guard g = state & 1 ? guard_restrict : guard_shutdown;
        guard_frame(&g, frame, n);
        guard_frame(&g, frame, n);  /* the same frame again: a known address, or a repeated violation */
        break;
    }
    case 3:
        syslog_keep("192.0.2.7", in, n < 1499 ? n : 1499);
        break;
    case 4: {
        unsigned char request[1500]; char name[80], mode[16];
        n = n < sizeof(request) ? n : sizeof(request);
        memcpy(request, in, n);
        tftp_request(request, n, name, mode);
        if (strlen(name) > 79 || strlen(mode) > 15) abort();
        (void)valid_file(name);
        break;
    }
    case 5: {  /* the fields of a --hsrp, --vrrp or --port-guard argument; a VRRP group's keepalived configuration */
        struct hsrp h; struct vrrp v; struct guard g;
        text_of(in, n, text, 200);
        if (state % 3 == 0) (void)hsrp_parse(text, &h);
        else if (state % 3 == 2) (void)guard_parse(text, &g);
        else if (vrrp_parse(text, &v)) {
            static const char *const keepalived[] = {"global_defs {", "router_id network-labs", "vrrp_version 2", "}", "vrrp_instance ",
                "state MASTER", "state BACKUP", "interface ", "virtual_router_id ", "priority ", "advert_int ", "mcast_src_ip ",
                "use_vmac vrrp", "nopreempt", "authentication {", "auth_type PASS", "auth_pass \"", "virtual_ipaddress {", NULL};
            v.owner = state & 4; v.self = v.vip;
            snprintf(v.vdev, sizeof(v.vdev), "vrrp15-%d", v.vrid);
            if (keepalived_config(&v, 1, out, sizeof(out))) abort();
            /* the address line of virtual_ipaddress: the only line that starts with a digit */
            for (char *line = out; *line; line = strchr(line, '\n') ? strchr(line, '\n') + 1 : line + strlen(line))
                if (line[strspn(line, " ")] >= '0' && line[strspn(line, " ")] <= '9') memset(line, ' ', strcspn(line, "\n"));
            only_directives(out, keepalived);
            const char *quote = strstr(out, "auth_pass \""), *end = quote ? strchr(quote + 11, '"') : NULL;
            if (quote && (!end || end - (quote + 11) > 8)) abort();  /* the password: 8 characters at most, closed */
        }
        break;
    }
    case 6: {  /* the --services tokens, and the dnsmasq and chrony configurations written from them */
        static struct services s; char *tokens[32]; int count = 0;
        text_of(in, n, text, sizeof(text));
        for (char *item = strtok(text, " "); item && count < 32; item = strtok(NULL, " ")) tokens[count++] = item;
        if (!services_parse(count, tokens, &s)) break;
        static const char *const dnsmasq[] = {"port=53", "no-resolv", "no-hosts", "no-poll", "local=/#/", "log-queries", "log-facility=-",
                                               "user=root", "group=root", "pid-file=", "host-record=", "cname=", NULL};
        static const char *const chrony[] = {"bindcmdaddress ", "pidfile ", "cmdport 0", "local stratum ", "allow", "server ", NULL};
        dnsmasq_config(&s, out, sizeof(out));
        only_directives(out, dnsmasq);
        for (const char *line = out; *line; line = strchr(line, '\n') ? strchr(line, '\n') + 1 : line + strlen(line)) {
            size_t length = strcspn(line, "\n"), commas = 0;
            for (size_t i = 0; i < length; i++) commas += line[i] == ',';
            if ((!strncmp(line, "host-record=", 12) || !strncmp(line, "cname=", 6)) && commas != 1) abort();  /* NAME,VALUE only */
        }
        chrony_config(&s, out, sizeof(out));
        only_directives(out, chrony);
        break;
    }
    case 7: case 8: {
        text_of(in, n, text, sizeof(text));
        int length;
        switch (state % 4) {
        case 0: length = bgp_render(text, out, sizeof(out)); break;
        case 1: length = eigrp_render(text, out, sizeof(out)); break;
        case 2: length = ospf_render(text, out, sizeof(out)); break;
        default: length = rip_render(text, out, sizeof(out)); break;
        }
        if (length >= (int)sizeof(out)) abort();
        break;
    }
    }
    return 0;
}
