/* Optional browser acceptance against an open native Tk workbench.
 * Requires Playwright and Chromium. URLs are passed privately through env.
 */
const {chromium}=require('playwright');
(async()=>{
  const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    page.setDefaultTimeout(10000);
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(process.env.NATIVE_WEB_CLIENT_URL);
    await page.locator('#message').filter({hasText:'Projet synchronisé'}).waitFor();
    await page.locator('#name').fill('BROWSER3');
    await page.locator('#address').fill('192.168.20.33/24');
    await page.locator('#apply').click();
    await page.locator('#message').filter({hasText:'Brouillon appliqué'}).waitFor();
    if(await page.locator('#identity').textContent()!=='BROWSER3 · Hôte')throw Error('Web name not synchronized');
    await page.locator('#address').fill('bad-address');await page.locator('#apply').click();
    await page.locator('#message.error').waitFor();await page.locator('#reload').click();
    await page.locator('#message').filter({hasText:'Projet synchronisé'}).waitFor();
    if(await page.locator('#address').inputValue()!=='192.168.20.33/24')throw Error('Invalid address changed draft');
    await page.goto(process.env.NATIVE_WEB_FIREWALL_URL);
    await page.locator('#identity').filter({hasText:'FW1'}).waitFor();
    await page.locator('[data-page="firewall"]').click();
    async function saveSection() {
      const response=page.waitForResponse(r=>r.url().endsWith('/api/apply')&&r.request().method()==='POST');
      await page.locator('#sectionSave').click();
      const reply=await response;if(reply.status()!==200)throw Error('Section refused: '+await reply.text());
      await page.locator('#message').filter({hasText:'Section appliquée'}).waitFor();
    }
    async function visit(name) {
      const url=new URL(process.env.NATIVE_WEB_FIREWALL_URL),parameters=new URLSearchParams(url.hash.slice(1));parameters.set('node',name);url.hash=parameters.toString();
      await page.goto(url.toString());await page.locator('#identity').filter({hasText:name}).waitFor();
    }
    await page.locator('#policyDefault').selectOption('drop');
    for(const [name,source,destination] of [['admin-dmz','192.168.10.10/32','172.16.0.10/32'],['dmz-admin','172.16.0.10/32','192.168.10.10/32']]) {
      await page.locator('#ruleName').fill(name);await page.locator('#ruleProtocol').selectOption('icmp');
      await page.locator('#ruleSource').fill(source);await page.locator('#ruleDestination').fill(destination);await page.locator('#stageRule').click();
    }
    await saveSection();
    await page.locator('#rulesTable').filter({hasText:'admin-dmz'}).waitFor();
    // Reorder and remove real entries, then keep the original order for capture.
    await page.locator('[data-down="0"]').click();await page.locator('[data-up="1"]').click();await saveSection();
    await page.locator('[data-page="nat"]').click();
    await page.locator('#ruleName').fill('lan-masquerade');await page.locator('#ruleOut').selectOption('eth1');
    await page.locator('#ruleSource').fill('192.168.10.0/24');await page.locator('#stageRule').click();await saveSection();
    await page.locator('[data-page="routing"]').click();await page.locator('#routeNetwork').fill('192.168.99.0/24');
    await page.locator('#routeNextHop').fill('10.0.0.1');await page.locator('#routePort').selectOption('eth0');await page.locator('#stageRoute').click();await saveSection();
    await visit('SW1');await page.locator('[data-page="switching"]').click();
    await page.locator('#switchVlans').fill('1,10,40');await saveSection();
    await page.locator('[data-page="svis"]').click();await page.locator('#logicalName').fill('vlan40');
    await page.locator('#logicalVlan').fill('40');await page.locator('#logicalAddress').fill('192.168.40.1/24');await page.locator('#logicalAdd').click();await saveSection();
    await visit('SRV1');await page.locator('[data-page="dnsserver"]').click();await page.locator('#serviceEnabled').check();
    await page.locator('#recordName').fill('srv.lab.test');await page.locator('#recordAddress').fill('172.16.0.10');await page.locator('#recordAdd').click();await saveSection();
    await visit('FW1');await page.locator('[data-page="firewall"]').click();
    await page.screenshot({path:process.env.NATIVE_WEB_SCREENSHOT||'/tmp/native-web-local.png',fullPage:true});
    if(errors.length)throw Error(errors.join('\n'));
    console.log('Browser firewall/NAT/routes, switch VLAN/SVI, server DNS and invalid-write recovery passed');
  } finally {await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
