/* Native FortiOS subset: each form sends the CLI block displayed in its preview. */
let fgSelected=null,fgObject=null;
const fgServices={ALL:['any',0],PING:['icmp',0],HTTP:['tcp',80],HTTPS:['tcp',443],DNS:['tcpudp',53],SMB:['tcp',445],RDP:['tcp',3389]};
const fgQuote=value=>JSON.stringify(String(value));
const fgMeta=id=>(S.node.vendor.fortios_policies||[]).find(r=>r.id===id);
function fgService(rule){return Object.keys(fgServices).find(k=>fgServices[k][0]===rule.protocol&&fgServices[k][1]===rule.port)||`${rule.protocol}/${rule.port||'any'}`;}
function fgAddress(cidr){return cidr==='0.0.0.0/0'?'all':Object.keys(S.node.vendor.fortios_addresses||{}).find(k=>S.node.vendor.fortios_addresses[k]===cidr)||null;}
async function fgApply(commands){
 if(busy)return;busy=true;
 try{S=await api('native',{revision:S.revision,commands});dirty=false;document.querySelector('.fg-dialog')?.remove();render();toast('FortiOS : bloc CLI appliqué au modèle.');}
 catch(err){toast(err.message,true);const d=document.querySelector('.fg-dialog');if(d){d.querySelector('.fg-help').textContent=err.message;}}
 finally{busy=false;}
}
function fgDialog(title,fields,commands,help){
 document.querySelector('.fg-dialog')?.remove();
 const dialog=document.createElement('dialog');dialog.className='fg-dialog';
 dialog.innerHTML=`<h2>${e(title)}</h2><form id="fg-form"><div class="fg-fields">${fields}</div><p class="fg-help">${e(help)}</p><pre class="fg-cli" aria-label="CLI equivalent"></pre><div class="fg-actions"><button type="button" id="fg-cancel">Cancel</button><button type="submit" class="primary">OK</button></div></form>`;
 document.body.append(dialog);
 const preview=()=>{try{dialog.querySelector('.fg-cli').textContent=commands().join('\n');}catch(err){dialog.querySelector('.fg-cli').textContent=err.message;}};
 dialog.querySelector('form').oninput=()=>{dirty=true;preview();};
 dialog.querySelector('form').onsubmit=ev=>{ev.preventDefault();try{fgApply(commands());}catch(err){dialog.querySelector('.fg-help').textContent=err.message;}};
 const close=()=>{dirty=false;dialog.close();dialog.remove();};dialog.querySelector('#fg-cancel').onclick=close;dialog.oncancel=ev=>{ev.preventDefault();close();};
 preview();dialog.showModal();
}
function fgField(id,label,value='',type='text'){return `<label for="${id}">${e(label)}</label><input id="${id}" type="${type}" value="${e(value)}" maxlength="255">`;}
function fgSelect(id,label,value,choices){return `<label for="${id}">${e(label)}</label><select id="${id}">${choices.map(k=>`<option value="${e(k)}" ${k===value?'selected':''}>${e(k)}</option>`).join('')}</select>`;}
function fgEditPolicy(id=null){
 const rule=S.node.firewall_rules.find(r=>r.id===id),meta=fgMeta(id)||{};
 const addresses=['all',...Object.keys(S.node.vendor.fortios_addresses||{})];
 const src=meta.srcaddr||(rule?fgAddress(rule.source):'all'),dst=meta.dstaddr||(rule?fgAddress(rule.target):'all');
 const svc=meta.service||(rule?fgService(rule):'HTTPS');
 let fields=fgField('fg-id','Policy ID (0 = auto)',id===null?0:id,'number')+fgField('fg-name','Name',meta.name||'')+
  fgSelect('fg-in','Incoming Interface','any',['any'])+fgSelect('fg-out','Outgoing Interface','any',['any'])+
  fgSelect('fg-source','Source',src||'Select a named object',[...(src?[]:['Select a named object']),...addresses])+
  fgSelect('fg-destination','Destination',dst||'Select a named object',[...(dst?[]:['Select a named object']),...addresses])+
  fgSelect('fg-schedule','Schedule','always',['always'])+fgSelect('fg-service','Service',svc,Object.keys(fgServices).includes(svc)?Object.keys(fgServices):[svc,...Object.keys(fgServices)])+
  fgSelect('fg-action','Action',rule?.action==='deny'?'deny':'accept',['accept','deny'])+fgField('fg-comments','Comments',meta.comments||'');
 fgDialog(id===null?'New Policy':'Edit Policy',fields,()=>{
  if(!Number.isInteger(Number(val('fg-id')))||Number(val('fg-id'))<0||Number(val('fg-id'))>65535)throw Error('Policy ID : entier 0..65535.');
  if(!addresses.includes(val('fg-source'))||!addresses.includes(val('fg-destination')))throw Error('Créer puis sélectionner les objets adresse nommés pour cette règle importée.');
  if(!fgServices[val('fg-service')])throw Error('Sélectionner un service du sous-ensemble implémenté.');
  return ['config firewall policy','edit '+val('fg-id'),...['name','srcintf','dstintf','srcaddr','dstaddr','schedule','service','action','comments'].map((key,i)=>'set '+key+' '+fgQuote(val(['fg-name','fg-in','fg-out','fg-source','fg-destination','fg-schedule','fg-service','fg-action','fg-comments'][i]))),'next','end'];
 },'Sous-ensemble transparent : interfaces any, schedule always, un objet source/destination et un service. NAT, UTM et VPN non implémentés.');
 if(id!==null)$('fg-id').readOnly=true;
}
function fgMove(){
 const ids=S.node.firewall_rules.map(r=>String(r.id));
 fgDialog('Move Policy',fgSelect('fg-moving','Policy',String(fgSelected),ids)+fgSelect('fg-direction','Position','before',['before','after'])+fgSelect('fg-anchor','Reference policy',ids.find(x=>x!==String(fgSelected)),ids),()=>['config firewall policy',`move ${val('fg-moving')} ${val('fg-direction')} ${val('fg-anchor')}`,'end'],'La séquence détermine la première règle correspondante ; les IDs ne sont pas renumérotés.');
}
function fgEditAddress(name=null){
 const cidr=(S.node.vendor.fortios_addresses||{})[name];let ip='192.168.10.0',mask='255.255.255.0';
 if(cidr){ip=cidr.split('/')[0];let bits=Number(cidr.split('/')[1]);mask=[0,1,2,3].map(i=>Math.max(0,Math.min(255,256-2**Math.max(0,8-Math.max(0,bits-8*i))))).join('.');}
 fgDialog(name===null?'New Address':'Edit Address',fgField('fg-object','Name',name||'')+fgField('fg-ip','IP Address',ip)+fgField('fg-mask','Netmask',mask),()=>{
  if(!val('fg-object')||val('fg-object')==='all')throw Error('Nom d’objet non vide, distinct de all.');
  return ['config firewall address','edit '+fgQuote(val('fg-object')),'set subnet '+val('fg-ip')+' '+val('fg-mask'),'next','end'];
 },'IPv4 subnet uniquement. Les changements de subnet sont appliqués aux politiques qui utilisent cet objet.');
 if(name!==null)$('fg-object').readOnly=true;
}
function renderFortiOS(){
 const objects=page==='addresses',rules=S.node.firewall_rules;
 if(!rules.some(r=>r.id===fgSelected))fgSelected=null;
 if(!Object.hasOwn(S.node.vendor.fortios_addresses||{},fgObject))fgObject=null;
 let rows=objects?Object.entries(S.node.vendor.fortios_addresses||{}).map(([name,cidr])=>`<tr data-object="${e(name)}" class="${fgObject===name?'selected':''}"><td>${e(name)}</td><td>Subnet</td><td>${e(cidr)}</td></tr>`):rules.map(r=>{const meta=fgMeta(r.id)||{};return `<tr data-policy="${r.id}" class="${fgSelected===r.id?'selected':''}"><td>${e(meta.name||'Policy')} (${r.id})</td><td>${e(meta.srcaddr||r.source)}</td><td>${e(meta.dstaddr||r.target)}</td><td>always</td><td>${e(meta.service||fgService(r))}</td><td class="fg-${r.action==='allow'?'accept':'deny'}">${r.action==='allow'?'ACCEPT':'DENY'}</td><td>Non implémenté</td><td>${e(meta.comments||'')}</td></tr>`;});
 const headers=objects?['Name','Type','Subnet']:['Name (ID)','Source','Destination','Schedule','Service','Action','NAT','Comments'];
 $('page').innerHTML=`<div class="fg-reference">Reconstitution partielle · référence FortiOS 7.4 · moteur LAN pédagogique, aucun firmware FortiOS. Les fonctions non implémentées ne sont pas annoncées actives.</div><h1 class="fg-heading">${objects?'Addresses':'Firewall Policy'}</h1><div class="fg-tools"><button class="fg-create" id="fg-create">+ Create New</button><button id="fg-edit" disabled>Edit</button><button id="fg-delete" disabled>Delete</button>${objects?'':'<button id="fg-move" disabled>Move</button><span class="fg-sequence">By Sequence</span>'}<input id="fg-search" aria-label="Search" placeholder="Search"></div><div class="fg-table"><table><thead><tr>${headers.map(x=>`<th>${e(x)}</th>`).join('')}</tr></thead><tbody>${rows.join('')||`<tr><td colspan="${headers.length}">No entries</td></tr>`}${objects?'':`<tr class="fg-implicit"><td>Implicit · modèle</td><td>all</td><td>all</td><td>always</td><td>ALL</td><td>${e(S.node.firewall_default.toUpperCase())}</td><td>—</td><td>Action par défaut du modèle</td></tr>`}</tbody></table></div>`;
 $('fg-create').onclick=()=>objects?fgEditAddress():fgEditPolicy();
 function selectRow(row){document.querySelectorAll('.fg-table .selected').forEach(x=>x.classList.remove('selected'));row.classList.add('selected');if(objects)fgObject=row.dataset.object;else fgSelected=Number(row.dataset.policy);$('fg-edit').disabled=false;$('fg-delete').disabled=false;if($('fg-move'))$('fg-move').disabled=rules.length<2;}
 document.querySelectorAll('[data-policy],[data-object]').forEach(row=>{row.onclick=()=>selectRow(row);row.ondblclick=()=>{selectRow(row);objects?fgEditAddress(fgObject):fgEditPolicy(fgSelected);};});
 const selected=document.querySelector('.fg-table tr.selected');if(selected)selectRow(selected);
 $('fg-edit').onclick=()=>objects?fgEditAddress(fgObject):fgEditPolicy(fgSelected);
 $('fg-delete').onclick=()=>fgDialog(objects?'Delete Address':'Delete Policy',`<div style="grid-column:1/-1">${e(objects?fgObject:String(fgSelected))}</div>`,()=>['config firewall '+(objects?'address':'policy'),'delete '+(objects?fgQuote(fgObject):fgSelected),'end'],'La suppression est appliquée au projet ; un objet référencé ne peut pas être supprimé.');
 if($('fg-move'))$('fg-move').onclick=fgMove;
 $('fg-search').oninput=()=>document.querySelectorAll('[data-policy],[data-object]').forEach(row=>row.hidden=!row.textContent.toLowerCase().includes($('fg-search').value.toLowerCase()));
}
