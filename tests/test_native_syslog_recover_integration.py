"""Public sender recovery refuses live/ambiguous state and replays retained queues."""
import json
import sys
from network_labs.appliances.runtime import run
from network_labs.appliances.syslog_forward import PID,SPOOL
import test_native_syslog_disk_queue_integration as disk_queue


class NativeSyslogRecoverTests(disk_queue.NativeSyslogDiskQueueTests):
    # Inherited protocol checks still cover both TCP and TLS, exact PID/argv,
    # actual spool markers, SIGKILL, wire evidence, drift and cold restore.
    def cli(self,manager):
        return run([sys.executable,'-m','network_labs.appliances','syslog-forward-recover',manager.name,'PC2'],check=False,timeout=25)

    def write_pid(self,manager,text):
        manager.crun('exec','PC2','/bin/sh','-c','cat > '+PID,input_text=text)

    def before_sender_crash(self,manager,node,old_pid,transport):
        original=manager.crun('exec','PC2','/bin/busybox','cat',PID).stdout
        def refused(reason):
            result=self.cli(manager);self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertIn('recovery refused',result.stderr.lower())
            self.assertIn(reason,result.stderr.lower())
        refused('live pid owner')
        self.assertEqual(manager.crun('exec','PC2','/bin/busybox','cat',PID).stdout,original)
        # A live sender remains protected even after its PID file disappears.
        manager.crun('exec','PC2','/bin/busybox','rm',PID);refused('live rsyslog process')
        self.assertNotEqual(manager.crun('exec','PC2','/bin/busybox','test','-e',PID,check=False).returncode,0)
        self.write_pid(manager,'1\n');refused('live pid owner')  # Unrelated live container init.
        self.assertEqual(manager.crun('exec','PC2','/bin/busybox','cat',PID).stdout,'1\n')
        self.write_pid(manager,'not-a-pid\n');refused('invalid sender pid file')
        self.assertEqual(manager.crun('exec','PC2','/bin/busybox','cat',PID).stdout,'not-a-pid\n')
        manager.crun('exec','PC2','/bin/busybox','rm',PID)
        manager.crun('exec','PC2','/bin/busybox','ln','-s','/run/messages',PID);refused('must not be a symlink')
        self.assertEqual(manager.crun('exec','PC2','/bin/busybox','readlink',PID).stdout.strip(),'/run/messages')
        manager.crun('exec','PC2','/bin/busybox','rm',PID);self.write_pid(manager,original)
        # No refusal may signal the original sender or replace its PID.
        self.assertEqual(manager.crun('exec','PC2','/bin/busybox','kill','-0',str(old_pid),check=False).returncode,0)

    def restart_sender(self,manager,node,old_pid,transport):
        original=manager.crun('exec','PC2','/bin/busybox','cat',PID).stdout
        manager.crun('exec','PC2','/bin/busybox','chmod','777',SPOOL)
        result=self.cli(manager);self.assertNotEqual(result.returncode,0)
        self.assertIn('spool differs',result.stderr)
        self.assertEqual(manager.crun('exec','PC2','/bin/busybox','cat',PID).stdout,original)
        manager.crun('exec','PC2','/bin/busybox','chmod','700',SPOOL)
        config=manager.directory/'PC2/files/syslog-forward.conf';text=config.read_text();config.write_text(text+'# drift\n')
        result=self.cli(manager);self.assertNotEqual(result.returncode,0)
        self.assertIn('configuration',result.stderr)
        self.assertEqual(manager.crun('exec','PC2','/bin/busybox','cat',PID).stdout,original)
        config.write_text(text)
        # Preserve the spool; remove local output to exclude log-file replay.
        manager.crun('exec','PC2','/bin/busybox','rm','-f','/run/messages')
        if transport=='tls':manager.crun('exec','PC2','/bin/busybox','rm',PID)
        recovered=self.cli(manager);self.assertEqual(recovered.returncode,0,recovered.stderr)
        report=json.loads(recovered.stdout);self.assertEqual(report['status'],'started')
        self.assertFalse(report['configuration_changed'])
        self.assertEqual(report['previous_pid'],old_pid if transport=='tcp' else None)
        actual=manager.crun('exec','PC2','/bin/busybox','cat',PID).stdout
        self.assertEqual(int(actual),report['pid']);self.assertNotEqual(report['pid'],old_pid)
        # A duplicate invocation must refuse and keep the new live PID.
        duplicate=self.cli(manager);self.assertNotEqual(duplicate.returncode,0)
        self.assertEqual(manager.crun('exec','PC2','/bin/busybox','cat',PID).stdout,actual)
