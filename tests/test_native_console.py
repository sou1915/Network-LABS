"""Console launch stays typed; credentials and interactive I/O stay in terminal."""
import subprocess
import unittest
from unittest.mock import patch
from network_labs.appliances import ui_console


class ConsoleTests(unittest.TestCase):
    def test_auth_failure_does_not_open_guest(self):
        with patch.object(ui_console.subprocess,'run',return_value=subprocess.CompletedProcess([],1)) as run:
            self.assertEqual(ui_console.open_console('lab','PC1'),1)
        run.assert_called_once_with(['sudo','-v'])

    def test_typed_terminal_and_guest_shell_preserve_real_stdio(self):
        with patch.object(ui_console.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as run:
            self.assertEqual(ui_console.open_console('lab','PC1'),0)
        self.assertEqual(run.call_args_list[0].args[0],['sudo','-v'])
        args=run.call_args_list[1].args[0]
        self.assertEqual(args[-6:],['exec','--tty','lab','PC1','--','/bin/sh'])
        self.assertEqual(run.call_args_list[1].kwargs,{})
        self.assertEqual(ui_console.terminal_args('lab','PC1')[-2:],['lab','PC1'])

    def test_invalid_selection_fails_before_sudo(self):
        with patch.object(ui_console.subprocess,'run') as run:
            for lab,node in [('lab;id','PC1'),('lab','../PC1'),('lab','--help')]:
                with self.assertRaises(ValueError):ui_console.open_console(lab,node)
            run.assert_not_called()
