/* More device pages as copies of the real products (engine and toolkit: native_products.js). Firewalls: Sophos Firewall,
 * Check Point (Gaia Portal and SmartConsole), SonicWall SonicOS, WatchGuard Fireware Web UI. Routers: Huawei web,
 * Ubiquiti EdgeOS. Switches: Huawei, UniFi Network, TP-Link Easy Smart, NETGEAR, D-Link Web Smart, Aruba (AOS-CX and
 * Instant On) and the Catalyst 2960 Device Manager. Each keeps its product's frame, menus, wording, tables, edit windows
 * and way of saving; drawn by Network LABS, no vendor logo or picture. Changes go through the laboratory's checked
 * actions (Huawei and Cisco pages send VRP / IOS commands). */
'use strict';
(() => {
  const K = window.nlProductsKit;
  if (!K) return;
  const {SKINS, D, N, h, maskOf, prefixOf, ipOf, lenOf, networkOf, validIp, fw, portByName, portName, peerName, running, svc, toast, cli, section, setAddress,
    rename, attempt, openTerminal, stage, pending, candidateFw, editFw, addressOf, staticRoutes, commit, discard, dialog, val, field, input, select, table, tr, NA,
    naBox, ruleFrom, checkNet, dhcpServer, skinCss, natBuild, natPieces, natRead, putEntry, dropEntry, moveEntry, zoneNames} = K;
  const V = () => K.view;
  const go = (page, extra = {}) => { Object.assign(V(), {page, edit: null}, extra); render(); };
  const MATCH = (test, id) => K.MATCH.push([test, id]);
  MATCH(d => d.brand === 'Sophos', 'sophos');
  MATCH(d => d.brand === 'Check Point', 'gaia');
  MATCH(d => d.brand === 'SonicWall', 'sonicos');
  MATCH(d => d.brand === 'WatchGuard', 'fireware');
  MATCH(d => d.brand === 'Huawei', 'huawei');
  MATCH((d, role) => d.brand === 'Ubiquiti' && role === 'router', 'edgeos');
  MATCH((d, role) => d.brand === 'Ubiquiti' && role === 'switch', 'unifi');
  MATCH(d => d.brand === 'TP-Link', 'tplink');
  MATCH(d => d.brand === 'NETGEAR' || d.brand === 'Netgear', 'netgear');
  MATCH(d => d.brand === 'D-Link', 'dlink');
  MATCH((d, role) => /Aruba/.test(d.brand) && role === 'switch', 'aruba');
  MATCH(d => d.brand === 'Cisco' && /2960/.test(d.model), 'devmgr');

  // ---- shared pieces ----
  const ports = () => Object.keys(N().interfaces);
  const clone = value => JSON.parse(JSON.stringify(value));
  const lease = sec => `${Math.floor(sec / 86400)}d ${new Date((sec % 86400) * 1000).toISOString().substr(11, 8)}`;
  async function now(work, done) { return attempt(work, done); }
  // Rules saved at once (products that apply on OK / Save), with a position (top or bottom) for new ones.
  async function saveRule(index, rule, top = false) {
    const f = clone(fw());
    f.rules = f.rules || [];
    if (index === null) { if (top) f.rules.unshift(rule); else f.rules.push(rule); } else f.rules[index] = rule;
    await section('firewall', {firewall: f});
  }
  // NAT read from an « original / translated » window: a translated destination makes a port forward (dnat), else the
  // translated source (MASQ or the interface's address) makes source NAT.
  const natColumns = root => natBuild({name: val(root, '#nxName'), in: val(root, '#nxIn'), out: val(root, '#nxOut'), source: val(root, '#nxSrc'),
    destination: val(root, '#nxDst'), service: val(root, '#nxSvc'), type: val(root, '#nxTo') ? 'dnat' : val(root, '#nxXsrc'), to: val(root, '#nxTo'), to_port: val(root, '#nxToPort')});
  const xsrcPiece = (entry, label, options) => field(label, select('nxXsrc', options, entry.type === 'dnat' ? '' : entry.type || ''));
  // DHCP server, as a product form saves it.
  function dhcpFrom(root, ids) {
    const dns = val(root, ids.dns) ? val(root, ids.dns).split(/[ ,]+/).filter(Boolean) : [];
    return {interface: val(root, ids.iface), start: val(root, ids.start), end: val(root, ids.end), router: val(root, ids.router), dns,
      lease_seconds: Number(val(root, ids.lease)) || 86400, reservations: []};
  }

  // Switch VLAN membership: U (untagged), T (tagged) or nothing, per port and VLAN, back to the laboratory's switchports.
  const vlans = () => (N().vlans && N().vlans.length ? N().vlans : [1]);
  const policy = port => (N().switchports || {})[port] || {mode: 'access', vlan: 1};
  const pvid = port => { const p = policy(port); return p.mode === 'trunk' ? p.native_vlan : p.vlan; };
  function member(port, vid) {
    const p = policy(port);
    if (p.mode !== 'trunk') return p.vlan === vid ? 'U' : '';
    if (vid === p.native_vlan) return 'U';
    return (p.allowed === 'all' ? vlans() : p.allowed).includes(vid) ? 'T' : '';
  }
  function portFrom(cells) {
    const untagged = Object.keys(cells).filter(v => cells[v] === 'U').map(Number), tagged = Object.keys(cells).filter(v => cells[v] === 'T').map(Number);
    if (untagged.length > 1) throw new Error('Un port n’est membre non étiqueté (untagged) que d’un seul VLAN.');
    if (!tagged.length) return {mode: 'access', vlan: untagged[0] || 1};
    return {mode: 'trunk', native_vlan: untagged[0] || 1, allowed: tagged.sort((a, b) => a - b)};
  }
  const cellsOf = port => Object.fromEntries(vlans().map(v => [v, member(port, v)]));
  async function saveSwitching(list, switchports) {
    await section('switching', {vlans: [...new Set(list)].sort((a, b) => a - b), switchports});
  }
  // One VLAN's membership changed on every port (TP-Link, NETGEAR, D-Link pages).
  async function setVlanMembers(vid, members, extra = []) {
    const list = [...new Set([...vlans(), vid, ...extra])];
    const switchports = {};
    for (const port of ports()) {
      const cells = cellsOf(port);
      if (members[port] === 'U') Object.keys(cells).forEach(v => { if (cells[v] === 'U') cells[v] = ''; });  // its PVID moves to this VLAN
      cells[vid] = members[port] || '';
      switchports[port] = portFrom(cells);
    }
    await saveSwitching(list, switchports);
  }
  async function dropVlan(vid) {
    if (vid === 1) throw new Error('Le VLAN 1 (défaut) ne se supprime pas.');
    const switchports = {};
    for (const port of ports()) {
      const cells = cellsOf(port);
      delete cells[vid];
      switchports[port] = portFrom(cells);
    }
    await saveSwitching(vlans().filter(v => v !== vid), switchports);
  }
  async function setPvid(port, vid) {
    const cells = cellsOf(port);
    Object.keys(cells).forEach(v => { if (cells[v] === 'U') cells[v] = ''; });
    cells[vid] = 'U';
    const switchports = clone(N().switchports || {});
    switchports[port] = portFrom(cells);
    await saveSwitching(vlans(), switchports);
  }
  // The member radios (TP-Link, D-Link) follow the VLAN ID typed in the form: a new VLAN starts with no member.
  function followVid(main, field, prefix) {
    main.querySelector(field).addEventListener('input', () => {
      const id = Number(val(main, field));
      if (!(id >= 1 && id <= 4094)) return;
      for (const port of ports()) {
        const box = main.querySelector(`input[name="${prefix}${CSS.escape(port)}"][value="${member(port, id)}"]`);
        if (box) box.checked = true;
      }
    });
  }
  const listText = text => (String(text).trim().toLowerCase() === 'all' ? 'all' : String(text).split(/[ ,]+/).filter(Boolean).map(Number));
  async function setPortMode(port, mode, access, native, allowed) {
    const switchports = clone(N().switchports || {}), extra = [];
    if (mode === 'trunk') {
      const list = listText(allowed || 'all');
      if (list !== 'all' && list.some(v => !(v >= 1 && v <= 4094))) throw new Error('VLAN autorisés : all ou 10,20…');
      switchports[port] = {mode: 'trunk', native_vlan: Number(native) || 1, allowed: list};
      if (list !== 'all') extra.push(...list);
      extra.push(Number(native) || 1);
    } else {
      switchports[port] = {mode: 'access', vlan: Number(access) || 1};
      extra.push(Number(access) || 1);
    }
    await saveSwitching([...vlans(), ...extra], switchports);
  }
  const portLink = p => (p.down ? 'down' : p.peer ? 'up' : 'nolink');
  // A switch faceplate (D-Link, Device Manager, Aruba, UniFi): numbered ports lit by their link.
  const faceplate = (cls, label = p => p.name.split('/').pop()) => `<div class="${cls}">${[...D().ports, ...D().spare.map(name => ({name, spare: true}))]
    .map(p => `<i class="${p.spare ? 'spare' : portLink(p)}" title="${h(p.name + (p.peer ? ' → ' + p.peer : ''))}">${h(label(p))}</i>`).join('')}</div>`;

  /* =============================== Sophos Firewall =============================== */
  skinCss(`
  .px-app.sophos{display:grid;grid-template-columns:230px 1fr;min-height:100vh;background:#eef1f5;color:#1f2d3d;font:13px 'Open Sans',Arial,sans-serif}
  .so-nav{background:#13283f;color:#c6d1dd;padding:10px 0}.so-nav .brand{color:#fff;font-size:17px;padding:8px 18px 14px}
  .so-nav .grp{font-size:10.5px;letter-spacing:.8px;color:#7f93a8;padding:14px 18px 6px}.so-nav a{display:block;padding:7px 18px;color:#d6dfe8;cursor:pointer}
  .so-nav a:hover{background:#1c3653}.so-nav a.on{background:#0f6bce;color:#fff}.so-nav a.na{color:#6f8399}
  .so-top{display:flex;align-items:center;gap:16px;padding:12px 22px;background:#fff;border-bottom:1px solid #dfe4ea}
  .so-top h1{font-size:20px;font-weight:600;margin:0}.so-top .grow{flex:1}.so-top span{color:#0f6bce;cursor:default}
  .so-main{padding:16px 22px}.so-tabs{display:flex;gap:18px;border-bottom:1px solid #dfe4ea;margin-bottom:12px}.so-tabs a{padding:8px 2px;cursor:pointer;color:#55687d}
  .so-tabs a.on{color:#0f6bce;border-bottom:3px solid #0f6bce;font-weight:600}.so-tabs a.na{color:#9aa8b6}
  .so-bar{display:flex;gap:8px;align-items:center;margin-bottom:10px}.so-bar .grow{flex:1}
  .so-btn{border:1px solid #0f6bce;background:#fff;color:#0f6bce;padding:6px 14px;border-radius:3px;cursor:pointer}.so-btn.pri{background:#0f6bce;color:#fff}
  .so-btn.del{border-color:#c62828;color:#c62828}
  .so-t{width:100%;border-collapse:collapse;background:#fff}.so-t th{text-align:left;padding:9px 10px;background:#f6f8fa;border-bottom:1px solid #dfe4ea;font-weight:600;white-space:nowrap}
  .so-t td{padding:9px 10px;border-bottom:1px solid #edf0f3;white-space:nowrap}.so-t tbody tr:hover td{background:#f2f7fd}.so-t a{color:#0f6bce;cursor:pointer}
  .so-acc{color:#2e7d32}.so-drop{color:#c62828}.so-dflt td{color:#8796a5;font-style:italic}
  .so-card{background:#fff;border:1px solid #dfe4ea;margin-bottom:14px}.so-card h3{margin:0;padding:10px 14px;border-bottom:1px solid #edf0f3;font-size:14px}
  .so-card .b{padding:12px 14px}.so-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
  .so-dial{display:flex;gap:18px}.so-dial div{text-align:center}.so-dial b{display:grid;place-items:center;width:58px;height:58px;border-radius:50%;border:5px solid #0f6bce;margin:0 auto 6px}
  .so-form h4{margin:16px 0 6px;color:#0f6bce;font-size:14px}.so-form{max-width:780px;background:#fff;border:1px solid #dfe4ea;padding:14px 18px}
  `);
  const SO_MENU = [['MONITOR & ANALYZE', [['Control center', 'control'], ['Current activities', 'na'], ['Reports', 'na'], ['Zero-day protection', 'engine'], ['Diagnostics', 'terminal']]],
    ['PROTECT', [['Rules and policies', 'rules'], ['Intrusion prevention', 'engine'], ['Web', 'engine'], ['Applications', 'engine'], ['Wireless', 'wireless'], ['Email', 'engine'],
      ['Web server', 'na'], ['Advanced protection', 'engine']]],
    ['CONFIGURE', [['Remote access VPN', 'vpn'], ['Site-to-site VPN', 'vpn'], ['Network', 'network'], ['Routing', 'routing'], ['Authentication', 'na'], ['System services', 'na']]],
    ['SYSTEM', [['Sophos Central', 'na'], ['Profiles', 'na'], ['Hosts and services', 'services'], ['Administration', 'admin'], ['Backup & firmware', 'na'], ['Certificates', 'na']]]];
  const soZones = () => zoneNames(['WAN', 'LAN', 'DMZ']);
  const soZone = port => soZones()[port] || 'LAN';
  SKINS.sophos = {
    start: {page: 'control', title: 'Control center'},
    draw(root) {
      root.innerHTML = `<nav class="so-nav"><div class="brand">Sophos Firewall</div>${SO_MENU.map(([g, items]) => `<div class="grp">${g}</div>${items.map(([label, page]) =>
        `<a data-go="${page}" data-t="${h(label)}" class="${['na', 'engine', 'vpn', 'wireless'].includes(page) ? 'na' : ''}${label === V().title ? ' on' : ''}">${h(label)}</a>`).join('')}`).join('')}</nav>
        <div><div class="so-top"><h1>${h(V().title)}</h1><span class="grow"></span><span>How-to guides</span><span>Log viewer</span><span>Help</span><span>admin ▾</span>
        <span style="color:#8796a5">${h(N().name)} · Network LABS</span></div><main class="so-main"></main></div>`;
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => go(a.dataset.go, {title: a.dataset.t, tab: null}); });
      const main = root.querySelector('main');
      const pages = {control: soControl, rules: soRules, network: soNetwork, routing: soRouting, services: soServices, admin: soAdmin,
        terminal: m => { openTerminal(); soControl(m); }, engine: m => { m.innerHTML = naBox(V().title, NA.engine); }, vpn: m => { m.innerHTML = naBox(V().title, NA.vpn); },
        wireless: m => { m.innerHTML = naBox(V().title, NA.wireless); }};
      (pages[V().page] || (m => { m.innerHTML = naBox(V().title, NA.later); }))(main);
    },
  };
  function soControl(main) {
    const d = D(), f = fw();
    main.innerHTML = `<div class="so-grid"><div class="so-card"><h3>System</h3><div class="b so-dial">${[['CPU', running() ? '2%' : '—'], ['Memory', running() ? '40%' : '—'],
      ['Bandwidth', '0 Kbps'], ['Sessions', String(state.live && state.live.sessions ? state.live.sessions.length : 0)]].map(([k, v]) => `<div><b>${v}</b>${k}</div>`).join('')}</div></div>
      <div class="so-card"><h3>Active firewall rules</h3><div class="b"><b style="font-size:24px">${f.rules.length}</b> rules · ${f.rules.filter(r => r.action === 'accept').length} accept ·
      ${(f.nat || []).length} NAT</div></div><div class="so-card"><h3>Messages</h3><div class="b">${running() ? 'No messages.' : 'Lab arrêté.'}</div></div>
      <div class="so-card" style="grid-column:span 2"><h3>Interfaces</h3><div class="b">${table('so-t', ['Name', 'Zone', 'IP address', 'Status'], d.ports.map(p => tr([h(p.name),
        h(soZone(p.port)), h(p.address || '—'), p.peer && !p.down ? '<span class="so-acc">● Connected</span>' : '<span class="so-drop">● Disconnected</span>'])))}</div></div>
      <div class="so-card"><h3>Device</h3><div class="b">${h(N().name)}<br>${h(d.brand)} ${h(d.model)}<br>SFOS · sous-ensemble Network LABS</div></div></div>`;
  }
  function soRules(main) {
    const tab = V().tab || 'Firewall rules';
    if (V().edit !== null && V().edit !== undefined) return tab === 'NAT rules' ? soNatForm(main, V().edit) : soRuleForm(main, V().edit);
    const f = fw();
    const tabs = `<div class="so-tabs">${['Firewall rules', 'NAT rules', 'SSL/TLS inspection rules'].map(t => `<a data-t="${t}" class="${t === tab ? 'on' : t.startsWith('SSL') ? 'na' : ''}">${t}</a>`).join('')}</div>`;
    if (tab === 'NAT rules') {
      main.innerHTML = `${tabs}<div class="so-bar"><span>IPv4</span><span class="grow"></span><button class="so-btn pri add">Add NAT rule</button></div>${table('so-t', ['#', 'Name', 'Original source',
        'Translated source', 'Original destination', 'Translated destination', 'Original service', 'Translated service', 'Inbound interface', 'Outbound interface', ''],
        (f.nat || []).map((r, i) => tr([String(i + 1), `<a data-e="${i}">${h(r.name)}</a>`, h(r.source || 'Any'), h(r.type === 'masquerade' ? 'MASQ' : r.type === 'snat' ? r.to : 'Original'),
          h(r.destination || 'Any'), h(r.type === 'dnat' ? r.to : 'Original'), h(r.protocol && r.protocol !== 'any' ? svc(r) : 'Any'), h(r.to_port || 'Original'),
          h(r.in ? portName(r.in) : 'Any'), h(r.out ? portName(r.out) : 'Any'), `<a data-x="${i}">✕</a>`])), 'No NAT rules')}`;
    } else {
      main.innerHTML = `${tabs}<div class="so-bar"><span>IPv4</span><span>|</span><span style="color:#9aa8b6">IPv6</span><span class="grow"></span><button class="so-btn pri add">Add firewall rule ▾</button></div>
        ${table('so-t', ['#', 'Name', 'Source', 'Destination', 'What', 'ID', 'Action', ''], [...f.rules.map((r, i) => tr([String(i + 1), `<a data-e="${i}">${h(r.name)}</a>`,
          h(`${r.in ? soZone(r.in) : 'Any zone'} · ${r.source || 'Any'}`), h(`${r.out ? soZone(r.out) : 'Any zone'} · ${r.destination || 'Any'}`), h(svc(r) === 'any' ? 'Any service' : svc(r)),
          String(i + 1), r.action === 'accept' ? '<span class="so-acc">✔ Accept</span>' : '<span class="so-drop">✖ Drop</span>', `<a data-x="${i}">✕</a>`])),
          `<tr class="so-dflt"><td>0</td><td>Default rule</td><td>Any</td><td>Any</td><td>Any service</td><td>0</td><td>${f.default === 'accept' ? 'Accept' : 'Drop'}</td><td></td></tr>`])}`;
    }
    main.querySelectorAll('[data-t]').forEach(a => { a.onclick = () => { if (!a.classList.contains('na')) go('rules', {tab: a.dataset.t}); }; });
    main.querySelector('.add').onclick = () => go('rules', {edit: 'new'});
    main.querySelectorAll('[data-e]').forEach(a => { a.onclick = () => go('rules', {edit: Number(a.dataset.e)}); });
    main.querySelectorAll('[data-x]').forEach(a => { a.onclick = () => now(() => (async () => { const f2 = clone(fw()); f2[tab === 'NAT rules' ? 'nat' : 'rules'].splice(Number(a.dataset.x), 1);
      await section('firewall', {firewall: f2}); })(), 'Rule deleted.'); });
  }
  function soRuleForm(main, index) {
    const r = index === 'new' ? {action: 'accept'} : fw().rules[index], zones = ports().map(p => [p, soZone(p)]);
    main.innerHTML = `<div class="so-form"><h3 style="margin:0 0 8px">${index === 'new' ? 'Add firewall rule' : 'Edit firewall rule'}</h3>${field('Rule status', '<span>● On</span>')}
      ${field('Rule name', input('soName', r.name || ''))}${field('Action', select('soAct', [['accept', 'Accept'], ['drop', 'Drop']], r.action))}
      ${field('Rule position', select('soPos', [['bottom', 'Bottom'], ['top', 'Top']], 'bottom'))}${field('Log firewall traffic', '<span>☐</span>')}
      <h4>Source</h4>${field('Source zones', select('soFrom', [['', 'Any'], ...zones], r.in || ''))}${field('Source networks and devices', input('soSrc', r.source || 'Any'))}
      <h4>Destination & services</h4>${field('Destination zones', select('soTo', [['', 'Any'], ...zones], r.out || ''))}${field('Destination networks', input('soDst', r.destination || 'Any'))}
      ${field('Services', input('soSvc', svc(r) === 'any' ? 'Any' : svc(r)), 'Any, HTTP, HTTPS, SSH, DNS, tcp/8080')}
      <div class="px-err"></div><div class="so-bar"><button class="so-btn pri save">Save</button><button class="so-btn cancel">Cancel</button></div></div>`;
    main.querySelector('.cancel').onclick = () => go('rules');
    main.querySelector('.save').onclick = async () => {
      try {
        const rule = ruleFrom(index === 'new' ? {} : r, {name: val(main, '#soName') || `rule-${fw().rules.length + 1}`, action: val(main, '#soAct'), in: val(main, '#soFrom'),
          out: val(main, '#soTo'), source: checkNet(val(main, '#soSrc').toLowerCase() === 'any' ? '' : val(main, '#soSrc'), 'Source'),
          destination: checkNet(val(main, '#soDst').toLowerCase() === 'any' ? '' : val(main, '#soDst'), 'Destination'), service: val(main, '#soSvc')});
        await saveRule(index === 'new' ? null : index, rule, val(main, '#soPos') === 'top');
        go('rules'); toast('Firewall rule saved.');
      } catch (error) { main.querySelector('.px-err').textContent = error.message; }
    };
  }
  function soNatForm(main, index) {
    const r = index === 'new' ? {type: 'masquerade'} : fw().nat[index];
    const x = natPieces(r, {name: 'Rule name', in: 'Inbound interface', out: 'Outbound interface', source: 'Original source', destination: 'Original destination',
      service: 'Original service', to: 'Translated destination (DNAT)', to_port: 'Translated service (port)', types: [['masquerade', 'x']], any: 'Any'});
    main.innerHTML = `<div class="so-form"><h3 style="margin:0 0 8px">${index === 'new' ? 'Add NAT rule' : 'Edit NAT rule'}</h3>${x.name}<h4>Translation settings</h4>${x.source}
      ${xsrcPiece(r, 'Translated source (SNAT)', [['', 'Original'], ['masquerade', 'MASQ'], ['snat', 'Interface address (static)']])}${x.destination}${x.to}${x.service}${x.to_port}
      <h4>Interface matching criteria</h4>${x.in}${x.out}<div class="px-err"></div><div class="so-bar"><button class="so-btn pri save">Save</button><button class="so-btn cancel">Cancel</button></div></div>`;
    main.querySelector('.cancel').onclick = () => go('rules', {tab: 'NAT rules'});
    main.querySelector('.save').onclick = async () => {
      try { await putEntry('nat', index === 'new' ? null : index, natColumns(main), false); go('rules', {tab: 'NAT rules'}); toast('NAT rule saved.'); }
      catch (error) { main.querySelector('.px-err').textContent = error.message; }
    };
  }
  function soNetwork(main) {
    const tab = V().tab || 'Interfaces', d = D();
    const tabs = `<div class="so-tabs">${['Interfaces', 'Zones', 'WAN link manager', 'DNS', 'DHCP', 'Neighbors (ARP-NDP)', 'Dynamic DNS'].map(t => `<a data-t="${t}" class="${t === tab ? 'on'
      : ['Interfaces', 'Zones', 'DHCP'].includes(t) ? '' : 'na'}">${t}</a>`).join('')}</div>`;
    if (V().edit !== null && V().edit !== undefined && tab === 'Interfaces') {
      const p = d.ports[V().edit], a = p.address;
      main.innerHTML = `${tabs}<div class="so-form"><h3 style="margin:0 0 8px">Edit interface</h3>${field('Name', input('n', p.name, 'disabled'))}${field('Hardware', input('hw', p.name, 'disabled'))}
        ${field('Network zone', input('z', soZone(p.port), 'disabled'))}${field('IP assignment', select('ia', ['Static'], 'Static'))}
        ${field('IPv4/netmask', input('soIp', ipOf(a)) + ' / ' + select('soLen', Array.from({length: 31}, (_, k) => [32 - k, `/${32 - k} (${maskOf(32 - k)})`]), lenOf(a)))}
        <div class="px-err"></div><div class="so-bar"><button class="so-btn pri save">Save</button><button class="so-btn cancel">Cancel</button></div></div>`;
      main.querySelector('.cancel').onclick = () => go('network', {tab});
      main.querySelector('.save').onclick = async () => {
        const ip = val(main, '#soIp');
        if (ip && !validIp(ip)) { main.querySelector('.px-err').textContent = 'IPv4 invalide.'; return; }
        if (await attempt(() => setAddress(p.port, ip ? `${ip}/${val(main, '#soLen')}` : ''), 'Interface saved.')) go('network', {tab});
      };
      return;
    }
    const s = dhcpServer();
    const body = tab === 'Zones' ? table('so-t', ['Name', 'Type', 'Members', 'Description'], [...new Set(Object.values(soZones()))].map(z => tr([h(z), 'System',
      h(ports().filter(p => soZone(p) === z).map(portName).join(', ')), ''])))
      : tab === 'DHCP' ? `<div class="so-bar"><span>Servers</span><span class="grow"></span><button class="so-btn pri dhcp">${s ? 'Edit' : 'Add'}</button>${s ? '<button class="so-btn del nodhcp">Delete</button>' : ''}</div>
        ${table('so-t', ['Name', 'Interface', 'Dynamic IP lease', 'Default gateway', 'DNS server', 'Lease time'], s ? [tr(['LAN_DHCP', h(portName(s.interface)), h(`${s.start} - ${s.end}`),
          h(s.router || ''), h((s.dns || []).join(', ')), h(lease(s.lease_seconds || 86400))])] : [])}`
      : table('so-t', ['Name', 'IP address', 'Status', 'Zone', 'MTU'], d.ports.map((p, i) => tr([`<a data-e="${i}">${h(p.name)} - ${h(soZone(p.port))}</a>`, h(p.address || '—'),
        p.peer && !p.down ? '<span class="so-acc">● Connected</span>' : '<span class="so-drop">● Disconnected</span>', h(soZone(p.port)), '1500'])));
    main.innerHTML = tabs + body;
    main.querySelectorAll('[data-t]').forEach(a => { a.onclick = () => { if (!a.classList.contains('na')) go('network', {tab: a.dataset.t}); }; });
    main.querySelectorAll('[data-e]').forEach(a => { a.onclick = () => go('network', {tab, edit: Number(a.dataset.e)}); });
    const add = main.querySelector('.dhcp');
    if (add) add.onclick = () => soDhcp(s);
    const del = main.querySelector('.nodhcp');
    if (del) del.onclick = () => now(() => section('dhcpserver', {dhcp_server: null}), 'DHCP server deleted.');
  }
  function soDhcp(s) {
    const options = D().ports.filter(p => p.address).map(p => [p.port, p.name]);
    dialog('sophos', 'DHCP server', `${field('Interface', select('soIf', options, s ? s.interface : options[0]?.[0]))}${field('Dynamic IP lease (start)', input('soS', s ? s.start : ''))}
      ${field('Dynamic IP lease (end)', input('soE', s ? s.end : ''))}${field('Default gateway', input('soR', s ? s.router : ''))}${field('DNS server', input('soD', s ? (s.dns || []).join(', ') : ''))}
      ${field('Lease time (seconds)', input('soL', s ? s.lease_seconds : 86400))}`,
    [['Save', 'pri', async b => { await section('dhcpserver', {dhcp_server: dhcpFrom(b, {iface: '#soIf', start: '#soS', end: '#soE', router: '#soR', dns: '#soD', lease: '#soL'})}); render(); }], ['Cancel']]);
  }
  function soRouting(main) {
    main.innerHTML = `<div class="so-tabs"><a class="on">Static routes</a><a class="na">SD-WAN routes</a><a class="na">Gateways</a><a class="na">BGP</a><a class="na">OSPF</a></div>
      <div class="so-card"><h3>IPv4 unicast route</h3>${table('so-t', ['Destination IP', 'Netmask', 'Gateway', 'Interface', 'Distance'], [...D().connected.map(r => tr([h(ipOf(r.network)),
        h(maskOf(lenOf(r.network))), '—', h(r.port), '0'])), ...D().static.map(r => tr([h(ipOf(r.network)), h(maskOf(lenOf(r.network))), h(r.gateway), h(r.port), '1']))])}
      <div class="b" style="color:#8796a5">Network LABS : les routes statiques de ce pare-feu se règlent dans ◉ Network LABS › Vue Network LABS › Routage.</div></div>`;
  }
  function soServices(main) {
    main.innerHTML = `<div class="so-tabs"><a class="na">IP host</a><a class="na">MAC host</a><a class="na">FQDN host</a><a class="on">Services</a></div>${table('so-t', ['Name', 'Type', 'Details'],
      [['HTTP', 'TCP/UDP', 'TCP 80'], ['HTTPS', 'TCP/UDP', 'TCP 443'], ['SSH', 'TCP/UDP', 'TCP 22'], ['DNS', 'TCP/UDP', 'UDP 53'], ['Ping', 'ICMP', 'Echo']].map(r => tr(r.map(h))))}`;
  }
  function soAdmin(main) {
    main.innerHTML = `<div class="so-tabs"><a class="on">Admin and user settings</a><a class="na">Device access</a><a class="na">Notification settings</a></div><div class="so-form">
      <h4 style="margin-top:0">Hostname settings</h4>${field('Hostname', input('soHost', N().name))}<div class="px-err"></div><button class="so-btn pri apply">Apply</button></div>`;
    main.querySelector('.apply').onclick = () => attempt(() => rename(val(main, '#soHost')), 'Hostname changed.');
  }

  /* =============================== Check Point: Gaia Portal and SmartConsole =============================== */
  skinCss(`
  .px-app.gaia{min-height:100vh;background:#f2f3f5;color:#222;font:13px Arial,Helvetica,sans-serif;display:grid;grid-template-rows:44px 1fr}
  .cp-top{display:flex;align-items:center;gap:16px;padding:0 16px;background:#253746;color:#fff}.cp-top b{font-size:16px}.cp-top .grow{flex:1}
  .cp-top button{border:1px solid #5b7184;background:#304657;color:#fff;padding:5px 12px;cursor:pointer;border-radius:2px}.cp-top button.on{background:#e65c00;border-color:#e65c00}
  .cp-body{display:grid;grid-template-columns:240px 1fr;min-height:0}.cp-tree{background:#fff;border-right:1px solid #d6d9dd;padding:8px 0;overflow:auto}
  .cp-tree a{display:block;padding:5px 14px;cursor:pointer;color:#222;white-space:nowrap}.cp-tree a.g{font-weight:bold;color:#253746;margin-top:6px;cursor:default}
  .cp-tree a.s{padding-left:30px}.cp-tree a.on{background:#dbe8f4;font-weight:bold}.cp-tree a.na{color:#9aa1a8}.cp-tree a:hover{background:#eef4fa}
  .cp-main{padding:14px 18px;overflow:auto}.cp-main h2{margin:0 0 10px;font-size:18px;font-weight:normal;color:#253746}
  .cp-box{background:#fff;border:1px solid #d6d9dd;margin-bottom:12px}.cp-box h3{margin:0;padding:7px 10px;font-size:13px;background:linear-gradient(#f7f8f9,#e6e9ec);border-bottom:1px solid #d6d9dd}
  .cp-box .b{padding:10px}.cp-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.cp-kv{display:grid;grid-template-columns:150px 1fr;gap:5px}.cp-kv span{color:#666}
  .cp-bar{display:flex;gap:6px;padding:6px 10px;border-bottom:1px solid #e6e9ec}.cp-bar button{border:1px solid #b3bac1;background:linear-gradient(#fff,#e9ecef);padding:4px 12px;cursor:pointer}
  .cp-t{width:100%;border-collapse:collapse}.cp-t th{text-align:left;background:#eef0f2;border:1px solid #d6d9dd;padding:5px 8px;font-weight:bold;white-space:nowrap}
  .cp-t td{border:1px solid #e6e9ec;padding:5px 8px;white-space:nowrap}.cp-t tr.sel td{background:#cfe2f3}.cp-t tr.cl td{background:#f6f6f6;color:#666}
  .sc{display:grid;grid-template-columns:86px 1fr;min-height:0}.sc-rail{background:#1b2a37;display:flex;flex-direction:column;gap:2px;padding-top:6px}
  .sc-rail a{color:#b7c4d0;text-align:center;font-size:10px;padding:10px 4px;cursor:pointer}.sc-rail a i{display:block;font-style:normal;font-size:20px;margin-bottom:4px}
  .sc-rail a.on{background:#2f4659;color:#fff}.sc-rail a.na{color:#64788a}
  .sc-main{display:flex;flex-direction:column;min-height:0}.sc-tool{display:flex;gap:6px;align-items:center;padding:6px 10px;background:#fff;border-bottom:1px solid #d6d9dd}
  .sc-tool button{border:1px solid #b3bac1;background:#fff;padding:4px 12px;cursor:pointer}.sc-tool button.pub{background:#e65c00;color:#fff;border-color:#e65c00}
  .sc-tool .grow{flex:1}.sc-split{display:grid;grid-template-columns:200px 1fr;flex:1;min-height:0}.sc-left{background:#fff;border-right:1px solid #d6d9dd;padding:8px}
  .sc-left a{display:block;padding:5px 8px;cursor:pointer}.sc-left a.on{background:#dbe8f4;font-weight:bold}.sc-left b{display:block;color:#253746;margin:6px 0 4px}
  .sc-acc{color:#2e7d32;font-weight:bold}.sc-drop{color:#c62828;font-weight:bold}
  .px-shade.gaia .px-dtitle{background:#253746;color:#fff}.px-shade.gaia .px-dfoot button{border:1px solid #b3bac1;background:#fff;padding:4px 16px;cursor:pointer}
  .px-shade.gaia .px-dfoot button.pri{background:#e65c00;color:#fff;border-color:#e65c00}
  `);
  const CP_TREE = [['Overview', 'overview'], ['Network Management', null], ['Network Interfaces', 'interfaces', 1], ['ARP', 'na', 1], ['DHCP Server', 'dhcp', 1], ['Hosts and DNS', 'hosts', 1],
    ['IPv4 Static Routes', 'routes', 1], ['NetFlow Export', 'na', 1], ['System Management', null], ['Time', 'na', 1], ['SNMP', 'na', 1], ['Job Scheduler', 'na', 1], ['Messages', 'na', 1],
    ['Advanced Routing', null], ['OSPF', 'features', 1], ['BGP', 'features', 1], ['Routing Monitor', 'routes', 1], ['User Management', null], ['Users', 'na', 1], ['Roles', 'na', 1],
    ['High Availability', null], ['VRRP', 'na', 1], ['ClusterXL', 'na', 1], ['Maintenance', null], ['Licenses', 'na', 1], ['Snapshot Management', 'na', 1], ['Upgrades (CPUSE)', 'na']];
  SKINS.gaia = {
    start: {mode: 'portal', page: 'overview', title: 'Overview', sc: 'policy'},
    draw(root) {
      const v = V(), count = pending();
      root.innerHTML = `<div class="cp-top"><b>${v.mode === 'portal' ? 'Gaia Portal' : 'SmartConsole'}</b><span>${h(N().name)} · ${h(D().model)} · sous-ensemble Network LABS</span><span class="grow"></span>
        <button data-m="portal" class="${v.mode === 'portal' ? 'on' : ''}">Gaia Portal</button><button data-m="smart" class="${v.mode === 'smart' ? 'on' : ''}">SmartConsole${count ? ` (${count})` : ''}</button>
        <span>admin</span></div><div class="cp-body"></div>`;
      root.querySelectorAll('[data-m]').forEach(b => { b.onclick = () => { v.mode = b.dataset.m; render(); }; });
      const body = root.querySelector('.cp-body');
      if (v.mode === 'smart') return cpSmart(body);
      body.innerHTML = `<nav class="cp-tree">${CP_TREE.map(([label, page, sub]) => page === null ? `<a class="g">▾ ${h(label)}</a>` : `<a data-go="${page}" data-t="${h(label)}" class="${sub ? 's' : ''}${
        page === 'na' ? ' na' : ''}${label === v.title ? ' on' : ''}">${h(label)}</a>`).join('')}</nav><main class="cp-main"></main>`;
      body.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => go(a.dataset.go, {title: a.dataset.t}); });
      const main = body.querySelector('main');
      main.innerHTML = `<h2>${h(v.title)}</h2>`;
      const pages = {overview: cpOverview, interfaces: cpInterfaces, routes: cpRoutes, dhcp: cpDhcp, hosts: cpHosts, features: m => m.insertAdjacentHTML('beforeend', `<div class="cp-box">
        <div class="b">${table('cp-t', ['Protocol', 'Configuration'], (D().features || []).filter(f => f.name.toUpperCase().includes(v.title)).map(f => tr([h(f.name), h(f.detail)])), 'Not configured')}</div></div>`)};
      (pages[v.page] || (m => m.insertAdjacentHTML('beforeend', naBox(v.title, NA.later))))(main);
    },
  };
  function cpOverview(main) {
    const d = D();
    main.insertAdjacentHTML('beforeend', `<div class="cp-grid"><div class="cp-box"><h3>System Overview</h3><div class="b cp-kv"><span>Hostname</span><b>${h(N().name)}</b>
      <span>Version</span><b>Gaia · sous-ensemble Network LABS</b><span>Edition</span><b>64-bit</b><span>Platform</span><b>${h(d.brand)} ${h(d.model)}</b>
      <span>Uptime</span><b>${running() ? 'en marche' : 'lab arrêté'}</b></div></div><div class="cp-box"><h3>Blades</h3><div class="b cp-kv"><span>Firewall</span><b class="sc-acc">✔</b>
      <span>IPS</span><b>✖</b><span>Application Control</span><b>✖</b><span>Threat Emulation</span><b>✖</b></div></div>
      <div class="cp-box"><h3>Network Configuration</h3>${table('cp-t', ['Interface', 'Status', 'IPv4 Address'], d.ports.map(p => tr([h(p.name), p.peer && !p.down ? 'Up' : 'Down', h(p.address || '—')])))}</div>
      <div class="cp-box"><h3>CPU Monitor · Memory Monitor</h3><div class="b cp-kv"><span>CPU</span><b>${running() ? '2%' : '—'}</b><span>Memory</span><b>${running() ? '41%' : '—'}</b></div></div></div>`);
  }
  function cpInterfaces(main) {
    const d = D();
    main.insertAdjacentHTML('beforeend', `<div class="cp-box"><div class="cp-bar"><button disabled>Add ▾</button><button class="edit">Edit</button><button disabled>Delete</button>
      <button class="ref">Refresh</button></div>${table('cp-t', ['Name', 'Type', 'IPv4 Address', 'Subnet Mask', 'Link Status', 'Comments'], d.ports.map((p, i) => tr([h(p.name), 'Ethernet',
        h(ipOf(p.address)), h(p.address ? maskOf(lenOf(p.address)) : ''), p.down ? 'Down' : p.peer ? 'Up' : 'No Link', h(p.peer ? 'to ' + p.peer : '')], `data-r="${i}"`)))}</div>`);
    let chosen = null;
    main.querySelectorAll('tr[data-r]').forEach(row => { row.onclick = () => { main.querySelectorAll('tr.sel').forEach(r => r.classList.remove('sel')); row.classList.add('sel'); chosen = Number(row.dataset.r); };
      row.ondblclick = () => cpEditIf(d.ports[chosen]); });
    main.querySelector('.edit').onclick = () => (chosen === null ? toast('Select an interface.', true) : cpEditIf(d.ports[chosen]));
    main.querySelector('.ref').onclick = () => load();
  }
  function cpEditIf(p) {
    dialog('gaia', `Edit ${p.name}`, `${field('', `<span>${p.down ? '☐' : '☑'} Enable</span>`)}${field('Comment', input('c', p.peer ? 'to ' + p.peer : ''))}
      ${field('', '<span>( ) Obtain IPv4 address automatically &nbsp; (•) Use the following IPv4 address:</span>')}${field('IPv4 address', input('cpIp', ipOf(p.address)))}
      ${field('Subnet mask', input('cpMask', p.address ? maskOf(lenOf(p.address)) : '255.255.255.0'))}`,
    [['OK', 'pri', async b => {
      const ip = val(b, '#cpIp'), prefix = prefixOf(val(b, '#cpMask'));
      if (ip && (!validIp(ip) || prefix === null)) throw new Error('IPv4 address / Subnet mask invalide.');
      await setAddress(p.port, ip ? `${ip}/${prefix}` : '');
      render(); toast('Interface saved.');
    }], ['Cancel']]);
  }
  function cpRoutes(main) {
    main.insertAdjacentHTML('beforeend', `<div class="cp-box"><div class="cp-bar"><button disabled>Add</button><button disabled>Edit</button><button disabled>Delete</button></div>${table('cp-t',
      ['Destination', 'Next Hop Type', 'Gateway', 'Rank', 'Comment'], [...D().connected.map(r => tr([h(r.network), 'Directly connected', h(r.port), '0', ''])),
        ...D().static.map(r => tr([h(r.network), 'Normal', h(r.gateway), '60', '']))])}<div class="b" style="color:#666">Network LABS : routes de ce pare-feu dans ◉ Network LABS › Vue Network LABS › Routage.</div></div>`);
  }
  function cpDhcp(main) {
    const s = dhcpServer();
    main.insertAdjacentHTML('beforeend', `<div class="cp-box"><div class="cp-bar"><button class="add">${s ? 'Edit' : 'Add'}</button>${s ? '<button class="del">Delete</button>' : ''}</div>
      ${table('cp-t', ['Subnet', 'Netmask', 'Address Pool', 'Default Gateway', 'DNS', 'Enabled'], s ? [tr([h(ipOf(networkOf(N().interfaces[s.interface]))), h(maskOf(lenOf(N().interfaces[s.interface]))),
        h(`${s.start} - ${s.end}`), h(s.router || ''), h((s.dns || []).join(', ')), '✔'])] : [])}</div>`);
    main.querySelector('.add').onclick = () => {
      const options = D().ports.filter(p => p.address).map(p => [p.port, p.name]);
      dialog('gaia', 'DHCP Server Subnet Configuration', `${field('Interface', select('cpIf', options, s ? s.interface : options[0]?.[0]))}${field('Address Pool from', input('cpS', s ? s.start : ''))}
        ${field('Address Pool to', input('cpE', s ? s.end : ''))}${field('Default Gateway', input('cpR', s ? s.router : ''))}${field('Primary DNS Server', input('cpD', s ? (s.dns || [])[0] || '' : ''))}
        ${field('Default Lease (seconds)', input('cpL', s ? s.lease_seconds : 43200))}`, [['OK', 'pri', async b => {
        await section('dhcpserver', {dhcp_server: dhcpFrom(b, {iface: '#cpIf', start: '#cpS', end: '#cpE', router: '#cpR', dns: '#cpD', lease: '#cpL'})}); render(); }], ['Cancel']]);
    };
    const del = main.querySelector('.del');
    if (del) del.onclick = () => now(() => section('dhcpserver', {dhcp_server: null}), 'DHCP server deleted.');
  }
  function cpHosts(main) {
    main.insertAdjacentHTML('beforeend', `<div class="cp-box"><h3>System Name</h3><div class="b">${field('Host Name', input('cpHost', N().name))}${field('Domain Name', input('dn', '', 'disabled'))}
      <button class="apply">Apply</button></div></div>`);
    main.querySelector('.apply').onclick = () => attempt(() => rename(val(main, '#cpHost')), 'Host name changed.');
  }
  // SmartConsole: the security policy and NAT rulebases; changes are published, then installed on the gateway.
  function cpSmart(body) {
    const v = V(), f = candidateFw(), count = pending();
    body.className = 'sc';
    body.innerHTML = `<nav class="sc-rail">${[['▤', 'GATEWAYS & SERVERS', 'gateways'], ['⛨', 'SECURITY POLICIES', 'policy'], ['☰', 'LOGS & MONITOR', 'na'], ['⚙', 'MANAGE & SETTINGS', 'na']]
      .map(([icon, label, page]) => `<a data-sc="${page}" class="${page === v.sc || (page === 'policy' && ['policy', 'nat'].includes(v.sc)) ? 'on' : ''}${page === 'na' ? ' na' : ''}"><i>${icon}</i>${label}</a>`).join('')}</nav>
      <div class="sc-main"><div class="sc-tool"><button disabled>Objects ▾</button><button class="install">⬇ Install Policy</button><span class="grow"></span>
      <button class="pub">Publish${count ? ` (${count})` : ''}</button><button class="disc">Discard</button><span>admin@${h(N().name)}</span></div><div class="sc-split"></div></div>`;
    body.querySelectorAll('[data-sc]').forEach(a => { a.onclick = () => { if (a.dataset.sc !== 'na') { v.sc = a.dataset.sc; render(); } }; });
    body.querySelector('.pub').onclick = () => { if (!count) return toast('No changes to publish.'); v.published = true; toast(`Session published (${count} change(s)). Install Policy to enforce it on the gateway.`); };
    body.querySelector('.disc').onclick = () => { v.published = false; discard(); };
    body.querySelector('.install').onclick = () => {
      if (count && !v.published) return toast('Publish the session before installing the policy.', true);
      dialog('gaia', 'Install Policy', `<p>Install the Standard policy on:</p>${table('cp-t', ['', 'Gateway', 'Access Control'], [tr(['☑', h(N().name), '☑'])])}`,
        [['Install', 'pri', async () => { await commit(null); v.published = false; render(); toast('Policy installed on ' + N().name + '.'); }], ['Cancel']]);
    };
    const split = body.querySelector('.sc-split');
    if (v.sc === 'gateways') {
      split.style.gridTemplateColumns = '1fr';
      split.innerHTML = `<div style="padding:10px">${table('cp-t', ['Status', 'Name', 'IP', 'Version', 'Active Blades', 'Hardware'], [tr([running() ? '🟢' : '⚪', h(N().name),
        h(ipOf(Object.values(N().interfaces).find(Boolean) || '') || '—'), 'Network LABS', 'Firewall', h(D().model)])])}</div>`;
      return;
    }
    split.innerHTML = `<div class="sc-left"><b>Access Control</b><a data-p="policy" class="${v.sc === 'policy' ? 'on' : ''}">Policy</a><a data-p="nat" class="${v.sc === 'nat' ? 'on' : ''}">NAT</a>
      <b>Threat Prevention</b><a style="color:#9aa1a8">Policy</a></div><div style="padding:8px;overflow:auto"><div class="sc-tool" style="border:1px solid #d6d9dd">
      <button class="add">⊕ Add rule</button><button class="edit">✎</button><button class="del">✖ Delete</button><button class="up">↑</button><button class="down">↓</button></div><div class="tbl"></div></div>`;
    split.querySelectorAll('[data-p]').forEach(a => { a.onclick = () => { v.sc = a.dataset.p; render(); }; });
    const nat = v.sc === 'nat', box = split.querySelector('.tbl');
    box.innerHTML = nat ? table('cp-t', ['No.', 'Original Source', 'Original Destination', 'Original Services', 'Translated Source', 'Translated Destination', 'Translated Services',
      'Install On', 'Comments'], (f.nat || []).map((r, i) => tr([String(i + 1), h(r.source || 'Any'), h(r.destination || 'Any'), h(r.protocol && r.protocol !== 'any' ? svc(r) : 'Any'),
        h(r.type === 'masquerade' ? 'Hide (interface)' : r.type === 'snat' ? r.to : '= Original'), h(r.type === 'dnat' ? r.to : '= Original'), h(r.to_port || '= Original'),
        'Policy Targets', h(r.name)], `data-r="${i}"`)), 'No NAT rules')
      : table('cp-t', ['No.', 'Name', 'Source', 'Destination', 'VPN', 'Services & Applications', 'Action', 'Track', 'Install On'], [...f.rules.map((r, i) => tr([String(i + 1), h(r.name),
        h(r.source || 'Any') + (r.in ? ` <small>(${h(portName(r.in))})</small>` : ''), h(r.destination || 'Any') + (r.out ? ` <small>(${h(portName(r.out))})</small>` : ''), 'Any',
        h(svc(r) === 'any' ? 'Any' : svc(r)), r.action === 'accept' ? '<span class="sc-acc">✔ Accept</span>' : '<span class="sc-drop">⊘ Drop</span>', 'Log', 'Policy Targets'], `data-r="${i}"`)),
        `<tr class="cl"><td>${f.rules.length + 1}</td><td>Cleanup rule</td><td>Any</td><td>Any</td><td>Any</td><td>Any</td><td>${f.default === 'accept' ? '✔ Accept' : '⊘ Drop'}</td><td>None</td><td>Policy Targets</td></tr>`]);
    let chosen = null;
    const list = nat ? 'nat' : 'rules';
    box.querySelectorAll('tr[data-r]').forEach(row => { row.onclick = () => { box.querySelectorAll('tr.sel').forEach(r => r.classList.remove('sel')); row.classList.add('sel'); chosen = Number(row.dataset.r); };
      row.ondblclick = () => cpEdit(nat, chosen); });
    const touch = () => { v.published = false; render(); };
    split.querySelector('.add').onclick = () => cpEdit(nat, null);
    split.querySelector('.edit').onclick = () => (chosen === null ? toast('Select a rule.', true) : cpEdit(nat, chosen));
    split.querySelector('.del').onclick = () => (chosen === null ? toast('Select a rule.', true) : dropEntry(list, chosen, true).then(touch));
    split.querySelector('.up').onclick = () => chosen !== null && moveEntry(list, chosen, -1, true).then(touch);
    split.querySelector('.down').onclick = () => chosen !== null && moveEntry(list, chosen, 1, true).then(touch);
  }
  function cpEdit(nat, index) {
    const f = candidateFw(), r = index === null ? (nat ? {type: 'masquerade'} : {action: 'accept'}) : f[nat ? 'nat' : 'rules'][index];
    const done = () => { V().published = false; render(); };
    if (nat) {
      const x = natPieces(r, {name: 'Comments', in: 'Original: from interface', out: 'Translated: through interface', source: 'Original Source', destination: 'Original Destination',
        service: 'Original Services', to: 'Translated Destination', to_port: 'Translated Services (port)', types: [['masquerade', 'x']], any: 'Any'});
      return dialog('gaia', 'NAT Rule', x.source + x.destination + x.service + xsrcPiece(r, 'Translated Source', [['', '= Original'], ['masquerade', 'Hide behind gateway (interface)'],
        ['snat', 'Static (interface address)']]) + x.to + x.to_port + x.in + x.out + x.name, [['OK', 'pri', async b => { await putEntry('nat', index, natColumns(b), true); done(); }], ['Cancel']]);
    }
    dialog('gaia', 'Rule', `${field('Name', input('cpName', r.name || ''))}${field('Source', input('cpSrc', r.source || 'Any'))}${field('Destination', input('cpDst', r.destination || 'Any'))}
      ${field('Services & Applications', input('cpSvc', svc(r) === 'any' ? 'Any' : svc(r)), 'Any, http, https, ssh, domain-udp, tcp/8080')}${field('Action', select('cpAct', [['accept', 'Accept'], ['drop', 'Drop']], r.action))}
      ${field('Track', select('t', ['Log'], 'Log'))}${field('Install On', select('i', ['Policy Targets'], 'Policy Targets'))}`,
    [['OK', 'pri', async b => {
      const any = text => (text.toLowerCase() === 'any' ? '' : text);
      const rule = ruleFrom(index === null ? {} : r, {name: val(b, '#cpName') || `rule-${f.rules.length + 1}`, action: val(b, '#cpAct'), in: r.in, out: r.out,
        source: checkNet(any(val(b, '#cpSrc')), 'Source'), destination: checkNet(any(val(b, '#cpDst')), 'Destination'), service: val(b, '#cpSvc').replace(/^domain-udp$/i, 'dns')});
      await putEntry('rules', index, rule, true);
      done();
    }], ['Cancel']]);
  }

  /* =============================== SonicWall SonicOS =============================== */
  skinCss(`
  .px-app.sonicos{min-height:100vh;background:#f3f5f7;color:#26323d;font:13px Arial,Helvetica,sans-serif;display:grid;grid-template-rows:50px 1fr}
  .sw-top{display:flex;align-items:stretch;background:#212e3a;color:#c9d4de}.sw-top .brand{display:flex;align-items:center;padding:0 18px;color:#fff;font-weight:bold;font-size:15px}
  .sw-top a{display:flex;align-items:center;padding:0 18px;cursor:pointer;font-weight:bold;letter-spacing:.5px;color:#c9d4de}.sw-top a.on{background:#f3f5f7;color:#212e3a}
  .sw-top a:hover{color:#fff}.sw-top a.on:hover{color:#212e3a}.sw-top .grow{flex:1}.sw-top span{display:flex;align-items:center;padding:0 14px}
  .sw-body{display:grid;grid-template-columns:220px 1fr;min-height:0}.sw-side{background:#fff;border-right:1px solid #dde3e8;padding:8px 0}
  .sw-side b{display:block;padding:10px 16px 4px;color:#7d8a96;font-size:11px;text-transform:uppercase}.sw-side a{display:block;padding:6px 16px 6px 24px;cursor:pointer}
  .sw-side a.on{background:#e3f0fb;color:#1162b0;font-weight:bold;border-left:3px solid #1162b0;padding-left:21px}.sw-side a.na{color:#a3adb6}
  .sw-main{padding:14px 18px;overflow:auto}.sw-crumb{color:#7d8a96;margin-bottom:6px}.sw-main h2{margin:0 0 12px;font-size:19px;font-weight:normal}
  .sw-bar{display:flex;gap:8px;align-items:center;margin-bottom:10px}.sw-bar .grow{flex:1}
  .sw-btn{border:1px solid #1162b0;background:#fff;color:#1162b0;padding:5px 12px;border-radius:3px;cursor:pointer}.sw-btn.pri{background:#1162b0;color:#fff}
  .sw-t{width:100%;border-collapse:collapse;background:#fff;border:1px solid #dde3e8}.sw-t th{text-align:left;padding:8px;background:#f7f9fa;border-bottom:1px solid #dde3e8;white-space:nowrap}
  .sw-t td{padding:8px;border-bottom:1px solid #edf1f4;white-space:nowrap}.sw-t a{color:#1162b0;cursor:pointer}.sw-ok{color:#2e7d32}.sw-no{color:#c62828}
  .sw-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.sw-card{background:#fff;border:1px solid #dde3e8;padding:12px}.sw-card h3{margin:0 0 8px;font-size:14px}
  .px-shade.sonicos .px-dtitle{background:#212e3a;color:#fff}.px-shade.sonicos .px-dfoot button{border:1px solid #1162b0;background:#fff;color:#1162b0;padding:5px 16px;cursor:pointer}
  .px-shade.sonicos .px-dfoot button.pri{background:#1162b0;color:#fff}
  `);
  const SW_TABS = {HOME: [['Dashboard', [['System', 'dashboard']]]], MONITOR: [['Real-Time Charts', [['System Monitor', 'na']]], ['Logs', [['System Logs', 'na']]]],
    DEVICE: [['Settings', [['Administration', 'admin'], ['Time', 'na']]], ['Diagnostics', [['Ping', 'terminal']]]],
    NETWORK: [['System', [['Interfaces', 'interfaces'], ['Zones', 'zones'], ['DHCP Server', 'dhcp'], ['Routing', 'routes']]], ['Firewall', [['Advanced', 'na'], ['Flood Protection', 'na']]]],
    OBJECT: [['Match Objects', [['Zones', 'zones'], ['Addresses', 'na'], ['Services', 'services']]]],
    POLICY: [['Rules and Policies', [['Access Rules', 'rules'], ['NAT Rules', 'nat'], ['Routing Rules', 'routes']]], ['Security Services', [['Gateway Anti-Virus', 'engine'], ['Intrusion Prevention', 'engine']]]]};
  const swZone = port => zoneNames(['WAN', 'LAN', 'DMZ'])[port] || 'LAN';
  SKINS.sonicos = {
    start: {tab: 'HOME', page: 'dashboard', title: 'System'},
    draw(root) {
      const v = V();
      root.innerHTML = `<div class="sw-top"><span class="brand">SonicOS</span>${Object.keys(SW_TABS).map(t => `<a data-tab="${t}" class="${t === v.tab ? 'on' : ''}">${t}</a>`).join('')}
        <span class="grow"></span><span>${h(N().name)} · ${h(D().model)} · Network LABS</span><span>admin ▾</span></div><div class="sw-body"><nav class="sw-side">${SW_TABS[v.tab].map(([g, items]) =>
          `<b>${h(g)}</b>${items.map(([label, page]) => `<a data-go="${page}" data-t="${h(label)}" class="${['na', 'engine'].includes(page) ? 'na' : ''}${label === v.title ? ' on' : ''}">${h(label)}</a>`).join('')}`).join('')}
        </nav><main class="sw-main"><div class="sw-crumb">${h(v.tab)} › ${h(v.title)}</div><h2>${h(v.title)}</h2></main></div>`;
      root.querySelectorAll('[data-tab]').forEach(a => { a.onclick = () => { const [, items] = SW_TABS[a.dataset.tab][0]; go(items[0][1], {tab: a.dataset.tab, title: items[0][0]}); }; });
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => go(a.dataset.go, {title: a.dataset.t}); });
      const main = root.querySelector('main');
      const pages = {dashboard: swDashboard, interfaces: swInterfaces, zones: swZones, dhcp: swDhcp, routes: swRoutes, rules: swRules, nat: swNat, admin: swAdmin, services: soServices2,
        terminal: m => { openTerminal(); swDashboard(m); }, engine: m => m.insertAdjacentHTML('beforeend', naBox(v.title, NA.engine))};
      (pages[v.page] || (m => m.insertAdjacentHTML('beforeend', naBox(v.title, NA.later))))(main);
    },
  };
  function soServices2(main) {
    main.insertAdjacentHTML('beforeend', table('sw-t', ['Name', 'Protocol', 'Port Range'], [['HTTP', 'TCP', '80'], ['HTTPS', 'TCP', '443'], ['SSH', 'TCP', '22'], ['DNS (Name Service)', 'UDP', '53'],
      ['Ping', 'ICMP', '8']].map(r => tr(r.map(h)))));
  }
  function swDashboard(main) {
    const d = D(), f = fw();
    main.insertAdjacentHTML('beforeend', `<div class="sw-grid"><div class="sw-card"><h3>System</h3>Model: ${h(d.model)}<br>Firmware: SonicOS · sous-ensemble Network LABS<br>Uptime: ${
      running() ? 'en marche' : 'lab arrêté'}</div><div class="sw-card"><h3>Network</h3>${d.ports.filter(p => p.peer && !p.down).length} / ${d.ports.length} interfaces up<br>${f.rules.length} access rules ·
      ${(f.nat || []).length} NAT policies</div><div class="sw-card"><h3>Threat</h3>Security services : ${h(NA.engine)}</div></div>
      <div class="sw-card" style="margin-top:12px"><h3>Interfaces</h3>${table('sw-t', ['Name', 'Zone', 'IP Address', 'Status'], d.ports.map(p => tr([h(p.name), h(swZone(p.port)), h(p.address || '0.0.0.0'),
        p.peer && !p.down ? '<span class="sw-ok">1 Gbps Full Duplex</span>' : '<span class="sw-no">No link</span>'])))}</div>`);
  }
  function swInterfaces(main) {
    const d = D();
    main.insertAdjacentHTML('beforeend', table('sw-t', ['Name', 'Zone', 'Group', 'IP Address', 'Subnet Mask', 'IP Assignment', 'Status', 'Enabled', 'Comment', 'Configure'],
      d.ports.map((p, i) => tr([h(p.name), h(swZone(p.port)), '', h(ipOf(p.address) || '0.0.0.0'), h(p.address ? maskOf(lenOf(p.address)) : '0.0.0.0'), 'Static',
        p.peer && !p.down ? '<span class="sw-ok">1 Gbps Full Duplex</span>' : '<span class="sw-no">No link</span>', p.down ? '○' : '●', h(p.peer ? 'to ' + p.peer : 'Default ' + swZone(p.port)),
        `<a data-e="${i}">✎</a>`]))));
    main.querySelectorAll('[data-e]').forEach(a => { a.onclick = () => {
      const p = d.ports[Number(a.dataset.e)];
      dialog('sonicos', `Edit Interface - ${p.name}`, `<p><b>General</b> · Advanced</p>${field('Zone', input('z', swZone(p.port), 'disabled'))}${field('Mode / IP Assignment', select('m', ['Static IP Mode'], ''))}
        ${field('IP Address', input('swIp', ipOf(p.address)))}${field('Subnet Mask', input('swMask', p.address ? maskOf(lenOf(p.address)) : '255.255.255.0'))}
        ${field('Comment', input('c', p.peer ? 'to ' + p.peer : ''))}${field('Management', '<span>☑ HTTPS ☑ Ping ☐ SNMP ☐ SSH</span>')}`,
      [['OK', 'pri', async b => {
        const ip = val(b, '#swIp'), prefix = prefixOf(val(b, '#swMask'));
        if (ip && (!validIp(ip) || prefix === null)) throw new Error('IP Address / Subnet Mask invalide.');
        await setAddress(p.port, ip ? `${ip}/${prefix}` : '');
        render(); toast(`${p.name} : settings saved.`);
      }], ['Cancel']]);
    }; });
  }
  function swZones(main) {
    main.insertAdjacentHTML('beforeend', table('sw-t', ['Name', 'Security Type', 'Member Interfaces', 'Interface Trust'], [...new Set(ports().map(swZone))].map(z => tr([h(z),
      z === 'WAN' ? 'Untrusted' : z === 'DMZ' ? 'Public' : 'Trusted', h(ports().filter(p => swZone(p) === z).map(portName).join(', ')), z === 'WAN' ? '' : '✔']))));
  }
  function swRules(main) {
    const f = fw(), zones = ports().map(p => [p, swZone(p)]);
    main.insertAdjacentHTML('beforeend', `<div class="sw-bar"><span>From: All ▾ → To: All ▾</span><span class="grow"></span><button class="sw-btn pri add">＋ Add</button></div>${table('sw-t',
      ['#', 'Priority', 'Name', 'Action', 'Source Zone', 'Destination Zone', 'Source', 'Destination', 'Service', 'Hits', 'Enable', ''], [...f.rules.map((r, i) => tr([String(i + 1), String(i + 1),
        `<a data-e="${i}">${h(r.name)}</a>`, r.action === 'accept' ? '<span class="sw-ok">✔ Allow</span>' : '<span class="sw-no">✖ Deny</span>', h(r.in ? swZone(r.in) : 'Any'), h(r.out ? swZone(r.out) : 'Any'),
        h(r.source || 'Any'), h(r.destination || 'Any'), h(svc(r) === 'any' ? 'Any' : svc(r)), '0', '●', `<a data-x="${i}">🗑</a>`])),
        `<tr><td></td><td>Default</td><td><i>Default Access Rule</i></td><td>${f.default === 'accept' ? 'Allow' : 'Deny'}</td><td>Any</td><td>Any</td><td>Any</td><td>Any</td><td>Any</td><td>0</td><td>●</td><td></td></tr>`])}`);
    const edit = index => {
      const r = index === null ? {action: 'accept'} : f.rules[index];
      dialog('sonicos', index === null ? 'Adding Rule' : 'Editing Rule', `<p><b>Source / Destination</b> · User & TCP/UDP · Security Profiles · Traffic Shaping · Logging · Optional Settings</p>
        ${field('Name', input('swName', r.name || ''))}${field('Action', select('swAct', [['accept', 'Allow'], ['drop', 'Deny']], r.action))}${field('From', select('swFrom', [['', 'Any'], ...zones], r.in || ''))}
        ${field('To', select('swTo', [['', 'Any'], ...zones], r.out || ''))}${field('Source · Address', input('swSrc', r.source || 'Any'))}${field('Destination · Address', input('swDst', r.destination || 'Any'))}
        ${field('Service', input('swSvc', svc(r) === 'any' ? 'Any' : svc(r)), 'Any, HTTP, HTTPS, SSH, DNS, tcp/8080')}`,
      [[index === null ? 'Add' : 'Save', 'pri', async b => {
        const any = text => (text.toLowerCase() === 'any' ? '' : text);
        await saveRule(index, ruleFrom(index === null ? {} : r, {name: val(b, '#swName') || `rule-${f.rules.length + 1}`, action: val(b, '#swAct'), in: val(b, '#swFrom'), out: val(b, '#swTo'),
          source: checkNet(any(val(b, '#swSrc')), 'Source'), destination: checkNet(any(val(b, '#swDst')), 'Destination'), service: val(b, '#swSvc')}));
        render(); toast('Access rule saved.');
      }], ['Cancel']]);
    };
    main.querySelector('.add').onclick = () => edit(null);
    main.querySelectorAll('[data-e]').forEach(a => { a.onclick = () => edit(Number(a.dataset.e)); });
    main.querySelectorAll('[data-x]').forEach(a => { a.onclick = () => now(async () => { const f2 = clone(fw()); f2.rules.splice(Number(a.dataset.x), 1); await section('firewall', {firewall: f2}); }, 'Rule deleted.'); });
  }
  function swNat(main) {
    const nat = fw().nat || [];
    main.insertAdjacentHTML('beforeend', `<div class="sw-bar"><span class="grow"></span><button class="sw-btn pri add">＋ Add</button></div>${table('sw-t', ['#', 'Name', 'Source Original',
      'Source Translated', 'Destination Original', 'Destination Translated', 'Service Original', 'Service Translated', 'Inbound', 'Outbound', ''], nat.map((r, i) => tr([String(i + 1),
        `<a data-e="${i}">${h(r.name)}</a>`, h(r.source || 'Any'), h(r.type === 'masquerade' ? `${r.out ? portName(r.out) : 'X1'} IP` : r.type === 'snat' ? r.to : 'Original'),
        h(r.destination || 'Any'), h(r.type === 'dnat' ? r.to : 'Original'), h(r.protocol && r.protocol !== 'any' ? svc(r) : 'Any'), h(r.to_port || 'Original'),
        h(r.in ? portName(r.in) : 'Any'), h(r.out ? portName(r.out) : 'Any'), `<a data-x="${i}">🗑</a>`])), 'No NAT policies')}`);
    const edit = index => {
      const r = index === null ? {type: 'masquerade'} : nat[index];
      const x = natPieces(r, {name: 'Name', in: 'Inbound Interface', out: 'Outbound Interface', source: 'Original Source', destination: 'Original Destination', service: 'Original Service',
        to: 'Translated Destination', to_port: 'Translated Service (port)', types: [['masquerade', 'x']], any: 'Any'});
      dialog('sonicos', index === null ? 'Adding NAT Policy' : 'Editing NAT Policy', x.name + x.source + xsrcPiece(r, 'Translated Source', [['', 'Original'], ['masquerade', 'Outbound interface IP (dynamic)'],
        ['snat', 'Outbound interface IP (static)']]) + x.destination + x.to + x.service + x.to_port + x.in + x.out,
      [[index === null ? 'Add' : 'Save', 'pri', async b => { await putEntry('nat', index, natColumns(b), false); render(); toast('NAT policy saved.'); }], ['Cancel']]);
    };
    main.querySelector('.add').onclick = () => edit(null);
    main.querySelectorAll('[data-e]').forEach(a => { a.onclick = () => edit(Number(a.dataset.e)); });
    main.querySelectorAll('[data-x]').forEach(a => { a.onclick = () => now(() => dropEntry('nat', Number(a.dataset.x), false), 'NAT policy deleted.'); });
  }
  function swDhcp(main) {
    const s = dhcpServer();
    main.insertAdjacentHTML('beforeend', `<div class="sw-bar"><span>☑ Enable DHCPv4 Server</span><span class="grow"></span><button class="sw-btn pri add">${s ? 'Edit' : 'Add Dynamic'}</button>${s
      ? '<button class="sw-btn del">Delete</button>' : ''}</div>${table('sw-t', ['Type', 'Interface', 'Range Start', 'Range End', 'Default Gateway', 'DNS', 'Lease Time'], s ? [tr(['Dynamic',
        h(portName(s.interface)), h(s.start), h(s.end), h(s.router || ''), h((s.dns || []).join(', ')), h(`${Math.round((s.lease_seconds || 86400) / 60)} min`)])] : [], 'No lease scopes')}`);
    main.querySelector('.add').onclick = () => {
      const options = D().ports.filter(p => p.address).map(p => [p.port, p.name]);
      dialog('sonicos', 'Dynamic Range Configuration', `${field('Interface', select('swIf', options, s ? s.interface : options[0]?.[0]))}${field('Range Start', input('swS', s ? s.start : ''))}
        ${field('Range End', input('swE', s ? s.end : ''))}${field('Default Gateway', input('swR', s ? s.router : ''))}${field('DNS Server 1', input('swD', s ? (s.dns || [])[0] || '' : ''))}
        ${field('Lease Time (seconds)', input('swL', s ? s.lease_seconds : 86400))}`, [['OK', 'pri', async b => {
        await section('dhcpserver', {dhcp_server: dhcpFrom(b, {iface: '#swIf', start: '#swS', end: '#swE', router: '#swR', dns: '#swD', lease: '#swL'})}); render(); }], ['Cancel']]);
    };
    const del = main.querySelector('.del');
    if (del) del.onclick = () => now(() => section('dhcpserver', {dhcp_server: null}), 'Lease scope deleted.');
  }
  function swRoutes(main) {
    main.insertAdjacentHTML('beforeend', `${table('sw-t', ['#', 'Source', 'Destination', 'Service', 'Gateway', 'Interface', 'Metric', 'Type'], [...D().connected.map((r, i) => tr([String(i + 1), 'Any',
      h(r.network), 'Any', '0.0.0.0', h(r.port), '1', 'Interface'])), ...D().static.map((r, i) => tr([String(D().connected.length + i + 1), 'Any', h(r.network), 'Any', h(r.gateway), h(r.port), '1', 'Static']))])}
      <p style="color:#7d8a96">Network LABS : routes de ce pare-feu dans ◉ Network LABS › Vue Network LABS › Routage.</p>`);
  }
  function swAdmin(main) {
    main.insertAdjacentHTML('beforeend', `<div class="sw-card">${field('Firewall Name', input('swHost', N().name))}${field('Firewall Domain Name', input('dn', '', 'disabled'))}
      <button class="sw-btn pri apply">Accept</button></div>`);
    main.querySelector('.apply').onclick = () => attempt(() => rename(val(main, '#swHost')), 'Firewall name changed.');
  }

  /* =============================== WatchGuard Fireware Web UI =============================== */
  skinCss(`
  .px-app.fireware{min-height:100vh;background:#fff;color:#222;font:13px Arial,Helvetica,sans-serif;display:grid;grid-template-rows:48px 1fr}
  .wg-top{display:flex;align-items:center;gap:16px;padding:0 16px;background:#1c1c1c;color:#fff}.wg-top b{font-size:15px}.wg-top .grow{flex:1}.wg-top span{color:#bbb}
  .wg-body{display:grid;grid-template-columns:220px 1fr;min-height:0}.wg-nav{background:#f0f0f0;border-right:1px solid #d7d7d7;overflow:auto;padding:6px 0}
  .wg-nav b{display:block;padding:10px 14px 4px;font-size:11.5px;color:#444}.wg-nav a{display:block;padding:4px 14px 4px 24px;cursor:pointer;color:#1a4f8b}
  .wg-nav a.on{background:#dcdcdc;color:#000;font-weight:bold}.wg-nav a.na{color:#9a9a9a}
  .wg-main{padding:14px 18px;overflow:auto}.wg-main h2{margin:0 0 12px;font-size:20px;font-weight:normal}
  .wg-bar{display:flex;gap:8px;margin:8px 0}.wg-btn{border:1px solid #9b9b9b;background:linear-gradient(#fff,#e3e3e3);padding:5px 14px;cursor:pointer;font-weight:bold;font-size:12px}
  .wg-btn.pri{background:linear-gradient(#4b8fd6,#2a6db3);color:#fff;border-color:#2a6db3}
  .wg-t{width:100%;border-collapse:collapse}.wg-t th{background:#e8e8e8;text-align:left;padding:6px 8px;border:1px solid #d0d0d0;white-space:nowrap}
  .wg-t td{padding:6px 8px;border:1px solid #e3e3e3;white-space:nowrap}.wg-t tr.sel td{background:#cde0f5}.wg-t a{color:#1a4f8b;cursor:pointer}
  .wg-ok{color:#2e7d32;font-weight:bold}.wg-no{color:#c62828;font-weight:bold}
  .wg-box{border:1px solid #d0d0d0;margin-bottom:12px}.wg-box h3{margin:0;padding:6px 10px;background:#e8e8e8;font-size:13px}.wg-box .b{padding:10px}
  .wg-cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}.wg-form{max-width:720px}
  .px-shade.fireware .px-dtitle{background:#1c1c1c;color:#fff}.px-shade.fireware .px-dfoot button{border:1px solid #9b9b9b;background:linear-gradient(#fff,#e3e3e3);padding:5px 16px;cursor:pointer}
  `);
  const WG_NAV = [['DASHBOARD', [['Front Panel', 'front'], ['Subscription Services', 'engine'], ['FireWatch', 'na'], ['Interfaces', 'ifstatus'], ['Traffic Monitor', 'na']]],
    ['SYSTEM STATUS', [['ARP Table', 'na'], ['DHCP Leases', 'na'], ['Routes', 'routes'], ['Diagnostics', 'terminal']]],
    ['NETWORK', [['Interfaces', 'interfaces'], ['Link Aggregation', 'na'], ['VLAN', 'na'], ['Bridge', 'na'], ['Multi-WAN', 'na'], ['NAT', 'nat'], ['Routes', 'routes']]],
    ['FIREWALL', [['Firewall Policies', 'policies'], ['Mobile VPN Policies', 'vpn'], ['Aliases', 'aliases'], ['Policy Checker', 'na'], ['Proxy Actions', 'engine']]],
    ['SUBSCRIPTION SERVICES', [['Gateway AntiVirus', 'engine'], ['IPS', 'engine'], ['WebBlocker', 'engine']]], ['AUTHENTICATION', [['Servers', 'na'], ['Users and Groups', 'na']]],
    ['VPN', [['Branch Office VPN', 'vpn'], ['Mobile VPN', 'vpn']]], ['SYSTEM', [['System', 'system'], ['Feature Key', 'na'], ['Logging', 'na'], ['Users and Roles', 'na']]]];
  const wgType = port => zoneNames(['External', 'Trusted', 'Optional'])[port] || 'Trusted';
  const wgAlias = port => { const i = ports().indexOf(port); const t = wgType(port); return t === 'Optional' ? `Optional-${i}` : t; };
  const wgAny = port => `Any-${wgType(port)}`;
  SKINS.fireware = {
    start: {page: 'front', title: 'Front Panel'},
    draw(root) {
      const v = V();
      root.innerHTML = `<div class="wg-top"><b>Fireware Web UI</b><span>${h(N().name)} · ${h(D().model)} · sous-ensemble Network LABS</span><span class="grow"></span><span>User: admin</span>
        <span>Help</span><span>Logout</span></div><div class="wg-body"><nav class="wg-nav">${WG_NAV.map(([g, items]) => `<b>${g}</b>${items.map(([label, page]) => `<a data-go="${page}" data-t="${h(label)}"
          class="${['na', 'engine', 'vpn'].includes(page) ? 'na' : ''}${label === v.title ? ' on' : ''}">${h(label)}</a>`).join('')}`).join('')}</nav><main class="wg-main"><h2>${h(v.title)}</h2></main></div>`;
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => go(a.dataset.go, {title: a.dataset.t}); });
      const main = root.querySelector('main');
      const pages = {front: wgFront, ifstatus: wgFront, interfaces: wgInterfaces, routes: wgRoutes, nat: wgNat, policies: wgPolicies, aliases: wgAliases, system: wgSystem,
        terminal: m => { openTerminal(); wgFront(m); }, engine: m => m.insertAdjacentHTML('beforeend', naBox(v.title, NA.engine)), vpn: m => m.insertAdjacentHTML('beforeend', naBox(v.title, NA.vpn))};
      (pages[v.page] || (m => m.insertAdjacentHTML('beforeend', naBox(v.title, NA.later))))(main);
    },
  };
  function wgFront(main) {
    const d = D();
    main.insertAdjacentHTML('beforeend', `<div class="wg-cols"><div class="wg-box"><h3>Device Information</h3><div class="b">Name: ${h(N().name)}<br>Model: ${h(d.model)}<br>Version: Fireware ·
      sous-ensemble Network LABS<br>System Time: ${new Date().toLocaleString('fr-FR')}<br>Uptime: ${running() ? 'en marche' : 'lab arrêté'}</div></div><div class="wg-box"><h3>Top Clients</h3>
      <div class="b">No data</div></div></div><div class="wg-box"><h3>Interfaces</h3>${table('wg-t', ['Interface', 'Name', 'Type', 'IPv4 Address', 'Link'], d.ports.map((p, i) => tr([String(i), h(wgAlias(p.port)),
        h(wgType(p.port)), h(p.address || '—'), p.peer && !p.down ? '<span class="wg-ok">● Up</span>' : '<span class="wg-no">● Down</span>'])))}</div>`);
  }
  function wgInterfaces(main) {
    const d = D();
    if (V().edit !== null && V().edit !== undefined) {
      const p = d.ports[V().edit];
      main.insertAdjacentHTML('beforeend', `<div class="wg-form"><h3>Interface Settings - Interface ${V().edit}</h3>${field('Interface Name (Alias)', input('n', wgAlias(p.port), 'disabled'))}
        ${field('Interface Type', select('t', [wgType(p.port)], wgType(p.port)))}<div class="wg-box"><h3>IPv4</h3><div class="b">${field('IP Address', input('wgIp', p.address, 'placeholder="a.b.c.d/nn"'))}
        </div></div><div class="px-err"></div><div class="wg-bar"><button class="wg-btn pri save">SAVE</button><button class="wg-btn cancel">CANCEL</button></div></div>`);
      main.querySelector('.cancel').onclick = () => go('interfaces');
      main.querySelector('.save').onclick = async () => {
        const ip = val(main, '#wgIp');
        if (ip && !/^\d+\.\d+\.\d+\.\d+\/\d+$/.test(ip)) { main.querySelector('.px-err').textContent = 'IP Address : a.b.c.d/nn'; return; }
        if (await attempt(() => setAddress(p.port, ip), 'Configuration saved.')) go('interfaces');
      };
      return;
    }
    main.insertAdjacentHTML('beforeend', `${table('wg-t', ['Interface', 'Name (Alias)', 'Type', 'IPv4', 'IPv6', 'NIC Config'], d.ports.map((p, i) => tr([String(i), `<a data-e="${i}">${h(wgAlias(p.port))}</a>`,
      h(wgType(p.port)), h(p.address || ''), '', 'Auto Negotiate'])))}<div class="wg-bar"><button class="wg-btn" disabled>EDIT</button></div>`);
    main.querySelectorAll('[data-e]').forEach(a => { a.onclick = () => go('interfaces', {edit: Number(a.dataset.e)}); });
  }
  function wgRoutes(main) {
    main.insertAdjacentHTML('beforeend', `${table('wg-t', ['Route To', 'Gateway', 'Metric', 'Interface'], [...D().connected.map(r => tr([h(r.network), 'direct', '0', h(r.port)])),
      ...D().static.map(r => tr([h(r.network), h(r.gateway), '1', h(r.port)]))])}<p style="color:#777">Network LABS : routes de ce pare-feu dans ◉ Network LABS › Vue Network LABS › Routage.</p>`);
  }
  function wgAliases(main) {
    main.insertAdjacentHTML('beforeend', table('wg-t', ['Alias', 'Description', 'Members'], [['Any', 'Any source or destination', 'Any'], ...[...new Set(ports().map(wgAny))].map(a => [a,
      'All ' + a.slice(4) + ' interfaces', ports().filter(p => wgAny(p) === a).map(wgAlias).join(', ')]), ['Firebox', 'The Firebox itself', '']].map(r => tr(r.map(h)))));
  }
  function wgPolicies(main) {
    const f = fw();
    if (V().edit !== null && V().edit !== undefined) return wgPolicyForm(main, V().edit);
    const label = (port, net) => [port ? wgAny(port) : 'Any', net].filter(Boolean).join(', ');
    main.insertAdjacentHTML('beforeend', `<div class="wg-bar"><button class="wg-btn pri add">ADD POLICY</button><button class="wg-btn up">▲</button><button class="wg-btn down">▼</button>
      <button class="wg-btn del">DELETE</button></div>${table('wg-t', ['Order', 'Action', 'Policy Name', 'Policy Type', 'From', 'To', 'Port', 'PBR', 'Application Control'],
        f.rules.map((r, i) => tr([String(i + 1), r.action === 'accept' ? '<span class="wg-ok">✔</span>' : '<span class="wg-no">✖</span>', `<a data-e="${i}">${h(r.name)}</a>`,
          h(r.protocol && r.protocol !== 'any' ? (r.dport ? `${r.protocol.toUpperCase()}-${r.dport}` : r.protocol.toUpperCase()) : 'Any'), h(label(r.in, r.source)), h(label(r.out, r.destination)),
          h(r.protocol && r.protocol !== 'any' ? `${r.protocol}:${r.dport || 'any'}` : 'any'), '', 'None'], `data-r="${i}"`)), 'No policies')}`);
    let chosen = null;
    main.querySelectorAll('tr[data-r]').forEach(row => { row.onclick = () => { main.querySelectorAll('tr.sel').forEach(r => r.classList.remove('sel')); row.classList.add('sel'); chosen = Number(row.dataset.r); }; });
    main.querySelector('.add').onclick = () => go('policies', {edit: 'new'});
    main.querySelectorAll('[data-e]').forEach(a => { a.onclick = () => go('policies', {edit: Number(a.dataset.e)}); });
    main.querySelector('.del').onclick = () => (chosen === null ? toast('Select a policy.', true) : now(() => dropEntry('rules', chosen, false), 'Policy deleted.'));
    main.querySelector('.up').onclick = () => chosen !== null && now(() => moveEntry('rules', chosen, -1, false));
    main.querySelector('.down').onclick = () => chosen !== null && now(() => moveEntry('rules', chosen, 1, false));
  }
  function wgPolicyForm(main, index) {
    const r = index === 'new' ? {action: 'accept'} : fw().rules[index];
    const aliases = [['', 'Any'], ...ports().map(p => [p, wgAny(p)])];
    main.insertAdjacentHTML('beforeend', `<div class="wg-form">${index === 'new' ? field('Select a policy type', select('wgType', [['any', 'Packet Filter: Any'], ['http', 'Packet Filter: HTTP'],
      ['https', 'Packet Filter: HTTPS'], ['ssh', 'Packet Filter: SSH'], ['dns', 'Packet Filter: DNS'], ['icmp', 'Packet Filter: Ping'], ['custom', 'Custom']], 'any')) : ''}
      ${field('Name', input('wgName', r.name || ''))}${field('Enable', '<span>☑</span>')}<div class="wg-box"><h3>Settings</h3><div class="b">
      ${field('Connections are', select('wgAct', [['accept', 'Allowed'], ['drop', 'Denied']], r.action))}${field('FROM', select('wgFrom', aliases, r.in || '') + ' ' + input('wgSrc', r.source || '', 'placeholder="network (optional)"'))}
      ${field('TO', select('wgTo', aliases, r.out || '') + ' ' + input('wgDst', r.destination || '', 'placeholder="network (optional)"'))}${field('Port', input('wgPort', svc(r) === 'any' ? 'any' : svc(r)),
        'Custom : tcp/8080, udp/53')}</div></div><div class="px-err"></div><div class="wg-bar"><button class="wg-btn pri save">SAVE</button><button class="wg-btn cancel">CANCEL</button></div></div>`);
    const type = main.querySelector('#wgType');
    if (type) type.onchange = () => { main.querySelector('#wgPort').value = type.value === 'custom' ? '' : type.value; if (!val(main, '#wgName')) main.querySelector('#wgName').value = type.value.toUpperCase(); };
    main.querySelector('.cancel').onclick = () => go('policies');
    main.querySelector('.save').onclick = async () => {
      try {
        await saveRule(index === 'new' ? null : index, ruleFrom(index === 'new' ? {} : r, {name: val(main, '#wgName') || `policy-${fw().rules.length + 1}`, action: val(main, '#wgAct'),
          in: val(main, '#wgFrom'), out: val(main, '#wgTo'), source: checkNet(val(main, '#wgSrc'), 'FROM'), destination: checkNet(val(main, '#wgDst'), 'TO'), service: val(main, '#wgPort')}));
        go('policies'); toast('Policy saved.');
      } catch (error) { main.querySelector('.px-err').textContent = error.message; }
    };
  }
  function wgNat(main) {
    const nat = fw().nat || [], dynamic = nat.map((r, i) => [r, i]).filter(([r]) => r.type !== 'dnat'), snat = nat.map((r, i) => [r, i]).filter(([r]) => r.type === 'dnat');
    main.insertAdjacentHTML('beforeend', `<div class="wg-box"><h3>Dynamic NAT</h3>${table('wg-t', ['#', 'From', 'To', 'Source IP', ''], dynamic.map(([r, i], k) => tr([String(k + 1), h(r.source || 'Any'),
      h(r.out ? wgAny(r.out) : 'Any-External'), h(r.type === 'snat' ? r.to : ''), `<a data-x="${i}">REMOVE</a>`])), 'No dynamic NAT')}<div class="wg-bar"><button class="wg-btn add-dyn">ADD</button></div></div>
      <div class="wg-box"><h3>SNAT (static NAT)</h3>${table('wg-t', ['Name', 'Type', 'SNAT Members', ''], snat.map(([r, i]) => tr([h(r.name), 'Static NAT', h(`${r.destination} → ${r.to}${r.to_port ? ':' + r.to_port : ''}`),
        `<a data-x="${i}">REMOVE</a>`])), 'No SNAT actions')}<div class="wg-bar"><button class="wg-btn add-snat">ADD</button></div></div>`);
    main.querySelector('.add-dyn').onclick = () => {
      const x = natPieces({type: 'masquerade'}, {source: 'From', out: 'To (interface)', name: 'Name', types: [['masquerade', 'Interface IP']]}, wgAny);
      dialog('fireware', 'Add Dynamic NAT', x.source + x.out + x.name + '<input type="hidden" id="nxType" value="masquerade">', [['OK', '', async b => { await putEntry('nat', null, natRead(b), false); render(); }], ['Cancel']]);
    };
    main.querySelector('.add-snat').onclick = () => {
      const x = natPieces({type: 'dnat'}, {name: 'Name', in: 'Interface', destination: 'External IP', to: 'Internal IP', service: 'Port (protocol/port)', to_port: 'Set internal port',
        types: [['dnat', 'Static NAT']]}, wgAlias);
      dialog('fireware', 'Add SNAT Member', x.name + x.in + x.destination + x.to + x.service + x.to_port + '<input type="hidden" id="nxType" value="dnat">',
        [['OK', '', async b => { await putEntry('nat', null, natRead(b), false); render(); }], ['Cancel']]);
    };
    main.querySelectorAll('[data-x]').forEach(a => { a.onclick = () => now(() => dropEntry('nat', Number(a.dataset.x), false), 'Removed.'); });
  }
  function wgSystem(main) {
    main.insertAdjacentHTML('beforeend', `<div class="wg-form">${field('Device Name', input('wgHost', N().name))}${field('Location', input('l', '', 'disabled'))}${field('Contact Person', input('c', '', 'disabled'))}
      <div class="wg-bar"><button class="wg-btn pri save">SAVE</button></div></div>`);
    main.querySelector('.save').onclick = () => attempt(() => rename(val(main, '#wgHost')), 'Configuration saved.');
  }

  /* =============================== Huawei web (AR routers, S switches) =============================== */
  skinCss(`
  .px-app.huawei{min-height:100vh;background:#f0f2f5;color:#333;font:12px 'Microsoft YaHei',Arial,sans-serif;display:grid;grid-template-rows:56px 1fr}
  .hw-top{display:flex;align-items:stretch;background:#2b3b4e;color:#fff}.hw-top .brand{display:flex;align-items:center;padding:0 20px;font-size:16px}
  .hw-top a{display:flex;align-items:center;padding:0 22px;cursor:pointer;color:#cbd6e2;font-size:14px}.hw-top a.on{background:#1f2c3b;color:#fff;border-bottom:3px solid #c7000b}
  .hw-top .grow{flex:1}.hw-top span{display:flex;align-items:center;padding:0 14px;color:#cbd6e2}
  .hw-body{display:grid;grid-template-columns:210px 1fr;min-height:0}.hw-tree{background:#fff;border-right:1px solid #dcdfe6;padding:8px 0}
  .hw-tree b{display:block;padding:9px 14px 4px;color:#555}.hw-tree a{display:block;padding:6px 14px 6px 28px;cursor:pointer}.hw-tree a.on{background:#e8f1fb;color:#0067b8;font-weight:bold}
  .hw-tree a.na{color:#a5a5a5}.hw-main{padding:14px 18px;overflow:auto}
  .hw-panel{background:#fff;border:1px solid #dcdfe6;margin-bottom:12px}.hw-panel h3{margin:0;padding:9px 12px;font-size:13px;border-bottom:1px solid #ebeef5;border-left:3px solid #0067b8}
  .hw-panel .b{padding:10px 12px}.hw-bar{display:flex;gap:8px;padding:8px 12px}.hw-btn{border:1px solid #0067b8;background:#fff;color:#0067b8;padding:4px 14px;cursor:pointer;border-radius:2px}
  .hw-btn.pri{background:#0067b8;color:#fff}.hw-t{width:100%;border-collapse:collapse}.hw-t th{background:#f5f7fa;text-align:left;padding:7px 10px;border-bottom:1px solid #ebeef5;white-space:nowrap}
  .hw-t td{padding:7px 10px;border-bottom:1px solid #ebeef5;white-space:nowrap}.hw-t a{color:#0067b8;cursor:pointer;margin-right:10px}.hw-up{color:#2e7d32}.hw-dn{color:#c62828}
  .hw-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.hw-kv{display:grid;grid-template-columns:140px 1fr;gap:6px}.hw-kv span{color:#777}
  .hw-ports{display:flex;gap:4px;flex-wrap:wrap;background:#3b4a5c;padding:10px}.hw-ports i{width:26px;height:20px;background:#22303e;border:2px solid #61707f;font-style:normal;color:#ccc;font-size:9px;display:grid;place-items:center}
  .hw-ports i.up{border-color:#46b14a}.hw-ports i.down{border-color:#d9363e}.hw-ports i.spare{opacity:.35}
  .hw-cfg{background:#fff;font:12px Consolas,monospace;white-space:pre;padding:10px;border:1px solid #dcdfe6;max-height:60vh;overflow:auto}
  .px-shade.huawei .px-dtitle{background:#2b3b4e;color:#fff}.px-shade.huawei .px-dfoot button{border:1px solid #0067b8;background:#fff;color:#0067b8;padding:4px 14px;cursor:pointer}
  .px-shade.huawei .px-dfoot button.pri{background:#0067b8;color:#fff}
  `);
  const HW_TABS = role => ({Home: [['Home', [['Device Information', 'home']]]], Monitoring: [['Monitoring', [['Interface', 'mon-if'], ['Routing Table', 'mon-route']]]],
    Configuration: role === 'switch' ? [['Interface Management', [['Ethernet Interface', 'ports'], ['VLAN', 'vlans'], ['VLANIF', 'na']]], ['Security', [['ACL', 'na']]], ['System', [['Device Name', 'sys']]]]
      : [['Interface Management', [['Physical Interface', 'ifs']]], ['IP Service', [['DHCP', 'dhcp']]], ['Route Configuration', [['Static Route', 'routes']]], ['Security', [['ACL', 'na'], ['NAT', 'na']]],
        ['System', [['Device Name', 'sys']]]],
    Maintenance: [['Maintenance', [['Configuration File', 'config'], ['Reboot', 'na']]]]});
  const hwName = name => name.replace(/^GE/i, 'GigabitEthernet');
  SKINS.huawei = {
    start: {tab: 'Home', page: 'home', title: 'Device Information'},
    draw(root) {
      const v = V(), tabs = HW_TABS(N().role);
      root.innerHTML = `<div class="hw-top"><span class="brand">Web Management · ${h(D().model)}</span>${Object.keys(tabs).map(t => `<a data-tab="${t}" class="${t === v.tab ? 'on' : ''}">${t}</a>`).join('')}
        <span class="grow"></span><span>${h(N().name)} · VRP sous-ensemble Network LABS</span><span>admin</span></div><div class="hw-body"><nav class="hw-tree">${tabs[v.tab].map(([g, items]) =>
          `<b>${h(g)}</b>${items.map(([label, page]) => `<a data-go="${page}" data-t="${h(label)}" class="${page === 'na' ? 'na' : ''}${label === v.title ? ' on' : ''}">${h(label)}</a>`).join('')}`).join('')}</nav>
        <main class="hw-main"></main></div>`;
      root.querySelectorAll('[data-tab]').forEach(a => { a.onclick = () => { const [, items] = tabs[a.dataset.tab][0]; go(items[0][1], {tab: a.dataset.tab, title: items[0][0]}); }; });
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => go(a.dataset.go, {title: a.dataset.t}); });
      const main = root.querySelector('main');
      const pages = {home: hwHome, 'mon-if': hwMonIf, 'mon-route': hwRouteTable, ifs: hwIfs, routes: hwRoutes, dhcp: hwDhcp, ports: hwPorts, vlans: hwVlans, sys: hwSys, config: hwConfig};
      (pages[v.page] || (m => { m.innerHTML = naBox(v.title, NA.later); }))(main);
    },
  };
  const hwPanel = (title, body, bar = '') => `<div class="hw-panel"><h3>${h(title)}</h3>${bar ? `<div class="hw-bar">${bar}</div>` : ''}<div class="b">${body}</div></div>`;
  function hwHome(main) {
    const d = D();
    main.innerHTML = hwPanel('Device Panel', faceplate('hw-ports', p => p.name.split('/').pop())) + `<div class="hw-grid">${hwPanel('Device Information', `<div class="hw-kv"><span>Device name</span><b>${h(N().name)}</b>
      <span>Device model</span><b>${h(d.model)}</b><span>Software version</span><b>VRP (sous-ensemble Network LABS)</b><span>Uptime</span><b>${running() ? 'en marche' : 'lab arrêté'}</b></div>`)}
      ${hwPanel('Resource Usage', `<div class="hw-kv"><span>CPU usage</span><b>${running() ? '3%' : '—'}</b><span>Memory usage</span><b>${running() ? '37%' : '—'}</b></div>`)}</div>`;
  }
  function hwMonIf(main) {
    main.innerHTML = hwPanel('Interface', table('hw-t', ['Interface', 'Physical Status', 'Protocol Status', 'IP Address', 'Link Type / VLAN'], D().ports.map(p => tr([h(hwName(p.name)),
      p.peer && !p.down ? '<span class="hw-up">Up</span>' : '<span class="hw-dn">Down</span>', p.peer && !p.down ? 'Up' : 'Down', h(p.address || '—'), h(p.detail)]))));
  }
  function hwRouteTable(main) {
    main.innerHTML = hwPanel('Routing Table', table('hw-t', ['Destination/Mask', 'Proto', 'Pre', 'NextHop', 'Interface'], [...D().connected.map(r => tr([h(r.network), 'Direct', '0', '—', h(hwName(r.port))])),
      ...D().static.map(r => tr([h(r.network), 'Static', '60', h(r.gateway), h(hwName(r.port))]))]));
  }
  function hwIfs(main) {
    const d = D();
    main.innerHTML = hwPanel('Physical Interface', table('hw-t', ['Interface Name', 'IP Address/Mask', 'Status', 'Description', 'Operation'], d.ports.map((p, i) => tr([h(hwName(p.name)),
      h(p.address ? `${ipOf(p.address)}/${maskOf(lenOf(p.address))}` : '—'), p.down ? '<span class="hw-dn">Down</span>' : p.peer ? '<span class="hw-up">Up</span>' : 'Down',
      h(p.peer ? 'To ' + p.peer : ''), `<a data-e="${i}">Modify</a>`]))));
    main.querySelectorAll('[data-e]').forEach(a => { a.onclick = () => {
      const p = d.ports[Number(a.dataset.e)];
      dialog('huawei', 'Modify Interface', `${field('Interface name', `<b>${h(hwName(p.name))}</b>`)}${field('IP address', input('hwIp', ipOf(p.address)))}${field('Mask', input('hwMask', p.address ? maskOf(lenOf(p.address)) : '255.255.255.0'))}
        ${field('Status', select('hwSt', [['up', 'Up'], ['down', 'Shutdown']], p.down ? 'down' : 'up'))}`, [['OK', 'pri', async b => {
        const ip = val(b, '#hwIp');
        if (ip && (!validIp(ip) || prefixOf(val(b, '#hwMask')) === null)) throw new Error('IP address / Mask invalide.');
        const text = [`interface ${hwName(p.name)}`, ip ? ` ip address ${ip} ${val(b, '#hwMask')}` : ' undo ip address', val(b, '#hwSt') === 'down' ? ' shutdown' : ' undo shutdown'].join('\n');
        await cli(text); render(); toast('Applied:\n' + text);
      }], ['Cancel']]);
    }; });
  }
  function hwRoutes(main) {
    const list = D().static;
    main.innerHTML = hwPanel('Static Route', table('hw-t', ['Destination Address', 'Mask', 'Next Hop', 'Preference', 'Operation'], list.map((r, i) => tr([h(ipOf(r.network)), h(maskOf(lenOf(r.network))),
      h(r.gateway), '60', `<a data-x="${i}">Delete</a>`])), 'No data'), '<button class="hw-btn pri add">Create</button>');
    main.querySelector('.add').onclick = () => dialog('huawei', 'Create Static Route', `${field('Destination address', input('hwD', '', 'placeholder="0.0.0.0"'))}${field('Mask', input('hwM', '', 'placeholder="0.0.0.0"'))}
      ${field('Next hop', input('hwN'))}${field('Preference', input('p', '60'))}`, [['OK', 'pri', async b => {
      if (!validIp(val(b, '#hwD')) || prefixOf(val(b, '#hwM')) === null || !validIp(val(b, '#hwN'))) throw new Error('Destination, Mask et Next hop : a.b.c.d');
      const text = `ip route-static ${val(b, '#hwD')} ${val(b, '#hwM')} ${val(b, '#hwN')}`;
      await cli(text); render(); toast('Applied:\n' + text);
    }], ['Cancel']]);
    main.querySelectorAll('[data-x]').forEach(a => { a.onclick = () => { const r = list[Number(a.dataset.x)];
      now(() => cli(`undo ip route-static ${ipOf(r.network)} ${maskOf(lenOf(r.network))} ${r.gateway}`), 'Static route deleted.'); }; });
  }
  function hwDhcp(main) {
    const s = dhcpServer();
    main.innerHTML = hwPanel('DHCP Server (interface address pool)', table('hw-t', ['Interface', 'Address Range', 'Gateway', 'DNS', 'Lease', 'Operation'], s ? [tr([h(hwName(portName(s.interface))),
      h(`${s.start} - ${s.end}`), h(s.router || ''), h((s.dns || []).join(', ')), h(lease(s.lease_seconds || 86400)), '<a class="x">Delete</a>'])] : [], 'No data'),
    `<button class="hw-btn pri add">${s ? 'Modify' : 'Create'}</button>`);
    main.querySelector('.add').onclick = () => {
      const options = D().ports.filter(p => p.address).map(p => [p.port, hwName(p.name)]);
      dialog('huawei', 'DHCP Server', `${field('Interface', select('hwIf', options, s ? s.interface : options[0]?.[0]))}${field('Start IP address', input('hwS', s ? s.start : ''))}
        ${field('End IP address', input('hwE', s ? s.end : ''))}${field('Gateway', input('hwR', s ? s.router : ''))}${field('DNS server', input('hwDn', s ? (s.dns || []).join(' ') : ''))}
        ${field('Lease (seconds)', input('hwL', s ? s.lease_seconds : 86400))}`, [['OK', 'pri', async b => {
        await section('dhcpserver', {dhcp_server: dhcpFrom(b, {iface: '#hwIf', start: '#hwS', end: '#hwE', router: '#hwR', dns: '#hwDn', lease: '#hwL'})}); render(); }], ['Cancel']]);
    };
    const x = main.querySelector('.x');
    if (x) x.onclick = () => now(() => section('dhcpserver', {dhcp_server: null}), 'Deleted.');
  }
  function hwPorts(main) {
    const d = D();
    main.innerHTML = hwPanel('Ethernet Interface', table('hw-t', ['Interface', 'Link Type', 'PVID', 'Allowed VLANs', 'Status', 'Operation'], d.ports.map((p, i) => { const pol = policy(p.port);
      return tr([h(hwName(p.name)), pol.mode === 'trunk' ? 'trunk' : 'access', String(pvid(p.port)), h(pol.mode === 'trunk' ? (pol.allowed === 'all' ? 'all' : pol.allowed.join(',')) : ''),
        p.down ? '<span class="hw-dn">Down</span>' : p.peer ? '<span class="hw-up">Up</span>' : 'Down', `<a data-e="${i}">Modify</a>`]); })));
    main.querySelectorAll('[data-e]').forEach(a => { a.onclick = () => {
      const p = d.ports[Number(a.dataset.e)], pol = policy(p.port);
      dialog('huawei', 'Modify Interface', `${field('Interface', `<b>${h(hwName(p.name))}</b>`)}${field('Link type', select('hwLt', [['access', 'access'], ['trunk', 'trunk']], pol.mode))}
        ${field('PVID (access)', select('hwPv', vlans(), pvid(p.port)))}${field('Allowed VLANs (trunk)', input('hwAl', pol.mode === 'trunk' ? (pol.allowed === 'all' ? 'all' : pol.allowed.join(' ')) : 'all'))}`,
      [['OK', 'pri', async b => {
        const trunk = val(b, '#hwLt') === 'trunk';
        const text = [`interface ${hwName(p.name)}`, ` port link-type ${trunk ? 'trunk' : 'access'}`,
          trunk ? ` port trunk allow-pass vlan ${val(b, '#hwAl').trim().toLowerCase() === 'all' ? 'all' : val(b, '#hwAl').replace(/,/g, ' ')}` : ` port default vlan ${val(b, '#hwPv')}`].join('\n');
        await cli(text); render(); toast('Applied:\n' + text);
      }], ['Cancel']]);
    }; });
  }
  function hwVlans(main) {
    const d = D();
    main.innerHTML = hwPanel('VLAN', table('hw-t', ['VLAN ID', 'Description', 'Untagged Ports', 'Tagged Ports', 'Operation'], vlans().map(v => tr([String(v), v === 1 ? 'default' : `VLAN ${String(v).padStart(4, '0')}`,
      h(d.ports.filter(p => member(p.port, v) === 'U').map(p => hwName(p.name)).join(', ')), h(d.ports.filter(p => member(p.port, v) === 'T').map(p => hwName(p.name)).join(', ')),
      v === 1 ? '' : `<a data-x="${v}">Delete</a>`]))), '<button class="hw-btn pri add">Create</button>');
    main.querySelector('.add').onclick = () => dialog('huawei', 'Create VLAN', field('VLAN ID', input('hwV', '', 'placeholder="2-4094, ex. 10 20"')), [['OK', 'pri', async b => {
      const ids = val(b, '#hwV').split(/[ ,]+/).filter(Boolean);
      if (!ids.length || ids.some(x => !(Number(x) >= 2 && Number(x) <= 4094))) throw new Error('VLAN ID : 2-4094');
      await cli(`vlan batch ${ids.join(' ')}`); render(); toast(`vlan batch ${ids.join(' ')}`);
    }], ['Cancel']]);
    main.querySelectorAll('[data-x]').forEach(a => { a.onclick = () => now(() => cli(`undo vlan ${a.dataset.x}`), `undo vlan ${a.dataset.x}`); });
  }
  function hwSys(main) {
    main.innerHTML = hwPanel('Device Name', `${field('Device name', input('hwHost', N().name))}<button class="hw-btn pri apply">Apply</button>`);
    main.querySelector('.apply').onclick = () => attempt(() => rename(val(main, '#hwHost')), 'sysname ' + val(main, '#hwHost'));
  }
  function hwConfig(main) {
    main.innerHTML = hwPanel('Current Configuration', `<div class="hw-cfg">${h(state.config_text || '')}</div>`);
  }

  /* =============================== Ubiquiti EdgeOS (EdgeRouter) =============================== */
  skinCss(`
  .px-app.edgeos{min-height:100vh;background:#f2f2f2;color:#333;font:13px 'Helvetica Neue',Arial,sans-serif;display:grid;grid-template-rows:46px 1fr}
  .eo-top{display:flex;align-items:stretch;background:#262626;color:#ddd}.eo-top .brand{display:flex;align-items:center;padding:0 16px;color:#fff;font-weight:bold}
  .eo-top a{display:flex;align-items:center;padding:0 16px;cursor:pointer}.eo-top a.on{background:#3d3d3d;color:#fff;border-bottom:3px solid #2a8bd8}.eo-top a.na{color:#888}
  .eo-top .grow{flex:1}.eo-main{padding:14px 18px}.eo-sub{display:flex;gap:4px;margin-bottom:10px}.eo-sub a{padding:6px 12px;background:#e2e2e2;cursor:pointer}.eo-sub a.on{background:#2a8bd8;color:#fff}
  .eo-sub a.na{color:#999}.eo-t{width:100%;border-collapse:collapse;background:#fff}.eo-t th{background:#4a4a4a;color:#fff;text-align:left;padding:7px 9px;font-weight:normal;white-space:nowrap}
  .eo-t td{padding:7px 9px;border-bottom:1px solid #e6e6e6;white-space:nowrap}.eo-up{color:#4caf50}.eo-dn{color:#e53935}
  .eo-btn{border:0;background:#2a8bd8;color:#fff;padding:6px 12px;border-radius:2px;cursor:pointer}.eo-btn.sec{background:#888}.eo-bar{display:flex;gap:8px;margin:8px 0}
  .eo-act{position:relative}.eo-act select{font:inherit}
  .px-shade.edgeos .px-dtitle{background:#262626;color:#fff}.px-shade.edgeos .px-dfoot button{border:0;background:#888;color:#fff;padding:6px 14px;cursor:pointer}
  .px-shade.edgeos .px-dfoot button.pri{background:#2a8bd8}
  `);
  SKINS.edgeos = {
    start: {page: 'dashboard'},
    draw(root) {
      const v = V();
      root.innerHTML = `<div class="eo-top"><span class="brand">${h(D().model)}</span>${[['Dashboard', 'dashboard'], ['Routing', 'routing'], ['Firewall/NAT', 'firewall'], ['Services', 'services'],
        ['Users', 'na'], ['QoS', 'na'], ['Wizards', 'na']].map(([label, page]) => `<a data-go="${page}" class="${page === v.page ? 'on' : ''}${page === 'na' ? ' na' : ''}">${label}</a>`).join('')}
        <span class="grow"></span><a data-go="na">Toolbox</a><a data-go="cli">CLI</a><a data-go="na">Alerts</a><a data-go="system" class="${v.page === 'system' ? 'on' : ''}">System</a></div><main class="eo-main"></main>`;
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { if (a.dataset.go === 'cli') return openTerminal(); if (a.dataset.go !== 'na') go(a.dataset.go); }; });
      const main = root.querySelector('main');
      ({dashboard: eoDashboard, routing: eoRouting, firewall: eoFirewall, services: eoServices, system: eoSystem}[v.page] || eoDashboard)(main);
    },
  };
  function eoDashboard(main) {
    const d = D();
    main.innerHTML = `<table class="eo-t"><thead><tr><th>Name</th><th>Type</th><th>IP Addresses</th><th>MAC</th><th>MTU</th><th>TX</th><th>RX</th><th>Status</th><th>Actions</th></tr></thead><tbody>${d.ports.map((p, i) =>
      `<tr><td>${h(p.name)}</td><td>ethernet</td><td>${h(p.address || '')}</td><td>—</td><td>1500</td><td>0</td><td>0</td><td>${p.peer && !p.down ? '<span class="eo-up">● Connected</span>' : '<span class="eo-dn">● Disconnected</span>'}</td>
      <td><button class="eo-btn" data-e="${i}">Actions ▾</button></td></tr>`).join('')}</tbody></table>
      <p style="color:#777;margin-top:10px">${h(N().name)} · EdgeOS (sous-ensemble Network LABS) · ${running() ? 'en marche' : 'lab arrêté'}</p>`;
    main.querySelectorAll('[data-e]').forEach(b => { b.onclick = () => {
      const p = d.ports[Number(b.dataset.e)];
      dialog('edgeos', `Config: ${p.name}`, `${field('Description', input('d', p.peer ? 'to ' + p.peer : ''))}${field('Address', `<span><label><input type="radio" name="eoMode" value="manual" ${p.address ? 'checked' : ''}> Manually define IP address</label>
        <label><input type="radio" name="eoMode" value="none" ${p.address ? '' : 'checked'}> No address</label></span>`)}${field('IP address', input('eoIp', p.address, 'placeholder="a.b.c.d/nn"'))}
        ${field('MTU', input('m', '1500', 'disabled'))}${field('Enable', `<span>${p.down ? '☐' : '☑'}</span>`)}`,
      [['Save', 'pri', async box => {
        const manual = box.querySelector('input[name=eoMode]:checked').value === 'manual', ip = val(box, '#eoIp');
        if (manual && !/^\d+\.\d+\.\d+\.\d+\/\d+$/.test(ip)) throw new Error('IP address : a.b.c.d/nn');
        await setAddress(p.port, manual ? ip : '');
        render(); toast(`${p.name} saved.`);
      }], ['Cancel']]);
    }; });
  }
  function eoRouting(main) {
    main.innerHTML = `<div class="eo-sub"><a class="on">Routes</a><a class="na">OSPF</a><a class="na">RIP</a><a class="na">BGP</a></div><div class="eo-bar"><button class="eo-btn add">+ Add Static Route</button></div>
      <table class="eo-t"><thead><tr><th>Type</th><th>Destination</th><th>Next Hop</th><th>Interface</th><th>Distance</th><th>Selected</th></tr></thead><tbody>${[...D().connected.map(r => `<tr><td>connected</td>
      <td>${h(r.network)}</td><td>—</td><td>${h(r.port)}</td><td>0</td><td>✔</td></tr>`), ...D().static.map(r => `<tr><td>static</td><td>${h(r.network)}</td><td>${h(r.gateway)}</td><td>${h(r.port)}</td>
      <td>1</td><td>✔</td></tr>`)].join('')}</tbody></table>`;
    main.querySelector('.add').onclick = () => toast('EdgeOS : les routes statiques se configurent dans le terminal (configure · set protocols static route …).', true);
  }
  function eoFirewall(main) {
    main.innerHTML = `<div class="eo-sub"><a class="on">Port Forwarding</a><a class="na">Firewall Policies</a><a class="na">NAT</a><a class="na">Firewall/NAT Groups</a></div>
      <table class="eo-t"><thead><tr><th>Original port</th><th>Protocol</th><th>Forward-to address</th><th>Forward-to port</th><th>Description</th></tr></thead><tbody>
      <tr class="px-none"><td colspan="5">Ce routeur du laboratoire ne fait ni filtrage ni NAT : utiliser un pare-feu.</td></tr></tbody></table>`;
  }
  function eoServices(main) {
    const s = dhcpServer();
    main.innerHTML = `<div class="eo-sub"><a class="on">DHCP Server</a><a class="na">DNS</a><a class="na">PPPoE</a></div><div class="eo-bar"><button class="eo-btn add">+ Add DHCP Server</button>${s
      ? '<button class="eo-btn sec del">Delete</button>' : ''}</div><table class="eo-t"><thead><tr><th>DHCP Name</th><th>Subnet</th><th>Pool Size</th><th>Leased</th><th>Available</th><th>Static</th></tr></thead>
      <tbody>${s ? `<tr><td>LAN</td><td>${h(networkOf(N().interfaces[s.interface]))}</td><td>${ipNum(s.end) - ipNum(s.start) + 1}</td><td>0</td><td>${ipNum(s.end) - ipNum(s.start) + 1}</td><td>0</td></tr>`
        : '<tr class="px-none"><td colspan="6">No DHCP servers</td></tr>'}</tbody></table>`;
    main.querySelector('.add').onclick = () => {
      const options = D().ports.filter(p => p.address).map(p => [p.port, `${p.name} (${networkOf(p.address)})`]);
      dialog('edgeos', 'Create DHCP Server', `${field('DHCP Name', input('n', 'LAN', 'disabled'))}${field('Subnet', select('eoIf', options, s ? s.interface : options[0]?.[0]))}
        ${field('Range Start', input('eoS', s ? s.start : ''))}${field('Range Stop', input('eoE', s ? s.end : ''))}${field('Router', input('eoR', s ? s.router : ''))}
        ${field('DNS 1', input('eoD', s ? (s.dns || [])[0] || '' : ''))}${field('Enable', '<span>☑</span>')}`, [['Save', 'pri', async b => {
        await section('dhcpserver', {dhcp_server: dhcpFrom(b, {iface: '#eoIf', start: '#eoS', end: '#eoE', router: '#eoR', dns: '#eoD', lease: '#none'})}); render(); }], ['Cancel']]);
    };
    const del = main.querySelector('.del');
    if (del) del.onclick = () => now(() => section('dhcpserver', {dhcp_server: null}), 'DHCP server deleted.');
  }
  const ipNum = ip => ip.split('.').reduce((a, b) => a * 256 + Number(b), 0);
  function eoSystem(main) {
    main.innerHTML = `<div style="max-width:620px;background:#fff;padding:14px;border:1px solid #ddd"><h3 style="margin-top:0">System</h3>${field('Host Name', input('eoHost', N().name))}
      ${field('Time Zone', select('tz', ['Europe/Paris'], 'Europe/Paris'))}<div class="eo-bar"><button class="eo-btn save">Save</button></div></div>`;
    main.querySelector('.save').onclick = () => attempt(() => rename(val(main, '#eoHost')), 'Saved.');
  }

  /* =============================== UniFi Network (UniFi switches) =============================== */
  skinCss(`
  .px-app.unifi{min-height:100vh;background:#f6f6f8;color:#212327;font:13px 'Lato','Helvetica Neue',Arial,sans-serif;display:grid;grid-template-columns:60px 1fr}
  .uf-rail{background:#fff;border-right:1px solid #e3e5e8;display:flex;flex-direction:column;align-items:center;gap:6px;padding-top:12px}
  .uf-rail a{width:40px;height:40px;border-radius:8px;display:grid;place-items:center;font-size:18px;color:#808893;cursor:pointer}.uf-rail a.on{background:#e6f0ff;color:#006fff}
  .uf-top{height:52px;display:flex;align-items:center;gap:12px;padding:0 20px;background:#fff;border-bottom:1px solid #e3e5e8}.uf-top b{font-size:16px}.uf-top .grow{flex:1}
  .uf-main{padding:18px 22px;position:relative}.uf-t{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden}
  .uf-t th{text-align:left;padding:10px 12px;color:#808893;font-weight:normal;border-bottom:1px solid #eceef1}.uf-t td{padding:11px 12px;border-bottom:1px solid #f1f2f4}
  .uf-t tr.click{cursor:pointer}.uf-t tr.click:hover td{background:#f4f8ff}.uf-on{color:#2ea043}.uf-off{color:#a3a9b2}
  .uf-panel{position:fixed;top:0;right:0;bottom:0;width:420px;background:#fff;box-shadow:-8px 0 24px rgba(0,0,0,.12);z-index:15;display:flex;flex-direction:column}
  .uf-head{padding:16px 18px;border-bottom:1px solid #eceef1}.uf-head b{display:block;font-size:16px}.uf-tabs{display:flex;gap:16px;padding:0 18px;border-bottom:1px solid #eceef1}
  .uf-tabs a{padding:10px 0;cursor:pointer;color:#808893}.uf-tabs a.on{color:#006fff;border-bottom:2px solid #006fff}.uf-panel .body{padding:16px 18px;overflow:auto;flex:1}
  .uf-ports{display:grid;grid-template-columns:repeat(8,1fr);gap:6px;margin-bottom:14px}.uf-ports i{height:34px;border-radius:5px;background:#e9ebee;display:grid;place-items:center;font-style:normal;cursor:pointer;font-size:12px}
  .uf-ports i.up{background:#d9f2df;color:#1d7a33}.uf-ports i.sel{outline:2px solid #006fff}.uf-btn{border:0;background:#006fff;color:#fff;padding:8px 16px;border-radius:6px;cursor:pointer}
  .uf-btn.sec{background:#eceef1;color:#212327}
  `);
  SKINS.unifi = {
    start: {page: 'devices', open: null, tab: 'Ports', port: 0},
    draw(root) {
      const v = V();
      root.innerHTML = `<nav class="uf-rail">${[['◎', 'dashboard'], ['▦', 'devices'], ['☺', 'clients'], ['⌗', 'topology'], ['▤', 'stats'], ['⚙', 'networks']].map(([icon, page]) =>
        `<a data-go="${page}" class="${page === v.page ? 'on' : ''}" title="${page}">${icon}</a>`).join('')}</nav><div><div class="uf-top"><b>Network</b><span>Default</span><span class="grow"></span>
        <span>${h(N().name)} · sous-ensemble Network LABS</span></div><main class="uf-main"></main></div>`;
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => go(a.dataset.go); });
      const main = root.querySelector('main');
      ({devices: ufDevices, networks: ufNetworks}[v.page] || (m => { m.innerHTML = naBox(v.page, 'La console UniFi gère tout un site ; ici, ce switch du laboratoire (UniFi Devices, Networks).'); }))(main);
    },
  };
  function ufDevices(main) {
    const d = D(), v = V(), up = d.ports.filter(p => p.peer && !p.down).length;
    main.innerHTML = `<h2 style="margin:0 0 12px;font-weight:normal">UniFi Devices</h2><table class="uf-t"><thead><tr><th>Name</th><th>Model</th><th>Status</th><th>Ports</th><th>Uplink</th><th>Experience</th></tr></thead>
      <tbody><tr class="click"><td><b>${h(N().name)}</b></td><td>${h(d.model.replace('UniFi ', ''))}</td><td class="${running() ? 'uf-on' : 'uf-off'}">${running() ? '● Online' : '○ Offline'}</td>
      <td>${up} / ${d.ports.length}</td><td>${h((d.ports.find(p => p.peer) || {}).peer || '—')}</td><td>${running() ? 'Excellent' : '—'}</td></tr></tbody></table>`;
    main.querySelector('tr.click').onclick = () => { v.open = true; render(); };
    if (!v.open) return;
    const p = d.ports[v.port] || d.ports[0];
    const panel = document.createElement('div');
    panel.className = 'uf-panel';
    const nets = vlans().map(x => [x, x === 1 ? 'Default (1)' : `VLAN ${x} (${x})`]), pol = policy(p.port);
    panel.innerHTML = `<div class="uf-head"><b>${h(N().name)}</b>${h(d.model)}</div><div class="uf-tabs">${['Overview', 'Ports', 'Settings'].map(t => `<a data-t="${t}" class="${t === v.tab ? 'on' : ''}">${t}</a>`).join('')}</div>
      <div class="body">${v.tab === 'Overview' ? `<p>Model : ${h(d.model)}<br>Firmware : Network LABS<br>Uptime : ${running() ? 'en marche' : '—'}<br>Ports used : ${up} / ${d.ports.length}</p>`
        : v.tab === 'Settings' ? `${field('Device Name', input('ufName', N().name))}<button class="uf-btn save-name">Apply Changes</button>`
        : `<div class="uf-ports">${d.ports.map((x, i) => `<i data-p="${i}" class="${portLink(x) === 'up' ? 'up' : ''}${i === v.port ? ' sel' : ''}">${i + 1}</i>`).join('')}</div>
          <b>Port ${v.port + 1} · ${h(p.name)}</b><p style="color:#808893">${h(p.peer ? 'Connected to ' + p.peer : 'Not connected')}</p>
          ${field('Native VLAN / Network', select('ufNative', nets, pvid(p.port)))}${field('Tagged VLAN Management', select('ufTag', [['none', 'Block All'], ['all', 'Allow All'],
            ['custom', 'Custom']], pol.mode === 'trunk' ? (pol.allowed === 'all' ? 'all' : 'custom') : 'none'))}${field('Tagged VLANs (custom)', input('ufTagged', pol.mode === 'trunk' && pol.allowed !== 'all' ? pol.allowed.join(',') : ''))}
          <div class="px-err"></div><button class="uf-btn apply">Apply Changes</button>`}<p><button class="uf-btn sec close">Close</button></p></div>`;
    main.append(panel);
    panel.querySelectorAll('[data-t]').forEach(a => { a.onclick = () => { v.tab = a.dataset.t; render(); }; });
    panel.querySelectorAll('[data-p]').forEach(i => { i.onclick = () => { v.port = Number(i.dataset.p); render(); }; });
    panel.querySelector('.close').onclick = () => { v.open = null; render(); };
    const name = panel.querySelector('.save-name');
    if (name) name.onclick = () => attempt(() => rename(val(panel, '#ufName')), 'Device name changed.');
    const apply = panel.querySelector('.apply');
    if (apply) apply.onclick = async () => {
      try {
        const tag = val(panel, '#ufTag');
        await (tag === 'none' ? setPortMode(p.port, 'access', val(panel, '#ufNative')) : setPortMode(p.port, 'trunk', null, val(panel, '#ufNative'), tag === 'all' ? 'all' : val(panel, '#ufTagged')));
        render(); toast(`Port ${v.port + 1} : changes applied.`);
      } catch (error) { panel.querySelector('.px-err').textContent = error.message; }
    };
  }
  function ufNetworks(main) {
    main.innerHTML = `<h2 style="margin:0 0 12px;font-weight:normal">Settings · Networks</h2><p><button class="uf-btn add">Create New Network</button></p><table class="uf-t"><thead><tr><th>Name</th><th>VLAN ID</th>
      <th>Ports (native)</th><th></th></tr></thead><tbody>${vlans().map(x => `<tr><td>${x === 1 ? 'Default' : `VLAN ${x}`}</td><td>${x}</td><td>${h(D().ports.filter(p => pvid(p.port) === x).map(p => p.name).join(', '))}</td>
      <td>${x === 1 ? '' : `<a data-x="${x}" style="color:#e5484d;cursor:pointer">Remove</a>`}</td></tr>`).join('')}</tbody></table>`;
    main.querySelector('.add').onclick = () => dialog('unifi', 'Create New Network', `${field('Network Name', input('n', ''))}${field('VLAN ID', input('ufVid', '', 'placeholder="2-4094"'))}`,
      [['Add', 'pri', async b => { const vid = Number(val(b, '#ufVid')); if (!(vid >= 2 && vid <= 4094)) throw new Error('VLAN ID : 2-4094');
        await saveSwitching([...vlans(), vid], clone(N().switchports || {})); render(); toast('Network created.'); }], ['Cancel']]);
    main.querySelectorAll('[data-x]').forEach(a => { a.onclick = () => now(() => dropVlan(Number(a.dataset.x)), 'Network removed.'); });
  }

  /* =============================== TP-Link Easy Smart =============================== */
  skinCss(`
  .px-app.tplink{min-height:100vh;background:#fff;color:#333;font:12px Arial,Helvetica,sans-serif;display:grid;grid-template-rows:70px 1fr}
  .tp-top{display:flex;align-items:center;justify-content:space-between;padding:0 24px;background:linear-gradient(#1b88c4,#0f6aa1);color:#fff}.tp-top b{font-size:20px}.tp-top span{font-size:13px}
  .tp-body{display:grid;grid-template-columns:200px 1fr;min-height:0}.tp-menu{background:#eef4f8;border-right:1px solid #cfdde8}
  .tp-menu b{display:block;padding:9px 14px;background:#d6e6f1;color:#0f6aa1;border-bottom:1px solid #c3d7e6;cursor:pointer}.tp-menu a{display:block;padding:6px 14px 6px 26px;cursor:pointer;color:#333}
  .tp-menu a.on{color:#0f6aa1;font-weight:bold;background:#fff}.tp-menu a.na{color:#9aa}.tp-main{padding:14px 20px;overflow:auto}
  .tp-title{background:#d6e6f1;color:#0f6aa1;font-weight:bold;padding:7px 10px;margin:10px 0 8px;border-left:4px solid #0f6aa1}
  .tp-t{border-collapse:collapse;min-width:520px}.tp-t th{background:#0f6aa1;color:#fff;padding:6px 10px;text-align:center;font-weight:normal;white-space:nowrap}
  .tp-t td{border:1px solid #cfdde8;padding:5px 10px;text-align:center;white-space:nowrap}.tp-t td.l{background:#eef4f8;text-align:right;font-weight:bold}.tp-t tr.sel td{background:#fff6d6}
  .tp-btn{border:1px solid #0f6aa1;background:linear-gradient(#fff,#e6eef4);color:#0f6aa1;padding:4px 16px;cursor:pointer;margin:6px 4px 6px 0}
  .tp-note{color:#666;margin-top:10px}.tp-note b{color:#c00}
  `);
  const TP_MENU = [['System', [['System Info', 'sysinfo'], ['IP Setting', 'ip'], ['User Account', 'na'], ['Backup and Restore', 'na'], ['System Reboot', 'na'], ['System Reset', 'na'], ['Firmware Upgrade', 'na']]],
    ['Switching', [['Port Setting', 'portsetting'], ['IGMP Snooping', 'na'], ['LAG', 'na']]], ['Monitoring', [['Port Statistics', 'stats'], ['Port Mirror', 'na'], ['Cable Test', 'na'], ['Loop Prevention', 'na']]],
    ['VLAN', [['MTU VLAN', 'na'], ['Port Based VLAN', 'na'], ['802.1Q VLAN', 'dot1q'], ['802.1Q PVID Setting', 'pvid']]], ['QoS', [['QoS Basic', 'na'], ['Bandwidth Control', 'na'], ['Storm Control', 'na']]]];
  SKINS.tplink = {
    start: {page: 'sysinfo', title: 'System Info', vid: null},
    draw(root) {
      const v = V();
      root.innerHTML = `<div class="tp-top"><b>Easy Smart Switch</b><span>${h(D().model)} · ${h(N().name)} · Network LABS</span></div><div class="tp-body"><nav class="tp-menu">${TP_MENU.map(([g, items]) =>
        `<b>${g}</b>${items.map(([label, page]) => `<a data-go="${page}" data-t="${h(label)}" class="${page === 'na' ? 'na' : ''}${label === v.title ? ' on' : ''}">${h(label)}</a>`).join('')}`).join('')}</nav>
        <main class="tp-main"></main></div>`;
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => go(a.dataset.go, {title: a.dataset.t}); });
      const main = root.querySelector('main');
      ({sysinfo: tpSys, ip: tpIp, portsetting: tpPorts, stats: tpStats, dot1q: tpDot1q, pvid: tpPvid}[v.page] || (m => { m.innerHTML = naBox(v.title, NA.later); }))(main);
    },
  };
  const tpPortNo = p => `Port ${D().ports.indexOf(p) + 1}`;
  function tpSys(main) {
    main.innerHTML = `<div class="tp-title">System Info</div><table class="tp-t"><tbody><tr><td class="l">Device Description</td><td style="text-align:left">${input('tpName', N().name)}
      <button class="tp-btn apply">Apply</button></td></tr>${[['MAC Address', '—'], ['IP Address', '—'], ['Subnet Mask', '—'], ['Default Gateway', '—'], ['Firmware Version', 'Network LABS'],
        ['Hardware Version', D().model]].map(([k, v]) => `<tr><td class="l">${k}</td><td style="text-align:left">${h(v)}</td></tr>`).join('')}</tbody></table>`;
    main.querySelector('.apply').onclick = () => attempt(() => rename(val(main, '#tpName')), 'Operation successful.');
  }
  function tpIp(main) {
    main.innerHTML = `<div class="tp-title">IP Setting</div><table class="tp-t"><tbody><tr><td class="l">DHCP Setting</td><td>Disable</td></tr><tr><td class="l">IP Address</td><td>—</td></tr></tbody></table>
      <p class="tp-note"><b>Note:</b> le switch du laboratoire n’a pas d’adresse de gestion.</p>`;
  }
  function tpPorts(main) {
    const d = D();
    main.innerHTML = `<div class="tp-title">Port Setting</div><table class="tp-t"><thead><tr><th>Port</th><th>Status</th><th>Speed/Duplex</th><th>Flow Control</th><th></th></tr></thead><tbody><tr>
      <td>${select('tpPort', d.ports.map(p => [p.port, tpPortNo(p)]), d.ports[0].port)}</td><td>${select('tpSt', [['1', 'Enable'], ['0', 'Disable']], '1')}</td><td>${select('sd', ['Auto'], 'Auto')}</td>
      <td>${select('fc', ['Off'], 'Off')}</td><td><button class="tp-btn apply">Apply</button></td></tr></tbody></table>
      <table class="tp-t" style="margin-top:10px"><thead><tr><th>Port</th><th>Status</th><th>Speed/Duplex Config</th><th>Speed/Duplex Actual</th><th>Flow Control Config</th><th>Flow Control Actual</th><th>Trunk</th></tr></thead>
      <tbody>${d.ports.map(p => tr([tpPortNo(p), p.down ? 'Disabled' : 'Enabled', 'Auto', p.peer && !p.down ? '1000M Full' : 'Link Down', 'Off', p.peer && !p.down ? 'Off' : '', '---'])).join('')}</tbody></table>`;
    main.querySelector('.apply').onclick = () => attempt(() => setAddress(val(main, '#tpPort'), '', val(main, '#tpSt') === '1'), 'Operation successful.');
  }
  function tpStats(main) {
    main.innerHTML = `<div class="tp-title">Port Statistics</div><table class="tp-t"><thead><tr><th>Port</th><th>Status</th><th>Link Status</th><th>TxGoodPkt</th><th>TxBadPkt</th><th>RxGoodPkt</th><th>RxBadPkt</th></tr></thead>
      <tbody>${D().ports.map(p => tr([tpPortNo(p), p.down ? 'Disabled' : 'Enabled', p.peer && !p.down ? '1000M Full' : 'Link Down', '0', '0', '0', '0'])).join('')}</tbody></table>`;
  }
  function tpDot1q(main) {
    const d = D(), v = V(), vid = v.vid || 1;
    main.innerHTML = `<div class="tp-title">802.1Q VLAN Setting</div><p>802.1Q VLAN Configuration : (•) Enable ( ) Disable</p><table class="tp-t"><tbody><tr><td class="l">VLAN ID (1-4094)</td>
      <td style="text-align:left">${input('tpVid', vid)}</td></tr><tr><td class="l">VLAN Name</td><td style="text-align:left">${input('tpVn', vid === 1 ? 'Default_VLAN' : `VLAN${vid}`)}</td></tr></tbody></table>
      <table class="tp-t" style="margin-top:8px"><thead><tr><th>Port</th><th>Untagged</th><th>Tagged</th><th>Not Member</th></tr></thead><tbody>${d.ports.map(p => { const m = member(p.port, vid);
        return `<tr><td>${tpPortNo(p)}</td>${['U', 'T', ''].map(c => `<td><input type="radio" name="m-${h(p.port)}" value="${c}" ${m === c ? 'checked' : ''}></td>`).join('')}</tr>`; }).join('')}</tbody></table>
      <button class="tp-btn add">Add/Modify</button><button class="tp-btn del">Delete</button><div class="px-err"></div>
      <table class="tp-t" style="margin-top:10px"><thead><tr><th>VLAN ID</th><th>VLAN Name</th><th>Member Ports</th><th>Tagged Ports</th><th>Untagged Ports</th></tr></thead><tbody>${vlans().map(x => {
        const tagged = d.ports.filter(p => member(p.port, x) === 'T').map(tpPortNo), untagged = d.ports.filter(p => member(p.port, x) === 'U').map(tpPortNo);
        return `<tr data-v="${x}" class="${x === vid ? 'sel' : ''}" style="cursor:pointer"><td>${x}</td><td>${x === 1 ? 'Default_VLAN' : `VLAN${x}`}</td><td>${h([...untagged, ...tagged].join(', '))}</td>
          <td>${h(tagged.join(', '))}</td><td>${h(untagged.join(', '))}</td></tr>`; }).join('')}</tbody></table>
      <p class="tp-note"><b>Note:</b> un port est non étiqueté (Untagged) dans un seul VLAN ; Tagged en fait un trunk 802.1Q.</p>`;
    main.querySelectorAll('tr[data-v]').forEach(row => { row.onclick = () => { v.vid = Number(row.dataset.v); render(); }; });
    followVid(main, '#tpVid', 'm-');
    main.querySelector('.add').onclick = async () => {
      try {
        const id = Number(val(main, '#tpVid'));
        if (!(id >= 1 && id <= 4094)) throw new Error('VLAN ID : 1-4094');
        const members = Object.fromEntries(d.ports.map(p => [p.port, (main.querySelector(`input[name="m-${CSS.escape(p.port)}"]:checked`) || {}).value || '']));
        await setVlanMembers(id, members);
        v.vid = id; render(); toast('Operation successful.');
      } catch (error) { main.querySelector('.px-err').textContent = error.message; }
    };
    main.querySelector('.del').onclick = () => attempt(() => dropVlan(Number(val(main, '#tpVid'))), 'Operation successful.').then(() => { v.vid = 1; });
  }
  function tpPvid(main) {
    const d = D();
    main.innerHTML = `<div class="tp-title">802.1Q PVID Setting</div><table class="tp-t"><tbody><tr><td class="l">Port</td><td>${select('tpP', d.ports.map(p => [p.port, tpPortNo(p)]), d.ports[0].port)}</td>
      <td class="l">PVID</td><td>${select('tpV', vlans(), 1)}</td><td><button class="tp-btn apply">Apply</button></td></tr></tbody></table><div class="px-err"></div>
      <table class="tp-t" style="margin-top:10px"><thead><tr><th>Port</th><th>PVID</th><th>LAG</th></tr></thead><tbody>${d.ports.map(p => tr([tpPortNo(p), String(pvid(p.port)), '---'])).join('')}</tbody></table>`;
    main.querySelector('.apply').onclick = () => attempt(() => setPvid(val(main, '#tpP'), Number(val(main, '#tpV'))), 'Operation successful.');
  }

  /* =============================== NETGEAR (Plus and Smart Managed Pro) =============================== */
  skinCss(`
  .px-app.netgear{min-height:100vh;background:#fff;color:#222;font:12px Arial,Helvetica,sans-serif;display:grid;grid-template-rows:auto 1fr}
  .ng-top{background:#1b2357;color:#fff}.ng-top .head{display:flex;align-items:center;justify-content:space-between;padding:10px 18px}.ng-top .head b{font-size:17px}
  .ng-tabs{display:flex;background:#2d3878}.ng-tabs a{padding:9px 16px;color:#d7dcf3;cursor:pointer;font-weight:bold}.ng-tabs a.on{background:#fff;color:#1b2357}
  .ng-body{display:grid;grid-template-columns:200px 1fr;min-height:0}.ng-menu{background:#eceef4;padding:8px 0}.ng-menu b{display:block;padding:8px 14px 3px;color:#1b2357}
  .ng-menu a{display:block;padding:5px 14px 5px 24px;cursor:pointer}.ng-menu a.on{background:#fff;color:#7b2d8b;font-weight:bold}.ng-menu a.na{color:#9a9ea9}
  .ng-main{padding:12px 18px}.ng-head{display:flex;justify-content:space-between;align-items:center;background:#1b2357;color:#fff;padding:6px 10px;font-weight:bold;margin-bottom:8px}
  .ng-head button{border:0;background:#7b2d8b;color:#fff;padding:5px 14px;cursor:pointer;font-weight:bold;margin-left:4px}.ng-head button.c{background:#5b6290}
  .ng-t{border-collapse:collapse;min-width:520px}.ng-t th{background:#dfe2ee;padding:6px 10px;text-align:left;white-space:nowrap}.ng-t td{padding:5px 10px;border-bottom:1px solid #e6e8ef;white-space:nowrap}
  .ng-cell{display:inline-grid;place-items:center;width:28px;height:24px;border:1px solid #b9bed2;cursor:pointer;font-weight:bold;margin:1px}.ng-cell.U{background:#d7f0db}.ng-cell.T{background:#dfe4fb}
  `);
  const NG_PLUS = {System: [['Management', [['Switch Information', 'info'], ['IP Address', 'ip'], ['Change Password', 'na']]], ['Monitoring', [['Port Statistics', 'stats'], ['Cable Tester', 'na'], ['Mirroring', 'na']]]],
    VLAN: [['Basic', [['Port Based VLAN', 'na']]], ['Advanced', [['VLAN Configuration', 'vlanconf'], ['VLAN Membership', 'membership'], ['Port PVID', 'pvid']]]], QoS: [['QoS', [['Global Config', 'na']]]], Help: [['Help', [['Online Help', 'na']]]]};
  const NG_PRO = {System: NG_PLUS.System, Switching: [['VLAN', [['VLAN Configuration', 'vlanconf'], ['VLAN Membership', 'membership'], ['Port PVID Configuration', 'pvid']]], ['Ports', [['Port Configuration', 'ports']]]],
    Routing: [['IP', [['Routing Table', 'na']]]], QoS: [['CoS', [['Basic', 'na']]]], Security: [['Management Security', [['Local User', 'na']]]], Monitoring: [['Ports', [['Port Statistics', 'stats']]]],
    Maintenance: [['Save Config', [['Save Configuration', 'save']]]], Help: [['Help', [['Online Help', 'na']]]]};
  SKINS.netgear = {
    start: {tab: 'System', page: 'info', title: 'Switch Information', vid: 1},
    draw(root) {
      const v = V(), tabs = /M4300/.test(D().model) ? NG_PRO : NG_PLUS;
      root.innerHTML = `<div class="ng-top"><div class="head"><b>${/M4300/.test(D().model) ? 'Smart Managed Pro Switch' : 'ProSAFE Plus Switch'}</b><span>${h(D().model)} · ${h(N().name)} · Network LABS · LOGOUT</span></div>
        <div class="ng-tabs">${Object.keys(tabs).map(t => `<a data-tab="${t}" class="${t === v.tab ? 'on' : ''}">${t}</a>`).join('')}</div></div><div class="ng-body"><nav class="ng-menu">${tabs[v.tab].map(([g, items]) =>
          `<b>${h(g)}</b>${items.map(([label, page]) => `<a data-go="${page}" data-t="${h(label)}" class="${page === 'na' ? 'na' : ''}${label === v.title ? ' on' : ''}">${h(label)}</a>`).join('')}`).join('')}</nav>
        <main class="ng-main"></main></div>`;
      root.querySelectorAll('[data-tab]').forEach(a => { a.onclick = () => { const [, items] = tabs[a.dataset.tab][0]; go(items[0][1], {tab: a.dataset.tab, title: items[0][0]}); }; });
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => go(a.dataset.go, {title: a.dataset.t}); });
      const main = root.querySelector('main');
      ({info: ngInfo, ip: tpIp, stats: ngStats, vlanconf: ngVlanConf, membership: ngMembership, pvid: ngPvid, ports: ngStats,
        save: m => { m.innerHTML = '<div class="ng-head">Save Configuration</div><p>La configuration du projet est déjà enregistrée.</p>'; }}[v.page] || (m => { m.innerHTML = naBox(v.title, NA.later); }))(main);
    },
  };
  const ngHead = (title, apply = true) => `<div class="ng-head"><span>${h(title)}</span>${apply ? '<span><button class="c cancel">CANCEL</button><button class="apply">APPLY</button></span>' : ''}</div>`;
  const ngPortNo = p => String(D().ports.indexOf(p) + 1);
  function ngInfo(main) {
    main.innerHTML = `${ngHead('Switch Information')}<table class="ng-t"><tbody>${[['Product Name', h(D().model)], ['Switch Name', input('ngName', N().name)], ['Serial Number', '—'], ['MAC Address', '—'],
      ['Firmware Version', 'Network LABS'], ['DHCP Mode', 'Disable'], ['IP Address', '—'], ['Subnet Mask', '—'], ['Gateway Address', '—']].map(([k, v]) => `<tr><th>${k}</th><td>${v}</td></tr>`).join('')}</tbody></table>`;
    main.querySelector('.apply').onclick = () => attempt(() => rename(val(main, '#ngName')), 'Settings applied.');
    main.querySelector('.cancel').onclick = () => render();
  }
  function ngStats(main) {
    main.innerHTML = `${ngHead('Port Statistics', false)}<table class="ng-t"><thead><tr><th>Port</th><th>Link</th><th>Bytes Received</th><th>Bytes Sent</th><th>CRC Error Packets</th></tr></thead>
      <tbody>${D().ports.map(p => tr([ngPortNo(p), p.peer && !p.down ? '1000M' : 'Down', '0', '0', '0'])).join('')}</tbody></table>`;
  }
  function ngVlanConf(main) {
    main.innerHTML = `${ngHead('VLAN Configuration')}<p>Advanced 802.1Q VLAN Status : <b>Enable</b> · Number of VLANs : ${vlans().length}</p><table class="ng-t"><thead><tr><th></th><th>VLAN ID</th><th>VLAN Name</th></tr></thead>
      <tbody><tr><td></td><td>${input('ngVid', '', 'placeholder="2-4094" size="8"')}</td><td><button class="add" style="cursor:pointer">ADD</button></td></tr>${vlans().map(x => `<tr><td>${x === 1 ? '' : `<input type="checkbox" data-v="${x}">`}</td>
        <td>${x}</td><td>${x === 1 ? 'Default' : ''}</td></tr>`).join('')}</tbody></table><p><button class="del" style="cursor:pointer">DELETE</button></p>`;
    main.querySelector('.add').onclick = () => { const vid = Number(val(main, '#ngVid')); if (!(vid >= 2 && vid <= 4094)) return toast('VLAN ID : 2-4094', true);
      attempt(() => saveSwitching([...vlans(), vid], clone(N().switchports || {})), 'VLAN added.'); };
    main.querySelector('.del').onclick = async () => { for (const box of main.querySelectorAll('input[data-v]:checked')) if (!await attempt(() => dropVlan(Number(box.dataset.v)))) break; toast('Deleted.'); };
    main.querySelector('.apply').onclick = () => toast('Settings applied.');
    main.querySelector('.cancel').onclick = () => render();
  }
  function ngMembership(main) {
    const d = D(), v = V(), vid = vlans().includes(v.vid) ? v.vid : 1;
    main.innerHTML = `${ngHead('VLAN Membership')}<p>VLAN ID ${select('ngV', vlans(), vid)} &nbsp; Group Operation : Untag All / Tag All / Remove All</p><p>${d.ports.map(p =>
      `<span style="display:inline-block;text-align:center;margin-right:4px"><small>${ngPortNo(p)}</small><br><span class="ng-cell ${member(p.port, vid)}" data-p="${h(p.port)}">${member(p.port, vid)}</span></span>`).join('')}</p>
      <p style="color:#666">Cliquer une case : U (untagged) → T (tagged) → vide (non membre). Puis APPLY.</p><div class="px-err"></div>`;
    main.querySelector('#ngV').onchange = () => { v.vid = Number(val(main, '#ngV')); render(); };
    main.querySelectorAll('.ng-cell').forEach(cell => { cell.onclick = () => { const next = {U: 'T', T: '', '': 'U'}[cell.textContent.trim()]; cell.textContent = next; cell.className = `ng-cell ${next}`; }; });
    main.querySelector('.apply').onclick = async () => {
      try { await setVlanMembers(vid, Object.fromEntries([...main.querySelectorAll('.ng-cell')].map(c => [c.dataset.p, c.textContent.trim()]))); render(); toast('Settings applied.'); }
      catch (error) { main.querySelector('.px-err').textContent = error.message; }
    };
    main.querySelector('.cancel').onclick = () => render();
  }
  function ngPvid(main) {
    const d = D();
    main.innerHTML = `${ngHead('Port PVID')}<table class="ng-t"><thead><tr><th>Port</th><th>PVID</th><th>VLAN Members</th></tr></thead><tbody>${d.ports.map(p => `<tr><td>${ngPortNo(p)}</td>
      <td><select data-p="${h(p.port)}">${vlans().map(x => `<option${x === pvid(p.port) ? ' selected' : ''}>${x}</option>`).join('')}</select></td><td>${h(vlans().filter(x => member(p.port, x)).join(', '))}</td></tr>`).join('')}
      </tbody></table><div class="px-err"></div>`;
    main.querySelector('.apply').onclick = async () => {
      try {
        for (const box of main.querySelectorAll('select[data-p]')) if (Number(box.value) !== pvid(box.dataset.p)) await setPvid(box.dataset.p, Number(box.value));
        render(); toast('Settings applied.');
      } catch (error) { main.querySelector('.px-err').textContent = error.message; }
    };
    main.querySelector('.cancel').onclick = () => render();
  }

  /* =============================== D-Link Web Smart =============================== */
  skinCss(`
  .px-app.dlink{min-height:100vh;background:#fff;color:#222;font:12px Arial,Helvetica,sans-serif;display:grid;grid-template-rows:auto auto 1fr}
  .dl-tool{display:flex;gap:16px;align-items:center;padding:6px 12px;background:linear-gradient(#f4f4f4,#dcdcdc);border-bottom:1px solid #b5b5b5}.dl-tool .grow{flex:1}.dl-tool span{cursor:pointer}
  .dl-face{display:flex;align-items:center;gap:20px;padding:10px 16px;background:#2f3438}.dl-face b{color:#fff}.dl-ports{display:grid;grid-template-columns:repeat(14,24px);gap:3px}
  .dl-ports i{height:18px;background:#15191c;border:1px solid #6a7177;font-style:normal;color:#9aa1a7;font-size:8px;display:grid;place-items:center}.dl-ports i.up{background:#1e6d2e;color:#fff}
  .dl-ports i.down{background:#7a1d1d}.dl-ports i.spare{opacity:.5}
  .dl-body{display:grid;grid-template-columns:220px 1fr;min-height:0}.dl-tree{border-right:1px solid #ccc;padding:6px 0;overflow:auto}.dl-tree b{display:block;padding:5px 10px}
  .dl-tree a{display:block;padding:3px 10px 3px 26px;cursor:pointer}.dl-tree a.on{background:#316ac5;color:#fff}.dl-tree a.na{color:#999}
  .dl-main{padding:10px 16px;overflow:auto}.dl-title{background:linear-gradient(#e7eef7,#c9d8ea);border:1px solid #a8bcd6;padding:5px 10px;font-weight:bold;margin-bottom:8px}
  .dl-t{border-collapse:collapse}.dl-t th{background:#dde6f1;border:1px solid #b8c7da;padding:4px 8px;white-space:nowrap}.dl-t td{border:1px solid #d6dee8;padding:4px 8px;white-space:nowrap;text-align:center}
  .dl-btn{border:1px solid #888;background:linear-gradient(#fff,#ddd);padding:3px 14px;cursor:pointer;margin:6px 4px 6px 0}
  `);
  const DL_TREE = [['System', null], ['System Information', 'info', 1], ['Port Settings', 'ports', 1], ['VLAN', null], ['802.1Q VLAN', 'dot1q', 1], ['802.1Q VLAN PVID', 'pvid', 1],
    ['Asymmetric VLAN', 'na', 1], ['L2 Features', null], ['Spanning Tree', 'na', 1], ['Link Aggregation', 'na', 1], ['QoS', null], ['Bandwidth Control', 'na', 1], ['Security', null],
    ['Port Security', 'na', 1], ['Monitoring', null], ['Statistics', 'stats', 1]];
  SKINS.dlink = {
    start: {page: 'info', title: 'System Information', vid: 1},
    draw(root) {
      const v = V();
      root.innerHTML = `<div class="dl-tool"><span class="save">Save ▾</span><span>Tools ▾</span><span>Online Help ▾</span><span class="grow"></span><span>Logged in as: admin · ${h(N().name)}</span><span>Logout</span></div>
        <div class="dl-face"><b>${h(D().model)}</b>${faceplate('dl-ports', p => p.name.split('/').pop())}</div><div class="dl-body"><nav class="dl-tree"><b>⊟ ${h(D().model)}</b>${DL_TREE.map(([label, page, sub]) =>
          page === null ? `<b>📁 ${h(label)}</b>` : `<a data-go="${page}" data-t="${h(label)}" class="${page === 'na' ? 'na' : ''}${label === v.title ? ' on' : ''}">${h(label)}</a>`).join('')}</nav><main class="dl-main"></main></div>`;
      root.querySelector('.save').onclick = () => toast('Save Configuration : enregistré (le projet est déjà à jour).');
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => go(a.dataset.go, {title: a.dataset.t}); });
      const main = root.querySelector('main');
      ({info: dlInfo, ports: dlPorts, dot1q: dlDot1q, pvid: dlPvid, stats: dlStats}[v.page] || (m => { m.innerHTML = naBox(v.title, NA.later); }))(main);
    },
  };
  const dlNo = p => String(D().ports.indexOf(p) + 1).padStart(2, '0');
  function dlInfo(main) {
    main.innerHTML = `<div class="dl-title">System Information</div><table class="dl-t"><tbody>${[['Device Type', h(D().model)], ['System Name', input('dlName', N().name) + ' <button class="dl-btn apply">Apply</button>'],
      ['MAC Address', '—'], ['IP Address', '—'], ['Firmware Version', 'Network LABS'], ['Hardware Version', 'A1']].map(([k, v]) => `<tr><th style="text-align:right">${k}</th><td style="text-align:left">${v}</td></tr>`).join('')}</tbody></table>`;
    main.querySelector('.apply').onclick = () => attempt(() => rename(val(main, '#dlName')), 'Success.');
  }
  function dlPorts(main) {
    const d = D();
    main.innerHTML = `<div class="dl-title">Port Settings</div><p>From Port ${select('dlP', d.ports.map(p => [p.port, dlNo(p)]), d.ports[0].port)} State ${select('dlS', [['1', 'Enabled'], ['0', 'Disabled']], '1')}
      Speed/Duplex ${select('sd', ['Auto'], 'Auto')} <button class="dl-btn apply">Apply</button></p><table class="dl-t"><thead><tr><th>Port</th><th>State</th><th>Speed/Duplex</th><th>Flow Control</th><th>Connection</th></tr></thead>
      <tbody>${d.ports.map(p => tr([dlNo(p), p.down ? 'Disabled' : 'Enabled', 'Auto', 'Disabled', p.peer && !p.down ? '1000M/Full' : 'Link Down'])).join('')}</tbody></table>`;
    main.querySelector('.apply').onclick = () => attempt(() => setAddress(val(main, '#dlP'), '', val(main, '#dlS') === '1'), 'Success.');
  }
  function dlDot1q(main) {
    const d = D(), v = V(), vid = v.vid || 1;
    main.innerHTML = `<div class="dl-title">802.1Q VLAN</div><p>VID ${input('dlVid', vid, 'size="6"')} VLAN Name ${input('dlVn', vid === 1 ? 'default' : `VLAN${vid}`, 'size="14"')}</p>
      <table class="dl-t"><thead><tr><th>Port</th>${d.ports.map(p => `<th>${dlNo(p)}</th>`).join('')}</tr></thead><tbody>${[['U', 'Untagged'], ['T', 'Tagged'], ['', 'Not Member']].map(([c, label]) =>
        `<tr><th>${label}</th>${d.ports.map(p => `<td><input type="radio" name="d-${h(p.port)}" value="${c}" ${member(p.port, vid) === c ? 'checked' : ''}></td>`).join('')}</tr>`).join('')}</tbody></table>
      <button class="dl-btn add">Add/Apply</button><div class="px-err"></div><table class="dl-t" style="margin-top:10px"><thead><tr><th>VID</th><th>VLAN Name</th><th>Tagged Ports</th><th>Untagged Ports</th><th></th><th></th></tr></thead>
      <tbody>${vlans().map(x => tr([String(x), x === 1 ? 'default' : `VLAN${x}`, h(d.ports.filter(p => member(p.port, x) === 'T').map(dlNo).join(',')), h(d.ports.filter(p => member(p.port, x) === 'U').map(dlNo).join(',')),
        `<button class="dl-btn" data-e="${x}">Edit</button>`, x === 1 ? '' : `<button class="dl-btn" data-x="${x}">Delete</button>`])).join('')}</tbody></table>`;
    main.querySelectorAll('[data-e]').forEach(b => { b.onclick = () => { v.vid = Number(b.dataset.e); render(); }; });
    main.querySelectorAll('[data-x]').forEach(b => { b.onclick = () => attempt(() => dropVlan(Number(b.dataset.x)), 'Success.').then(() => { v.vid = 1; }); });
    followVid(main, '#dlVid', 'd-');
    main.querySelector('.add').onclick = async () => {
      try {
        const id = Number(val(main, '#dlVid'));
        if (!(id >= 1 && id <= 4094)) throw new Error('VID : 1-4094');
        await setVlanMembers(id, Object.fromEntries(d.ports.map(p => [p.port, (main.querySelector(`input[name="d-${CSS.escape(p.port)}"]:checked`) || {}).value || ''])));
        v.vid = id; render(); toast('Success.');
      } catch (error) { main.querySelector('.px-err').textContent = error.message; }
    };
  }
  function dlPvid(main) {
    const d = D();
    main.innerHTML = `<div class="dl-title">802.1Q VLAN PVID</div><p>Port ${select('dlP', d.ports.map(p => [p.port, dlNo(p)]), d.ports[0].port)} PVID ${select('dlV', vlans(), 1)} <button class="dl-btn apply">Apply</button></p>
      <table class="dl-t"><thead><tr><th>Port</th><th>PVID</th></tr></thead><tbody>${d.ports.map(p => tr([dlNo(p), String(pvid(p.port))])).join('')}</tbody></table>`;
    main.querySelector('.apply').onclick = () => attempt(() => setPvid(val(main, '#dlP'), Number(val(main, '#dlV'))), 'Success.');
  }
  function dlStats(main) {
    main.innerHTML = `<div class="dl-title">Statistics</div><table class="dl-t"><thead><tr><th>Port</th><th>Link Status</th><th>RX Packets</th><th>TX Packets</th><th>CRC Error</th></tr></thead><tbody>${D().ports.map(p =>
      tr([dlNo(p), p.peer && !p.down ? 'Link Up' : 'Link Down', '0', '0', '0'])).join('')}</tbody></table>`;
  }

  /* =============================== Aruba (AOS-CX and Instant On) =============================== */
  skinCss(`
  .px-app.aruba{min-height:100vh;background:#f4f4f4;color:#222;font:13px Arial,Helvetica,sans-serif;display:grid;grid-template-columns:210px 1fr;grid-template-rows:50px 1fr}
  .ar-top{grid-column:1/-1;display:flex;align-items:center;gap:14px;padding:0 18px;background:#232323;color:#fff}.ar-top b{font-size:16px}.ar-top .grow{flex:1}.ar-top span{color:#bbb}
  .ar-nav{background:#333;color:#ddd;padding:8px 0}.ar-nav a{display:block;padding:10px 18px;cursor:pointer}.ar-nav a.on{background:#4a4a4a;color:#fff;border-left:4px solid #01a982;padding-left:14px}
  .ar-nav a.na{color:#888}.ar-main{padding:16px 20px;overflow:auto}.ar-main h2{margin:0 0 12px;font-weight:normal}
  .ar-card{background:#fff;border:1px solid #ddd;margin-bottom:14px}.ar-card h3{margin:0;padding:10px 14px;border-bottom:1px solid #eee;font-size:14px}.ar-card .b{padding:12px 14px}
  .ar-t{width:100%;border-collapse:collapse}.ar-t th{text-align:left;padding:9px 10px;border-bottom:2px solid #ddd;white-space:nowrap}.ar-t td{padding:8px 10px;border-bottom:1px solid #eee;white-space:nowrap}
  .ar-t tr.click{cursor:pointer}.ar-t tr.click:hover td{background:#eefaf6}.ar-up{color:#01a982}.ar-dn{color:#c62828}
  .ar-ports{display:grid;grid-template-columns:repeat(14,1fr);gap:4px;background:#2f2f2f;padding:10px}.ar-ports i{height:22px;background:#151515;border:1px solid #666;color:#aaa;font-style:normal;font-size:9px;display:grid;place-items:center}
  .ar-ports i.up{border-color:#01a982;color:#fff}.ar-ports i.down{border-color:#c62828}.ar-ports i.spare{opacity:.4}
  .ar-btn{border:0;background:#01a982;color:#fff;padding:7px 14px;cursor:pointer;border-radius:2px}.ar-btn.sec{background:#888}
  .ar-side{position:fixed;top:0;right:0;bottom:0;width:430px;background:#fff;box-shadow:-6px 0 20px rgba(0,0,0,.2);z-index:15;padding:16px 18px;overflow:auto}
  `);
  SKINS.aruba = {
    start: {page: 'overview', edit: null},
    draw(root) {
      const v = V(), instant = /Instant On/.test(D().model);
      const nav = instant ? [['Dashboard', 'overview'], ['Setup Network · VLANs', 'vlans'], ['Switching · Port configuration', 'interfaces'], ['Diagnostics', 'terminal'], ['Maintenance', 'na']]
        : [['Overview', 'overview'], ['Analytics', 'na'], ['System', 'na'], ['Interfaces', 'interfaces'], ['VLANs', 'vlans'], ['LAGs', 'na'], ['Diagnostics', 'terminal'], ['Configuration', 'config']];
      root.innerHTML = `<div class="ar-top"><b>${instant ? 'Aruba Instant On' : 'Aruba CX'}</b><span>${h(D().model)} · ${h(N().name)}</span><span class="grow"></span><span>sous-ensemble Network LABS</span><span>admin ▾</span></div>
        <nav class="ar-nav">${nav.map(([label, page]) => `<a data-go="${page}" class="${page === v.page ? 'on' : ''}${page === 'na' ? ' na' : ''}">${h(label)}</a>`).join('')}</nav><main class="ar-main"></main>`;
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { if (a.dataset.go === 'terminal') return openTerminal(); if (a.dataset.go !== 'na') go(a.dataset.go); }; });
      const main = root.querySelector('main');
      ({overview: arOverview, interfaces: arInterfaces, vlans: arVlans, config: arConfig}[v.page] || arOverview)(main);
    },
  };
  function arOverview(main) {
    const d = D();
    main.innerHTML = `<h2>${/Instant On/.test(d.model) ? 'Dashboard' : 'Overview'}</h2><div class="ar-card"><h3>${h(d.model)}</h3><div class="b">${faceplate('ar-ports', p => p.name.split('/').pop())}</div></div>
      <div class="ar-card"><h3>System</h3><div class="b">Product: ${h(d.brand)} ${h(d.model)}<br>Firmware: Network LABS<br>Uptime: ${running() ? 'en marche' : 'lab arrêté'}<br>VLANs: ${vlans().length} ·
      Interfaces up: ${d.ports.filter(p => p.peer && !p.down).length} / ${d.ports.length}</div></div>`;
  }
  function arInterfaces(main) {
    const d = D(), v = V();
    main.innerHTML = `<h2>Interfaces</h2><div class="ar-card">${table('ar-t', ['Name', 'Admin', 'Link', 'Speed', 'VLAN Mode', 'VLANs', 'Description'], d.ports.map((p, i) => { const pol = policy(p.port);
      return tr([h(p.name), p.down ? '<span class="ar-dn">Down</span>' : 'Up', p.peer && !p.down ? '<span class="ar-up">● Up</span>' : '<span class="ar-dn">● Down</span>', p.peer ? '1G' : '—',
        pol.mode === 'trunk' ? 'Trunk' : 'Access', h(pol.mode === 'trunk' ? `native ${pol.native_vlan} · ${pol.allowed === 'all' ? 'all' : pol.allowed.join(',')}` : String(pol.vlan)), h(p.peer ? 'to ' + p.peer : '')],
      `class="click" data-i="${i}"`); }))}</div>`;
    main.querySelectorAll('tr[data-i]').forEach(row => { row.onclick = () => { v.edit = Number(row.dataset.i); render(); }; });
    if (v.edit === null || v.edit === undefined) return;
    const p = d.ports[v.edit], pol = policy(p.port), side = document.createElement('div');
    side.className = 'ar-side';
    side.innerHTML = `<h3 style="margin-top:0">Edit Interface ${h(p.name)}</h3>${field('Admin State', select('arAdmin', [['1', 'Up'], ['0', 'Down']], p.down ? '0' : '1'))}
      ${field('VLAN Mode', select('arMode', [['access', 'Access'], ['trunk', 'Trunk']], pol.mode))}${field('Access VLAN', select('arVlan', vlans(), pol.mode === 'trunk' ? 1 : pol.vlan))}
      ${field('Native VLAN', select('arNative', vlans(), pol.mode === 'trunk' ? pol.native_vlan : 1))}${field('Allowed VLANs', input('arAllowed', pol.mode === 'trunk' ? (pol.allowed === 'all' ? 'all' : pol.allowed.join(',')) : 'all'))}
      <div class="px-err"></div><p><button class="ar-btn apply">Apply</button> <button class="ar-btn sec close">Cancel</button></p>`;
    main.append(side);
    side.querySelector('.close').onclick = () => { v.edit = null; render(); };
    side.querySelector('.apply').onclick = async () => {
      try {
        await setPortMode(p.port, val(side, '#arMode'), val(side, '#arVlan'), val(side, '#arNative'), val(side, '#arAllowed'));
        if ((val(side, '#arAdmin') === '1') === p.down) await setAddress(p.port, '', val(side, '#arAdmin') === '1');
        v.edit = null; render(); toast(`${p.name} : configuration applied.`);
      } catch (error) { side.querySelector('.px-err').textContent = error.message; }
    };
  }
  function arVlans(main) {
    const d = D();
    main.innerHTML = `<h2>VLANs</h2><p><button class="ar-btn add">＋ Add VLAN</button></p><div class="ar-card">${table('ar-t', ['VLAN ID', 'Name', 'Admin', 'Oper', 'Interfaces', ''], vlans().map(x => tr([String(x),
      x === 1 ? 'DEFAULT_VLAN_1' : `VLAN${x}`, 'Up', d.ports.some(p => member(p.port, x) && p.peer) ? '<span class="ar-up">Up</span>' : 'Down', h(d.ports.filter(p => member(p.port, x)).map(p => p.name).join(', ')),
      x === 1 ? '' : `<a data-x="${x}" style="color:#c62828;cursor:pointer">Delete</a>`])))}</div>`;
    main.querySelector('.add').onclick = () => dialog('aruba', 'Add VLAN', `${field('VLAN ID', input('arVid', '', 'placeholder="2-4094"'))}${field('Name', input('n', ''))}`, [['Apply', 'pri', async b => {
      const vid = Number(val(b, '#arVid')); if (!(vid >= 2 && vid <= 4094)) throw new Error('VLAN ID : 2-4094');
      await saveSwitching([...vlans(), vid], clone(N().switchports || {})); render(); toast('VLAN added.'); }], ['Cancel']]);
    main.querySelectorAll('[data-x]').forEach(a => { a.onclick = () => now(() => dropVlan(Number(a.dataset.x)), 'VLAN deleted.'); });
  }
  function arConfig(main) {
    const d = D();
    const text = [`hostname ${N().name}`, ...vlans().map(x => `vlan ${x}`), ...d.ports.map(p => { const pol = policy(p.port);
      return [`interface ${p.name}`, p.down ? '    shutdown' : '    no shutdown', pol.mode === 'trunk' ? `    vlan trunk native ${pol.native_vlan}\n    vlan trunk allowed ${pol.allowed === 'all' ? 'all' : pol.allowed.join(',')}`
        : `    vlan access ${pol.vlan}`].join('\n'); })].join('\n');
    main.innerHTML = `<h2>Configuration</h2><div class="ar-card"><h3>Running configuration</h3><pre class="b" style="margin:0;font:12px Consolas,monospace">${h(text)}</pre></div>`;
  }

  /* =============================== Cisco Catalyst 2960: Device Manager =============================== */
  skinCss(`
  .px-app.devmgr{min-height:100vh;background:#fff;color:#000;font:12px Arial,Helvetica,sans-serif;display:grid;grid-template-rows:auto 1fr}
  .dm-banner{display:flex;align-items:center;gap:20px;padding:8px 14px;background:linear-gradient(#e6e9ec,#c9ced3);border-bottom:1px solid #999}
  .dm-banner b{font-size:15px}.dm-banner .grow{flex:1}.dm-banner span{color:#1f4f8f;cursor:pointer}
  .dm-panel{display:grid;grid-template-columns:repeat(13,20px);grid-auto-flow:column;grid-template-rows:20px 20px;gap:2px;background:#3a4047;padding:6px;border-radius:2px}
  .dm-panel i{background:#16191c;border:1px solid #777;font-style:normal;color:#aaa;font-size:7px;display:grid;place-items:center}.dm-panel i.up{background:#1a5e28;border-color:#42c763;color:#fff}
  .dm-panel i.down{background:#6b1a1a;border-color:#e05656}.dm-panel i.spare{opacity:.45}
  .dm-body{display:grid;grid-template-columns:200px 1fr;min-height:0}.dm-tree{background:#e9ebee;border-right:1px solid #aaa;padding:6px 0}.dm-tree b{display:block;padding:6px 10px;background:#cdd3d9}
  .dm-tree a{display:block;padding:4px 10px 4px 22px;cursor:pointer;color:#1f4f8f}.dm-tree a.on{background:#fff;font-weight:bold;color:#000}.dm-tree a.na{color:#888}
  .dm-main{padding:12px 16px;overflow:auto}.dm-main h2{font-size:16px;margin:0 0 10px;color:#1f3f6b}
  .dm-t{border-collapse:collapse}.dm-t th{background:linear-gradient(#f5f5f5,#dadada);border:1px solid #aaa;padding:4px 8px;text-align:left;white-space:nowrap}
  .dm-t td{border:1px solid #ccc;padding:3px 8px;white-space:nowrap}.dm-btns{margin-top:10px;display:flex;gap:8px}.dm-btns button{border:1px solid #777;background:linear-gradient(#fff,#ddd);padding:3px 16px;cursor:pointer}
  .dm-tabs{display:flex;gap:2px;margin-bottom:8px}.dm-tabs a{padding:4px 12px;border:1px solid #aaa;background:#e3e3e3;cursor:pointer}.dm-tabs a.on{background:#fff;font-weight:bold}
  `);
  const DM_TREE = [['Dashboard', 'dashboard'], ['Configure', null], ['Smartports', 'na', 1], ['Port Settings', 'ports', 1], ['Express Setup', 'na', 1], ['VLANs', 'vlans', 1], ['Restart / Reset', 'na', 1],
    ['Monitor', null], ['Port Utilization', 'util', 1], ['Port Status', 'status', 1], ['Trends', 'na', 1], ['Diagnostics', null], ['Ping', 'terminal', 1], ['Network Assistant', 'na']];
  const dmIos = name => name.replace(/^fa/i, 'FastEthernet').replace(/^gi/i, 'GigabitEthernet');
  SKINS.devmgr = {
    start: {page: 'dashboard', title: 'Dashboard', tab: 'Configure VLANs'},
    draw(root) {
      const v = V();
      root.innerHTML = `<div class="dm-banner"><b>Catalyst 2960 Device Manager - ${h(N().name)}</b>${faceplate('dm-panel', p => p.name.split('/').pop())}<span class="grow"></span>
        <span class="ref">Refresh</span><span>Print</span><span>Help</span></div><div class="dm-body"><nav class="dm-tree"><b>Contents</b>${DM_TREE.map(([label, page, sub]) => page === null
          ? `<b>⊟ ${h(label)}</b>` : `<a data-go="${page}" data-t="${h(label)}" class="${page === 'na' ? 'na' : ''}${label === v.title ? ' on' : ''}">${h(label)}</a>`).join('')}</nav><main class="dm-main"></main></div>`;
      root.querySelector('.ref').onclick = () => load();
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { if (a.dataset.go === 'terminal') return openTerminal(); go(a.dataset.go, {title: a.dataset.t}); }; });
      const main = root.querySelector('main');
      ({dashboard: dmDashboard, ports: dmPorts, vlans: dmVlans, util: dmUtil, status: dmStatus}[v.page] || (m => { m.innerHTML = naBox(v.title, NA.later); }))(main);
    },
  };
  function dmDashboard(main) {
    const d = D();
    main.innerHTML = `<h2>Dashboard</h2><table class="dm-t"><tbody>${[['Host Name', N().name], ['Product ID', 'WS-C2960 · ' + d.model], ['Version ID', 'IOS (sous-ensemble Network LABS)'],
      ['Serial Number', '—'], ['Uptime', running() ? 'en marche' : 'lab arrêté'], ['IP Address', '—'], ['VLANs', vlans().join(', ')]].map(([k, v]) => `<tr><th>${k}</th><td>${h(v)}</td></tr>`).join('')}</tbody></table>
      <h2 style="margin-top:14px">Switch Health</h2><table class="dm-t"><tbody><tr><th>Bandwidth Used</th><td>0%</td></tr><tr><th>Packet Error</th><td>0%</td></tr><tr><th>Fan</th><td>OK</td></tr><tr><th>Temperature</th><td>OK</td></tr></tbody></table>`;
  }
  function dmPorts(main) {
    const d = D();
    main.innerHTML = `<h2>Port Settings</h2><table class="dm-t"><thead><tr><th>Port</th><th>Description</th><th>Status</th><th>Speed</th><th>Duplex</th><th>Auto-MDIX</th></tr></thead><tbody>${d.ports.map(p =>
      `<tr><td>${h(dmIos(p.name))}</td><td>${h(p.peer ? 'to ' + p.peer : '')}</td><td><label><input type="checkbox" data-p="${h(p.port)}" ${p.down ? '' : 'checked'}> Enabled</label></td><td>Auto</td><td>Auto</td><td>Enabled</td></tr>`).join('')}
      </tbody></table><div class="dm-btns"><button class="submit">Submit</button><button class="cancel">Cancel</button></div>`;
    main.querySelector('.cancel').onclick = () => render();
    main.querySelector('.submit').onclick = () => {
      const lines = [...main.querySelectorAll('input[data-p]')].flatMap(box => { const p = d.ports.find(x => x.port === box.dataset.p);
        return box.checked === p.down ? [`interface ${dmIos(p.name)}`, box.checked ? ' no shutdown' : ' shutdown'] : []; });
      if (!lines.length) return toast('No changes.');
      attempt(() => cli(lines.join('\n')), 'Submitted:\n' + lines.join('\n'));
    };
  }
  function dmVlans(main) {
    const d = D(), v = V(), tab = v.tab;
    const tabs = `<div class="dm-tabs">${['Configure VLANs', 'Port Membership'].map(t => `<a data-t="${t}" class="${t === tab ? 'on' : ''}">${t}</a>`).join('')}</div>`;
    if (tab === 'Configure VLANs') {
      main.innerHTML = `<h2>VLANs</h2>${tabs}<table class="dm-t"><thead><tr><th></th><th>VLAN ID</th><th>VLAN Name</th></tr></thead><tbody>${vlans().map(x => `<tr><td>${x === 1 ? '' : `<input type="checkbox" data-v="${x}">`}</td>
        <td>${x}</td><td>${x === 1 ? 'default' : `VLAN${String(x).padStart(4, '0')}`}</td></tr>`).join('')}</tbody></table><p>VLAN ID ${input('dmVid', '', 'size="6"')} Name ${input('dmVn', '', 'size="14"')}
        <button class="create">Create</button> <button class="delete">Delete</button></p>`;
      main.querySelector('.create').onclick = () => {
        const vid = Number(val(main, '#dmVid'));
        if (!(vid >= 2 && vid <= 1005)) return toast('VLAN ID : 2-1005', true);
        const text = `vlan ${vid}` + (val(main, '#dmVn') ? `\n name ${val(main, '#dmVn')}` : '');
        attempt(() => cli(text), 'Submitted:\n' + text);
      };
      main.querySelector('.delete').onclick = () => { const text = [...main.querySelectorAll('input[data-v]:checked')].map(b => `no vlan ${b.dataset.v}`).join('\n');
        if (text) attempt(() => cli(text), 'Submitted:\n' + text); };
    } else {
      main.innerHTML = `<h2>VLANs</h2>${tabs}<table class="dm-t"><thead><tr><th>Port</th><th>Mode</th><th>Administrative VLAN</th><th>Native VLAN</th><th>Allowed VLANs</th></tr></thead><tbody>${d.ports.map(p => {
        const pol = policy(p.port);
        return `<tr data-p="${h(p.port)}"><td>${h(dmIos(p.name))}</td><td><select class="m">${[['access', 'Static Access'], ['trunk', 'Trunk']].map(([x, l]) => `<option value="${x}"${x === pol.mode ? ' selected' : ''}>${l}</option>`).join('')}</select></td>
          <td><select class="a">${vlans().map(x => `<option${x === (pol.mode === 'access' ? pol.vlan : 1) ? ' selected' : ''}>${x}</option>`).join('')}</select></td>
          <td><select class="n">${vlans().map(x => `<option${x === (pol.mode === 'trunk' ? pol.native_vlan : 1) ? ' selected' : ''}>${x}</option>`).join('')}</select></td>
          <td><input class="w" size="10" value="${h(pol.mode === 'trunk' ? (pol.allowed === 'all' ? 'all' : pol.allowed.join(',')) : 'all')}"></td></tr>`; }).join('')}</tbody></table>
        <div class="dm-btns"><button class="submit">Submit</button><button class="cancel">Cancel</button></div>`;
      main.querySelector('.cancel').onclick = () => render();
      main.querySelector('.submit').onclick = () => {
        const lines = [];
        main.querySelectorAll('tr[data-p]').forEach(row => {
          const p = d.ports.find(x => x.port === row.dataset.p), pol = policy(p.port), mode = row.querySelector('.m').value;
          const access = Number(row.querySelector('.a').value), native = Number(row.querySelector('.n').value), allowed = row.querySelector('.w').value.trim();
          const same = mode === pol.mode && (mode === 'access' ? access === pol.vlan : native === pol.native_vlan && allowed === (pol.allowed === 'all' ? 'all' : pol.allowed.join(',')));
          if (same) return;
          lines.push(`interface ${dmIos(p.name)}`, mode === 'trunk' ? ` switchport mode trunk\n switchport trunk native vlan ${native}\n switchport trunk allowed vlan ${allowed}`
            : ` switchport mode access\n switchport access vlan ${access}`);
        });
        if (!lines.length) return toast('No changes.');
        attempt(() => cli(lines.join('\n')), 'Submitted:\n' + lines.join('\n'));
      };
    }
    main.querySelectorAll('[data-t]').forEach(a => { a.onclick = () => { v.tab = a.dataset.t; render(); }; });
  }
  function dmUtil(main) {
    main.innerHTML = `<h2>Port Utilization</h2><table class="dm-t"><thead><tr><th>Port</th><th>Utilization</th><th>Packets</th></tr></thead><tbody>${D().ports.map(p => tr([h(dmIos(p.name)), '0%', '0'])).join('')}</tbody></table>`;
  }
  function dmStatus(main) {
    main.innerHTML = `<h2>Port Status</h2><table class="dm-t"><thead><tr><th>Port</th><th>Status</th><th>VLAN</th><th>Duplex</th><th>Speed</th><th>Neighbor</th></tr></thead><tbody>${D().ports.map(p =>
      tr([h(dmIos(p.name)), p.down ? 'disabled' : p.peer ? 'connected' : 'notconnect', policy(p.port).mode === 'trunk' ? 'trunk' : String(pvid(p.port)), 'a-full', p.peer ? 'a-100' : 'auto', h(p.peer || '')])).join('')}</tbody></table>`;
  }
})();
