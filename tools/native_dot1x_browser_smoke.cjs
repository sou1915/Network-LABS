const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:900}});page.setDefaultTimeout(10000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.env.NATIVE_WEB_DOT1X_URL);await page.locator('#message').filter({hasText:'Projet synchronisé'}).waitFor();
  await page.locator('[data-page="dot1x"]').click();
  async function save(expected=200){const waiting=page.waitForResponse(r=>r.url().endsWith('/api/apply')&&r.request().method()==='POST');await page.locator('#sectionSave').click();const response=await waiting;if(response.status()!==expected)throw Error(await response.text());await page.locator(expected===200?'#message':'#message.error').filter({hasText:expected===200?'Section appliquée':''}).waitFor()}
  await page.locator('#dot1xUsers').fill('learner, guest');await page.locator('#dot1xSeconds').fill('4');await page.locator('#dot1xRenewals').fill('1');await save();
  await page.locator('#dot1xSeconds').fill('31');await save(400);await page.locator('#sectionReload').click();await page.waitForFunction(()=>document.getElementById('dot1xSeconds')?.value==='4');
  await page.screenshot({path:'/tmp/native-dot1x-local.png',fullPage:true});
  if(errors.length)throw Error(errors.join('\n'));console.log('Browser wired policy save and invalid duration recovery passed');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
