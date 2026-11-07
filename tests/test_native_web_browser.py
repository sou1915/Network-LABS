"""Opt-in actual browser → loopback HTTP → Tk native draft acceptance."""
import os
from pathlib import Path
import subprocess
import time
import unittest


@unittest.skipUnless(os.environ.get('NETWORK_LABS_BROWSER_TESTS')=='1','opt-in Chromium/Playwright acceptance')
class NativeWebBrowserTests(unittest.TestCase):
    def test_browser_changes_native_draft_and_recovers_from_invalid_edit(self):
        import tkinter as tk
        from network_labs.__main__ import App
        from network_labs.appliances.campus import campus_example
        from network_labs.appliances.web_management import NativeDeviceAPI
        from network_labs.web_portal import WebPortal
        root=tk.Tk()
        try:
            app=App(root);root.geometry('1280x720');window=app.open_native_lab();window.load_spec(campus_example('/tmp/rootfs'))
            window.web_portal=portal=WebPortal(window,api=NativeDeviceAPI(window),native=True)
            env={**os.environ,'NATIVE_WEB_CLIENT_URL':portal.url('PC3'),'NATIVE_WEB_FIREWALL_URL':portal.url('FW1')}
            with subprocess.Popen(['node',str(Path(__file__).resolve().parents[1]/'tools/native_web_browser_smoke.cjs')],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT) as browser:
                deadline=time.monotonic()+50
                while browser.poll() is None and time.monotonic()<deadline:root.update();time.sleep(.01)
                if browser.poll() is None:browser.terminate()
                output=browser.communicate(timeout=5)[0].decode()
                self.assertEqual(browser.returncode,0,output)
            nodes={n['name']:n for n in window.manifest()['nodes']}
            self.assertEqual(nodes['BROWSER3']['interfaces']['eth0'],'192.168.20.33/24')
            self.assertEqual(len(nodes['FW1']['firewall']['rules']),2)
            self.assertEqual(nodes['FW1']['firewall']['nat'][0]['type'],'masquerade')
            self.assertEqual(nodes['SW1']['svis']['vlan40']['address'],'192.168.40.1/24')
            self.assertEqual(nodes['SRV1']['dns_server']['records'],{'srv.lab.test':'172.16.0.10'})
            self.assertEqual(nodes['SW1']['spanning_tree']['mode'],'stp')
            self.assertEqual(nodes['SW1']['lldp']['ports'],['eth0'])
            self.assertEqual(nodes['SW1']['port_security']['eth1']['mac_addresses'],['02:00:00:00:00:11'])
        finally:root.destroy()


    def test_browser_stp_component_and_paired_lacp(self):
        import tkinter as tk
        from network_labs.__main__ import App
        from network_labs.appliances.examples import lacp_lab
        from network_labs.appliances.web_management import NativeDeviceAPI
        from network_labs.web_portal import WebPortal
        root=tk.Tk()
        try:
            app=App(root);root.geometry('1280x720');window=app.open_native_lab();window.load_spec(lacp_lab('/tmp/rootfs'))
            window.web_portal=portal=WebPortal(window,api=NativeDeviceAPI(window),native=True)
            env={**os.environ,'NATIVE_WEB_SWITCH_URL':portal.url('SW1')}
            with subprocess.Popen(['node',str(Path(__file__).resolve().parents[1]/'tools/native_switch_browser_smoke.cjs')],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT) as browser:
                deadline=time.monotonic()+45
                while browser.poll() is None and time.monotonic()<deadline:root.update();time.sleep(.01)
                if browser.poll() is None:browser.terminate()
                output=browser.communicate(timeout=5)[0].decode();self.assertEqual(browser.returncode,0,output)
            nodes={n['name']:n for n in window.manifest()['nodes']}
            for name in ('SW1','SW2'):
                self.assertEqual(nodes[name]['spanning_tree']['mode'],'stp')
                self.assertEqual(nodes[name]['port_channels']['bond1']['min_links'],2)
            self.assertEqual(nodes['SW2']['port_channels']['bond1']['mode'],'passive')
        finally:root.destroy()

    def test_browser_access_security_configuration_and_dependencies(self):
        import tkinter as tk
        from network_labs.__main__ import App
        from network_labs.appliances.access_security import access_security_example
        from network_labs.appliances.web_management import NativeDeviceAPI
        from network_labs.web_portal import WebPortal
        root=tk.Tk()
        try:
            app=App(root);root.geometry('1280x720');window=app.open_native_lab();window.load_spec(access_security_example('/tmp/rootfs'))
            window.web_portal=portal=WebPortal(window,api=NativeDeviceAPI(window),native=True)
            env={**os.environ,'NATIVE_WEB_ADMISSION_URL':portal.url('SW1')}
            with subprocess.Popen(['node',str(Path(__file__).resolve().parents[1]/'tools/native_admission_browser_smoke.cjs')],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT) as browser:
                deadline=time.monotonic()+45
                while browser.poll() is None and time.monotonic()<deadline:root.update();time.sleep(.01)
                if browser.poll() is None:browser.terminate()
                output=browser.communicate(timeout=5)[0].decode();self.assertEqual(browser.returncode,0,output)
            switch=next(n for n in window.manifest()['nodes'] if n['name']=='SW1')
            self.assertTrue(switch['dhcp_snooping']['enabled'])
            self.assertEqual(switch['arp_inspection']['vlans'],[10]);self.assertEqual(len(switch['arp_inspection']['bindings']),3)
            self.assertEqual(switch['ip_source_guard'],{'eth0':'ip-mac','eth2':'ip-mac'})
        finally:root.destroy()
