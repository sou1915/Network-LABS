"""Explicit local user/action or reusable role authorization for RADIUS entry points."""
import ipaddress
import re

from .spec import integer, keys
from .runtime import RuntimeFailure

ACTIONS = ('identity', 'hostname', 'security-context', 'shell')


def validate_node(node):
    policy = node.get('radius_access')
    if policy is None: return
    keys(policy, ('server', 'users', 'roles', 'user_roles', 'session_seconds', 'accounting', 'accounting_retries', 'accounting_outbox', 'accounting_journal'), 'RADIUS access')
    integer(policy.setdefault('session_seconds', 300), 1, 3600, 'RADIUS shell session seconds')
    if type(policy.setdefault('accounting', False)) is not bool:
        raise ValueError('RADIUS access accounting must be boolean.')
    if type(policy.get('accounting_outbox', False)) is not bool or (policy.get('accounting_outbox') and not policy['accounting']):
        raise ValueError('Accounting outbox requires a boolean and enabled accounting.')
    if type(policy.get('accounting_journal', False)) is not bool or (policy.get('accounting_journal') and not policy.get('accounting_outbox')):
        raise ValueError('Accounting journal requires a boolean and enabled Stop outbox.')
    integer(policy.get('accounting_retries', 0), 0, 2, 'Accounting retries')
    if policy.get('accounting_retries', 0) and not policy['accounting']:
        raise ValueError('Accounting retries require accounting enabled.')
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
    role_mode = 'roles' in policy or 'user_roles' in policy
    if role_mode:
        if 'users' in policy:
            raise ValueError('Choose either direct users or roles with user_roles; mixed grants are refused.')
        roles = policy.get('roles')
        users = policy.get('user_roles')
        if not isinstance(roles, dict) or not 1 <= len(roles) <= 16:
            raise ValueError('RADIUS access requires 1..16 explicit roles.')
        for name, actions in roles.items():
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}', name):
                raise ValueError('RADIUS role names require 1..32 ASCII letters, digits, _ or -, starting with a letter.')
            validate_actions(actions)
    else:
        users = policy.get('users')
    if not isinstance(users, dict) or not 1 <= len(users) <= 16:
        raise ValueError('RADIUS access requires 1..16 explicit users.')
    for name, grants in users.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}', name):
            raise ValueError('RADIUS access requires ASCII login names, at most 64 characters.')
        if role_mode:
            if (not isinstance(grants, list) or not 1 <= len(grants) <= 16
                    or any(not isinstance(role, str) or role not in roles for role in grants)
                    or len(set(grants)) != len(grants)):
                raise ValueError('RADIUS user_roles requires distinct declared role names.')
        else:
            validate_actions(grants)
    policy['server'] = str(server)
    if role_mode:
        policy['roles'] = {name: sorted(roles[name]) for name in sorted(roles)}
        policy['user_roles'] = {name: sorted(users[name]) for name in sorted(users)}
    else:
        policy['users'] = {name: sorted(users[name]) for name in sorted(users)}


def validate_actions(actions):
    if (not isinstance(actions, list) or not actions or len(actions) > len(ACTIONS)
            or any(not isinstance(action, str) or action not in ACTIONS for action in actions)
            or len(set(actions)) != len(actions)):
        raise ValueError('RADIUS access actions must be distinct supported actions.')


def allowed_actions(policy, username):
    """Resolve one validated user's grants; malformed or mixed runtime policy denies."""
    try:
        if 'roles' in policy or 'user_roles' in policy:
            if 'users' in policy: return []
            roles = policy['roles']; assignments = policy['user_roles'].get(username, [])
            if not isinstance(assignments, list) or not 1 <= len(assignments) <= 16:
                return []
            if any(not isinstance(role, str) or role not in roles for role in assignments) or len(set(assignments)) != len(assignments):
                return []
            actions = set()
            for role in assignments:
                validate_actions(roles[role]); actions.update(roles[role])
            return sorted(actions)
        actions = policy.get('users', {}).get(username, [])
        validate_actions(actions)
        return sorted(actions)
    except (ValueError, TypeError, KeyError, AttributeError):
        return []


def authorization(policy, username):
    actions = allowed_actions(policy, username)
    roles = sorted(policy['user_roles'][username]) if actions and 'user_roles' in policy else []
    return {'mode': 'roles' if 'roles' in policy or 'user_roles' in policy else 'users',
            'roles': roles, 'actions': actions}


def authorize(manager, source, server, username, action):
    state = manager.read()
    if state['phase'] != 'running' or 'pending_spec' in state or 'pending_node' in state:
        raise RuntimeFailure('RADIUS access requires a running lab without pending configuration.')
    node = next((node for node in state['spec']['nodes'] if node['name'] == source), {})
    policy = node.get('radius_access')
    if policy is None: return 'NO_ACCESS_POLICY'
    if server != policy['server']: return 'SERVER_NOT_ALLOWED'
    if action not in allowed_actions(policy, username): return 'ACTION_NOT_ALLOWED'
    return None
