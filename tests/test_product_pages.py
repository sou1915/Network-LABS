"""The device pages as copies of the real products (native_products.js): which product gets which interface, the device's
configuration in its own syntax for the pages, and, in a real browser when one is available, edits made through the
products' own forms (Cisco WebUI « Update & Apply to Device », ASDM « Apply », pfSense « Apply Changes », PAN-OS
« Commit ») landing in the project; the static routes of the products without a command set (/api/route); and the
host devices' own products: Synology DSM, QNAP QTS, HP and Brother printer pages, AXIS camera, Yealink phone, and the
server management controllers (iDRAC, iLO, XClarity)."""
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


HOST_FLOWS = r"""
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
  for (const name of ['QN', 'BRO', 'TEL', 'IDR', 'ILO', 'XCC']) { await open(name); seen[name] = await page.evaluate(() => document.querySelector('.px-app').className); }
  await open('NAS'); seen.NAS = await page.evaluate(() => document.querySelector('.px-app').className);
  await page.click('.ds-ico[data-w="control"]'); await page.click('.ds-main .edit'); await page.fill('#dsIp', '192.168.10.120'); await page.fill('#dsGw', '192.168.10.1'); await ok();
  await open('QN'); await page.click('.qt-ico[data-w="network"]'); await page.click('.qt-main .conf'); await page.check('input[name="qtm"][value="dhcp"]');
  const greyed = await page.evaluate(() => document.querySelector('#qtIp').disabled); await ok();
  await open('PRN'); seen.PRN = await page.evaluate(() => document.querySelector('.px-app').className);
  await page.click('.hp-nav [data-go="network"]'); await page.fill('#hpIp', '192.168.10.122'); await page.click('.hp-main .apply'); await page.waitForTimeout(400);
  await open('CAM'); seen.CAM = await page.evaluate(() => document.querySelector('.px-app').className);
  await page.click('.ax-nav [data-go="network"]'); await page.fill('#axIp', '192.168.10.124'); await page.fill('#axName', 'CAM-HALL'); await page.click('.ax-main .save');
  await page.waitForTimeout(600); const stayed = await page.evaluate(() => Boolean(document.querySelector('#axName')));
  await open('PFS'); await page.click('.pf-nav .m a:has-text("System")'); await page.click('.pf-drop a[data-go="routing"]'); await page.click('.pf-tabs [data-t="Static Routes"]');
  await page.click('.pf-btns .add'); await page.fill('#pfNet', '172.16.0.0'); await page.selectOption('#pfNetLen', '16'); await page.fill('#pfGw', '10.74.0.254');
  await page.click('.pf-page .save'); await page.click('.pf-alert .apply'); await page.waitForTimeout(500);
  await open('SOPH'); await page.click('[data-go="routing"]'); await page.click('.so-bar .add'); await page.fill('#soNet', '172.17.0.0'); await page.fill('#soMask', '255.255.0.0');
  await page.fill('#soGw', '192.168.99.1'); await ok(); const refused = await page.textContent('.px-shade .px-err');
  await page.fill('#soGw', '10.71.0.254'); await ok();
  console.log('RESULT ' + JSON.stringify({seen, errors, greyed, stayed, refused}));
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


def hosts_lab():
    spec = blank_project('hotes')
    add = lambda spec, **k: topology_edit.add_microvm_node(spec, kernel='/k', disk='/d', memory_mib=64, **k)
    spec = add(spec, name='SW1', role='switch', ports=10, model='cisco-2960')
    hosts = (('NAS', 'synology-ds224'), ('QN', 'qnap-ts264'), ('PRN', 'hp-4002dn'), ('BRO', 'brother-hl5200'), ('CAM', 'axis-p3265'),
             ('TEL', 'yealink-t54w'), ('IDR', 'dell-poweredge'), ('ILO', 'hpe-proliant'), ('XCC', 'lenovo-thinksystem'))
    for i, (name, model) in enumerate(hosts):
        spec = add(spec, name=name, role='host', ports=1, model=model, addresses=f'192.168.10.{20 + i}/24')
        spec = topology_edit.connect(spec, (name, 'eth0'), ('SW1', f'eth{i + 1}'))
    spec = add(spec, name='PFS', role='firewall', ports=3, model='pfsense', addresses='10.74.0.1/24,10.74.1.1/24,10.74.2.1/24')
    spec = add(spec, name='SOPH', role='firewall', ports=3, model='sophos-fw', addresses='10.71.0.1/24,10.71.1.1/24,10.71.2.1/24')
    return validate(spec)


def drive(app, script, names):
    """Runs a flows script against the workbench's portal, pumping the portal like the Tk loop does; returns its RESULT."""
    portal = WebPortal(app, api=NativeDeviceAPI(app), native=True)
    try:
        urls = {name: portal.url(name, 'dashboard') for name in names}
        with tempfile.TemporaryDirectory() as folder:
            job = subprocess.Popen(['node', '-e', script, json.dumps(urls)], cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
        raise unittest.SkipTest('Chromium absent')
    line = next((l for l in out.splitlines() if l.startswith('RESULT ')), None)
    if line is None:
        raise AssertionError(out[-2000:] + err[-2000:])
    return json.loads(line[7:])


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
        hosts = SCRIPT.with_name('native_products_hosts.js').read_text(encoding='utf-8')
        for skin in ('dsm', 'qts', 'hpews', 'brother', 'axis', 'yealink', 'idrac', 'ilo', 'xcc'):
            self.assertIn(f"SKINS.{skin} =", hosts)
        for wording in ('Control Panel', 'Network & Virtual Switch', 'IP Preferred Address Method', 'TCP/IP (Wired)', 'Assign IPv4 automatically',
                        'Internet Port', 'Virtual Console', 'Integrated Remote Console', 'XClarity Controller'):
            self.assertIn(wording, hosts)
        self.assertIn("role === 'host'", script)  # PCs keep their desktop: only these products take a host's page
        self.assertNotIn('<img', script + more + hosts)  # drawn by Network LABS: no vendor picture or logo


class RouteActionTest(unittest.TestCase):
    """/api/route: the static routes of the products whose brand has no command set in the laboratory."""
    def test_a_route_is_added_checked_and_removed(self):
        from network_labs.appliances.vendor_config import routes
        from network_labs.appliances.web_management import Conflict
        app = Workbench()
        app.spec = more_lab()
        app.view_lab = app.spec['name']
        api = NativeDeviceAPI(app)
        revision = lambda: api.dispatch('state', {'node': 'SOPH'})['revision']
        node = lambda: next(n for n in app.spec['nodes'] if n['name'] == 'SOPH')
        api.dispatch('route', {'node': 'SOPH', 'revision': revision(), 'network': '172.17.5.0/16', 'gateway': '10.71.0.254'})
        self.assertEqual(routes(node()), [('172.17.0.0/16', '10.71.0.254')])
        with self.assertRaisesRegex(ValueError, 'subnet'):
            api.dispatch('route', {'node': 'SOPH', 'revision': revision(), 'network': '172.18.0.0/16', 'gateway': '192.168.99.1'})
        with self.assertRaises(Conflict):
            api.dispatch('route', {'node': 'SOPH', 'revision': 'old', 'network': '172.18.0.0/16', 'gateway': '10.71.0.254'})
        with self.assertRaises(ValueError):
            api.dispatch('route', {'node': 'TPL', 'revision': api.dispatch('state', {'node': 'TPL'})['revision'], 'network': '0.0.0.0/0', 'gateway': '10.0.0.1'})
        api.dispatch('route', {'node': 'SOPH', 'revision': revision(), 'network': '172.17.0.0/16', 'gateway': ''})
        self.assertEqual(routes(node()), [])


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
            self.assertLess(page.index(b'/native_products_more.js'), page.index(b'/native_products_hosts.js'))
            self.assertLess(page.index(b'/native_products_hosts.js'), page.index(b'/native_desktop.js'))
            self.assertLess(page.index(b'/native_desktop.js'), page.index(b'/native_simple.js'))
            connection.request('GET', '/native_products_hosts.js', headers={'Host': portal.host})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(b'SKINS.dsm', response.read())
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

    def test_host_products_and_static_routes_reach_the_project(self):
        app = Workbench()
        app.spec = hosts_lab()
        app.view_lab = app.spec['name']
        result = drive(app, HOST_FLOWS, ('NAS', 'QN', 'PRN', 'BRO', 'CAM', 'TEL', 'IDR', 'ILO', 'XCC', 'PFS', 'SOPH'))
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['seen'], {'NAS': 'px-app dsm', 'QN': 'px-app qts', 'PRN': 'px-app hpews', 'BRO': 'px-app brother', 'CAM': 'px-app axis',
                                          'TEL': 'px-app yealink', 'IDR': 'px-app idrac', 'ILO': 'px-app ilo', 'XCC': 'px-app xcc'})
        self.assertTrue(result['greyed'])  # DHCP chosen: the address fields are greyed out, as on the product
        self.assertTrue(result['stayed'])  # renamed from its Network page: the same page stays open
        self.assertIn('subnet', result['refused'])  # the lab's check, in the product's dialog
        nodes = {n['name']: n for n in app.spec['nodes']}
        self.assertEqual((nodes['NAS']['interfaces']['eth0'], nodes['NAS']['gateway']), ('192.168.10.120/24', '192.168.10.1'))
        self.assertEqual((nodes['QN']['interfaces']['eth0'], nodes['QN']['dhcp_clients']), ('', ['eth0']))
        self.assertEqual(nodes['PRN']['interfaces']['eth0'], '192.168.10.122/24')
        self.assertEqual(nodes['CAM-HALL']['interfaces']['eth0'], '192.168.10.124/24')
        from network_labs.appliances.vendor_config import routes
        self.assertEqual(routes(nodes['PFS']), [('172.16.0.0/16', '10.74.0.254')])  # staged, then « Apply Changes »
        self.assertEqual(routes(nodes['SOPH']), [('172.17.0.0/16', '10.71.0.254')])


if __name__ == '__main__':
    unittest.main()
