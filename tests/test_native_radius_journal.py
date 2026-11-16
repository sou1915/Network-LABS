"""Durable pre-Start intent and original-runtime cleanup evidence boundaries."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import ExitStack,redirect_stdout,redirect_stderr
from unittest.mock import Mock,patch
from network_labs.appliances.runtime import Manager,RuntimeFailure
from network_labs.appliances.examples import radius_lab
from network_labs.appliances import radius_journal as journal,radius_outbox as outbox
from network_labs.appliances.spec import validate
from network_labs.appliances.__main__ import main
from test_native_management import KEY

SID='aaa-'+'a'*32
SECRET='private-journal-test-secret'
BOOT='12345678-1234-1234-1234-123456789abc'
IDENTITY={'boot_id':BOOT,'namespace_dev':4,'namespace_ino':5,'container_pid':7,'container_start':'100'}


class JournalTests(unittest.TestCase):
    def context(self):
        stack=ExitStack();directory=stack.enter_context(tempfile.TemporaryDirectory());root=Path(directory)
        stack.enter_context(patch('network_labs.appliances.runtime.CONFIG_ROOT',root/'saved'))
        manager=Manager('journal-test');manager.state={'phase':'running','spec':radius_lab('/rootfs',SECRET,'a'*64,allow_shell=True,accounting=True,accounting_outbox=True,accounting_journal=True)}
        stack.enter_context(patch('network_labs.appliances.radius_journal.identity',return_value=IDENTITY.copy()))
        stack.enter_context(patch('network_labs.appliances.radius_journal.BOOT',root/'boot'));(root/'boot').write_text(BOOT)
        stack.enter_context(patch('network_labs.appliances.radius_journal.runtime.process_identity',return_value='123'))
        group_path=root/'group';group_path.mkdir();(group_path/'cgroup.events').write_text('populated 1\nfrozen 0\n');(group_path/'cgroup.kill').write_text('')
        stack.enter_context(patch('network_labs.appliances.radius_journal.session_parent',return_value=root))
        group_path.rename(root/SID);group=Mock(name=SID);group.name=SID;group.path=root/SID
        return stack,manager,root,group

    def test_committed_intent_is_private_and_contains_no_credential_bytes(self):
        stack,manager,root,group=self.context()
        with stack:
            record=journal.begin(manager,'PC1','learner',group);path=journal.directory(manager)/(SID+'.json')
            self.assertEqual(path.stat().st_mode&0o777,0o600);self.assertNotIn(SECRET,path.read_text())
            self.assertEqual(journal.pending(Manager(manager.name))['entries'][0]['phase'],'intent')
            self.assertEqual(record['phase'],'intent')

    def test_live_supervisor_populated_group_and_missing_group_never_create_stop(self):
        stack,manager,root,group=self.context()
        with stack:
            journal.begin(manager,'PC1','learner',group)
            actual=journal.reconcile(manager,SID,terminate=True);self.assertEqual(actual['error'],'SUPERVISOR_STILL_ACTIVE')
            with patch('network_labs.appliances.radius_journal.runtime.process_identity',return_value=None):
                actual=journal.reconcile(manager,SID);self.assertEqual(actual['error'],'SESSION_STILL_POPULATED')
                (group.path/'cgroup.events').unlink();(group.path/'cgroup.kill').unlink();group.path.rmdir()
                actual=journal.reconcile(manager,SID,terminate=True);self.assertEqual(actual['status'],'unknown')
            self.assertEqual(outbox.pending(manager)['pending'],0);self.assertEqual(journal.pending(manager)['pending'],1)

    def test_explicit_termination_needs_matching_group_and_empty_evidence(self):
        stack,manager,root,group=self.context()
        with stack:
            journal.begin(manager,'PC1','learner',group)
            # A synthetic filesystem cannot emulate cgroup.kill; remaining
            # populated after that write must never produce a cleanup checkpoint.
            with patch('network_labs.appliances.radius_journal.runtime.process_identity',return_value=None),patch('network_labs.appliances.radius_journal.time.monotonic',side_effect=[0,3]):
                actual=journal.reconcile(manager,SID,terminate=True)
            self.assertEqual(actual['status'],'unknown');self.assertEqual(outbox.pending(manager)['pending'],0)
            self.assertEqual(journal.pending(manager)['entries'][0]['phase'],'intent')

    def test_empty_checkpoint_allows_safe_handoff_after_runtime_change(self):
        stack,manager,root,group=self.context()
        with stack:
            record=journal.begin(manager,'PC1','learner',group);(group.path/'cgroup.events').write_text('populated 0\nfrozen 0\n');journal.mark_empty(manager,record)
            with patch('network_labs.appliances.radius_journal.runtime.process_identity',return_value=None),patch('network_labs.appliances.radius_journal.identity',return_value={**IDENTITY,'namespace_ino':999}):
                actual=journal.reconcile(manager,SID,terminate=True)
            self.assertEqual(actual['status'],'passed',actual);self.assertFalse(actual['terminated']);self.assertTrue(group.path.exists())
            self.assertEqual(journal.pending(manager)['pending'],0);self.assertEqual(outbox.pending(manager)['pending'],1)
            stop=outbox.read(outbox.folder(manager)/(SID+'.json'),manager);self.assertEqual(stop['terminate_cause'],9);self.assertEqual(stop['session_seconds'],0)

    def test_existing_committed_stop_finishes_handoff_without_rewriting_event(self):
        stack,manager,root,group=self.context()
        with stack:
            record=journal.begin(manager,'PC1','learner',group);(group.path/'cgroup.events').write_text('populated 0\n');journal.mark_empty(manager,record)
            stop=outbox.enqueue(manager,'PC1','192.0.2.20','learner',SECRET,SID,12,1,100,cleanup_complete=True)
            with patch('network_labs.appliances.radius_journal.runtime.process_identity',return_value=None),patch('network_labs.appliances.radius_journal.identity',return_value={**IDENTITY,'namespace_ino':999}):
                result=journal.reconcile(manager,SID)
            self.assertEqual(result['status'],'passed');self.assertEqual(journal.pending(manager)['pending'],0)
            self.assertEqual(outbox.read(outbox.folder(manager)/(SID+'.json'),manager),stop)

    def test_runtime_group_or_policy_changes_block_intent_before_kernel_write(self):
        for change in ('runtime','group','policy'):
            stack,manager,root,group=self.context()
            with self.subTest(change=change),stack:
                journal.begin(manager,'PC1','learner',group)
                if change=='runtime':stack.enter_context(patch('network_labs.appliances.radius_journal.identity',return_value={**IDENTITY,'namespace_ino':6}))
                elif change=='group':
                    path=journal.directory(manager)/(SID+'.json');record=json.loads(path.read_text());record['cgroup_ino']+=1;path.write_text(json.dumps(record))
                else:manager.state['spec']['nodes'][0]['radius_access']['session_seconds']=60
                with patch('network_labs.appliances.radius_journal.runtime.process_identity',return_value=None):actual=journal.reconcile(manager,SID,terminate=True)
                self.assertNotEqual(actual['status'],'passed');self.assertEqual((group.path/'cgroup.kill').read_text(),'');self.assertEqual(outbox.pending(manager)['pending'],0)

    def test_empty_checkpoint_write_failure_keeps_original_intent(self):
        stack,manager,root,group=self.context()
        with stack:
            record=journal.begin(manager,'PC1','learner',group);(group.path/'cgroup.events').write_text('populated 0\n')
            with patch('network_labs.appliances.radius_journal.os.replace',side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):journal.mark_empty(manager,record)
            self.assertEqual(journal.pending(manager)['entries'][0]['phase'],'intent')

    def test_policy_cli_and_metadata_read_do_not_need_a_running_lab_lock(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name,value in (('password','journal-test-password'),('secret',SECRET)):
                path=root/name;path.write_text(value);path.chmod(0o600)
            args=['example','--rootfs','/rootfs','--radius','--radius-shell','--radius-accounting','--radius-accounting-outbox','--radius-accounting-journal',
                  '--radius-user','learner','--radius-password-file',str(root/'password'),'--radius-secret-file',str(root/'secret')]
            with redirect_stdout(io.StringIO()) as output:self.assertEqual(main(args),0)
            self.assertTrue(json.loads(output.getvalue())['nodes'][0]['radius_access']['accounting_journal'])
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):self.assertEqual(main(['example','--rootfs','/rootfs','--radius-accounting-journal']),1)
        with self.assertRaises(ValueError):radius_lab('/rootfs',SECRET,'a'*64,allow_shell=True,accounting=True,accounting_journal=True)
        spec=radius_lab('/rootfs',SECRET,'a'*64,accounting=True,accounting_outbox=True,accounting_journal=True,ssh_key=KEY,ssh_shell=True)
        self.assertTrue(spec['nodes'][0]['radius_access']['accounting_journal'])
        self.assertTrue(spec['nodes'][0]['management']['ssh_radius'])
