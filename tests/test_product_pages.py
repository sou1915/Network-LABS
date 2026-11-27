"""The device pages as copies of the real products (native_products.js): which product gets which interface, the device's
configuration in its own syntax for the pages, and, in a real browser when one is available, edits made through the
products' own forms (Cisco WebUI « Update & Apply to Device », ASDM « Apply », pfSense « Apply Changes », PAN-OS
« Commit ») landing in the project; the static routes of the products without a command set (/api/route); and the
host devices' own products: Synology DSM, QNAP QTS, HP and Brother printer pages, AXIS camera, Yealink phone, and the
server management controllers (iDRAC, iLO, XClarity); and Windows PCs and servers as Windows shows them (Settings,
Control Panel, the TCP/IPv4 properties dialog, Server Manager)."""
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from network_labs.appliances import guest_services, topology_edit
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
  // Each product opens on its sign-in page (once per device and tab): its factory credentials let the flow in.
  const login = async (tab = page) => {
    if (!(await tab.$('.px-login'))) return;
    if (await tab.$('.px-login .us') && !(await tab.inputValue('.px-login .us'))) await tab.fill('.px-login .us', await tab.getAttribute('.px-login', 'data-user'));
    await tab.fill('.px-login .pw', await tab.getAttribute('.px-login', 'data-pass'));
    await tab.click('.px-login .go');
    await tab.waitForFunction(() => !document.querySelector('.px-login'));
  };
  const open = async name => { await page.goto(urls[name]); await page.waitForSelector('.px-app'); await login(); };
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
  await page.waitForFunction(() => !document.body.classList.contains('px-wait'));  // pfSense's own stylesheets have loaded
  const look = {pfSense: await page.evaluate(() => [getComputedStyle(document.querySelector('#topmenu')).backgroundColor,
    getComputedStyle(document.body).fontFamily.split(',')[0].replace(/["']/g, ''), [...document.querySelectorAll('link[data-px-sheet]')].map(l => l.getAttribute('href'))])};
  await page.click('#topmenu .dropdown-toggle:has-text("Firewall")'); await page.click('#topmenu .dropdown-menu a[data-go="rules"]'); await page.click('.action-buttons .add >> nth=0');
  await page.selectOption('#pfAct', 'accept'); await page.selectOption('#pfProto', 'tcp'); await page.fill('#pfPort', '443'); await page.fill('#pfName', 'Allow HTTPS');
  await page.click('form.nl-form .save'); await page.click('.alert-warning .apply'); await page.waitForSelector('.alert-success');
  await open('PAN'); seen.PAN = await product();
  await page.click('.pa-top [data-t="Policies"]'); await page.click('.pa-bar .add'); await page.fill('#paName', 'web-in');
  await page.click('.pa-dtabs [data-p="4"]'); await page.fill('#paSvc', 'service-https'); await page.click('.px-dfoot button.pri');
  await page.click('.pa-commit'); await page.click('.px-dfoot button:text-is("Commit")'); await page.waitForSelector('text=Configuration committed successfully');
  await page.goto(urls.FW1); await page.waitForSelector('.px-login'); await login(); await page.waitForTimeout(1500);  // then the FortiGate's own face
  seen.FW1 = await page.evaluate(() => (document.querySelector('.px-app') ? 'px' : 'own face'));
  look.after = await page.evaluate(() => document.querySelectorAll('link[data-px-sheet]').length);  // another product: the stylesheets are gone
  console.log('RESULT ' + JSON.stringify({seen, errors, look}));
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
  // Each product opens on its sign-in page (once per device and tab): its factory credentials let the flow in.
  const login = async (tab = page) => {
    if (!(await tab.$('.px-login'))) return;
    if (await tab.$('.px-login .us') && !(await tab.inputValue('.px-login .us'))) await tab.fill('.px-login .us', await tab.getAttribute('.px-login', 'data-user'));
    await tab.fill('.px-login .pw', await tab.getAttribute('.px-login', 'data-pass'));
    await tab.click('.px-login .go');
    await tab.waitForFunction(() => !document.querySelector('.px-login'));
  };
  const open = async name => { await page.goto(urls[name]); await page.waitForSelector('.px-app'); await login(); };
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
  const look = await page.evaluate(() => [getComputedStyle(document.querySelector('.page-side')).position, getComputedStyle(document.body).fontFamily.split(',')[0].replace(/["']/g, '')]);
  await page.click('[data-g="Firewall"]'); await page.click('[data-g="Firewall/NAT"]'); await page.click('[data-go="nat:Port Forward"]'); await page.click('[data-add]');
  await page.selectOption('#nxIn', 'eth0'); await page.selectOption('#nxProto', 'tcp'); await page.fill('#nxPort', '443');  // destination: the WAN address
  await page.fill('#nxTo', '10.73.1.10'); await page.fill('#nxName', 'web publish');
  await page.click('form.nl-form .save'); await page.click('.alert .apply'); await page.waitForTimeout(500);
  console.log('RESULT ' + JSON.stringify({seen, errors, look}));
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
  // Each product opens on its sign-in page (once per device and tab): its factory credentials let the flow in.
  const login = async (tab = page) => {
    if (!(await tab.$('.px-login'))) return;
    if (await tab.$('.px-login .us') && !(await tab.inputValue('.px-login .us'))) await tab.fill('.px-login .us', await tab.getAttribute('.px-login', 'data-user'));
    await tab.fill('.px-login .pw', await tab.getAttribute('.px-login', 'data-pass'));
    await tab.click('.px-login .go');
    await tab.waitForFunction(() => !document.querySelector('.px-login'));
  };
  const open = async name => { await page.goto(urls[name]); await page.waitForSelector('.px-app'); await login(); };
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
  await open('PFS'); await page.click('#topmenu .dropdown-toggle:has-text("System")'); await page.click('#topmenu .dropdown-menu a[data-go="routing"]');
  await page.click('.nav-pills [data-t="Static Routes"]');
  await page.click('.action-buttons .add'); await page.fill('#pfNet', '172.16.0.0'); await page.selectOption('#pfNetLen', '16'); await page.fill('#pfGw', '10.74.0.254');
  await page.click('form.nl-form .save'); await page.click('.alert-warning .apply'); await page.waitForTimeout(500);
  await open('SOPH'); await page.click('[data-go="routing"]'); await page.click('.so-bar .add'); await page.fill('#soNet', '172.17.0.0'); await page.fill('#soMask', '255.255.0.0');
  await page.fill('#soGw', '192.168.99.1'); await ok(); const refused = await page.textContent('.px-shade .px-err');
  await page.fill('#soGw', '10.71.0.254'); await page.press('#soGw', 'Enter'); await page.waitForTimeout(500);  // Enter confirms the window
  const saved = await page.evaluate(() => state.device.static.map(r => r.network + '>' + r.gateway));
  const other = await browser.newPage({ viewport: { width: 1440, height: 900 } });  // the same device changed in another tab
  await other.goto(urls.SOPH); await other.waitForSelector('.px-app'); await login(other); await other.click('[data-go="routing"]'); await other.click('[data-x="0"]'); await other.waitForTimeout(500);
  await page.waitForTimeout(5000);
  const followed = await page.evaluate(() => state.device.static.length);
  console.log('RESULT ' + JSON.stringify({seen, errors, greyed, stayed, refused, saved, followed}));
  await browser.close();
})();
"""


WINDOWS_FLOWS = r"""
const { chromium } = require('playwright');
(async () => {
  const urls = JSON.parse(process.argv[1]);
  let browser;
  try { browser = await chromium.launch(); } catch (error) { console.log('NOBROWSER'); return; }
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  // Windows opens on its lock screen, once per device and tab: a click opens the session.
  const open = async name => { await page.goto(urls[name]); await page.waitForSelector('.px-app'); await page.click('.wn-lock'); await page.waitForTimeout(450);
    await page.click('.wn-signin .go'); await page.waitForTimeout(800); };
  const seen = {};
  await open('W11'); seen.W11 = await page.evaluate(() => document.querySelector('.px-app').className);
  await page.click('.wn-mid [data-start]'); await page.click('.wn-pin[data-app="settings"]'); await page.click('[data-p="network"]'); await page.click('.wn-card.link[data-eth]');
  await page.click('.wn-mbtn.edit'); await page.selectOption('.wn-cd .mode', 'static'); await page.fill('.wn-cd .a', '192.168.20.50'); await page.fill('.wn-cd .m', '255.255.255.0');
  await page.fill('.wn-cd .g', '192.168.20.1'); await page.click('.wn-cd .save'); await page.waitForTimeout(500);
  const settings = await page.evaluate(() => [state.node.interfaces.eth0, state.node.gateway]);
  await page.click('.wn-tt .x'); await page.click('.wn-bar [data-app="cpl"]'); await page.click('[data-cat="Réseau et Internet"] >> nth=0'); await page.click('[data-ncpa]');
  await page.dblclick('[data-ad="eth0"]'); await page.click('.wn-win.dlg .pr'); await page.click('.wn-win.dlg >> nth=-1 >> .prop');
  const boxes = page.locator('.wn-win.dlg >> nth=-1 >> .wn-ipbox.a input');
  for (const [i, v] of ['192', '168', '20', '60'].entries()) await boxes.nth(i).fill(v);
  await page.click('.wn-win.dlg >> nth=-1 >> .ok');
  const held = await page.evaluate(() => state.node.interfaces.eth0);  // the TCP/IPv4 OK keeps it; « Propriétés de Ethernet » OK applies it
  await page.click('.wn-win.dlg >> nth=-1 >> .ok'); await page.waitForTimeout(500);
  const classic = await page.evaluate(() => state.node.interfaces.eth0);
  await page.click('.wn-bar [data-app="terminal"]'); await page.keyboard.type('ipconfig'); await page.keyboard.press('Enter');
  const ipconfig = await page.textContent('.wn-term .log');
  await open('W10'); seen.W10 = await page.evaluate(() => document.querySelector('.px-app').className);
  await page.click('.wn-bar [data-start]'); await page.click('.wn-start10 [data-app="settings"] >> nth=0'); await page.click('[data-p="network"]');
  await page.click('[data-p="ethernet"]'); await page.click('[data-eth]'); await page.click('.wn-mbtn.edit'); await page.selectOption('.wn-cd .mode', 'dhcp'); await page.click('.wn-cd .save');
  await page.waitForTimeout(500);
  await open('SRV'); seen.SRV = await page.evaluate(() => document.querySelector('.px-app').className);
  const manager = await page.evaluate(() => Boolean(document.querySelector('.wn-sm .welcome')));
  console.log('RESULT ' + JSON.stringify({seen, errors, settings, held, classic, ipconfig, manager}));
  await browser.close();
})();
"""


WINDOWS_FONT_FLOWS = r"""
const { chromium } = require('playwright');
(async () => {
  const urls = JSON.parse(process.argv[1]);
  let browser;
  try { browser = await chromium.launch(); } catch (error) { console.log('NOBROWSER'); return; }
  const errors = [], out = {};
  // A PC with these fonts installed: text measured in them comes out wider than in the browser's own fallback fonts.
  const pc = async fonts => {
    const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(names => {
      const measure = CanvasRenderingContext2D.prototype.measureText;
      CanvasRenderingContext2D.prototype.measureText = function (text) {
        const metrics = measure.call(this, text);
        return names.some(name => this.font.includes(name)) ? {width: metrics.width + 7} : metrics;
      };
    }, fonts);
    return page;
  };
  const open = async (page, name) => { await page.goto(urls[name]); await page.waitForSelector('.px-app'); await page.click('.wn-lock'); await page.waitForTimeout(450);
    await page.click('.wn-signin .go'); await page.waitForTimeout(800); };
  const code = (page, selector) => page.evaluate(s => [...document.querySelectorAll(s)].map(e => e.textContent.codePointAt(0).toString(16).toUpperCase()), selector);
  const family = (page, selector) => page.evaluate(s => getComputedStyle(document.querySelector(s)).fontFamily, selector);
  let page = await pc([]);
  await open(page, 'W11'); await page.click('.wn-bar [data-app="settings"]');
  out.plain = await page.evaluate(() => document.querySelectorAll('nl-g').length);
  page = await pc(['Segoe Fluent Icons', 'Segoe MDL2 Assets']);
  await open(page, 'W11'); await page.click('.wn-bar [data-app="settings"]'); await page.click('[data-p="network"]');
  out.caption = await code(page, '.wn-tt .cap nl-g');
  out.search = await code(page, '.wn-spill nl-g');
  out.rows = await code(page, '.wn-card .chev nl-g');
  out.family11 = await family(page, 'nl-g');
  await open(page, 'W10'); await page.click('.wn-bar [data-start]'); await page.click('.wn-start10 [data-app="settings"] >> nth=0');
  out.home10 = await code(page, '.wn-home10 nl-g');
  out.family10 = await family(page, '.wn-home10 nl-g');
  page = await pc(['Segoe MDL2 Assets']);  // a Windows 10 PC: the Windows 11 page keeps the Fluent icons
  await open(page, 'W11');
  out.w11OnW10 = await page.evaluate(() => document.querySelectorAll('nl-g').length);
  console.log('RESULT ' + JSON.stringify({errors, ...out}));
  await browser.close();
})();
"""


def windows_lab():
    spec = blank_project('windows')
    add = lambda spec, **k: topology_edit.add_microvm_node(spec, kernel='/k', disk='/d', memory_mib=64, **k)
    spec = add(spec, name='SW1', role='switch', ports=4, model='cisco-2960')
    for i, (name, model) in enumerate((('W11', 'windows-11'), ('W10', 'windows-10'), ('SRV', 'windows-server'))):
        spec = add(spec, name=name, role='host', ports=1, model=model, addresses=f'192.168.20.{10 + i}/24')
        spec = topology_edit.connect(spec, (name, 'eth0'), ('SW1', f'eth{i + 1}'))
    return validate(spec)


LINUX_FLOWS = r"""
const { chromium } = require('playwright');
(async () => {
  const urls = JSON.parse(process.argv[1]);
  let browser;
  try { browser = await chromium.launch(); } catch (error) { console.log('NOBROWSER'); return; }
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const errors = [], seen = {};
  page.on('pageerror', error => errors.push(error.message));
  const open = async name => { await page.goto(urls[name]); await page.waitForSelector('.px-app.gn'); };
  // Ubuntu: Settings › Réseau › ⚙ › IPv4 › Manuel, then « Appliquer »; the terminal runs « ip a » on the PC.
  await open('UB'); seen.UB = await page.evaluate(() => document.querySelector('.px-app').className);
  seen.dock = await page.evaluate(() => [...document.querySelectorAll('.gn-dock [data-app]')].map(e => e.dataset.app));
  seen.icons = await page.evaluate(() => [...document.images].map(i => i.naturalWidth > 0 && i.getAttribute('src')).filter(Boolean).length);
  await page.click('[data-qs]'); seen.quick = await page.textContent('.gn-qs [data-net]');
  await page.click('.gn-qs [data-net]'); await page.click('[data-conn="eth0"]'); await page.click('[data-tab="IPv4"]');
  await page.check('[name=m][value=static]'); await page.fill('[name=ip]', '192.168.20.70'); await page.fill('[name=mask]', '255.255.255.0');
  await page.fill('[name=gw]', '192.168.20.1'); await page.click('[data-apply]'); await page.waitForTimeout(500);
  seen.manual = await page.evaluate(() => [state.node.interfaces.eth0, state.node.gateway, document.querySelectorAll('.gw-conn').length]);
  await page.click('.gn-act'); await page.click('.gn-ov [data-app="terminal"]');
  await page.keyboard.type('ip a'); await page.keyboard.press('Enter'); await page.waitForTimeout(700);
  await page.keyboard.type('hostname evil'); await page.keyboard.press('Enter'); await page.waitForTimeout(500);
  seen.terminal = await page.textContent('.gn-term .log');
  // Debian: GNOME's own shell (no dock) and its connection editor back to DHCP.
  await open('DEB'); seen.DEB = await page.evaluate(() => document.querySelector('.px-app').className);
  seen.debDock = await page.evaluate(() => Boolean(document.querySelector('.gn-dock')));
  await page.click('.gn-act'); await page.click('.gn-ov [data-app="settings"]'); await page.click('[data-conn="eth0"]'); await page.click('[data-tab="IPv4"]');
  await page.check('[name=m][value=dhcp]'); await page.click('[data-apply]'); await page.waitForTimeout(500);
  seen.dhcp = await page.evaluate(() => state.node.dhcp_clients);
  await page.goto(urls.SRV); await page.waitForSelector('.pc-app'); seen.SRV = await page.evaluate(() => Boolean(document.querySelector('.px-app.gn')));
  console.log('RESULT ' + JSON.stringify({errors, ...seen}));
  await browser.close();
})();
"""


def linux_lab():
    spec = blank_project('linux')
    add = lambda spec, **k: topology_edit.add_microvm_node(spec, kernel='/k', disk='/d', memory_mib=64, **k)
    spec = add(spec, name='SW1', role='switch', ports=4, model='cisco-2960')
    for i, (name, model) in enumerate((('UB', 'linux-ubuntu'), ('DEB', 'linux-debian'), ('SRV', 'linux-rocky'))):
        spec = add(spec, name=name, role='host', ports=1, model=model, addresses=f'192.168.20.{10 + i}/24')
        spec = topology_edit.connect(spec, (name, 'eth0'), ('SW1', f'eth{i + 1}'))
    next(n for n in spec['nodes'] if n['name'] == 'SRV')['services'] = guest_services.default_services('SRV')  # a server: Services
    return validate(spec)


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


def drive(app, script, names, seconds=150):
    """Runs a flows script against the workbench's portal, pumping the portal like the Tk loop does; returns its RESULT."""
    portal = WebPortal(app, api=NativeDeviceAPI(app), native=True)
    try:
        urls = {name: portal.url(name, 'dashboard') for name in names}
        with tempfile.TemporaryDirectory() as folder:
            job = subprocess.Popen(['node', '-e', script, json.dumps(urls)], cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            deadline = time.time() + seconds
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
        for wording in ('Install Policy', 'Add firewall rule', 'ADD POLICY', '802.1Q VLAN', 'VLAN Membership', 'Device Manager', 'ip route-static',
                        'Client Devices', 'Port Insights', 'function hwRange'):
            self.assertIn(wording, more)
        hosts = SCRIPT.with_name('native_products_hosts.js').read_text(encoding='utf-8')
        for skin in ('dsm', 'qts', 'hpews', 'brother', 'axis', 'yealink', 'idrac', 'ilo', 'xcc'):
            self.assertIn(f"SKINS.{skin} =", hosts)
        for wording in ('Control Panel', 'Network & Virtual Switch', 'IP Preferred Address Method', 'TCP/IP (Wired)', 'Assign IPv4 automatically',
                        'Internet Port', 'Virtual Console', 'Integrated Remote Console', 'XClarity Controller'):
            self.assertIn(wording, hosts)
        self.assertIn("role === 'host'", script)  # PCs keep their desktop: only these products take a host's page
        win = SCRIPT.with_name('native_products_windows.js').read_text(encoding='utf-8')
        for skin in ('win11', 'win10'):
            self.assertIn(f"SKINS.{skin} = shell('{skin}')", win)
        for wording in ('Propriétés de : Protocole Internet version 4 (TCP/IPv4)', 'Modifier les paramètres IP', 'Connexions réseau', 'Centre Réseau et partage',
                        'Gestionnaire de serveur', 'Obtenir une adresse IP automatiquement', 'Taper ici pour rechercher'):
            self.assertIn(wording, win)
        self.assertNotIn('<img', win)
        icons = SCRIPT.with_name('native_windows_icons.js').read_text(encoding='utf-8')
        self.assertIn('MIT License', icons)  # Microsoft's Fluent UI System Icons, credited
        for name in ('"settings:c"', '"wifi:c"', '"search"', '"chevron_up"'):
            self.assertIn(name, icons)
        self.assertNotIn('<img', script + more + hosts)  # drawn by Network LABS: no vendor picture or logo
        for skin, credentials in (('pfsense', "'admin', 'pfsense'"), ('idrac', "'root', 'calvin'"), ('edgeos', "'ubnt', 'ubnt'"), ('fortios', "'admin', ''")):
            self.assertIn(f"{skin}: [", script)
            self.assertIn(credentials, script)  # the product's factory credentials


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
            self.assertLess(page.index(b'/native_products_hosts.js'), page.index(b'/native_products_bsd.js'))
            self.assertLess(page.index(b'/native_products_bsd.js'), page.index(b'/native_windows_icons.js'))
            self.assertLess(page.index(b'/native_windows_icons.js'), page.index(b'/native_products_windows.js'))
            self.assertLess(page.index(b'/native_products_windows.js'), page.index(b'/native_desktop.js'))
            self.assertLess(page.index(b'/native_desktop.js'), page.index(b'/native_simple.js'))
            # The first state request waits for every script: a busy machine must not draw before a product registered.
            self.assertIn(b"document.addEventListener('DOMContentLoaded',load)", page)
            connection.request('GET', '/native_products_hosts.js', headers={'Host': portal.host})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(b'SKINS.dsm', response.read())
            connection.request('GET', '/native_products.js', headers={'Host': portal.host})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(b'window.nlProduct', response.read())
            # pfSense's and OPNsense's own stylesheets, their fonts and Font Awesome; nothing else under /ui/.
            for path, kind, marker in (('/ui/pfsense/pfSense.css', 'text/css', b'@import url("bootstrap.min.css")'),
                                       ('/ui/pfsense/bootstrap.min.css', 'text/css', b'Bootstrap v3.4.1'),
                                       ('/ui/pfsense/login.css', 'text/css', b'form.login'), ('/ui/opnsense/main.css', 'text/css', b'.page-side'),
                                       ('/ui/fontawesome/css/all.min.css', 'text/css', b'Font Awesome Free 6.5.1'),
                                       ('/ui/fontawesome/webfonts/fa-solid-900.woff2', 'font/woff2', b'wOF2'),
                                       ('/ui/pfsense/Roboto-Regular.woff2', 'font/woff2', b'wOF2'),
                                       ('/ui/opnsense/SourceSansPro-Regular.woff2', 'font/woff2', b'wOF2'),
                                       ('/ui/linux/yaru/org.gnome.Settings.png', 'image/png', b'\x89PNG'),
                                       ('/ui/linux/adwaita/network-wired-symbolic.svg', 'image/svg+xml', b'<svg'),
                                       ('/ui/linux/fonts/UbuntuSans.ttf', 'font/ttf', b'\x00\x01\x00\x00'),
                                       ('/ui/linux/fonts/Cantarell-Regular.otf', 'font/otf', b'OTTO'),
                                       ('/ui/linux/walls/ubuntu.jpg', 'image/jpeg', b'\xff\xd8')):
                connection.request('GET', path, headers={'Host': portal.host})
                response = connection.getresponse()
                body = response.read()
                self.assertEqual((response.status, response.getheader('Content-Type').split(';')[0]), (200, kind), path)
                self.assertIn(marker, body, path)
            for path in ('/ui/pfsense/../../web_portal.py', '/ui/pfsense/LICENSE', '/ui/other/x.css', '/ui/pfsense/missing.css', '/ui/opnsense/%2e%2e/x.css',
                         '/ui/linux/yaru/COPYRIGHT.txt', '/ui/linux/yaru/../fonts/UbuntuSans.ttf', '/ui/linux/x/y.svg'):
                connection.request('GET', path, headers={'Host': portal.host})
                response = connection.getresponse()
                response.read()
                self.assertEqual(response.status, 404, path)
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
        # pfSense drawn with pfSense's own stylesheet (its #212121 navbar, Roboto), dropped again on the next product's page
        self.assertEqual(result['look']['pfSense'], ['rgb(33, 33, 33)', 'Roboto', ['/ui/fontawesome/css/all.min.css', '/ui/pfsense/pfSense.css']])
        self.assertEqual(result['look']['after'], 0)
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
        self.assertEqual(result['look'], ['fixed', 'SourceSansProRegular'])  # OPNsense's theme: its fixed side menu, Source Sans Pro
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
        self.assertEqual(result['saved'], ['172.17.0.0/16>10.71.0.254'])  # saved with Enter
        self.assertEqual(result['followed'], 0)  # deleted in another tab: the first one followed by itself
        self.assertEqual(routes(nodes['SOPH']), [])

    def test_windows_pcs_and_servers_are_set_up_the_windows_way(self):
        app = Workbench()
        app.spec = windows_lab()
        app.view_lab = app.spec['name']
        result = drive(app, WINDOWS_FLOWS, ('W11', 'W10', 'SRV'))
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['seen'], {'W11': 'px-app win11', 'W10': 'px-app win10', 'SRV': 'px-app win10 server'})
        self.assertEqual(result['settings'], ['192.168.20.50/24', '192.168.20.1'])  # Paramètres › Ethernet › Modifier
        self.assertEqual(result['held'], '192.168.20.50/24')  # held by the TCP/IPv4 dialog until « Propriétés de Ethernet » OK
        self.assertEqual(result['classic'], '192.168.20.60/24')
        self.assertIn('Adresse IPv4. . . . . . . . . . . . . .: 192.168.20.60', result['ipconfig'])
        self.assertTrue(result['manager'])  # Windows Server opens on Server Manager
        nodes = {n['name']: n for n in app.spec['nodes']}
        self.assertEqual((nodes['W11']['interfaces']['eth0'], nodes['W11']['gateway']), ('192.168.20.60/24', '192.168.20.1'))
        self.assertEqual(nodes['W10']['dhcp_clients'], ['eth0'])

    def test_linux_pcs_are_gnome_desktops_the_distributions_own(self):
        app = Workbench()
        app.spec = linux_lab()
        app.view_lab = app.spec['name']
        result = drive(app, LINUX_FLOWS, ('UB', 'DEB', 'SRV'))
        self.assertEqual(result['errors'], [])
        self.assertIn('yaru', result['UB'].split())
        self.assertEqual(result['dock'], ['web', 'files', 'terminal', 'settings', 'editor'])  # the Ubuntu Dock
        self.assertGreaterEqual(result['icons'], 6)  # Yaru's own icons, loaded
        self.assertIn('Connecté', result['quick'])
        self.assertEqual(result['manual'], ['192.168.20.70/24', '192.168.20.1', 0])  # « Appliquer » saved and closed the dialog
        self.assertIn('inet 192.168.20.70/24', result['terminal'])  # « ip a » on the PC itself
        self.assertIn('Commande non disponible ici.', result['terminal'])  # read-only: « hostname NAME » is refused
        self.assertIn('adwaita', result['DEB'].split())
        self.assertFalse(result['debDock'])  # GNOME's own shell: the overview's dash, no dock
        self.assertEqual(result['dhcp'], ['eth0'])
        self.assertFalse(result['SRV'])  # a machine that serves keeps the server desktop and its Services

    def test_windows_draws_its_glyphs_with_the_pcs_own_icon_font(self):
        app = Workbench()
        app.spec = windows_lab()
        app.view_lab = app.spec['name']
        result = drive(app, WINDOWS_FONT_FLOWS, ('W11', 'W10'))
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['plain'], 0)  # no Segoe font on this PC: the Fluent UI System Icons stand in
        self.assertEqual(result['caption'], ['E921', 'E922', 'E8BB'])  # ChromeMinimize, ChromeMaximize, ChromeClose
        self.assertEqual(result['search'], ['E721'])
        self.assertTrue(result['rows'] and set(result['rows']) == {'E974'}, result['rows'])  # SettingsCard's ChevronRightMed
        self.assertTrue(result['family11'].startswith('"Segoe Fluent Icons"'), result['family11'])
        self.assertEqual(result['home10'], ['E7F8', 'E772', 'E774', 'E771', 'E71D', 'E77B', 'E775', 'E776', 'E72E', 'E895'])
        self.assertTrue(result['family10'].startswith('"Segoe MDL2 Assets"'), result['family10'])
        self.assertEqual(result['w11OnW10'], 0)


if __name__ == '__main__':
    unittest.main()
