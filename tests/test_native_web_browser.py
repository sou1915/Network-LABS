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
            self.assertEqual(window.config_vars['name'].get(),'BROWSER3')
            self.assertEqual(window.config_vars['address'].get(),'192.168.20.33/24')
        finally:root.destroy()
