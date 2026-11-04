# Optional IPv6 local-input filtering

`example --ipv6-input-firewall` adds a separately opted-in
`firewall_ipv6.input` policy to the existing static physical IPv6 firewall.
The forward chain remains independent. Omitting `input` retains the existing
forward-only behavior and creates no input chain. An input policy protects
traffic delivered to the firewall itself; it does not filter local output.

```bash
python3 -m network_labs.appliances rootfs --busybox /usr/bin/busybox \
  --dnsmasq /usr/sbin/dnsmasq --output /absolute/rootfs-dns
python3 -m network_labs.appliances example --ipv6-input-firewall \
  --rootfs /absolute/rootfs-dns > ipv6-input.json
sudo python3 -m network_labs.appliances start ipv6-input.json
sudo python3 -m network_labs.appliances probe ipv6-input-firewall-lan PC1 \
  server.lab.test --protocol dns --family ipv6 --dns-transport tcp --json
```

The reference permits PC1 (`2001:db8:10::10`) to reach FW1's client-side
address (`2001:db8:10::1`) with echo requests and TCP destination port 8080.
Other local input is default-denied. Permitting a port does not create a service
listener: the reference manages DNS on the separate PC2 endpoint, while native
validation starts disposable HTTP listeners on FW1 as independent controls.
Forwarded DNS retains the separate existing UDP/TCP 53 and conntrack rules.

Input rules use the existing bounded name/action/in/source/destination/protocol/
dport/icmp_type fields. `out` is refused because input has no outgoing interface.
Nested input policies are refused. The separate input `default` and `stateful`
settings have the same types as forwarding policy. Stateful established/related
acceptance applies to responses to FW1-originated traffic as well; without it,
explicit return rules are needed. Rule order is preserved.

Two mandatory exceptions precede the configurable input rules: loopback is
accepted, and Neighbor Solicitation/Advertisement (ICMPv6 135/136) with immediate
IPv6 next-header ICMPv6 and hop limit 255 are accepted on declared physical ports.
These keep static DAD/neighbor discovery working under default denial. They are
not neighbor authentication, comprehensive extension/fragment validation or
RA Guard, and cannot be overridden by a later custom drop rule. RA/SLAAC/DHCPv6
and multicast service compositions remain outside this static profile.

The combined table is installed in the owned namespace before physical links
are created or services start. Inspection exposes both actual chains through
the existing `firewall_ipv6` ruleset observation. The whole managed ruleset is
fingerprinted; unmanaged input rules or extra tables refuse save. Startup saves
only declared policy, not conntrack state or fixture processes. Recreate from
the saved declaration to restore policy after drift.

The profile remains limited to the existing static IPv6-only physical OCI
firewall and separately validated DNS coexistence. This adds no generic host
input ACL, output ACL, NAT66, dual-stack firewall, SVI/subinterface/dynamic/AAA
composition or application authentication.

Native validation requires proven local listeners, allowed and denied clients/
ports, input counters and actual packet captures, fresh NDP after neighbor
flush, stateful local replies versus a stateless negative control, continued
forwarded DNS, omission compatibility, drift refusal, cold restore and host
network/nftables invariants. Exact evidence belongs in LAN_NEXT_STEPS.md.

```bash
gh workflow run tests.yml --ref handoff/codex-dot1x-2026-11-04 -f suite=ipv6-input-firewall
```
