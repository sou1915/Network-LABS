"""Own one cgroup-v2 subtree per authenticated CLI shell."""
from pathlib import Path
import time
import uuid

from .runtime import RuntimeFailure
from .spec import identifier, prefix

CGROUP_ROOT = Path('/sys/fs/cgroup')


def session_parent(manager, source):
    identifier(source)
    return CGROUP_ROOT / 'network-labs' / prefix(manager.read()['spec']) / source


class SessionGroup:
    def __init__(self, manager, source):
        self.name = 'aaa-' + uuid.uuid4().hex
        self.path = session_parent(manager, source) / self.name
        self.closed = False

    def __enter__(self):
        if not (CGROUP_ROOT / 'cgroup.controllers').is_file():
            raise RuntimeFailure('RADIUS login requires cgroup v2 session control.')
        try:
            self.path.mkdir(mode=0o700)
        except OSError as error:
            raise RuntimeFailure('RADIUS login session cgroup unavailable; no shell launched.') from error
        try:
            if not (self.path / 'cgroup.kill').is_file():
                raise RuntimeFailure('RADIUS login requires cgroup.kill; no shell launched.')
            # Exercise the kill interface on the new, empty subtree before
            # permitting a process to enter it (threaded/unsupported groups fail).
            (self.path / 'cgroup.kill').write_text('1')
        except (OSError, RuntimeFailure) as error:
            try: self.path.rmdir()
            except OSError: pass
            raise RuntimeFailure('RADIUS login session control unavailable; no shell launched.') from error
        return self

    def __exit__(self, *_):
        try:
            (self.path / 'cgroup.kill').write_text('1')
            deadline = time.monotonic() + 2
            while True:
                events = dict(line.split() for line in (self.path / 'cgroup.events').read_text().splitlines())
                if events.get('populated') == '0': break
                if time.monotonic() >= deadline:
                    raise RuntimeFailure('RADIUS session cleanup did not complete; session cgroup retained.')
                time.sleep(.05)
            self.path.rmdir()
            self.closed = True
        except (OSError, ValueError) as error:
            raise RuntimeFailure('RADIUS session cleanup unavailable; session cgroup retained.') from error
        return False


def shell_args(name, terminal):
    # Refuse to read user commands if the runtime ignored --cgroup. The
    # namespace-relative prefix can vary; the final generated component cannot.
    guard = ('case "$(/bin/busybox cat /proc/self/cgroup)" in '
             '0::*/"$1") shift; exec "$@";; *) exit 125;; esac')
    return ['/bin/busybox', 'sh', '-c', guard, 'network-labs-session', name,
            '/bin/busybox', 'sh', *(['-i'] if terminal else [])]
