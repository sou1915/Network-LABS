"""The node terminals of one running lab, served to the workbench: CLI windows inside the app, no password each time.

Started as root once (with the lab, from the same sudo prompt), it listens on a Unix socket that only the user
who started it can open (mode 0600, owned by them, checked again with SO_PEERCRED). Each request is one JSON line:
open a node's terminal, type one line, or ask for completions. Lines go to guest_console.Console, the same typed
terminal as before: vendor modes, show, ping and live configuration through the guest agent; never a shell. The
server leaves when the lab stops, or after four idle hours.
"""
import json
import os
from pathlib import Path
import socket
import struct
import threading
import time

from .spec import identifier

ROOT = Path('/run/network-labs/consoles')
LIMIT = 4096  # one request line
IDLE = 4 * 3600
SESSIONS = 64


def socket_path(uid, lab, root=None):
    identifier(lab)
    if type(uid) is not int or uid < 0:
        raise ValueError('uid')
    return Path(root or ROOT) / f'{uid}-{lab}.sock'


class Server:
    def __init__(self, lab, uid, root=None, console=None, alive=None):
        from . import guest_console
        self.lab, self.uid = lab, uid
        self.path = socket_path(uid, lab, root)
        self.console = console or (lambda node: guest_console.Console(lab, node))
        self.alive = alive or (lambda: _lab_running(lab))
        self.sessions = {}  # (session, node) -> Console
        self.lock = threading.Lock()
        self.last = time.monotonic()

    def bind(self):
        self.path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_socket()):
            raise ValueError(f'{self.path} is not a console socket.')
        # Bound and listening under a temporary name, then renamed: the socket appears only once it accepts, so a
        # terminal that finds it can connect at once.
        staging = self.path.with_name('.' + self.path.name + '.new')
        staging.unlink(missing_ok=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            listener.bind(str(staging))
        finally:
            os.umask(old)
        if os.geteuid() == 0:
            os.chown(staging, self.uid, -1)
        os.chmod(staging, 0o600)
        listener.listen(8)
        listener.settimeout(1)
        os.replace(staging, self.path)
        return listener

    def serve(self):
        listener = self.bind()
        try:
            while self.alive() and time.monotonic() - self.last < IDLE:
                try:
                    connection, _ = listener.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self.handle, args=(connection,), daemon=True).start()
        finally:
            listener.close()
            self.path.unlink(missing_ok=True)

    def handle(self, connection):
        with connection:
            connection.settimeout(120)
            try:
                if not self.allowed(connection):
                    return
                data = b''
                while b'\n' not in data and len(data) <= LIMIT:
                    chunk = connection.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                if len(data) > LIMIT or b'\n' not in data:
                    reply = {'ok': False, 'error': 'Requête invalide.'}
                else:
                    reply = self.answer(json.loads(data.split(b'\n', 1)[0]))
            except (ValueError, OSError) as error:
                reply = {'ok': False, 'error': str(error)}
            try:
                connection.sendall(json.dumps(reply, ensure_ascii=False).encode() + b'\n')
            except OSError:
                pass

    def allowed(self, connection):
        """Only the user who started the lab (or root) talks to its terminals."""
        try:
            credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i'))
        except OSError:
            return False
        _, uid, _ = struct.unpack('3i', credentials)
        return uid in (self.uid, 0)

    def answer(self, request):
        """{'op': 'ping' | 'open' | 'line' | 'complete' | 'close', 'session', 'node', 'text'} -> reply."""
        if not isinstance(request, dict) or request.get('op') not in ('ping', 'open', 'line', 'complete', 'close'):
            raise ValueError('Opération inconnue.')
        self.last = time.monotonic()
        if request['op'] == 'ping':
            return {'ok': True, 'lab': self.lab}
        session, node = request.get('session'), request.get('node')
        if not isinstance(session, str) or not 8 <= len(session) <= 64 or not session.isalnum():
            raise ValueError('Session invalide.')
        identifier(node)
        key = (session, node)
        if request['op'] == 'close':
            with self.lock:
                self.sessions.pop(key, None)
            return {'ok': True}
        console = self.session(key, fresh=request['op'] == 'open')
        if request['op'] == 'open':
            from .vendor_config import TITLES
            title = TITLES.get(console.syntax, 'shell BusyBox de la micro-VM')
            greeting = console.greeting() if hasattr(console, 'greeting') else ''
            return {'ok': True, 'prompt': console.prompt(), 'greeting': greeting,
                    'banner': f'{node} · {title}. « ? » : les commandes du mode · « help SUJET » · Tab : compléter.'}
        text = request.get('text')
        if not isinstance(text, str) or len(text) > 1024 or '\n' in text:
            raise ValueError('Ligne invalide.')
        if request['op'] == 'complete':
            return {'ok': True, 'words': console.complete(text)}
        try:
            reply, closed = console.line(text), False
        except EOFError:
            reply, closed = '', True
            with self.lock:
                self.sessions.pop(key, None)
        except (ValueError, KeyError) as error:
            reply, closed = '% ' + str(error), False
        except Exception as error:  # the running lab can change under the terminal: say why, keep the prompt
            reply, closed = f'% {type(error).__name__} : {error}', False
        return {'ok': True, 'reply': reply, 'prompt': '' if closed else console.prompt(), 'closed': closed}

    def session(self, key, fresh=False):
        with self.lock:
            if fresh or key not in self.sessions:
                if len(self.sessions) >= SESSIONS:
                    self.sessions.pop(next(iter(self.sessions)))
                self.sessions[key] = self.console(key[1])
            return self.sessions[key]


def _lab_running(lab):
    from .runtime import Manager
    return Manager(lab).directory.exists()


def request(lab, payload, uid=None, root=None, timeout=120):
    """The workbench side: one request to the lab's console server, its JSON reply."""
    path = socket_path(os.getuid() if uid is None else uid, lab, root)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(path))
        client.sendall(json.dumps(payload, ensure_ascii=False).encode() + b'\n')
        data = b''
        while b'\n' not in data:
            chunk = client.recv(65536)
            if not chunk:
                break
            data += chunk
            if len(data) > 8 * 1024 * 1024:
                raise ValueError('Réponse trop longue.')
    reply = json.loads(data.split(b'\n', 1)[0])
    if not isinstance(reply, dict) or type(reply.get('ok')) is not bool:
        raise ValueError('Réponse invalide du serveur de consoles.')
    return reply


def available(lab, uid=None, root=None):
    try:
        return request(lab, {'op': 'ping'}, uid, root, timeout=2).get('lab') == lab
    except (OSError, ValueError):
        return False


def main(arguments):
    """console-server LAB UID: run as root, until the lab stops."""
    lab, uid = arguments[0], int(arguments[1])
    if os.geteuid() != 0:
        raise ValueError('Le serveur de consoles démarre avec le lab (root).')
    Server(lab, uid).serve()
    return 0
