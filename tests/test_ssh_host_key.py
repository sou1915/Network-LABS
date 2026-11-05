"""Explicit offline SSH identity policy, snapshot privacy and runtime conformity."""
import copy
import hashlib
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from network_labs.appliances.examples import management_lab
from network_labs.appliances.management import commands
from network_labs.appliances.runtime import RuntimeFailure
from network_labs.appliances.ssh_host_key import KEY,policy,read_identity,preflight,observe
from network_labs.appliances.spec import validate
from test_native_management import KEY as PUBLIC


class SSHHostKeyTests(unittest.TestCase):
    def profile(self):
        with patch('network_labs.appliances.ssh_host_key.read_identity',return_value=(b'fixture',PUBLIC)):
            return management_lab('/rootfs',PUBLIC,ssh_actions=['identity'],ssh_host_key_file='/offline/key')

    def test_explicit_host_identity_leaves_default_ephemeral_and_refuses_compositions(self):
        spec=self.profile();node=spec['nodes'][2]
        self.assertEqual(validate(copy.deepcopy(spec)),spec)
        self.assertEqual(node['management']['ssh_host_key'],{'file':'/offline/key','public_key':PUBLIC})
        self.assertEqual(node['management']['syslog_remote'],'')
        argv=commands(node)['ssh'];self.assertNotIn('-R',argv);self.assertEqual(argv[argv.index('-r')+1],KEY)
        self.assertIn('-R',commands(management_lab('/rootfs',PUBLIC)['nodes'][2])['ssh'])
        for fault in ('relative','no-actions','syslog','telnet','bad-public','radius'):
            candidate=copy.deepcopy(spec);config=candidate['nodes'][2]['management']
            if fault=='relative':config['ssh_host_key']['file']='relative/key'
            if fault=='no-actions':config.pop('ssh_actions')
            if fault=='syslog':config['syslog_remote']='192.0.2.10'
            if fault=='telnet':config['telnet_radius']=True
            if fault=='bad-public':config['ssh_host_key']['public_key']='ssh-rsa invalid'
            if fault=='radius':config['ssh_radius']=True
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(candidate)

    def test_checked_snapshot_is_private_and_source_modes_symlinks_and_size_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'key';path.write_bytes(b'private fixture');path.chmod(0o600)
            def derive(argv,**options):
                snapshot=Path(argv[-1]);self.assertEqual(snapshot.read_bytes(),b'private fixture')
                self.assertEqual(snapshot.stat().st_mode&0o777,0o600)
                self.assertNotIn('private fixture',str(argv))
                return subprocess.CompletedProcess(argv,0,'Public key portion is:\n'+PUBLIC+' fixture\n','')
            with patch('network_labs.appliances.ssh_host_key.subprocess.run',side_effect=derive):
                self.assertEqual(policy(path),{'file':str(path),'public_key':PUBLIC})
            path.chmod(0o644)
            with self.assertRaises(ValueError):read_identity(path)
            path.chmod(0o600);link=Path(folder)/'link';link.symlink_to(path)
            with self.assertRaises(OSError):read_identity(link)
            path.write_bytes(b'x'*4097)
            with self.assertRaises(ValueError):read_identity(path)

    def test_preflight_public_mismatch_never_succeeds_and_runtime_mode_hash_are_checked(self):
        node=self.profile()['nodes'][2]
        with patch('network_labs.appliances.ssh_host_key.read_identity',return_value=(b'private fixture','different')):
            with self.assertRaises(RuntimeFailure):preflight(node)
        digest=hashlib.sha256(b'private fixture').hexdigest()
        for mode,actual,valid in (('regular file:600:0:0\n',digest,True),('regular file:644:0:0\n',digest,False),
                                  ('symbolic link:777:0:0\n',digest,False),('regular file:600:0:0\n','a'*64,False)):
            def crun(*args,**options):
                return subprocess.CompletedProcess(args,0,mode if 'stat' in args else actual+'  '+KEY+'\n','')
            manager=SimpleNamespace(crun=crun,read=lambda:{'ssh_host_key_hashes':{'R1':digest}})
            with self.subTest(mode=mode,actual=actual):self.assertEqual(observe(manager,node)['configuration_verified'],valid)
