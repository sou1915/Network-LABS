"""Opt-in real OCI boot/packet tests, and what their modules share. Run on a disposable Linux host with sudo.

NETWORK_LABS_NATIVE_TESTS=1 requires crun, iproute2, busybox-static, nftables, conntrack, tcpdump and nsenter. These
tests are deliberately never replaced with mocks when explicitly requested.
"""
import os
import json
import sys
from pathlib import Path
import time
import unittest

from network_labs.appliances.runtime import RuntimeFailure


def unexpected_host_link_changes(before, after, hardware_names=()):
    return {'removed_or_replaced': before - after,
            'added_virtual': {entry for entry in after - before if entry[0] not in hardware_names}}


def solicit_ipv6_router(manager, index):
    """Send a real Router Solicitation after capture readiness, not a fake RA.

    A fixed capture window need not overlap an unsolicited advertisement.
    Linux supplies the ICMPv6 checksum and the interface link-local source.
    A newly created/restarted node may still be performing link-local DAD;
    sending then fails with EADDRNOTAVAIL before any packet reaches the guard.
    """
    deadline = time.monotonic() + 5
    while True:
        records = json.loads(manager.ns(index, 'ip', '-j', '-6', 'addr', 'show', 'dev', 'eth0', timeout=2).stdout)
        addresses = [a for row in records for a in row.get('addr_info', []) if a.get('scope') == 'link']
        if any(a.get('dadfailed') or 'dadfailed' in a.get('flags', []) for a in addresses):
            raise RuntimeFailure('Router Solicitation source failed link-local DAD on eth0')
        if any(not a.get('tentative') and 'tentative' not in a.get('flags', []) and
               a.get('preferred_life_time', 0) != 0 for a in addresses):
            break
        if time.monotonic() >= deadline:
            raise RuntimeFailure('Router Solicitation requires a usable link-local source on eth0: ' + repr(records))
        time.sleep(.1)
    code = (
        "import socket; index=socket.if_nametoindex('eth0'); "
        "sock=socket.socket(socket.AF_INET6,socket.SOCK_RAW,socket.IPPROTO_ICMPV6); "
        "sock.settimeout(2); sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_MULTICAST_IF,index); "
        "sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_MULTICAST_HOPS,255); "
        "sock.sendto(bytes([133,0,0,0,0,0,0,0]),('ff02::2',0,0,index)); sock.close()"
    )
    manager.ns(index, sys.executable, '-I', '-c', code, timeout=3)


def ipv6_default_expired(manager, index, destination):
    """Expired fib6 entries may remain observable until GC releases them.

    Require actual elapsed lifetime (or absence) AND failed kernel selection;
    never flush the route or confuse an absent source address with this check.
    """
    routes = json.loads(manager.ns(index, 'ip', '-j', '-6', 'route', 'show', 'table', 'main').stdout)
    defaults = [r for r in routes if r.get('dst') == 'default']
    if any(type(r.get('expires')) is not int or r['expires'] > 0 for r in defaults):
        return False
    return manager.ns(index, 'ip', '-6', 'route', 'get', destination, check=False, timeout=3).returncode != 0


NATIVE = os.environ.get('NETWORK_LABS_NATIVE_TESTS') == '1'
# The tests themselves, one module per topic: test_native_integration_{services,management,ipv6,dhcp,routing,switching,
# security,lab}.py (python3 -m unittest discover -s tests -p 'test_native_integration*.py' runs them all).


class RealContainerCase(unittest.TestCase):
    """What the topic modules' test classes share."""

    def assertHostLinksUnchanged(self, before, after):
        # Hosted runners may hotplug a hardware-backed Azure VF mid-job.
        # Preserve every baseline identity and reject all added virtual links;
        # the engine cannot create a PCI device. Do not whitelist by name.
        hardware = {name for name, _ in after - before if (Path('/sys/class/net') / name / 'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before, after, hardware),
                         {'removed_or_replaced': set(), 'added_virtual': set()})
