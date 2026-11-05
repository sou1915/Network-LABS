"""Strict pre-provisioned host trust combined with the real RADIUS denial suite."""
import json
from pathlib import Path
import unittest
import test_native_ssh_radius as reference
from network_labs.appliances.runtime import run
from test_native_integration import unexpected_host_link_changes


class NativePinnedSSHRadiusTests(reference.NativeSSHRadiusTests):
    PINNED_HOST_KEY=True

    def test_real_ssh_radius_actions_denials_outages_protected_bridge_and_restart(self):
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        baseline={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout
            for fam in ('-4','-6') for kind in ('route','rule')}
        super().test_real_ssh_radius_actions_denials_outages_protected_bridge_and_restart()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in baseline.items():
            self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
