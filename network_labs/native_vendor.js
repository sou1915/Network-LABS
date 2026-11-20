/* Vendor management faces for firewalls other than FortiGate (its own face is native_fortios.js): each product's menu
 * layout and vocabulary — ASDM's Home / Configuration / Monitoring, pfSense's top menus, PAN-OS's tabs, a side menu for
 * the others — in a neutral Network LABS look (no vendor logo, colours or assets). The Status page is a dashboard built
 * from the lab draft; interfaces are edited here (/api/apply); rules and NAT open the lab's rule editors; what the lab
 * does not run is listed with the reason, as on the FortiGate face. */
'use strict';
(() => {
  const ENGINE = 'Nécessite les moteurs d’inspection du constructeur, absents d’un nœud Linux.';
  const LATER = 'Pas encore relié à ce modèle dans le laboratoire (prévu).';
  const VPN = 'Pas de moteur VPN dans l’image invitée du laboratoire.';
  const CLI = 'Disponible : terminal de l’équipement (double-clic dans Network LABS).';
  const PROFILES = [
    {test: d => d.brand === 'Cisco', family: 'tabs', product: 'ASDM', os: 'ASA', accent: '#2f6fa8',
      terms: {rules: 'Access Rules', nat: 'NAT Rules', allow: 'Permit', deny: 'Deny', ifaces: 'Interfaces', home: 'Device Dashboard'},
      menu: [['Home', [['status', 'Device Dashboard']]],
        ['Configuration', [['g', 'Device Setup'], ['interfaces', 'Interface Settings'], ['routes', 'Routing'], ['g', 'Firewall'],
          ['rules', 'Access Rules'], ['nat', 'NAT Rules'], ['x-obj', 'Objects', 'Les règles prennent des réseaux a.b.c.d/nn ou any.'],
          ['g', 'Remote Access VPN'], ['x-vpn', 'AnyConnect / IPsec', VPN], ['g', 'Device Management'], ['settings', 'System']]],
        ['Monitoring', [['live', 'Interfaces et sessions'], ['x-log', 'Logging', LATER]]]]},
    {test: d => d.model === 'pfSense', family: 'menubar', product: 'pfSense', os: 'pfSense', accent: '#3d5a8a',
      terms: {rules: 'Firewall Rules', nat: 'NAT', allow: 'Pass', deny: 'Block', ifaces: 'Interfaces', home: 'Status / Dashboard'},
      menu: [['System', [['settings', 'General Setup'], ['x-pkg', 'Package Manager', 'Paquets du constructeur : absents du nœud Linux.']]],
        ['Interfaces', [['interfaces', 'Assignments']]], ['Firewall', [['nat', 'NAT'], ['rules', 'Rules'],
          ['x-alias', 'Aliases', 'Les règles prennent des réseaux a.b.c.d/nn.'], ['x-shaper', 'Traffic Shaper', LATER]]],
        ['Services', [['x-dhcp', 'DHCP Server', 'Disponible : vue Network LABS › Serveur DHCP.'], ['x-dns', 'DNS Resolver', LATER]]],
        ['VPN', [['x-ipsec', 'IPsec', VPN], ['x-ovpn', 'OpenVPN', VPN]]],
        ['Status', [['status', 'Dashboard'], ['live', 'Interfaces (état réel)']]],
        ['Diagnostics', [['routes', 'Routes'], ['x-ping', 'Ping', CLI]]]]},
    {test: d => d.brand === 'Palo Alto', family: 'tabs', product: 'PAN-OS', os: 'PAN-OS', accent: '#2c7a7b',
      terms: {rules: 'Security Policy Rules', nat: 'NAT Policy Rules', allow: 'allow', deny: 'deny', ifaces: 'Interfaces', home: 'Dashboard'},
      menu: [['Dashboard', [['status', 'Dashboard']]], ['ACC', [['x-acc', 'Application Command Center', ENGINE]]],
        ['Monitor', [['live', 'Traffic (état réel)'], ['x-threat', 'Threat', ENGINE]]],
        ['Policies', [['rules', 'Security'], ['nat', 'NAT'], ['x-qos', 'QoS', LATER], ['x-pbf', 'Policy Based Forwarding', LATER]]],
        ['Objects', [['x-addr', 'Addresses', 'Les règles prennent des réseaux a.b.c.d/nn ou any.'], ['x-app', 'Applications', ENGINE]]],
        ['Network', [['interfaces', 'Interfaces'], ['x-zone', 'Zones', 'Une zone par port dans le laboratoire.'], ['routes', 'Virtual Routers'],
          ['x-gp', 'GlobalProtect', VPN]]],
        ['Device', [['settings', 'Setup'], ['x-admin', 'Administrators', 'Accès par l’application, pas de comptes du boîtier.']]]]},
    {test: () => true, family: 'side', product: '', os: '', accent: '#2f6f9f',
      terms: {rules: 'Security Policies', nat: 'NAT', allow: 'Allow', deny: 'Deny', ifaces: 'Interfaces', home: 'Dashboard'},
      menu: [['Dashboard', [['status', 'Dashboard'], ['live', 'Monitor (état réel)']]],
        ['Network', [['interfaces', 'Interfaces'], ['routes', 'Routing']]],
        ['Policies', [['rules', 'Security Policies'], ['nat', 'NAT']]],
        ['VPN', [['x-vpn', 'IPsec VPN', VPN]]], ['System', [['settings', 'Settings']]]]},
  ];
  const CLI_ONLY = 'Se configure dans le terminal de l’équipement (double-clic dans Network LABS) ; listé ici.';
  const ROLE_PROFILES = {
    router: [
      {test: d => d.brand === 'Cisco', family: 'tabs', product: 'WebUI', os: 'IOS', accent: '#2f6fa8',
        terms: {home: 'Dashboard', ifaces: 'Interfaces'},
        menu: [['Dashboard', [['status', 'Dashboard']]],
          ['Monitoring', [['routes', 'Routing Table'], ['features', 'Routing Protocols & Services'], ['live', 'Interfaces (état réel)']]],
          ['Configuration', [['g', 'Interface'], ['interfaces', 'Ethernet'], ['subif', 'Subinterfaces 802.1Q'], ['g', 'Services'],
            ['dhcp', 'DHCP Pool'], ['x-nat', 'NAT', CLI_ONLY], ['x-acl', 'Access Lists', CLI_ONLY], ['x-vpn', 'VPN', VPN]]],
          ['Administration', [['settings', 'Device']]]]},
      {test: () => true, family: 'side', accent: '#2f6f9f', terms: {home: 'Dashboard', ifaces: 'Interfaces'},
        menu: [['Dashboard', [['status', 'Dashboard'], ['live', 'Monitor (état réel)']]],
          ['Interfaces', [['interfaces', 'Interfaces'], ['subif', 'VLAN (802.1Q)']]],
          ['Routing', [['routes', 'Routes'], ['features', 'Protocols & services']]],
          ['Services', [['dhcp', 'DHCP Server']]], ['System', [['settings', 'Identity']]]]},
    ],
    switch: [
      {test: d => d.brand === 'Cisco' && /Catalyst/.test(d.model + d.title), family: 'tabs', product: 'Device Manager', os: 'IOS',
        accent: '#2f6fa8', terms: {home: 'Dashboard', ifaces: 'Ports'},
        menu: [['Dashboard', [['status', 'Dashboard']]],
          ['Configuration', [['ports', 'Port Settings'], ['vlans', 'VLAN'], ['features', 'Spanning Tree · Security · EtherChannel'],
            ['x-qos', 'QoS', LATER]]],
          ['Monitoring', [['live', 'Ports et VLAN (état réel)']]], ['Administration', [['settings', 'Device']]]]},
      {test: () => true, family: 'side', accent: '#2f6f9f', terms: {home: 'Dashboard', ifaces: 'Ports'},
        menu: [['Dashboard', [['status', 'Dashboard'], ['live', 'Monitor (état réel)']]],
          ['Switching', [['ports', 'Ports'], ['vlans', 'VLAN'], ['features', 'Spanning tree & sécurité']]],
          ['System', [['settings', 'System']]]]},
    ],
  };
  // A side-menu product's name, from its brand (the menus stay the shared ones).
  const PRODUCTS = {MikroTik: 'WebFig', Juniper: 'J-Web', Huawei: 'Web NMS', Arista: 'EOS', Nokia: 'SR OS', VyOS: 'VyOS',
    Ubiquiti: 'EdgeOS', 'HPE Aruba': 'ArubaOS', Aruba: 'ArubaOS', 'TP-Link': 'Easy Smart', NETGEAR: 'NETGEAR', Netgear: 'NETGEAR',
    'D-Link': 'Smart Console', Dell: 'OS10', Extreme: 'EXOS', Cisco: 'IOS'};
  // Product names and section names of the side-menu vendors (the rest of the side profile is shared).
  const SIDE = {
    OPNsense: ['OPNsense', {Dashboard: 'Lobby', Network: 'Interfaces', Policies: 'Firewall', rules: 'Rules', home: 'Lobby / Dashboard'}],
    Firewall: ['Sophos Firewall', {Dashboard: 'Monitor & analyze', Network: 'Configure', Policies: 'Protect', rules: 'Firewall rules',
      nat: 'NAT rules', home: 'Control center'}],
    Quantum: ['Gaia', {Dashboard: 'Gateways & Servers', Policies: 'Security Policies', rules: 'Access Control', home: 'Overview'}],
    TZ: ['SonicOS', {Dashboard: 'Monitor', Policies: 'Policy', rules: 'Security Policy', nat: 'NAT Policy', home: 'Dashboard'}],
    SRX: ['J-Web', {Dashboard: 'Dashboard', Network: 'Configure', rules: 'Security Policies', home: 'Dashboard'}],
    vSRX: ['J-Web', {Dashboard: 'Dashboard', Network: 'Configure', rules: 'Security Policies', home: 'Dashboard'}],
    'Firebox T45': ['Fireware', {Dashboard: 'Dashboard', Policies: 'Firewall', rules: 'Firewall Policies', home: 'Front Panel'}],
  };

  const css = document.createElement('style');
  css.textContent = `
  body.vx{margin:0;background:#eef2f6}
  body.vx>header,body.vx>.layout{display:none}
  .vx-app{min-height:100vh;display:grid;grid-template-rows:auto auto 1fr;font:13px Inter,Arial,sans-serif;color:#1d2a36}
  .vx-top{display:flex;align-items:center;gap:16px;padding:0 18px;height:50px;background:#1f2b37;color:#e8eef4}
  .vx-top b{font-size:15px}.vx-top .sub{color:#9fb0c0}.vx-top .grow{flex:1}
  .vx-top button{background:#2c3a48;color:#e8eef4;border:1px solid #3d4c5b;border-radius:4px;padding:6px 12px}
  .vx-top button:hover{background:#364757}
  .vx-pill{display:inline-flex;align-items:center;gap:7px;border-radius:999px;padding:4px 11px;background:#2c3a48;font-size:12px}
  .vx-pill i{width:8px;height:8px;border-radius:50%;background:#8a98a6}.vx-pill i.on{background:#3ddc84}
  .vx-product{font-size:11px;letter-spacing:.6px;text-transform:uppercase;color:#c8d6e3;border:1px solid #3d4c5b;border-radius:3px;padding:2px 7px}
  .vx-tabs{display:flex;gap:2px;padding:0 14px;background:#f7f9fb;border-bottom:1px solid #d7dfe7}
  .vx-tabs button{border:0;border-bottom:3px solid transparent;border-radius:0;background:none;padding:11px 16px;font-weight:600;color:#4a5b6c}
  .vx-tabs button.on{color:var(--vx);border-bottom-color:var(--vx)}.vx-tabs button:hover{background:#eef3f7}
  .vx-menubar{display:flex;gap:2px;padding:0 10px;background:#2a3036;position:relative}
  .vx-menubar>div{position:relative}
  .vx-menubar>div>button{background:none;border:0;border-radius:0;color:#e6ebf0;padding:12px 14px;font-weight:500}
  .vx-menubar>div>button:hover,.vx-menubar>div.open>button{background:#3a4148}
  .vx-drop{display:none;position:absolute;left:0;top:100%;min-width:220px;background:#fff;border:1px solid #d7dfe7;box-shadow:0 8px 20px rgba(0,0,0,.18);z-index:5}
  .vx-menubar>div.open .vx-drop{display:block}
  .vx-drop button{display:block;width:100%;text-align:left;border:0;border-radius:0;background:#fff;padding:9px 14px;color:#1d2a36}
  .vx-drop button:hover{background:#eef3f7}.vx-drop button.na{color:#8a98a6}
  .vx-body{display:grid;grid-template-columns:230px 1fr;min-height:0}.vx-body.wide{grid-template-columns:1fr}
  .vx-nav{background:#fff;border-right:1px solid #d7dfe7;padding:10px 0}
  .vx-app.side .vx-nav{background:#26313c;border:0}
  .vx-nav .grp{padding:12px 16px 4px;font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:#7d8c9a}
  .vx-nav button{display:block;width:100%;text-align:left;background:none;border:0;border-left:3px solid transparent;border-radius:0;
    padding:8px 16px 8px 26px;color:#22323f}
  .vx-app.side .vx-nav button{color:#d7e0e8}
  .vx-nav button:hover{background:#eef3f7}.vx-app.side .vx-nav button:hover{background:#2f3c49}
  .vx-nav button.on{border-left-color:var(--vx);background:#e8f1f8;color:#0f2f4a;font-weight:600}
  .vx-app.side .vx-nav button.on{background:#334454;color:#fff}
  .vx-nav button.na{color:#8a98a6}.vx-nav button.na:after,.vx-drop button.na:after{content:"  ○";font-size:10px}
  .vx-main{padding:18px 22px;overflow:auto}
  .vx-main h1{font-size:18px;margin:0 0 4px}.vx-main .lead{color:#647587;margin:0 0 14px;font-size:12px}
  .vx-crumb{font-size:11.5px;color:#7d8c9a;margin-bottom:6px}
  .vx-face{display:flex;align-items:center;gap:20px;background:linear-gradient(180deg,#3a4652,#1f2830);border-radius:8px;padding:14px 20px;
    margin-bottom:14px;color:#cfd8e1;box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 3px 10px rgba(16,24,32,.18)}
  .vx-plate{min-width:130px}.vx-plate b{display:block;font-size:16px;color:#fff}.vx-plate span{font-size:11px;color:#9fb0c0}
  .vx-leds{display:flex;gap:12px;margin-top:10px;font-size:9.5px;color:#9fb0c0}.vx-leds span{display:flex;align-items:center;gap:5px}
  .vx-leds i{width:7px;height:7px;border-radius:50%;background:#56636f}.vx-leds i.on{background:#3ddc84;box-shadow:0 0 6px #3ddc84}
  .vx-ports{display:flex;gap:8px;flex-wrap:wrap;flex:1}
  .vx-fp{width:72px;text-align:center;cursor:pointer}.vx-fp.spare{opacity:.4;cursor:default}
  .vx-fp .num{display:block;font-size:10.5px;font-weight:600;color:#dfe7ee;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .vx-fp .jack{position:relative;height:30px;margin:0 12px;border-radius:3px;background:#0b1015;border:1px solid #56636f}
  .vx-fp .jack:after{content:'';position:absolute;left:30%;right:30%;bottom:-1px;height:7px;background:#1f2830;border:1px solid #56636f;border-bottom:0}
  .vx-fp .led{position:absolute;top:3px;width:7px;height:4px;border-radius:1px;background:#3a4652}.vx-fp .l{left:4px}.vx-fp .r{right:4px}
  .vx-fp.up .l{background:#3ddc84;box-shadow:0 0 5px #3ddc84}.vx-fp.up .r{background:#f5b041}.vx-fp.down .l{background:#e04f4f}
  .vx-fp .addr{display:block;margin-top:4px;font-size:10px;color:#9fb0c0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .vx-widgets{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
  .vx-w{background:#fff;border:1px solid #d5dde5;border-radius:6px;overflow:hidden}.vx-w.wide{grid-column:span 2}.vx-w.full{grid-column:1/-1}
  .vx-w h3{margin:0;padding:9px 12px;font-size:13px;border-bottom:1px solid #edf1f4;background:#f7f9fb;display:flex;justify-content:space-between}
  .vx-app.menubar .vx-w h3{background:#424a52;color:#fff;border-color:#424a52}
  .vx-w h3 small{font-weight:500;color:#7d8c9a}.vx-app.menubar .vx-w h3 small{color:#c9d2da}
  .vx-w .body{padding:12px}.vx-w .body.flush{padding:0}
  .vx-kv{display:grid;grid-template-columns:130px 1fr;gap:6px 10px}.vx-kv span{color:#647587}
  .vx-big{font-size:30px;font-weight:600}.vx-big small{font-size:15px;color:#7d8c9a;font-weight:500}
  .vx-meter{display:flex;height:8px;border-radius:4px;background:#e6ecf1;overflow:hidden;margin:12px 0 8px}.vx-meter i{display:block;height:100%}
  .vx-legend{display:flex;gap:12px;font-size:11px;color:#647587;flex-wrap:wrap}.vx-legend span{display:flex;align-items:center;gap:5px}
  .vx-legend i{width:8px;height:8px;border-radius:2px;display:inline-block}
  .vx-main table{width:100%;border-collapse:collapse;font-size:12.5px}
  .vx-main th{background:#f3f6f8;text-align:left;font-weight:600;padding:8px 12px;border-bottom:1px solid #d5dde5;white-space:nowrap;color:#3d4f61}
  .vx-main td{padding:8px 12px;border-bottom:1px solid #edf1f4;white-space:nowrap}
  .vx-main tr:last-child td{border-bottom:0}.vx-main tbody tr:hover td{background:#f5f9fc}
  .vx-table{background:#fff;border:1px solid #d5dde5;border-radius:6px;overflow:auto}
  .vx-empty{margin:0;padding:14px 12px;color:#7d8c9a;font-size:12px}
  .vx-ok{color:#167a3e;font-weight:600}.vx-bad{color:#b42323;font-weight:600}.vx-off{color:#8a98a6}
  .vx-tag{display:inline-block;border-radius:3px;padding:1px 7px;font-size:11px;background:#e8f1f8;color:#20577f}
  .vx-tag.s{background:#eef0fb;color:#3c4ca0}.vx-tag.nat{background:#e7f5f1;color:#1d6b55}
  .vx-bar{display:flex;gap:8px;align-items:center;margin-bottom:10px}
  .vx-bar button{border-radius:4px;padding:6px 12px;border:1px solid #c9d3dc;background:#fff}
  .vx-bar button.new{background:var(--vx);border-color:var(--vx);color:#fff}
  .vx-na{max-width:680px;background:#fff;border:1px solid #d5dde5;border-radius:6px;padding:18px 20px}.vx-na b{display:block;font-size:15px;margin-bottom:6px}
  .vx-note{font-size:12px;color:#647587;margin-top:10px;line-height:1.5}
  .vx-form{display:grid;grid-template-columns:150px 1fr;gap:10px 14px;align-items:center;max-width:620px;background:#fff;border:1px solid #d5dde5;
    border-radius:6px;padding:16px 18px;margin-top:14px}
  .vx-form label{color:#4a5b6c}.vx-form input,.vx-form select{border-radius:4px;border:1px solid #c9d3dc;padding:6px 9px;font:inherit}
  .vx-form .acts{grid-column:1/-1;display:flex;gap:8px;justify-content:flex-end}
  .vx-form .acts button{border-radius:4px;padding:7px 14px;border:1px solid #c9d3dc;background:#fff}
  .vx-form .acts .ok{background:var(--vx);color:#fff;border-color:var(--vx)}.vx-form .err{grid-column:1/-1;color:#b42323;min-height:16px}
  .vx-fp .vbar{display:block;height:4px;margin:4px 12px 0;border-radius:2px}
  .vchip{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:7px;vertical-align:-1px}
  .vx-toast{position:fixed;left:50%;transform:translateX(-50%);bottom:16px;background:#1f2b37;color:#fff;padding:10px 14px;border-radius:6px;
    box-shadow:0 6px 20px rgba(0,0,0,.25);z-index:6}
  `;
  document.head.appendChild(css);

  const ASKED = {dashboard: 'status', overview: 'status', firewall: 'rules', nat: 'nat', routing: 'routes', interfaces: 'interfaces'};
  let vxPage = ASKED[typeof page === 'string' ? page : ''] || 'status', standard = false, profile = null, editing = null;
  const app = document.createElement('div');
  const portName = port => (state.device.port_names || {})[port] || port;
  const mask = prefix => [0, 8, 16, 24].map(s => (prefix >= s + 8 ? 255 : prefix <= s ? 0 : 256 - 2 ** (8 - (prefix - s)))).join('.');
  const ipMask = cidr => { const [ip, p] = cidr.split('/'); return `${ip} ${mask(Number(p))}`; };
  const fw = () => state.node.firewall || {rules: [], nat: [], default: 'drop'};
  const service = r => !r.protocol || r.protocol === 'any' ? 'any' : r.dport ? `${r.protocol}/${r.dport}` : r.protocol;
  const percent = (part, whole) => whole ? Math.round(100 * part / whole) : 0;
  const tableHtml = (head, rows, empty) => rows.length ? `<table>${head.some(Boolean) ? `<thead><tr>${head.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>` : ''}<tbody>${
    rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>` : `<p class="vx-empty">${esc(empty)}</p>`;

  function choose(d, role) {
    if (role !== 'firewall') {
      const found = ROLE_PROFILES[role].find(p => p.test(d));
      const product = /Nexus/.test(d.model) ? 'NX-OS' : PRODUCTS[d.brand] || d.model;
      return found.family === 'side' ? {...found, product, os: product} : found;
    }
    const found = PROFILES.find(p => p.test(d));
    if (found.family !== 'side') return found;
    const [product, names] = SIDE[d.model] || [d.brand, {}];
    const rename = ([group, items]) => [names[group] || group, items.map(([id, label, why]) => [id,
      id === 'status' ? names.home || label : id === 'rules' ? names.rules || label : id === 'nat' ? names.nat || label : label, why])];
    return {...found, product, os: product, terms: {...found.terms, rules: names.rules || found.terms.rules, nat: names.nat || found.terms.nat,
      home: names.home || found.terms.home}, menu: found.menu.map(rename)};
  }
  function toast(text) {
    let box = document.querySelector('.vx-toast');
    if (!box) { box = document.createElement('div'); box.className = 'vx-toast'; document.body.append(box); }
    box.textContent = text;
    setTimeout(() => box.remove(), 4200);
  }
  const items = () => profile.menu.flatMap(([group, list]) => list.filter(([id]) => id !== 'g').map(([id, label, why]) => ({group, id, label, why})));
  const current = () => items().find(item => item.id === vxPage) || items()[0];
  function openStandard(target) {
    standard = true; document.body.classList.remove('vx'); app.remove(); page = target; render();
  }

  // ---- pages ----
  function statusPage(main) {
    const d = state.device, n = state.node, rules = fw().rules, nat = fw().nat || [], live = state.live, running = state.observed === 'running';
    const allow = rules.filter(r => r.action === 'accept').length, deny = rules.length - allow, t = profile.terms;
    const up = d.ports.filter(p => p.peer && !p.down).length;
    const face = [...d.ports, ...d.spare.map(name => ({name, spare: true}))].map(p => {
      const kind = p.spare ? 'spare' : p.down ? 'down' : p.peer ? 'up' : 'free';
      const tip = p.spare ? `${p.name} · port du modèle non déclaré` : `${p.name}${p.address ? ' · ' + p.address : ''} · ${p.peer ? 'câblé vers ' + p.peer : 'libre'}`;
      return `<div class="vx-fp ${kind}" title="${esc(tip)}"><span class="num">${esc(p.name)}</span><div class="jack"><i class="led l"></i><i class="led r"></i></div>
        <span class="addr">${p.spare ? '&nbsp;' : esc(p.address ? p.address.split('/')[0] : '—')}</span></div>`;
    }).join('');
    const ifRows = d.ports.map(p => [`<b>${esc(p.name)}</b>`, esc(p.address ? ipMask(p.address) : 'unassigned'), esc(p.peer || '—'),
      p.down ? '<span class="vx-bad">● down</span>' : p.peer ? '<span class="vx-ok">● up</span>' : '<span class="vx-off">● no link</span>']);
    const routeRows = [...d.connected.map(r => [esc(r.network), '—', esc(r.port), '<span class="vx-tag">connected</span>']),
      ...d.static.map(r => [esc(r.network), esc(r.gateway), esc(r.port), '<span class="vx-tag s">static</span>'])];
    const ruleRows = rules.slice(0, 6).map((r, i) => [String(i + 1), `<b>${esc(r.name)}</b>`,
      esc(`${r.in ? portName(r.in) : 'any'} → ${r.out ? portName(r.out) : 'any'}`), esc(r.source || 'any'), esc(r.destination || 'any'),
      esc(service(r)), r.action === 'accept' ? `<span class="vx-ok">✔ ${esc(t.allow)}</span>` : `<span class="vx-bad">✖ ${esc(t.deny)}</span>`]);
    main.insertAdjacentHTML('beforeend', `<h1>${esc(t.home)}</h1><p class="lead">${esc(n.name)} · ${esc(d.brand)} ${esc(d.model)} : la configuration du
      laboratoire${live ? ', et le relevé de ' + esc(live.time) : ''}.</p>
      <div class="vx-face"><div class="vx-plate"><b>${esc(d.model)}</b><span>${esc(d.brand)}</span>
        <div class="vx-leds"><span><i class="on"></i>PWR</span><span><i class="${running ? 'on' : ''}"></i>STATUS</span></div></div>
        <div class="vx-ports">${face}</div></div>
      <div class="vx-widgets">
        <div class="vx-w"><h3>System Information</h3><div class="body vx-kv"><span>Hostname</span><b>${esc(n.name)}</b>
          <span>Model</span><b>${esc(d.brand)} ${esc(d.model)}</b><span>Software</span><b>Linux · Network LABS</b>
          <span>Menus</span><b>${esc(profile.product || d.model)}</b><span>Runtime</span><b>${esc(d.runtime)}</b>
          <span>State</span><b>${running ? '<span class="vx-ok">● En marche</span>' : '<span class="vx-off">○ Non observé</span>'}</b></div></div>
        <div class="vx-w"><h3>${esc(t.ifaces)}<small>${up} up / ${d.ports.length}</small></h3><div class="body"><div class="vx-big">${up}<small> / ${d.ports.length}</small></div>
          <div class="vx-meter"><i style="width:${percent(up, d.ports.length)}%;background:#3ddc84"></i></div>
          <div class="vx-legend"><span><i style="background:#3ddc84"></i>up ${up}</span><span><i style="background:#c9d3dc"></i>no link ${
            d.ports.filter(p => !p.peer).length}</span><span><i style="background:#e04f4f"></i>down ${d.ports.filter(p => p.down).length}</span></div></div></div>
        <div class="vx-w"><h3>${esc(t.rules)}<small>default ${fw().default === 'accept' ? esc(t.allow) : esc(t.deny)}</small></h3><div class="body">
          <div class="vx-big">${rules.length}</div><div class="vx-meter">${rules.length ? `<i style="width:${percent(allow, rules.length)}%;background:#2e9d5b"></i><i style="width:${
            percent(deny, rules.length)}%;background:#c0392b"></i>` : ''}</div>
          <div class="vx-legend"><span><i style="background:#2e9d5b"></i>${esc(t.allow)} ${allow}</span><span><i style="background:#c0392b"></i>${esc(t.deny)} ${deny}</span>
          <span><i style="background:#1f7a8c"></i>NAT ${nat.length}</span></div></div></div>
        <div class="vx-w full"><h3>${esc(t.ifaces)}<small>configuration du laboratoire</small></h3><div class="body flush">${tableHtml(['Name', 'IP Address / Mask', 'Câble vers', 'Link'],
          ifRows, 'Aucun port déclaré.')}</div></div>
        <div class="vx-w wide"><h3>Routing Table</h3><div class="body flush">${tableHtml(['Destination', 'Gateway', 'Interface', 'Type'], routeRows,
          'Aucune route : donner une adresse à un port.')}</div></div>
        <div class="vx-w"><h3>Sessions</h3><div class="body"><div class="vx-big">${live && live.sessions ? live.sessions.length : '—'}</div>
          <div class="vx-note">${live ? 'relevé à ' + esc(live.time) : 'Lab en marche : Monitoring › état réel.'}</div></div></div>
        <div class="vx-w full"><h3>${esc(t.rules)}<small>${rules.length} règle${rules.length > 1 ? 's' : ''}</small></h3><div class="body flush">${tableHtml(['#', 'Name',
          'From → To', 'Source', 'Destination', 'Service', 'Action'], ruleRows, 'Aucune règle : ' + t.rules + ' › Add.')}</div></div>
      </div>`);
    main.querySelectorAll('.vx-fp:not(.spare)').forEach((element, index) => {
      element.onclick = () => { vxPage = 'interfaces'; editing = state.device.ports[index].port; draw(); };
    });
  }

  const VLAN_COLOURS = ['#3aa0e8', '#35c47c', '#f2a93b', '#b06ee8', '#e85d75', '#2ec4c4', '#8f9c2b', '#e07b39'];
  const vlanColour = vid => vid === 1 ? '#8a9bb0' : VLAN_COLOURS[vid % VLAN_COLOURS.length];
  const featureList = () => (state.device.features || []);
  const featureRows = () => featureList().map(f => [`<span class="vx-tag">${esc(f.name)}</span>`, esc(f.detail)]);

  function devicePage(main) {
    const d = state.device, n = state.node, running = state.observed === 'running', t = profile.terms, live = state.live;
    const switching = n.role === 'switch';
    const up = d.ports.filter(p => p.peer && !p.down).length;
    const face = [...d.ports, ...d.spare.map(name => ({name, spare: true}))].map(p => {
      const kind = p.spare ? 'spare' : p.down ? 'down' : p.peer ? 'up' : 'free';
      const bar = switching && !p.spare ? `<i class="vbar" style="background:${p.trunk ? 'repeating-linear-gradient(90deg,#3aa0e8 0 6px,#35c47c 6px 12px,#f2a93b 12px 18px)'
        : vlanColour(p.vlan)}"></i>` : '';
      const tip = p.spare ? `${p.name} · port du modèle non déclaré` : `${p.name} · ${p.detail}${p.peer ? ' · câblé vers ' + p.peer : ' · libre'}`;
      return `<div class="vx-fp ${kind}" title="${esc(tip)}"><span class="num">${esc(p.name)}</span><div class="jack"><i class="led l"></i><i class="led r"></i></div>
        ${bar}<span class="addr">${p.spare ? '&nbsp;' : esc(switching ? (p.trunk ? 'trunk' : 'VLAN ' + p.vlan) : p.address ? p.address.split('/')[0] : '—')}</span></div>`;
    }).join('');
    const ifRows = switching ? d.ports.map(p => [`<b>${esc(p.name)}</b>`, p.trunk ? '<span class="vx-tag s">trunk</span>' : '<span class="vx-tag">access</span>',
        esc(p.trunk ? p.detail.replace('Trunk ', '') : 'VLAN ' + p.vlan), esc(p.peer || '—'),
        p.down ? '<span class="vx-bad">● down</span>' : p.peer ? '<span class="vx-ok">● up</span>' : '<span class="vx-off">● no link</span>'])
      : d.ports.map(p => [`<b>${esc(p.name)}</b>`, esc(p.address ? ipMask(p.address) : p.detail), esc(p.peer || '—'),
        p.down ? '<span class="vx-bad">● down</span>' : p.peer ? '<span class="vx-ok">● up</span>' : '<span class="vx-off">● no link</span>']);
    const routeRows = [...d.connected.map(r => [esc(r.network), '—', esc(r.port), '<span class="vx-tag">C · connected</span>']),
      ...d.static.map(r => [esc(r.network), esc(r.gateway), esc(r.port), '<span class="vx-tag s">S · static</span>'])];
    const vlanRows = d.vlans.map(v => [`<span class="vchip" style="background:${vlanColour(v)}"></span><b>VLAN ${v}</b>`,
      esc(d.ports.filter(p => !p.trunk && p.vlan === v).map(p => p.name).join(', ') || '—'),
      esc(d.ports.filter(p => p.trunk && (/toutes/.test(p.detail) || p.detail.replace('Trunk ', '').split(',').map(Number).includes(v))).map(p => p.name).join(', ') || '—')]);
    const second = switching
      ? `<div class="vx-w"><h3>VLAN<small>${d.vlans.length} déclaré${d.vlans.length > 1 ? 's' : ''}</small></h3><div class="body"><div class="vx-big">${d.vlans.length}</div>
          <div class="vx-legend">${d.vlans.slice(0, 6).map(v => `<span><i style="background:${vlanColour(v)}"></i>VLAN ${v}</span>`).join('')}</div></div></div>`
      : `<div class="vx-w"><h3>Routing<small>${featureList().length} protocole${featureList().length > 1 ? 's' : ''} / service${featureList().length > 1 ? 's' : ''}</small></h3>
          <div class="body"><div class="vx-big">${d.connected.length + d.static.length}<small> route${d.connected.length + d.static.length > 1 ? 's' : ''}</small></div>
          <div class="vx-legend"><span><i style="background:#3aa0e8"></i>connectées ${d.connected.length}</span><span><i style="background:#6c63d6"></i>statiques ${
            d.static.length}</span></div><div class="vx-note">${esc(featureList().map(f => f.name).filter((v, i, a) => a.indexOf(v) === i).join(' · ') || 'routes statiques seulement')}</div></div></div>`;
    main.insertAdjacentHTML('beforeend', `<h1>${esc(t.home)}</h1><p class="lead">${esc(n.name)} · ${esc(d.brand)} ${esc(d.model)} : la configuration du
      laboratoire${live ? ', et le relevé de ' + esc(live.time) : ''}.</p>
      <div class="vx-face"><div class="vx-plate"><b>${esc(d.model)}</b><span>${esc(d.brand)}</span>
        <div class="vx-leds"><span><i class="on"></i>PWR</span><span><i class="${running ? 'on' : ''}"></i>SYS</span></div></div>
        <div class="vx-ports">${face}</div></div>
      <div class="vx-widgets">
        <div class="vx-w"><h3>System Information</h3><div class="body vx-kv"><span>Hostname</span><b>${esc(n.name)}</b>
          <span>Model</span><b>${esc(d.brand)} ${esc(d.model)}</b><span>Software</span><b>Linux · Network LABS</b>
          <span>CLI</span><b>${esc(d.cli || 'terminal Linux')}</b><span>Runtime</span><b>${esc(d.runtime)}</b>
          <span>State</span><b>${running ? '<span class="vx-ok">● En marche</span>' : '<span class="vx-off">○ Non observé</span>'}</b></div></div>
        <div class="vx-w"><h3>${esc(t.ifaces)}<small>${up} up / ${d.ports.length}</small></h3><div class="body"><div class="vx-big">${up}<small> / ${d.ports.length}</small></div>
          <div class="vx-meter"><i style="width:${percent(up, d.ports.length)}%;background:#3ddc84"></i></div>
          <div class="vx-legend"><span><i style="background:#3ddc84"></i>up ${up}</span><span><i style="background:#c9d3dc"></i>no link ${
            d.ports.filter(p => !p.peer).length}</span><span><i style="background:#e04f4f"></i>down ${d.ports.filter(p => p.down).length}</span></div></div></div>
        ${second}
        <div class="vx-w full"><h3>${esc(t.ifaces)}<small>configuration du laboratoire</small></h3><div class="body flush">${tableHtml(
          switching ? ['Port', 'Mode', 'VLAN', 'Câble vers', 'Link'] : ['Name', 'IP Address / Mask', 'Câble vers', 'Link'], ifRows, 'Aucun port déclaré.')}</div></div>
        <div class="vx-w wide"><h3>${switching ? 'VLAN' : 'Routing Table'}</h3><div class="body flush">${switching
          ? tableHtml(['VLAN', 'Ports access', 'Trunks'], vlanRows, 'Aucun VLAN.') : tableHtml(['Destination', 'Gateway', 'Interface', 'Type'], routeRows,
            'Aucune route : donner une adresse à un port.')}</div></div>
        <div class="vx-w"><h3>${switching ? 'Spanning tree · sécurité' : 'Protocols & services'}</h3><div class="body flush">${tableHtml(['', ''],
          featureRows(), switching ? 'Rien de plus que les VLAN : spanning tree, sécurité des ports et EtherChannel se configurent dans le terminal.'
            : 'Routes statiques seulement : OSPF, RIP, EIGRP, BGP, HSRP, NAT se configurent dans le terminal.')}</div></div>
      </div>`);
    main.querySelectorAll('.vx-fp:not(.spare)').forEach((element, index) => {
      element.onclick = () => { vxPage = switching ? 'ports' : 'interfaces'; editing = switching ? null : state.device.ports[index].port; draw(); };
    });
  }

  function portsPage(main) {
    const d = state.device;
    const rows = d.ports.map(p => [`<b>${esc(p.name)}</b>`, p.trunk ? '<span class="vx-tag s">trunk</span>' : '<span class="vx-tag">access</span>',
      p.trunk ? esc(p.detail.replace('Trunk ', 'VLAN ')) : `<span class="vchip" style="background:${vlanColour(p.vlan)}"></span>VLAN ${esc(p.vlan)}`,
      esc(p.peer || '—'), p.down ? '<span class="vx-bad">down</span>' : p.peer ? '<span class="vx-ok">up</span>' : '<span class="vx-off">no link</span>',
      `<span class="vx-off">${esc(p.port)}</span>`]);
    main.insertAdjacentHTML('beforeend', `<h1>${esc(current().label)}</h1><p class="lead">Mode et VLAN de chaque port, et l’équipement au bout du câble.</p>
      <div class="vx-bar"><button type="button" class="new">✎ Modifier les ports et les VLAN</button></div>
      <div class="vx-table">${tableHtml(['Port', 'Mode', 'VLAN', 'Câble vers', 'Link', 'Linux'], rows, 'Aucun port.')}</div>
      <p class="vx-note">Modifier ouvre l’éditeur de ports du laboratoire ; « switchport » dans le terminal fait de même.</p>`);
    main.querySelector('.vx-bar button').onclick = () => openStandard('switching');
  }

  function vlansPage(main) {
    const d = state.device;
    const rows = d.vlans.map(v => [`<span class="vchip" style="background:${vlanColour(v)}"></span><b>${v}</b>`,
      esc(v === 1 ? 'default' : `VLAN${String(v).padStart(4, '0')}`), esc(d.ports.filter(p => !p.trunk && p.vlan === v).map(p => p.name).join(', ') || '—'),
      esc(d.ports.filter(p => p.trunk).map(p => p.name).join(', ') || '—')]);
    main.insertAdjacentHTML('beforeend', `<h1>${esc(current().label)}</h1><p class="lead">VLAN déclarés et leurs ports.</p>
      <div class="vx-bar"><button type="button" class="new">+ Add / ✎ Edit</button></div>
      <div class="vx-table">${tableHtml(['VLAN ID', 'Name', 'Access ports', 'Trunks'], rows, 'Aucun VLAN.')}</div>`);
    main.querySelector('.vx-bar button').onclick = () => openStandard('switching');
  }

  function subinterfacesPage(main) {
    const rows = state.device.subinterfaces.map(s => [`<b>${esc(s.name)}</b>`, `<span class="vx-tag s">VLAN ${esc(s.vlan)}</span>`, esc(s.address || '—'),
      `<span class="vx-off">${esc(s.port)}</span>`]);
    main.insertAdjacentHTML('beforeend', `<h1>${esc(current().label)}</h1><p class="lead">Sous-interfaces 802.1Q (router-on-a-stick).</p>
      <div class="vx-bar"><button type="button" class="new">+ Add / ✎ Edit</button></div>
      <div class="vx-table">${tableHtml(['Interface', 'Encapsulation', 'IP Address', 'Linux'], rows, 'Aucune sous-interface.')}</div>`);
    main.querySelector('.vx-bar button').onclick = () => openStandard('subinterfaces');
  }

  function featuresPage(main) {
    main.insertAdjacentHTML('beforeend', `<h1>${esc(current().label)}</h1><p class="lead">Ce que l’équipement fait tourner, d’après le projet.</p>
      <div class="vx-table">${tableHtml(['Fonction', 'Détail'], featureRows(), 'Rien de configuré au-delà des adresses et routes.')}</div>
      <p class="vx-note">Ces fonctions se configurent dans le terminal de l’équipement (double-clic dans Network LABS), comme sur l’appareil ;
      « show » y lit leur état réel quand le lab est en marche.</p>`);
  }

  function dhcpPage(main) {
    const server = state.node.dhcp_server;
    main.insertAdjacentHTML('beforeend', `<h1>${esc(current().label)}</h1><p class="lead">Serveur DHCP de l’équipement.</p>
      <div class="vx-na"><b>${server ? 'Actif sur ' + esc(portName(server.interface)) : 'Aucun pool'}</b>${server
        ? esc(`${server.start} – ${server.end}${server.router ? ' · passerelle ' + server.router : ''}`) : 'Créer un pool pour un réseau d’un port.'}
        <div class="vx-bar" style="margin-top:12px"><button type="button" class="new">${server ? '✎ Edit' : '+ Add'}</button></div></div>`);
    main.querySelector('.vx-bar button').onclick = () => openStandard('dhcpserver');
  }

  function interfacesPage(main) {
    const d = state.device, n = state.node;
    main.insertAdjacentHTML('beforeend', `<h1>${esc(current().label)}</h1><p class="lead">Ports physiques du modèle déclarés dans le laboratoire.</p>`);
    const rows = d.ports.map(p => [`<b>${esc(p.name)}</b>`, esc(p.address ? ipMask(p.address) : 'unassigned'), esc(p.peer || '—'),
      p.down ? '<span class="vx-bad">down</span>' : p.peer ? '<span class="vx-ok">up</span>' : '<span class="vx-off">no link</span>',
      `<span class="vx-off">${esc(p.port)}</span>`, `<button type="button" data-port="${esc(p.port)}">Edit</button>`]);
    main.insertAdjacentHTML('beforeend', `<div class="vx-table">${tableHtml(['Interface', 'IP Address / Mask', 'Câble vers', 'Link', 'Linux', ''],
      rows, 'Aucun port.')}</div>`);
    main.querySelectorAll('[data-port]').forEach(button => { button.onclick = () => { editing = button.dataset.port; draw(); }; });
    if (!editing) return;
    const port = editing, address = n.interfaces[port] || '';
    main.insertAdjacentHTML('beforeend', `<form class="vx-form"><b style="grid-column:1/-1">Edit Interface · ${esc(portName(port))}</b>
      <label>IP Address</label><input id="vxIp" value="${esc(address.split('/')[0] || '')}" placeholder="a.b.c.d">
      <label>Subnet Mask</label><input id="vxMask" value="${esc(address ? mask(Number(address.split('/')[1])) : '255.255.255.0')}">
      <label>Default Gateway</label><input id="vxGw" value="${esc(n.gateway || '')}" placeholder="(aucune)">
      <div class="err"></div><div class="acts"><button type="button" class="cancel">Cancel</button><button type="submit" class="ok">OK</button></div></form>
      <p class="vx-note">Appliqué au projet (validé comme le reste du laboratoire) : la micro-VM le prend au ▶ Démarrer. Lab en marche : le terminal de l’équipement change le port en direct.</p>`);
    const form = main.querySelector('.vx-form');
    form.querySelector('.cancel').onclick = () => { editing = null; draw(); };
    form.onsubmit = async event => {
      event.preventDefault();
      const ip = form.querySelector('#vxIp').value.trim(), bits = form.querySelector('#vxMask').value.trim().split('.').map(Number);
      const prefix = bits.length === 4 ? bits.map(b => b.toString(2).padStart(8, '0')).join('').replace(/0+$/, '') : '';
      if (ip && (!/^1*$/.test(prefix) || bits.some(b => !(b >= 0 && b <= 255)))) { form.querySelector('.err').textContent = 'Masque invalide.'; return; }
      try {
        state = await request('/api/apply', {node, revision: state.revision, name: n.name, port, address: ip ? `${ip}/${prefix.length}` : '',
          gateway: form.querySelector('#vxGw').value.trim(), enabled: true});
        editing = null; render(); toast(`${portName(port)} : appliqué au projet.`);
      } catch (error) { form.querySelector('.err').textContent = error.message; }
    };
  }

  function routesPage(main) {
    const d = state.device;
    const rows = [...d.connected.map(r => [esc(r.network), '—', esc(r.port), '<span class="vx-tag">connected</span>']),
      ...d.static.map(r => [esc(r.network), esc(r.gateway), esc(r.port), '<span class="vx-tag s">static</span>'])];
    main.insertAdjacentHTML('beforeend', `<h1>${esc(current().label)}</h1><p class="lead">Routes du projet : réseaux des ports et routes statiques.</p>
      <div class="vx-table">${tableHtml(['Destination', 'Gateway', 'Interface', 'Type'], rows, 'Aucune route.')}</div>
      <p class="vx-note">La route par défaut se règle avec la passerelle d’une interface (${esc(profile.terms.ifaces)} › Edit) ; les autres routes,
      dans le terminal de l’équipement.</p>`);
  }

  function rulesPage(main, nat) {
    const t = profile.terms, list = nat ? fw().nat || [] : fw().rules;
    const rows = nat ? list.map((r, i) => [String(i + 1), `<b>${esc(r.name)}</b>`, `<span class="vx-tag nat">${esc(({masquerade: 'Dynamic PAT', snat: 'Static source',
      dnat: 'Destination'})[r.type] || r.type)}</span>`, esc(r.in ? portName(r.in) : r.out ? portName(r.out) : 'any'),
      esc([r.source, r.destination].filter(Boolean).join(' → ') || 'any'), esc(r.to ? r.to + (r.to_port ? ':' + r.to_port : '') : 'interface address')])
      : list.map((r, i) => [String(i + 1), `<b>${esc(r.name)}</b>`, esc(r.in ? portName(r.in) : 'any'), esc(r.out ? portName(r.out) : 'any'),
        esc(r.source || 'any'), esc(r.destination || 'any'), esc(service(r)),
        r.action === 'accept' ? `<span class="vx-ok">✔ ${esc(t.allow)}</span>` : `<span class="vx-bad">✖ ${esc(t.deny)}</span>`]);
    main.insertAdjacentHTML('beforeend', `<h1>${esc(nat ? t.nat : t.rules)}</h1><p class="lead">${nat ? 'Traductions d’adresses, appliquées dans l’ordre.'
      : `Évaluées de haut en bas ; le reste suit l’action par défaut (${fw().default === 'accept' ? esc(t.allow) : esc(t.deny)}).`}</p>
      <div class="vx-bar"><button type="button" class="new">+ Add</button><button type="button" class="edit">✎ Edit</button></div>
      <div class="vx-table">${tableHtml(nat ? ['#', 'Name', 'Type', 'Interface', 'Original', 'Translated'] : ['#', 'Name', 'Source Interface',
        'Destination Interface', 'Source', 'Destination', 'Service', 'Action'], rows, nat ? 'Aucune traduction.' : 'Aucune règle.')}</div>
      <p class="vx-note">Add et Edit ouvrent l’éditeur de règles du laboratoire (même politique, validée à l’enregistrement).</p>`);
    main.querySelectorAll('.vx-bar button').forEach(button => { button.onclick = () => openStandard(nat ? 'nat' : 'firewall'); });
  }

  function livePage(main) {
    const live = state.live, running = state.observed === 'running';
    main.insertAdjacentHTML('beforeend', `<h1>${esc(current().label)}</h1><p class="lead">L’état réel du nœud en marche, comparé au projet.</p>
      <div class="vx-na"><b>${live ? 'Relevé à ' + esc(live.time) : running ? 'Aucun relevé' : 'Lab arrêté'}</b>${live
        ? (live.conform ? '<span class="vx-ok">● Conforme au projet</span>' : '<span class="vx-bad">● Écarts avec le projet</span>')
        : running ? 'Le relevé lit les interfaces, routes et sessions du nœud.' : 'Démarrer le laboratoire, puis relever l’état réel.'}
        <div class="vx-bar" style="margin-top:12px"><button type="button" class="new">Ouvrir le relevé</button></div></div>`);
    main.querySelector('.vx-bar button').onclick = () => openStandard('dashboard');
  }

  function settingsPage(main) {
    const d = state.device, n = state.node;
    main.insertAdjacentHTML('beforeend', `<h1>${esc(current().label)}</h1><p class="lead">Paramètres système.</p><div class="vx-w"><h3>System</h3>
      <div class="body vx-kv"><span>Hostname</span><b>${esc(n.name)}</b><span>Model</span><b>${esc(d.brand)} ${esc(d.model)}</b>
      <span>Software</span><b>Linux · Network LABS (pas ${esc(profile.os || d.model)})</b><span>CLI</span><b>${esc(d.cli || 'terminal Linux')}</b></div></div>
      <p class="vx-note">Renommer l’équipement depuis Network LABS (Nom système). Ce boîtier exécute Linux : les menus suivent l’organisation de
      ${esc(profile.product || d.model)} pour l’apprentissage, sans le système ni l’interface du constructeur.</p>`);
  }

  function unavailablePage(main) {
    const item = current();
    main.insertAdjacentHTML('beforeend', `<h1>${esc(item.label)}</h1><p class="lead">${esc(item.group)} › ${esc(item.label)}</p>
      <div class="vx-na"><b>Non disponible dans le laboratoire</b>${esc(item.why || LATER)}<p class="vx-note">Ce menu existe sur le produit réel ;
      il est montré pour situer la fonction.</p></div>`);
  }

  function navButton(id, label, why) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.classList.toggle('on', id === vxPage);
    button.classList.toggle('na', Boolean(why));
    button.onclick = () => { vxPage = id; editing = null; app.querySelector('.vx-menubar .open')?.classList.remove('open'); draw(); };
    return button;
  }

  function draw() {
    const n = state.node, d = state.device, running = state.observed === 'running', item = current();
    app.className = 'vx-app ' + profile.family;
    app.style.setProperty('--vx', profile.accent);
    app.innerHTML = `<div class="vx-top"><b>${esc(n.name)}</b><span class="sub">${esc(d.brand)} ${esc(d.model)} · menus ${esc(profile.product || d.model)} · système Linux</span>
      <span class="grow"></span><span class="vx-pill"><i class="${running ? 'on' : ''}"></i>${running ? 'En marche' : 'Non observé'}</span>
      <button type="button" class="simple">◐ Design Studio</button><button type="button" class="std">Vue Network LABS</button>
      <button type="button" class="ref">↻</button></div>
      <div class="vx-strip"></div><div class="vx-body"><nav class="vx-nav"></nav><main class="vx-main"></main></div>`;
    const strip = app.querySelector('.vx-strip'), nav = app.querySelector('.vx-nav');
    if (profile.family === 'tabs') {
      strip.className = 'vx-tabs';
      for (const [group, list] of profile.menu) {
        const first = list.find(([id]) => id !== 'g');
        const tab = navButton(first[0], group);
        tab.classList.toggle('on', group === item.group);
        strip.append(tab);
      }
      const list = profile.menu.find(([group]) => group === item.group)[1];
      for (const [id, label, why] of list) {
        if (id === 'g') nav.insertAdjacentHTML('beforeend', `<div class="grp">${esc(label)}</div>`);
        else nav.append(navButton(id, label, why));
      }
      if (list.length < 2) { nav.remove(); app.querySelector('.vx-body').classList.add('wide'); }  // one page: no side menu
    } else if (profile.family === 'menubar') {
      strip.className = 'vx-menubar';
      for (const [group, list] of profile.menu) {
        const holder = document.createElement('div');
        const top = document.createElement('button');
        top.type = 'button'; top.textContent = group + ' ▾';
        top.onclick = () => { const open = holder.classList.contains('open'); strip.querySelectorAll('.open').forEach(x => x.classList.remove('open'));
          if (!open) holder.classList.add('open'); };
        const drop = document.createElement('div');
        drop.className = 'vx-drop';
        list.forEach(([id, label, why]) => drop.append(navButton(id, label, why)));
        holder.append(top, drop);
        strip.append(holder);
      }
      nav.remove();
      app.querySelector('.vx-body').classList.add('wide');
    } else {
      strip.remove();
      for (const [group, list] of profile.menu) {
        nav.insertAdjacentHTML('beforeend', `<div class="grp">${esc(group)}</div>`);
        list.forEach(([id, label, why]) => nav.append(navButton(id, label, why)));
      }
    }
    app.querySelector('.std').onclick = () => openStandard('dashboard');
    app.querySelector('.ref').onclick = () => load();
    app.querySelector('.simple').onclick = () => window.nlSetDesign && window.nlSetDesign('studio');
    const main = app.querySelector('main');
    if (profile.family !== 'side') main.insertAdjacentHTML('beforeend', `<div class="vx-crumb">${esc(item.group)} › ${esc(item.label)}</div>`);
    const pages = {status: n.role === 'firewall' ? statusPage : devicePage, interfaces: interfacesPage, routes: routesPage,
      rules: m => rulesPage(m, false), nat: m => rulesPage(m, true), live: livePage, settings: settingsPage, ports: portsPage, vlans: vlansPage,
      subif: subinterfacesPage, features: featuresPage, dhcp: dhcpPage};
    (item.why ? unavailablePage : pages[item.id] || unavailablePage)(main);
  }

  const previous = render;
  render = function () {
    previous();
    if (window.nlDesignNow && window.nlDesignNow() !== 'vendor') { app.remove(); document.body.classList.remove('vx'); return; }  // the « Simple » design draws the page
    const role = state && state.node && state.node.role;
    if (state && state.device && window.nlProduct && window.nlProduct(state.device)) { app.remove(); document.body.classList.remove('vx'); return; }  // its own copy
    if (!state || !state.device || standard || state.device.brand === 'Linux' || !['firewall', 'router', 'switch'].includes(role)
        || (role === 'firewall' && state.device.cli === 'FortiOS')) return;
    profile = choose(state.device, role);
    if (!app.isConnected) { document.body.append(app); document.body.classList.add('vx'); }
    draw();
  };
})();
