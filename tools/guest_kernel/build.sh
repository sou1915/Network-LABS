#!/usr/bin/env bash
# Build the pinned Network LABS guest kernel: Linux 5.10.223 with Firecracker's v1.10.1
# CI guest config plus network-labs.fragment. Every input is pinned by SHA-256, and the
# result must keep every option Firecracker's config enables.
#
# Usage: tools/guest_kernel/build.sh OUTPUT_DIR
# Needs: curl xz-utils make gcc flex bison bc libelf-dev libssl-dev
set -euo pipefail

KERNEL_VERSION=5.10.223
# Printed by the first CI build after matching kernel.org's sha256sums list.
KERNEL_SHA256=ca09d86a6b79706c33382d3f8606f476eb07918417a87fb1815f6a4aa81f2ba1
FIRECRACKER_TAG=v1.10.1
CONFIG_SHA256=df50707f6b8460038483c7979712533d4bcab47ec9cb340e2df31e470918fb34

here="$(cd "$(dirname "$0")" && pwd)"
output="$(mkdir -p "${1:?output directory}" && cd "$1" && pwd)"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
cd "$work"

curl -fsSL --retry 3 -o linux.tar.xz "https://cdn.kernel.org/pub/linux/kernel/v5.x/linux-${KERNEL_VERSION}.tar.xz"
actual="$(sha256sum linux.tar.xz | cut -d' ' -f1)"
echo "GUEST_KERNEL_TARBALL_SHA256 ${actual}"
if [ -n "$KERNEL_SHA256" ]; then
    [ "$actual" = "$KERNEL_SHA256" ] || { echo "kernel tarball hash mismatch: $actual" >&2; exit 1; }
else
    curl -fsSL --retry 3 -o sums "https://cdn.kernel.org/pub/linux/kernel/v5.x/sha256sums.asc"
    grep -q "^${actual}  linux-${KERNEL_VERSION}.tar.xz$" sums || { echo "kernel tarball not in kernel.org sha256sums" >&2; exit 1; }
fi

curl -fsSL --retry 3 -o base.config \
    "https://raw.githubusercontent.com/firecracker-microvm/firecracker/${FIRECRACKER_TAG}/resources/guest_configs/microvm-kernel-ci-x86_64-5.10.config"
echo "${CONFIG_SHA256}  base.config" | sha256sum -c -

tar -xf linux.tar.xz
cd "linux-${KERNEL_VERSION}"
cat ../base.config "$here/network-labs.fragment" > .config
make olddefconfig >/dev/null

# Every option Firecracker enables must survive, and every fragment option must take effect.
# Firecracker's CI kernels come from Amazon Linux's 5.10 tree, which adds a few options
# (DAMON, VMGENID, ...) that this kernel.org tree does not define. Those are reported and
# skipped; an option the tree does define but that ended up disabled stops the build.
missing=0
while IFS= read -r line; do
    grep -qxF "$line" .config && continue
    symbol="${line#CONFIG_}"; symbol="${symbol%%=*}"
    if grep -rqE "^[[:space:]]*(menu)?config[[:space:]]+${symbol}[[:space:]]*$" --include='Kconfig*' .; then
        echo "lost from base config: $line" >&2; missing=1
    else
        echo "not defined in Linux ${KERNEL_VERSION} (Amazon Linux addition), skipped: $line"
    fi
done < <(grep -E '^CONFIG_[A-Z0-9_]+=y$' ../base.config)
while IFS= read -r line; do
    grep -qxF "$line" .config || { echo "fragment option not applied: $line" >&2; missing=1; }
done < <(grep -E '^CONFIG_' "$here/network-labs.fragment")
[ "$missing" = 0 ]

make -j"$(nproc)" vmlinux >/dev/null
name="vmlinux-${KERNEL_VERSION}-network-labs"
install -m 0644 vmlinux "$output/$name"
install -m 0644 .config "$output/$name.config"
( cd "$output" && sha256sum "$name" > "$name.sha256" && cat "$name.sha256" )
