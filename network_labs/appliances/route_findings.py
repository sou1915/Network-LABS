"""Human explanations of a route snapshot, without another kernel query."""
MODES = {0: 'off', 1: 'strict', 2: 'loose'}


def ipv4_labels(settings):
    ports = settings.get('interfaces', {})
    rpf = ', '.join(f"{name}={MODES.get(row.get('effective_rp_filter'), '?')}({row.get('effective_rp_filter') if row.get('effective_rp_filter') is not None else '?'})"
                    for name, row in sorted(ports.items())) or 'interfaces inconnues'
    forwarding = ', '.join(f"{name}=" + {0: 'off', 1: 'on'}.get(row.get('forwarding'), '?')
                           for name, row in sorted(ports.items())) or 'interfaces inconnues'
    return rpf, forwarding


def findings(report):
    rows = []
    def add(code, message, evidence, severity='info', next_step=None):
        rows.append({'code': code, 'severity': severity, 'message': message,
                     'evidence': evidence, 'next_step': next_step})
    selected = report['selected']
    if selected is None:
        add('ROUTE_LOOKUP_UNAVAILABLE', 'Aucune décision exploitable dans ce lookup ; consulter l’erreur retournée par ip route.',
            report['lookup'], 'unknown', 'Vérifier le contexte source/entrée, les règles de routage et les tables Linux.')
    else:
        add('ROUTE_SELECTED', f"Décision observée : sortie {selected.get('dev') or '?'}, next-hop {selected.get('gateway') or 'non affiché'}.",
            selected)
        if selected.get('type') == 'local':
            add('ROUTE_LOCAL', 'Destination terminée localement par ce node ; ce lookup ne nécessite pas de forwarding transit.', selected)
    for label, link in (('EGRESS', report.get('egress_link')), ('INGRESS', next((r for r in report['links']['records'] or []
                         if r.get('ifname') == report['query'].get('ingress')), None))):
        if link is None:
            continue
        flags = link.get('flags')
        if not isinstance(flags, list):
            add(label + '_FLAGS_UNAVAILABLE', f"{link.get('ifname')} : flags de lien inconnus.", link, 'unknown')
        elif 'UP' not in flags:
            add(label + '_ADMIN_DOWN', f"{link.get('ifname')} : interface administrativement désactivée dans ce relevé.",
                link, 'warning', 'Vérifier le shutdown demandé et la configuration de cette interface.')
        elif 'LOWER_UP' not in flags:
            add(label + '_NO_LOWER_UP', f"{link.get('ifname')} : UP, mais le kernel ne signale pas LOWER_UP.",
                link, 'warning', 'Vérifier le parent VLAN, le lien et son état opérationnel.')
    ingress = report['query'].get('ingress')
    if ingress is not None:
        settings = report['ipv4_settings']['interfaces'].get(ingress, {})
        if selected is None or selected.get('type') != 'local':
            value = settings.get('forwarding')
            if value == 0:
                add('INGRESS_FORWARDING_DISABLED', f'{ingress} : forwarding IPv4 désactivé pour le trafic à transférer ; les destinations locales sont distinctes.',
                    settings, 'warning', 'Comparer ce réglage avec le routage voulu et la destination locale/transit.')
            elif value is None:
                add('INGRESS_FORWARDING_UNKNOWN', f'{ingress} : forwarding IPv4 inconnu.', settings, 'unknown')
        effective = settings.get('effective_rp_filter')
        add('INGRESS_RP_FILTER', f"{ingress} : rp_filter effectif={effective if effective is not None else '?'} ({MODES.get(effective, 'inconnu')}). Aucun rejet de ce flux n’est déduit.",
            {'all': report['ipv4_settings'].get('all_rp_filter'), **settings}, 'unknown' if effective is None else 'info',
            'Examiner la route inverse et les règles sans désactiver automatiquement la validation de source.')
    neighbors = report.get('neighbors')
    if neighbors is None:
        if selected is not None:
            add('NEIGHBOR_NOT_QUERIED', 'Aucun voisin IPv4 interrogé pour ce type de route/contexte.',
                {'scope': report.get('neighbor_scope')})
    elif neighbors['records'] is None:
        add('NEIGHBOR_UNAVAILABLE', 'Relevé du voisin indisponible ; aucune absence ou panne n’est affirmée.', neighbors, 'unknown')
    elif not neighbors['records']:
        add('NEIGHBOR_NOT_CACHED', f"Aucune entrée voisine observée pour {report['neighbor_target']}. Un cache vide ne signifie pas que le peer est en panne.",
            {'target': report['neighbor_target']}, next_step='Si nécessaire, lancer un test de trafic séparé puis relire le voisinage.')
    else:
        for neighbor in neighbors['records']:
            if neighbor.get('dst') != report['neighbor_target'] or neighbor.get('dev') != (selected or {}).get('dev'):
                add('NEIGHBOR_CONTEXT_UNKNOWN', 'Entrée voisine non corrélée au prochain saut demandé.', neighbor, 'unknown')
                continue
            state = neighbor.get('state')
            if not isinstance(state, list) or not state or any(not isinstance(s, str) for s in state):
                add('NEIGHBOR_STATE_UNKNOWN', 'État NUD du voisin inconnu.', neighbor, 'unknown')
            elif 'FAILED' in state:
                add('NEIGHBOR_FAILED', 'Validation du voisin échouée selon le kernel ; ce relevé ne prouve pas la cause d’un ping précis.',
                    neighbor, 'warning', 'Vérifier le peer, le VLAN, le lien et les réponses ARP, puis retester séparément.')
            elif 'INCOMPLETE' in state:
                add('NEIGHBOR_PENDING', 'Voisin INCOMPLETE : résolution pas encore terminée ; cet état peut être transitoire.', neighbor)
            elif set(state) <= {'REACHABLE', 'PERMANENT', 'NOARP', 'STALE', 'DELAY', 'PROBE'}:
                add('NEIGHBOR_CACHED', 'État voisin observé : ' + ', '.join(state) + '. Un cache existant ne certifie pas la livraison ; STALE/DELAY/PROBE ne signifient pas un peer mort.', neighbor)
            else:
                add('NEIGHBOR_STATE_UNKNOWN', 'État NUD non reconnu : ' + ', '.join(state) + '.', neighbor, 'unknown')
    missing = [name for name in ('lookup', 'fibmatch', 'rules', 'links') if report[name]['records'] is None]
    if not report['ipv4_settings'].get('available'):
        missing.append('ipv4_settings')
    if missing:
        add('ROUTE_CONTEXT_PARTIAL', 'Certaines observations restent indisponibles : ' + ', '.join(missing) + '.', {'missing': missing}, 'unknown')
    return rows
