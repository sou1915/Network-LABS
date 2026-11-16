"""Pinned Linux link events for a finite controlled-port authorization."""
import fcntl
import select
import socket
import struct


class LinkLost(Exception):
    """The controlled interface lost administrative state or carrier."""


class LinkMonitor:
    def __init__(self, config, interface_socket):
        self.port=config['port'];self.index=config['ifindex'];self.interface_socket=interface_socket
        self.events=None

    def __enter__(self):
        self.events=socket.socket(socket.AF_NETLINK,socket.SOCK_RAW,socket.NETLINK_ROUTE)
        try:
            self.events.bind((0,1))  # RTMGRP_LINK, in the already pinned NAS namespace.
            self.events.setblocking(False)
            self.check()
        except BaseException:
            self.events.close();raise
        return self

    def __exit__(self,*_):
        self.events.close()

    def check(self):
        # Subscribe before sampling. A queued down/up pair must revoke the old
        # authorization even when the current flags have already recovered.
        for _ in range(64):
            if not select.select([self.events],[],[],0)[0]:break
            data,_,flags,sender=self.events.recvmsg(65536)
            if flags & socket.MSG_TRUNC or sender[0]!=0:raise ValueError('Unconfirmed link events')
            self.inspect(data)
        else:raise ValueError('Link event budget exceeded')
        request=struct.pack('16sH14x',self.port.encode(),0)
        flags=struct.unpack_from('H',fcntl.ioctl(self.interface_socket,0x8913,request),16)[0]  # SIOCGIFFLAGS
        if flags & 0x41 != 0x41:raise LinkLost  # IFF_UP and IFF_RUNNING

    def inspect(self,data):
        offset=0
        while offset<len(data):
            if len(data)-offset<16:raise ValueError('Truncated link event')
            size,kind,_,_,_=struct.unpack_from('=IHHII',data,offset)
            if size<16 or offset+size>len(data):raise ValueError('Invalid link event length')
            if kind in (2,4):raise ValueError('Link event stream lost')  # NLMSG_ERROR/OVERRUN
            if kind in (16,17):  # RTM_NEWLINK/DELLINK
                if size<32:raise ValueError('Truncated interface event')
                _,_,_,index,flags,_=struct.unpack_from('=BBHiII',data,offset+16)
                if index==self.index and (kind==17 or flags & 0x41 != 0x41):raise LinkLost
            offset+=(size+3)&~3
