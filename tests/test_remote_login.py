"""telnet and ssh from a PC (or a router) into a router, as Packet Tracer and IOS let them in: the vty lines' password and
login, enable over a vty, usernames and RSA keys for SSH, transport input, access-class, and an address nobody answers."""
import unittest

from network_labs.appliances import command_catalogue, guest_console
from network_labs.appliances.draft_lab import DraftLab
from network_labs.appliances.spec import validate

from tests.test_draft_lab import project

ADDRESSING = ['en', 'conf t', 'int g0/0/0', 'ip add 192.168.1.1 255.255.255.0', 'no shut', 'int g0/0/1', 'ip add 192.168.2.1 255.255.255.0',
              'no shut', 'end']
SSH = ['conf t', 'enable secret class', 'ip domain-name lab.local', 'crypto key generate rsa', 'username admin secret s3cret',
       'line vty 0 4', 'transport input ssh', 'login local', 'end']


class RemoteLoginTest(unittest.TestCase):
    def setUp(self):
        self.box = {'spec': project()}
        self.lab = DraftLab(lambda: self.box['spec'], lambda spec: self.box.update(spec=validate(spec)))
        self.consoles = {}
        self.type('R1', *ADDRESSING)
        self.type('PC1', 'ip addr add 192.168.1.10/24 dev eth0', 'ip route add default via 192.168.1.1')
        self.type('PC2', 'ip addr add 192.168.2.10/24 dev eth0', 'ip route add default via 192.168.2.1')

    def type(self, node, *lines):
        console = self.consoles.setdefault(node, guest_console.Console('mon-lab', node, lambda _: self.lab))
        return [console.line(line) for line in lines]

    def prompt(self, node):
        return self.consoles[node].prompt()

    def test_telnet_with_the_vty_password_then_enable_and_exit(self):
        self.assertEqual(self.type('PC1', 'telnet 192.168.1.1')[0],
                         'Trying 192.168.1.1 ...Open\n\nPassword required, but none set\n\n[Connection to 192.168.1.1 closed by foreign host]')
        self.type('R1', 'conf t', 'line vty 0 4', 'password cisco', 'login', 'end')
        self.assertEqual(self.type('PC1', 'telnet 192.168.1.1')[0], 'Trying 192.168.1.1 ...Open\n\nUser Access Verification\n')
        self.assertEqual(self.prompt('PC1'), 'Password: ')
        self.assertEqual(self.type('PC1', 'wrong'), [''])  # asked again, as IOS
        self.type('PC1', 'cisco')
        self.assertEqual(self.prompt('PC1'), 'R1>')
        self.assertEqual(self.type('PC1', 'en'), ['% No password set'])  # over a vty, IOS wants an enable secret first
        self.assertIn('GigabitEthernet0/0/1   192.168.2.1', self.type('PC1', 'sh ip int br')[0])
        self.assertEqual(self.type('PC1', 'exit'), ['\n[Connection to 192.168.1.1 closed by foreign host]'])
        self.assertEqual(self.prompt('PC1'), 'root@PC1:~# ')

    def test_three_bad_passwords_close_the_connection(self):
        self.type('R1', 'conf t', 'line vty 0 4', 'password cisco', 'login', 'end')
        replies = self.type('PC1', 'telnet 192.168.1.1', 'a', 'b', 'c')
        self.assertEqual(replies[-1], '% Bad passwords\n\n[Connection to 192.168.1.1 closed by foreign host]')
        self.assertEqual(self.prompt('PC1'), 'root@PC1:~# ')

    def test_ssh_with_a_username_and_keys_and_the_access_class(self):
        self.type('R1', *SSH)
        self.assertEqual(self.type('PC1', 'telnet 192.168.1.1')[0], 'Trying 192.168.1.1 ...\n% Connection refused by remote host')
        self.type('PC1', 'ssh -l admin 192.168.1.1', 's3cret', 'en', 'class')
        self.assertEqual(self.prompt('PC1'), 'R1#')
        self.type('PC1', 'exit')
        self.assertEqual(self.type('PC1', 'ssh -l admin 192.168.1.1', 'nope')[-1], '% Login invalid\n')
        self.type('R1', 'conf t', 'access-list 10 permit host 192.168.2.10', 'line vty 0 4', 'access-class 10 in', 'end')
        self.assertEqual(self.type('PC2', 'ssh -l admin 192.168.2.1', 's3cret'), ['', ''])
        self.assertEqual(self.prompt('PC2'), 'R1>')
        self.assertIn('*  2 vty 0     admin      idle                 00:00:00 192.168.2.10', self.type('PC2', 'show users')[0])
        self.consoles.pop('PC1')
        self.assertEqual(self.type('PC1', 'ssh -l admin 192.168.1.1'), ['% Connection refused by remote host'])

    def test_an_address_nobody_answers_and_router_to_router(self):
        self.assertEqual(self.type('PC1', 'telnet 10.9.9.9'), ['Trying 10.9.9.9 ...\n% Connection timed out; remote host not responding'])
        self.type('R1', 'conf t', 'line vty 0 4', 'no login', 'end')
        self.assertEqual(self.type('PC1', 'telnet 192.168.1.1'), ['Trying 192.168.1.1 ...Open\n\nUser Access Verification\n'])
        self.assertEqual(self.prompt('PC1'), 'R1>')  # no login on the vty lines: straight in

    def test_optional_word_groups_in_the_catalogue(self):
        router = next(n for n in self.box['spec']['nodes'] if n['name'] == 'R1')
        for line in ('username admin secret x', 'username admin privilege 15 secret x', 'crypto key generate rsa',
                     'crypto key generate rsa modulus 2048'):
            self.assertEqual(command_catalogue.ios_check(router, 'config', line), ('ok', None), line)


if __name__ == '__main__':
    unittest.main()
