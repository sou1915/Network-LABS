"""Bounded real Telnet test peer; credentials arrive on stdin, never argv."""
import json
from pathlib import Path
import socket
import sys
import time

request = json.load(sys.stdin)
text = bytearray(); pending = bytearray(); closed = False
sock = socket.create_connection((request['address'], 23), timeout=3)
sock.settimeout(.1)
deadline = time.monotonic() + 10


def receive():
    global closed
    try: data = sock.recv(4096)
    except socket.timeout: return
    except ConnectionResetError: data = b''
    if not data:
        closed = True; return
    pending.extend(data)
    while pending:
        if pending[0] != 255:
            text.append(pending.pop(0))
            if len(text) > 16384: raise RuntimeError('Telnet output budget exceeded')
            continue
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


def wait_for(marker):
    while time.monotonic() < deadline and not closed:
        if marker in text: return True
        receive()
    if not closed: raise RuntimeError('Telnet prompt deadline exceeded')
    return False


def send(value):
    sock.sendall(value.encode().replace(b'\xff', b'\xff\xff') + b'\r\n')


try:
    if wait_for(b'RADIUS action '):
        if request.get('ready'):
            Path(request['ready']).write_text('ready')
            while not Path(request['release']).exists() and time.monotonic() < deadline: time.sleep(.02)
        if request.get('disconnect'):
            sock.close(); closed = True
        else:
            send(request['action'])
            if wait_for(b'RADIUS username: '):
                send(request['username'])
                if wait_for(b'RADIUS password: '):
                    send(request['password'])
                    if request.get('shell_script') is not None and wait_for(b'$ '):
                        script = request['shell_script'].replace('\n', '\r\n').encode().replace(b'\xff', b'\xff\xff')
                        sock.sendall(script)
                        if request.get('disconnect_marker'):
                            if not wait_for(request['disconnect_marker'].encode()):
                                raise RuntimeError('Shell disconnect marker unavailable')
                            sock.close(); closed = True
            while not closed and time.monotonic() < deadline: receive()
            if not closed: raise RuntimeError('Telnet did not close after one diagnostic')
    print(json.dumps({'output': text.decode(errors='replace'), 'closed': closed}))
finally:
    sock.close()
