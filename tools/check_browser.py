"""Optional live browser smoke test. Run under DISPLAY / xvfb-run; see docs/WEB.md."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import tkinter as tk
from network_labs.__main__ import App
from network_labs.web_portal import WebPortal

root=tk.Tk()
process=None
try:
    app=App(root);app.replace_lab(App.service_demo);root.withdraw()
    app.web_portal=portal=WebPortal(app)
    output=Path(os.environ.get('QA_OUTPUT',tempfile.mkdtemp(prefix='network-labs-browser-'))).resolve();output.mkdir(parents=True,exist_ok=True)
    env={**os.environ,'DEVICE_URL':portal.url('SW1'),'QA_OUTPUT':str(output)}
    process=subprocess.Popen(['node',str(Path(__file__).with_name('browser_smoke.cjs'))],env=env)
    deadline=time.monotonic()+120
    while process.poll() is None and time.monotonic()<deadline:
        root.update();time.sleep(.01)
    if process.poll() is None:
        process.kill();raise RuntimeError('Browser check timed out.')
    if process.returncode:
        raise RuntimeError('Browser check failed. Install Playwright or set CHROME_EXECUTABLE; see docs/WEB.md.')
    assert app.lab.nodes['SW1'].vlans['30']=='WEB_CLIENTS'
    assert app.lab.nodes['PC1'].address=='192.168.10.10/24'
    assert app.lab.nodes['NAS1'].services['tcp/443']=='HTTPS'
    assert app.lab.nodes['SRV1'].dns_records['web-test.lan']=='192.168.10.20'
    assert any(r['id']==50 and r['port']==443 for r in app.lab.nodes['FW1'].firewall_rules)
    print('Live backend assertions passed. Screenshots:',output)
finally:
    if process is not None and process.poll() is None:process.kill()
    root.destroy()
