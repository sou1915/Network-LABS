# Explicit IPv6 read-only TFTP

`example --ipv6-tftp` provides one managed read-only dnsmasq TFTP server on a
static IPv6-only host and a two-router physical path from PC1. The server opts
in with `tftp_server.family: "ipv6"`; omission keeps IPv4 validation/configuration.
The client independently selects `tftp-read --family ipv6`; its default remains
IPv4. Server literals must match that family, with no DNS or family fallback.
IPv6 loopback, link-local, scoped, multicast, unspecified and IPv4-mapped targets
are refused by the managed client. The route lookup and socket bind use the
observed source address of the selected family. IPv6 sockets are v6-only.

```bash
python3 -m network_labs.appliances rootfs --busybox /usr/bin/busybox \
  --dnsmasq /usr/sbin/dnsmasq --output /absolute/rootfs-tftp
python3 -m network_labs.appliances example --ipv6-tftp \
  --rootfs /absolute/rootfs-tftp > ipv6-tftp.json
sudo python3 -m network_labs.appliances start ipv6-tftp.json
sudo python3 -m network_labs.appliances tftp-read ipv6-tftp-lan PC1 \
  2001:db8:20::20 sample.bin --family ipv6 --block-size 1024 --json
```

`--tftp-file NAME=PATH` can explicitly import the same bounded public binary
assets as the existing IPv4 example. Without imports the reference includes
sample text and binary files. Server assets remain at most eight declared files,
64 KiB per binary file or 4096 UTF-8 bytes per text file. Runtime server startup
waits for the declared IPv6 address to finish DAD. The service binds its declared
physical interface, with the IPv6 listen address explicit in configuration.
The profile declares no non-loopback IPv4 addresses or IPv4 routing; this is not
a claim that all internal dnsmasq socket families are disabled.

The existing octet-read semantics remain: at most 65536 bytes, 256 received
datagrams, one 1..10-second deadline, finite per-block timeout retransmissions,
optional blksize negotiation (512..1428), fixed-peer DATA/OACK acceptance and
bounded repeated final ACKs. IPv6 peer tuples retain the learned transfer port
and scope fields. Wrong TIDs cannot advance the transfer or replace its peer.
Hash comparison remains optional and explicit. Passed means bytes received and
the initial final ACK sent, not confirmed server receipt. No output file is
saved, and no write protocol, encryption or authentication is added.

The managed IPv6 server profile is restricted to one separate single-interface
server, statically numbered physical IPv6-only hosts/routers and static routes.
DNS/AAA/management, dynamic IPv6, switches, SVIs/subinterfaces, firewall/security
and mixed/dual-stack service compositions are refused here. Existing read-only
IPv4 TFTP defaults remain available. This does not establish generic
interoperability with every external server or IPv6 path MTU.

Native validation requires real dnsmasq empty/binary/exact-block/64-KiB reads,
classic and negotiated blocks, actual IPv6 UDP captures, correct hashes,
wrong-hash and missing-file failures, service and forwarding outage/recovery,
an independent local wire control during routing failure, file/configuration
drift refusal, saved family retention, cold restore and host network invariants.
A local IPv6 wire test also injects a wrong TID and repeats final DATA to check
peer pinning, SHA-256 and bounded final-ACK behavior. Exact evidence is recorded
in LAN_NEXT_STEPS.md; environment skips are not native proof.

```bash
gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-tftp
```
