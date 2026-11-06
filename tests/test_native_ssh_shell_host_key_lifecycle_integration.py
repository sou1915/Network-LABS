"""Pinned journaled shell: real PTY, expiry, disconnect and complete accounting."""
import test_native_ssh_radius_shell as reference
import json
from pathlib import Path
from network_labs.appliances.runtime import run
from test_native_integration import unexpected_host_link_changes


class NativePinnedSSHShellLifecycleTests(reference.NativeSSHRadiusShellTests):
    PINNED_HOST_KEY=True

    def test_real_shell_pty_background_expiry_disconnect_accounting_and_restart(self):
        namespaces=run(['ip','netns','list']).stdout
        before={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        routes={(fam,kind):run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout
            for fam in ('-4','-6') for kind in ('route','rule')}
        sysctls={key:run(['sysctl','-n',key]).stdout for key in
            ('net.ipv4.ip_forward','net.ipv6.conf.all.forwarding','net.ipv4.ip_unprivileged_port_start')}
        super().test_real_shell_pty_background_expiry_disconnect_accounting_and_restart()
        self.assertEqual(run(['ip','netns','list']).stdout,namespaces)
        for (fam,kind),value in routes.items():self.assertEqual(run(['ip','-j',fam,kind,'show',*(['table','all'] if kind=='route' else [])]).stdout,value)
        for key,value in sysctls.items():self.assertEqual(run(['sysctl','-n',key]).stdout,value)
        after={(r['ifname'],r['ifindex']) for r in json.loads(run(['ip','-j','link','show']).stdout)}
        hardware={n for n,_ in after-before if (Path('/sys/class/net')/n/'device').exists()}
        self.assertEqual(unexpected_host_link_changes(before,after,hardware),{'removed_or_replaced':set(),'added_virtual':set()})
