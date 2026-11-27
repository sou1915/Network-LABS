/* Device view for the native management pages: a product header, the front panel and a dashboard per role.
 * Everything shown comes from the validated lab draft (state.device, built by appliances/device_view.py). */
'use strict';
(() => {
  const css = document.createElement('style');
  css.textContent = `
  :root{--accent:#111111}
  .brand{display:none}
  .device-hero{position:relative;overflow:hidden;border-radius:20px;padding:22px 26px;display:grid;grid-template-columns:190px 1fr auto;
    gap:24px;align-items:center;color:#ffffff;background:linear-gradient(120deg,var(--hero-a),var(--hero-b));box-shadow:0 10px 30px rgba(17,17,17,.18)}
  .device-hero:after{content:"";position:absolute;inset:0;background:radial-gradient(circle at 85% -20%,rgba(255,255,255,.22),transparent 55%);pointer-events:none}
  .device-hero img{width:190px;height:auto;filter:grayscale(1) drop-shadow(0 8px 14px rgba(0,0,0,.35))}
  .device-hero h1{margin:0;font-size:28px;letter-spacing:-.4px}
  .device-hero .model{margin-top:4px;font-size:15px;color:rgba(255,255,255,.86)}
  .chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
  .chip{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:5px 11px;font-size:12px;background:rgba(255,255,255,.14);
    border:1px solid rgba(255,255,255,.22);backdrop-filter:blur(4px)}
  .status{justify-self:end;text-align:right}
  .status .pill{display:inline-flex;align-items:center;gap:8px;border-radius:999px;padding:8px 14px;font-weight:600;background:rgba(0,0,0,.22)}
  .dot{width:9px;height:9px;border-radius:50%;background:#a6a6a6;box-shadow:0 0 0 3px rgba(255,255,255,.12)}
  .dot.on{background:#111111;box-shadow:0 0 10px #111111}
  .status small{display:block;margin-top:8px;color:rgba(255,255,255,.75)}
  .panel{margin-top:16px;border-radius:18px;background:#ffffff;border:1px solid #e7e7e7;padding:18px 22px}
  .panel-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px}
  .panel-head h2{margin:0;font-size:15px}
  .faceplate{display:flex;flex-wrap:wrap;gap:10px;padding:14px;border-radius:14px;background:linear-gradient(#2f2f2f,#111111);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.08),inset 0 -2px 6px rgba(0,0,0,.4)}
  .port{width:92px;border-radius:10px;padding:8px 8px 7px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);color:#b6b6b6;
    font-size:11px;text-align:center;position:relative}
  .port .jack{height:26px;margin:4px auto 6px;width:34px;border-radius:4px;background:#111111;border:1px solid #575757;position:relative}
  .port .jack:after{content:"";position:absolute;left:9px;right:9px;bottom:-1px;height:7px;background:#111111;border:1px solid #575757;border-top:0}
  .port .led{position:absolute;top:8px;right:8px;width:7px;height:7px;border-radius:50%;background:#4a4a4a}
  .port.up .led{background:#ffffff;box-shadow:0 0 8px rgba(255,255,255,.7)}
  .port.down .led{background:transparent;border:1.5px solid #ffffff;box-sizing:border-box}
  .port b{display:block;font-size:12px;color:#ffffff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .port .detail{color:#a8a8a8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .port .peer{margin-top:3px;color:#d9d9d9;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .port.spare{width:74px;opacity:.4;padding-top:6px}.port.spare b{font-size:10.5px;font-weight:500}.port.spare .jack{height:18px;width:24px;margin:4px auto 2px}
  .port .vlanbar{position:absolute;left:0;right:0;bottom:0;height:4px;border-radius:0 0 10px 10px}
  .legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:12px;color:#595959}
  .legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
  .panel + .kpis{margin-top:16px}
  .kpi{border-radius:16px;padding:16px 18px;background:#ffffff;border:1px solid #e7e7e7;position:relative;overflow:hidden}
  .kpi:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--accent)}
  .kpi span{color:#5e5e5e;font-size:12px}.kpi strong{display:block;font-size:26px;margin-top:6px;letter-spacing:-.5px}
  .kpi em{font-style:normal;font-size:12px;color:#5e5e5e}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  .tag{display:inline-block;border-radius:999px;padding:3px 10px;font-size:12px;font-weight:600}
  .tag.allow{background:#111111;color:#ffffff}.tag.deny{background:#ffffff;color:#111111;box-shadow:inset 0 0 0 1.5px #111111}
  .tag.c{background:#e6e6e6;color:#111111}.tag.s{background:#ffffff;color:#111111;box-shadow:inset 0 0 0 1px #9a9a9a}.tag.t{background:#111111;color:#ffffff}
  .flow{white-space:nowrap}.flow b{font-weight:600}.flow i{font-style:normal;color:#7a7a7a;margin:0 6px}
  .empty{padding:18px;border-radius:12px;background:#f8f8f8;color:#5e5e5e;text-align:center}
  .vchip{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:8px;vertical-align:-1px;box-shadow:inset 0 0 0 1px #111111}
  .live-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
  .live-head .verdict{font-weight:600}.verdict.ok{color:#111111}.verdict.bad{color:#5f5f5f}
  .tag.ok{background:#111111;color:#ffffff}.tag.bad{background:#ffffff;color:#111111;box-shadow:inset 0 0 0 1.5px #111111}.tag.extra{background:#f4f4f4;color:#5f5f5f}
  .observe{background:var(--accent);color:#ffffff;border:0;font-weight:600}
  .observe:disabled{background:#e2e2e2;color:#4a4a4a}
  @media (max-width:1100px){.kpis{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}.device-hero{grid-template-columns:120px 1fr}
    .device-hero img{width:120px}.status{grid-column:1/-1;justify-self:start;text-align:left}}
  `;
  document.head.appendChild(css);

  const THEMES = {
    router: ['#111111', '#111111', '#111111'], switch: ['#111111', '#111111', '#111111'],
    firewall: ['#5f5f5f', '#5f5f5f', '#5f5f5f'], host: ['#111111', '#111111', '#111111'],
  };
  const VLAN_COLOURS = ['#e6e6e6', '#9a9a9a', '#cfcfcf', '#7a7a7a', '#f5f5f5', '#b5b5b5', '#8a8a8a', '#dadada'];
  const vlanColour = vid => vid === 1 ? '#5c5c5c' : VLAN_COLOURS[vid % VLAN_COLOURS.length];
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
      const bar = n.role === 'switch' ? `<span class="vlanbar" style="background:${p.trunk ? 'repeating-linear-gradient(90deg,#ffffff 0 8px,#7a7a7a 8px 16px)' : vlanColour(p.vlan)}"></span>` : '';
      return `<div class="port ${cls}" title="${esc(p.port)} · ${esc(p.detail)}"><span class="led"></span><b>${esc(p.name)}</b><div class="jack"></div>
        <div class="detail">${esc(p.detail)}</div><div class="peer">${esc(p.peer || 'non câblé')}</div>${bar}</div>`;
    }).join('') + d.spare.map(name => `<div class="port spare" title="Port du modèle non déclaré dans ce laboratoire"><b>${esc(name)}</b><div class="jack"></div></div>`).join('');
    const legend = n.role === 'switch'
      ? d.vlans.map(v => `<span><i style="background:${vlanColour(v)};box-shadow:inset 0 0 0 1px #111111"></i>VLAN ${v}</span>`).join('') + '<span><i style="background:repeating-linear-gradient(90deg,#111111 0 3px,#cfcfcf 3px 6px);box-shadow:inset 0 0 0 1px #111111"></i>Trunk 802.1Q</span>'
      : '<span><i style="background:#111111;border-radius:50%"></i>Câblé</span><span><i style="background:#cfcfcf;border-radius:50%"></i>Libre</span><span><i style="border:1.5px solid #111111;border-radius:50%;box-sizing:border-box"></i>Arrêté</span>';
    const spare = d.spare.length ? '<span><i style="background:#444444"></i>Port du modèle non déclaré</span>' : '';
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

  const stateTag = value => value === 'ok' ? '<span class="tag ok">Conforme</span>'
    : value === 'ospf' ? '<span class="tag t">Apprise OSPF</span>'
    : value === 'non déclarée' ? '<span class="tag extra">Non déclarée</span>' : `<span class="tag bad">${esc(value[0].toUpperCase() + value.slice(1))}</span>`;
  let observeUntil = 0;

  function liveSection(n) {
    const live = state.live, running = state.observed === 'running';
    const button = `<button type="button" class="observe" id="observeNode"${running && !state.observing ? '' : ' disabled'}>`
      + `${state.observing ? 'Relevé en cours… confirmer dans le terminal' : live ? '↻ Relever à nouveau' : 'Relever l’état réel'}</button>`;
    if (!live) {
      const why = running ? 'Lit les interfaces, routes' + (n.role === 'switch' ? ', VLAN du pont' : '') + (n.ospf ? ', voisins OSPF' : '') + (n.role === 'firewall' ? ' et sessions suivies' : '')
        + ' sur le nœud en marche (authentification sudo dans un terminal), puis les compare au projet.'
        : 'Démarrer le laboratoire et actualiser son état : le relevé lit le nœud en marche.';
      return panelHtml('État réel', 'nœud Linux en marche', `<div class="live-head"><span class="muted">${esc(why)}</span>${button}</div>`);
    }
    const verdict = live.conform ? '<span class="verdict ok">● Conforme au projet</span>' : '<span class="verdict bad">● Écarts avec le projet</span>';
    const parts = [`<div class="live-head"><span>${verdict} <span class="muted">· relevé à ${esc(live.time)}</span></span>${button}</div>`];
    parts.push('<h3 class="muted" style="margin:16px 0 8px">Interfaces</h3>' + tableOr(['Port', 'Lien', 'Adresses relevées', 'Projet', ''],
      live.interfaces.map(i => [`<b>${esc(i.name)}</b> <span class="muted">${esc(i.port)}</span>`, i.up ? '<span class="tag ok">UP</span>' : '<span class="tag bad">DOWN</span>',
        esc(i.addresses.join(', ') || '—'), esc(i.declared || '—'), stateTag(i.ok ? 'ok' : 'écart')]), 'Aucune interface relevée.'));
    if (n.role !== 'switch') {
      const title = live.ospf ? 'Routes (statiques et OSPF)' : 'Routes statiques';
      parts.push(`<h3 class="muted" style="margin:16px 0 8px">${title}</h3>` + tableOr(['Réseau', 'Passerelle', 'Interface', ''],
        live.routes.map(r => [`<b>${esc(r.network)}</b>`, esc(r.gateway) + (r.state === 'ospf' && r.metric != null ? ` <span class="muted">coût ${esc(r.metric)}</span>` : ''),
          esc(r.port), stateTag(r.state)]), 'Aucune route, ni déclarée ni relevée.'));
    }
    if (live.ospf) {
      const o = live.ospf;
      const head = o.running ? (o.complete ? '<span class="tag ok">Voisinages complets</span>' : '<span class="tag bad">Voisin manquant</span>')
        : '<span class="tag bad">OSPF arrêté</span>';
      parts.push(`<h3 class="muted" style="margin:16px 0 8px">OSPF zone 0 · router-id ${esc(o.router_id)} ${head}</h3>`
        + tableOr(['Interface', 'Mode', 'Coût', 'Voisins Full'], o.interfaces.map(i => [`<b>${esc(i.name)}</b>`,
          i.passive ? 'passive (pas de hello)' : 'active', esc(i.cost), i.passive ? '—' : (i.neighbors ? `<span class="tag ok">${i.neighbors}</span>` : '<span class="tag bad">0</span>')]), 'Aucune interface OSPF.')
        + '<div style="margin-top:12px">' + tableOr(['Voisin (router-id)', 'État', 'Adresse', 'Interface'], o.neighbors.map(r => [`<b>${esc(r.router_id)}</b>`,
          r.state === 'Full' ? '<span class="tag ok">Full</span>' : `<span class="tag bad">${esc(r.state)}</span>`, esc(r.address), esc(r.port)]),
          'Aucun voisin OSPF relevé.') + '</div>');
    }
    if (live.vlans) parts.push('<h3 class="muted" style="margin:16px 0 8px">VLAN du pont Linux</h3>' + tableOr(['Port', 'VLAN', 'Mode', ''],
      live.vlans.map(v => [`<b>${esc(v.port)}</b>`, `<span class="vchip" style="background:${vlanColour(v.vlan)}"></span>VLAN ${esc(v.vlan)}`,
        v.mode === 'pvid' ? 'non étiqueté (PVID)' : 'étiqueté 802.1Q', stateTag(v.state)]), 'Un seul VLAN 1 non étiqueté : pont sans filtrage VLAN.'));
    if (n.role === 'firewall') parts.push('<h3 class="muted" style="margin:16px 0 8px">Sessions suivies</h3>' + (live.sessions
      ? tableOr(['Protocole', 'Source', 'Destination', 'Port', 'État'], live.sessions.map(x => [`<span class="tag t">${esc(x.protocol.toUpperCase())}</span>`,
        esc(x.source), esc(x.destination), esc(x.port || '—'), esc(x.state || (x.replied ? 'réponse vue' : 'sans réponse'))]), 'Aucune session en cours.')
      : `<div class="empty">Sessions indisponibles : ${esc(live.sessions_error || 'non relevées')}</div>`));
    return panelHtml('État réel', 'relevé sur le nœud Linux en marche', parts.join(''));
  }

  async function observe() {
    try {
      state = await request('/api/observe', {node});
      render();
      message('Relevé demandé : confirmer avec sudo dans le terminal ouvert par Network LABS.');
      observeUntil = Date.now() + 180000;
      const before = state.live && state.live.time;
      const poll = async () => {
        if (Date.now() > observeUntil) return;
        try {
          const next = await request('/api/state?node=' + encodeURIComponent(node));
          const done = !next.observing && (next.live && next.live.time) !== before;
          if (done || !next.observing) { state = next; render(); message(done ? 'État réel relevé.' : 'Relevé terminé sans nouvelle observation : voir les événements.', !done); return; }
        } catch (error) { message(error.message, true); return; }
        setTimeout(poll, 1500);
      };
      setTimeout(poll, 1500);
    } catch (error) { message(error.message, true); }
  }

  function dashboard() {
    const n = state.node, d = state.device;
    $('title').textContent = 'Tableau de bord';
    $('listing').classList.remove('table');
    const body = n.role === 'firewall' ? firewallDashboard(n, d) : n.role === 'router' ? routerDashboard(n, d)
      : n.role === 'switch' ? switchDashboard(n, d) : kpis([['Ports', d.ports.length, ''], ['Adresses', d.connected.length, ''],
        ['Routes', d.static.length, ''], ['Câblés', d.ports.filter(p => p.peer).length, '']]) + `<div class="grid2">${interfacesTable(d)}${routingTable(d)}</div>`;
    $('listing').innerHTML = liveSection(n) + body;
    const button = $('observeNode');
    if (button) button.onclick = observe;
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
