"""Server-enforced, fixed SSH diagnostics; key authentication remains separate."""
import shlex

ACTIONS = {'identity': ['/bin/busybox', 'id'],
           'hostname': ['/bin/busybox', 'hostname'],
           'security-context': ['/bin/busybox', 'cat', '/proc/self/status']}
SCRIPT = '/lab/ssh-dispatch.sh'
RELAY_BINARY = '/usr/lib/network-labs/ssh-radius-client'
KEY_OPTIONS = 'command="/bin/sh ' + SCRIPT + '",no-port-forwarding,no-agent-forwarding,no-pty'


def dispatcher(actions, *, radius=False, session_seconds=300):
    # All command names and argv come from constants. Never evaluate the
    # command requested by the remote client, including subsystem requests.
    if 'shell' in actions and not radius: raise ValueError('SSH shell requires RADIUS.')
    branches = []
    for action in sorted(actions):
        label = "''|shell" if action == 'shell' else action
        duration = session_seconds + 15 if action == 'shell' else 15
        if radius and 'shell' in actions:
            args = [RELAY_BINARY, action, str(duration)]
        else:
            args = (['/bin/busybox', 'timeout', '-s', 'KILL', str(duration), '/bin/sh', '/lab/ssh-radius-client.sh', action]
                    if radius else ACTIONS[action])
        branches.append('    ' + label + ') exec ' + shlex.join(args) + ';;')
    branches = '\n'.join(branches)
    return '''#!/bin/sh
PATH=/bin:/usr/bin
LC_ALL=C
export PATH LC_ALL
unset ENV BASH_ENV CDPATH
case "${SSH_ORIGINAL_COMMAND-}" in
%s
    *) printf 'SSH action denied.\\n' >&2; exit 126;;
esac
''' % branches


def key_options(actions):
    return KEY_OPTIONS.removesuffix(',no-pty') if 'shell' in actions else KEY_OPTIONS


def service_process(args, *, terminal=False):
    # crun exec starts from a host process, not the container init's privilege
    # context. Explicitly set NNP; Dropbear needs only these capabilities to
    # bind SSH and switch the authenticated child's UID/groups.
    caps = ['CAP_SETUID', 'CAP_SETGID', 'CAP_NET_BIND_SERVICE']
    if terminal: caps += ['CAP_CHOWN', 'CAP_FOWNER', 'CAP_KILL']
    return {'terminal': False, 'user': {'uid': 0, 'gid': 0, 'additionalGids': []},
            'args': list(args), 'cwd': '/', 'env': ['PATH=/bin:/usr/bin', 'HOME=/root'],
            'noNewPrivileges': True,
            'capabilities': {**{name: list(caps) for name in ('bounding', 'effective', 'permitted')},
                             'inheritable': [], 'ambient': []}}
