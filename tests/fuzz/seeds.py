"""Seed inputs for agent_fuzz.c: one well-formed message per handler (first byte: the handler, second: the state)."""
import socket
import struct


def checksum(data):
    if len(data) % 2:
        data += b'\0'
    total = sum(struct.unpack(f'!{len(data) // 2}H', data))
    while total >> 16:
        total = (total & 0xffff) + (total >> 16)
    return ~total & 0xffff


def ipv4(protocol, source, destination, payload, ttl=1):
    header = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(payload), 0, 0, ttl, protocol, 0, socket.inet_aton(source),
                         socket.inet_aton(destination))
    header = header[:10] + struct.pack('!H', checksum(header)) + header[12:]
    return b'\x01\x00\x5e\x00\x00\x02' + b'\x00\x00\x0c\x07\xac\x01' + b'\x08\x00' + header + payload


def hsrp_v1(state=16, priority=120, op=0):
    message = struct.pack('!BBBBBBBB8s4s', 0, op, state, 3, 10, priority, 1, 0, b'cisco\0\0\0', socket.inet_aton('192.168.1.1'))
    udp = struct.pack('!HHHH', 1985, 1985, 8 + len(message), 0) + message
    return ipv4(17, '192.168.1.3', '224.0.0.2', udp)


def hsrp_v2(state=6, priority=120, op=0):
    group = struct.pack('!BBBBBBH6sIII16s', 1, 40, 2, op, state, 4, 4095, b'\x00\x00\x0c\x9f\xff\xff', priority, 1000, 4000,
                        socket.inet_aton('10.0.0.1') + bytes(12))
    auth = struct.pack('!BB8s', 3, 8, b'lab\0\0\0\0\0')
    message = group + auth
    udp = struct.pack('!HHHH', 1985, 1985, 8 + len(message), 0) + message
    return ipv4(17, '10.0.0.3', '224.0.0.102', udp)


def seeds():
    found = {
        'hsrp-v1-active': b'\0\4' + hsrp_v1(), 'hsrp-v1-coup': b'\0\4' + hsrp_v1(op=1), 'hsrp-v1-standby': b'\0\3' + hsrp_v1(state=8),
        'hsrp-v2-active': b'\1\4' + hsrp_v2(), 'hsrp-v2-resign': b'\1\2' + hsrp_v2(op=2),
        'guard-frame': b'\2\0' + b'\xff' * 6 + b'\x02\x00\x00\x00\x00\x09\x08\x06' + bytes(28),
        'guard-bpdu': b'\2\1' + b'\x01\x80\xc2\x00\x00\x00\x02\x00\x00\x00\x00\x09\x00\x26' + bytes(38),
        'syslog': b'\3\0<34>Oct 11 22:14:15 R1 %LINK-3-UPDOWN: Interface eth0, changed state to up',
        'tftp-read': b'\4\0\0\1config.txt\0octet\0', 'tftp-write': b'\4\0\0\2backup-r1.cfg\0NETASCII\0',
        'hsrp-spec': b'\x05\0eth0/1/1/192.168.1.1/110/y/3/10/636973636f',
        'vrrp-spec': b'\x05\1eth0.20/12/10.0.20.254/100/y/1/-', 'vrrp-owner-password': b'\x05\5eth1/7/10.0.0.254/120/n/2/736563726574',
        'guard-spec': b'\x05\2eth3/3/r/y/n/10/020000000001',
        'services': b'\x06\0dns a:www.lab=192.0.2.10 cname:web=www.lab ntp:3 syslog tftp sync:192.0.2.1',
        'bgp': b'\x07\0' + b'65001 1.1.1.1 10.0.0.2:65002,10.0.1.2:65003 10.1.0.0/24,10.2.0.0/16',
        'eigrp': b'\x07\1' + b'100 1.1.1.1 10.0.0.0/24,10.1.0.0/24 eth1',
        'ospf': b'\x07\2' + b'1.1.1.1 10 40 eth0:0:10,eth1:0:10',
        'rip': b'\x07\3' + b'1.1.1.1 2 eth0,eth1',
    }
    return found
