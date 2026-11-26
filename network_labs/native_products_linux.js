/* A Linux PC as its owner sees it (engine: native_products.js): GNOME as Ubuntu 24.04 LTS ships it (Yaru: its icons, the
 * Ubuntu Sans font, the Ubuntu Dock, Ubuntu's wallpaper), or as Debian, Fedora and Rocky Linux ship it (GNOME's Adwaita icons
 * and wallpaper, Cantarell or Adwaita Sans). Icons, fonts and wallpapers are the distributions' own files, copied from their
 * packages with their licences (assets/linux, tools/build_linux_assets.py). The top bar and its quick settings, the dock or
 * the overview, Settings › Réseau (the wired connection: IPv4 Automatique (DHCP) or Manuel, DNS), the Terminal (each line runs
 * on the PC itself: /api/host_command), Fichiers and a web browser (/api/browse). Every change goes to the project as on the
 * other pages (/api/host_ip, /api/apply). A machine that serves (HTTP, DNS…) keeps the server desktop with its Services. */
'use strict';
(() => {
  const K = window.nlProductsKit;
  if (!K) return;
  const {SKINS, D, N, h, maskOf, prefixOf, validIp, toast, send, skinCss} = K;
  const V = () => K.view;
  // Each distribution's desktop: Ubuntu's (Yaru) or GNOME's own (Adwaita), its GNOME, its terminal and its shell prompt.
  const DISTROS = {
    Canonical: {theme: 'yaru', os: 'Ubuntu 24.04.1 LTS', gnome: '46', terminal: 'Terminal', prompt: 'ubuntu', font: 'ubuntu', browser: 'Navigateur web'},
    Debian: {theme: 'adwaita', os: 'Debian GNU/Linux 13 (trixie)', gnome: '48', terminal: 'Console', prompt: 'debian', font: 'adwaita', browser: 'Web'},
    Fedora: {theme: 'adwaita', os: 'Fedora Linux 42 (Workstation Edition)', gnome: '48', terminal: 'Console', prompt: 'fedora', font: 'adwaita', browser: 'Web'},
    Rocky: {theme: 'adwaita', os: 'Rocky Linux 9.5 (Blue Onyx)', gnome: '40', terminal: 'Terminal', prompt: 'fedora', font: 'cantarell', browser: 'Web'},
  };
  const linux = (d, role) => role === 'host' && Boolean(DISTROS[d.brand]) && !N().services;  // a server keeps its Services desktop
  K.MATCH.push([(d, role) => linux(d, role) && d.brand === 'Canonical', 'yaru']);
  K.MATCH.push([(d, role) => linux(d, role), 'adwaita']);
  const OS = () => DISTROS[D().brand] || DISTROS.Debian;
  const YARU = () => V().skin === 'yaru';

  // ---- the machine, as GNOME names it ----
  const ports = () => Object.keys(N().interfaces);
  const devPort = port => D().ports.find(p => p.port === port) || {};
  const disabled = port => (N().shutdown || []).includes(port);
  const cabled = port => Boolean(devPort(port).peer) && !disabled(port);
  const dhcp = port => (N().dhcp_clients || []).includes(port);
  const address = port => N().interfaces[port] || '';
  const gateway = () => N().gateway || '';
  const dnsServer = () => (N().resolvers || [])[0] || '';
  const USER = 'utilisateur';
  const host = () => N().name.toLowerCase();
  const mac = port => {
    let hash = 0;
    for (const c of N().name + port) hash = (hash * 31 + c.charCodeAt(0)) >>> 0;
    return ['52', '54', '00', ...[16, 8, 0].map(s => ((hash >> s) & 255).toString(16).padStart(2, '0'))].join(':').toUpperCase();
  };
  const wiredName = port => (ports().indexOf(port) <= 0 ? 'Câblé' : `Ethernet (${port})`);
  const later = what => toast(`${what} : pas relié au laboratoire.`, true);

  async function saveIp(port, mode, ipText, maskText, gw, dnsText) {
    let cidr = '';
    if (mode === 'static') {
      const prefix = String(maskText).includes('.') ? prefixOf(maskText) : Number(maskText);
      if (!validIp(ipText)) throw new Error('Adresse IPv4 non valable.');
      if (prefix === null || !(prefix >= 1 && prefix <= 32)) throw new Error('Masque de réseau non valable.');
      if (gw && !validIp(gw)) throw new Error('Passerelle non valable.');
      if (dnsText && !validIp(dnsText)) throw new Error('Adresse DNS non valable.');
      cidr = `${ipText}/${prefix}`;
    }
    const dnsField = N().runtime !== 'firecracker' ? {} : {dns: mode === 'static' ? dnsText || '' : ''};
    await send('/api/host_ip', {port, mode, address: cidr, gateway: mode === 'static' ? gw : '', ...dnsField});
    toast(`${wiredName(port)} : ${mode === 'dhcp' ? 'automatique (DHCP)' : cidr} enregistré` + (typeof state.ip_live === 'string' ? ` · PC en marche : ${state.ip_live}.` : '.'));
  }

  // ---- the theme's own icons: symbolic ones take the text's colour, as GTK draws them ----
  const ASSETS = '/ui/linux/';
  const theme = () => (YARU() ? 'yaru' : 'adwaita');
  const sym = (name, size = 16) => {
    const url = `${ASSETS}${theme()}/${name}-symbolic.svg`;
    return `<i class="gs" style="width:${size}px;height:${size}px;-webkit-mask-image:url(${url});mask-image:url(${url})"></i>`;
  };
  const full = (name, size = 48) => `<img class="gf" src="${ASSETS}${theme()}/${name}.${YARU() ? 'png' : 'svg'}" width="${size}" height="${size}" alt="" draggable="false">`;
  const APPS = {
    web: {label: () => OS().browser, icon: () => 'org.gnome.Epiphany'},
    files: {label: () => 'Fichiers', icon: () => 'org.gnome.Nautilus'},
    terminal: {label: () => OS().terminal, icon: () => (YARU() ? 'org.gnome.Terminal' : 'org.gnome.Console')},
    settings: {label: () => 'Paramètres', icon: () => 'org.gnome.Settings'},
    editor: {label: () => 'Éditeur de texte', icon: () => 'org.gnome.TextEditor'},
  };
  const DOCK = ['web', 'files', 'terminal', 'settings', 'editor'];
  const clock = () => {
    const now = new Date();
    return `${now.toLocaleDateString('fr-FR', {weekday: 'short', day: 'numeric', month: 'short'})}  ${now.toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'})}`;
  };

  skinCss(`
  @font-face{font-family:'Ubuntu Sans';src:url('/ui/linux/fonts/UbuntuSans.ttf') format('truetype');font-weight:100 800;font-stretch:75% 100%}
  @font-face{font-family:'Ubuntu Sans Mono';src:url('/ui/linux/fonts/UbuntuSansMono.ttf') format('truetype');font-weight:400 700}
  @font-face{font-family:'Cantarell';src:url('/ui/linux/fonts/Cantarell-Regular.otf') format('opentype');font-weight:400}
  @font-face{font-family:'Cantarell';src:url('/ui/linux/fonts/Cantarell-Bold.otf') format('opentype');font-weight:700}
  @font-face{font-family:'Inter';src:url('/InterVariable.ttf') format('truetype');font-weight:100 900}
  /* libadwaita's light colours (GNOME 46): window, views, header bars, cards; Yaru's text and orange for Ubuntu */
  .px-app.gn{position:fixed;inset:0;overflow:hidden;cursor:default;user-select:none;--gAccent:#3584e4;--gText:rgba(0,0,6,.8);--gDim:rgba(0,0,6,.55);
    --gWin:#fafafa;--gView:#fff;--gHead:#ebebeb;--gSide:#ebebeb;--gShade:rgba(0,0,6,.07);--gBtn:rgba(0,0,6,.1);--gBtnH:rgba(0,0,6,.15);
    --gPop:#36363a;--gPopText:#fff;--gTile:rgba(255,255,255,.1);--gTileH:rgba(255,255,255,.15);--gPanel:#000;
    font:14.67px/1.36 'Adwaita Sans',Inter,Cantarell,sans-serif;color:var(--gText)}
  .px-app.gn.f-cantarell{font-family:Cantarell,sans-serif}
  .px-app.gn.yaru{--gAccent:#e95420;--gText:#3d3d3d;--gDim:rgba(61,61,61,.6);--gPop:#fafafa;--gPopText:#3d3d3d;--gTile:#e3e3e3;--gTileH:#d9d9d9;
    --gPanel:#131313;font-family:'Ubuntu Sans',sans-serif}
  .px-app.gn *{box-sizing:border-box}
  .gn .gs{display:inline-block;flex:none;background:currentColor;-webkit-mask-size:contain;mask-size:contain;-webkit-mask-repeat:no-repeat;mask-repeat:no-repeat;
    -webkit-mask-position:center;mask-position:center;vertical-align:middle}
  .gn .gf{display:block;flex:none}
  .gn-wall{position:absolute;inset:0;background:#3a3a3a url('/ui/linux/walls/gnome.jpg') center/cover}
  .yaru .gn-wall{background-image:url('/ui/linux/walls/ubuntu.jpg')}
  /* the top bar: 32 px, black (Ubuntu: #131313), bold, the clock in the middle */
  .gn-panel{position:absolute;left:0;right:0;top:0;height:32px;background:var(--gPanel);color:#fff;font-weight:700;display:flex;align-items:center;
    justify-content:space-between;padding:0 4px;z-index:5000}
  .gn-pb{height:26px;display:flex;align-items:center;gap:8px;padding:0 12px;border-radius:999px;color:#fff;transition:background .15s}
  .gn-pb:hover,.gn-pb.on{background:rgba(255,255,255,.17)}
  .gn-act i{display:block;height:8px;width:8px;border-radius:4px;background:rgba(255,255,255,.55)}.gn-act i.on{width:30px;background:#fff}.gn-act{gap:5px}
  .gn-clock{position:absolute;left:50%;transform:translateX(-50%);white-space:pre}
  .gn-right{display:flex;align-items:center;gap:2px}
  /* the Ubuntu Dock: the whole left edge, 48 px icons, orange dots for the running apps */
  .gn-dock{position:absolute;left:0;top:32px;bottom:0;width:66px;background:rgba(29,29,29,.82);display:flex;flex-direction:column;align-items:center;
    padding:6px 0;gap:2px;z-index:4000}
  .gn-dk{position:relative;width:58px;height:58px;display:grid;place-items:center;border-radius:12px;color:#fff}
  .gn-dk:hover{background:rgba(255,255,255,.12)}.gn-dk.run::before{content:'';position:absolute;left:1px;top:50%;width:5px;height:5px;margin-top:-2.5px;
    border-radius:50%;background:var(--gAccent)}
  .gn-dock .gn-sep{width:40px;height:1px;background:rgba(255,255,255,.2);margin:4px 0}.gn-dock .gn-sp{flex:1}
  .gn-desk{position:absolute;left:78px;top:44px}.gn-di{width:96px;display:flex;flex-direction:column;align-items:center;gap:4px;padding:6px 2px;border-radius:8px;
    color:#fff;text-align:center;font-size:13.5px;text-shadow:0 1px 2px rgba(0,0,0,.8)}.gn-di:hover{background:rgba(255,255,255,.18)}
  .gn-di.sel{background:rgba(233,84,32,.5)}
  /* popovers of the shell: quick settings (GNOME 46: 13.5 px corners, 48 px pill toggles, 12 px between them) */
  .gn-pop{position:absolute;z-index:6000;background:var(--gPop);color:var(--gPopText);border-radius:13.5px;border:1px solid rgba(0,0,0,.12);
    box-shadow:0 2px 6px rgba(0,0,0,.2);animation:gnIn .12s ease-out}
  @keyframes gnIn{from{opacity:0;transform:translateY(-4px)}}
  .gn-qs{right:6px;top:38px;width:400px;padding:18px}
  .gn-qs-top{display:flex;gap:12px;margin-bottom:14px}.gn-qs-top .grow{flex:1}
  .gn-cb{width:42px;height:42px;border-radius:999px;display:grid;place-items:center;background:var(--gTile)}.gn-cb:hover{background:var(--gTileH)}
  .gn-slider{display:flex;align-items:center;gap:12px;height:42px;padding:0 6px 0 12px;margin-bottom:14px}
  .gn-slider .bar{flex:1;height:4px;border-radius:2px;background:rgba(127,127,127,.35);position:relative}
  .gn-slider .bar i{position:absolute;left:0;top:0;bottom:0;border-radius:2px;background:var(--gAccent)}
  .gn-slider .bar b{position:absolute;top:50%;width:20px;height:20px;margin:-10px 0 0 -10px;border-radius:50%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.35)}
  .gn-tg{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .gn-t{display:flex;height:48px;border-radius:999px;background:var(--gTile);overflow:hidden}.gn-t:hover{background:var(--gTileH)}
  .gn-t .m{flex:1;display:flex;align-items:center;gap:9px;padding:0 6px 0 15px;min-width:0}
  .gn-t .m b{display:block;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .gn-t .m small{display:block;font-size:12.5px;font-weight:400;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;opacity:.85}
  .gn-t .a{width:38px;display:grid;place-items:center;border-left:1px solid rgba(127,127,127,.25)}
  .gn-t.on{background:var(--gAccent);color:#fff}.gn-t.on .a{border-left-color:rgba(0,0,0,.25)}
  /* the overview / « Afficher les applications »: the apps on the dimmed wallpaper, the dash at the bottom */
  .gn-ov{position:absolute;left:0;right:0;top:32px;bottom:0;z-index:3500;background:rgba(32,32,32,.72);backdrop-filter:blur(24px);display:flex;
    flex-direction:column;align-items:center;color:#fff;animation:gnFade .15s ease-out}
  .yaru .gn-ov{left:66px}@keyframes gnFade{from{opacity:0}}
  .gn-search{margin-top:22px;width:320px;height:38px;border-radius:999px;background:rgba(255,255,255,.12);display:flex;align-items:center;gap:8px;padding:0 14px}
  .gn-search input{flex:1;background:none;border:0;outline:0;color:#fff;font:inherit}.gn-search input::placeholder{color:rgba(255,255,255,.6)}
  .gn-apps{flex:1;display:grid;grid-template-columns:repeat(6,140px);align-content:center;justify-content:center;gap:24px 12px}
  .gn-ga{display:flex;flex-direction:column;align-items:center;gap:10px;padding:14px 6px;border-radius:18px;font-size:14px}.gn-ga:hover{background:rgba(255,255,255,.1)}
  .gn-dash{margin-bottom:14px;display:flex;align-items:center;gap:4px;padding:10px 12px;border-radius:24px;background:rgba(255,255,255,.12)}
  .gn-dash .gn-sep{width:1px;height:40px;background:rgba(255,255,255,.25);margin:0 6px}
  /* windows: libadwaita's (12 px corners, its shadows, 47 px header bars, round window buttons) */
  .gn-win{position:absolute;display:flex;flex-direction:column;background:var(--gWin);border-radius:12px;overflow:hidden;color:var(--gText);
    box-shadow:0 1px 3px 1px rgba(0,0,0,.09),0 2px 14px 5px rgba(0,0,0,.05),0 0 0 1px rgba(0,0,0,.09)}
  .gn-win.back{box-shadow:0 1px 3px 1px rgba(0,0,0,.05),0 2px 8px 2px rgba(0,0,0,.03),0 0 0 1px rgba(0,0,0,.07)}
  .gn-win.max{left:0!important;top:32px!important;width:100%!important;height:calc(100% - 32px)!important;border-radius:0}
  .yaru .gn-win.max{left:66px!important;width:calc(100% - 66px)!important}
  .gn-hb{flex:none;height:47px;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding:0 6px;background:var(--gHead);
    box-shadow:inset 0 -1px var(--gShade);position:relative}
  .gn-hb .l,.gn-hb .r{display:flex;align-items:center;gap:6px;min-width:0}.gn-hb .r{justify-content:flex-end}
  .gn-hb .t{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:0 12px;text-align:center}
  .gn-ib{width:34px;height:34px;border:0;border-radius:6px;background:none;color:inherit;display:grid;place-items:center;cursor:default}
  .gn-ib:hover{background:rgba(0,0,6,.07)}.gn-ib:active{background:rgba(0,0,6,.16)}
  .gn-ctl{display:flex;align-items:center;margin-left:6px}.gn-ctl button{width:24px;height:24px;margin:0 4px;border:0;border-radius:50%;background:var(--gBtn);
    color:inherit;display:grid;place-items:center;cursor:default;padding:0}.gn-ctl button:hover{background:var(--gBtnH)}
  .gn-btn{height:34px;padding:0 17px;border:0;border-radius:6px;background:var(--gBtn);color:inherit;font:inherit;font-weight:700;cursor:default}
  .gn-btn:hover{background:var(--gBtnH)}.gn-btn.sugg{background:var(--gAccent);color:#fff}.gn-btn.sugg:hover{filter:brightness(1.08)}
  /* split views (Settings, Files): the sidebar, its own header bar, then the page */
  .gn-split{flex:1;display:flex;min-height:0}.gn-side{width:280px;flex:none;display:flex;flex-direction:column;background:var(--gSide);
    box-shadow:inset -1px 0 var(--gShade)}.gn-main{flex:1;display:flex;flex-direction:column;min-width:0;background:var(--gWin)}
  .gn-side .gn-hb{background:var(--gSide)}
  .gn-sl{flex:1;overflow:auto;padding:6px}.gn-sl a{display:flex;align-items:center;gap:12px;height:40px;padding:0 10px;border-radius:6px}
  .gn-sl a:hover{background:rgba(0,0,6,.05)}.gn-sl a.on{background:rgba(0,0,6,.1)}.gn-sl hr{border:0;border-top:1px solid var(--gShade);margin:6px 4px}
  .gn-page{flex:1;overflow:auto;padding:24px 12px}.gn-clamp{max-width:600px;margin:0 auto}
  .gn-group{margin-bottom:24px}.gn-gh{display:flex;align-items:center;justify-content:space-between;margin:0 0 10px;font-weight:700}
  .gn-gh .gn-ib{width:30px;height:30px}
  .gn-list{background:var(--gView);border-radius:12px;box-shadow:0 0 0 1px rgba(0,0,6,.03),0 1px 3px 1px rgba(0,0,6,.07),0 2px 6px 2px rgba(0,0,6,.03)}
  .gn-row{min-height:50px;display:flex;align-items:center;gap:12px;padding:8px 12px}.gn-row+.gn-row{box-shadow:inset 0 1px var(--gShade)}
  .gn-row .grow{flex:1;min-width:0}.gn-row small{display:block;color:var(--gDim);font-size:13px}.gn-row .dim{color:var(--gDim)}
  .gn-row.link:hover{background:rgba(0,0,6,.03)}
  .gn-sw{width:48px;height:26px;border-radius:13px;background:rgba(0,0,6,.15);position:relative;flex:none;transition:background .15s}
  .gn-sw::after{content:'';position:absolute;left:3px;top:3px;width:20px;height:20px;border-radius:50%;background:#fff;box-shadow:0 2px 4px rgba(0,0,0,.2);transition:left .15s}
  .gn-sw.on{background:var(--gAccent)}.gn-sw.on::after{left:25px}.gn-sw.off{opacity:.5}
  .gn-status{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;height:100%;color:var(--gDim);text-align:center}
  .gn-status b{font-size:24px;color:var(--gText)}
  /* Network LABS' menu: under its top-bar button, in the shell's popover style; the floating pill itself is not drawn */
  .px-app.gn ~ .px-pill{top:38px;bottom:auto;right:56px}.px-app.gn ~ .px-pill .px-pill-main{display:none}.px-app.gn ~ .px-pill.open{z-index:6100}
  .px-app.gn ~ .px-pill .px-pill-menu{top:0;bottom:auto;border-radius:13.5px}
  /* a dialog's window behind it is dimmed, as libadwaita does */
  .gn-win .gn-dim{position:absolute;inset:0;background:rgba(0,0,0,.25);border-radius:inherit;z-index:5}
  /* the connection editor (GNOME Settings' « Câblé » dialog) */
  .gn-tabs{display:flex;justify-content:center;gap:4px;padding:8px;background:var(--gWin);box-shadow:inset 0 -1px var(--gShade)}
  .gn-tabs a{padding:6px 14px;border-radius:6px;font-weight:700;color:var(--gDim)}.gn-tabs a:hover{background:rgba(0,0,6,.05)}
  .gn-tabs a.on{background:rgba(0,0,6,.1);color:var(--gText)}
  .gn-form{flex:1;overflow:auto;padding:18px 24px;background:var(--gView)}
  .gn-form h4{margin:16px 0 8px;font-size:14.67px;display:flex;align-items:center;justify-content:space-between}.gn-form h4:first-child{margin-top:0}
  .gn-radios{display:grid;grid-template-columns:1fr 1fr;gap:8px 20px}.gn-radios label,.gn-check{display:flex;align-items:center;gap:8px}
  .gn input[type=radio],.gn input[type=checkbox]{appearance:none;width:14px;height:14px;margin:0;border-radius:50%;box-shadow:inset 0 0 0 2px rgba(0,0,6,.25);flex:none}
  .gn input[type=checkbox]{border-radius:4px}.gn input[type=radio]:checked{background:radial-gradient(circle,#fff 0 2.5px,var(--gAccent) 3px);box-shadow:none}
  .gn input[type=checkbox]:checked{background:var(--gAccent) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 14 14'%3E%3Cpath d='M3.5 7.2 6 9.6l4.6-5' fill='none' stroke='white' stroke-width='2'/%3E%3C/svg%3E");box-shadow:none}
  .gn-in{height:34px;width:100%;border:0;border-radius:6px;background:rgba(0,0,6,.06);padding:0 9px;font:inherit;color:inherit;outline:0}
  .gn-in:focus{box-shadow:inset 0 0 0 2px color-mix(in srgb,var(--gAccent) 50%,transparent)}.gn-in:disabled{opacity:.5}
  .gn-addr{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px}.gn-addr span{font-size:13px;color:var(--gDim)}
  .gn-kv{display:grid;grid-template-columns:200px 1fr;gap:10px 18px}.gn-kv span:nth-child(odd){color:var(--gDim);text-align:right}
  .gn-hint{font-size:13px;color:var(--gDim);margin-top:4px}
  /* the terminals: Ubuntu's (aubergine), GNOME Console (dark), GNOME Terminal on Rocky (light) */
  .gn-hb.dk{background:#303030;color:#fff;box-shadow:inset 0 -1px rgba(0,0,0,.36)}.gn-hb.dk .gn-ib:hover{background:rgba(255,255,255,.1)}
  .gn-hb.dk .gn-ctl button{background:rgba(255,255,255,.1)}.gn-hb.dk .gn-ctl button:hover{background:rgba(255,255,255,.15)}
  .gn-term{flex:1;overflow:auto;padding:4px 6px;font:16px/1.25 'Ubuntu Sans Mono',monospace;white-space:pre-wrap;word-break:break-all;cursor:text;user-select:text}
  .gn-term.aub{background:#300a24;color:#fff}.gn-term.dark{background:#1e1e1e;color:#fff;font-family:'Adwaita Mono','Source Code Pro','DejaVu Sans Mono','Ubuntu Sans Mono',monospace}
  .gn-term.light{background:#fff;color:#171421;font-family:'Source Code Pro','DejaVu Sans Mono','Ubuntu Sans Mono',monospace}
  .gn-term input{background:none;border:0;outline:0;color:inherit;font:inherit;padding:0;width:50%;caret-color:currentColor}
  .gn-term .pu{color:#8ae234}.gn-term .pp{color:#729fcf}
  /* Files: the sidebar's places, the folder's icons */
  .gn-path{display:flex;align-items:center;gap:6px;height:34px;padding:0 12px;border-radius:6px;background:rgba(0,0,6,.06);font-weight:700}
  .gn-files{flex:1;overflow:auto;padding:12px;display:grid;grid-template-columns:repeat(auto-fill,112px);align-content:start;gap:6px;background:var(--gView)}
  .gn-files div{display:flex;flex-direction:column;align-items:center;gap:6px;padding:8px 4px;border-radius:8px;text-align:center;font-size:13.5px}
  .gn-files div:hover{background:rgba(0,0,6,.05)}
  /* the browser */
  .gn-url{width:100%;max-width:560px;height:34px;border:0;border-radius:6px;background:rgba(0,0,6,.06);padding:0 12px;font:inherit;color:inherit;outline:0;text-align:center}
  .gn-url:focus{text-align:left;box-shadow:inset 0 0 0 2px color-mix(in srgb,var(--gAccent) 50%,transparent)}
  .gn-view{flex:1;background:#fff;min-height:0}.gn-view iframe{width:100%;height:100%;border:0;display:block}
  `);

  /* =============================== the shell =============================== */
  const shell = {get start() { return {wins: [], seq: 1, fly: null}; }, draw(root) { drawShell(root); }};
  SKINS.yaru = shell;
  SKINS.adwaita = shell;
  const NL = '<svg viewBox="0 0 16 16" width="16" height="16"><circle cx="8" cy="8" r="6.4" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="8" cy="8" r="2.6" fill="currentColor"/></svg>';
  const SIZES = {settings: [960, 640], conn: [620, 600], terminal: [740, 470], files: [900, 560], web: [1000, 640]};
  const SINGLE = new Set(['settings', 'files', 'conn']);

  function drawShell(root) {
    const v = V(), port = ports()[0];
    root.classList.add('gn', 'f-' + OS().font);
    root.innerHTML = `<div class="gn-wall"></div>
      <div class="gn-panel"><span class="gn-pb gn-act${v.fly === 'grid' ? ' on' : ''}" data-ov="1" title="Activités"><i class="on"></i><i></i></span>
        <span class="gn-pb gn-clock">${h(clock())}</span>
        <span class="gn-right"><span class="gn-pb gn-nl" title="Network LABS">${NL}</span><span class="gn-pb gn-sys${v.fly === 'qs' ? ' on' : ''}" data-qs="1">${
  sym(cabled(port) ? 'network-wired' : 'network-wired-disconnected')}${sym('audio-volume-high')}${sym('system-shutdown')}</span></span></div>
      ${YARU() ? dock() + `<div class="gn-desk"><div class="gn-di${v.sel ? ' sel' : ''}" data-home="1">${full('user-home', 64)}<span>Dossier personnel</span></div></div>` : ''}`;
    for (const win of v.wins) {
      if (!win.min) root.append(windowEl(win));
    }
    if (v.fly === 'qs') root.append(quickSettings());
    if (v.fly === 'grid') root.append(overview());
    const front = [...root.querySelectorAll('.gn-win')].pop();
    front?.querySelector('[data-autofocus]')?.focus({preventScroll: true});
    root.querySelectorAll('[data-ov]').forEach(b => { b.onclick = event => { event.stopPropagation(); v.fly = v.fly === 'grid' ? null : 'grid'; render(); }; });
    root.querySelector('[data-qs]').onclick = event => { event.stopPropagation(); v.fly = v.fly === 'qs' ? null : 'qs'; render(); };
    root.querySelector('.gn-nl').onclick = event => { event.stopPropagation(); document.querySelector('.px-pill')?.classList.toggle('open'); };
    root.querySelectorAll('[data-app]').forEach(b => { b.onclick = event => { event.stopPropagation(); launch(b.dataset.app); }; });
    root.querySelector('[data-trash]')?.addEventListener('click', () => openWin('files', {place: 'trash'}));
    const home = root.querySelector('[data-home]');
    if (home) {
      home.onclick = event => { event.stopPropagation(); v.sel = true; home.classList.add('sel'); };
      home.ondblclick = () => openWin('files', {place: 'home'});
    }
    root.querySelector('.gn-wall').onclick = () => { if (v.fly || v.sel) { v.fly = null; v.sel = false; render(); } };
  }
  // A dock or dash icon: opens the app, or brings its window back to the front (GNOME: a second click does not minimise).
  function launch(kind) {
    const v = V(), win = v.wins.filter(x => x.kind === kind).pop();
    v.fly = null;
    if (!win) return openWin(kind);
    win.min = false;
    v.wins = [...v.wins.filter(x => x !== win), win];
    render();
  }
  function dock() {
    const v = V();
    return `<div class="gn-dock">${DOCK.map(k => `<span class="gn-dk${v.wins.some(w => w.kind === k) ? ' run' : ''}" data-app="${k}" title="${h(APPS[k].label())}">${
      full(APPS[k].icon(), 48)}</span>`).join('')}<span class="gn-sp"></span><span class="gn-sep"></span>
      <span class="gn-dk" data-trash="1" title="Corbeille">${full('user-trash', 48)}</span>
      <span class="gn-dk" data-ov="1" title="Afficher les applications">${sym('view-app-grid', 30)}</span></div>`;
  }
  function overview() {
    const el = document.createElement('div');
    el.className = 'gn-ov';
    el.innerHTML = `<div class="gn-search">${sym('edit-find')}<input placeholder="Taper pour rechercher"></div>
      <div class="gn-apps">${Object.keys(APPS).map(k => `<span class="gn-ga" data-app="${k}">${full(APPS[k].icon(), 96)}<span>${h(APPS[k].label())}</span></span>`).join('')}</div>
      ${YARU() ? '' : `<div class="gn-dash">${DOCK.map(k => `<span class="gn-dk" data-app="${k}" title="${h(APPS[k].label())}">${full(APPS[k].icon(), 48)}</span>`).join('')}
        <span class="gn-sep"></span><span class="gn-dk" title="Afficher les applications">${sym('view-app-grid', 30)}</span></div>`}`;
    el.onclick = event => { if (!event.target.closest('[data-app],.gn-search')) { V().fly = null; render(); } };
    return el;
  }
  // GNOME's quick settings: screenshot, Settings, lock, power; the volume; the toggles (Câblé first).
  function quickSettings() {
    const port = ports()[0], on = cabled(port);
    const el = document.createElement('div');
    el.className = 'gn-pop gn-qs';
    const tile = (lit, icon, title, sub, arrow, attrs = '') => `<span class="gn-t${lit ? ' on' : ''}" ${attrs}><span class="m">${sym(icon)}<span style="min-width:0"><b>${
      h(title)}</b>${sub ? `<small>${h(sub)}</small>` : ''}</span></span>${arrow ? `<span class="a">${sym('go-next')}</span>` : ''}</span>`;
    el.innerHTML = `<div class="gn-qs-top"><span class="gn-cb" title="Capture d’écran">${sym('camera-photo')}</span><span class="grow"></span>
        <span class="gn-cb" data-settings="1" title="Paramètres">${sym('emblem-system')}</span><span class="gn-cb" title="Verrouiller">${sym('system-lock-screen')}</span>
        <span class="gn-cb" title="Éteindre / Se déconnecter">${sym('system-shutdown')}</span></div>
      <div class="gn-slider">${sym('audio-volume-high')}<span class="bar"><i style="width:62%"></i><b style="left:62%"></b></span></div>
      <div class="gn-tg">${tile(on, on ? 'network-wired' : 'network-wired-disconnected', 'Câblé', on ? 'Connecté' : disabled(port) ? 'Désactivé' : 'Câble débranché', true, 'data-net="1"')}
        ${tile(false, 'power-profile-balanced', 'Mode d’alimentation', 'Équilibré', true)}${tile(false, 'night-light', 'Éclairage nocturne', '', false)}
        ${tile(false, 'weather-clear-night', 'Style sombre', '', false)}</div>`;
    el.onclick = event => event.stopPropagation();
    el.querySelector('[data-settings]').onclick = () => openWin('settings', {panel: 'network'});
    el.querySelector('[data-net]').onclick = () => openWin('settings', {panel: 'network'});
    el.querySelectorAll('.gn-t:not([data-net]),.gn-cb:not([data-settings])').forEach(b => { b.onclick = () => later(b.textContent.trim() || b.title); });
    return el;
  }

  /* =============================== windows =============================== */
  function openWin(kind, data = {}) {
    const v = V();
    v.fly = null;
    const existing = SINGLE.has(kind) && v.wins.find(x => x.kind === kind);
    if (existing) {
      Object.assign(existing, data, {min: false});
      v.wins = [...v.wins.filter(x => x !== existing), existing];
      return render();
    }
    const [wd, ht] = SIZES[kind], n = v.wins.length, area = document.querySelector('.px-app');
    const W = area ? area.clientWidth : 1280, H = area ? area.clientHeight : 800, left = YARU() ? 66 : 0;
    const parent = data.parent && v.wins.find(x => x.id === data.parent);
    if (parent) {  // a dialog: centred over its window (libadwaita)
      const [pw, ph] = SIZES[parent.kind];
      v.wins.push({id: v.seq++, kind, x: Math.max(left, parent.x + (pw - wd) / 2), y: Math.max(36, parent.y + (ph - ht) / 2), ...data});
      return render();
    }
    v.wins.push({id: v.seq++, kind, x: Math.max(left + 10, Math.min(W - wd - 10, left + (W - left - wd) / 2 + n * 28 - 40)),
      y: Math.max(42, Math.min(H - ht - 10, 32 + (H - 32 - ht) / 2 + n * 28 - 20)), ...data});
    render();
  }
  function closeWin(id) {
    const v = V();
    v.wins = v.wins.filter(x => x.id !== id && x.parent !== id);
    render();
  }
  function focusWin(id) {
    const v = V(), child = v.wins.find(x => x.parent === id);
    if (child) id = child.id;  // a window with its dialog open: the dialog stays in front
    const win = v.wins.find(x => x.id === id);
    if (!win || v.wins[v.wins.length - 1] === win) return;
    v.wins = [...v.wins.filter(x => x !== win), win];
    document.querySelectorAll('.gn-win').forEach(el => {  // no redraw: what is being typed elsewhere stays
      const index = v.wins.findIndex(x => String(x.id) === el.dataset.w);
      el.style.zIndex = 10 + index;
      el.classList.toggle('back', index !== v.wins.length - 1);
    });
  }
  // GNOME draws only « close »; Ubuntu adds « minimise » and « maximise », all three round.
  const controls = () => `<span class="gn-ctl">${YARU() ? `<button data-c="min" title="Réduire">${sym('window-minimize')}</button><button data-c="max" title="Maximiser">${
    sym('window-maximize')}</button>` : ''}<button data-c="close" title="Fermer">${sym('window-close')}</button></span>`;
  const BODY = {settings: settingsApp, conn: connection, terminal, files, web};
  function windowEl(win) {
    const v = V(), [wd, ht] = SIZES[win.kind], index = v.wins.indexOf(win);
    const el = document.createElement('div');
    el.className = `gn-win gw-${win.kind}${win.max ? ' max' : ''}${index !== v.wins.length - 1 ? ' back' : ''}`;
    el.dataset.w = win.id;
    Object.assign(el.style, {left: win.x + 'px', top: win.y + 'px', width: wd + 'px', height: ht + 'px', zIndex: 10 + index});
    BODY[win.kind](el, win);
    if (v.wins.some(x => x.parent === win.id)) el.insertAdjacentHTML('beforeend', '<div class="gn-dim"></div>');
    el.addEventListener('mousedown', () => focusWin(win.id));
    el.querySelectorAll('[data-c]').forEach(b => {
      b.onclick = () => {
        if (b.dataset.c === 'close') return closeWin(win.id);
        if (b.dataset.c === 'min') win.min = true; else win.max = !win.max;
        render();
      };
    });
    el.querySelectorAll('.gn-hb').forEach(bar => {
      bar.addEventListener('dblclick', event => { if (!event.target.closest('button,input,a,.gn-path')) { win.max = !win.max; render(); } });
      bar.addEventListener('mousedown', event => {
        if (event.target.closest('button,input,a,.gn-path') || win.max) return;
        const sx = event.clientX - win.x, sy = event.clientY - win.y;
        const move = e => { win.x = Math.max(-200, e.clientX - sx); win.y = Math.max(32, Math.min(innerHeight - 60, e.clientY - sy)); el.style.left = win.x + 'px'; el.style.top = win.y + 'px'; };
        const up = () => { document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); };
        document.addEventListener('mousemove', move);
        document.addEventListener('mouseup', up);
      });
    });
    return el;
  }

  /* =============================== Settings =============================== */
  // GNOME 46's sidebar, in its groups, with Settings' own icons.
  const PANELS = [['network', 'Réseau'], ['bluetooth', 'Bluetooth'], '-', ['display', 'Écrans'], ['sound', 'Son'], ['power', 'Énergie'], ['multitasking', 'Multitâche'],
    ['appearance', 'Apparence'], '-', ['applications', 'Applications'], ['notifications', 'Notifications'], ['search', 'Recherche'], ['online-accounts', 'Comptes en ligne'],
    ['sharing', 'Partage'], '-', ['mouse', 'Souris et pavé tactile'], ['keyboard', 'Clavier'], ['color', 'Couleur'], ['printers', 'Imprimantes'], '-',
    ['accessibility', 'Accessibilité'], ['privacy', 'Confidentialité et sécurité'], ['system', 'Système']];
  const sw = (on, attrs = '', off = false) => `<span class="gn-sw${on ? ' on' : ''}${off ? ' off' : ''}" ${attrs}></span>`;
  function settingsApp(el, win) {
    const panel = win.panel || 'network', title = (PANELS.find(p => p[0] === panel) || [0, ''])[1];
    el.innerHTML = `<div class="gn-split"><div class="gn-side"><div class="gn-hb"><span class="l"><button class="gn-ib" title="Rechercher">${sym('edit-find')}</button></span>
        <span class="t">Paramètres</span><span class="r"><button class="gn-ib" title="Menu principal">${sym('open-menu')}</button></span></div>
      <div class="gn-sl">${PANELS.map(p => (p === '-' ? '<hr>' : `<a data-panel="${p[0]}" class="${p[0] === panel ? 'on' : ''}">${sym('panel-' + p[0])}${h(p[1])}</a>`)).join('')}</div></div>
      <div class="gn-main"><div class="gn-hb"><span class="l"></span><span class="t">${h(title)}</span><span class="r">${controls()}</span></div>
        <div class="gn-page"></div></div></div>`;
    el.querySelectorAll('[data-panel]').forEach(a => { a.onclick = () => { win.panel = a.dataset.panel; render(); }; });
    const page = el.querySelector('.gn-page');
    if (panel === 'network') return networkPanel(page, win);
    if (panel === 'system') return systemPanel(page);
    page.innerHTML = `<div class="gn-status">${sym('panel-' + panel, 96)}<b>${h(title)}</b><span>Ce panneau n’est pas relié au laboratoire.</span></div>`;
  }
  function networkPanel(page, win) {
    const group = (title, add, rows) => `<div class="gn-group"><div class="gn-gh"><span>${h(title)}</span>${add ? `<button class="gn-ib" title="Ajouter">${sym('list-add')}</button>` : ''}</div>
      <div class="gn-list">${rows}</div></div>`;
    page.innerHTML = `<div class="gn-clamp">${ports().map(p => group(wiredName(p), true, `<div class="gn-row"><div class="grow">${cabled(p) ? 'Connecté - 1000 Mb/s'
      : disabled(p) ? 'Désactivé' : 'Câble débranché'}</div>${sw(!disabled(p), `data-port="${h(p)}" title="${disabled(p) ? 'Activer' : 'Désactiver'}"`, !devPort(p).peer)}
      <button class="gn-ib" data-conn="${h(p)}" title="Paramètres de la connexion">${sym('emblem-system')}</button></div>`)).join('')}
      ${group('VPN', true, '<div class="gn-row"><div class="grow dim">Non configuré</div></div>')}
      ${group('', false, `<div class="gn-row link"><div class="grow">Proxy réseau</div><span class="dim">Désactivé</span><button class="gn-ib">${sym('emblem-system')}</button></div>`)}</div>`;
    page.querySelectorAll('[data-conn]').forEach(b => { b.onclick = () => openWin('conn', {port: b.dataset.conn, parent: win.id, tab: 'Détails'}); });
    page.querySelectorAll('[data-port]').forEach(s => {
      s.onclick = () => {
        const port = s.dataset.port;
        send('/api/apply', {name: N().name, port, address: address(port), gateway: gateway(), enabled: disabled(port)})
          .then(() => { toast(`${wiredName(port)} : ${disabled(port) ? 'désactivé' : 'activé'}.`); render(); }, error => toast(error.message, true));
      };
    });
    page.querySelectorAll('.gn-gh .gn-ib, .gn-row.link').forEach(b => { b.onclick = () => later(b.title || 'Proxy réseau'); });
  }
  function systemPanel(page) {
    page.innerHTML = `<div class="gn-clamp"><div class="gn-group"><div class="gn-gh"><span>À propos</span></div><div class="gn-list">${[
      ['Nom de l’appareil', h(N().name)], ['Modèle du matériel', 'Network LABS · machine virtuelle'], ['Système d’exploitation', h(OS().os)],
      ['Version de GNOME', OS().gnome], ['Système de fenêtrage', 'Wayland'], ['Version du noyau', 'Linux 6.1 (micro-VM)']]
      .map(([k, value]) => `<div class="gn-row"><div class="grow">${k}</div><span class="dim">${value}</span></div>`).join('')}</div></div></div>`;
  }
  // « Câblé » › ⚙: GNOME's connection editor (Détails, Identité, IPv4, IPv6, Sécurité); « Appliquer » saves IPv4 into the project.
  function connection(el, win) {
    const port = win.port;
    if (win.mode === undefined) {
      const [ipText, prefix] = address(port).split('/');
      Object.assign(win, {mode: dhcp(port) || !ipText ? 'dhcp' : 'static', ip: ipText || '', mask: prefix ? maskOf(Number(prefix)) : '', gw: gateway(),
        dnsAuto: !dnsServer(), dns: dnsServer()});
    }
    const tabs = ['Détails', 'Identité', 'IPv4', 'IPv6', 'Sécurité'];
    el.innerHTML = `<div class="gn-hb"><span class="l"><button class="gn-btn" data-cancel="1">Annuler</button></span><span class="t">${h(wiredName(port))}</span>
      <span class="r"><button class="gn-btn sugg" data-apply="1">Appliquer</button></span></div>
      <div class="gn-tabs">${tabs.map(t => `<a data-tab="${t}" class="${t === win.tab ? 'on' : ''}">${t}</a>`).join('')}</div><div class="gn-form"></div>`;
    const form = el.querySelector('.gn-form');
    el.querySelectorAll('[data-tab]').forEach(a => { a.onclick = () => { keep(); win.tab = a.dataset.tab; render(); }; });
    const keep = () => {  // what is typed in the IPv4 tab stays when another tab is opened
      const get = name => form.querySelector(`[name="${name}"]`);
      if (!get('ip')) return;
      Object.assign(win, {ip: get('ip').value.trim(), mask: get('mask').value.trim(), gw: get('gw').value.trim(), dns: get('dns').value.trim()});
    };
    if (win.tab === 'Détails') {
      form.innerHTML = `<div class="gn-kv"><span>Vitesse de connexion</span><span>${cabled(port) ? '1000 Mb/s' : '—'}</span><span>Adresse IPv4</span><span>${
        h(address(port).split('/')[0] || '—')}</span><span>Adresse matérielle</span><span>${mac(port)}</span><span>Route par défaut</span><span>${h(gateway() || '—')}</span>
        <span>DNS</span><span>${h(dnsServer() || '—')}</span></div><div style="margin-top:22px;display:grid;gap:10px">
        <label class="gn-check"><input type="checkbox" checked> Se connecter automatiquement</label><label class="gn-check"><input type="checkbox" checked> Rendre disponible pour les autres utilisateurs</label>
        <label class="gn-check"><input type="checkbox"> Connexion limitée : a une limite de données ou peut engendrer des frais</label></div>`;
    } else if (win.tab === 'Identité') {
      form.innerHTML = `<div class="gn-kv" style="align-items:center"><span>Nom</span><input class="gn-in" value="${h(wiredName(port) === 'Câblé' ? 'Connexion filaire 1' : wiredName(port))}">
        <span>Adresse MAC</span><input class="gn-in" value="${mac(port)} (${h(port)})" disabled><span>Adresse clonée</span><input class="gn-in" disabled>
        <span>MTU</span><input class="gn-in" value="automatique" disabled></div>`;
    } else if (win.tab === 'IPv4') {
      const manual = win.mode === 'static';
      form.innerHTML = `<h4>Méthode IPv4</h4><div class="gn-radios">${[['dhcp', 'Automatique (DHCP)'], ['local', 'Réseau local seulement'], ['static', 'Manuel'],
        ['off', 'Désactiver'], ['shared', 'Partagée avec d’autres ordinateurs']].map(([k, label]) => `<label><input type="radio" name="m" value="${k}"${k === win.mode ? ' checked' : ''}${
        ['dhcp', 'static'].includes(k) ? '' : ' disabled'}> ${label}</label>`).join('')}</div>
        <h4>Adresses</h4><div class="gn-addr"><span>Adresse</span><span>Masque de réseau</span><span>Passerelle</span>
          <input class="gn-in" name="ip" value="${h(win.ip)}"${manual ? '' : ' disabled'}><input class="gn-in" name="mask" value="${h(win.mask)}"${manual ? '' : ' disabled'}>
          <input class="gn-in" name="gw" value="${h(win.gw)}"${manual ? '' : ' disabled'}></div>
        <h4>DNS <span style="display:flex;align-items:center;gap:8px;font-weight:400">Automatique ${sw(win.dnsAuto, 'data-dns="1"')}</span></h4>
        <input class="gn-in" name="dns" value="${h(win.dns)}"${win.dnsAuto ? ' disabled' : ''}><div class="gn-hint">Adresses IP séparées par des virgules</div>
        <h4>Routes <span style="display:flex;align-items:center;gap:8px;font-weight:400">Automatique ${sw(true)}</span></h4>
        <label class="gn-check" style="margin-top:6px"><input type="checkbox"> Utiliser cette connexion uniquement pour les ressources de son réseau</label>`;
      form.querySelectorAll('[name=m]').forEach(r => { r.onchange = () => { keep(); win.mode = r.value; render(); }; });
      form.querySelector('[data-dns]').onclick = () => { keep(); win.dnsAuto = !win.dnsAuto; render(); };
    } else if (win.tab === 'IPv6') {
      form.innerHTML = `<h4>Méthode IPv6</h4><div class="gn-radios">${['Automatique', 'Automatique, DHCP uniquement', 'Réseau local seulement', 'Manuel', 'Désactiver',
        'Partagée avec d’autres ordinateurs'].map((label, i) => `<label><input type="radio" name="m6"${i === 0 ? ' checked' : ''} disabled> ${label}</label>`).join('')}</div>
        <div class="gn-hint" style="margin-top:16px">IPv6 de ce PC : dans la configuration du laboratoire.</div>`;
    } else {
      form.innerHTML = `<h4>Sécurité 802.1x ${sw(false)}</h4><div class="gn-hint">L’authentification 802.1X se règle sur le switch et le serveur RADIUS du laboratoire.</div>`;
    }
    el.querySelector('[data-cancel]').onclick = () => closeWin(win.id);
    el.querySelector('[data-apply]').onclick = async () => {
      keep();
      try {
        await saveIp(port, win.mode, win.ip, win.mask, win.gw, win.dnsAuto ? '' : win.dns.split(',')[0].trim());
        closeWin(win.id);
      } catch (error) { toast(error.message, true); }
    };
  }

  /* =============================== Terminal =============================== */
  // Ubuntu's GNOME Terminal (aubergine, its coloured prompt), GNOME Console on Debian and Fedora, GNOME Terminal on Rocky.
  // Each line runs on the PC itself (/api/host_command): in its guest when the lab runs, from the project otherwise.
  function terminal(el, win) {
    const style = OS().prompt === 'ubuntu' ? 'aub' : D().brand === 'Rocky' ? 'light' : 'dark';
    const promptHtml = OS().prompt === 'ubuntu' ? `<b class="pu">${USER}@${h(host())}</b>:<b class="pp">~</b>$ `
      : OS().prompt === 'debian' ? `${USER}@${h(host())}:~$ ` : `[${USER}@${h(host())} ~]$ `;
    const title = OS().prompt === 'fedora' ? `${USER}@${host()}:~` : `${USER}@${host()}: ~`;
    win.log = win.log || '';
    el.innerHTML = `<div class="gn-hb${style === 'light' ? '' : ' dk'}"><span class="l"><button class="gn-ib" title="Nouvel onglet">${sym('list-add')}</button></span>
      <span class="t">${h(title)}</span><span class="r"><button class="gn-ib" title="Rechercher">${sym('edit-find')}</button><button class="gn-ib" title="Menu">${
      sym('open-menu')}</button>${controls()}</span></div><div class="gn-term ${style}"><span class="log"></span><span class="pr">${promptHtml}</span><input spellcheck="false"
      autocomplete="off" data-autofocus="1"></div>`;
    const term = el.querySelector('.gn-term'), input = term.querySelector('input'), log = term.querySelector('.log'), pr = term.querySelector('.pr');
    log.innerHTML = win.log;
    term.onclick = () => input.focus();
    setTimeout(() => { term.scrollTop = term.scrollHeight; });
    const print = text => { win.log += text; log.innerHTML = win.log; term.scrollTop = term.scrollHeight; };
    el.querySelectorAll('.gn-hb .l .gn-ib, .gn-hb .r .gn-ib').forEach(b => { b.onclick = () => later(b.title); });
    input.onkeydown = event => {
      if (event.key === 'l' && event.ctrlKey) { event.preventDefault(); win.log = ''; log.innerHTML = ''; return; }
      if (event.key !== 'Enter') return;
      const line = input.value.trim(), word = line.split(/\s+/)[0];
      input.value = '';
      if (word === 'clear') { win.log = ''; log.innerHTML = ''; return; }
      if (word === 'exit') return closeWin(win.id);
      print(`${promptHtml}${h(line)}\n`);
      if (!line) return;
      if (word === 'whoami') return print(`${USER}\n`);
      if (word === 'pwd') return print(`/home/${USER}\n`);
      input.disabled = true;
      pr.style.visibility = 'hidden';
      request('/api/host_command', {node, line}).then(r => r.reply, e => e.message).then(text => {
        print(text ? `${h(text.replace(/\n+$/, ''))}\n` : '');
        input.disabled = false;
        pr.style.visibility = '';
        input.focus();
      });
    };
  }

  /* =============================== Fichiers (Nautilus) =============================== */
  const PLACES = [['recent', 'document-open-recent', 'Récents'], ['starred', 'starred', 'Favoris'], ['home', 'user-home', 'Dossier personnel'], '-',
    ['desktop', 'user-desktop', 'Bureau'], ['documents', 'folder-documents', 'Documents'], ['download', 'folder-download', 'Téléchargements'],
    ['music', 'folder-music', 'Musique'], ['pictures', 'folder-pictures', 'Images'], ['videos', 'folder-videos', 'Vidéos'], ['trash', 'user-trash', 'Corbeille'], '-',
    ['other', 'list-add', 'Autres emplacements']];
  const HOME = [['user-desktop', 'Bureau'], ['folder-documents', 'Documents'], ['folder-pictures', 'Images'], ['folder-templates', 'Modèles'],
    ['folder-music', 'Musique'], ['folder-publicshare', 'Public'], ['folder-download', 'Téléchargements'], ['folder-videos', 'Vidéos']];
  function files(el, win) {
    const place = win.place || 'home', here = PLACES.find(p => p[0] === place) || PLACES[2];
    el.innerHTML = `<div class="gn-split"><div class="gn-side" style="width:220px"><div class="gn-hb"><span class="l"></span><span class="t">Fichiers</span>
        <span class="r"><button class="gn-ib" title="Menu principal">${sym('open-menu')}</button></span></div>
      <div class="gn-sl">${PLACES.map(p => (p === '-' ? '<hr>' : `<a data-place="${p[0]}" class="${p[0] === place ? 'on' : ''}">${sym(p[1])}${h(p[2])}</a>`)).join('')}</div></div>
      <div class="gn-main"><div class="gn-hb"><span class="l"><button class="gn-ib" title="Précédent">${sym('go-previous')}</button><button class="gn-ib" title="Suivant">${
        sym('go-next')}</button></span><span class="gn-path">${sym(here[1])}${h(here[2])}</span><span class="r"><button class="gn-ib" title="Rechercher">${
        sym('edit-find')}</button><button class="gn-ib" title="Menu">${sym('open-menu')}</button>${controls()}</span></div>
        ${place === 'home' ? `<div class="gn-files">${HOME.map(([icon, label]) => `<div data-open="${h(label)}">${full(icon, 72)}<span>${label}</span></div>`).join('')}</div>`
          : `<div class="gn-status" style="background:var(--gView)">${sym(here[1], 96)}<b>${place === 'trash' ? 'La corbeille est vide' : 'Le dossier est vide'}</b></div>`}</div></div>`;
    el.querySelectorAll('[data-place]').forEach(a => { a.onclick = () => { win.place = a.dataset.place; render(); }; });
    el.querySelectorAll('[data-open]').forEach(d => { d.ondblclick = () => later(d.dataset.open); });
    el.querySelectorAll('.gn-main .gn-hb .gn-ib').forEach(b => { b.onclick = () => later(b.title); });
  }

  /* =============================== the browser: the lab's web servers, fetched from this PC (/api/browse) =============================== */
  function web(el, win) {
    el.innerHTML = `<div class="gn-hb"><span class="l"><button class="gn-ib" data-back="1" title="Précédent">${sym('go-previous')}</button><button class="gn-ib" title="Suivant">${
      sym('go-next')}</button></span><input class="gn-url" spellcheck="false" placeholder="Rechercher ou saisir une adresse" value="${h(win.url || '')}">
      <span class="r"><button class="gn-ib" title="Menu">${sym('open-menu')}</button>${controls()}</span></div><div class="gn-view"><div class="gn-status">${
      full(APPS.web.icon(), 96)}<b>${h(OS().browser)}</b><span>L’adresse d’un serveur du laboratoire (http://10.0.0.10 ou http://www.lab.local) :<br>la page vient du réseau
      du laboratoire, depuis ${h(N().name)}.</span></div></div>`;
    const field = el.querySelector('.gn-url'), view = el.querySelector('.gn-view');
    win.history = win.history || [];
    const go = async (url, remember = true) => {
      url = url.trim();
      if (!url) return;
      if (!/^https?:\/\//.test(url)) url = 'http://' + url;
      field.value = url;
      let page;
      try { page = await request('/api/browse', {node, url}); } catch (error) { toast(error.message, true); return; }
      win.url = url;
      if (remember) win.history.push(url);
      if (page.error) {
        view.innerHTML = `<div class="gn-status">${sym('network-wired-disconnected', 96)}<b>Impossible de se connecter</b><span>${h(page.error)}</span></div>`;
        return;
      }
      const frame = document.createElement('iframe');
      frame.setAttribute('sandbox', 'allow-same-origin');  // the server's page, without its scripts
      frame.srcdoc = page.body;
      view.replaceChildren(frame);
      frame.onload = () => {
        const base = url.replace(/^(https?:\/\/[^/]+).*$/, '$1');
        frame.contentDocument?.querySelectorAll('a[href]').forEach(a => a.addEventListener('click', event => {
          event.preventDefault();
          const href = a.getAttribute('href');
          go(/^https?:\/\//.test(href) ? href : base + '/' + href.replace(/^\//, ''));
        }));
      };
    };
    field.addEventListener('keydown', event => { if (event.key === 'Enter') go(field.value); });
    el.querySelector('[data-back]').onclick = () => { if (win.history.length > 1) { win.history.pop(); go(win.history[win.history.length - 1], false); } };
    if (win.url) go(win.url, false);
    else setTimeout(() => field.focus());
  }
})();
