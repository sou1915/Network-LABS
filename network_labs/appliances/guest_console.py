"""An interactive terminal for one running micro-VM, in its vendor's style, run as root in a real terminal window.

A modelled router gets its vendor's prompt and modes: show commands and ping read the running guest; configuration
lines are collected while in configuration mode and applied live when it ends (IOS/EOS « end », VRP « return »,
Junos and PAN-OS « commit », a FortiOS « config … end » block, a RouterOS line): static routes, gateway, OSPF,
BGP and access lists change on the running router, and a firewall policy on a firewall. A host gets a small shell
with BusyBox's own output: ping, ip addr, ip route. There is still no shell in the guest: every command is one of
the agent's typed requests. The lab lock is held only while a command runs, so the workbench keeps working.
"""
import ipaddress
import re

from . import command_catalogue, vendor_config, vendor_show


class Console:
    def __init__(self, lab, node, manager_factory=None):
        from .runtime import Manager
        self.lab, self.name = lab, node
        self.factory = manager_factory or Manager
        self.mode = 'exec'  # exec, enable, config
        self.pending = []
        self.depth = 0  # FortiOS « config » blocks
        self.context = None  # configuration sub-mode (IOS config-if, VRP interface…), from the command catalogue
        self.label = ''  # what the prompt shows for it on VRP (GE0/0/0, ospf-1, bgp…)
        self.spec = None
        node = self.node()
        self.syntax = vendor_config.dialect(node) if node['role'] != 'host' else None
        self.catalogue_node = node

    # ---- the running lab ----

    def manager(self):
        return self.factory(self.lab)

    def node(self, spec=None):
        if spec is None:
            with self.manager().locked() as manager:
                spec = manager.read()['spec']
        node = next((n for n in spec['nodes'] if n['name'] == self.name), None)
        if node is None:
            raise ValueError(f'Nœud inconnu dans le lab {self.lab} : {self.name}')
        if node['runtime'] != 'firecracker':
            raise ValueError('Ce terminal sert aux micro-VM ; un nœud OCI ouvre son shell Linux.')
        return node

    def observe(self):
        with self.manager().locked() as manager:
            manager.state = None
            return manager.observe_node(self.name)

    def ping(self, destination, count=5):
        with self.manager().locked() as manager:
            manager.state = None
            return manager.ping_node(self.name, destination, count=count)

    def query(self, operation):
        from .guest_startup import query
        with self.manager().locked() as manager:
            return query(manager.directory / self.name / 'guest.vsock', operation)

    # ---- prompt ----

    def prompt(self):
        name = self.name
        if self.syntax is None:
            return f'root@{name}:~# '
        if self.syntax in ('ios', 'eos'):
            config = f'{name}({self.context or "config"})#'
            return {'exec': f'{name}>', 'enable': f'{name}#', 'config': config}[self.mode] + ' '
        if self.syntax == 'vrp':
            return (f'[{name}{"-" + self.label if self.label else ""}]' if self.mode == 'config' else f'<{name}>') + ' '
        if self.syntax in ('junos', 'panos'):
            return f'admin@{name}' + ('# ' if self.mode == 'config' else '> ')
        return vendor_show.PROMPTS[self.syntax].format(name) + ' '

    # ---- one line ----

    def line(self, text):
        """The reply to one typed line ('' for none); raises EOFError to close the terminal."""
        command = ' '.join(text.split())
        low = command.lower()
        if not command:
            return ''
        if self.mode != 'config' and low in ('exit', 'quit', 'logout'):
            raise EOFError  # as on a real console: exit ends the session (disable goes back to user mode)
        if low in ('?', 'help'):
            return self.help()
        if low.startswith(('help ', '? ')):
            return self.topic_help(command.split(None, 1)[1])
        if command.endswith('?'):
            return self.context_help(command[:-1])
        if self.syntax is None:
            return self.host(command, low)
        if self.mode == 'config' or self.entering(low):
            return self.configure(command, low)
        if self.syntax in ('ios', 'eos') and low in ('enable', 'en'):
            self.mode = 'enable'
            return ''
        if self.syntax in ('ios', 'eos') and low == 'disable':
            self.mode = 'exec'
            return ''
        if re.fullmatch(r'(show|sh) (running-config|run|configuration|full-configuration)|display current-configuration'
                        r'|show config running|/export', low):
            node = self.node()
            with self.manager().locked() as manager:
                return vendor_config.render(manager.read()['spec'], node['name'])
        destination = vendor_show.ping_destination(self.node(), command)
        if destination:
            return vendor_show.ping_text(self.node(), self.ping(destination))
        return vendor_show.show(self.node(), self.observe(), command)

    def entering(self, low):
        """True when LOW starts configuration (and switches mode), for the dialects that have a configuration mode."""
        starts = {'ios': ('configure terminal', 'conf t', 'configure', 'config t'), 'eos': ('configure terminal', 'conf t', 'configure'),
                  'vrp': ('system-view', 'sys'), 'junos': ('configure', 'edit'), 'panos': ('configure',)}
        if low in starts.get(self.syntax, ()):
            if self.syntax in ('ios', 'eos') and self.mode == 'exec':
                raise ValueError('% Commande réservée au mode privilégié : taper enable d’abord.')
            self.mode, self.pending = 'config', []
            return True
        if self.syntax == 'fortios' and low.startswith('config '):
            self.mode, self.pending, self.depth = 'config', [], 0
            return True
        if self.syntax == 'routeros' and low.startswith('/') and not low.startswith(('/ping', '/export')) and ' print' not in low:
            self.mode, self.pending = 'config', []
            return True
        return False

    def configure(self, command, low):
        if low in ('configure terminal', 'conf t', 'configure', 'config t', 'system-view', 'sys', 'edit') and not self.pending:
            return self.banner()
        ends = {'ios': ('end',), 'eos': ('end',), 'vrp': ('return',), 'junos': ('commit', 'commit and-quit'),
                'panos': ('commit',)}
        if self.syntax in ('junos', 'panos') and low in ('exit', 'quit') and not self.pending:
            self.mode = 'exec'
            return ''
        if self.syntax in ('junos', 'panos') and low in ('exit', 'quit'):
            self.mode, self.pending = 'exec', []
            return 'Modifications non validées (commit) abandonnées.'
        leaving = (self.syntax in ('ios', 'eos') and low == 'exit') or (self.syntax == 'vrp' and low == 'quit')
        if leaving and self.context is not None:
            self.pending.append(command)  # the parser leaves its sub-mode too
            self.up()
            return ''
        if low in ends.get(self.syntax, ()) or leaving:
            reply = self.apply()
            self.context, self.label = None, ''
            if low != 'commit':
                self.mode = 'enable' if self.syntax in ('ios', 'eos') else 'exec'
            return reply
        self.pending.append(command)
        self.enter(command, low)
        if self.syntax == 'fortios':
            self.depth += 1 if low.startswith('config ') else -1 if low == 'end' else 0
            if self.depth == 0:
                self.mode = 'exec'
                return self.apply()
        if self.syntax == 'routeros':
            self.mode = 'exec'
            return self.apply()
        return ''

    def enter(self, command, low):
        """Follow the configuration sub-mode a line enters (or leaves, for a global IOS command typed in a sub-mode)."""
        mode = command_catalogue.context(self.syntax, low)
        if mode is None:
            if self.syntax in ('ios', 'eos') and self.context and command_catalogue.global_command(self.catalogue_node, low):
                self.context = None  # IOS leaves the sub-mode for a global command
            return
        self.context = mode
        if self.syntax == 'vrp':
            words = command.split()
            self.label = {'interface': words[-1], 'ospf': f'ospf-{words[1]}' if len(words) > 1 else 'ospf',
                          'ospf-area': f'{self.label}-area-0.0.0.0', 'bgp': 'bgp', 'bgp-af-ipv4': 'bgp-af-ipv4'}[mode]

    def up(self):
        """One sub-mode up: IOS exit returns to config, VRP quit to the parent view."""
        if self.syntax == 'vrp':
            parent = command_catalogue.VRP_PARENT.get(self.context)
            if parent in ('ospf', 'bgp'):
                self.context = parent
                self.label = self.label.rsplit('-area-', 1)[0] if parent == 'ospf' else 'bgp'
                return
        self.context, self.label = None, ''

    def catalogue_mode(self):
        """The command catalogue's name for where the terminal is."""
        if self.syntax is None:
            return 'shell'
        if self.syntax in ('ios', 'eos'):
            return (self.context or 'config') if self.mode == 'config' else 'exec'
        if self.syntax == 'vrp':
            return (self.context or 'system') if self.mode == 'config' else 'user'
        if self.syntax in ('junos', 'panos'):
            return 'configuration' if self.mode == 'config' else 'operational'
        return 'config' if self.mode == 'config' else 'exec'

    def banner(self):
        if self.syntax in ('ios', 'eos'):
            return 'Enter configuration commands, one per line.  End with end.'
        if self.syntax == 'vrp':
            return 'Enter system view, return user view with return command.'
        return '[edit]'

    def apply(self):
        """The collected lines, read in this vendor's syntax and applied to the running node."""
        lines, self.pending = self.pending, []
        if not lines:
            return ''
        with self.manager().locked() as manager:
            manager.state = None
            spec = manager.read()['spec']
            current = self.node(spec)
            try:
                changed = vendor_config.apply(spec, self.name, '\n'.join(lines))
            except ValueError as error:
                return '% ' + str(error).replace('\n', '\n% ')
            wanted = next(n for n in changed['nodes'] if n['name'] == self.name)
            if wanted == current:
                return 'Aucun changement.'
            if wanted.get('firewall') != current.get('firewall'):
                manager.configure_firewall(self.name, wanted['firewall'])
                current = dict(current, firewall=wanted['firewall'])
            if wanted != current:
                manager.state = None
                try:
                    manager.configure_routing(self.name, wanted)
                except ValueError as error:
                    return '% Pas applicable à chaud : ' + str(error) + ' (l’atelier : Enregistrer puis redémarrer).'
        return 'Appliqué au nœud en marche (relu dans la micro-VM).'

    # ---- host shell ----

    def host(self, command, low):
        words = low.split()
        if words[0] == 'ping' and len(words) >= 2:
            address = words[-1]
            ipaddress.IPv4Address(address)
            result = self.ping(address, count=4)
            lines = [f'PING {address} ({address}): 56 data bytes']
            for index, reply in enumerate(result['replies']):
                lines.append(f'64 bytes from {address}: seq={index} ttl=64' if reply['ok'] else f'Request timeout for seq={index}')
            answered = sum(r['ok'] for r in result['replies'])
            lines += ['', f'--- {address} ping statistics ---',
                      f'{len(result["replies"])} packets transmitted, {answered} packets received, '
                      f'{round(100 * (1 - answered / max(1, len(result["replies"]))))}% packet loss']
            return '\n'.join(lines)
        if words[:2] in (['ip', 'a'], ['ip', 'addr'], ['ip', 'address']) or words == ['ifconfig']:
            return self.query('addresses').rstrip()
        if words[:2] in (['ip', 'r'], ['ip', 'route']) or words == ['route']:
            return self.query('routes').rstrip()
        if words == ['hostname']:
            return self.name
        raise ValueError(f'{words[0]}: commande non disponible (ping, ip addr, ip route, hostname, exit).')

    def help(self):
        """The commands of the current mode, one per line, then how to get more."""
        mode = self.catalogue_mode()
        found = command_catalogue.help_for(self.catalogue_node, mode, '')
        syntax = command_catalogue.syntax_of(self.catalogue_node)
        lines = [f'Mode {mode} — {command_catalogue.MODES[syntax].get(mode, "")}'] if mode in command_catalogue.MODES[syntax] else []
        width = min(46, max((len(e['syntax']) for e in found), default=0))
        lines += [f'  {e["syntax"]:<{width}}  {e["help"]}' for e in found]
        topics = ', '.join(command_catalogue.topics(self.catalogue_node))
        lines += ['', f'« MOT ? » : les commandes qui commencent par MOT · « help SUJET » : un sujet avec exemples ({topics}) · '
                      'Tab complète les mots.']
        return '\n'.join(lines)

    def topic_help(self, text):
        """Every command of a topic (or matching words), with its mode and example."""
        wanted = text.strip().lower()
        found = [e for e in command_catalogue.entries(self.catalogue_node) if e['topic'].lower().startswith(wanted)]
        found = found or command_catalogue.search(self.catalogue_node, text)
        if not found:
            return '% Aucun sujet ni commande pour « ' + text.strip() + ' » ; sujets : ' + \
                ', '.join(command_catalogue.topics(self.catalogue_node))
        lines = []
        for entry in found:
            lines += [f'{entry["syntax"]}   [{entry["mode"]}]', f'    {entry["help"]}']
            lines += ['    ex. ' + ' ; '.join(entry['example'])]
        return '\n'.join(lines)

    def context_help(self, typed):
        """IOS-style « ? » after some words: the commands of this mode that start with them."""
        found = command_catalogue.help_for(self.catalogue_node, self.catalogue_mode(), typed)
        if not found:
            return '% Commande inconnue ici : « help » liste les commandes de ce mode.'
        width = min(46, max(len(e['syntax']) for e in found))
        return '\n'.join(f'  {e["syntax"]:<{width}}  {e["help"]}' for e in found)

    def complete(self, buffer):
        """Tab completion: the words that can follow BUFFER in this mode."""
        return command_catalogue.completions(self.catalogue_node, self.catalogue_mode(), buffer)

def run(lab, node, read=input, write=print, manager_factory=None):
    console = Console(lab, node, manager_factory)
    if read is input:
        _readline(console)
    title = vendor_config.TITLES.get(console.syntax, 'shell BusyBox de la micro-VM')
    write(f'Terminal de {node} · lab {lab} · {title}. « ? » : les commandes du mode · « help BGP » : un sujet · '
          'Tab : compléter · « exit » : fermer.')
    while True:
        try:
            text = read(console.prompt())
        except (EOFError, KeyboardInterrupt):
            write('')
            return 0
        try:
            reply = console.line(text)
        except EOFError:
            return 0
        except (ValueError, KeyError) as error:
            reply = '% ' + str(error)
        except Exception as error:  # the running lab can change under the terminal: say why, keep the prompt
            reply = f'% {type(error).__name__} : {error}'
        if reply:
            write(reply)


def _readline(console):
    """Tab completion from the command catalogue, where the terminal has readline (Linux)."""
    try:
        import readline
    except ImportError:
        return
    matches = []

    def complete(text, state):
        if state == 0:
            buffer = readline.get_line_buffer()[:readline.get_endidx()]
            matches[:] = [word + ' ' for word in console.complete(buffer)]
        return matches[state] if state < len(matches) else None

    readline.set_completer_delims(' ')
    readline.set_completer(complete)
    readline.parse_and_bind('tab: complete')
