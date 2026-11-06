"""Kernel link-event decoding and fail-closed observation boundaries."""
import socket
import struct
import unittest
from unittest.mock import Mock,patch
from network_labs.appliances.dot1x_link import LinkLost,LinkMonitor


def event(index=7,flags=0x41,kind=16):
    return struct.pack('=IHHII',32,kind,0,0,0)+struct.pack('=BBHiII',0,0,1,index,flags,0xffffffff)


class LinkMonitorTests(unittest.TestCase):
    def monitor(self):return LinkMonitor({'port':'eth0','ifindex':7},Mock())

    def test_pinned_interface_down_delete_and_queued_down_up_revoke(self):
        monitor=self.monitor()
        monitor.inspect(event()+event(index=8,flags=0)+event(kind=3))
        for value in (event(flags=1),event(flags=0x40),event(kind=17),event(flags=0)+event()):
            with self.subTest(value=value),self.assertRaises(LinkLost):monitor.inspect(value)

    def test_truncation_errors_and_overrun_are_not_silently_accepted(self):
        monitor=self.monitor()
        for value in (b'x',event()[:-1],struct.pack('=IHHII',0,16,0,0,0),event(kind=2),event(kind=4)):
            with self.subTest(value=value),self.assertRaises(ValueError):monitor.inspect(value)

    def test_subscription_precedes_snapshot_and_closes_after_initial_carrier_loss(self):
        monitor=self.monitor();events=Mock()
        with patch('socket.socket',return_value=events),patch('select.select',return_value=([],[],[])),patch('fcntl.ioctl',return_value=struct.pack('16sH14x',b'eth0',1)) as ioctl:
            with self.assertRaises(LinkLost):monitor.__enter__()
        events.bind.assert_called_once_with((0,1));events.close.assert_called_once()
        self.assertEqual(ioctl.call_args.args[1],0x8913)

    def test_recovered_snapshot_cannot_hide_queued_loss_and_event_loss_fails_closed(self):
        for data,flags,sender,error in ((event(flags=0)+event(),0,(0,1),LinkLost),(event(),socket.MSG_TRUNC,(0,1),ValueError),(event(),0,(123,1),ValueError)):
            monitor=self.monitor();monitor.events=Mock();monitor.events.recvmsg.return_value=(data,[],flags,sender)
            with patch('select.select',return_value=([monitor.events],[],[])),patch('fcntl.ioctl') as ioctl:
                with self.assertRaises(error):monitor.check()
                ioctl.assert_not_called()

    def test_unrelated_events_and_healthy_snapshot_do_not_revoke(self):
        monitor=self.monitor();monitor.events=Mock();monitor.events.recvmsg.return_value=(event(index=8,flags=0),[],0,(0,1))
        with patch('select.select',side_effect=[([monitor.events],[],[]),([],[],[])]),patch('fcntl.ioctl',return_value=struct.pack('16sH14x',b'eth0',0x41)):
            monitor.check()

    def test_event_flood_exhausts_bounded_budget(self):
        monitor=self.monitor();monitor.events=Mock();monitor.events.recvmsg.return_value=(event(index=8),[],0,(0,1))
        with patch('select.select',return_value=([monitor.events],[],[])),self.assertRaises(ValueError):monitor.check()
        self.assertEqual(monitor.events.recvmsg.call_count,64)
