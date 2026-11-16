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

    def test_backend_arguments_are_accepted_by_the_real_cli(self):
        """The desktop entry once passed an option the CLI rejects, so no capture ever started."""
        from network_labs.appliances.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'new.pcap')
            with patch.object(ui_capture.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as run:
                ui_capture.record('lab','PC1','eth0',path,3,100,'icmp')
            args=run.call_args_list[1].args[0];backend=args[args.index(str(ui_capture.SOURCE))+1:]
            with patch('network_labs.appliances.capture.capture',return_value={'stop_reason':'completed'}) as capture,patch('sys.stdout'):
                self.assertEqual(main(backend),0)
            self.assertEqual(capture.call_args.args[1:3],('PC1','eth0'))
            self.assertEqual(capture.call_args.kwargs['expression'],'icmp');self.assertEqual(str(capture.call_args.args[3]),path)
