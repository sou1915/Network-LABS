"""Kernel cgroup high-water proof and a 20-node headless memory checkpoint."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import patch
from network_labs.appliances.benchmark import benchmark,wait_ready,CGROUP_ROOT
from network_labs.appliances.examples import enterprise
from network_labs.appliances.firewall import fingerprint
from network_labs.appliances.runtime import run,static_busybox_rootfs
from network_labs.appliances.spec import example,prefix,MIB
from test_native_integration import unexpected_host_link_changes


@unittest.skipUnless(os.environ.get('NETWORK_LABS_NATIVE_TESTS')=='1','Opt-in privileged native test')
class NativeBenchmarkPeakTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.geteuid(),0)
        for tool in ('busybox','crun','ip','nft'):self.assertIsNotNone(shutil.which(tool),tool)
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.rootfs=static_busybox_rootfs(shutil.which('busybox'),self.root/'rootfs')
        self.namespaces=run(['ip','netns','list']).stdout
        self.links={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        self.routes={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout for fam in ('-4','-6') for kind in ('route','rule')}
        self.forwarding={key:run(['sysctl','-n',key]).stdout for key in ('net.ipv4.ip_forward','net.ipv6.conf.all.forwarding')}
        self.rules=fingerprint(json.loads(run(['nft','-j','-n','list','ruleset']).stdout))

    def tearDown(self):
        self.assertEqual(run(['ip','netns','list']).stdout,self.namespaces)
        for (fam,kind),value in self.routes.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        for key,value in self.forwarding.items():self.assertEqual(run(['sysctl','-n',key]).stdout,value)
        self.assertEqual(fingerprint(json.loads(run(['nft','-j','-n','list','ruleset']).stdout)),self.rules)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        hardware={n for n,_ in after-self.links if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(self.links,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})

    def artifact(self,name,report):
        directory=os.environ.get('NETWORK_LABS_BENCHMARK_ARTIFACT_DIR')
        if directory:
            root=Path(directory);root.mkdir(parents=True,exist_ok=True)
            with (root/name).open('x') as output:json.dump(report,output,indent=2);output.write('\n')

    def check(self,spec,report):
        self.assertEqual(report['version'],2);self.assertTrue(report['cleanup_complete'])
        self.assertTrue(report['all_nodes_running_after_load']);self.assertTrue(report['load']['all_packets_received'])
        self.assertFalse(report['lab_cgroup_context']['existed_before_start'])
        self.assertIsNotNone(report['lab_cgroup_after_load']['memory_peak_bytes'],'This dedicated job requires kernel memory.peak support')
        self.assertTrue(report['assessment']['lab_cgroup_current_run_kernel_peak_under_target'])
        self.assertFalse(report['assessment']['oom_kill_observed'])
        self.assertEqual(report['assessment']['total_application_under_target'],'unverified')
        parent=CGROUP_ROOT/prefix(spec)
        if parent.exists():self.assertIn('populated 0',(parent/'cgroup.events').read_text())

    def test_presampling_transient_exceeds_phase_samples_but_is_caught_by_kernel(self):
        spec=example(self.rootfs);spec['name']='peak-burst-'+uuid.uuid4().hex[:12]
        spec['nodes'][0]['memory_mib']=64
        def burst(manager):
            wait_ready(manager)
            # Each tmpfs is capped at 8 MiB. Retain 6 MiB in each until both
            # allocations are charged, then free them before phase sampling.
            for path in ('/tmp/benchmark-burst','/run/benchmark-burst'):
                manager.crun('exec','PC1','/bin/busybox','dd','if=/dev/zero','of='+path,'bs=1048576','count=6')
            manager.crun('exec','PC1','/bin/busybox','rm','/tmp/benchmark-burst','/run/benchmark-burst')
        with patch('network_labs.appliances.benchmark.wait_ready',side_effect=burst):
            report=benchmark(spec,target='192.0.2.20',sources=['PC1'],seconds=2)
        self.check(spec,report)
        peak=report['lab_cgroup_after_load']['memory_peak_bytes']
        sampled=max(report['idle']['lab_cgroup_memory_sampled_peak_bytes'],report['load']['metrics']['lab_cgroup_memory_sampled_peak_bytes'])
        self.assertGreaterEqual(peak,12*MIB);self.assertGreater(peak-sampled,4*MIB)
        report['scope']='Presampling 12 MiB transient in owned-node tmpfs; not application memory or a throughput benchmark.'
        self.artifact('presampling-transient.json',report)

    def test_twenty_nodes_ten_seconds_each_phase_and_kernel_peak(self):
        spec=enterprise(self.rootfs);spec['name']='enterprise-peak-'+uuid.uuid4().hex[:12]
        # Match the existing native enterprise return-route control.
        next(n for n in spec['nodes'] if n['name']=='FW1')['routes'].append(
            {'destination':'10.10.10.2/32','gateway':'172.31.255.2','interface':'eth0'})
        report=benchmark(spec,target='198.51.100.10',seconds=10)
        self.check(spec,report)
        self.assertEqual(report['node_count'],20);self.assertEqual(len(report['load']['flows']),12)
        self.assertEqual(report['load']['requested_packets_per_source'],100)
        self.assertTrue(all(r['received']==100 for r in report['load']['flows']))
        report['scope']='Headless 20-node shared-kernel OCI reference, 10 seconds idle and 10 seconds bounded ICMP; no full-application 2 GiB or laptop certification.'
        self.artifact('enterprise-20-kernel-peak.json',report)
