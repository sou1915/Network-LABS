/* libFuzzer target for the guest agent: everything it reads from the network, and the typed fields it parses.
 *
 * The first byte picks the handler, the rest is its input: HSRP v1 and v2 frames, VRRP frames (with and without a
 * password), frames on a security port, DNS queries, Syslog messages, TFTP requests, and the --hsrp, --vrrp,
 * --port-guard, --services and routing fields the host sends. Each input starts from the same configured groups, so
 * a crash replays alone. tests/test_agent_fuzz.py builds it with clang (-fsanitize=fuzzer,address,undefined), with
 * HSRP_RUN, VRRP_RUN, GUARD_RUN and SERVICES_RUN in a temporary folder, and runs it in its own network namespace:
 * the groups name port eth15, which the fuzzer's namespace does not have, so nothing on the machine changes. */
#define main agent_main
#include "../../network_labs/appliances/guest/agent.c"
#undef main
#include <stdint.h>

static struct hsrp hsrp_v1, hsrp_v2;
static struct vrrp vrrp_open_group, vrrp_password;
static struct guard guard_shutdown, guard_restrict;
static struct services dns_records;

static void prepare(void) {
    static int ready;
    if (ready) return;
    ready = 1;
    if (!hsrp_parse("eth15/1/1/192.168.1.1/110/y/3/10/636973636f", &hsrp_v1)) abort();
    if (!hsrp_parse("eth15.10/4095/2/10.0.0.1/100/n/1/4/6c6162", &hsrp_v2)) abort();
    if (!vrrp_parse("eth15/1/192.168.1.254/100/y/1/-", &vrrp_open_group)) abort();
    if (!vrrp_parse("eth15/7/10.0.0.254/120/n/2/736563726574", &vrrp_password)) abort();
    if (!guard_parse("eth15/2/s/y/y/0/-", &guard_shutdown)) abort();
    if (!guard_parse("eth15/1/r/n/n/0/020000000001", &guard_restrict)) abort();
    char *tokens[] = {"dns", "a:www.lab=192.0.2.10", "a:mail.lab=192.0.2.11", "cname:web=www.lab", "ntp:2", "syslog"};
    if (!services_parse(6, tokens, &dns_records)) abort();
    hsrp_v1.fd = hsrp_v2.fd = vrrp_open_group.fd = vrrp_password.fd = guard_shutdown.fd = guard_restrict.fd = -1;
    inet_pton(AF_INET, "192.168.1.2", &hsrp_v1.self); inet_pton(AF_INET, "10.0.0.2", &hsrp_v2.self);
    inet_pton(AF_INET, "192.168.1.2", &vrrp_open_group.self); inet_pton(AF_INET, "10.0.0.2", &vrrp_password.self);
}

/* DATA as a NUL-terminated string (at most ROOM - 1 bytes). */
static char *text_of(const uint8_t *data, size_t size, char *room, size_t limit) {
    size_t n = size < limit - 1 ? size : limit - 1;
    memcpy(room, data, n); room[n] = 0;
    return room;
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    prepare();
    if (size < 2) return 0;
    unsigned pick = data[0] % 12, state = data[1];
    const uint8_t *in = data + 2; size_t n = size - 2;
    unsigned char frame[1600]; char text[2048], out[8192];
    if (pick <= 3 || pick == 4) {  /* frames: as large as the receive buffers */
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
    case 2: case 3: {
        struct vrrp v = pick == 2 ? vrrp_open_group : vrrp_password;
        v.state = state % 3; v.master_advert = v.advert; v.down_at = 150;
        vrrp_packet(&v, frame, n, 100.0);
        break;
    }
    case 4: {
        struct guard g = state & 1 ? guard_restrict : guard_shutdown;
        guard_frame(&g, frame, n);
        guard_frame(&g, frame, n);  /* the same frame again: a known address, or a repeated violation */
        break;
    }
    case 5: {
        unsigned char query[1500], answer[1500];
        n = n < sizeof(query) ? n : sizeof(query);
        memcpy(query, in, n);
        size_t length = dns_answer(&dns_records, query, n, answer, sizeof(answer));
        if (length > sizeof(answer)) abort();
        break;
    }
    case 6:
        syslog_keep("192.0.2.7", in, n < 1499 ? n : 1499);
        break;
    case 7: {
        unsigned char request[1500]; char name[80], mode[16];
        n = n < sizeof(request) ? n : sizeof(request);
        memcpy(request, in, n);
        tftp_request(request, n, name, mode);
        if (strlen(name) > 79 || strlen(mode) > 15) abort();
        (void)valid_file(name);
        break;
    }
    case 8: {
        struct hsrp h; struct vrrp v; struct guard g;
        text_of(in, n, text, 200);
        if (state % 3 == 0) (void)hsrp_parse(text, &h);
        else if (state % 3 == 1) (void)vrrp_parse(text, &v);
        else (void)guard_parse(text, &g);
        break;
    }
    case 9: {
        static struct services s; char *tokens[32]; int count = 0, rest = 0;
        text_of(in, n, text, sizeof(text));
        for (char *item = strtok(text, " "); item && count < 32; item = strtok(NULL, " ")) tokens[count++] = item;
        (void)rest;
        (void)services_parse(count, tokens, &s);
        break;
    }
    case 10: case 11: {
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
