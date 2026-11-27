#!/usr/bin/env bash
# GitHub-hosted Ubuntu prerequisites; never reconfigure a developer machine.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != true || "$(id -u)" != 0 ]]; then
    echo 'This helper requires root inside GitHub Actions.' >&2
    exit 2
fi
recommends=(--no-install-recommends)
if [[ "${1:-}" == --with-recommends ]]; then
    recommends=()
    shift
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
# Only Ubuntu packages are installed here, so only Ubuntu's archive is read: a third-party source of the runner image
# (Microsoft's answered 403 for hours, "no longer signed") would otherwise fail the update or leave its lists half read.
mkdir -p /etc/apt/sources.list.d.disabled
for source in /etc/apt/sources.list.d/*; do
    [[ -e "$source" ]] || continue
    # Ubuntu's own sources name its archive directly or, on the hosted runners, through apt-mirrors.txt.
    grep -qE 'ubuntu\.com/ubuntu|mirror\+file:/etc/apt/apt-mirrors\.txt' "$source" || mv "$source" /etc/apt/sources.list.d.disabled/
done
apt-get "${native_apt_options[@]}" update
apt-get "${native_apt_options[@]}" install -y "${recommends[@]}" "$@"
