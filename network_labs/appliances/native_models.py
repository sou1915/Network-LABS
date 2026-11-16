"""Vendor device models for native nodes, derived from the shared device catalogue (network_labs.profiles).

A model gives a native node its brand, model name, port layout and presentation. The node still runs real
Linux networking (an OCI container or a Firecracker micro-VM): a model is not vendor firmware, and vendor
consoles stay limited to what network_labs.device_identity reports for that model.
"""
from ..device_identity import identity
from ..profiles import PROFILES, profile_ports, profile_role

# Shared-catalogue roles that native Linux nodes can stand in for, and the native role they map to.
_HOST_ROLES = {'Poste': 'host', 'Serveur': 'server', 'NAS': 'server', 'Imprimante': 'device', 'Caméra': 'device',
               'Téléphone IP': 'device', 'IoT': 'device', 'Portable': 'host'}
# Specialised references with no Linux equivalent here (Wi-Fi, hubs, L7 appliances) are left out.
_EXCLUDED_ROLES = {'Point d’accès', 'Contrôleur WLAN', 'Hub', 'Firewall spécialisé'}
MICROVM_PORTS = 4
CONTAINER_PORTS = 24


# Each brand's documented port naming (first port first). Brands not listed keep the shared catalogue's names.
_BRAND_PORTS = {
    'Fortinet': lambda i: f'port{i + 1}',
    'Palo Alto': lambda i: f'ethernet1/{i + 1}',
    'Juniper': lambda i: f'ge-0/0/{i}',
    'MikroTik': lambda i: f'ether{i + 1}',
    'Check Point': lambda i: f'eth{i + 1}',
    'Netgate': lambda i: f'igb{i}',
    'Deciso': lambda i: f'igb{i}',
    'Sophos': lambda i: f'Port{i + 1}',
    'SonicWall': lambda i: f'X{i}',
    'Huawei': lambda i: f'GE0/0/{i + 1}',
    'Arista': lambda i: f'Ethernet{i + 1}',
    'HPE Aruba': lambda i: f'1/1/{i + 1}',
}
# Native firewalls route on every port; the shared catalogue's two-port transparent layout does not apply.
FIREWALL_PORTS = 8


def _native_role(profile):
    role = profile_role(profile)
    # Generic entries duplicate the workbench's own Linux devices.
    if role in _EXCLUDED_ROLES or profile.brand == 'Générique':
        return None, None
    if profile.family == 'lab-firewall' or role == 'Firewall':
        return 'firewall', 'firewall'
    if profile.kind == 'Routeur':
        return 'router', 'router'
    if profile.kind == 'Switch':
        return 'switch', 'switch'
    if profile.kind == 'PC':
        return 'host', _HOST_ROLES.get(role, 'host')
    return None, None


def _build():
    models = {}
    for profile in PROFILES.values():
        role, presentation = _native_role(profile)
        if role is None:
            continue
        kind = {'firewall': 'Switch', 'switch': 'Switch', 'router': 'Routeur'}.get(role, 'PC')
        face = identity(profile.id)
        # Educational suffixes describe that engine's limits (transparent firewalls, one simulated router uplink);
        # native nodes route on every port, so they show the plain product name and a four-port router layout.
        name = profile.model.split(' · profil')[0].split(' (')[0]
        ports = [f'gi0/{i}' for i in range(4)] if role == 'router' else profile_ports(profile.id, kind)
        if role == 'firewall':
            ports = [f'gi0/{i}' for i in range(FIREWALL_PORTS)]
        if profile.brand in _BRAND_PORTS and role != 'host':
            ports = [_BRAND_PORTS[profile.brand](i) for i in range(len(ports))]
        models[profile.id] = {
            'id': profile.id, 'brand': profile.brand, 'model': name, 'role': role, 'presentation': presentation,
            'ports': ports, 'skin': face['skin'], 'title': face['title'],
            # Only the IOS-style subset exists on native nodes today, for Cisco routers and switches in containers.
            'console': 'ios-basic' if profile.brand == 'Cisco' and role in ('router', 'switch') else 'linux',
        }
    return models


# Native-only references the shared catalogue lacks (it has two router brands). Port names follow each vendor's
# documented naming; the node still runs Linux, so these are names, a layout and a presentation only.
_EXTRA = [
    ('juniper-mx204', 'Juniper', 'MX204', 'router', [f'xe-0/0/{i}' for i in range(8)]),
    ('juniper-vsrx', 'Juniper', 'vSRX', 'firewall', [f'ge-0/0/{i}' for i in range(8)]),
    ('huawei-ar6120', 'Huawei', 'NetEngine AR6120', 'router', [f'GE0/0/{i}' for i in range(10)]),
    ('arista-7280r', 'Arista', '7280R3', 'router', [f'Ethernet{i}' for i in range(1, 25)]),
    ('nokia-7750-sr1', 'Nokia', '7750 SR-1', 'router', [f'1/1/{i}' for i in range(1, 13)]),
    ('vyos-router', 'VyOS', 'VyOS 1.4', 'router', [f'eth{i}' for i in range(8)]),
    ('ubiquiti-er4', 'Ubiquiti', 'EdgeRouter 4', 'router', [f'eth{i}' for i in range(4)]),
    ('cisco-isr4331', 'Cisco', 'ISR 4331', 'router', [f'gi0/0/{i}' for i in range(3)]),
    ('cisco-nexus-9300', 'Cisco', 'Nexus 93180YC', 'switch', [f'Ethernet1/{i}' for i in range(1, 49)]),
    ('dell-s5248f', 'Dell', 'PowerSwitch S5248F', 'switch', [f'ethernet1/1/{i}' for i in range(1, 49)]),
    ('extreme-x440', 'Extreme', 'X440-G2-24t', 'switch', [str(i) for i in range(1, 25)]),
    ('netgear-m4300', 'NETGEAR', 'M4300-28G', 'switch', [f'1/0/{i}' for i in range(1, 29)]),
    ('watchguard-t45', 'WatchGuard', 'Firebox T45', 'firewall', [f'eth{i}' for i in range(5)]),
    ('mikrotik-chr', 'MikroTik', 'Cloud Hosted Router', 'router', [f'ether{i}' for i in range(1, 9)]),
    ('apple-macos', 'Apple', 'Mac (macOS)', 'host', ['en0']),
    ('fedora-ws', 'Fedora', 'Fedora Workstation', 'host', ['enp1s0']),
]


def _add_extra(models):
    for model_id, brand, name, role, ports in _EXTRA:
        models[model_id] = {'id': model_id, 'brand': brand, 'model': name, 'role': role, 'presentation': role,
                            'ports': ports, 'skin': 'generic', 'title': name, 'console': 'linux'}
    return models


MODELS = _add_extra(_build())


def model_info(model_id):
    if model_id not in MODELS:
        raise ValueError('Modèle inconnu : ' + str(model_id))
    return MODELS[model_id]


def label(node, short=False):
    """'Cisco · Catalyst 9200L · 24 GE + 4 uplinks' for a modelled node ('Cisco · Catalyst 9200L' when short),
    else the generic Linux label."""
    if node.get('model') in MODELS:
        info = MODELS[node['model']]
        return info['brand'] + ' · ' + (short_name(info) if short else info['model'])
    return {'switch': 'Switch Linux', 'router': 'Routeur Linux', 'firewall': 'Pare-feu Linux'}.get(node['role'], 'Linux')


def short_name(info):
    """The product name without the port summary: 'Catalyst 9200L' for 'Catalyst 9200L · 24 GE + 4 uplinks'."""
    return info['model'].split(' · ')[0]


def default_ports(model_id, runtime):
    """Port count for a new node: the model's layout, within what the runtime supports."""
    info = model_info(model_id)
    if info['role'] == 'host':
        return 1
    limit = MICROVM_PORTS if runtime == 'firecracker' else CONTAINER_PORTS
    return max(2 if info['role'] in ('router', 'firewall') else 1, min(len(info['ports']), limit))


def aliases(model_id, ports):
    """Model port names for a container's eth ports (eth0 -> gi0/1, ...); micro-VM ports keep their eth names."""
    names = model_info(model_id)['ports']
    return {names[i]: port for i, port in enumerate(ports) if i < len(names)}


def port_names(node):
    """{eth port: name shown to the user}: the node's own aliases, else the model's names by position, else eth."""
    shown = {}
    aliases = {eth: name for name, eth in (node.get('interface_aliases') or {}).items()}
    names = MODELS[node['model']]['ports'] if node.get('model') in MODELS else []
    for port in node.get('interfaces', {}):
        index = int(port[3:]) if port.startswith('eth') and port[3:].isdigit() else None
        if port in aliases:
            shown[port] = aliases[port]
        elif index is not None and index < len(names):
            shown[port] = names[index]
        else:
            shown[port] = port
    return shown


def port_label(node, port):
    """One port's display name ('port1' for a FortiGate's eth0); unknown ports keep their own name."""
    return port_names(node).get(port, port)


def validate(node):
    """A node's optional 'model' must exist and match the node's role."""
    if 'model' not in node:
        return
    info = model_info(node['model'])
    if info['role'] != node['role']:
        raise ValueError(f"Le modèle {info['brand']} {info['model']} est un équipement {info['role']}, pas {node['role']}.")


def grouped():
    """Models for the library, as [(category, [model, ...])], brands sorted within each category."""
    order = [('Routeurs', ('router',)), ('Switches', ('switch',)), ('Pare-feu', ('firewall',)), ('Postes clients', ('host',)),
             ('Serveurs et stockage', ('server',)), ('Périphériques', ('device',))]
    result = []
    for category, presentations in order:
        entries = sorted((m for m in MODELS.values() if m['presentation'] in presentations), key=lambda m: (m['brand'], m['model']))
        result.append((category, entries))
    return result
