/* A PC's or server's desktop, as Packet Tracer's « Desktop » tab: app tiles on a wallpaper and a taskbar, in a neutral
 * Network LABS look (no vendor logo or assets). « Configuration IP » sets DHCP or a static address, mask and gateway in
 * the project (/api/host_ip); « Invite de commandes » opens the device's terminal in the application (/api/open_cli);
 * « Informations réseau » shows what ipconfig /all would, from the project. */
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
  .pc-toast{position:fixed;left:50%;bottom:64px;transform:translateX(-50%);background:rgba(9,22,36,.92);color:#fff;padding:10px 16px;border-radius:10px;
    box-shadow:0 8px 24px rgba(0,0,0,.35);font-size:12.5px;z-index:9}
  `;
  document.head.appendChild(css);

  const svg = path => `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${path}</svg>`;
  const APPS = [
    ['ip', 'Configuration IP', '#1f7ae0', svg('<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4M7 9h4M7 12h7"/>')],
    ['cmd', 'Invite de commandes', '#22313f', svg('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 10l3 2-3 2M12 15h5"/>')],
    ['info', 'Informations réseau', '#0f9d8a', svg('<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v5h1"/>')],
    ['web', 'Navigateur web', '#6b55d3', svg('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18"/>'),
      'Bientôt : les pages des serveurs du laboratoire.'],
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
        <div class="pc-row"><label>Serveur DNS</label><input disabled placeholder="non géré par le laboratoire"></div>
      </fieldset>
      <div class="pc-note">Appliqué au projet ; lab en marche, aussi au poste réel (ip addr / ip route dans sa console). DHCP : au prochain
        ▶ Démarrer, le bail arrive au démarrage du poste.</div>
      <div class="pc-acts"><button type="button" class="cancel">Annuler</button><button type="button" class="ok">Appliquer</button></div>
      <div class="pc-msg"></div>`);
    const fields = () => ['pcIp', 'pcMask', 'pcGw'].map(id => box.querySelector('#' + id));
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
          gateway: mode === 'static' ? box.querySelector('#pcGw').value.trim() : ''});
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
    for (const [id, title, colour, glyph, later] of APPS) {
      const icon = document.createElement('button');
      icon.type = 'button';
      icon.className = 'pc-icon' + (later ? ' off' : '');
      icon.title = later || title;
      icon.innerHTML = `<span class="pc-glyph" style="background:${colour}">${glyph}</span><span>${esc(title)}</span>`;
      icon.onclick = () => later ? toast(title + ' — ' + later) : ({ip: () => ipConfig(), cmd: prompt, info})[id]();
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
  window.pcDesktop = {ipConfig, info};
})();
