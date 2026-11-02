"""Bounded educational HTTPS exchange with temporary explicit certificate trust."""
import ipaddress
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile

from .runtime import RuntimeFailure
from .spec import namespace
from .verify import _endpoint


def certificate(directory, address):
    address = str(ipaddress.IPv4Address(address))
    openssl = shutil.which('openssl')
    if not openssl: raise RuntimeFailure('HTTPS demo requires a trusted local OpenSSL executable.')
    directory = Path(directory); cert, key = directory / 'certificate.pem', directory / 'private.key'
    result = subprocess.run([openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                             '-subj', '/CN=network-labs-demo', '-addext', 'subjectAltName=IP:' + address,
                             '-keyout', str(key), '-out', str(cert)], capture_output=True, text=True, timeout=10)
    if result.returncode: raise RuntimeFailure('Could not generate the temporary HTTPS demonstration certificate.')
    key.chmod(0o600)
    return cert, key


def demo(manager, client, server):
    from .service_probe import probe, load_ca
    state = manager.read()
    if state['phase'] != 'running' or 'pending_spec' in state or 'pending_node' in state:
        raise RuntimeFailure('HTTPS demo requires a running lab without pending configuration.')
    if client == server: raise ValueError('Choose two different managed hosts.')
    endpoints = []
    for name in (client, server):
        match = next(((i, n) for i, n in enumerate(state['spec']['nodes']) if n['name'] == name), None)
        if (match is None or match[1]['runtime'] != 'oci' or match[1]['role'] != 'host' or
                set(match[1]['interfaces']) != {'eth0'} or match[1].get('subinterfaces') or match[1].get('port_channels')):
            raise ValueError('HTTPS demo requires two managed single-interface OCI hosts.')
        endpoint = _endpoint(manager, *match)
        if endpoint['status'] != 'ready': raise RuntimeFailure(name + ': HTTPS demo endpoint not ready.')
        endpoints.append((match[0], endpoint['address']))
    if endpoints[0][1] == endpoints[1][1]: raise ValueError('The two hosts need distinct observed addresses.')
    with tempfile.TemporaryDirectory(prefix='network-labs-https-') as folder:
        cert, key = certificate(folder, endpoints[1][1])
        worker = Path(__file__).with_name('https_demo_worker.py').read_text()
        argv = ['ip', 'netns', 'exec', namespace(state['spec'], endpoints[1][0]), sys.executable, '-I', '-c', worker,
                endpoints[1][1], endpoints[0][1], str(cert), str(key), '443']
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                if not selector.select(timeout=3): raise RuntimeFailure('HTTPS demo responder did not become ready.')
                try: ready = json.loads(process.stdout.readline())
                except ValueError as error: raise RuntimeFailure('HTTPS responder readiness unavailable.') from error
            if ready.get('status') != 'ready' or ready.get('port') != 443:
                raise RuntimeFailure('HTTPS responder could not bind the node address on TCP/443.')
            result = probe(manager, client, endpoints[1][1], protocol='https', ca_pem=load_ca(cert))
            response = {'status': 'unknown'}
            if result['status'] == 'passed':
                output, _ = process.communicate(timeout=5)
                try: response = json.loads(output.strip())
                except ValueError: pass
            status = result['status'] if result['status'] != 'passed' else 'passed' if response.get('status') == 'responded' and process.returncode == 0 else 'unknown'
            return {'lab': manager.name, 'client': client, 'server': server, 'status': status, 'probe': result,
                    'responder': response, 'temporary': True, 'configuration_changed': False,
                    'scope': 'Temporary host-Python TLS responder in the managed network namespace. A generated certificate is trusted only for this demo; no public CA, persistent service, guest trust-store update or saved key.'}
        except subprocess.TimeoutExpired as error:
            raise RuntimeFailure('HTTPS demo responder deadline reached.') from error
        finally:
            if process.poll() is None:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            process.communicate()


def render(report):
    from .service_probe import render as render_probe
    return ('HTTPS éducatif temporaire : ' + report['server'] + '\n' + render_probe(report['probe']) +
            '\nCertificat de démonstration explicitement approuvé, pas de CA publique. Aucun service permanent.\nRésultat global : ' + report['status'])
