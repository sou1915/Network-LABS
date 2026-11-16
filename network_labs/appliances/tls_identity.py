"""Bounded offline TLS exchange; no sockets or implicit trust configuration."""
import ssl


def handshake(server_context,client_context,server_hostname=None):
    incoming=[ssl.MemoryBIO(),ssl.MemoryBIO()];outgoing=[ssl.MemoryBIO(),ssl.MemoryBIO()]
    peers=[client_context.wrap_bio(incoming[0],outgoing[0],server_side=False,server_hostname=server_hostname),
           server_context.wrap_bio(incoming[1],outgoing[1],server_side=True)]
    finished=set()
    for _ in range(16):
        for index,peer in enumerate(peers):
            if index not in finished:
                try:peer.do_handshake();finished.add(index)
                except ssl.SSLWantReadError:pass
            if outgoing[index].pending:
                incoming[1-index].write(outgoing[index].read())
        if len(finished)==2:return peers
    raise ValueError('Offline TLS identity validation did not complete within its handshake budget.')
