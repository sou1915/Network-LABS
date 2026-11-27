"""Server services on micro-VMs (guest_services, service_commands): a server's DNS, HTTP, NTP and Syslog services and IOS's
« ip dns server », « ip host », « ip name-server », « ntp master », « ntp server », « logging host », « logging trap »,
« ip http server »; what the guest runs, the requests it gets, and the terminal commands on a stopped lab (the project
answers through the network model). The agent's own daemon is checked for real in network namespaces when the test runs
as root with gcc (two namespaces joined by a veth: DNS, PTR, CNAME, BusyBox nslookup against it, NTP server and client,
syslog collection, the web server)."""
import copy
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from network_labs.appliances import guest_console, guest_services, topology_edit
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.guest_control import service_command
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project

R1 = ['en', 'conf t', 'int g0/0/0', 'ip address 192.168.1.1 255.255.255.0', 'no shut', 'int g0/0/1', 'ip address 10.0.0.1 255.255.255.0',
      'no shut', 'exit', 'ip name-server 10.0.0.10', 'ip host printer 192.168.1.50', 'ntp server 10.0.0.10', 'logging host 10.0.0.10',
      'logging trap warnings', 'end']


def lab(kernel='/k', disk='/d'):
    spec = blank_project('svc')
    spec = topology_edit.add_microvm_node(spec, name='R1', role='router', kernel=kernel, disk=disk, ports=2, model='cisco-isr4331')
    spec = topology_edit.add_microvm_node(spec, name='SRV', role='host', kernel=kernel, disk=disk, ports=1, addresses='10.0.0.10/24')
    spec = topology_edit.add_microvm_node(spec, name='PC1', role='host', kernel=kernel, disk=disk, ports=1, addresses='192.168.1.10/24')
    for name, gateway in (('SRV', '10.0.0.1'), ('PC1', '192.168.1.1')):
        next(n for n in spec['nodes'] if n['name'] == name)['gateway'] = gateway
    server = next(n for n in spec['nodes'] if n['name'] == 'SRV')
    server['services'] = guest_services.default_services('SRV')
    server['services']['dns'] = {'on': True, 'records': [['www.lab.local', 'A', '10.0.0.10'], ['web.lab.local', 'CNAME', 'www.lab.local']]}
    server['services']['ntp'] = {'on': True}
    server['services']['syslog'] = {'on': True}
    server['services']['tftp'] = {'on': True, 'files': {}}
    next(n for n in spec['nodes'] if n['name'] == 'PC1')['resolvers'] = ['10.0.0.10']
    spec = topology_edit.connect(spec, ('R1', 'eth0'), ('PC1', 'eth0'))
    spec = topology_edit.connect(spec, ('R1', 'eth1'), ('SRV', 'eth0'))
    return validate(spec)


def configured(kernel='/k', disk='/d'):
    """The lab with R1's lines typed in its CLI (on the project)."""
    box = {'spec': lab(kernel, disk)}
    draft = DraftLab(lambda: box['spec'], lambda spec: box.update(spec=validate(spec)))
    console = guest_console.Console('svc', 'R1', lambda _: draft)
    for line in R1:
        console.line(line)
    return box['spec']


class ServicesModelTest(unittest.TestCase):
    def setUp(self):
        self.box = {'spec': lab()}
        self.draft = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))
        router = guest_console.Console('svc', 'R1', lambda _: self.draft)
        self.typed = [router.line(line) for line in R1]
        self.router = guest_console.Console('svc', 'R1', lambda _: self.draft)
        self.router.line('en')
        self.pc = guest_console.Console('svc', 'PC1', lambda _: self.draft)

    def node(self, name):
        return next(n for n in self.box['spec']['nodes'] if n['name'] == name)

    def test_the_guests_get_their_services(self):
        tokens, pages = guest_services.wanted(self.node('SRV'))
        self.assertEqual(tokens, ['dns', 'a:www.lab.local=10.0.0.10', 'cname:web.lab.local=www.lab.local', 'ntp:1', 'syslog', 'tftp'])
        self.assertEqual(sorted(pages), ['hello.html', 'index.html'])
        self.assertEqual(guest_services.wanted(self.node('R1')), (['sync:10.0.0.10'], None))
        self.assertEqual(guest_services.log_hosts(self.node('R1')), ['10.0.0.10'])
        self.assertEqual(guest_services.trap_level(self.node('R1')), 4)
        # every token is one the agent request accepts
        self.assertTrue(service_command('services-start', tokens).startswith('SERVICES_START dns a:www.lab.local=10.0.0.10'))

    def test_ios_lines_make_a_dns_and_ntp_server(self):
        console = guest_console.Console('svc', 'R1', lambda _: self.draft)
        for line in ['en', 'conf t', 'ip host intranet.lab.local 192.168.1.80 192.168.1.81', 'ip dns server', 'ntp master 3',
                     'ip http server', 'end']:
            self.assertNotIn('% Invalid', console.line(line), line)
        tokens, pages = guest_services.wanted(self.node('R1'))
        self.assertEqual(tokens, ['dns', 'a:intranet.lab.local=192.168.1.80', 'a:intranet.lab.local=192.168.1.81', 'a:printer=192.168.1.50',
                                  'ntp:3', 'sync:10.0.0.10'])
        self.assertIn('index.html', pages)

    def test_ios_resolves_names_and_shows_ntp_and_logging(self):
        reply = self.router.line('ping www.lab.local')
        self.assertIn('Translating "www.lab.local"...domain server (10.0.0.10) [OK]', reply)
        self.assertIn('Success rate is 100 percent (5/5)', reply)
        self.assertIn('% Unrecognized host or address, or protocol not running.', self.router.line('ping nothere.lab.local'))
        self.assertIn('printer                   None  (perm, OK)  0   IP    192.168.1.50', self.router.line('show hosts'))
        self.assertTrue(self.router.line('show ntp status').startswith('Clock is synchronized, stratum 2, reference is 10.0.0.10'))
        self.assertIn('*~10.0.0.10', self.router.line('sh ntp assoc'))
        self.assertFalse(self.router.line('show clock').startswith('*'))  # NTP: the clock is authoritative
        shown = self.router.line('show logging')
        self.assertIn('Trap logging: level warnings', shown)
        self.assertIn('Logging to 10.0.0.10  (udp port 514', shown)
        self.assertIn('%SYS-5-CONFIG_I: Configured from console by console', shown)
        running = self.router.line('show running-config')
        for line in ('ip host printer 192.168.1.50', 'ip name-server 10.0.0.10', 'ntp server 10.0.0.10', 'logging host 10.0.0.10'):
            self.assertIn(line, running)

    def test_without_ntp_the_clock_is_not_authoritative(self):
        self.router.line('conf t')
        self.router.line('no ntp server 10.0.0.10')
        self.router.line('end')
        self.assertTrue(self.router.line('show clock').startswith('*'))
        self.assertTrue(self.router.line('show ntp status').startswith('Clock is unsynchronized, stratum 16'))

    def test_a_pc_looks_up_names_and_browses(self):
        self.assertIn('Name:\twww.lab.local\nAddress: 10.0.0.10', self.pc.line('nslookup www.lab.local'))
        self.assertIn('web.lab.local\tcanonical name = www.lab.local', self.pc.line('nslookup web.lab.local'))
        self.assertIn("** server can't find nope.lab.local: NXDOMAIN", self.pc.line('nslookup nope.lab.local'))
        self.assertIn('10.0.0.10.in-addr.arpa\tname = www.lab.local', self.pc.line('nslookup 10.0.0.10'))
        pinged = self.pc.line('ping web.lab.local')
        self.assertIn('PING web.lab.local (10.0.0.10): 56 data bytes', pinged)
        self.assertIn('--- web.lab.local ping statistics ---', pinged)
        self.assertIn('<h1>Hello, World!</h1>', self.pc.line('wget -qO- http://web.lab.local/hello.html'))
        self.assertIn('404 Not Found', self.pc.line('curl http://www.lab.local/none.html'))
        self.assertTrue(self.pc.line('curl -i http://10.0.0.10/').startswith('HTTP/1.1 200 OK'))
        self.assertIn('Connection refused', self.pc.line('curl http://192.168.1.1/'))
        self.assertEqual(self.pc.line('ping nobody.lab.local'), "ping: bad address 'nobody.lab.local'")

    def test_a_windows_pc_answers_as_windows(self):
        self.node('PC1')['model'] = 'windows-11'
        self.box['spec'] = validate(self.box['spec'])
        pinged = self.pc.line('ping web.lab.local')
        self.assertTrue(pinged.startswith("Envoi d’une requête 'Ping'  web.lab.local [10.0.0.10] avec 32 octets de données :"), pinged)
        self.assertIn('Paquets : envoyés = 4, reçus = 4, perdus = 0 (perte 0%),', pinged)
        self.assertIn('La requête Ping n’a pas pu trouver l’hôte nobody.lab.local.', self.pc.line('ping nobody.lab.local'))
        self.assertEqual(self.pc.line('nslookup web.lab.local'),
                         'Serveur :   UnKnown\nAddress:  10.0.0.10\n\nNom :    www.lab.local\nAddress:  10.0.0.10\nAliases:  web.lab.local')
        self.assertIn('*** UnKnown ne parvient pas à trouver nope.lab.local : Non-existent domain', self.pc.line('nslookup nope.lab.local'))

    def test_a_firewall_rule_or_a_stopped_service_breaks_the_lookup(self):
        server = self.node('SRV')
        server['services']['dns']['on'] = False
        self.box['spec'] = validate(self.box['spec'])
        self.assertEqual(self.pc.line('nslookup www.lab.local'), ';; connection timed out; no servers could be reached')
        server = self.node('SRV')
        server['services']['dns']['on'] = True
        server['services']['http']['on'] = False
        self.box['spec'] = validate(self.box['spec'])
        self.assertIn('Connection refused', self.pc.line('curl http://www.lab.local/'))

    def test_a_router_backs_its_configuration_up_to_tftp_and_restores_it(self):
        self.assertEqual(self.router.line('copy running-config tftp:'), '')
        self.assertEqual(self.router.prompt(), 'Address or name of remote host []? ')
        self.assertEqual(self.router.line('10.0.0.10'), '')
        self.assertEqual(self.router.prompt(), 'Destination filename [r1-confg]? ')
        self.assertRegex(self.router.line(''), r'^!!\n\d+ bytes copied in [\d.]+ secs')
        saved = guest_services.tftp_files(self.node('SRV'))['r1-confg']
        self.assertIn('hostname R1', saved)
        self.assertIn('ip host printer 192.168.1.50', saved)
        server = guest_console.Console('svc', 'SRV', lambda _: self.draft)
        self.assertIn('r1-confg', server.line('ls -l /tftpboot'))
        self.assertIn('ip name-server 10.0.0.10', server.line('cat /tftpboot/r1-confg'))
        for line in ('conf t', 'hostname CHANGED', 'no ip host printer', 'end'):
            self.router.line(line)
        self.assertNotIn('ip host printer', self.router.line('show running-config'))
        for line in ('copy tftp: running-config', '10.0.0.10', 'r1-confg'):
            self.assertEqual(self.router.line(line), '')
        restored = self.router.line('')
        self.assertIn('[OK - ', restored)
        self.assertTrue(restored.endswith('%SYS-5-CONFIG_I: Configured from tftp://10.0.0.10/r1-confg by console'))
        running = self.router.line('show running-config')
        self.assertIn('hostname R1', running)  # merged back, as IOS does
        self.assertIn('ip host printer 192.168.1.50', running)
        self.assertEqual(self.router.line('copy tftp://10.0.0.99/x running-config'), '')  # Destination filename [running-config]?
        self.assertIn('%Error opening tftp://10.0.0.99/x (Timed out)', self.router.line(''))
        self.assertEqual(self.router.line('copy startup-config tftp://10.0.0.10/s.cfg'),
                         '%Error opening nvram:startup-config (No such file or directory)')

    def test_services_are_checked(self):
        spec = lab()
        for bad in ({'dns': {'on': True, 'records': [['bad name', 'A', '10.0.0.1']]}}, {'dns': {'on': True, 'records': [['a.lab', 'MX',
                                                                                                                         'x']]}},
                    {'dns': {'on': True, 'records': [['a.lab', 'A', '300.1.1.1']]}}, {'http': {'on': True, 'pages': {'../x.html': 'x'}}},
                    {'http': {'on': True, 'pages': {'a.php': 'x'}}}, {'ftp': {'on': True}}, {'ntp': {'on': 'yes'}},
                    {'dns': {'on': True, 'records': [['a.lab', 'CNAME', 'b.lab'], ['a.lab', 'A', '10.0.0.1']]}}):
            candidate = copy.deepcopy(spec)
            next(n for n in candidate['nodes'] if n['name'] == 'SRV')['services'] = bad
            with self.subTest(services=bad), self.assertRaises(ValueError):
                validate(candidate)
        router = copy.deepcopy(spec)
        next(n for n in router['nodes'] if n['name'] == 'R1')['services'] = {'dns': {'on': True}}
        with self.assertRaises(ValueError):
            validate(router)

    def test_guest_requests_are_checked(self):
        self.assertEqual(service_command('resolve', ['10.0.0.10', 'www.lab.local']), 'RESOLVE 10.0.0.10 www.lab.local')
        self.assertEqual(service_command('syslog-send', ['10.0.0.10', '<189>1: x']), 'SYSLOG_SEND 10.0.0.10 3c3138393e313a2078')
        self.assertEqual(service_command('http-get', ['10.0.0.10', 80, '/a.html']), 'HTTP_GET 10.0.0.10 80 /a.html')
        for operation, values in (('services-start', ['dns;reboot']), ('services-start', []), ('resolve', ['10.0.0.10', 'a b']),
                                  ('http-get', ['10.0.0.10', 80, '/../etc/passwd']), ('http-page', ['../x.html', b'x']),
                                  ('syslog-send', ['10.0.0.10', 'no pri']), ('services-show', ['x']), ('ntp-query', ['host.lab'])):
            with self.subTest(operation=operation, values=values), self.assertRaises(ValueError):
                service_command(operation, values)

    def test_syslog_datagrams_are_ios_ones(self):
        import datetime
        when = datetime.datetime(2026, 11, 26, 10, 0, 1, 123000)
        self.assertEqual(guest_services.syslog_message('R1', 7, '%LINK-3-UPDOWN: Interface GigabitEthernet0/0/0, changed state to up',
                                                       when),
                         (3, '<187>7: *Nov 26 10:00:01.123: %LINK-3-UPDOWN: Interface GigabitEthernet0/0/0, changed state to up'))


@unittest.skipUnless(shutil.which('gcc') and shutil.which('ip') and os.geteuid() == 0 and Path('/bin/busybox').exists(),
                     'root, gcc, iproute2 and BusyBox required for the agent in network namespaces')
class AgentServicesTest(unittest.TestCase):
    """The agent's --services daemon and its clients, for real between two network namespaces."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        root, agent = Path(cls.folder.name), Path('network_labs/appliances/guest/agent.c').resolve()
        harness = root / 'harness.c'
        harness.write_text(f'#define main agent_main\n#include "{agent}"\n#undef main\nint main(int argc, char **argv) {{\n'
                           '    int pipes[2]; if (argc != 2 || pipe(pipes)) return 2;\n'
                           '    dprintf(pipes[1], "%s\\n", argv[1]); close(pipes[1]); serve(pipes[0], 1, 1); return 0;\n}\n')
        for side in ('srv', 'pc'):
            (root / side).mkdir()
            defines = [f'-DSERVICES_RUN="{root / side}"', f'-DAGENT_PROGRAM="{root / ("agent_" + side)}"']
            subprocess.run(['gcc', '-Wall', '-Wextra', '-Werror', *defines, '-o', str(root / ('agent_' + side)), str(agent)], check=True)
            subprocess.run(['gcc', '-Wall', '-Wno-unused-function', *defines, '-o', str(root / ('h_' + side)), str(harness)], check=True)
        cls.root = root
        tag = str(os.getpid())
        cls.spaces = (f'nls{tag}', f'nlp{tag}')
        commands = [['ip', 'netns', 'add', cls.spaces[0]], ['ip', 'netns', 'add', cls.spaces[1]],
                    ['ip', 'link', 'add', 'vs' + tag, 'type', 'veth', 'peer', 'name', 'vp' + tag],
                    ['ip', 'link', 'set', 'vs' + tag, 'netns', cls.spaces[0]], ['ip', 'link', 'set', 'vp' + tag, 'netns', cls.spaces[1]],
                    ['ip', '-n', cls.spaces[0], 'addr', 'add', '10.9.0.1/24', 'dev', 'vs' + tag], ['ip', '-n', cls.spaces[0], 'link',
                                                                                                   'set', 'vs' + tag, 'up'],
                    ['ip', '-n', cls.spaces[1], 'addr', 'add', '10.9.0.2/24', 'dev', 'vp' + tag], ['ip', '-n', cls.spaces[1], 'link',
                                                                                                   'set', 'vp' + tag, 'up'],
                    ['ip', '-n', cls.spaces[0], 'link', 'set', 'lo', 'up'], ['ip', '-n', cls.spaces[1], 'link', 'set', 'lo', 'up']]
        try:
            for command in commands:
                subprocess.run(command, check=True, capture_output=True)
        except subprocess.CalledProcessError as error:
            cls.tearDownClass()
            raise unittest.SkipTest(f'network namespaces unavailable: {error.stderr.decode(errors="replace").strip()}')

    @classmethod
    def tearDownClass(cls):
        for side, space in zip(('srv', 'pc'), cls.spaces):
            for request in ('SERVICES_STOP', 'HTTP_STOP'):
                subprocess.run(['ip', 'netns', 'exec', space, str(cls.root / ('h_' + side)), 'NL1 ' + request], capture_output=True)
            subprocess.run(['ip', 'netns', 'del', space], capture_output=True)
        cls.folder.cleanup()

    def ask(self, side, request):
        space = self.spaces[0 if side == 'srv' else 1]
        out = subprocess.run(['ip', 'netns', 'exec', space, str(self.root / ('h_' + side)), 'NL1 ' + request], capture_output=True,
                             timeout=10).stdout
        header, _, body = out.partition(b'\n')
        return int(header.split()[1]), body.decode()

    def test_dns_ntp_syslog_and_web_for_real(self):
        self.assertEqual(self.ask('srv', service_command('services-start', ['dns', 'a:www.lab.local=10.9.0.1', 'a:www.lab.local=10.9.0.3',
                                                                             'cname:web.lab.local=www.lab.local', 'ntp:3', 'syslog'])), (0,
                                                                                     ''))
        self.assertEqual(self.ask('pc', 'RESOLVE 10.9.0.1 www.lab.local'), (0, 'A 10.9.0.1\nA 10.9.0.3\n'))
        self.assertEqual(self.ask('pc', 'RESOLVE 10.9.0.1 WEB.lab.local'), (0, 'CNAME www.lab.local\nA 10.9.0.1\nA 10.9.0.3\n'))
        self.assertEqual(self.ask('pc', 'RESOLVE 10.9.0.1 nope.lab.local'), (1, 'NXDOMAIN'))
        self.assertEqual(self.ask('pc', 'RESOLVE 10.9.0.1 10.9.0.1'), (0, 'PTR www.lab.local\n'))
        looked = subprocess.run(['ip', 'netns', 'exec', self.spaces[1], 'busybox', 'nslookup', 'web.lab.local', '10.9.0.1'],
                                capture_output=True, text=True, timeout=10).stdout
        self.assertIn('canonical name = www.lab.local', looked)  # BusyBox's own resolver, against the agent's server
        code, ntp = self.ask('pc', 'NTP_QUERY 10.9.0.1')
        self.assertEqual((code, ntp.split()[:2]), (0, ['stratum', '3']))
        self.assertEqual(self.ask('pc', service_command('syslog-send', ['10.9.0.1',
                                                                        '<189>12: *Nov 26 10:00:01.000: %SYS-5-CONFIG_I: test'])), (0, ''))
        time.sleep(.3)
        self.assertIn('10.9.0.2 <189>12: *Nov 26 10:00:01.000: %SYS-5-CONFIG_I: test', self.ask('srv', 'SYSLOG_READ')[1])
        self.assertEqual(self.ask('srv', service_command('http-page', ['index.html', b'<h1>Hello from SRV</h1>'])), (0, ''))
        self.assertEqual(self.ask('srv', 'HTTP_START'), (0, ''))
        time.sleep(.5)
        code, page = self.ask('pc', 'HTTP_GET 10.9.0.1 80 /')
        self.assertEqual(code, 0)
        self.assertTrue(page.startswith('HTTP/1.1 200 OK'), page)
        self.assertIn('<h1>Hello from SRV</h1>', page)
        self.assertEqual(self.ask('pc', service_command('services-start', ['sync:10.9.0.1'])), (0, ''))
        time.sleep(2.5)
        sync = guest_services.parse_state(self.ask('pc', 'SERVICES_SHOW')[1])['sync']
        self.assertEqual((sync['server'], sync['synced'], sync['stratum']), ('10.9.0.1', '1', '3'))
        shown = guest_services.parse_state(self.ask('srv', 'SERVICES_SHOW')[1])
        self.assertEqual((shown['dns']['records'], shown['syslog']['messages'], shown['http']), ('3', '1', True))
        self.assertEqual(self.ask('srv', 'SERVICES_STOP'), (0, ''))
        self.assertEqual(self.ask('srv', 'HTTP_STOP'), (0, ''))
        self.assertEqual(self.ask('pc', 'RESOLVE 10.9.0.1 www.lab.local'), (1, 'timeout'))
        self.assertEqual(self.ask('pc', 'HTTP_GET 10.9.0.1 80 /'), (1, 'connection refused'))

    def test_tftp_for_real(self):
        from network_labs.appliances.guest_control import service_command
        self.assertEqual(self.ask('srv', service_command('services-start', ['tftp'])), (0, ''))
        text = ''.join(f'interface GigabitEthernet0/0/{i}\n ip address 10.0.{i}.1 255.255.255.0\n!\n' for i in range(60))  # several blocks
        data = text.encode()
        for i in range(0, len(data), 1000):
            self.assertEqual(self.ask('pc', service_command('file-put', ['out', 'r1-confg', data[i:i + 1000]])), (0, ''))
        self.assertEqual(self.ask('pc', 'TFTP_PUT 10.9.0.1 r1-confg'), (0, str(len(data))))
        self.assertEqual(self.ask('srv', 'TFTP_FILES'), (0, f'r1-confg {len(data)}\n'))
        self.assertEqual(self.ask('pc', 'TFTP_GET 10.9.0.1 r1-confg'), (0, text))
        self.assertEqual(self.ask('pc', 'TFTP_GET 10.9.0.1 missing'), (1, 'File not found'))
        self.assertEqual(self.ask('srv', 'SERVICES_STOP'), (0, ''))
        self.assertEqual(self.ask('pc', 'TFTP_GET 10.9.0.1 r1-confg'), (1, 'Timed out'))

    def test_bad_requests_are_refused(self):
        for request in ('SERVICES_START dns;id', 'SERVICES_START a:bad name=1.2.3.4', 'HTTP_PAGE ../x.html 41', 'HTTP_PAGE a.php 41',
                        'FILE_PUT etc passwd 41', 'FILE_PUT out ../x 41', 'TFTP_GET 10.9.0.1 ../etc', 'TFTP_READ .hidden',
                        'HTTP_GET 10.9.0.1 80 /../etc/passwd', 'SYSLOG_SEND 10.9.0.1 zz', 'RESOLVE 10.9.0.1 -x'):
            with self.subTest(request=request):
                self.assertEqual(self.ask('srv', request)[0], 2)


if __name__ == '__main__':
    unittest.main()
