"""Typed native capture entry and no-overwrite/authentication boundaries."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from network_labs.appliances import ui_capture


class CaptureEntryTests(unittest.TestCase):
    def test_literal_paths_and_bpf_are_argv_not_shell_and_stdio_is_inherited(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'capture $(literal).pcap');expression='icmp or (tcp port 80)'
            with patch.object(ui_capture.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as run:
                self.assertEqual(ui_capture.record('lab','PC1','eth0',path,3,100,expression),0)
            self.assertEqual(run.call_args_list[0].args[0],['sudo','-v'])
            args=run.call_args_list[1].args[0];self.assertEqual(args[args.index('--output')+1],path)
            self.assertEqual(args[-1],'--filter='+expression);self.assertEqual(run.call_args_list[1].kwargs,{})

    def test_invalid_limits_and_existing_paths_fail_before_auth(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(ui_capture.subprocess,'run') as run:
            path=Path(folder)/'new.pcap'
            for seconds,packets in [(0,10),(61,10),(2,10000)]:
                with self.assertRaises(ValueError):ui_capture.record('lab','PC1','eth0',str(path),seconds,packets,'')
            path.write_bytes(b'preserve')
            with self.assertRaises(ValueError):ui_capture.record('lab','PC1','eth0',str(path),2,10,'')
            self.assertEqual(path.read_bytes(),b'preserve');run.assert_not_called()
            link=Path(folder)/'link.pcap';link.symlink_to(Path(folder)/'missing')
            with self.assertRaises(ValueError):ui_capture.terminal_args('lab','PC1','eth0',str(link),2,10,'')

    def test_denied_auth_never_records(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(ui_capture.subprocess,'run',return_value=subprocess.CompletedProcess([],1)) as run:
            self.assertEqual(ui_capture.record('lab','PC1','eth0',str(Path(folder)/'new.pcap'),2,10,''),1)
            run.assert_called_once_with(['sudo','-v'])
