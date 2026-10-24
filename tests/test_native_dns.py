"""Local DNS policy, independent resolver ownership, and truthful passive evidence."""
import copy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from network_labs.appliances.dns import server_config, observe_server, observe_resolver
from network_labs.appliances.examples import dns_lab
from network_labs.appliances.ios import compile_config
from network_labs.appliances.runtime import oci_config
from network_labs.appliances.spec import validate


class DNSTests(unittest.TestCase):
    def test_canonical_names_and_no_host_upstream_inheritance(self):
        spec = dns_lab('/rootfs')
        spec['nodes'][2]['dns_server'].update(zone='LAB.Test.', records={'WWW.LAB.TEST.': '10.10.0.20'})
        node = validate(spec)['nodes'][2]
        text = server_config(node)
        self.assertEqual(node['dns_server']['records'], {'www.lab.test': '10.10.0.20'})
        for line in ('no-resolv', 'no-hosts', 'cache-size=0', 'bind-interfaces', 'listen-address=10.10.0.2',
                     'local=/lab.test/', 'host-record=www.lab.test,10.10.0.20,60'):
            self.assertIn(line + '\n', text)
        self.assertNotIn('server=', text)
        self.assertNotIn('dhcp-range', text)  # Existing BusyBox DHCP remains a separate daemon.

    def test_unrepresentable_or_injectable_dns_policy_is_rejected(self):
        changes = [dict(zone='localhost'), dict(zone='lab.test\nserver=8.8.8.8'), dict(ttl=True), dict(ttl=86401),
                   dict(records={}), dict(records={'evil.test': '10.10.0.20'}),
                   dict(records={'*.lab.test': '10.10.0.20'}), dict(records={'é.lab.test': '10.10.0.20'}),
                   dict(records={'a.lab.test': '127.0.0.1'}), dict(records={'a.lab.test': '224.0.0.1'}),
                   dict(records={'a.lab.test': '0.0.0.0'}), dict(records={'a.lab.test': '255.255.255.255'}),
                   dict(records={'a.lab.test': '10.10.0.20\nserver=8.8.8.8'}),
                   dict(records={'a.lab.test': 168427540}),
                   dict(records={'A.lab.test.': '10.10.0.20', 'a.lab.test': '10.10.0.21'}),
                   dict(records={'a.lab.test': '10.10.0.20', 'b.lab.test': '10.10.0.20'}),
                   dict(upstream='8.8.8.8'), dict(interface='eth9')]
        for change in changes:
            spec = dns_lab('/rootfs'); spec['nodes'][2]['dns_server'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate(spec)

    def test_many_long_names_cannot_exceed_the_observable_config_budget(self):
        spec = dns_lab('/rootfs')
        prefix = ('x' * 60 + '.') * 3
        spec['nodes'][2]['dns_server']['records'] = {
            prefix + 'y' * 50 + f'{i:03}.lab.test': f'10.20.{i // 254}.{i % 254 + 1}' for i in range(256)}
        with self.assertRaisesRegex(ValueError, '64 KiB'):
            validate(spec)

    def test_static_resolver_cannot_compete_with_dhcp_or_untracked_startup(self):
        for resolvers in ('10.10.0.2', ['127.0.0.1'], ['10.10.0.2'] * 2, ['1.1.1.1'] * 4):
            spec = dns_lab('/rootfs'); spec['nodes'][4]['resolvers'] = resolvers
            with self.subTest(resolvers=resolvers), self.assertRaises(ValueError):
                validate(spec)
        spec = dns_lab('/rootfs'); spec['nodes'][0]['resolvers'] = ['10.10.0.2']
        with self.assertRaisesRegex(ValueError, 'DHCP'):
            validate(spec)
        for index in (2, 4):
            spec = dns_lab('/rootfs'); spec['nodes'][index]['startup'] = [['/bin/true']]
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate(spec)

    def test_static_resolver_is_readonly_per_node_and_dhcp_file_stays_writable(self):
        spec = dns_lab('/rootfs')
        mounts = oci_config(spec, spec['nodes'][4], 4, '/bundle/rootfs')['mounts']
        resolver = next(m for m in mounts if m['destination'] == '/etc/resolv.conf')
        self.assertEqual(resolver['source'], '/bundle/files/resolv.conf')
        self.assertIn('ro', resolver['options'])
        self.assertFalse(any(m['destination'] == '/etc/resolv.conf'
                             for m in oci_config(spec, spec['nodes'][0], 0, '/bundle/rootfs')['mounts']))

    def test_config_conformity_never_claims_running_or_successful_resolution(self):
        node = dns_lab('/rootfs')['nodes'][2]
        for code, output, verified in ((0, server_config(node), True), (0, 'changed', False), (1, '', False), (0, 'x' * 65537, False)):
            manager = Mock()
            manager.crun.return_value = subprocess.CompletedProcess([], code, output, '')
            manager.ns.return_value = subprocess.CompletedProcess([], 0, '', '')
            observed = observe_server(manager, 2, node)
            self.assertEqual(observed['configuration_verified'], verified)
            self.assertEqual(observed['listener_snapshot'], [])
            for key in ('running', 'ready', 'resolved'):
                self.assertNotIn(key, observed)
        manager.crun.side_effect = subprocess.TimeoutExpired('crun', 5)
        self.assertFalse(observe_server(manager, 2, node)['configuration_available'])
        manager.crun.side_effect = None
        manager.crun.return_value = subprocess.CompletedProcess([], 0, 'nameserver 10.10.0.2\n', '')
        self.assertTrue(observe_resolver(manager, dns_lab('/rootfs')['nodes'][4])['configuration_verified'])

    def test_partial_ios_adapter_refuses_managed_dns_node_without_mutating_input(self):
        spec = dns_lab('/rootfs'); spec['nodes'][2]['dialect'] = 'ios-basic'
        before = copy.deepcopy(spec)
        with self.assertRaisesRegex(ValueError, 'DHCP|DNS'):
            compile_config(spec, 'DNS1', 'conf t\ninterface eth0\nshutdown\nend')
        self.assertEqual(spec, before)

    def test_offline_assets_require_real_elf_identity_and_complete_dependencies(self):
        import struct
        from network_labs.appliances.dns_rootfs import assets
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / 'dnsmasq'
            binary.write_bytes(b'not an executable')
            with self.assertRaisesRegex(ValueError, 'ELF'):
                assets(binary)
            raw = bytearray(160); raw[:6] = b'\x7fELF\x02\x01'
            struct.pack_into('<Q', raw, 32, 64)
            struct.pack_into('<HH', raw, 54, 56, 1)
            struct.pack_into('<I', raw, 64, 3)
            loader = (str(Path(folder) / 'loader') + '\0').encode()
            struct.pack_into('<Q', raw, 72, 120); struct.pack_into('<Q', raw, 96, len(loader))
            raw[120:120 + len(loader)] = loader
            binary.write_bytes(raw)
            (Path(folder) / 'loader').write_bytes(b'loader')
            library = Path(folder) / 'lib.so'; library.write_bytes(b'lib')
            version = subprocess.CompletedProcess([], 0, 'Dnsmasq version 2.test\n', '')
            missing = subprocess.CompletedProcess([], 0, 'lib.so => not found\n', '')
            with patch('network_labs.appliances.dns_rootfs.subprocess.run', side_effect=[version, missing]):
                with self.assertRaisesRegex(ValueError, 'libraries'):
                    assets(binary)
            linked = subprocess.CompletedProcess([], 0, f'lib.so => {library} (0x123)\n', '')
            with patch('network_labs.appliances.dns_rootfs.subprocess.run', side_effect=[version, linked]) as execute, \
                 patch.dict('os.environ', {'LD_PRELOAD': '/bad', 'LD_LIBRARY_PATH': '/bad', 'LD_AUDIT': '/bad'}):
                planned = dict((str(target), source) for source, target in assets(binary))
                self.assertEqual(planned['/usr/sbin/dnsmasq'], binary)
                self.assertEqual(planned[str(library)], library)
                self.assertIn(str(Path(folder) / 'loader'), planned)
                self.assertFalse({'LD_PRELOAD', 'LD_LIBRARY_PATH', 'LD_AUDIT'} & execute.call_args.kwargs['env'].keys())


# Test client only: executed by host Python in the owned client netns. The
# production DNS responder is dnsmasq, never this packet encoder/decoder.
DNS_QUERY = r'''
import socket,struct,sys
host,kind,transport=sys.argv[1],int(sys.argv[2]),sys.argv[3]
question=b''.join(bytes([len(label)])+label.encode('ascii') for label in host.split('.'))+b'\0'+struct.pack('!HH',kind,1)
packet=struct.pack('!6H',0x5a19,0x0100,1,0,0,0)+question
with socket.socket(socket.AF_INET,socket.SOCK_STREAM if transport=='tcp' else socket.SOCK_DGRAM) as sock:
    sock.settimeout(2)
    sock.connect((sys.argv[4] if len(sys.argv)>4 else '10.10.0.2',53))
    if transport=='tcp':
        sock.sendall(struct.pack('!H',len(packet))+packet)
        def exact(size):
            data=b''
            while len(data)<size:
                part=sock.recv(size-len(data))
                if not part: raise EOFError('DNS TCP frame closed early')
                data+=part
            return data
        response=exact(struct.unpack('!H',exact(2))[0])
    else:
        sock.send(packet)
        response=sock.recv(65535)
    print(response.hex())
'''


def dns_response(hexadecimal):
    """Decode enough RFC 1035 wire data to assert actual A/PTR/negative replies."""
    import socket
    import struct
    packet = bytes.fromhex(hexadecimal.strip())
    identifier, flags, questions, answers, _, _ = struct.unpack_from('!6H', packet)
    if identifier != 0x5a19 or not flags & 0x8000 or flags & 0x0200:
        raise AssertionError('Unexpected DNS identity, direction or truncation')
    def domain(offset, seen=()):
        labels = []
        while True:
            if offset in seen or len(seen) > 128:
                raise AssertionError('DNS compression loop')
            seen += (offset,)
            length = packet[offset]; offset += 1
            if length & 0xc0 == 0xc0:
                target = ((length & 0x3f) << 8) | packet[offset]
                suffix, _ = domain(target, seen)
                return '.'.join(labels + [suffix]), offset + 1
            if length == 0:
                return '.'.join(labels), offset
            if length > 63:
                raise AssertionError('Invalid DNS label')
            labels.append(packet[offset:offset + length].decode('ascii'))
            offset += length
    offset = 12
    for _ in range(questions):
        _, offset = domain(offset); offset += 4
    records = []
    for _ in range(answers):
        owner, offset = domain(offset)
        kind, cls, ttl, size = struct.unpack_from('!HHIH', packet, offset); offset += 10
        if kind == 1 and size == 4:
            value = socket.inet_ntoa(packet[offset:offset + size])
        elif kind == 12:
            value, _ = domain(offset)
        else:
            value = packet[offset:offset + size].hex()
        records.append((owner, kind, cls, ttl, value))
        offset += size
    return flags & 15, records
