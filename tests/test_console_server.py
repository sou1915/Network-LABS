"""The in-app terminals: the lab's console server (socket, sessions, typed lines only) and the CLI window."""
import json
import os
import socket
import stat
import tempfile
import threading
import time
import unittest
from unittest import mock

from network_labs.appliances import console_server


class FakeConsole:
    def __init__(self, node):
        self.node, self.mode, self.syntax = node, 'exec', 'ios'

    def prompt(self):
        return f'{self.node}{"#" if self.mode == "enable" else ">"} '

    def line(self, text):
        if text == 'exit':
            raise EOFError
        if text == 'en':
            self.mode = 'enable'
            return ''
        if text == 'boom':
            raise ValueError('Commande inconnue')
        return 'reply to ' + text

    def complete(self, buffer):
        return ['bgp'] if buffer == 'show ip b' else ['bgp', 'route']


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.running = True
        self.server = console_server.Server('lab-1', os.getuid(), root=self.folder.name, console=FakeConsole,
                                            alive=lambda: self.running)
        thread = threading.Thread(target=self.server.serve, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(setattr, self, 'running', False)
        deadline = time.monotonic() + 5
        while not self.server.path.exists() and time.monotonic() < deadline:
            time.sleep(.02)

    def ask(self, payload):
        return console_server.request('lab-1', payload, root=self.folder.name)

    def test_socket_is_private_and_sessions_keep_their_mode(self):
        info = self.server.path.stat()
        self.assertTrue(stat.S_ISSOCK(info.st_mode))
        self.assertEqual((stat.S_IMODE(info.st_mode), info.st_uid), (0o600, os.getuid()))
        self.assertTrue(console_server.available('lab-1', root=self.folder.name))
        self.assertFalse(console_server.available('lab-2', root=self.folder.name))
        opened = self.ask({'op': 'open', 'session': 'a' * 16, 'node': 'R1'})
        self.assertEqual(opened['prompt'], 'R1> ')
        self.assertIn('Cisco IOS', opened['banner'])
        self.assertEqual(self.ask({'op': 'line', 'session': 'a' * 16, 'node': 'R1', 'text': 'en'})['prompt'], 'R1# ')
        other = self.ask({'op': 'line', 'session': 'b' * 16, 'node': 'R1', 'text': 'show'})
        self.assertEqual(other['prompt'], 'R1> ')  # another window, another terminal
        self.assertEqual(self.ask({'op': 'line', 'session': 'a' * 16, 'node': 'R1', 'text': 'boom'})['reply'], '% Commande inconnue')
        self.assertEqual(self.ask({'op': 'complete', 'session': 'a' * 16, 'node': 'R1', 'text': 'show ip b'})['words'], ['bgp'])
        closed = self.ask({'op': 'line', 'session': 'a' * 16, 'node': 'R1', 'text': 'exit'})
        self.assertTrue(closed['closed'])
        self.assertEqual(self.ask({'op': 'line', 'session': 'a' * 16, 'node': 'R1', 'text': 'x'})['prompt'], 'R1> ')  # a fresh one

    def test_bad_requests_are_refused(self):
        for payload in ({'op': 'shell'}, {'op': 'line', 'session': 'short', 'node': 'R1', 'text': 'x'},
                        {'op': 'line', 'session': 'a' * 16, 'node': '../R1', 'text': 'x'},
                        {'op': 'line', 'session': 'a' * 16, 'node': 'R1', 'text': 'a\nb'}):
            with self.subTest(payload=payload):
                self.assertFalse(self.ask(payload)['ok'])
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(self.server.path))
            client.sendall(b'x' * 5000)
            self.assertFalse(json.loads(client.recv(4096))['ok'])

    def test_the_socket_appears_only_once_it_accepts(self):
        server = console_server.Server('lab-3', os.getuid(), root=self.folder.name, console=FakeConsole, alive=lambda: False)
        listener = server.bind()
        self.addCleanup(listener.close)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(server.path))  # listening already: no refused connection in between
        self.assertEqual(sorted(p.name for p in server.path.parent.iterdir() if 'lab-3' in p.name), [server.path.name])
        self.assertEqual(stat.S_IMODE(server.path.stat().st_mode), 0o600)

    def test_the_server_leaves_with_the_lab(self):
        self.running = False
        deadline = time.monotonic() + 10
        while self.server.path.exists() and time.monotonic() < deadline:
            time.sleep(.1)
        self.assertFalse(self.server.path.exists())


class BridgeConsolesTest(unittest.TestCase):
    def test_consoles_action_is_a_status_that_starts_the_terminals(self):
        from network_labs.appliances import ui_bridge
        request = {'id': '0' * 32, 'owner_uid': os.geteuid(), 'action': 'consoles', 'target': 'lab-1', 'lab': 'lab-1',
                   'node': None, 'destination': None}
        ui_bridge.validate_request(request)
        topology = {'name': 'lab-1', 'nodes': [], 'links': []}
        backend = mock.Mock(returncode=0, stdout=json.dumps({'ok': True, 'action': 'status', 'lab': 'lab-1', 'topology': topology,
                                                            'data': {'name': 'lab-1', 'phase': 'running', 'nodes': []}}))
        with mock.patch('subprocess.run', side_effect=[mock.Mock(returncode=0), backend]) as run, \
                mock.patch.object(ui_bridge, 'start_consoles', return_value=True) as start:
            payload = ui_bridge.execute_request(request)
        self.assertEqual(run.call_args_list[1].args[0][-2:], ['status', 'lab-1'])
        start.assert_called_once_with('lab-1')
        self.assertEqual((payload['action'], payload['consoles']), ('consoles', True))


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI requires X display')
class ConsoleWindowTest(unittest.TestCase):
    def test_typing_history_completion_question_mark_and_more(self):
        import tkinter as tk
        from network_labs.appliances.ui_cli import ConsoleWindow
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        consoles = {}

        def request(payload):
            console = consoles.setdefault(payload.get('session'), FakeConsole(payload['node']))
            if payload['op'] == 'open':
                return {'ok': True, 'prompt': console.prompt(), 'banner': ''}
            if payload['op'] == 'complete':
                return {'ok': True, 'words': console.complete(payload['text'])}
            if payload['op'] == 'close':
                return {'ok': True}
            text = payload['text']
            reply = '\n'.join(f'line {i}' for i in range(40)) if text == 'show long' else console.line(text)
            return {'ok': True, 'reply': reply, 'prompt': console.prompt(), 'closed': False}
        window = ConsoleWindow(root, 'lab-1', 'R1', request=request)

        def settle():
            for _ in range(200):
                root.update()
                if not window.busy:
                    break
                time.sleep(.01)
            root.update()

        def type_line(text):
            window.set_typed(text)
            window.submit()
            settle()
        self.assertIn('Press RETURN to get started!', window.text.get('1.0', 'end'))
        window.submit()  # Return: the console starts
        settle()
        self.assertEqual(window.text.get('1.0', 'end').strip(), 'R1>')
        type_line('en')
        self.assertTrue(window.text.get('1.0', 'end').rstrip().endswith('R1#'))
        window.set_typed('show ip b')
        window.complete()
        settle()
        self.assertEqual(window.typed(), 'show ip bgp ')
        window.set_typed('show ip')
        window.help()  # « ? »: the help, then the prompt and the same line again
        settle()
        self.assertEqual(window.typed(), 'show ip')
        self.assertIn('reply to show ip?', window.text.get('1.0', 'end'))
        window.set_typed('')
        window.recall(-1)
        self.assertEqual(window.typed(), 'en')
        type_line('show long')
        self.assertIsNotNone(window.paging)
        self.assertTrue(window.text.get('1.0', 'end').rstrip().endswith('--More--'))
        window.page('Return')
        self.assertIn('line 24', window.text.get('1.0', 'end'))
        window.page('space')
        self.assertIn('line 39', window.text.get('1.0', 'end'))
        self.assertIsNone(window.paging)
        self.assertTrue(window.text.get('1.0', 'end').rstrip().endswith('R1#'))
        window.close()

if __name__ == '__main__':
    unittest.main()
