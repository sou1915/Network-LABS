"""Node-local Unix syslog input and plain TCP output with volatile bounded queues."""
from .syslog_server import BINARY, MODULES

CONFIG = '/lab/syslog-forward.conf'
PID = '/run/rsyslog-forward.pid'
REQUIRED_MODULES = ('imuxsock.so', 'lmnet.so', 'lmnetstrms.so', 'lmnsd_ptcp.so', 'lmtcpclt.so')


def enabled(node):
    return (node.get('management') or {}).get('syslog_transport', 'udp') in ('tcp', 'tls')


def command():
    return [BINARY, '-n', '-i', PID, '-M', MODULES, '-f', CONFIG]


def files(node):
    remote = node['management']['syslog_remote']
    tls = node['management'].get('syslog_transport') == 'tls'
    from .syslog_tls import global_options
    driver = ('StreamDriver="gtls" StreamDriverMode="1" StreamDriverAuthMode="x509/name" StreamDriverPermittedPeers="' + node['management']['syslog_tls']['peer'] + '" StreamDriver.CheckExtendedKeyPurpose="on" StreamDriver.PrioritizeSAN="on" gnutlsPriorityString="NORMAL:-VERS-ALL:+VERS-TLS1.2:+VERS-TLS1.3"') if tls else 'StreamDriver="ptcp"'
    config = '\n'.join([
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
        '         queue.type="FixedArray" queue.size="256" queue.workerThreads="1" queue.dequeueBatchSize="1"',
        '         queue.timeoutEnqueue="0" queue.saveOnShutdown="off")',
        '}',
        'input(type="imuxsock" Socket="/dev/log" CreatePath="off" RateLimit.Interval="0" Ruleset="NetworkLabsForward")',
        '',
    ])
    return {'syslog-forward.conf': config,
            'rotate-syslog-local.sh': '#!/bin/sh\nexec /bin/busybox mv -f /run/messages /run/messages.1\n'}


def start(manager, node):
    from .runtime import RuntimeFailure
    result = manager.crun('exec', node['name'], BINARY, '-N1', '-M', MODULES, '-f', CONFIG, check=False, timeout=5)
    if result.returncode:
        raise RuntimeFailure(node['name'] + ': TCP syslog forwarding configuration rejected: ' + (result.stdout + result.stderr)[-2048:])
    manager.crun('exec', '--detach', node['name'], *command(), log=manager.directory / node['name'] / 'syslog.log')
