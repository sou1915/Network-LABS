/* A PC's or server's desktop, as Packet Tracer's « Desktop » tab: app tiles on a wallpaper and a taskbar, in a neutral
 * Network LABS look (no vendor logo or assets). « Configuration IP » sets DHCP or a static address, mask, gateway and DNS
 * server in the project (/api/host_ip); « Invite de commandes » opens the device's terminal in the application
 * (/api/open_cli); « Informations réseau » shows what ipconfig /all would, from the project; « Navigateur web » fetches
 * a server's pages from this device (/api/browse: a real HTTP GET in the guest when the lab runs, the project otherwise);
 * a server's « Services » (HTTP, DNS, NTP, SYSLOG, as Packet Tracer's Services tab) are kept in the project
 * (/api/services) and run in its guest (guest_services). */
'use strict';
(() => {
  const css = document.createElement('style');
  css.textContent = `
  body.pc{margin:0;background:#0f2235}
  body.pc>header,body.pc>.layout{display:none}
  .pc-app{position:fixed;inset:0;display:grid;grid-template-rows:1fr 48px;font:13px Inter,Arial,sans-serif;color:#13263a;
    background:radial-gradient(1200px 700px at 78% 18%,rgba(97,183,255,.55),transparent 60%),
      radial-gradient(900px 600px at 12% 92%,rgba(46,196,182,.35),transparent 60%),linear-gradient(140deg,#0e2a47,#123a5e 45%,#0d2f4a)}
  .pc-desk{position:relative;padding:24px 28px;display:grid;grid-auto-flow:column;grid-template-rows:repeat(auto-fill,112px);grid-auto-columns:108px;gap:10px 14px;align-content:start;justify-content:start}
  .pc-icon{display:flex;flex-direction:column;align-items:center;gap:8px;padding:10px 6px;border-radius:12px;color:#fff;cursor:pointer;
    text-align:center;font-size:12.5px;line-height:1.25;user-select:none;border:1px solid transparent;background:none}
  .pc-icon:hover{background:rgba(255,255,255,.12);border-color:rgba(255,255,255,.18)}
  .pc-icon.off{opacity:.55;cursor:default}.pc-icon.off:hover{background:none;border-color:transparent}
  .pc-glyph{width:54px;height:54px;border-radius:14px;display:grid;place-items:center;box-shadow:0 8px 18px rgba(0,0,0,.28);font-size:26px}
  .pc-glyph svg{width:30px;height:30px}
  .pc-bar{display:flex;align-items:center;gap:12px;padding:0 14px;background:rgba(9,22,36,.78);backdrop-filter:blur(10px);color:#e7f0f8;
    border-top:1px solid rgba(255,255,255,.08)}
  .pc-bar b{font-size:13px}.pc-bar .sub{color:#9db3c8;font-size:12px}.pc-bar .grow{flex:1}
  .pc-bar button{background:rgba(255,255,255,.08);color:#e7f0f8;border:1px solid rgba(255,255,255,.14);border-radius:8px;padding:6px 12px;font-size:12px}
  .pc-bar button:hover{background:rgba(255,255,255,.16)}
  .pc-pill{display:inline-flex;align-items:center;gap:7px;border-radius:999px;padding:4px 11px;background:rgba(255,255,255,.08);font-size:12px}
  .pc-pill i{width:8px;height:8px;border-radius:50%;background:#8a98a6}.pc-pill i.on{background:#3ddc84;box-shadow:0 0 8px #3ddc84}
  .pc-clock{font-variant-numeric:tabular-nums;color:#cfe0ef;font-size:12px;text-align:right;line-height:1.2}
  .pc-win{position:absolute;top:48px;left:calc(50% + 60px);transform:translateX(-50%);width:min(600px,80vw);background:#f7f9fc;border-radius:12px;
    box-shadow:0 24px 60px rgba(0,0,0,.45);overflow:hidden;border:1px solid rgba(255,255,255,.4)}
  .pc-win .title{display:flex;align-items:center;gap:10px;padding:10px 12px 10px 16px;background:#e9eff6;border-bottom:1px solid #d9e3ee;font-weight:600}
  .pc-win .title span{flex:1}.pc-win .title button{border:0;background:none;font-size:16px;padding:2px 8px;border-radius:6px;cursor:pointer;color:#30465c}
  .pc-win .title button:hover{background:#d3dfeb}
  .pc-win .content{padding:18px 20px}
  .pc-win fieldset{border:1px solid #d9e3ee;border-radius:10px;padding:12px 14px;margin:0 0 14px}
  .pc-win legend{padding:0 6px;font-size:12px;font-weight:600;color:#30465c}
  .pc-row{display:grid;grid-template-columns:170px 1fr;align-items:center;gap:10px;margin:8px 0}
  .pc-row label{color:#43586e;font-size:12.5px}
  .pc-row input,.pc-row select{border:1px solid #c9d6e3;border-radius:7px;padding:7px 10px;font:inherit;background:#fff}
  .pc-row input:disabled{background:#eef2f6;color:#7e8fa1}
  .pc-radio{display:flex;gap:18px;margin:4px 0 10px}.pc-radio label{display:flex;align-items:center;gap:7px;cursor:pointer}
  .pc-radio input{appearance:auto;width:auto;height:auto}
  .pc-acts{display:flex;justify-content:flex-end;gap:10px;margin-top:6px}
  .pc-acts button{border-radius:8px;padding:8px 16px;border:1px solid #c9d6e3;background:#fff;cursor:pointer}
  .pc-acts .ok{background:#1769c4;border-color:#1769c4;color:#fff}.pc-acts .ok:disabled{opacity:.55}
  .pc-msg{margin-top:12px;font-size:12px;line-height:1.5;color:#37506a;min-height:18px}.pc-msg.bad{color:#b42323}
  .pc-note{font-size:11.5px;color:#6a7f94;line-height:1.5}
  .pc-pre{background:#0c1622;color:#d9e8f5;border-radius:8px;padding:14px 16px;font:12px "DejaVu Sans Mono",monospace;white-space:pre;overflow:auto;margin:0}
  .pc-win.wide{width:min(860px,92vw)}.pc-win.wide .content{padding:0}
  .pc-url{display:flex;gap:8px;padding:10px 12px;background:#eef3f8;border-bottom:1px solid #d9e3ee}
  .pc-url input{flex:1;border:1px solid #c9d6e3;border-radius:16px;padding:7px 14px;font:inherit;background:#fff}
  .pc-url button{border:1px solid #c9d6e3;border-radius:8px;background:#fff;padding:6px 12px;cursor:pointer}
  .pc-page{width:100%;height:min(56vh,460px);border:0;background:#fff;display:block}
  .pc-status{padding:6px 12px;font-size:11.5px;color:#5c7086;border-top:1px solid #e2e9f1;background:#f6f8fb;min-height:16px}
  .pc-error{padding:40px 30px;color:#37506a;height:min(56vh,460px);box-sizing:border-box}.pc-error h3{margin:0 0 8px;font-size:17px;color:#1d3349}
  .sv{display:grid;grid-template-columns:150px 1fr;min-height:min(60vh,480px)}
  .sv-tabs{background:#eef3f8;border-right:1px solid #d9e3ee;padding:8px 0}
  .sv-tabs a{display:block;padding:9px 16px;cursor:pointer;color:#30465c;font-weight:600;font-size:12.5px;letter-spacing:.3px}
  .sv-tabs a.on{background:#fff;color:#1769c4;box-shadow:inset 3px 0 #1769c4}
  .sv-body{padding:16px 20px;overflow:auto;max-height:min(64vh,520px)}
  .sv-body h3{margin:0 0 12px;font-size:15px;text-align:center;letter-spacing:.5px;color:#1d3349}
  .sv-onoff{display:flex;gap:22px;align-items:center;margin:0 0 14px}.sv-onoff label{display:flex;gap:6px;align-items:center;cursor:pointer}
  .sv-onoff input{appearance:auto;width:auto;height:auto}
  .sv-t{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:10px}.sv-t th{background:#eef3f8;text-align:left;padding:6px 8px;border:1px solid #d9e3ee}
  .sv-t td{padding:6px 8px;border:1px solid #e2e9f1}.sv-t tr.sel td{background:#e3efff}.sv-t tbody tr{cursor:pointer}
  .sv-grid{display:grid;grid-template-columns:90px 1fr 70px 1fr;gap:8px;align-items:center}
  .sv-grid input,.sv-grid select,.sv-body textarea{border:1px solid #c9d6e3;border-radius:7px;padding:6px 9px;font:inherit;background:#fff}
  .sv-body textarea{width:100%;box-sizing:border-box;height:180px;font:12px "DejaVu Sans Mono",monospace;margin-top:8px}
  .sv-btns{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}.sv-btns button{border:1px solid #c9d6e3;border-radius:7px;background:#fff;padding:6px 12px;cursor:pointer}
  .sv-btns button.ok,.sv-foot button.ok{background:#1769c4;border-color:#1769c4;color:#fff}
  .sv-foot button{border:1px solid #c9d6e3;border-radius:8px;background:#fff;padding:8px 16px;cursor:pointer}
  .sv-foot{display:flex;align-items:center;gap:10px;padding:10px 16px;border-top:1px solid #d9e3ee;background:#f6f8fb}
  .sv-foot .grow{flex:1}.sv-foot .pc-msg{margin:0}
  .pc-toast{position:fixed;left:50%;bottom:64px;transform:translateX(-50%);background:rgba(9,22,36,.92);color:#fff;padding:10px 16px;border-radius:10px;
    box-shadow:0 8px 24px rgba(0,0,0,.35);font-size:12.5px;z-index:9}
  `;
  document.head.appendChild(css);

  const svg = path => `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${path}</svg>`;
  const APPS = [
    ['ip', 'Configuration IP', '#1f7ae0', svg('<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4M7 9h4M7 12h7"/>')],
    ['cmd', 'Invite de commandes', '#22313f', svg('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 10l3 2-3 2M12 15h5"/>')],
    ['info', 'Informations réseau', '#0f9d8a', svg('<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v5h1"/>')],
    ['web', 'Navigateur web', '#6b55d3', svg('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18"/>')],
    ['services', 'Services', '#2d8a4e', svg('<rect x="4" y="3" width="16" height="7" rx="1.5"/><rect x="4" y="14" width="16" height="7" rx="1.5"/><path d="M8 6.5h.01M8 17.5h.01M12 6.5h5M12 17.5h5"/>')],
    ['mail', 'Messagerie', '#d9822b', svg('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>'),
      'Bientôt : un serveur de messagerie dans le laboratoire.'],
    ['text', 'Éditeur de texte', '#5b6b7b', svg('<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 12h7M9 16h7"/>'),
      'Bientôt.'],
  ];
  let desk = null, toastTimer = null, standard = false;
  const prefixToMask = prefix => [0, 8, 16, 24].map(s => (prefix >= s + 8 ? 255 : prefix <= s ? 0 : 256 - 2 ** (8 - (prefix - s)))).join('.');
  const maskToPrefix = mask => {
    const parts = mask.trim().split('.').map(Number);
    if (parts.length !== 4 || parts.some(p => !(p >= 0 && p <= 255) || !Number.isInteger(p))) return null;
    const bits = parts.map(p => p.toString(2).padStart(8, '0')).join('');
    return /^1*0*$/.test(bits) ? bits.indexOf('0') === -1 ? 32 : bits.indexOf('0') : null;
  };

  function toast(text) {
    let box = document.querySelector('.pc-toast');
    if (!box) { box = document.createElement('div'); box.className = 'pc-toast'; document.body.append(box); }
    box.textContent = text;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => box.remove(), 4200);
  }

  function windowBox(title, body) {
    desk.querySelector('.pc-win')?.remove();
    const box = document.createElement('div');
    box.className = 'pc-win';
    box.innerHTML = `<div class="title"><span>${esc(title)}</span><button type="button" aria-label="Fermer">✕</button></div><div class="content">${body}</div>`;
    box.querySelector('.title button').onclick = () => box.remove();
    desk.append(box);
    return box;
  }

  const ports = () => Object.keys(state.node.interfaces);
  const label = port => (state.device.port_names || {})[port] || port;

  function ipConfig(port = ports()[0]) {
    const n = state.node, address = n.interfaces[port] || '', dhcp = (n.dhcp_clients || []).includes(port);
    const [ip, prefix] = address ? address.split('/') : ['', ''];
    const box = windowBox('Configuration IP', `
      ${ports().length > 1 ? `<div class="pc-row"><label>Interface</label><select id="pcPort">${ports().map(p =>
        `<option value="${esc(p)}"${p === port ? ' selected' : ''}>${esc(label(p))}</option>`).join('')}</select></div>` : ''}
      <fieldset><legend>Configuration IPv4 · ${esc(label(port))}</legend>
        <div class="pc-radio"><label><input type="radio" name="pcMode" value="dhcp"${dhcp ? ' checked' : ''}>DHCP</label>
          <label><input type="radio" name="pcMode" value="static"${dhcp ? '' : ' checked'}>Statique</label></div>
        <div class="pc-row"><label>Adresse IPv4</label><input id="pcIp" value="${esc(ip)}" placeholder="192.168.1.10"></div>
        <div class="pc-row"><label>Masque de sous-réseau</label><input id="pcMask" value="${esc(prefix ? prefixToMask(Number(prefix)) : '255.255.255.0')}"></div>
        <div class="pc-row"><label>Passerelle par défaut</label><input id="pcGw" value="${esc(dhcp ? '' : n.gateway || '')}" placeholder="192.168.1.1"></div>
        <div class="pc-row"><label>Serveur DNS</label><input id="pcDns" value="${esc((n.resolvers || [])[0] || '')}" placeholder="10.0.0.53"></div>
      </fieldset>
      <div class="pc-note">Appliqué au projet ; lab en marche, aussi au poste réel (ip addr / ip route dans sa console). DHCP : au prochain
        ▶ Démarrer, le bail arrive au démarrage du poste.</div>
      <div class="pc-acts"><button type="button" class="cancel">Annuler</button><button type="button" class="ok">Appliquer</button></div>
      <div class="pc-msg"></div>`);
    const fields = () => ['pcIp', 'pcMask', 'pcGw', 'pcDns'].map(id => box.querySelector('#' + id));
    const sync = () => { const off = box.querySelector('input[name=pcMode]:checked').value === 'dhcp'; fields().forEach(f => { f.disabled = off; }); };
    box.querySelectorAll('input[name=pcMode]').forEach(radio => { radio.onchange = sync; });
    sync();
    box.querySelector('#pcPort')?.addEventListener('change', event => ipConfig(event.target.value));
    box.querySelector('.cancel').onclick = () => box.remove();
    const ok = box.querySelector('.ok'), msg = box.querySelector('.pc-msg');
    ok.onclick = async () => {
      const mode = box.querySelector('input[name=pcMode]:checked').value;
      let addressText = '';
      if (mode === 'static') {
        const prefixValue = maskToPrefix(box.querySelector('#pcMask').value);
        if (prefixValue === null) { msg.textContent = 'Masque invalide (ex. 255.255.255.0).'; msg.classList.add('bad'); return; }
        addressText = box.querySelector('#pcIp').value.trim() + '/' + prefixValue;
      }
      ok.disabled = true;
      try {
        state = await request('/api/host_ip', {node, revision: state.revision, port, mode, address: addressText,
          gateway: mode === 'static' ? box.querySelector('#pcGw').value.trim() : '',
          ...(state.node.runtime === 'firecracker' ? {dns: mode === 'static' ? box.querySelector('#pcDns').value.trim() : ''} : {})});
        render();
        const done = mode === 'dhcp' ? `${label(port)} : DHCP` : `${label(port)} : ${addressText}`;
        toast(typeof state.ip_live === 'string' ? `${done} — projet ; poste en marche : ${state.ip_live}.` : `${done} — appliqué au projet.`);
      } catch (error) { msg.textContent = error.message; msg.classList.add('bad'); ok.disabled = false; }
    };
  }

  function info() {
    const n = state.node, lines = [`Configuration IP de ${n.name}`, ''];
    for (const port of ports()) {
      const address = n.interfaces[port], dhcp = (n.dhcp_clients || []).includes(port);
      const cabled = state.device.ports.find(p => p.port === port)?.peer;
      lines.push(`Carte Ethernet ${label(port)} :`, '');
      lines.push(`   État du média . . . . . . . . . . : ${cabled ? 'Média connecté (' + cabled + ')' : 'Média déconnecté'}`);
      lines.push(`   DHCP activé . . . . . . . . . . . : ${dhcp ? 'Oui' : 'Non'}`);
      if (address) {
        lines.push(`   Adresse IPv4. . . . . . . . . . . : ${address.split('/')[0]}`);
        lines.push(`   Masque de sous-réseau . . . . . . : ${prefixToMask(Number(address.split('/')[1]))}`);
      } else {
        lines.push(`   Adresse IPv4. . . . . . . . . . . : ${dhcp ? '(bail du serveur DHCP au démarrage)' : '(aucune)'}`);
      }
      lines.push(`   Passerelle par défaut . . . . . . : ${dhcp ? '(du bail DHCP)' : n.gateway || ''}`, '');
    }
    windowBox('Informations réseau', `<pre class="pc-pre">${esc(lines.join('\n'))}</pre>
      <div class="pc-note" style="margin-top:10px">Configuration du projet. Lab en marche : « ipconfig /all » dans l’invite de commandes lit le poste réel.</div>`);
  }

  // ---- the web browser: pages of the laboratory's servers, fetched from this device ----
  let history = [];
  function browser(start = '') {
    const box = windowBox('Navigateur web', `<div class="pc-url"><button type="button" class="back" title="Précédente">←</button>
      <input id="pcUrl" value="${esc(start || 'http://')}" spellcheck="false"><button type="button" class="go">Aller</button></div>
      <div class="pc-view"><div class="pc-error"><h3>Navigateur web</h3>Taper l’adresse d’un serveur du laboratoire (http://10.0.0.10 ou
      http://www.lab.local) : la page vient du réseau du laboratoire, depuis ${esc(state.node.name)}.</div></div><div class="pc-status"></div>`);
    box.classList.add('wide');
    const field = box.querySelector('#pcUrl'), view = box.querySelector('.pc-view'), status = box.querySelector('.pc-status');
    const go = async (url, remember = true) => {
      url = url.trim();
      if (!url || url === 'http://') return;
      field.value = url;
      status.textContent = 'Connexion à ' + url + '…';
      let page;
      try { page = await request('/api/browse', {node, url}); }
      catch (error) { status.textContent = error.message; return; }
      if (remember) history.push(url);
      if (page.error) {
        view.innerHTML = `<div class="pc-error"><h3>Page inaccessible</h3>${esc(page.error)}</div>`;
        status.textContent = 'Échec : ' + url;
        return;
      }
      const frame = document.createElement('iframe');
      frame.className = 'pc-page';
      frame.setAttribute('sandbox', 'allow-same-origin');  // the server's page, without its scripts
      frame.srcdoc = page.body;
      view.replaceChildren(frame);
      status.textContent = `HTTP ${page.status} ${page.reason} · ${url}`;
      frame.onload = () => {
        const base = url.replace(/^(http:\/\/)?([^/]+).*$/, 'http://$2');
        frame.contentDocument?.querySelectorAll('a[href]').forEach(a => {
          a.addEventListener('click', event => {
            event.preventDefault();
            const href = a.getAttribute('href');
            go(/^http:\/\//.test(href) ? href : base + '/' + href.replace(/^\//, ''));
          });
        });
      };
    };
    box.querySelector('.go').onclick = () => go(field.value);
    field.addEventListener('keydown', event => { if (event.key === 'Enter') go(field.value); });
    box.querySelector('.back').onclick = () => { if (history.length > 1) { history.pop(); go(history[history.length - 1], false); } };
    field.focus();
    if (start) go(start);
  }

  // ---- a server's services, as Packet Tracer's Services tab ----
  const SERVICE_TABS = [['http', 'HTTP'], ['dns', 'DNS'], ['ntp', 'NTP'], ['syslog', 'SYSLOG']];
  function services(tab = 'http') {
    const held = JSON.parse(JSON.stringify(state.node.services || {}));
    for (const [key] of SERVICE_TABS) held[key] = held[key] || {on: false};
    held.dns.records = held.dns.records || [];
    if (!state.node.services) held.http = {on: true, pages: {'index.html': `<html>\n<body>\n<h1>${state.node.name}</h1>\n</body>\n</html>\n`}};
    held.http.pages = held.http.pages || {};
    const box = windowBox('Services', `<div class="sv"><nav class="sv-tabs">${SERVICE_TABS.map(([key, title]) => `<a data-t="${key}">${title}</a>`).join('')}</nav>
      <div class="sv-body"></div></div><div class="sv-foot"><span class="pc-msg"></span><span class="grow"></span>
      <button type="button" class="cancel">Fermer</button><button type="button" class="ok save">Enregistrer</button></div>`);
    box.classList.add('wide');
    const body = box.querySelector('.sv-body'), msg = box.querySelector('.pc-msg');
    const onoff = key => `<div class="sv-onoff"><b>${key.toUpperCase()}</b><label><input type="radio" name="sv-on" value="1"${held[key].on ? ' checked' : ''}> Activé</label>
      <label><input type="radio" name="sv-on" value="0"${held[key].on ? '' : ' checked'}> Désactivé</label></div>`;
    const wireOnoff = key => body.querySelectorAll('input[name=sv-on]').forEach(r => { r.onchange = () => { held[key].on = r.value === '1'; }; });
    const show = key => {
      box.querySelectorAll('.sv-tabs a').forEach(a => a.classList.toggle('on', a.dataset.t === key));
      if (key === 'http') {
        const names = Object.keys(held.http.pages);
        let chosen = names[0] || null;
        body.innerHTML = `<h3>HTTP</h3>${onoff('http')}<table class="sv-t"><thead><tr><th>Fichier</th><th>Taille</th></tr></thead><tbody>${names.map(name =>
          `<tr data-p="${esc(name)}"><td>${esc(name)}</td><td>${new Blob([held.http.pages[name]]).size} o</td></tr>`).join('') ||
          '<tr><td colspan="2">Aucune page</td></tr>'}</tbody></table>
          <div class="sv-btns"><input id="svNew" placeholder="nouvelle-page.html" style="border:1px solid #c9d6e3;border-radius:7px;padding:6px 9px">
          <button type="button" class="new">Nouveau</button><button type="button" class="del">Supprimer</button></div>
          <textarea id="svText" spellcheck="false"></textarea>`;
        wireOnoff('http');
        const text = body.querySelector('#svText');
        const pick = name => {
          chosen = name;
          body.querySelectorAll('tr[data-p]').forEach(row => row.classList.toggle('sel', row.dataset.p === name));
          text.value = name ? held.http.pages[name] : '';
          text.disabled = !name;
        };
        body.querySelectorAll('tr[data-p]').forEach(row => { row.onclick = () => pick(row.dataset.p); });
        text.oninput = () => { if (chosen) held.http.pages[chosen] = text.value; };
        body.querySelector('.new').onclick = () => {
          const name = body.querySelector('#svNew').value.trim().toLowerCase();
          if (!/^[a-z0-9_-]{1,35}\.(html|htm|txt|css)$/.test(name)) { msg.textContent = 'Nom de page : page.html, .htm, .txt ou .css.'; msg.classList.add('bad'); return; }
          held.http.pages[name] = held.http.pages[name] || '<html>\n<body>\n\n</body>\n</html>\n';
          show('http'); pick(name);
        };
        body.querySelector('.del').onclick = () => { if (chosen) { delete held.http.pages[chosen]; show('http'); } };
        pick(chosen);
      } else if (key === 'dns') {
        let chosen = -1;
        body.innerHTML = `<h3>DNS</h3>${onoff('dns')}<div class="sv-grid"><label>Nom</label><input id="svName" placeholder="www.lab.local">
          <label>Type</label><select id="svType"><option value="A">A Record</option><option value="CNAME">CNAME</option></select>
          <label id="svValueLabel">Adresse</label><input id="svValue" placeholder="10.0.0.10"></div>
          <div class="sv-btns"><button type="button" class="add">Ajouter</button><button type="button" class="edit">Enregistrer</button>
          <button type="button" class="del">Supprimer</button></div><table class="sv-t"><thead><tr><th>N°</th><th>Nom</th><th>Type</th><th>Détails</th></tr></thead>
          <tbody>${held.dns.records.map(([name, kind, value], i) => `<tr data-i="${i}"><td>${i}</td><td>${esc(name)}</td><td>${kind === 'A' ? 'A Record' : 'CNAME'}</td>
          <td>${esc(value)}</td></tr>`).join('') || '<tr><td colspan="4">Aucun enregistrement</td></tr>'}</tbody></table>`;
        wireOnoff('dns');
        const kind = body.querySelector('#svType');
        kind.onchange = () => { body.querySelector('#svValueLabel').textContent = kind.value === 'A' ? 'Adresse' : 'Nom canonique'; };
        const read = () => [body.querySelector('#svName').value.trim().toLowerCase(), kind.value, body.querySelector('#svValue').value.trim().toLowerCase()];
        body.querySelectorAll('tr[data-i]').forEach(row => { row.onclick = () => {
          chosen = Number(row.dataset.i);
          const [name, k, value] = held.dns.records[chosen];
          body.querySelector('#svName').value = name; kind.value = k; body.querySelector('#svValue').value = value; kind.onchange();
          body.querySelectorAll('tr[data-i]').forEach(r => r.classList.toggle('sel', r === row));
        }; });
        body.querySelector('.add').onclick = () => { const r = read(); if (r[0] && r[2]) { held.dns.records.push(r); show('dns'); } };
        body.querySelector('.edit').onclick = () => { const r = read(); if (chosen >= 0 && r[0] && r[2]) { held.dns.records[chosen] = r; show('dns'); } };
        body.querySelector('.del').onclick = () => { if (chosen >= 0) { held.dns.records.splice(chosen, 1); show('dns'); } };
      } else if (key === 'ntp') {
        body.innerHTML = `<h3>NTP</h3>${onoff('ntp')}<p class="pc-note">Le serveur donne l’heure de son horloge (strate 1, référence LOCL) : les routeurs
          et switches s’y synchronisent avec « ntp server ${esc((Object.values(state.node.interfaces).find(Boolean) || 'A.B.C.D').split('/')[0])} »
          (show ntp status, show clock sans « * »).</p>`;
        wireOnoff('ntp');
      } else {
        body.innerHTML = `<h3>SYSLOG</h3>${onoff('syslog')}<table class="sv-t"><thead><tr><th>N°</th><th>Heure</th><th>Équipement</th><th>Message</th></tr></thead>
          <tbody class="logs"><tr><td colspan="4">…</td></tr></tbody></table><div class="sv-btns"><button type="button" class="refresh">↻ Actualiser</button></div>`;
        wireOnoff('syslog');
        const fill = async () => {
          const rows = body.querySelector('.logs');
          try {
            const read = await request('/api/syslog', {node});
            rows.innerHTML = read.messages.map((m, i) => `<tr><td>${i + 1}</td><td>${esc(m.time)}</td><td>${esc(m.source)}</td><td>${esc(m.message)}</td></tr>`).join('')
              || `<tr><td colspan="4">${read.running ? 'Aucun message reçu.' : 'Lab arrêté : les messages arrivent quand le lab est en marche.'}</td></tr>`;
          } catch (error) { rows.innerHTML = `<tr><td colspan="4">${esc(error.message)}</td></tr>`; }
        };
        body.querySelector('.refresh').onclick = fill;
        fill();
      }
    };
    box.querySelectorAll('.sv-tabs a').forEach(a => { a.onclick = () => show(a.dataset.t); });
    box.querySelector('.cancel').onclick = () => box.remove();
    box.querySelector('.save').onclick = async () => {
      msg.classList.remove('bad');
      try {
        state = await request('/api/services', {node, revision: state.revision, services: held});
        render();
        msg.textContent = state.observed === 'running' ? 'Enregistré dans le projet ; ⚡ Appliquer au lab en marche (onglet CLI) ou redémarrer.'
          : 'Enregistré dans le projet (actif au ▶ Démarrer).';
      } catch (error) { msg.textContent = error.message; msg.classList.add('bad'); }
    };
    show(tab);
  }

  async function prompt() {
    try { await request('/api/open_cli', {node}); toast('Invite de commandes ouverte dans Network LABS.'); }
    catch (error) { toast(error.message); }
  }

  function clock() {
    const now = new Date();
    return `${now.toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'})}<br>${now.toLocaleDateString('fr-FR')}`;
  }

  function draw() {
    const n = state.node, d = state.device, running = state.observed === 'running';
    const open = desk && desk.querySelector('.pc-win');
    const app = document.querySelector('.pc-app') || document.createElement('div');
    app.className = 'pc-app';
    app.innerHTML = `<div class="pc-desk"></div><div class="pc-bar"><b>${esc(n.name)}</b><span class="sub">${esc(d.brand)} · ${esc(d.model)}</span>
      <span class="pc-pill"><i class="${running ? 'on' : ''}"></i>${running ? 'En marche' : 'Lab arrêté'}</span><span class="grow"></span>
      <button type="button" class="simple">◐ Design Studio</button><button type="button" class="std">Vue Network LABS</button>
      <button type="button" class="ref">↻</button><span class="pc-clock">${clock()}</span></div>`;
    desk = app.querySelector('.pc-desk');
    const server = state.device.server || state.node.services;  // Packet Tracer's Server: a Services tab
    for (const [id, title, colour, glyph, later] of APPS.filter(([id]) => id !== 'services' || server)) {
      const icon = document.createElement('button');
      icon.type = 'button';
      icon.className = 'pc-icon' + (later ? ' off' : '');
      icon.title = later || title;
      icon.innerHTML = `<span class="pc-glyph" style="background:${colour}">${glyph}</span><span>${esc(title)}</span>`;
      icon.onclick = () => later ? toast(title + ' — ' + later) : ({ip: () => ipConfig(), cmd: prompt, info, web: () => browser(), services: () => services()})[id]();
      desk.append(icon);
    }
    if (open) desk.append(open);
    app.querySelector('.std').onclick = () => { standard = true; document.body.classList.remove('pc'); app.remove(); render(); };
    app.querySelector('.ref').onclick = () => load();
    app.querySelector('.simple').onclick = () => window.nlSetDesign && window.nlSetDesign('studio');
    if (!app.isConnected) document.body.append(app);
  }

  const previous = render;
  render = function () {
    previous();
    if (window.nlDesignNow && window.nlDesignNow() !== 'vendor') { document.querySelector('.pc-app')?.remove(); document.body.classList.remove('pc'); return; }
    if (window.nlProduct && state && state.device && window.nlProduct(state.device)) { document.querySelector('.pc-app')?.remove(); document.body.classList.remove('pc'); return; }  // its own product page
    if (!state || !state.node || state.node.role !== 'host' || standard) return;
    document.body.classList.add('pc');
    draw();
  };
  window.pcDesktop = {ipConfig, info, browser, services};
})();
