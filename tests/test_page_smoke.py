"""Every device model's page, opened in a real browser: it draws without a script error, and text typed in a device's
configuration (a banner, an interface description), which a shared project file can carry, is shown as text, never run
as HTML. Then the Simple design and the Network LABS view of a router, a switch and a PC."""
import unittest

from network_labs.appliances import ios_store, topology_edit
from network_labs.appliances.native_models import MODELS
from network_labs.appliances.spec import validate
from network_labs.appliances.ui_quick import blank_project
from test_product_pages import browser_available, drive
from test_workbench_polish import Workbench

HOSTILE = '<img src=x onerror="window.__nlxss=(window.__nlxss||0)+1"><script>window.__nlxss=1</script>'

SMOKE = r"""
const { chromium } = require('playwright');
(async () => {
  const urls = JSON.parse(process.argv[1]);
  let browser;
  try { browser = await chromium.launch(); } catch (error) { console.log('NOBROWSER'); return; }
  const result = {errors: {}, ran: [], blank: [], pages: 0};
  for (const [design, names] of [['vendor', Object.keys(urls)], ['simple', ['R', 'S', 'H']], ['standard', ['R', 'S']]]) {
    for (const name of names) {
      const context = await browser.newContext({ viewport: { width: 1280, height: 860 } });
      await context.addInitScript(value => { try { localStorage.setItem('network-labs-design', value); } catch (e) {} },
                                  design === 'simple' ? 'simple' : 'vendor');
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('dialog', dialog => dialog.dismiss());
      await page.goto(urls[name]);
      await page.waitForTimeout(900);
      if (await page.$('.px-login')) {  // the product's sign-in page: its factory credentials
        if (await page.$('.px-login .us') && !(await page.inputValue('.px-login .us')))
          await page.fill('.px-login .us', await page.getAttribute('.px-login', 'data-user'));
        await page.fill('.px-login .pw', await page.getAttribute('.px-login', 'data-pass'));
        await page.click('.px-login .go');
        await page.waitForTimeout(700);
      }
      if (design === 'standard' && await page.$('.px-pill-main')) {
        await page.click('.px-pill-main'); await page.click('.px-pill [data-a=std]'); await page.waitForTimeout(500);
      }
      const seen = await page.evaluate(() => ({ran: window.__nlxss || 0, drawn: document.body.querySelectorAll('*').length}));
      if (errors.length) result.errors[design + ' ' + name] = errors;
      if (seen.ran) result.ran.push(design + ' ' + name);
      if (seen.drawn < 30) result.blank.push(design + ' ' + name);  // a desktop is mostly icons: count what is drawn
      result.pages++;
      await context.close();
    }
  }
  console.log('RESULT ' + JSON.stringify(result));
  await browser.close();
})();
"""


def every_model_lab():
    """One node of each model in the library; the ones with a command set carry hostile text in their configuration."""
    spec = dict(blank_project('modeles'), budget_mib=65536)  # 60 nodes: never started, only drawn
    add = lambda spec, **k: topology_edit.add_microvm_node(spec, kernel='/k', disk='/d', memory_mib=64, **k)
    names = {}
    for index, (model_id, model) in enumerate(sorted(MODELS.items())):
        name = f'M{index:02d}'
        role, ports = model['role'], min(len(model.get('ports') or ['eth0']), 8)
        addresses = '' if role == 'switch' else ','.join(f'10.{index}.{port}.1/24' for port in range(ports))
        spec = add(spec, name=name, role=role, ports=ports, model=model_id, addresses=addresses)
        names[name] = model_id
    spec = add(spec, name='R', role='router', ports=2, model='cisco-isr4331', addresses='10.200.0.1/24,10.200.1.1/24')
    spec = add(spec, name='S', role='switch', ports=4, model='cisco-9200l')
    spec = add(spec, name='H', role='host', ports=1, addresses='10.200.0.10/24')
    for node in spec['nodes']:
        if node['role'] in ('router', 'switch', 'firewall'):
            ios_store.store(node, 'config', f'banner motd #{HOSTILE}#')
            ios_store.store(node, 'config-if', f'description {HOSTILE}', port='eth0')
    return validate(spec), names


@unittest.skipUnless(browser_available(), 'Playwright (Node) absent: pages not opened in a browser')
class EveryPageTest(unittest.TestCase):
    def test_every_models_page_draws_and_shows_typed_text_as_text(self):
        app = Workbench()
        app.spec, names = every_model_lab()
        app.view_lab = app.spec['name']
        self.assertEqual(len(names), len(MODELS))
        result = drive(app, SMOKE, list(names) + ['R', 'S', 'H'], seconds=600)
        self.assertEqual(result['pages'], len(names) + 3 + 3 + 2)
        self.assertEqual(result['errors'], {}, {page: names.get(page.split()[1]) for page in result['errors']})
        self.assertEqual(result['ran'], [])  # the hostile banner and descriptions never ran
        self.assertEqual(result['blank'], [])


if __name__ == '__main__':
    unittest.main()
