/* The device pages as copies of the real products' management interfaces: each product's frame, menus, wording, tables,
 * edit dialogs and way of saving (WebFig's OK, Cisco WebUI's « Update & Apply to Device », ASDM's Apply, pfSense's
 * « Apply Changes », PAN-OS's and J-Web's Commit). Drawn by Network LABS: no vendor logo, picture or file. Every change
 * goes through the laboratory's checked actions; when the product has a command set in the laboratory (IOS, RouterOS,
 * Junos, PAN-OS), the page sends the product's own commands, as the real interface does behind its forms.
 * Products covered here: MikroTik (WebFig), Cisco IOS-XE (WebUI), Cisco ASA (ASDM), pfSense, Palo Alto (PAN-OS),
 * Juniper (J-Web), and the products that have no web interface (VyOS, Nokia SR OS, Arista EOS, Dell OS10, Cisco NX-OS):
 * their console. The other devices keep native_vendor.js / native_fortios.js. */
'use strict';
(() => {
  const SKINS = {};
  function pick(d, role) {
    // Printers, NAS, cameras, phones and server management cards: their products' pages (native_products_hosts.js).
    if (role === 'host') { const own = (window.nlProductsKit ? window.nlProductsKit.MATCH : []).find(([test]) => test(d, role)); return own ? own[1] : null; }
    if (d.brand === 'MikroTik') return 'webfig';
    if (d.brand === 'Cisco' && d.model === 'ASA') return 'asdm';
    if (d.brand === 'Cisco' && /^(ISR|Catalyst 9200|Routeur IOS)/.test(d.model)) return 'iosxe';
    if (d.brand === 'Cisco' && /Nexus/.test(d.model)) return 'cli';
    if (d.model === 'pfSense') return 'pfsense';
    if (d.model === 'OPNsense') return 'opnsense';
    if (d.brand === 'Palo Alto') return 'panos';
    if (d.brand === 'Juniper') return 'jweb';
    if (['VyOS', 'Nokia', 'Arista', 'Dell', 'Extreme'].includes(d.brand)) return 'cli';
    const more = (window.nlProductsKit ? window.nlProductsKit.MATCH : []).find(([test]) => test(d, role));
    return more ? more[1] : null;
  }
  window.nlProduct = device => (device && state && state.node ? pick(device, state.node.role) : null);

  // ---- toolkit ----
  const app = document.createElement('div');
  const pill = document.createElement('div');
  let view = {}, standard = false;
  const D = () => state.device, N = () => state.node;
  const h = esc;
  const maskOf = prefix => [0, 8, 16, 24].map(s => (prefix >= s + 8 ? 255 : prefix <= s ? 0 : 256 - 2 ** (8 - (prefix - s)))).join('.');
  const prefixOf = text => {
    const parts = String(text).trim().split('.').map(Number);
    if (parts.length !== 4 || parts.some(p => !(p >= 0 && p <= 255))) return null;
    const bits = parts.map(p => p.toString(2).padStart(8, '0')).join('');
    return /^1*0*$/.test(bits) ? bits.indexOf('0') === -1 ? 32 : bits.indexOf('0') : null;
  };
  const ipOf = cidr => (cidr ? cidr.split('/')[0] : '');
  const lenOf = cidr => (cidr ? Number(cidr.split('/')[1]) : 24);
  const ipNum = ip => ip.split('.').reduce((a, b) => a * 256 + Number(b), 0);
  const numIp = n => [24, 16, 8, 0].map(s => Math.floor(n / 2 ** s) % 256).join('.');
  const networkOf = cidr => { const p = lenOf(cidr); return numIp(Math.floor(ipNum(ipOf(cidr)) / 2 ** (32 - p)) * 2 ** (32 - p)) + '/' + p; };
  const validIp = ip => /^\d{1,3}(\.\d{1,3}){3}$/.test(ip) && ip.split('.').every(x => Number(x) <= 255);
  const fw = () => N().firewall || {default: 'drop', stateful: true, rules: [], nat: []};
  const portByName = name => D().ports.find(p => p.name === name || p.port === name);
  const portName = port => (D().port_names || {})[port] || port;
  const peerName = p => (p.peer ? p.peer.split(' · ')[0] : '');
  const running = () => state.observed === 'running';
  const svc = r => (!r.protocol || r.protocol === 'any' ? 'any' : r.dport ? `${r.protocol}/${r.dport}` : r.protocol);
  const parseService = text => {
    const t = String(text || '').trim().toLowerCase();
    const named = {http: 80, https: 443, ssh: 22, telnet: 23, dns: 53, domain: 53, ftp: 21, smtp: 25, www: 80, rdp: 3389};
    if (!t || ['any', 'ip', 'application-default', 'any-service'].includes(t)) return {protocol: 'any'};
    if (['icmp', 'ping', 'junos-ping', 'icmp-echo'].includes(t)) return {protocol: 'icmp'};
    const m = t.match(/^(?:service-|junos-)?(tcp|udp)?[/\-_ ]?([a-z]+|\d+)?(?:-udp|-tcp)?$/);
    if (!m) throw new Error('Service : any, icmp, tcp/443, udp/53, http, https, ssh, dns…');
    const port = m[2] ? (/^\d+$/.test(m[2]) ? Number(m[2]) : named[m[2]]) : null;
    if (m[2] && !port) throw new Error('Service inconnu : ' + text);
    const protocol = m[1] || (port === 53 ? 'udp' : 'tcp');
    return port ? {protocol, dport: port} : {protocol};
  };
  const cleanRule = r => Object.fromEntries(Object.entries(r).filter(([, v]) => v !== '' && v !== undefined && v !== null && v !== 'any'));

  function toast(text, bad = false) {
    let box = document.querySelector('.px-toast');
    if (!box) { box = document.createElement('div'); box.className = 'px-toast'; document.body.append(box); }
    box.textContent = text;
    box.classList.toggle('bad', bad);
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => box.remove(), bad ? 7000 : 4200);
  }
  let sending = 0;  // saves in flight: the page does not refresh itself under them
  async function send(path, data) {
    sending += 1;
    try { state = await request(path, {node, revision: state.revision, ...data}); } finally { sending -= 1; }
    node = state.node.name;
    return state;
  }
  const cli = text => send('/api/cli', {text});
  const section = (name, config) => send('/api/apply', {section: name, config});
  const setAddress = (port, address, enabled) => send('/api/apply', {name: N().name, port, address, gateway: N().gateway || '',
    enabled: enabled === undefined ? !(N().shutdown || []).includes(port) : enabled});
  const route = (network, gateway) => send('/api/route', {network, gateway});
  async function rename(name) {
    await send('/api/apply', {name, port: Object.keys(N().interfaces)[0], address: Object.values(N().interfaces)[0] || '',
      gateway: N().gateway || '', enabled: !(N().shutdown || []).includes(Object.keys(N().interfaces)[0])});
    view.node = N().name;  // the same page stays open under the new name
    return state;
  }
  async function attempt(work, done) {
    try { await work(); render(); if (done) toast(done); return true; } catch (error) { toast(error.message, true); render(); return false; }
  }
  const openTerminal = () => request('/api/open_cli', {node}).then(() => toast('Terminal ouvert dans Network LABS.'), e => toast(e.message, true));

  // The staged changes of the products that save on Apply / Commit (ASDM, pfSense, PAN-OS, J-Web).
  const stage = () => (view.stage = view.stage || {fw: null, ifaces: {}, routes: {add: [], del: []}, dhcp: undefined, name: null, vlans: null});
  const pending = () => { const s = view.stage; return !s ? 0 : (s.fw ? 1 : 0) + Object.keys(s.ifaces).length + s.routes.add.length + s.routes.del.length
    + (s.dhcp !== undefined ? 1 : 0) + (s.name ? 1 : 0) + (s.vlans ? 1 : 0); };
  const candidateFw = () => (view.stage && view.stage.fw) || fw();
  const editFw = () => { const s = stage(); s.fw = s.fw || JSON.parse(JSON.stringify(fw())); s.fw.rules = s.fw.rules || []; s.fw.nat = s.fw.nat || []; return s.fw; };
  const addressOf = port => (view.stage && port in view.stage.ifaces ? view.stage.ifaces[port] : N().interfaces[port] || '');
  const staticRoutes = () => {
    const s = view.stage || {routes: {add: [], del: []}};
    return [...D().static.filter(r => !s.routes.del.includes(r.network) && !s.routes.add.some(a => a.network === r.network)), ...s.routes.add];
  };
  async function commit(routeCli) {
    const s = view.stage;
    if (!s) return;
    if (s.fw) await section('firewall', {firewall: s.fw});
    for (const [port, address] of Object.entries(s.ifaces)) await setAddress(port, address);
    const lines = routeCli ? [...s.routes.del.map(n => routeCli(n, null)), ...s.routes.add.map(r => routeCli(r.network, r.gateway))] : [];
    if (lines.length) await cli(lines.join('\n'));
    if (!routeCli) {  // brands without a command set: the laboratory's route action
      for (const network of s.routes.del) await route(network, '');
      for (const r of s.routes.add) await route(r.network, r.gateway);
    }
    if (s.dhcp !== undefined) await section('dhcpserver', {dhcp_server: s.dhcp});
    if (s.vlans) await section('switching', s.vlans);
    if (s.name) await rename(s.name);
    view.stage = null;
  }
  const discard = () => { view.stage = null; render(); };

  function dialog(cls, title, body, buttons) {
    document.querySelector('.px-shade')?.remove();
    const shade = document.createElement('div');
    shade.className = 'px-shade ' + cls;
    shade.innerHTML = `<div class="px-dialog" role="dialog"><div class="px-dtitle"><span>${h(title)}</span><button class="px-x" type="button">✕</button></div>
      <div class="px-dbody">${body}<div class="px-err"></div></div><div class="px-dfoot"></div></div>`;
    const close = () => shade.remove();
    shade.querySelector('.px-x').onclick = close;
    const foot = shade.querySelector('.px-dfoot');
    for (const [label, kind, action] of buttons) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = kind || ''; button.textContent = label;
      button.onclick = async () => {
        if (!action) return close();
        const all = [...foot.querySelectorAll('button')];
        all.forEach(b => { b.disabled = true; });  // one save at a time, as on the products
        try { const keep = await action(shade); if (!keep) close(); } catch (error) { shade.querySelector('.px-err').textContent = error.message; }
        finally { all.forEach(b => { b.disabled = false; }); }
      };
      foot.append(button);
    }
    // Enter in a field confirms the window, as on the products.
    shade.addEventListener('keydown', event => {
      if (event.key !== 'Enter' || event.target.tagName !== 'INPUT') return;
      event.preventDefault();
      (foot.querySelector('button.pri') || foot.firstElementChild)?.click();
    });
    app.append(shade);
    shade.querySelector('input,select')?.focus();
    return shade;
  }
  const val = (root, sel) => (root.querySelector(sel)?.value ?? '').trim();
  const field = (label, html, hint = '') => `<label class="px-f"><span>${h(label)}</span>${html}${hint ? `<small>${h(hint)}</small>` : ''}</label>`;
  const input = (id, value = '', extra = '') => `<input id="${id}" value="${h(value)}" ${extra}>`;
  const select = (id, options, chosen) => `<select id="${id}">${options.map(o => { const [v, l] = Array.isArray(o) ? o : [o, o];
    return `<option value="${h(v)}"${String(v) === String(chosen) ? ' selected' : ''}>${h(l)}</option>`; }).join('')}</select>`;
  const table = (cls, head, rows, empty = 'No items') => `<table class="${cls}"><thead><tr>${head.map(c => `<th>${h(c)}</th>`).join('')}</tr></thead><tbody>${
    rows.length ? rows.join('') : `<tr class="px-none"><td colspan="${head.length}">${h(empty)}</td></tr>`}</tbody></table>`;
  const tr = (cells, attrs = '') => `<tr ${attrs}>${cells.map(c => `<td>${c}</td>`).join('')}</tr>`;
  const NA = {
    engine: 'Nécessite les moteurs d’inspection du constructeur, absents du nœud Linux du laboratoire.',
    vpn: 'Pas de moteur VPN dans l’image invitée du laboratoire.',
    later: 'Pas encore relié à ce modèle dans le laboratoire.',
    wireless: 'Pas de radio Wi-Fi dans le laboratoire.',
    cli: 'Disponible dans le terminal de l’équipement (◉ Network LABS › Terminal).',
  };
  const naBox = (what, why) => `<div class="px-na"><b>${h(what)}</b><p>${h(why || NA.later)}</p><small>Ce menu existe sur le produit réel ;
    il est montré pour situer la fonction.</small></div>`;
  // A rule's name in the laboratory is an identifier: the products' free-text descriptions become one (« Block SSH » → Block-SSH).
  const ruleName = text => { const slug = String(text).trim().replace(/\s+/g, '-').replace(/[^A-Za-z0-9_-]/g, '').replace(/^[^A-Za-z]+/, '').slice(0, 32);
    return slug || 'rule-' + (fw().rules.length + 1); };
  const ruleFrom = (base, values) => cleanRule({...base, name: ruleName(values.name), action: values.action, in: values.in || undefined, out: values.out || undefined,
    source: values.source || undefined, destination: values.destination || undefined, ...parseService(values.service)});
  const checkNet = (text, what) => {
    if (!text || text === 'any') return '';
    const [ip, p] = text.split('/');
    if (!validIp(ip) || (p !== undefined && !(Number(p) >= 0 && Number(p) <= 32))) throw new Error(`${what} : any ou a.b.c.d/nn.`);
    return p === undefined ? ip + '/32' : text;
  };

  // ---- NAT: one model behind every product's own window ----
  // masquerade (interface PAT / « hide ») and snat (the interface's address) need the outgoing interface; dnat (a port
  // forward, a VIP) needs the incoming interface, the public destination and the inside address.
  function natBuild(v) {
    const service = parseService(v.service || 'any');
    const e = {name: ruleName(v.name || `nat-${(candidateFw().nat || []).length + 1}`), type: v.type, source: checkNet(v.source, 'Source'),
      destination: checkNet(v.destination, 'Destination'), ...service};
    if (v.type === 'dnat') {
      if (!v.in) throw new Error('Traduction de destination : choisir l’interface d’entrée.');
      if (!e.destination) throw new Error('Traduction de destination : l’adresse publique d’origine (a.b.c.d) est requise.');
      if (!validIp(v.to || '')) throw new Error('Adresse traduite (serveur interne) : a.b.c.d.');
      e.in = v.in;
      e.to = v.to;
      if (v.to_port) {
        if (!service.dport) throw new Error('Port traduit : indiquer aussi le service d’origine (tcp/80, udp/53…).');
        e.to_port = Number(v.to_port);
      }
    } else if (v.type === 'masquerade' || v.type === 'snat') {
      if (!v.out) throw new Error('Traduction de source : choisir l’interface de sortie.');
      e.out = v.out;
      if (v.in) e.in = v.in;
      if (v.type === 'snat') {
        if (!addressOf(v.out)) throw new Error('L’interface de sortie n’a pas d’adresse.');
        e.to = ipOf(addressOf(v.out));
      }
    } else throw new Error('Choisir une traduction (source ou destination).');
    return cleanRule(e);
  }
  // The pieces of a NAT window (ids nx*), each product placing them under its own labels.
  function natPieces(entry, L, iface = portName) {
    const ports = Object.keys(N().interfaces).map(port => [port, iface(port)]);
    const any = [['', L.any || 'any'], ...ports];
    return {name: field(L.name || 'Name', input('nxName', entry.name || '')), in: field(L.in || 'Inbound Interface', select('nxIn', any, entry.in || '')),
      out: field(L.out || 'Outbound Interface', select('nxOut', any, entry.out || '')), source: field(L.source || 'Source', input('nxSrc', entry.source || 'any')),
      destination: field(L.destination || 'Destination', input('nxDst', entry.destination || 'any')),
      service: field(L.service || 'Service', input('nxSvc', entry.protocol && entry.protocol !== 'any' ? svc(entry) : 'any'), L.serviceHint || 'any, tcp/80, udp/53'),
      type: field(L.type || 'Translation', select('nxType', L.types, entry.type || L.types[0][0])), to: field(L.to || 'Translated Address', input('nxTo', entry.type === 'dnat' ? entry.to || '' : '')),
      to_port: field(L.to_port || 'Translated Port', input('nxToPort', entry.to_port || ''))};
  }
  const natRead = root => natBuild({name: val(root, '#nxName'), in: val(root, '#nxIn'), out: val(root, '#nxOut'), source: val(root, '#nxSrc'),
    destination: val(root, '#nxDst'), service: val(root, '#nxSvc'), type: val(root, '#nxType'), to: val(root, '#nxTo'), to_port: val(root, '#nxToPort')});
  // Rules and NAT entries: staged (Apply / Commit products) or sent at once (products that save on OK).
  async function putEntry(list, index, entry, staged) {
    const f = staged ? editFw() : JSON.parse(JSON.stringify(fw()));
    f[list] = f[list] || [];
    if (index === null) f[list].push(entry); else f[list][index] = entry;
    if (!staged) await section('firewall', {firewall: f});
  }
  async function dropEntry(list, index, staged) {
    const f = staged ? editFw() : JSON.parse(JSON.stringify(fw()));
    f[list].splice(index, 1);
    if (!staged) await section('firewall', {firewall: f});
  }
  async function moveEntry(list, index, step, staged) {
    const f = staged ? editFw() : JSON.parse(JSON.stringify(fw())), to = index + step;
    if (to < 0 || to >= f[list].length) return;
    [f[list][index], f[list][to]] = [f[list][to], f[list][index]];
    if (!staged) await section('firewall', {firewall: f});
  }
  // The outside port: the one toward the default gateway, else the first (WAN / outside / untrust / External).
  function wanPort() {
    const ports = Object.keys(N().interfaces), hop = (D().static.find(r => r.network === '0.0.0.0/0') || {}).gateway || N().gateway;
    const inside = hop && ports.find(port => N().interfaces[port] && networkOf(N().interfaces[port]) === networkOf(hop + '/' + lenOf(N().interfaces[port])));
    return inside || ports[0];
  }
  function zoneNames(names) {
    const ports = Object.keys(N().interfaces), wan = wanPort(), rest = ports.filter(p => p !== wan), zones = {[wan]: names[0]};
    rest.forEach((port, i) => { zones[port] = names[i + 1] || `${names[names.length - 1]}${i + 2 - names.length + 1}`; });
    return zones;
  }

  // ---- the Network LABS pill: the laboratory's controls, kept out of the product's screens ----
  pill.className = 'px-pill';
  pill.innerHTML = `<div class="px-pill-menu"><button data-a="load">↻ Actualiser depuis le projet</button><button data-a="cli">⌨ Terminal de l’équipement</button>
    <button data-a="studio">◐ Design Studio</button><button data-a="simple">◧ Design Simple</button><button data-a="std">☰ Vue Network LABS</button></div>
    <button class="px-pill-main" type="button">◉ Network LABS</button>`;
  pill.querySelector('.px-pill-main').onclick = () => pill.classList.toggle('open');
  pill.querySelectorAll('[data-a]').forEach(button => {
    button.onclick = () => {
      pill.classList.remove('open');
      ({load: () => load(), cli: openTerminal, studio: () => window.nlSetDesign && window.nlSetDesign('studio'),
        simple: () => window.nlSetDesign && window.nlSetDesign('simple'), std: () => { standard = true; page = 'dashboard'; render(); }})[button.dataset.a]();
    };
  });

  const css = document.createElement('style');
  css.textContent = `
  body.px{margin:0}body.px>header,body.px>.layout{display:none}
  :where(.px-app,.px-pill) button,:where(.px-app) input,:where(.px-app) select,:where(.px-app) textarea{all:revert;font:inherit;box-sizing:border-box}
  :where(.px-app) input[type=checkbox],:where(.px-app) input[type=radio]{all:revert}:where(.px-app) input[type=checkbox]::after{content:none}
  :where(.px-app) label{all:revert}:where(.px-app) table{font-size:inherit}
  :where(.px-app) th,:where(.px-app) td{padding:revert;border:revert;background:revert;text-align:revert}
  :where(.px-app) main{min-width:0}:where(.px-app) tr:last-child td{border-bottom:revert}:where(.px-app) h1,:where(.px-app) h2{font-size:revert;margin:revert}
  .px-app{min-height:100vh;font:13px Arial,Helvetica,sans-serif}
  .px-pill{position:fixed;right:14px;bottom:14px;z-index:12;font:12px Inter,Arial,sans-serif}
  .px-pill-main{background:rgba(23,40,58,.88);color:#fff;border:1px solid rgba(255,255,255,.18);border-radius:999px;padding:7px 13px;cursor:pointer;
    box-shadow:0 6px 18px rgba(0,0,0,.25)}
  .px-pill-menu{display:none;position:absolute;right:0;bottom:40px;background:#17283a;border-radius:10px;padding:6px;min-width:230px;box-shadow:0 10px 26px rgba(0,0,0,.35)}
  .px-pill.open .px-pill-menu{display:block}
  .px-pill-menu button{display:block;width:100%;text-align:left;background:none;border:0;color:#e6eef6;padding:8px 10px;border-radius:7px;cursor:pointer;font:inherit}
  .px-pill-menu button:hover{background:#24405e}
  .px-toast{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:#24303c;color:#fff;padding:10px 16px;border-radius:4px;z-index:40;
    font:13px Arial,sans-serif;box-shadow:0 6px 20px rgba(0,0,0,.3);max-width:70vw;white-space:pre-wrap}.px-toast.bad{background:#a12a2a}
  .px-shade{position:fixed;inset:0;background:rgba(0,0,0,.32);z-index:20;display:grid;place-items:center}
  .px-dialog{background:#fff;min-width:440px;max-width:720px;max-height:88vh;display:flex;flex-direction:column;box-shadow:0 12px 40px rgba(0,0,0,.35)}
  .px-dtitle{display:flex;align-items:center;justify-content:space-between;padding:9px 12px;font-weight:bold}
  .px-x{border:0;background:none;cursor:pointer;font-size:14px;color:inherit}
  .px-dbody{padding:14px 16px;overflow:auto}.px-dfoot{display:flex;gap:8px;justify-content:flex-end;padding:10px 14px}
  .px-err{color:#c0392b;min-height:16px;margin-top:8px;white-space:pre-wrap}
  .px-f{display:grid;grid-template-columns:170px 1fr;align-items:center;gap:4px 12px;margin:7px 0}.px-f small{grid-column:2;color:#777;font-size:11px}
  .px-f input,.px-f select,.px-f textarea{font:inherit;padding:4px 6px;border:1px solid #aab3bc;border-radius:2px;min-width:0}
  .px-na{max-width:640px;margin:16px 0;padding:16px 18px;border:1px solid #d6d6d6;background:#fafafa}.px-na b{display:block;margin-bottom:6px;font-size:14px}
  .px-na p{margin:0 0 8px}.px-na small{color:#777}
  .px-none td{color:#888;font-style:italic}
  `;
  document.head.appendChild(css);
  const skinCss = text => { const style = document.createElement('style'); style.textContent = text; document.head.appendChild(style); };

  /* =============================== MikroTik WebFig (RouterOS) =============================== */
  skinCss(`
  .px-app.webfig{background:#fff;color:#222;display:grid;grid-template-rows:38px 1fr;font:12px Verdana,Arial,sans-serif}
  .wf-top{display:flex;align-items:center;gap:10px;padding:0 10px;background:linear-gradient(#f4f4f4,#dcdcdc);border-bottom:1px solid #b9b9b9}
  .wf-top b{font-size:14px}.wf-top .ver{color:#555}.wf-top .grow{flex:1}
  .wf-top button{border:1px solid #a9a9a9;background:linear-gradient(#fff,#e2e2e2);border-radius:3px;padding:3px 10px;font:inherit;cursor:pointer}
  .wf-top button.on{background:linear-gradient(#dfe9f5,#c2d4ea);border-color:#7e9bc0}
  .wf-body{display:grid;grid-template-columns:190px 1fr;min-height:0}
  .wf-menu{background:#ededed;border-right:1px solid #c4c4c4;padding:4px 0;overflow:auto}
  .wf-menu a{display:flex;align-items:center;gap:7px;padding:4px 10px;color:#1b1b1b;text-decoration:none;cursor:pointer;white-space:nowrap}
  .wf-menu a:hover{background:#dde6f0}.wf-menu a.on{background:#c9d8ea;font-weight:bold}.wf-menu a.sub{padding-left:28px}
  .wf-menu a i{font-style:normal;width:14px;text-align:center;color:#5a6f88}.wf-menu a.na{color:#7a7a7a}
  .wf-menu .arrow{margin-left:auto;color:#777}
  .wf-main{padding:10px 14px;overflow:auto}
  .wf-title{font-size:16px;font-weight:bold;margin:2px 0 8px}
  .wf-tabs{display:flex;gap:2px;border-bottom:1px solid #b9b9b9;margin-bottom:6px;flex-wrap:wrap}
  .wf-tabs a{padding:4px 10px;border:1px solid #c4c4c4;border-bottom:0;background:linear-gradient(#fafafa,#e4e4e4);cursor:pointer;color:#333}
  .wf-tabs a.on{background:#fff;font-weight:bold;position:relative;top:1px}.wf-tabs a.na{color:#888}
  .wf-bar{display:flex;align-items:center;gap:8px;margin:6px 0}
  .wf-bar button,.wf-form .btns button{border:1px solid #a9a9a9;background:linear-gradient(#fff,#e2e2e2);border-radius:3px;padding:3px 12px;font:inherit;cursor:pointer}
  .wf-bar button:hover,.wf-form .btns button:hover{background:linear-gradient(#f3f8ff,#d6e4f5)}
  .wf-bar .count{margin-left:auto;color:#555}.wf-bar input{border:1px solid #aaa;padding:2px 5px;font:inherit;width:170px}
  .wf-t{border-collapse:collapse;width:100%}
  .wf-t th{background:linear-gradient(#f6f6f6,#e3e3e3);border:1px solid #c6c6c6;padding:3px 7px;text-align:left;font-weight:normal;color:#333;white-space:nowrap}
  .wf-t td{border-bottom:1px solid #e6e6e6;padding:3px 7px;white-space:nowrap;cursor:pointer}
  .wf-t tr:hover td{background:#e8f0fa}.wf-t tr.cmt td{color:#7a7a7a;font-style:italic;cursor:default;border-bottom:0}
  .wf-t tr.dis td{color:#999}.wf-t td.flags{color:#555;width:34px;font-family:Consolas,monospace}
  .wf-form{display:flex;gap:18px;align-items:flex-start}
  .wf-form .fields{display:grid;grid-template-columns:150px 260px;gap:6px 10px;align-items:center}
  .wf-form .fields input,.wf-form .fields select{font:inherit;padding:2px 4px;border:1px solid #aaa}
  .wf-form .btns{display:flex;flex-direction:column;gap:4px;min-width:90px}
  .wf-term{background:#000;color:#cfcfcf;font:12px Consolas,'DejaVu Sans Mono',monospace;padding:10px 12px;white-space:pre;min-height:380px;overflow:auto}
  .webfig .px-err{color:#c00}
  `);
  const WF_MENU = [['Quick Set', 'na', '⚡'], ['CAPsMAN', 'na', '◎'], ['WiFi', 'na', '≋'], ['Interfaces', 'interfaces', '▦'], ['Bridge', 'bridge', '⌗'],
    ['PPP', 'na', '⇄'], ['Switch', 'na', '⊞'], ['Mesh', 'na', '✣'],
    ['IP', [['ARP', 'na'], ['Addresses', 'addresses'], ['DHCP Client', 'na'], ['DHCP Server', 'dhcp'], ['DNS', 'na'], ['Firewall', 'firewall'],
      ['Neighbors', 'neighbors'], ['Pool', 'pool'], ['Routes', 'routes'], ['Services', 'na'], ['Settings', 'na']], '⌘'],
    ['IPv6', [['Addresses', 'na'], ['Routes', 'na']], '⌘'], ['MPLS', [['LDP', 'na']], '⇶'],
    ['Routing', [['BGP', 'bgp'], ['Filters', 'na'], ['OSPF', 'ospf'], ['RIP', 'rip'], ['Router ID', 'na'], ['Tables', 'na']], '⤨'],
    ['System', [['Clock', 'na'], ['Identity', 'identity'], ['Logging', 'na'], ['Packages', 'na'], ['Resources', 'resources'], ['Users', 'na']], '⚙'],
    ['Queues', 'na', '☰'], ['Dot1X', 'na', '⛨'], ['Files', 'na', '🗀'], ['Log', 'na', '☷'], ['RADIUS', 'na', '⚿'],
    ['Tools', [['Ping', 'terminal'], ['Traceroute', 'terminal'], ['Torch', 'na']], '🛠'], ['New Terminal', 'terminal', '▣']];
  SKINS.webfig = {
    start: {page: 'interfaces', open: {}},
    draw(root) {
      const n = N(), d = D();
      const menu = WF_MENU.map(([label, target, icon]) => {
        if (Array.isArray(target)) {
          const open = view.open[label] || target.some(([, t]) => t === view.page && t !== 'na');
          return `<a data-group="${h(label)}"><i>${icon}</i>${h(label)}<span class="arrow">${open ? '▾' : '▸'}</span></a>` + (open ? target.map(([sub, t]) =>
            `<a class="sub${t === 'na' ? ' na' : ''}${t === view.page && view.label === label + '/' + sub ? ' on' : ''}" data-go="${t}" data-label="${h(label + '/' + sub)}">${h(sub)}</a>`).join('') : '');
        }
        return `<a class="${target === 'na' ? 'na' : ''}${target === view.page && view.label === label ? ' on' : ''}" data-go="${target}" data-label="${h(label)}"><i>${icon}</i>${h(label)}</a>`;
      }).join('');
      root.innerHTML = `<div class="wf-top"><b>RouterOS</b><span class="ver">${h(d.model)} · ${h(n.name)} · sous-ensemble Network LABS</span><span class="grow"></span>
        <button>Quick Set</button><button class="on">WebFig</button><button data-go="terminal">Terminal</button></div>
        <div class="wf-body"><nav class="wf-menu">${menu}</nav><main class="wf-main"></main></div>`;
      root.querySelectorAll('[data-group]').forEach(a => { a.onclick = () => { view.open[a.dataset.group] = !view.open[a.dataset.group]; render(); }; });
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { view.page = a.dataset.go; view.label = a.dataset.label || a.textContent; view.tab = null; view.edit = null; render(); }; });
      const main = root.querySelector('main');
      const pages = {interfaces: wfInterfaces, addresses: wfAddresses, routes: wfRoutes, firewall: wfFirewall, dhcp: wfDhcp, pool: wfPool,
        neighbors: wfNeighbors, identity: wfIdentity, resources: wfResources, terminal: wfTerminal, bridge: wfBridge,
        ospf: m => wfProtocol(m, 'OSPF'), bgp: m => wfProtocol(m, 'BGP'), rip: m => wfProtocol(m, 'RIP')};
      (pages[view.page] || (m => { m.innerHTML = `<div class="wf-title">${h((view.label || '').replace('/', ' › '))}</div>${naBox(view.label || '', NA.later)}`; }))(main);
    },
  };
  const wfTabs = (tabs, on) => `<div class="wf-tabs">${tabs.map(t => `<a class="${t === on ? 'on' : 'na'}">${h(t)}</a>`).join('')}</div>`;
  const wfBar = (count, add = true) => `<div class="wf-bar">${add ? '<button class="add">Add New</button>' : ''}<span class="count">${count} item${count === 1 ? '' : 's'}</span>
    <input placeholder="Filter"></div>`;
  function wfForm(main, title, fieldsHtml, buttons) {
    main.innerHTML = `<div class="wf-title">${h(title)}</div><div class="wf-form"><div class="fields">${fieldsHtml}</div><div class="btns">${
      buttons.map(([label]) => `<button>${h(label)}</button>`).join('')}</div></div><div class="px-err"></div>`;
    main.querySelectorAll('.btns button').forEach((button, i) => {
      button.onclick = async () => {
        try { if (await buttons[i][1](main) !== true) { view.edit = null; render(); } } catch (error) { main.querySelector('.px-err').textContent = error.message; }
      };
    });
  }
  const wfCancel = ['Cancel', async () => {}];
  const wfDisabled = label => [label, async () => { throw new Error(`« ${label} » : ${NA.later}`); }];
  function wfInterfaces(main) {
    const rows = D().ports.flatMap((p, i) => [p.peer ? `<tr class="cmt"><td></td><td colspan="8">;;; vers ${h(p.peer)}</td></tr>` : '',
      tr([p.down ? 'X' : p.peer && running() ? 'R' : '', h(p.name), 'Ethernet', '1500', '1592', '0 bps', '0 bps', '0', '0'], `data-i="${i}" class="${p.down ? 'dis' : ''}"`)]);
    if (view.edit !== null && view.edit !== undefined) {
      const p = D().ports[view.edit];
      return wfForm(main, `Interface <${p.name}>`, `<span>Name:</span>${input('wfName', p.name, 'disabled')}<span>Type:</span>${input('t', 'Ethernet', 'disabled')}
        <span>MTU:</span>${input('m', '1500', 'disabled')}<span>L2 MTU:</span>${input('l', '1592', 'disabled')}<span>ARP:</span>${select('a', ['enabled'], 'enabled')}
        <span>Comment:</span>${input('c', p.peer ? 'vers ' + p.peer : '', 'disabled')}<span>Running:</span><b>${p.down ? 'disabled' : p.peer && running() ? 'yes' : 'no'}</b>`,
      [['OK', async () => {}], wfCancel, ['Apply', async () => true], [p.down ? 'Enable' : 'Disable', async () => {
        await setAddress(p.port, N().interfaces[p.port] || '', p.down); toast(`${p.name} ${p.down ? 'enabled' : 'disabled'}.`); }],
      wfDisabled('Comment'), wfDisabled('Torch')]);
    }
    main.innerHTML = `<div class="wf-title">Interfaces</div>${wfTabs(['Interface', 'Interface List', 'Ethernet', 'EoIP Tunnel', 'IP Tunnel', 'GRE Tunnel',
      'VLAN', 'VRRP', 'Bonding', 'LTE'], 'Interface')}${wfBar(D().ports.length)}${table('wf-t', ['', 'Name', 'Type', 'Actual MTU', 'L2 MTU', 'Tx', 'Rx',
      'Tx Packet (p/s)', 'Rx Packet (p/s)'], rows)}`;
    main.querySelector('.add').onclick = () => toast('Add New › VLAN, Bonding, Bridge… : ' + NA.later, true);
    main.querySelectorAll('tr[data-i]').forEach(row => { row.onclick = () => { view.edit = Number(row.dataset.i); render(); }; });
  }
  function wfAddresses(main) {
    const list = D().ports.filter(p => p.address);
    if (view.edit) {
      const p = view.edit === 'new' ? null : portByName(view.edit);
      const ports = D().ports.map(x => x.name);
      return wfForm(main, p ? `Address <${p.address}>` : 'New Address', `<span>Address:</span>${input('wfAddr', p ? p.address : '', 'placeholder="a.b.c.d/nn"')}
        <span>Network:</span>${input('wfNet', p ? ipOf(networkOf(p.address)) : '', 'disabled')}<span>Interface:</span>${select('wfIf', ports, p ? p.name : ports[0])}`,
      [['OK', async m => {
        const address = val(m, '#wfAddr'), target = portByName(val(m, '#wfIf'));
        if (!/^\d+\.\d+\.\d+\.\d+\/\d+$/.test(address)) throw new Error('Address : a.b.c.d/nn');
        const lines = [];
        if (p && p.name !== target.name) lines.push(`/ip address remove [find interface=${p.name}]`);
        if (target.address) lines.push(`/ip address remove [find interface=${target.name}]`);
        lines.push(`/ip address add address=${address} interface=${target.name}`);
        await cli(lines.join('\n')); toast(lines.join('\n'));
      }], wfCancel, ['Apply', async () => true], wfDisabled('Disable'), wfDisabled('Comment'), wfDisabled('Copy'),
      ['Remove', async () => { if (p) { await cli(`/ip address remove [find interface=${p.name}]`); toast(`/ip address remove [find interface=${p.name}]`); } }]]);
    }
    main.innerHTML = `<div class="wf-title">Address List</div>${wfBar(list.length)}${table('wf-t', ['', 'Address', 'Network', 'Interface'],
      list.map(p => tr(['', h(p.address), h(ipOf(networkOf(p.address))), h(p.name)], `data-n="${h(p.name)}"`)))}`;
    main.querySelector('.add').onclick = () => { view.edit = 'new'; render(); };
    main.querySelectorAll('tr[data-n]').forEach(row => { row.onclick = () => { view.edit = row.dataset.n; render(); }; });
  }
  function wfRoutes(main) {
    const d = D();
    if (view.edit) {
      const r = view.edit === 'new' ? null : d.static.find(x => x.network === view.edit);
      return wfForm(main, r ? `Route <${r.network}>` : 'New Route', `<span>Dst. Address:</span>${input('wfDst', r ? r.network : '0.0.0.0/0')}
        <span>Gateway:</span>${input('wfGw', r ? r.gateway : '', 'placeholder="a.b.c.d"')}<span>Distance:</span>${input('wfDist', '1')}
        <span>Routing Table:</span>${select('wfTab', ['main'], 'main')}`,
      [['OK', async m => {
        const lines = [];
        if (r && r.network !== val(m, '#wfDst')) lines.push(`/ip route remove [find dst-address=${r.network}]`);
        lines.push(`/ip route add dst-address=${val(m, '#wfDst')} gateway=${val(m, '#wfGw')}`);
        await cli(lines.join('\n')); toast(lines.join('\n'));
      }], wfCancel, ['Apply', async () => true], wfDisabled('Disable'), wfDisabled('Comment'), wfDisabled('Copy'),
      ['Remove', async () => { if (r) { await cli(`/ip route remove [find dst-address=${r.network}]`); toast('Route removed.'); } }]]);
    }
    const rows = [...d.connected.map(r => tr(['DAc', h(r.network), h(r.port), '0', 'main'])),
      ...d.static.map(r => tr(['As', h(r.network), h(r.gateway), '1', 'main'], `data-r="${h(r.network)}"`))];
    main.innerHTML = `<div class="wf-title">Routes</div>${wfTabs(['Routes', 'Nexthops', 'Rules', 'VRF'], 'Routes')}${wfBar(rows.length)}${table('wf-t',
      ['', 'Dst. Address', 'Gateway', 'Distance', 'Routing Table'], rows)}<p style="color:#666">D - dynamic, A - active, c - connect, s - static</p>`;
    main.querySelector('.add').onclick = () => { view.edit = 'new'; render(); };
    main.querySelectorAll('tr[data-r]').forEach(row => { row.onclick = () => { view.edit = row.dataset.r; render(); }; });
  }
  function wfFirewall(main) {
    const filtering = N().role === 'firewall';
    const rules = filtering ? fw().rules : [];
    main.innerHTML = `<div class="wf-title">Firewall</div>${wfTabs(['Filter Rules', 'NAT', 'Mangle', 'Raw', 'Service Ports', 'Connections', 'Address Lists',
      'Layer7 Protocols'], 'Filter Rules')}${wfBar(rules.length)}${table('wf-t', ['#', 'Action', 'Chain', 'Src. Address', 'Dst. Address', 'Proto...', 'Dst. Port',
      'In. Interface', 'Out. Interface', 'Bytes', 'Packets'], rules.map((r, i) => tr([String(i), r.action === 'accept' ? '✔ accept' : '✖ drop', 'forward',
      h(r.source || ''), h(r.destination || ''), h(r.protocol && r.protocol !== 'any' ? r.protocol : ''), h(r.dport || ''), h(r.in ? portName(r.in) : ''),
      h(r.out ? portName(r.out) : ''), '0 B', '0'])))}${filtering ? '' : '<p style="color:#666">Ce routeur du laboratoire ne filtre pas : le filtrage se fait sur un pare-feu.</p>'}`;
    main.querySelector('.add').onclick = () => toast(filtering ? 'Ajouter une règle : terminal, /ip firewall filter add chain=forward …'
      : 'Ce routeur du laboratoire ne filtre pas : utiliser un pare-feu.', true);
  }
  const dhcpServer = () => N().dhcp_server;
  function wfDhcp(main) {
    const s = dhcpServer();
    if (view.edit) {
      const ports = D().ports.filter(p => p.address).map(p => p.name);
      return wfForm(main, s ? 'DHCP Server <dhcp1>' : 'New DHCP Server', `<span>Name:</span>${input('n', 'dhcp1', 'disabled')}
        <span>Interface:</span>${select('wfIf', ports, s ? portName(s.interface) : ports[0])}<span>Address Pool (from):</span>${input('wfFrom', s ? s.start : '')}
        <span>Address Pool (to):</span>${input('wfTo', s ? s.end : '')}<span>Gateway:</span>${input('wfGw', s ? s.router : '')}
        <span>DNS Servers:</span>${input('wfDns', s ? (s.dns || []).join(',') : '')}<span>Lease Time:</span>${input('wfLease', s ? s.lease_seconds : 3600)}`,
      [['OK', async m => {
        const dns = val(m, '#wfDns') ? val(m, '#wfDns').split(',').map(x => x.trim()) : [];
        await section('dhcpserver', {dhcp_server: {interface: portByName(val(m, '#wfIf')).port, start: val(m, '#wfFrom'), end: val(m, '#wfTo'),
          router: val(m, '#wfGw'), dns, lease_seconds: Number(val(m, '#wfLease')) || 3600, reservations: []}});
        toast('DHCP server applied.');
      }], wfCancel, ['Apply', async () => true], ['Remove', async () => { await section('dhcpserver', {dhcp_server: null}); toast('DHCP server removed.'); }]]);
    }
    const lease = sec => new Date(sec * 1000).toISOString().substr(11, 8);
    main.innerHTML = `<div class="wf-title">DHCP Server</div>${wfTabs(['DHCP', 'Networks', 'Leases', 'Options', 'Option Sets', 'Vendor Classes', 'Alerts'], 'DHCP')}
      ${wfBar(s ? 1 : 0)}${table('wf-t', ['', 'Name', 'Interface', 'Relay', 'Lease Time', 'Address Pool', 'Add ARP For Leases'],
        s ? [tr(['', 'dhcp1', h(portName(s.interface)), '', lease(s.lease_seconds || 3600), 'dhcp_pool0', 'no'], 'data-e="1"')] : [])}
      <p style="margin-top:14px"><b>Networks</b></p>${table('wf-t', ['Address', 'Gateway', 'DNS Servers'], s ? [tr([h(networkOf(N().interfaces[s.interface])),
        h(s.router || ''), h((s.dns || []).join(','))])] : [])}`;
    main.querySelector('.add').onclick = () => { if (s) return toast('Un seul serveur DHCP par équipement dans le laboratoire.', true); view.edit = 'new'; render(); };
    main.querySelectorAll('tr[data-e]').forEach(row => { row.onclick = () => { view.edit = 'edit'; render(); }; });
  }
  function wfPool(main) {
    const s = dhcpServer();
    main.innerHTML = `<div class="wf-title">IP Pool</div>${wfTabs(['Pools', 'Used Addresses'], 'Pools')}${wfBar(s ? 1 : 0, false)}${table('wf-t',
      ['Name', 'Addresses', 'Next Pool'], s ? [tr(['dhcp_pool0', h(`${s.start}-${s.end}`), 'none'])] : [])}`;
  }
  function wfNeighbors(main) {
    const list = D().ports.filter(p => p.peer);
    main.innerHTML = `<div class="wf-title">Neighbor List</div>${wfTabs(['Neighbors', 'Discovery Settings'], 'Neighbors')}${wfBar(list.length, false)}
      ${table('wf-t', ['Interface', 'IP Address', 'Identity', 'Platform', 'Board Name'], list.map(p => tr([h(p.name), '', h(peerName(p)), '', h(p.peer.split(' · ')[1] || '')])))}
      <p style="color:#666">Les voisins sont les câbles du projet (MNDP/LLDP réels : lab en marche, terminal).</p>`;
  }
  function wfProtocol(main, name) {
    const list = (D().features || []).filter(f => f.name.toUpperCase().includes(name));
    main.innerHTML = `<div class="wf-title">${name}</div>${wfTabs(name === 'OSPF' ? ['Instances', 'Areas', 'Interface Templates', 'Neighbors', 'LSA']
      : name === 'BGP' ? ['Connections', 'Templates', 'Sessions', 'Advertisements'] : ['Instances', 'Interface Templates', 'Neighbors'], name === 'BGP' ? 'Connections' : 'Instances')}
      ${wfBar(list.length, false)}${table('wf-t', ['Name', 'Detail'], list.map(f => tr([h(f.name), h(f.detail)])))}
      <p style="color:#666">${h(name)} se configure dans le terminal (/routing ${name.toLowerCase()} …), comme sur RouterOS.</p>`;
  }
  function wfIdentity(main) {
    wfForm(main, 'Identity', `<span>Identity:</span>${input('wfId', N().name)}`, [['OK', async m => {
      if (val(m, '#wfId') !== N().name) { await rename(val(m, '#wfId')); toast('/system identity set name=' + val(m, '#wfId')); } }], wfCancel,
    ['Apply', async m => { if (val(m, '#wfId') !== N().name) await rename(val(m, '#wfId')); return true; }]]);
  }
  function wfResources(main) {
    const n = N();
    wfForm(main, 'Resources', `<span>Uptime:</span><b>${running() ? 'en marche' : 'arrêté'}</b><span>Version:</span><b>sous-ensemble RouterOS · Network LABS</b>
      <span>Free Memory:</span><b>—</b><span>Total Memory:</span><b>${h(n.memory_mib || 128)} MiB</b><span>CPU:</span><b>Linux micro-VM</b>
      <span>CPU Count:</span><b>${h(n.vcpus || 1)}</b><span>CPU Load:</span><b>—</b><span>Architecture Name:</span><b>x86_64</b>
      <span>Board Name:</span><b>${h(D().model)}</b><span>Platform:</span><b>Network LABS</b>`, [['OK', async () => {}], wfDisabled('PCI'), wfDisabled('USB'), wfDisabled('CPU'), wfDisabled('IRQ')]);
  }
  function wfTerminal(main) {
    const text = state.config_text || '';
    main.innerHTML = `<div class="wf-title">Terminal</div><div class="wf-term">[admin@${h(N().name)}] &gt; /export compact\n${h(text)}\n[admin@${h(N().name)}] &gt; </div>
      <div class="wf-bar"><button class="open">Ouvrir le terminal interactif</button></div>`;
    main.querySelector('.open').onclick = openTerminal;
  }
  function wfBridge(main) {
    const d = D(), switching = N().role === 'switch';
    const tab = view.tab || 'Bridge';
    let body = '';
    if (tab === 'Bridge') body = wfBar(switching ? 1 : 0) + table('wf-t', ['', 'Name', 'Type', 'L2 MTU', 'Tx', 'Rx'], switching ? [tr(['R', 'bridge1', 'Bridge', '1592', '0 bps', '0 bps'])] : []);
    if (tab === 'Ports') body = wfBar(switching ? d.ports.length : 0) + table('wf-t', ['', 'Interface', 'Bridge', 'Horizon', 'Trusted', 'Priority (hex)', 'Path Cost', 'PVID',
      'Frame Types'], switching ? d.ports.map((p, i) => tr([p.down ? 'X' : '', h(p.name), 'bridge1', '', 'no', '80', '10', p.trunk ? '1' : h(p.vlan),
      p.trunk ? 'admit-only-vlan-tagged' : 'admit-only-untagged-and-priority-tagged'], `data-p="${i}"`)) : []);
    if (tab === 'VLANs') body = wfBar(d.vlans.length) + table('wf-t', ['', 'Bridge', 'VLAN IDs', 'Current Tagged', 'Current Untagged'], d.vlans.map(v => tr(['', 'bridge1',
      String(v), h(d.ports.filter(p => p.trunk).map(p => p.name).join(',')), h(d.ports.filter(p => !p.trunk && p.vlan === v).map(p => p.name).join(','))])));
    if (view.edit !== null && view.edit !== undefined && tab === 'Ports') {
      const p = d.ports[view.edit];
      return wfForm(main, `Bridge Port <${p.name}>`, `<span>Interface:</span>${input('i', p.name, 'disabled')}<span>Bridge:</span>${input('b', 'bridge1', 'disabled')}
        <span>PVID:</span>${select('wfPvid', d.vlans, p.trunk ? 1 : p.vlan)}<span>Frame Types:</span>${select('wfFt', [['access', 'admit-only-untagged-and-priority-tagged'],
          ['trunk', 'admit-only-vlan-tagged']], p.trunk ? 'trunk' : 'access')}`,
      [['OK', async m => {
        const ports = JSON.parse(JSON.stringify(N().switchports || {}));
        ports[p.port] = val(m, '#wfFt') === 'trunk' ? {mode: 'trunk', native_vlan: 1, allowed: 'all'} : {mode: 'access', vlan: Number(val(m, '#wfPvid'))};
        await section('switching', {vlans: N().vlans || [1], switchports: ports}); toast(`${p.name} : appliqué.`);
      }], wfCancel]);
    }
    if (view.edit === 'vlan') {
      return wfForm(main, 'New Bridge VLAN', `<span>Bridge:</span>${input('b', 'bridge1', 'disabled')}<span>VLAN IDs:</span>${input('wfVid', '', 'placeholder="2-4094"')}`,
        [['OK', async m => {
          const vid = Number(val(m, '#wfVid'));
          if (!(vid >= 2 && vid <= 4094)) throw new Error('VLAN IDs : 2-4094');
          await section('switching', {vlans: [...new Set([...(N().vlans || [1]), vid])].sort((a, b) => a - b), switchports: N().switchports || {}});
          toast(`VLAN ${vid} ajouté.`);
        }], wfCancel]);
    }
    main.innerHTML = `<div class="wf-title">Bridge</div><div class="wf-tabs">${['Bridge', 'Ports', 'Port Extensions', 'VLANs', 'MSTIs', 'Port MST Overrides', 'Filters', 'NAT', 'Hosts', 'MDB']
      .map(t => `<a class="${t === tab ? 'on' : ['Bridge', 'Ports', 'VLANs'].includes(t) ? '' : 'na'}" data-t="${t}">${t}</a>`).join('')}</div>${body}
      ${switching ? '' : '<p style="color:#666">Aucun pont sur ce routeur.</p>'}`;
    main.querySelectorAll('[data-t]').forEach(a => { a.onclick = () => { if (['Bridge', 'Ports', 'VLANs'].includes(a.dataset.t)) { view.tab = a.dataset.t; view.edit = null; render(); } }; });
    main.querySelectorAll('tr[data-p]').forEach(row => { row.onclick = () => { view.edit = Number(row.dataset.p); render(); }; });
    const add = main.querySelector('.add');
    if (add) add.onclick = () => { if (tab === 'VLANs' && switching) { view.edit = 'vlan'; render(); } else toast(NA.later, true); };
  }

  /* =============================== Cisco IOS-XE WebUI =============================== */
  skinCss(`
  .px-app.iosxe{background:#f5f6f7;color:#2b2b2b;display:grid;grid-template-columns:220px 1fr;grid-template-rows:54px 1fr;font:13px Arial,Helvetica,sans-serif}
  .ix-top{grid-column:1/-1;display:flex;align-items:center;gap:16px;padding:0 18px;background:#fff;border-bottom:1px solid #dcdfe3}
  .ix-top .prod{font-size:16px}.ix-top .prod small{color:#6c757d;margin-left:8px;font-size:12px}.ix-top .grow{flex:1}
  .ix-top .who{color:#6c757d}.ix-top .ic{border:0;background:none;font-size:16px;color:#49505a;cursor:pointer;padding:4px 6px}
  .ix-nav{background:#2b3640;color:#cfd6dd;padding-top:8px}
  .ix-nav input{margin:6px 12px 10px;width:calc(100% - 24px);box-sizing:border-box;background:#38444f;border:0;color:#fff;padding:7px 9px;border-radius:2px}
  .ix-nav a{display:flex;align-items:center;gap:12px;padding:12px 18px;cursor:pointer;color:#cfd6dd;border-left:3px solid transparent}
  .ix-nav a:hover{background:#34414d}.ix-nav a.on{background:#1f2830;border-left-color:#049fd9;color:#fff}.ix-nav a i{font-style:normal;width:18px;text-align:center}
  .ix-nav a .chev{margin-left:auto}
  .ix-fly{position:absolute;left:220px;top:54px;z-index:9;background:#fff;box-shadow:4px 4px 18px rgba(0,0,0,.2);padding:16px 22px;display:flex;gap:34px}
  .ix-fly h4{margin:0 0 8px;font-size:13px;color:#049fd9;text-transform:none}.ix-fly a{display:block;padding:4px 0;color:#333;cursor:pointer}
  .ix-fly a:hover{color:#049fd9;text-decoration:underline}.ix-fly a.na{color:#9aa1a8}
  .ix-main{padding:16px 22px;overflow:auto;position:relative}
  .ix-crumb{color:#6c757d;font-size:12px;margin-bottom:8px}.ix-crumb b{color:#2b2b2b}
  .ix-card{background:#fff;border:1px solid #dcdfe3;margin-bottom:14px}.ix-card h3{margin:0;padding:10px 14px;font-size:14px;border-bottom:1px solid #e6e8eb;font-weight:normal}
  .ix-card .b{padding:12px 14px}
  .ix-grid{display:grid;grid-template-columns:2fr 1fr 1fr;gap:14px}
  .ix-kv{display:grid;grid-template-columns:150px 1fr;gap:7px}.ix-kv span{color:#6c757d}
  .ix-gauge{width:120px;height:120px;border-radius:50%;margin:6px auto;display:grid;place-items:center}
  .ix-gauge b{width:92px;height:92px;border-radius:50%;background:#fff;display:grid;place-items:center;font-size:20px}
  .ix-panel{display:flex;gap:12px;flex-wrap:wrap;background:linear-gradient(#4a5561,#353e48);padding:14px 16px 10px;border-radius:3px;box-shadow:inset 0 1px 0 #5d6976}
  .ix-port{display:flex;flex-direction:column;align-items:center;gap:5px;color:#d4dbe2;font-size:10px;cursor:pointer}
  .ix-port i{width:34px;height:28px;border-radius:2px;background:#0f1418;border:2px solid #5b6570;position:relative}
  .ix-port i::after{content:'';position:absolute;left:10px;right:10px;bottom:-2px;height:7px;background:#353e48}
  .ix-port.up i{border-color:#6cc04a;box-shadow:0 0 7px rgba(108,192,74,.55)}.ix-port.down i{border-color:#cf2030}.ix-port:hover i{filter:brightness(1.6)}
  .ix-legend{display:flex;gap:14px;font-size:12px;color:#6c757d;margin-top:8px}.ix-legend i{display:inline-block;width:10px;height:10px;margin-right:5px;border:2px solid}
  .ix-tools{display:flex;gap:8px;margin-bottom:8px}
  .ix-btn{border:1px solid #049fd9;color:#049fd9;background:#fff;padding:6px 14px;border-radius:2px;cursor:pointer;font:inherit}
  .ix-btn.pri{background:#049fd9;color:#fff}.ix-btn.del{border-color:#cf2030;color:#cf2030}
  .ix-t{width:100%;border-collapse:collapse;background:#fff}
  .ix-t th{text-align:left;padding:9px 10px;border-bottom:2px solid #dcdfe3;font-weight:bold;font-size:12px;color:#49505a;white-space:nowrap}
  .ix-t td{padding:9px 10px;border-bottom:1px solid #eceef0;white-space:nowrap}.ix-t tbody tr:hover td{background:#f0f8fc}
  .ix-t a{color:#049fd9;cursor:pointer}.ix-up{color:#6cc04a}.ix-dn{color:#cf2030}
  .ix-slide{position:fixed;top:0;right:0;bottom:0;width:520px;background:#fff;box-shadow:-6px 0 22px rgba(0,0,0,.25);z-index:15;display:flex;flex-direction:column}
  .ix-slide h2{margin:0;padding:16px 18px;font-size:17px;font-weight:normal;border-bottom:1px solid #e6e8eb}
  .ix-slide .tabs{display:flex;border-bottom:1px solid #e6e8eb;padding:0 18px}.ix-slide .tabs a{padding:10px 14px;color:#6c757d}
  .ix-slide .tabs a.on{color:#049fd9;border-bottom:3px solid #049fd9}
  .ix-slide .body{padding:14px 18px;overflow:auto;flex:1}.ix-slide .foot{padding:12px 18px;border-top:1px solid #e6e8eb;display:flex;justify-content:space-between}
  .ix-tog{display:inline-flex;border:1px solid #aab3bc;border-radius:12px;overflow:hidden}.ix-tog button{border:0;background:#fff;padding:3px 12px;cursor:pointer;font:inherit}
  .ix-tog button.on{background:#049fd9;color:#fff}
  .ix-cli{width:100%;height:220px;font:12px Consolas,'DejaVu Sans Mono',monospace;border:1px solid #c5cbd1;padding:8px;box-sizing:border-box}
  .ix-out{background:#1d242b;color:#d7dde3;font:12px Consolas,'DejaVu Sans Mono',monospace;white-space:pre;padding:10px;max-height:320px;overflow:auto;margin-top:10px}
  `);
  const IX_CONFIG = role => [
    ['Interface', [['Ethernet', 'ethernet'], ['Logical', 'na'], ...(role === 'router' ? [['Subinterface', 'subif']] : [])]],
    ...(role === 'switch' ? [['Layer2', [['Discovery Protocols', 'na'], ['EtherChannel', 'features'], ['LLDP', 'na'], ['Spanning Tree', 'features'], ['VLAN', 'vlan'], ['VTP', 'na']]]] : []),
    ['Routing Protocols', [['BGP', 'features'], ['EIGRP', 'features'], ['OSPF', 'features'], ['RIP', 'features'], ['Static Routing', 'static']]],
    ['Security', [['AAA', 'na'], ['ACL', 'features'], ['Port Security', role === 'switch' ? 'features' : 'na']]],
    ['Services', [['DHCP', role === 'router' ? 'dhcp' : 'na'], ['IP SLA', 'na'], ['NAT', role === 'router' ? 'features' : 'na'], ['NTP', 'na']]]];
  const IX_MENU = role => [['Dashboard', '◷', 'dashboard'], ['Monitoring', '▤', [['General', [['Interfaces', 'mon-if'], ['Routing', 'mon-route']]]]],
    ['Configuration', '⚙', IX_CONFIG(role)], ['Administration', '⚑', [['Device', [['General', 'admin-general']]], ['Command Line Interface', [['CLI', 'admin-cli']]],
      ['Software Management', [['Software Upgrade', 'na']]], ['Time', [['NTP', 'na']]]]],
    ['Licensing', '✦', 'na'], ['Troubleshooting', '⚒', [['Ping and Traceroute', [['Ping', 'terminal']]], ['Packet Capture', [['Capture', 'na']]]]]];
  SKINS.iosxe = {
    start: {page: 'dashboard'},
    draw(root) {
      const n = N(), d = D(), menu = IX_MENU(n.role);
      root.innerHTML = `<div class="ix-top"><span class="prod">${h(d.brand)} ${h(d.model.split(' · ')[0])}<small>IOS-XE · sous-ensemble Network LABS</small></span>
        <span class="grow"></span><span class="who">Welcome <b>admin</b></span><button class="ic" title="Save Configuration">💾</button>
        <button class="ic" title="Refresh">↻</button><button class="ic" title="Logout">⏻</button></div>
        <nav class="ix-nav"><input placeholder="Search Menu Items">${menu.map(([label, icon, target]) => `<a data-m="${h(label)}" class="${
          view.section === label ? 'on' : ''}"><i>${icon}</i>${h(label)}${Array.isArray(target) ? '<span class="chev">›</span>' : ''}</a>`).join('')}</nav>
        <main class="ix-main"></main>`;
      root.querySelector('.ic[title="Save Configuration"]').onclick = () => toast('Configuration saved (copy running-config startup-config) : le projet est enregistré.');
      root.querySelector('.ic[title="Refresh"]').onclick = () => load();
      root.querySelectorAll('[data-m]').forEach(a => {
        a.onclick = () => {
          const [label, , target] = menu.find(m => m[0] === a.dataset.m);
          root.querySelector('.ix-fly')?.remove();
          if (!Array.isArray(target)) { view.section = label; view.page = target; view.slide = null; return render(); }
          const fly = document.createElement('div');
          fly.className = 'ix-fly';
          fly.innerHTML = target.map(([group, items]) => `<div><h4>${h(group)}</h4>${items.map(([item, go]) => `<a class="${go === 'na' ? 'na' : ''}" data-go="${go}"
            data-title="${h(group + ' > ' + item)}">${h(item)}</a>`).join('')}</div>`).join('');
          fly.querySelectorAll('[data-go]').forEach(link => { link.onclick = () => { view.section = label; view.page = link.dataset.go; view.title = link.dataset.title; view.slide = null; render(); }; });
          root.append(fly);
        };
      });
      const main = root.querySelector('main');
      main.innerHTML = `<div class="ix-crumb">${h(view.section || 'Dashboard')}${view.title && view.page !== 'dashboard' ? ' › <b>' + h(view.title) + '</b>' : ''}</div>`;
      const pages = {dashboard: ixDashboard, ethernet: ixEthernet, static: ixStatic, vlan: ixVlan, dhcp: ixDhcp, features: ixFeatures, subif: ixSubif,
        'mon-if': ixEthernet, 'mon-route': ixRouteTable, 'admin-general': ixGeneral, 'admin-cli': ixCli, terminal: m => { openTerminal(); ixDashboard(m); }};
      (pages[view.page] || (m => m.insertAdjacentHTML('beforeend', naBox(view.title || '', NA.later))))(main);
    },
  };
  const ixMaskLine = cidr => (cidr ? `${ipOf(cidr)} ${maskOf(lenOf(cidr))}` : '');
  function ixDashboard(main) {
    const d = D(), n = N(), up = d.ports.filter(p => p.peer && !p.down).length;
    // Lab stopped: an empty dial and a dash, not a reading the device never gave.
    const gauge = (value, colour) => `<div class="ix-gauge" style="background:conic-gradient(${colour} 0 ${value || 0}%,#e6e8eb ${value || 0}% 100%)"><b>${
      value === null ? '—' : value + '%'}</b></div>`;
    main.insertAdjacentHTML('beforeend', `<div class="ix-grid"><div class="ix-card"><h3>${n.role === 'switch' ? 'Switch View' : 'Interfaces'}</h3><div class="b">
      <div class="ix-panel">${d.ports.map((p, i) => `<span class="ix-port ${p.down ? 'down' : p.peer ? 'up' : ''}" data-pi="${i}" title="${h(ios(p.name) + (p.peer ? ' → '
        + p.peer : ' · not connected'))}"><i></i>${h(p.name.replace(/^[a-z]+/i, ''))}</span>`).join('')}</div><div class="ix-legend"><span><i style="border-color:#6cc04a"></i>Up</span><span><i style="border-color:#cf2030"></i>Admin Down</span>
      <span><i style="border-color:#56606a"></i>Down</span></div></div></div>
      <div class="ix-card"><h3>CPU Utilization</h3><div class="b">${gauge(running() ? 3 : null, '#6cc04a')}</div></div>
      <div class="ix-card"><h3>Memory Utilization</h3><div class="b">${gauge(running() ? 41 : null, '#049fd9')}</div></div></div>
      <div class="ix-grid"><div class="ix-card"><h3>System Information</h3><div class="b ix-kv"><span>Host name</span><b>${h(n.name)}</b>
      <span>Model</span><b>${h(d.brand)} ${h(d.model.split(' · ')[0])}</b><span>Software</span><b>IOS-XE (sous-ensemble Network LABS)</b>
      <span>Interfaces up</span><b>${up} / ${d.ports.length}</b><span>Uptime</span><b>${running() ? 'en marche' : 'lab arrêté'}</b></div></div>
      <div class="ix-card" style="grid-column:span 2"><h3>Device Configuration</h3><div class="b ix-kv"><span>Routes</span><b>${d.connected.length} connected · ${d.static.length} static</b>
      <span>Protocols</span><b>${h((d.features || []).map(f => f.name).filter((v, i, a) => a.indexOf(v) === i).join(', ') || '—')}</b>
      ${n.role === 'switch' ? `<span>VLANs</span><b>${h(d.vlans.join(', '))}</b>` : ''}</div></div></div>`);
    main.querySelectorAll('[data-pi]').forEach(port => { port.onclick = () => ixEditIf(d.ports[Number(port.dataset.pi)]); });
  }
  function ixSlide(title, body, onApply, applyLabel = 'Update & Apply to Device') {
    document.querySelector('.ix-slide')?.remove();
    const slide = document.createElement('div');
    slide.className = 'ix-slide';
    slide.innerHTML = `<h2>${h(title)}</h2><div class="tabs"><a class="on">General</a><a>Advanced</a></div><div class="body">${body}<div class="px-err"></div></div>
      <div class="foot"><button class="ix-btn cancel">↶ Cancel</button><button class="ix-btn pri ok">${h(applyLabel)}</button></div>`;
    slide.querySelector('.cancel').onclick = () => slide.remove();
    slide.querySelector('.ok').onclick = async () => {
      try { const text = await onApply(slide); slide.remove(); render(); toast(text ? 'Applied to device:\n' + text : 'Applied to device.'); }
      catch (error) { slide.querySelector('.px-err').textContent = error.message; }
    };
    slide.querySelectorAll('.ix-tog').forEach(group => group.querySelectorAll('button').forEach(button => {
      button.onclick = () => group.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === button));
    }));
    app.append(slide);
    return slide;
  }
  const tog = (id, options, on) => `<span class="ix-tog" id="${id}">${options.map(([v, l]) => `<button type="button" data-v="${v}" class="${v === on ? 'on' : ''}">${l}</button>`).join('')}</span>`;
  const togVal = (root, id) => root.querySelector(`#${id} .on`)?.dataset.v;
  function ixEthernet(main) {
    const d = D(), n = N(), switching = n.role === 'switch';
    main.insertAdjacentHTML('beforeend', `<div class="ix-card"><h3>Ethernet Interfaces</h3><div class="b">${table('ix-t', switching
      ? ['Name', 'Status', 'Admin Status', 'Port Mode', 'VLAN', 'Description'] : ['Name', 'Status', 'Admin Status', 'IPv4 Address', 'IPv4 Netmask', 'Description'],
      d.ports.map((p, i) => tr([`<a data-i="${i}">${h(ios(p.name))}</a>`, p.peer && !p.down ? '<span class="ix-up">▲</span>' : '<span class="ix-dn">▼</span>',
        p.down ? '<span class="ix-dn">▼</span>' : '<span class="ix-up">▲</span>', ...(switching ? [p.trunk ? 'trunk' : 'access', h(p.trunk ? p.detail.replace('Trunk ', '') : p.vlan)]
          : [h(ipOf(p.address) || 'unassigned'), h(p.address ? maskOf(lenOf(p.address)) : '')]), h(p.peer ? 'to ' + p.peer : '')])))}</div></div>`);
    main.querySelectorAll('[data-i]').forEach(a => { a.onclick = () => ixEditIf(D().ports[Number(a.dataset.i)]); });
  }
  const ios = name => name.replace(/^gi/i, 'GigabitEthernet').replace(/^fa/i, 'FastEthernet').replace(/^te/i, 'TenGigabitEthernet');
  function ixEditIf(p) {
    const switching = N().role === 'switch';
    ixSlide('Edit Physical Interface', field('Interface', `<b>${h(ios(p.name))}</b>`) + field('Description', input('ixDesc', p.peer ? 'to ' + p.peer : '', 'disabled'))
      + field('Admin Status', tog('ixAdmin', [['up', 'UP'], ['down', 'DOWN']], p.down ? 'down' : 'up'))
      + (switching ? field('Switchport Mode', select('ixMode', [['access', 'Access'], ['trunk', 'Trunk']], p.trunk ? 'trunk' : 'access'))
        + field('Access VLAN', select('ixVlan', D().vlans, p.vlan || 1))
        : field('IPv4 Address', input('ixIp', ipOf(p.address))) + field('IPv4 Netmask', input('ixMask', p.address ? maskOf(lenOf(p.address)) : ''))),
    async slide => {
      const lines = [`interface ${ios(p.name)}`];
      if (switching) {
        lines.push(val(slide, '#ixMode') === 'trunk' ? ' switchport mode trunk' : ` switchport mode access\n switchport access vlan ${val(slide, '#ixVlan')}`);
      } else if (val(slide, '#ixIp')) {
        const prefix = prefixOf(val(slide, '#ixMask'));
        if (!validIp(val(slide, '#ixIp')) || prefix === null) throw new Error('IPv4 Address / Netmask invalide.');
        lines.push(` ip address ${val(slide, '#ixIp')} ${val(slide, '#ixMask')}`);
      } else lines.push(' no ip address');
      lines.push(togVal(slide, 'ixAdmin') === 'down' ? ' shutdown' : ' no shutdown');
      await cli(lines.join('\n'));
      return lines.join('\n');
    });
  }
  function ixStatic(main) {
    const d = D();
    main.insertAdjacentHTML('beforeend', `<div class="ix-card"><h3>IPv4 Static Routes</h3><div class="b"><div class="ix-tools"><button class="ix-btn add">＋ Add</button>
      <button class="ix-btn del">✕ Delete</button></div>${table('ix-t', ['', 'VRF', 'Prefix', 'Mask', 'Outgoing Interface / Next Hop', 'AD', 'Permanent'],
        d.static.map((r, i) => tr([`<input type="checkbox" data-i="${i}">`, 'Global', h(ipOf(r.network)), h(maskOf(lenOf(r.network))), h(r.gateway), '1', 'No'])), 'No items to display')}</div></div>`);
    main.querySelector('.add').onclick = () => ixSlide('Add Static Route', field('VRF', select('v', ['Global'], 'Global')) + field('Prefix', input('ixPre', '', 'placeholder="0.0.0.0"'))
      + field('Mask', input('ixMk', '', 'placeholder="0.0.0.0"')) + field('Next Hop', input('ixNh')) + field('AD', input('ixAd', '1')) + field('Permanent', tog('p', [['no', 'NO'], ['yes', 'YES']], 'no')),
    async slide => {
      if (!validIp(val(slide, '#ixPre')) || prefixOf(val(slide, '#ixMk')) === null || !validIp(val(slide, '#ixNh'))) throw new Error('Prefix, Mask et Next Hop : a.b.c.d');
      const line = `ip route ${val(slide, '#ixPre')} ${val(slide, '#ixMk')} ${val(slide, '#ixNh')}`;
      await cli(line);
      return line;
    }, 'Apply to Device');
    main.querySelector('.del').onclick = async () => {
      const chosen = [...main.querySelectorAll('input[data-i]:checked')].map(box => d.static[Number(box.dataset.i)]);
      if (!chosen.length) return toast('Sélectionner une route.', true);
      const text = chosen.map(r => `no ip route ${ipOf(r.network)} ${maskOf(lenOf(r.network))} ${r.gateway}`).join('\n');
      await attempt(() => cli(text), 'Applied to device:\n' + text);
    };
  }
  function ixRouteTable(main) {
    const d = D();
    main.insertAdjacentHTML('beforeend', `<div class="ix-card"><h3>Routing Table</h3><div class="b">${table('ix-t', ['Code', 'Network', 'Next Hop', 'Interface'],
      [...d.connected.map(r => tr(['C', h(r.network), 'directly connected', h(ios(r.port))])), ...d.static.map(r => tr(['S', h(r.network), h(r.gateway), h(ios(r.port))]))])}
      </div></div>`);
  }
  function ixVlan(main) {
    const d = D();
    main.insertAdjacentHTML('beforeend', `<div class="ix-card"><h3>VLAN</h3><div class="b"><div class="ix-tools"><button class="ix-btn add">＋ Add</button>
      <button class="ix-btn del">✕ Delete</button></div>${table('ix-t', ['', 'VLAN ID', 'Name', 'Status', 'Ports'], d.vlans.map(v => tr([v === 1 ? '' : `<input type="checkbox" data-v="${v}">`,
        String(v), v === 1 ? 'default' : 'VLAN' + String(v).padStart(4, '0'), 'active', h(d.ports.filter(p => !p.trunk && p.vlan === v).map(p => ios(p.name)).join(', '))])))}</div></div>`);
    main.querySelector('.add').onclick = () => ixSlide('Create VLAN', field('VLAN ID', input('ixVid', '', 'placeholder="2-4094"')) + field('Name', input('ixVn'))
      + field('State', tog('s', [['act', 'ACTIVATED'], ['sus', 'SUSPENDED']], 'act')), async slide => {
      const vid = Number(val(slide, '#ixVid'));
      if (!(vid >= 2 && vid <= 4094)) throw new Error('VLAN ID : 2-4094');
      const text = `vlan ${vid}` + (val(slide, '#ixVn') ? `\n name ${val(slide, '#ixVn')}` : '');
      await cli(text);
      return text;
    }, 'Apply to Device');
    main.querySelector('.del').onclick = async () => {
      const chosen = [...main.querySelectorAll('input[data-v]:checked')].map(box => box.dataset.v);
      if (!chosen.length) return toast('Sélectionner un VLAN.', true);
      const text = chosen.map(v => `no vlan ${v}`).join('\n');
      await attempt(() => cli(text), 'Applied to device:\n' + text);
    };
  }
  function ixDhcp(main) {
    const s = dhcpServer();
    main.insertAdjacentHTML('beforeend', `<div class="ix-card"><h3>DHCP Pool</h3><div class="b"><div class="ix-tools"><button class="ix-btn add">＋ Add</button>
      ${s ? '<button class="ix-btn del">✕ Delete</button>' : ''}</div>${table('ix-t', ['Pool Name', 'Network', 'Address Range', 'Default Router', 'DNS Server', 'Lease'],
        s ? [tr(['LAN-POOL', h(networkOf(N().interfaces[s.interface])), h(`${s.start} - ${s.end}`), h(s.router || ''), h((s.dns || []).join(' ')), h(`${Math.round((s.lease_seconds || 3600) / 60)} min`)])] : [])}
      </div></div>`);
    main.querySelector('.add').onclick = () => {
      const ports = D().ports.filter(p => p.address);
      ixSlide('Create DHCP Pool', field('DHCP Pool Name', input('n', 'LAN-POOL', 'disabled')) + field('Interface', select('ixIf', ports.map(p => [p.port, ios(p.name)]), s ? s.interface : ports[0]?.port))
        + field('Start Address', input('ixS', s ? s.start : '')) + field('End Address', input('ixE', s ? s.end : '')) + field('Default Router', input('ixR', s ? s.router : ''))
        + field('DNS Server', input('ixD', s ? (s.dns || []).join(' ') : '')) + field('Lease (minutes)', input('ixL', s ? Math.round((s.lease_seconds || 3600) / 60) : 60)),
      async slide => {
        await section('dhcpserver', {dhcp_server: {interface: val(slide, '#ixIf'), start: val(slide, '#ixS'), end: val(slide, '#ixE'), router: val(slide, '#ixR'),
          dns: val(slide, '#ixD') ? val(slide, '#ixD').split(/[ ,]+/) : [], lease_seconds: 60 * (Number(val(slide, '#ixL')) || 60), reservations: []}});
      }, 'Apply to Device');
    };
    const del = main.querySelector('.del');
    if (del) del.onclick = () => attempt(() => section('dhcpserver', {dhcp_server: null}), 'Applied to device.');
  }
  function ixFeatures(main) {
    main.insertAdjacentHTML('beforeend', `<div class="ix-card"><h3>${h(view.title || 'Features')}</h3><div class="b">${table('ix-t', ['Feature', 'Configuration'],
      (D().features || []).map(f => tr([h(f.name), h(f.detail)])), 'Rien de configuré.')}<p style="color:#6c757d">Se configure en CLI : Administration › Command Line Interface,
      ou le terminal de l’équipement.</p></div></div>`);
  }
  function ixSubif(main) {
    main.insertAdjacentHTML('beforeend', `<div class="ix-card"><h3>Subinterfaces</h3><div class="b">${table('ix-t', ['Name', 'VLAN', 'IPv4 Address'],
      D().subinterfaces.map(s => tr([h(ios(s.name)), h(s.vlan), h(s.address || '')])))}<p style="color:#6c757d">encapsulation dot1Q : en CLI.</p></div></div>`);
  }
  function ixGeneral(main) {
    main.insertAdjacentHTML('beforeend', `<div class="ix-card"><h3>General</h3><div class="b">${field('Hostname', input('ixHost', N().name))}
      <button class="ix-btn pri apply">Apply to Device</button></div></div>`);
    main.querySelector('.apply').onclick = () => attempt(() => rename(val(main, '#ixHost')), 'hostname ' + val(main, '#ixHost'));
  }
  function ixCli(main) {
    main.insertAdjacentHTML('beforeend', `<div class="ix-card"><h3>Command Line Interface</h3><div class="b">
      <label><input type="radio" name="ixm" value="exec"> Exec</label> <label><input type="radio" name="ixm" value="conf" checked> Configure</label>
      <textarea class="ix-cli" placeholder="interface GigabitEthernet0/0/1&#10; ip address 192.0.2.1 255.255.255.0"></textarea>
      <div class="ix-tools" style="margin-top:8px"><button class="ix-btn pri run">Run Command</button><button class="ix-btn clear">Clear</button></div>
      <div class="ix-out">${h(state.config_text || '')}</div></div></div>`);
    main.querySelector('.clear').onclick = () => { main.querySelector('.ix-cli').value = ''; };
    main.querySelector('.run').onclick = async () => {
      const text = main.querySelector('.ix-cli').value, mode = main.querySelector('input[name=ixm]:checked').value;
      if (mode === 'exec') {
        if (/^\s*sh(ow)?\s+run/i.test(text)) return void (main.querySelector('.ix-out').textContent = state.config_text || '');
        return toast('Exec : show running-config ici ; les autres commandes show dans le terminal de l’équipement.', true);
      }
      await attempt(() => cli(text), 'Configuration applied.');
    };
  }

  /* =============================== Cisco ASDM =============================== */
  skinCss(`
  .px-app.asdm{background:#d6d9dd;color:#000;font:12px Tahoma,Verdana,Arial,sans-serif;display:grid;grid-template-rows:auto auto auto 1fr auto;height:100vh}
  .as-title{background:linear-gradient(#e9ecef,#cfd4da);padding:4px 10px;border-bottom:1px solid #a9afb6}
  .as-menu{display:flex;gap:14px;padding:3px 10px;background:#f0f0f0;border-bottom:1px solid #c7c7c7}.as-menu span{cursor:default}
  .as-tool{display:flex;align-items:center;gap:2px;padding:4px 6px;background:linear-gradient(#fafafa,#e3e6e9);border-bottom:1px solid #b8bec5}
  .as-tool button{display:flex;align-items:center;gap:5px;border:1px solid transparent;background:none;padding:4px 9px;font:inherit;cursor:pointer;border-radius:2px}
  .as-tool button:hover{border-color:#9fb4cc;background:#e6eef7}.as-tool button.on{border-color:#7f9cc0;background:#d2e1f2}.as-tool i{font-style:normal;font-size:15px}
  .as-tool .sep{width:1px;height:22px;background:#b8bec5;margin:0 6px}.as-tool .grow{flex:1}.as-tool input{font:inherit;width:150px}
  .as-body{display:grid;grid-template-columns:260px 1fr;min-height:0;gap:4px;padding:4px}
  .as-left{display:flex;flex-direction:column;gap:4px;min-height:0}
  .as-pane{background:#fff;border:1px solid #9aa3ad;display:flex;flex-direction:column;min-height:0}
  .as-pane h4{margin:0;padding:3px 6px;background:linear-gradient(#5d7aa0,#3f5b80);color:#fff;font-weight:bold;font-size:12px}
  .as-pane .tree{padding:4px 2px;overflow:auto;flex:1}.as-pane .tree a{display:block;padding:2px 6px;cursor:pointer;white-space:nowrap}
  .as-pane .tree a:hover{background:#e6eef7}.as-pane .tree a.on{background:#316ac5;color:#fff}.as-pane .tree a.grp{font-weight:bold;cursor:default}
  .as-pane .tree a.l2{padding-left:20px}.as-pane .tree a.l3{padding-left:34px}.as-pane .tree a.na{color:#888}
  .as-dev{padding:4px 6px}.as-dev .acts{display:flex;gap:6px;margin-bottom:4px}.as-dev .acts span{color:#1f4f8f;cursor:default}
  .as-outlook button{display:block;width:100%;text-align:left;border:0;border-top:1px solid #9aa3ad;background:linear-gradient(#f4f6f8,#dde2e7);padding:6px 8px;font:inherit;cursor:pointer}
  .as-outlook button.on{background:linear-gradient(#cfe0f3,#a9c6e6);font-weight:bold}
  .as-main{background:#fff;border:1px solid #9aa3ad;display:flex;flex-direction:column;min-height:0}
  .as-head{padding:4px 8px;background:linear-gradient(#f2f4f6,#dfe3e8);border-bottom:1px solid #b8bec5;font-weight:bold;color:#1f3f6b}
  .as-content{padding:8px;overflow:auto;flex:1}
  .as-tabs{display:flex;gap:2px;border-bottom:1px solid #9aa3ad;margin-bottom:6px}.as-tabs a{padding:3px 12px;border:1px solid #9aa3ad;border-bottom:0;background:#e9ecef;cursor:pointer}
  .as-tabs a.on{background:#fff;font-weight:bold}
  .as-box{border:1px solid #9aa3ad;margin-bottom:8px}.as-box h5{margin:0;padding:3px 6px;background:linear-gradient(#eef1f4,#d9dee4);font-size:12px}
  .as-box .b{padding:6px 8px}.as-cols{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  .as-kv{display:grid;grid-template-columns:130px 1fr;gap:3px 8px}
  .as-t{width:100%;border-collapse:collapse}.as-t th{background:linear-gradient(#f7f7f7,#e1e4e8);border:1px solid #b8bec5;padding:3px 6px;text-align:left;font-weight:normal;white-space:nowrap}
  .as-t td{border:1px solid #e3e6e9;padding:3px 6px;white-space:nowrap;cursor:default}.as-t tr.grp td{background:#eef2f7;font-weight:bold}
  .as-t tr.sel td{background:#316ac5;color:#fff}.as-t tr.imp td{color:#777;font-style:italic}
  .as-t .ok{color:#1d8a32;font-weight:bold}.as-t .no{color:#c62828;font-weight:bold}
  .as-rt{display:flex;gap:4px;margin-bottom:6px;flex-wrap:wrap}.as-rt button{font:inherit;padding:2px 8px;border:1px solid #9aa3ad;background:linear-gradient(#fff,#e3e6e9);cursor:pointer}
  .as-apply{display:flex;justify-content:center;gap:10px;padding:6px;border-top:1px solid #b8bec5;background:#eef0f2}
  .as-apply button{font:inherit;padding:3px 18px;border:1px solid #8a939d;background:linear-gradient(#fff,#e1e4e8);cursor:pointer}
  .as-apply button.dirty{border-color:#c48a00;background:linear-gradient(#fff6d8,#f2d27a)}
  .as-status{display:flex;gap:16px;padding:3px 10px;background:#eceef0;border-top:1px solid #b8bec5;color:#333}
  .as-syslog{background:#000;color:#c8c8c8;font:11px Consolas,monospace;height:90px;padding:6px;overflow:auto}
  .px-shade.asdm .px-dialog{border:1px solid #6d7a88;font:12px Tahoma,Verdana,sans-serif}.px-shade.asdm .px-dtitle{background:linear-gradient(#5d7aa0,#3f5b80);color:#fff}
  .px-shade.asdm .px-dfoot button{font:inherit;padding:3px 18px;border:1px solid #8a939d;background:linear-gradient(#fff,#e1e4e8);cursor:pointer}
  .px-shade.asdm fieldset{border:1px solid #b8bec5;margin:8px 0;padding:6px 10px}.px-shade.asdm legend{color:#1f3f6b}
  `);
  const asName = (port, i) => ['outside', 'inside', 'dmz'][i] || `inside${i}`;
  const asLevel = i => [0, 100, 50][i] ?? 100;
  const asIface = port => { const i = Object.keys(N().interfaces).indexOf(port); return i < 0 ? port : asName(port, i); };
  const AS_CONF = [['Device Setup', [['Startup Wizard', 'na'], ['Interface Settings', null], ['Interfaces', 'interfaces', 2], ['Routing', null], ['Static Routes', 'routes', 2],
    ['Device Name/Password', 'name', 1], ['System Time', 'na', 1]]], ['Firewall', [['Access Rules', 'rules'], ['NAT Rules', 'nat'], ['Service Policy Rules', 'na'],
    ['AAA Rules', 'na'], ['Filter Rules', 'na'], ['Objects', 'na'], ['Threat Detection', 'na'], ['Botnet Traffic Filter', 'na']]],
    ['Remote Access VPN', [['Introduction', 'vpn'], ['Network (Client) Access', 'vpn'], ['Clientless SSL VPN Access', 'vpn']]],
    ['Site-to-Site VPN', [['Connection Profiles', 'vpn'], ['Group Policies', 'vpn']]], ['Device Management', [['Management Access', 'na'], ['Licensing', 'na'],
      ['System Image/Configuration', 'na'], ['High Availability and Scalability', 'na'], ['Logging', 'na'], ['Users/AAA', 'na']]]];
  const AS_MON = [['Interfaces', [['ARP Table', 'na'], ['Interface Graphs', 'mon-if']]], ['VPN', [['VPN Statistics', 'vpn']]], ['Routing', [['Routes', 'mon-routes']]],
    ['Properties', [['Connections', 'mon-conn']]], ['Logging', [['Real-Time Log Viewer', 'na']]]];
  SKINS.asdm = {
    start: {mode: 'home', group: 'Firewall', page: 'rules'},
    draw(root) {
      const n = N(), d = D(), dirty = pending();
      const mode = view.mode, tree = mode === 'monitoring' ? AS_MON : AS_CONF;
      const group = tree.find(([g]) => g === view.group) || tree[0];
      const mgmt = ipOf(Object.values(n.interfaces).find(Boolean) || '') || '—';
      root.innerHTML = `<div class="as-title">Cisco ASDM for ASA - ${h(mgmt)} · ${h(n.name)} <span style="color:#555">(sous-ensemble Network LABS)</span></div>
        <div class="as-menu">${['File', 'View', 'Tools', 'Wizards', 'Window', 'Help'].map(m => `<span>${m}</span>`).join('')}</div>
        <div class="as-tool"><button data-mode="home" class="${mode === 'home' ? 'on' : ''}"><i>⌂</i>Home</button><button data-mode="configuration" class="${
          mode === 'configuration' ? 'on' : ''}"><i>⚙</i>Configuration</button><button data-mode="monitoring" class="${mode === 'monitoring' ? 'on' : ''}"><i>▦</i>Monitoring</button>
          <span class="sep"></span><button class="save"><i>💾</i>Save</button><button class="refresh"><i>↻</i>Refresh</button><button><i>◀</i>Back</button>
          <button><i>▶</i>Forward</button><button><i>?</i>Help</button><span class="grow"></span><input placeholder="Type topic to search"><button>Go</button></div>
        <div class="as-body"><div class="as-left"><div class="as-pane" style="flex:0 0 120px"><h4>Device List</h4><div class="as-dev"><div class="acts"><span>✚ Add</span>
          <span>✖ Delete</span><span>⚡ Connect</span></div><div>⊟ ${h(mgmt)}</div></div></div>${mode === 'home' ? '' : `<div class="as-pane" style="flex:1"><h4>${h(group[0])}</h4>
          <div class="tree">${group[1].map(([label, go, depth]) => go === null ? `<a class="grp">⊟ ${h(label)}</a>` : `<a class="l${(depth || 1) + 1}${go === 'na' || go === 'vpn' ? ' na' : ''}${
            go === view.page ? ' on' : ''}" data-go="${go}">${h(label)}</a>`).join('')}</div><div class="as-outlook">${tree.map(([g]) => `<button data-g="${h(g)}" class="${
            g === group[0] ? 'on' : ''}">${h(g)}</button>`).join('')}</div></div>`}</div>
          <div class="as-main"><div class="as-head">${mode === 'home' ? 'Home' : `${mode === 'monitoring' ? 'Monitoring' : 'Configuration'} &gt; ${h(group[0])} &gt; ${
            h((group[1].find(([, go]) => go === view.page) || ['', ''])[0])}`}</div><div class="as-content"></div>
          ${mode === 'configuration' ? `<div class="as-apply"><button class="apply${dirty ? ' dirty' : ''}">Apply</button><button class="reset">Reset</button></div>` : ''}</div></div>
        <div class="as-status"><span>admin</span><span>15</span><span>${dirty ? '⚠ ' + dirty + ' modification(s) non appliquée(s)' : '🔒'}</span><span>${new Date().toLocaleString('fr-FR')}</span></div>`;
      root.querySelectorAll('[data-mode]').forEach(b => { b.onclick = () => { view.mode = b.dataset.mode; if (view.mode === 'monitoring') { view.group = 'Interfaces'; view.page = 'mon-if'; }
        if (view.mode === 'configuration') { view.group = 'Firewall'; view.page = 'rules'; } render(); }; });
      root.querySelectorAll('[data-g]').forEach(b => { b.onclick = () => { const items = tree.find(([g]) => g === b.dataset.g)[1];
        view.group = b.dataset.g; view.page = (items.find(([, go]) => go && go !== 'na' && go !== 'vpn') || items.find(([, go]) => go) || [])[1]; render(); }; });
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { view.page = a.dataset.go; render(); }; });
      root.querySelector('.save').onclick = () => toast('write memory : la configuration courante est celle du projet.');
      root.querySelector('.refresh').onclick = () => load();
      const apply = root.querySelector('.apply');
      if (apply) apply.onclick = () => attempt(() => commit(asRouteCli), 'Configuration envoyée à l’ASA (Apply).');
      const reset = root.querySelector('.reset');
      if (reset) reset.onclick = discard;
      const main = root.querySelector('.as-content');
      if (mode === 'home') return asHome(main);
      const pages = {interfaces: asInterfaces, rules: asRules, nat: asNat, routes: asRoutes, name: asName2, 'mon-if': asMonIf, 'mon-routes': asMonRoutes, 'mon-conn': asMonConn,
        vpn: m => { m.innerHTML = naBox('VPN', NA.vpn); }};
      (pages[view.page] || (m => { m.innerHTML = naBox('Configuration', NA.later); }))(main);
    },
  };
  const asRouteCli = (network, gateway) => (gateway ? `ip route ${ipOf(network)} ${maskOf(lenOf(network))} ${gateway}`
    : `no ip route ${ipOf(network)} ${maskOf(lenOf(network))} ${D().static.find(r => r.network === network).gateway}`);
  function asHome(main) {
    const d = D(), n = N();
    main.innerHTML = `<div class="as-tabs"><a class="on">Device Dashboard</a><a>Firewall Dashboard</a></div><div class="as-cols">
      <div class="as-box"><h5>Device Information</h5><div class="b"><div class="as-tabs"><a class="on">General</a><a>License</a><a>Virtual Resources</a></div><div class="as-kv">
        <span>Host Name:</span><b>${h(n.name)}</b><span>ASA Version:</span><b>sous-ensemble Network LABS</b><span>Device Uptime:</span><b>${running() ? 'en marche' : '—'}</b>
        <span>ASDM Version:</span><b>—</b><span>Firewall Mode:</span><b>Routed</b><span>Context Mode:</span><b>Single</b><span>Total Memory:</span><b>${h(n.memory_mib || 128)} MB</b>
        <span>Device Type:</span><b>${h(d.brand)} ${h(d.model)}</b></div></div></div>
      <div class="as-box"><h5>VPN Sessions</h5><div class="b as-kv"><span>IPsec:</span><b>0</b><span>Clientless SSL VPN:</span><b>0</b><span>AnyConnect Client:</span><b>0</b></div>
        <h5>System Resources Status</h5><div class="b as-kv"><span>CPU:</span><b>${running() ? '1%' : '—'}</b><span>Memory:</span><b>${running() ? '38 MB' : '—'}</b></div></div></div>
      <div class="as-box"><h5>Interface Status</h5>${table('as-t', ['Interface', 'IP Address/Mask', 'Line', 'Link', 'Kbps'], d.ports.map((p, i) => tr([h(asName(p.port, i)),
        h(p.address ? `${ipOf(p.address)}/${lenOf(p.address)}` : 'unassigned'), p.down ? '<span class="no">● down</span>' : '<span class="ok">● up</span>',
        p.peer && !p.down ? '<span class="ok">● up</span>' : '<span class="no">● down</span>', '0'])))}</div>
      <div class="as-box"><h5>Traffic Status</h5><div class="b">Connections Per Second Usage : 0 · '${h(asName('', 0))}' Interface Traffic Usage (Kbps) : 0</div></div>
      <div class="as-box"><h5>Latest ASDM Syslog Messages</h5><div class="as-syslog">Logging is disabled. To enable logging, go to Configuration &gt; Device Management &gt; Logging.</div></div>`;
  }
  function asInterfaces(main) {
    const d = D();
    main.innerHTML = `<div style="display:flex;gap:8px"><div style="flex:1">${table('as-t', ['Interface', 'Name', 'State', 'Security Level', 'IP Address', 'Subnet Mask Prefix Length',
      'Type', 'Management Only', 'MTU'], d.ports.map((p, i) => { const a = addressOf(p.port); return tr([h('GigabitEthernet' + p.name.slice(2)), h(asName(p.port, i)),
      p.down ? 'Disabled' : 'Enabled', String(asLevel(i)), h(ipOf(a)), h(a ? `${maskOf(lenOf(a))}` : ''), 'Hardware', 'No', '1500'], `data-i="${i}"`); }))}</div>
      <div class="as-rt" style="flex-direction:column"><button class="edit">Edit</button><button disabled>Add ▾</button><button disabled>Delete</button></div></div>
      <p>☐ Enable traffic between two or more interfaces which are configured with same security levels</p>`;
    let chosen = null;
    main.querySelectorAll('tr[data-i]').forEach(row => { row.onclick = () => { main.querySelectorAll('tr.sel').forEach(r => r.classList.remove('sel')); row.classList.add('sel'); chosen = Number(row.dataset.i); };
      row.ondblclick = () => asEditIf(chosen); });
    main.querySelector('.edit').onclick = () => (chosen === null ? toast('Sélectionner une interface.', true) : asEditIf(chosen));
  }
  function asEditIf(i) {
    const p = D().ports[i], a = addressOf(p.port);
    dialog('asdm', 'Edit Interface', `<div class="as-tabs"><a class="on">General</a><a>Advanced</a><a>IPv6</a></div>${field('Hardware Port:', `<b>GigabitEthernet${h(p.name.slice(2))}</b>`)}
      ${field('Interface Name:', input('n', asName(p.port, i), 'disabled'))}${field('Security Level:', input('s', asLevel(i), 'disabled'))}
      ${field('', '<span>☐ Dedicate this interface to management only</span>')}${field('', `<span>${p.down ? '☐' : '☑'} Enable Interface</span>`)}
      <fieldset><legend>IP Address</legend>${field('', '<span>(•) Use Static IP &nbsp; ( ) Obtain Address via DHCP &nbsp; ( ) Use PPPoE</span>')}
      ${field('IP Address:', input('asIp', ipOf(a)))}${field('Subnet Mask:', input('asMask', a ? maskOf(lenOf(a)) : '255.255.255.0'))}</fieldset>`,
    [['OK', '', async box => {
      const ip = val(box, '#asIp'), prefix = prefixOf(val(box, '#asMask'));
      if (ip && (!validIp(ip) || prefix === null)) throw new Error('IP Address / Subnet Mask invalide.');
      stage().ifaces[p.port] = ip ? `${ip}/${prefix}` : '';
      render();
    }], ['Cancel'], ['Help', '', async () => true]]);
  }
  function asRules(main) {
    const f = candidateFw(), ports = Object.keys(N().interfaces);
    const groups = [...ports.map(port => [asIface(port), f.rules.map((r, i) => [r, i]).filter(([r]) => r.in === port)]), ['Global', f.rules.map((r, i) => [r, i]).filter(([r]) => !r.in)]]
      .filter(([, list]) => list.length);
    const rows = groups.flatMap(([name, list]) => [`<tr class="grp"><td colspan="10">⊟ ${h(name)} (${list.length} ${name === 'Global' ? '' : 'incoming '}rule${list.length > 1 ? 's' : ''})</td></tr>`,
      ...list.map(([r, i], k) => tr([String(k + 1), '☑', h(r.source || 'any'), h(r.destination || 'any') + (r.out ? ` <span style="color:#777">(${h(asIface(r.out))})</span>` : ''),
        h(svc(r) === 'any' ? 'ip' : svc(r)), r.action === 'accept' ? '<span class="ok">✔ Permit</span>' : '<span class="no">✖ Deny</span>', '0', '', '', h(r.name)], `data-r="${i}"`))]);
    rows.push(`<tr class="imp"><td></td><td>☑</td><td>any</td><td>any</td><td>ip</td><td>${f.default === 'accept' ? 'Permit' : '✖ Deny'}</td><td></td><td></td><td></td><td>Implicit rule</td></tr>`);
    main.innerHTML = `<div class="as-rt"><button class="add">✚ Add ▾</button><button class="edit">✎ Edit</button><button class="del">✖ Delete</button><button class="up">↑</button>
      <button class="down">↓</button><button disabled>✂</button><button disabled>⧉</button><button disabled>📋 ▾</button><button disabled>🔍 Find</button><button disabled>Diagram</button>
      <button disabled>Export ▾</button><button disabled>Clear Hits</button><button disabled>Show Log</button><button class="trace">Packet Trace</button></div>
      ${table('as-t', ['#', 'Enabled', 'Source', 'Destination', 'Service', 'Action', 'Hits', 'Logging', 'Time', 'Description'], rows)}
      <p>Access Rule Type: (•) IPv4 and IPv6 &nbsp; ( ) IPv4 Only &nbsp; ( ) IPv6 Only</p>`;
    let chosen = null;
    main.querySelectorAll('tr[data-r]').forEach(row => { row.onclick = () => { main.querySelectorAll('tr.sel').forEach(r => r.classList.remove('sel')); row.classList.add('sel'); chosen = Number(row.dataset.r); };
      row.ondblclick = () => asEditRule(chosen); });
    main.querySelector('.add').onclick = () => asEditRule(null);
    main.querySelector('.edit').onclick = () => (chosen === null ? toast('Sélectionner une règle.', true) : asEditRule(chosen));
    main.querySelector('.del').onclick = () => { if (chosen === null) return toast('Sélectionner une règle.', true); editFw().rules.splice(chosen, 1); render(); };
    const move = step => { if (chosen === null) return; const list = editFw().rules, to = chosen + step; if (to < 0 || to >= list.length) return;
      [list[chosen], list[to]] = [list[to], list[chosen]]; render(); };
    main.querySelector('.up').onclick = () => move(-1);
    main.querySelector('.down').onclick = () => move(1);
    main.querySelector('.trace').onclick = () => toast('Packet Trace : ✉ Simulation de Network LABS suit un paquet à travers le lab.');
  }
  function asEditRule(index) {
    const r = index === null ? {action: 'accept'} : candidateFw().rules[index], ports = Object.keys(N().interfaces);
    dialog('asdm', index === null ? 'Add Access Rule' : 'Edit Access Rule', `${field('Interface:', select('asIn', [['', 'Any'], ...ports.map(p => [p, asIface(p)])], r.in || ''))}
      ${field('Action:', `<span><label><input type="radio" name="asAct" value="accept" ${r.action === 'accept' ? 'checked' : ''}> Permit</label>
        <label><input type="radio" name="asAct" value="drop" ${r.action !== 'accept' ? 'checked' : ''}> Deny</label></span>`)}
      <fieldset><legend>Source Criteria</legend>${field('Source:', input('asSrc', r.source || 'any'))}${field('User:', input('u', '', 'disabled'))}</fieldset>
      <fieldset><legend>Destination Criteria</legend>${field('Destination:', input('asDst', r.destination || 'any'))}${field('Service:', input('asSvc', svc(r) === 'any' ? 'ip' : svc(r)), 'ip, icmp, tcp/https, tcp/80, udp/53')}</fieldset>
      ${field('Description:', input('asName', r.name || ''))}${field('', '<span>☑ Enable Logging</span>')}
      <fieldset><legend>More Options</legend>${field('Traffic Direction:', select('d', ['In'], 'In'))}${field('Egress interface:', select('asOut', [['', 'Any'], ...ports.map(p => [p, asIface(p)])], r.out || ''))}</fieldset>`,
    [['OK', '', async box => {
      const name = val(box, '#asName') || `rule-${candidateFw().rules.length + 1}`;
      const rule = ruleFrom(index === null ? {} : r, {name, action: box.querySelector('input[name=asAct]:checked').value, in: val(box, '#asIn'), out: val(box, '#asOut'),
        source: checkNet(val(box, '#asSrc'), 'Source'), destination: checkNet(val(box, '#asDst'), 'Destination'), service: val(box, '#asSvc')});
      const list = editFw().rules;
      if (index === null) list.push(rule); else list[index] = rule;
      render();
    }], ['Cancel'], ['Help', '', async () => true]]);
  }
  function asNat(main) {
    const nat = candidateFw().nat || [];
    main.innerHTML = `<div class="as-rt"><button class="add">✚ Add ▾</button><button class="edit">✎ Edit</button><button class="del">✖ Delete</button><button class="up">↑</button>
      <button class="down">↓</button><button disabled>🔍 Find</button><button disabled>Diagram</button><button class="trace">Packet Trace</button></div>
      ${table('as-t', ['#', 'Source Intf', 'Dest Intf', 'Source', 'Destination', 'Service', 'Translated Source', 'Translated Destination', 'Translated Service', 'Options'], [
        `<tr class="grp"><td colspan="10">⊟ "Network Object" NAT (Rule ${nat.length ? 1 : 0}-${nat.length})</td></tr>`,
        ...nat.map((r, i) => tr([String(i + 1), h(r.in ? asIface(r.in) : 'Any'), h(r.out ? asIface(r.out) : 'Any'), h(r.source || 'any'), h(r.destination || 'any'),
          h(r.protocol && r.protocol !== 'any' ? svc(r) : 'any'), h(r.type === 'masquerade' ? `${r.out ? asIface(r.out) : 'interface'} (PAT)` : r.type === 'snat' ? r.to : 'Original'),
          h(r.type === 'dnat' ? r.to : 'Original'), h(r.to_port ? `tcp/${r.to_port}` : 'Original'), r.type === 'masquerade' ? 'Dynamic' : 'Static'], `data-r="${i}"`))])}`;
    let chosen = null;
    main.querySelectorAll('tr[data-r]').forEach(row => { row.onclick = () => { main.querySelectorAll('tr.sel').forEach(r => r.classList.remove('sel')); row.classList.add('sel'); chosen = Number(row.dataset.r); };
      row.ondblclick = () => asEditNat(chosen); });
    main.querySelector('.add').onclick = () => asEditNat(null);
    main.querySelector('.edit').onclick = () => (chosen === null ? toast('Sélectionner une règle NAT.', true) : asEditNat(chosen));
    main.querySelector('.del').onclick = () => (chosen === null ? toast('Sélectionner une règle NAT.', true) : dropEntry('nat', chosen, true).then(render));
    main.querySelector('.up').onclick = () => chosen !== null && moveEntry('nat', chosen, -1, true).then(render);
    main.querySelector('.down').onclick = () => chosen !== null && moveEntry('nat', chosen, 1, true).then(render);
    main.querySelector('.trace').onclick = () => toast('Packet Trace : ✉ Simulation de Network LABS suit un paquet à travers le lab.');
  }
  function asEditNat(index) {
    const r = index === null ? {type: 'masquerade'} : candidateFw().nat[index];
    const x = natPieces(r, {name: 'Description:', in: 'Source Interface:', out: 'Destination Interface:', source: 'Source Address:', destination: 'Destination Address:',
      service: 'Service:', type: 'Translation Type:', types: [['masquerade', 'Dynamic PAT (Hide)'], ['snat', 'Static (interface IP)'], ['dnat', 'Static (destination)']],
      to: 'Translated Destination:', to_port: 'Translated Service (port):', any: 'any'}, asIface);
    dialog('asdm', index === null ? 'Add NAT Rule' : 'Edit NAT Rule', `<fieldset><legend>Match Criteria: Original Packet</legend>${x.in}${x.out}${x.source}${x.destination}${x.service}</fieldset>
      <fieldset><legend>Action: Translated Packet</legend>${x.type}${x.to}${x.to_port}</fieldset><fieldset><legend>Options</legend>${field('', '<span>☑ Enable rule</span>')}${x.name}</fieldset>`,
    [['OK', '', async box => { await putEntry('nat', index, natRead(box), true); render(); }], ['Cancel'], ['Help', '', async () => true]]);
  }
  function asRoutes(main) {
    const list = staticRoutes();
    main.innerHTML = `<div style="display:flex;gap:8px"><div style="flex:1">${table('as-t', ['Interface', 'IP Address', 'Netmask', 'Gateway IP', 'Metric/Distance', 'Options'],
      list.map((r, i) => tr([h(r.port ? asIface(portByName(r.port)?.port || r.port) : '—'), h(ipOf(r.network)), h(maskOf(lenOf(r.network))), h(r.gateway), '1', 'None'], `data-i="${i}"`)))}</div>
      <div class="as-rt" style="flex-direction:column"><button class="add">Add</button><button class="del">Delete</button></div></div>`;
    let chosen = null;
    main.querySelectorAll('tr[data-i]').forEach(row => { row.onclick = () => { main.querySelectorAll('tr.sel').forEach(r => r.classList.remove('sel')); row.classList.add('sel'); chosen = Number(row.dataset.i); }; });
    main.querySelector('.add').onclick = () => dialog('asdm', 'Add Static Route', `${field('IP Address Type:', '<span>(•) IPv4 &nbsp; ( ) IPv6</span>')}
      ${field('Interface:', select('i', Object.keys(N().interfaces).map(p => asIface(p)), asIface(Object.keys(N().interfaces)[0])))}${field('Network:', input('asNet', '', 'placeholder="0.0.0.0/0"'))}
      ${field('Gateway IP:', input('asGw'))}${field('Metric:', input('m', '1'))}`, [['OK', '', async box => {
        const network = checkNet(val(box, '#asNet') || '0.0.0.0/0', 'Network') || '0.0.0.0/0';
        if (!validIp(val(box, '#asGw'))) throw new Error('Gateway IP : a.b.c.d');
        stage().routes.add.push({network: networkOf(network), gateway: val(box, '#asGw'), port: ''});
        render();
      }], ['Cancel'], ['Help', '', async () => true]]);
    main.querySelector('.del').onclick = () => {
      if (chosen === null) return toast('Sélectionner une route.', true);
      const r = list[chosen], s = stage();
      if (s.routes.add.includes(r)) s.routes.add.splice(s.routes.add.indexOf(r), 1); else s.routes.del.push(r.network);
      render();
    };
  }
  function asName2(main) {
    main.innerHTML = `<div class="as-box"><h5>Hostname and Domain Name</h5><div class="b">${field('Hostname:', input('asHost', (view.stage && view.stage.name) || N().name))}
      ${field('Domain Name:', input('dn', 'lab.local', 'disabled'))}</div></div><div class="as-box"><h5>Enable Password</h5><div class="b">${field('', '<span>☐ Change the privileged mode password</span>')}</div></div>`;
    main.querySelector('#asHost').onchange = event => { stage().name = event.target.value.trim() !== N().name ? event.target.value.trim() : null; render(); };
  }
  function asMonIf(main) {
    main.innerHTML = table('as-t', ['Interface', 'IP Address', 'Line', 'Link', 'Peer'], D().ports.map((p, i) => tr([h(asName(p.port, i)), h(p.address || 'unassigned'),
      p.down ? '<span class="no">down</span>' : '<span class="ok">up</span>', p.peer && !p.down ? '<span class="ok">up</span>' : '<span class="no">down</span>', h(p.peer || '')])));
  }
  function asMonRoutes(main) {
    main.innerHTML = table('as-t', ['Protocol', 'Type', 'Destination IP', 'Netmask', 'Gateway', 'Interface'], [...D().connected.map(r => tr(['CONNECTED', '-', h(ipOf(r.network)),
      h(maskOf(lenOf(r.network))), '-', h(r.port)])), ...D().static.map(r => tr(['STATIC', '-', h(ipOf(r.network)), h(maskOf(lenOf(r.network))), h(r.gateway), h(r.port)]))]);
  }
  function asMonConn(main) {
    const live = state.live;
    main.innerHTML = live && live.sessions ? table('as-t', ['Session'], live.sessions.map(s => tr([h(typeof s === 'string' ? s : JSON.stringify(s))])))
      : naBox('Connections', 'Lab en marche : relever l’état réel (◉ Network LABS › Vue Network LABS › relevé).');
  }

  /* =============================== pfSense =============================== */
  skinCss(`
  .px-app.pfsense{background:#fff;color:#212121;font:14px 'Roboto','Helvetica Neue',Arial,sans-serif}
  .pf-nav{display:flex;align-items:stretch;background:#212121;color:#fff;height:52px;padding:0 16px;position:relative}
  .pf-brand{display:flex;align-items:center;gap:6px;font-weight:bold;font-size:18px;margin-right:22px;letter-spacing:.2px}.pf-brand small{font-weight:normal;font-size:11px;color:#9e9e9e}
  .pf-nav>div.m{position:relative}.pf-nav>div.m>a{display:flex;align-items:center;height:100%;padding:0 13px;color:#e0e0e0;cursor:pointer}
  .pf-nav>div.m>a:hover,.pf-nav>div.m.open>a{background:#424242;color:#fff}.pf-nav .grow{flex:1}
  .pf-drop{display:none;position:absolute;top:52px;left:0;min-width:190px;background:#fff;box-shadow:0 6px 16px rgba(0,0,0,.25);z-index:8;padding:5px 0}
  .pf-nav>div.m.open .pf-drop{display:block}.pf-drop a{display:block;padding:6px 18px;color:#212121;cursor:pointer;white-space:nowrap}.pf-drop a:hover{background:#eee}
  .pf-drop a.na{color:#9e9e9e}
  .pf-page{padding:14px 22px}.pf-h1{font-size:26px;margin:4px 0 14px;font-weight:300}.pf-h1 b{font-weight:300;color:#555}
  .pf-tabs{display:flex;gap:2px;border-bottom:1px solid #ddd;margin-bottom:12px}.pf-tabs a{padding:8px 14px;color:#1e88e5;cursor:pointer;border:1px solid transparent;border-bottom:0}
  .pf-tabs a.on{color:#555;border-color:#ddd;background:#fff;position:relative;top:1px}
  .pf-panel{border:1px solid #ddd;margin-bottom:16px}.pf-panel>h2{margin:0;padding:8px 12px;background:#424242;color:#fff;font-size:15px;font-weight:normal}
  .pf-panel .b{padding:10px 12px}.pf-cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  .pf-t{width:100%;border-collapse:collapse}.pf-t th{text-align:left;padding:8px;border-bottom:2px solid #ddd;font-size:13px;white-space:nowrap}
  .pf-t td{padding:7px 8px;border-top:1px solid #ddd;font-size:13px;white-space:nowrap}.pf-t tbody tr:nth-child(odd) td{background:#f9f9f9}
  .pf-t tbody tr:hover td{background:#f0f0f0}.pf-t .k{width:180px;font-weight:bold}
  .pf-ok{color:#43a047}.pf-no{color:#e53935}.pf-ic{cursor:pointer;color:#1e88e5;margin-right:8px}
  .pf-btns{display:flex;gap:6px;justify-content:flex-end;margin:10px 0}
  .pf-btn{border:0;border-radius:3px;padding:7px 12px;color:#fff;cursor:pointer;font:inherit;font-size:13px}
  .pf-btn.ok{background:#43a047}.pf-btn.pri{background:#1e88e5}.pf-btn.del{background:#e53935}.pf-btn.info{background:#00acc1}.pf-btn.def{background:#fff;color:#212121;border:1px solid #ccc}
  .pf-alert{background:#fff8e1;border:1px solid #ffe082;color:#6d4c00;padding:12px 14px;margin-bottom:14px;display:flex;align-items:center;gap:14px}
  .pf-alert .grow{flex:1}
  .pf-form .row{display:grid;grid-template-columns:220px 1fr;gap:12px;align-items:center;padding:9px 12px;border-top:1px solid #eee}
  .pf-form .row>span{text-align:right;font-weight:bold;font-size:13px}.pf-form input,.pf-form select{font:inherit;font-size:13px;padding:6px 8px;border:1px solid #ccc;border-radius:3px}
  .pf-form small{display:block;color:#757575;font-size:12px;margin-top:3px}
  .px-nat .px-f{grid-template-columns:220px 1fr;padding:6px 12px;border-top:1px solid #eee;margin:0}.px-nat .px-f>span{text-align:right;font-weight:bold;font-size:13px}.pf-bar{height:14px;background:#eee;border-radius:2px;overflow:hidden;width:220px;display:inline-block;vertical-align:middle}
  .pf-bar i{display:block;height:100%;background:#43a047}
  `);
  const pfName = (port, i) => (i === 0 ? 'WAN' : i === 1 ? 'LAN' : `OPT${i - 1}`);
  const pfIface = port => { const i = Object.keys(N().interfaces).indexOf(port); return i < 0 ? port : pfName(port, i); };
  const PF_MENU = () => [['System', [['Advanced', 'na'], ['General Setup', 'general'], ['High Avail. Sync', 'na'], ['Package Manager', 'na'], ['Routing', 'routing'],
    ['Cert. Manager', 'na'], ['User Manager', 'na']]], ['Interfaces', [['Assignments', 'assign'], ...Object.keys(N().interfaces).map((p, i) => [pfName(p, i), 'if:' + p])]],
    ['Firewall', [['Aliases', 'na'], ['NAT', 'nat'], ['Rules', 'rules'], ['Schedules', 'na'], ['Traffic Shaper', 'na'], ['Virtual IPs', 'na']]],
    ['Services', [['DHCP Server', 'dhcp'], ['DNS Resolver', 'na'], ['NTP', 'na'], ['SNMP', 'na'], ['UPnP & NAT-PMP', 'na']]],
    ['VPN', [['IPsec', 'vpn'], ['L2TP', 'vpn'], ['OpenVPN', 'vpn'], ['WireGuard', 'vpn']]],
    ['Status', [['Dashboard', 'dashboard'], ['DHCP Leases', 'na'], ['Gateways', 'routing'], ['Interfaces', 'status-if'], ['System Logs', 'na']]],
    ['Diagnostics', [['ARP Table', 'na'], ['Command Prompt', 'terminal'], ['Packet Capture', 'na'], ['Ping', 'terminal'], ['Routes', 'diag-routes'], ['States', 'na']]],
    ['Help', [['About this Page', 'na']]]];
  SKINS.pfsense = {
    start: {page: 'dashboard'},
    draw(root) {
      const menu = PF_MENU();
      root.innerHTML = `<div class="pf-nav"><span class="pf-brand">pfSense <small>COMMUNITY EDITION · Network LABS</small></span>${menu.map(([m, items]) => `<div class="m"><a>${h(m)} ▾</a>
        <div class="pf-drop">${items.map(([label, go]) => `<a data-go="${go}" data-title="${h(m + ' / ' + label)}" class="${go === 'na' || go === 'vpn' ? 'na' : ''}">${h(label)}</a>`).join('')}</div></div>`).join('')}
        <span class="grow"></span><div class="m"><a class="out" title="Logout">⏻</a></div></div><div class="pf-page"></div>`;
      root.querySelectorAll('.pf-nav>div.m>a').forEach(a => { a.onclick = () => { const holder = a.parentElement, open = holder.classList.contains('open');
        root.querySelectorAll('.m.open').forEach(x => x.classList.remove('open')); if (!open) holder.classList.add('open'); }; });
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { view.page = a.dataset.go; view.title = a.dataset.title; view.edit = null; render(); }; });
      const main = root.querySelector('.pf-page');
      pfDispatch(main);
    },
  };
  function pfDispatch(main) {
    pfApplyBar(main);
    const go = view.page || 'dashboard';
    const pages = {dashboard: pfDashboard, rules: pfRules, nat: pfNat, assign: pfAssign, routing: pfRouting, dhcp: pfDhcp, general: pfGeneral, 'status-if': pfStatusIf,
      'diag-routes': pfDiagRoutes, terminal: m => { openTerminal(); pfDashboard(m); }, vpn: m => pfTitle(m, view.title, naBox(view.title, NA.vpn))};
    if (go.startsWith('if:')) return pfInterface(main, go.slice(3));
    (pages[go] || (m => pfTitle(m, view.title || '', naBox(view.title || '', NA.later))))(main);
  }
  function pfApplyBar(main) {
    if (!pending()) return;
    const opn = view.skin === 'opnsense';
    main.innerHTML = `<div class="pf-alert"><span class="grow">${opn ? 'The firewall rule configuration has been changed.<br>You must apply the changes in order for them to take effect.'
      : 'The firewall configuration has been changed. The changes must be applied for them to take effect.'}</span>
      <button class="pf-btn ok apply">${opn ? 'Apply changes' : '✔ Apply Changes'}</button><button class="pf-btn def undo">Discard</button></div>`;
    main.querySelector('.apply').onclick = () => attempt(() => commit(null), opn ? 'The changes have been applied successfully.' : 'The changes have been applied successfully.');
    main.querySelector('.undo').onclick = discard;
  }
  const pfTitle = (main, title, html) => {
    const shown = view.skin === 'opnsense' ? title.replace(/ \/ /g, ': ') : title, sep = view.skin === 'opnsense' ? ': ' : ' / ';
    main.insertAdjacentHTML('beforeend', `<div class="pf-h1">${h(shown).replace(sep, sep + '<b>')}${shown.includes(sep) ? '</b>' : ''}</div>${html}`);
  };
  function pfDashboard(main) {
    const n = N(), d = D();
    const bar = v => `<span class="pf-bar"><i style="width:${v}%"></i></span> ${v}%`;
    pfTitle(main, 'Status / Dashboard', `<div class="pf-cols"><div class="pf-panel"><h2>System Information</h2><table class="pf-t"><tbody>
      ${[['Name', h(n.name) + '.home.arpa'], ['User', 'admin@192.168.1.100 (Local Database)'], ['System', h(`${d.brand} ${d.model}`)], ['Version', 'sous-ensemble Network LABS (système Linux)'],
        ['Platform', 'Network LABS micro-VM'], ['CPU Type', `${h(n.vcpus || 1)} CPU(s)`], ['Uptime', running() ? 'en marche' : 'lab arrêté'], ['DNS server(s)', '127.0.0.1'],
        ['State table size', `${bar(0)} (0/${(n.memory_mib || 128) * 800})`], ['Load average', '0.00, 0.00, 0.00'], ['CPU usage', bar(running() ? 1 : 0)],
        ['Memory usage', bar(running() ? 35 : 0) + ` of ${h(n.memory_mib || 128)} MiB`], ['Disk usage ( / )', bar(12)]].map(([k, v]) => `<tr><td class="k">${k}</td><td>${v}</td></tr>`).join('')}
      </tbody></table></div><div><div class="pf-panel"><h2>Interfaces</h2><table class="pf-t"><tbody>${d.ports.map((p, i) => `<tr><td class="k">${h(pfName(p.port, i))}</td>
        <td>${p.peer && !p.down ? '<span class="pf-ok">▲</span>' : '<span class="pf-no">▼</span>'}</td><td>${p.peer && !p.down ? '1000baseT &lt;full-duplex&gt;' : 'no carrier'}</td>
        <td>${h(ipOf(p.address))}</td></tr>`).join('')}</tbody></table></div>
      <div class="pf-panel"><h2>Gateways</h2><table class="pf-t"><thead><tr><th>Name</th><th>RTT</th><th>Loss</th><th>Status</th></tr></thead><tbody>${n.gateway
        ? `<tr><td>WAN_GW<br><small>${h(n.gateway)}</small></td><td>—</td><td>—</td><td class="pf-ok">${running() ? 'Online' : 'Unknown'}</td></tr>` : '<tr class="px-none"><td colspan="4">No gateways</td></tr>'}</tbody></table></div>
      <div class="pf-panel"><h2>Firewall Rules</h2><div class="b">${candidateFw().rules.length} rules · ${(candidateFw().nat || []).length} NAT</div></div></div></div>`);
  }
  function pfRules(main) {
    const ports = Object.keys(N().interfaces), f = candidateFw();
    const tab = view.tab || ports[1] || ports[0];
    const list = f.rules.map((r, i) => [r, i]).filter(([r]) => (tab === 'floating' ? !r.in : r.in === tab));
    const proto = r => (!r.protocol || r.protocol === 'any' ? 'IPv4 *' : 'IPv4 ' + r.protocol.toUpperCase());
    pfTitle(main, 'Firewall / Rules / ' + (tab === 'floating' ? 'Floating' : pfIface(tab)), `<div class="pf-tabs"><a data-t="floating" class="${tab === 'floating' ? 'on' : ''}">Floating</a>${
      ports.map(p => `<a data-t="${p}" class="${p === tab ? 'on' : ''}">${h(pfIface(p))}</a>`).join('')}</div><div class="pf-panel"><h2>Rules (Drag to Change Order)</h2>
      <table class="pf-t"><thead><tr><th></th><th></th><th>States</th><th>Protocol</th><th>Source</th><th>Port</th><th>Destination</th><th>Port</th><th>Gateway</th><th>Queue</th>
      <th>Schedule</th><th>Description</th><th>Actions</th></tr></thead><tbody>${list.length ? list.map(([r, i]) => `<tr><td><input type="checkbox" data-c="${i}"></td>
        <td>${r.action === 'accept' ? '<span class="pf-ok">✔</span>' : '<span class="pf-no">✖</span>'}</td><td>0/0 B</td><td>${h(proto(r))}</td><td>${h(r.source || '*')}</td><td>*</td>
        <td>${h(r.destination || '*')}${r.out ? ` <small>(${h(pfIface(r.out))})</small>` : ''}</td><td>${h(r.dport || '*')}</td><td>*</td><td>none</td><td></td><td>${h(r.name)}</td>
        <td><span class="pf-ic" data-e="${i}" title="Edit">✎</span><span class="pf-ic" data-x="${i}" title="Delete">🗑</span></td></tr>`).join('')
        : '<tr class="px-none"><td colspan="13">No rules are currently defined for this interface. All incoming connections on this interface will be blocked until pass rules are added.</td></tr>'}
      </tbody></table></div><div class="pf-btns"><button class="pf-btn ok add">↑ Add</button><button class="pf-btn ok add">↓ Add</button><button class="pf-btn del dels">🗑 Delete</button>
      <button class="pf-btn pri save">💾 Save</button><button class="pf-btn info">＋ Separator</button></div>`);
    main.querySelectorAll('[data-t]').forEach(a => { a.onclick = () => { view.tab = a.dataset.t; render(); }; });
    main.querySelectorAll('.add').forEach(b => { b.onclick = () => pfEditRule(null, tab === 'floating' ? '' : tab); });
    main.querySelectorAll('[data-e]').forEach(b => { b.onclick = () => pfEditRule(Number(b.dataset.e)); });
    main.querySelectorAll('[data-x]').forEach(b => { b.onclick = () => { editFw().rules.splice(Number(b.dataset.x), 1); render(); }; });
    main.querySelector('.dels').onclick = () => { const out = [...main.querySelectorAll('[data-c]:checked')].map(c => Number(c.dataset.c)).sort((a, b) => b - a);
      if (!out.length) return toast('Cocher les règles à supprimer.', true); out.forEach(i => editFw().rules.splice(i, 1)); render(); };
    main.querySelector('.save').onclick = () => toast(pending() ? 'Saved. Apply Changes to load them.' : 'Nothing to save.');
  }
  function pfEditRule(index, iface) {
    const f = candidateFw(), r = index === null ? {action: 'accept', in: iface} : f.rules[index], ports = Object.keys(N().interfaces);
    const page = document.querySelector('.pf-page');
    page.innerHTML = `<div class="pf-h1">Firewall / Rules / <b>Edit</b></div><div class="pf-panel pf-form"><h2>Edit Firewall Rule</h2>
      <div class="row"><span>Action</span><div>${select('pfAct', [['accept', 'Pass'], ['drop', 'Block']], r.action)}<small>Choose what to do with packets that match the criteria specified below.</small></div></div>
      <div class="row"><span>Interface</span><div>${select('pfIn', [['', '(Floating)'], ...ports.map(p => [p, pfIface(p)])], r.in || '')}</div></div>
      <div class="row"><span>Address Family</span><div>${select('af', ['IPv4'], 'IPv4')}</div></div>
      <div class="row"><span>Protocol</span><div>${select('pfProto', [['any', 'Any'], ['tcp', 'TCP'], ['udp', 'UDP'], ['icmp', 'ICMP']], r.protocol || 'any')}</div></div></div>
      <div class="pf-panel pf-form"><h2>Source</h2><div class="row"><span>Source</span><div>${input('pfSrc', r.source || 'any')}<small>any, single host a.b.c.d or network a.b.c.d/nn</small></div></div></div>
      <div class="pf-panel pf-form"><h2>Destination</h2><div class="row"><span>Destination</span><div>${input('pfDst', r.destination || 'any')}</div></div>
      <div class="row"><span>Destination Port Range</span><div>${input('pfPort', r.dport || '', 'placeholder="(other) / any"')}<small>Specify the destination port for this rule (TCP/UDP).</small></div></div>
      <div class="row"><span>Egress interface</span><div>${select('pfOut', [['', 'any'], ...ports.map(p => [p, pfIface(p)])], r.out || '')}<small>Network LABS : sortie de la règle (facultatif).</small></div></div></div>
      <div class="pf-panel pf-form"><h2>Extra Options</h2><div class="row"><span>Log</span><div>☐ Log packets that are handled by this rule</div></div>
      <div class="row"><span>Description</span><div>${input('pfName', r.name || '')}<small>A description may be entered here for administrative reference.</small></div></div></div>
      <div class="px-err"></div><button class="pf-btn pri save">💾 Save</button>`;
    page.querySelector('.save').onclick = () => {
      try {
        const protocol = val(page, '#pfProto'), port = val(page, '#pfPort');
        const rule = ruleFrom(index === null ? {} : r, {name: val(page, '#pfName') || `rule-${f.rules.length + 1}`, action: val(page, '#pfAct'), in: val(page, '#pfIn'),
          out: val(page, '#pfOut'), source: checkNet(val(page, '#pfSrc'), 'Source'), destination: checkNet(val(page, '#pfDst'), 'Destination'),
          service: protocol === 'any' ? 'any' : protocol === 'icmp' ? 'icmp' : `${protocol}/${port}`.replace(/\/$/, '')});
        const list = editFw().rules;
        if (index === null) list.push(rule); else list[index] = rule;
        view.page = 'rules'; view.tab = rule.in || 'floating'; render();
      } catch (error) { page.querySelector('.px-err').textContent = error.message; }
    };
  }
  function pfNat(main) {
    const nat = candidateFw().nat || [], tab = view.tab === 'Outbound' || view.tab === 'Port Forward' ? view.tab : 'Port Forward';
    const forwards = nat.map((r, i) => [r, i]).filter(([r]) => r.type === 'dnat'), outbound = nat.map((r, i) => [r, i]).filter(([r]) => r.type !== 'dnat');
    const acts = i => `<span class="pf-ic" data-e="${i}" title="Edit">✎</span><span class="pf-ic" data-x="${i}" title="Delete">🗑</span>`;
    pfTitle(main, 'Firewall / NAT / ' + tab, `<div class="pf-tabs">${['Port Forward', '1:1', 'Outbound', 'NPt'].map(t => `<a data-t="${t}" class="${t === tab ? 'on' : ''}">${t}</a>`).join('')}</div>
      ${tab === 'Outbound' ? `<div class="pf-panel"><h2>Outbound NAT Mode</h2><div class="b">( ) Automatic outbound NAT rule generation &nbsp; (•) Hybrid Outbound NAT rule generation
        &nbsp; ( ) Manual Outbound NAT rule generation &nbsp; ( ) Disable Outbound NAT</div></div><div class="pf-panel"><h2>Mappings</h2>${table('pf-t', ['Interface', 'Source', 'Source Port',
        'Destination', 'Destination Port', 'NAT Address', 'NAT Port', 'Static Port', 'Description', 'Actions'], outbound.map(([r, i]) => tr([h(r.out ? pfIface(r.out) : 'WAN'), h(r.source || 'any'), '*',
        h(r.destination || '*'), h(r.dport || '*'), h(r.type === 'masquerade' ? (r.out ? pfIface(r.out) : 'WAN') + ' address' : r.to), '*', '✖', h(r.name), acts(i)])), 'No outbound mappings.')}</div>`
      : `<div class="pf-panel"><h2>Rules</h2>${table('pf-t', ['Interface', 'Protocol', 'Source Address', 'Source Ports', 'Dest. Address', 'Dest. Ports', 'NAT IP', 'NAT Ports', 'Description', 'Actions'],
        forwards.map(([r, i]) => tr([h(r.in ? pfIface(r.in) : 'WAN'), h((r.protocol || 'any').toUpperCase()), h(r.source || '*'), '*', h(r.destination || 'WAN address'), h(r.dport || '*'),
        h(r.to || ''), h(r.to_port || r.dport || '*'), h(r.name), acts(i)])), 'No port forward rules.')}</div>`}
      <div class="pf-btns"><button class="pf-btn ok add">↑ Add</button><button class="pf-btn ok add">↓ Add</button><button class="pf-btn pri save">💾 Save</button></div>`);
    main.querySelectorAll('[data-t]').forEach(a => { a.onclick = () => { view.tab = a.dataset.t; render(); }; });
    main.querySelectorAll('.add').forEach(b => { b.onclick = () => pfEditNat(null, tab === 'Outbound' ? 'masquerade' : 'dnat'); });
    main.querySelectorAll('[data-e]').forEach(b => { b.onclick = () => pfEditNat(Number(b.dataset.e)); });
    main.querySelectorAll('[data-x]').forEach(b => { b.onclick = () => dropEntry('nat', Number(b.dataset.x), true).then(render); });
    main.querySelector('.save').onclick = () => toast(pending() ? 'Saved. Apply Changes to load them.' : 'Nothing to save.');
  }
  function pfEditNat(index, kind) {
    const r = index === null ? {type: kind, in: wanPort(), out: wanPort()} : candidateFw().nat[index], forward = r.type === 'dnat';
    const x = natPieces(r, {name: 'Description', in: 'Interface', out: 'Interface', source: 'Source', destination: forward ? 'Destination' : 'Destination',
      service: forward ? 'Protocol / Destination port' : 'Protocol / port', type: 'Translation', to: 'Redirect target IP', to_port: 'Redirect target port',
      types: forward ? [['dnat', 'Port forward (redirect)']] : [['masquerade', 'Interface Address'], ['snat', 'Interface Address (static)']]}, pfIface);
    const page = document.querySelector('.pf-page'), title = forward ? 'Port Forward' : 'Outbound';
    page.innerHTML = '';
    pfTitle(page, `Firewall / NAT / ${title} / Edit`, `<div class="pf-panel pf-form px-nat"><h2>${forward ? 'Edit Redirect Entry' : 'Edit Advanced Outbound NAT Entry'}</h2>
      ${forward ? x.in + x.service + x.source + x.destination + x.to + x.to_port + '<input type="hidden" id="nxType" value="dnat">' : x.out + x.service + x.source + x.destination + x.type}${x.name}</div>
      <div class="px-err"></div><button class="pf-btn pri save">💾 Save</button>`);
    page.querySelector('.save').onclick = async () => {
      try { await putEntry('nat', index, natRead(page), true); view.page = 'nat'; view.tab = title; render(); } catch (error) { page.querySelector('.px-err').textContent = error.message; }
    };
  }
  function pfAssign(main) {
    pfTitle(main, 'Interfaces / Interface Assignments', `<div class="pf-tabs">${['Interface Assignments', 'Interface Groups', 'Wireless', 'VLANs', 'QinQs', 'PPPs', 'GREs', 'GIFs', 'Bridges', 'LAGGs']
      .map((t, i) => `<a class="${i ? '' : 'on'}">${t}</a>`).join('')}</div><div class="pf-panel"><h2>Interface Assignments</h2>${table('pf-t', ['Interface', 'Network port'],
      D().ports.map((p, i) => tr([`<a class="pf-ic" data-go="if:${h(p.port)}">${h(pfName(p.port, i))}</a>`, `${h(p.name)} <small>(${h(p.peer ? 'câble vers ' + p.peer : 'libre')})</small>`])))}</div>
      <div class="pf-btns"><button class="pf-btn pri">💾 Save</button></div>`);
    main.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { view.page = a.dataset.go; render(); }; });
  }
  function pfInterface(main, port) {
    const a = addressOf(port), i = Object.keys(N().interfaces).indexOf(port);
    pfTitle(main, `Interfaces / ${pfName(port, i)} (${portName(port)})`, `<div class="pf-panel pf-form"><h2>General Configuration</h2>
      <div class="row"><span>Enable</span><div>☑ Enable interface</div></div><div class="row"><span>Description</span><div>${input('d', pfName(port, i), 'disabled')}</div></div>
      <div class="row"><span>IPv4 Configuration Type</span><div>${select('pfType', [['static', 'Static IPv4'], ['none', 'None']], a ? 'static' : 'none')}</div></div>
      <div class="row"><span>IPv6 Configuration Type</span><div>${select('v6', ['None'], 'None')}</div></div><div class="row"><span>MTU</span><div>${input('mtu', '', 'disabled')}</div></div></div>
      <div class="pf-panel pf-form"><h2>Static IPv4 Configuration</h2><div class="row"><span>IPv4 Address</span><div>${input('pfIp', ipOf(a))} / ${select('pfLen',
        Array.from({length: 31}, (_, k) => 32 - k), lenOf(a))}</div></div><div class="row"><span>IPv4 Upstream gateway</span><div>${input('gw', i === 0 ? N().gateway || 'None' : 'None', 'disabled')}
        <small>Network LABS : la passerelle par défaut se règle dans System / Routing.</small></div></div></div>
      <div class="pf-panel pf-form"><h2>Reserved Networks</h2><div class="row"><span>Block private networks</span><div>☐</div></div><div class="row"><span>Block bogon networks</span><div>☐</div></div></div>
      <div class="px-err"></div><button class="pf-btn pri save">💾 Save</button>`);
    main.querySelector('.save').onclick = () => {
      const ip = val(main, '#pfIp');
      if (val(main, '#pfType') === 'static' && !validIp(ip)) { main.querySelector('.px-err').textContent = 'IPv4 Address invalide.'; return; }
      stage().ifaces[port] = val(main, '#pfType') === 'static' ? `${ip}/${val(main, '#pfLen')}` : '';
      render();
    };
  }
  function pfRouting(main) {
    const n = N(), tab = view.tab === 'Static Routes' ? 'Static Routes' : 'Gateways';
    pfTitle(main, 'System / Routing / ' + tab, `<div class="pf-tabs">${['Gateways', 'Static Routes', 'Gateway Groups'].map(t => `<a data-t="${t}" class="${t === tab ? 'on' : ''}">${t}</a>`).join('')}</div>
      ${tab === 'Gateways' ? `<div class="pf-panel"><h2>Gateways</h2>${table('pf-t', ['Name', 'Default', 'Interface', 'Gateway', 'Monitor IP', 'Description'], n.gateway
        ? [tr(['WAN_GW', '<span class="pf-ok">✔</span> Default (IPv4)', 'WAN', h(n.gateway), h(n.gateway), 'Interface WAN Gateway'])] : [])}</div>`
      : `<div class="pf-panel"><h2>Static Routes</h2>${table('pf-t', ['Network', 'Gateway', 'Interface', 'Description', 'Actions'], staticRoutes().map((r, i) => tr([h(r.network),
        h(r.gateway), h(r.port || ''), '', `<span class="pf-ic" data-x="${i}" title="Delete">🗑</span>`])), 'No routes')}</div>
        <div class="pf-btns"><button class="pf-btn ok add">＋ Add</button></div>`}`);
    main.querySelectorAll('[data-t]').forEach(a => { a.onclick = () => { view.tab = a.dataset.t; render(); }; });
    main.querySelectorAll('[data-x]').forEach(b => { b.onclick = () => { const r = staticRoutes()[Number(b.dataset.x)], st = stage();
      if (st.routes.add.includes(r)) st.routes.add.splice(st.routes.add.indexOf(r), 1); else st.routes.del.push(r.network); render(); }; });
    const add = main.querySelector('.add');
    if (add) add.onclick = () => {
      const page = document.querySelector('.pf-page');
      page.innerHTML = '';
      pfTitle(page, 'System / Routing / Static Routes / Edit', `<div class="pf-panel pf-form"><h2>Edit Route Entry</h2><div class="row"><span>Destination network</span>
        <div>${input('pfNet', '', 'placeholder="192.168.50.0"')} / ${select('pfNetLen', Array.from({length: 33}, (_, k) => 32 - k), 24)}<small>Destination network for this static route</small></div></div>
        <div class="row"><span>Gateway</span><div>${input('pfGw', '', 'placeholder="a.b.c.d"')}<small>The gateway, on the network of one of the interfaces</small></div></div>
        <div class="row"><span>Disabled</span><div>☐ Disable this static route</div></div><div class="row"><span>Description</span><div>${input('d')}</div></div></div>
        <div class="px-err"></div><button class="pf-btn pri save">💾 Save</button>`);
      page.querySelector('.save').onclick = () => {
        const net = val(page, '#pfNet'), gw = val(page, '#pfGw');
        if (!validIp(net) || !validIp(gw)) { page.querySelector('.px-err').textContent = 'Destination network et Gateway : a.b.c.d'; return; }
        stage().routes.add.push({network: networkOf(`${net}/${val(page, '#pfNetLen')}`), gateway: gw, port: ''});
        view.page = 'routing'; view.tab = 'Static Routes'; render();
      };
    };
  }
  function pfDhcp(main) {
    const ports = D().ports.filter(p => p.address && p !== D().ports[0]);
    const s = view.stage && view.stage.dhcp !== undefined ? view.stage.dhcp : dhcpServer();
    const tab = view.tab && ports.some(p => p.port === view.tab) ? view.tab : (s ? s.interface : ports[0]?.port);
    const on = s && s.interface === tab, a = N().interfaces[tab] || '';
    pfTitle(main, `Services / DHCP Server / ${pfIface(tab)}`, `<div class="pf-tabs">${ports.map(p => `<a data-t="${p.port}" class="${p.port === tab ? 'on' : ''}">${h(pfIface(p.port))}</a>`).join('')}</div>
      <div class="pf-panel pf-form"><h2>General Options</h2><div class="row"><span>Enable</span><div><label><input type="checkbox" id="pfOn" ${on ? 'checked' : ''}> Enable DHCP server on ${h(pfIface(tab))} interface</label></div></div>
      <div class="row"><span>Subnet</span><div>${h(networkOf(a))}</div></div><div class="row"><span>Address Pool Range</span><div>From ${input('pfFrom', on ? s.start : '')} To ${input('pfTo', on ? s.end : '')}</div></div></div>
      <div class="pf-panel pf-form"><h2>Server Options</h2><div class="row"><span>DNS Servers</span><div>${input('pfDns', on ? (s.dns || []).join(', ') : '')}</div></div></div>
      <div class="pf-panel pf-form"><h2>Other DHCP Options</h2><div class="row"><span>Gateway</span><div>${input('pfGw', on ? s.router || '' : ipOf(a))}<small>The default is to use the IP on this interface of the firewall as the gateway.</small></div></div>
      <div class="row"><span>Default Lease Time</span><div>${input('pfLease', on ? s.lease_seconds : 7200)}<small>seconds</small></div></div></div>
      <div class="px-err"></div><button class="pf-btn pri save">💾 Save</button>`);
    main.querySelectorAll('[data-t]').forEach(x => { x.onclick = () => { view.tab = x.dataset.t; render(); }; });
    main.querySelector('.save').onclick = () => {
      if (!main.querySelector('#pfOn').checked) { if (on) stage().dhcp = null; return render(); }
      stage().dhcp = {interface: tab, start: val(main, '#pfFrom'), end: val(main, '#pfTo'), router: val(main, '#pfGw'),
        dns: val(main, '#pfDns') ? val(main, '#pfDns').split(/[ ,]+/) : [], lease_seconds: Number(val(main, '#pfLease')) || 7200, reservations: []};
      render();
    };
  }
  function pfGeneral(main) {
    pfTitle(main, 'System / General Setup', `<div class="pf-panel pf-form"><h2>System</h2><div class="row"><span>Hostname</span><div>${input('pfHost', (view.stage && view.stage.name) || N().name)}
      <small>Name of the firewall host, without domain part.</small></div></div><div class="row"><span>Domain</span><div>${input('dm', 'home.arpa', 'disabled')}</div></div></div>
      <button class="pf-btn pri save">💾 Save</button>`);
    main.querySelector('.save').onclick = () => { const name = val(main, '#pfHost'); stage().name = name !== N().name ? name : null; render(); };
  }
  function pfStatusIf(main) {
    pfTitle(main, 'Status / Interfaces', D().ports.map((p, i) => `<div class="pf-panel"><h2>${h(pfName(p.port, i))} Interface (${h(p.name)})</h2><table class="pf-t"><tbody>
      ${[['Status', p.peer && !p.down ? 'up' : 'no carrier'], ['IPv4 Address', ipOf(p.address) || '—'], ['Subnet mask IPv4', p.address ? maskOf(lenOf(p.address)) : '—'],
        ['Media', p.peer ? '1000baseT <full-duplex>' : '—'], ['Peer', p.peer || '—']].map(([k, v]) => `<tr><td class="k">${k}</td><td>${h(v)}</td></tr>`).join('')}</tbody></table></div>`).join(''));
  }
  function pfDiagRoutes(main) {
    pfTitle(main, 'Diagnostics / Routes', `<div class="pf-panel"><h2>IPv4 Routes</h2>${table('pf-t', ['Destination', 'Gateway', 'Flags', 'Uses', 'Mtu', 'Netif'],
      [...D().connected.map(r => tr([h(r.network), 'link#', 'U', '0', '1500', h(r.port)])), ...D().static.map(r => tr([h(r.network), h(r.gateway), 'UGS', '0', '1500', h(r.port)]))])}</div>`);
  }

  /* =============================== OPNsense (pfSense's pages in OPNsense's frame) =============================== */
  skinCss(`
  .px-app.opnsense{background:#f7f7f7;color:#333;font:14px 'SourceSansPro','Helvetica Neue',Arial,sans-serif;display:grid;grid-template-columns:240px 1fr;min-height:100vh}
  .op-side{background:#3a3a3a;color:#ddd;align-self:stretch;border-radius:0;padding:0;margin:0}.op-brand{height:56px;display:flex;align-items:center;padding:0 18px;font-size:21px;color:#fff;background:#2c2c2c;letter-spacing:.3px}
  .op-brand b{color:#e76f24;font-weight:600}.op-group>a{display:flex;align-items:center;gap:10px;padding:10px 18px;color:#e2e2e2;cursor:pointer}
  .op-group>a:hover{background:#474747}.op-group.open>a{background:#2f2f2f;color:#fff}.op-group>a i{font-style:normal;width:16px;text-align:center;color:#bbb}
  .op-group>a .c{margin-left:auto;color:#999}.op-items{background:#2f2f2f}.op-items a{display:block;padding:7px 18px 7px 44px;color:#c8c8c8;cursor:pointer;font-size:13px}
  .op-items a:hover{color:#fff}.op-items a.on{color:#fff;border-left:3px solid #e76f24;padding-left:41px;background:#292929}.op-items a.na{color:#8a8a8a}
  .op-top{height:56px;background:#fff;border-bottom:1px solid #e3e3e3;display:flex;align-items:center;gap:14px;padding:0 20px}
  .op-top input{border:1px solid #ddd;border-radius:3px;padding:6px 10px;width:240px}.op-top .grow{flex:1}.op-top span{color:#666}
  .px-app.opnsense .pf-page{padding:18px 22px}.px-app.opnsense .pf-h1{font-size:20px;font-weight:600}.px-app.opnsense .pf-h1 b{font-weight:600;color:#333}
  .px-app.opnsense .pf-panel{background:#fff;border:1px solid #e3e3e3}.px-app.opnsense .pf-panel>h2{background:#fff;color:#333;border-bottom:1px solid #e3e3e3;font-weight:600}
  .px-app.opnsense .pf-btn.ok,.px-app.opnsense .pf-btn.pri{background:#e76f24}.px-app.opnsense .pf-tabs a{color:#e76f24}.px-app.opnsense .pf-ic{color:#e76f24}
  .px-app.opnsense .pf-alert{background:#dff0d8;border-color:#c6e1b8;color:#2f5f22}
  `);
  const OPN_MENU = () => {
    const ports = Object.keys(N().interfaces);
    return [['Lobby', '⌂', [['Dashboard', 'dashboard'], ['License', 'na'], ['Password', 'na']]], ['Reporting', '▤', [['Health', 'na'], ['Insight', 'na'], ['Traffic', 'na']]],
      ['System', '⚙', [['Access', 'na'], ['Configuration', 'na'], ['Firmware', 'na'], ['Gateways', 'routing:Gateways'], ['High Availability', 'na'], ['Routes', 'routing:Static Routes'],
        ['Settings', 'general'], ['Trust', 'na'], ['Diagnostics', 'na']]],
      ['Interfaces', '⇆', [...ports.map((p, i) => [`[${pfName(p, i)}]`, 'if:' + p]), ['Assignments', 'assign'], ['Overview', 'status-if'], ['Diagnostics', 'diag-routes']]],
      ['Firewall', '⛨', [['Aliases', 'na'], ['Rules: Floating', 'rules:floating'], ...ports.map((p, i) => [`Rules: ${pfName(p, i)}`, 'rules:' + p]),
        ['NAT: Port Forward', 'nat:Port Forward'], ['NAT: Outbound', 'nat:Outbound'], ['Shaper', 'na'], ['Settings', 'na'], ['Log Files', 'na']]],
      ['VPN', '⚿', [['IPsec', 'vpn'], ['OpenVPN', 'vpn'], ['WireGuard', 'vpn']]], ['Services', '☰', [['DHCPv4', 'dhcp'], ['Unbound DNS', 'na'], ['Network Time', 'na']]],
      ['Power', '⏻', [['Reboot', 'na'], ['Power Off', 'na']]], ['Help', '?', [['Documentation', 'na']]]];
  };
  SKINS.opnsense = {
    start: {page: 'dashboard', group: 'Lobby', item: 'Dashboard'},
    draw(root) {
      const menu = OPN_MENU();
      root.innerHTML = `<aside class="op-side"><div class="op-brand"><b>OPN</b>sense</div>${menu.map(([group, icon, items]) => `<div class="op-group${group === view.group ? ' open' : ''}">
        <a data-g="${h(group)}"><i>${icon}</i>${h(group)}<span class="c">${group === view.group ? '▾' : '▸'}</span></a>${group === view.group ? `<div class="op-items">${items.map(([label, go]) =>
          `<a data-go="${go}" data-l="${h(label)}" class="${['na', 'vpn'].includes(go) ? 'na' : ''}${label === view.item ? ' on' : ''}">${h(label)}</a>`).join('')}</div>` : ''}</div>`).join('')}</aside>
        <div><div class="op-top"><input placeholder="Search…"><span class="grow"></span><span>root@${h(N().name)}.localdomain · Network LABS</span><span>⏻</span></div>
        <div class="pf-page"></div></div>`;
      root.querySelectorAll('[data-g]').forEach(a => { a.onclick = () => { view.group = view.group === a.dataset.g ? '' : a.dataset.g; render(); }; });
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => {
        const [go, tab] = a.dataset.go.split(':');
        view.item = a.dataset.l; view.title = `${view.group} / ${a.dataset.l}`; view.edit = null;
        if (go === 'if') { view.page = a.dataset.go; view.tab = null; } else { view.page = go; view.tab = tab || null; }
        render();
      }; });
      pfDispatch(root.querySelector('.pf-page'));
    },
  };

  /* =============================== Palo Alto PAN-OS =============================== */
  skinCss(`
  .px-app.panos{background:#f4f5f5;color:#333;font:12px Arial,Helvetica,sans-serif;display:grid;grid-template-rows:46px 1fr;height:100vh}
  .pa-top{display:flex;align-items:stretch;background:#27323c;color:#d8dee3}
  .pa-top .tabs{display:flex}.pa-top .tabs a{display:flex;align-items:center;padding:0 16px;cursor:pointer;color:#d8dee3;font-size:13px;border-bottom:3px solid transparent}
  .pa-top .tabs a:hover{background:#334250}.pa-top .tabs a.on{background:#f4f5f5;color:#27323c;border-bottom-color:#f4f5f5;font-weight:bold}
  .pa-top .grow{flex:1}.pa-top .right{display:flex;align-items:center;gap:12px;padding:0 14px}
  .pa-commit{background:#fff;color:#27323c;border:0;border-radius:2px;padding:6px 14px;font:bold 12px Arial;cursor:pointer}.pa-commit.dirty{background:#f9a825;color:#000}
  .pa-body{display:grid;grid-template-columns:210px 1fr;min-height:0}
  .pa-tree{background:#fff;border-right:1px solid #d5d9dc;overflow:auto;padding:6px 0}
  .pa-tree a{display:block;padding:5px 14px;cursor:pointer;color:#333;white-space:nowrap}.pa-tree a:hover{background:#eef3f6}.pa-tree a.on{background:#dbe9f2;font-weight:bold}
  .pa-tree a.sub{padding-left:28px}.pa-tree a.na{color:#9aa3aa}
  .pa-main{display:flex;flex-direction:column;min-height:0}.pa-content{flex:1;overflow:auto;padding:0}
  .pa-t{width:100%;border-collapse:collapse;background:#fff}.pa-t th{background:#eceff1;border:1px solid #d5d9dc;padding:5px 7px;text-align:left;font-weight:bold;white-space:nowrap;color:#444}
  .pa-t td{border:1px solid #e6e9eb;padding:5px 7px;white-space:nowrap;vertical-align:top}.pa-t tbody tr:nth-child(even) td{background:#fafbfb}
  .pa-t tr.sel td{background:#cfe3f1!important}.pa-t tr.dflt td{color:#8a949b;font-style:italic;background:#f2f4f5}.pa-t a{color:#0b6ea8;cursor:pointer}
  .pa-zone{display:inline-flex;align-items:center;gap:4px}.pa-zone:before{content:'';width:10px;height:10px;background:#7aa6c2;border-radius:2px}
  .pa-allow{color:#2e7d32}.pa-deny{color:#c62828}
  .pa-bar{display:flex;gap:2px;padding:5px 8px;background:#eceff1;border-top:1px solid #d5d9dc;flex-wrap:wrap}
  .pa-bar button{border:0;background:none;padding:4px 8px;cursor:pointer;font:12px Arial;color:#333}.pa-bar button:hover{background:#dde3e7}.pa-bar button:disabled{color:#9aa3aa;cursor:default}
  .pa-sub{display:flex;gap:2px;padding:6px 8px 0;background:#f4f5f5;border-bottom:1px solid #d5d9dc}.pa-sub a{padding:6px 12px;cursor:pointer;color:#555}
  .pa-sub a.on{background:#fff;border:1px solid #d5d9dc;border-bottom:0;font-weight:bold;position:relative;top:1px}
  .pa-widgets{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;padding:10px}
  .pa-w{background:#fff;border:1px solid #d5d9dc}.pa-w h4{margin:0;padding:6px 9px;background:#eceff1;border-bottom:1px solid #d5d9dc;font-size:12px}
  .pa-w .b{padding:8px 10px}.pa-kv{display:grid;grid-template-columns:150px 1fr;gap:4px}.pa-kv span{color:#666}
  .pa-ports{display:flex;flex-wrap:wrap;gap:4px}.pa-ports i{width:22px;height:22px;background:#9aa3aa;display:grid;place-items:center;font-style:normal;color:#fff;font-size:9px}
  .pa-ports i.up{background:#43a047}.pa-ports i.down{background:#e53935}
  .px-shade.panos .px-dialog{border-radius:2px;font:12px Arial}.px-shade.panos .px-dtitle{background:#27323c;color:#fff}
  .px-shade.panos .px-dfoot button{border:1px solid #9aa3aa;background:#fff;padding:5px 18px;cursor:pointer;font:12px Arial}.px-shade.panos .px-dfoot button.pri{background:#0b6ea8;color:#fff;border-color:#0b6ea8}
  .pa-dtabs{display:flex;gap:2px;border-bottom:1px solid #d5d9dc;margin-bottom:10px}.pa-dtabs a{padding:6px 10px;cursor:pointer;color:#555}.pa-dtabs a.on{border-bottom:3px solid #0b6ea8;color:#000}
  .pa-dpane{display:none}.pa-dpane.on{display:block}
  `);
  const zoneOf = port => 'l3-' + portName(port).replace(/\//g, '-');
  const portOfZone = zone => Object.keys(N().interfaces).find(p => zoneOf(p) === zone) || '';
  const PA_TREE = {
    Dashboard: [], ACC: [], Monitor: [['Logs', null], ['Traffic', 'na', 1], ['Threat', 'na', 1], ['URL Filtering', 'na', 1], ['System', 'na', 1], ['Session Browser', 'sessions']],
    Policies: [['Security', 'security'], ['NAT', 'nat'], ['QoS', 'na'], ['Policy Based Forwarding', 'na'], ['Decryption', 'na'], ['Tunnel Inspection', 'na'], ['Application Override', 'na'],
      ['Authentication', 'na'], ['DoS Protection', 'na'], ['SD-WAN', 'na']],
    Objects: [['Addresses', 'na'], ['Address Groups', 'na'], ['Regions', 'na'], ['Applications', 'na'], ['Services', 'services'], ['Security Profiles', 'na'], ['Log Forwarding', 'na']],
    Network: [['Interfaces', 'interfaces'], ['Zones', 'zones'], ['VLANs', 'na'], ['Virtual Wires', 'na'], ['Virtual Routers', 'vrouters'], ['IPSec Tunnels', 'vpn'], ['GRE Tunnels', 'na'],
      ['DHCP', 'dhcp'], ['DNS Proxy', 'na'], ['GlobalProtect', 'vpn'], ['QoS', 'na'], ['LLDP', 'na'], ['Network Profiles', 'na']],
    Device: [['Setup', 'setup'], ['High Availability', 'na'], ['Config Audit', 'na'], ['Administrators', 'na'], ['Log Settings', 'na'], ['Server Profiles', 'na'], ['Software', 'na'], ['Licenses', 'na']],
  };
  SKINS.panos = {
    start: {tab: 'Dashboard', page: 'dashboard'},
    draw(root) {
      const dirty = pending(), tree = PA_TREE[view.tab];
      root.innerHTML = `<div class="pa-top"><div class="tabs">${Object.keys(PA_TREE).map(t => `<a data-t="${t}" class="${t === view.tab ? 'on' : ''}">${t}</a>`).join('')}</div>
        <span class="grow"></span><div class="right"><span>PAN-OS · sous-ensemble Network LABS</span><button class="pa-commit${dirty ? ' dirty' : ''}">Commit ▾</button><span>🔒</span><span>⚙</span>
        <span>admin</span></div></div><div class="pa-body">${tree.length ? `<nav class="pa-tree">${tree.map(([label, go, depth]) => go === null ? `<a><b>▾ ${h(label)}</b></a>`
          : `<a data-go="${go}" class="${depth ? 'sub ' : ''}${go === 'na' || go === 'vpn' ? 'na' : ''}${go === view.page ? ' on' : ''}" data-title="${h(label)}">${h(label)}</a>`).join('')}</nav>` : ''}
        <div class="pa-main" style="${tree.length ? '' : 'grid-column:1/-1'}"><div class="pa-content"></div></div></div>`;
      root.querySelectorAll('[data-t]').forEach(a => { a.onclick = () => { view.tab = a.dataset.t; const first = PA_TREE[view.tab].find(([, go]) => go && go !== 'na');
        view.page = view.tab === 'Dashboard' ? 'dashboard' : view.tab === 'ACC' ? 'acc' : first ? first[1] : 'na'; view.title = first ? first[0] : view.tab; render(); }; });
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { view.page = a.dataset.go; view.title = a.dataset.title; render(); }; });
      root.querySelector('.pa-commit').onclick = () => paCommit();
      const main = root.querySelector('.pa-content');
      const pages = {dashboard: paDashboard, security: paSecurity, nat: paNat, interfaces: paInterfaces, zones: paZones, vrouters: paRouters, setup: paSetup, dhcp: paDhcp,
        services: paServices, sessions: m => { m.innerHTML = naBox('Session Browser', state.live ? 'Relevé du nœud en marche : ◉ Network LABS › Vue Network LABS.' : 'Lab arrêté.'); },
        acc: m => { m.innerHTML = naBox('Application Command Center', NA.engine); }, vpn: m => { m.innerHTML = naBox(view.title, NA.vpn); }};
      (pages[view.page] || (m => { m.innerHTML = naBox(view.title || '', NA.later); }))(main);
    },
  };
  function paCommit() {
    const count = pending();
    dialog('panos', 'Commit', `<p>Doing a commit will overwrite the running configuration with the commit scope. ${count ? `<b>${count}</b> change(s) in the candidate configuration.`
      : 'There are no changes to commit.'}</p>${field('Commit Scope', '<span>(•) Commit All Changes &nbsp; ( ) Commit Changes Made By: admin</span>')}${field('Description', input('pd'))}`,
    [['Preview Changes', '', async () => { toast(count ? `${count} modification(s) : règles, interfaces, routes.` : 'No changes.'); return true; }], ['Validate Commit', '', async () => {
      toast('Validation: configuration is valid.'); return true; }], ['Commit', 'pri', async () => {
      if (!count) return;
      await commit(paRouteCli);
      render();
      dialog('panos', 'Commit Status', `<div class="pa-kv"><span>Operation</span><b>Commit</b><span>Status</span><b>Completed</b><span>Result</span><b class="pa-allow">Successful</b>
        <span>Progress</span><b>100%</b></div><p>Configuration committed successfully</p>`, [['Close']]);
      return true;
    }], ['Cancel']]);
  }
  const paRouteCli = (network, gateway) => (gateway ? `set network virtual-router default routing-table ip static-route r-${network.replace('/', '-')} destination ${network} nexthop ip-address ${gateway}`
    : `delete network virtual-router default routing-table ip static-route r-${network.replace('/', '-')}`);
  function paDashboard(main) {
    const n = N(), d = D(), f = candidateFw();
    main.innerHTML = `<div class="pa-widgets"><div class="pa-w"><h4>General Information</h4><div class="b pa-kv"><span>Device Name</span><b>${h(n.name)}</b>
      <span>MGT IP Address</span><b>${h(ipOf(Object.values(n.interfaces).find(Boolean) || '') || '—')}</b><span>Model</span><b>${h(d.model)}</b><span>Serial #</span><b>—</b>
      <span>Software Version</span><b>sous-ensemble Network LABS</b><span>Application Version</span><b>—</b><span>Threat Version</span><b>—</b><span>Uptime</span><b>${running() ? 'en marche' : 'lab arrêté'}</b>
      <span>Time</span><b>${new Date().toLocaleString('fr-FR')}</b></div></div>
      <div class="pa-w"><h4>Interfaces</h4><div class="b"><div class="pa-ports">${d.ports.map(p => `<i class="${p.down ? 'down' : p.peer ? 'up' : ''}" title="${h(p.name)}">${h(p.name.split('/').pop())}</i>`).join('')}</div>
        <p style="color:#666">■ up &nbsp; ■ down &nbsp; ■ not connected</p></div></div>
      <div class="pa-w"><h4>System Resources</h4><div class="b pa-kv"><span>Management CPU</span><b>${running() ? '2%' : '—'}</b><span>Data Plane CPU</span><b>${running() ? '0%' : '—'}</b>
        <span>Session Count</span><b>${state.live && state.live.sessions ? state.live.sessions.length : 0} / 64000</b></div></div>
      <div class="pa-w"><h4>Logged In Admins</h4><div class="b">${table('pa-t', ['Admin', 'From', 'Client', 'Session Start'], [tr(['admin', '127.0.0.1', 'Web', new Date().toLocaleTimeString('fr-FR')])])}</div></div>
      <div class="pa-w"><h4>Config Logs</h4><div class="b">${pending() ? `${pending()} change(s) not committed` : 'No data available.'}</div></div>
      <div class="pa-w"><h4>Security Policies</h4><div class="b pa-kv"><span>Rules</span><b>${f.rules.length}</b><span>NAT</span><b>${(f.nat || []).length}</b></div></div></div>`;
  }
  function paSecurity(main) {
    const f = candidateFw();
    const zone = port => (port ? `<span class="pa-zone">${h(zoneOf(port))}</span>` : 'any');
    const rows = f.rules.map((r, i) => tr([String(i + 1), `<a data-e="${i}">${h(r.name)}</a>`, 'none', 'universal', zone(r.in), h(r.source || 'any'), 'any', 'any', zone(r.out),
      h(r.destination || 'any'), 'any', 'any', h(svc(r) === 'any' ? 'any' : `${r.protocol}${r.dport ? '-' + r.dport : ''}`), r.action === 'accept' ? '<span class="pa-allow">⊕ Allow</span>'
        : '<span class="pa-deny">⊘ Deny</span>', 'none', '▤'], `data-r="${i}"`));
    rows.push(`<tr class="dflt"><td>${f.rules.length + 1}</td><td>intrazone-default</td><td>none</td><td>intrazone</td><td>any</td><td>any</td><td>any</td><td>any</td><td>(intrazone)</td><td>any</td>
      <td>any</td><td>any</td><td>any</td><td>⊕ Allow</td><td>none</td><td>▤</td></tr>`, `<tr class="dflt"><td>${f.rules.length + 2}</td><td>interzone-default</td><td>none</td><td>interzone</td>
      <td>any</td><td>any</td><td>any</td><td>any</td><td>any</td><td>any</td><td>any</td><td>any</td><td>any</td><td>${f.default === 'accept' ? '⊕ Allow' : '⊘ Deny'}</td><td>none</td><td>▤</td></tr>`);
    main.innerHTML = `<table class="pa-t"><thead><tr><th rowspan="2"></th><th rowspan="2">Name</th><th rowspan="2">Tags</th><th rowspan="2">Type</th><th colspan="4">Source</th>
      <th colspan="3">Destination</th><th rowspan="2">Application</th><th rowspan="2">Service</th><th rowspan="2">Action</th><th rowspan="2">Profile</th><th rowspan="2">Options</th></tr>
      <tr><th>Zone</th><th>Address</th><th>User</th><th>Device</th><th>Zone</th><th>Address</th><th>Device</th></tr></thead><tbody>${rows.join('')}</tbody></table>`;
    paToolbar(main, 'rules', i => paEditRule(i), () => paEditRule(null));
  }
  function paToolbar(main, kind, edit, add) {
    let chosen = null;
    main.parentElement.querySelector('.pa-bar')?.remove();
    main.querySelectorAll('tr[data-r]').forEach(row => { row.onclick = () => { main.querySelectorAll('tr.sel').forEach(r => r.classList.remove('sel')); row.classList.add('sel'); chosen = Number(row.dataset.r); }; });
    main.querySelectorAll('[data-e]').forEach(a => { a.onclick = () => edit(Number(a.dataset.e)); });
    const bar = document.createElement('div');
    bar.className = 'pa-bar';
    bar.innerHTML = `<button class="add">⊕ Add</button><button class="del">⊖ Delete</button><button class="clone">⧉ Clone</button><button disabled>Override</button><button disabled>Revert</button>
      <button disabled>☑ Enable</button><button disabled>☐ Disable</button><button class="up">Move ▴</button><button class="down">Move ▾</button><button disabled>PDF/CSV</button>
      <button disabled>Highlight Unused Rules</button>`;
    main.parentElement.append(bar);
    bar.querySelector('.add').onclick = add;
    if (!kind) { bar.querySelectorAll('.del,.clone,.up,.down').forEach(b => { b.disabled = true; }); return; }
    const need = fn => () => (chosen === null ? toast('Sélectionner une ligne.', true) : fn());
    bar.querySelector('.del').onclick = need(() => { editFw()[kind].splice(chosen, 1); render(); });
    bar.querySelector('.clone').onclick = need(() => { const copy = {...editFw()[kind][chosen]}; copy.name += '-1'; editFw()[kind].splice(chosen + 1, 0, copy); render(); });
    const move = step => need(() => { const l = editFw()[kind], to = chosen + step; if (to < 0 || to >= l.length) return; [l[chosen], l[to]] = [l[to], l[chosen]]; render(); });
    bar.querySelector('.up').onclick = move(-1);
    bar.querySelector('.down').onclick = move(1);
  }
  function paEditRule(index) {
    const f = candidateFw(), r = index === null ? {action: 'accept'} : f.rules[index], zones = Object.keys(N().interfaces).map(p => [zoneOf(p), zoneOf(p)]);
    const box = dialog('panos', 'Security Policy Rule', `<div class="pa-dtabs">${['General', 'Source', 'Destination', 'Application', 'Service/URL Category', 'Actions', 'Usage']
      .map((t, i) => `<a data-p="${i}" class="${i ? '' : 'on'}">${t}</a>`).join('')}</div>
      <div class="pa-dpane on" data-q="0">${field('Name', input('paName', r.name || ''))}${field('Rule Type', select('t', ['universal (default)'], ''))}${field('Description', input('d'))}${field('Tags', input('g'))}</div>
      <div class="pa-dpane" data-q="1">${field('Source Zone', select('paFrom', [['', 'any'], ...zones], r.in ? zoneOf(r.in) : ''))}${field('Source Address', input('paSrc', r.source || 'any'))}${field('Source User', select('u', ['any'], 'any'))}</div>
      <div class="pa-dpane" data-q="2">${field('Destination Zone', select('paTo', [['', 'any'], ...zones], r.out ? zoneOf(r.out) : ''))}${field('Destination Address', input('paDst', r.destination || 'any'))}</div>
      <div class="pa-dpane" data-q="3">${field('Application', '<span>☑ Any</span>', 'App-ID : moteur du constructeur, absent du laboratoire.')}</div>
      <div class="pa-dpane" data-q="4">${field('Service', input('paSvc', svc(r) === 'any' ? 'any' : svc(r)), 'any, application-default, service-http, service-https, tcp/22, udp/53')}${field('URL Category', '<span>☑ any</span>')}</div>
      <div class="pa-dpane" data-q="5">${field('Action', select('paAct', [['accept', 'Allow'], ['drop', 'Deny']], r.action))}${field('Log Setting', '<span>☑ Log at Session End</span>')}${field('Profile Type', select('pt', ['None'], 'None'))}</div>
      <div class="pa-dpane" data-q="6"><p>Rule Usage : hit counts are collected on the running device.</p></div>`,
    [['OK', 'pri', async b => {
      const rule = ruleFrom(index === null ? {} : r, {name: val(b, '#paName') || `rule${f.rules.length + 1}`, action: val(b, '#paAct'), in: portOfZone(val(b, '#paFrom')),
        out: portOfZone(val(b, '#paTo')), source: checkNet(val(b, '#paSrc'), 'Source Address'), destination: checkNet(val(b, '#paDst'), 'Destination Address'),
        service: val(b, '#paSvc').replace(/^service-/, '')});
      const list = editFw().rules;
      if (index === null) list.push(rule); else list[index] = rule;
      render();
    }], ['Cancel']]);
    box.querySelectorAll('[data-p]').forEach(a => { a.onclick = () => { box.querySelectorAll('[data-p]').forEach(x => x.classList.toggle('on', x === a));
      box.querySelectorAll('[data-q]').forEach(x => x.classList.toggle('on', x.dataset.q === a.dataset.p)); }; });
  }
  function paNat(main) {
    const nat = candidateFw().nat || [];
    main.innerHTML = `<table class="pa-t"><thead><tr><th rowspan="2"></th><th rowspan="2">Name</th><th rowspan="2">Tags</th><th colspan="6">Original Packet</th><th colspan="2">Translated Packet</th></tr>
      <tr><th>Source Zone</th><th>Destination Zone</th><th>Destination Interface</th><th>Source Address</th><th>Destination Address</th><th>Service</th><th>Source Translation</th>
      <th>Destination Translation</th></tr></thead><tbody>${nat.length ? nat.map((r, i) => tr([String(i + 1), `<a data-e="${i}">${h(r.name)}</a>`, 'none',
        r.in ? `<span class="pa-zone">${h(zoneOf(r.in))}</span>` : 'any', r.out ? `<span class="pa-zone">${h(zoneOf(r.out))}</span>` : 'any', h(r.out ? portName(r.out) : 'any'),
        h(r.source || 'any'), h(r.destination || 'any'), h(r.protocol && r.protocol !== 'any' ? svc(r) : 'any'),
        h(r.type === 'masquerade' ? `dynamic-ip-and-port ${r.out ? portName(r.out) : ''}` : r.type === 'snat' ? `static-ip ${r.to}` : 'none'),
        h(r.type === 'dnat' ? `address: ${r.to}${r.to_port ? ' port: ' + r.to_port : ''}` : 'none')], `data-r="${i}"`)).join('') : '<tr class="px-none"><td colspan="11">No NAT policy rules.</td></tr>'}</tbody></table>`;
    paToolbar(main, 'nat', i => paEditNat(i), () => paEditNat(null));
  }
  function paEditNat(index) {
    const r = index === null ? {type: 'masquerade'} : candidateFw().nat[index], zones = Object.keys(N().interfaces).map(p => [p, zoneOf(p)]);
    const x = natPieces(r, {name: 'Name', in: 'Source Zone', out: 'Destination Interface', source: 'Source Address', destination: 'Destination Address', service: 'Service',
      type: 'Translation Type', types: [['masquerade', 'Dynamic IP And Port (interface address)'], ['snat', 'Static IP (interface address)'], ['dnat', 'Destination: Static IP']],
      to: 'Translated Address', to_port: 'Translated Port', any: 'any'}, port => zoneOf(port));
    const box = dialog('panos', 'NAT Policy Rule', `<div class="pa-dtabs">${['General', 'Original Packet', 'Translated Packet'].map((t, i) => `<a data-p="${i}" class="${i ? '' : 'on'}">${t}</a>`).join('')}</div>
      <div class="pa-dpane on" data-q="0">${x.name}${field('Description', input('d'))}${field('NAT Type', select('t', ['ipv4'], 'ipv4'))}</div>
      <div class="pa-dpane" data-q="1">${x.in}${field('Destination Zone', select('dz', [['', 'any'], ...zones], ''))}${x.out}${x.service}${x.source}${x.destination}</div>
      <div class="pa-dpane" data-q="2">${x.type}<p style="color:#666">Source translation : Address Type « Interface Address » sur la Destination Interface.</p>${x.to}${x.to_port}</div>`,
    [['OK', 'pri', async b => { await putEntry('nat', index, natRead(b), true); render(); }], ['Cancel']]);
    box.querySelectorAll('[data-p]').forEach(a => { a.onclick = () => { box.querySelectorAll('[data-p]').forEach(y => y.classList.toggle('on', y === a));
      box.querySelectorAll('[data-q]').forEach(y => y.classList.toggle('on', y.dataset.q === a.dataset.p)); }; });
  }
  function paInterfaces(main) {
    const d = D(), vr = 'default';
    main.innerHTML = `<div class="pa-sub">${['Ethernet', 'VLAN', 'Loopback', 'Tunnel', 'SD-WAN'].map((t, i) => `<a class="${i ? '' : 'on'}">${t}</a>`).join('')}</div>
      <table class="pa-t"><thead><tr><th>Interface</th><th>Interface Type</th><th>Management Profile</th><th>Link State</th><th>IP Address</th><th>Virtual Router</th><th>Tag</th>
      <th>VLAN / Virtual-Wire</th><th>Security Zone</th><th>Features</th><th>Comment</th></tr></thead><tbody>${d.ports.map((p, i) => { const a = addressOf(p.port);
        return tr([`<a data-e="${i}">${h(p.name)}</a>`, 'Layer3', '', p.down ? '<span class="pa-deny">■</span>' : p.peer ? '<span class="pa-allow">■</span>' : '<span style="color:#9aa3aa">■</span>',
          h(a || 'none'), vr, 'Untagged', 'none', `<span class="pa-zone">${h(zoneOf(p.port))}</span>`, '', h(p.peer ? 'to ' + p.peer : '')], `data-r="${i}"`); }).join('')}</tbody></table>`;
    main.querySelectorAll('[data-e]').forEach(a => { a.onclick = () => paEditIf(d.ports[Number(a.dataset.e)]); });
  }
  function paEditIf(p) {
    const a = addressOf(p.port);
    const box = dialog('panos', 'Ethernet Interface', `${field('Interface Name', `<b>${h(p.name)}</b>`)}${field('Comment', input('c', p.peer ? 'to ' + p.peer : ''))}
      ${field('Interface Type', select('t', ['Layer3'], 'Layer3'))}${field('Netflow Profile', select('nf', ['None'], 'None'))}<div class="pa-dtabs"><a data-p="0" class="on">Config</a>
      <a data-p="1">IPv4</a><a data-p="2">IPv6</a><a data-p="3">Advanced</a></div><div class="pa-dpane on" data-q="0">${field('Virtual Router', select('vr', ['default'], 'default'))}
      ${field('Security Zone', select('z', [zoneOf(p.port)], zoneOf(p.port)))}</div><div class="pa-dpane" data-q="1">${field('Type', '<span>(•) Static &nbsp; ( ) PPPoE &nbsp; ( ) DHCP Client</span>')}
      ${field('IP', input('paIp', a, 'placeholder="a.b.c.d/nn"'), 'Une adresse par port dans le laboratoire.')}</div><div class="pa-dpane" data-q="2"><p>IPv6 : non disponible.</p></div>
      <div class="pa-dpane" data-q="3">${field('Link Speed', select('ls', ['auto'], 'auto'))}${field('Link Duplex', select('ld', ['auto'], 'auto'))}</div>`,
    [['OK', 'pri', async b => {
      const ip = val(b, '#paIp');
      if (ip && !/^\d+\.\d+\.\d+\.\d+\/\d+$/.test(ip)) throw new Error('IP : a.b.c.d/nn');
      stage().ifaces[p.port] = ip;
      render();
    }], ['Cancel']]);
    box.querySelectorAll('[data-p]').forEach(x => { x.onclick = () => { box.querySelectorAll('[data-p]').forEach(y => y.classList.toggle('on', y === x));
      box.querySelectorAll('[data-q]').forEach(y => y.classList.toggle('on', y.dataset.q === x.dataset.p)); }; });
  }
  function paZones(main) {
    main.innerHTML = table('pa-t', ['Name', 'Type', 'Interfaces / Virtual Systems', 'Zone Protection Profile', 'Packet Buffer Protection', 'Log Setting', 'Enabled (User-ID)'],
      D().ports.map(p => tr([`<span class="pa-zone">${h(zoneOf(p.port))}</span>`, 'layer3', h(p.name), '', '', '', ''])));
  }
  function paRouters(main) {
    const list = staticRoutes();
    main.innerHTML = `${table('pa-t', ['Name', 'Interfaces', 'Configuration', 'RIP', 'OSPF', 'OSPFv3', 'BGP', 'Multicast', 'Runtime Stats'], [tr(['<a data-e="0">default</a>',
      h(D().ports.map(p => p.name).join(', ')), `Static Routes: ${list.length}`, 'Disabled', D().ospf ? 'Enabled' : 'Disabled', 'Disabled', (D().features || []).some(f => f.name === 'BGP') ? 'Enabled' : 'Disabled',
      'Disabled', '<a>More Runtime Stats</a>'])])}`;
    main.querySelector('[data-e]').onclick = () => {
      const box = dialog('panos', 'Virtual Router - default', `<div class="pa-dtabs">${['Router Settings', 'Static Routes', 'Redistribution Profile', 'RIP', 'OSPF', 'OSPFv3', 'BGP', 'Multicast']
        .map((t, i) => `<a class="${i === 1 ? 'on' : ''}">${t}</a>`).join('')}</div>${table('pa-t', ['Name', 'Destination', 'Interface', 'Type', 'Value', 'Admin Distance', 'Metric', ''],
          list.map((r, i) => tr([`r-${h(r.network.replace('/', '-'))}`, h(r.network), h(r.port || ''), 'ip-address', h(r.gateway), 'default', '10', `<a data-x="${i}">⊖</a>`])))}
        <p><b>⊕ Add</b></p>${field('Destination', input('paDst', '', 'placeholder="0.0.0.0/0"'))}${field('Next Hop · IP Address', input('paNh'))}`,
      [['OK', 'pri', async b => {
        if (val(b, '#paDst') || val(b, '#paNh')) {
          const network = checkNet(val(b, '#paDst'), 'Destination') || '0.0.0.0/0';
          if (!validIp(val(b, '#paNh'))) throw new Error('Next Hop : a.b.c.d');
          stage().routes.add.push({network: networkOf(network), gateway: val(b, '#paNh'), port: ''});
        }
        render();
      }], ['Cancel']]);
      box.querySelectorAll('[data-x]').forEach(x => { x.onclick = () => { const r = list[Number(x.dataset.x)], s = stage();
        if (s.routes.add.includes(r)) s.routes.add.splice(s.routes.add.indexOf(r), 1); else s.routes.del.push(r.network); box.remove(); render(); }; });
    };
  }
  function paDhcp(main) {
    const s = view.stage && view.stage.dhcp !== undefined ? view.stage.dhcp : dhcpServer();
    main.innerHTML = `<div class="pa-sub"><a class="on">DHCP Server</a><a>DHCP Relay</a></div>${table('pa-t', ['Interface', 'Mode', 'Probe IP', 'IP Pools', 'Gateway', 'DNS', 'Lease'],
      s ? [tr([`<a data-e="1">${h(portName(s.interface))}</a>`, 'enabled', '☐', h(`${s.start}-${s.end}`), h(s.router || ''), h((s.dns || []).join(', ')), h(`${s.lease_seconds} s`)])] : [])}`;
    const edit = () => {
      const ports = D().ports.filter(p => p.address);
      dialog('panos', 'DHCP Server', `${field('Interface', select('paIf', ports.map(p => [p.port, p.name]), s ? s.interface : ports[0]?.port))}${field('Mode', select('m', ['enabled'], 'enabled'))}
        ${field('IP Pools', input('paPool', s ? `${s.start}-${s.end}` : '', 'placeholder="a.b.c.d-a.b.c.e"'))}${field('Gateway', input('paGw', s ? s.router : ''))}
        ${field('Primary DNS', input('paDns', s ? (s.dns || [])[0] || '' : ''))}${field('Lease (seconds)', input('paL', s ? s.lease_seconds : 86400))}`,
      [['OK', 'pri', async b => {
        const [start, end] = val(b, '#paPool').split('-').map(x => x.trim());
        stage().dhcp = {interface: val(b, '#paIf'), start, end, router: val(b, '#paGw'), dns: val(b, '#paDns') ? [val(b, '#paDns')] : [], lease_seconds: Number(val(b, '#paL')) || 86400, reservations: []};
        render();
      }], ['Cancel']]);
    };
    main.querySelector('[data-e]')?.addEventListener('click', edit);
    paToolbar(main, null, () => {}, edit);
  }
  function paServices(main) {
    main.innerHTML = table('pa-t', ['Name', 'Location', 'Protocol', 'Destination Port'], [['service-http', 'Predefined', 'TCP', '80,8080'], ['service-https', 'Predefined', 'TCP', '443']]
      .map(r => tr(r.map(h))));
  }
  function paSetup(main) {
    main.innerHTML = `<div class="pa-sub">${['Management', 'Operations', 'Services', 'Interfaces', 'Telemetry', 'Content-ID', 'WildFire', 'Session'].map((t, i) => `<a class="${i ? '' : 'on'}">${t}</a>`).join('')}</div>
      <div class="pa-widgets" style="grid-template-columns:1fr 1fr"><div class="pa-w"><h4>General Settings <a data-e="1" style="float:right">⚙</a></h4><div class="b pa-kv"><span>Hostname</span>
      <b>${h((view.stage && view.stage.name) || N().name)}</b><span>Domain</span><b></b><span>Login Banner</span><b></b><span>Time Zone</span><b>Europe/Paris</b></div></div></div>`;
    main.querySelector('[data-e]').onclick = () => dialog('panos', 'General Settings', field('Hostname', input('paHost', N().name)), [['OK', 'pri', async b => {
      const name = val(b, '#paHost'); stage().name = name !== N().name ? name : null; render(); }], ['Cancel']]);
  }

  /* =============================== Juniper J-Web =============================== */
  skinCss(`
  .px-app.jweb{background:#f2f4f6;color:#333;font:13px 'Open Sans',Arial,sans-serif;display:grid;grid-template-columns:230px 1fr;grid-template-rows:52px 1fr;height:100vh}
  .jw-top{grid-column:1/-1;display:flex;align-items:center;gap:14px;padding:0 16px;background:#fff;border-bottom:1px solid #d9dee3}
  .jw-top .prod{font-weight:bold;font-size:15px}.jw-top .prod small{font-weight:normal;color:#78838e;margin-left:8px}.jw-top .grow{flex:1}
  .jw-commit{position:relative}.jw-commit>button{border:1px solid #84b135;background:#84b135;color:#fff;padding:6px 14px;border-radius:2px;cursor:pointer;font:inherit}
  .jw-commit .n{background:#fff;color:#84b135;border-radius:9px;padding:0 6px;margin-left:6px;font-size:11px}
  .jw-commit .menu{display:none;position:absolute;right:0;top:34px;background:#fff;box-shadow:0 6px 18px rgba(0,0,0,.2);min-width:170px;z-index:9}
  .jw-commit.open .menu{display:block}.jw-commit .menu a{display:block;padding:8px 14px;cursor:pointer}.jw-commit .menu a:hover{background:#eef2f5}
  .jw-nav{background:#2b3a4a;color:#c9d2db;overflow:auto;padding:6px 0}
  .jw-nav a{display:flex;align-items:center;gap:10px;padding:9px 16px;cursor:pointer;color:#c9d2db}.jw-nav a:hover{background:#34475a}
  .jw-nav a.on{background:#1f2b37;color:#fff;border-left:3px solid #84b135;padding-left:13px}.jw-nav a.sub{padding-left:42px;font-size:12px}.jw-nav a.grp{color:#8fa0b1;font-size:11px;padding:10px 16px 4px;cursor:default;text-transform:uppercase}
  .jw-nav a.na{color:#6f8193}.jw-nav a i{font-style:normal;width:16px;text-align:center}
  .jw-main{padding:16px 20px;overflow:auto}.jw-h{font-size:20px;margin:0 0 12px;font-weight:normal}
  .jw-card{background:#fff;border:1px solid #d9dee3;margin-bottom:14px}.jw-card h3{margin:0;padding:10px 14px;font-size:14px;font-weight:600;border-bottom:1px solid #e6eaee;display:flex;align-items:center}
  .jw-card h3 .acts{margin-left:auto;display:flex;gap:10px}.jw-card h3 .acts a{cursor:pointer;color:#0076ce;font-weight:normal;font-size:16px}
  .jw-card .b{padding:12px 14px}.jw-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
  .jw-kv{display:grid;grid-template-columns:150px 1fr;gap:6px}.jw-kv span{color:#78838e}
  .jw-t{width:100%;border-collapse:collapse}.jw-t th{text-align:left;padding:8px 10px;background:#f7f8fa;border-bottom:1px solid #d9dee3;font-weight:600;white-space:nowrap;color:#4b5763}
  .jw-t td{padding:8px 10px;border-bottom:1px solid #edf0f2;white-space:nowrap}.jw-t.wrap th,.jw-t.wrap td{white-space:normal}.jw-t tr.sel td{background:#e3f0fa}.jw-t tbody tr:hover td{background:#f4f8fb}
  .jw-up{color:#84b135}.jw-dn{color:#d0021b}.jw-ports{display:flex;gap:12px;flex-wrap:wrap;background:#eef1f4;border:1px solid #dde2e7;padding:12px 14px 8px;border-radius:3px}
  .jw-pt{display:flex;flex-direction:column;align-items:center;gap:5px;font-size:11px;color:#4b5763;cursor:pointer}
  .jw-pt i{width:34px;height:28px;border:2px solid #9aa5b0;background:#2f3b47;border-radius:2px;position:relative}
  .jw-pt i::after{content:'';position:absolute;left:10px;right:10px;top:-2px;height:7px;background:#eef1f4}
  .jw-pt.up i{border-color:#84b135;box-shadow:0 0 6px rgba(132,177,53,.55)}.jw-pt.down i{border-color:#d0021b}.jw-pt:hover i{filter:brightness(1.4)}
  .jw-slide{position:fixed;top:0;right:0;bottom:0;width:480px;background:#fff;z-index:15;box-shadow:-6px 0 20px rgba(0,0,0,.2);display:flex;flex-direction:column}
  .jw-slide h2{margin:0;padding:16px 18px;font-size:17px;font-weight:normal;border-bottom:1px solid #e6eaee}.jw-slide .body{flex:1;overflow:auto;padding:14px 18px}
  .jw-slide .foot{padding:12px 18px;border-top:1px solid #e6eaee;display:flex;gap:8px;justify-content:flex-end}
  .jw-btn{border:1px solid #b9c2cb;background:#fff;padding:6px 16px;border-radius:2px;cursor:pointer;font:inherit}.jw-btn.pri{background:#0076ce;border-color:#0076ce;color:#fff}
  .jw-view{background:#fff;border:1px solid #d9dee3;font:12px Consolas,'DejaVu Sans Mono',monospace;white-space:pre;padding:12px;overflow:auto;max-height:70vh}
  `);
  const jwZone = (port, i) => (i === 0 ? 'untrust' : i === 1 ? 'trust' : i === 2 ? 'dmz' : `zone-${portName(port).replace(/[^a-z0-9]/gi, '')}`);
  const jwZoneOf = port => jwZone(port, Object.keys(N().interfaces).indexOf(port));
  const JW_NAV = role => [['Dashboard', 'dashboard', '◷'], ['Monitor', null], ['Interfaces', 'mon-if', '', 1], ['Routing', 'mon-route', '', 1], ['Device Administration', null],
    ['Basic Settings', 'basic', '', 1], ['CLI Tools', 'cli', '', 1], ['Network', null], ['Interfaces', 'interfaces', '', 1], ...(role === 'switch' ? [['VLAN', 'vlans', '', 1]] : []),
    ['DHCP Server', role === 'switch' ? 'na' : 'dhcp', '', 1], ['Static Routing', 'static', '', 1], ['OSPF', 'features', '', 1], ['BGP', 'features', '', 1],
    ...(role === 'firewall' ? [['Security Policies & Objects', null], ['Security Policies', 'policies', '', 1], ['Zones/Screens', 'zones', '', 1], ['Global Addresses', 'na', '', 1],
      ['Services', 'na', '', 1], ['NAT', null], ['Source NAT', 'nat', '', 1], ['Destination NAT', 'nat', '', 1], ['Security Services', null], ['IPS', 'engine', '', 1],
      ['Content Security', 'engine', '', 1], ['VPN', null], ['IPsec VPN', 'vpn', '', 1]] : [])];
  SKINS.jweb = {
    start: {page: 'dashboard', title: 'Dashboard'},
    draw(root) {
      const n = N(), d = D(), count = pending();
      root.innerHTML = `<div class="jw-top"><span class="prod">J-Web<small>${h(d.brand)} ${h(d.model)} · ${h(n.name)} · sous-ensemble Network LABS</small></span><span class="grow"></span>
        <div class="jw-commit"><button>Commit${count ? `<span class="n">${count}</span>` : ''} ▾</button><div class="menu"><a data-c="commit">Commit</a><a data-c="check">Commit Check</a>
        <a data-c="compare">Compare</a><a data-c="discard">Discard</a></div></div><span>?</span><span>root ▾</span></div>
        <nav class="jw-nav">${JW_NAV(n.role).map(([label, go, icon, sub]) => go === null ? `<a class="grp">${h(label)}</a>` : `<a data-go="${go}" data-title="${h(label)}" class="${sub ? 'sub ' : ''}${
          ['na', 'vpn', 'engine'].includes(go) ? 'na' : ''}${go === view.page && view.title === label ? ' on' : ''}">${icon ? `<i>${icon}</i>` : ''}${h(label)}</a>`).join('')}</nav><main class="jw-main"></main>`;
      root.querySelector('.jw-commit>button').onclick = () => root.querySelector('.jw-commit').classList.toggle('open');
      root.querySelectorAll('[data-c]').forEach(a => { a.onclick = () => {
        root.querySelector('.jw-commit').classList.remove('open');
        if (a.dataset.c === 'discard') return discard();
        if (a.dataset.c === 'check') return toast(count ? 'configuration check succeeds' : 'No changes to commit.');
        if (a.dataset.c === 'compare') return toast(count ? jwPreview().join('\n') : 'No changes.');
        if (!count) return toast('No changes to commit.');
        attempt(() => commit(jwRouteCli), 'commit complete');
      }; });
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { view.page = a.dataset.go; view.title = a.dataset.title; render(); }; });
      const main = root.querySelector('main');
      const pages = {dashboard: jwDashboard, interfaces: jwInterfaces, 'mon-if': jwInterfaces, static: jwStatic, 'mon-route': jwRouteTable, policies: jwPolicies, zones: jwZones,
        nat: jwNat, basic: jwBasic, cli: jwCli, dhcp: jwDhcp, vlans: jwVlans, features: m => { m.innerHTML = `<h1 class="jw-h">${h(view.title)}</h1><div class="jw-card"><div class="b">${table('jw-t',
          ['Protocol', 'Configuration'], (D().features || []).filter(f => f.name.toUpperCase().includes(view.title)).map(f => tr([h(f.name), h(f.detail)])), 'Not configured')}<p style="color:#78838e">
          Configurer en CLI : set protocols ${h(view.title.toLowerCase())} … (CLI Tools ou terminal).</p></div></div>`; },
        vpn: m => { m.innerHTML = `<h1 class="jw-h">${h(view.title)}</h1>${naBox(view.title, NA.vpn)}`; }, engine: m => { m.innerHTML = `<h1 class="jw-h">${h(view.title)}</h1>${naBox(view.title, NA.engine)}`; }};
      (pages[view.page] || (m => { m.innerHTML = `<h1 class="jw-h">${h(view.title || '')}</h1>${naBox(view.title || '', NA.later)}`; }))(main);
    },
  };
  const jwRouteCli = (network, gateway) => (gateway ? `set routing-options static route ${network} next-hop ${gateway}` : `delete routing-options static route ${network}`);
  const jwPreview = () => { const s = view.stage || {ifaces: {}, routes: {add: [], del: []}};
    return [...Object.entries(s.ifaces).map(([p, a]) => a ? `set interfaces ${portName(p)} unit 0 family inet address ${a}` : `delete interfaces ${portName(p)} unit 0 family inet`),
      ...s.routes.del.map(n => jwRouteCli(n)), ...s.routes.add.map(r => jwRouteCli(r.network, r.gateway)), ...(s.fw ? ['[edit security policies] …'] : []), ...(s.name ? [`set system host-name ${s.name}`] : [])]; };
  function jwSlide(title, body, ok) {
    document.querySelector('.jw-slide')?.remove();
    const slide = document.createElement('div');
    slide.className = 'jw-slide';
    slide.innerHTML = `<h2>${h(title)}</h2><div class="body">${body}<div class="px-err"></div></div><div class="foot"><button class="jw-btn cancel">Cancel</button><button class="jw-btn pri ok">OK</button></div>`;
    slide.querySelector('.cancel').onclick = () => slide.remove();
    slide.querySelector('.ok').onclick = async () => { try { await ok(slide); slide.remove(); render(); } catch (error) { slide.querySelector('.px-err').textContent = error.message; } };
    app.append(slide);
  }
  function jwDashboard(main) {
    const n = N(), d = D();
    main.innerHTML = `<h1 class="jw-h">Dashboard</h1><div class="jw-grid"><div class="jw-card"><h3>System Information</h3><div class="b jw-kv"><span>System Name</span><b>${h(n.name)}</b>
      <span>Device Model</span><b>${h(d.model.toLowerCase())}</b><span>Junos Version</span><b>sous-ensemble Network LABS</b><span>Serial Number</span><b>—</b>
      <span>System Uptime</span><b>${running() ? 'en marche' : 'lab arrêté'}</b></div></div><div class="jw-card"><h3>Resource Utilization</h3><div class="b jw-kv"><span>CPU Control Plane</span>
      <b>${running() ? '3%' : '—'}</b><span>Memory</span><b>${running() ? '42%' : '—'}</b><span>Storage</span><b>11%</b></div></div><div class="jw-card"><h3>Alarms</h3><div class="b jw-kv">
      <span>Major</span><b>0</b><span>Minor</span><b>0</b></div></div></div><div class="jw-card"><h3>Interface Status</h3><div class="b"><div class="jw-ports">${d.ports.map((p, i) =>
        `<span class="jw-pt ${p.down ? 'down' : p.peer ? 'up' : ''}" data-pi="${i}" title="${h(p.name + (p.peer ? ' → ' + p.peer : ' · not connected'))}"><i></i>${h(p.name)}</span>`).join('')}
      </div></div></div>`;
    main.querySelectorAll('[data-pi]').forEach(port => { port.onclick = () => jwEditIf(d.ports[Number(port.dataset.pi)]); });
  }
  function jwInterfaces(main) {
    const d = D(), fwRole = N().role === 'firewall';
    main.innerHTML = `<h1 class="jw-h">Interfaces</h1><div class="jw-card"><h3>Ports<span class="acts"><a class="edit" title="Edit">✎</a><a title="Delete" class="del">🗑</a></span></h3>
      ${table('jw-t', ['Interface', 'Link Status', 'IP Address', ...(fwRole ? ['Zone'] : []), 'Services', 'Description', 'Admin Status'], d.ports.map((p, i) => { const a = addressOf(p.port);
        return tr([`▸ ${h(p.name)}`, p.peer && !p.down ? '<span class="jw-up">▲ Up</span>' : '<span class="jw-dn">▼ Down</span>', h(a ? `${a} (${p.name}.0)` : ''), ...(fwRole ? [h(jwZoneOf(p.port))] : []),
          fwRole ? 'ping' : '', h(p.peer ? 'to ' + p.peer : ''), p.down ? 'Down' : 'Up'], `data-r="${i}"`); }))}</div>`;
    let chosen = null;
    main.querySelectorAll('tr[data-r]').forEach(row => { row.onclick = () => { main.querySelectorAll('tr.sel').forEach(r => r.classList.remove('sel')); row.classList.add('sel'); chosen = Number(row.dataset.r); };
      row.ondblclick = () => jwEditIf(d.ports[chosen]); });
    main.querySelector('.edit').onclick = () => (chosen === null ? toast('Select an interface.', true) : jwEditIf(d.ports[chosen]));
    main.querySelector('.del').onclick = () => { if (chosen === null) return toast('Select an interface.', true); stage().ifaces[d.ports[chosen].port] = ''; render(); };
  }
  function jwEditIf(p) {
    const a = addressOf(p.port);
    jwSlide(`Edit Logical Interface : ${p.name}.0`, field('Unit', input('u', '0', 'disabled')) + field('Description', input('d', p.peer ? 'to ' + p.peer : '')) + field('VLAN ID', input('v', '', 'disabled'))
      + field('IPv4 Address', input('jwIp', a, 'placeholder="a.b.c.d/nn"')) + (N().role === 'firewall' ? field('Zone', select('z', [jwZoneOf(p.port)], jwZoneOf(p.port))) : ''),
    async slide => {
      const ip = val(slide, '#jwIp');
      if (ip && !/^\d+\.\d+\.\d+\.\d+\/\d+$/.test(ip)) throw new Error('IPv4 Address : a.b.c.d/nn');
      stage().ifaces[p.port] = ip;
    });
  }
  function jwStatic(main) {
    const list = staticRoutes();
    main.innerHTML = `<h1 class="jw-h">Static Routing</h1><div class="jw-card"><h3>Static Routes<span class="acts"><a class="add">＋</a><a class="del">🗑</a></span></h3>${table('jw-t',
      ['Route', 'Next-Hop Address', 'Preference', 'Metric', 'Routing Instance'], list.map((r, i) => tr([h(r.network), h(r.gateway), '5', '', 'master'], `data-r="${i}"`)))}</div>`;
    let chosen = null;
    main.querySelectorAll('tr[data-r]').forEach(row => { row.onclick = () => { main.querySelectorAll('tr.sel').forEach(r => r.classList.remove('sel')); row.classList.add('sel'); chosen = Number(row.dataset.r); }; });
    main.querySelector('.add').onclick = () => jwSlide('Add Static Route', field('IP Address/Prefix', input('jwDst', '', 'placeholder="0.0.0.0/0"')) + field('Next-Hop', input('jwNh')) + field('Preference', input('p', '5')),
      async slide => {
        const network = checkNet(val(slide, '#jwDst'), 'IP Address/Prefix') || '0.0.0.0/0';
        if (!validIp(val(slide, '#jwNh'))) throw new Error('Next-Hop : a.b.c.d');
        stage().routes.add.push({network: networkOf(network), gateway: val(slide, '#jwNh'), port: ''});
      });
    main.querySelector('.del').onclick = () => { if (chosen === null) return toast('Select a route.', true); const r = list[chosen], s = stage();
      if (s.routes.add.includes(r)) s.routes.add.splice(s.routes.add.indexOf(r), 1); else s.routes.del.push(r.network); render(); };
  }
  function jwRouteTable(main) {
    const d = D();
    main.innerHTML = `<h1 class="jw-h">Routing</h1><div class="jw-card"><h3>Route Information · inet.0</h3>${table('jw-t', ['Destination', 'Protocol', 'Preference', 'Next-Hop', 'Interface'],
      [...d.connected.map(r => tr([h(r.network), 'Direct', '0', '', h(r.port + '.0')])), ...d.static.map(r => tr([h(r.network), 'Static', '5', h(r.gateway), h(r.port + '.0')]))])}</div>`;
  }
  function jwPolicies(main) {
    const f = candidateFw();
    main.innerHTML = `<h1 class="jw-h">Security Policies</h1><div class="jw-card"><h3>Rules (${f.rules.length})<span class="acts"><a class="add" title="Create">＋</a><a class="edit" title="Edit">✎</a>
      <a class="del" title="Delete">🗑</a><a class="up">↑</a><a class="down">↓</a></span></h3>${table('jw-t wrap', ['Seq.', 'Rule Name', 'Source Zone', 'Source Addresses', 'Destination Zone',
        'Destination Addresses', 'Dynamic Application', 'Services', 'Action', 'Hit Count'], [...f.rules.map((r, i) => tr([String(i + 1), h(r.name), h(r.in ? jwZoneOf(r.in) : 'any'),
        h(r.source || 'any'), h(r.out ? jwZoneOf(r.out) : 'any'), h(r.destination || 'any'), 'None', h(svc(r) === 'any' ? 'any' : `junos-${svc(r).replace('/', '-')}`),
        r.action === 'accept' ? '<span class="jw-up">✔ permit</span>' : '<span class="jw-dn">✖ deny</span>', '0'], `data-r="${i}"`)),
        tr(['', '<i>Global default policy</i>', 'any', 'any', 'any', 'any', '', 'any', f.default === 'accept' ? 'permit' : 'deny-all', ''])])}</div>`;
    let chosen = null;
    main.querySelectorAll('tr[data-r]').forEach(row => { row.onclick = () => { main.querySelectorAll('tr.sel').forEach(r => r.classList.remove('sel')); row.classList.add('sel'); chosen = Number(row.dataset.r); };
      row.ondblclick = () => jwEditRule(chosen); });
    main.querySelector('.add').onclick = () => jwEditRule(null);
    main.querySelector('.edit').onclick = () => (chosen === null ? toast('Select a rule.', true) : jwEditRule(chosen));
    main.querySelector('.del').onclick = () => { if (chosen === null) return toast('Select a rule.', true); editFw().rules.splice(chosen, 1); render(); };
    const move = step => () => { if (chosen === null) return; const l = editFw().rules, to = chosen + step; if (to < 0 || to >= l.length) return; [l[chosen], l[to]] = [l[to], l[chosen]]; render(); };
    main.querySelector('.up').onclick = move(-1);
    main.querySelector('.down').onclick = move(1);
  }
  function jwEditRule(index) {
    const f = candidateFw(), r = index === null ? {action: 'accept'} : f.rules[index], zones = Object.keys(N().interfaces).map(p => [p, jwZoneOf(p)]);
    jwSlide(index === null ? 'Create Rule' : `Edit Rule : ${r.name}`, field('Rule Name', input('jwName', r.name || '')) + field('Rule Description', input('d'))
      + field('Source Zone', select('jwFrom', [['', 'any'], ...zones], r.in || '')) + field('Source Addresses', input('jwSrc', r.source || 'any'))
      + field('Destination Zone', select('jwTo', [['', 'any'], ...zones], r.out || '')) + field('Destination Addresses', input('jwDst', r.destination || 'any'))
      + field('Services', input('jwSvc', svc(r) === 'any' ? 'any' : svc(r)), 'any, junos-http, junos-https, junos-ssh, junos-ping, tcp/8080')
      + field('Rule Action', select('jwAct', [['accept', 'permit'], ['drop', 'deny']], r.action)),
    async slide => {
      const rule = ruleFrom(index === null ? {} : r, {name: val(slide, '#jwName') || `rule-${f.rules.length + 1}`, action: val(slide, '#jwAct'), in: val(slide, '#jwFrom'), out: val(slide, '#jwTo'),
        source: checkNet(val(slide, '#jwSrc'), 'Source Addresses'), destination: checkNet(val(slide, '#jwDst'), 'Destination Addresses'), service: val(slide, '#jwSvc')});
      const list = editFw().rules;
      if (index === null) list.push(rule); else list[index] = rule;
    });
  }
  function jwZones(main) {
    main.innerHTML = `<h1 class="jw-h">Zones/Screens</h1><div class="jw-card">${table('jw-t', ['Zone Name', 'Zone Type', 'Interfaces', 'Host Inbound Services', 'Screen'],
      D().ports.map(p => tr([h(jwZoneOf(p.port)), 'security', h(p.name + '.0'), 'ping', ''])))}</div>`;
  }
  function jwNat(main) {
    const nat = candidateFw().nat || [], destination = view.title === 'Destination NAT';
    const list = nat.map((r, i) => [r, i]).filter(([r]) => (r.type === 'dnat') === destination);
    main.innerHTML = `<h1 class="jw-h">${destination ? 'Destination NAT' : 'Source NAT'}</h1><div class="jw-card"><h3>Rule Set rs1 · Rules<span class="acts"><a class="add" title="Create">＋</a>
      <a class="edit" title="Edit">✎</a><a class="del" title="Delete">🗑</a></span></h3>${table('jw-t', destination ? ['Rule Name', 'From', 'Destination Address', 'Destination Port', 'Action', 'Pool Address', 'Pool Port']
        : ['Rule Name', 'From', 'To', 'Source Address', 'Destination Address', 'Action'], list.map(([r, i]) => tr(destination
        ? [h(r.name), h(r.in ? jwZoneOf(r.in) : 'any'), h(r.destination || 'any'), h(r.dport || 'any'), 'pool', h(r.to), h(r.to_port || r.dport || '')]
        : [h(r.name), h(r.in ? jwZoneOf(r.in) : 'any'), h(r.out ? jwZoneOf(r.out) : 'any'), h(r.source || 'any'), h(r.destination || 'any'), r.type === 'masquerade' ? 'interface' : `pool ${h(r.to)}`],
        `data-r="${i}"`)), 'No NAT rules')}</div>`;
    let chosen = null;
    main.querySelectorAll('tr[data-r]').forEach(row => { row.onclick = () => { main.querySelectorAll('tr.sel').forEach(r => r.classList.remove('sel')); row.classList.add('sel'); chosen = Number(row.dataset.r); };
      row.ondblclick = () => jwEditNat(chosen, destination); });
    main.querySelector('.add').onclick = () => jwEditNat(null, destination);
    main.querySelector('.edit').onclick = () => (chosen === null ? toast('Select a rule.', true) : jwEditNat(chosen, destination));
    main.querySelector('.del').onclick = () => (chosen === null ? toast('Select a rule.', true) : dropEntry('nat', chosen, true).then(render));
  }
  function jwEditNat(index, destination) {
    const r = index === null ? {type: destination ? 'dnat' : 'masquerade'} : candidateFw().nat[index];
    const x = natPieces(r, {name: 'Rule Name', in: 'From (zone)', out: 'To (zone)', source: 'Source Address', destination: destination ? 'Destination Address (public)' : 'Destination Address',
      service: 'Destination Port (protocol/port)', type: 'Action', types: destination ? [['dnat', 'pool (translate)']] : [['masquerade', 'interface'], ['snat', 'pool (interface address)']],
      to: 'Pool Address', to_port: 'Pool Port'}, jwZoneOf);
    jwSlide(destination ? 'Create Destination NAT Rule' : 'Create Source NAT Rule', destination ? x.name + x.in + x.destination + x.service + x.type + x.to + x.to_port
      : x.name + x.in + x.out + x.source + x.destination + x.type, async slide => { await putEntry('nat', index, natRead(slide), true); });
  }
  function jwBasic(main) {
    main.innerHTML = `<h1 class="jw-h">Basic Settings</h1><div class="jw-card"><h3>System Identity</h3><div class="b">${field('Hostname', input('jwHost', (view.stage && view.stage.name) || N().name))}
      ${field('Domain', input('dm', '', 'disabled'))}${field('Root Password', input('pw', '********', 'disabled'))}<button class="jw-btn pri save">Save</button></div></div>`;
    main.querySelector('.save').onclick = () => { const name = val(main, '#jwHost'); stage().name = name !== N().name ? name : null; render(); toast('Saved to candidate configuration. Commit to activate.'); };
  }
  function jwCli(main) {
    main.innerHTML = `<h1 class="jw-h">CLI Tools</h1><div class="jw-card"><h3>CLI Viewer · show configuration | display set</h3><div class="b"><div class="jw-view">${h(state.config_text || '')}</div>
      <p><button class="jw-btn open">CLI Terminal</button></p></div></div><div class="jw-card"><h3>CLI Editor</h3><div class="b"><textarea class="jwText" style="width:100%;height:140px;font:12px Consolas,monospace"
      placeholder="set routing-options static route 0.0.0.0/0 next-hop 192.0.2.1"></textarea><p><button class="jw-btn pri load">Commit</button></p></div></div>`;
    main.querySelector('.open').onclick = openTerminal;
    main.querySelector('.load').onclick = () => attempt(() => cli(main.querySelector('.jwText').value), 'commit complete');
  }
  function jwDhcp(main) {
    const s = view.stage && view.stage.dhcp !== undefined ? view.stage.dhcp : dhcpServer();
    main.innerHTML = `<h1 class="jw-h">DHCP Server</h1><div class="jw-card"><h3>DHCP Pools<span class="acts"><a class="add">＋</a>${s ? '<a class="del">🗑</a>' : ''}</span></h3>${table('jw-t',
      ['Pool Name', 'Network Address', 'Address Range', 'Router', 'DNS', 'Lease Time'], s ? [tr(['pool1', h(networkOf(N().interfaces[s.interface])), h(`${s.start} - ${s.end}`), h(s.router || ''),
        h((s.dns || []).join(', ')), h(`${s.lease_seconds} s`)])] : [])}</div>`;
    main.querySelector('.add').onclick = () => { const ports = D().ports.filter(p => p.address);
      jwSlide('DHCP Pool', field('Interface', select('jwIf', ports.map(p => [p.port, p.name + '.0']), s ? s.interface : ports[0]?.port)) + field('Address Range Low', input('jwLo', s ? s.start : ''))
        + field('Address Range High', input('jwHi', s ? s.end : '')) + field('Router', input('jwR', s ? s.router : '')) + field('DNS Server', input('jwD', s ? (s.dns || []).join(',') : ''))
        + field('Lease Time (s)', input('jwL', s ? s.lease_seconds : 86400)), async slide => {
          stage().dhcp = {interface: val(slide, '#jwIf'), start: val(slide, '#jwLo'), end: val(slide, '#jwHi'), router: val(slide, '#jwR'),
            dns: val(slide, '#jwD') ? val(slide, '#jwD').split(',').map(x => x.trim()) : [], lease_seconds: Number(val(slide, '#jwL')) || 86400, reservations: []};
        }); };
    const del = main.querySelector('.del');
    if (del) del.onclick = () => { stage().dhcp = null; render(); };
  }
  function jwVlans(main) {
    const d = D();
    main.innerHTML = `<h1 class="jw-h">VLAN</h1><div class="jw-card"><h3>VLANs<span class="acts"><a class="add">＋</a></span></h3>${table('jw-t', ['VLAN Name', 'VLAN ID', 'Interfaces', 'Description'],
      d.vlans.map(v => tr([v === 1 ? 'default' : `vlan${v}`, String(v), h(d.ports.filter(p => !p.trunk && p.vlan === v).map(p => p.name + '.0').join(', ')), ''])))}</div>
      <div class="jw-card"><h3>Port Configuration</h3>${table('jw-t', ['Interface', 'Port Mode', 'VLAN'], d.ports.map((p, i) => tr([h(p.name), p.trunk ? 'trunk' : 'access',
        p.trunk ? 'all' : `<select data-p="${i}">${d.vlans.map(v => `<option${v === p.vlan ? ' selected' : ''}>${v}</option>`).join('')}</select>`])))}</div>`;
    main.querySelector('.add').onclick = () => jwSlide('Create VLAN', field('VLAN Name', input('jwVn')) + field('VLAN ID', input('jwVid', '', 'placeholder="2-4094"')), async slide => {
      const vid = Number(val(slide, '#jwVid'));
      if (!(vid >= 2 && vid <= 4094)) throw new Error('VLAN ID : 2-4094');
      const s = stage();
      s.vlans = s.vlans || {vlans: [...(N().vlans || [1])], switchports: JSON.parse(JSON.stringify(N().switchports || {}))};
      s.vlans.vlans = [...new Set([...s.vlans.vlans, vid])].sort((a, b) => a - b);
    });
    main.querySelectorAll('select[data-p]').forEach(box => { box.onchange = () => { const p = d.ports[Number(box.dataset.p)], s = stage();
      s.vlans = s.vlans || {vlans: [...(N().vlans || [1])], switchports: JSON.parse(JSON.stringify(N().switchports || {}))};
      s.vlans.switchports[p.port] = {mode: 'access', vlan: Number(box.value)}; render(); }; });
  }

  /* =============================== products managed from their CLI =============================== */
  skinCss(`
  .px-app.cli{background:#0d1117;color:#c9d1d9;font:13px Consolas,'DejaVu Sans Mono',monospace;display:grid;grid-template-rows:auto 1fr}
  .cl-top{display:flex;align-items:center;gap:12px;padding:8px 14px;background:#161b22;border-bottom:1px solid #30363d;font:13px Arial,sans-serif}
  .cl-top b{color:#fff}.cl-top .grow{flex:1}.cl-top button{background:#238636;border:0;color:#fff;border-radius:5px;padding:6px 12px;cursor:pointer;font:13px Arial}
  .cl-body{padding:14px 18px;white-space:pre-wrap;overflow:auto}.cl-note{font:13px Arial,sans-serif;color:#8b949e;max-width:860px;margin-bottom:14px;line-height:1.5}
  .cl-prompt{color:#7ee787}
  `);
  const CLI_PRODUCTS = {
    VyOS: ['vyos@{n}:~$', 'show configuration commands', 'VyOS n’a pas d’interface web : il se configure en ligne de commande (console ou SSH), en mode configure puis commit.'],
    Nokia: ['A:{n}#', 'admin show configuration', 'Le Nokia 7750 SR se gère en ligne de commande (SR OS, MD-CLI) ou par NSP : pas d’interface web sur l’équipement.'],
    Arista: ['{n}#', 'show running-config', 'Arista EOS se configure en ligne de commande (et par son API JSON eAPI) : pas d’interface web de configuration.'],
    Dell: ['{n}#', 'show running-configuration', 'Dell SmartFabric OS10 se configure en ligne de commande (console ou SSH) : pas d’interface web.'],
    Cisco: ['{n}#', 'show running-config', 'Cisco NX-OS se configure en ligne de commande (et par NX-API) : pas d’interface web de configuration.'],
    Extreme: ['{n}.1 #', 'show configuration', 'Extreme EXOS se configure en ligne de commande (console ou SSH) ; son interface web Chalet n’est pas reproduite ici.'],
  };
  function cliText() {
    if (state.config_text) return state.config_text;
    const n = N(), d = D();
    if (d.brand === 'VyOS') {
      return [`set system host-name '${n.name}'`, ...d.ports.filter(p => p.address).map(p => `set interfaces ethernet ${p.name} address '${p.address}'`),
        ...d.static.map(r => `set protocols static route ${r.network} next-hop ${r.gateway}`)].join('\n');
    }
    return [`# ${n.name}`, ...d.ports.map(p => `interface ${p.name}  ${p.address || 'no address'}  ${p.down ? 'shutdown' : 'no shutdown'}`),
      ...d.static.map(r => `static-route ${r.network} next-hop ${r.gateway}`)].join('\n');
  }
  SKINS.cli = {
    start: {},
    draw(root) {
      const n = N(), d = D(), [prompt, command, note] = CLI_PRODUCTS[d.brand] || CLI_PRODUCTS.Cisco;
      const shown = prompt.replace('{n}', n.name);
      root.innerHTML = `<div class="cl-top"><b>SSH · admin@${h(n.name)}</b><span>${h(d.brand)} ${h(d.model)}</span><span class="grow"></span><button class="open">⌨ Ouvrir la console</button></div>
        <div class="cl-body"><div class="cl-note">${h(note)} Le terminal de l’équipement accepte ses commandes ; la configuration ci-dessous est celle du projet.</div><span class="cl-prompt">${h(shown)}</span> ${h(command)}
${h(cliText())}
<span class="cl-prompt">${h(shown)}</span> </div>`;
      root.querySelector('.open').onclick = openTerminal;
    },
  };

  // ---- the toolkit, for the products drawn by native_products_more.js ----
  window.nlProductsKit = {SKINS, MATCH: [], get view() { return view; }, D, N, h, maskOf, prefixOf, ipOf, lenOf, networkOf, validIp, fw, portByName, portName, peerName,
    running, svc, parseService, toast, send, cli, section, setAddress, rename, attempt, openTerminal, stage, pending, candidateFw, editFw, addressOf, staticRoutes, commit,
    discard, dialog, val, field, input, select, table, tr, NA, naBox, ruleFrom, ruleName, checkNet, dhcpServer, skinCss, natBuild, natPieces, natRead, putEntry, dropEntry,
    moveEntry, wanPort, zoneNames, cleanRule, route, openStandard: target => { standard = true; page = target; render(); }};

  // ---- drawing ----
  let typed = false;  // a field changed since the last drawing: the page does not refresh itself over it
  function draw(id) {
    typed = false;
    if (view.node !== N().name || view.skin !== id) view = {node: N().name, skin: id, ...JSON.parse(JSON.stringify(SKINS[id].start)), edit: null};
    app.className = 'px-app ' + id;
    SKINS[id].draw(app);
    pill.querySelector('[data-a="std"]').textContent = '☰ Vue Network LABS';
  }
  const previous = render;
  render = function () {
    previous();
    const vendor = !window.nlDesignNow || window.nlDesignNow() === 'vendor';
    const id = vendor && state && state.device ? window.nlProduct(state.device) : null;
    if (!id || standard) {
      app.remove();
      pill.remove();
      document.body.classList.remove('px');
      if (id && standard && !document.querySelector('.px-back')) {
        const back = document.createElement('button');
        back.className = 'px-back';
        back.textContent = '← Revenir à l’interface du produit';
        back.style.cssText = 'position:fixed;right:18px;bottom:18px;z-index:30;padding:10px 14px;border-radius:10px;border:0;background:#0f62c9;color:#fff;cursor:pointer';
        back.onclick = () => { standard = false; back.remove(); render(); };
        document.body.append(back);
      }
      if (!id) document.querySelector('.px-back')?.remove();
      return;
    }
    document.querySelector('.px-back')?.remove();
    document.body.classList.add('px');
    if (!app.isConnected) document.body.append(app);
    if (!pill.isConnected) document.body.append(pill);
    draw(id);
  };
  app.addEventListener('input', () => { typed = true; });
  // Changes staged for Apply / Commit are not in the project yet: the browser asks before leaving, as the products do.
  window.addEventListener('beforeunload', event => {
    if (!document.body.classList.contains('px') || !pending()) return;
    event.preventDefault();
    event.returnValue = '';
  });
  // The project changes elsewhere (the application, another page, the lab starting or stopping): the page follows by
  // itself, but never while something is being done here (a window open, a field typed in, changes staged, a save running).
  const busy = () => typed || sending || pending() || document.querySelector('.px-shade, .ix-slide, .jw-slide, .uf-panel, .ix-fly, .pf-nav .m.open, .jw-commit.open, .px-pill.open') ||
    (app.contains(document.activeElement) && ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName));
  setInterval(async () => {
    if (document.hidden || !document.body.classList.contains('px') || !state || busy()) return;
    let fresh;
    try { fresh = await request('/api/state?node=' + encodeURIComponent(node)); } catch (error) { return; }
    const same = fresh.revision === state.revision && fresh.observed === state.observed && JSON.stringify(fresh.live) === JSON.stringify(state.live);
    if (same || busy() || fresh.node.name !== state.node.name) return;
    state = fresh;
    render();
  }, 4000);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') { document.querySelector('.px-shade')?.remove(); document.querySelector('.ix-slide,.jw-slide')?.remove(); document.querySelector('.ix-fly')?.remove(); }
  });
  document.addEventListener('click', event => {
    if (!event.target.closest('.ix-fly,[data-m]')) document.querySelector('.ix-fly')?.remove();
    if (!event.target.closest('.pf-nav .m')) document.querySelectorAll('.pf-nav .m.open').forEach(x => x.classList.remove('open'));
    if (!event.target.closest('.px-pill')) pill.classList.remove('open');
  });
})();
