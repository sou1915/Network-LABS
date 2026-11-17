/* Device view for the native management pages: a product header, the front panel and a dashboard per role.
 * Everything shown comes from the validated lab draft (state.device, built by appliances/device_view.py). */
'use strict';
(() => {
  const css = document.createElement('style');
  css.textContent = `
  :root{--accent:#2f9be0}
  .brand{display:none}
  .device-hero{position:relative;overflow:hidden;border-radius:20px;padding:22px 26px;display:grid;grid-template-columns:190px 1fr auto;
    gap:24px;align-items:center;color:#fff;background:linear-gradient(120deg,var(--hero-a),var(--hero-b));box-shadow:0 10px 30px rgba(15,35,55,.18)}
  .device-hero:after{content:"";position:absolute;inset:0;background:radial-gradient(circle at 85% -20%,rgba(255,255,255,.22),transparent 55%);pointer-events:none}
  .device-hero img{width:190px;height:auto;filter:drop-shadow(0 8px 14px rgba(0,0,0,.35))}
  .device-hero h1{margin:0;font-size:28px;letter-spacing:-.4px}
  .device-hero .model{margin-top:4px;font-size:15px;color:rgba(255,255,255,.86)}
  .chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
  .chip{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:5px 11px;font-size:12px;background:rgba(255,255,255,.14);
    border:1px solid rgba(255,255,255,.22);backdrop-filter:blur(4px)}
  .status{justify-self:end;text-align:right}
  .status .pill{display:inline-flex;align-items:center;gap:8px;border-radius:999px;padding:8px 14px;font-weight:600;background:rgba(0,0,0,.22)}
  .dot{width:9px;height:9px;border-radius:50%;background:#9aa9b8;box-shadow:0 0 0 3px rgba(255,255,255,.12)}
  .dot.on{background:#3ddc84;box-shadow:0 0 10px #3ddc84}
  .status small{display:block;margin-top:8px;color:rgba(255,255,255,.75)}
  .panel{margin-top:16px;border-radius:18px;background:#fff;border:1px solid #e0e8f2;padding:18px 22px}
  .panel-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px}
  .panel-head h2{margin:0;font-size:15px}
  .faceplate{display:flex;flex-wrap:wrap;gap:10px;padding:14px;border-radius:14px;background:linear-gradient(#24323f,#141d26);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.08),inset 0 -2px 6px rgba(0,0,0,.4)}
  .port{width:92px;border-radius:10px;padding:8px 8px 7px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);color:#dbe6f0;
    font-size:11px;text-align:center;position:relative}
  .port .jack{height:26px;margin:4px auto 6px;width:34px;border-radius:4px;background:#0a1016;border:1px solid #4a5a68;position:relative}
  .port .jack:after{content:"";position:absolute;left:9px;right:9px;bottom:-1px;height:7px;background:#0a1016;border:1px solid #4a5a68;border-top:0}
  .port .led{position:absolute;top:8px;right:8px;width:7px;height:7px;border-radius:50%;background:#55606a}
  .port.up .led{background:#3ddc84;box-shadow:0 0 8px #3ddc84}
  .port.down .led{background:#ff5d5d;box-shadow:0 0 8px #ff5d5d}
  .port b{display:block;font-size:12px;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .port .detail{color:#9fb2c4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .port .peer{margin-top:3px;color:#7fc4ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .port.spare{width:74px;opacity:.4;padding-top:6px}.port.spare b{font-size:10.5px;font-weight:500}.port.spare .jack{height:18px;width:24px;margin:4px auto 2px}
  .port .vlanbar{position:absolute;left:0;right:0;bottom:0;height:4px;border-radius:0 0 10px 10px}
  .legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:12px;color:#5f7389}
  .legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
  .kpi{border-radius:16px;padding:16px 18px;background:#fff;border:1px solid #e0e8f2;position:relative;overflow:hidden}
  .kpi:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--accent)}
  .kpi span{color:#66788f;font-size:12px}.kpi strong{display:block;font-size:26px;margin-top:6px;letter-spacing:-.5px}
  .kpi em{font-style:normal;font-size:12px;color:#66788f}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  .tag{display:inline-block;border-radius:999px;padding:3px 10px;font-size:12px;font-weight:600}
  .tag.allow{background:#e3f7ec;color:#137a43}.tag.deny{background:#fde8e8;color:#b42323}
  .tag.c{background:#e8f1fb;color:#1f5f9c}.tag.s{background:#fff3dd;color:#8a5a00}.tag.t{background:#efe9fb;color:#5b3aa6}
  .flow{white-space:nowrap}.flow b{font-weight:600}.flow i{font-style:normal;color:#8a9bb0;margin:0 6px}
  .empty{padding:18px;border-radius:12px;background:#f6f9fc;color:#66788f;text-align:center}
  .vchip{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:8px;vertical-align:-1px}
  @media (max-width:1100px){.kpis{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}.device-hero{grid-template-columns:120px 1fr}
    .device-hero img{width:120px}.status{grid-column:1/-1;justify-self:start;text-align:left}}
  `;
  document.head.appendChild(css);

  const THEMES = {
    router: ['#0d2638', '#1f5a85', '#2f9be0'], switch: ['#123049', '#2b6f9f', '#3aa0e8'],
    firewall: ['#2a0f12', '#8a2b1f', '#ff6a3d'], host: ['#16263a', '#34536f', '#4aa3df'],
  };
  const VLAN_COLOURS = ['#3aa0e8', '#35c47c', '#f2a93b', '#b06ee8', '#e85d75', '#2ec4c4', '#8f9c2b', '#e07b39'];
  const vlanColour = vid => vid === 1 ? '#8a9bb0' : VLAN_COLOURS[vid % VLAN_COLOURS.length];
  const hero = document.createElement('section');
  hero.className = 'device-hero';
  const front = document.createElement('section');
  front.className = 'panel';
  document.querySelector('main').prepend(front);
  document.querySelector('main').prepend(hero);
  const portName = port => (state.device.port_names || {})[port] || port;
  const service = rule => {
    if (!rule.protocol || rule.protocol === 'any') return 'Tous';
    return rule.dport ? `${rule.protocol.toUpperCase()}/${rule.dport}` : rule.protocol.toUpperCase();
  };
  const panelHtml = (title, note, body) =>
    `<div class="panel"><div class="panel-head"><h2>${esc(title)}</h2><span class="muted">${esc(note || '')}</span></div>${body}</div>`;
  const tableOr = (head, rows, empty) => rows.length ? `<div class="table">${table(head, rows)}</div>` : `<div class="empty">${esc(empty)}</div>`;
  const kpis = items => `<div class="kpis">${items.map(([label, value, hint]) =>
    `<div class="kpi"><span>${esc(label)}</span><strong>${esc(value)}</strong><em>${esc(hint || '')}</em></div>`).join('')}</div>`;

  function drawHero() {
    const n = state.node, d = state.device, theme = THEMES[n.role] || THEMES.host;
    document.documentElement.style.setProperty('--accent', theme[2]);
    hero.style.setProperty('--hero-a', theme[0]);
    hero.style.setProperty('--hero-b', theme[1]);
    const running = state.observed === 'running';
    const cabled = d.ports.filter(p => p.peer).length;
    hero.innerHTML = `<img alt="" src="/devices/${esc(d.art)}@${d.art.startsWith('host') || d.art === 'server' ? 145 : 175}.png">
      <div><h1>${esc(n.name)}</h1><div class="model">${esc(d.brand)} · ${esc(d.model)} — ${esc(d.role_name)}</div>
      <div class="chips"><span class="chip">⬢ ${esc(d.runtime)}</span>
      <span class="chip">⇄ ${d.ports.length} port${d.ports.length > 1 ? 's' : ''} déclaré${d.ports.length > 1 ? 's' : ''} · ${cabled} câblé${cabled > 1 ? 's' : ''}</span>
      ${d.cli ? `<span class="chip">⌨ CLI ${esc(d.cli)}</span>` : ''}<span class="chip">◆ Système Linux</span></div></div>
      <div class="status"><span class="pill"><span class="dot${running ? ' on' : ''}"></span>${running ? 'En marche' : 'Non observé'}</span>
      <small>Projet ${esc(state.project)}</small></div>`;
  }

  function drawFront() {
    const d = state.device, n = state.node;
    const tiles = d.ports.map(p => {
      const cls = p.down ? 'down' : p.peer ? 'up' : '';
      const bar = n.role === 'switch' ? `<span class="vlanbar" style="background:${p.trunk ? 'repeating-linear-gradient(90deg,#3aa0e8 0 8px,#35c47c 8px 16px,#f2a93b 16px 24px)' : vlanColour(p.vlan)}"></span>` : '';
      return `<div class="port ${cls}" title="${esc(p.port)} · ${esc(p.detail)}"><span class="led"></span><b>${esc(p.name)}</b><div class="jack"></div>
        <div class="detail">${esc(p.detail)}</div><div class="peer">${esc(p.peer || 'non câblé')}</div>${bar}</div>`;
    }).join('') + d.spare.map(name => `<div class="port spare" title="Port du modèle non déclaré dans ce laboratoire"><b>${esc(name)}</b><div class="jack"></div></div>`).join('');
    const legend = n.role === 'switch'
      ? d.vlans.map(v => `<span><i style="background:${vlanColour(v)}"></i>VLAN ${v}</span>`).join('') + '<span><i style="background:linear-gradient(90deg,#3aa0e8,#35c47c,#f2a93b)"></i>Trunk 802.1Q</span>'
      : '<span><i style="background:#3ddc84"></i>Câblé</span><span><i style="background:#55606a"></i>Libre</span><span><i style="background:#ff5d5d"></i>Arrêté</span>';
    const spare = d.spare.length ? '<span><i style="background:#3a4652"></i>Port du modèle non déclaré</span>' : '';
    front.innerHTML = `<div class="panel-head"><h2>Face avant</h2><span class="muted">Noms de ports ${esc(d.brand)} · interface Linux en info-bulle</span></div>
      <div class="faceplate">${tiles}</div><div class="legend">${legend}${spare}</div>`;
  }

  function firewallDashboard(n, d) {
    const fw = n.firewall || {rules: [], nat: []};
    const rules = (fw.rules || []).map((r, i) => [String(i + 1), `<b>${esc(r.name)}</b>`,
      `<span class="flow"><b>${esc(r.in ? portName(r.in) : 'toutes')}</b><i>→</i><b>${esc(r.out ? portName(r.out) : 'toutes')}</b></span>`,
      esc(r.source || 'toutes'), esc(r.destination || 'toutes'), esc(service(r)),
      `<span class="tag ${r.action === 'accept' ? 'allow' : 'deny'}">${r.action === 'accept' ? 'Autoriser' : 'Bloquer'}</span>`]);
    const nat = (fw.nat || []).map(r => [`<b>${esc(r.name)}</b>`, `<span class="tag t">${esc(({masquerade: 'Masquerade', snat: 'SNAT', dnat: 'DNAT'})[r.type] || r.type)}</span>`,
      esc(r.in ? portName(r.in) : r.out ? portName(r.out) : '—'), esc([r.source, r.destination].filter(Boolean).join(' → ') || 'tout'),
      esc(r.to ? r.to + (r.to_port ? ':' + r.to_port : '') : 'adresse du port')]);
    return kpis([['Règles de sécurité', rules.length, 'évaluées dans l’ordre'], ['Règles NAT', nat.length, 'source et destination'],
        ['Action par défaut', fw.default === 'accept' ? 'Autoriser' : 'Bloquer', fw.stateful ? 'suivi des sessions actif' : 'sans état'],
        ['Ports câblés', d.ports.filter(p => p.peer).length + ' / ' + d.ports.length, 'zones = ports']])
      + panelHtml('Politique de sécurité', 'trafic transitant · IPv4', tableOr(['#', 'Nom', 'Flux', 'Source', 'Destination', 'Service', 'Action'], rules,
        'Aucune règle : tout le trafic transitant suit l’action par défaut.'))
      + panelHtml('NAT', 'traductions d’adresses', tableOr(['Nom', 'Type', 'Port', 'Correspondance', 'Traduit vers'], nat, 'Aucune traduction déclarée.'));
  }

  function routingTable(d) {
    const rows = [...d.static.map(r => ['<span class="tag s">S</span>', `<b>${esc(r.network)}</b>`, esc(r.gateway), esc(r.port)]),
      ...d.connected.map(r => ['<span class="tag c">C</span>', `<b>${esc(r.network)}</b>`, 'directement connecté', esc(r.port)])];
    return panelHtml('Table de routage déclarée', 'C connecté · S statique', tableOr(['', 'Réseau', 'Passerelle', 'Interface'], rows, 'Aucune route.'));
  }

  function interfacesTable(d) {
    const rows = d.ports.map(p => [`<b>${esc(p.name)}</b>`, `<span class="muted">${esc(p.port)}</span>`, esc(p.address || p.detail), esc(p.peer || '—')]);
    for (const sub of d.subinterfaces) rows.push([`<b>${esc(sub.name)}</b>`, `<span class="muted">${esc(sub.port)}</span>`,
      esc(sub.address || '—'), `<span class="tag t">VLAN ${esc(sub.vlan)}</span>`]);
    return panelHtml('Interfaces', 'adresses du projet', tableOr(['Port', 'Linux', 'Adresse', 'Voisin / VLAN'], rows, 'Aucun port.'));
  }

  function routerDashboard(n, d) {
    return kpis([['Interfaces routées', d.connected.length, 'ports et sous-interfaces'], ['Routes statiques', d.static.length, 'y compris défaut'],
        ['Sous-interfaces', Object.keys(n.subinterfaces || {}).length, '802.1Q'], ['Ports câblés', d.ports.filter(p => p.peer).length + ' / ' + d.ports.length, '']])
      + `<div class="grid2">${interfacesTable(d)}${routingTable(d)}</div>`;
  }

  function switchDashboard(n, d) {
    const access = d.ports.filter(p => !p.trunk), trunks = d.ports.filter(p => p.trunk);
    const vlanRows = d.vlans.map(v => [`<span class="vchip" style="background:${vlanColour(v)}"></span><b>VLAN ${v}</b>`,
      esc(v === 1 ? 'default' : `VLAN${String(v).padStart(4, '0')}`),
      esc(access.filter(p => p.vlan === v).map(p => p.name).join(', ') || '—'),
      esc(trunks.filter(p => /toutes/.test(p.detail) || p.detail.replace('Trunk ', '').split(',').map(Number).includes(v)).map(p => p.name).join(', ') || '—')]);
    const portRows = d.ports.map(p => [`<b>${esc(p.name)}</b>`, p.trunk ? '<span class="tag t">Trunk</span>' : '<span class="tag c">Access</span>',
      esc(p.trunk ? p.detail.replace('Trunk ', '') : 'VLAN ' + p.vlan), esc(p.peer || '—')]);
    return kpis([['VLAN', d.vlans.length, 'déclarés'], ['Ports access', access.length, ''], ['Trunks', trunks.length, '802.1Q'],
        ['Ports câblés', d.ports.filter(p => p.peer).length + ' / ' + d.ports.length, '']])
      + `<div class="grid2">${panelHtml('VLAN', 'membres par VLAN', tableOr(['VLAN', 'Nom', 'Ports access', 'Trunks'], vlanRows, 'Aucun VLAN.'))}`
      + `${panelHtml('Ports', 'mode et voisin', tableOr(['Port', 'Mode', 'VLAN', 'Voisin'], portRows, 'Aucun port.'))}</div>`;
  }

  function dashboard() {
    const n = state.node, d = state.device;
    $('title').textContent = 'Tableau de bord';
    $('listing').classList.remove('table');
    const body = n.role === 'firewall' ? firewallDashboard(n, d) : n.role === 'router' ? routerDashboard(n, d)
      : n.role === 'switch' ? switchDashboard(n, d) : kpis([['Ports', d.ports.length, ''], ['Adresses', d.connected.length, ''],
        ['Routes', d.static.length, ''], ['Câblés', d.ports.filter(p => p.peer).length, '']]) + `<div class="grid2">${interfacesTable(d)}${routingTable(d)}</div>`;
    $('listing').innerHTML = body;
  }

  const previous = render;
  render = function () {
    previous();
    if (!state || !state.device) return;
    drawHero();
    drawFront();
    if (page === 'dashboard') dashboard();
    if (page === 'interfaces') {
      // Vendor port names in the interface list; switches have no addresses or gateway to edit here.
      $('listing').querySelectorAll('tbody tr').forEach(row => {
        const cell = row.cells[0];
        if (cell && state.device.port_names[cell.textContent]) cell.innerHTML = `<b>${esc(portName(cell.textContent))}</b> <span class="muted">${esc(cell.textContent)}</span>`;
      });
    }
    for (const id of ['address', 'gateway']) $(id).closest('label').style.display = state.node.role === 'switch' ? 'none' : '';
    document.title = `${state.node.name} · ${state.device.title} · Network LABS`;
  };
})();
