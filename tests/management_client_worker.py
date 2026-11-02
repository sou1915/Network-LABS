"""Bounded native-test clients; executed in a node's network namespace only."""
import json
from pathlib import Path
import socket
import sys
import time

mode, request = sys.argv[1], json.loads(sys.argv[2])
if mode == 'syslog':
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((request['address'], 514)); sock.settimeout(.25)
    Path(request['ready']).write_text('ready')
    rows = []; deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try: data, peer = sock.recvfrom(4096)
        except socket.timeout: continue
        rows.append({'text': data.decode(errors='replace'), 'source': peer[0]})
        if request['token'] in rows[-1]['text']: break
    sock.close(); print(json.dumps(rows))
elif mode == 'telnet':
    sock = socket.create_connection((request['address'], 23), timeout=3); sock.settimeout(.25)
    text = bytearray(); pending = bytearray()
    def read_until(marker, seconds=7):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if marker.encode() in text: return
            try: data = sock.recv(4096)
            except socket.timeout: continue
            if not data: raise RuntimeError('Telnet closed before ' + marker + ': ' + repr(bytes(text)))
            pending.extend(data)
            while pending:
                if pending[0] != 255:
                    text.append(pending.pop(0)); continue
                if len(pending) < 2: break
                code = pending[1]
                if code == 255:
                    text.append(255); del pending[:2]
                elif code in (251, 252, 253, 254):
                    if len(pending) < 3: break
                    option = pending[2]
                    if code in (251, 253): sock.sendall(bytes([255, 254 if code == 251 else 252, option]))
                    del pending[:3]
                elif code == 250:
                    end = pending.find(b'\xff\xf0', 2)
                    if end < 0: break
                    del pending[:end + 2]
                else: del pending[:2]
        raise RuntimeError('Telnet timeout before ' + marker + ': ' + repr(bytes(text)))
    read_until('login:')
    sock.sendall(b'lab\r\n'); read_until('Password:')
    sock.sendall(request['password'].encode() + b'\r\n')
    if request.get('reject'):
        read_until('Login incorrect'); print(json.dumps({'rejected': True}))
    else:
        # The marker is not contiguous in the echoed command, only its output.
        read_until('$ ')
        sock.sendall(b'/bin/busybox id -u; /bin/hostname; printf TELNET-%s-OK SESSION\r\n')
        read_until('TELNET-SESSION-OK')
        print(json.dumps({'output': text.decode(errors='replace')}))
    sock.close()
else: raise ValueError('Unknown management test client')
