"""Passive explanations of observed native state, never a simulated packet path."""
from collections import Counter
from datetime import datetime, timezone
import json
import subprocess

from .runtime import RuntimeFailure
from .interface_stats import managed_ports, decode


def _add(findings, code, message, evidence, severity='info'):
    findings.append({'code': code, 'severity': severity, 'message': message, 'evidence': evidence})


def port_counters(node, links):
    findings, unavailable = [], []
    for name in sorted(managed_ports(node)):
        link = links.get(name, {})
        observed = decode(link)
        if observed['width_bits'] is None:
            unavailable.append(name); continue
        values = observed['counters']
        evidence = {'port': name, **observed, 'cumulative': True}
        display = lambda field: str(values[field]) if values[field] is not None else '?'
        _add(findings, 'PORT_COUNTERS', f"{name} : RX={display('rx_packets')} paquets/{display('rx_bytes')} octets, TX={display('tx_packets')} paquets/{display('tx_bytes')} octets (cumulés).", evidence)
        missing = [k for k, v in values.items() if v is None]
        if missing:
            _add(findings, 'PORT_COUNTERS_PARTIAL', f'{name} : certains compteurs ne sont pas disponibles ; ? ne signifie pas zéro.', {'port': name, 'missing': missing}, 'unknown')
        nonzero = {k: v for k, v in values.items() if k.endswith(('_errors', '_dropped')) and v is not None and v > 0}
        if nonzero:
            _add(findings, 'PORT_ERRORS_OR_DROPS', f'{name} : erreur/drop cumulé non nul : ' + ', '.join(f'{k}={v}' for k, v in nonzero.items()) + '. Ces totaux ne déterminent ni la cause ni un flux précis.', evidence, 'warning')
    if unavailable:
        _add(findings, 'PORT_COUNTERS_UNAVAILABLE', 'Compteurs indisponibles : ' + ', '.join(unavailable) + '.', {'ports': unavailable}, 'unknown')
    return findings


def explain_node(node, actual):
    """Interpret one observed snapshot; do not infer events or packet delivery."""
    findings = []
    links = {r['ifname']: r for r in actual['links']}
    findings.extend(port_counters(node, links))
    for port in node['interfaces'] | node.get('port_channels', {}):
        link = links.get(port)
        if link is None:
            _add(findings, 'INTERFACE_MISSING', f'{port} : interface absente du relevé kernel.', {'port': port}, 'warning')
            continue
        flags = link.get('flags', [])
        if 'UP' not in flags:
            expected = port in node.get('shutdown', [])
            _add(findings, 'LINK_ADMIN_DOWN', f'{port} : interface administrativement désactivée' +
                 (' comme configuré.' if expected else ', alors que la configuration demande UP.'),
                 {'port': port, 'flags': flags, 'configured_shutdown': expected}, 'info' if expected else 'warning')
        elif 'LOWER_UP' not in flags:
            _add(findings, 'LINK_NO_CARRIER', f'{port} : interface UP, sans liaison opérationnelle signalée par le kernel.',
                 {'port': port, 'flags': flags}, 'warning')

    if node.get('port_security'):
        security = actual.get('port_security', {})
        verified = security.get('available') is True and security.get('fingerprint_matches') is True
        _add(findings, 'PORT_SECURITY_POLICY' if verified else 'PORT_SECURITY_UNVERIFIED',
             'Port security statique : ' + ('règles gérées observées conformes.' if verified else 'règles absentes, modifiées ou non vérifiées.'),
             {'available': security.get('available'), 'fingerprint_matches': security.get('fingerprint_matches')}, 'info' if verified else 'warning')
        for port, observation in security.get('ports', {}).items():
            denied = observation.get('dropped_packets')
            _add(findings, 'PORT_SECURITY_DROPS' if denied is not None and denied > 0 else 'PORT_SECURITY_COUNTERS',
                 f'{port} : paquets refusés cumulés=' + (str(denied) if denied is not None else '?') +
                 '. Compteur de trames, pas un nombre de machines ou un résultat de ping ; pas de shutdown automatique.',
                 {'port': port, **observation, 'policy_verified': verified}, 'warning' if denied is not None and denied > 0 else 'info')

    if node.get('dhcp_server') is not None:
        server = actual.get('dhcp_server', {})
        verified = server.get('configuration_verified') is True
        _add(findings, 'DHCP_SERVER_CONFIG' if verified else 'DHCP_SERVER_CONFIG_UNVERIFIED',
             'Serveur DHCP : ' + ('fichier de configuration conforme.' if verified else 'fichier absent/modifié/non vérifié.'),
             {'configuration_verified': verified, 'pool': server.get('pool')}, 'info' if verified else 'warning')
        _add(findings, 'DHCP_RESERVATIONS',
             f"{len(node['dhcp_server'].get('reservations', []))} réservations MAC/IP configurées ; ce ne sont pas des baux observés ni une preuve de disponibilité du serveur.",
             {'declared_reservations': node['dhcp_server'].get('reservations', [])})

    from .snooping import effective
    if effective(node) is not None:
        snoop = actual.get('dhcp_snooping', {})
        verified = snoop.get('policy_verified') is True
        _add(findings, 'DHCP_SNOOPING_POLICY' if verified else 'DHCP_SNOOPING_UNVERIFIED',
             'DHCP snooping IPv4 : ' + ('filtre trusted/untrusted conforme.' if verified else 'filtre absent ou non vérifié.'),
             {'counters': snoop.get('counters', []), 'policy_verified': verified}, 'info' if verified else 'warning')
        bindings = snoop.get('bindings')
        available = snoop.get('observer_available') is True and bindings is not None
        _add(findings, 'DHCP_SNOOPING_BINDINGS' if available else 'DHCP_SNOOPING_OBSERVER_UNAVAILABLE',
             (f'{len(bindings)} bindings REQUEST/ACK observés ; ne prouve pas leur installation sur les clients.' if available else
              'Bindings indisponibles : observateur absent, relevé périmé ou politique non vérifiée.'),
             {'bindings': bindings, 'capture_drops': snoop.get('capture_drops'), 'events': snoop.get('events')}, 'info' if available else 'unknown')
        drops = [c for c in snoop.get('counters', []) if c.get('packets', 0) > 0]
        if drops:
            _add(findings, 'DHCP_SNOOPING_DROPS', 'Rejets DHCP/tag/fragment cumulés ; examiner chaque règle, sans attribuer un flux précis.', {'counters': drops}, 'warning')

    from .arp_inspection import effective as arp_effective
    if arp_effective(node) is not None:
        arp = actual.get('arp_inspection', {})
        verified = arp.get('policy_verified') is True
        _add(findings, 'ARP_INSPECTION_POLICY' if verified else 'ARP_INSPECTION_UNVERIFIED',
             'Inspection ARP : ' + ('politique ARP kernel conforme ; protection IPv4 évaluée séparément.' if verified else 'politique absente/modifiée/non vérifiée.'),
             {'policy_verified': verified, 'counters': arp.get('counters', []), 'dynamic_sets': arp.get('dynamic_sets', [])}, 'info' if verified else 'warning')
        _add(findings, 'ARP_INSPECTION_DYNAMIC_WINDOW', 'Autorisations DHCP limitées à 2 s après leur dernier renouvellement kernel ; règles statiques et ports trusted indépendants.',
             {'maximum_dynamic_grant_ms': 2000, 'observer_available': actual.get('dhcp_snooping', {}).get('observer_available')})
        drops = [c for c in arp.get('counters', []) if c.get('packets', 0) > 0 and not c.get('rule', '').startswith(('static:', 'dynamic:'))]
        if drops:
            _add(findings, 'ARP_INSPECTION_DROPS', 'Rejets ARP cumulés ; ces compteurs ne déterminent pas seuls la cause d’un ping.', {'counters': drops}, 'warning')

    from .source_guard import effective as guard_effective
    if guard_effective(node) is not None:
        guard = actual.get('ip_source_guard', {})
        verified = guard.get('policy_verified') is True
        _add(findings, 'IP_SOURCE_GUARD_POLICY' if verified else 'IP_SOURCE_GUARD_UNVERIFIED',
             'IP Source Guard : ' + ('filtre IPv4 conforme.' if verified else 'politique absente/modifiée/non vérifiée.'),
             {'ports': guard.get('ports'), 'policy_verified': verified}, 'info' if verified else 'warning')
        _add(findings, 'IP_SOURCE_GUARD_DYNAMIC_WINDOW',
             'Bindings DHCP : autorisations kernel limitées à 2 s sans renouvellement ; DHCP initial source 0.0.0.0 autorisé. IPv6 hors périmètre.',
             {'maximum_dynamic_grant_ms': 2000, 'observer_available': actual.get('dhcp_snooping', {}).get('observer_available')})
        drops = [c for c in guard.get('counters', []) if c.get('rule', '').startswith('deny:') and c.get('packets', 0) > 0]
        if drops:
            _add(findings, 'IP_SOURCE_GUARD_DROPS', 'Rejets IPv4 cumulés ; ne prouvent pas seuls la cause d’un ping.', {'counters': drops}, 'warning')

    if node.get('multicast') is not None:
        multicast = actual.get('multicast', {})
        verified = multicast.get('policy_verified') is True
        _add(findings, 'MULTICAST_POLICY' if verified else 'MULTICAST_UNVERIFIED',
             'Multicast : ' + ('paramètres kernel conformes.' if verified else 'paramètres absents/modifiés/non vérifiés.'),
             {'policy_verified': verified, 'bridge': multicast.get('bridge'), 'ports': multicast.get('ports')}, 'info' if verified else 'warning')
        _add(findings, 'MULTICAST_MEMBERSHIPS',
             'MDB observée : les memberships ne prouvent pas la livraison ; groupes inconnus et ports routeurs suivent la politique kernel.',
             {'mdb': multicast.get('mdb')}, 'info' if multicast.get('mdb') is not None else 'unknown')
        if node['multicast']['querier']:
            _add(findings, 'MULTICAST_QUERIER', 'Querier local non numéroté : queries source 0.0.0.0, convergence et compatibilité des hôtes à vérifier.',
                 {'source_address': '0.0.0.0', 'igmp_version': 2})

    tree = actual.get('spanning_tree')
    if tree:
        protocol = tree.get('protocol')
        if protocol == 'stp':
            _add(findings, 'STP_ROOT' if tree['is_root'] else 'STP_ROOT_PATH',
                 (f"Ce switch est root du STP commun ({tree['bridge_id']})." if tree['is_root'] else
                  f"Root STP observé : {tree['root_id']}, via {tree['root_port']}, coût {tree['root_path_cost']}."),
                 {k: tree.get(k) for k in ('protocol', 'bridge_id', 'root_id', 'root_port', 'root_path_cost')})
            forwarding = []
            for port, data in tree['ports'].items():
                state = data.get('state')
                flags = links.get(port, {}).get('flags', [])
                evidence = {'port': port, **data, 'link_flags': flags}
                if state == 'forwarding':
                    forwarding.append(port)
                elif state == 'blocking':
                    _add(findings, 'STP_BLOCKING', f'{port} : données bloquées par STP ; cet état peut être normal sur un lien redondant.', evidence)
                elif state in ('listening', 'learning'):
                    protected = data.get('root_guard') is True and state == 'listening'
                    _add(findings, 'STP_ROOT_GUARD_LISTENING' if protected else 'STP_TRANSITION',
                         f'{port} : {state}, les données ne sont pas transmises.' +
                         (' Root Guard actif ; des BPDUs supérieures peuvent maintenir cet état, sans preuve de cause dans ce relevé.'
                          if protected else ' Transition STP en cours au moment du relevé.'), evidence,
                         'warning' if protected else 'info')
                elif state == 'disabled':
                    operational = 'UP' in flags and 'LOWER_UP' in flags
                    guarded = operational and data.get('bpdu_guard') is True
                    _add(findings, 'STP_DISABLED_WITH_BPDU_GUARD' if guarded else 'STP_DISABLED',
                         f'{port} : moteur STP désactivé sur ce port, sans transmission de données.' +
                         (' BPDU Guard actif et lien opérationnel : vérifier la source des BPDUs. Après retrait de la protection, cycler le lien pour récupérer.'
                          if guarded else ''), evidence, 'warning' if operational else 'info')
                else:
                    _add(findings, 'STP_PORT_UNKNOWN', f'{port} : état STP non reconnu.', evidence, 'unknown')
                if data.get('bpdu_guard') is True or data.get('root_guard') is True:
                    _add(findings, 'STP_PROTECTION', f"{port} : BPDU Guard={'on' if data.get('bpdu_guard') else 'off'}, Root Guard={'on' if data.get('root_guard') else 'off'}.",
                         {'port': port, 'bpdu_guard': data.get('bpdu_guard'), 'root_guard': data.get('root_guard')})
            if forwarding:
                _add(findings, 'STP_FORWARDING', 'Ports en forwarding : ' + ', '.join(forwarding) + '.', {'ports': forwarding})
        elif protocol == 'off':
            _add(findings, 'STP_OFF', 'STP désactivé sur ce bridge.', {'protocol': protocol})
        else:
            _add(findings, 'STP_CONTROLLER_UNKNOWN', 'Contrôleur STP non géré par ce backend.', {'protocol': protocol}, 'unknown')

    for name, channel in actual.get('port_channels', {}).items():
        configured = node['port_channels'][name]
        negotiated = channel['negotiated_members']
        ready = channel['ready']
        degraded = ready and len(negotiated) < len(configured['members'])
        _add(findings, 'LACP_DEGRADED' if degraded else 'LACP_READY' if ready else 'LACP_NOT_READY',
             f"{name} : {len(negotiated)}/{len(configured['members'])} membres négociés, min-links={configured['min_links']}. " +
             ('Agrégat opérationnel avec capacité réduite.' if degraded else 'Agrégat opérationnel.' if ready else 'Agrégat non prêt au moment du relevé.'),
             {'port': name, 'ready': ready, 'negotiated_members': negotiated, 'min_links': configured['min_links'],
              'members': channel['members']}, 'info' if ready and not degraded else 'warning')

    for record in actual.get('vlans', []):
        if record['ifname'] not in node.get('switchports', {}):
            continue
        entries = record.get('vlans', [])
        labels = []
        for entry in entries:
            label = str(entry['vlan']) + ('-' + str(entry['vlanEnd']) if entry.get('vlanEnd') else '')
            flags = entry.get('flags', [])
            if 'PVID' in flags:
                label += ' PVID'
            if 'Egress Untagged' in flags:
                label += ' untagged'
            labels.append(label)
        _add(findings, 'VLAN_MEMBERSHIP', f"{record['ifname']} : VLAN kernel " + (', '.join(labels) if labels else 'aucun') + '.',
             {'port': record['ifname'], 'memberships': entries})

    ipv4 = {}
    for record in actual['addresses']:
        values = [f"{a['local']}/{a['prefixlen']}" for a in record.get('addr_info', [])
                  if a.get('family') == 'inet' and a.get('scope') == 'global']
        if values:
            ipv4[record['ifname']] = values
    if ipv4:
        _add(findings, 'IPV4_ADDRESSES', 'IPv4 observées : ' + '; '.join(f'{p}={", ".join(v)}' for p, v in ipv4.items()) + '.', ipv4)
    for port in node.get('dhcp_clients', []):
        present = bool(ipv4.get(port))
        _add(findings, 'DHCP_ADDRESS_PRESENT' if present else 'DHCP_ADDRESS_MISSING',
             f'{port} : client DHCP configuré, ' + ('IPv4 présente ; son origine et le bail ne sont pas vérifiés.' if present else 'aucune IPv4 globale observée ; vérifier le serveur et le chemin VLAN.'),
             {'port': port, 'addresses': ipv4.get(port, [])}, 'info' if present else 'warning')
    if node['role'] in ('router', 'firewall'):
        enabled = actual['forwarding']
        _add(findings, 'IPV4_FORWARDING', 'Routage IPv4 ' + ('activé.' if enabled else 'désactivé.'),
             {'enabled': enabled, 'configured': node['forwarding']}, 'warning' if enabled != node['forwarding'] else 'info')
    if actual['routes']:
        _add(findings, 'IPV4_ROUTES', f"{len(actual['routes'])} routes IPv4 observées ; leur présence ne prouve pas la joignabilité.", {'routes': actual['routes']})
    if node.get('firewall') is not None:
        from .firewall import TABLE
        chains, counters = [], []
        for entry in actual.get('firewall', {}).get('nftables', []):
            chain = entry.get('chain', {})
            if chain.get('family') == 'ip' and chain.get('table') == TABLE and chain.get('hook') == 'forward':
                chains.append({'name': chain['name'], 'policy': chain.get('policy')})
            rule = entry.get('rule', {})
            if rule.get('family') == 'ip' and rule.get('table') == TABLE:
                for expr in rule.get('expr', []):
                    if isinstance(expr, dict) and isinstance(expr.get('counter'), dict):
                        counters.append({'chain': rule['chain'], 'comment': rule.get('comment'), **expr['counter']})
        _add(findings, 'FIREWALL_SNAPSHOT' if chains else 'FIREWALL_CHAIN_MISSING',
             'Firewall IPv4 : ' + (', '.join(f"{c['name']} policy={c['policy']}" for c in chains) if chains else 'chaîne de forwarding gérée absente') +
             '. Les compteurs sont cumulatifs et ne prouvent pas le résultat d’un ping précis.',
             {'chains': chains, 'counters': counters}, 'info' if chains else 'warning')
    return findings


def explain(manager, name=None):
    state = manager.read()
    selected = [n for n in state['spec']['nodes'] if name is None or n['name'] == name]
    if not selected:
        raise ValueError('Unknown node: ' + str(name))
    report = {'version': 1, 'lab': manager.name, 'phase': state['phase'], 'revision': state.get('revision', 0), 'selection': name,
              'language': 'fr', 'source': 'OCI runtime state and current kernel observations from inspect',
              'started_at': datetime.now(timezone.utc).isoformat(), 'passive': True, 'packet_delivery': 'not_tested',
              'scope': 'Sequential current observations; not an event history or a global convergence certificate.', 'nodes': []}
    snapshots = {}
    for node in selected:
        item = {'name': node['name'], 'role': node['role'], 'runtime': node['runtime'],
                'observations_available': False, 'container_status': None, 'findings': []}
        report['nodes'].append(item)
        if state['phase'] != 'running' or node['runtime'] != 'oci':
            _add(item['findings'], 'OBSERVATION_UNAVAILABLE', 'Relevé réseau indisponible : ' +
                 ('lab hors phase running.' if state['phase'] != 'running' else 'aucun agent invité pour ce runtime.'),
                 {'phase': state['phase'], 'runtime': node['runtime']}, 'unknown')
            continue
        try:
            result = manager.crun('state', node['name'], check=False)
            if result.returncode:
                raise RuntimeFailure(result.stderr.strip() or 'crun state unavailable')
            item['container_status'] = json.loads(result.stdout)['status']
            if item['container_status'] != 'running':
                _add(item['findings'], 'CONTAINER_NOT_RUNNING', 'Le conteneur ne tourne pas ; aucun état réseau prêt n’est affirmé.',
                     {'status': item['container_status']}, 'warning')
                continue
            actual = manager.inspect(node['name'])
            item['findings'] = explain_node(node, actual)
            if node['role'] == 'switch':
                snapshots[node['name']] = {k: actual[k] for k in ('links', 'vlans', 'spanning_tree') if k in actual}
                snapshots[node['name']]['port_channels'] = {p: {'ready': c.get('ready')} for p, c in actual.get('port_channels', {}).items()}
            item['observations_available'] = True
        except (RuntimeFailure, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
            _add(item['findings'], 'OBSERVATION_FAILED', 'Lecture incomplète : ' + str(error), {}, 'unknown')
    from .vlan_audit import compare_links
    report['link_check_scope'] = 'Declared switch-to-switch links; logical LACP ports; full-lab selection only. No cable discovery or delivery proof.'
    report['link_checks'] = compare_links(state['spec'], snapshots) if name is None else []
    report['link_checks_complete'] = all(c['status'] != 'unknown' for c in report['link_checks']) if name is None else None
    report['completed_at'] = datetime.now(timezone.utc).isoformat()
    report['observation_complete'] = all(n['observations_available'] for n in report['nodes'])
    report['counts'] = dict(Counter(f['severity'] for item in report['nodes'] + report['link_checks'] for f in item['findings']))
    return report


def render(report):
    lines = [f"Lab {report['lab']} | phase {report['phase']} | révision {report['revision']}",
             'Diagnostic passif : relevés successifs, aucun paquet de test envoyé.',
             f"Relevés disponibles : {sum(n['observations_available'] for n in report['nodes'])}/{len(report['nodes'])} | alertes : {report['counts'].get('warning', 0)} | inconnus : {report['counts'].get('unknown', 0)}"]
    for node in report['nodes']:
        lines += ['', f"{node['name']} ({node['role']}, {node['runtime']}) | conteneur : {node['container_status'] or 'non vérifié'}"]
        for finding in node['findings']:
            lines.append(f"  [{finding['severity'].upper()}] {finding['message']}")
    for check in report.get('link_checks', []):
        ends = check['endpoints']
        lines += ['', f"Lien déclaré {ends[0]['node']}/{ends[0]['port']} ↔ {ends[1]['node']}/{ends[1]['port']} | comparaison VLAN : {check['status']}"]
        for finding in check['findings']:
            lines.append(f"  [{finding['severity'].upper()}] {finding['message']}")
    if not report.get('link_checks'):
        lines.append('\nComparaison VLAN entre switches : ' + ('utiliser explain LAB sans sélection de node.' if report.get('selection') else 'aucun lien switch-switch déclaré à comparer.'))
    lines += ['', 'La livraison des paquets reste à tester. Ce relevé ne vérifie pas toute la configuration gérée (save/export).']
    return '\n'.join(lines)
