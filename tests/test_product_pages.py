"""The device pages as copies of the real products (native_products.js): which product gets which interface, the device's
configuration in its own syntax for the pages, and, in a real browser when one is available, edits made through the
products' own forms (Cisco WebUI « Update & Apply to Device », ASDM « Apply », pfSense « Apply Changes », PAN-OS
« Commit ») landing in the project."""
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from network_labs.appliances import topology_edit
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project
from network_labs.appliances.web_management import NativeDeviceAPI, running_config
from network_labs.web_portal import WebPortal
from test_workbench_polish import Workbench

SCRIPT = Path(__file__).resolve().parents[1] / 'network_labs' / 'native_products.js'

FLOWS = r"""
const { chromium } = require('playwright');
(async () => {
  const urls = JSON.parse(process.argv[1]);
  let browser;
  try { browser = await chromium.launch(); } catch (error) { console.log('NOBROWSER'); return; }
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const open = async name => { await page.goto(urls[name]); await page.waitForSelector('.px-app'); };
  const product = async () => page.evaluate(() => document.querySelector('.px-app').className);
  const seen = {};
  await open('R1'); seen.R1 = await product();
  await page.click('a[data-m="Configuration"]'); await page.click('.ix-fly a[data-go="ethernet"]'); await page.click('a[data-i="1"]');
  await page.fill('#ixIp', '198.51.100.2'); await page.click('.ix-slide .ok'); await page.waitForSelector('.px-toast');
  await open('ASA'); seen.ASA = await product();
  await page.click('[data-mode="configuration"]'); await page.click('.as-rt .add'); await page.selectOption('#asIn', 'eth1');
  await page.check('input[name=asAct][value=drop]'); await page.fill('#asSvc', 'tcp/23'); await page.fill('#asName', 'Bloquer Telnet LAN');
  await page.click('.px-dfoot button:text-is("OK")'); await page.click('.as-apply .apply'); await page.waitForSelector('.px-toast');
  await open('PFS'); seen.PFS = await product();
  await page.click('.pf-nav .m a:has-text("Firewall")'); await page.click('.pf-drop a[data-go="rules"]'); await page.click('.pf-btns .add >> nth=0');
  await page.selectOption('#pfAct', 'accept'); await page.selectOption('#pfProto', 'tcp'); await page.fill('#pfPort', '443'); await page.fill('#pfName', 'Allow HTTPS');
  await page.click('.pf-page .save'); await page.click('.pf-alert .apply'); await page.waitForSelector('.px-toast');
  await open('PAN'); seen.PAN = await product();
  await page.click('.pa-top [data-t="Policies"]'); await page.click('.pa-bar .add'); await page.fill('#paName', 'web-in');
  await page.click('.pa-dtabs [data-p="4"]'); await page.fill('#paSvc', 'service-https'); await page.click('.px-dfoot button.pri');
  await page.click('.pa-commit'); await page.click('.px-dfoot button:text-is("Commit")'); await page.waitForSelector('text=Configuration committed successfully');
  await page.goto(urls.FW1); await page.waitForTimeout(1500);  // the FortiGate keeps its own face (native_fortios.js)
  seen.FW1 = await page.evaluate(() => (document.querySelector('.px-app') ? 'px' : 'own face'));
  console.log('RESULT ' + JSON.stringify({seen, errors}));
  await browser.close();
})();
"""


MORE_FLOWS = r"""
const { chromium } = require('playwright');
(async () => {
  const urls = JSON.parse(process.argv[1]);
  let browser;
  try { browser = await chromium.launch(); } catch (error) { console.log('NOBROWSER'); return; }
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const open = async name => { await page.goto(urls[name]); await page.waitForSelector('.px-app'); };
  const ok = async () => { await page.click('.px-dfoot button >> nth=0'); await page.waitForTimeout(400); };
  const seen = {};
  await open('SOPH'); seen.SOPH = await page.evaluate(() => document.querySelector('.px-app').className);
  await page.click('[data-go="rules"]'); await page.click('.so-bar .add'); await page.fill('#soName', 'LAN to web'); await page.selectOption('#soFrom', 'eth1');
  await page.fill('#soSvc', 'HTTPS'); await page.click('.so-form .save'); await page.waitForSelector('.px-toast');
  await page.click('.so-tabs a[data-t="NAT rules"]'); await page.click('.so-bar .add'); await page.fill('#nxName', 'lan masq'); await page.selectOption('#nxXsrc', 'masquerade');
  await page.selectOption('#nxOut', 'eth0'); await page.click('.so-form .save'); await page.waitForTimeout(500);
  await open('CP'); seen.CP = await page.evaluate(() => document.querySelector('.px-app').className);
  await page.click('[data-m="smart"]'); await page.click('.sc-split .add'); await page.fill('#cpName', 'Allow DNS'); await page.fill('#cpSvc', 'domain-udp'); await ok();
  await page.click('.sc-tool .pub'); await page.click('.sc-tool .install'); await ok(); await page.waitForTimeout(400);
  await open('HW'); seen.HW = await page.evaluate(() => document.querySelector('.px-app').className);
  await page.click('[data-tab="Configuration"]'); await page.click('[data-go="routes"]'); await page.click('.hw-bar .add'); await page.fill('#hwD', '0.0.0.0'); await page.fill('#hwM', '0.0.0.0');
  await page.fill('#hwN', '10.70.0.254'); await ok();
  await open('TPL'); seen.TPL = await page.evaluate(() => document.querySelector('.px-app').className);
  await page.click('[data-go="dot1q"]'); await page.fill('#tpVid', '10'); await page.check('input[name="m-eth1"][value="U"]'); await page.check('input[name="m-eth0"][value="T"]');
  await page.click('.tp-main .add'); await page.waitForTimeout(500);
  await open('OPN'); seen.OPN = await page.evaluate(() => document.querySelector('.px-app').className);
  await page.click('[data-g="Firewall"]'); await page.click('[data-go="nat:Port Forward"]'); await page.click('.pf-btns .add >> nth=0'); await page.selectOption('#nxIn', 'eth0');
  await page.fill('#nxSvc', 'tcp/443'); await page.fill('#nxDst', '10.73.0.1'); await page.fill('#nxTo', '10.73.1.10'); await page.fill('#nxName', 'web publish');
  await page.click('.pf-page .save'); await page.click('.pf-alert .apply'); await page.waitForTimeout(500);
  console.log('RESULT ' + JSON.stringify({seen, errors}));
  await browser.close();
})();
"""


def more_lab():
    spec = blank_project('produits')
    add = lambda spec, **k: topology_edit.add_microvm_node(spec, kernel='/k', disk='/d', memory_mib=64, **k)
    spec = add(spec, name='SOPH', role='firewall', ports=3, model='sophos-fw', addresses='10.71.0.1/24,10.71.1.1/24,10.71.2.1/24')
    spec = add(spec, name='CP', role='firewall', ports=3, model='checkpoint-fw', addresses='10.72.0.1/24,10.72.1.1/24,10.72.2.1/24')
    spec = add(spec, name='OPN', role='firewall', ports=3, model='opnsense', addresses='10.73.0.1/24,10.73.1.1/24,10.73.2.1/24')
    spec = add(spec, name='HW', role='router', ports=2, model='huawei-ar6120', addresses='10.70.0.1/24,10.70.1.1/24')
    spec = add(spec, name='TPL', role='switch', ports=8, model='tplink-sg108e')
    return validate(spec)


def browser_available():
    try:
        return subprocess.run(['node', '-e', "require('playwright')"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class RunningConfigTest(unittest.TestCase):
    def test_vendor_devices_carry_their_configuration_in_their_own_syntax(self):
        app = Workbench()
        router = next(n for n in app.spec['nodes'] if n['name'] == 'R1')
        text = running_config(app.spec, router)
        self.assertIn('hostname R1', text)
        self.assertIn('ip address 203.0.113.1 255.255.255.252', text)  # IOS, as the WebUI's CLI page and Monitoring show it
        pc = next(n for n in app.spec['nodes'] if n['name'] == 'PC1')
        self.assertIsNone(running_config(app.spec, pc))
        self.assertIn('hostname R1', NativeDeviceAPI(app).dispatch('state', {'node': 'R1'})['config_text'])

    def test_the_page_picks_each_products_own_interface(self):
        script = SCRIPT.read_text(encoding='utf-8')
        for marker in ("return 'webfig'", "return 'asdm'", "return 'iosxe'", "return 'pfsense'", "return 'panos'", "return 'jweb'", "return 'cli'"):
            self.assertIn(marker, script)
        for wording in ('Update & Apply to Device', 'Apply Changes', 'Commit All Changes', 'Add New', 'Access Rules', 'Security Policy Rule', 'NAT Policy Rule'):
            self.assertIn(wording, script)
        more = SCRIPT.with_name('native_products_more.js').read_text(encoding='utf-8')
        for skin in ('sophos', 'gaia', 'sonicos', 'fireware', 'huawei', 'edgeos', 'unifi', 'tplink', 'netgear', 'dlink', 'aruba', 'devmgr'):
            self.assertIn(f"'{skin}');", more)  # registered with the engine
        for wording in ('Install Policy', 'Add firewall rule', 'ADD POLICY', '802.1Q VLAN', 'VLAN Membership', 'Device Manager', 'ip route-static'):
            self.assertIn(wording, more)
        self.assertNotIn('<img', script + more)  # drawn by Network LABS: no vendor picture or logo


class PortalTest(unittest.TestCase):
    def test_the_portal_serves_the_product_pages_after_the_vendor_faces(self):
        app = Workbench()
        portal = WebPortal(app, api=NativeDeviceAPI(app), native=True)
        try:
            import http.client
            connection = http.client.HTTPConnection(portal.host)
            connection.request('GET', '/', headers={'Host': portal.host})
            page = connection.getresponse().read()
            self.assertLess(page.index(b'/native_vendor.js'), page.index(b'/native_products.js'))
            self.assertLess(page.index(b'/native_products.js'), page.index(b'/native_products_more.js'))
            self.assertLess(page.index(b'/native_products_more.js'), page.index(b'/native_simple.js'))
            connection.request('GET', '/native_products.js', headers={'Host': portal.host})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(b'window.nlProduct', response.read())
        finally:
            portal.close()


@unittest.skipUnless(browser_available(), 'Playwright (Node) absent: product pages not driven in a browser')
class ProductFormsTest(unittest.TestCase):
    def test_edits_through_the_products_forms_reach_the_project(self):
        app = Workbench()
        api = NativeDeviceAPI(app)
        portal = WebPortal(app, api=api, native=True)
        try:
            urls = {name: portal.url(name, 'dashboard') for name in ('R1', 'ASA', 'PFS', 'PAN', 'FW1')}
            with tempfile.TemporaryDirectory() as folder:
                job = subprocess.Popen(['node', '-e', FLOWS, json.dumps(urls)], cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                deadline = time.time() + 150
                while job.poll() is None and time.time() < deadline:
                    portal.poll()  # the workbench's Tk loop, in this test
                    time.sleep(.02)
                if job.poll() is None:
                    job.kill()
                out, err = job.communicate()
        finally:
            portal.close()
        if 'NOBROWSER' in out:
            self.skipTest('Chromium absent')
        line = next((l for l in out.splitlines() if l.startswith('RESULT ')), None)
        self.assertIsNotNone(line, out[-2000:] + err[-2000:])
        result = json.loads(line[7:])
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['seen'], {'R1': 'px-app iosxe', 'ASA': 'px-app asdm', 'PFS': 'px-app pfsense', 'PAN': 'px-app panos', 'FW1': 'own face'})
        nodes = {n['name']: n for n in app.spec['nodes']}
        self.assertEqual(nodes['R1']['interfaces']['eth1'], '198.51.100.2/24')
        asa = {r['name']: r for r in nodes['ASA']['firewall']['rules']}
        self.assertEqual({k: asa['Bloquer-Telnet-LAN'][k] for k in ('action', 'in', 'protocol', 'dport')},
                         {'action': 'drop', 'in': 'eth1', 'protocol': 'tcp', 'dport': 23})
        pfsense = {r['name']: r for r in nodes['PFS']['firewall']['rules']}
        self.assertEqual((pfsense['Allow-HTTPS']['action'], pfsense['Allow-HTTPS']['dport'], pfsense['Allow-HTTPS']['in']), ('accept', 443, 'eth1'))
        panos = {r['name']: r for r in nodes['PAN']['firewall']['rules']}
        self.assertEqual((panos['web-in']['action'], panos['web-in']['protocol'], panos['web-in']['dport']), ('accept', 'tcp', 443))


    def test_edits_through_more_products_reach_the_project(self):
        app = Workbench()
        app.spec = more_lab()
        app.view_lab = app.spec['name']
        portal = WebPortal(app, api=NativeDeviceAPI(app), native=True)
        try:
            urls = {name: portal.url(name, 'dashboard') for name in ('SOPH', 'CP', 'HW', 'TPL', 'OPN')}
            with tempfile.TemporaryDirectory() as folder:
                job = subprocess.Popen(['node', '-e', MORE_FLOWS, json.dumps(urls)], cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                deadline = time.time() + 150
                while job.poll() is None and time.time() < deadline:
                    portal.poll()
                    time.sleep(.02)
                if job.poll() is None:
                    job.kill()
                out, err = job.communicate()
        finally:
            portal.close()
        if 'NOBROWSER' in out:
            self.skipTest('Chromium absent')
        line = next((l for l in out.splitlines() if l.startswith('RESULT ')), None)
        self.assertIsNotNone(line, out[-2000:] + err[-2000:])
        result = json.loads(line[7:])
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['seen'], {'SOPH': 'px-app sophos', 'CP': 'px-app gaia', 'HW': 'px-app huawei', 'TPL': 'px-app tplink', 'OPN': 'px-app opnsense'})
        nodes = {n['name']: n for n in app.spec['nodes']}
        sophos = nodes['SOPH']['firewall']
        self.assertEqual([(r['name'], r['in'], r['dport']) for r in sophos['rules']], [('LAN-to-web', 'eth1', 443)])
        self.assertEqual([(r['name'], r['type'], r['out']) for r in sophos['nat']], [('lan-masq', 'masquerade', 'eth0')])
        self.assertEqual([(r['name'], r['protocol'], r['dport']) for r in nodes['CP']['firewall']['rules']], [('Allow-DNS', 'udp', 53)])  # published, installed
        from network_labs.appliances.vendor_config import routes
        self.assertEqual(routes(nodes['HW']), [('0.0.0.0/0', '10.70.0.254')])  # sent as ip route-static
        self.assertEqual(nodes['TPL']['vlans'], [1, 10])
        self.assertEqual(nodes['TPL']['switchports']['eth1'], {'mode': 'access', 'vlan': 10})
        self.assertEqual(nodes['TPL']['switchports']['eth0'], {'mode': 'trunk', 'native_vlan': 1, 'allowed': [10]})
        self.assertEqual(nodes['TPL']['switchports']['eth2'], {'mode': 'access', 'vlan': 1})  # untouched
        forward = nodes['OPN']['firewall']['nat'][0]
        self.assertEqual({k: forward[k] for k in ('type', 'in', 'destination', 'to', 'protocol', 'dport')},
                         {'type': 'dnat', 'in': 'eth0', 'destination': '10.73.0.1/32', 'to': '10.73.1.10', 'protocol': 'tcp', 'dport': 443})


if __name__ == '__main__':
    unittest.main()
