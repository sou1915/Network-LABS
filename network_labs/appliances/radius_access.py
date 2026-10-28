"""Declared local authorization for the fixed RADIUS diagnostic executor."""
import ipaddress
import re

from .spec import keys
from .runtime import RuntimeFailure

ACTIONS = ('identity', 'hostname', 'security-context')


def validate_node(node):
    policy = node.get('radius_access')
    if policy is None: return
    keys(policy, ('server', 'users'), 'RADIUS access')
    if (node['runtime'] != 'oci' or node['role'] != 'host' or set(node['interfaces']) != {'eth0'}
            or node.get('subinterfaces') or node.get('port_channels')):
        raise ValueError('RADIUS access requires a single-interface OCI host.')
    try: server = ipaddress.IPv4Address(policy.get('server'))
    except (ValueError, TypeError) as error:
        raise ValueError('RADIUS access requires a literal remote IPv4 server.') from error
    if (not isinstance(policy.get('server'), str) or server.is_multicast or server.is_loopback
            or server.is_unspecified or server.is_reserved):
        raise ValueError('RADIUS access requires a usable remote unicast IPv4 server.')
    if node['interfaces']['eth0'] and server == ipaddress.IPv4Interface(node['interfaces']['eth0']).ip:
        raise ValueError('RADIUS access server must be remote.')
    users = policy.get('users')
    if not isinstance(users, dict) or not 1 <= len(users) <= 16:
        raise ValueError('RADIUS access requires 1..16 explicit users.')
    for name, actions in users.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}', name):
            raise ValueError('RADIUS access requires ASCII login names, at most 64 characters.')
        if (not isinstance(actions, list) or not actions or len(actions) > len(ACTIONS)
                or any(not isinstance(action, str) or action not in ACTIONS for action in actions)
                or len(set(actions)) != len(actions)):
            raise ValueError('RADIUS access user actions must be distinct supported diagnostics.')
    policy['server'] = str(server)
    policy['users'] = {name: sorted(users[name]) for name in sorted(users)}


def authorize(manager, source, server, username, action):
    state = manager.read()
    if state['phase'] != 'running' or 'pending_spec' in state or 'pending_node' in state:
        raise RuntimeFailure('RADIUS access requires a running lab without pending configuration.')
    node = next((node for node in state['spec']['nodes'] if node['name'] == source), {})
    policy = node.get('radius_access')
    if policy is None: return 'NO_ACCESS_POLICY'
    if server != policy['server']: return 'SERVER_NOT_ALLOWED'
    if action not in policy['users'].get(username, []): return 'ACTION_NOT_ALLOWED'
    return None
