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
        self.assertNotEqual(configs[0]['vsock']['uds_path'], configs[1]['vsock']['uds_path'])
        self.assertEqual(configs[0]['vsock']['guest_cid'], 3)
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

    def test_multinic_manifest_and_distinct_vmm_taps(self):
        from network_labs.appliances.microvm import multinic_example
        spec=multinic_example('/kernel','/disk');node=spec['nodes'][0]
        config=firecracker_config(node,Path('/kernel'),Path('/disk'))
        self.assertEqual(config['network-interfaces'],[{'iface_id':'eth0','host_dev_name':'tap0'},{'iface_id':'eth1','host_dev_name':'tap1'}])
        for interfaces in ({'eth0':'192.0.2.10/24','eth2':'198.51.100.10/24'}, {'eth0':'192.0.2.10/24','eth1':'192.0.2.11/24'}):
            bad=copy.deepcopy(spec);bad['nodes'][0]['interfaces']=interfaces
            with self.assertRaises(ValueError):validate(bad)

    def test_total_vcpus_are_budgeted(self):
        from network_labs.appliances.microvm import multinic_example
        spec=multinic_example('/kernel','/disk')
        for node in spec['nodes']:node['vcpus']=32
        with self.assertRaisesRegex(ValueError,'vCPU'):validate(spec)
        spec['budget_vcpus']=96
        self.assertEqual(plan(spec)['budget_vcpus'],96)
        for value in (0,1025,True,'8'):
            spec['budget_vcpus']=value
            with self.subTest(value=value),self.assertRaises(ValueError):validate(spec)
        self.assertNotIn('budget_vcpus',validate(example('/kernel','/disk')))

    def test_jailer_command_drops_privileges_and_caps_the_vmm(self):
        from network_labs.appliances.runtime import jailer_command,jailer_path,VM_UID_BASE
        from network_labs.appliances.spec import namespace,prefix
        spec=example('/kernel','/disk',vcpus=2,memory_mib=192)
        command=jailer_command(spec,spec['nodes'][1],1,'/usr/bin/jailer','/usr/bin/firecracker',Path('/private/VM2/jail'),VM_UID_BASE+257)
        pairs=dict(zip(command[1:command.index('--')][::2],command[1:command.index('--')][1::2]))
        self.assertEqual((pairs['--uid'],pairs['--gid'],pairs['--id']),(str(VM_UID_BASE+257),str(VM_UID_BASE+257),'vm1'))
        self.assertEqual(pairs['--netns'],'/run/netns/'+namespace(spec,1))
        self.assertEqual(pairs['--parent-cgroup'],'network-labs/'+prefix(spec))
        self.assertIn('memory.max='+str((192+128)*1024*1024),command);self.assertIn('cpu.max=200000 100000',command)
        self.assertEqual(command[command.index('--'):],['--','--no-api','--config-file','/firecracker.json'])
        self.assertNotIn('--cgroup',jailer_command(spec,spec['nodes'][0],0,'/j','/f',Path('/b'),VM_UID_BASE,cgroup=False))
        with patch.dict('os.environ',{'NETWORK_LABS_VM_JAILER':'0'}),patch('shutil.which',return_value='/usr/bin/jailer'):self.assertIsNone(jailer_path())
        with patch.dict('os.environ',{},clear=True),patch('shutil.which',return_value='/usr/bin/jailer'):self.assertEqual(jailer_path(),'/usr/bin/jailer')

    def test_each_running_lab_gets_its_own_vmm_uid_block(self):
        import tempfile
        from network_labs.appliances.runtime import allocate_vm_uid_base,VM_UID_BASE,VM_UID_BLOCK
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);(root/'vm-uids.lock').touch()
            self.assertEqual(allocate_vm_uid_base(root,'a'),VM_UID_BASE)
            (root/'a').mkdir();(root/'a'/'state.json').write_text(json.dumps({'vm_uid_base':VM_UID_BASE}))
            self.assertEqual(allocate_vm_uid_base(root,'a'),VM_UID_BASE)
            self.assertEqual(allocate_vm_uid_base(root,'b'),VM_UID_BASE+VM_UID_BLOCK)
            (root/'c').mkdir();(root/'c'/'state.json').write_text(json.dumps({'vm_uid_base':VM_UID_BASE+VM_UID_BLOCK}))
            self.assertEqual(allocate_vm_uid_base(root,'b'),VM_UID_BASE+2*VM_UID_BLOCK)
            # A lab without a recorded block (older runtime, or state not yet written) may hold the first one.
            (root/'a'/'state.json').write_text('{}');(root/'d').mkdir()
            self.assertEqual(allocate_vm_uid_base(root,'b'),VM_UID_BASE+2*VM_UID_BLOCK)
            (root/'c'/'state.json').unlink()
            self.assertEqual(allocate_vm_uid_base(root,'b'),VM_UID_BASE+VM_UID_BLOCK)

    def test_stop_keeps_lab_state_while_a_vmm_survives_sigkill(self):
        import tempfile
        from network_labs.appliances import runtime
        with tempfile.TemporaryDirectory() as root:
            manager=runtime.Manager('lab');manager.directory=Path(root)/'lab';manager.directory.mkdir()
            state={'spec':example('/kernel','/disk'),'vms':[{'name':'VM1','pid':4242,'starttime':'77','jailed':False}],
                   'containers':[],'namespaces':['nlxn0'],'host_links':[],'mounts':[]}
            (manager.directory/'state.json').write_text(json.dumps(state))
            with patch.object(runtime,'process_identity',return_value='77'),patch.object(runtime.os,'kill') as kill, \
                 patch.object(runtime.os,'waitpid',side_effect=ChildProcessError),patch.object(runtime.time,'sleep'), \
                 patch.object(runtime,'run',side_effect=AssertionError('fabric removed under a live VMM')), \
                 patch('network_labs.appliances.dot1x.stop'),patch('network_labs.appliances.dot1x_supplicant.stop'), \
                 patch('network_labs.appliances.stp_carrier.stop'):
                with self.assertRaisesRegex(runtime.RuntimeFailure,'VMM VM1 .pid 4242. is still running'):manager.stop()
            kill.assert_called_once_with(4242,runtime.signal.SIGKILL)
            self.assertEqual(json.loads((manager.directory/'state.json').read_text()),state)
