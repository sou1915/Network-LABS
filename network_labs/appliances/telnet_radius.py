"""Explicit Telnet fixed diagnostics, with credentials checked by a host worker."""
from .radius_exec import execute, verified_accept
from .ssh_radius import managed_secret
from .ssh_access import ACTIONS

PORT = 814
LOGIN = '/usr/lib/network-labs/telnet-radius-login'


def dispatch(manager, source, action, username, password, *, audit=None):
    node = next(n for n in manager.read()['spec']['nodes'] if n['name'] == source)
    config = node.get('management') or {}
    if config.get('telnet_radius') is not True or action not in ACTIONS or action not in config.get('telnet_actions', []):
        if audit: audit('POLICY_DENIED')
        return None
    address, secret = managed_secret(manager.state['spec'], node)
    result = execute(manager, source, address, action=action, username=username, password=password, secret=secret, timeout=2)
    if (result.get('status') == 'passed' and result.get('executed') is True and result.get('returncode') == 0
            and verified_accept(result.get('authentication') or {})):
        output = result.get('stdout')
        if isinstance(output, str) and len(output.encode()) <= 4096:
            if audit: audit('VERIFIED_ACCEPT_EXECUTED')
            return output
    if audit: audit('AUTHENTICATION_OR_EXECUTION_DENIED')
    return None


def rootfs_assets(binary):
    from .dns_rootfs import assets
    return assets(binary, destination=LOGIN, identity='Network LABS Telnet RADIUS login 1',
                  version_check=lambda r: r.returncode == 0 and r.stdout == 'Network LABS Telnet RADIUS login 1\n')


def service_process(args):
    # telnetd allocates/owns PTYs and the helper drops all privileges before
    # reading credentials. CAP_SETPCAP is needed only to empty its bounding set.
    from .ssh_access import service_process as process
    result = process(args, terminal=True)
    for key in ('bounding', 'effective', 'permitted'):
        result['capabilities'][key].append('CAP_SETPCAP')
    return result
