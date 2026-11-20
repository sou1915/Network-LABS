/* FortiOS-style workflow for Fortinet models: the product's menu tree, terms, table columns and
 * "Create New -> form -> OK" flow, in a neutral Network LABS look (no vendor logo, colours or assets).
 * Every form shows the FortiOS CLI block it sends; /api/cli applies it with the CLI tab's parser. */
'use strict';
(() => {
  const css = document.createElement('style');
  css.textContent = `
  body.fg{background:#eef1f4;margin:0}
  body.fg>header,body.fg>.layout{display:none}
  .fg-app{display:grid;grid-template-columns:230px 1fr;grid-template-rows:52px 1fr;min-height:100vh;font:13px Inter,Arial,sans-serif;color:#1d2a36}
  .fg-top{grid-column:1/-1;display:flex;align-items:center;gap:18px;padding:0 18px;background:#1c2630;color:#e9eef3}
  .fg-top b{font-size:15px}.fg-top .sub{color:#9fb0c0}.fg-top .grow{flex:1}
  .fg-top button{background:#2b3846;color:#e9eef3;border:1px solid #3c4b5a;border-radius:4px;padding:6px 12px}
  .fg-pill{display:inline-flex;align-items:center;gap:7px;border-radius:999px;padding:4px 11px;background:#2b3846;font-size:12px}
  .fg-pill i{width:8px;height:8px;border-radius:50%;background:#8a98a6}.fg-pill i.on{background:#3ddc84}
  .fg-nav{background:#26313c;color:#cfd8e1;padding:10px 0;overflow:auto}
  .fg-nav .grp{padding:12px 16px 4px;font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:#8496a8}
  .fg-nav button{display:block;width:100%;text-align:left;background:none;border:0;border-left:3px solid transparent;color:#d7e0e8;
    padding:8px 16px 8px 28px;border-radius:0;font-size:13px}
  .fg-nav button:hover{background:#2f3c49}.fg-nav button.on{background:#334454;border-left-color:#3aa0b8;color:#fff}
  .fg-nav button.na{color:#7d8c9a}.fg-nav button.na:after{content:"  ○";font-size:10px;color:#6b7a88}
  .fg-na{max-width:680px;background:#fff;border:1px solid #d5dde5;border-radius:4px;padding:18px 20px}
  .fg-na b{display:block;font-size:15px;margin-bottom:6px}.fg-legend{padding:14px 16px;font-size:11px;color:#7d8c9a}
  .fg-main{padding:18px 22px;overflow:auto}
  .fg-main h1{font-size:18px;margin:0 0 4px}.fg-main .lead{color:#647587;margin:0 0 14px;font-size:12px}
  .fg-bar{display:flex;gap:8px;align-items:center;margin-bottom:10px}
  .fg-bar button{border-radius:4px;padding:6px 12px;border:1px solid #c9d3dc;background:#fff;color:#1d2a36}
  .fg-bar button.new{background:#1f7a8c;border-color:#1f7a8c;color:#fff}.fg-bar button:disabled{opacity:.45}
  .fg-bar input{margin-left:auto;border-radius:4px;padding:6px 10px;border:1px solid #c9d3dc;min-width:200px}
  .fg-table{background:#fff;border:1px solid #d5dde5;border-radius:4px;overflow:auto}
  .fg-table table{width:100%;border-collapse:collapse;font-size:12.5px}
  .fg-table th{background:#f3f6f8;text-align:left;font-weight:600;padding:8px 10px;border-bottom:1px solid #d5dde5;white-space:nowrap}
  .fg-table td{padding:8px 10px;border-bottom:1px solid #edf1f4;white-space:nowrap}
  .fg-table tr.sel td{background:#e3f1f4}.fg-table tbody tr{cursor:pointer}.fg-table tbody tr:hover td{background:#f2f8fa}
  .fg-obj{display:inline-flex;align-items:center;gap:5px;background:#eef3f7;border:1px solid #d5dfe8;border-radius:3px;padding:1px 7px}
  .fg-acc{color:#167a3e;font-weight:600}.fg-den{color:#b42323;font-weight:600}
  .fg-on{color:#167a3e}.fg-off{color:#8a98a6}
  .fg-widgets{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
  .fg-w{background:#fff;border:1px solid #d5dde5;border-radius:4px}
  .fg-w h3{margin:0;padding:9px 12px;font-size:13px;border-bottom:1px solid #edf1f4;background:#f7f9fb}
  .fg-w .body{padding:12px}
  .fg-kv{display:grid;grid-template-columns:130px 1fr;gap:6px 10px}.fg-kv span{color:#647587}
  .fg-big{font-size:30px;font-weight:600}
  .fg-ports{display:flex;gap:8px;flex-wrap:wrap}
  .fg-port{width:54px;text-align:center;font-size:11px}
  .fg-port .j{height:26px;border-radius:3px;background:#2a3540;border:2px solid #8a98a6;margin-bottom:4px}
  .fg-port.up .j{border-color:#3ddc84}
  .fg-panel{position:fixed;top:52px;right:0;bottom:0;width:min(560px,94vw);background:#fff;box-shadow:-10px 0 30px rgba(0,0,0,.18);
    display:flex;flex-direction:column;z-index:5}
  .fg-panel h2{margin:0;padding:14px 18px;font-size:16px;border-bottom:1px solid #e3e9ee}
  .fg-panel form{flex:1;overflow:auto;padding:14px 18px;display:grid;grid-template-columns:150px 1fr;gap:10px 14px;align-content:start}
  .fg-panel label{color:#4a5b6c;padding-top:7px}
  .fg-panel input,.fg-panel select{border-radius:4px;border:1px solid #c9d3dc;padding:6px 9px}
  .fg-panel .full{grid-column:1/-1}
  .fg-panel pre{grid-column:1/-1;background:#111a22;color:#cfe3f0;border-radius:4px;padding:10px 12px;font:12px "DejaVu Sans Mono",monospace;
    margin:6px 0 0;white-space:pre-wrap}
  .fg-panel .err{grid-column:1/-1;color:#b42323;min-height:16px}
  .fg-panel .acts{display:flex;justify-content:flex-end;gap:8px;padding:12px 18px;border-top:1px solid #e3e9ee}
  .fg-panel .acts button{border-radius:4px;padding:7px 16px}.fg-panel .acts .ok{background:#1f7a8c;color:#fff;border-color:#1f7a8c}
  .fg-seg{display:flex}.fg-seg label{padding:6px 14px;border:1px solid #c9d3dc;margin:0;cursor:pointer;color:#1d2a36}
  .fg-seg label:first-child{border-radius:4px 0 0 4px}.fg-seg label:last-child{border-radius:0 4px 4px 0;border-left:0}
  .fg-seg input{display:none}.fg-seg input:checked+span{font-weight:700;color:#1f7a8c}
  .fg-toast{position:fixed;left:250px;bottom:16px;background:#1c2630;color:#fff;padding:10px 14px;border-radius:6px;max-width:60vw;
    box-shadow:0 6px 20px rgba(0,0,0,.25);z-index:6}
  .fg-toast.bad{background:#8c1d1d}
  .fg-note{font-size:12px;color:#647587;margin-top:10px}
  .fg-face{display:flex;align-items:center;gap:20px;background:linear-gradient(180deg,#34404b,#1d252d);border-radius:6px;
    padding:14px 20px;margin-bottom:14px;color:#cfd8e1;box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 3px 10px rgba(16,24,32,.18)}
  .fg-plate{min-width:120px}.fg-plate b{display:block;font-size:16px;color:#fff;letter-spacing:.3px}.fg-plate span{font-size:11px;color:#9fb0c0}
  .fg-leds{display:flex;gap:12px;margin-top:10px;font-size:9.5px;color:#9fb0c0}.fg-leds span{display:flex;align-items:center;gap:5px}
  .fg-leds i{width:7px;height:7px;border-radius:50%;background:#56636f}.fg-leds i.on{background:#3ddc84;box-shadow:0 0 6px #3ddc84}
  .fg-faceports{display:flex;gap:8px;flex-wrap:wrap;flex:1}
  .fg-fp{width:66px;text-align:center;cursor:pointer}.fg-fp.spare{opacity:.4;cursor:default}
  .fg-fp .num{display:block;font-size:10.5px;font-weight:600;color:#dfe7ee;margin-bottom:4px}
  .fg-fp .jack{position:relative;height:30px;margin:0 9px;border-radius:3px;background:#0b1015;border:1px solid #56636f}
  .fg-fp .jack:after{content:'';position:absolute;left:30%;right:30%;bottom:-1px;height:7px;background:#1d252d;border:1px solid #56636f;border-bottom:0}
  .fg-fp .led{position:absolute;top:3px;width:7px;height:4px;border-radius:1px;background:#3a4652}.fg-fp .l{left:4px}.fg-fp .r{right:4px}
  .fg-fp.up .l{background:#3ddc84;box-shadow:0 0 5px #3ddc84}.fg-fp.up .r{background:#f5b041}.fg-fp.down .l{background:#e04f4f}
  .fg-fp:not(.spare):hover .jack{border-color:#3aa0b8}
  .fg-fp .addr{display:block;margin-top:4px;font-size:10px;color:#9fb0c0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .fg-w.wide{grid-column:span 2}.fg-w.full{grid-column:1/-1}.fg-w .body.flush{padding:0}
  .fg-w table{width:100%;border-collapse:collapse;font-size:12px}.fg-w th{background:#fafbfc;font-weight:600;color:#4a5b6c}
  .fg-w th,.fg-w td{text-align:left;padding:7px 12px;border-bottom:1px solid #edf1f4;white-space:nowrap}
  .fg-w tr:last-child td{border-bottom:0}.fg-empty{margin:0;padding:14px 12px;color:#7d8c9a;font-size:12px}
  .fg-big small{font-size:15px;color:#7d8c9a;font-weight:500}
  .fg-meter{display:flex;height:8px;border-radius:4px;background:#e6ecf1;overflow:hidden;margin:12px 0 8px}.fg-meter i{display:block;height:100%}
  .fg-legend2{display:flex;gap:12px;font-size:11px;color:#647587}.fg-legend2 span{display:flex;align-items:center;gap:5px}
  .fg-legend2 i{width:8px;height:8px;border-radius:2px;display:inline-block}
  .fg-tag{display:inline-block;border-radius:3px;padding:1px 7px;font-size:11px}.fg-tag.c{background:#e3f1f4;color:#1f6f80}
  .fg-tag.s{background:#eef0fb;color:#3c4ca0}
  `;
  document.head.appendChild(css);

  // The FortiOS menu tree. Items the lab runs are pages; 'elsewhere' points to where the app offers it; the rest says why not.
  const ENGINE = 'Nécessite les moteurs d’inspection du constructeur, absents d’un nœud Linux.';
  const LATER = 'Pas encore relié à ce modèle dans le laboratoire (prévu).';
  const PAGES = [
    ['Dashboard', [['status', 'Status'], ['x-dash-sec', 'Security', ENGINE], ['x-dash-net', 'Network', 'Voir Status et le relevé de l’état réel.']]],
    ['Security Fabric', [['x-fabric', 'Physical Topology', 'Voir la topologie de l’application.'], ['x-fabric2', 'Fabric Connectors', 'Service du constructeur (Security Fabric).']]],
    ['Network', [['interfaces', 'Interfaces'], ['x-dns', 'DNS', LATER], ['x-capture', 'Packet Capture', 'Disponible : onglet PCAP de l’application.'],
      ['x-sdwan', 'SD-WAN', 'Moteur SD-WAN du constructeur.'], ['routes', 'Static Routes'], ['x-pbr', 'Policy Routes', LATER],
      ['x-ospf', 'OSPF', LATER], ['x-bgp', 'BGP', LATER], ['x-diag', 'Diagnostics', 'Disponible : onglet CLI, « execute ping ».']]],
    ['Policy & Objects', [['policy', 'Firewall Policy'], ['x-addr', 'Addresses', 'Les politiques acceptent un réseau a.b.c.d/nn ou « all ».'],
      ['x-svc', 'Services', 'Services prédéfinis et TCP-n / UDP-n dans la politique.'], ['x-sched', 'Schedules', 'Toujours « always » dans le laboratoire.'],
      ['vip', 'Virtual IPs'], ['x-pool', 'IP Pools', 'NAT de politique : adresse de l’interface de sortie uniquement.'], ['x-shape', 'Traffic Shaping', LATER]]],
    ['Security Profiles', [['x-av', 'AntiVirus', ENGINE], ['x-web', 'Web Filter', ENGINE], ['x-app', 'Application Control', ENGINE],
      ['x-ips', 'Intrusion Prevention', ENGINE], ['x-ssl', 'SSL/SSH Inspection', ENGINE]]],
    ['VPN', [['x-ipsec', 'IPsec Tunnels', 'Pas de moteur IPsec dans l’image invitée du laboratoire.'], ['x-sslvpn', 'SSL-VPN Settings', 'Service VPN SSL du constructeur.']]],
    ['User & Authentication', [['x-users', 'User Definition', LATER], ['x-radius', 'RADIUS Servers', LATER]]],
    ['System', [['x-admin', 'Administrators', 'Accès par l’application ; pas de comptes du boîtier.'], ['settings', 'Settings'],
      ['x-ha', 'HA', 'Cluster du constructeur.'], ['x-snmp', 'SNMP', LATER], ['x-fw', 'Firmware', 'Le nœud exécute Linux : pas de firmware du constructeur.'],
      ['x-guard', 'FortiGuard', 'Service en ligne du constructeur.']]],
    ['Log & Report', [['x-traffic', 'Forward Traffic', 'Sessions suivies : Status (relevé de l’état réel).'], ['x-logset', 'Log Settings', LATER]]],
  ];
  const ITEMS = Object.fromEntries(PAGES.flatMap(([group, items]) => items.map(([id, label, why]) => [id, {group, label, why}])));
  const SERVICES = ['ALL', 'ALL_ICMP', 'HTTP', 'HTTPS', 'SSH', 'DNS', 'TELNET'];
  // The page asked for in the link (the main script keeps it in « page » after it clears the URL): Status by default.
  const ASKED = {dashboard: 'status', overview: 'status', firewall: 'policy', nat: 'vip', routing: 'routes', interfaces: 'interfaces'};
  let fgPage = ASKED[typeof page === 'string' ? page : ''] || 'status', selected = null, filter = '', standard = false, toastTimer = null;
  const app = document.createElement('div');
  app.className = 'fg-app';
  const q = value => JSON.stringify(String(value));
  const mask = prefix => [0, 8, 16, 24].map(shift => (prefix >= shift + 8 ? 255 : prefix <= shift ? 0 : 256 - 2 ** (8 - (prefix - shift)))).join('.');
  const ipMask = cidr => { const [ip, p] = cidr.split('/'); return `${ip} ${mask(Number(p))}`; };
  const portName = port => (state.device.port_names || {})[port] || port;
  const ports = () => Object.keys(state.node.interfaces);
  const fw = () => state.node.firewall || {rules: [], nat: []};
  const serviceOf = r => {
    const map = {any: 'ALL', icmp: 'ALL_ICMP'}, named = {'tcp/80': 'HTTP', 'tcp/443': 'HTTPS', 'tcp/22': 'SSH', 'udp/53': 'DNS', 'tcp/23': 'TELNET'};
    if (!r.dport) return map[r.protocol || 'any'] || (r.protocol || 'any').toUpperCase();
    return named[`${r.protocol}/${r.dport}`] || `${r.protocol.toUpperCase()}-${r.dport}`;
  };

  function toast(text, bad = false) {
    let box = document.querySelector('.fg-toast');
    if (!box) { box = document.createElement('div'); box.className = 'fg-toast'; document.body.append(box); }
    box.textContent = text; box.classList.toggle('bad', bad); box.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { box.hidden = true; }, bad ? 9000 : 4500);
  }

  async function send(text) {
    state = await request('/api/cli', {node, revision: state.revision, text});
    render();
  }

  function panel(title, fields, commands) {
    document.querySelector('.fg-panel')?.remove();
    const box = document.createElement('div');
    box.className = 'fg-panel';
    box.innerHTML = `<h2>${esc(title)}</h2><form>${fields}<div class="full muted">Équivalent CLI FortiOS (envoyé tel quel)</div><pre></pre>
      <div class="err"></div></form><div class="acts"><button type="button" class="cancel">Cancel</button><button type="button" class="ok">OK</button></div>`;
    document.body.append(box);
    const preview = () => { try { box.querySelector('pre').textContent = commands(box).join('\n'); box.querySelector('.err').textContent = ''; }
      catch (error) { box.querySelector('pre').textContent = ''; box.querySelector('.err').textContent = error.message; } };
    box.querySelector('form').addEventListener('input', preview);
    box.querySelector('form').addEventListener('change', preview);
    box.querySelector('.cancel').onclick = () => box.remove();
    box.querySelector('.ok').onclick = async () => {
      try { await send(commands(box).join('\n')); box.remove(); toast('Appliqué au brouillon du laboratoire. Enregistrer puis redémarrer pour l’activer.'); }
      catch (error) { box.querySelector('.err').textContent = error.message; }
    };
    preview();
    return box;
  }
  const field = (id, label, value = '', extra = '') => `<label for="${id}">${esc(label)}</label><input id="${id}" value="${esc(value)}" ${extra}>`;
  const choice = (id, label, value, options) => `<label for="${id}">${esc(label)}</label><select id="${id}">${options.map(([v, t]) =>
    `<option value="${esc(v)}"${String(v) === String(value) ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select>`;
  const val = (box, id) => box.querySelector('#' + id).value.trim();
  const cidrOrAll = (text, label) => {
    if (!text || text.toLowerCase() === 'all') return 'all';
    if (!/^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/.test(text)) throw Error(`${label} : « all » ou un réseau a.b.c.d/nn.`);
    return text;
  };

  function table(head, rows, onSelect) {
    const wrap = document.createElement('div');
    wrap.className = 'fg-table';
    wrap.innerHTML = `<table><thead><tr>${head.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map((r, i) =>
      `<tr data-i="${i}"${selected === i ? ' class="sel"' : ''}>${r.cells.map(c => `<td>${c}</td>`).join('')}</tr>`).join('')
      || `<tr><td colspan="${head.length}" class="muted">Aucune entrée.</td></tr>`}</tbody></table>`;
    wrap.querySelectorAll('tbody tr[data-i]').forEach(tr => {
      tr.onclick = () => { selected = Number(tr.dataset.i); onSelect(); };
      tr.ondblclick = () => { selected = Number(tr.dataset.i); rows[selected].edit(); };
    });
    return wrap;
  }

  function toolbar(main, {create, edit, remove}, count) {
    const bar = document.createElement('div');
    bar.className = 'fg-bar';
    bar.innerHTML = `${create ? '<button class="new">+ Create New</button>' : ''}${edit ? '<button class="edit">✎ Edit</button>' : ''}
      ${remove ? '<button class="del">🗑 Delete</button>' : ''}<input type="search" placeholder="Search" value="${esc(filter)}">`;
    if (create) bar.querySelector('.new').onclick = create;
    if (edit) { bar.querySelector('.edit').disabled = selected === null || selected >= count; bar.querySelector('.edit').onclick = edit; }
    if (remove) { bar.querySelector('.del').disabled = selected === null || selected >= count; bar.querySelector('.del').onclick = remove; }
    bar.querySelector('input').oninput = event => { filter = event.target.value; selected = null; draw(); };
    main.append(bar);
  }
  const matches = cells => !filter || cells.join(' ').toLowerCase().includes(filter.toLowerCase());

  // ---- pages ----
  function statusPage(main) {
    const d = state.device, n = state.node, rules = fw().rules, live = state.live, running = state.observed === 'running';
    const accept = rules.filter(r => r.action === 'accept').length, deny = rules.length - accept;
    const faceports = [...d.ports, ...d.spare.map(name => ({name, spare: true}))];
    const up = d.ports.filter(p => p.peer && !p.down).length;
    const addressed = d.ports.filter(p => p.address).length;
    const percent = (part, whole) => whole ? Math.round(100 * part / whole) : 0;
    const port = p => {
      const kind = p.spare ? 'spare' : p.down ? 'down' : p.peer ? 'up' : 'free';
      const tip = p.spare ? `${p.name} · port du modèle non déclaré dans le laboratoire`
        : `${p.name}${p.address ? ' · ' + p.address : ''}${p.peer ? ' · câblé vers ' + p.peer : ' · libre'}${p.down ? ' · arrêté' : ''}`;
      return `<div class="fg-fp ${kind}" title="${esc(tip)}"><span class="num">${esc(p.name)}</span>
        <div class="jack"><i class="led l"></i><i class="led r"></i></div>
        <span class="addr">${p.spare ? '&nbsp;' : esc(p.address ? p.address.split('/')[0] : p.peer ? 'sans IP' : '—')}</span></div>`;
    };
    const routeRows = [...d.connected.map(r => [esc(r.network), '<span class="muted">—</span>', esc(r.port), '<span class="fg-tag c">Connected</span>']),
      ...d.static.map(r => [esc(r.network), esc(r.gateway), esc(r.port), '<span class="fg-tag s">Static</span>'])];
    const interfaceRows = d.ports.map(p => [`<b>${esc(p.name)}</b>`, esc(p.address ? ipMask(p.address) : '0.0.0.0 0.0.0.0'),
      esc(p.peer || '—'), p.down ? '<span class="fg-den">● Down</span>' : p.peer ? '<span class="fg-acc">● Up</span>' : '<span class="fg-off">● Libre</span>']);
    const mini = (head, rows, empty) => rows.length ? `<table><thead><tr>${head.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${
      rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>` : `<p class="fg-empty">${esc(empty)}</p>`;
    const policyRows = rules.slice(0, 6).map((r, i) => [String(i + 1), `<b>${esc(r.name)}</b>`,
      esc(`${r.in ? portName(r.in) : 'any'} → ${r.out ? portName(r.out) : 'any'}`), esc(serviceOf(r)),
      r.action === 'accept' ? '<span class="fg-acc">✔ ACCEPT</span>' : '<span class="fg-den">✖ DENY</span>']);
    main.insertAdjacentHTML('beforeend', `<h1>Status</h1><p class="lead">Vue d’ensemble de ${esc(n.name)} : la configuration du
      laboratoire${live ? ', et le relevé de ' + esc(live.time) : ''}.</p>
      <div class="fg-face"><div class="fg-plate"><b>${esc(d.model)}</b><span>${esc(d.brand)}</span>
        <div class="fg-leds"><span><i class="on"></i>PWR</span><span><i class="${running ? 'on' : ''}"></i>STATUS</span></div></div>
        <div class="fg-faceports">${faceports.map(port).join('')}</div></div>
      <div class="fg-widgets">
        <div class="fg-w"><h3>System Information</h3><div class="body fg-kv"><span>Hostname</span><b>${esc(n.name)}</b>
          <span>Model</span><b>${esc(d.brand)} ${esc(d.model)}</b><span>Firmware</span><b>Linux · Network LABS</b>
          <span>Mode</span><b>NAT</b><span>CLI</span><b>FortiOS (sous-ensemble)</b><span>Runtime</span><b>${esc(d.runtime)}</b>
          <span>État</span><b>${running ? '<span class="fg-acc">● En marche</span>' : '<span class="fg-off">○ Non observé</span>'}</b></div></div>
        <div class="fg-w"><h3>Interfaces</h3><div class="body"><div class="fg-big">${up}<small> / ${d.ports.length}</small></div>
          <div class="muted">ports câblés et actifs · ${addressed} avec une adresse</div>
          <div class="fg-meter"><i style="width:${percent(up, d.ports.length)}%;background:#3ddc84"></i></div>
          <div class="fg-legend2"><span><i style="background:#3ddc84"></i>Up ${up}</span><span><i style="background:#c9d3dc"></i>Libres ${
            d.ports.filter(p => !p.peer).length}</span><span><i style="background:#e04f4f"></i>Arrêtés ${d.ports.filter(p => p.down).length}</span></div></div></div>
        <div class="fg-w"><h3>Security Policies</h3><div class="body"><div class="fg-big">${rules.length}</div>
          <div class="muted">politiques · action par défaut ${fw().default === 'accept' ? 'ACCEPT' : 'DENY'}</div>
          <div class="fg-meter">${rules.length ? `<i style="width:${percent(accept, rules.length)}%;background:#2e9d5b"></i><i style="width:${
            percent(deny, rules.length)}%;background:#c0392b"></i>` : ''}</div>
          <div class="fg-legend2"><span><i style="background:#2e9d5b"></i>ACCEPT ${accept}</span><span><i style="background:#c0392b"></i>DENY ${deny}</span>
          <span><i style="background:#1f7a8c"></i>NAT ${fw().nat.length}</span></div></div></div>
        <div class="fg-w wide"><h3>Network Interfaces</h3><div class="body flush">${mini(['Name', 'IP/Netmask', 'Câble vers', 'Status'], interfaceRows,
          'Aucun port déclaré.')}</div></div>
        <div class="fg-w"><h3>Sessions</h3><div class="body"><div class="fg-big">${live && live.sessions ? live.sessions.length : '—'}</div>
          <div class="muted">${live ? 'relevé à ' + esc(live.time) : 'Lab en marche : « Vue Network LABS » → Relever l’état réel.'}</div></div></div>
        <div class="fg-w full"><h3>Routing Monitor</h3><div class="body flush">${mini(['Destination', 'Gateway', 'Interface', 'Type'], routeRows,
          'Aucune route : donner une adresse à un port (Network › Interfaces).')}</div></div>
        <div class="fg-w full"><h3>Firewall Policy</h3><div class="body flush">${mini(['ID', 'Name', 'From → To', 'Service', 'Action'], policyRows,
          'Aucune politique : Policy & Objects › Firewall Policy › Create New.')}</div></div>
      </div>`);
    main.querySelectorAll('.fg-fp:not(.spare)').forEach((element, index) => {
      element.onclick = () => { fgPage = 'interfaces'; selected = index; draw(); };
    });
  }

  function interfacesPage(main) {
    main.insertAdjacentHTML('beforeend', '<h1>Interfaces</h1><p class="lead">Ports physiques du modèle déclarés dans le laboratoire.</p>');
    const rows = ports().map(p => {
      const address = state.node.interfaces[p];
      const server = state.node.dhcp_server;
      const dhcp = server && server.interface === p ? `<span class="fg-on">✔ ${esc(server.start)} – ${esc(server.end)}</span>` : '<span class="fg-off">—</span>';
      const cells = [`<b>${esc(portName(p))}</b>`, 'Physical Interface', address ? esc(ipMask(address)) : '0.0.0.0 0.0.0.0', dhcp,
        esc(state.device.ports.find(x => x.port === p)?.peer || '—'), `<span class="muted">${esc(p)}</span>`];
      return {cells, edit: () => interfaceForm(p, address)};
    }).filter(r => matches(r.cells));
    toolbar(main, {edit: () => rows[selected]?.edit()}, rows.length);
    main.append(table(['Name', 'Type', 'IP/Netmask', 'DHCP Server', 'Connected to', 'Linux'], rows, draw));
  }

  function interfaceForm(p, address) {
    const server = state.node.dhcp_server, mine = server && server.interface === p, other = server && !mine;
    panel(`Edit Interface · ${portName(p)}`,
      field('fgIp', 'IP/Netmask', address || '', 'placeholder="a.b.c.d/nn"') + `<label>Interface Linux</label><div style="padding-top:7px">${esc(p)}</div>`
      + `<div class="full" style="font-weight:600;margin-top:8px">DHCP Server</div>`
      + `<label>DHCP Server</label><label style="padding-top:7px"><input type="checkbox" id="fgDhcp"${mine ? ' checked' : ''}${other ? ' disabled' : ''}>
        ${other ? 'Déjà actif sur ' + esc(portName(server.interface)) + ' (un seul serveur par équipement)' : 'Activer'}</label>`
      + field('fgStart', 'Address range · start', mine ? server.start : '') + field('fgEnd', 'Address range · end', mine ? server.end : '')
      + field('fgGwD', 'Default gateway', mine ? server.router || '' : (address || '').split('/')[0])
      + field('fgDns', 'DNS server', mine ? (server.dns || [])[0] || '' : '') + field('fgLease', 'Lease time (s)', mine ? server.lease_seconds : 600),
      box => {
        const ip = val(box, 'fgIp'), dotted = /^\d{1,3}(\.\d{1,3}){3}$/;
        if (!/^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/.test(ip)) throw Error('IP/Netmask : a.b.c.d/nn.');
        const lines = ['config system interface', `    edit ${q(portName(p))}`, `        set ip ${ipMask(ip)}`, '    next', 'end'];
        const on = box.querySelector('#fgDhcp').checked;
        if (on) {
          if (!dotted.test(val(box, 'fgStart')) || !dotted.test(val(box, 'fgEnd'))) throw Error('Address range : a.b.c.d – a.b.c.d.');
          if (val(box, 'fgGwD') && !dotted.test(val(box, 'fgGwD'))) throw Error('Default gateway : a.b.c.d.');
          if (val(box, 'fgDns') && !dotted.test(val(box, 'fgDns'))) throw Error('DNS server : a.b.c.d.');
          if (!/^\d+$/.test(val(box, 'fgLease'))) throw Error('Lease time : secondes.');
          lines.push('config system dhcp server', '    edit 1', `        set interface ${q(portName(p))}`, `        set netmask ${mask(Number(ip.split('/')[1]))}`,
            ...(val(box, 'fgGwD') ? [`        set default-gateway ${val(box, 'fgGwD')}`] : []), ...(val(box, 'fgDns') ? [`        set dns-server1 ${val(box, 'fgDns')}`] : []),
            `        set lease-time ${val(box, 'fgLease')}`, '        config ip-range', '            edit 1', `                set start-ip ${val(box, 'fgStart')}`,
            `                set end-ip ${val(box, 'fgEnd')}`, '            next', '        end', '    next', 'end');
        } else if (mine) {
          lines.push('config system dhcp server', '    delete 1', 'end');
        }
        return lines;
      });
  }

  function routesPage(main) {
    main.insertAdjacentHTML('beforeend', '<h1>Static Routes</h1><p class="lead">Routes statiques IPv4 du boîtier (la route par défaut comprise).</p>');
    const statics = state.device.static;
    const rows = statics.map((r, i) => ({cells: [esc(String(i + 1)), `<b>${esc(r.network)}</b>`, esc(r.gateway), esc(r.port), '<span class="fg-on">● Enabled</span>'],
      edit: () => routeForm(i + 1, r)})).filter(r => matches(r.cells));
    toolbar(main, {create: () => routeForm(statics.length + 1, null), edit: () => rows[selected]?.edit(),
      remove: () => confirmSend(`Supprimer la route ${selected + 1} ?`, ['config router static', `    delete ${selected + 1}`, 'end'])}, rows.length);
    main.append(table(['ID', 'Destination', 'Gateway IP', 'Interface', 'Status'], rows, draw));
  }
  function routeForm(id, route) {
    panel(route ? `Edit Static Route ${id}` : 'New Static Route',
      field('fgDst', 'Destination', route ? route.network : '', 'placeholder="0.0.0.0/0 ou a.b.c.d/nn"') + field('fgGw', 'Gateway Address', route ? route.gateway : '') +
      choice('fgDev', 'Interface', route ? route.port : portName(ports()[0]), ports().map(p => [portName(p), portName(p)])),
      box => { const dst = val(box, 'fgDst') || '0.0.0.0/0';
        if (!/^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/.test(dst)) throw Error('Destination : a.b.c.d/nn.');
        if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(val(box, 'fgGw'))) throw Error('Gateway Address : a.b.c.d.');
        return ['config router static', `    edit ${id}`, ...(dst === '0.0.0.0/0' ? [] : [`        set dst ${ipMask(dst)}`]),
          `        set gateway ${val(box, 'fgGw')}`, `        set device ${q(val(box, 'fgDev'))}`, '    next', 'end']; });
  }

  function policyPage(main) {
    main.insertAdjacentHTML('beforeend', '<h1>Firewall Policy</h1><p class="lead">Politiques évaluées de haut en bas ; le trafic non autorisé suit l’action par défaut ('
      + (fw().default === 'accept' ? 'ACCEPT' : 'DENY') + ').</p>');
    const nat = new Set(fw().nat.map(r => r.name));
    const rows = fw().rules.map((r, i) => ({cells: [esc(String(i + 1)), `<b>${esc(r.name)}</b>`,
      `<span class="fg-obj">⇄ ${esc(r.in ? portName(r.in) : 'any')}</span>`, `<span class="fg-obj">⇄ ${esc(r.out ? portName(r.out) : 'any')}</span>`,
      `<span class="fg-obj">▣ ${esc(r.source || 'all')}</span>`, `<span class="fg-obj">▣ ${esc(r.destination || 'all')}</span>`,
      '<span class="fg-obj">◷ always</span>', `<span class="fg-obj">${esc(serviceOf(r))}</span>`,
      r.action === 'accept' ? '<span class="fg-acc">✔ ACCEPT</span>' : '<span class="fg-den">✖ DENY</span>',
      nat.has(r.name + '-nat') ? '<span class="fg-on">✔ Enabled</span>' : '<span class="fg-off">Disabled</span>'],
      edit: () => policyForm(i + 1, r, nat.has(r.name + '-nat'))})).filter(r => matches(r.cells));
    toolbar(main, {create: () => policyForm(fw().rules.length + 1, null, false), edit: () => rows[selected]?.edit(),
      remove: () => confirmSend(`Supprimer la politique ${selected + 1} ?`, ['config firewall policy', `    delete ${selected + 1}`, 'end'])}, rows.length);
    main.append(table(['ID', 'Name', 'From', 'To', 'Source', 'Destination', 'Schedule', 'Service', 'Action', 'NAT'], rows, draw));
    const central = fw().nat.filter(r => r.type !== 'dnat' && !fw().rules.some(p => p.name + '-nat' === r.name));
    if (central.length) main.insertAdjacentHTML('beforeend', `<p class="fg-note">Traductions source hors politique (définies ailleurs dans le projet) : ${central.map(r =>
      esc(`${r.name} → ${portName(r.out)}`)).join(', ')}.</p>`);
  }
  function policyForm(id, rule, natOn) {
    const opts = [['any', 'any'], ...ports().map(p => [portName(p), portName(p)])];
    const service = rule ? serviceOf(rule) : 'ALL';
    panel(rule ? `Edit Policy · ${rule.name}` : 'New Policy',
      field('fgName', 'Name', rule ? rule.name : '', 'maxlength="35"') + choice('fgIn', 'Incoming Interface', rule && rule.in ? portName(rule.in) : 'any', opts)
      + choice('fgOut', 'Outgoing Interface', rule && rule.out ? portName(rule.out) : 'any', opts)
      + field('fgSrc', 'Source', rule ? rule.source || 'all' : 'all') + field('fgDstA', 'Destination', rule ? rule.destination || 'all' : 'all')
      + '<label>Schedule</label><div style="padding-top:7px">always</div>'
      + choice('fgSvc', 'Service', SERVICES.includes(service) ? service : 'custom', [...SERVICES.map(s => [s, s]), ['custom', 'Autre (TCP-n / UDP-n)']])
      + field('fgSvcC', 'Service personnalisé', SERVICES.includes(service) ? '' : service, 'placeholder="TCP-8080"')
      + `<label>Action</label><div class="fg-seg"><label><input type="radio" name="fgAct" value="accept"${!rule || rule.action === 'accept' ? ' checked' : ''}>
        <span>✔ ACCEPT</span></label><label><input type="radio" name="fgAct" value="deny"${rule && rule.action !== 'accept' ? ' checked' : ''}><span>✖ DENY</span></label></div>`
      + `<label>NAT</label><label style="padding-top:7px"><input type="checkbox" id="fgNat"${natOn ? ' checked' : ''}> Utiliser l’adresse de l’interface de sortie</label>`,
      box => {
        const name = val(box, 'fgName');
        if (!/^[A-Za-z0-9_.-]{1,35}$/.test(name)) throw Error('Name : lettres, chiffres, « _ », « - », « . » (35 max).');
        const svc = val(box, 'fgSvc') === 'custom' ? val(box, 'fgSvcC').toUpperCase() : val(box, 'fgSvc');
        if (!/^(ALL|ALL_ICMP|HTTP|HTTPS|SSH|DNS|TELNET|(TCP|UDP)-\d{1,5})$/.test(svc)) throw Error('Service : choisir un service ou TCP-n / UDP-n.');
        const act = box.querySelector('input[name=fgAct]:checked').value, natNow = box.querySelector('#fgNat').checked;
        if (natNow && val(box, 'fgOut') === 'any') throw Error('NAT : choisir une interface de sortie.');
        return ['config firewall policy', `    edit ${id}`, `        set name ${q(name)}`, `        set srcintf ${q(val(box, 'fgIn'))}`,
          `        set dstintf ${q(val(box, 'fgOut'))}`, `        set srcaddr ${q(cidrOrAll(val(box, 'fgSrc'), 'Source'))}`,
          `        set dstaddr ${q(cidrOrAll(val(box, 'fgDstA'), 'Destination'))}`, `        set action ${act}`, '        set schedule "always"',
          `        set service ${q(svc)}`, `        set nat ${natNow ? 'enable' : 'disable'}`, '    next', 'end'];
      });
  }

  function vipPage(main) {
    main.insertAdjacentHTML('beforeend', '<h1>Virtual IPs</h1><p class="lead">Publication d’un serveur interne : une adresse externe redirigée vers une adresse mappée (DNAT).</p>');
    const vips = fw().nat.filter(r => r.type === 'dnat');
    const rows = vips.map(v => ({cells: [`<b>${esc(v.name)}</b>`, esc(v.in ? portName(v.in) : 'any'), esc(v.destination.split('/')[0]), esc(v.to),
      v.dport ? esc(`${v.protocol.toUpperCase()} ${v.dport} → ${v.to_port || v.dport}`) : '<span class="fg-off">Disabled</span>'],
      edit: () => vipForm(v), name: v.name})).filter(r => matches(r.cells));
    toolbar(main, {create: () => vipForm(null), edit: () => rows[selected]?.edit(),
      remove: () => confirmSend(`Supprimer la Virtual IP ${rows[selected].name} ?`, ['config firewall vip', `    delete ${q(rows[selected].name)}`, 'end'])}, rows.length);
    main.append(table(['Name', 'Interface', 'External IP', 'Mapped IP', 'Port Forwarding'], rows, draw));
  }
  function vipForm(vip) {
    panel(vip ? `Edit Virtual IP · ${vip.name}` : 'New Virtual IP',
      field('fgVName', 'Name', vip ? vip.name : '', vip ? 'readonly' : '') + choice('fgVIf', 'Interface', vip ? portName(vip.in) : portName(ports()[ports().length - 1]),
        ports().map(p => [portName(p), portName(p)])) + field('fgExt', 'External IP Address', vip ? vip.destination.split('/')[0] : '')
      + field('fgMap', 'Mapped IP Address', vip ? vip.to : '')
      + `<label>Port Forwarding</label><label style="padding-top:7px"><input type="checkbox" id="fgPf"${vip && vip.dport ? ' checked' : ''}> Activer</label>`
      + choice('fgProto', 'Protocol', vip && vip.dport ? vip.protocol : 'tcp', [['tcp', 'TCP'], ['udp', 'UDP']])
      + field('fgEPort', 'External Service Port', vip && vip.dport ? vip.dport : '') + field('fgMPort', 'Map to Port', vip && vip.dport ? vip.to_port || vip.dport : ''),
      box => {
        const name = val(box, 'fgVName'), ip = /^\d{1,3}(\.\d{1,3}){3}$/;
        if (!/^[A-Za-z0-9_.-]{1,40}$/.test(name)) throw Error('Name : lettres, chiffres, « _ », « - », « . ».');
        if (!ip.test(val(box, 'fgExt')) || !ip.test(val(box, 'fgMap'))) throw Error('External IP et Mapped IP : a.b.c.d.');
        const pf = box.querySelector('#fgPf').checked;
        if (pf && !(/^\d{1,5}$/.test(val(box, 'fgEPort')) && /^\d{1,5}$/.test(val(box, 'fgMPort')))) throw Error('Ports : nombres 1–65535.');
        return ['config firewall vip', `    edit ${q(name)}`, `        set extip ${val(box, 'fgExt')}`, `        set mappedip ${q(val(box, 'fgMap'))}`,
          `        set extintf ${q(val(box, 'fgVIf'))}`, ...(pf ? ['        set portforward enable', `        set protocol ${val(box, 'fgProto')}`,
            `        set extport ${val(box, 'fgEPort')}`, `        set mappedport ${val(box, 'fgMPort')}`] : ['        set portforward disable']), '    next', 'end'];
      });
  }

  function unavailablePage(main) {
    const item = ITEMS[fgPage];
    main.insertAdjacentHTML('beforeend', `<h1>${esc(item.label)}</h1><p class="lead">${esc(item.group)} › ${esc(item.label)}</p>
      <div class="fg-na"><b>Non disponible dans le laboratoire</b>${esc(item.why)}<p class="fg-note">Ce menu existe sur le produit réel ;
      il est montré pour situer la fonction. Un réglage sans effet sur le réseau du laboratoire n’est pas proposé.</p></div>`);
  }

  function settingsPage(main) {
    main.insertAdjacentHTML('beforeend', `<h1>Settings</h1><p class="lead">Paramètres système.</p><div class="fg-w"><h3>System</h3><div class="body fg-kv">
      <span>Host name</span><b>${esc(state.node.name)}</b><span>Firmware</span><b>Linux · Network LABS (pas FortiOS)</b>
      <span>CLI</span><b>Sous-ensemble FortiOS, onglet CLI de l’application</b></div></div>
      <p class="fg-note">Renommer l’équipement depuis l’application (Nom système). Ce boîtier exécute Linux : les menus suivent l’organisation
      de FortiOS pour l’apprentissage, sans le système ni l’interface du constructeur.</p>`);
  }

  async function confirmSend(question, lines) {
    if (!window.confirm(question + '\n\n' + lines.join('\n'))) return;
    try { await send(lines.join('\n')); selected = null; toast('Supprimé du brouillon du laboratoire.'); } catch (error) { toast(error.message, true); }
  }

  function draw() {
    const n = state.node, d = state.device;
    const running = state.observed === 'running';
    app.innerHTML = `<div class="fg-top"><b>${esc(n.name)}</b><span class="sub">${esc(d.brand)} ${esc(d.model)} · menus FortiOS · système Linux</span>
      <span class="grow"></span><span class="fg-pill"><i class="${running ? 'on' : ''}"></i>${running ? 'En marche' : 'Non observé'}</span>
      <button class="simple">◐ Design simple</button><button class="std">Vue Network LABS</button><button class="ref">↻</button></div>
      <nav class="fg-nav"></nav><main class="fg-main"></main>`;
    const nav = app.querySelector('nav');
    for (const [group, items] of PAGES) {
      nav.insertAdjacentHTML('beforeend', `<div class="grp">${esc(group)}</div>`);
      for (const [id, label, why] of items) {
        const button = document.createElement('button');
        button.textContent = label; button.classList.toggle('on', id === fgPage); button.classList.toggle('na', Boolean(why));
        button.onclick = () => { fgPage = id; selected = null; filter = ''; document.querySelector('.fg-panel')?.remove(); draw(); };
        nav.append(button);
      }
    }
    nav.insertAdjacentHTML('beforeend', '<div class="fg-legend">○ menu du produit non disponible dans le laboratoire</div>');
    app.querySelector('.std').onclick = () => { standard = true; document.body.classList.remove('fg'); app.remove(); render(); };
    app.querySelector('.ref').onclick = () => load();
    app.querySelector('.simple').onclick = () => window.nlSetDesign && window.nlSetDesign('simple');
    const main = app.querySelector('main');
    const pages = {status: statusPage, interfaces: interfacesPage, routes: routesPage, policy: policyPage, vip: vipPage, settings: settingsPage};
    (pages[fgPage] || unavailablePage)(main);
  }

  const previous = render;
  render = function () {
    previous();
    if (window.nlDesignNow && window.nlDesignNow() === 'simple') { app.remove(); document.body.classList.remove('fg'); return; }  // the « Simple » design draws the page
    if (!state || !state.device || state.device.cli !== 'FortiOS' || standard) return;
    if (!app.isConnected) { document.body.append(app); document.body.classList.add('fg'); }
    if (selected !== null && selected >= 999) selected = null;
    draw();
  };
  window.fortiosView = page => { fgPage = page; if (state) draw(); };
})();
