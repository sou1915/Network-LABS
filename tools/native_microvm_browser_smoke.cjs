const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(10000);
  await page.goto(process.env.NATIVE_WEB_VM_URL);await page.locator('#message').filter({hasText:'Projet synchronisé'}).waitFor();
  if(!await page.locator('#apply').isDisabled())throw Error('VM network form must remain readonly');
  await page.locator('[data-page="vmresources"]').click();
  async function save(status=200){const response=page.waitForResponse(r=>r.url().endsWith('/api/apply')&&r.request().method()==='POST');await page.locator('#sectionSave').click();const r=await response;if(r.status()!==status)throw Error(await r.text());await page.locator(status===200?'#message':'#message.error').filter({hasText:status===200?'Section appliquée':''}).waitFor()}
  await page.locator('#vmMemory').fill('192');await page.locator('#vmCpus').fill('2');await save();
  await page.locator('#vmMemory').fill('1800');await save(400);await page.locator('#sectionReload').click();await page.waitForFunction(()=>document.getElementById('vmMemory')?.value==='192');
  await page.screenshot({path:'/tmp/native-microvm-resources.png',fullPage:true});
  if(errors.length)throw Error(errors.join('\n'));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
