/* « Studio » look of the device pages: the dark design of the Network LABS application (icon rail, top bar, devices as
 * tiles coloured by role). native_simple.js draws the page; this file gives it the Studio colours, the role tiles and
 * the rail icons. The application tells the page its own design (state.app_design), so a page opened from the Studio
 * workbench opens in Studio unless the browser kept another choice. */
'use strict';
(() => {
  const ROLE_COLOURS = {router: ['#3b82f6', '#1d4ed8'], switch: ['#14b8a6', '#0f766e'], firewall: ['#f97316', '#c2410c'],
    host: ['#8b5cf6', '#6d28d9'], server: ['#64748b', '#334155']};
  const GLYPHS = {
    router: '<circle cx="12" cy="12" r="8.5"/><path d="M12 5.5v4M12 14.5v4M5.5 12h4M14.5 12h4M10.3 7.2L12 5.5l1.7 1.7M10.3 16.8L12 18.5l1.7-1.7'
      + 'M7.2 10.3L5.5 12l1.7 1.7M16.8 10.3l1.7 1.7-1.7 1.7"/>',
    switch: '<rect x="3" y="6" width="18" height="12" rx="2.5"/><path d="M7 10h9.5M14.5 8l2 2-2 2M17 14H7.5M9.5 12l-2 2 2 2"/>',
    firewall: '<path d="M12 3l7.5 3v5.5c0 4.6-3.2 8.2-7.5 9.5-4.3-1.3-7.5-4.9-7.5-9.5V6z"/><path d="M8 11h8M8 14.5h8M12 7.5v3.5M10 11v3.5M14 11v3.5"/>',
    host: '<rect x="3" y="4.5" width="18" height="12" rx="2"/><path d="M9 20h6M12 16.5V20"/>',
    server: '<rect x="5" y="3.5" width="14" height="5.5" rx="1.5"/><rect x="5" y="9.25" width="14" height="5.5" rx="1.5"/>'
      + '<rect x="5" y="15" width="14" height="5.5" rx="1.5"/><path d="M8 6.25h.01M8 12h.01M8 17.75h.01"/>',
  };
  const ICONS = {
    overview: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/>'
      + '<rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    ports: '<rect x="4" y="5" width="16" height="13" rx="2"/><path d="M8 18v-4h8v4M10 14v-3h4v3"/>',
    vlans: '<path d="M12 3.5l8.5 4.5-8.5 4.5L3.5 8z"/><path d="M3.5 12l8.5 4.5 8.5-4.5M3.5 16l8.5 4.5 8.5-4.5"/>',
    security: '<path d="M12 3l7.5 3v5.5c0 4.6-3.2 8.2-7.5 9.5-4.3-1.3-7.5-4.9-7.5-9.5V6z"/><path d="M9 12l2 2 4-4"/>',
    routing: '<circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="6" r="2.5"/><path d="M8.5 18H15a3 3 0 000-6H9a3 3 0 010-6h6.5"/>',
    services: '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="15" cy="6" r="2.2"/><circle cx="8.5" cy="12" r="2.2"/><circle cx="13" cy="18" r="2.2"/>',
    terminal: '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M7 9.5l3 2.5-3 2.5M12.5 15H17"/>',
    refresh: '<path d="M19 12a7 7 0 11-2.05-4.95"/><path d="M19.5 4.5v4.5H15"/>',
  };
  const svg = (paths, size, colour) => `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="${colour}" `
    + `stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;

  window.nlStudio = {
    kind: device => String(device.art || 'host').split('-')[0],
    // A device as on the workbench canvas: a rounded tile in its role's colours, its white icon, a status light.
    tile(kind, light, size = 52) {
      const [a, b] = ROLE_COLOURS[kind] || ROLE_COLOURS.host;
      const lamp = light ? `<i class="st-light ${light}"></i>` : '';
      return `<span class="st-tile" style="--a:${a};--b:${b};--s:${size}px">${svg(GLYPHS[kind] || GLYPHS.host, Math.round(size * .55), '#fff')}${lamp}</span>`;
    },
    icon: (name, size = 20, colour = 'currentColor') => svg(ICONS[name] || '', size, colour),
  };

  const css = document.createElement('style');
  css.textContent = `
  body.sd.st{background:#0c131b;color:#dbe7f3}
  .sd-app.st{color:#dbe7f3;display:grid;grid-template-columns:84px 1fr;min-height:100vh;background:#0c131b}
  .st-rail{position:sticky;top:0;height:100vh;background:#0a1017;border-right:1px solid #1d2b38;display:flex;flex-direction:column;align-items:center;
    padding:14px 0;gap:6px;box-sizing:border-box}
  .st-logo{width:38px;height:38px;border-radius:11px;display:grid;place-items:center;font-weight:700;color:#fff;margin-bottom:12px;
    background:linear-gradient(180deg,#3b82f6 0 55%,#1d4ed8 55%);box-shadow:0 3px 0 #0f2347}
  .st-rail button{width:66px;border:1px solid transparent;background:none;border-radius:12px;padding:8px 2px 7px;color:#7f95ab;cursor:pointer;
    display:flex;flex-direction:column;align-items:center;gap:4px;font:600 10.5px Inter,Arial,sans-serif;position:relative}
  .st-rail button:hover{background:#16273a;color:#dbe7f3}
  .st-rail button.on{background:#13243a;border-color:#2563eb;color:#60a5fa}
  .st-rail button em{position:absolute;top:3px;right:7px;font-style:normal;font-size:9.5px;min-width:15px;padding:0 4px;border-radius:9px;
    background:#1d2b38;color:#9fb3c8;line-height:15px}
  .st-rail button.on em{background:#1e3a5f;color:#bfdbfe}
  .st-main{min-width:0}
  .st-top{position:sticky;top:0;z-index:4;display:flex;align-items:center;gap:16px;padding:14px 28px;background:rgba(15,25,34,.94);
    backdrop-filter:blur(8px);border-bottom:1px solid #1d2b38}
  .st-top h1{margin:0;font-size:20px;color:#eef5fb;letter-spacing:-.2px}.st-top .model{color:#7f95ab;font-size:13px;margin-top:3px}
  .st-chips{display:flex;gap:7px;flex-wrap:wrap;margin-top:7px}
  .st-chip{display:inline-flex;align-items:center;gap:6px;border:1px solid #23364a;background:#132131;border-radius:999px;padding:3px 10px;
    font-size:11.5px;color:#c9d7e5}
  .st-chip i{width:7px;height:7px;border-radius:50%;background:#64748b}.st-chip i.on{background:#22c55e;box-shadow:0 0 7px #22c55e}
  .st-chip.on{color:#4ade80;border-color:#1f4d33;background:#0e2418}
  .st-tile{width:var(--s);height:var(--s);border-radius:calc(var(--s)*.3);display:grid;place-items:center;position:relative;flex:none;
    background:linear-gradient(180deg,var(--a) 0 58%,var(--b) 58%);box-shadow:0 8px 22px -8px var(--b),inset 0 1px 0 rgba(255,255,255,.28)}
  .st-light{position:absolute;right:-4px;bottom:-4px;width:15px;height:15px;border-radius:50%;background:#64748b;border:3px solid #0f1922}
  .st-light.running{background:#22c55e;box-shadow:0 0 8px #22c55e}.st-light.stopped{background:#ef4444}
  .st-seg{display:inline-flex;background:#111c27;border:1px solid #1d2b38;border-radius:12px;padding:3px}
  .st-seg button{border:0;background:none;border-radius:9px;padding:7px 13px;font:600 12.5px Inter,Arial,sans-serif;color:#9fb3c8;cursor:pointer}
  .st-seg button:hover{background:#16273a;color:#dbe7f3}.st-seg button.on{background:#2563eb;color:#fff}
  .st-action{display:inline-flex;align-items:center;gap:8px;border:1px solid #23364a;background:#132131;color:#dbe7f3;border-radius:11px;
    padding:8px 13px;font:600 13px Inter,Arial,sans-serif;cursor:pointer}
  .st-action:hover{background:#1a2c40;border-color:#2f5f99}
  .st-action.primary{background:#2563eb;border-color:#2563eb;color:#fff}.st-action.primary:hover{background:#3b82f6}
  .st-wrap{max-width:1220px;margin:0 auto;padding:22px 28px 60px}
  .st-title{display:flex;align-items:baseline;gap:10px;margin:24px 0 14px;font-size:17px;color:#eef5fb}
  .st-title small{color:#7f95ab;font-size:12.5px;font-weight:400}
  .sd-app.st .sd-chassis{background:#0f1922;border:1px solid #1d2b38;box-shadow:none}
  .sd-app.st .sd-chassis .head{color:#7f95ab}.sd-app.st .sd-chassis .head b{color:#eef5fb}
  .sd-app.st .sd-port{background:#132131;border-color:#23364a;color:#dbe7f3}
  .sd-app.st .sd-port:hover{background:#16273a;border-color:#3b82f6}.sd-app.st .sd-port.sel{background:#13243a;border-color:#60a5fa}
  .sd-app.st .sd-port .jack,.sd-app.st .sd-port .jack:after{background:#070b10;border-color:#2c4258}
  .sd-app.st .sd-port small,.sd-app.st .sd-legend{color:#7f95ab}
  .sd-app.st .sd-card{background:#121e2a;border-color:#213347;color:#dbe7f3}
  .sd-app.st .sd-card h3{color:#eef5fb}
  .sd-app.st .sd-card .sub,.sd-app.st .sd-kpi span,.sd-app.st .sd-kpi em,.sd-app.st .sd-note,.sd-app.st .sd-row .muted,
  .sd-app.st .sd-check .text small,.sd-app.st .sd-rule .what small,.sd-app.st .sd-chip small,.sd-app.st .sd-facts span{color:#7f95ab}
  .sd-app.st .sd-kpi strong{color:#eef5fb}
  .sd-app.st .sd-check,.sd-app.st .sd-row,.sd-app.st .sd-rule,.sd-app.st .sd-vlan{border-color:#1d2b38}
  .sd-app.st .sd-check.ok .mark{background:#0e2418;color:#4ade80}.sd-app.st .sd-check.warn .mark{background:#2a2412;color:#fbbf24}
  .sd-app.st .sd-check.info .mark{background:#13243a;color:#60a5fa}
  .sd-app.st .sd-btn,.sd-app.st .sd-chip,.sd-app.st .sd-icon{background:#132131;border-color:#23364a;color:#dbe7f3}
  .sd-app.st .sd-btn:hover,.sd-app.st .sd-chip:hover,.sd-app.st .sd-icon:hover{background:#1a2c40;border-color:#2f5f99}
  .sd-app.st .sd-btn.primary{background:#2563eb;border-color:#2563eb;color:#fff}.sd-app.st .sd-btn.primary:hover{background:#3b82f6}
  .sd-app.st .sd-search,.sd-app.st .sd-drawer input,.sd-app.st .sd-drawer select{background:#0c141d;border-color:#23364a;color:#dbe7f3}
  .sd-app.st .sd-search::placeholder,.sd-app.st .sd-drawer input::placeholder{color:#5d7288}
  .sd-app.st .sd-tag{background:#1a2836;color:#9fb3c8}.sd-app.st .sd-tag[style]{color:#dbe7f3!important}
  .sd-app.st .sd-tag.green{background:#0e2418;color:#4ade80}.sd-app.st .sd-tag.red{background:#2a1416;color:#f87171}
  .sd-app.st .sd-tag.blue{background:#13243a;color:#93c5fd}.sd-app.st .sd-tag.violet{background:#1f1838;color:#c4b5fd}
  .sd-app.st .sd-rule .n{background:#1a2836;color:#9fb3c8}
  .sd-app.st .sd-empty{background:#0f1922;color:#7f95ab;border:1px dashed #213347}
  .sd-app.st .sd-shade{background:rgba(3,8,14,.6)}
  .sd-app.st .sd-drawer{background:#0f1922;color:#dbe7f3;box-shadow:-18px 0 40px rgba(0,0,0,.5);border-left:1px solid #1d2b38}
  .sd-app.st .sd-drawer .head,.sd-app.st .sd-drawer .foot{border-color:#1d2b38}.sd-app.st .sd-drawer label{color:#9fb3c8}
  .sd-app.st .sd-drawer a{color:#93c5fd}
  .sd-app.st .sd-seg{background:#0c141d;border:1px solid #1d2b38}.sd-app.st .sd-seg button{color:#9fb3c8}
  .sd-app.st .sd-seg button.on{background:#1e3a5f;color:#bfdbfe;box-shadow:none}
  .sd-app.st .sd-err{color:#f87171}
  body.st .sd-toast{background:#1a2c40;border:1px solid #2f5f99;color:#eef5fb}
  /* The full editors (rules and NAT, DHCP, sub-interfaces…) reached from a Studio page: the same dark colours. */
  body.stb{background:#0c131b;color:#dbe7f3}
  body.stb header{background:#0f1922;border:1px solid #1d2b38}body.stb header span{color:#7f95ab}
  body.stb aside{background:#0a1017;border:1px solid #1d2b38}body.stb aside .muted{color:#5d7288}
  body.stb aside button{color:#9fb3c8;background:transparent;border-color:transparent}body.stb aside button:hover{background:#16273a}
  body.stb aside button.active{background:#13243a;border-color:#2563eb;color:#60a5fa}
  body.stb button,body.stb input,body.stb select,body.stb textarea{background:#132131;border-color:#23364a;color:#dbe7f3}
  body.stb button:hover{background:#1a2c40}body.stb input:focus,body.stb select:focus{outline-color:#3b82f6}
  body.stb .primary,body.stb .observe{background:#2563eb;border-color:#2563eb;color:#fff}body.stb .primary:hover{background:#3b82f6}
  body.stb .card,body.stb .panel,body.stb .kpi{background:#121e2a;border-color:#213347}
  body.stb .metric,body.stb .empty{background:#0f1922;color:#7f95ab}
  body.stb h1,body.stb h2,body.stb .kpi strong{color:#eef5fb}
  body.stb .muted,body.stb label,body.stb .kpi span,body.stb .kpi em,body.stb .legend{color:#7f95ab}
  body.stb .table{border-color:#213347}body.stb th{background:#132131;color:#9fb3c8;border-color:#1d2b38}body.stb td{border-color:#1d2b38}
  body.stb tr.selected td,body.stb .selected td{background:#13243a}
  body.stb .notice{background:#0f1d2c;color:#c9d7e5}body.stb #message.error{background:#2a1416;color:#f87171}
  body.stb fieldset{border-color:#213347}body.stb legend{color:#c9d7e5}
  body.stb .badge{background:#1a2836;color:#9fb3c8}body.stb .good,body.stb .verdict.ok{color:#4ade80}body.stb .verdict.bad{color:#f87171}
  body.stb .tag.allow,body.stb .tag.ok{background:#0e2418;color:#4ade80}body.stb .tag.deny,body.stb .tag.bad{background:#2a1416;color:#f87171}
  body.stb .tag.c{background:#13243a;color:#93c5fd}body.stb .tag.s,body.stb .tag.extra{background:#2a2412;color:#fbbf24}
  body.stb .tag.t{background:#1f1838;color:#c4b5fd}
  body.stb input[type=checkbox]{background:#2c4258}body.stb input[type=checkbox]:checked{background:#2563eb}
  @media (max-width:900px){.sd-app.st{grid-template-columns:1fr}.st-rail{position:static;height:auto;flex-direction:row;flex-wrap:wrap;justify-content:center}
    .st-logo{display:none}.st-top{flex-wrap:wrap}}
  `;
  document.head.appendChild(css);
})();
