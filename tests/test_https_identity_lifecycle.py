"""Real offline HTTPS chain/time/purpose validation without network traffic."""
from pathlib import Path
import shutil
import ssl
import tempfile
import unittest
from unittest.mock import patch
from https_test_identity import lifecycle_identities
from network_labs.appliances.https_server import identity_assets,install,policy,preflight,BINARY,CERT
from network_labs.appliances.runtime import RuntimeFailure


@unittest.skipUnless(shutil.which('openssl'),'OpenSSL fixture generation required')
class HTTPSIdentityLifecycleTests(unittest.TestCase):
    def test_offline_trust_time_purpose_and_leaf_rekey(self):
        with tempfile.TemporaryDirectory() as folder:
            certs=lifecycle_identities(folder)
            with patch('socket.socket',side_effect=AssertionError('Offline validation must not open sockets')):
                first=identity_assets(certs['ca'],certs['valid_cert'],certs['valid_key'])
                renewed=identity_assets(certs['ca'],certs['renewed_cert'],certs['renewed_key'])
                self.assertNotEqual(first[CERT],renewed[CERT])
                for name,code in (('expired',10),('future',9),('client-only',26)):
                    with self.subTest(identity=name),self.assertRaises(ssl.SSLCertVerificationError) as caught:
                        identity_assets(certs['ca'],certs[name+'_cert'],certs[name+'_key'])
                    self.assertEqual(caught.exception.verify_code,code)
                with self.assertRaises(ssl.SSLCertVerificationError):
                    identity_assets(certs['wrong_ca'],certs['valid_cert'],certs['valid_key'])

    def test_changed_or_expired_pinned_rootfs_refuses_preflight(self):
        with tempfile.TemporaryDirectory() as folder:
            certs=lifecycle_identities(folder);root=Path(folder)/'rootfs';root.mkdir()
            install(root,identity_assets(certs['ca'],certs['valid_cert'],certs['valid_key']))
            binary=root/BINARY.lstrip('/');binary.parent.mkdir(parents=True,exist_ok=True);binary.touch()
            node={'name':'PC1','rootfs':str(root),'https_server':policy(root)}
            self.assertEqual(len(preflight(node)),64)
            (root/CERT.lstrip('/')).write_bytes(certs['expired_cert'].read_bytes())
            node['https_server']=policy(root)  # Even an explicitly pinned expired identity fails.
            with self.assertRaisesRegex(RuntimeFailure,'expired'):preflight(node)
