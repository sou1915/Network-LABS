"""Real dual-NIC guest: separate fabrics, selective failure, no implicit routing, cold restore."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from network_labs.appliances.guest_image import build
from network_labs.appliances.guest_control import request
from network_labs.appliances.guest_startup import save_observed, observe, query
from network_labs.appliances.microvm import multinic_example
from network_labs.appliances.persistence import load_startup
from network_labs.appliances.runtime import Manager, process_identity


@unittest.skipUnless(os.environ.get('NETWORK_LABS_MICROVM_TESTS') == '1', 'Opt-in real KVM test')
class MultiNICGuestTests(unittest.TestCase):
    def test_independent_ports_isolation_and_restore(self):
        self.assertEqual(os.geteuid(), 0)
        self.assertTrue(Path('/dev/kvm').exists(), 'KVM required, no fallback')
        kernel=Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
        evidence=Path(os.environ.get('NETWORK_LABS_MICROVM_EVIDENCE','/tmp/network-labs-microvm-evidence'))/'multinic'
        evidence.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='nlmn-') as temporary:
            root=Path(temporary)
            build(shutil.which('busybox'),root/'base.ext4',with_agent=True)
            spec=multinic_example(kernel,root/'base.ext4')
            with patch('network_labs.appliances.runtime.STATE_ROOT',root/'state'), patch('network_labs.appliances.runtime.CONFIG_ROOT',root/'config'):
                manager=Manager(spec['name']);records=[];results={'probes':[]}
                with manager.locked():
                    try:
                        manager.start(spec);records.extend(manager.state['vms'])
                        sockets={n['name']:manager.directory/n['name']/'guest.vsock' for n in spec['nodes']}
                        # VM1 readiness/readback is required by multi-NIC startup.
                        results['addresses']=query(sockets['VM1'],'addresses')
                        fabric=json.loads(manager.ns(0,'ip','-j','link','show').stdout)
                        masters={item['ifname']:item.get('master') for item in fabric}
                        # Each tap is joined to its cable by a tc redirect each way (every frame crosses, LACP included).
                        for port in ('eth0','eth1'):
                            tap='tap'+port[3:]
                            self.assertIsNone(masters[tap])
                            self.assertIsNone(masters[port])
                            for here,there in ((tap,port),(port,tap)):
                                shown=manager.ns(0,'tc','filter','show','dev',here,'ingress').stdout
                                self.assertIn(f'Egress Redirect to device {there}',shown)
                        results['fabric']=masters
                        def probe(name,destination,expected):
                            result=request(sockets[name],'ping',destination=destination)
                            results['probes'].append({'source':name,'destination':destination,**result})
                            self.assertEqual(result['exit_code']==0,expected,result)
                        # Wait for endpoint agents without changing their network state.
                        import time
                        for name in ('VM2','VM3'):
                            deadline=time.monotonic()+40
                            while True:
                                try: query(sockets[name],'ready');break
                                except (ValueError,OSError):
                                    if time.monotonic()>=deadline:raise
                                    time.sleep(.1)
                        probe('VM1','192.0.2.20',True);probe('VM1','198.51.100.20',True)
                        probe('VM2','192.0.2.10',True);probe('VM3','198.51.100.10',True)
                        query(sockets['VM2'],'route-add',network='198.51.100.0/24',gateway='192.0.2.10')
                        query(sockets['VM3'],'route-add',network='192.0.2.0/24',gateway='198.51.100.10')
                        probe('VM2','198.51.100.20',False);probe('VM3','192.0.2.20',False)
                        query(sockets['VM1'],'link',interface='eth1',state='down')
                        probe('VM3','198.51.100.10',False);probe('VM2','192.0.2.10',True)
                        query(sockets['VM1'],'link',interface='eth1',state='up')
                        query(sockets['VM1'],'address-delete',interface='eth1',cidr='198.51.100.10/24')
                        probe('VM3','198.51.100.10',False);probe('VM2','192.0.2.10',True)
                        query(sockets['VM1'],'address-add',interface='eth1',cidr='198.51.100.10/24')
                        probe('VM3','198.51.100.10',True)
                        results['saved']=save_observed(manager)
                        restored=load_startup(manager.name)
                        for name in sockets: shutil.copyfile(manager.directory/name/'console.log',evidence/(name+'-before-restart.log'))
                        manager.stop()
                        for record in records:self.assertNotEqual(process_identity(record['pid']),record['starttime'])
                        manager=Manager(spec['name']);manager.start(restored);records.extend(manager.state['vms'])
                        results['restored_profiles']={n['name']:observe(sockets[n['name']],n) for n in restored['nodes']}
                        results['restored_addresses']=query(sockets['VM1'],'addresses')
                        probe('VM1','192.0.2.20',True);probe('VM1','198.51.100.20',True)
                        probe('VM2','198.51.100.20',False)
                        results['cold_restore_passed']=True
                        (evidence/'result.json').write_text(json.dumps(results,indent=2))
                    finally:
                        for name in ('VM1','VM2','VM3'):
                            console=manager.directory/name/'console.log'
                            if console.exists():shutil.copyfile(console,evidence/(name+'.log'))
                        if manager.directory.exists():manager.stop()
                for record in records:self.assertNotEqual(process_identity(record['pid']),record['starttime'])
                self.assertFalse(manager.directory.exists())
                (evidence/'cleanup.txt').write_text('All owned VMMs and private lab resources removed.\n')
