"""Server-enforced, fixed SSH diagnostics; key authentication remains separate."""
import shlex

ACTIONS = {'identity': ['/bin/busybox', 'id'],
           'hostname': ['/bin/busybox', 'hostname'],
           'security-context': ['/bin/busybox', 'cat', '/proc/self/status']}
SCRIPT = '/lab/ssh-dispatch.sh'
KEY_OPTIONS = 'command="/bin/sh ' + SCRIPT + '",no-port-forwarding,no-agent-forwarding,no-pty'


def dispatcher(actions):
    # All command names and argv come from constants. Never evaluate the
    # command requested by the remote client, including subsystem requests.
    branches = '\n'.join('    ' + action + ') exec ' + shlex.join(ACTIONS[action]) + ';;'
                         for action in sorted(actions))
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
