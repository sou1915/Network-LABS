"""Server-enforced, fixed SSH diagnostics; key authentication remains separate."""
import shlex

ACTIONS = {'identity': ['/bin/busybox', 'id'],
           'hostname': ['/bin/busybox', 'hostname'],
           'security-context': ['/bin/busybox', 'cat', '/proc/self/status']}
SCRIPT = '/lab/ssh-dispatch.sh'
KEY_OPTIONS = 'command="/bin/sh ' + SCRIPT + '",no-port-forwarding,no-agent-forwarding,no-pty'


def dispatcher(actions, *, radius=False):
    # All command names and argv come from constants. Never evaluate the
    # command requested by the remote client, including subsystem requests.
    branches = '\n'.join('    ' + action + ') exec ' +
                         (shlex.join(['/bin/busybox', 'timeout', '-s', 'KILL', '15', '/bin/sh', '/lab/ssh-radius-client.sh', action])
                          if radius else shlex.join(ACTIONS[action])) + ';;' for action in sorted(actions))
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


def service_process(args):
    # crun exec starts from a host process, not the container init's privilege
    # context. Explicitly set NNP; Dropbear needs only these capabilities to
    # bind SSH and switch the authenticated child's UID/groups.
    caps = ['CAP_SETUID', 'CAP_SETGID', 'CAP_NET_BIND_SERVICE']
    return {'terminal': False, 'user': {'uid': 0, 'gid': 0, 'additionalGids': []},
            'args': list(args), 'cwd': '/', 'env': ['PATH=/bin:/usr/bin', 'HOME=/root'],
            'noNewPrivileges': True,
            'capabilities': {**{name: list(caps) for name in ('bounding', 'effective', 'permitted')},
                             'inheritable': [], 'ambient': []}}
