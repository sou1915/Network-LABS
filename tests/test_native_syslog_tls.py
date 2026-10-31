"""Explicit mutual TLS policy and conservative identity-asset observations."""
import copy
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from network_labs.appliances.examples import syslog_tcp_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.syslog_server import files as collector_files
from network_labs.appliances.syslog_forward import files as sender_files
from network_labs.appliances.syslog_tls import CA,CERT,KEY,observe,validate_policy


def tls_spec():
    spec=syslog_tcp_lab('/rootfs',forward=True)
    policy={'peer':'sender.lab','ca_sha256':'a'*64,'certificate_sha256':'b'*64}
    spec['nodes'][0]['syslog_server'].update(transport='tls',tls=policy)
    spec['nodes'][2]['management'].update(syslog_transport='tls',syslog_tls={**policy,'peer':'collector.lab'})
    return validate(spec)


class SyslogTLSTests(unittest.TestCase):
    def test_both_daemons_require_mutual_names_encryption_and_explicit_public_files(self):
        spec=tls_spec(); self.assertEqual(validate(copy.deepcopy(spec)),spec)
        for text in (collector_files(spec['nodes'][0])['syslog-server.conf'],sender_files(spec['nodes'][2])['syslog-forward.conf']):
            for token in (CA,CERT,KEY,'6514','x509/name','gtls','TLS1.2','TLS1.3','PrioritizeSAN="on"','CheckExtendedKeyPurpose="on"'):
                self.assertIn(token,text)
            self.assertNotIn('StreamDriver="ptcp"',text); self.assertNotIn('port="514"',text)
        self.assertIn('StreamDriverMode="1"',sender_files(spec['nodes'][2])['syslog-forward.conf'])
        self.assertIn('StreamDriver.Mode="1"',collector_files(spec['nodes'][0])['syslog-server.conf'])

    def test_incomplete_ambiguous_or_injected_trust_is_rejected(self):
        valid={'peer':'collector.lab','ca_sha256':'a'*64,'certificate_sha256':'b'*64}
        for patch in ({'peer':'*.lab'},{'peer':'collector.lab"'},{'peer':'COLLECTOR.lab'},{'ca_sha256':'bad'},{'private_key':'secret'}):
            with self.subTest(patch=patch),self.assertRaises(ValueError): validate_policy({**valid,**patch})
        for section in ('syslog_server','management'):
            spec=tls_spec(); config=spec['nodes'][0 if section=='syslog_server' else 2][section]
            config.pop('tls' if section=='syslog_server' else 'syslog_tls')
            with self.assertRaises(ValueError): validate(spec)
        spec=tls_spec();spec['nodes'][0]['syslog_server']['transport']='tcp'
        with self.assertRaises(ValueError): validate(spec)

    def test_missing_or_changed_key_and_key_permissions_never_verify(self):
        node=tls_spec()['nodes'][2]
        for key_hash,mode,record in (('c'*64,'600\n',True),('d'*64,'600\n',True),('c'*64,'644\n',True),('c'*64,'600\n',False)):
            def crun(*args,**options):
                text=mode if 'stat' in args else '\n'.join(h+'  '+p for h,p in (('a'*64,CA),('b'*64,CERT),(key_hash,KEY)))+'\n'
                return subprocess.CompletedProcess(args,0,text,'')
            manager=SimpleNamespace(crun=crun,read=lambda:{'syslog_tls_key_hashes':{'PC2':'c'*64} if record else {}})
            with self.subTest(key_hash=key_hash,mode=mode,record=record): self.assertEqual(observe(manager,node)['configuration_verified'],key_hash=='c'*64 and mode=='600\n' and record)

    def test_non_tls_nodes_mask_shared_offline_identity_directory(self):
        from network_labs.appliances.runtime import oci_config
        from network_labs.appliances.syslog_tls import BASE
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/BASE.lstrip('/')).mkdir(parents=True)
            spec=syslog_tcp_lab(root);node=spec['nodes'][1]
            self.assertIn(BASE,oci_config(spec,node,1,root)['linux']['maskedPaths'])
            spec=tls_spec();spec['nodes'][0]['rootfs']=str(root)
            self.assertNotIn(BASE,oci_config(spec,spec['nodes'][0],0,root)['linux']['maskedPaths'])
