"""Persistent HTTPS policy, protected offline identities and drift boundaries."""
import copy
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from network_labs.appliances.https_server import BASE,CA,CERT,KEY,BINARY,files,validate_node,identity_assets,install,policy,preflight,observe
from network_labs.appliances.spec import example,validate
from network_labs.appliances.service_adapters import adapters
from network_labs.appliances.runtime import RuntimeFailure,oci_config
from https_test_identity import identities


def spec():
    value=example('/rootfs');value['nodes'][0]['https_server']={'interface':'eth0','ca_sha256':'a'*64,'certificate_sha256':'b'*64}
    return validate(value)


class HTTPSServerTests(unittest.TestCase):
    def test_scoped_policy_rendering_and_immutable_edits(self):
        value=spec();node=value['nodes'][0];self.assertEqual(validate(copy.deepcopy(value)),value)
        text=files(node)['https.conf']
        for token in ('worker_processes 1','user https https','worker_connections 16','192.0.2.10:443 ssl','TLSv1.2 TLSv1.3',CERT,KEY,'return 404','return 405'):
            self.assertIn(token,text)
        self.assertNotIn('proxy_pass',text);self.assertNotIn('listen 80',text);self.assertNotIn('include ',text)
        for edit in (lambda n:n.update(role='router'),lambda n:n['interfaces'].update(eth1=''),lambda n:n.update(startup=[['/bin/sleep','1']]),lambda n:n.update(shutdown=['eth0']),lambda n:n['https_server'].update(ca_sha256='bad')):
            value=spec();edit(value['nodes'][0])
            with self.subTest(edit=edit),self.assertRaises(ValueError):validate(value)
        old=spec()['nodes'][0];new=copy.deepcopy(old);new['https_server']['certificate_sha256']='c'*64
        with self.assertRaisesRegex(ValueError,'recreation'):adapters(new,old)

    @unittest.skipUnless(shutil.which('openssl'),'OpenSSL fixture generation required')
    def test_private_material_mode_matching_and_pinned_preflight(self):
        with tempfile.TemporaryDirectory() as folder:
            certs=identities(folder);root=Path(folder)/'image';root.mkdir()
            values=identity_assets(certs['ca'],certs['valid_cert'],certs['valid_key']);install(root,values)
            self.assertEqual((root/KEY.lstrip('/')).stat().st_mode & 0o777,0o600)
            binary=root/BINARY.lstrip('/');binary.parent.mkdir(parents=True,exist_ok=True);binary.touch()
            value=example(root);node=value['nodes'][0];node['https_server']=policy(root);value=validate(value)
            self.assertEqual(len(preflight(node)),64)
            self.assertIn(BASE,oci_config(value,value['nodes'][1],1,root)['linux']['maskedPaths'])
            self.assertNotIn(BASE,oci_config(value,node,0,root)['linux']['maskedPaths'])
            (root/KEY.lstrip('/')).chmod(0o644)
            with self.assertRaises(RuntimeFailure):preflight(node)
            (root/KEY.lstrip('/')).chmod(0o600);(root/CA.lstrip('/')).write_text('altered')
            with self.assertRaises(RuntimeFailure):preflight(node)
            with self.assertRaises(ssl.SSLError):identity_assets(certs['ca'],certs['valid_cert'],certs['wrong_key'])

    def test_missing_changed_or_publicly_readable_key_never_verifies(self):
        node=spec()['nodes'][0]
        for key_hash,mode in (('c'*64,'600:0:0\n'),('d'*64,'600:0:0\n'),('c'*64,'644:0:0\n'),('c'*64,'600:65531:65531\n')):
            def crun(*args,**options):
                if 'head' in args:text=files(node)['https.conf']
                elif 'stat' in args:text=mode
                else:text='\n'.join(h+'  '+p for h,p in (('a'*64,CA),('b'*64,CERT),(key_hash,KEY)))+'\n'
                return subprocess.CompletedProcess(args,0,text,'')
            manager=SimpleNamespace(crun=crun,read=lambda:{'https_key_hashes':{'PC1':'c'*64}})
            result=observe(manager,node);self.assertEqual(result['configuration_verified'],key_hash=='c'*64 and mode=='600:0:0\n')
            self.assertNotIn('c'*64,json.dumps(result));self.assertNotIn('PRIVATE KEY',json.dumps(result))
