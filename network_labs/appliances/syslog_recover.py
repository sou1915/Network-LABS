"""Explicit restart of a dead disk-queue sender; never signal a live process."""
import re
import time
from .runtime import RuntimeFailure
from .syslog_forward import BINARY,PID,command,start


# Runs inside the selected owned container, so /proc is its PID namespace.
# A second census and inode/PID comparison precede stale PID-file removal.
CHECK_DEAD=r'''set -eu
pid_file=$1
sender_binary=$2
cleanup=$3
expected=$4
fail() { echo "$1" >&2; exit 1; }
read_pid() {
 [ ! -L "$pid_file" ] || fail 'Sender PID file must not be a symlink.'
 if [ ! -e "$pid_file" ]; then printf none; return; fi
 [ -f "$pid_file" ] || fail 'Sender PID file must be regular.'
 before=$(/bin/busybox stat -c '%d:%i' "$pid_file")
 value=$(/bin/busybox head -c 65 "$pid_file")
 [ ${#value} -le 64 ] || fail 'Invalid sender PID file.'
 case "$value" in ''|*[!0-9]*|0*) fail 'Invalid sender PID file.';; esac
 [ ${#value} -le 10 ] && [ "$value" -le 2147483647 ] || fail 'Invalid sender PID file.'
 after=$(/bin/busybox stat -c '%d:%i' "$pid_file")
 [ "$before" = "$after" ] || fail 'Sender PID file changed during observation.'
 printf '%s:%s' "$value" "$before"
}
process_state() {
 entry=$1
 if text=$(/bin/busybox head -c 4097 "$entry/stat" 2>/dev/null); then
  [ ${#text} -le 4096 ] || fail 'Process observation exceeded its bound.'
  fields=${text##*) }
  [ "$fields" != "$text" ] || fail 'Invalid process observation.'
  state=${fields%% *}
  case "$state" in R|S|D|T|t|I|Z|X|x|K|W|P) printf '%s' "$state";; *) fail 'Unknown process state.';; esac
 else
  [ ! -d "$entry" ] || fail 'Process state unavailable.'
  printf gone
 fi
}
snapshot=$(read_pid)
old_pid=${snapshot%%:*}
if [ "$old_pid" != none ]; then
 state=$(process_state "/proc/$old_pid")
 case "$state" in gone|Z|X|x) :;; *) fail 'A live PID owner exists; sender recovery refused.';; esac
fi
count=0
for process in /proc/[0-9]*; do
 count=$((count+1))
 [ "$count" -le 128 ] || fail 'Process census exceeded its bound.'
 state=$(process_state "$process")
 case "$state" in gone|Z|X|x) continue;; esac
 if executable=$(/bin/busybox readlink "$process/exe" 2>/dev/null); then
  case "$executable" in "$sender_binary"|"$sender_binary (deleted)") fail 'A live rsyslog process exists; sender recovery refused.';; esac
 else
  state=$(process_state "$process")
  case "$state" in gone|Z|X|x) continue;; *) fail 'Process identity unavailable.';; esac
 fi
done
if [ "$cleanup" = yes ]; then
 [ "$snapshot" = "$expected" ] && [ "$(read_pid)" = "$snapshot" ] || fail 'Sender PID file changed before recovery.'
 if [ "$old_pid" != none ]; then
  state=$(process_state "/proc/$old_pid")
  case "$state" in gone|Z|X|x) :;; *) fail 'PID owner became live; recovery refused.';; esac
  /bin/busybox rm -- "$pid_file"
 fi
fi
printf '%s\n' "$snapshot"
'''


def _dead(manager,node,cleanup=False,snapshot='none'):
    result=manager.crun('exec',node['name'],'/bin/busybox','sh','-c',CHECK_DEAD,'syslog-recovery',
                        PID,BINARY,'yes' if cleanup else 'no',snapshot,check=False,timeout=5)
    value=result.stdout.strip()
    if result.returncode or not re.fullmatch(r'none|[1-9][0-9]{0,9}:[0-9]+:[0-9]+',value):
        raise RuntimeFailure('Syslog sender recovery refused: '+(result.stderr.strip()[-512:] or 'Dead-process evidence unavailable.'))
    return value


def recover(manager,name):
    """Caller holds the lab lock. Start only; no signals or queue rewriting."""
    manager.state=None  # Read the latest state after a separate CLI acquired the lock.
    state=manager.read()
    if state['phase']!='running' or 'pending_spec' in state or 'pending_node' in state:
        raise RuntimeFailure('Syslog sender recovery requires a running lab without pending configuration.')
    node=next((n for n in state['spec']['nodes'] if n['name']==name),None)
    if node is None or node['runtime']!='oci' or not (node.get('management') or {}).get('syslog_disk_queue'):
        raise ValueError('Syslog sender recovery requires an existing opted-in disk-queue OCI sender.')
    from .management import observe
    if not observe(manager,node)['configuration_verified']:
        raise RuntimeFailure('Syslog sender configuration, identity or spool differs; recovery refused.')
    snapshot=_dead(manager,node)
    from .syslog_tls import paired_nodes,preflight as tls_preflight,preflight_pair
    pair=paired_nodes(state['spec'])
    if pair is not None:
        for peer in pair:tls_preflight(peer)
        preflight_pair(state['spec'])
    if _dead(manager,node,True,snapshot)!=snapshot:
        raise RuntimeFailure('Syslog sender PID evidence changed; recovery refused.')
    start(manager,node)
    until=time.monotonic()+8
    while time.monotonic()<until:
        result=manager.crun('exec',name,'/bin/busybox','head','-c','65',PID,check=False,timeout=3)
        text=result.stdout.strip()
        if result.returncode==0 and re.fullmatch(r'[1-9][0-9]{0,9}',text) and int(text)<=2147483647:
            pid=int(text)
            argv=manager.crun('exec',name,'/bin/busybox','head','-c','4097','/proc/'+text+'/cmdline',check=False,timeout=3)
            stat=manager.crun('exec',name,'/bin/busybox','head','-c','4097','/proc/'+text+'/stat',check=False,timeout=3)
            fields=stat.stdout.rsplit(')',1)[-1].split()
            if (argv.returncode==0 and argv.stdout=='\0'.join(command())+'\0' and stat.returncode==0 and
                    0<len(stat.stdout)<=4096 and fields and fields[0] not in ('Z','X','x')):
                again=manager.crun('exec',name,'/bin/busybox','head','-c','65',PID,check=False,timeout=3)
                if again.returncode==0 and again.stdout.strip()==text:
                    return {'status':'started','lab':manager.name,'node':name,'pid':pid,
                            'previous_pid':None if snapshot=='none' else int(snapshot.split(':')[0]),
                            'configuration_changed':False,
                            'scope':'Observed new sender PID/argv in the same owned node. No signals, queue rewrite, local-log replay or delivery verdict; lab stop still removes its spool.'}
        time.sleep(.05)
    raise RuntimeFailure('Sender start requested but live PID/argv evidence did not become ready; inspect the node before retrying.')
