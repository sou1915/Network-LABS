"""Durable closed-session intents, private bounds and policy-pinned explicit replay."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,MagicMock,patch
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.runtime import Manager,RuntimeFailure
from network_labs.appliances.__main__ import main
from contextlib import redirect_stdout,redirect_stderr
from network_labs.appliances.radius_outbox import enqueue,pending,flush,folder,read,acknowledge
from network_labs.appliances.radius_accounting_worker import accounting_request
from test_native_radius_accounting_retry import attrs

SECRET='private-outbox-test-secret'
SID='aaa-'+'a'*32


class OutboxTests(unittest.TestCase):
    def manager(self):
        m=Manager('outbox-test');m.state={'phase':'running','spec':radius_lab('/rootfs',SECRET,'a'*64,allow_shell=True,accounting=True,accounting_outbox=True)}
        return m

    def put(self,m,sid=SID):
        return enqueue(m,'PC1','192.0.2.20','learner',SECRET,sid,12,1,int(time.time())-7,cleanup_complete=True)

    def test_private_fsynced_record_survives_fresh_manager_without_active_state(self):
        with tempfile.TemporaryDirectory() as d,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(d)/'saved'):
            manager=self.manager();record=self.put(manager);directory=folder(manager)
            self.assertEqual(directory.stat().st_mode&0o777,0o700)
            path=directory/(SID+'.json');self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertNotIn(SECRET,path.read_text());self.assertNotIn('password',path.read_text())
            fresh=Manager(manager.name);self.assertEqual(pending(fresh)['pending'],1)
            self.assertNotIn('policy_sha256',str(pending(fresh)))
            self.assertEqual(read(path,manager),record)

    def test_only_verified_receipt_removes_event_and_replay_never_launches_sessions(self):
        with tempfile.TemporaryDirectory() as d,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(d)/'saved'):
            manager=self.manager();self.put(manager)
            with patch('network_labs.appliances.radius_accounting.send',return_value={'status':'passed','response_verified':False}) as send:
                result=flush(manager);self.assertEqual(result['remaining'],1)
                self.assertEqual(send.call_args.kwargs['event'],'stop');self.assertGreaterEqual(send.call_args.kwargs['delay_seconds'],7)
                self.assertEqual(send.call_args.kwargs['session_seconds'],12)
            with patch('network_labs.appliances.radius_accounting.send',return_value={'status':'passed','response_verified':True}):
                result=flush(manager);self.assertEqual(result['status'],'passed');self.assertEqual(result['remaining'],0)

    def test_changed_secret_address_user_or_policy_blocks_before_network(self):
        for change in ('secret','address','user','retry'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(d)/'saved'):
                manager=self.manager();self.put(manager);source=manager.state['spec']['nodes'][0];server=manager.state['spec']['nodes'][2]
                if change=='secret':server['radius_server']['clients'][0]['secret']='new-private-outbox-secret'
                elif change=='address':source['interfaces']['eth0']='192.0.2.11/24'
                elif change=='user':source['radius_access']['users']={}
                else:source['radius_access']['accounting_retries']=1
                with patch('network_labs.appliances.radius_accounting.send') as send:
                    result=flush(manager);send.assert_not_called();self.assertEqual(result['attempted'],0);self.assertEqual(result['remaining'],1)

    def test_failed_cleanup_capacity_and_corruption_never_silently_drop_events(self):
        with tempfile.TemporaryDirectory() as d,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(d)/'saved'):
            manager=self.manager()
            with self.assertRaises(ValueError):enqueue(manager,'PC1','192.0.2.20','learner',SECRET,SID,1,1,1,cleanup_complete=False)
            self.assertEqual(pending(manager)['pending'],0)
            for n in range(32):self.put(manager,'aaa-'+format(n,'032x'))
            with self.assertRaises(RuntimeFailure):self.put(manager)
            self.assertEqual(pending(manager)['pending'],32)
            from network_labs.appliances.radius_login import login
            accept={'status':'passed','endpoint':{'address':'192.0.2.10'},'authentication':{'response_verified':True,'response_code':2,'decision':'accepted'}}
            with patch('network_labs.appliances.radius_login.probe',return_value=accept),patch('network_labs.appliances.radius_login.SessionGroup') as groups,patch('network_labs.appliances.radius_login.account') as account:
                blocked=login(manager,'PC1','192.0.2.20',username='learner',password='test-password',secret=SECRET)
                groups.assert_not_called();account.assert_not_called();self.assertFalse(blocked['session_attempted'])
            path=folder(manager)/('aaa-'+format(0,'032x')+'.json');path.write_text('{invalid')
            with patch('network_labs.appliances.radius_accounting.send') as send:
                result=flush(manager);send.assert_not_called();self.assertEqual(result['status'],'unknown')
            self.assertTrue(path.exists())

    def test_symlinks_fifo_overpermissive_or_oversize_records_refuse_without_delivery(self):
        for change in ('symlink','fifo','mode','size'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(d)/'saved'):
                manager=self.manager();self.put(manager);path=folder(manager)/(SID+'.json')
                if change=='symlink':path.unlink();path.symlink_to(Path(d)/'missing')
                elif change=='fifo':path.unlink();os.mkfifo(path,0o600)
                elif change=='mode':path.chmod(0o644)
                else:path.write_text('x'*4097)
                with patch('network_labs.appliances.radius_accounting.send') as send:
                    result=flush(manager);send.assert_not_called();self.assertEqual(result['status'],'unknown')

    def test_supervisor_commits_only_after_cleanup_and_before_stop_send(self):
        from network_labs.appliances.radius_login import login
        accept={'status':'passed','endpoint':{'address':'192.0.2.10'},'authentication':{'response_verified':True,'response_code':2,'decision':'accepted'}}
        for closed in (True,False):
            with self.subTest(closed=closed),tempfile.TemporaryDirectory() as d,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(d)/'saved'):
                manager=self.manager();manager.directory=Path(d)/'runtime';manager.directory.mkdir()
                group=MagicMock();group.name=SID;group.closed=False;group.__enter__.return_value=group
                def finish(*_):group.closed=closed
                group.__exit__.side_effect=finish
                def receipt(*_,**kw):
                    if kw['event']=='stop':self.assertTrue(group.closed);self.assertEqual(pending(manager)['pending'],1)
                    return {'status':'passed','response_verified':True,'requests_sent':1}
                with patch('network_labs.appliances.radius_login.probe',return_value=accept),patch('network_labs.appliances.radius_login.SessionGroup',return_value=group),patch('network_labs.appliances.radius_login.account',side_effect=receipt) as account,patch('network_labs.appliances.radius_login.subprocess.call',return_value=0):
                    result=login(manager,'PC1','192.0.2.20',username='learner',password='test-password',secret=SECRET)
                self.assertEqual(account.call_count,2 if closed else 1)
                self.assertEqual(pending(manager)['pending'],0)
                self.assertEqual(result['accounting']['outbox']['status'],'cleared') if closed else self.assertEqual(result['accounting']['stop']['status'],'withheld')

    def test_cli_outbox_opt_in_is_saved_only_with_enabled_accounting(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name,value in (('secret',SECRET),('password','outbox-test-password')):
                path=root/name;path.write_text(value);path.chmod(0o600)
            args=['example','--rootfs','/rootfs','--radius','--radius-shell','--radius-accounting','--radius-accounting-outbox',
                  '--radius-user','learner','--radius-password-file',str(root/'password'),'--radius-secret-file',str(root/'secret')]
            with redirect_stdout(io.StringIO()) as output:self.assertEqual(main(args),0)
            spec=json.loads(output.getvalue());self.assertTrue(spec['nodes'][0]['radius_access']['accounting_outbox'])
            self.assertNotIn('outbox-test-password',output.getvalue())
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            self.assertEqual(main(['example','--rootfs','/rootfs','--radius-accounting-outbox']),1)

    def test_policy_requires_managed_accounting_and_finite_initial_delay_is_encoded(self):
        for value in (1,'yes',None):
            with self.assertRaises(ValueError):radius_lab('/rootfs',SECRET,'a'*64,allow_shell=True,accounting=True,accounting_outbox=value)
        with self.assertRaises(ValueError):radius_lab('/rootfs',SECRET,'a'*64,accounting_outbox=True)
        manager=self.manager();del manager.state['spec']['nodes'][2]['radius_server']
        with tempfile.TemporaryDirectory() as d,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(d)/'saved'):
            with self.assertRaises(ValueError):self.put(manager)
        packet=accounting_request({'username':'learner','source':'192.0.2.10','event':'stop','session_id':SID,'session_seconds':12,'terminate_cause':1,'secret':SECRET},delay_seconds=37)
        self.assertEqual(int.from_bytes(attrs(packet)[41],'big'),37)
