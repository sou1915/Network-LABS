/* The « Simple » design of the device pages, beside the vendor design (FortiGate, ASDM, pfSense, WebUI…): one layout for
 * every device, in the application's black and white. A clickable front panel (a port opens a drawer to change it), task tabs in plain words, health checks
 * that say what to fix with a button that does it, and the neighbours one click away. The choice of design is kept in
 * the browser (localStorage). Every change goes through the same checked actions as the other pages. */
'use strict';
(() => {
  const KEY = 'network-labs-design';
  // The browser's choice, else the product's own interface (the « Constructeur » design: a copy of the real product).
  // The browser's choice, else the product's own interface; « studio », the dark design of earlier versions, is now « simple ».
  window.nlDesign = () => { try { const kept = localStorage.getItem(KEY) || 'vendor'; return kept === 'studio' ? 'simple' : kept; } catch (error) { return 'vendor'; } };
  window.nlSetDesign = value => {
    try { localStorage.setItem(KEY, value); } catch (error) { /* private window: the choice lasts this page only */ }
    chosen = value;
    render();
  };
  let chosen = null;  // when localStorage refuses, the page still switches
  const design = () => chosen || window.nlDesign();
  window.nlDesignNow = () => design();  // what the other faces ask before drawing themselves

  const css = document.createElement('style');
  css.textContent = `
  body.sd{margin:0;background:#f7f7f7}
  body.sd>header,body.sd>.layout{display:none}
  .sd-app{font:14px Inter,Arial,sans-serif;color:#111111;min-height:100vh}
  .sd-top{position:sticky;top:0;z-index:4;display:flex;align-items:center;gap:16px;padding:12px 28px;background:rgba(255,255,255,.92);
    backdrop-filter:blur(8px);border-bottom:1px solid #e9e9e9}
  .sd-top img{width:76px;height:auto;filter:grayscale(1) drop-shadow(0 4px 8px rgba(0,0,0,.18))}
  .sd-top h1{margin:0;font-size:20px;letter-spacing:-.2px}.sd-top .model{color:#595959;font-size:13px;margin-top:2px}
  .sd-badge{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:4px 11px;font-size:12px;font-weight:600;background:#f2f2f2;color:#424242}
  .sd-badge i{width:8px;height:8px;border-radius:50%;background:#a6a6a6}.sd-badge i.on{background:#111111;box-shadow:0 0 8px #111111}
  .sd-grow{flex:1}
  .sd-switch{display:inline-flex;background:#f2f2f2;border-radius:999px;padding:3px}
  .sd-switch button{border:0;background:none;border-radius:999px;padding:6px 14px;font-size:12.5px;color:#4a4a4a;cursor:pointer}
  .sd-switch button.on{background:#ffffff;color:#111111;font-weight:600;box-shadow:0 1px 4px rgba(17,17,17,.15)}
  .sd-icon{border:1px solid #e2e2e2;background:#ffffff;border-radius:10px;padding:7px 11px;cursor:pointer}
  .sd-wrap{max-width:1180px;margin:0 auto;padding:22px 28px 60px}
  .sd-chassis{border-radius:18px;padding:18px 20px;background:linear-gradient(180deg,#393939,#202020);box-shadow:0 12px 28px rgba(17,17,17,.18)}
  .sd-chassis .head{display:flex;justify-content:space-between;align-items:center;color:#a9a9a9;font-size:12px;margin-bottom:12px}
  .sd-chassis .head b{color:#ffffff;font-size:14px}
  .sd-ports{display:flex;flex-wrap:wrap;gap:10px}
  .sd-port{width:96px;border-radius:12px;padding:9px 8px 8px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);color:#b8b8b8;
    text-align:center;cursor:pointer;transition:transform .12s,background .12s,border-color .12s;position:relative}
  .sd-port:hover{transform:translateY(-2px);background:rgba(255,255,255,.11);border-color:#ffffff}
  .sd-port.sel{border-color:#ffffff;background:rgba(255,255,255,.16)}
  .sd-port b{display:block;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sd-port .jack{height:24px;width:32px;margin:6px auto;border-radius:4px;background:#111111;border:1px solid #606060;position:relative}
  .sd-port .jack:after{content:'';position:absolute;left:9px;right:9px;bottom:-1px;height:6px;background:#111111;border:1px solid #606060;border-top:0}
  .sd-port .dot{position:absolute;top:9px;right:9px;width:8px;height:8px;border-radius:50%;background:#4a4a4a}
  .sd-port.up .dot{background:#ffffff;box-shadow:0 0 8px rgba(255,255,255,.7)}.sd-port.down .dot{background:transparent;border:1.5px solid #ffffff;box-sizing:border-box}
  .sd-port small{display:block;font-size:10.5px;color:#a8a8a8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sd-port .vbar{position:absolute;left:10px;right:10px;bottom:0;height:3px;border-radius:3px 3px 0 0}
  .sd-port.spare{opacity:.35;cursor:default}.sd-port.spare:hover{transform:none;background:rgba(255,255,255,.05);border-color:rgba(255,255,255,.1)}
  .sd-legend{display:flex;gap:14px;margin-top:12px;font-size:11.5px;color:#a8a8a8;flex-wrap:wrap}
  .sd-legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:-1px}
  .sd-tabs{display:flex;gap:8px;margin:22px 0 16px;flex-wrap:wrap}
  .sd-tabs button{border:1px solid #e2e2e2;background:#ffffff;border-radius:999px;padding:9px 18px;font-size:13.5px;cursor:pointer;color:#111111}
  .sd-tabs button:hover{border-color:#bebebe}
  .sd-tabs button.on{background:#111111;border-color:#111111;color:#ffffff;font-weight:600}
  .sd-tabs button span{display:inline-block;margin-left:6px;border-radius:999px;padding:0 7px;font-size:11.5px;background:rgba(0,0,0,.08)}
  .sd-tabs button.on span{background:rgba(255,255,255,.25)}
  .sd-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
  .sd-card{background:#ffffff;border:1px solid #e9e9e9;border-radius:16px;padding:16px 18px}
  .sd-card h3{margin:0 0 12px;font-size:14.5px}.sd-card .sub{color:#626262;font-size:12.5px}
  .sd-kpi span{color:#626262;font-size:12.5px}.sd-kpi strong{display:block;font-size:28px;margin-top:4px;letter-spacing:-.5px}
  .sd-kpi em{font-style:normal;font-size:12px;color:#626262}
  .sd-span2{grid-column:span 2}.sd-span4{grid-column:1/-1}
  .sd-check{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #f1f1f1}
  .sd-check:last-child{border-bottom:0}
  .sd-check .mark{width:28px;height:28px;border-radius:50%;display:grid;place-items:center;font-size:14px;flex:none}
  .sd-check.ok .mark{background:#efefef;color:#111111}.sd-check.warn .mark{background:#f3f3f3;color:#5f5f5f}.sd-check.info .mark{background:#efefef;color:#111111}
  .sd-check .text{flex:1;line-height:1.4}.sd-check .text small{display:block;color:#626262}
  .sd-btn{border:1px solid #d9d9d9;background:#ffffff;border-radius:10px;padding:7px 13px;cursor:pointer;font-size:13px;color:#111111}
  .sd-btn:hover{border-color:#b5b5b5;background:#f7f7f7}
  .sd-btn.primary{background:#111111;border-color:#111111;color:#ffffff}.sd-btn.primary:hover{background:#111111}
  .sd-btn:disabled{opacity:.5;cursor:default}
  .sd-chips{display:flex;flex-wrap:wrap;gap:8px}
  .sd-chip{display:inline-flex;align-items:center;gap:7px;border:1px solid #e2e2e2;border-radius:999px;padding:6px 12px;background:#ffffff;cursor:pointer;font-size:13px}
  .sd-chip:hover{border-color:#b5b5b5;background:#f7f7f7}.sd-chip small{color:#626262}
  .sd-row{display:grid;grid-template-columns:150px 1fr 1fr 1fr auto;gap:12px;align-items:center;padding:11px 4px;border-bottom:1px solid #f1f1f1}
  .sd-row:last-child{border-bottom:0}.sd-row b{font-size:13.5px}.sd-row .muted{color:#626262;font-size:12.5px}
  .sd-pill{display:inline-flex;align-items:center;gap:6px;font-size:12.5px}.sd-pill i{width:8px;height:8px;border-radius:50%;background:#a6a6a6}
  .sd-pill.up i{background:#111111}.sd-pill.down i{background:#5f5f5f}
  .sd-search{width:100%;box-sizing:border-box;border:1px solid #e2e2e2;border-radius:12px;padding:10px 14px;font:inherit;margin-bottom:10px}
  .sd-tag{display:inline-block;border-radius:999px;padding:3px 10px;font-size:12px;font-weight:600;background:#f2f2f2;color:#424242}
  .sd-tag.green{background:#111111;color:#ffffff}.sd-tag.red{background:#ffffff;color:#111111;box-shadow:inset 0 0 0 1.5px #111111}.sd-tag.blue{background:#e6e6e6;color:#111111}
  .sd-tag.violet{background:#ffffff;color:#111111;box-shadow:inset 0 0 0 1px #8a8a8a}
  .sd-rule{display:flex;align-items:center;gap:12px;padding:11px 4px;border-bottom:1px solid #f1f1f1}.sd-rule:last-child{border-bottom:0}
  .sd-rule .n{width:26px;height:26px;border-radius:8px;background:#f2f2f2;display:grid;place-items:center;font-size:12px;font-weight:600;color:#424242}
  .sd-rule .what{flex:1}.sd-rule .what small{display:block;color:#626262}
  .sd-vlan{display:flex;align-items:flex-start;gap:14px;padding:12px 4px;border-bottom:1px solid #f1f1f1}.sd-vlan:last-child{border-bottom:0}
  .sd-vlan .sw{width:14px;height:14px;border-radius:4px;margin-top:3px;flex:none;box-shadow:inset 0 0 0 1px #111111}
  .sd-empty{padding:22px;border-radius:12px;background:#f8f8f8;color:#626262;text-align:center}
  .sd-shade{position:fixed;inset:0;background:rgba(17,17,17,.28);z-index:8}
  .sd-drawer{position:fixed;top:0;right:0;bottom:0;width:min(420px,94vw);background:#ffffff;z-index:9;box-shadow:-18px 0 40px rgba(17,17,17,.22);
    display:flex;flex-direction:column;animation:sdIn .16s ease-out}
  @keyframes sdIn{from{transform:translateX(30px);opacity:.4}to{transform:none;opacity:1}}
  .sd-drawer .head{padding:18px 20px;border-bottom:1px solid #e9e9e9;display:flex;align-items:center;gap:12px}
  .sd-drawer .head h2{margin:0;font-size:18px;flex:1}.sd-drawer .body{padding:18px 20px;overflow:auto;flex:1}
  .sd-drawer label{display:block;font-size:12.5px;color:#4b4b4b;margin:12px 0 6px}
  .sd-drawer input,.sd-drawer select{width:100%;box-sizing:border-box;border:1px solid #d9d9d9;border-radius:10px;padding:9px 12px;font:inherit}
  .sd-seg{display:flex;background:#f2f2f2;border-radius:10px;padding:3px}
  .sd-seg button{flex:1;border:0;background:none;border-radius:8px;padding:8px;cursor:pointer;color:#4a4a4a}
  .sd-seg button.on{background:#ffffff;color:#111111;font-weight:600;box-shadow:0 1px 4px rgba(17,17,17,.15)}
  .sd-drawer .foot{padding:14px 20px;border-top:1px solid #e9e9e9;display:flex;gap:10px;justify-content:flex-end}
  .sd-facts{display:grid;grid-template-columns:110px 1fr;gap:8px 12px;font-size:13px}.sd-facts span{color:#626262}
  .sd-err{color:#5f5f5f;font-size:12.5px;min-height:18px;margin-top:10px}
  .sd-note{font-size:12.5px;color:#626262;line-height:1.5;margin-top:10px}
  .sd-toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:#111111;color:#ffffff;border-radius:12px;padding:11px 16px;
    font-size:13px;box-shadow:0 10px 28px rgba(0,0,0,.28);z-index:10}
  .sd-back{position:fixed;right:18px;bottom:18px;z-index:10}
  @media (max-width:900px){.sd-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.sd-row{grid-template-columns:1fr 1fr}.sd-top img{display:none}}
  `;
  document.head.appendChild(css);

  const VLAN_COLOURS = ['#e6e6e6', '#9a9a9a', '#cfcfcf', '#7a7a7a', '#f5f5f5', '#b5b5b5', '#8a8a8a', '#dadada'];
  const vlanColour = vid => vid === 1 ? '#5c5c5c' : VLAN_COLOURS[vid % VLAN_COLOURS.length];
  const mask = prefix => [0, 8, 16, 24].map(s => (prefix >= s + 8 ? 255 : prefix <= s ? 0 : 256 - 2 ** (8 - (prefix - s)))).join('.');
  const prefixOf = text => {
    const parts = text.trim().split('.').map(Number);
    if (parts.length !== 4 || parts.some(p => !(p >= 0 && p <= 255))) return null;
    const bits = parts.map(p => p.toString(2).padStart(8, '0')).join('');
    return /^1*0*$/.test(bits) ? (bits.indexOf('0') === -1 ? 32 : bits.indexOf('0')) : null;
  };
  let tab = 'overview', drawer = null, filter = '', standardView = false, toastTimer = null;
  const root = document.createElement('div');
  root.className = 'sd-app';

  function toast(text) {
    let box = document.querySelector('.sd-toast');
    if (!box) { box = document.createElement('div'); box.className = 'sd-toast'; document.body.append(box); }
    box.textContent = text;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => box.remove(), 3800);
  }
  const roleName = role => ({router: 'Routeur', switch: 'Switch', firewall: 'Pare-feu', host: 'Poste'})[role] || role;
  const portName = port => (state.device.port_names || {})[port] || port;
  const peerName = p => p.peer ? p.peer.split(' · ')[0] : null;
  const tabs = () => {
    const role = state.node.role, d = state.device;
    const list = [['overview', 'Vue d’ensemble'], ['ports', role === 'host' ? 'Réseau' : 'Ports', d.ports.length]];
    if (role === 'switch') list.push(['vlans', 'VLAN', d.vlans.length]);
    if (role === 'firewall') list.push(['security', 'Sécurité', (state.node.firewall?.rules || []).length]);
    if (role !== 'switch') list.push(['routing', 'Routage', d.connected.length + d.static.length]);
    if (role !== 'host') list.push(['services', 'Services', (d.features || []).length]);
    return list;
  };

  // ---- what to look at first: checks with the button that fixes each ----
  function checks() {
    const n = state.node, d = state.device, found = [];
    const add = (kind, text, hint, action, label) => found.push({kind, text, hint, action, label});
    const cabled = d.ports.filter(p => p.peer);
    if (!cabled.length) add('warn', 'Aucun câble', 'L’équipement n’est relié à rien.', null);
    if (n.role === 'host') {
      const port = d.ports[0];
      const dhcp = (n.dhcp_clients || []).includes(port?.port);
      if (port && !port.address && !dhcp) add('warn', 'Pas d’adresse IP', 'Le poste ne peut joindre personne.', () => openDrawer(port.port), 'Configurer');
      else if (dhcp) add('ok', 'Adresse par DHCP', 'Le bail arrive au démarrage du poste.');
      else if (port) add('ok', `Adresse ${port.address}`, 'Configurée dans le projet.');
      if (port && port.address && !n.gateway && !dhcp) add('warn', 'Pas de passerelle', 'Le poste ne joint que son propre réseau.', () => openDrawer(port.port), 'Ajouter');
      else if (n.gateway) add('ok', `Passerelle ${n.gateway}`, 'Pour les autres réseaux.');
    } else if (n.role === 'switch') {
      const vlans = new Set(d.ports.map(p => p.vlan).filter(Boolean));
      add('info', d.vlans.length > 1 ? `${d.vlans.length} VLAN déclarés` : 'Tous les ports dans le VLAN 1',
        d.vlans.length > 1 ? `Ports d’accès répartis sur ${vlans.size} VLAN.` : 'Un seul domaine de diffusion.', () => { tab = 'vlans'; draw(); }, 'VLAN');
      const trunks = d.ports.filter(p => p.trunk);
      if (trunks.length) add('ok', `${trunks.length} trunk${trunks.length > 1 ? 's' : ''} 802.1Q`, trunks.map(p => p.name).join(', '));
    } else {
      for (const p of cabled.filter(p => !p.address && !d.subinterfaces.some(s => s.name.startsWith(p.name + '.'))))
        add('warn', `${p.name} est câblé sans adresse`, `Vers ${p.peer} : rien ne peut le traverser.`, () => openDrawer(p.port), 'Configurer');
      if (cabled.length && cabled.every(p => p.address)) add('ok', 'Chaque port câblé a son adresse', `${cabled.length} réseau${cabled.length > 1 ? 'x' : ''} connecté${cabled.length > 1 ? 's' : ''}.`);
      if (n.role === 'firewall') {
        const rules = n.firewall?.rules || [];
        if (!rules.length) add('warn', 'Aucune règle de sécurité', 'Tout le trafic qui traverse est bloqué (action par défaut).', () => { tab = 'security'; draw(); }, 'Règles');
        else add('ok', `${rules.length} règle${rules.length > 1 ? 's' : ''} de sécurité`, `${rules.filter(r => r.action === 'accept').length} autorise(nt), le reste bloque.`);
      }
      if (n.role === 'router' && !d.static.length && !(d.features || []).some(f => ['OSPF', 'RIP', 'EIGRP', 'BGP'].includes(f.name)) && d.connected.length > 1)
        add('info', 'Réseaux connectés seulement', 'Pour aller plus loin : une route statique ou un protocole, dans le terminal.', openTerminal, 'Terminal');
    }
    const free = d.ports.filter(p => !p.peer).length;
    if (free && n.role !== 'host') add('info', `${free} port${free > 1 ? 's' : ''} libre${free > 1 ? 's' : ''}`, 'Câbler depuis le schéma : « Connecter un câble ».');
    return found;
  }

  // ---- tabs ----
  function overview(main) {
    const n = state.node, d = state.device, f = d.features || [];
    const cabled = d.ports.filter(p => p.peer).length;
    const kpi = (label, value, hint) => `<div class="sd-card sd-kpi"><span>${esc(label)}</span><strong>${esc(value)}</strong><em>${esc(hint || '')}</em></div>`;
    const second = n.role === 'switch' ? kpi('VLAN', d.vlans.length, 'déclarés') : n.role === 'host' ? kpi('Adresse', d.ports[0]?.address?.split('/')[0] || '—',
        d.ports[0]?.address ? 'masque ' + mask(Number(d.ports[0].address.split('/')[1])) : '')
      : kpi('Routes', d.connected.length + d.static.length, `${d.static.length} statique${d.static.length > 1 ? 's' : ''}`);
    const third = n.role === 'firewall' ? kpi('Règles', (n.firewall?.rules || []).length, 'de sécurité')
      : n.role === 'host' ? kpi('Passerelle', n.gateway || '—', n.gateway ? 'vers les autres réseaux' : 'aucune : réseau local seulement') : kpi('Services', f.length, f.map(x => x.name).filter((v, i, a) => a.indexOf(v) === i).join(' · ') || 'aucun');
    const neighbours = d.ports.filter(p => p.peer);
    const list = checks();
    main.insertAdjacentHTML('beforeend', `<div class="sd-grid">
      ${kpi('Ports câblés', `${cabled} / ${d.ports.length}`, `${d.ports.filter(p => p.down).length} arrêté(s)`)}${second}${third}
      ${kpi('État', state.observed === 'running' ? 'En marche' : 'Arrêté', state.observed === 'running' ? 'micro-VM active' : 'projet')}
      <div class="sd-card sd-span2"><h3>À vérifier</h3><div class="checks"></div></div>
      <div class="sd-card sd-span2"><h3>Voisins</h3>${neighbours.length ? '<div class="sd-chips neighbours"></div>'
        : '<div class="sd-empty">Aucun câble : relier cet équipement depuis le schéma.</div>'}
        <div class="sd-note">Un clic ouvre la page de l’équipement voisin.</div></div></div>`);
    const box = main.querySelector('.checks');
    for (const item of list) {
      const row = document.createElement('div');
      row.className = 'sd-check ' + item.kind;
      row.innerHTML = `<span class="mark">${item.kind === 'ok' ? '✓' : item.kind === 'warn' ? '!' : 'i'}</span>
        <span class="text">${esc(item.text)}<small>${esc(item.hint || '')}</small></span>`;
      if (item.action) {
        const button = document.createElement('button');
        button.className = 'sd-btn'; button.textContent = item.label; button.onclick = item.action;
        row.append(button);
      }
      box.append(row);
    }
    const chips = main.querySelector('.neighbours');
    for (const p of neighbours) {
      const chip = document.createElement('button');
      chip.className = 'sd-chip';
      chip.innerHTML = `<b>${esc(peerName(p))}</b><small>${esc(p.peer.split(' · ')[1] || '')} ← ${esc(p.name)}</small>`;
      chip.onclick = () => go(peerName(p));
      chips?.append(chip);
    }
  }

  function portsTab(main) {
    const n = state.node, d = state.device, switching = n.role === 'switch';
    main.insertAdjacentHTML('beforeend', `<div class="sd-card"><input class="sd-search" placeholder="Filtrer : nom, adresse, VLAN, voisin…" value="${esc(filter)}">
      <div class="rows"></div></div>`);
    const input = main.querySelector('.sd-search');
    input.oninput = () => { filter = input.value; fill(); };
    const fill = () => {
      const rows = main.querySelector('.rows');
      rows.innerHTML = '';
      const shown = d.ports.filter(p => !filter || [p.name, p.port, p.address, p.detail, p.peer].join(' ').toLowerCase().includes(filter.toLowerCase()));
      for (const p of shown) {
        const row = document.createElement('div');
        row.className = 'sd-row';
        const link = p.down ? 'down' : p.peer ? 'up' : '';
        row.innerHTML = `<b>${esc(p.name)}</b><span class="sd-pill ${link}"><i></i>${p.down ? 'Arrêté' : p.peer ? 'Câblé' : 'Libre'}</span>
          <span>${switching ? (p.trunk ? '<span class="sd-tag violet">Trunk</span>' : `<span class="sd-tag"><i style="display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px;background:${vlanColour(p.vlan)};box-shadow:inset 0 0 0 1px #111111"></i>VLAN ${esc(p.vlan)}</span>`)
            : esc(p.address || ((n.dhcp_clients || []).includes(p.port) ? 'DHCP' : 'sans adresse'))}</span>
          <span class="muted">${esc(p.peer || '—')}</span>`;
        const button = document.createElement('button');
        button.className = 'sd-btn'; button.textContent = 'Modifier'; button.onclick = () => openDrawer(p.port);
        row.append(button);
        rows.append(row);
      }
      if (!shown.length) rows.innerHTML = '<div class="sd-empty">Aucun port ne correspond.</div>';
    };
    fill();
  }

  function vlansTab(main) {
    const d = state.device;
    main.insertAdjacentHTML('beforeend', `<div class="sd-grid"><div class="sd-card sd-span4"><h3>VLAN du switch</h3><div class="list"></div>
      <div style="display:flex;gap:10px;margin-top:14px"><input class="sd-search" style="margin:0;max-width:220px" placeholder="Numéro de VLAN (2-4094)" id="sdVlan">
      <button class="sd-btn primary" id="sdVlanAdd">+ Ajouter le VLAN</button></div>
      <div class="sd-note">Pour mettre un port dans un VLAN : cliquer sur le port, sur la face avant.</div></div></div>`);
    const list = main.querySelector('.list');
    for (const v of d.vlans) {
      const access = d.ports.filter(p => !p.trunk && p.vlan === v), trunks = d.ports.filter(p => p.trunk);
      const row = document.createElement('div');
      row.className = 'sd-vlan';
      row.innerHTML = `<span class="sw" style="background:${vlanColour(v)}"></span><div style="flex:1"><b>VLAN ${v}</b> <span class="sub">${v === 1 ? 'par défaut' : ''}</span>
        <div class="sd-chips" style="margin-top:8px">${access.map(p => `<span class="sd-chip" data-port="${esc(p.port)}">${esc(p.name)}<small>${esc(peerName(p) || 'libre')}</small></span>`).join('')
        || '<span class="sub">aucun port d’accès</span>'}${trunks.length ? `<span class="sd-tag violet">+ ${trunks.length} trunk${trunks.length > 1 ? 's' : ''}</span>` : ''}</div></div>`;
      row.querySelectorAll('[data-port]').forEach(chip => { chip.onclick = () => openDrawer(chip.dataset.port); });
      list.append(row);
    }
    main.querySelector('#sdVlanAdd').onclick = async () => {
      const vid = Number(main.querySelector('#sdVlan').value);
      if (!(vid >= 2 && vid <= 4094)) return toast('Un numéro de VLAN de 2 à 4094.');
      if (d.vlans.includes(vid)) return toast(`Le VLAN ${vid} existe déjà.`);
      await saveSwitching(state.node.switchports || {}, [...new Set([...(state.node.vlans || [1]), vid])].sort((a, b) => a - b), `VLAN ${vid} ajouté au projet.`);
    };
  }

  function securityTab(main) {
    const fw = state.node.firewall || {rules: [], nat: []};
    main.insertAdjacentHTML('beforeend', `<div class="sd-grid"><div class="sd-card sd-span4"><h3>Règles de sécurité <span class="sub">— lues de haut en bas,
      le reste ${fw.default === 'accept' ? 'est autorisé' : 'est bloqué'}</span></h3><div class="rules"></div>
      <div style="margin-top:14px"><button class="sd-btn primary" id="sdRules">Gérer les règles et le NAT</button></div></div>
      <div class="sd-card sd-span4"><h3>Traductions d’adresses (NAT)</h3><div class="nat"></div></div></div>`);
    const describe = r => `${r.in ? portName(r.in) : 'partout'} → ${r.out ? portName(r.out) : 'partout'}`;
    const service = r => !r.protocol || r.protocol === 'any' ? 'tout service' : r.dport ? `${r.protocol.toUpperCase()} ${r.dport}` : r.protocol.toUpperCase();
    const rules = main.querySelector('.rules');
    (fw.rules || []).forEach((r, i) => rules.insertAdjacentHTML('beforeend', `<div class="sd-rule"><span class="n">${i + 1}</span>
      <span class="sd-tag ${r.action === 'accept' ? 'green' : 'red'}">${r.action === 'accept' ? 'Autoriser' : 'Bloquer'}</span>
      <span class="what"><b>${esc(r.name)}</b><small>${esc(describe(r))} · ${esc(r.source || 'toute source')} → ${esc(r.destination || 'toute destination')} · ${esc(service(r))}</small></span></div>`));
    if (!(fw.rules || []).length) rules.innerHTML = '<div class="sd-empty">Aucune règle : tout le trafic qui traverse suit l’action par défaut.</div>';
    const nat = main.querySelector('.nat');
    (fw.nat || []).forEach(r => nat.insertAdjacentHTML('beforeend', `<div class="sd-rule"><span class="sd-tag violet">${esc(({masquerade: 'Masquerade', snat: 'Source', dnat: 'Destination'})[r.type] || r.type)}</span>
      <span class="what"><b>${esc(r.name)}</b><small>${esc(r.out ? 'sortie ' + portName(r.out) : r.in ? 'entrée ' + portName(r.in) : '')} ${esc(r.to ? '→ ' + r.to : '→ adresse du port')}</small></span></div>`));
    if (!(fw.nat || []).length) nat.innerHTML = '<div class="sd-empty">Aucune traduction.</div>';
    main.querySelector('#sdRules').onclick = () => showStandard('firewall');
  }

  function routingTab(main) {
    const d = state.device, n = state.node;
    main.insertAdjacentHTML('beforeend', `<div class="sd-grid"><div class="sd-card sd-span4"><h3>Où vont les paquets</h3><div class="routes"></div>
      <div class="sd-note">${n.role === 'host' ? 'La passerelle se change en cliquant sur le port.' : 'Routes statiques et protocoles : dans le terminal de l’équipement.'}</div>
      <div style="margin-top:12px"><button class="sd-btn" id="sdTerm">⌨ Ouvrir le terminal</button></div></div></div>`);
    const box = main.querySelector('.routes');
    const rows = [...d.connected.map(r => ['blue', 'Connecté', r.network, `directement par ${r.port}`]),
      ...d.static.map(r => ['violet', r.network === '0.0.0.0/0' ? 'Par défaut' : 'Statique', r.network, `via ${r.gateway} (${r.port})`])];
    for (const [colour, kind, network, how] of rows)
      box.insertAdjacentHTML('beforeend', `<div class="sd-rule"><span class="sd-tag ${colour}">${esc(kind)}</span><span class="what"><b>${esc(network)}</b><small>${esc(how)}</small></span></div>`);
    if (!rows.length) box.innerHTML = '<div class="sd-empty">Aucune route : donner une adresse à un port.</div>';
    main.querySelector('#sdTerm').onclick = openTerminal;
  }

  function servicesTab(main) {
    const f = state.device.features || [];
    main.insertAdjacentHTML('beforeend', `<div class="sd-grid">${f.map(x => `<div class="sd-card sd-span2"><span class="sd-tag blue">${esc(x.name)}</span>
      <p style="margin:10px 0 0">${esc(x.detail)}</p></div>`).join('') || '<div class="sd-card sd-span4"><div class="sd-empty">Aucun service ni protocole configuré.</div></div>'}
      <div class="sd-card sd-span4"><div class="sd-note" style="margin:0">Ces fonctions se configurent dans le terminal de l’équipement, comme sur l’appareil réel ;
      « show » y lit leur état quand le lab est en marche.</div><div style="margin-top:12px"><button class="sd-btn" id="sdTerm">⌨ Ouvrir le terminal</button></div></div></div>`);
    main.querySelector('#sdTerm').onclick = openTerminal;
  }

  // ---- the port drawer ----
  function openDrawer(port) { drawer = port; draw(); }
  function closeDrawer() { drawer = null; draw(); }

  function drawerHtml() {
    const n = state.node, d = state.device, p = d.ports.find(x => x.port === drawer);
    if (!p) return '';
    const switching = n.role === 'switch', host = n.role === 'host', dhcp = (n.dhcp_clients || []).includes(p.port);
    const [ip, prefix] = p.address ? p.address.split('/') : ['', '24'];
    const policy = (n.switchports || {})[p.port] || {mode: 'access', vlan: 1};
    const form = switching ? `<label>Mode du port</label><div class="sd-seg" id="sdMode"><button data-v="access" class="${policy.mode !== 'trunk' ? 'on' : ''}">Accès</button>
        <button data-v="trunk" class="${policy.mode === 'trunk' ? 'on' : ''}">Trunk 802.1Q</button></div>
        <div id="sdAccess"><label>VLAN</label><select id="sdVid">${(n.vlans || [1]).map(v => `<option value="${v}"${v === policy.vlan ? ' selected' : ''}>VLAN ${v}</option>`).join('')}</select></div>`
      : `${host ? `<label>Obtention de l’adresse</label><div class="sd-seg" id="sdMode"><button data-v="static" class="${dhcp ? '' : 'on'}">Statique</button>
        <button data-v="dhcp" class="${dhcp ? 'on' : ''}">DHCP</button></div>` : ''}
        <div id="sdStatic"><label>Adresse IPv4</label><input id="sdIp" value="${esc(ip)}" placeholder="192.168.1.1">
        <label>Masque</label><input id="sdMask" value="${esc(mask(Number(prefix)))}">
        <label>${host ? 'Passerelle par défaut' : 'Passerelle par défaut de l’équipement (optionnel)'}</label><input id="sdGw" value="${esc(n.gateway || '')}" placeholder="aucune"></div>`;
    return `<div class="sd-shade"></div><div class="sd-drawer" role="dialog"><div class="head"><h2>${esc(p.name)}</h2>
      <span class="sd-pill ${p.down ? 'down' : p.peer ? 'up' : ''}"><i></i>${p.down ? 'Arrêté' : p.peer ? 'Câblé' : 'Libre'}</span>
      <button class="sd-icon" id="sdClose" aria-label="Fermer">✕</button></div>
      <div class="body"><div class="sd-facts"><span>Port Linux</span><b>${esc(p.port)}</b><span>Câble vers</span><b>${p.peer
        ? `<a href="#" id="sdPeer">${esc(p.peer)}</a>` : '—'}</b>${switching ? `<span>Actuellement</span><b>${esc(p.trunk ? 'Trunk ' + p.detail.replace('Trunk ', '') : 'VLAN ' + p.vlan)}</b>` : ''}</div>
      ${form}<div class="sd-err"></div><div class="sd-note">Enregistré dans le projet, vérifié comme le reste du laboratoire${host
        ? ' ; lab en marche, appliqué aussi au poste' : ''}. Arrêter un port : « shutdown » dans le terminal.</div></div>
      <div class="foot"><button class="sd-btn" id="sdTerm">⌨ Terminal</button><span class="sd-grow"></span><button class="sd-btn" id="sdCancel">Annuler</button>
      <button class="sd-btn primary" id="sdSave">Enregistrer</button></div></div>`;
  }

  function bindDrawer() {
    const box = root.querySelector('.sd-drawer');
    if (!box) return;
    const n = state.node, p = state.device.ports.find(x => x.port === drawer), err = box.querySelector('.sd-err');
    root.querySelector('.sd-shade').onclick = closeDrawer;
    box.querySelector('#sdClose').onclick = box.querySelector('#sdCancel').onclick = closeDrawer;
    box.querySelector('#sdTerm').onclick = openTerminal;
    const peer = box.querySelector('#sdPeer');
    if (peer) peer.onclick = event => { event.preventDefault(); go(peerName(p)); };
    let mode = box.querySelector('#sdMode .on')?.dataset.v;
    const sync = () => {
      box.querySelector('#sdStatic') && (box.querySelector('#sdStatic').style.display = mode === 'dhcp' ? 'none' : '');
      box.querySelector('#sdAccess') && (box.querySelector('#sdAccess').style.display = mode === 'trunk' ? 'none' : '');
    };
    box.querySelectorAll('#sdMode button').forEach(button => {
      button.onclick = () => { mode = button.dataset.v; box.querySelectorAll('#sdMode button').forEach(b => b.classList.toggle('on', b === button)); sync(); };
    });
    sync();
    box.querySelector('#sdSave').onclick = async () => {
      err.textContent = '';
      try {
        if (n.role === 'switch') {
          const ports = JSON.parse(JSON.stringify(n.switchports || {}));
          ports[p.port] = mode === 'trunk' ? {mode: 'trunk', native_vlan: 1, allowed: 'all'} : {mode: 'access', vlan: Number(box.querySelector('#sdVid').value)};
          return await saveSwitching(ports, n.vlans || [1], `${p.name} : ${mode === 'trunk' ? 'trunk' : 'VLAN ' + ports[p.port].vlan}.`);
        }
        const ipText = box.querySelector('#sdIp').value.trim(), prefix = prefixOf(box.querySelector('#sdMask').value);
        if (mode !== 'dhcp' && ipText && prefix === null) { err.textContent = 'Masque invalide (ex. 255.255.255.0).'; return; }
        const address = ipText ? `${ipText}/${prefix}` : '', gateway = box.querySelector('#sdGw').value.trim();
        if (n.role === 'host') {
          state = await request('/api/host_ip', {node, revision: state.revision, port: p.port, mode: mode || 'static',
            address: mode === 'dhcp' ? '' : address, gateway: mode === 'dhcp' ? '' : gateway});
        } else {
          state = await request('/api/apply', {node, revision: state.revision, name: n.name, port: p.port, address, gateway, enabled: true});
        }
        drawer = null;
        render();
        toast(`${p.name} enregistré${typeof state.ip_live === 'string' ? ' · poste en marche : ' + state.ip_live : ''}.`);
      } catch (error) { err.textContent = error.message; }
    };
  }

  async function saveSwitching(switchports, vlans, done) {
    state = await request('/api/apply', {node, revision: state.revision, section: 'switching', config: {vlans, switchports}});
    drawer = null;
    render();
    toast(done);
  }

  // ---- moving around ----
  async function openTerminal() {
    try { await request('/api/open_cli', {node}); toast('Terminal ouvert dans Network LABS.'); } catch (error) { toast(error.message); }
  }
  function go(name) {
    if (!state.equipment.some(e => e.name === name)) return toast(name + ' n’est pas dans le projet.');
    node = name; tab = 'overview'; drawer = null; filter = '';
    load();
  }
  function showStandard(target) {
    standardView = true; page = target; root.remove(); document.body.classList.remove('sd'); render();
    let back = document.querySelector('.sd-back');
    if (!back) {
      back = document.createElement('button');
      back.className = 'sd-btn primary sd-back'; back.textContent = '← Revenir au design simple';
      back.onclick = () => { standardView = false; back.remove(); render(); };
      document.body.append(back);
    }
  }

  // The front panel: every port, a click opens its drawer (both looks).
  function faceHtml() {
    const n = state.node, d = state.device;
    const ports = [...d.ports, ...d.spare.map(name => ({name, spare: true}))].map(p => {
      const kind = p.spare ? 'spare' : p.down ? 'down' : p.peer ? 'up' : '';
      const bar = n.role === 'switch' && !p.spare ? `<i class="vbar" style="background:${p.trunk
        ? 'repeating-linear-gradient(90deg,#ffffff 0 6px,#7a7a7a 6px 12px)' : vlanColour(p.vlan)}"></i>` : '';
      const line = p.spare ? 'non déclaré' : n.role === 'switch' ? (p.trunk ? 'trunk' : 'VLAN ' + p.vlan)
        : p.address ? p.address.split('/')[0] : (n.dhcp_clients || []).includes(p.port) ? 'DHCP' : 'sans adresse';
      return `<div class="sd-port ${kind}${drawer === p.port ? ' sel' : ''}" ${p.spare ? '' : `data-port="${esc(p.port)}"`} title="${esc(p.spare ? 'Port du modèle non déclaré' : p.peer ? 'Câblé vers ' + p.peer : 'Libre')}">
        <span class="dot"></span><b>${esc(p.name)}</b><div class="jack"></div><small>${esc(line)}</small><small>${esc(p.spare ? '' : peerName(p) || 'libre')}</small>${bar}</div>`;
    }).join('');
    return `<div class="sd-chassis"><div class="head"><b>Face avant</b><span>Cliquer sur un port pour le régler</span></div>
        <div class="sd-ports">${ports}</div><div class="sd-legend"><span><i style="background:#ffffff"></i>câblé</span><span><i style="background:#4a4a4a"></i>libre</span>
        <span><i style="border:1.5px solid #ffffff;box-sizing:border-box"></i>arrêté</span>${n.role === 'switch' ? d.vlans.map(v => `<span><i style="background:${vlanColour(v)};border-radius:2px"></i>VLAN ${v}</span>`).join('') : ''}</div></div>`;
  }

  const designSwitch = current => [['vendor', 'Constructeur'], ['simple', 'Simple']]
    .map(([id, label]) => `<button data-d="${id}" class="${id === current ? 'on' : ''}">${label}</button>`).join('');

  function draw() {
    const n = state.node, d = state.device, running = state.observed === 'running';
    if (!tabs().some(([id]) => id === tab)) tab = 'overview';
    root.innerHTML = `<div class="sd-top"><img alt="" src="/devices/${esc(d.art)}@${d.art.startsWith('host') || d.art === 'server' ? 145 : 175}.png">
      <div><h1>${esc(n.name)}</h1><div class="model">${esc(d.brand)} · ${esc(d.model)}</div></div>
      <span class="sd-badge">${esc(roleName(n.role))}</span><span class="sd-badge"><i class="${running ? 'on' : ''}"></i>${running ? 'En marche' : 'Lab arrêté'}</span>
      <span class="sd-grow"></span><span class="sd-switch" title="Choisir le design des pages">${designSwitch('simple')}</span>
      <button class="sd-icon" id="sdRefresh" title="Actualiser">↻</button></div>
      <div class="sd-wrap">${faceHtml()}
        <nav class="sd-tabs">${tabs().map(([id, label, count]) => `<button data-tab="${id}" class="${id === tab ? 'on' : ''}">${esc(label)}${count !== undefined ? `<span>${count}</span>` : ''}</button>`).join('')}</nav>
        <main></main></div>${drawer ? drawerHtml() : ''}`;
    root.querySelectorAll('.sd-switch button').forEach(button => { button.onclick = () => window.nlSetDesign(button.dataset.d); });
    root.querySelector('#sdRefresh').onclick = () => load();
    root.querySelectorAll('[data-tab]').forEach(button => { button.onclick = () => { tab = button.dataset.tab; drawer = null; draw(); }; });
    root.querySelectorAll('.sd-port[data-port]').forEach(element => { element.onclick = () => openDrawer(element.dataset.port); });
    const main = root.querySelector('main');
    ({overview, ports: portsTab, vlans: vlansTab, security: securityTab, routing: routingTab, services: servicesTab})[tab](main);
    bindDrawer();
    document.title = `${n.name} · Network LABS`;
  }

  const previous = render;
  render = function () {
    previous();
    if (!state || !state.device) return;
    if (design() !== 'simple' || standardView) {
      root.remove(); document.body.classList.remove('sd');
      return;
    }
    document.body.classList.add('sd');
    if (!root.isConnected) document.body.append(root);
    draw();
  };
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && drawer) closeDrawer(); });
})();
