"""Build network_labs/appliances/openconfig/catalogue.json from the OpenConfig YANG models.

The catalogue is the list of OpenConfig leaves Network LABS implements, each with what the models say about it:
its schema path, YANG type (resolved through typedefs to ranges and enum values), default, units and description.
The CLIs, the generated GUI pages and the OpenConfig JSON import and export all read it, so an option's name,
range and help text come from the standard, not from this project.

A development tool: it needs pyang and a checkout of github.com/openconfig/public at the pinned commit.
    pip install pyang
    git clone https://github.com/openconfig/public && git -C public checkout COMMIT
    python3 tools/openconfig/generate.py public > network_labs/appliances/openconfig/catalogue.json
"""
import json
import os
import sys

COMMIT = 'fa27bd6ac13d14a167719bbf4eac48b1f298e43f'
NI = '/network-instances/network-instance'
BGP = NI + '/protocols/protocol/bgp'
NEIGHBOR = BGP + '/neighbors/neighbor'
AFI = '/afi-safis/afi-safi'
RP = '/routing-policy'
STATEMENT = RP + '/policy-definitions/policy-definition/statements/statement'
BGP_ACTIONS = STATEMENT + '/actions/bgp-actions'

# The leaves Network LABS implements, by OpenConfig schema path (config containers only).
LEAVES = [
    BGP + '/global/config/as',
    BGP + '/global/config/router-id',
    BGP + '/global/graceful-restart/config/enabled',
    BGP + '/global/use-multiple-paths/ebgp/config/maximum-paths',
    BGP + '/global/route-selection-options/config/always-compare-med',
    BGP + '/global/route-selection-options/config/ignore-as-path-length',
    BGP + '/global/route-selection-options/config/external-compare-router-id',
    NEIGHBOR + '/config/neighbor-address',
    NEIGHBOR + '/config/peer-as',
    NEIGHBOR + '/config/enabled',
    NEIGHBOR + '/config/description',
    NEIGHBOR + '/config/auth-password',
    NEIGHBOR + '/config/remove-private-as',
    NEIGHBOR + '/config/send-community-type',
    NEIGHBOR + '/timers/config/keepalive-interval',
    NEIGHBOR + '/timers/config/hold-time',
    NEIGHBOR + '/timers/config/connect-retry',
    NEIGHBOR + '/timers/config/minimum-advertisement-interval',
    NEIGHBOR + '/transport/config/passive-mode',
    NEIGHBOR + '/as-path-options/config/allow-own-as',
    NEIGHBOR + '/as-path-options/config/replace-peer-as',
    NEIGHBOR + AFI + '/apply-policy/config/import-policy',
    NEIGHBOR + AFI + '/apply-policy/config/export-policy',
    NEIGHBOR + AFI + '/apply-policy/config/default-import-policy',
    NEIGHBOR + AFI + '/apply-policy/config/default-export-policy',
    NEIGHBOR + AFI + '/ipv4-unicast/prefix-limit/config/max-prefixes',
    NEIGHBOR + AFI + '/ipv4-unicast/prefix-limit/config/warning-threshold-pct',
    NI + '/table-connections/table-connection/config/src-protocol',
    NI + '/table-connections/table-connection/config/import-policy',
    RP + '/defined-sets/prefix-sets/prefix-set/config/name',
    RP + '/defined-sets/prefix-sets/prefix-set/prefixes/prefix/config/ip-prefix',
    RP + '/defined-sets/prefix-sets/prefix-set/prefixes/prefix/config/masklength-range',
    RP + '/defined-sets/bgp-defined-sets/community-sets/community-set/config/community-set-name',
    RP + '/defined-sets/bgp-defined-sets/community-sets/community-set/config/community-member',
    RP + '/policy-definitions/policy-definition/config/name',
    STATEMENT + '/config/name',
    STATEMENT + '/conditions/match-prefix-set/config/prefix-set',
    STATEMENT + '/conditions/bgp-conditions/match-community-set/config/community-set',
    STATEMENT + '/actions/config/policy-result',
    BGP_ACTIONS + '/config/set-local-pref',
    BGP_ACTIONS + '/config/set-med',
    BGP_ACTIONS + '/config/set-route-origin',
    BGP_ACTIONS + '/set-as-path-prepend/config/repeat-n',
    BGP_ACTIONS + '/set-as-path-prepend/config/asn',
    BGP_ACTIONS + '/set-community/config/options',
    BGP_ACTIONS + '/set-community/inline/config/communities',
]
CONTEXT = None
MODULES = ['network-instance/openconfig-network-instance.yang', 'policy/openconfig-routing-policy.yang',
           'bgp/openconfig-bgp-policy.yang']


def text(statement, keyword):
    found = statement.search_one(keyword)
    return ' '.join(found.arg.split()) if found is not None and found.arg is not None else None


def describe_type(type_statement):
    """The YANG type as data: the typedef chain, then its base, ranges, lengths, patterns and enum values."""
    chain = []
    while True:
        name = type_statement.arg
        info = {'name': name}
        for keyword in ('range', 'length'):
            if text(type_statement, keyword):
                info[keyword] = text(type_statement, keyword)
        patterns = [p.arg for p in type_statement.search('pattern')]
        if patterns:
            info['patterns'] = patterns
        enums = type_statement.search('enum')
        if enums:
            info['enum'] = [{'name': e.arg, 'description': text(e, 'description')} for e in enums]
        identity = type_statement.search_one('base')
        if identity is not None:
            info['identities'] = _derived(identity.i_identity)
        if name == 'leafref' and type_statement.search_one('path') is not None:
            info['path'] = type_statement.search_one('path').arg
        members = type_statement.search('type')
        if members:  # union
            info['union'] = [describe_type(m) for m in members]
        chain.append(info)
        typedef = getattr(type_statement, 'i_typedef', None)
        if typedef is None:
            return chain if len(chain) > 1 else chain[0]
        info['description'] = text(typedef, 'description')
        type_statement = typedef.search_one('type')


def _derived(base):
    """The names of every identity loaded that derives from BASE, directly or not."""
    found = []
    for module in CONTEXT.modules.values():
        for identity in getattr(module, 'i_identities', {}).values():
            if identity is not base and _derives(identity, base):
                found.append(identity.arg)
    return sorted(set(found))


def _derives(identity, base):
    for parent in identity.search('base'):
        target = getattr(parent, 'i_identity', None)
        if target is base or (target is not None and _derives(target, base)):
            return True
    return False


def find(context, path):
    """The schema node at PATH (prefixes dropped, choice/case transparent)."""
    words = [w for w in path.split('/') if w]
    for module in context.modules.values():
        node = next((c for c in getattr(module, 'i_children', []) if c.arg == words[0]), None)
        if node is None:
            continue
        for word in words[1:]:
            node = _child(node, word)
            if node is None:
                break
        if node is not None:
            return node
    raise KeyError(path)


def _child(node, word):
    for child in getattr(node, 'i_children', []):
        if child.keyword in ('choice', 'case'):
            found = _child(child, word)
            if found is not None:
                return found
        elif child.arg == word:
            return child
    return None


def main(root):
    from pyang import context, repository
    models = os.path.join(root, 'release', 'models')
    search = [d for d, _, _ in os.walk(models)]
    ctx = context.Context(repository.FileRepository(os.pathsep.join(search), use_env=False))
    for name in MODULES:
        with open(os.path.join(models, name), encoding='utf-8') as stream:
            ctx.add_module(name, stream.read())
    ctx.validate()
    global CONTEXT
    CONTEXT = ctx
    leaves = []
    for path in LEAVES:
        node = find(ctx, path)
        entry = {'path': path, 'keyword': node.keyword, 'module': node.i_module.arg,
                 'revision': node.i_module.search_one('revision').arg,
                 'type': describe_type(node.search_one('type')), 'description': text(node, 'description')}
        for keyword in ('default', 'units', 'status'):
            if text(node, keyword):
                entry[keyword] = text(node, keyword)
        leaves.append(entry)
    document = {'source': 'https://github.com/openconfig/public', 'commit': COMMIT,
                'generated_by': 'tools/openconfig/generate.py (pyang)', 'leaves': leaves}
    json.dump(document, sys.stdout, indent=1, ensure_ascii=False, sort_keys=False)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main(sys.argv[1])
