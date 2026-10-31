# Common STP and LACP recovery validation

The native integration test
`test_common_stp_uses_lacp_as_one_port_and_fails_over_to_spare_trunk`
uses two OCI switches, four hosts, VLANs 10 and 20, a two-member Linux
802.3ad bond and a higher-cost spare trunk. Linux selects the STP tree;
the manager reconciles dynamic learning after managed administrative recovery.

| Scenario | Required observations |
|---|---|
| Three full member outage/recovery cycles | Surviving member, spare trunk, then restored aggregate carry traffic; both VLANs pass bidirectional ICMP after recovery |
| Failure on the second bridge's FDB flush | First real flush has occurred; rollback preserves declared configuration and revision, clears the journal, restores spare-path traffic and permits retry |
| One member lost with `min-links 2` | Aggregate loses carrier despite one negotiated member; spare carries traffic; member recovery reconciles dynamic learning on both switches |
| Logical port-channel shutdown/re-enable | Physical members stay administratively up; spare carries traffic; re-enable restores the aggregate path |
| Saved shutdown policy and restart | `min-links 2` and logical shutdown survive; spare carries traffic after restart; re-enable restores both VLANs |
| FDB preservation and persistence | Manually added static marker survives live recovery, but is absent after restart because it was never declared in the saved configuration |

The FDB marker is runtime test state. Its disappearance after restart is
intentional: startup files contain declared configuration, not a snapshot
of manually inserted or dynamically learned MAC addresses.

Run the scenario on a disposable privileged Linux host with `crun`,
`iproute2`, `busybox-static`, `util-linux`, `tcpdump` and bonding support:

```bash
sudo modprobe bonding max_bonds=0
sudo env NETWORK_LABS_NATIVE_TESTS=1 python3 -m unittest discover \
  -s tests -p test_native_integration.py -k test_common_stp_uses -v
```

The dedicated `switching-interop` CI job runs this same test. Its packet
checks are separate from the manager's sequential kernel control-state
observations. This does not validate physical carrier failures without a
management command, every kernel version, MSTP/PVST or OVS RSTP.
The initial failure was observed on `6.17.0-1022-azure`; successful recovery
runs on `7.0.0-1017-azure` do not establish a fix on that original kernel.

The full matrix, including saved shutdown/restart, passed in the
[native switching job](https://github.com/sou1915/Network-LABS/actions/runs/40748151462/job/123027335447)
for commit `fd6e380` on 2026-10-28. General tests and RADIUS interoperability
also passed; the complete native suite for that commit was still running
when this record was written.

See [Native LAN core](NATIVE_LAN_CORE.md) for the transaction, deadlines,
commands and dynamic-only FDB cleanup scope.

## Peer-induced carrier and opt-in automatic recovery

The reusable `example --stp-lacp` topology adds the higher-cost spare trunk to
`--lacp`. `--stp-lacp-min-links 1` (default) or `2` sets the declared carrier
threshold on both bundles. It uses the same four PCs and VLANs 10/20, with
common STP priorities 4096/8192, hello 1, max-age 6 and forward-delay 4.

```bash
python3 -m network_labs.appliances example --stp-lacp \
  --stp-lacp-min-links 2 --rootfs "$HOME/network-labs-rootfs" > stp-lacp-lan.json
sudo python3 -m network_labs.appliances start stp-lacp-lan.json
sudo python3 -m network_labs.appliances inspect stp-lacp-lan SW1
sudo python3 -m network_labs.appliances show stp-lacp-lan SW2 --text 'show spanning-tree'
```

The separate `stp-lacp-carrier-interop` job runs
`test_native_stp_lacp_carrier_integration.py` on a disposable Ubuntu 24.04
runner. Its fault injector directly sets the *peer* SW2 veth member down/up.
On SW1, the corresponding member stays administratively UP while LOWER_UP
reflects actual carrier loss/return. This is a virtual peer-induced carrier
case, not a physical cable/NIC test, and not packet loss with carrier retained.

The first natural-recovery run on `7.0.0-1017-azure` reproduced a real failure:
with min-links 1, one returned member restored the observed STP/LACP control
path but PC1 traffic remained blocked, with old spare-path FDB learning still
present. The profile therefore explicitly enables
`spanning_tree.carrier_recovery:true` on both switches. This is optional and
false by default for other topologies. It is an owned background worker,
**not a claim that the kernel naturally repaired every case**.

The test helper never invokes a managed configuration edit or FDB flush during
cycles. Its spy rejects such helper repairs and mutations outside the two peer
member faults. The runtime worker independently observes stable control/path
changes and flushes dynamic FDB entries on both owned bridges. Actual repair
counts/completion, preserved static markers and unchanged declared policy and
revision are checked separately from packet recovery.

| Carrier scenario | Required evidence |
|---|---|
| One peer member down, min-links 1 | One negotiated member; carrier remains on the aggregate; bundle path remains selected |
| One peer member down, min-links 2 | One negotiated member but aggregate not ready; STP selects the spare |
| Both peer members down | No negotiated members; spare carries both VLANs bidirectionally |
| One member returned | Bundle returns for threshold 1; threshold 2 remains on spare |
| Both members returned | Both negotiate; original common-tree bundle path returns |
| Two cycles per threshold | Opt-in worker repairs dynamic learning after settled path changes; packet recovery has its own deadline; runtime static marker survives |
| Actual path captures | Warmed bidirectional echo for VLANs 10/20 appears on the selected bundle/spare, absent on the inactive path; IPv4 TTL stays 64 |
| Drift and saved restart | External peer admin changes cannot be saved as declared policy; after restoration, save/restart rebuilds threshold/topology without runtime FDB markers |

Control convergence and packet recovery have independent checks. The scenario
checks host IPv4 routes/rules/forwarding and virtual-link cleanup. It records the
actual runner kernel; passing there does not establish a fix on the original
6.17 kernel or all kernels. The initial worker scope is exactly two opted-in Linux common-STP switches,
each with one paired two-member LACP channel and initially UP interfaces. Trust,
STP and network edits on those switches require recreation. Two equal settled
observations with a common root and a ready selected LACP root port precede a
repair; incomplete/failed reads do not flush. Each namespace identity is checked
before use. Partial flush failures remain incomplete and retry after stable
observations, including when the path changes back. Only dynamic FDB entries
are touched, never static/permanent entries or addresses/routes. Worker health,
repair count and the last event are reported as `stp_carrier_recovery` by inspect;
they are not a packet-delivery verdict. Save rejects an unavailable/stale worker.
The worker is stopped before namespace teardown and recreated with fresh runtime
state after cold restore. Runtime PID/tokens/events do not enter saved policy.

This does not provide generic FDB repair for arbitrary topologies, MSTP/PVST,
OVS, optical faults or support on every kernel. One-way control-loss coverage
is separately described below.

The opt-in automatic carrier profile passed the
[dedicated carrier job](https://github.com/sou1915/Network-LABS/actions/runs/40960722168/job/123752453718)
at implementation commit `c5b7caabd35ecc3116731e15f77991fec2a7dc5d` on
`7.0.0-1017-azure` with iproute2 6.1.0. The 167-second scenario completed two
full cycles for each threshold, both tagged packet paths, static-marker
preservation, successful worker repairs, unchanged revision/configuration,
saved restart, fresh worker identity and worker termination before cleanup.
The general tests and older managed-administrative `switching-interop` job also
passed on this commit; its complete native suite subsequently finished
successfully as well. This records the implemented opt-in repair, not natural recovery
without a worker or validation on the original 6.17 kernel.


## One-way control loss with member carrier retained

The dedicated `stp-lacp-control-loss-interop` job runs
`test_native_stp_lacp_control_loss_integration.py` using the same bounded
`--stp-lacp` profile and its existing opt-in dynamic FDB worker.
The injector installs a software `tc flower` ingress drop on SW1 eth2,
then eth3, matching EtherType `0x8809` and destination
`01:80:c2:00:00:02`. This suppresses SW2-to-SW1 Slow Protocol multicast,
including LACP; it does not match IP, ARP, VLAN data or reverse-direction
traffic. This is not a physical unidirectional cable fault or arbitrary
packet loss. The sender is the passive peer and receiver the active peer.

For min-links 1 and 2, two cycles require the actual negotiated-member
counts to decrease 2 -> 1 -> 0 and return 0 -> 1 -> 2. Every member on both
peers must remain administratively UP, LOWER_UP and MII up at the fault and
recovery checkpoints. No test-helper link mutations, managed configuration
edits or FDB repairs are allowed. Positive tc action drop counters are
required before each filter is removed, and all four member qdiscs must
match their initial state after recovery.

The first native run at commit `87351bdcd2f6590b4d9763852b35e8ecaac4d966`
on `7.0.0-1017-azure` exposed a min-links-1 boundary: both peers had zero
negotiated members and defaulted/expired partner state while both bonds still
had carrier and STP continued selecting bond1. The test's original assumption
that all-control loss would always select the spare was false. That
[initial run](https://github.com/sou1915/Network-LABS/actions/runs/41036138771/job/123997315590)
failed only the min-links-1 subtest; min-links 2 completed the failover matrix.
The existing dynamic-FDB worker cannot fix a forwarding-path selection that
has not changed, and this increment does not add a runtime link/STP override.

The revised matrix requires **automatic failover with min-links 2** and
explicitly reproduces **carrier without ready LACP with min-links 1**.
`inspect` reports `port_channels.bond1.carrier_without_ready_lacp:true`
when the bond is UP/LOWER_UP but lacks enough negotiated members. It still
reports `ready:false`; physical carrier must not be mistaken for negotiation.
This diagnostic does not prove actual fallback packet delivery. The threshold-1
all-control-loss checkpoint does not claim packet recovery or spare selection.
Use threshold 2 for the bounded silent-control-loss failover scenario.

For threshold 2, control checks, selected-path tagged captures, bidirectional
VLAN 10/20 traffic with TTL 64, worker repair evidence, static FDB preservation,
unchanged declaration/revision, cold restore and worker cleanup use the
same assertions as the carrier scenario. Threshold 1 also verifies normal
traffic after partial/full recovery, static markers, cold restore and cleanup. External tc injection is removed
before save: persistence does **not** currently audit arbitrary tc filters,
and this test does not claim that saving during an injected fault is refused.
The revised scenario passed the
[dedicated one-way control-loss job](https://github.com/sou1915/Network-LABS/actions/runs/41036997483/job/124000165427)
at implementation commit `b234b9a294298d1e4fec4f82054b4f726d866f2a` on
`7.0.0-1017-azure` with iproute2 6.1.0 in 293 seconds. The log explicitly
records the min-links-1 boundary in both cycles; the min-links-2 automatic
failover/recovery, tagged traffic, preserved static marker and saved restart
checks completed. General tests, older administrative switching, peer carrier,
all dedicated IPv6 jobs, SSH and RADIUS also passed on this commit. Its full
`native-containers` suite was still running when this checkpoint was recorded.
The local suite completed 762 tests with 116 environment-dependent skips.
This proves the bounded threshold-2 scenario and threshold-1 limitation, not
strict LACP failover with threshold 1 or arbitrary one-way data-plane faults.

References: [iproute2 flower manual](https://man7.org/linux/man-pages/man8/tc-flower.8.html)
and [Linux bonding options](https://www.kernel.org/doc/html/latest/networking/bonding.html).


## Explicit native strict LACP and reverse control loss

An experimental optional `port_channels.bond1.lacp_strict:true` policy maps
to Linux's native bonding option. Generate the bounded reference with:

```bash
python3 -m network_labs.appliances example --stp-lacp --stp-lacp-strict \
  --stp-lacp-min-links 1 --rootfs /path/to/rootfs > strict-stp-lacp.json
```

Omission keeps the legacy profile and its documented threshold-1 fallback
boundary. Explicit `true` or `false` requires a supporting iproute2 and
kernel; integers and strings are rejected. Tool preflight checks the installed
`ip link help bond` before allocating a lab. The requested option is passed
at bond creation, then exact `lacp_strict` netlink readback is required before
enslaving members. A rejected command or missing/mismatched readback aborts
startup and uses ordinary owned-lab cleanup. Unsupported kernels may silently
ignore an unknown netlink attribute, so successful command exit alone is
insufficient. No userspace bridge/link override is substituted.

`inspect` reports both `lacp_strict_requested` and actual `lacp_strict` (null
when evidence is absent). Save rejects changed/missing strict readback.
Explicit-policy switch edits require recreation. The option is declarative;
runtime member/FDB states remain outside saved startup policy.

`lacp-strict-capability` builds upstream iproute2 at
`30365d0967bd4ec993600bb8f27532061bec7413` into a private CI path, leaving
the system binary in place. It verifies either actual strict readback on both
switches or explicit refusal without leaked lab state/namespaces/virtual links.
Its log distinguishes `STRICT_UNSUPPORTED` from `STRICT_VERIFIED`. Only a
verified host proceeds to the full strict matrix: both receive directions,
min-links 1 and 2, two cycles, tagged packet paths, static markers and cold
restore. `NETWORK_LABS_REQUIRE_STRICT=1` makes unsupported hosts fail rather
than accept the refusal branch. A passing refusal branch is **not** native
strict packet-delivery evidence. Native evidence is pending for this increment.

Separately, `stp-lacp-reverse-control-loss-interop` runs the legacy
min-links-2 profile with receive drops on SW2: active SW1 -> passive SW2.
It requires two full fault/recovery cycles with all physical member carriers
retained, actual negotiated member counts, positive drop counters, tagged
VLAN 10/20 packets on the selected path, static-marker preservation, qdisc
restoration, unchanged declaration/revision, save/restart and cleanup.
This direction does not assume threshold-1 fallback behaves identically.

References: [Linux bonding strict option](https://www.kernel.org/doc/html/latest/networking/bonding.html)
and [upstream iproute2 strict support](https://kernel.googlesource.com/pub/scm/network/iproute2/iproute2/+/30365d0967bd4ec993600bb8f27532061bec7413).
