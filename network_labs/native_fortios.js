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
  `;
  document.head.appendChild(css);

  const PAGES = [['Dashboard', [['status', 'Status']]], ['Network', [['interfaces', 'Interfaces'], ['routes', 'Static Routes']]],
    ['Policy & Objects', [['policy', 'Firewall Policy'], ['vip', 'Virtual IPs']]], ['System', [['settings', 'Settings']]]];
  const SERVICES = ['ALL', 'ALL_ICMP', 'HTTP', 'HTTPS', 'SSH', 'DNS', 'TELNET'];
  let fgPage = 'policy', selected = null, filter = '', standard = false, toastTimer = null;
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
    const d = state.device, rules = fw().rules, live = state.live;
    main.insertAdjacentHTML('beforeend', `<h1>Status</h1><p class="lead">Vue d’ensemble du boîtier simulé.</p><div class="fg-widgets">
      <div class="fg-w"><h3>System Information</h3><div class="body fg-kv"><span>Hostname</span><b>${esc(state.node.name)}</b>
        <span>Model</span><b>${esc(d.brand)} ${esc(d.model)}</b><span>Firmware</span><b>Linux · Network LABS</b>
        <span>Mode</span><b>NAT</b><span>Runtime</span><b>${esc(d.runtime)}</b></div></div>
      <div class="fg-w"><h3>Security Policies</h3><div class="body"><div class="fg-big">${rules.length}</div>
        <div class="muted">${rules.filter(r => r.action === 'accept').length} ACCEPT · ${rules.filter(r => r.action !== 'accept').length} DENY ·
        défaut ${fw().default === 'accept' ? 'ACCEPT' : 'DENY'}</div></div></div>
      <div class="fg-w"><h3>Sessions</h3><div class="body"><div class="fg-big">${live && live.sessions ? live.sessions.length : '—'}</div>
        <div class="muted">${live ? 'relevé à ' + esc(live.time) : 'Relever l’état réel depuis la vue Network LABS (lab en marche).'}</div></div></div>
      <div class="fg-w" style="grid-column:1/-1"><h3>Network Interfaces</h3><div class="body fg-ports">${d.ports.map(p =>
        `<div class="fg-port${p.peer ? ' up' : ''}"><div class="j"></div><b>${esc(p.name)}</b></div>`).join('')}</div></div></div>`);
  }

  function interfacesPage(main) {
    main.insertAdjacentHTML('beforeend', '<h1>Interfaces</h1><p class="lead">Ports physiques du modèle déclarés dans le laboratoire.</p>');
    const rows = ports().map(p => {
      const address = state.node.interfaces[p];
      const cells = [`<b>${esc(portName(p))}</b>`, 'Physical Interface', address ? esc(ipMask(address)) : '0.0.0.0 0.0.0.0',
        esc(state.device.ports.find(x => x.port === p)?.peer || '—'), `<span class="muted">${esc(p)}</span>`];
      return {cells, edit: () => panel(`Edit Interface · ${portName(p)}`,
        field('fgIp', 'IP/Netmask', address || '', 'placeholder="a.b.c.d/nn"') + `<label>Interface Linux</label><div style="padding-top:7px">${esc(p)}</div>`,
        box => { const ip = val(box, 'fgIp'); if (!/^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/.test(ip)) throw Error('IP/Netmask : a.b.c.d/nn.');
          return ['config system interface', `    edit ${q(portName(p))}`, `        set ip ${ipMask(ip)}`, '    next', 'end']; })};
    }).filter(r => matches(r.cells));
    toolbar(main, {edit: () => rows[selected]?.edit()}, rows.length);
    main.append(table(['Name', 'Type', 'IP/Netmask', 'Connected to', 'Linux'], rows, draw));
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
      <button class="std">Vue Network LABS</button><button class="ref">↻</button></div><nav class="fg-nav"></nav><main class="fg-main"></main>`;
    const nav = app.querySelector('nav');
    for (const [group, items] of PAGES) {
      nav.insertAdjacentHTML('beforeend', `<div class="grp">${esc(group)}</div>`);
      for (const [id, label] of items) {
        const button = document.createElement('button');
        button.textContent = label; button.classList.toggle('on', id === fgPage);
        button.onclick = () => { fgPage = id; selected = null; filter = ''; document.querySelector('.fg-panel')?.remove(); draw(); };
        nav.append(button);
      }
    }
    app.querySelector('.std').onclick = () => { standard = true; document.body.classList.remove('fg'); app.remove(); render(); };
    app.querySelector('.ref').onclick = () => load();
    const main = app.querySelector('main');
    ({status: statusPage, interfaces: interfacesPage, routes: routesPage, policy: policyPage, vip: vipPage, settings: settingsPage})[fgPage](main);
  }

  const previous = render;
  render = function () {
    previous();
    if (!state || !state.device || state.device.cli !== 'FortiOS' || standard) return;
    if (!app.isConnected) { document.body.append(app); document.body.classList.add('fg'); }
    if (selected !== null && selected >= 999) selected = null;
    draw();
  };
  window.fortiosView = page => { fgPage = page; if (state) draw(); };
})();
