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

## Peer-induced carrier validation

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
The test never invokes a managed configuration edit or an FDB flush during
those cycles. A spy rejects accidental flushes and interface mutations outside
the two peer member faults; declared policy and revision must stay unchanged.

| Carrier scenario | Required evidence |
|---|---|
| One peer member down, min-links 1 | One negotiated member; carrier remains on the aggregate; bundle path remains selected |
| One peer member down, min-links 2 | One negotiated member but aggregate not ready; STP selects the spare |
| Both peer members down | No negotiated members; spare carries both VLANs bidirectionally |
| One member returned | Bundle returns for threshold 1; threshold 2 remains on spare |
| Both members returned | Both negotiate; original common-tree bundle path returns |
| Two cycles per threshold | Packet delivery recovers naturally within the bounded test deadline; runtime static marker survives |
| Actual path captures | Warmed bidirectional echo for VLANs 10/20 appears on the selected bundle/spare, absent on the inactive path; hop limit stays 64 |
| Drift and saved restart | External peer admin changes cannot be saved as declared policy; after restoration, save/restart rebuilds threshold/topology without runtime FDB markers |

Control convergence and packet recovery have independent checks. The scenario
checks host IPv4 routes/rules/forwarding and virtual-link cleanup. It records the
actual runner kernel; passing there does not establish a fix on the original
6.17 kernel or all kernels. No carrier watchdog, generic automatic FDB repair,
MSTP/PVST, OVS, optical faults or one-way LACP loss is introduced by this test.
