The Linux guest kernel Network LABS micro-VMs boot: Firecracker's CI kernel (Amazon Linux microvm 5.10.223, Firecracker
v1.10.1's guest config) plus 802.1Q VLANs, bridge VLAN filtering, bonding (LACP) and macvlan (HSRP, VRRP).

`network-labs-lab setup --download` fetches `vmlinux-5.10.223-network-labs` from this release and checks its SHA-256
against the value pinned in `network_labs/appliances/setup.py`; you do not need to download anything by hand.

Built and boot-tested on KVM by `.github/workflows/guest-kernel-release.yml` from `tools/guest_kernel/build.sh`.

Licence: GNU GPL version 2. The corresponding source is attached: `linux-5.10.223-amzn2-source.tar.xz` (the exact
tree, from https://github.com/amazonlinux/linux at the commit pinned in `build.sh`), Firecracker's base configuration,
`network-labs.fragment`, the final `.config` and `build.sh`, which rebuilds the kernel from them.
