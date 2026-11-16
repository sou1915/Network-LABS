#!/usr/bin/env bash
# GitHub-hosted Ubuntu prerequisites; never reconfigure a developer machine.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != true || "$(id -u)" != 0 ]]; then
    echo 'This helper requires root inside GitHub Actions.' >&2
    exit 2
fi
if (( $# == 0 || $# > 64 )); then
    echo 'Supply 1..64 explicit Ubuntu package names.' >&2
    exit 2
fi
for native_package in "$@"; do
    if [[ ! "$native_package" =~ ^[a-z0-9][a-z0-9+.-]*$ ]]; then
        echo 'Invalid package name.' >&2
        exit 2
    fi
done

# Hosted runner mirror lists selected an unresponsive Azure mirror for package
# indexes despite fetching InRelease from archive.ubuntu.com. Use the same
# official HTTPS archive consistently; leave other APT sources/trust intact.
if [[ -f /etc/apt/apt-mirrors.txt && ! -L /etc/apt/apt-mirrors.txt ]]; then
    printf '%s\n' 'https://archive.ubuntu.com/ubuntu/' > /etc/apt/apt-mirrors.txt
fi
native_apt_options=(-o Acquire::Retries=2 -o Acquire::http::Timeout=20
                    -o Acquire::https::Timeout=20 -o APT::Update::Error-Mode=any)
apt-get "${native_apt_options[@]}" update
apt-get "${native_apt_options[@]}" install -y --no-install-recommends "$@"
