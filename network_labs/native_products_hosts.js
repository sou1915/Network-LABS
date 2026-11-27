/* The devices that are neither routers, switches nor firewalls, in their products' own web interfaces (engine:
 * native_products.js): Synology DSM and QNAP QTS (NAS), HP LaserJet Embedded Web Server and Brother Web Based
 * Management (printers), AXIS OS (camera), Yealink (IP phone), and the server management controllers Dell iDRAC,
 * HPE iLO and Lenovo XClarity Controller. Their network settings go to the project like the PC desktop's
 * « Configuration IP » (/api/host_ip); a controller opens the server's console (Virtual Console / Remote Console).
 * Drawn by Network LABS, no vendor logo or picture. PCs keep their desktop (native_desktop.js). */
'use strict';
(() => {
  const K = window.nlProductsKit;
  if (!K) return;
  const {SKINS, D, N, h, maskOf, prefixOf, ipOf, lenOf, validIp, running, toast, send, rename, attempt, openTerminal, dialog, val, field, input, select, table, tr, NA,
    naBox, skinCss} = K;
  const V = () => K.view;
  // A list of settings the way these pages show them: a name, then its value, no header row.
  const kv = (cls, rows) => `<table class="${cls}"><tbody>${rows.map(([k, v]) => `<tr><th>${h(k)}</th><td>${h(v)}</td></tr>`).join('')}</tbody></table>`;
  const go = (page, extra = {}) => { Object.assign(V(), {page}, extra); render(); };
  const own = (models, id) => K.MATCH.push([(d, role) => role === 'host' && models.some(m => d.model.startsWith(m)), id]);
  own(['DiskStation'], 'dsm');
  own(['TS-'], 'qts');
  own(['LaserJet'], 'hpews');
  own(['HL-'], 'brother');
  own(['P3265'], 'axis');
  own(['SIP-T'], 'yealink');
  own(['PowerEdge'], 'idrac');
  own(['ProLiant'], 'ilo');
  own(['ThinkSystem'], 'xcc');

  // ---- the device's one network port, as its product shows it ----
  const port0 = () => Object.keys(N().interfaces)[0];
  const isDhcp = () => (N().dhcp_clients || []).includes(port0());
  const address = () => N().interfaces[port0()] || '';
  const gateway = () => N().gateway || '';
  const linked = () => Boolean(D().ports[0] && D().ports[0].peer && !D().ports[0].down);
  const peer = () => (D().ports[0] && D().ports[0].peer) || '—';
  async function saveIp(mode, ip, mask, gw) {
    let cidr = '';
    if (mode === 'static') {
      const prefix = String(mask).includes('.') ? prefixOf(mask) : Number(mask);
      if (!validIp(ip) || prefix === null || !(prefix >= 1 && prefix <= 32)) throw new Error('Adresse IP et masque : a.b.c.d et 255.255.255.0.');
      if (gw && !validIp(gw)) throw new Error('Passerelle : a.b.c.d');
      cidr = `${ip}/${prefix}`;
    }
    await send('/api/host_ip', {port: port0(), mode, address: cidr, gateway: mode === 'static' ? gw : ''});
    render();
    const live = typeof state.ip_live === 'string' ? ` · appareil en marche : ${state.ip_live}` : '';
    toast((mode === 'dhcp' ? 'DHCP' : cidr) + ' enregistré' + live + '.');
  }
  const ipLine = () => (isDhcp() ? 'DHCP' : address() || '—');
  const fields = (prefix, dhcpLabel, manualLabel) => `${field('', `<span><label><input type="radio" name="${prefix}m" value="dhcp" ${isDhcp() ? 'checked' : ''}> ${h(dhcpLabel)}</label><br>
    <label><input type="radio" name="${prefix}m" value="static" ${isDhcp() ? '' : 'checked'}> ${h(manualLabel)}</label></span>`)}
    ${field('IP address', input(prefix + 'Ip', ipOf(address())))}${field('Subnet mask', input(prefix + 'Mask', address() ? maskOf(lenOf(address())) : '255.255.255.0'))}
    ${field('Gateway', input(prefix + 'Gw', gateway()))}`;
  // Choosing DHCP greys out the address fields, as on the products.
  function modeSync(root, prefix) {
    const boxes = ['Ip', 'Mask', 'Gw'].map(k => root.querySelector(`#${prefix}${k}`)).filter(Boolean);
    const choice = () => (root.querySelector(`input[name="${prefix}m"]:checked`) || root.querySelector(`#${prefix}Mode`) || {}).value;
    const sync = () => boxes.forEach(box => { box.disabled = choice() !== 'static'; });
    root.querySelectorAll(`input[name="${prefix}m"], #${prefix}Mode`).forEach(choiceBox => choiceBox.addEventListener('change', sync));
    sync();
    return root;
  }
  const readIp = (root, prefix) => saveIp(root.querySelector(`input[name="${prefix}m"]:checked`).value, val(root, `#${prefix}Ip`), val(root, `#${prefix}Mask`), val(root, `#${prefix}Gw`));

  /* =============================== Synology DSM =============================== */
  skinCss(`
  .px-app.dsm{position:fixed;inset:0;font:13px 'Roboto','Segoe UI',Arial,sans-serif;color:#333;background:linear-gradient(160deg,#2f6ea5,#5aa2cf 45%,#9cc8e3)}
  .ds-bar{height:38px;display:flex;align-items:center;gap:6px;padding:0 8px;background:rgba(255,255,255,.88);box-shadow:0 1px 4px rgba(0,0,0,.15)}
  .ds-bar button{border:0;background:none;padding:6px 10px;border-radius:4px;cursor:pointer;font-size:15px}.ds-bar button.on{background:rgba(0,0,0,.08)}.ds-bar .grow{flex:1}
  .ds-desk{position:absolute;top:56px;left:24px;display:grid;gap:18px}.ds-ico{width:96px;text-align:center;color:#fff;cursor:pointer;text-shadow:0 1px 3px rgba(0,0,0,.5)}
  .ds-ico i{display:grid;place-items:center;width:58px;height:58px;margin:0 auto 6px;border-radius:12px;background:#fff;font-style:normal;font-size:28px;box-shadow:0 4px 10px rgba(0,0,0,.25)}
  .ds-widgets{position:absolute;top:56px;right:20px;width:300px;display:grid;gap:12px}.ds-w{background:rgba(255,255,255,.92);border-radius:8px;padding:12px 14px}
  .ds-w h4{margin:0 0 8px;font-size:13px}.ds-ok,.ds-off{color:#2e9d4b;font-weight:bold;font-size:16px}.ds-off{color:#8a949e}
  .ds-win{position:absolute;top:62px;left:150px;right:340px;bottom:30px;background:#fff;border-radius:8px;box-shadow:0 12px 40px rgba(0,0,0,.35);display:flex;flex-direction:column;overflow:hidden}
  .ds-wt{display:flex;align-items:center;padding:8px 14px;background:#f4f6f8;border-bottom:1px solid #e0e4e8;font-weight:bold}.ds-wt .x{margin-left:auto;cursor:pointer;border:0;background:none;font-size:15px}
  .ds-wb{display:grid;grid-template-columns:200px 1fr;flex:1;min-height:0}.ds-nav{background:#f7f8fa;border-right:1px solid #e6e9ec;overflow:auto;padding:6px 0}
  .ds-nav b{display:block;padding:10px 14px 4px;color:#8a949e;font-size:11px}.ds-nav a{display:block;padding:7px 14px 7px 22px;cursor:pointer}.ds-nav a.on{background:#dceaf7;color:#0d67b8;font-weight:bold}
  .ds-nav a.na{color:#a5adb5}.ds-main{padding:14px 18px;overflow:auto}.ds-tabs{display:flex;gap:16px;border-bottom:1px solid #e6e9ec;margin-bottom:12px}.ds-tabs a{padding:7px 0;cursor:pointer;color:#666}
  .ds-tabs a.on{color:#0d67b8;border-bottom:2px solid #0d67b8}.ds-tabs a.na{color:#b0b6bc}
  .ds-kv{border-collapse:collapse}.ds-kv th{text-align:left;font-weight:normal;color:#777;padding:7px 28px 7px 0}.ds-kv td{padding:7px 0}
  .ds-t{width:100%;border-collapse:collapse}.ds-t th{text-align:left;padding:7px;border-bottom:1px solid #e6e9ec;color:#777;font-weight:normal}.ds-t td{padding:8px 7px;border-bottom:1px solid #f0f2f4}
  .ds-btn{border:1px solid #c9d1d9;background:#fff;padding:5px 14px;border-radius:3px;cursor:pointer;margin-right:6px}.ds-btn.pri{background:#0d67b8;color:#fff;border-color:#0d67b8}
  .px-shade.dsm .px-dtitle{background:#f4f6f8}.px-shade.dsm .px-dialog{border-radius:8px}.px-shade.dsm .px-dfoot button{border:1px solid #c9d1d9;background:#fff;padding:5px 16px;border-radius:3px;cursor:pointer}
  .px-shade.dsm .px-dfoot button.pri{background:#0d67b8;color:#fff;border-color:#0d67b8}
  `);
  const DS_NAV = [['File Sharing', [['Shared Folder', 'na'], ['File Services', 'na'], ['User & Group', 'na']]], ['Connectivity', [['External Access', 'na'], ['Network', 'network'], ['Security', 'na']]],
    ['System', [['Info Center', 'info'], ['Login Portal', 'na'], ['Regional Options', 'na'], ['Hardware & Power', 'na'], ['Update & Restore', 'na']]]];
  SKINS.dsm = {
    start: {win: null, page: 'network', tab: 'Network Interface'},
    draw(root) {
      const v = V();
      root.innerHTML = `<div class="ds-bar"><button title="Main Menu">▦</button>${v.win ? `<button class="on">${v.win === 'control' ? '⚙' : '📦'}</button>` : ''}<span class="grow"></span>
        <span>${h(N().name)} · DSM · sous-ensemble Network LABS</span><button title="Options">👤</button></div>
        <div class="ds-desk">${[['📦', 'Package Center', 'na'], ['⚙', 'Control Panel', 'control'], ['🗂', 'File Station', 'na'], ['?', 'DSM Help', 'na']].map(([icon, label, win]) =>
          `<div class="ds-ico" data-w="${win}"><i>${icon}</i>${label}</div>`).join('')}</div>
        <div class="ds-widgets"><div class="ds-w"><h4>System Health</h4><div class="${running() ? 'ds-ok' : 'ds-off'}">${running() ? 'Healthy' : 'Stopped'}</div><div>Server name: ${h(N().name)}<br>LAN 1: ${h(ipLine())}<br>Uptime: ${
          running() ? 'en marche' : '—'}</div></div><div class="ds-w"><h4>Resource Monitor</h4>CPU ${running() ? '3%' : '—'} · RAM ${running() ? '22%' : '—'}<br>LAN ↑ 0 KB/s ↓ 0 KB/s</div></div>`;
      root.querySelectorAll('[data-w]').forEach(i => { i.ondblclick = i.onclick = () => { if (i.dataset.w === 'na') return toast('Package Center, File Station : ' + NA.later, true); go(v.page, {win: i.dataset.w}); }; });
      if (v.win !== 'control') return;
      const win = document.createElement('div');
      win.className = 'ds-win';
      win.innerHTML = `<div class="ds-wt">Control Panel<button class="x">✕</button></div><div class="ds-wb"><nav class="ds-nav">${DS_NAV.map(([g, items]) => `<b>${g}</b>${items.map(([label, page]) =>
        `<a data-go="${page}" class="${page === 'na' ? 'na' : ''}${page === v.page ? ' on' : ''}">${label}</a>`).join('')}`).join('')}</nav><main class="ds-main"></main></div>`;
      root.append(win);
      win.querySelector('.x').onclick = () => go(v.page, {win: null});
      win.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { if (a.dataset.go !== 'na') go(a.dataset.go); }; });
      (v.page === 'info' ? dsInfo : dsNetwork)(win.querySelector('main'));
    },
  };
  function dsNetwork(main) {
    const v = V(), tab = v.tab;
    main.innerHTML = `<div class="ds-tabs">${['General', 'Network Interface', 'Traffic Control', 'Static Route', 'Connectivity'].map(t => `<a data-t="${t}" class="${t === tab ? 'on'
      : ['General', 'Network Interface'].includes(t) ? '' : 'na'}">${t}</a>`).join('')}</div>`;
    main.querySelectorAll('[data-t]').forEach(a => { a.onclick = () => { if (!a.classList.contains('na')) go('network', {tab: a.dataset.t}); }; });
    if (tab === 'General') {
      main.insertAdjacentHTML('beforeend', `${field('Server name', input('dsName', N().name))}${field('Default gateway', `<span>${h(gateway() || '—')} (LAN 1)</span>`)}
        ${field('Preferred DNS server', input('dns', '', 'disabled'))}<p><button class="ds-btn pri apply">Apply</button><button class="ds-btn">Reset</button></p>`);
      main.querySelector('.apply').onclick = () => attempt(() => rename(val(main, '#dsName')), 'Settings applied.');
      return;
    }
    main.insertAdjacentHTML('beforeend', `<p><button class="ds-btn" disabled>Create ▾</button><button class="ds-btn edit">Edit</button><button class="ds-btn" disabled>Delete</button></p>
      ${table('ds-t', ['Name', 'Status', 'IP address', 'Peer'], [tr([`<b>LAN 1</b>`, linked() ? '🟢 Connected' : '⚪ Disconnected', h(ipLine()), h(peer())])])}`);
    main.querySelector('.edit').onclick = () => modeSync(dialog('dsm', 'LAN 1', `<div class="ds-tabs"><a class="on">IPv4</a><a class="na">IPv6</a><a class="na">802.1X</a></div>
      ${fields('ds', 'Get network configuration automatically (DHCP)', 'Use manual configuration')}${field('', '<span>☑ Set as default gateway</span>')}`,
    [['OK', 'pri', b => readIp(b, 'ds')], ['Cancel']]), 'ds');
  }
  function dsInfo(main) {
    const d = D();
    main.innerHTML = `<div class="ds-tabs"><a class="on">General</a><a class="na">Network</a><a class="na">Storage</a><a class="na">Service</a></div>${kv('ds-kv', [['Server name', N().name],
      ['Model name', d.model], ['Serial number', '—'], ['DSM version', 'sous-ensemble Network LABS'], ['Physical memory', `${N().memory_mib || 128} MB`], ['System time', new Date().toLocaleString('fr-FR')],
      ['Operating time', running() ? 'en marche' : '—'], ['LAN 1', ipLine()], ['Default gateway', gateway() || '—']])}`;
  }

  /* =============================== QNAP QTS =============================== */
  skinCss(`
  .px-app.qts{position:fixed;inset:0;font:13px 'Segoe UI',Arial,sans-serif;color:#2b2b2b;background:linear-gradient(135deg,#1c2b3a,#2e4d6b 50%,#3f6b8f)}
  .qt-bar{height:42px;display:flex;align-items:center;gap:10px;padding:0 12px;background:rgba(0,0,0,.55);color:#fff}.qt-bar .grow{flex:1}.qt-bar button{border:0;background:none;color:#fff;font-size:16px;cursor:pointer}
  .qt-desk{position:absolute;top:70px;left:40px;display:flex;flex-wrap:wrap;gap:22px;width:520px}.qt-ico{width:100px;text-align:center;color:#fff;cursor:pointer}
  .qt-ico i{display:grid;place-items:center;width:64px;height:64px;margin:0 auto 6px;border-radius:16px;background:linear-gradient(#3a8ee6,#1f66c1);font-style:normal;font-size:28px}
  .qt-win{position:absolute;top:60px;left:90px;right:90px;bottom:40px;background:#fff;border-radius:4px;box-shadow:0 14px 40px rgba(0,0,0,.4);display:flex;flex-direction:column}
  .qt-wt{display:flex;align-items:center;padding:9px 14px;background:#2d3e50;color:#fff}.qt-wt .x{margin-left:auto;cursor:pointer;border:0;background:none;color:#fff;font-size:15px}
  .qt-wb{display:grid;grid-template-columns:210px 1fr;flex:1;min-height:0}.qt-nav{background:#f1f3f5;border-right:1px solid #dde1e5;padding:8px 0}
  .qt-nav a{display:block;padding:8px 16px;cursor:pointer}.qt-nav a.on{background:#fff;color:#1f66c1;font-weight:bold;border-left:3px solid #1f66c1}.qt-nav a.na{color:#a8b0b8}
  .qt-main{padding:16px 20px;overflow:auto}.qt-tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.qt-tile{border:1px solid #dde1e5;border-radius:4px;padding:16px;text-align:center;cursor:pointer}
  .qt-tile:hover{border-color:#1f66c1}.qt-t{width:100%;border-collapse:collapse}.qt-t th{background:#f1f3f5;text-align:left;padding:8px}.qt-t td{padding:8px;border-bottom:1px solid #eef0f2}
  .qt-btn{border:0;background:#1f66c1;color:#fff;padding:6px 14px;border-radius:3px;cursor:pointer}
  .px-shade.qts .px-dtitle{background:#2d3e50;color:#fff}.px-shade.qts .px-dfoot button{border:0;background:#8a96a3;color:#fff;padding:6px 16px;border-radius:3px;cursor:pointer}
  .px-shade.qts .px-dfoot button.pri{background:#1f66c1}
  `);
  SKINS.qts = {
    start: {win: null, page: 'interfaces'},
    draw(root) {
      const v = V();
      root.innerHTML = `<div class="qt-bar"><button>☰</button><span>QTS · ${h(N().name)} · sous-ensemble Network LABS</span><span class="grow"></span><button>🔍</button><button>👤</button></div>
        <div class="qt-desk">${[['⚙', 'Control Panel', 'control'], ['🗂', 'File Station', 'na'], ['🛍', 'App Center', 'na'], ['💽', 'Storage & Snapshots', 'na'], ['🖧', 'Network & Virtual Switch', 'network']].map(([icon, label, win]) =>
          `<div class="qt-ico" data-w="${win}"><i>${icon}</i>${label}</div>`).join('')}</div>`;
      root.querySelectorAll('[data-w]').forEach(i => { i.onclick = () => { if (i.dataset.w === 'na') return toast(NA.later, true); go(i.dataset.w === 'network' ? 'interfaces' : 'tiles', {win: i.dataset.w}); }; });
      if (!v.win) return;
      const win = document.createElement('div');
      win.className = 'qt-win';
      const network = v.win === 'network';
      win.innerHTML = `<div class="qt-wt">${network ? 'Network & Virtual Switch' : 'Control Panel'}<button class="x">✕</button></div><div class="qt-wb"><nav class="qt-nav">${(network
        ? [['Overview', 'overview'], ['Interfaces', 'interfaces'], ['Virtual Switch', 'na'], ['DHCP Server', 'na'], ['DNS', 'na'], ['Routing', 'na']]
        : [['System', 'tiles'], ['General Settings', 'general'], ['Privilege', 'na'], ['Network & File Services', 'tiles'], ['Applications', 'na']]).map(([label, page]) =>
        `<a data-go="${page}" class="${page === 'na' ? 'na' : ''}${page === v.page ? ' on' : ''}">${label}</a>`).join('')}</nav><main class="qt-main"></main></div>`;
      root.append(win);
      win.querySelector('.x').onclick = () => go(v.page, {win: null});
      win.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { if (a.dataset.go !== 'na') go(a.dataset.go); }; });
      const main = win.querySelector('main');
      ({tiles: qtTiles, general: qtGeneral, interfaces: qtInterfaces, overview: qtOverview}[v.page] || qtTiles)(main);
    },
  };
  function qtTiles(main) {
    main.innerHTML = `<div class="qt-tiles">${[['🖥', 'General Settings', 'general'], ['🔒', 'Security', 'na'], ['🔧', 'Hardware', 'na'], ['🔌', 'Power', 'na'], ['🖧', 'Network & Virtual Switch', 'net'],
      ['📣', 'Notification Center', 'na'], ['🛠', 'Firmware Update', 'na'], ['💾', 'Backup / Restore', 'na']].map(([icon, label, page]) => `<div class="qt-tile" data-go="${page}"><div style="font-size:28px">${icon}</div>${label}</div>`).join('')}</div>`;
    main.querySelectorAll('[data-go]').forEach(t => { t.onclick = () => { if (t.dataset.go === 'net') go('interfaces', {win: 'network'}); else if (t.dataset.go !== 'na') go(t.dataset.go); }; });
  }
  function qtGeneral(main) {
    main.innerHTML = `<h3 style="margin-top:0">General Settings · System Administration</h3>${field('Server name', input('qtName', N().name))}${field('System port', input('p', '8080', 'disabled'))}
      <button class="qt-btn apply">Apply</button>`;
    main.querySelector('.apply').onclick = () => attempt(() => rename(val(main, '#qtName')), 'Settings applied.');
  }
  function qtOverview(main) {
    main.innerHTML = `<h3 style="margin-top:0">Overview</h3>${table('qt-t', ['Interface', 'Status', 'IP Address', 'Connected to'], [tr(['Adapter 1', linked() ? '🟢 Connected' : '⚪ Disconnected', h(ipLine()), h(peer())])])}`;
  }
  function qtInterfaces(main) {
    main.innerHTML = `<h3 style="margin-top:0">Interfaces</h3>${table('qt-t', ['Name', 'Status', 'IP Address', 'Default Gateway', ''], [tr(['Adapter 1', linked() ? '🟢 Connected' : '⚪ Disconnected', h(ipLine()),
      h(gateway() || '—'), '<button class="qt-btn conf">⋯ Configure</button>'])])}`;
    main.querySelector('.conf').onclick = () => modeSync(dialog('qts', 'Configure · Adapter 1', `<p><b>IPv4</b> · IPv6 · DNS</p>${fields('qt', 'Obtain IP address settings automatically via DHCP', 'Use static IP address')}`,
      [['Apply', 'pri', b => readIp(b, 'qt')], ['Cancel']]), 'qt');
  }

  /* =============================== HP LaserJet Embedded Web Server =============================== */
  skinCss(`
  .px-app.hpews{min-height:100vh;background:#f5f6f7;color:#222;font:13px 'Segoe UI',Arial,sans-serif;display:grid;grid-template-columns:230px 1fr;grid-template-rows:60px 1fr}
  .hp-top{grid-column:1/-1;display:flex;align-items:center;gap:14px;padding:0 20px;background:#1d5f8f;color:#fff}.hp-top b{font-size:17px}.hp-top .grow{flex:1}
  .hp-nav{background:#fff;border-right:1px solid #e1e4e8;padding:10px 0}.hp-nav a{display:flex;gap:10px;padding:10px 18px;cursor:pointer}.hp-nav a.on{background:#e7f1f9;color:#1d5f8f;font-weight:bold;border-left:4px solid #1d5f8f}
  .hp-nav a.na{color:#a3aab1}.hp-main{padding:18px 24px}.hp-card{background:#fff;border:1px solid #e1e4e8;border-radius:4px;padding:16px 18px;margin-bottom:14px;max-width:760px}
  .hp-card h3{margin:0 0 10px;font-size:15px}.hp-ready{color:#2e8540;font-size:18px;font-weight:bold}.hp-ready.off{color:#8a939c}
  .hp-kv{border-collapse:collapse}.hp-kv th{text-align:left;font-weight:normal;color:#5c6670;padding:6px 28px 6px 0}.hp-kv td{padding:6px 0}.hp-toner{height:16px;background:#e4e7ea;border-radius:3px;overflow:hidden;width:260px}
  .hp-toner i{display:block;height:100%;width:70%;background:#222}.hp-tabs{display:flex;gap:18px;border-bottom:1px solid #e1e4e8;margin-bottom:12px}.hp-tabs a{padding:8px 0;color:#666}
  .hp-tabs a.on{color:#1d5f8f;border-bottom:3px solid #1d5f8f}.hp-btn{border:0;background:#1d5f8f;color:#fff;padding:7px 18px;border-radius:3px;cursor:pointer;margin-right:8px}.hp-btn.sec{background:#8a939c}
  `);
  SKINS.hpews = {
    start: {page: 'home'},
    draw(root) {
      const v = V();
      root.innerHTML = `<div class="hp-top"><b>${h(D().model)}</b><span>${h(N().name)}</span><span class="grow"></span><span>Embedded Web Server · sous-ensemble Network LABS</span><span>Sign In</span></div>
        <nav class="hp-nav">${[['⌂', 'Home', 'home'], ['🖨', 'Print', 'na'], ['🧴', 'Supplies', 'supplies'], ['🖧', 'Networking', 'network'], ['🔒', 'Security', 'na'], ['⚙', 'Settings', 'settings'],
          ['☁', 'HP Web Services', 'na']].map(([icon, label, page]) => `<a data-go="${page}" class="${page === 'na' ? 'na' : ''}${page === v.page ? ' on' : ''}"><span>${icon}</span>${label}</a>`).join('')}</nav>
        <main class="hp-main"></main>`;
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { if (a.dataset.go !== 'na') go(a.dataset.go); }; });
      const main = root.querySelector('main');
      ({home: hpHome, supplies: hpHome, network: hpNetwork, settings: hpSettings}[v.page] || hpHome)(main);
    },
  };
  function hpHome(main) {
    main.innerHTML = `<div class="hp-card"><h3>Printer Status</h3><div class="hp-ready${running() ? '' : ' off'}">${running() ? '✔ Ready' : '○ Off'}</div></div><div class="hp-card"><h3>Supplies</h3>Black Cartridge
      <div class="hp-toner"><i></i></div>~70%</div><div class="hp-card"><h3>Device Information</h3>${kv('hp-kv', [['Device Name', N().name], ['Product Name', D().model], ['IP Address', ipLine()],
      ['Network Connection', linked() ? 'Wired (802.3) · connected' : 'Not connected'], ['Firmware', 'sous-ensemble Network LABS']])}</div>`;
  }
  function hpNetwork(main) {
    main.innerHTML = `<div class="hp-tabs"><a class="on">Wired (802.3)</a><a>Wi-Fi Direct</a><a>Network Identification</a></div><div class="hp-card"><h3>IPv4 Configuration</h3>
      ${field('IP Preferred Address Method', select('hpMode', [['dhcp', 'Automatic (DHCP)'], ['static', 'Manual']], isDhcp() ? 'dhcp' : 'static'))}${field('Manual IP Address', input('hpIp', ipOf(address())))}
      ${field('Manual Subnet Mask', input('hpMask', address() ? maskOf(lenOf(address())) : '255.255.255.0'))}${field('Manual Default Gateway', input('hpGw', gateway()))}
      <div class="px-err"></div><p><button class="hp-btn apply">Apply</button><button class="hp-btn sec">Cancel</button></p></div>`;
    modeSync(main, 'hp');
    main.querySelector('.apply').onclick = async () => {
      try { await saveIp(val(main, '#hpMode'), val(main, '#hpIp'), val(main, '#hpMask'), val(main, '#hpGw')); } catch (error) { main.querySelector('.px-err').textContent = error.message; }
    };
  }
  function hpSettings(main) {
    main.innerHTML = `<div class="hp-card"><h3>Device Information</h3>${field('Device Name', input('hpName', N().name))}${field('Device Location', input('l', '', 'disabled'))}
      <p><button class="hp-btn apply">Apply</button></p></div>`;
    main.querySelector('.apply').onclick = () => attempt(() => rename(val(main, '#hpName')), 'Settings applied.');
  }

  /* =============================== Brother Web Based Management =============================== */
  skinCss(`
  .px-app.brother{min-height:100vh;background:#fff;color:#222;font:13px Arial,Helvetica,sans-serif}
  .br-top{display:flex;align-items:center;justify-content:space-between;padding:12px 22px;border-bottom:3px solid #0e3c7a}.br-top b{font-size:18px;color:#0e3c7a}
  .br-tabs{display:flex;gap:2px;padding:0 22px;background:#eef2f7;border-bottom:1px solid #c9d3df}.br-tabs a{padding:10px 18px;cursor:pointer;color:#0e3c7a}.br-tabs a.on{background:#fff;font-weight:bold;border:1px solid #c9d3df;border-bottom:0}
  .br-body{display:grid;grid-template-columns:220px 1fr}.br-side{padding:14px 0;border-right:1px solid #e1e6ec}.br-side b{display:block;padding:8px 18px;color:#0e3c7a}
  .br-side a{display:block;padding:5px 18px 5px 28px;cursor:pointer}.br-side a.on{font-weight:bold;background:#e8eef6}.br-side a.na{color:#a3abb4}.br-main{padding:16px 22px;max-width:720px}
  .br-main h3{color:#0e3c7a;border-bottom:1px solid #c9d3df;padding-bottom:6px}
  .br-kv{border-collapse:collapse}.br-kv th{text-align:left;font-weight:normal;background:#eef2f7;padding:6px 24px 6px 10px;border:1px solid #d6dde6}.br-kv td{padding:6px 12px;border:1px solid #d6dde6}.br-btn{border:1px solid #8a96a3;background:linear-gradient(#fff,#e2e6ea);padding:4px 18px;cursor:pointer;margin-right:6px}
  .br-toner{display:inline-block;width:30px;height:90px;border:1px solid #888;position:relative;vertical-align:bottom}.br-toner i{position:absolute;left:0;right:0;bottom:0;height:70%;background:#222}
  `);
  SKINS.brother = {
    start: {tab: 'Home', page: 'status'},
    draw(root) {
      const v = V();
      const side = v.tab === 'Network' ? [['Network', [['Network Status', 'netstatus'], ['Interface', 'na']]], ['Wired', [['TCP/IP (Wired)', 'tcpip'], ['Ethernet', 'na']]], ['Protocol', [['Protocol', 'na']]]]
        : v.tab === 'Administrator' ? [['Administrator', [['Login Password', 'na'], ['Machine Information', 'machine']]]] : [['Home', [['Status', 'status'], ['Other Information', 'na']]]];
      root.innerHTML = `<div class="br-top"><b>${h(D().model)} series</b><span>${h(N().name)} · Web Based Management · sous-ensemble Network LABS</span></div>
        <div class="br-tabs">${['Home', 'Print', 'Administrator', 'Network'].map(t => `<a data-t="${t}" class="${t === v.tab ? 'on' : ''}">${t}</a>`).join('')}</div>
        <div class="br-body"><nav class="br-side">${side.map(([g, items]) => `<b>${g}</b>${items.map(([label, page]) => `<a data-go="${page}" class="${page === 'na' ? 'na' : ''}${page === v.page ? ' on' : ''}">${label}</a>`).join('')}`).join('')}</nav>
        <main class="br-main"></main></div>`;
      root.querySelectorAll('[data-t]').forEach(a => { a.onclick = () => { const first = {Home: 'status', Print: 'na', Administrator: 'machine', Network: 'tcpip'}[a.dataset.t]; go(first, {tab: a.dataset.t}); }; });
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { if (a.dataset.go !== 'na') go(a.dataset.go); }; });
      const main = root.querySelector('main');
      ({status: brStatus, tcpip: brTcpip, netstatus: brNetStatus, machine: brMachine}[v.page] || (m => { m.innerHTML = naBox(v.tab, NA.later); }))(main);
    },
  };
  function brStatus(main) {
    main.innerHTML = `<h3>Status</h3>${field('Device Status', `<b>${running() ? 'Ready' : 'Sleep'}</b>`)}${field('Automatic Refresh', '<span>(•) Off ( ) On</span>')}
      ${field('Toner Level', '<span><span class="br-toner"><i></i></span> BK</span>')}${field('Web Language', select('l', ['Auto'], 'Auto'))}`;
  }
  function brTcpip(main) {
    main.innerHTML = `<h3>TCP/IP (Wired)</h3>${field('Boot Method', select('brMode', [['static', 'Static'], ['dhcp', 'DHCP'], ['auto', 'Auto']], isDhcp() ? 'dhcp' : 'static'))}
      ${field('IP Address', input('brIp', ipOf(address())))}${field('Subnet Mask', input('brMask', address() ? maskOf(lenOf(address())) : '255.255.255.0'))}${field('Gateway', input('brGw', gateway()))}
      <div class="px-err"></div><p><button class="br-btn cancel">Cancel</button><button class="br-btn submit">Submit</button></p>`;
    modeSync(main, 'br');
    main.querySelector('.cancel').onclick = () => render();
    main.querySelector('.submit').onclick = async () => {
      try { await saveIp(val(main, '#brMode') === 'static' ? 'static' : 'dhcp', val(main, '#brIp'), val(main, '#brMask'), val(main, '#brGw')); } catch (error) { main.querySelector('.px-err').textContent = error.message; }
    };
  }
  function brNetStatus(main) {
    main.innerHTML = `<h3>Network Status</h3>${kv('br-kv', [['Wired Status', linked() ? '100BASE-TX Full Duplex' : 'Inactive'], ['IP Address', ipLine()], ['Subnet Mask', address() ? maskOf(lenOf(address())) : '—'],
      ['Gateway', gateway() || '—'], ['Node Name', N().name]])}`;
  }
  function brMachine(main) {
    main.innerHTML = `<h3>Machine Information</h3>${field('Node Name', input('brName', N().name))}${field('Location', input('l', '', 'disabled'))}<p><button class="br-btn submit">Submit</button></p>`;
    main.querySelector('.submit').onclick = () => attempt(() => rename(val(main, '#brName')), 'Submitted.');
  }

  /* =============================== AXIS OS (network camera) =============================== */
  skinCss(`
  .px-app.axis{min-height:100vh;background:#121212;color:#e6e6e6;font:13px 'Segoe UI',Arial,sans-serif;display:grid;grid-template-columns:220px 1fr;grid-template-rows:52px 1fr}
  .ax-top{grid-column:1/-1;display:flex;align-items:center;gap:14px;padding:0 18px;background:#1e1e1e;border-bottom:1px solid #2c2c2c}.ax-top b{font-size:15px}.ax-top .grow{flex:1}.ax-top span{color:#9a9a9a}
  .ax-nav{background:#1a1a1a;padding:8px 0}.ax-nav a{display:block;padding:10px 20px;cursor:pointer;color:#cfcfcf}.ax-nav a.on{background:#2b2b2b;color:#fff;border-left:3px solid #ffcc33;padding-left:17px}
  .ax-nav a.sub{padding-left:36px;font-size:12px}.ax-nav a.na{color:#666}.ax-main{padding:16px 20px;overflow:auto}
  .ax-live{height:340px;border-radius:4px;background:radial-gradient(circle at 30% 60%,#3c4a3a,#1c241c 60%),linear-gradient(#262e26,#141914);position:relative;margin-bottom:14px}
  .ax-live span{position:absolute;top:10px;left:12px;font:12px Consolas,monospace;color:#fff;background:rgba(0,0,0,.4);padding:2px 6px}
  .ax-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.ax-card{background:#1e1e1e;border:1px solid #2c2c2c;border-radius:4px;padding:12px 14px}.ax-card h4{margin:0 0 8px;color:#ffcc33}
  .ax-form{max-width:620px;background:#1e1e1e;border:1px solid #2c2c2c;border-radius:4px;padding:14px 18px}.ax-form input,.ax-form select{background:#2b2b2b;color:#eee;border:1px solid #444}
  .ax-btn{border:0;background:#ffcc33;color:#111;padding:7px 18px;border-radius:3px;cursor:pointer;font-weight:bold}
  `);
  SKINS.axis = {
    start: {page: 'status'},
    draw(root) {
      const v = V();
      root.innerHTML = `<div class="ax-top"><b>AXIS ${h(D().model)}</b><span>${h(N().name)}</span><span class="grow"></span><span>AXIS OS · sous-ensemble Network LABS</span><span>root</span></div>
        <nav class="ax-nav">${[['Status', 'status'], ['Video', 'video'], ['Audio', 'na'], ['Analytics', 'na'], ['Recordings', 'na'], ['Apps', 'na'], ['System', null], ['Date and time', 'na', 1],
          ['Network', 'network', 1], ['Security', 'na', 1], ['Accounts', 'na', 1], ['Events', 'na', 1], ['Storage', 'na', 1], ['Maintenance', 'na', 1]].map(([label, page, sub]) => page === null
          ? `<a class="na">${label}</a>` : `<a data-go="${page}" class="${sub ? 'sub ' : ''}${page === 'na' ? 'na' : ''}${page === v.page ? ' on' : ''}">${label}</a>`).join('')}</nav><main class="ax-main"></main>`;
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { if (a.dataset.go !== 'na') go(a.dataset.go); }; });
      const main = root.querySelector('main');
      ({status: axStatus, video: axStatus, network: axNetwork}[v.page] || axStatus)(main);
    },
  };
  function axStatus(main) {
    main.innerHTML = `<div class="ax-live"><span>${h(N().name)} · ${new Date().toLocaleString('fr-FR')}</span>${running() ? '' : '<div style="position:absolute;inset:0;display:grid;place-items:center;color:#888">Lab arrêté : pas de flux vidéo</div>'}</div>
      <div class="ax-cards"><div class="ax-card"><h4>Device info</h4>Product: AXIS ${h(D().model)}<br>Firmware: sous-ensemble Network LABS<br>Serial number: —</div>
      <div class="ax-card"><h4>Network</h4>IPv4: ${h(ipLine())}<br>Hostname: ${h(N().name)}<br>Link: ${linked() ? 'connected' : 'disconnected'}</div><div class="ax-card"><h4>Time sync</h4>NTP: not configured</div></div>`;
  }
  function axNetwork(main) {
    main.innerHTML = `<div class="ax-form"><h3 style="margin-top:0">IPv4</h3>${field('Assign IPv4 automatically', select('axMode', [['dhcp', 'On (DHCP)'], ['static', 'Off (manual)']], isDhcp() ? 'dhcp' : 'static'))}
      ${field('IP address', input('axIp', ipOf(address())))}${field('Subnet mask', input('axMask', address() ? maskOf(lenOf(address())) : '255.255.255.0'))}${field('Router', input('axGw', gateway()))}
      <h3>Hostname</h3>${field('Hostname', input('axName', N().name))}<div class="px-err"></div><button class="ax-btn save">Save</button></div>`;
    modeSync(main, 'ax');
    main.querySelector('.save').onclick = async () => {
      try {
        await saveIp(val(main, '#axMode'), val(main, '#axIp'), val(main, '#axMask'), val(main, '#axGw'));
        if (val(main, '#axName') !== N().name) await attempt(() => rename(val(main, '#axName')));
      } catch (error) { main.querySelector('.px-err').textContent = error.message; }
    };
  }

  /* =============================== Yealink IP phone =============================== */
  skinCss(`
  .px-app.yealink{min-height:100vh;background:#fff;color:#333;font:12px Arial,Helvetica,sans-serif}
  .yl-head{display:flex;align-items:center;justify-content:space-between;padding:10px 22px}.yl-head b{font-size:20px;color:#2a6db0}
  .yl-tabs{display:flex;background:#2a6db0}.yl-tabs a{padding:10px 18px;color:#e8f0fa;cursor:pointer;font-weight:bold}.yl-tabs a.on{background:#fff;color:#2a6db0}
  .yl-body{display:grid;grid-template-columns:180px 1fr}.yl-side{background:#f2f5f9;padding:10px 0;min-height:70vh}.yl-side a{display:block;padding:8px 18px;cursor:pointer}.yl-side a.on{background:#fff;color:#2a6db0;font-weight:bold}
  .yl-side a.na{color:#a9b2bc}.yl-main{padding:16px 24px}.yl-t{border-collapse:collapse;min-width:560px}.yl-t td{padding:7px 10px;border:1px solid #e1e6ec}.yl-t td.l{background:#f2f5f9;width:220px}
  .yl-btn{border:1px solid #2a6db0;background:#2a6db0;color:#fff;padding:6px 22px;cursor:pointer;margin-right:8px}.yl-btn.sec{background:#fff;color:#2a6db0}
  `);
  SKINS.yealink = {
    start: {tab: 'Status', page: 'status'},
    draw(root) {
      const v = V();
      const sides = {Status: [['Status', 'status']], Account: [['Register', 'register'], ['Basic', 'na'], ['Codec', 'na']], Network: [['Basic', 'basic'], ['PC Port', 'na'], ['NAT', 'na'], ['Advanced', 'na']],
        DSSKey: [['Line Key', 'na']], Features: [['Forward&DND', 'na']], Settings: [['Preference', 'na'], ['Time&Date', 'na']], Directory: [['Local Directory', 'na']], Security: [['Password', 'na']]};
      root.innerHTML = `<div class="yl-head"><b>${h(D().model)}</b><span>${h(N().name)} · sous-ensemble Network LABS · Log Out</span></div><div class="yl-tabs">${Object.keys(sides).map(t =>
        `<a data-t="${t}" class="${t === v.tab ? 'on' : ''}">${t}</a>`).join('')}</div><div class="yl-body"><nav class="yl-side">${sides[v.tab].map(([label, page]) =>
          `<a data-go="${page}" class="${page === 'na' ? 'na' : ''}${page === v.page ? ' on' : ''}">${label}</a>`).join('')}</nav><main class="yl-main"></main></div>`;
      root.querySelectorAll('[data-t]').forEach(a => { a.onclick = () => go(sides[a.dataset.t][0][1], {tab: a.dataset.t}); });
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { if (a.dataset.go !== 'na') go(a.dataset.go); }; });
      const main = root.querySelector('main');
      ({status: ylStatus, basic: ylBasic, register: ylRegister}[v.page] || (m => { m.innerHTML = naBox(v.tab, NA.later); }))(main);
    },
  };
  const ylRows = rows => `<table class="yl-t"><tbody>${rows.map(([k, val2]) => `<tr><td class="l">${k}</td><td>${val2}</td></tr>`).join('')}</tbody></table>`;
  function ylStatus(main) {
    main.innerHTML = `<h3>Version</h3>${ylRows([['Firmware Version', 'sous-ensemble Network LABS'], ['Hardware Version', h(D().model)]])}<h3>Network</h3>${ylRows([['Internet Port', 'IPv4'],
      ['IPv4 WAN IP', h(ipLine())], ['MAC', '—'], ['Link', linked() ? 'Up' : 'Down']])}<h3>Account Status</h3>${ylRows([['Account 1', 'Disabled'], ['Account 2', 'Disabled']])}`;
  }
  function ylBasic(main) {
    main.innerHTML = `<h3>Internet Port</h3>${ylRows([['Mode (IPv4/IPv6)', 'IPv4'], ['IPv4 Config', `<label><input type="radio" name="ylm" value="dhcp" ${isDhcp() ? 'checked' : ''}> DHCP</label>
      <label><input type="radio" name="ylm" value="static" ${isDhcp() ? '' : 'checked'}> Static IP Address</label>`], ['IP Address', input('ylIp', ipOf(address()))],
      ['Subnet Mask', input('ylMask', address() ? maskOf(lenOf(address())) : '255.255.255.0')], ['Default Gateway', input('ylGw', gateway())], ['Static DNS', input('dns', '', 'disabled')]])}
      <div class="px-err"></div><p><button class="yl-btn ok">Confirm</button><button class="yl-btn sec cancel">Cancel</button></p>`;
    modeSync(main, 'yl');
    main.querySelector('.cancel').onclick = () => render();
    main.querySelector('.ok').onclick = async () => {
      try { await saveIp(main.querySelector('input[name=ylm]:checked').value, val(main, '#ylIp'), val(main, '#ylMask'), val(main, '#ylGw')); } catch (error) { main.querySelector('.px-err').textContent = error.message; }
    };
  }
  function ylRegister(main) {
    main.innerHTML = `<h3>Register · Account 1</h3>${ylRows([['Line Active', 'Disabled'], ['Label', ''], ['Display Name', ''], ['Register Name', ''], ['SIP Server 1', '—']])}
      <p style="color:#888">Pas de serveur SIP (IPBX) dans le laboratoire : le téléphone ne s’enregistre pas ; son réseau (Network › Basic) est réel.</p>`;
  }

  /* =============================== server management controllers: iDRAC, iLO, XClarity =============================== */
  skinCss(`
  .px-app.idrac,.px-app.ilo,.px-app.xcc{min-height:100vh;font:13px 'Segoe UI',Arial,sans-serif;color:#222;background:#f0f2f4}
  .bmc-top{display:flex;align-items:center;gap:14px;padding:0 18px;height:52px;color:#fff}.bmc-top b{font-size:15px}.bmc-top .grow{flex:1}.bmc-top span{opacity:.8}
  .px-app.idrac .bmc-top{background:#1d3a57}.px-app.ilo .bmc-top{background:#2b2f33}.px-app.xcc .bmc-top{background:#1f1f1f}
  .bmc-tabs{display:flex;background:#fff;border-bottom:1px solid #d9dee3}.bmc-tabs a{padding:11px 18px;cursor:pointer;color:#444}.bmc-tabs a.on{color:#1d6fb8;border-bottom:3px solid #1d6fb8;font-weight:bold}
  .bmc-tabs a.na{color:#a7aeb5}.bmc-body{display:grid;grid-template-columns:230px 1fr}.bmc-side{background:#2f3439;color:#ddd;min-height:calc(100vh - 52px);padding:8px 0}
  .bmc-side b{display:block;padding:10px 16px 4px;font-size:11px;color:#9aa3ab}.bmc-side a{display:block;padding:8px 16px 8px 24px;cursor:pointer}.bmc-side a.on{background:#454c53;color:#fff;border-left:3px solid #2ea36b}
  .bmc-side a.na{color:#7d858c}.bmc-main{padding:16px 20px}.bmc-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
  .bmc-card{background:#fff;border:1px solid #d9dee3;border-radius:3px}.bmc-card h3{margin:0;padding:10px 14px;border-bottom:1px solid #eef0f2;font-size:14px}.bmc-card .b{padding:12px 14px}
  .bmc-kv{display:grid;grid-template-columns:160px 1fr;gap:6px}.bmc-kv span{color:#666}.bmc-ok{color:#2e8540;font-weight:bold}.bmc-off{color:#a3001b;font-weight:bold}
  .bmc-console{height:150px;background:#000;display:grid;place-items:center;color:#7fdc7f;font:12px Consolas,monospace;margin-bottom:10px}
  .bmc-btn{border:0;background:#1d6fb8;color:#fff;padding:7px 14px;border-radius:2px;cursor:pointer}
  .bmc-t{width:100%;border-collapse:collapse}.bmc-t th{text-align:left;padding:7px 10px;border-bottom:1px solid #d9dee3;color:#555;font-weight:600;background:#f7f8f9}
  .bmc-t td{padding:8px 10px;border-bottom:1px solid #eef0f2}
  `);
  const BMC = {
    idrac: {title: 'Integrated Dell Remote Access Controller 9', tabs: [['Dashboard', 'dashboard'], ['System', 'system'], ['Storage', 'na'], ['Configuration', 'na'], ['Maintenance', 'logs'],
      ['iDRAC Settings', 'bmcnet']], console: 'Virtual Console', side: null},
    ilo: {title: 'iLO 5', tabs: null, console: 'Integrated Remote Console (HTML5)', side: [['Information', [['Overview', 'dashboard'], ['iLO Event Log', 'logs'], ['Integrated Management Log', 'logs']]],
      ['System Information', [['Summary · Network', 'system']]], ['Remote Console & Media', [['Remote Console', 'console']]], ['Power & Thermal', [['Server Power', 'na']]],
      ['iLO Dedicated Network Port', [['Settings', 'bmcnet']]], ['Administration', [['User Administration', 'na']]]]},
    xcc: {title: 'XClarity Controller', tabs: null, console: 'Remote Console', side: [['', [['Home', 'dashboard'], ['Events', 'logs'], ['Inventory', 'system'], ['Utilization', 'na'], ['Remote Console', 'console'],
      ['Firmware Update', 'na'], ['Server Configuration', 'na'], ['BMC Configuration', 'bmcnet']]]]},
  };
  function bmcSkin(id) {
    return {
      start: {page: 'dashboard'},
      draw(root) {
        const v = V(), spec = BMC[id];
        const nav = spec.tabs ? `<div class="bmc-tabs">${spec.tabs.map(([label, page]) => `<a data-go="${page}" class="${page === 'na' ? 'na' : ''}${page === v.page ? ' on' : ''}">${label}</a>`).join('')}</div>` : '';
        root.innerHTML = `<div class="bmc-top"><b>${spec.title}</b><span>${h(D().brand)} ${h(D().model)} · ${h(N().name)}</span><span class="grow"></span><span>sous-ensemble Network LABS · root</span></div>${nav}
          ${spec.side ? `<div class="bmc-body"><nav class="bmc-side">${spec.side.map(([g, items]) => `${g ? `<b>${g}</b>` : ''}${items.map(([label, page]) => `<a data-go="${page}" class="${page === 'na' ? 'na'
            : ''}${page === v.page ? ' on' : ''}">${label}</a>`).join('')}`).join('')}</nav><main class="bmc-main"></main></div>` : '<main class="bmc-main"></main>'}`;
        root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => { if (a.dataset.go === 'console') return openTerminal(); if (a.dataset.go !== 'na') go(a.dataset.go); }; });
        const main = root.querySelector('main');
        ({dashboard: bmcDashboard, system: bmcSystem, logs: bmcLogs, bmcnet: bmcNet}[v.page] || bmcDashboard)(main, spec);
      },
    };
  }
  SKINS.idrac = bmcSkin('idrac');
  SKINS.ilo = bmcSkin('ilo');
  SKINS.xcc = bmcSkin('xcc');
  function bmcDashboard(main, spec) {
    main.innerHTML = `<div class="bmc-grid"><div class="bmc-card"><h3>Health Information</h3><div class="b"><span class="bmc-ok">✔ System is Healthy</span><br><br>Active events: 0</div></div>
      <div class="bmc-card"><h3>System Information</h3><div class="b bmc-kv"><span>Power State</span>${running() ? '<b class="bmc-ok">ON</b>' : '<b class="bmc-off">OFF</b>'}<span>Model</span><b>${h(D().model)}</b>
      <span>Host Name</span><b>${h(N().name)}</b><span>Operating System</span><b>Linux (micro-VM)</b><span>Service Tag / Serial</span><b>—</b><span>OS IP Address</span><b>${h(ipLine())}</b></div></div>
      <div class="bmc-card"><h3>${spec.console}</h3><div class="b"><div class="bmc-console">${running() ? `${h(N().name)} login: _` : 'No signal'}</div><button class="bmc-btn launch">Launch ${spec.console}</button></div></div></div>
      <p style="color:#666">La mise sous tension suit ▶ Démarrer / ■ Arrêter dans Network LABS. L’adresse du système : sa console, comme sur le serveur réel, ou ◉ Network LABS › ☰ Vue Network LABS › Interfaces.</p>`;
    main.querySelector('.launch').onclick = openTerminal;
  }
  function bmcSystem(main) {
    main.innerHTML = `<div class="bmc-card"><h3>Network Devices</h3><div class="b">${table('bmc-t', ['Device', 'Port', 'Link Status', 'OS IPv4 Address', 'Connected To'], [tr(['Embedded NIC 1', 'Port 1',
      linked() ? '<span class="bmc-ok">Up</span>' : '<span class="bmc-off">Down</span>', h(ipLine()), h(peer())])])}</div></div>
      <div class="bmc-card" style="margin-top:14px"><h3>Inventory</h3><div class="b bmc-kv"><span>Processors</span><b>${h(N().vcpus || 1)} vCPU</b><span>Memory</span><b>${h(N().memory_mib || 128)} MiB</b>
      <span>BIOS</span><b>Network LABS</b></div></div>`;
  }
  function bmcLogs(main) {
    main.innerHTML = `<div class="bmc-card"><h3>Event Log</h3><div class="b">${table('bmc-t', ['Severity', 'Date and Time', 'Message'], running()
      ? [tr(['<span class="bmc-ok">OK</span>', new Date().toLocaleString('fr-FR'), 'The server is powered on.'])] : [tr(['<span class="bmc-ok">OK</span>', '—', 'The server is powered off.'])])}</div></div>`;
  }
  function bmcNet(main) {
    main.innerHTML = `<div class="bmc-card"><h3>Controller Network (dedicated management port)</h3><div class="b">${naBox('Management NIC',
      'Le port de gestion dédié du contrôleur n’est pas câblé dans le laboratoire : seule la carte réseau du serveur l’est (System › Network Devices).')}</div></div>`;
  }
})();
