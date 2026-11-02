"""Build pinned BusyBox with a PD-only unicast source-address fix.

Usage: python3 tools/build_pd_busybox.py SOURCE OUTPUT
SOURCE must be a clean checkout of BusyBox 1.36.1. No source is downloaded.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys

PIN = '1a64f6a20aaf6ea4dbba68bbfa8cc1ab7e5c57c4'
MARKER = 'Network LABS PD source-address fix 1'


def build(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    def run(*args):
        return subprocess.run(args, cwd=source, check=True, text=True, stdout=subprocess.PIPE).stdout
    if run('git', 'rev-parse', 'HEAD').strip() != PIN or run('git', 'status', '--porcelain').strip():
        raise SystemExit('Expected a clean BusyBox 1.36.1 checkout at ' + PIN)
    packet = source / 'networking/udhcp/d6_packet.c'
    text = packet.read_text()
    old = 'sa.sin6_addr = *src_ipv6; /* struct copy */'
    if text.count(old) != 1: raise SystemExit('Unexpected BusyBox source layout')
    packet.write_text(text.replace(old, 'sa.sin6_addr = src_ipv6 ? *src_ipv6 : client6_data.ll_ip6; /* PD-only: no IA_NA address */\n\tsa.sin6_scope_id = client_data.ifindex;'))
    client = source / 'networking/udhcp/d6_dhcpc.c'
    text = client.read_text()
    # Add a discoverable compatibility marker to this exact patched applet.
    anchor = '//usage:#define udhcpc6_full_usage "\\n"'
    if text.count(anchor) != 1: raise SystemExit('Unexpected BusyBox help layout')
    client.write_text(text.replace(anchor, anchor + '\n//usage:     "' + MARKER + '\\n"'))
    run('make', 'defconfig')
    config = source / '.config'
    settings = {'STATIC': 'y', 'TC': 'n', 'WERROR': 'n'}
    lines = config.read_text().splitlines()
    for key, value in settings.items():
        lines = [line for line in lines if not line.startswith('CONFIG_' + key + '=') and line != '# CONFIG_' + key + ' is not set']
        lines.append('CONFIG_' + key + '=' + value if value != 'n' else '# CONFIG_' + key + ' is not set')
    config.write_text('\n'.join(lines) + '\n')
    run('make', 'oldconfig')
    run('make', '-j' + str(min(os.cpu_count() or 2, 4)))
    help_text = subprocess.run([source / 'busybox', 'udhcpc6', '--help'], text=True, capture_output=True)
    if MARKER not in help_text.stdout + help_text.stderr: raise SystemExit('Patched PD applet unavailable')
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / 'busybox', output)
    output.chmod(0o755)
    print(output)


if __name__ == '__main__':
    build(*sys.argv[1:])
