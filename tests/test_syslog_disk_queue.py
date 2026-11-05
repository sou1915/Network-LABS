"""Opt-in disk action queue, unchanged legacy defaults and honest observations."""
import copy
import io
import json
import subprocess
from pathlib import Path
import tempfile
from contextlib import redirect_stdout
from types import SimpleNamespace
import unittest
from network_labs.appliances.__main__ import main
from network_labs.appliances.examples import syslog_tcp_lab
from network_labs.appliances.service_adapters import adapters
from network_labs.appliances.spec import validate
from network_labs.appliances.syslog_forward import SPOOL,files,observe_spool,preflight
from network_labs.appliances.runtime import RuntimeFailure
from test_native_syslog_tls import tls_spec


class SyslogDiskQueueTests(unittest.TestCase):
    def test_cli_opt_in_and_tls_preserve_default_memory_queues(self):
        original=syslog_tcp_lab('/rootfs',forward=True)
        self.assertNotIn('queue.filename',files(original['nodes'][2])['syslog-forward.conf'])
        self.assertIsNone(observe_spool(None,original['nodes'][2]))
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example','--syslog-tcp','--syslog-tcp-forward','--syslog-disk-queue','--rootfs','/rootfs']),0)
        spec=json.loads(output.getvalue());self.assertEqual(spec,syslog_tcp_lab('/rootfs',forward=True,disk_queue=True))
        tls=tls_spec();tls['nodes'][2]['management']['syslog_disk_queue']=True;validate(tls)
        for node in (spec['nodes'][2],tls['nodes'][2]):
            config=files(node)['syslog-forward.conf']
            for token in ('main_queue(queue.type="FixedArray" queue.size="256"','queue.type="Disk"',SPOOL,
                          'queue.maxDiskSpace="1m"','queue.checkpointInterval="1"','queue.syncQueueFiles="on"',
                          'queue.fileCreateMode="0600"','queue.saveOnShutdown="on"'):
                self.assertIn(token,config)
            self.assertNotIn('imfile',config)
        old=original['nodes'][2];new=copy.deepcopy(old);new['management']['syslog_disk_queue']=True
        with self.assertRaisesRegex(ValueError,'recreation'):adapters(new,old)

    def test_type_and_udp_combinations_remain_refused(self):
        for value in (1,'on',{},None):
            spec=syslog_tcp_lab('/rootfs',forward=True);spec['nodes'][2]['management']['syslog_disk_queue']=value
            with self.subTest(value=value),self.assertRaises(ValueError):validate(spec)
        for value in (True,False):
            spec=syslog_tcp_lab('/rootfs',forward=True);spec['nodes'][2]['management'].update(syslog_transport='udp',syslog_disk_queue=value)
            with self.subTest(udp=value),self.assertRaises(ValueError):validate(spec)

    def test_base_images_cannot_import_queue_records_into_a_new_lab(self):
        with tempfile.TemporaryDirectory() as folder:
            node=syslog_tcp_lab(folder,forward=True,disk_queue=True)['nodes'][2]
            preflight(node)
            spool=Path(folder)/SPOOL.lstrip('/');spool.mkdir(parents=True)
            (spool/'forward.00000001').write_bytes(b'foreign queue data')
            with self.assertRaisesRegex(RuntimeFailure,'imported syslog spool'):preflight(node)
            (spool/'forward.00000001').unlink();spool.rmdir();spool.symlink_to('/missing-spool')
            with self.assertRaisesRegex(RuntimeFailure,'imported syslog spool'):preflight(node)

    def test_spool_observation_is_directory_conformity_only(self):
        node=syslog_tcp_lab('/rootfs',forward=True,disk_queue=True)['nodes'][2]
        for linked,directory,mode in ((False,True,'700:0:0\n'),(True,True,'700:0:0\n'),(False,False,'700:0:0\n'),(False,True,'777:0:0\n'),(False,True,'700:65532:65532\n')):
            def crun(*args,**options):
                status=0 if ('stat' in args or ('-L' in args and linked) or ('-d' in args and directory)) else 1
                return subprocess.CompletedProcess(args,status,mode if 'stat' in args else '','')
            result=observe_spool(SimpleNamespace(crun=crun),node)
            self.assertEqual(result['configuration_verified'],not linked and directory and mode=='700:0:0\n')
            self.assertNotIn('queue_depth',result);self.assertNotIn('delivered',result)
