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
        self.base = None  # IOS: the lab when « configure terminal » was typed; the block typed since applies onto it
        node = self.node()
        self.syntax = vendor_config.dialect(node) if node['role'] != 'host' else None
        self.catalogue_node = node
        from . import ios_store
        self.hostname = ios_store.hostname(node)
        self.typed, self.clock_offset, self.started = [], 0.0, __import__('time').monotonic()
        self.attempts = 0
        # A console line with « login » and a password asks for it first, as IOS does.
        self.awaiting = 'login' if self.syntax in ('ios', 'eos') and ios_store.console_login(node) else None

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

    def dhcp_bindings(self):
        """[{'address', 'mac'}] this node's DHCP server has given: the guest's lease file, or the model's leases."""
        node = self.node()
        if not node.get('dhcp_server'):
            return []
        with self.manager().locked() as manager:
            if hasattr(manager, 'query_node'):  # the lab is stopped: the leases the network model gives
                from . import network_model
                from .dhcp import pool_network
                model = network_model.Model(manager.read()['spec'])
                return [{'address': str(lease.ip), 'mac': ''} for lease, _ in model.leases.values() if lease.ip in pool_network(node)]
            from .guest_startup import leases
            return leases(manager.directory / self.name / 'guest.vsock', node['dhcp_server']['interface'])

    def trace(self, destination):
        with self.manager().locked() as manager:
            manager.state = None
            return manager.trace_node(self.name, destination)

    def traceroute(self, syntax, command):
        """The reply to a traceroute / tracert line, or None when COMMAND is not one."""
        from . import trace
        matched, destination = trace.parse(syntax, command)
        if not matched:
            return None
        if destination is None:
            return trace.unknown(syntax)
        return trace.text(syntax, self.trace(destination), command)

    def query(self, operation):
        from .guest_startup import query
        with self.manager().locked() as manager:
            if hasattr(manager, 'query_node'):  # the project, while the lab is stopped (draft_lab.DraftLab)
                return manager.query_node(self.name, operation)
            return query(manager.directory / self.name / 'guest.vsock', operation)

    # ---- prompt ----

    def prompt(self):
        name = self.name
        if self.syntax is None:
            return f'root@{name}:~# '
        if self.syntax in ('ios', 'eos'):  # IOS types straight after the prompt, without a space
            if self.awaiting:
                return 'Password: '
            name = self.hostname
            shown = {'config-rip': 'config-router', 'config-eigrp': 'config-router'}.get(self.context, self.context)
            config = f'{name}({shown or "config"})#'
            return {'exec': f'{name}>', 'enable': f'{name}#', 'config': config}[self.mode]
        if self.syntax == 'vrp':
            return (f'[{name}{"-" + self.label if self.label else ""}]' if self.mode == 'config' else f'<{name}>') + ' '
        if self.syntax in ('junos', 'panos'):
            return f'admin@{name}' + ('# ' if self.mode == 'config' else '> ')
        return vendor_show.PROMPTS[self.syntax].format(name) + ' '

    # ---- one line ----

    def line(self, text):
        """The reply to one typed line ('' for none); raises EOFError to close the terminal."""
        if self.syntax in ('ios', 'eos'):
            return self.ios_line(text)
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
        if self.mode == 'config' and low.startswith('do '):
            # « do show … » from configuration, as on IOS, which has applied every line typed so far.
            applied = self.apply(quiet=True) if self.syntax in ('ios', 'eos', 'vrp') else ''
            shown = self.execute(command[3:].strip())
            return '\n'.join(part for part in (applied, shown) if part)
        if self.mode == 'config' and self.syntax in ('ios', 'eos', 'vrp'):
            command = command_catalogue.expand(self.catalogue_node, command)
            low = command.lower()
        if self.mode == 'config' or self.entering(low):
            return self.configure(command, low)
        return self.execute(command)

    # ---- Cisco IOS (and Arista EOS), as Packet Tracer and the real CLI behave ----

    def greeting(self):
        """What the console shows before its first prompt: the banner motd, then the login (as IOS)."""
        from . import ios_store
        if self.syntax not in ('ios', 'eos'):
            return ''
        node = self.node()
        parts = [ios_store.banner(node)] if ios_store.banner(node) else []
        if self.awaiting == 'login':
            parts.append('\nUser Access Verification\n')
        return '\n'.join(parts)

    def password(self, typed):
        """The line typed at « Password: » (console login or enable): three tries, as IOS."""
        from . import ios_store
        node = self.node()
        good = typed == ios_store.console_login(node) if self.awaiting == 'login' else bool(ios_store.check_enable(node, typed))
        if good:
            self.mode = 'enable' if self.awaiting == 'enable' else self.mode
            self.awaiting, self.attempts = None, 0
            return ''
        self.attempts += 1
        if self.attempts < 3:
            return ''
        failed, self.awaiting, self.attempts = self.awaiting, None, 0
        if failed == 'login':
            self.awaiting = 'login'
            return '% Bad passwords'
        return '% Bad secrets'

    def node_now(self):
        return self.node()

    def spec_now(self):
        with self.manager().locked() as manager:
            return manager.read()['spec']

    def uptime(self):
        minutes = int((__import__('time').monotonic() - self.started) // 60)
        return f'{minutes} minute' + ('s' if minutes != 1 else '')

    def store_startup(self, text):
        """« copy running-config startup-config »: the configuration kept in the device's stored IOS lines."""
        import copy
        from . import ios_store
        with self.manager().locked() as manager:
            manager.state = None
            spec = manager.read()['spec']
            wanted = copy.deepcopy(self.node(spec))
            current = ios_store.config(wanted)
            current['startup'] = text
            wanted['cli_config'] = current
            ios_store.validate(wanted)
            return self.change(manager, spec, wanted)

    def ios_line(self, text):
        """One IOS line: « ? » help, IOS errors with the ^ marker, each configuration line applied at once."""
        if self.awaiting:
            return self.password(text)
        node, mode = self.catalogue_node, self.catalogue_mode()
        if text.strip() and not text.rstrip().endswith('?'):
            self.typed.append(' '.join(text.split()))
        if text.rstrip().endswith('?'):
            return command_catalogue.ios_help(node, mode, text.rstrip()[:-1])
        command = ' '.join(text.split())
        low = command.lower()
        if not command:
            return ''
        if low == 'help' or low.startswith('help '):
            return self.topic_help(command[5:]) if low.startswith('help ') else self.help()
        if self.mode != 'config':
            return self.ios_exec(command)
        if low.startswith('do '):
            return self.ios_exec(command[3:].strip(), from_config=True)
        command = command_catalogue.expand(node, command)
        low = command.lower()
        if low in ('end', 'exit') and (low == 'end' or self.context is None):
            reply = self.ios_apply(final=True)
            self.mode, self.context, self.pending, self.base = 'enable', None, [], None
            return '\n'.join(part for part in (reply, '%SYS-5-CONFIG_I: Configured from console by console') if part)
        if low == 'exit':
            self.pending.append(command)  # the parser leaves its sub-mode too
            self.context = None
            return ''
        status, detail = command_catalogue.ios_check(node, mode, command)
        if status == 'incomplete':
            return '% Incomplete command.'
        if status == 'ambiguous':
            return f'% Ambiguous command:  "{detail}"'
        if status == 'invalid' and not self.parses(command):
            return self.marker(detail)
        self.pending.append(command)
        self.enter(command, low)
        return self.ios_apply()

    def ios_exec(self, command, from_config=False):
        """User and privileged EXEC; « show … | include|exclude|begin|section TEXT » filters the output, as on IOS."""
        match = re.fullmatch(r'(.+?)\s*\|\s*(i|in|inc|incl|include|e|ex|exc|exclude|b|be|begin|s|se|sec|section)\s+(.+)', command,
                             re.IGNORECASE)
        if match:
            return _filter(self.ios_command(match[1], from_config), match[2].lower()[:1], match[3])
        return self.ios_command(command, from_config)

    def ios_command(self, command, from_config=False):
        node = self.catalogue_node
        low = command_catalogue.expand(node, command).lower()
        if low in ('exit', 'logout', 'quit') and not from_config:
            raise EOFError
        if low in ('enable', 'en'):
            from . import ios_store
            if not from_config and self.mode == 'exec' and ios_store.check_enable(self.node(), '') is not None:
                self.awaiting = 'enable'  # « Password: », as IOS asks when an enable secret or password is set
                return ''
            self.mode = 'enable' if not from_config else self.mode
            return ''
        if low == 'disable' and not from_config:
            self.mode = 'exec'
            return ''
        if low in ('configure terminal', 'conf t', 'config t', 'configure') and not from_config:
            if self.mode == 'exec':
                return self.marker(0)
            self.mode, self.pending, self.context = 'config', [], None
            with self.manager().locked() as manager:
                self.base = manager.read()['spec']
            return 'Enter configuration commands, one per line.  End with CNTL/Z.'
        if re.fullmatch(r'(write( memory)?|wr|copy running-config startup-config|copy run start|erase startup-config|write erase)',
                        low) and self.mode == 'exec' and not from_config:
            return self.marker(0)
        if re.fullmatch(r'(show|sh) (running-config|run)', low):
            return self.ios_running()
        from . import ios_exec
        extra = ios_exec.answer(self, low)
        if extra is not None:
            return extra
        traced = self.traceroute(self.syntax, low)
        if traced is not None:
            return traced
        destination = vendor_show.ping_destination(self.node(), low)
        if destination:
            return vendor_show.ping_text(self.node(), self.ping(destination))
        if low.split()[0] == 'show' or low.startswith('sh '):
            try:
                return vendor_show.show(self.node(), self.observe(), low)
            except ValueError as error:
                status, detail = command_catalogue.ios_check(node, 'exec', low)
                if status == 'incomplete':
                    return '% Incomplete command.'
                return self.marker(detail) if status == 'invalid' else '% ' + str(error)
        status, detail = command_catalogue.ios_check(node, 'exec', low)
        if status == 'incomplete':
            return '% Incomplete command.'
        if status == 'ambiguous':
            return f'% Ambiguous command:  "{detail}"'
        return (f'Translating "{command.split()[0]}"...domain server (255.255.255.255)\n'
                '% Unknown command or computer name, or unable to find computer address')

    def marker(self, position):
        """IOS's answer to a wrong word: a ^ under it (the line is shown just above, after the prompt)."""
        return ' ' * (len(self.prompt()) + (position or 0)) + "^\n% Invalid input detected at '^' marker."

    def parses(self, command):
        """Whether the vendor parser takes this line after the block typed so far (lines the catalogue omits)."""
        try:
            vendor_config.apply(self.base, self.name, '\n'.join(self.pending + [command]))
            return True
        except ValueError as error:
            return not str(error).startswith(f'Ligne {len(self.pending) + 1} :')

    def ios_apply(self, final=False):
        """Apply the block typed since « configure terminal » to the running device, as IOS applies each line.
        A block that is not complete yet (BGP without a neighbour…) waits for the next lines; at « end » it is said."""
        if not self.pending:
            return ''
        try:
            changed = vendor_config.apply(self.base, self.name, '\n'.join(self.pending))
        except ValueError as error:
            text = str(error)
            if text.startswith(f'Ligne {len(self.pending)} :'):
                self.pending.pop()
                return '% ' + text.split('\n', 1)[-1]
            return f'% {text} (pas encore appliqué)' if final else ''
        wanted = next(n for n in changed['nodes'] if n['name'] == self.name)
        with self.manager().locked() as manager:
            manager.state = None
            spec = manager.read()['spec']
            before = self.node(spec)
            reply = self.change(manager, spec, wanted)
        if reply.startswith('%'):
            return reply
        from . import ios_store
        self.hostname = ios_store.hostname(wanted)
        return self.ios_events(before, wanted, spec)

    def ios_events(self, before, after, spec):
        """The console messages IOS prints when a port goes up or down."""
        from .vendor_config import ios_name, port_names
        shown = port_names(after)
        cabled = {end[1] for link in spec['links'] for end in link if end[0] == self.name}
        lines = []
        for port in [*after['interfaces'], *(after.get('svis') or {})]:  # ports, then a switch's interface vlan
            name = ios_name(shown.get(port, port)) if self.syntax == 'ios' else shown.get(port, port)
            if port in (after.get('svis') or {}):
                cabled = cabled | ({port} if cabled else set())  # an SVI comes up with a connected port in its VLAN
            was, now = port in (before.get('shutdown') or []), port in (after.get('shutdown') or [])
            if was and not now:
                state = 'up' if port in cabled else 'down'
                lines.append(f'%LINK-5-CHANGED: Interface {name}, changed state to {state}')
                if port in cabled:
                    lines.append(f'%LINEPROTO-5-UPDOWN: Line protocol on Interface {name}, changed state to up')
            elif now and not was and not (port in (after.get('svis') or {}) and port not in (before.get('svis') or {})):
                # (a new interface vlan exists already shut on a Catalyst: nothing to report)
                lines += [f'%LINK-5-CHANGED: Interface {name}, changed state to administratively down',
                          f'%LINEPROTO-5-UPDOWN: Line protocol on Interface {name}, changed state to down']
        return '\n'.join(lines)

    def ios_running(self):
        """« show running-config » laid out as IOS prints it."""
        with self.manager().locked() as manager:
            body = vendor_config.render(manager.read()['spec'], self.name)
        lines = [line for line in body.splitlines() if not line.startswith(('! Network LABS', '! le nœud'))]
        while lines and lines[0] == '!':
            lines.pop(0)
        encrypted = any(line == 'service password-encryption' for line in lines)
        text = '\n'.join(['version 16.9', 'no service timestamps log datetime msec', 'no service timestamps debug datetime msec']
                         + ([] if encrypted else ['no service password-encryption']) + ['!'] + lines)
        return f'Building configuration...\n\nCurrent configuration : {len(text) + 1} bytes\n!\n{text}'

    def execute(self, command):
        """An exec-mode command: mode changes, the running configuration, ping or a show command."""
        low = command.lower()
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
        traced = self.traceroute(self.syntax, command)
        if traced is not None:
            return traced
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
            # The block just closed (an interface, a routing process…) takes effect now, as each line does on IOS.
            return self.apply(quiet=True) if self.context is None else ''
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
            context = 'config-if' if self.context == 'config-if-range' else self.context
            return (context or 'config') if self.mode == 'config' else 'exec'
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

    def apply(self, quiet=False):
        """The collected lines, read in this vendor's syntax and applied to the running node (QUIET: say nothing when
        nothing changed)."""
        lines, self.pending = self.pending, []
        if not lines:
            return ''
        with self.manager().locked() as manager:
            manager.state = None
            spec = manager.read()['spec']
            try:
                changed = vendor_config.apply(spec, self.name, '\n'.join(lines))
            except ValueError as error:
                return '% ' + str(error).replace('\n', '\n% ')
            reply = self.change(manager, spec, next(n for n in changed['nodes'] if n['name'] == self.name))
            return '' if quiet and reply == 'Aucun changement.' else reply

    def change(self, manager, spec, wanted):
        """Bring the running node to WANTED (lock held): firewall policy, then addresses, routes and protocols."""
        current = self.node(spec)
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
        if hasattr(manager, 'query_node'):  # the lab is stopped: the CLI wrote into the project
            return 'Enregistré dans le projet (appliqué au ▶ Démarrer).'
        return 'Appliqué au nœud en marche (relu dans la micro-VM).'

    # ---- host shell ----

    def host(self, command, low):
        words = low.split()
        if words[:3] in (['ip', 'addr', 'add'], ['ip', 'address', 'add'], ['ip', 'addr', 'del'], ['ip', 'address', 'del'],
                         ['ip', 'route', 'add'], ['ip', 'route', 'del']):
            return self.host_change(words)
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
        traced = self.traceroute('host', command)
        if traced is not None:
            return traced
        if words[:2] in (['ip', 'a'], ['ip', 'addr'], ['ip', 'address']) or words == ['ifconfig']:
            return self.query('addresses').rstrip()
        if words[:2] in (['ip', 'r'], ['ip', 'route']) or words == ['route']:
            return self.query('routes').rstrip()
        if words == ['hostname']:
            return self.name
        raise ValueError(f'{words[0]}: commande non disponible (ping, traceroute, tracert, ip addr, ip route, hostname, exit).')

    def host_change(self, words):
        """ip addr add|del A.B.C.D/N dev ethX, ip route add|del default|NET/N via A.B.C.D: applied to the running host."""
        from .vendor_config import _delete_route, _network, _upsert_route, routes
        import copy
        with self.manager().locked() as manager:
            manager.state = None
            spec = manager.read()['spec']
            wanted = copy.deepcopy(self.node(spec))
            verb = words[2]
            if words[1] in ('addr', 'address'):
                if len(words) != 6 or words[4] != 'dev' or words[5] not in wanted['interfaces'] or '/' not in words[3]:
                    raise ValueError(f'ip addr {verb} A.B.C.D/N dev eth0')
                cidr, port = str(ipaddress.IPv4Interface(words[3])), words[5]
                if port in wanted.get('dhcp_clients', []):
                    raise ValueError(f'{port} prend son adresse par DHCP.')
                if verb == 'add':
                    if wanted['interfaces'][port]:
                        raise ValueError(f'{port} a déjà {wanted["interfaces"][port]} : « ip addr del » d’abord.')
                    wanted['interfaces'][port] = cidr
                else:
                    if wanted['interfaces'][port] != cidr:
                        raise ValueError(f'{cidr} n’est pas l’adresse de {port}.')
                    # As on Linux: the routes through that network go with the address.
                    lost = ipaddress.IPv4Interface(cidr).network
                    for network, gateway in routes(wanted):
                        if ipaddress.IPv4Address(gateway) in lost:
                            _delete_route(wanted, network)
                    wanted['interfaces'][port] = ''
            else:
                if len(words) != 6 or words[4] != 'via':
                    raise ValueError(f'ip route {verb} default|RÉSEAU/N via A.B.C.D')
                network = '0.0.0.0/0' if words[3] == 'default' else _network(words[3])
                if verb == 'add':
                    _upsert_route(wanted, network, str(ipaddress.IPv4Address(words[5])))
                else:
                    _delete_route(wanted, network)
            reply = self.change(manager, spec, wanted)
            return reply if reply.startswith('%') else ''  # as on Linux: ip addr / ip route say nothing when they work

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


def _filter(text, kind, pattern):
    """IOS output modifiers: include (i), exclude (e), begin (b), section (s); PATTERN is a regular expression."""
    try:
        wanted = re.compile(pattern)
    except re.error:
        return "% Invalid input detected at '^' marker."
    lines = text.splitlines()
    if kind == 'i':
        return '\n'.join(l for l in lines if wanted.search(l))
    if kind == 'e':
        return '\n'.join(l for l in lines if not wanted.search(l))
    if kind == 'b':
        start = next((i for i, l in enumerate(lines) if wanted.search(l)), len(lines))
        return '\n'.join(lines[start:])
    found, keep = [], False
    for line in lines:  # section: a matching top-level line and the indented lines under it
        if not line.startswith(' '):
            keep = bool(wanted.search(line))
        if keep:
            found.append(line)
    return '\n'.join(found)
