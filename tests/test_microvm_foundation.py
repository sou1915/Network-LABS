"""Micro-VM resources reach the VMM; existing OCI quotas remain distinct."""
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from network_labs.appliances.microvm import example
from network_labs.appliances.spec import validate,example as oci_example
from network_labs.appliances.runtime import firecracker_config,plan
from network_labs.appliances.__main__ import main


class MicroVMFoundationTests(unittest.TestCase):
    def test_independent_vm_resources_and_disks_reach_firecracker(self):
        spec=example('/assets/kernel','/assets/base.ext4',vcpus=2,memory_mib=192)
        self.assertTrue(all(n['runtime']=='firecracker' for n in spec['nodes']))
        spec['nodes'][1]['vcpus']=3
        configs=[firecracker_config(n,Path(n['kernel']),Path('/private')/n['name']/'rootfs.ext4') for n in spec['nodes']]
        self.assertEqual([c['machine-config']['vcpu_count'] for c in configs],[2,3])
        self.assertTrue(all(c['machine-config']['mem_size_mib']==192 for c in configs))
        self.assertNotEqual(configs[0]['drives'][0]['path_on_host'],configs[1]['drives'][0]['path_on_host'])
        self.assertIn('ip=192.0.2.10',configs[0]['boot-source']['boot_args'])
        self.assertIn('ip=192.0.2.20',configs[1]['boot-source']['boot_args'])
        before=copy.deepcopy(spec)
        with patch('subprocess.run',side_effect=AssertionError('host mutation')):report=plan(spec)
        self.assertEqual(spec,before);self.assertEqual(report['allocated_vm_vcpus'],5)
        self.assertEqual(report['allocated_node_mib'],384)
        self.assertTrue(all(not n['exec'] for n in report['nodes']))

    def test_cpu_types_budget_and_oci_confusion_are_rejected(self):
        for value in (0,33,True,1.5,'2'):
            with self.subTest(value=value),self.assertRaises(ValueError):example('/kernel','/disk',vcpus=value)
        with self.assertRaises(ValueError):example('/kernel','/disk',memory_mib=1024)
        spec=oci_example('/rootfs');spec['nodes'][0]['vcpus']=2
        with self.assertRaisesRegex(ValueError,'micro-VM'):validate(spec)
        spec=example('/kernel','/disk');del spec['nodes'][0]['vcpus']
        self.assertEqual(validate(spec)['nodes'][0]['vcpus'],1)

    def test_cli_generates_manifest_without_installed_kvm_or_asset_reads(self):
        output=io.StringIO()
        with patch('sys.stdout',output),patch('subprocess.run',side_effect=AssertionError('host mutation')):
            self.assertEqual(main(['microvm-example','--kernel','/missing/kernel','--disk','/missing/disk','--vcpus','2']),0)
        spec=json.loads(output.getvalue());self.assertEqual(len(spec['nodes']),2)
        self.assertEqual(spec['nodes'][1]['vcpus'],2)
        self.assertEqual(spec['links'],[[['VM1','eth0'],['VM2','eth0']]])
