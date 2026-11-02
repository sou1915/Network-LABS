"""Compare observed 802.1Q memberships on declared switch-to-switch links.

This is a passive configuration comparison, not forwarding or cable discovery.
"""


def _port(actual, name):
    links = {r['ifname']: r for r in actual['links']}
    bridge, port = links.get('br0', {}), links.get(name, {})
    data = bridge.get('linkinfo', {}).get('info_data', {})
    if (not port or port.get('master') not in ('br0', bridge.get('ifindex'))
            or bridge.get('ifindex') is None or data.get('vlan_filtering') != 1
            or data.get('vlan_protocol') != '802.1Q'):
        raise ValueError('Port/bridge 802.1Q avec filtrage actif et master br0 non confirmé.')
    if port.get('linkinfo', {}).get('info_slave_data', {}).get('vlan_tunnel'):
        raise ValueError('Port en vlan_tunnel : comparaison non prise en charge.')
    records = [r for r in actual.get('vlans', []) if r['ifname'] == name]
    if not records:
        raise ValueError('Membership VLAN absente du relevé ; une liste vide n’est pas supposée.')
    membership = {}
    for record in records:
        for entry in record['vlans']:
            low, high = entry['vlan'], entry.get('vlanEnd', entry['vlan'])
            if type(low) is not int or type(high) is not int or not 1 <= low <= high <= 4094:
                raise ValueError('Range VLAN kernel invalide.')
            flags = entry.get('flags', [])
            settings = ('PVID' in flags, 'Egress Untagged' in flags)
            for vid in range(low, high + 1):
                if vid in membership and membership[vid] != settings:
                    raise ValueError('Flags VLAN kernel contradictoires.')
                membership[vid] = settings
    pvids = [v for v, flags in membership.items() if flags[0]]
    if len(pvids) > 1:
        raise ValueError('Plusieurs PVID observés sur le même port.')
    return {'vlans': sorted(membership), 'untagged': sorted(v for v, flags in membership.items() if flags[1]),
            'pvid': pvids[0] if pvids else None, 'link_flags': port.get('flags', []),
            'stp': actual.get('spanning_tree', {}).get('ports', {}).get(name),
            'lacp_ready': actual.get('port_channels', {}).get(name, {}).get('ready')}


def compare_links(spec, snapshots):
    nodes = {n['name']: n for n in spec['nodes']}
    bundles = {(n['name'], p): b for n in spec['nodes'] for b, c in n['port_channels'].items() for p in c['members']}
    pairs = {}
    for link in spec['links']:
        if any(nodes[n]['role'] != 'switch' for n, _ in link):
            continue
        ends = tuple(sorted((n, bundles.get((n, p), p)) for n, p in link))
        pairs.setdefault(ends, []).append(link)
    reports = []
    for ends, physical in pairs.items():
        result = {'endpoints': [{'node': n, 'port': p} for n, p in ends],
                  'declared_physical_links': physical, 'status': 'unknown', 'findings': [], 'evidence': {}}
        reports.append(result)
        def add(code, message, evidence, severity='warning'):
            result['findings'].append({'code': code, 'severity': severity, 'message': message, 'evidence': evidence})
        try:
            observed = []
            for n, p in ends:
                if n not in snapshots:
                    raise ValueError(n + ' : relevé kernel indisponible.')
                observed.append(_port(snapshots[n], p))
            result['evidence'] = {'a': observed[0], 'b': observed[1]}
            for i, source in enumerate(observed):
                target = observed[1 - i]
                direction = f'{ends[i][0]}/{ends[i][1]} → {ends[1-i][0]}/{ends[1-i][1]}'
                if not source['vlans']:
                    add('VLAN_NO_MEMBERSHIP', direction + ' : aucun VLAN de données observé au départ.', {'direction': direction})
                missing = sorted(set(source['vlans']) - set(source['untagged']) - set(target['vlans']))
                if missing:
                    add('VLAN_TAGGED_NOT_ADMITTED', direction + f' : VLAN taggés {missing} absents des memberships du port récepteur.',
                        {'direction': direction, 'vlans': missing})
                if source['untagged']:
                    if target['pvid'] is None:
                        add('VLAN_UNTAGGED_NO_PVID', direction + ' : sortie untagged mais aucun PVID observé à réception.',
                            {'direction': direction, 'source_vlans': source['untagged'], 'target_pvid': None})
                    else:
                        changed = sorted(set(source['untagged']) - {target['pvid']})
                        if changed:
                            add('VLAN_UNTAGGED_RECLASSIFIED', direction + f" : VLAN locaux {changed} sortent untagged et entrent dans le PVID {target['pvid']}. Vérifier si cette reclassification est voulue.",
                                {'direction': direction, 'source_vlans': changed, 'target_pvid': target['pvid']})
            result['status'] = 'attention' if result['findings'] else 'compatible'
            if not result['findings']:
                add('VLAN_MEMBERSHIPS_COMPATIBLE', 'Memberships et traitement tag/untagged compatibles sur ce lien déclaré. Disponibilité, STP/LACP et livraison restent à vérifier.', {}, 'info')
        except (ValueError, KeyError, TypeError) as error:
            add('VLAN_LINK_UNKNOWN', 'Comparaison indisponible : ' + str(error), {}, 'unknown')
    return reports
