/* Actual browser configuration of the access-only LAN defence profile. */
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:900}});page.setDefaultTimeout(10000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.env.NATIVE_WEB_ADMISSION_URL);await page.locator('#message').filter({hasText:'Projet synchronisé'}).waitFor();
  async function save(expected=200){const waiting=page.waitForResponse(r=>r.url().endsWith('/api/apply')&&r.request().method()==='POST');await page.locator('#sectionSave').click();const response=await waiting;if(response.status()!==expected)throw Error(await response.text());await page.locator(expected===200?'#message':'#message.error').filter({hasText:expected===200?'Section appliquée':''}).waitFor()}
  await page.locator('[data-page="snooping"]').click();await page.locator('#snoopEnabled').check();await page.locator('#snoopVlans').fill('10');await page.locator('#snoopTrust3').check();await save();
  await page.locator('[data-page="arpinspection"]').click();await page.locator('#arpVlans').fill('10');await page.locator('#arpTrust2').check();await page.locator('#arpTrust3').check();
  for(const [port,mac,address] of [['eth0','02:00:00:00:10:11','10.10.0.10'],['eth1','02:00:00:00:10:22','10.10.0.99'],['eth2','02:00:00:00:10:33','10.10.0.88']]){
   await page.locator('#bindingPort').selectOption(port);await page.locator('#bindingVlan').fill('10');await page.locator('#bindingMac').fill(mac);await page.locator('#bindingAddress').fill(address);await page.locator('#bindingAdd').click();
  }
  await save();await page.screenshot({path:process.env.NATIVE_WEB_ARP_SCREENSHOT||'/tmp/native-arp-local.png',fullPage:true});
  await page.locator('[data-page="sourceguard"]').click();await page.locator('#sourceMode0').selectOption('ip-mac');await page.locator('#sourceMode2').selectOption('ip-mac');await save();
  await page.locator('[data-page="snooping"]').click();await page.locator('#snoopEnabled').uncheck();await save(400);await page.locator('#sectionReload').click();await page.waitForFunction(()=>document.getElementById('snoopEnabled')?.checked===true);
  await page.locator('[data-page="sourceguard"]').click();await page.screenshot({path:process.env.NATIVE_WEB_ADMISSION_SCREENSHOT||'/tmp/native-admission-local.png',fullPage:true});
  await page.locator('[data-page="multicast"]').click();await page.locator('#multicastManaged').check();await page.locator('#multicastQuerier').check();await page.locator('#multicastRouter3').selectOption('permanent');await page.locator('#multicastFlood0').uncheck();await page.locator('#multicastLeave0').check();await save();
  await page.locator('#multicastSnooping').uncheck();await save(400);await page.locator('#sectionReload').click();await page.waitForFunction(()=>document.getElementById('multicastSnooping')?.checked===true);
  await page.screenshot({path:'/tmp/native-multicast-local.png',fullPage:true});
  if(errors.length)throw Error(errors.join('\n'));console.log('Browser snooping, DAI/shared bindings, source guard and dependency protection passed');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
