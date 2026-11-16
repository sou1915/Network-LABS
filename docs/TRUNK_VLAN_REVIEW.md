# Trunk/VLAN review

A live `vlan 30` declaration previously updated the manifest but could leave
Linux bridge trunks unchanged. The apply path skipped a port whenever its
switchport object was identical. That is insufficient for `allowed all` and
explicit allowed lists reserving a VLAN not yet declared: their effective
memberships also depend on the switch's VLAN table.

The apply path now compares effective memberships before skipping a port.
The same comparison applies during rollback, removing newly activated
memberships after a partially failed VLAN declaration. Unaffected access
ports and trunks excluding the VLAN are skipped. This does not add atomic
multi-switch configuration or change the existing admission/tagging policy.

The regression first failed against the old implementation. Unit coverage
checks physical and logical LACP trunks, all/explicit/excluded allowed lists,
native flags and reverse application. The dedicated native CI scenario uses
real Linux bridges and actual packet delivery on both physical and LACP trunks:

- Injected VLAN activation failure, rollback and unchanged existing traffic.
- Activation of an undeclared, reserved VLAN and `allowed all` without editing
  the trunk's switchport object.
- VLAN isolation using an explicit ARP solicitation across VLANs.
- Packet captures showing tagged VLAN30 and untagged native VLAN30 traffic.
- Pruning the native VLAN, `allowed none`, restoration and saved restart.

Existing native scenarios separately exercise VLAN access reassignment,
inter-VLAN SVIs/router subinterfaces, STP and LACP failure/recovery.
OVS's current RSTP profile accepts access ports only; it is not a trunk backend.
Physical carrier failures, additional kernels, broader protocol/security
interactions and MSTP/PVST remain separate work. Passing these tests is not
proof of every topology or vendor-specific switch behavior.
