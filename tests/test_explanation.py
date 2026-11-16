import unittest
from network_labs.__main__ import App
from network_labs.cli import Session
from network_labs.device_identity import identity

class ExplanationTests(unittest.TestCase):
 def test_dns_transport_forward_return_and_firewall_evidence(self):
  lab=App.service_demo();ok,trace=lab.probe('PC1','nas.lan','tcp',445);self.assertTrue(ok)
  report=lab.last_explanation
  self.assertIn('TCP/445',report['title']);self.assertTrue(report['ok'])
  self.assertTrue(any(x['title']=='Résolution du nom' for x in report['steps']))
  for phase in ('Aller','Retour','Filtrage'):self.assertTrue(any(x['phase']==phase for x in report['steps']))
  self.assertEqual(sum(x['phase'] in ('Aller','Retour') for x in report['steps']),sum(map(len,lab.last_hops)))
  self.assertEqual(report['checks'],[])
 def test_blocked_rule_is_explained_without_claiming_success(self):
  lab=App.service_demo();ok,_=lab.probe('PC1','camera.lan','tcp',554);self.assertFalse(ok)
  report=lab.last_explanation;self.assertFalse(report['ok']);self.assertIn('40',str(report['steps']))
  self.assertIn('firewall',str(report['checks']).lower());self.assertNotIn('Résultat : accessible',str(report))
 def test_failed_dns_does_not_reuse_previous_paths(self):
  lab=App.service_demo();lab.probe('PC1','nas.lan','tcp',445)
  ok,_=lab.probe('PC1','missing.lan','tcp',443);self.assertFalse(ok)
  self.assertFalse(lab.last_hops);self.assertIn('TCP/443',lab.last_explanation['title'])
  self.assertFalse(any(x['phase'] in ('Aller','Retour') for x in lab.last_explanation['steps']))
 def test_service_closed_is_distinguished_from_network_failure(self):
  lab=App.service_demo();Session(lab,'NAS1').execute('unlisten tcp 445');ok,_=lab.probe('PC1','nas.lan','tcp',445)
  self.assertFalse(ok);self.assertIn('service',str(lab.last_explanation['checks']).lower())
  self.assertTrue(lab.last_hops)
 def test_families_have_separate_shells_and_truthful_console_metadata(self):
  profiles=['windows-11','linux-ubuntu','fortigate','palo-alto','pfsense','synology-ds224','qnap-ts264','hp-4002dn','brother-hl5200','axis-p3265','yealink-t54w','unifi-lite8','mikrotik-crs326']
  self.assertEqual(len(set(identity(x)['skin'] for x in profiles)),len(profiles))
  self.assertFalse(identity('hp-4002dn')['native']);self.assertEqual(identity('fortigate')['console'],'fortios')
