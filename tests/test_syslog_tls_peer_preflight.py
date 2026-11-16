"""Opted-in mutual certificate checks retain default live-failure lab support."""
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from network_labs.appliances.__main__ import main
from network_labs.appliances.examples import syslog_tls_lab
from network_labs.appliances.runtime import RuntimeFailure
from network_labs.appliances.spec import validate
from network_labs.appliances.syslog_tls import assets,install,preflight_pair,paired_nodes
from syslog_test_identity import lifecycle_certificates
from test_native_syslog_tls import tls_spec
from test_native_syslog_tls_integration import certificates


class SyslogTLSPeerPolicyTests(unittest.TestCase):
    def test_pair_policy_rejects_half_flags_types_and_mismatched_topology(self):
        original=tls_spec()
        self.assertIsNone(paired_nodes(original));preflight_pair(original)  # No offline file access by default.
        for fault in ('one-sided','integer','string','remote','sender'):
            spec=copy.deepcopy(original)
            for index,section,field in ((0,'syslog_server','tls'),(2,'management','syslog_tls')):
                spec['nodes'][index][section][field]['verify_peer_on_start']=True
            if fault=='one-sided':del spec['nodes'][2]['management']['syslog_tls']['verify_peer_on_start']
            if fault=='integer':spec['nodes'][0]['syslog_server']['tls']['verify_peer_on_start']=1
            if fault=='string':spec['nodes'][2]['management']['syslog_tls']['verify_peer_on_start']='true'
            if fault=='remote':spec['nodes'][2]['management']['syslog_remote']='192.0.2.99'
            if fault=='sender':spec['nodes'][0]['syslog_server']['senders']=['192.0.2.99']
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)

    @unittest.skipUnless(shutil.which('openssl'),'OpenSSL fixture generation required')
    def test_real_role_time_trust_names_and_distinct_issuer_pair_without_sockets(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'fixtures').mkdir();ca,wrong,leaves=lifecycle_certificates(root/'fixtures')
            def spec(server='collector.lab',client='sender.lab',server_ca=ca,client_ca=ca,server_name='collector.lab',client_name='sender.lab',opt=True):
                images=[]
                for role,identity,trust in (('server',server,server_ca),('client',client,client_ca)):
                    image=root/(role+'-'+str(len(list(root.iterdir()))));image.mkdir()
                    install(image,assets(trust,*leaves[identity]));images.append(image)
                return syslog_tls_lab(*images,server_name,client_name,verify_peer_on_start=opt)
            with patch('socket.socket',side_effect=AssertionError('Offline check must not open sockets')):
                preflight_pair(spec());preflight_pair(spec('renewed-collector.lab','renewed-sender.lab'))
                for role in ('collector.lab','sender.lab'):
                    for version in ('expired','future'):
                        selection={'server':version+'-'+role} if role=='collector.lab' else {'client':version+'-'+role}
                        with self.subTest(identity=selection),self.assertRaises(RuntimeFailure):preflight_pair(spec(**selection))
                for change in ({'client_ca':wrong},{'server_ca':wrong},{'server_name':'wrong.lab'},
                               {'client_name':'wrong.lab'},{'client':'intruder.lab'},
                               {'client':'collector.lab'},{'server':'sender.lab'}):
                    with self.subTest(change=change),self.assertRaises(RuntimeFailure):preflight_pair(spec(**change))
                # Each CA is a peer trust bundle, not necessarily the issuer
                # of the local identity. Distinct issuing CAs remain valid.
                other=root/'other';other.mkdir();other_ca,_,other_leaves=certificates(other)
                leaves['second-sender']=other_leaves['sender.lab']
                preflight_pair(spec(client='second-sender',server_ca=other_ca,client_ca=ca))
            value=spec();server=value['nodes'][0]['rootfs'];client=value['nodes'][2]['rootfs']
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['example','--syslog-tls','--syslog-tls-preflight','--rootfs',server,
                    '--syslog-client-rootfs',client,'--syslog-server-name','collector.lab','--syslog-client-name','sender.lab']),0)
            self.assertEqual(json.loads(output.getvalue()),value)
