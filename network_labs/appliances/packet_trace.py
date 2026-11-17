"""Follow one real ping across the lab: record every link while it travels, then list what each wire carried.

trace() takes a snapshot of the running lab, records each link at once (one bounded capture per link, which
holds the lab lock only while it starts), sends one echo request from SOURCE, and reads the captures:
for each ICMP echo frame, the link it crossed, its 802.1Q tag and the addresses on the wire (so NAT
rewrites show up hop by hop). Nothing is inferred: a link that carried nothing has no hop.
"""
from concurrent.futures import ThreadPoolExecutor
import ipaddress
from pathlib import Path
import struct
import tempfile
import threading

MAX_LINKS = 16
EXPRESSION = 'icmp or (vlan and icmp)'


def parse_icmp(path):
    """ICMP echo frames of a classic Ethernet PCAP: [{time, vlan, source, destination, type, id, seq}]."""
    data = Path(path).read_bytes()
    if len(data) < 24:
        return []
    endian = {b'\xd4\xc3\xb2\xa1': '<', b'\xa1\xb2\xc3\xd4': '>', b'\x4d\x3c\xb2\xa1': '<', b'\xa1\xb2\x3c\x4d': '>'}.get(data[:4])
    if endian is None:
        return []
    nano = data[:4] in (b'\x4d\x3c\xb2\xa1', b'\xa1\xb2\x3c\x4d')
    frames, offset = [], 24
    while offset + 16 <= len(data):
        seconds, fraction, included, _ = struct.unpack(endian + 'IIII', data[offset:offset + 16])
        frame = data[offset + 16:offset + 16 + included]
        offset += 16 + included
        if len(frame) < 14:
            continue
        kind, cursor, vlan = struct.unpack('!H', frame[12:14])[0], 14, None
        if kind == 0x8100 and len(frame) >= 18:
            vlan = struct.unpack('!H', frame[14:16])[0] & 0x0fff
            kind, cursor = struct.unpack('!H', frame[16:18])[0], 18
        if kind != 0x0800 or len(frame) < cursor + 20:
            continue
        header = (frame[cursor] & 0x0f) * 4
        if frame[cursor + 9] != 1 or len(frame) < cursor + header + 8:
            continue
        icmp = frame[cursor + header:cursor + header + 8]
        if icmp[0] not in (0, 8):
            continue
        frames.append({'time': seconds + fraction / (1e9 if nano else 1e6), 'vlan': vlan,
                       'source': str(ipaddress.IPv4Address(frame[cursor + 12:cursor + 16])),
                       'destination': str(ipaddress.IPv4Address(frame[cursor + 16:cursor + 20])),
                       'type': 'request' if icmp[0] == 8 else 'reply', 'id': struct.unpack('!H', icmp[4:6])[0],
                       'seq': struct.unpack('!H', icmp[6:8])[0]})
    return frames


def hops(links, captures):
    """Order the frames of every link in time: [{link, endpoints, time_ms, vlan, source, destination, type}]."""
    found = []
    for index, frames in captures.items():
        seen = set()
        for frame in frames:
            key = (frame['type'], frame['id'], frame['seq'])
            if key in seen:
                continue  # one crossing per link and direction is enough to follow the packet
            seen.add(key)
            found.append(dict(frame, link=index, endpoints=links[index]))
    found.sort(key=lambda hop: hop['time'])
    start = found[0]['time'] if found else 0
    return [{'link': h['link'], 'endpoints': h['endpoints'], 'time_ms': round((h['time'] - start) * 1000, 3), 'vlan': h['vlan'],
             'source': h['source'], 'destination': h['destination'], 'type': h['type']} for h in found]


def trace(lab, source, destination, seconds=6):
    """Record every link while SOURCE pings DESTINATION once (no lab lock held while recording)."""
    from .capture import capture
    from .runtime import Manager, RuntimeFailure
    destination = str(ipaddress.IPv4Address(destination))
    with Manager(lab).locked() as manager:
        spec = manager.read()['spec']
    links = spec['links'][:MAX_LINKS]
    if not any(source == endpoint[0] for link in links for endpoint in link):
        raise RuntimeFailure(f'{source} has no cabled port to send from.')
    with tempfile.TemporaryDirectory(prefix='nl-trace-') as folder, ThreadPoolExecutor(max(1, len(links))) as pool:
        readies, futures = [], []
        for index, link in enumerate(links):
            ready = threading.Event()
            node, port = link[0]
            futures.append(pool.submit(capture, Manager(lab), node, port, Path(folder) / f'{index}.pcap', seconds=seconds, packets=8,
                                       expression=EXPRESSION, ready=ready.set))
            readies.append(ready)
        for ready, future in zip(readies, futures):
            while not ready.wait(0.2):
                if future.done():
                    future.result()  # a capture that failed to start reports why
                    break
        with Manager(lab).locked() as manager:
            ping = manager.ping_node(source, destination, count=1)
        captures = {}
        for index, future in enumerate(futures):
            future.result(timeout=seconds + 15)
            captures[index] = parse_icmp(Path(folder) / f'{index}.pcap')
    return {'source': source, 'destination': destination, 'answered': ping['replies'][0]['ok'], 'hops': hops(links, captures)}
