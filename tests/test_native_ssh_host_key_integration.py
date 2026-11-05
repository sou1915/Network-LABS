"""Strict known-host verification across cold restore and explicit key replacement."""
import base64
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
from network_labs.appliances.examples import management_lab
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager,RuntimeFailure,run,static_busybox_rootfs
from network_labs.appliances.ssh_host_key import KEY,policy
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeSSHHostKeyTests(unittest.TestCase):
    def test_strict_identity_restore_private_drift_refusal_and_explicit_replacement(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('dropbear','dropbearkey','ssh','ssh-keygen','busybox','crun','ip'):self.assertIsNotNone(shutil.which(tool),tool)
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        with tempfile.TemporaryDirectory() as folder,patch('network_labs.appliances.runtime.CONFIG_ROOT',Path(folder)/'saved'):
            root=Path(folder);client=root/'client';original=root/'host';replacement=root/'replacement'
            run(['ssh-keygen','-q','-t','ed25519','-N','','-f',client])
            for path in (original,replacement):run(['dropbearkey','-t','ed25519','-f',path]);path.chmod(0o600)
            original_bytes=original.read_bytes();new_policy=policy(replacement)
            rootfs=static_busybox_rootfs(shutil.which('busybox'),root/'rootfs',dropbear=shutil.which('dropbear'))
            spec=management_lab(rootfs,client.with_suffix('.pub').read_text(),ssh_actions=['identity','hostname'],ssh_host_key_file=original)
            spec['name']='ssh-host-key-'+str(os.getpid());manager=Manager(spec['name']);known=root/'known_hosts'
            declared=spec['nodes'][2]['management']['ssh_host_key']['public_key']
            known.write_text('192.0.2.20 '+declared+'\n')
            def ssh(command='identity'):
                return manager.ns(0,'ssh','-F','/dev/null','-o','BatchMode=yes','-o','IdentitiesOnly=yes',
                    '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(known),'-o','GlobalKnownHostsFile=/dev/null',
                    '-o','HostKeyAlgorithms=ssh-ed25519','-o','ConnectTimeout=2','-o','LogLevel=ERROR',
                    '-i',str(client),'lab@192.0.2.20',command,check=False,timeout=6,input_text='')
            def ready():
                until=time.monotonic()+10
                while time.monotonic()<until:
                    reply=ssh()
                    if reply.returncode==0:
                        self.assertIn('uid=65532',reply.stdout);return
                    time.sleep(.1)
                self.fail('Strict known-host SSH did not become ready: '+reply.stderr)
            def refuse():
                with manager.locked(),self.assertRaises(RuntimeFailure):manager.write_startup()
            def restore_runtime_key():
                manager.crun('exec','R1','/bin/sh','-c','umask 077; /bin/busybox base64 -d > '+KEY,
                    input_text=base64.b64encode(original_bytes).decode('ascii'))
                manager.crun('exec','R1','/bin/busybox','chmod','600',KEY)
            try:
                with manager.locked():manager.start(spec)
                ready();state=copy.deepcopy(manager.read())
                self.assertEqual(ssh('hostname').stdout.strip(),'R1');self.assertEqual(ssh('/bin/sh').returncode,126)
                self.assertNotEqual(manager.crun('exec','--user','65532:65532','R1','/bin/busybox','cat',KEY,check=False).returncode,0)
                for node in ('PC1','SW1'):
                    self.assertNotEqual(manager.crun('exec',node,'/bin/busybox','test','-e',KEY,check=False).returncode,0)
                self.assertTrue(manager.inspect('R1')['management']['ssh_host_key']['configuration_verified'])
                manager.crun('exec','R1','/bin/busybox','chmod','644',KEY);refuse()
                manager.crun('exec','R1','/bin/busybox','chmod','600',KEY)
                manager.crun('exec','R1','/bin/sh','-c','printf altered > '+KEY);refuse()
                restore_runtime_key();ready()
                manager.crun('exec','R1','/bin/busybox','rm',KEY)
                manager.crun('exec','R1','/bin/busybox','ln','-s','/etc/passwd',KEY);refuse()
                manager.crun('exec','R1','/bin/busybox','rm',KEY);restore_runtime_key()
                self.assertEqual(manager.read(),state)
                with manager.locked():
                    manager.write_startup();saved=load_startup(spec['name']);self.assertEqual(saved,spec)
                    self.assertNotIn(base64.b64encode(original_bytes).decode(),json.dumps(saved))
                    manager.stop();manager.start(saved)
                ready()  # Same known_hosts file, no keyscan or trust rewrite.
                self.assertEqual(known.read_text(),'192.0.2.20 '+declared+'\n')
                with manager.locked():manager.stop()
                # Invalid or changed source assets fail before any lab allocation.
                for fault in ('mode','mismatch','malformed','symlink','missing'):
                    if fault=='mode':original.chmod(0o644)
                    if fault=='mismatch':original.write_bytes(replacement.read_bytes())
                    if fault=='malformed':original.write_bytes(b'invalid')
                    if fault=='symlink':original.unlink();original.symlink_to(replacement)
                    if fault=='missing':original.unlink()
                    with self.subTest(fault=fault),manager.locked(),self.assertRaises(RuntimeFailure):manager.start(saved)
                    self.assertFalse(manager.directory.exists())
                    if original.is_symlink():original.unlink()
                    original.write_bytes(original_bytes);original.chmod(0o600)
                rotated=copy.deepcopy(saved);rotated['nodes'][2]['management']['ssh_host_key']=new_policy
                with manager.locked():manager.start(rotated)
                # Real new daemon still answers, but the old trusted identity fails.
                until=time.monotonic()+10
                while time.monotonic()<until:
                    denied=ssh()
                    if 'Host key verification failed' in denied.stderr:break
                    time.sleep(.1)
                self.assertNotEqual(denied.returncode,0);self.assertIn('Host key verification failed',denied.stderr)
                known.write_text('192.0.2.20 '+new_policy['public_key']+'\n');ready()
                with manager.locked():manager.write_startup();manager.stop();manager.start(load_startup(spec['name']))
                ready()
            finally:
                if manager.directory.exists():
                    with manager.locked():manager.stop()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
