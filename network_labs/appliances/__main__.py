"""Native lab commands. No display needed and no implicit host changes."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from .catalog import capabilities
from .runtime import Manager, RuntimeFailure, plan, static_busybox_rootfs
from .spec import example, load


def main(arguments=None):
    parser = argparse.ArgumentParser(description='Network LABS native experimental appliances')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor', help='Read-only host dependency report; not a boot test.')
    sample = commands.add_parser('example', help='Print a three-node OCI manifest; no host changes.')
    sample.add_argument('--rootfs', type=Path, required=True)
    rootfs = commands.add_parser('rootfs', help='Build an offline minimal rootfs from trusted static BusyBox.')
    rootfs.add_argument('--busybox', type=Path, required=True)
    rootfs.add_argument('--output', type=Path, required=True)
    for command in ('plan', 'start'):
        item = commands.add_parser(command)
        item.add_argument('manifest', type=Path)
    for command in ('status', 'stop'):
        item = commands.add_parser(command)
        item.add_argument('name')
    execute = commands.add_parser('exec', help='Execute real commands in an OCI node, not the simulator CLI.')
    execute.add_argument('--tty', action='store_true')
    execute.add_argument('name'); execute.add_argument('node')
    execute.add_argument('argv', nargs=argparse.REMAINDER)
    args = parser.parse_args(arguments)
    try:
        if args.command == 'doctor':
            result = capabilities()
        elif args.command == 'example':
            result = example(args.rootfs)
        elif args.command == 'rootfs':
            result = {'rootfs': str(static_busybox_rootfs(args.busybox, args.output))}
        elif args.command == 'plan':
            result = plan(load(args.manifest))
        else:
            spec = load(args.manifest) if args.command == 'start' else None
            with Manager(spec['name'] if spec else args.name).locked() as manager:
                if args.command == 'start':
                    manager.start(spec); result = manager.status()
                elif args.command == 'stop':
                    manager.stop(); result = {'stopped': args.name}
                elif args.command == 'exec':
                    command = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
                    return manager.execute(args.node, command, tty=args.tty)
                else:
                    result = manager.status()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (RuntimeFailure, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print('Native lab: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
