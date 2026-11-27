#!/usr/bin/env bash
# Build the pinned Network LABS guest kernel the way Firecracker builds its own CI kernel:
# Amazon Linux's microvm 5.10.223 tree with Firecracker's v1.10.1 CI guest config, plus
# network-labs.fragment. The source is pinned by git commit (git verifies every object),
# the config by SHA-256, and the result must keep every option Firecracker enables.
#
# A kernel.org 5.10.223 built from the same config boots but cannot use Firecracker's
# virtio-mmio devices (probe error -22 on disk, network and vsock, so no root disk);
# Firecracker's config is written for the Amazon Linux tree its CI kernel comes from.
#
# Usage: tools/guest_kernel/build.sh OUTPUT_DIR
# Needs: git curl make gcc flex bison bc libelf-dev libssl-dev (and xz-utils for the source archive)
#
# NETWORK_LABS_KERNEL_SOURCE=1 also writes the corresponding source next to the kernel, as a release must ship it
# (GPL 2.0): the exact tree (git archive of the pinned commit), Firecracker's base config, the fragment and this script.
# The build is reproducible for one compiler: fixed build user, host and timestamp (the commit's date).
set -euo pipefail

KERNEL_VERSION=5.10.223
KERNEL_REPOSITORY=https://github.com/amazonlinux/linux
KERNEL_TAG=microvm-kernel-5.10.223-232.872.amzn2
KERNEL_COMMIT=8c3eeb0cc41e3fa4e5e27e29c557124ed1a1c451   # the commit that tag points to
FIRECRACKER_TAG=v1.10.1
CONFIG_SHA256=df50707f6b8460038483c7979712533d4bcab47ec9cb340e2df31e470918fb34

here="$(cd "$(dirname "$0")" && pwd)"
output="$(mkdir -p "${1:?output directory}" && cd "$1" && pwd)"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
cd "$work"

git init -q linux
git -C linux fetch -q --depth 1 "$KERNEL_REPOSITORY" "$KERNEL_COMMIT"
git -C linux checkout -q FETCH_HEAD
[ "$(git -C linux rev-parse HEAD)" = "$KERNEL_COMMIT" ] || { echo "kernel source is not commit $KERNEL_COMMIT" >&2; exit 1; }
echo "GUEST_KERNEL_SOURCE ${KERNEL_TAG} ${KERNEL_COMMIT}"
export KBUILD_BUILD_USER=network-labs KBUILD_BUILD_HOST=network-labs
KBUILD_BUILD_TIMESTAMP="$(git -C linux log -1 --format=%cd --date=rfc2822)"; export KBUILD_BUILD_TIMESTAMP
if [ "${NETWORK_LABS_KERNEL_SOURCE:-0}" = 1 ]; then
    git -C linux archive --format=tar --prefix="linux-${KERNEL_VERSION}-amzn2/" HEAD | xz -6 -T0 > "$output/linux-${KERNEL_VERSION}-amzn2-source.tar.xz"
    install -m 0644 "$here/network-labs.fragment" "$here/build.sh" "$output/"
fi

curl -fsSL --retry 3 -o base.config \
    "https://raw.githubusercontent.com/firecracker-microvm/firecracker/${FIRECRACKER_TAG}/resources/guest_configs/microvm-kernel-ci-x86_64-5.10.config"
echo "${CONFIG_SHA256}  base.config" | sha256sum -c -
if [ "${NETWORK_LABS_KERNEL_SOURCE:-0}" = 1 ]; then install -m 0644 base.config "$output/firecracker-${FIRECRACKER_TAG}-base.config"; fi

cd linux
cat ../base.config "$here/network-labs.fragment" > .config
make olddefconfig >/dev/null

# Every option Firecracker enables must survive, and every fragment option must take effect.
# An option whose symbol no Kconfig file in this tree defines is reported and skipped; an
# option the tree defines but that ended up disabled stops the build.
missing=0
while IFS= read -r line; do
    grep -qxF "$line" .config && continue
    symbol="${line#CONFIG_}"; symbol="${symbol%%=*}"
    if grep -rqE "^[[:space:]]*(menu)?config[[:space:]]+${symbol}[[:space:]]*$" --include='Kconfig*' .; then
        echo "lost from base config: $line" >&2; missing=1
    else
        echo "not defined in this kernel tree, skipped: $line"
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
