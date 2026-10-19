// Optional development check; requires Playwright. No browser dependency for end users.
const {chromium}=require('playwright');const assert=require('node:assert/strict');const path=require('node:path');
const output=process.env.QA_OUTPUT||process.cwd();
(async()=>{
 const b=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE||undefined,headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 const p=await b.newPage({viewport:{width:1440,height:1000}});let errors=[];p.on('pageerror',x=>errors.push(String(x)));
 await p.goto(process.env.DEVICE_URL);await p.locator('#page h1').waitFor();
 await p.getByRole('button',{name:'VLANs',exact:true}).click();await p.locator('#vlan').fill('30');await p.locator('#vname').fill('WEB_CLIENTS');await p.getByRole('button',{name:'Créer / modifier le VLAN',exact:true}).click();await p.getByRole('cell',{name:'WEB_CLIENTS',exact:true}).waitFor();
 await p.screenshot({path:path.join(output,'web_switch.png'),fullPage:true});
 await p.locator('#inventory').selectOption('PC1');await p.locator('#page h1').waitFor();
 await p.locator('#nav [data-page=network]').click();await p.locator('#address').fill('10.0.0.99/24');await p.locator('#gateway').fill('bad');await p.getByRole('button',{name:'Appliquer les modifications',exact:true}).click();await p.locator('#toast.error').waitFor();
 await p.locator('#refresh').click();await p.locator('#address').waitFor();await p.waitForFunction(()=>document.getElementById('address')?.value==='192.168.10.10/24');
 await p.locator('#nav [data-page=diagnostics]').click();await p.locator('#testproto').selectOption('tcp');await p.locator('#target').fill('nas.lan');await p.locator('#testport').fill('445');await p.getByRole('button',{name:'Exécuter le test',exact:true}).click();await p.waitForFunction(()=>document.getElementById('trace')?.textContent.includes('service SMB accessible'));
 await p.screenshot({path:path.join(output,'web_diagnostics.png'),fullPage:true});
 await p.locator('#inventory').selectOption('NAS1');await p.locator('#page h1').waitFor();await p.locator('#nav [data-page=services]').click();await p.locator('#svcport').fill('443');await p.locator('#svcname').fill('HTTPS');await p.getByRole('button',{name:'Activer le service',exact:true}).click();await p.getByRole('cell',{name:'HTTPS',exact:true}).waitFor();
 await p.locator('#inventory').selectOption('SRV1');await p.locator('#page h1').waitFor();await p.getByRole('button',{name:'DNS local',exact:true}).click();await p.locator('#dname').fill('web-test.lan');await p.locator('#dip').fill('192.168.10.20');await p.getByRole('button',{name:'Ajouter / remplacer un enregistrement',exact:true}).click();await p.getByRole('cell',{name:'web-test.lan',exact:true}).waitFor();
 await p.locator('#inventory').selectOption('FW1');await p.locator('#page h1').waitFor();await p.locator('#nav [data-page=firewall]').click();
 await p.locator('#ruleid').fill('50');await p.locator('#rport').fill('443');await p.locator('#src').fill('192.168.10.10/32');await p.locator('#dst').fill('192.168.10.20/32');await p.getByRole('button',{name:'Ajouter / remplacer la règle',exact:true}).click();await p.getByRole('cell',{name:'50',exact:true}).waitFor();
 await p.screenshot({path:path.join(output,'web_firewall.png'),fullPage:true});
 await p.setViewportSize({width:390,height:844});await p.evaluate(()=>window.scrollTo(0,0));await p.waitForTimeout(100);assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await p.screenshot({path:path.join(output,'web_mobile.png'),fullPage:true});
 // Distinct actual DOM structures, not merely different model labels.
 await p.setViewportSize({width:1440,height:1000});
 const families=[['PC1','windows','.os-network'],['NAS1','qts','.desktop-home'],['PRN1','brother','.printer-home'],['CAM1','axis','.viewport'],['FW1','fortios','.security-grid'],['SYNO','dsm','.desktop-home'],['PA','panos','.security-grid'],['PHONE','yealink','.phone-status'],['LINUX','linux','.os-network'],['PFS','pfsense','.security-grid'],['UBNT','unifi','.ports'],['MT','routeros','.ports'],['ASA','asdm','.security-grid'],['SOPHOS','sophos','.security-grid'],['CP','checkpoint','.security-grid'],['SONIC','sonicwall','.security-grid'],['JUNIPER','jweb','.security-grid'],['OPN','opnsense','.security-grid'],['TP','tplink','.ports'],['ARUBA','aruba','.ports'],['DLINK','dlink','.ports'],['CISCO','cisco','.ports'],['HP','hp','.printer-home']];
 for(const [name,skin,selector] of families){
  await p.locator('#inventory').selectOption(name);
  await p.waitForFunction(([id,skin])=>document.getElementById('inventory').value===id&&document.body.dataset.skin===skin,[name,skin]);
  await p.locator(selector).waitFor();await p.screenshot({path:path.join(output,'family_'+skin+'.png'),fullPage:true});
  assert.equal(await p.locator('#cli').isVisible(),['windows','linux','fortios','panos','routeros','cisco'].includes(skin));
  await p.setViewportSize({width:390,height:844});await p.waitForTimeout(40);
  if(!await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)){await p.screenshot({path:path.join(output,'overflow_'+skin+'.png'),fullPage:true});console.log(await p.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,cls:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right})).slice(0,20)));throw Error(skin+' mobile overflow');}
  await p.setViewportSize({width:1440,height:1000});
 }
 assert.deepEqual(errors,[]);console.log('Browser checks passed: live VLAN, rollback, TCP probe, NAS service, DNS record, firewall rule, differentiated family dashboards, mobile rendering.');await b.close();
})().catch(e=>{console.error(e);process.exit(1)});
