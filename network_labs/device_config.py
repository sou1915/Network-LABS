"""Atomic GUI changes through the same parser as the CLI, preserving live objects."""
from dataclasses import asdict
import json
from .text_lab import import_device_config

def fingerprint(node):
    data=asdict(node)
    data.pop('x',None);data.pop('y',None)
    return json.dumps(data,sort_keys=True)

def apply_device_commands(lab,target,commands):
    result=import_device_config('\n'.join(commands),lab,target)
    candidate=result.lab
    commit_candidate(lab,candidate)
    return result

def commit_candidate(lab,candidate):
    """Publish validated configuration while preserving GUI/terminal references."""
    # Existing terminals and port dialogs keep references to these objects.
    nodes=lab.nodes
    for name,new_node in candidate.nodes.items():
        if name not in nodes:
            nodes[name]=new_node;continue
        old=nodes[name];ports=old.ports
        for key in list(ports):
            if key not in new_node.ports:
                del ports[key]
        for key,new_port in new_node.ports.items():
            if key in ports:
                ports[key].__dict__.clear();ports[key].__dict__.update(new_port.__dict__)
            else:
                ports[key]=new_port
        old.__dict__.clear();old.__dict__.update(new_node.__dict__);old.ports=ports
    candidate.nodes=nodes
    lab.__dict__.clear();lab.__dict__.update(candidate.__dict__)

def apply_native_commands(lab,target,commands):
    import copy
    from .vendor_cli import console_session
    from .device_identity import identity
    if identity(lab.nodes[target].profile)['console']!='fortios':
        raise ValueError('Cette API native est réservée au sous-ensemble FortiOS.')
    candidate=copy.deepcopy(lab)
    session=console_session(candidate,target)
    if not commands or not commands[0].startswith('config ') or commands[-1]!='end':
        raise ValueError('Bloc FortiOS complet config … end requis.')
    for command in commands:
        result=session.execute(command)
        if result.startswith('%'):raise ValueError(result[1:].strip())
    if session.context:raise ValueError('Bloc FortiOS incomplet.')
    commit_candidate(lab,candidate)
