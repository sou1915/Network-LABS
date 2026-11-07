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
    await page.locator('#listing pre').filter({hasText:'drop'}).waitFor();
    await page.locator('[data-page="interfaces"]').click();
    await page.screenshot({path:process.env.NATIVE_WEB_SCREENSHOT||'/tmp/native-web-local.png',fullPage:true});
    if(errors.length)throw Error(errors.join('\n'));
    console.log('Browser configuration, invalid-write recovery, device navigation and firewall view passed');
  } finally {await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
