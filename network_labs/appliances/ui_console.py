"""Native guest shell in a real terminal; credentials and PTY stay outside Tk."""
import subprocess
import sys
from .spec import identifier
from .ui_bridge import SOURCE

BOOTSTRAP='import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module("network_labs.appliances.ui_console",run_name="__main__")'
CLI_BOOTSTRAP='import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module("network_labs.appliances",run_name="__main__")'


def terminal_args(lab,node):
    identifier(lab);identifier(node)
    return [sys.executable,'-I','-c',BOOTSTRAP,str(SOURCE),lab,node]


def open_console(lab,node):
    identifier(lab);identifier(node)
    # Keep authentication and all guest I/O on the terminal's real descriptors.
    auth=subprocess.run(['sudo','-v'])
    if auth.returncode:return auth.returncode
    print(f'Console Linux native : {lab} / {node}. Taper exit pour fermer.',flush=True)
    return subprocess.run(['sudo','-n',sys.executable,'-I','-c',CLI_BOOTSTRAP,str(SOURCE),
                           'exec','--tty',lab,node,'--','/bin/sh']).returncode


def main(arguments=None):
    args=sys.argv[1:] if arguments is None else arguments
    if len(args)!=2:raise ValueError('Console requires a lab and one OCI node.')
    return open_console(*args)


if __name__=='__main__':
    try:code=main()
    except (OSError,ValueError) as error:print(str(error),file=sys.stderr);code=1
    if code and sys.stdin.isatty():input('Console non ouverte ou terminée en erreur. Entrée pour fermer…')
    raise SystemExit(code)
