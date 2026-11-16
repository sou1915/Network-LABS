import unittest
from network_labs.engine import Lab,Node
from network_labs.vendor_cli import console_session
from network_labs.cli import Session

class NativeConsoleTests(unittest.TestCase):
 def lab(self,profile,kind='Switch'):
  lab=Lab();lab.add(Node('D1',kind,profile=profile));return lab,console_session(lab,'D1')
 def run_lines(self,console,lines):
  for line in lines.splitlines():
   result=console.execute(line)
   self.assertFalse(result.startswith('%'),(line,result))
 def test_fortios_hostname_interfaces_and_native_help(self):
  lab,c=self.lab('fortigate')
  self.assertTrue(c.execute('configure terminal').startswith('%'))
  self.run_lines(c,'config system global\nset hostname BRANCH\nend\nconfig system interface\nedit port1\nset status down\nset alias "LAN users"\nnext\nend')
  self.assertEqual(lab.nodes['D1'].hostname,'BRANCH');self.assertTrue(lab.nodes['D1'].ports['gi0/1'].shutdown)
  self.assertIn('LAN users',c.execute('show system interface'));self.assertEqual(c.prompt,'BRANCH #')
  self.assertNotIn('switchport',c.help())
 def test_fortios_objects_policy_validation_and_reload(self):
  lab,c=self.lab('fortigate')
  self.run_lines(c,'config firewall address\nedit CLIENT\nset subnet 192.168.10.10 255.255.255.255\nnext\nend\nconfig firewall policy\nedit 10\nset srcintf any\nset dstintf any\nset srcaddr CLIENT\nset dstaddr all\nset action accept\nset schedule always\nset service HTTPS\nnext\nend')
  rule=lab.nodes['D1'].firewall_rules[0];self.assertEqual((rule['source'],rule['protocol'],rule['port']),('192.168.10.10/32','tcp',443))
  self.run_lines(c,'config firewall policy\nedit 20\nset action accept')
  before=lab.dumps();self.assertTrue(c.execute('next').startswith('%'));self.assertEqual(lab.dumps(),before)
  c.execute('abort');lab2=Lab.loads(lab.dumps());self.assertEqual(lab2.nodes['D1'].vendor,lab.nodes['D1'].vendor)
 def test_fortios_stale_edit_is_blocked(self):
  lab,c=self.lab('fortigate');self.run_lines(c,'config system interface\nedit port2\nset status down')
  Session(lab,'D1').execute('firewall default allow')
  self.assertIn('modifiée',c.execute('next'));self.assertFalse(lab.nodes['D1'].ports['gi0/2'].shutdown)
 def test_panos_candidate_commit_and_invalid_rollback(self):
  lab,c=self.lab('palo-alto')
  self.run_lines(c,'configure\nset deviceconfig system hostname PA_BRANCH\nset rulebase security rules WEB from any to any source 192.168.10.0/24 destination any application any service service-https action allow')
  self.assertEqual(lab.nodes['D1'].hostname,'');self.assertEqual(lab.nodes['D1'].firewall_rules,[])
  self.run_lines(c,'commit');self.assertEqual(lab.nodes['D1'].hostname,'PA_BRANCH');self.assertEqual(lab.nodes['D1'].firewall_rules[0]['port'],443)
  self.run_lines(c,'set rulebase security rules INCOMPLETE action deny')
  before=lab.dumps();self.assertTrue(c.execute('commit').startswith('%'));self.assertEqual(lab.dumps(),before)
 def test_panos_conflicts_and_unimplemented_features(self):
  lab,c=self.lab('palo-alto');self.run_lines(c,'configure\nset deviceconfig system hostname TEST')
  Session(lab,'D1').execute('firewall default allow');self.assertIn('modifiée',c.execute('commit'))
  self.assertTrue(c.execute('set rulebase security rules X application ssl').startswith('%'))
  self.assertTrue(c.execute('firewall default allow').startswith('%'))
 def test_routeros_has_native_names_and_rejects_ios(self):
  lab,c=self.lab('mikrotik-crs326')
  self.run_lines(c,'/system identity set name=ACCESS\n/interface set ether1 disabled=yes\n/interface set sfp-sfpplus1 comment="Trunk fiber"')
  self.assertEqual(lab.nodes['D1'].hostname,'ACCESS');self.assertTrue(lab.nodes['D1'].ports['gi0/1'].shutdown)
  self.assertIn('sfp-sfpplus1',c.execute('/interface print'));self.assertIn('Trunk fiber',c.execute('/interface print'))
  self.assertTrue(c.execute('switchport mode trunk').startswith('%'))
  self.assertTrue(c.execute('/interface set ether1 disabled=wrong').startswith('%'))
 def test_os_consoles_use_real_network_syntax(self):
  for profile,commands,invalid in [('windows-11','netsh interface ipv4 set address name="Ethernet" source=static address=10.0.0.2 mask=255.255.255.0 gateway=10.0.0.1','ip address 1.1.1.1/24'),('linux-ubuntu','sudo ip addr replace 10.0.0.2/24 dev eth0\nsudo ip route replace default via 10.0.0.1 dev eth0','listen tcp 80 HTTP')]:
   lab,c=self.lab(profile,'PC');self.run_lines(c,commands)
   self.assertEqual(lab.nodes['D1'].address,'10.0.0.2/24');self.assertEqual(lab.nodes['D1'].gateway,'10.0.0.1')
   self.assertTrue(c.execute(invalid).startswith('%'));self.assertTrue(c.execute('rm -rf /').startswith('%'))
 def test_gui_only_devices_do_not_invent_a_cisco_console(self):
  for profile,kind in [('hp-4002dn','PC'),('synology-ds224','PC'),('netgear-gs108e','Switch'),('juniper-srx','Switch')]:
   lab,c=self.lab(profile,kind);before=lab.dumps()
   self.assertIn('non implémentée',c.execute('configure terminal'));self.assertEqual(lab.dumps(),before)

 def test_panos_hostname_commit_preserves_rules_from_other_editors(self):
  lab,c=self.lab('palo-alto');Session(lab,'D1').execute('firewall rule 10 allow udp any any 53')
  before=lab.nodes['D1'].firewall_rules.copy();self.run_lines(c,'configure\nset deviceconfig system hostname PA\ncommit')
  self.assertEqual(lab.nodes['D1'].firewall_rules,before)
  self.run_lines(c,'set rulebase security rules HTTPS from any to any source any destination any application any service service-https action allow\ncommit')
  self.assertTrue(any(r['port']==53 for r in lab.nodes['D1'].firewall_rules))
  self.run_lines(c,'delete rulebase security rules HTTPS\ncommit')
  self.assertEqual(lab.nodes['D1'].firewall_rules,before)

 def test_fortios_native_policy_changes_the_shared_path(self):
  from network_labs.__main__ import App
  lab=App.service_demo();c=console_session(lab,'FW1')
  self.assertFalse(lab.probe('PC1','camera.lan','tcp',554)[0])
  self.run_lines(c,'config firewall policy\nedit 30\nset srcintf any\nset dstintf any\nset srcaddr all\nset dstaddr all\nset action accept\nset schedule always\nset service ALL\nnext\nend')
  self.assertTrue(lab.probe('PC1','camera.lan','tcp',554)[0])

 def test_fortios_dns_service_matches_both_tcp_and_udp(self):
  from network_labs.__main__ import App
  lab=App.service_demo();lab.nodes['FW1'].firewall_rules=[];c=console_session(lab,'FW1')
  self.run_lines(c,'config firewall policy\nedit 1\nset srcintf any\nset dstintf any\nset srcaddr all\nset dstaddr all\nset action accept\nset schedule always\nset service DNS\nnext\nend')
  for protocol in ('tcp','udp'):self.assertTrue(lab.probe('PC1','192.168.10.2',protocol,53)[0])
  self.assertEqual(Lab.loads(lab.dumps()).nodes['FW1'].firewall_rules[0]['protocol'],'tcpudp')

 def test_panos_exit_keeps_candidate_until_commit(self):
  lab,c=self.lab('palo-alto');self.run_lines(c,'configure\nset deviceconfig system hostname CANDIDATE\nexit\nconfigure')
  self.assertIn('CANDIDATE',c.execute('show'));self.assertEqual(lab.nodes['D1'].hostname,'')
  self.run_lines(c,'commit');self.assertEqual(lab.nodes['D1'].hostname,'CANDIDATE')
