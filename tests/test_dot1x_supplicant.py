"""Owned peer schema, sealed private handoff, preflight and cleanup boundaries."""
import copy
from contextlib import contextmanager,nullcontext
import fcntl
import hashlib
import json
import os
import socket
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

    @contextmanager
    def recovery_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);asset=root/'password';asset.write_text('private-recovery-password');asset.chmod(0o600)
            spec=self.spec(str(root),str(asset));spec['nodes'][0]['dot1x_supplicant']['password_sha256']=hashlib.sha256(asset.read_bytes()).hexdigest()
            manager=Mock();manager.directory=root/'runtime';manager.directory.mkdir()
            directory=peer.control(manager);directory.mkdir(mode=0o700)
            with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as server:server.bind(str(directory/'eth0'))
            record={'pid':123,'starttime':'123','namespace':[1,2],'ifindex':9,
                'control_directory':peer.directory_identity(directory),'control_socket':peer.socket_identity(directory/'eth0'),
                'config_sha256':hashlib.sha256(peer.config_text(spec['nodes'][0],directory).encode()).hexdigest()}
            state={'phase':'running','spec':spec,'dot1x_supplicants':{'PC1':record}}
            def read():manager.state=state;return state
            manager.read.side_effect=read;manager.state=state;manager.locked.side_effect=lambda:nullcontext()
            manager.ns.return_value.stdout=json.dumps([{'ifindex':9,'address':spec['nodes'][0]['interface_macs']['eth0'],'flags':['UP']}])
            with patch.object(peer,'alive',return_value=False) as alive,patch.object(peer,'namespace_identity',return_value=[1,2]) as ns,patch.object(peer.shutil,'which',return_value='/trusted/wpa_supplicant'),patch('network_labs.appliances.dot1x.observe',return_value={'configuration_verified':True,'admitted':False}) as gate,patch.object(peer,'ping',return_value=False) as ping:
                yield manager,state,directory,record,alive,ns,gate,ping

    def test_recovery_restarts_only_recorded_dead_peer_with_closed_gate_without_signals(self):
        with self.recovery_fixture() as (manager,state,directory,record,*_):
            def start(manager,*,name):
                self.assertEqual(name,'PC1');self.assertEqual(state['phase'],'recovering-peer')
                self.assertFalse(directory.exists());self.assertFalse(state['dot1x_supplicants'])
                directory.mkdir(mode=0o700);state['dot1x_supplicants']['PC1']={**record,'pid':124}
            with patch.object(peer,'start',side_effect=start),patch.object(peer.os,'killpg') as signal:
                result=peer.recover(manager,'PC1')
            signal.assert_not_called();self.assertEqual(result['status'],'passed')
            self.assertTrue(result['port_closed']);self.assertTrue(result['authentication_required'])
            self.assertEqual(state['phase'],'running');self.assertEqual(state['dot1x_supplicants']['PC1']['pid'],124)
            self.assertEqual(state['spec']['nodes'][0]['dot1x_supplicant']['password_sha256'],hashlib.sha256(b'private-recovery-password').hexdigest())

    def test_recovery_refuses_live_peer_active_authentication_or_incomplete_runtime_before_mutations(self):
        for fault in ('live','auth','phase','pending','legacy'):
            with self.subTest(fault=fault),self.recovery_fixture() as (manager,state,directory,record,alive,*_):
                if fault=='live':alive.return_value=True
                elif fault=='auth':state['dot1x_workers']={'SW1':{'pid':321}}
                elif fault=='phase':state['phase']='recovering-peer'
                elif fault=='pending':state['pending_spec']={}
                else:record.pop('control_socket')
                with patch.object(peer,'start') as start,self.assertRaises(RuntimeFailure):peer.recover(manager,'PC1')
                start.assert_not_called();self.assertTrue((directory/'eth0').exists());self.assertIn('PC1',state['dot1x_supplicants'])

    def test_recovery_refuses_open_or_unverified_gate_namespace_or_interface_drift(self):
        for fault in ('open','gate','namespace','interface'):
            with self.subTest(fault=fault),self.recovery_fixture() as (manager,state,directory,record,_,ns,gate,ping):
                if fault=='open':gate.return_value={'configuration_verified':True,'admitted':True}
                elif fault=='gate':gate.return_value={'configuration_verified':False,'admitted':False}
                elif fault=='namespace':ns.return_value=[1,3]
                else:manager.ns.return_value.stdout=json.dumps([{'ifindex':10,'address':'00:00:00:00:00:00','flags':[]}])
                with patch.object(peer,'start') as start,self.assertRaises(RuntimeFailure):peer.recover(manager,'PC1')
                start.assert_not_called();self.assertEqual(state['phase'],'running');self.assertTrue((directory/'eth0').exists())

    def test_recovery_rejects_changed_credentials_without_unlinking_old_control_or_losing_record(self):
        with self.recovery_fixture() as (manager,state,directory,record,*_):
            Path(state['spec']['nodes'][0]['dot1x_supplicant']['password_file']).write_text('changed-recovery-password')
            with patch.object(peer,'start') as start,self.assertRaises(ValueError):peer.recover(manager,'PC1')
            start.assert_not_called();self.assertEqual(state['phase'],'running');self.assertIs(state['dot1x_supplicants']['PC1'],record)
            self.assertEqual(peer.socket_identity(directory/'eth0'),record['control_socket'])

    def test_recovery_refuses_foreign_control_files_modes_or_unrecorded_live_socket(self):
        for fault in ('foreign-file','socket-replaced','directory-mode','live-socket'):
            with self.subTest(fault=fault),self.recovery_fixture() as (manager,state,directory,record,alive,ns,gate,ping):
                if fault=='foreign-file':(directory/'do-not-delete').write_text('foreign')
                elif fault=='socket-replaced':(directory/'eth0').unlink();(directory/'eth0').write_text('foreign')
                elif fault=='directory-mode':directory.chmod(0o755)
                else:ping.return_value=True
                with patch.object(peer,'start') as start,self.assertRaises(RuntimeFailure):peer.recover(manager,'PC1')
                start.assert_not_called();self.assertEqual(state['phase'],'running')
                self.assertTrue((directory/'eth0').exists());self.assertIs(state['dot1x_supplicants']['PC1'],record)

    def test_failed_recovery_retains_phase_and_existing_auth_and_save_guards_refuse(self):
        with self.recovery_fixture() as (manager,state,directory,record,*_):
            with patch.object(peer,'start',side_effect=RuntimeFailure('readiness unconfirmed')),self.assertRaises(RuntimeFailure):peer.recover(manager,'PC1')
            self.assertEqual(state['phase'],'recovering-peer')
            from network_labs.appliances.dot1x import authenticate
            with patch('subprocess.Popen') as spawn,self.assertRaises(RuntimeFailure):authenticate(manager,'SW1')
            spawn.assert_not_called()
            real=Manager(state['spec']['name']);real.directory=manager.directory
            (real.directory/'state.json').write_text(json.dumps(state))
            with self.assertRaises(RuntimeFailure):real.write_startup()

    def test_recovery_allows_absent_old_socket_directory_after_confirmed_peer_exit(self):
        with self.recovery_fixture() as (manager,state,directory,record,*_):
            (directory/'eth0').unlink();directory.rmdir()
            with patch.object(peer,'start') as start:result=peer.recover(manager,'PC1')
            start.assert_called_once_with(manager,name='PC1');self.assertEqual(result['status'],'passed')

    def test_recovery_does_not_wait_for_or_remove_a_live_cached_child_reusing_old_pid(self):
        with self.recovery_fixture() as (manager,state,directory,record,*_):
            unrelated=Mock();unrelated.poll.return_value=None
            with patch.dict(peer.PROCESSES,{record['pid']:unrelated},clear=True),patch.object(peer,'start'):
                result=peer.recover(manager,'PC1')
                self.assertIs(peer.PROCESSES[record['pid']],unrelated)
            self.assertEqual(result['status'],'passed');unrelated.wait.assert_not_called()

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
            with patch.object(peer,'socket_identity',return_value=[3,4]),patch.object(peer,'namespace_identity',return_value=[1,2]),patch.object(peer,'process_identity',return_value='pinned'),patch.object(peer,'observe',return_value={'configuration_verified':True}),patch.object(peer.shutil,'which',return_value='/trusted/wpa_supplicant'),patch.object(peer.subprocess,'Popen',side_effect=spawn):
                peer.start(manager)
            try:
                record=manager.state['dot1x_supplicants']['PC1'];self.assertEqual(record['namespace'],[1,2]);self.assertEqual(record['ifindex'],9)
                self.assertNotIn(password,json.dumps(manager.state));self.assertEqual(list((manager.directory/'dot1x-peer').iterdir()),[])
            finally:peer.PROCESSES.pop(123,None)

    def test_peer_edits_require_recreation(self):
        old=self.spec()['nodes'][0];new=copy.deepcopy(old);new['dot1x_supplicant']['password_sha256']='c'*64;manager=Mock()
        with self.assertRaises(RuntimeFailure):configure(manager,0,new,old)
        manager.ns.assert_not_called()

    def test_normal_cli_redacts_peer_password_pin_without_changing_exportable_spec(self):
        from network_labs.appliances.radius_server import redact
        spec=self.spec();result=redact(spec)
        self.assertEqual(result['nodes'][0]['dot1x_supplicant']['password_sha256'],'[redacted]')
        self.assertEqual(spec['nodes'][0]['dot1x_supplicant']['password_sha256'],'b'*64)

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

    def test_reap_completed_children_after_another_cli_recovery_without_touching_live_peer(self):
        dead=Mock();dead.poll.return_value=-9;live=Mock();live.poll.return_value=None
        with patch.dict(peer.PROCESSES,{123:dead,124:live},clear=True),patch.object(peer.os,'killpg') as signal:
            peer.reap_children();self.assertNotIn(123,peer.PROCESSES);self.assertIs(peer.PROCESSES[124],live)
        dead.wait.assert_called_once_with(timeout=0);live.wait.assert_not_called();signal.assert_not_called()
