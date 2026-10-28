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
