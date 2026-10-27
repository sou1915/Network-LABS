"""Bounded two-node SNTP demonstration; no daemon or clock changes persist."""
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys

from .runtime import RuntimeFailure
from .spec import integer, namespace
from .verify import _endpoint


def demo(manager, client, server, *, server_offset_seconds=0):
    from .service_probe import probe
    integer(server_offset_seconds, -86400, 86400, 'Server offset seconds')
    state = manager.read()
    if state['phase'] != 'running' or 'pending_spec' in state or 'pending_node' in state:
        raise RuntimeFailure('SNTP demo requires a running lab without pending configuration.')
    if client == server:
        raise ValueError('Choose two different managed hosts.')
    endpoints = []
    for name in (client, server):
        match = next(((i, n) for i, n in enumerate(state['spec']['nodes']) if n['name'] == name), None)
        if (match is None or match[1]['runtime'] != 'oci' or match[1]['role'] != 'host' or
                set(match[1]['interfaces']) != {'eth0'} or match[1].get('subinterfaces') or match[1].get('port_channels')):
            raise ValueError('SNTP demo requires two managed single-interface OCI hosts.')
        observation = _endpoint(manager, *match)
        if observation['status'] != 'ready':
            raise RuntimeFailure(name + ': endpoint not ready: ' + ', '.join(observation['reasons']))
        endpoints.append((match[0], observation))
    source, target = endpoints[0][1]['address'], endpoints[1][1]['address']
    if source == target:
        raise ValueError('The two hosts need distinct observed addresses.')
    worker = Path(__file__).with_name('sntp_demo_worker.py').read_text()
    argv = ['ip', 'netns', 'exec', namespace(state['spec'], endpoints[1][0]), sys.executable, '-I', '-c', worker, target, source, '123', str(server_offset_seconds)]
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=3):
                raise RuntimeFailure('SNTP demo responder did not become ready.')
            line = process.stdout.readline()
        try:
            ready = json.loads(line)
        except ValueError as error:
            raise RuntimeFailure('SNTP demo responder readiness unavailable.') from error
        if ready.get('status') != 'ready' or ready.get('port') != 123:
            raise RuntimeFailure('SNTP demo responder could not bind UDP/123: ' + str(ready.get('detail', 'unknown'))[:300])
        result = probe(manager, client, target, protocol='sntp')
        output, _ = process.communicate(timeout=10)
        try:
            response = json.loads(output.strip())
        except ValueError:
            response = {'status': 'unknown'}
        return {'lab': manager.name, 'client': client, 'server': server, 'status': result['status'] if response.get('status') == 'responded' and process.returncode == 0 else 'unknown',
                'probe': result, 'responder': response, 'server_offset_seconds': server_offset_seconds,
                'temporary': True, 'configuration_changed': False,
                'scope': 'Educational one-shot server uses host clock plus a temporary offset and illustrative stratum; no independent upstream, authentication or clock setting. Not a managed persistent NTP service or independent node clock.'}
    except subprocess.TimeoutExpired as error:
        raise RuntimeFailure('SNTP demo responder did not finish within its deadline.') from error
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.communicate()


def render(report):
    from .service_probe import render as render_probe
    return ('Serveur SNTP éducatif temporaire : ' + report['server'] + ' ; décalage simulé : ' + str(report['server_offset_seconds']) + ' s\n' + render_probe(report['probe']) +
            '\nServeur basé sur l’horloge de l’hôte ; stratum illustratif, aucune synchronisation ni authentification.\n'
            'Résultat global : ' + report['status'])
