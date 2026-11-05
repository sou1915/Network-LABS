"""Bounded managed IPv6 upstream graph and unchanged clockless invocation."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from network_labs.appliances.examples import ipv6_ntp_relay_lab
from network_labs.appliances.ntp_server import config_text,command
from network_labs.appliances.spec import validate
from network_labs.appliances.__main__ import main


class IPv6NTPRelayTests(unittest.TestCase):
    def test_reference_pins_upstream_source_and_separates_reference_from_relay(self):
        spec=ipv6_ntp_relay_lab('/rootfs');self.assertEqual(validate(spec),spec)
        relay=spec['nodes'][3];source=spec['nodes'][5]
        self.assertIn('server 2001:db8:40::40 iburst\n',config_text(relay))
        self.assertIn('bindacqaddress 2001:db8:20::20\n',config_text(relay))
        self.assertNotIn('local stratum',config_text(relay))
        self.assertIn('local stratum 10\n',config_text(source))
        self.assertIn('allow 2001:db8:20::20/128\n',config_text(source))
        self.assertIn('-x',command('ipv6'))
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['example','--ipv6-ntp-relay','--rootfs','/rootfs']),0)
        self.assertEqual(json.loads(output.getvalue()),spec)

    def test_unknown_non_ntp_unallowed_and_cyclic_upstreams_refuse(self):
        original=ipv6_ntp_relay_lab('/rootfs')
        for fault in ('unknown','non-ntp','acl','self','cycle','third-server','two-roots'):
            spec=copy.deepcopy(original);relay=spec['nodes'][3]['ntp_server'];source=spec['nodes'][5]['ntp_server']
            if fault=='unknown':relay['upstream']='2001:db8:99::99'
            if fault=='non-ntp':relay['upstream']='2001:db8:30::30'
            if fault=='acl':source['clients']=['2001:db8:10::10']
            if fault=='self':relay['upstream']='2001:db8:20::20'
            if fault=='cycle':source.pop('local_stratum');source['upstream']='2001:db8:20::20'
            if fault=='third-server':spec['nodes'][4]['ntp_server']={'interface':'eth0','family':'ipv6','local_stratum':10,'clients':['2001:db8:10::10']}
            if fault=='two-roots':relay.pop('upstream');relay['local_stratum']=10
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate(spec)
