"""Reconcile dynamic MAC learning after managed aggregate restoration."""
import json
import time
from types import SimpleNamespace

from .runtime import RuntimeFailure


def restored_channels(node, previous):
    if node.get('spanning_tree', {}).get('mode') != 'stp' or node.get('switch_backend') == 'ovs': return []
    result = []
    for name, channel in node.get('port_channels', {}).items():
        old = previous.get('port_channels', {}).get(name)
        if old != channel: continue
        def available(policy):
            return (name not in policy['shutdown'] and
                    sum(member not in policy['shutdown'] for member in channel['members']) >= channel['min_links'])
        if not available(previous) and available(node): result.append(name)
    return result


def component(spec, edited):
    """Scope cache cleanup to managed common-STP switches connected administratively."""
    nodes = {n['name']: (i, edited if n['name'] == edited['name'] else n) for i, n in enumerate(spec['nodes'])
             if n['runtime'] == 'oci' and n['role'] == 'switch' and n['spanning_tree']['mode'] == 'stp' and n.get('switch_backend') != 'ovs'}
    adjacency = {name: set() for name in nodes}
    def up(node, port):
        if port in node['shutdown']: return False
        for name, channel in node['port_channels'].items():
            if port in channel['members']:
                return name not in node['shutdown'] and sum(p not in node['shutdown'] for p in channel['members']) >= channel['min_links']
        return True
    for (left, lp), (right, rp) in spec['links']:
        if left in nodes and right in nodes and up(nodes[left][1], lp) and up(nodes[right][1], rp):
            adjacency[left].add(right); adjacency[right].add(left)
    pending = [edited['name']]; seen = set()
    while pending:
        name = pending.pop()
        if name in seen or name not in nodes: continue
        seen.add(name); pending.extend(adjacency[name] - seen)
    return [nodes[name] for name in sorted(seen)]


def reconcile(manager, index, node, previous):
    channels = restored_channels(node, previous)
    if not channels: return None
    peers = component(manager.state['spec'], node)
    if len(peers) < 2: return None
    from .spanning_tree import kernel_ids, observe
    from .lacp import observe as observe_lacp
    budget = min(90, node['spanning_tree']['max_age'] + 2 * node['spanning_tree']['forward_delay'] + 5)
    deadline = time.monotonic() + budget; stable = None
    def ns(peer_index, *args, **options):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeFailure('STP/LACP administrative recovery deadline reached.')
        options['timeout'] = min(options.get('timeout', 3), remaining)
        return manager.ns(peer_index, *args, **options)
    bounded = SimpleNamespace(ns=ns)
    while time.monotonic() < deadline:
        snapshot = []; roots = set(); settled = True
        try:
            for peer_index, peer in peers:
                links = json.loads(ns(peer_index, 'ip', '-j', '-d', 'link', 'show').stdout)
                tree = observe(peer, links, kernel_ids(bounded, peer_index))
                settled = settled and tree['protocol'] == 'stp' and tree['local_state_settled']
                roots.add(tree['root_id'])
                snapshot.append((peer['name'], tree['root_id'], tree['root_port'],
                                 tuple(sorted((p, data['state']) for p, data in tree['ports'].items()))))
                if peer_index == index:
                    bundles = observe_lacp(bounded, peer_index, peer, links)
                    settled = settled and all(bundles[name]['ready'] for name in channels)
            fingerprint = tuple(snapshot)
            if settled and None not in roots and len(roots) == 1:
                if stable == fingerprint: break
                stable = fingerprint
            else:
                stable = None
        except (ValueError, KeyError, TypeError) as error:
            raise RuntimeFailure('STP/LACP recovery observation unavailable.') from error
        time.sleep(.2)
    else:
        raise RuntimeFailure('STP/LACP administrative recovery did not settle before the bounded deadline.')
    # A common STP tree covers all VLANs. Old spare-path destinations can
    # survive a short kernel TCN ageing interval; remove dynamic entries only
    # after the new path settles, on both ends, preserving permanent/static FDB.
    for peer_index, peer in peers:
        ns(peer_index, 'bridge', 'fdb', 'flush', 'dev', 'br0', 'dynamic')
    return {'channels': channels, 'bridges': [peer['name'] for _, peer in peers], 'dynamic_only': True,
            'scope': 'Sequential kernel control-state observations and dynamic FDB reconciliation after administrative recovery. No packet-delivery verdict or carrier-failure watchdog.'}
