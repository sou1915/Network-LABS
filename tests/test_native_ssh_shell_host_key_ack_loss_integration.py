"""Pinned journaled SSH shell: real lost accounting receipts, no false success."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from network_labs.appliances.capture import capture
from network_labs.appliances.examples import radius_lab
from network_labs.appliances.firewall import fingerprint
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.radius_session import session_parent
from network_labs.appliances import radius_journal as journal,radius_outbox as outbox
from network_labs.appliances.runtime import Manager,run,static_busybox_rootfs
from network_labs.appliances.spec import namespace,validate
from test_native_radius_accounting_retry_integration import requests
from test_native_radius_accounting_retry import attrs
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativePinnedShellAckLossTests(unittest.TestCase):
    def test_lost_start_blocks_payload_lost_stop_is_unknown_and_explicit_flush_recovers(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('dropbear','dropbearkey','freeradius','ssh','ssh-keygen','cc','busybox','crun','ip','nft','tcpdump'):
            self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        routes={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        host_nft=fingerprint(json.loads(run(['nft','-j','list','ruleset']).stdout))
        secret='pinned-shell-ack-loss-secret';password='pinned-shell-ack-loss-password';clients=[]
        with tempfile.TemporaryDirectory() as folder,ThreadPoolExecutor(max_workers=1) as pool,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);key=root/'client';host=root/'host';known=root/'known_hosts'
            run(['ssh-keygen','-q','-t','ed25519','-N','','-f',key]);run(['dropbearkey','-t','ed25519','-f',host]);host.chmod(0o600)
            relay=root/'relay';run(['cc','-O2','-Wall','-Wextra','-Werror',Path(__file__).parents[1]/'network_labs/appliances/ssh_radius_relay.c','-o',relay])
            modules=next(p for p in ('/usr/lib/freeradius','/usr/lib/x86_64-linux-gnu/freeradius') if (Path(p)/'rlm_pap.so').is_file())
            rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',dropbear=shutil.which('dropbear'),ssh_relay=relay,
                freeradius=shutil.which('freeradius'),freeradius_modules=modules,freeradius_dictionaries='/usr/share/freeradius')
            spec=radius_lab(rootfs,secret,hashlib.sha256(password.encode()).hexdigest(),ssh_key=key.with_suffix('.pub').read_text(),
                ssh_shell=True,accounting=True,accounting_outbox=True,accounting_journal=True,ssh_host_key_file=host)
            spec['name']='pinned-ack-loss-'+str(os.getpid());spec['nodes'][0]['radius_access']['session_seconds']=15
            spec['nodes'][1]['interfaces']['eth2']=''
            spec['nodes'].append({'name':'PC3','runtime':'oci','rootfs':str(rootfs),'interfaces':{'eth0':'192.0.2.30/24'}})
            spec['links'].append([['SW1','eth2'],['PC3','eth0']]);spec=validate(spec);manager=Manager(spec['name'])
            trusted='192.0.2.10 '+spec['nodes'][0]['management']['ssh_host_key']['public_key']+'\n';known.write_text(trusted)
            def args(action='shell'):
                return ['ssh','-F','/dev/null','-T','-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
                    '-o','UserKnownHostsFile='+str(known),'-o','GlobalKnownHostsFile=/dev/null','-o','ConnectTimeout=2','-o','LogLevel=ERROR',
                    '-i',str(key),'lab@192.0.2.10',action]
            def ssh(script='',action='shell'):
                return manager.ns(3,*args(action),input_text='learner\n'+password+'\n'+script,check=False,timeout=14)
            def wait(predicate,label):
                until=time.monotonic()+10
                while time.monotonic()<until:
                    if predicate():return
                    time.sleep(.05)
                self.fail(label)
            def loss(enabled):
                manager.ns(0,'nft','flush','chain','inet','pinned_ack_loss','input')
                if enabled:manager.ns(0,'nft','add','rule','inet','pinned_ack_loss','input','ip','saddr','192.0.2.20','udp','sport','1813','counter','drop')
            def dropped():
                rules=json.loads(manager.ns(0,'nft','-j','list','chain','inet','pinned_ack_loss','input').stdout)
                return sum(e['counter']['packets'] for r in rules['nftables'] for e in r.get('rule',{}).get('expr',[]) if 'counter' in e)
            def observed(name,seconds,operation):
                event=threading.Event();path=root/name
                future=pool.submit(capture,Manager(spec['name']),'PC1','eth0',path,seconds=seconds,packets=100,expression='udp port 1813',ready=event.set)
                self.assertTrue(event.wait(5));result=operation();future.result(timeout=seconds+4)
                return result,requests(path.read_bytes())
            def queued():
                self.assertEqual(journal.pending(manager)['pending'],0)
                pending=outbox.pending(manager);self.assertEqual(pending['pending'],1,pending)
                sid=pending['entries'][0]['session_id']
                self.assertEqual(list(session_parent(manager,'PC1').glob('aaa-*')),[])
                return outbox.read(outbox.folder(manager)/(sid+'.json'),manager)
            def flush():
                with manager.locked():return outbox.flush(manager,limit=1)
            def recover(record,label):
                loss(False);result,packets=observed(label,3,flush)
                self.assertEqual(result['status'],'passed',result);self.assertEqual(len(packets),1)
                fields=attrs(packets[0]);self.assertEqual(fields[44].decode(),record['session_id'])
                self.assertEqual(int.from_bytes(fields[40],'big'),2)
                self.assertEqual(outbox.pending(manager)['pending'],0);self.assertEqual(journal.pending(manager)['pending'],0)
            try:
                with manager.locked():manager.start(spec)
                wait(lambda:ssh(action='identity').returncode==0,'Pinned diagnostic/RADIUS authentication unavailable')
                manager.ns(0,'nft','add','table','inet','pinned_ack_loss')
                manager.ns(0,'nft','add','chain','inet','pinned_ack_loss','input','{ type filter hook input priority 0; policy accept; }')
                loss(True)
                denied,packets=observed('lost-start.pcap',7,lambda:ssh('/bin/busybox touch /tmp/forbidden-payload\nexit\n'))
                self.assertEqual(denied.returncode,126,denied);self.assertEqual(denied.stdout,'')
                self.assertNotEqual(manager.crun('exec','PC1','/bin/busybox','test','-e','/tmp/forbidden-payload',check=False).returncode,0)
                self.assertEqual(ssh(action='identity').returncode,0)  # UDP/1812 and SSH remain live.
                self.assertEqual(dropped(),2);self.assertEqual(len(packets),2)
                start=queued();self.assertEqual(start['session_seconds'],0);self.assertEqual(start['terminate_cause'],9)
                self.assertEqual({int.from_bytes(attrs(p)[40],'big') for p in packets},{1,2})
                self.assertTrue(all(attrs(p)[44].decode()==start['session_id'] for p in packets))
                for packet in packets:
                    self.assertEqual(packet[4:20],hashlib.md5(packet[:4]+bytes(16)+packet[20:]+secret.encode()).digest())
                recover(start,'start-recovery.pcap')
                # Admit a real shell first, then lose only its Stop receipt.
                output=root/'live-shell.log'
                with output.open('wb') as log:
                    client=subprocess.Popen(['ip','netns','exec',namespace(spec,3),*args()],stdin=subprocess.PIPE,stdout=log,stderr=log,text=True)
                clients.append(client);client.stdin.write('learner\n'+password+'\n/bin/busybox touch /tmp/admitted-payload\n/bin/echo PAYLOAD-READY\n');client.stdin.flush()
                wait(lambda:'PAYLOAD-READY' in output.read_text(errors='replace'),'Accounted shell did not start')
                self.assertEqual(journal.pending(manager)['pending'],1);self.assertEqual(outbox.pending(manager)['pending'],0)
                loss(True)
                def finish():
                    client.stdin.write('exit 0\n');client.stdin.flush();client.stdin.close();return client.wait(timeout=12)
                code,packets=observed('lost-stop.pcap',4,finish)
                self.assertEqual(code,125,output.read_text(errors='replace'))
                self.assertEqual(dropped(),1);self.assertEqual(len(packets),1)
                stop=queued();self.assertNotEqual(stop['session_id'],start['session_id']);self.assertEqual(stop['terminate_cause'],1)
                self.assertEqual(attrs(packets[0])[44].decode(),stop['session_id'])
                self.assertEqual(int.from_bytes(attrs(packets[0])[40],'big'),2)
                self.assertEqual(manager.crun('exec','PC1','/bin/busybox','test','-f','/tmp/admitted-payload',check=False).returncode,0)
                recover(stop,'stop-recovery.pcap')
                records=manager.crun('exec','PC2','/bin/busybox','cat','/run/network-labs-radius-accounting/sessions').stdout.splitlines()
                for record in (start,stop):
                    self.assertTrue(any(line.startswith('Start|'+record['session_id']+'|') for line in records))
                    self.assertGreaterEqual(sum(line.startswith('Stop|'+record['session_id']+'|') for line in records),2)
                manager.ns(0,'nft','delete','table','inet','pinned_ack_loss')
                with manager.locked():
                    manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec);manager.stop();manager.start(saved)
                self.assertEqual(known.read_text(),trusted)
                wait(lambda:ssh('/bin/echo RESTORED-ACKNOWLEDGED\nexit\n').returncode==0,'Restored pinned accounted shell unavailable')
                self.assertEqual(journal.pending(manager)['pending'],0);self.assertEqual(outbox.pending(manager)['pending'],0)
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
                for client in clients:
                    if client.poll() is None:client.kill()
                    client.wait(timeout=3)
                    if client.stdin and not client.stdin.closed:client.stdin.close()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in routes.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        self.assertEqual(fingerprint(json.loads(run(['nft','-j','list','ruleset']).stdout)),host_nft)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
