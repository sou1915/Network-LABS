"""Explicit offline Dropbear host identity; private bytes never enter declarations."""
import hashlib
import os
from pathlib import Path
import base64
import stat
import subprocess
import tempfile

KEY='/run/network-labs-ssh-host.key'


def selected(node):return (node.get('management') or {}).get('ssh_host_key')


def read_identity(path):
    """Validate a bounded private snapshot with the trusted host dropbearkey tool."""
    from .management import public_key
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as source:
        info=os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600:
            raise ValueError('SSH host key requires a regular non-symlink file with mode 0600.')
        raw=source.read(4097)
    if not raw or len(raw)>4096:raise ValueError('SSH host key must contain 1..4096 bytes.')
    # The temporary file contains the exact checked snapshot, not a second
    # read of a potentially replaced source. No private bytes in argv/logs.
    with tempfile.TemporaryDirectory(prefix='network-labs-host-key-') as folder:
        snapshot=Path(folder)/'key'
        out=os.open(snapshot,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(out,'wb') as target:target.write(raw)
        result=subprocess.run(['dropbearkey','-y','-f',str(snapshot)],capture_output=True,text=True,timeout=3)
    lines=[line.strip() for line in result.stdout.splitlines() if line.startswith('ssh-ed25519 ')]
    if result.returncode or len(lines)!=1:raise ValueError('A valid Dropbear ed25519 private host key is required.')
    return raw,public_key(lines[0])


def policy(path):
    path=Path(path).absolute()
    try:_,public=read_identity(path)
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        raise ValueError('An available mode-0600 Dropbear ed25519 host key and host dropbearkey tool are required.') from error
    return {'file':str(path),'public_key':public}


def validate(node):
    value=selected(node)
    if value is None:return
    from .spec import keys
    from .management import public_key
    keys(value,('file','public_key'),'SSH host key')
    path=value.get('file')
    if not isinstance(path,str) or not path.startswith('/') or '\x00' in path or len(path)>4096:
        raise ValueError('SSH host key requires an absolute offline file path.')
    value['public_key']=public_key(value.get('public_key'))
    config=node['management']
    if (not config['ssh_keys'] or config.get('ssh_actions') is None or
            config.get('telnet_password_hash') or config.get('telnet_radius') or config.get('syslog_remote') or
            any(node.get(k) for k in ('radius_server','syslog_server','snmp_agent','snmp_receiver','ntp_server','tftp_server','dns_server'))):
        raise ValueError('Pinned SSH host identity requires restricted SSH without Telnet, syslog or other server co-location.')
    if node.get('ipv6') and not (config.get('ssh_radius') and config.get('ssh_ipv6')):
        raise ValueError('Pinned IPv6 SSH requires the explicit dual-stack RADIUS diagnostic profile.')
    access=node.get('radius_access')
    if config.get('ssh_radius'):
        from .radius_access import allowed_actions
        users=access.get('user_roles',access.get('users')) if isinstance(access,dict) else None
        if not isinstance(access,dict) or not isinstance(users,dict) or not users:
            raise ValueError('Pinned SSH RADIUS identity requires explicit diagnostic or journaled-shell grants.')
        if 'shell' in config['ssh_actions']:
            if node.get('ipv6') or not all(access.get(k) for k in ('accounting','accounting_outbox','accounting_journal')):
                raise ValueError('Pinned SSH shell requires IPv4 and accounting with durable Stop outbox and session journal.')
        elif access.get('accounting') or any('shell' in allowed_actions(access,user) for user in users):
            raise ValueError('Pinned SSH diagnostics exclude shell grants or accounting; select the journaled IPv4 shell explicitly.')
    elif access:
        raise ValueError('Pinned SSH with RADIUS access requires explicit ssh_radius diagnostics.')


def preflight(node):
    value=selected(node)
    if value is None:return None
    from .runtime import RuntimeFailure
    try:
        raw,public=read_identity(value['file'])
        if public!=value['public_key']:raise ValueError('Offline SSH host identity differs from the declared public key.')
        return raw
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        raise RuntimeFailure(node['name']+': SSH host key preflight failed; check the declared public identity, mode 0600 and host dropbearkey tool.') from error


def install(manager,node,raw):
    # /run is a fresh owned-node tmpfs; refuse any unexpected path instead of
    # following/reusing it. The shell's stdin contains private bytes only.
    manager.crun('exec',node['name'],'/bin/sh','-c',
        'umask 077; set -C; /bin/busybox base64 -d > '+KEY,input_text=base64.b64encode(raw).decode('ascii'))
    manager.crun('exec',node['name'],'/bin/busybox','chown','0:0',KEY)
    manager.state.setdefault('ssh_host_key_hashes',{})[node['name']]=hashlib.sha256(raw).hexdigest()
    manager.save()


def observe(manager,node):
    if selected(node) is None:return None
    from .runtime import RuntimeFailure
    valid=False
    try:
        mode=manager.crun('exec',node['name'],'/bin/busybox','stat','-c','%F:%a:%u:%g',KEY,check=False,timeout=3)
        digest=manager.crun('exec',node['name'],'/bin/busybox','sha256sum',KEY,check=False,timeout=3)
        expected=manager.read().get('ssh_host_key_hashes',{}).get(node['name'])
        valid=(mode.returncode==0 and mode.stdout=='regular file:600:0:0\n' and digest.returncode==0 and
               bool(expected) and digest.stdout.split()[0]==expected)
    except (OSError,RuntimeFailure,subprocess.SubprocessError,IndexError):pass
    return {'configuration_verified':valid,'public_key':selected(node)['public_key'],
            'scope':'Private-file conformity only; real SSH clients must verify the declared public identity.'}
