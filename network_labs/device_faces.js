/* Family-specific shells and role dashboards. Shared forms operate on one model. */
function applyIdentity(){
 document.body.dataset.skin=S.profile.skin;
 const logo=document.querySelector('.logo');logo.textContent=S.profile.title;
 document.querySelector('.railcap').textContent=S.profile.role==='Firewall'?'Security appliance':S.profile.role==='NAS'?'Applications':'Device settings';
 document.querySelector('.railfoot').textContent='Prototype simulé · fonctions implémentées uniquement';
 $('cli').hidden=!S.profile.native&&S.profile.console!=='simulator';
 $('deviceTitle').textContent=(S.node.hostname||node)+' · '+S.profile.model;
}
function familyMenu(items){
 const skin=S.profile.skin,role=S.profile.role;
 let names={};
 if(skin==='fortios')names={overview:'Dashboard · Status',ports:'Network · Interfaces',firewall:'Policy & Objects · Firewall Policy',config:'System · Configuration'};
 if(skin==='panos')names={overview:'Dashboard',firewall:'Policies',ports:'Network',config:'Device'};
 if(skin==='asdm')names={overview:'Home · Device Dashboard',ports:'Configuration · Interfaces',firewall:'Configuration · Access Rules',config:'Monitoring · Configuration'};
 if(skin==='sophos')names={overview:'Control center',ports:'Configure · Network',firewall:'Protect · Rules and policies',config:'System services'};
 if(skin==='checkpoint')names={overview:'Gateways & Servers',ports:'Network Management',firewall:'Security Policies · Access Control',config:'Manage & Settings'};
 if(skin==='sonicwall')names={overview:'Monitor · System',ports:'Network · Interfaces',firewall:'Policy · Rules',config:'Device · Settings'};
 if(skin==='jweb')names={overview:'Dashboard',ports:'Network · Interfaces',firewall:'Security · Policies',config:'Administration'};
 if(skin==='pfsense')names={overview:'Status',ports:'Interfaces',firewall:'Firewall · Rules',config:'Diagnostics · Configuration'};
 if(skin==='opnsense')names={overview:'Lobby · Dashboard',ports:'Interfaces · Overview',firewall:'Firewall · Rules',config:'System · Configuration'};
 if(skin==='dsm'||skin==='qts')names={overview:'Bureau',network:'Panneau de configuration · Réseau',services:'Services réseau',diagnostics:'Outils réseau',config:'Informations système'};
 if(role==='Caméra')names={overview:'Live view',network:'System · Network',services:'Stream · RTSP',diagnostics:'Maintenance · Diagnostics',config:'System information'};
 if(role==='Téléphone IP')names={overview:'Status',network:'Network · Basic',services:'Account · SIP',diagnostics:'Settings · Diagnostics',config:'Status · System'};
 if(role==='Imprimante')names={overview:'État du périphérique',network:'Réseau · TCP/IP',services:'Protocoles d’impression',diagnostics:'Diagnostic réseau',config:'Informations produit'};
 if(skin==='windows')names={overview:'Accueil',network:'Réseau et Internet · Ethernet',services:'Ports de services simulés',diagnostics:'Diagnostic réseau',config:'Informations système'};
 if(skin==='linux')names={overview:'Vue d’ensemble',network:'Réseau · Filaire',services:'Services réseau',diagnostics:'Diagnostic',config:'À propos'};
 if(skin==='unifi')names={overview:'Devices · Overview',ports:'Port Manager',vlans:'Networks',config:'Device settings'};
 if(skin==='routeros')names={overview:'Quick Set',ports:'Interfaces',vlans:'Bridge · VLANs',config:'System · Resources'};
 if(['tplink','netgear','aruba','dlink','unifi','routeros'].includes(skin))items=items.filter(([id])=>id!=='switching');
 return items.map(([id,text])=>[id,names[id]||text]);
}
function familyOverview(){
 const n=S.node,role=S.profile.role,skin=S.profile.skin;
 let state=S.links.some(x=>x.enabled),ip=n.address||'Non configurée';
 const launch=(id,name,desc)=>`<button class="launch" data-launch="${id}"><span class="appicon">${{network:'◎',services:'▤',diagnostics:'↗',config:'⚙',firewall:'▥',ports:'▦'}[id]||'▦'}</span><strong>${name}</strong><small>${desc}</small></button>`;
 const info=()=>`<dl class="meta"><dt>Modèle</dt><dd>${e(S.profile.model)}</dd><dt>Adresse IPv4</dt><dd>${e(ip)}</dd><dt>Adresse MAC</dt><dd>${e(n.mac)}</dd><dt>État LAN</dt><dd>${badge(state)}</dd></dl>`;
 if(role==='NAS')return `<div class="desktop-home"><div class="desktop-welcome"><h1>${e(n.hostname||n.name)}</h1><p>${skin==='qts'?'QTS · espace de gestion réseau':'DiskStation · espace de gestion réseau'}</p></div><div class="app-grid">${launch('network','Panneau de configuration','Interfaces, IPv4 et DNS')}${launch('services','Services réseau','SMB et ports simulés')}${launch('diagnostics','Outils réseau','Connectivité et filtrage')}${launch('config','Informations','Configuration du lab')}</div><section class="card nas-status"><h2>État réseau du NAS</h2>${info()}${note('Stockage, disques, dossiers et sessions SMB ne sont pas émulés. Les services déclarés servent aux tests de connectivité.')}</section></div>`;
 if(role==='Caméra')return title('Live view','Surveillance de la connexion réseau de la caméra.')+`<div class="camera-grid"><section class="viewport"><svg viewBox="0 0 120 80" aria-hidden="true"><rect x="12" y="20" width="65" height="40" rx="7"/><path d="M77 30l30-14v48L77 50z"/></svg><h2>Flux vidéo indisponible dans la simulation</h2><p>Le profil simule le réseau et le port RTSP ; aucune image de caméra n’est générée.</p></section><section class="card"><h2>Camera status</h2>${info()}<p>RTSP / TCP 554 : ${badge(!!n.services['tcp/554'])}</p>${launch('network','System · Network','Configurer la connexion')}${launch('services','Stream settings','Activer le port RTSP simulé')}</section></div>`;
 if(role==='Imprimante')return title('État du périphérique','Gestion réseau et protocoles d’impression.')+`<div class="printer-home"><section class="printer-visual"><svg viewBox="0 0 160 170" aria-hidden="true"><path d="M45 50V10h70v40M40 130H15V55h130v75h-25M40 100h80v60H40z"/><path d="M55 120h50m-50 15h50"/><circle cx="126" cy="75" r="4"/></svg><h2>${e(S.profile.model)}</h2>${badge(state)}</section><section class="card"><h2>Informations réseau</h2>${info()}<p>Impression RAW / TCP 9100 : ${badge(!!n.services['tcp/9100'])}</p>${launch('network','Configuration TCP/IP','Adresse et passerelle')}${launch('services','Protocoles','Disponibilité des ports')}</section></div>`+note('Les niveaux d’encre, consommables et travaux ne sont pas simulés.');
 if(role==='Téléphone IP')return title('Status','Informations du terminal IP.')+`<div class="phone-status"><section class="card"><h2>Network</h2>${info()}${launch('network','Network · Basic','DHCP ou IPv4 statique')}</section><section class="card"><h2>Account · SIP</h2><div class="phone-lcd">${e(n.hostname||n.name)}<br>${e(ip)}<br><small>SIP / UDP 5060 ${n.services['udp/5060']?'ouvert dans le modèle':'fermé dans le modèle'}</small></div>${launch('services','SIP service','Activer / désactiver le port simulé')}${note('Aucun compte SIP enregistré ni appel réel ; ces états ne sont pas inventés.')}</section></div>`;
 if(skin==='windows'||skin==='linux')return title(skin==='windows'?'Réseau et Internet':'Réseau','Connexion Ethernet du poste.')+`<section class="card os-network"><div class="ethernet-icon">◎</div><div><h2>Ethernet</h2><p>${state?'Connecté au lab':'Non connecté au lab'}</p><p>${e(ip)}</p></div>${launch('network',skin==='windows'?'Propriétés Ethernet':'Paramètres de la connexion','Adresse, passerelle et DNS')}</section><div class="os-options">${launch('diagnostics','Diagnostic réseau','Ping et tests de port')}${launch('config','Propriétés du système',S.profile.model)}</div>`;
 if(role==='Firewall')return title(skin==='panos'?'Dashboard':skin==='pfsense'?'Status / Dashboard':'Dashboard · Status','État du firewall transparent et décisions du test courant.')+`<div class="security-grid"><section class="card"><h2>System information</h2><dl class="meta"><dt>Hostname</dt><dd>${e(n.hostname||n.name)}</dd><dt>Model</dt><dd>${e(S.profile.model)}</dd><dt>Mode du modèle</dt><dd>Bridge LAN · ${e(n.firewall_mode)}</dd><dt>Default action</dt><dd>${e(n.firewall_default)}</dd></dl>${launch('ports','Interfaces','État des deux ports LAN')}</section><section class="card"><h2>Policy overview</h2><div class="policy-count">${n.firewall_rules.length}<small>règles du modèle</small></div><div class="policy-totals"><span>${S.counters.allow} autorisés</span><span>${S.counters.deny} refusés</span></div>${launch('firewall',skin==='fortios'?'Policy & Objects':'Security policies','Configurer les règles réseau')}</section><section class="card security-log"><h2>Traffic · Dernier test</h2><pre>${e(S.firewall_log.join('\n')||'Aucune décision enregistrée.')}</pre></section></div>`;
 return null;
}
function bindFamilyActions(){document.querySelectorAll('[data-launch]').forEach(b=>b.onclick=()=>navigate(b.dataset.launch));}
