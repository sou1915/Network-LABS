"""Bounded native PCAP entry; authentication and result stay in a terminal."""
from pathlib import Path
import subprocess
import sys
from .capture import limits
from .spec import identifier
from .ui_bridge import SOURCE
from .ui_console import CLI_BOOTSTRAP

BOOTSTRAP='import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module("network_labs.appliances.ui_capture",run_name="__main__")'


def validate(lab,node,interface,output,seconds,packets,expression):
    identifier(lab);identifier(node)
    if not isinstance(interface,str) or not interface or len(interface)>15 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-' for c in interface):
        raise ValueError('Interface de capture invalide.')
    limits(seconds,packets,2048,expression)
    path=Path(output)
    if not path.is_absolute() or not path.parent.is_dir():raise ValueError('Choisir un fichier PCAP absolu dans un dossier existant.')
    if path.exists() or path.is_symlink():raise ValueError('Le fichier PCAP existe déjà ; choisir un nouveau nom.')
    return str(path)


def terminal_args(lab,node,interface,output,seconds,packets,expression):
    output=validate(lab,node,interface,output,seconds,packets,expression)
    return [sys.executable,'-I','-c',BOOTSTRAP,str(SOURCE),lab,node,interface,output,str(seconds),str(packets),expression]


def record(lab,node,interface,output,seconds,packets,expression):
    output=validate(lab,node,interface,output,seconds,packets,expression)
    auth=subprocess.run(['sudo','-v'])
    if auth.returncode:return auth.returncode
    print(f'Capture native : {lab} / {node} / {interface}. Résultat et fichier confirmés ci-dessous après la fin.',flush=True)
    return subprocess.run(['sudo','-n',sys.executable,'-I','-c',CLI_BOOTSTRAP,str(SOURCE),'--json','capture',lab,node,interface,
                           '--output',output,'--seconds',str(seconds),'--packets',str(packets),'--snaplen','2048','--filter='+expression]).returncode


def main(arguments=None):
    args=sys.argv[1:] if arguments is None else arguments
    if len(args)!=7:raise ValueError('Capture requires lab, node, interface, output, duration, packets and BPF.')
    return record(*args[:4],int(args[4]),int(args[5]),args[6])


if __name__=='__main__':
    try:code=main()
    except (OSError,ValueError) as error:print(str(error),file=sys.stderr);code=1
    if sys.stdin.isatty():input('Consulter le résultat de capture ci-dessus. Entrée pour fermer…')
    raise SystemExit(code)
