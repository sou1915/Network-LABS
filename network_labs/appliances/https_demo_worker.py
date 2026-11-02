"""Temporary single-response TLS endpoint for a managed namespace demo."""
import json
import socket
import ssl
import sys
import time


def serve(address, allowed, certificate, key, port=443):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate, key)
    deadline = time.monotonic() + 10
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((address, port)); listener.listen(4)
        print(json.dumps({'status': 'ready', 'port': listener.getsockname()[1]}), flush=True)
        for _ in range(4):
            remaining = deadline - time.monotonic()
            if remaining <= 0: break
            listener.settimeout(remaining)
            raw, peer = listener.accept()
            with raw:
                if peer[0] != allowed: continue
                raw.settimeout(min(3, remaining))
                try:
                    with context.wrap_socket(raw, server_side=True) as channel:
                        request = b''
                        while b'\r\n\r\n' not in request and len(request) < 4096:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0: raise TimeoutError('Demo deadline reached')
                            channel.settimeout(min(3, remaining))
                            part = channel.recv(4096 - len(request))
                            if not part: break
                            request += part
                        if not request.startswith(b'HEAD / HTTP/1.0\r\n') or b'\r\n\r\n' not in request:
                            continue
                        channel.sendall(b'HTTP/1.0 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                        print(json.dumps({'status': 'responded'}), flush=True)
                        return
                except (ssl.SSLError, TimeoutError, ConnectionError):
                    continue  # The client's preliminary plain TCP connection is expected.
    raise TimeoutError('No valid HTTPS request before demo limit')


if __name__ == '__main__':
    try:
        serve(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]))
    except (OSError, ValueError) as error:
        print(json.dumps({'status': 'error', 'detail': str(error)[:300]}), flush=True)
        sys.exit(1)
