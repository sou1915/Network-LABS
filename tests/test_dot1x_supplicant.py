"""Owned peer schema, sealed private handoff, preflight and cleanup boundaries."""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from network_labs.appliances.examples import dot1x_lab
from network_labs.appliances.spec import validate
from network_labs.appliances.runtime import Manager,RuntimeFailure
from network_labs.appliances.lan import configure
from network_labs.appliances import dot1x_supplicant as peer


class ManagedPeerTests(unittest.TestCase):
    def spec(self,root='/rootfs',asset='/private/peer-password'):
        spec=dot1x_lab(root,'managed-peer-test-secret','a'*64,asset)
        spec['nodes'][0]['dot1x_supplicant']={'interface':'eth0','username':'learner','password_file':asset,'password_sha256':'b'*64}
        return validate(spec)

    def test_explicit_pair_identity_and_strict_private_asset_schema(self):
        spec=self.spec();self.assertEqual(validate(spec),spec)
        explicit_none=copy.deepcopy(spec)
        for index in (0,2):explicit_none['nodes'][index]['dot1x']=None
        self.assertEqual(validate(explicit_none),explicit_none)
        for fault in ({'interface':'eth1'},{'username':'unknown'},{'username':'bad\nuser'},{'password_file':'relative'},{'password_file':'/a/../b'},{'password_sha256':'plain'},{'password':'forbidden'}):
            bad=copy.deepcopy(spec);bad['nodes'][0]['dot1x_supplicant'].update(fault)
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(bad)
        bad=copy.deepcopy(spec);bad['nodes'][2]['dot1x_supplicant']=bad['nodes'][0].pop('dot1x_supplicant')
        with self.assertRaises(ValueError):validate(bad)
        bad=copy.deepcopy(spec);bad['nodes'][1].pop('dot1x')
        with self.assertRaises(ValueError):validate(bad)

    def test_changed_peer_asset_refuses_before_runtime_allocation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);asset=root/'password';asset.write_text('private-peer-test-password');asset.chmod(0o600)
            spec=self.spec(str(root),str(asset));manager=Manager(spec['name']);manager.directory=root/'absent'
            report={'host':{'linux':True},'runtimes':[{'id':'oci','prerequisites_detected':True}]}
            with patch('network_labs.appliances.runtime.capabilities',return_value=report),patch('network_labs.appliances.dot1x_supplicant.shutil.which',return_value='/trusted/wpa_supplicant'),patch('network_labs.appliances.runtime.run') as run:
                with self.assertRaises(ValueError):manager.start(spec)
                run.assert_not_called();self.assertFalse(manager.directory.exists())

    def test_sealed_memfd_is_private_and_secret_is_absent_from_argv_state_and_runtime_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);asset=root/'password';password='private-peer-test-password';asset.write_text(password);asset.chmod(0o600)
            spec=self.spec(str(root),str(asset));spec['nodes'][0]['dot1x_supplicant']['password_sha256']=hashlib.sha256(password.encode()).hexdigest()
            manager=Mock();manager.directory=root/'runtime';manager.directory.mkdir();manager.state={'spec':spec}
            manager.ns.return_value.stdout=json.dumps([{'ifindex':9}]);process=Mock(pid=123);process.poll.return_value=None
            def spawn(args,**options):
                fd=options['pass_fds'][0];self.assertEqual(os.fstat(fd).st_mode&0o777,0o600)
                self.assertIn('-D',args);self.assertIn('wired',args);self.assertNotIn(password,' '.join(args))
                with os.fdopen(os.dup(fd),'rb') as stream:text=stream.read().decode()
                self.assertIn('password='+password.encode().hex(),text);self.assertNotIn(password,text)
                self.assertEqual(fcntl.fcntl(fd,1034)&15,15)  # Linux F_GET_SEALS
                with self.assertRaises(OSError):os.write(fd,b'change')
                self.assertIs(options['stdout'],__import__('subprocess').DEVNULL)
                return process
            with patch.object(peer,'namespace_identity',return_value=[1,2]),patch.object(peer,'process_identity',return_value='pinned'),patch.object(peer,'observe',return_value={'configuration_verified':True}),patch.object(peer.shutil,'which',return_value='/trusted/wpa_supplicant'),patch.object(peer.subprocess,'Popen',side_effect=spawn):
                peer.start(manager)
            try:
                record=manager.state['dot1x_supplicants']['PC1'];self.assertEqual(record['namespace'],[1,2]);self.assertEqual(record['ifindex'],9)
                self.assertNotIn(password,json.dumps(manager.state));self.assertEqual(list((manager.directory/'dot1x-peer').iterdir()),[])
            finally:peer.PROCESSES.pop(123,None)

    def test_peer_edits_require_recreation(self):
        old=self.spec()['nodes'][0];new=copy.deepcopy(old);new['dot1x_supplicant']['password_sha256']='c'*64;manager=Mock()
        with self.assertRaises(RuntimeFailure):configure(manager,0,new,old)
        manager.ns.assert_not_called()

    def test_reused_pid_is_not_signalled_and_dead_owned_child_is_reaped(self):
        manager=Mock();manager.state={'dot1x_supplicants':{'PC1':{'pid':123,'starttime':'old'}}};child=Mock();peer.PROCESSES[123]=child
        with patch.object(peer,'alive',return_value=False),patch.object(peer.os,'killpg') as kill:
            peer.stop(manager)
        kill.assert_not_called();child.wait.assert_called_once();self.assertFalse(manager.state['dot1x_supplicants'])

    def test_foreign_group_or_unconfirmed_death_retains_record(self):
        for group in (122,123):
            manager=Mock();manager.state={'dot1x_supplicants':{'PC1':{'pid':123,'starttime':'old'}}}
            with patch.object(peer,'alive',return_value=True),patch.object(peer.os,'getpgid',return_value=group),patch.object(peer.os,'killpg') as kill,patch.object(peer.time,'monotonic',side_effect=[0,3,3,6]):
                with self.assertRaises(RuntimeFailure):peer.stop(manager)
            self.assertIn('PC1',manager.state['dot1x_supplicants'])
            self.assertEqual(kill.call_count,0 if group==122 else 2)

    def test_dead_service_is_unverified_and_is_not_automatically_restarted(self):
        manager=Mock();manager.read.return_value={'dot1x_supplicants':{'PC1':{'pid':123,'starttime':'old'}}}
        with patch.object(peer,'alive',return_value=False),patch.object(peer.subprocess,'Popen') as spawn:
            result=peer.observe(manager,0,self.spec()['nodes'][0])
        self.assertFalse(result['running']);self.assertFalse(result['configuration_verified']);spawn.assert_not_called()
