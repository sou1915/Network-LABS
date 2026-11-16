"""Node-local Unix input and TCP/TLS output with opt-in disk action queue."""
import subprocess
from pathlib import Path
from .syslog_server import BINARY, MODULES

CONFIG = '/lab/syslog-forward.conf'
PID = '/run/rsyslog-forward.pid'
SPOOL='/var/spool/network-labs-syslog'
REQUIRED_MODULES = ('imuxsock.so', 'lmnet.so', 'lmnetstrms.so', 'lmnsd_ptcp.so', 'lmtcpclt.so')


def enabled(node):
    return (node.get('management') or {}).get('syslog_transport', 'udp') in ('tcp', 'tls')


def command():
    return [BINARY, '-n', '-i', PID, '-M', MODULES, '-f', CONFIG]


def preflight(node):
    if not (node.get('management') or {}).get('syslog_disk_queue'):return
    from .runtime import RuntimeFailure
    path=Path(node['rootfs'])/SPOOL.lstrip('/')
    if path.exists() or path.is_symlink():
        raise RuntimeFailure(node['name']+': Disk-queue images must not contain an imported syslog spool; use a clean base image.')


def files(node):
    remote = node['management']['syslog_remote']
    tls = node['management'].get('syslog_transport') == 'tls'
    from .syslog_tls import global_options
    driver = ('StreamDriver="gtls" StreamDriverMode="1" StreamDriverAuthMode="x509/name" StreamDriverPermittedPeers="' + node['management']['syslog_tls']['peer'] + '" StreamDriver.CheckExtendedKeyPurpose="on" StreamDriver.PrioritizeSAN="on" gnutlsPriorityString="NORMAL:-VERS-ALL:+VERS-TLS1.2:+VERS-TLS1.3"') if tls else 'StreamDriver="ptcp"'
    queue=(['         queue.type="Disk" queue.filename="forward" queue.spoolDirectory="'+SPOOL+'"',
            '         queue.maxDiskSpace="1m" queue.maxFileSize="64k"',
            '         queue.checkpointInterval="1" queue.syncQueueFiles="on"',
            '         queue.workerThreads="1" queue.dequeueBatchSize="1"',
            '         queue.timeoutEnqueue="0" queue.saveOnShutdown="on")']
           if node['management'].get('syslog_disk_queue') else
           ['         queue.type="FixedArray" queue.size="256" queue.workerThreads="1" queue.dequeueBatchSize="1"',
            '         queue.timeoutEnqueue="0" queue.saveOnShutdown="off")'])
    config = '\n'.join([
        *(['$umask 0077'] if node['management'].get('syslog_disk_queue') else []),
        'global(workDirectory="/run" net.enableDNS="off" maxMessageSize="1k"' + (global_options() if tls else '') + ')',
        'main_queue(queue.type="FixedArray" queue.size="256" queue.workerThreads="1" queue.dequeueBatchSize="1" queue.timeoutEnqueue="0")',
        'module(load="imuxsock" SysSock.Use="off")',
        'template(name="NetworkLabsLocal" type="string" string="%rawmsg%\\n")',
        'ruleset(name="NetworkLabsForward") {',
        '  action(type="omfile" file="/run/messages" template="NetworkLabsLocal"',
        '         fileCreateMode="0600" flushOnTXEnd="on" rotation.sizeLimit="65536"',
        '         rotation.sizeLimitCommand="/bin/sh /lab/rotate-syslog-local.sh")',
        '  action(type="omfwd" target="' + remote + '" port="' + ('6514' if tls else '514') + '" protocol="tcp"',
        '         TCP_Framing="octet-counted" ' + driver + ' template="RSYSLOG_SyslogProtocol23Format"',
        '         action.resumeRetryCount="-1" action.resumeInterval="1" action.resumeIntervalMax="5"',
        '         action.reportSuspension="on" action.reportSuspensionContinuation="on"',
        *queue,
        '}',
        'input(type="imuxsock" Socket="/dev/log" CreatePath="off" RateLimit.Interval="0" Ruleset="NetworkLabsForward")',
        '',
    ])
    return {'syslog-forward.conf': config,
            'rotate-syslog-local.sh': '#!/bin/sh\nexec /bin/busybox mv -f /run/messages /run/messages.1\n'}


def start(manager, node):
    from .runtime import RuntimeFailure
    if node['management'].get('syslog_disk_queue'):
        manager.crun('exec',node['name'],'/bin/busybox','mkdir','-p',SPOOL)
        if manager.crun('exec',node['name'],'/bin/busybox','test','-L',SPOOL,check=False).returncode==0:
            raise RuntimeFailure(node['name']+': Syslog spool must not be a symlink.')
        manager.crun('exec',node['name'],'/bin/busybox','chown','0:0',SPOOL)
        manager.crun('exec',node['name'],'/bin/busybox','chmod','700',SPOOL)
    result = manager.crun('exec', node['name'], BINARY, '-N1', '-M', MODULES, '-f', CONFIG, check=False, timeout=5)
    if result.returncode:
        raise RuntimeFailure(node['name'] + ': TCP syslog forwarding configuration rejected: ' + (result.stdout + result.stderr)[-2048:])
    manager.crun('exec', '--detach', node['name'], *command(), log=manager.directory / node['name'] / 'syslog.log')


def observe_spool(manager,node):
    if not (node.get('management') or {}).get('syslog_disk_queue'):return None
    from .runtime import RuntimeFailure
    verified=False
    try:
        link=manager.crun('exec',node['name'],'/bin/busybox','test','-L',SPOOL,check=False,timeout=3)
        directory=manager.crun('exec',node['name'],'/bin/busybox','test','-d',SPOOL,check=False,timeout=3)
        mode=manager.crun('exec',node['name'],'/bin/busybox','stat','-c','%a:%u:%g',SPOOL,check=False,timeout=3)
        verified=link.returncode==1 and directory.returncode==0 and mode.returncode==0 and mode.stdout=='700:0:0\n'
    except (OSError,ValueError,RuntimeFailure,subprocess.TimeoutExpired):pass
    return {'configuration_verified':verified,'storage':'owned node overlay','path':SPOOL,
            'scope':'Directory type/ownership/mode only; no queue content, depth, fsync, daemon liveness or delivery verdict. Sender process restart only; lab stop/recreation removes this spool.'}
