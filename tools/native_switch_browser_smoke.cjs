/* Real browser edits of a paired LACP lab; no simulated link negotiation. */
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:900}});page.setDefaultTimeout(10000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.env.NATIVE_WEB_SWITCH_URL);await page.locator('#message').filter({hasText:'Projet synchronisé'}).waitFor();
  async function save(){const waiting=page.waitForResponse(r=>r.url().endsWith('/api/apply')&&r.request().method()==='POST');await page.locator('#sectionSave').click();const response=await waiting;if(response.status()!==200)throw Error(await response.text());await page.locator('#message').filter({hasText:'Section appliquée'}).waitFor()}
  await page.locator('[data-page="stp"]').click();await page.locator('#treeMode').selectOption('stp');await page.locator('#treePriority').fill('4096');await save();
  await page.locator('[data-page="aggregation"]').click();await page.locator('#lagMinimum').fill('2');await page.locator('#lagPeerMode').selectOption('passive');await save();
  await page.locator('#lagOperation').selectOption('remove');await save();
  await page.locator('#listing').filter({hasText:'Port-channel'}).waitFor();
  await page.locator('#lagMinimum').fill('2');await page.locator('#lagPeerMode').selectOption('passive');await page.locator('#lagAllowed').fill('10,20');await save();
  await page.screenshot({path:process.env.NATIVE_WEB_LACP_SCREENSHOT||'/tmp/native-lacp-local.png',fullPage:true});
  if(errors.length)throw Error(errors.join('\n'));console.log('Browser STP component update, paired LACP edit/removal/recreation passed');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
