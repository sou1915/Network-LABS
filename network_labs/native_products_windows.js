/* A Windows PC or server, as its owner sees it (engine: native_products.js). Two shells: Windows 11 (centred taskbar,
 * Start, quick settings, the Settings app, Windows Terminal) and Windows 10 / Windows Server 2022 (taskbar on the left
 * with its search box, Windows 10 Settings, Server Manager opening on a server). Both have the dialogs every Windows
 * user knows: Panneau de configuration › Centre Réseau et partage › Connexions réseau, État / Détails / Propriétés de
 * Ethernet and « Propriétés de : Protocole Internet version 4 (TCP/IPv4) ». Windows are moved by their title bar.
 * Every change goes to the project as on the other pages (/api/host_ip, /api/apply). Layout, words and workflows are
 * Windows'; icons and wallpaper are drawn here (no Microsoft logo, artwork or font). */
'use strict';
(() => {
  const K = window.nlProductsKit;
  if (!K) return;
  const {SKINS, D, N, h, maskOf, prefixOf, lenOf, validIp, running, toast, send, rename, openTerminal, skinCss} = K;
  const V = () => K.view;
  const windows = (d, role) => role === 'host' && d.brand === 'Microsoft';
  K.MATCH.push([(d, role) => windows(d, role) && /Windows 11/.test(d.model), 'win11']);
  K.MATCH.push([(d, role) => windows(d, role), 'win10']);  // Windows 10 and Windows Server 2022: the Windows 10 shell
  const W11 = () => V().skin === 'win11';
  const SERVER = () => /Server/.test(D().model);

  // ---- the machine, as Windows names it ----
  const ports = () => Object.keys(N().interfaces);
  const nic = port => (ports().indexOf(port) <= 0 ? 'Ethernet' : `Ethernet ${ports().indexOf(port) + 1}`);
  const devPort = port => D().ports.find(p => p.port === port) || {};
  const disabled = port => (N().shutdown || []).includes(port);
  const cabled = port => Boolean(devPort(port).peer) && !disabled(port);
  const dhcp = port => (N().dhcp_clients || []).includes(port);
  const address = port => N().interfaces[port] || '';
  const ip = port => address(port).split('/')[0];
  const mask = port => (address(port) ? maskOf(lenOf(address(port))) : '');
  const gateway = () => N().gateway || '';
  const mac = port => {
    let hash = 0;
    for (const c of N().name + port) hash = (hash * 31 + c.charCodeAt(0)) >>> 0;
    return ['52', '54', '00', ...[16, 8, 0].map(s => ((hash >> s) & 255).toString(16).padStart(2, '0'))].join('-').toUpperCase();
  };
  const ADAPTER = 'Carte Ethernet VirtIO';
  const access = port => (!cabled(port) ? 'Pas d’accès réseau' : gateway() || dhcp(port) ? 'Internet' : 'Pas d’accès Internet');

  async function saveIp(port, mode, ipText, maskText, gw) {
    let cidr = '';
    if (mode === 'static') {
      const prefix = String(maskText).includes('.') ? prefixOf(maskText) : Number(maskText);
      if (!validIp(ipText)) throw new Error('L’adresse IP entrée n’est pas valide.');
      if (prefix === null || !(prefix >= 1 && prefix <= 32)) throw new Error('Le masque de sous-réseau entré n’est pas valide.');
      if (gw && !validIp(gw)) throw new Error('La passerelle par défaut entrée n’est pas valide.');
      cidr = `${ipText}/${prefix}`;
    }
    await send('/api/host_ip', {port, mode, address: cidr, gateway: mode === 'static' ? gw : ''});
    toast(`${nic(port)} : ${mode === 'dhcp' ? 'DHCP' : cidr} enregistré` + (typeof state.ip_live === 'string' ? ` · poste en marche : ${state.ip_live}.` : '.'));
  }
  async function setEnabled(port, enabled) {
    await send('/api/apply', {name: N().name, port, address: address(port), gateway: gateway(), enabled});
  }
  const later = what => toast(`${what} : pas relié au laboratoire.`, true);

  // Fluent UI System Icons (Microsoft, MIT License; native_windows_icons.js): the icon family Windows 11 is drawn with.
  const FX = (name, size = 20, colour = '') => {
    const [box, body] = (window.nlFluent || {})[name] || [20, ''];
    return `<svg viewBox="0 0 ${box} ${box}" width="${size}" height="${size}" fill="${name.endsWith(':c') ? 'none' : 'currentColor'}"${colour ? ` style="color:${colour}"` : ''
    } aria-hidden="true">${body}</svg>`;
  };

  // ---- drawn icons (no Microsoft artwork) ----
  const svg = (body, size = 24, box = 24) => `<svg viewBox="0 0 ${box} ${box}" width="${size}" height="${size}" aria-hidden="true">${body}</svg>`;
  const ICON = {
    start: (s, c = '#2b88d8') => svg([3, 9.5, 16].map(y => [3, 9.5, 16].map(x => `<rect x="${x}" y="${y}" width="5" height="5" rx="1.3" fill="${c}"/>`).join('')).join(''), s),
    search: s => FX('search', s),
    settings: s => FX('settings:c', s),
    explorer: s => svg('<defs><linearGradient id="wnG2" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffd86b"/><stop offset="1" stop-color="#f5b43a"/></linearGradient></defs><path d="M2.5 6a1.5 1.5 0 0 1 1.5-1.5h5.2l2 2.2H20a1.5 1.5 0 0 1 1.5 1.5V10h-19z" fill="#e39f2b"/><rect x="2.5" y="8.6" width="19" height="11.4" rx="1.6" fill="url(#wnG2)"/><rect x="2.5" y="8.6" width="19" height="2" rx="1" fill="#3a8fe0"/>', s),
    terminal: s => svg('<defs><linearGradient id="wnG3" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4a4a4a"/><stop offset="1" stop-color="#1f1f1f"/></linearGradient></defs><rect x="2" y="3.5" width="20" height="17" rx="3" fill="url(#wnG3)"/><rect x="2.5" y="4" width="19" height="16" rx="2.6" fill="none" stroke="#7a7a7a" stroke-width=".6"/><path d="M6.2 9.2l3.2 2.6-3.2 2.6" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/><path d="M11.4 15.2h6" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/>', s),
    cmd: s => svg('<rect x="2" y="3.5" width="20" height="17" rx="1" fill="#1b1b1b"/><rect x="2" y="3.5" width="20" height="3" fill="#4a4a4a"/><text x="4.2" y="15.5" font-size="6.5" font-family="monospace" fill="#fff">C:\\</text>', s),
    cpl: s => svg('<rect x="2.5" y="3.5" width="19" height="15" rx="1.5" fill="#3d8fd6"/><rect x="4.5" y="6" width="6" height="3" fill="#bfe1ff"/><rect x="12" y="6" width="7.5" height="3" fill="#fff"/><rect x="4.5" y="11" width="15" height="2" fill="#fff"/><rect x="4.5" y="14.5" width="10" height="2" fill="#fff"/><rect x="8" y="19" width="8" height="2" fill="#7a8796"/>', s),
    notepad: s => FX('document:c', s),
    calc: s => svg('<rect x="4" y="2.5" width="16" height="19" rx="2" fill="#4a5563"/><rect x="6.5" y="5" width="11" height="4" fill="#d9e2ea"/>' + [0, 1, 2].map(r => [0, 1, 2].map(c => `<rect x="${6.5 + c * 4}" y="${11 + r * 3.4}" width="3" height="2.4" fill="#cfd8e1"/>`).join('')).join(''), s),
    taskmgr: s => FX('data_area:c', s),
    pc: s => svg('<defs><linearGradient id="wnG4" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4fb3ff"/><stop offset="1" stop-color="#0b5cad"/></linearGradient></defs><rect x="2" y="3.2" width="20" height="13.4" rx="1.4" fill="#c9d3dd"/><rect x="3.2" y="4.4" width="17.6" height="11" rx=".6" fill="url(#wnG4)"/><path d="M3.2 12.5 20.8 6.8V4.4H3.2z" fill="#fff" opacity=".12"/><path d="M9.5 16.6h5l.6 2.6h-6.2z" fill="#a9b4bf"/><rect x="6.6" y="19" width="10.8" height="1.6" rx=".8" fill="#8995a1"/>', s),
    bin: s => svg('<path d="M5.6 7.2h12.8l-1.3 13.1a1.6 1.6 0 0 1-1.6 1.4H8.5a1.6 1.6 0 0 1-1.6-1.4z" fill="#e9f1f8" fill-opacity=".85" stroke="#7d8d9e" stroke-width=".9"/><path d="M8.6 9.4l.6 10M12 9.4v10M15.4 9.4l-.6 10" stroke="#a8b6c4" stroke-width=".9"/><rect x="4.6" y="4.8" width="14.8" height="2.6" rx="1" fill="#dce5ee" stroke="#7d8d9e" stroke-width=".9"/>', s),
    network: s => svg('<defs><linearGradient id="wnG5" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4fb3ff"/><stop offset="1" stop-color="#0b5cad"/></linearGradient></defs><rect x="2" y="3.2" width="16" height="11" rx="1.2" fill="#c9d3dd"/><rect x="3" y="4.2" width="14" height="9" rx=".5" fill="url(#wnG5)"/><path d="M8 14.2h4l.5 2h-5z" fill="#a9b4bf"/><circle cx="17" cy="16.4" r="5" fill="#2f9e5f"/><path d="M12 16.4h10M17 11.4c1.6 1.6 1.6 8.4 0 10M17 11.4c-1.6 1.6-1.6 8.4 0 10" fill="none" stroke="#d9f5e4" stroke-width=".8"/>', s),
    ethernet: s => svg('<rect x="3" y="4" width="18" height="12" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 20h8M12 16v4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="M9 9h6v4H9z" fill="currentColor"/>', s),
    offline: s => FX('globe_prohibited', s),
    speaker: s => FX('speaker_2', s),
    bell: s => FX('alert', s),
    power: s => FX('power', s),
    adapter: (s, state) => svg(`<rect x="6" y="5" width="26" height="18" rx="1.5" fill="#3b87d6"/><rect x="8" y="7" width="22" height="14" fill="#8fd0ff"/><rect x="15" y="24" width="8" height="3" fill="#7a8796"/><rect x="11" y="27" width="16" height="2.5" rx="1" fill="#7a8796"/><path d="M19 30v6M14 36h10" stroke="#556372" stroke-width="2"/>${
      state === 'off' ? '<circle cx="33" cy="33" r="6.5" fill="#d13438"/><path d="M30 30l6 6M36 30l-6 6" stroke="#fff" stroke-width="2"/>'
        : state === 'disabled' ? '<rect x="0" y="0" width="40" height="40" fill="#fff" opacity=".55"/>' : '<circle cx="33" cy="33" r="6.5" fill="#16a34a"/><path d="M30 33.2l2.2 2.2 4-4.4" fill="none" stroke="#fff" stroke-width="2"/>'}`, s, 40),
    server: s => svg('<rect x="4" y="2.5" width="16" height="6" rx="1" fill="#4b6584"/><rect x="4" y="9.5" width="16" height="6" rx="1" fill="#4b6584"/><rect x="4" y="16.5" width="16" height="5" rx="1" fill="#4b6584"/><circle cx="7" cy="5.5" r="1" fill="#7ee08a"/><circle cx="7" cy="12.5" r="1" fill="#7ee08a"/><circle cx="7" cy="19" r="1" fill="#7ee08a"/>', s),
    user: s => svg('<circle cx="12" cy="12" r="11" fill="#cfd8e3"/><circle cx="12" cy="9.5" r="4" fill="#fff"/><path d="M4.8 19.2a8 8 0 0 1 14.4 0" fill="#fff"/>', s),
  };

  // Settings' own icons, Fluent-style (drawn here): the categories in colour, the rows in outline.
  const FL = {
    home: '<path d="M3.5 9.2 10 3.8l6.5 5.4V16a1 1 0 0 1-1 1h-3.3v-4.5H7.8V17H4.5a1 1 0 0 1-1-1z" fill="#cfe4fb" stroke="#0067c0" stroke-width="1.3" stroke-linejoin="round"/>',
    system: '<rect x="2.5" y="3.5" width="15" height="10" rx="1.5" fill="#cfe4fb" stroke="#0067c0" stroke-width="1.3"/><path d="M7 16.5h6M10 13.5v3" stroke="#0067c0" stroke-width="1.3" stroke-linecap="round"/>',
    bt: '<path d="M6 6.5l8 7-4 3.5V3l4 3.5-8 7" fill="none" stroke="#0067c0" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>',
    network: '<path d="M10 2.8 17.2 10 10 17.2 2.8 10z" fill="#cfe4fb" stroke="#0067c0" stroke-width="1.3" stroke-linejoin="round"/><path d="M6.6 10h6.8M10 6.6v6.8" stroke="#0067c0" stroke-width="1.2"/>',
    perso: '<path d="M13.8 3.3a1.6 1.6 0 0 1 2.3 2.3l-6.8 6.8-3-.7-.7-3z" fill="#f3b046" stroke="#9a5d00" stroke-width="1"/><path d="M5.2 13.2c-1.4.2-2.2 1.3-2.2 3.3 2 .1 3.6-.6 4.2-2.3z" fill="#0067c0"/>',
    apps: '<rect x="3" y="3" width="6" height="6" rx="1.2" fill="#0067c0"/><rect x="3" y="11" width="6" height="6" rx="1.2" fill="#0067c0"/><rect x="11" y="11" width="6" height="6" rx="1.2" fill="#0067c0"/><rect x="11.2" y="2.4" width="5.6" height="5.6" rx="1.2" fill="#4cc2ff" transform="rotate(45 14 5.2)"/>',
    accounts: '<circle cx="10" cy="6.8" r="3.3" fill="#9bd27c" stroke="#2f7a1a" stroke-width="1"/><path d="M3.8 17c.4-3.3 3-5 6.2-5s5.8 1.7 6.2 5z" fill="#9bd27c" stroke="#2f7a1a" stroke-width="1"/>',
    time: '<circle cx="10" cy="10" r="7" fill="#cfe4fb" stroke="#0067c0" stroke-width="1.3"/><path d="M10 6v4.3l2.8 1.7" fill="none" stroke="#0067c0" stroke-width="1.4" stroke-linecap="round"/>',
    games: '<path d="M5.2 6.5h9.6a3 3 0 0 1 2.9 2.3l.9 4a2 2 0 0 1-3.5 1.6l-1.4-1.7H6.3l-1.4 1.7a2 2 0 0 1-3.5-1.6l.9-4a3 3 0 0 1 2.9-2.3z" fill="#e3e7ec" stroke="#5b6570" stroke-width="1.1"/><path d="M6.4 8.6v2.4M5.2 9.8h2.4" stroke="#5b6570" stroke-width="1.1"/><circle cx="13.6" cy="9.4" r=".8" fill="#5b6570"/>',
    access: '<circle cx="10" cy="10" r="7.3" fill="#cfe4fb" stroke="#0067c0" stroke-width="1.2"/><circle cx="10" cy="6.4" r="1.3" fill="#0067c0"/><path d="M6.4 8.6h7.2M10 8.6v3.2l-2 3.4M10 11.8l2 3.4" fill="none" stroke="#0067c0" stroke-width="1.2" stroke-linecap="round"/>',
    privacy: '<path d="M10 2.6 16 5v4.6c0 3.8-2.6 6.4-6 7.8-3.4-1.4-6-4-6-7.8V5z" fill="#e3e7ec" stroke="#5b6570" stroke-width="1.2" stroke-linejoin="round"/>',
    update: '<path d="M15.6 8.2A5.8 5.8 0 0 0 5 6.4M4.4 11.8A5.8 5.8 0 0 0 15 13.6" fill="none" stroke="#0067c0" stroke-width="1.5" stroke-linecap="round"/><path d="M4.4 3.6 5 6.6l3-.6M15.6 16.4 15 13.4l-3 .6" fill="none" stroke="#0067c0" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
    profile: '<path d="M10 2.8 16 5.2v4.4c0 3.7-2.6 6.2-6 7.6-3.4-1.4-6-3.9-6-7.6V5.2z" fill="none" stroke="#1b1b1b" stroke-width="1.1"/><path d="M7.3 9.9l1.9 1.9 3.6-3.8" fill="none" stroke="#1b1b1b" stroke-width="1.1" stroke-linecap="round"/>',
    auth: '<circle cx="7" cy="12.5" r="3.2" fill="none" stroke="#1b1b1b" stroke-width="1.1"/><path d="M9.3 10.2 16.5 3M13.8 5.7l1.8 1.8M12 7.5l1.6 1.6" fill="none" stroke="#1b1b1b" stroke-width="1.1" stroke-linecap="round"/>',
    metered: '<path d="M3.5 14a6.5 6.5 0 1 1 13 0" fill="none" stroke="#1b1b1b" stroke-width="1.1" stroke-linecap="round"/><path d="M10 14l3.4-4.2" stroke="#1b1b1b" stroke-width="1.2" stroke-linecap="round"/><circle cx="10" cy="14" r="1.1" fill="#1b1b1b"/>',
    ip: '<rect x="3" y="4" width="14" height="9.5" rx="1.3" fill="none" stroke="#1b1b1b" stroke-width="1.1"/><path d="M7.5 16.5h5M10 13.5v3M7 8.8h6" stroke="#1b1b1b" stroke-width="1.1" stroke-linecap="round"/>',
    dns: '<circle cx="10" cy="10" r="7" fill="none" stroke="#1b1b1b" stroke-width="1.1"/><path d="M3 10h14M10 3c2.2 2.2 2.2 11.8 0 14M10 3c-2.2 2.2-2.2 11.8 0 14" fill="none" stroke="#1b1b1b" stroke-width=".9"/>',
    info: '<circle cx="10" cy="10" r="7" fill="none" stroke="#1b1b1b" stroke-width="1.1"/><path d="M10 9v4.6" stroke="#1b1b1b" stroke-width="1.2" stroke-linecap="round"/><circle cx="10" cy="6.6" r=".9" fill="#1b1b1b"/>',
    vpn: '<path d="M10 2.8 16 5.2v4.4c0 3.7-2.6 6.2-6 7.6-3.4-1.4-6-3.9-6-7.6V5.2z" fill="none" stroke="#1b1b1b" stroke-width="1.1"/><rect x="7.4" y="9" width="5.2" height="4" rx=".6" fill="none" stroke="#1b1b1b" stroke-width="1"/><path d="M8.4 9V7.8a1.6 1.6 0 0 1 3.2 0V9" fill="none" stroke="#1b1b1b" stroke-width="1"/>',
    proxy: '<rect x="3" y="4" width="14" height="9.5" rx="1.3" fill="none" stroke="#1b1b1b" stroke-width="1.1"/><circle cx="10" cy="8.8" r="2.4" fill="none" stroke="#1b1b1b" stroke-width="1"/><path d="M7.5 16.5h5" stroke="#1b1b1b" stroke-width="1.1"/>',
    dial: '<path d="M5 3.5h2.4l1.2 3.3-1.6 1.2a8.5 8.5 0 0 0 5 5l1.2-1.6 3.3 1.2v2.4A1.5 1.5 0 0 1 15 16.5 11.5 11.5 0 0 1 3.5 5 1.5 1.5 0 0 1 5 3.5z" fill="none" stroke="#1b1b1b" stroke-width="1.1" stroke-linejoin="round"/>',
    advanced: '<rect x="3" y="4.5" width="9" height="6" rx="1" fill="none" stroke="#1b1b1b" stroke-width="1.1"/><rect x="8" y="9.5" width="9" height="6" rx="1" fill="#f9f9f9" stroke="#1b1b1b" stroke-width="1.1"/>',
    ethernet: '<rect x="3" y="3.5" width="14" height="9.5" rx="1.3" fill="none" stroke="#1b1b1b" stroke-width="1.1"/><path d="M7.5 16.5h5M10 13v3.5" stroke="#1b1b1b" stroke-width="1.1" stroke-linecap="round"/><rect x="7.6" y="6.4" width="4.8" height="3.6" rx=".4" fill="none" stroke="#1b1b1b" stroke-width="1"/>',
    usage: '<path d="M3.5 16.5h13M5.5 16.5V11M9 16.5V6.5M12.5 16.5V9M16 16.5V4" stroke="#1b1b1b" stroke-width="1.3" stroke-linecap="round"/>',
    rename: '<path d="M4 15.5 13.6 5.9a1.5 1.5 0 0 1 2.1 2.1L6.1 17.6H4z" fill="none" stroke="#1b1b1b" stroke-width="1.1" stroke-linejoin="round"/>',
  };
  // Settings' categories in colour and its rows in outline, from the Fluent set; the Ethernet glyph stays drawn here.
  const FLUENT_OF = {home: 'home:c', system: 'laptop:c', bt: ['bluetooth', '#0067c0'], network: 'wifi:c', perso: 'paint_brush:c', apps: 'apps:c',
    accounts: 'person:c', time: 'globe:c', games: 'game_chat:c', access: ['accessibility', '#0067c0'], privacy: 'shield:c', update: 'arrow_sync:c',
    profile: 'shield', auth: 'key', metered: 'data_usage', ip: 'desktop', dns: 'globe', info: 'info', vpn: 'shield_lock', proxy: 'router', dial: 'call',
    advanced: 'network_check', usage: 'data_usage', rename: 'rename'};
  const fl = (name, size = 20) => {
    const fluent = FLUENT_OF[name];
    if (!fluent || !window.nlFluent) return svg(FL[name] || FL.info, size, 20);
    const [icon, colour] = Array.isArray(fluent) ? fluent : [fluent, ''];
    return FX(icon, size, colour);
  };
  const CAP = {min: '<path d="M0 5.5h10" stroke="currentColor"/>', max: '<rect x=".5" y=".5" width="9" height="9" rx="1" fill="none" stroke="currentColor"/>',
    restore: '<rect x=".5" y="2.5" width="7" height="7" rx="1" fill="none" stroke="currentColor"/><path d="M2.5 2.5V1.5a1 1 0 0 1 1-1h5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1h-1" fill="none" stroke="currentColor"/>',
    close: '<path d="M.5.5l9 9M9.5.5l-9 9" stroke="currentColor" stroke-width="1.05"/>', back: '<path d="M10 5H1M4.5 1.5 1 5l3.5 3.5" fill="none" stroke="currentColor" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/>'};
  const glyph = name => `<svg viewBox="0 0 10 10" width="10" height="10" style="overflow:visible">${CAP[name]}</svg>`;
  const toggle = on => `<span class="wn-sw${on ? ' on' : ''}"><i></i></span>`;

  /* =============================== styles =============================== */
  skinCss(`
  @font-face{font-family:'Selawik';src:url('/Selawik-Regular.woff2') format('woff2');font-weight:400}
  @font-face{font-family:'Selawik';src:url('/Selawik-Semibold.woff2') format('woff2');font-weight:600}
  @font-face{font-family:'Selawik';src:url('/Selawik-Semilight.woff2') format('woff2');font-weight:300}
  .px-app.win11,.px-app.win10{position:fixed;inset:0;overflow:hidden;font:14px 'Segoe UI Variable Text','Segoe UI',Selawik,Inter,Arial,sans-serif;color:#1b1b1b;
    user-select:none;-webkit-font-smoothing:antialiased}
  @font-face{font-family:'Cascadia Mono';src:url('/CascadiaMono-Regular.woff2') format('woff2')}
  .px-app.win11 ~ .px-pill,.px-app.win10 ~ .px-pill{top:auto;bottom:6px;right:140px}.px-app.win11 ~ .px-pill .px-pill-main,.px-app.win10 ~ .px-pill .px-pill-main{display:none}
  .px-app.win11 ~ .px-pill .px-pill-menu{bottom:50px;background:rgba(249,249,249,.97);border:1px solid rgba(0,0,0,.12);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.18);
    font:13px 'Segoe UI',Selawik,Inter,sans-serif}.px-app.win11 ~ .px-pill .px-pill-menu button{color:#1b1b1b;border-radius:4px}.px-app.win11 ~ .px-pill .px-pill-menu button:hover{background:rgba(0,0,0,.05)}
  .px-app.win10 ~ .px-pill .px-pill-menu{bottom:44px;background:#2b2b2b;border-radius:0;font:13px 'Segoe UI',Selawik,Inter,sans-serif}
  .px-app.win11 .wn-wall{position:absolute;inset:0;background:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1600 900' preserveAspectRatio='xMidYMid slice'><defs><linearGradient id='a' x1='0' y1='1' x2='1' y2='0'><stop offset='0' stop-color='%23cfe8ff' stop-opacity='0'/><stop offset='.55' stop-color='%23e3f2ff' stop-opacity='.9'/><stop offset='1' stop-color='%2399ccff' stop-opacity='.25'/></linearGradient><filter id='b'><feGaussianBlur stdDeviation='16'/></filter></defs><g filter='url(%23b)'><path d='M-120 840 C 280 560 660 780 980 450 S 1480 170 1760 230 L 1760 380 C 1460 350 1250 540 1020 660 S 420 990 -120 980 Z' fill='url(%23a)'/><path d='M-120 720 C 360 440 760 640 1080 320 S 1500 60 1760 80 L 1760 150 C 1460 140 1200 350 1000 490 S 360 880 -120 900 Z' fill='%23ffffff' fill-opacity='.3'/><path d='M200 980 C 520 760 900 820 1200 600 S 1560 420 1760 460 L 1760 520 C 1500 520 1300 680 1080 780 S 640 1000 200 1040 Z' fill='%2366b3ff' fill-opacity='.35'/></g></svg>") center/cover,
    radial-gradient(60% 60% at 62% 48%,#3b8ff0 0%,rgba(59,143,240,0) 70%),linear-gradient(135deg,#0a3d91,#1a66cf 55%,#3d9bf0)}
  .px-app.win10 .wn-wall{position:absolute;inset:0;background:radial-gradient(40% 70% at 64% 46%,rgba(120,190,255,.55),rgba(0,0,0,0) 70%),
    linear-gradient(115deg,#03101f 0%,#06305f 46%,#0a4f94 60%,#05254a 75%,#020b16)}
  .px-app.win10.server .wn-wall{background:linear-gradient(160deg,#0b2a46,#0e3c64 55%,#08223a)}
  .wn-desk{position:absolute;left:6px;top:6px;display:grid;gap:4px}
  .wn-di{width:78px;padding:6px 2px;text-align:center;color:#fff;font-size:12px;text-shadow:0 0 3px rgba(0,0,0,.85),0 1px 2px rgba(0,0,0,.9);border:1px solid transparent;border-radius:2px;cursor:default}
  .wn-di svg{display:block;margin:0 auto 4px}.wn-di:hover{background:rgba(255,255,255,.14);border-color:rgba(255,255,255,.25)}
  .wn-di.sel{background:rgba(255,255,255,.28);border-color:rgba(255,255,255,.45)}
  /* taskbar */
  .wn-bar{position:absolute;left:0;right:0;bottom:0;height:48px;display:flex;align-items:center;z-index:50}
  .px-app.win11 .wn-bar{background:rgba(238,242,247,.86);backdrop-filter:blur(24px);border-top:1px solid rgba(0,0,0,.08)}
  .px-app.win10 .wn-bar{height:40px;background:rgba(16,16,16,.92);color:#fff}
  .wn-mid{display:flex;align-items:center;gap:4px}.px-app.win11 .wn-mid{position:absolute;left:50%;transform:translateX(-50%)}
  .wn-tb{height:40px;min-width:40px;display:grid;place-items:center;border-radius:4px;position:relative;cursor:default;color:inherit}
  .px-app.win11 .wn-tb:hover{background:rgba(255,255,255,.7)}.px-app.win10 .wn-tb{height:40px;min-width:48px;border-radius:0}.px-app.win10 .wn-tb:hover{background:rgba(255,255,255,.12)}
  .wn-tb.run::after{content:'';position:absolute;bottom:2px;left:50%;width:6px;height:3px;border-radius:2px;background:#8a8a8a;transform:translateX(-50%)}
  .wn-tb.run.front::after{width:16px;background:#005fb8}.px-app.win10 .wn-tb.run::after{width:100%;left:0;bottom:0;height:2px;transform:none;border-radius:0;background:#76b9ed}
  .wn-search10{height:40px;width:300px;display:flex;align-items:center;gap:10px;padding:0 12px;background:#f3f3f3;color:#555;font-size:13px}
  .wn-tray{margin-left:auto;display:flex;align-items:center;height:100%;padding-right:6px;gap:2px}
  .wn-tray .ic{height:40px;padding:0 6px;display:flex;align-items:center;gap:8px;border-radius:4px;cursor:default;color:inherit}
  .px-app.win11 .wn-tray .ic:hover{background:rgba(255,255,255,.7)}.px-app.win10 .wn-tray .ic:hover{background:rgba(255,255,255,.12)}
  .wn-clock{text-align:right;font-size:12px;line-height:1.35;padding:0 6px}
  /* flyouts */
  .wn-fly{position:absolute;z-index:60;background:rgba(242,245,249,.97);backdrop-filter:blur(30px);border:1px solid rgba(0,0,0,.1);box-shadow:0 18px 40px rgba(0,0,0,.28)}
  .px-app.win11 .wn-fly{border-radius:8px}.px-app.win10 .wn-fly{background:rgba(31,31,31,.97);color:#fff;border-color:#3a3a3a}
  .wn-start11{left:50%;bottom:58px;width:640px;height:680px;transform:translateX(-50%);display:flex;flex-direction:column}
  .wn-start11 .sb{margin:30px 32px 18px;display:flex;align-items:center;gap:10px;padding:8px 14px;border-radius:18px;background:#fff;border:1px solid #d5dbe2;border-bottom:2px solid #005fb8}
  .wn-start11 .sb input{border:0;outline:0;flex:1;font:inherit;background:none}
  .wn-start11 h4{margin:4px 48px 10px;font-size:14px;font-weight:600;display:flex;justify-content:space-between}
  .wn-start11 h4 span{font-weight:normal;font-size:12px;background:#fff;border:1px solid #e0e0e0;border-radius:4px;padding:2px 8px}
  .wn-pins{display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin:0 36px}
  .wn-pin{padding:12px 4px 8px;border-radius:4px;text-align:center;font-size:12px;cursor:default}.wn-pin:hover{background:rgba(255,255,255,.85)}
  .wn-pin svg{display:block;margin:0 auto 8px}
  .wn-rec{margin:6px 48px;color:#5b5b5b;font-size:12.5px}
  .wn-sfoot{margin-top:auto;height:64px;display:flex;align-items:center;padding:0 48px;background:rgba(228,233,239,.8);border-top:1px solid #dde2e8;border-radius:0 0 8px 8px}
  .wn-sfoot .u{display:flex;align-items:center;gap:12px;padding:6px 10px;border-radius:4px}.wn-sfoot .u:hover,.wn-sfoot .p:hover{background:rgba(255,255,255,.8)}
  .wn-sfoot .p{margin-left:auto;padding:8px;border-radius:4px;display:grid}
  .wn-start10{left:0;bottom:40px;width:620px;height:640px;display:grid;grid-template-columns:48px 260px 1fr}
  .wn-start10 .rail{display:flex;flex-direction:column;justify-content:flex-end;padding-bottom:6px}.wn-start10 .rail span{height:48px;display:grid;place-items:center}
  .wn-start10 .rail span:hover{background:#3a3a3a}.wn-start10 .list{overflow:auto;padding:8px 0}.wn-start10 .list b{display:block;padding:10px 14px 4px;font-size:13px}
  .wn-start10 .list a{display:flex;align-items:center;gap:12px;padding:6px 14px;font-size:13px;cursor:default}.wn-start10 .list a:hover{background:#3a3a3a}
  .wn-start10 .tiles{padding:12px;display:grid;grid-template-columns:repeat(3,96px);grid-auto-rows:96px;gap:4px;align-content:start}
  .wn-start10 .tiles i{background:#0063b1;display:flex;flex-direction:column;justify-content:space-between;padding:8px;font-style:normal;font-size:12px;cursor:default}
  .wn-start10 .tiles i:hover{outline:2px solid rgba(255,255,255,.5)}
  .wn-quick{right:12px;bottom:58px;width:360px;padding:18px 16px 0}
  .wn-quick .tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
  .wn-quick .tile{display:flex;flex-direction:column;align-items:center;gap:6px;font-size:12px}
  .wn-quick .tile b{width:100%;height:46px;border-radius:6px;display:grid;place-items:center;background:#fbfbfb;border:1px solid #dde2e8;font-weight:normal}
  .wn-quick .tile.on b{background:#005fb8;color:#fff;border-color:#005fb8}
  .wn-quick .slide{display:flex;align-items:center;gap:12px;margin:18px 4px}.wn-quick .slide i{flex:1;height:4px;border-radius:2px;background:linear-gradient(90deg,#005fb8 62%,#8a8a8a 62%)}
  .wn-quick .foot{display:flex;align-items:center;justify-content:space-between;margin:0 -16px;padding:12px 16px;background:rgba(228,233,239,.85);border-top:1px solid #dde2e8;
    border-radius:0 0 8px 8px;font-size:12px}
  .wn-net10{right:0;bottom:40px;width:360px}.wn-net10 .row{display:flex;gap:12px;padding:14px 16px;align-items:center;background:#2b2b2b}
  .wn-net10 a{display:block;padding:12px 16px;color:#9ccdfa;font-size:13px;cursor:default}.wn-net10 .tiles{display:flex;gap:2px;padding:0 0 2px}
  .wn-net10 .tiles i{flex:1;height:70px;background:#3a3a3a;font-style:normal;font-size:12px;padding:8px}
  /* windows */
  .wn-win{position:absolute;display:flex;flex-direction:column;background:#fff;box-shadow:0 12px 40px rgba(0,0,0,.32);border:1px solid rgba(0,0,0,.18);min-width:300px}
  .px-app.win11 .wn-win{border-radius:8px;overflow:hidden}.px-app.win10 .wn-win{border-color:#6f9fd3}
  .wn-win.back{box-shadow:0 6px 18px rgba(0,0,0,.2)}
  .wn-tt{height:32px;display:flex;align-items:center;flex:none;font-size:12px;cursor:default}.px-app.win11 .wn-tt{background:#f3f3f3}
  .px-app.win11 .wn-win.mica .wn-tt{background:#eef2f6}.px-app.win10 .wn-tt{background:#fff;height:30px}
  .wn-tt .ico{display:grid;place-items:center;width:40px}.wn-tt .t{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .wn-tt .cap{width:46px;height:100%;display:grid;place-items:center;font-size:12px;color:#1b1b1b;cursor:default}
  .wn-tt .cap:hover{background:rgba(0,0,0,.06)}.wn-tt .cap.x:hover{background:#c42b1c;color:#fff}
  .wn-win.back .wn-tt{color:#8a8a8a}
  .wn-body{flex:1;min-height:0;overflow:auto;position:relative}
  /* classic dialog look (Win32) */
  .wn-win.dlg .wn-body{background:#f0f0f0;padding:10px 12px 12px;font:12px 'Segoe UI',Selawik,Inter,Arial,sans-serif}
  .wn-tabs{display:flex;gap:0;border-bottom:1px solid #d9d9d9;margin-bottom:-1px;position:relative;z-index:1}
  .wn-tabs a{padding:4px 10px;border:1px solid transparent;border-bottom:0;cursor:default}.wn-tabs a.on{background:#fff;border-color:#d9d9d9;border-radius:2px 2px 0 0}
  .wn-page{background:#fff;border:1px solid #d9d9d9;padding:10px 12px}
  .wn-grp{border:1px solid #dcdcdc;border-radius:2px;padding:8px 10px 10px;margin:10px 0 0;position:relative}
  .wn-grp>.lg{position:absolute;top:-8px;left:8px;background:#fff;padding:0 3px}
  .wn-fld{display:grid;grid-template-columns:1fr 150px;align-items:center;margin:6px 0 0 18px}
  .wn-fld.off{color:#9a9a9a}
  .wn-ipbox{display:flex;align-items:center;height:22px;border:1px solid #7a7a7a;background:#fff;padding:0 2px;width:146px}
  .wn-ipbox input{width:28px;border:0;outline:0;text-align:center;font:inherit;padding:0;background:none}.wn-ipbox span{width:6px;text-align:center}
  .wn-fld.off .wn-ipbox{border-color:#cfcfcf;background:#f4f4f4}.wn-fld.off .wn-ipbox input,.wn-fld.off .wn-ipbox span{color:#a0a0a0}
  .wn-rad{display:flex;align-items:center;gap:6px;margin:6px 0 0}.wn-rad input,.wn-chk input{margin:0;appearance:auto}
  .wn-chk{display:flex;align-items:center;gap:6px}
  .wn-btns{display:flex;justify-content:flex-end;gap:8px;margin-top:12px}
  .wn-btn{min-width:75px;height:23px;padding:0 10px;border:1px solid #adadad;background:#e1e1e1;font:12px 'Segoe UI',Selawik,Inter,Arial,sans-serif;cursor:default}
  .wn-btn:hover{background:#e5f1fb;border-color:#0078d7}.wn-btn.def{border:2px solid #0078d7}.wn-btn:disabled{color:#a0a0a0;border-color:#cfcfcf;background:#f0f0f0}
  .wn-list{background:#fff;border:1px solid #828790;height:132px;overflow:auto;margin-top:4px}
  .wn-list div{display:flex;align-items:center;gap:6px;padding:1px 4px;white-space:nowrap}.wn-list div.sel{background:#0078d7;color:#fff}
  .wn-kv{width:100%;border-collapse:collapse;background:#fff;border:1px solid #828790}.wn-kv th{text-align:left;font-weight:normal;border-bottom:1px solid #e5e5e5;padding:3px 6px;background:#fff}
  .wn-kv td{padding:2px 6px;white-space:nowrap}
  .wn-err{color:#c42b1c;margin-top:8px;min-height:15px}
  /* explorer-style windows (control panel, network connections) */
  .wn-addr{display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid #e5e5e5;background:#fff;font-size:12.5px}
  .wn-addr .nav{color:#8a8a8a;letter-spacing:6px}.wn-addr .path{flex:1;border:1px solid #d9d9d9;padding:4px 8px;display:flex;gap:4px;align-items:center}
  .wn-addr .path a{cursor:default}.wn-addr .path a:hover{background:#e5f3ff}.wn-addr .find{width:200px;border:1px solid #d9d9d9;padding:4px 8px;color:#8a8a8a}
  .wn-cmdbar{display:flex;gap:2px;align-items:center;padding:4px 8px;border-bottom:1px solid #e5e5e5;background:#f5f8fc;font-size:12.5px}
  .wn-cmdbar a{padding:4px 8px;cursor:default;white-space:nowrap}.wn-cmdbar a:hover{background:#e5f3ff;outline:1px solid #cce8ff}.wn-cmdbar a.off{color:#a0a0a0;pointer-events:none}
  .wn-ad{display:inline-flex;gap:8px;padding:6px 10px;margin:8px;border:1px solid transparent;width:300px;cursor:default;font-size:12.5px;line-height:1.35}
  .wn-ad:hover{background:#e5f3ff;border-color:#e5f3ff}.wn-ad.sel{background:#cce8ff;border-color:#99d1ff}.wn-ad small{color:#6d6d6d;display:block}
  .wn-cpl{display:grid;grid-template-columns:230px 1fr;min-height:100%}.wn-cpl nav{background:linear-gradient(#e9f0f8,#f8fbfe);padding:14px 12px;font-size:12.5px}
  .wn-cpl nav a{display:block;color:#0066cc;padding:4px 0;cursor:default}.wn-cpl nav a:hover{text-decoration:underline}.wn-cpl nav b{display:block;margin-bottom:10px}
  .wn-cpl main{padding:16px 22px;font-size:12.5px}.wn-cpl h2{font-size:17px;font-weight:normal;color:#1e3287;margin:0 0 14px}
  .wn-cpl a.lk{color:#0066cc;cursor:default}.wn-cpl a.lk:hover{text-decoration:underline}
  .wn-cats{display:grid;grid-template-columns:1fr 1fr;gap:18px 30px}.wn-cat{display:flex;gap:12px}.wn-cat b{display:block;color:#0d5d36;font-size:14px;font-weight:normal}
  .wn-cat b.lk{color:#0d5d36}.wn-cat small{display:block;color:#0066cc;font-size:12px;margin-top:2px}
  .wn-active{border:1px solid #c7d3e0;padding:10px 14px;display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:8px 0 18px}
  /* modern settings (Windows 11) */
  .wn-set{display:grid;grid-template-columns:300px 1fr;height:100%;background:#f3f3f3;font-size:14px}
  .wn-set nav{padding:8px 8px 8px 16px;overflow:auto}.wn-set .me{display:flex;align-items:center;gap:14px;padding:10px 8px 18px}.wn-set .me b{display:block;font-weight:600}
  .wn-set .me small{color:#5b5b5b;font-size:12px}.wn-set .find{display:flex;align-items:center;justify-content:space-between;padding:7px 12px;background:#fff;border:1px solid #e0e0e0;
    border-bottom-color:#8a8a8a;border-radius:4px;color:#7a7a7a;font-size:13px;margin-bottom:10px}
  .wn-set nav a{display:flex;align-items:center;gap:14px;padding:9px 12px;border-radius:4px;position:relative;cursor:default}.wn-set nav a:hover{background:#e9e9e9}
  .wn-set nav a.on{background:#eaeaea}.wn-set nav a.on::before{content:'';position:absolute;left:0;top:10px;bottom:10px;width:3px;border-radius:2px;background:#005fb8}
  .wn-set nav a i{width:18px;text-align:center;font-style:normal;color:#005fb8}
  .wn-set main{padding:10px 40px 30px 24px;overflow:auto}.wn-set h1{font-size:28px;font-weight:600;margin:6px 0 22px;display:flex;align-items:center;gap:10px}
  .wn-set h1 small{font-size:28px;color:#5b5b5b;font-weight:600}.wn-set h1 a{color:#5b5b5b;cursor:default}.wn-set h1 a:hover{color:#1b1b1b}
  .wn-card{background:#fbfbfb;border:1px solid #e5e5e5;border-radius:6px;padding:14px 18px;display:flex;align-items:center;gap:16px;margin-bottom:4px}
  .wn-card.link{cursor:default}.wn-card.link:hover{background:#f6f6f6}.wn-card .grow{flex:1}.wn-card small{display:block;color:#5b5b5b;font-size:12px;margin-top:2px}
  .wn-card .chev{color:#5b5b5b}.wn-hero{display:flex;align-items:center;gap:18px;background:#fbfbfb;border:1px solid #e5e5e5;border-radius:6px;padding:18px;margin-bottom:18px}
  .wn-hero b{font-size:20px;font-weight:600;display:block}.wn-hero .st{color:#5b5b5b}
  .wn-mbtn{height:32px;padding:0 14px;border-radius:4px;border:1px solid #d0d0d0;border-bottom-color:#b5b5b5;background:#fdfdfd;font:inherit;font-size:13px;cursor:default}
  .wn-mbtn:hover{background:#f6f6f6}.wn-mbtn.acc{background:#005fb8;border-color:#0050a0;color:#fff}.wn-mbtn.acc:hover{background:#1a6fc4}
  .wn-props{display:grid;grid-template-columns:260px 1fr;gap:6px 20px;font-size:13.5px;padding:8px 18px 14px}.wn-props span{color:#1b1b1b}.wn-props b{font-weight:normal}
  .wn-sec{margin:24px 0 8px;font-weight:600}
  .wn-shade{position:absolute;inset:0;background:rgba(255,255,255,.35);display:grid;place-items:center;z-index:5}
  .wn-cd{width:460px;background:#f9f9f9;border:1px solid #d5d5d5;border-radius:8px;box-shadow:0 20px 50px rgba(0,0,0,.25);overflow:hidden}
  .wn-cd .b{padding:22px 24px;background:#fff}.wn-cd h3{margin:0 0 16px;font-size:20px;font-weight:600}.wn-cd label{display:block;margin:12px 0 6px;font-size:13px}
  .wn-cd input[type=text],.wn-cd select{width:100%;box-sizing:border-box;height:32px;border:1px solid #d0d0d0;border-bottom-color:#8a8a8a;border-radius:4px;padding:0 10px;font:inherit;background:#fff}
  .wn-cd .f{display:flex;gap:8px;padding:20px 24px;background:#f3f3f3;border-top:1px solid #e5e5e5}.wn-cd .f button{flex:1}
  .wn-tog{display:flex;align-items:center;gap:10px;margin-top:10px}.wn-tog i{width:40px;height:20px;border-radius:10px;background:#005fb8;position:relative}
  .wn-tog i::after{content:'';position:absolute;right:4px;top:4px;width:12px;height:12px;border-radius:50%;background:#fff}
  /* Windows 10 settings */
  .px-app.win10 .wn-set{grid-template-columns:280px 1fr;background:#fff}.px-app.win10 .wn-set nav{background:#f2f2f2;padding:8px 0}
  .px-app.win10 .wn-set nav a{border-radius:0;padding:10px 20px}.px-app.win10 .wn-set nav a.on::before{left:0;top:6px;bottom:6px;width:4px;background:#0078d7}
  .px-app.win10 .wn-set nav a.on{background:#e5e5e5}.px-app.win10 .wn-set nav .grp{font-weight:600;padding:12px 20px 6px}
  .px-app.win10 .wn-set h1{font-size:28px;font-weight:300}.px-app.win10 .wn-card{background:#fff;border:0;border-radius:0;padding:10px 0}
  .wn-home10{padding:30px 40px;display:grid;grid-template-columns:repeat(4,1fr);gap:24px 30px;background:#fff}
  .wn-home10 a{display:flex;gap:12px;cursor:default;padding:10px;border:1px solid transparent}.wn-home10 a:hover{border-color:#ccc}
  .wn-home10 a b{display:block;font-weight:normal}.wn-home10 a small{color:#666;font-size:12px}
  .wn-link10{color:#0067b8;cursor:default}.wn-link10:hover{text-decoration:underline}
  /* terminal / cmd */
  .wn-term{background:#0c0c0c;color:#cccccc;font:14px 'Cascadia Mono',Consolas,'DejaVu Sans Mono',monospace;padding:6px 10px;height:100%;box-sizing:border-box;overflow:auto;
    white-space:pre-wrap;user-select:text;cursor:text}
  .wn-term input{background:none;border:0;outline:0;color:#cccccc;font:inherit;width:60%;padding:0;caret-color:#cccccc}
  .wn-ttabs{height:40px;background:#202020;display:flex;align-items:flex-end;padding-left:8px;gap:4px;color:#fff;font-size:12px}
  .wn-ttabs .tab{background:#0c0c0c;padding:8px 14px 10px;border-radius:6px 6px 0 0;display:flex;gap:10px;align-items:center;min-width:180px}
  .wn-ttabs .plus{padding:8px 10px;color:#ccc}
  /* server manager */
  .wn-sm{display:grid;grid-template-rows:52px 1fr;height:100%}.wn-sm .hd{display:flex;align-items:center;gap:16px;padding:0 16px;background:#fff;border-bottom:1px solid #e1e1e1;font-size:20px;font-weight:300}
  .wn-sm .hd small{font-size:13px;margin-left:auto;display:flex;gap:18px;color:#333}.wn-sm .bd{display:grid;grid-template-columns:200px 1fr;min-height:0}
  .wn-sm nav{background:#f3f3f3;border-right:1px solid #e1e1e1;padding:8px 0}.wn-sm nav a{display:flex;gap:10px;padding:8px 14px;cursor:default;font-size:13px}
  .wn-sm nav a.on{background:#cde6f7}.wn-sm main{overflow:auto;padding:14px 20px;font-size:12.5px}
  .wn-sm .welcome{background:#0f6cbd;color:#fff;padding:16px 20px;display:grid;grid-template-columns:200px 1fr;gap:20px}
  .wn-sm .welcome b{font-size:16px;font-weight:300}.wn-sm .welcome ol{margin:0;padding-left:20px;line-height:2}
  .wn-sm .welcome li a{color:#fff;cursor:default}.wn-sm .props{display:grid;grid-template-columns:240px 1fr 240px 1fr;gap:6px 14px;border:1px solid #e1e1e1;padding:12px 14px}
  .wn-sm .props span{color:#555}.wn-sm .props a{color:#0067b8;cursor:default}.wn-sm .props a:hover{text-decoration:underline}
  .wn-sm h3{font-size:14px;font-weight:normal;margin:4px 0 10px;color:#333;letter-spacing:.5px}
  .wn-ctx{position:absolute;z-index:70;background:#f9f9f9;border:1px solid #cfcfcf;box-shadow:0 8px 20px rgba(0,0,0,.2);padding:4px 0;font-size:12.5px;min-width:220px}
  .wn-ctx a{display:block;padding:6px 26px;cursor:default}.wn-ctx a:hover{background:#e5f3ff}.wn-ctx hr{border:0;border-top:1px solid #e0e0e0;margin:4px 0}
  /* Windows 11 context menu: rounded, light, sub-menus marked » */
  .wn-ctx.w11{border-radius:8px;background:rgba(249,249,249,.97);backdrop-filter:blur(20px);padding:4px;min-width:250px;border-color:rgba(0,0,0,.12);box-shadow:0 8px 24px rgba(0,0,0,.18)}
  .wn-ctx.w11 a{display:flex;align-items:center;gap:12px;padding:7px 12px;border-radius:4px}.wn-ctx.w11 a:hover{background:rgba(0,0,0,.05)}
  .wn-ctx.w11 a em{margin-left:auto;font-style:normal;color:#5b5b5b}.wn-ctx.w11 a svg{flex:none}.wn-ctx.w11 hr{margin:4px -4px}
  /* caption buttons, maximised and minimised windows, opening */
  .wn-tt .cap svg{display:block}.wn-tt .back{width:40px;height:100%;display:grid;place-items:center;color:#1b1b1b}.wn-tt .back:hover{background:rgba(0,0,0,.05)}
  .wn-win.max{left:0!important;top:0!important;width:100%!important;height:calc(100% - 48px)!important;border-radius:0!important;border:0}
  .px-app.win10 .wn-win.max{height:calc(100% - 40px)!important}.wn-win.min{display:none}
  @keyframes wnOpen{from{opacity:0;transform:scale(.96) translateY(6px)}to{opacity:1;transform:none}}.wn-win.fresh{animation:wnOpen .17s cubic-bezier(.1,.9,.2,1)}
  @keyframes wnStart11{from{opacity:0;transform:translate(-50%,36px)}to{opacity:1;transform:translate(-50%,0)}}.wn-start11.fresh{animation:wnStart11 .22s cubic-bezier(.1,.9,.2,1)}
  @keyframes wnUp{from{opacity:0;transform:translateY(30px)}to{opacity:1;transform:none}}.wn-start10.fresh,.wn-quick.fresh,.wn-net10.fresh{animation:wnUp .2s cubic-bezier(.1,.9,.2,1)}
  /* taskbar: search box, task view, tray chevron */
  .wn-spill{height:34px;width:180px;display:flex;align-items:center;gap:10px;padding:0 14px;margin:0 4px;border-radius:17px;background:rgba(255,255,255,.8);
    border:1px solid rgba(0,0,0,.07);color:#5b5b5b;font-size:13px;box-sizing:border-box;cursor:default}.wn-spill:hover{background:#fff}
  .wn-tray .chev{padding:0 8px}.wn-tray .lang{font-size:12px;padding:0 8px}
  /* Windows 11 controls: toggle switch, radio rows, expander */
  .wn-sw{width:40px;height:20px;border-radius:10px;border:1px solid #5b5b5b;position:relative;display:inline-block;vertical-align:middle;box-sizing:border-box;background:#f6f6f6;flex:none;cursor:default}
  .wn-sw i{position:absolute;left:4px;top:4px;width:10px;height:10px;border-radius:50%;background:#5b5b5b;transition:left .15s,width .15s}
  .wn-sw.on{background:#005fb8;border-color:#005fb8}.wn-sw.on i{left:24px;background:#fff}.wn-sw:hover i{width:12px;height:12px;top:3px}
  .wn-card .ic{width:20px;flex:none;display:grid;place-items:center}.wn-card .val{color:#1b1b1b;min-width:150px;text-align:right}
  .wn-card.exp{display:block;padding:0}.wn-card.exp .head{display:flex;align-items:center;gap:16px;padding:14px 18px}.wn-card.exp .rows{border-top:1px solid #e5e5e5;padding:10px 18px 14px 54px}
  .wn-card.exp label{display:flex;gap:10px;align-items:flex-start;margin:8px 0}.wn-card.exp label input{appearance:auto;margin-top:3px}.wn-card.exp label small{display:block}
  .wn-set nav a i{display:grid;place-items:center}.wn-set h1{font-weight:600;letter-spacing:-.2px}
  .wn-cd input[type=text]:focus,.wn-cd select:focus{outline:0;border-bottom:2px solid #005fb8}.wn-cd .tg{display:flex;align-items:center;gap:12px;margin:14px 0 4px}
  .wn-props-card{position:relative}.wn-props-card .copy{position:absolute;right:16px;top:12px}
  /* Windows Terminal and File Explorer: tabs in the title bar */
  .wn-win.tabbed .wn-tt{height:40px;align-items:flex-end;padding-left:8px}.wn-win.tabbed .cap{align-self:stretch;height:auto}
  .wn-win.tabbed.dark{background:#0c0c0c;border-color:#3a3a3a}.wn-win.tabbed.dark .wn-tt{background:#202020;color:#fff}.wn-win.tabbed.dark .cap{color:#fff}
  .wn-win.tabbed.dark .cap:hover{background:rgba(255,255,255,.1)}.wn-win.tabbed.light .wn-tt{background:#eef2f6}
  .wt-tab{height:34px;min-width:210px;max-width:240px;display:flex;align-items:center;gap:10px;padding:0 8px 0 12px;border-radius:8px 8px 0 0;font-size:12px}
  .wn-win.tabbed.dark .wt-tab{background:#0c0c0c}.wn-win.tabbed.light .wt-tab{background:#f9f9f9}.wt-tab span:nth-child(2){flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .wt-x{width:24px;height:24px;display:grid;place-items:center;border-radius:4px}.wt-x:hover{background:rgba(128,128,128,.25)}
  .wt-plus{height:34px;width:34px;display:grid;place-items:center;font-size:16px;border-radius:6px 6px 0 0}.wt-plus:hover{background:rgba(128,128,128,.2)}
  .wn-win.tabbed.dark .wn-term{height:100%}
  .ex-top{display:flex;align-items:center;gap:8px;padding:6px 10px;background:#f9f9f9;font-size:13px}.ex-nav{display:flex;gap:14px;color:#1b1b1b;padding:0 6px}
  .ex-path{flex:1;display:flex;align-items:center;gap:8px;height:30px;padding:0 10px;border-radius:4px;background:#fff;border:1px solid #e5e5e5}
  .ex-find{width:240px;display:flex;align-items:center;justify-content:space-between;height:30px;padding:0 10px;border-radius:4px;background:#fff;border:1px solid #e5e5e5;color:#6b6b6b}
  .ex-cmd{display:flex;align-items:center;gap:2px;padding:6px 10px;background:#f9f9f9;border-bottom:1px solid #e5e5e5;font-size:13px}
  .ex-cmd a{display:flex;align-items:center;gap:6px;padding:6px 8px;border-radius:4px;cursor:default}.ex-cmd a:hover{background:rgba(0,0,0,.05)}.ex-cmd a.off{color:#a0a0a0}
  .ex-cmd i{width:1px;height:22px;background:#e0e0e0;margin:0 6px}
  .ex-body{display:grid;grid-template-columns:200px 1fr;height:calc(100% - 118px);background:#fff}.ex-body nav{padding:6px;border-right:1px solid #ededed;overflow:auto;font-size:13px}
  .ex-body nav a{display:flex;align-items:center;gap:10px;padding:5px 10px;border-radius:4px;cursor:default}.ex-body nav a:hover{background:rgba(0,0,0,.04)}
  .ex-body nav a.on{background:#e5f1fb}.ex-body nav hr{border:0;border-top:1px solid #ededed;margin:6px 0}.ex-body main{padding:12px 20px;font-size:13px;overflow:auto}
  .ex-sec{display:flex;align-items:center;gap:8px;font-weight:600;margin:4px 0 10px}.ex-drive{display:inline-flex;gap:10px;padding:8px 12px;border-radius:4px;cursor:default}
  .ex-drive:hover{background:#e5f3ff}.ex-drive .bar{width:200px;height:12px;background:#e6e6e6;margin:5px 0}.ex-drive .bar i{display:block;height:100%;background:#26a0da}
  .ex-drive small{color:#6d6d6d}.ex-hosts{display:flex;flex-wrap:wrap;gap:12px}.ex-hosts div{width:100px;text-align:center}.ex-hosts span{display:block}.ex-empty{color:#6d6d6d;text-align:center;margin-top:40px}
  .ex-status{height:24px;display:flex;align-items:center;padding:0 12px;font-size:12px;background:#fff;border-top:1px solid #ededed}
  .wn-quick .tile b{position:relative}.wn-quick .tile b em{position:absolute;right:0;top:0;bottom:0;width:28px;display:grid;place-items:center;border-left:1px solid rgba(0,0,0,.08)}
  .wn-quick .tile.on b em{border-left-color:rgba(255,255,255,.35)}.wn-quick .slide{color:#1b1b1b}.wn-quick .foot a{color:inherit;display:grid}
  /* messages as Windows notifications: a card at the bottom right, above the clock */
  .px-app.win11 ~ .px-toast,.px-app.win10 ~ .px-toast{left:auto;right:12px;bottom:60px;transform:none;width:364px;box-sizing:border-box;padding:12px 16px 16px;
    font:13px 'Segoe UI',Selawik,Inter,sans-serif;line-height:1.45}
  .px-app.win11 ~ .px-toast{background:rgba(249,249,249,.98);color:#1b1b1b;border:1px solid rgba(0,0,0,.1);border-radius:8px;box-shadow:0 12px 32px rgba(0,0,0,.22)}
  .px-app.win10 ~ .px-toast{bottom:52px;background:#1f1f1f;color:#fff;border-radius:0}
  .px-app.win11 ~ .px-toast::before,.px-app.win10 ~ .px-toast::before{content:'Network LABS';display:block;font-size:12px;opacity:.7;margin-bottom:8px}
  .px-app.win11 ~ .px-toast.bad{color:#c42b1c}.px-app.win10 ~ .px-toast.bad{color:#ff99a4}
  /* lock screen */
  .wn-lock{position:absolute;inset:0;z-index:100;color:#fff;cursor:default;transition:transform .35s cubic-bezier(.6,0,.9,.4)}
  .wn-lock .wn-wall{filter:brightness(.92)}.wn-lock.leave{transform:translateY(-100%)}
  .wn-lock .t{position:absolute;left:0;right:0;top:11%;text-align:center;font-size:118px;font-weight:600;line-height:1;text-shadow:0 2px 12px rgba(0,0,0,.2)}
  .wn-lock .d{position:absolute;left:0;right:0;top:calc(11% + 132px);text-align:center;font-size:24px;font-weight:600;text-shadow:0 1px 6px rgba(0,0,0,.25)}
  .px-app.win10 .wn-lock .t{left:4.5%;right:auto;top:auto;bottom:calc(9% + 54px);font-weight:300;font-size:110px;text-align:left}
  .px-app.win10 .wn-lock .d{left:4.5%;right:auto;top:auto;bottom:9%;font-weight:300;font-size:38px;text-align:left}
  .wn-lock .ico{position:absolute;right:28px;bottom:24px;display:flex;gap:18px}.wn-lock .cad{position:absolute;left:0;right:0;bottom:22%;text-align:center;font-size:20px}
  `);

  /* =============================== the shell =============================== */
  const shell = id => ({
    get start() {  // read when the page opens: a server starts with Server Manager open, as Windows Server does
      return {wins: id === 'win10' && SERVER() ? [{id: 1, kind: 'servermgr', x: 90, y: 40, page: 'dash'}] : [], seq: 2, fly: null, sel: null};
    },
    draw(root) { drawShell(root); },
  });
  SKINS.win11 = shell('win11');
  SKINS.win10 = shell('win10');

  const clock = () => {
    const now = new Date();
    return `${now.toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'})}<br>${now.toLocaleDateString('fr-FR')}`;
  };
  const APPS = [['settings', 'Paramètres'], ['explorer', 'Explorateur de fichiers'], ['terminal', 'Terminal'], ['cmd', 'Invite de commandes'],
    ['cpl', 'Panneau de configuration'], ['notepad', 'Bloc-notes'], ['calc', 'Calculatrice'], ['taskmgr', 'Gestionnaire des tâches']];
  const OPEN = {settings: () => openWin('settings'), explorer: () => openWin('explorer', {page: 'pc'}), terminal: () => openWin('cmd'),
    cmd: () => openWin('cmd'), cpl: () => openWin('cpl', {page: 'home'}), servermgr: () => openWin('servermgr', {page: 'dash'}),
    ncpa: () => openWin('cpl', {page: 'ncpa'}), notepad: () => later('Bloc-notes'), calc: () => later('Calculatrice'),
    taskmgr: () => later('Gestionnaire des tâches')};
  const appIcon = (kind, size = 24) => (ICON[kind] || ICON.pc)(size);
  const NL_TRAY = '<svg viewBox="0 0 16 16" width="16" height="16"><circle cx="8" cy="8" r="6.4" fill="none" stroke="currentColor" stroke-width="1.3"/><circle cx="8" cy="8" r="2.6" fill="currentColor"/></svg>';

  function drawShell(root) {
    const v = V(), w11 = W11();
    root.classList.toggle('server', SERVER());
    const port = ports()[0];
    const netIcon = cabled(port) ? ICON.ethernet(18) : ICON.offline(18);
    const pinned = w11 ? ['explorer', 'settings', 'terminal', 'cpl'] : SERVER() ? ['servermgr', 'explorer', 'cmd', 'cpl'] : ['explorer', 'settings', 'cmd', 'cpl'];
    const kindOf = k => (k === 'terminal' ? 'cmd' : k);
    const open = v.wins.filter(x => !x.parent);
    const top = open.filter(x => !x.min).slice(-1)[0];
    const tip = k => (k === 'servermgr' ? 'Gestionnaire de serveur' : (APPS.find(x => x[0] === k) || [0, ''])[1]);
    const taskview = svg('<rect x="3" y="6" width="12" height="11" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 6V4.5A1.5 1.5 0 0 1 9.5 3h10A1.5 1.5 0 0 1 21 4.5v9a1.5 1.5 0 0 1-1.5 1.5H15" fill="none" stroke="currentColor" stroke-width="1.5"/>', 20);
    const chevron = FX('chevron_up', 16);
    root.innerHTML = `<div class="wn-wall"></div><div class="wn-desk">${[['pc', 'Ce PC'], ['bin', 'Corbeille'], ['network', 'Réseau']].map(([k, label]) =>
      `<div class="wn-di${v.sel === k ? ' sel' : ''}" data-di="${k}">${ICON[k](44)}${label}</div>`).join('')}</div>
      <div class="wn-bar">${w11 ? '' : `<span class="wn-tb" data-start="1">${ICON.start(20, '#ffffff')}</span><span class="wn-search10" data-start="1">${ICON.search(16)} Taper ici pour rechercher</span>
        <span class="wn-tb" title="Affichage des tâches">${taskview}</span>`}
        <div class="wn-mid">${w11 ? `<span class="wn-tb" data-start="1" title="Démarrer">${ICON.start(24)}</span><span class="wn-spill" data-start="1">${ICON.search(16)}Rechercher</span>
          <span class="wn-tb" title="Affichage des tâches">${taskview}</span>` : ''}
        ${pinned.map(k => { const win = open.find(x => x.kind === kindOf(k));
          return `<span class="wn-tb${win ? ' run' : ''}${win && win === top ? ' front' : ''}" data-app="${k}" title="${tip(k)}">${k === 'servermgr' ? ICON.server(24) : appIcon(k)}</span>`; }).join('')}</div>
        <div class="wn-tray"><span class="ic chev" title="Afficher les icônes cachées">${chevron}</span><span class="ic nl" title="Network LABS">${NL_TRAY}</span>${w11 ? '' : '<span class="ic lang">FRA</span>'}
          <span class="ic" data-fly="net" title="${h(nic(port))}\n${cabled(port) ? access(port) : 'Câble réseau non connecté'}">${netIcon}${ICON.speaker(18)}</span>
          <span class="ic wn-clock" data-fly="cal">${clock()}</span>${w11 ? `<span class="ic">${ICON.bell(16)}</span>` : ''}</div></div>`;
    for (const win of v.wins) {
      const parent = win.parent && v.wins.find(x => x.id === win.parent);
      if (!win.min && !(parent && parent.min)) root.append(windowEl(win));
    }
    // The window in front takes the keyboard at once (the terminal's prompt), as on Windows.
    const front = [...root.querySelectorAll('.wn-win')].pop();
    front?.querySelector('[data-autofocus]')?.focus({preventScroll: true});
    if (v.fly === 'start') root.append(w11 ? start11() : start10());
    if (v.fly === 'net') root.append(w11 ? quick11() : net10());
    const fly = root.querySelector('.wn-fly');
    if (fly && v.flyFresh) fly.classList.add('fresh');
    v.flyFresh = false;
    root.querySelectorAll('[data-start]').forEach(b => { b.onclick = event => { event.stopPropagation(); v.fly = v.fly === 'start' ? null : 'start'; v.flyFresh = true; render(); }; });
    root.querySelectorAll('[data-fly]').forEach(b => { b.onclick = event => { event.stopPropagation(); if (b.dataset.fly === 'cal') return; v.fly = v.fly === 'net' ? null : 'net';
      v.flyFresh = true; render(); }; });
    // A pinned app: opens it, brings it back from the taskbar, or, when it is in front, puts it away there (as Windows does).
    root.querySelectorAll('[data-app]').forEach(b => { b.onclick = () => {
      const win = open.find(x => x.kind === kindOf(b.dataset.app));
      if (!win) return OPEN[b.dataset.app]();
      if (win.min) { win.min = false; v.wins = [...v.wins.filter(x => x !== win), win]; return render(); }
      if (win === top) { win.min = true; return render(); }
      focusWin(win.id);
    }; });
    // Network LABS' own menu (refresh, the device's terminal, designs): in the tray, where Windows keeps its helpers.
    root.querySelector('.wn-tray .nl').onclick = event => { event.stopPropagation(); document.querySelector('.px-pill')?.classList.toggle('open'); };
    root.querySelectorAll('[data-di]').forEach(icon => {
      icon.onclick = () => { v.sel = icon.dataset.di; root.querySelectorAll('.wn-di').forEach(x => x.classList.toggle('sel', x === icon)); };
      icon.ondblclick = () => openWin('explorer', {page: icon.dataset.di});
    });
    root.querySelector('.wn-wall').onclick = () => { if (v.fly) { v.fly = null; render(); } };
    root.querySelector('.wn-wall').oncontextmenu = event => { event.preventDefault(); context(root, event, w11
      ? [['Affichage', null, '›', 'grid'], ['Trier par', null, '›', 'arrow_sort'], ['Actualiser', () => render(), '', 'arrow_clockwise'], ['-'], ['Nouveau', null, '›', 'add_circle'], ['-'],
        ['Paramètres d’affichage', () => openWin('settings', {page: 'system'}), '', 'desktop'], ['Personnaliser', () => openWin('settings', {page: 'perso'}), '', 'paint_brush'], ['-'],
        ['Ouvrir dans le Terminal', () => openWin('cmd'), '', 'window_console'], ['-'], ['Afficher plus d’options', null, '', 'open']]
      : [['Affichage', null, '›'], ['Trier par', null, '›'], ['Actualiser', () => render()], ['-'], ['Nouveau', null, '›'], ['-'], ['Paramètres d’affichage', () => openWin('settings')],
        ['Personnaliser', () => openWin('settings')]]); };
    if (v.locked === undefined) {
      try { v.locked = !sessionStorage.getItem(lockKey()); } catch (error) { v.locked = true; }
    }
    if (v.locked) root.append(lockScreen());
  }
  // The lock screen, once per device and browser tab: a click or a key opens the session, as on Windows.
  const lockKey = () => `nl-windows-session:${state.project}:${N().name}`;
  function lockScreen() {
    const now = new Date(), lock = document.createElement('div');
    lock.className = 'wn-lock';
    lock.innerHTML = `<div class="wn-wall"></div><div class="t">${now.toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'})}</div>
      <div class="d">${now.toLocaleDateString('fr-FR', {weekday: 'long', day: 'numeric', month: 'long'})}</div>${SERVER() ? '<div class="cad">Appuyez sur Ctrl+Alt+Suppr pour déverrouiller.</div>' : ''}
      <div class="ico">${cabled(ports()[0]) ? ICON.ethernet(20) : ICON.offline(20)}${ICON.power(20)}</div>`;
    const enter = () => {
      if (lock.classList.contains('leave')) return;
      try { sessionStorage.setItem(lockKey(), '1'); } catch (error) { /* private window: the session opens for this page only */ }
      lock.classList.add('leave');
      setTimeout(() => { V().locked = false; render(); }, 360);
    };
    lock.onclick = enter;
    return lock;
  }
  // One listener for every drawing of the lock screen: a key opens the session like a click.
  document.addEventListener('keydown', () => {
    const lock = document.querySelector('.wn-lock');
    if (lock && !lock.classList.contains('leave')) lock.click();
  });
  function context(root, event, items) {
    root.querySelector('.wn-ctx')?.remove();
    const menu = document.createElement('div');
    menu.className = 'wn-ctx' + (W11() ? ' w11' : '');
    menu.style.left = event.clientX + 'px';
    menu.style.top = event.clientY + 'px';
    menu.innerHTML = items.map(([label, , more, icon]) => (label === '-' ? '<hr>' : `<a>${W11() ? `<span style="width:16px;display:grid">${icon ? FX(icon, 16) : ''}</span>` : ''}${h(label)}${
      more ? `<em>${more}</em>` : ''}</a>`)).join('');
    [...menu.querySelectorAll('a')].forEach((a, i) => { const item = items.filter(([l]) => l !== '-')[i]; a.onclick = () => { menu.remove(); (item[1] || (() => later(item[0])))(); }; });
    root.append(menu);
    setTimeout(() => document.addEventListener('click', () => menu.remove(), {once: true}));
  }

  function start11() {
    const v = V(), fly = document.createElement('div');
    fly.className = 'wn-fly wn-start11';
    fly.innerHTML = `<div class="sb">${ICON.search(16)}<input placeholder="Rechercher des applications, des paramètres et des documents"></div>
      <h4>Épinglé <span>Toutes les applications ›</span></h4><div class="wn-pins">${APPS.map(([k, label]) => `<div class="wn-pin" data-app="${k}">${appIcon(k, 32)}${label}</div>`).join('')}</div>
      <h4 style="margin-top:28px">Recommandé <span>Plus ›</span></h4><div class="wn-rec">Pour afficher vos fichiers récents et vos nouvelles applications, activez-les dans les paramètres de démarrage.</div>
      <div class="wn-sfoot"><span class="u">${ICON.user(32)}<span>Utilisateur</span></span><span class="p" title="Marche/Arrêt">${ICON.power(18)}</span></div>`;
    wireStart(fly);
    fly.querySelector('.p').onclick = () => toast('Le poste démarre et s’arrête avec le lab : ▶ Démarrer / ■ Arrêter dans Network LABS.');
    return fly;
  }
  function start10() {
    const fly = document.createElement('div');
    fly.className = 'wn-fly wn-start10';
    const list = [...APPS, ...(SERVER() ? [['servermgr', 'Gestionnaire de serveur']] : [])].sort((a, b) => a[1].localeCompare(b[1], 'fr'));
    fly.innerHTML = `<div class="rail"><span title="Utilisateur">${ICON.user(22)}</span><span title="Paramètres" data-app="settings">${ICON.settings(20)}</span>
      <span class="p" title="Marche/Arrêt">${ICON.power(18)}</span></div><div class="list">${list.map(([k, label], i) => `${i === 0 || label[0] !== list[i - 1][1][0]
        ? `<b>${label[0]}</b>` : ''}<a data-app="${k}">${k === 'servermgr' ? ICON.server(24) : appIcon(k)}${label}</a>`).join('')}</div>
      <div class="tiles">${[['settings', 'Paramètres'], ['explorer', 'Explorateur'], ['cpl', 'Panneau de configuration'], ['cmd', 'Invite de commandes']].map(([k, label]) =>
        `<i data-app="${k}">${appIcon(k, 28)}<span>${label}</span></i>`).join('')}</div>`;
    wireStart(fly);
    fly.querySelector('.p').onclick = () => toast('Le poste démarre et s’arrête avec le lab : ▶ Démarrer / ■ Arrêter dans Network LABS.');
    return fly;
  }
  function wireStart(fly) {
    fly.onclick = event => event.stopPropagation();
    fly.querySelectorAll('[data-app]').forEach(a => { a.onclick = () => { V().fly = null; OPEN[a.dataset.app](); }; });
    const box = fly.querySelector('input');
    if (!box) return;
    setTimeout(() => box.focus());
    box.onkeydown = event => {
      if (event.key !== 'Enter') return;
      const q = box.value.trim().toLowerCase();
      const direct = {'ncpa.cpl': 'ncpa', cmd: 'cmd', 'cmd.exe': 'cmd', control: 'cpl', 'control panel': 'cpl', wt: 'terminal', powershell: 'cmd', 'ms-settings:': 'settings'}[q];
      const found = direct || (APPS.find(([, label]) => label.toLowerCase().includes(q)) || [])[0];
      V().fly = null;
      if (found) OPEN[found](); else { render(); toast(`Aucun résultat pour « ${box.value} ».`, true); }
    };
  }
  function quick11() {
    const port = ports()[0], fly = document.createElement('div');
    fly.className = 'wn-fly wn-quick';
    const tile = (on, icon, label, more) => `<span class="tile${on ? ' on' : ''}"><b>${FX(icon, 18)}${more ? `<em>${FX('chevron_right', 12)}</em>` : ''}</b>${label}</span>`;
    fly.innerHTML = `<div class="tiles">${tile(cabled(port), cabled(port) ? 'desktop' : 'globe_prohibited', cabled(port) ? 'Ethernet' : 'Non connecté', true)}
      ${tile(false, 'bluetooth', 'Bluetooth', true)}${tile(false, 'airplane', 'Mode avion')}${tile(false, 'battery_saver', 'Économiseur d’énergie')}
      ${tile(false, 'weather_moon', 'Éclairage nocturne')}${tile(false, 'accessibility', 'Accessibilité', true)}</div>
      <div class="slide">${FX('brightness_high', 18)}<i></i></div><div class="slide">${FX('speaker_2', 18)}<i></i>${FX('chevron_right', 14)}</div>
      <div class="foot"><span>${h(nic(port))} · ${cabled(port) ? h(access(port)) : 'Câble réseau non connecté'}</span><span style="display:flex;gap:14px">${FX('edit', 16)}
      <a data-go="net" title="Paramètres réseau et Internet">${FX('settings', 16)}</a></span></div>`;
    fly.onclick = event => event.stopPropagation();
    fly.querySelector('[data-go]').onclick = () => { V().fly = null; openWin('settings', {page: 'network'}); };
    return fly;
  }
  function net10() {
    const port = ports()[0], fly = document.createElement('div');
    fly.className = 'wn-fly wn-net10';
    fly.innerHTML = `<div class="row">${cabled(port) ? ICON.ethernet(22) : ICON.offline(22)}<div><b>${h(nic(port))}</b><br><small>${cabled(port) ? h(access(port))
      : 'Câble réseau non connecté'}</small></div></div><a data-go="net">Paramètres réseau et Internet</a><small style="display:block;padding:0 16px 10px;color:#aaa">
      Modifier les paramètres, par exemple rendre une connexion limitée.</small><div class="tiles"><i>✈<br>Mode avion</i><i>⌁<br>Point d’accès mobile</i></div>`;
    fly.onclick = event => event.stopPropagation();
    fly.querySelector('[data-go]').onclick = () => { V().fly = null; openWin('settings', {page: 'network'}); };
    return fly;
  }

  /* =============================== windows =============================== */
  const SIZES = {settings: [1000, 660], cpl: [940, 600], cmd: [780, 460], explorer: [860, 540], servermgr: [1060, 640], status: [372, 470],
    details: [430, 420], props: [380, 540], ipv4: [412, 556], rename: [420, 260]};
  const SINGLE = new Set(['settings', 'cpl', 'cmd', 'servermgr', 'explorer']);
  function openWin(kind, data = {}) {
    const v = V();
    v.fly = null;
    const existing = SINGLE.has(kind) && v.wins.find(x => x.kind === kind);
    if (existing) {
      Object.assign(existing, data, {min: false});
      v.wins = [...v.wins.filter(x => x !== existing), existing];
      return render();
    }
    const [wd, ht] = SIZES[kind] || [600, 400], n = v.wins.length, area = document.querySelector('.px-app');
    const W = area ? area.clientWidth : 1280, H = area ? area.clientHeight : 800;
    v.wins.push({id: v.seq++, kind, x: Math.max(10, Math.min(W - wd - 10, (W - wd) / 2 + n * 26 - 40)), y: Math.max(10, Math.min(H - ht - 60, (H - ht) / 2 - 30 + n * 26)),
      fresh: true, ...data});
    render();
  }
  function closeWin(id) {
    const v = V();
    v.wins = v.wins.filter(x => x.id !== id && x.parent !== id);
    render();
  }
  function focusWin(id) {
    const v = V(), win = v.wins.find(x => x.id === id);
    if (!win || v.wins[v.wins.length - 1] === win) return;
    v.wins = [...v.wins.filter(x => x !== win), win];
    document.querySelectorAll('.wn-win').forEach(el => {  // no redraw: what is being typed elsewhere stays
      const index = v.wins.findIndex(x => String(x.id) === el.dataset.w);
      el.style.zIndex = 10 + index;
      el.classList.toggle('back', index !== v.wins.length - 1);
    });
  }
  const KINDS = {
    settings: win => ({title: 'Paramètres', icon: 'settings', mica: true, body: el => (W11() ? settings11 : settings10)(el, win)}),
    cpl: win => ({title: {home: 'Panneau de configuration', net: 'Centre Réseau et partage', ncpa: 'Connexions réseau'}[win.page] || 'Panneau de configuration', icon: 'cpl',
      body: el => controlPanel(el, win)}),
    cmd: win => ({title: 'Invite de commandes', icon: 'cmd', tab: W11() ? 'dark' : null, body: el => terminal(el, win)}),
    explorer: win => ({title: {pc: 'Ce PC', bin: 'Corbeille', network: 'Réseau'}[win.page] || 'Explorateur de fichiers', icon: win.page === 'bin' ? 'bin' : win.page === 'network' ? 'network' : 'pc',
      tab: W11() ? 'light' : null, body: el => explorer(el, win)}),
    servermgr: win => ({title: 'Gestionnaire de serveur', icon: 'server', body: el => serverManager(el, win)}),
    status: win => ({title: `État de ${nic(win.port)}`, icon: null, dialog: true, body: el => statusDlg(el, win)}),
    details: win => ({title: 'Détails de connexion réseau', icon: null, dialog: true, body: el => detailsDlg(el, win)}),
    props: win => ({title: `Propriétés de ${nic(win.port)}`, icon: null, dialog: true, body: el => propsDlg(el, win)}),
    ipv4: win => ({title: 'Propriétés de : Protocole Internet version 4 (TCP/IPv4)', icon: null, dialog: true, body: el => ipv4Dlg(el, win)}),
  };
  function windowEl(win) {
    const v = V(), spec = KINDS[win.kind](win), [wd, ht] = SIZES[win.kind] || [600, 400], index = v.wins.indexOf(win);
    const el = document.createElement('div');
    el.className = `wn-win${spec.dialog ? ' dlg' : ''}${spec.mica ? ' mica' : ''}${spec.tab ? ' tabbed ' + spec.tab : ''}${win.max ? ' max' : ''}${win.fresh ? ' fresh' : ''}${
      index !== v.wins.length - 1 ? ' back' : ''}`;
    delete win.fresh;  // the opening animation plays once
    el.dataset.w = win.id;
    Object.assign(el.style, {left: win.x + 'px', top: win.y + 'px', width: wd + 'px', height: ht + 'px', zIndex: 10 + index});
    const back = win.kind === 'settings' && W11();  // Windows 11 Settings: a back arrow before its name
    // Windows Terminal and File Explorer (Windows 11): the title bar is a row of tabs.
    const head = spec.tab ? `<span class="wt-tab">${spec.icon === 'server' ? ICON.server(16) : appIcon(spec.icon, 16)}<span>${h(spec.title)}</span><span class="wt-x">${glyph('close')}</span></span>
      <span class="wt-plus">+</span>${spec.tab === 'dark' ? `<span class="wt-plus">${FX('chevron_down', 12)}</span>` : ''}<span class="t"></span>` : '';
    el.innerHTML = spec.tab ? `<div class="wn-tt">${head}<span class="cap mn" title="Réduire">${glyph('min')}</span><span class="cap mx" title="${win.max ? 'Niveau inf.' : 'Agrandir'}">${
      glyph(win.max ? 'restore' : 'max')}</span><span class="cap x" title="Fermer">${glyph('close')}</span></div><div class="wn-body"></div>` : `<div class="wn-tt">${back
      ? `<span class="back" title="Précédent">${glyph('back')}</span>` : ''}<span class="ico"${back ? ' style="width:24px"' : ''}>${spec.icon
      ? (spec.icon === 'server' ? ICON.server(16) : appIcon(spec.icon, 16)) : ''}</span><span class="t"${spec.icon ? '' : ' style="padding-left:10px;margin-left:-40px"'}>${h(spec.title)}</span>${
      spec.dialog ? '' : `<span class="cap mn" title="Réduire">${glyph('min')}</span><span class="cap mx" title="${win.max ? 'Niveau inf.' : 'Agrandir'}">${glyph(win.max ? 'restore' : 'max')}</span>`}
      <span class="cap x" title="Fermer">${glyph('close')}</span></div><div class="wn-body"></div>`;
    el.addEventListener('mousedown', () => focusWin(win.id));
    el.querySelector('.x').onclick = () => closeWin(win.id);
    el.querySelector('.wt-x')?.addEventListener('click', () => closeWin(win.id));
    el.querySelectorAll('.wt-plus').forEach(b => { b.onclick = () => later('Nouvel onglet'); });
    const toggleMax = () => { win.max = !win.max; render(); };
    el.querySelector('.mn')?.addEventListener('click', () => { win.min = true; render(); });
    el.querySelector('.mx')?.addEventListener('click', toggleMax);
    if (!spec.dialog) el.querySelector('.wn-tt').addEventListener('dblclick', event => { if (!event.target.closest('.cap,.back')) toggleMax(); });
    el.querySelector('.back')?.addEventListener('click', () => { const previous = (win.history || []).pop(); if (previous) { win.page = previous; render(); } });
    drag(el, win);
    spec.body(el.querySelector('.wn-body'));
    return el;
  }
  function drag(el, win) {
    const bar = el.querySelector('.wn-tt');
    bar.addEventListener('mousedown', event => {
      if (event.target.closest('.cap,.back,.wt-tab,.wt-plus') || win.max) return;
      const sx = event.clientX - win.x, sy = event.clientY - win.y;
      const move = e => { win.x = Math.max(-200, e.clientX - sx); win.y = Math.max(0, Math.min(window.innerHeight - 80, e.clientY - sy)); el.style.left = win.x + 'px'; el.style.top = win.y + 'px'; };
      const up = () => { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
    });
  }

  /* =============================== Settings (Windows 11) =============================== */
  const NAV11 = [['home', '⌂', 'Accueil'], ['system', '▭', 'Système'], ['bt', '⌬', 'Bluetooth et appareils'], ['network', '◈', 'Réseau et Internet'],
    ['perso', '✎', 'Personnalisation'], ['apps', '▦', 'Applications'], ['accounts', '☺', 'Comptes'], ['time', '◷', 'Heure et langue'], ['games', '◉', 'Jeux'],
    ['access', '♿', 'Accessibilité'], ['privacy', '⛨', 'Confidentialité et sécurité'], ['update', '⟳', 'Windows Update']];
  const goPage = (win, page, extra = {}) => { win.history = [...(win.history || []), win.page || 'home'].slice(-20); Object.assign(win, extra, {page}); render(); };
  const row = (icon, title, sub, right = '<span class="chev">›</span>', attrs = '') => `<div class="wn-card${right.includes('chev') ? ' link' : ''}" ${attrs}><span class="ic">${fl(icon)}</span>
    <div class="grow">${title}${sub ? `<small>${sub}</small>` : ''}</div>${right}</div>`;
  function settings11(el, win) {
    const page = win.page || 'home', top = page === 'ethernet' || page === 'advanced' ? 'network' : page;
    el.innerHTML = `<div class="wn-set"><nav><div class="me">${ICON.user(60)}<div><b>Utilisateur</b><small>Compte local</small></div></div>
      <div class="find">Rechercher un paramètre ${ICON.search(14)}</div>${NAV11.map(([id, , label]) => `<a data-p="${id}" class="${id === top ? 'on' : ''}"><i>${fl(id)}</i>${label}</a>`).join('')}</nav><main></main></div>`;
    el.querySelectorAll('[data-p]').forEach(a => { a.onclick = () => goPage(win, a.dataset.p); });
    const main = el.querySelector('main'), port = win.port || ports()[0];
    if (page === 'network') {
      main.innerHTML = `<h1>Réseau et Internet</h1><div class="wn-hero">${ICON.pc(72)}<div><b>${h(nic(port))}</b><span class="st">${cabled(port) ? access(port) === 'Internet'
        ? 'Connecté' : 'Connecté · ' + h(access(port)) : disabled(port) ? 'Désactivé' : 'Non connecté'}</span></div><span style="flex:1"></span>
        <div style="display:flex;gap:8px"><button class="wn-mbtn" data-eth="${h(port)}">${fl('info', 16)} Propriétés</button><button class="wn-mbtn" data-usage="1">${fl('usage', 16)} Utilisation des données<br>
        <small style="color:#5b5b5b">${running() ? '12 Mo' : '0 Mo'}, 30 derniers jours</small></button></div></div>
        ${ports().map(p => row('ethernet', h(nic(p)), 'Authentification, IP et paramètres DNS, réseaux limités', '<span class="chev">›</span>', `data-eth="${h(p)}"`)).join('')}
        ${row('vpn', 'VPN', 'Ajouter, se connecter, gérer', undefined, 'data-x="VPN"')}${row('proxy', 'Proxy', 'Serveur proxy pour les connexions Ethernet et Wi-Fi', undefined, 'data-x="Proxy"')}
        ${row('dial', 'Accès à distance', 'Configurer une connexion Internet à distance', undefined, 'data-x="Accès à distance"')}
        ${row('advanced', 'Paramètres réseau avancés', 'Afficher toutes les cartes réseau, réinitialisation du réseau', undefined, 'data-adv="1"')}`;
      main.querySelectorAll('[data-eth]').forEach(c => { c.onclick = () => goPage(win, 'ethernet', {port: c.dataset.eth}); });
      main.querySelectorAll('[data-x]').forEach(c => { c.onclick = () => later(c.dataset.x); });
      main.querySelector('[data-usage]').onclick = () => later('Utilisation des données');
      main.querySelector('[data-adv]').onclick = () => goPage(win, 'advanced');
    } else if (page === 'ethernet') {
      const manual = !dhcp(port) && Boolean(address(port)), profile = win.profile || 'public';
      main.innerHTML = `<h1><a data-back="1">Réseau et Internet</a><small>›</small>${h(nic(port))}</h1>
        <div class="wn-card exp"><div class="head"><span class="ic">${fl('profile')}</span><div class="grow">Type de profil réseau<small>${profile === 'public' ? 'Public (recommandé)' : 'Privé'}</small></div></div>
          <div class="rows"><label><input type="radio" name="prof" value="public"${profile === 'public' ? ' checked' : ''}><span>Public (recommandé)<small>Votre appareil n’est pas détectable sur le réseau.
          Utilisez ce paramètre dans la plupart des cas : à la maison, au travail ou dans un lieu public.</small></span></label><label><input type="radio" name="prof" value="private"${profile === 'private'
            ? ' checked' : ''}><span>Privé<small>Votre appareil est détectable sur le réseau. Sélectionnez ce paramètre si vous avez besoin de partager des fichiers ou d’utiliser des applications
          qui communiquent sur ce réseau.</small></span></label></div></div>
        ${row('auth', 'Paramètres d’authentification', 'Authentification 802.1X', '<button class="wn-mbtn" data-na="802.1X">Modifier</button>')}
        ${row('metered', 'Connexion limitée', 'Certaines applications peuvent fonctionner différemment pour réduire l’utilisation des données lorsque vous êtes connecté à ce réseau',
          `<span class="val">${win.metered ? 'Activé' : 'Désactivé'}</span>${toggle(win.metered)}`, 'data-metered="1"')}
        ${row('ip', 'Attribution d’adresse IP :', '', `<span class="val">${manual ? 'Manuel' : 'Automatique (DHCP)'}</span><button class="wn-mbtn edit">Modifier</button>`)}
        ${row('dns', 'Attribution du serveur DNS :', '', '<span class="val">Automatique (DHCP)</span><button class="wn-mbtn" data-na="DNS">Modifier</button>')}
        <div class="wn-card exp wn-props-card"><button class="wn-mbtn copy">Copier</button><div class="wn-props" style="grid-template-columns:330px 1fr;padding:16px 18px">${[
          ['Vitesse de liaison (réception/transmission) :', cabled(port) ? '1000/1000 (Mbits/s)' : '—'],
          ...(manual ? [['Adresse IPv4 :', ip(port)], ['Masque de sous-réseau IPv4 :', mask(port)], ['Passerelle IPv4 :', gateway() || '—']] : [['Adresse IPv4 :', dhcp(port) && cabled(port) ? '(bail DHCP)' : '—']]),
          ['Serveurs DNS IPv4 :', '—'], ['Fabricant :', 'Network LABS'], ['Description :', ADAPTER], ['Version du pilote :', '100.94.104.26100'], ['Adresse physique (MAC) :', mac(port)]]
          .map(([k, val]) => `<span>${k}</span><b>${h(val)}</b>`).join('')}</div></div>`;
      main.querySelector('[data-back]').onclick = () => goPage(win, 'network');
      main.querySelectorAll('input[name=prof]').forEach(r => { r.onchange = () => { win.profile = r.value; render(); }; });
      main.querySelectorAll('[data-na]').forEach(b => { b.onclick = () => later(b.dataset.na); });
      main.querySelector('[data-metered]').onclick = () => { win.metered = !win.metered; render(); };
      main.querySelector('.copy').onclick = () => toast('Propriétés copiées dans le Presse-papiers.');
      main.querySelector('.edit').onclick = () => editIpModern(main, port, 'mask');
    } else if (page === 'advanced') {
      main.innerHTML = `<h1><a data-back="1">Réseau et Internet</a><small>›</small>Paramètres réseau avancés</h1><div class="wn-sec">Cartes réseau</div>
        ${ports().map(p => row('ethernet', h(nic(p)), h(ADAPTER), `<button class="wn-mbtn" data-dis="${h(p)}">${disabled(p) ? 'Activer' : 'Désactiver'}</button>`)).join('')}
        <div class="wn-sec">Paramètres associés</div>${row('advanced', 'Plus d’options de carte réseau', '', '<span class="chev">↗</span>', 'data-ncpa="1"')}
        ${row('info', 'Centre Réseau et partage', '', '<span class="chev">↗</span>', 'data-net="1"')}`;
      main.querySelector('[data-back]').onclick = () => goPage(win, 'network');
      main.querySelector('[data-ncpa]').onclick = () => openWin('cpl', {page: 'ncpa'});
      main.querySelector('[data-net]').onclick = () => openWin('cpl', {page: 'net'});
      main.querySelectorAll('[data-dis]').forEach(b => { b.onclick = () => K.attempt(() => setEnabled(b.dataset.dis, disabled(b.dataset.dis)), 'Carte réseau modifiée.'); });
    } else if (page === 'system' || page === 'home') {
      main.innerHTML = `<h1>${page === 'home' ? 'Accueil' : 'Système'}</h1><div class="wn-hero">${ICON.pc(76)}<div><b>${h(N().name)}</b><span class="st">${h(D().model)} · machine virtuelle</span><br>
        <a class="wn-link10 ren" style="color:#005fb8">Renommer</a></div></div>
        ${[['system', 'Affichage', 'Moniteurs, luminosité, éclairage nocturne, profil d’affichage'], ['bt', 'Son', 'Niveaux de volume, sortie, entrée, périphériques audio'],
          ['update', 'Notifications', 'Alertes des applications et du système'], ['metered', 'Alimentation', 'Veille, utilisation de la batterie'],
          ['advanced', 'Stockage', 'Espace de stockage, lecteurs, règles de configuration'], ['info', 'Informations système', 'Spécifications de l’appareil, renommer le PC, spécifications de Windows']]
          .map(([icon, t, sub]) => row(icon, t, sub, undefined, `data-sys="${t}"`)).join('')}`;
      main.querySelector('.ren').onclick = () => renameModern(main);
      main.querySelectorAll('[data-sys]').forEach(c => { c.onclick = () => (c.dataset.sys === 'Informations système' ? renameModern(main) : later(c.dataset.sys)); });
    } else {
      const label = (NAV11.find(([id]) => id === page) || [0, 0, 'Paramètres'])[2];
      main.innerHTML = `<h1>${h(label)}</h1>${row(page, 'Cette page existe dans Windows ; elle n’est pas reliée au laboratoire.', 'Réseau et Internet et Système le sont.', '')}`;
    }
  }
  // « Modifier les paramètres IP »: Windows 11 asks for a subnet mask, Windows 10 for a prefix length.
  function editIpModern(main, port, kind) {
    const shade = document.createElement('div');
    shade.className = 'wn-shade';
    const manual = !dhcp(port) && Boolean(address(port));
    shade.innerHTML = `<div class="wn-cd"><div class="b"><h3>Modifier les paramètres IP</h3><select class="mode"><option value="dhcp">Automatique (DHCP)</option>
      <option value="static"${manual ? ' selected' : ''}>Manuel</option></select><div class="man"><div class="tg"><b style="font-weight:600">IPv4</b></div><div class="tg">${toggle(true)}Activé</div>
      <label>Adresse IP</label><input type="text" class="a" value="${h(ip(port))}"><label>${kind === 'mask' ? 'Masque de sous-réseau' : 'Longueur du préfixe de sous-réseau'}</label>
      <input type="text" class="m" value="${h(kind === 'mask' ? mask(port) : address(port) ? String(lenOf(address(port))) : '')}"><label>Passerelle</label><input type="text" class="g" value="${h(gateway())}">
      <label>DNS préféré</label><input type="text" disabled placeholder="non géré par le laboratoire"><div class="tg" style="margin-top:18px"><b style="font-weight:600">IPv6</b></div>
      <div class="tg">${toggle(false)}Désactivé</div></div><div class="wn-err"></div></div>
      <div class="f"><button class="wn-mbtn acc save">Enregistrer</button><button class="wn-mbtn cancel">Annuler</button></div></div>`;
    const sync = () => { shade.querySelector('.man').style.display = shade.querySelector('.mode').value === 'static' ? '' : 'none'; };
    shade.querySelector('.mode').onchange = sync;
    sync();
    shade.querySelector('.cancel').onclick = () => shade.remove();
    shade.querySelector('.save').onclick = async () => {
      const b = shade.querySelector('.save');
      b.disabled = true;
      try { await saveIp(port, shade.querySelector('.mode').value, shade.querySelector('.a').value.trim(), shade.querySelector('.m').value.trim(), shade.querySelector('.g').value.trim()); render(); }
      catch (error) { shade.querySelector('.wn-err').textContent = error.message; b.disabled = false; }
    };
    main.closest('.wn-body').append(shade);
    shade.querySelector('select').focus();
  }
  function renameModern(main) {
    const shade = document.createElement('div');
    shade.className = 'wn-shade';
    shade.innerHTML = `<div class="wn-cd"><div class="b"><h3>Renommer votre PC</h3>Nom actuel du PC : ${h(N().name)}<label>Entrer un nouveau nom</label><input type="text" class="n" value="${h(N().name)}">
      <div class="wn-err"></div></div><div class="f"><button class="wn-mbtn acc ok">Suivant</button><button class="wn-mbtn cancel">Annuler</button></div></div>`;
    shade.querySelector('.cancel').onclick = () => shade.remove();
    shade.querySelector('.ok').onclick = async () => {
      try { await rename(shade.querySelector('.n').value.trim()); render(); toast('Le nouveau nom s’appliquera au prochain démarrage du lab.'); }
      catch (error) { shade.querySelector('.wn-err').textContent = error.message; }
    };
    main.closest('.wn-body').append(shade);
    shade.querySelector('.n').select();
  }

  /* =============================== Settings (Windows 10) =============================== */
  const HOME10 = [['system', 'Système', 'Affichage, son, notifications, alimentation'], ['devices', 'Périphériques', 'Bluetooth, imprimantes, souris'],
    ['network', 'Réseau et Internet', 'Wi-Fi, mode Avion, VPN'], ['perso', 'Personnalisation', 'Arrière-plan, écran de verrouillage, couleurs'],
    ['apps', 'Applications', 'Désinstaller, valeurs par défaut, fonctionnalités facultatives'], ['accounts', 'Comptes', 'Vos comptes, e-mail, synchronisation, travail, famille'],
    ['time', 'Heure et langue', 'Voix, région, date'], ['access', 'Options d’ergonomie', 'Narrateur, loupe, contraste élevé'],
    ['privacy', 'Confidentialité', 'Emplacement, caméra, microphone'], ['update', 'Mise à jour et sécurité', 'Windows Update, récupération, sauvegarde']];
  function settings10(el, win) {
    const page = win.page || 'home';
    if (page === 'home') {
      el.innerHTML = `<div style="text-align:center;padding:26px 0 0;font-size:28px;font-weight:300">Paramètres Windows</div><div style="text-align:center;margin:14px"><span class="wn-search10"
        style="display:inline-flex;width:360px;background:#fff;border:1px solid #999">Rechercher un paramètre ${ICON.search(14)}</span></div><div class="wn-home10">${HOME10.map(([id, t, s]) =>
          `<a data-p="${id}">${ICON[id === 'network' ? 'network' : id === 'system' ? 'pc' : 'settings'](32)}<span><b>${t}</b><small>${s}</small></span></a>`).join('')}</div>`;
      el.querySelectorAll('[data-p]').forEach(a => { a.onclick = () => { win.page = a.dataset.p === 'network' ? 'status' : a.dataset.p === 'system' ? 'about' : a.dataset.p; render(); }; });
      return;
    }
    const net = ['status', 'ethernet', 'eth'].includes(page), port = win.port || ports()[0];
    const nav = net ? [['status', 'État'], ['ethernet', 'Ethernet'], ['dial', 'Accès à distance'], ['vpn', 'VPN'], ['proxy', 'Proxy']]
      : page === 'about' ? [['display', 'Affichage'], ['sound', 'Son'], ['power', 'Alimentation et mise en veille'], ['storage', 'Stockage'], ['about', 'Informations système']] : [];
    el.innerHTML = `<div class="wn-set"><nav><a data-home="1">⌂ Accueil</a><div class="find">Rechercher un paramètre ${ICON.search(14)}</div><div class="grp">${net ? 'Réseau et Internet'
      : page === 'about' ? 'Système' : ''}</div>${nav.map(([id, t]) => `<a data-p="${id}" class="${id === page || (id === 'ethernet' && page === 'eth') ? 'on' : ''}">${t}</a>`).join('')}</nav><main></main></div>`;
    el.querySelector('[data-home]').onclick = () => { win.page = 'home'; render(); };
    el.querySelectorAll('[data-p]').forEach(a => { a.onclick = () => { if (['status', 'ethernet', 'about'].includes(a.dataset.p)) { win.page = a.dataset.p; render(); } else later(a.textContent); }; });
    const main = el.querySelector('main');
    if (page === 'status') {
      main.innerHTML = `<h1>État</h1><div class="wn-sec" style="margin-top:0">État du réseau</div><div style="display:flex;align-items:center;gap:14px;margin:14px 0">${ICON.pc(56)}
        <span style="flex:none;width:80px;border-top:2px ${cabled(port) ? 'solid' : 'dashed'} #555"></span>${ICON.network(40)}</div><div style="font-size:20px;font-weight:300">${cabled(port)
          ? access(port) === 'Internet' ? 'Vous êtes connecté à Internet' : 'Vous n’êtes pas connecté à Internet' : 'Non connecté'}</div>
        <p style="color:#555">${h(nic(port))} · ${cabled(port) ? 'Réseau non identifié · Réseau public' : 'Câble réseau non connecté'}</p>
        <div class="wn-sec">Modifier vos paramètres réseau</div><div class="wn-card link" data-ncpa="1">${ICON.network(24)}<div class="grow">Modifier les options d’adaptateur
        <small>Afficher les cartes réseau et modifier les paramètres de connexion.</small></div></div><div class="wn-card link" data-net="1">${ICON.cpl(24)}<div class="grow">Centre Réseau et partage
        <small>Pour les réseaux auxquels vous vous connectez, choisissez ce que vous voulez partager.</small></div></div>`;
      main.querySelector('[data-ncpa]').onclick = () => openWin('cpl', {page: 'ncpa'});
      main.querySelector('[data-net]').onclick = () => openWin('cpl', {page: 'net'});
    } else if (page === 'ethernet') {
      main.innerHTML = `<h1>Ethernet</h1>${ports().map(p => `<div class="wn-card link" data-eth="${h(p)}">${cabled(p) ? ICON.ethernet(28) : ICON.offline(28)}<div class="grow">${h(nic(p))}
        <small>${cabled(p) ? 'Réseau non identifié' : disabled(p) ? 'Désactivé' : 'Non connecté'}</small></div></div>`).join('')}<div class="wn-sec">Paramètres associés</div>
        <p><a class="wn-link10" data-ncpa="1">Modifier les options d’adaptateur</a></p><p><a class="wn-link10" data-net="1">Centre Réseau et partage</a></p>`;
      main.querySelectorAll('[data-eth]').forEach(c => { c.onclick = () => { win.page = 'eth'; win.port = c.dataset.eth; render(); }; });
      main.querySelector('[data-ncpa]').onclick = () => openWin('cpl', {page: 'ncpa'});
      main.querySelector('[data-net]').onclick = () => openWin('cpl', {page: 'net'});
    } else if (page === 'eth') {
      main.innerHTML = `<h1>${h(nic(port))}</h1><div class="wn-sec">Paramètres IP</div><p>Attribution d’adresse IP :<br><b style="font-weight:normal">${dhcp(port) || !address(port) ? 'Automatique (DHCP)' : 'Manuel'}</b></p>
        <button class="wn-mbtn edit">Modifier</button><div class="wn-sec">Propriétés</div><div class="wn-props" style="padding:0">${[['Vitesse de liaison (réception/transmission) :',
          cabled(port) ? '1000/1000 (Mbits/s)' : '—'], ['Adresse IPv4 :', dhcp(port) ? '(attribuée par le serveur DHCP)' : ip(port) || '—'], ['Serveurs DNS IPv4 :', '—'],
          ['Fabricant :', 'Network LABS'], ['Description :', ADAPTER], ['Adresse physique (MAC) :', mac(port)]].map(([k, val]) => `<span>${k}</span><b>${h(val)}</b>`).join('')}</div>
        <p><button class="wn-mbtn copy">Copier</button></p>`;
      main.querySelector('.edit').onclick = () => editIpModern(main, port, 'prefix');
      main.querySelector('.copy').onclick = () => toast('Propriétés copiées.');
    } else if (page === 'about') {
      main.innerHTML = `<h1>Informations système</h1><div class="wn-sec">Spécifications de l’appareil</div><div class="wn-props" style="padding:0">${[['Nom de l’appareil', N().name],
        ['Processeur', `${N().vcpus || 1} processeur(s) virtuel(s)`], ['Mémoire RAM installée', `${N().memory_mib || 512} Mo`], ['Type du système', 'Système d’exploitation 64 bits']]
        .map(([k, val]) => `<span>${k}</span><b>${h(val)}</b>`).join('')}</div><p><button class="wn-mbtn ren">Renommer ce PC</button></p><div class="wn-sec">Spécifications de Windows</div>
        <div class="wn-props" style="padding:0"><span>Édition</span><b>${h(D().model)}</b><span>Version</span><b>${SERVER() ? '21H2' : '22H2'}</b></div>`;
      main.querySelector('.ren').onclick = () => renameModern(main);
    } else {
      main.innerHTML = `<h1>Paramètres</h1><p>Cette page existe dans Windows ; elle n’est pas reliée au laboratoire.</p>`;
    }
  }

  /* =============================== Control Panel, network and sharing, network connections =============================== */
  function controlPanel(el, win) {
    const page = win.page || 'home';
    const crumbs = {home: ['Panneau de configuration'], net: ['Panneau de configuration', 'Réseau et Internet', 'Centre Réseau et partage'],
      ncpa: ['Panneau de configuration', 'Réseau et Internet', 'Connexions réseau']}[page];
    el.innerHTML = `<div class="wn-addr"><span class="nav">← → ↑</span><span class="path">${ICON.cpl(16)} ${crumbs.map((c, i) => `<a data-c="${i}">${c}</a>`).join(' › ')}</span>
      <span class="find">Rechercher dans : ${crumbs[crumbs.length - 1]}</span></div><div class="cp"></div>`;
    el.querySelectorAll('[data-c]').forEach(a => { a.onclick = () => { win.page = a.dataset.c === '0' ? 'home' : 'net'; render(); }; });
    const box = el.querySelector('.cp'), port = ports()[0];
    if (page === 'home') {
      box.innerHTML = `<div class="wn-cpl" style="grid-template-columns:1fr"><main><h2>Ajuster les paramètres de l’ordinateur</h2><div class="wn-cats">${[
        ['Système et sécurité', 'Vérifier l’état de votre ordinateur · Sauvegarder et restaurer'], ['Comptes d’utilisateurs', 'Modifier le type de compte'],
        ['Réseau et Internet', 'Afficher l’état et la gestion du réseau'], ['Apparence et personnalisation', ''], ['Matériel et audio', 'Afficher les périphériques et imprimantes'],
        ['Horloge et région', 'Modifier les formats de date, d’heure ou de nombre'], ['Programmes', 'Désinstaller un programme'], ['Options d’ergonomie', 'Laisser Windows suggérer les paramètres']]
        .map(([t, s]) => `<div class="wn-cat">${t === 'Réseau et Internet' ? ICON.network(40) : ICON.cpl(40)}<div><b class="lk" data-cat="${t}">${t}</b>${s ? `<small data-cat="${t}">${s}</small>` : ''}</div></div>`)
        .join('')}</div></main></div>`;
      box.querySelectorAll('[data-cat]').forEach(a => { a.style.cursor = 'default'; a.onclick = () => { if (a.dataset.cat === 'Réseau et Internet') { win.page = 'net'; render(); } else later(a.dataset.cat); }; });
    } else if (page === 'net') {
      box.innerHTML = `<div class="wn-cpl"><nav><b>Page d’accueil du panneau de configuration</b><a data-ncpa="1">Modifier les paramètres de la carte</a>
        <a data-na="1">Modifier les paramètres de partage avancés</a><a data-na="1">Options de diffusion multimédia en continu</a></nav><main>
        <h2>Afficher les informations de base de votre réseau et configurer des connexions</h2><div style="color:#1e3287">Afficher vos réseaux actifs</div>
        ${ports().some(cabled) ? ports().filter(cabled).map(p => `<div class="wn-active"><div>${ICON.network(28)}<br><b style="font-weight:normal">Réseau non identifié</b><br>Réseau public</div>
          <div>Type d’accès : ${h(access(p))}<br>Connexions : ${ICON.ethernet(14)} <a class="lk" data-st="${h(p)}">${h(nic(p))}</a></div></div>`).join('')
          : '<div class="wn-active" style="grid-template-columns:1fr">Vous n’êtes connecté à aucun réseau.</div>'}
        <div style="color:#1e3287;margin-top:14px">Modifier vos paramètres réseau</div><p><a class="lk" data-na="1">Configurer une nouvelle connexion ou un nouveau réseau</a><br>
        Configurer une connexion haut débit, d’accès à distance ou VPN, ou configurer un routeur ou un point d’accès.</p><p><a class="lk" data-na="1">Résoudre les problèmes</a><br>
        Diagnostiquer et réparer les problèmes de réseau, ou obtenir des informations de dépannage.</p></main></div>`;
      box.querySelector('[data-ncpa]').onclick = () => { win.page = 'ncpa'; render(); };
      box.querySelectorAll('[data-na]').forEach(a => { a.onclick = () => later(a.textContent.trim()); });
      box.querySelectorAll('[data-st]').forEach(a => { a.onclick = () => openWin('status', {port: a.dataset.st, parent: win.id}); });
    } else {
      const sel = win.sel === undefined ? null : win.sel;
      const commands = sel === null ? [['Organiser ▾']] : [['Organiser ▾'], [disabled(sel) ? 'Activer ce périphérique réseau' : 'Désactiver ce périphérique réseau', 'dis'],
        ['Diagnostiquer cette connexion'], ['Renommer cette connexion'], ['Afficher le statut de cette connexion', 'st'], ['Modifier les paramètres de cette connexion', 'pr']];
      box.innerHTML = `<div class="wn-cmdbar">${commands.map(([t, a]) => `<a data-a="${a || ''}">${t}</a>`).join('')}</div><div class="ads">${ports().map(p => {
        const state = disabled(p) ? 'disabled' : cabled(p) ? 'ok' : 'off';
        return `<div class="wn-ad${sel === p ? ' sel' : ''}" data-ad="${h(p)}">${ICON.adapter(48, state)}<div>${h(nic(p))}<small>${disabled(p) ? 'Désactivé' : cabled(p)
          ? 'Réseau non identifié' : 'Câble réseau non connecté'}</small><small>${h(ADAPTER)}</small></div></div>`; }).join('')}</div>`;
      box.querySelectorAll('[data-ad]').forEach(ad => {
        ad.onclick = event => { event.stopPropagation(); win.sel = ad.dataset.ad; render(); };
        ad.ondblclick = () => openWin(cabled(ad.dataset.ad) ? 'status' : 'props', {port: ad.dataset.ad, parent: win.id});
        ad.oncontextmenu = event => { event.preventDefault(); win.sel = ad.dataset.ad; const p = ad.dataset.ad;
          context(document.querySelector('.px-app'), event, [[disabled(p) ? 'Activer' : 'Désactiver', () => K.attempt(() => setEnabled(p, disabled(p)), 'Carte réseau modifiée.')],
            ['Statut', () => openWin('status', {port: p, parent: win.id})], ['Diagnostiquer', null], ['-'], ['Renommer', null], ['-'], ['Propriétés', () => openWin('props', {port: p, parent: win.id})]]); };
      });
      box.querySelectorAll('[data-a]').forEach(a => { a.onclick = event => {
        event.stopPropagation();
        if (a.dataset.a === 'dis') K.attempt(() => setEnabled(sel, disabled(sel)), 'Carte réseau modifiée.');
        else if (a.dataset.a === 'st') { if (cabled(sel)) openWin('status', {port: sel, parent: win.id}); else toast('Câble réseau non connecté.', true); }
        else if (a.dataset.a === 'pr') openWin('props', {port: sel, parent: win.id});
        else later(a.textContent);
      }; });
      box.onclick = () => { if (win.sel !== null && win.sel !== undefined) { win.sel = null; render(); } };
    }
  }
  function statusDlg(el, win) {
    const p = win.port;
    el.innerHTML = `<div class="wn-tabs"><a class="on">Général</a></div><div class="wn-page"><div class="wn-grp"><span class="lg">Connexion</span>
      <table style="width:100%">${[['Connectivité IPv4 :', access(p)], ['Connectivité IPv6 :', 'Pas d’accès réseau'], ['État du média :', disabled(p) ? 'Désactivé' : 'Activé'],
        ['Durée :', running() ? '00:12:41' : '00:00:00'], ['Vitesse :', '1,0 Gbits/s']].map(([k, val]) => `<tr><td>${k}</td><td style="text-align:right">${h(val)}</td></tr>`).join('')}</table>
      <div style="margin-top:8px"><button class="wn-btn det">Détails...</button></div></div><div class="wn-grp"><span class="lg">Activité</span>
      <table style="width:100%"><tr><td></td><td style="text-align:center">Envoyés —</td><td style="text-align:center">— Reçus</td></tr><tr><td>Octets :</td><td style="text-align:center">${running()
        ? '18 433' : '0'}</td><td style="text-align:center">${running() ? '21 096' : '0'}</td></tr></table></div>
      <div style="display:flex;gap:6px;margin-top:10px"><button class="wn-btn pr">Propriétés</button><button class="wn-btn dis">Désactiver</button><button class="wn-btn" data-na="1">Diagnostiquer</button></div></div>
      <div class="wn-btns"><button class="wn-btn def close">Fermer</button></div>`;
    el.querySelector('.det').onclick = () => openWin('details', {port: p, parent: win.id});
    el.querySelector('.pr').onclick = () => openWin('props', {port: p, parent: win.id});
    el.querySelector('.dis').onclick = () => K.attempt(async () => { await setEnabled(p, false); closeWin(win.id); }, 'Carte réseau désactivée.');
    el.querySelector('[data-na]').onclick = () => later('Diagnostiquer');
    el.querySelector('.close').onclick = () => closeWin(win.id);
  }
  function detailsDlg(el, win) {
    const p = win.port;
    const rows = [['Suffixe DNS propre à la connexion', ''], ['Description', ADAPTER], ['Adresse physique', mac(p)], ['DHCP activé', dhcp(p) ? 'Oui' : 'Non'],
      ...(dhcp(p) ? [['Adresse IPv4', '(bail DHCP au démarrage)']] : address(p) ? [['Adresse IPv4', ip(p)], ['Masque de sous-réseau IPv4', mask(p)]] : []),
      ['Passerelle par défaut IPv4', dhcp(p) ? '' : gateway()], ['Serveurs DNS IPv4', ''], ['Serveur WINS IPv4', ''], ['NetBIOS sur Tcpip activé', 'Oui']];
    el.innerHTML = `<div>Détails de la connexion réseau :</div><table class="wn-kv" style="margin-top:6px"><tr><th>Propriété</th><th>Valeur</th></tr>${rows.map(([k, val]) =>
      `<tr><td>${h(k)}</td><td>${h(val)}</td></tr>`).join('')}</table><div class="wn-btns"><button class="wn-btn def close">Fermer</button></div>`;
    el.querySelector('.close').onclick = () => closeWin(win.id);
  }
  const ITEMS = [['Client pour les réseaux Microsoft', true], ['Partage de fichiers et imprimantes Réseaux Microsoft', true], ['Planificateur de paquets QoS', true],
    ['Protocole Internet version 4 (TCP/IPv4)', true], ['Protocole de multiplexage de carte réseau Microsoft', false], ['Pilote de protocole LLDP Microsoft', true],
    ['Protocole Internet version 6 (TCP/IPv6)', true], ['Répondeur de découverte de la topologie de la couche de liaison', true],
    ['Pilote E/S de mappage de découverte de topologie de la couche de liaison', true]];
  function propsDlg(el, win) {
    const p = win.port, chosen = win.item === undefined ? 3 : win.item;
    el.innerHTML = `<div class="wn-tabs"><a class="on">Gestion de réseau</a><a>Partage</a></div><div class="wn-page">Connexion en utilisant :
      <div style="display:flex;gap:8px;margin:6px 0 10px;align-items:center"><div style="flex:1;border:1px solid #adadad;background:#fff;padding:3px 6px">${ICON.ethernet(14)} ${h(ADAPTER)}</div>
      <button class="wn-btn" data-na="1">Configurer...</button></div>Cette connexion utilise les éléments suivants :<div class="wn-list">${ITEMS.map(([t, on], i) =>
        `<div data-i="${i}" class="${i === chosen ? 'sel' : ''}"><input type="checkbox" ${on ? 'checked' : ''} disabled> ${h(t)}</div>`).join('')}</div>
      <div style="display:flex;gap:8px;margin-top:8px"><button class="wn-btn" data-na="1">Installer...</button><button class="wn-btn" disabled>Désinstaller</button>
        <button class="wn-btn prop"${chosen === 3 || chosen === 6 ? '' : ' disabled'}>Propriétés</button></div><div class="wn-grp" style="margin-top:12px"><span class="lg">Description</span>
        ${chosen === 3 ? 'Protocole TCP/IP (Transmission Control Protocol/Internet Protocol). Le protocole de réseau étendu par défaut qui permet la communication entre différents réseaux interconnectés.'
          : chosen === 6 ? 'Protocole TCP/IP version 6. Non relié au laboratoire.' : 'Composant de Windows, sans effet dans le laboratoire.'}</div>
      <div class="wn-err"></div></div><div class="wn-btns"><button class="wn-btn def ok">OK</button><button class="wn-btn cancel">Annuler</button></div>`;
    el.querySelectorAll('[data-i]').forEach(row => { row.onclick = () => { win.item = Number(row.dataset.i); render(); };
      row.ondblclick = () => { if (Number(row.dataset.i) === 3) openWin('ipv4', {port: p, parent: win.id}); }; });
    el.querySelectorAll('[data-na]').forEach(b => { b.onclick = () => later(b.textContent); });
    el.querySelector('.prop').onclick = () => (chosen === 3 ? openWin('ipv4', {port: p, parent: win.id}) : later('IPv6'));
    el.querySelector('.cancel').onclick = () => { delete win.pending; closeWin(win.id); };
    // As in Windows, the TCP/IPv4 dialog's OK keeps the values; this window's OK applies them.
    el.querySelector('.ok').onclick = async () => {
      if (!win.pending) return closeWin(win.id);
      const x = win.pending, ok = el.querySelector('.ok');
      ok.disabled = true;
      try { await saveIp(p, x.mode, x.ip, x.mask, x.gw); closeWin(win.id); }
      catch (error) { el.querySelector('.wn-err').textContent = error.message; ok.disabled = false; }
    };
  }
  // The four-box address field of Windows' classic dialogs: digits only, « . » or a full box moves to the next one.
  const ipBox = (cls, value) => `<span class="wn-ipbox ${cls}">${[0, 1, 2, 3].map(i => `<input maxlength="3" value="${h((value || '').split('.')[i] || '')}">${i < 3 ? '<span>.</span>' : ''}`).join('')}</span>`;
  const ipValue = box => { const parts = [...box.querySelectorAll('input')].map(i => i.value.trim()); return parts.every(x => x === '') ? '' : parts.join('.'); };
  function wireIp(root) {
    root.querySelectorAll('.wn-ipbox').forEach(box => {
      const inputs = [...box.querySelectorAll('input')];
      inputs.forEach((input, i) => {
        input.addEventListener('keydown', event => {
          if ((event.key === '.' || event.key === ' ') && i < 3) { event.preventDefault(); if (input.value) inputs[i + 1].focus(), inputs[i + 1].select(); }
          else if (event.key === 'Backspace' && !input.value && i > 0) inputs[i - 1].focus();
          else if (event.key.length === 1 && !/\d/.test(event.key)) event.preventDefault();
        });
        input.addEventListener('input', () => {
          if (Number(input.value) > 255) { input.value = '255'; toast(`${input.value} n’est pas une entrée valide. Spécifiez une valeur comprise entre 1 et 255.`, true); }
          if (input.value.length === 3 && i < 3) { inputs[i + 1].focus(); inputs[i + 1].select(); }
        });
      });
    });
  }
  function ipv4Dlg(el, win) {
    const parent = V().wins.find(x => x.id === win.parent) || {}, p = win.port, held = parent.pending;
    const manual = held ? held.mode === 'static' : !dhcp(p) && Boolean(address(p));
    const values = held || {ip: ip(p), mask: mask(p), gw: gateway()};
    el.innerHTML = `<div class="wn-tabs"><a class="on">Général</a>${manual ? '' : '<a>Configuration alternative</a>'}</div><div class="wn-page">
      <div>Les paramètres IP peuvent être déterminés automatiquement si votre réseau le permet. Sinon, vous devez demander les paramètres IP appropriés à votre administrateur réseau.</div>
      <label class="wn-rad" style="margin-top:12px"><input type="radio" name="v4" value="dhcp"${manual ? '' : ' checked'}>Obtenir une adresse IP automatiquement</label>
      <div class="wn-grp" style="margin-top:6px;padding-top:2px"><label class="wn-rad lg" style="top:-10px;margin:0"><input type="radio" name="v4" value="static"${manual ? ' checked' : ''}>Utiliser l’adresse IP suivante :</label>
        <div class="wn-fld m" style="margin-top:14px"><span>Adresse IP :</span>${ipBox('a', values.ip)}</div><div class="wn-fld m"><span>Masque de sous-réseau :</span>${ipBox('k', values.mask)}</div>
        <div class="wn-fld m"><span>Passerelle par défaut :</span>${ipBox('g', values.gw)}</div></div>
      <label class="wn-rad" style="margin-top:12px"><input type="radio" name="d4" ${manual ? 'disabled' : 'checked'}>Obtenir les adresses des serveurs DNS automatiquement</label>
      <div class="wn-grp" style="margin-top:6px;padding-top:2px"><label class="wn-rad lg" style="top:-10px;margin:0"><input type="radio" name="d4" ${manual ? 'checked' : ''}>Utiliser l’adresse de serveur DNS suivante :</label>
        <div class="wn-fld off" style="margin-top:14px"><span>Serveur DNS préféré :</span>${ipBox('d1', '')}</div><div class="wn-fld off"><span>Serveur DNS auxiliaire :</span>${ipBox('d2', '')}</div></div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px"><label class="wn-chk"><input type="checkbox">Valider les paramètres en quittant</label>
        <button class="wn-btn" data-na="1">Avancé...</button></div><div class="wn-err"></div></div>
      <div class="wn-btns"><button class="wn-btn def ok">OK</button><button class="wn-btn cancel">Annuler</button></div>`;
    wireIp(el);
    el.querySelectorAll('.wn-fld.off input').forEach(i => { i.disabled = true; });
    const sync = () => {
      const on = el.querySelector('input[name=v4]:checked').value === 'static';
      el.querySelectorAll('.wn-fld.m').forEach(f => { f.classList.toggle('off', !on); f.querySelectorAll('input').forEach(i => { i.disabled = !on; }); });
    };
    el.querySelectorAll('input[name=v4]').forEach(r => { r.onchange = sync; });
    sync();
    // Windows fills in the mask of the address's class when the address is left: 255.0.0.0, 255.255.0.0 or 255.255.255.0.
    el.querySelector('.wn-ipbox.a').addEventListener('focusout', () => {
      const a = ipValue(el.querySelector('.wn-ipbox.a')), k = el.querySelector('.wn-ipbox.k');
      if (!validIp(a) || ipValue(k)) return;
      const first = Number(a.split('.')[0]), fill = first < 128 ? '255.0.0.0' : first < 192 ? '255.255.0.0' : '255.255.255.0';
      fill.split('.').forEach((x, i) => { k.querySelectorAll('input')[i].value = x; });
    });
    el.querySelector('[data-na]').onclick = () => later('Paramètres TCP/IP avancés');
    el.querySelector('.cancel').onclick = () => closeWin(win.id);
    el.querySelector('.ok').onclick = () => {
      const mode = el.querySelector('input[name=v4]:checked').value, x = {mode, ip: ipValue(el.querySelector('.a')), mask: ipValue(el.querySelector('.k')), gw: ipValue(el.querySelector('.g'))};
      const err = el.querySelector('.wn-err');
      if (mode === 'static') {
        if (!validIp(x.ip)) return void (err.textContent = 'L’adresse IP entrée n’est pas valide.');
        if (prefixOf(x.mask) === null) return void (err.textContent = 'Le masque de sous-réseau entré n’est pas valide.');
        if (x.gw && !validIp(x.gw)) return void (err.textContent = 'La passerelle par défaut entrée n’est pas valide.');
      }
      parent.pending = x;
      closeWin(win.id);
      toast('Cliquez sur OK dans « Propriétés de Ethernet » pour appliquer.');
    };
  }

  /* =============================== Terminal / cmd =============================== */
  const PAD = (label, width) => { let line = '   ' + label; while (line.length < width) line += line.length % 2 ? '.' : ' '; return line; };
  function ipconfig(all) {
    const out = ['', 'Configuration IP de Windows', ''];
    if (all) {
      out.push(`${PAD('Nom de l’hôte', 36)} : ${N().name}`, `${PAD('Suffixe DNS principal', 36)} :`, `${PAD('Type de noeud', 36)} : Hybride`,
        `${PAD('Routage IP activé', 36)} : Non`, `${PAD('Proxy WINS activé', 36)} : Non`, '');
    }
    for (const p of ports()) {
      out.push(`Carte Ethernet ${nic(p)} :`, '');
      if (!cabled(p)) {
        out.push(`${PAD('Statut du média', 42)}: Média déconnecté`, `${PAD('Suffixe DNS propre à la connexion', 42)}:`);
        if (all) out.push(`${PAD('Description', 42)}: ${ADAPTER}`, `${PAD('Adresse physique', 42)}: ${mac(p)}`, `${PAD('DHCP activé', 42)}: ${dhcp(p) ? 'Oui' : 'Non'}`);
        out.push('');
        continue;
      }
      out.push(`${PAD('Suffixe DNS propre à la connexion', 42)}:`);
      if (all) out.push(`${PAD('Description', 42)}: ${ADAPTER}`, `${PAD('Adresse physique', 42)}: ${mac(p)}`, `${PAD('DHCP activé', 42)}: ${dhcp(p) ? 'Oui' : 'Non'}`,
        `${PAD('Configuration automatique activée', 42)}: Oui`);
      if (dhcp(p)) out.push(`${PAD('Adresse IPv4', 42)}: (bail DHCP : démarrer le lab, puis la console du poste)`);
      else if (address(p)) out.push(`${PAD('Adresse IPv4', 42)}: ${ip(p)}${all ? '(préféré)' : ''}`, `${PAD('Masque de sous-réseau', 42)}: ${mask(p)}`);
      out.push(`${PAD('Passerelle par défaut', 42)}: ${dhcp(p) ? '' : gateway()}`, '');
    }
    return out.join('\n');
  }
  function terminal(el, win) {
    const w11 = W11();
    const banner = w11 ? `Microsoft Windows [version 10.0.22631.4460]\n(c) Microsoft Corporation. Tous droits réservés.\n\n`
      : SERVER() ? `Microsoft Windows [version 10.0.20348.2849]\n(c) Microsoft Corporation. Tous droits réservés.\n\n`
        : `Microsoft Windows [version 10.0.19045.5131]\n(c) Microsoft Corporation. Tous droits réservés.\n\n`;
    win.log = win.log === undefined ? banner : win.log;
    const promptText = `C:\\Users\\${SERVER() ? 'Administrateur' : 'Utilisateur'}>`;
    el.innerHTML = `<div class="wn-term"><span class="log"></span>${h(promptText)}<input spellcheck="false" autocomplete="off" data-autofocus="1"></div>`;
    const term = el.querySelector('.wn-term'), input = term.querySelector('input'), log = term.querySelector('.log');
    log.textContent = win.log;
    term.onclick = () => input.focus();
    setTimeout(() => { term.scrollTop = term.scrollHeight; });
    input.onkeydown = event => {
      if (event.key !== 'Enter') return;
      const line = input.value, word = line.trim().split(/\s+/)[0].toLowerCase(), args = line.trim().toLowerCase();
      let answer = '';
      if (!line.trim()) answer = '';
      else if (word === 'cls') { win.log = ''; log.textContent = ''; input.value = ''; return; }
      else if (word === 'exit') { closeWin(win.id); return; }
      else if (args === 'ipconfig' || args === 'ipconfig /all') answer = ipconfig(args.endsWith('/all'));
      else if (word === 'hostname') answer = N().name;
      else if (word === 'ver') answer = '\n' + banner.split('\n')[0];
      else if (word === 'whoami') answer = `${N().name.toLowerCase()}\\${SERVER() ? 'administrateur' : 'utilisateur'}`;
      else if (word === 'help') answer = 'Pour plus d’informations sur une commande spécifique, entrez HELP suivi de la commande.\nCLS      Efface l’écran.\nEXIT     Quitte l’interpréteur de commandes.\n'
        + 'HOSTNAME Affiche le nom de l’ordinateur.\nIPCONFIG Affiche la configuration IP.\nPING, TRACERT, ARP, NSLOOKUP : console du poste (lab en marche).';
      else if (word === 'ncpa.cpl') { openWin('cpl', {page: 'ncpa'}); }
      else if (word === 'control') { openWin('cpl', {page: 'home'}); }
      else if (['ping', 'tracert', 'arp', 'nslookup', 'netsh', 'route', 'netstat', 'pathping'].includes(word)) {
        if (running()) { answer = `[${word} s’exécute sur le poste réel : la console de ${N().name} s’ouvre dans Network LABS]`; openTerminal(); }
        else answer = `Le poste est éteint : démarrez le lab (▶ Démarrer dans Network LABS) pour envoyer des paquets.`;
      } else answer = `'${line.trim().split(/\s+/)[0]}' n’est pas reconnu en tant que commande interne\nou externe, un programme exécutable ou un fichier de commandes.`;
      win.log += `${promptText}${line}\n${answer ? answer + '\n' : ''}\n`;
      log.textContent = win.log;
      input.value = '';
      term.scrollTop = term.scrollHeight;
    };
  }

  /* =============================== Explorer (Ce PC, Corbeille, Réseau) =============================== */
  function explorer(el, win) {
    const page = win.page || 'pc', others = (state.equipment || []).filter(e => e.name !== N().name && e.role === 'host');
    const title = {pc: 'Ce PC', bin: 'Corbeille', network: 'Réseau'}[page] || 'Ce PC';
    const nav = [['home:c', 'Accueil', 'na'], ['image', 'Galerie', 'na'], ['-'], ['desktop', 'Bureau', 'na'], ['arrow_download', 'Téléchargements', 'na'], ['document', 'Documents', 'na'],
      ['image', 'Images', 'na'], ['music_note_2', 'Musique', 'na'], ['video', 'Vidéos', 'na'], ['-'], ['laptop:c', 'Ce PC', 'pc'], ['globe', 'Réseau', 'network'], ['delete', 'Corbeille', 'bin']];
    const tool = (icon, label, off = false) => `<a class="${off ? 'off' : ''}" title="${label}">${FX(icon, 18)}${label.includes('▾') ? ' ' + label : ''}</a>`;
    el.innerHTML = `<div class="ex-top"><span class="ex-nav">${FX('arrow_left', 16)}${FX('arrow_right', 16)}${FX('arrow_up', 16)}${FX('arrow_clockwise', 16)}</span>
      <span class="ex-path">${page === 'network' ? FX('globe', 16) : page === 'bin' ? FX('delete', 16) : FX('laptop:c', 16)}<span>›</span>${title}<span>›</span></span>
      <span class="ex-find">Rechercher dans : ${title} ${FX('search', 14)}</span></div>
      <div class="ex-cmd">${tool('add_circle', 'Nouveau ▾')}<i></i>${tool('cut', 'Couper', true)}${tool('copy', 'Copier', true)}${tool('clipboard_paste', 'Coller', true)}
        ${tool('rename', 'Renommer', true)}${tool('share', 'Partager', true)}${tool('delete', 'Supprimer', true)}<i></i>${tool('arrow_sort', 'Trier ▾')}${tool('grid', 'Afficher ▾')}<i></i>
        ${tool('more_horizontal', 'Voir plus')}<span style="flex:1"></span>${tool('panel_left', 'Détails')}</div>
      <div class="ex-body"><nav>${nav.map(([icon, label, go]) => (icon === '-' ? '<hr>' : `<a data-ex="${go}" class="${go === page ? 'on' : ''}">${FX(icon, 16)}${label}</a>`)).join('')}</nav>
      <main>${page === 'pc' ? `<div class="ex-sec">${FX('chevron_down', 12)} Périphériques et lecteurs</div><div class="ex-drive">${FX('hard_drive', 40)}<div>Disque local (C:)
        <div class="bar"><i style="width:38%"></i></div><small>39,6 Go disponibles sur 63,3 Go</small></div></div>` : page === 'network' ? `<div class="ex-sec">${FX('chevron_down', 12)}
        Ordinateur (${others.length})</div><div class="ex-hosts">${others.map(e => `<div>${ICON.pc(44)}<span>${h(e.name)}</span></div>`).join('') || '<p>Aucun.</p>'}</div>`
        : '<p class="ex-empty">Ce dossier est vide.</p>'}</main></div><div class="ex-status">${page === 'pc' ? '1 élément' : page === 'network' ? `${others.length} élément(s)` : '0 élément'}</div>`;
    el.querySelectorAll('[data-ex]').forEach(a => { a.onclick = () => { if (a.dataset.ex === 'na') later(a.textContent.trim()); else { win.page = a.dataset.ex; render(); } }; });
    el.querySelectorAll('.ex-cmd a:not(.off)').forEach(a => { a.onclick = () => later(a.title); });
    el.querySelector('.ex-drive')?.addEventListener('dblclick', () => later('Disque local (C:)'));
  }

  /* =============================== Server Manager (Windows Server) =============================== */
  function serverManager(el, win) {
    const page = win.page || 'dash', p = ports()[0];
    el.innerHTML = `<div class="wn-sm"><div class="hd">‹ › Gestionnaire de serveur ▸ ${page === 'local' ? 'Serveur local' : 'Tableau de bord'}<small><span>⟳</span><span>⚑</span><span>Gérer</span><span>Outils</span>
      <span>Afficher</span><span>Aide</span></small></div><div class="bd"><nav>${[['dash', '▦ Tableau de bord'], ['local', '▭ Serveur local'], ['all', '▤ Tous les serveurs'],
        ['files', '▣ Services de fichiers et de stockage ▸']].map(([k, t]) => `<a data-sm="${k}" class="${k === page ? 'on' : ''}">${t}</a>`).join('')}</nav><main></main></div></div>`;
    el.querySelectorAll('[data-sm]').forEach(a => { a.onclick = () => { if (['dash', 'local'].includes(a.dataset.sm)) { win.page = a.dataset.sm; render(); } else later(a.textContent.trim()); }; });
    const main = el.querySelector('main');
    if (page === 'dash') {
      main.innerHTML = `<div class="welcome"><b>BIENVENUE DANS GESTIONNAIRE DE SERVEUR</b><ol><li><a data-local="1">Configurer ce serveur local</a></li><li><a data-na="1">Ajouter des rôles et des fonctionnalités</a></li>
        <li><a data-na="1">Ajouter d’autres serveurs à gérer</a></li><li><a data-na="1">Créer un groupe de serveurs</a></li><li><a data-na="1">Connecter ce serveur aux services cloud</a></li></ol></div>
        <h3 style="margin-top:18px">RÔLES ET GROUPES DE SERVEURS</h3><div style="display:flex;gap:12px">${[['Serveur local', 1], ['Tous les serveurs', 1]].map(([t, n]) =>
          `<div style="width:220px;border:1px solid #e1e1e1"><div style="background:#2d6db5;color:#fff;padding:6px 10px">${t} <b style="float:right">${n}</b></div><div style="padding:6px 10px;line-height:1.9">⊕ Facilité de gestion<br>Événements<br>Services<br>Performances<br>Résultats BPA</div></div>`).join('')}</div>`;
      main.querySelector('[data-local]').onclick = () => { win.page = 'local'; render(); };
      main.querySelectorAll('[data-na]').forEach(a => { a.onclick = () => later(a.textContent); });
    } else {
      main.innerHTML = `<h3>PROPRIÉTÉS<br><small style="font-size:12px">Pour ${h(N().name)}</small></h3><div class="props">${[['Nom de l’ordinateur', `<a data-ren="1">${h(N().name)}</a>`],
        ['Dernières mises à jour installées', 'Jamais'], ['Groupe de travail', '<a>WORKGROUP</a>'], ['Windows Update', 'Télécharger les mises à jour uniquement'],
        ['', ''], ['Dernière recherche de mises à jour', 'Jamais'], ['Pare-feu Microsoft Defender', '<a>Public : Actif</a>'], ['Antivirus Microsoft Defender', '<a>Protection en temps réel : Activé</a>'],
        ['Gestion à distance', '<a>Activé</a>'], ['Commentaires et diagnostics', '<a>Paramètres</a>'], ['Bureau à distance', '<a>Désactivé</a>'],
        ['Configuration de sécurité renforcée d’Internet Explorer', '<a>Actif</a>'], ['Association de cartes réseau', '<a>Désactivé</a>'], ['Fuseau horaire', '<a>(UTC+01:00) Bruxelles, Copenhague, Madrid, Paris</a>'],
        [nic(p), `<a data-ncpa="1">${h(cabled(p) ? (dhcp(p) ? 'Adresse IPv4 attribuée par DHCP' : ip(p) || 'Non configuré') : 'Non connecté')}, Compatible IPv6</a>`],
        ['ID de produit', 'Non activé'], ['Version du système d’exploitation', 'Microsoft Windows Server 2022 Standard'], ['Processeurs', `${N().vcpus || 1} processeur(s) virtuel(s)`],
        ['Informations sur le matériel', 'Machine virtuelle Network LABS'], ['Mémoire installée (RAM)', `${N().memory_mib || 512} Mo`]].map(([k, val]) => `<span>${h(k)}</span><span>${val}</span>`).join('')}</div>`;
      main.querySelector('[data-ncpa]').onclick = () => openWin('cpl', {page: 'ncpa'});
      main.querySelector('[data-ren]').onclick = () => renameModern(main);
    }
  }

  // Escape closes the open flyout or the window in front, as on Windows.
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !['win11', 'win10'].includes(V().skin)) return;
    const v = V();
    if (v.fly) { v.fly = null; render(); } else if (document.querySelector('.wn-shade')) document.querySelector('.wn-shade').remove();
  });
  document.addEventListener('click', () => { const v = V(); if (['win11', 'win10'].includes(v.skin) && v.fly) { v.fly = null; render(); } });
})();
