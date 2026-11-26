/* pfSense and OPNsense in their own web interfaces, drawn with the stylesheets the two projects publish: pfSense's
 * Bootstrap 3 theme (pfSense.css and login.css, Apache License 2.0) and OPNsense's theme (BSD 2-Clause), with the
 * Font Awesome Free icons both use. The markup is the products' own: navbar, breadcrumb, panels, striped tables and
 * form-horizontal forms for pfSense; side menu, content boxes, help toggles and grids for OPNsense. The products'
 * logos are left out, their names are written instead. Changes wait for « Apply Changes », as on the products
 * (engine: native_products.js; files: appliances/assets/pfsense, opnsense, fontawesome). */
'use strict';
(() => {
  const K = window.nlProductsKit;
  if (!K) return;
  const {SKINS, D, N, h, maskOf, ipOf, lenOf, networkOf, validIp, running, openTerminal, stage, pending, candidateFw, editFw, addressOf,
    staticRoutes, commit, val, NA, ruleFrom, checkNet, dhcpServer, natBuild, putEntry, dropEntry, portName, attempt, skinCss} = K;
  const V = () => K.view;
  const FA = '/ui/fontawesome/css/all.min.css';
  const year = new Date().getFullYear();

  skinCss(`
  :where(.px-app.pfsense,.px-app.opnsense,.px-login.lg-own) :is(header,aside,footer,nav,main){all:revert;box-sizing:border-box}
  :where(.px-app.pfsense,.px-app.opnsense,.px-login.lg-own) .table{border:0;border-radius:0;overflow:visible}
  :where(.px-app.pfsense,.px-app.opnsense,.px-login.lg-own) label{box-sizing:border-box}
  :where(.px-app.pfsense,.px-app.opnsense,.px-login.lg-own) header span{color:inherit}:where(.px-app.pfsense,.px-app.opnsense,.px-login.lg-own) header strong{font-size:inherit}
  :where(.px-app.pfsense,.px-app.opnsense) .panel{padding:0;margin-top:0}:where(.px-app.pfsense,.px-app.opnsense) .badge{margin-top:0}
  .px-app.pfsense,.px-app.opnsense,.px-app.px-login.lg-own{font:inherit;color:inherit}
  .px-app.pfsense{padding-bottom:60px;min-height:100vh;position:relative}
  .px-app.pfsense .navbar-brand{display:flex;align-items:flex-end;gap:7px;height:50px;padding:0 10px 9px;line-height:1}
  .pf-word{color:#fff;font:500 27px/1 Roboto,sans-serif;letter-spacing:-.5px}
  .px-app.pfsense .navbar-nav>li>a{cursor:pointer}.px-app.pfsense .dropdown-menu a{cursor:pointer}
  .px-app.pfsense .dropdown-menu a.nl-na{color:#9e9e9e}
  .px-app.pfsense .panel-body .table{margin-bottom:0}.px-app.pfsense .panel-body>p,.px-app.pfsense .panel-body>.nl-pad{padding:10px 15px;margin:0}
  .px-app.pfsense .widget-heading-icon a{cursor:pointer;margin-left:4px}
  .px-app.pfsense td a[class*=fa-]{cursor:pointer;margin-right:3px}.px-app.pfsense .nav-pills a{cursor:pointer}
  .px-app.pfsense .nl-hint{color:#757575}
  .px-login.pfsense-login .lg-hint{display:block;margin-top:22px;color:#fff;opacity:.7;font-size:12px;text-align:center}
  .px-login.pfsense-login #logodiv{display:flex;align-items:center;justify-content:center}
  .px-login.pfsense-login .pf-word{color:#212121;font-size:40px}
  .px-app.opnsense .navbar-brand{display:flex;align-items:center;height:62px;padding:0 20px}
  .op-word{font:600 26px/1 SourceSansProSemibold,SourceSansProRegular,sans-serif;color:#3c3c3c;letter-spacing:-.2px}.op-word b{color:#d94f00;font-weight:inherit}
  .px-app.opnsense #mainmenu a{cursor:pointer}.px-app.opnsense #mainmenu a.nl-na{color:#9a9a9a}
  .px-app.opnsense .showhelp,.px-app.opnsense .op-fullhelp,.px-app.opnsense .btn{cursor:pointer}
  .px-app.opnsense .content-box-main{padding:0}.px-app.opnsense .content-box-head{padding:10px 15px}.px-app.opnsense .content-box-head h3{font-size:16px}
  .px-app.opnsense .op-widgets{display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start}
  .px-app.opnsense .nl-pad{padding:12px 15px;margin:0}.px-app.opnsense .modal{overflow-y:auto}.px-app.opnsense .selectpicker{min-width:72px}
  .px-login.opnsense-login .lg-hint{display:block;margin-top:14px;color:#777;font-size:12px}
  .px-login.opnsense-login .login-modal-head{display:flex;align-items:center}
  `);

  // ---- what both products show and stage the same way ----
  const ports = () => Object.keys(N().interfaces);
  const ifName = port => { const i = ports().indexOf(port); return i < 0 ? port : i === 0 ? 'WAN' : i === 1 ? 'LAN' : `OPT${i - 1}`; };
  const portOf = p => D().ports.find(x => x.port === p) || {};
  const up = p => Boolean(p.peer && !p.down);
  const fa = (name, extra = '', title = '') => `<i class="fa-solid fa-${name}${extra ? ' ' + extra : ''}"${title ? ` title="${h(title)}"` : ''}></i>`;
  const options = (list, chosen) => list.map(o => { const [v, l, off] = Array.isArray(o) ? o : [o, o];
    return `<option value="${h(v)}"${String(v) === String(chosen) ? ' selected' : ''}${off ? ' disabled' : ''}>${h(l)}</option>`; }).join('');
  const sel = (id, list, chosen, extra = '') => `<select class="form-control" id="${id}" ${extra}>${options(list, chosen)}</select>`;
  const inp = (id, value = '', extra = '') => `<input class="form-control" type="text" id="${id}" value="${h(value)}" ${extra}>`;
  const chk = (id, on, text, extra = '') => `<label class="chkboxlbl"><input type="checkbox" id="${id}"${on ? ' checked' : ''} ${extra}> ${h(text)}</label>`;
  const masks = (low = 1) => Array.from({length: 33 - low}, (_, k) => 32 - k);
  const go = (page, extra = {}) => { Object.assign(V(), {page, tab: null, edit: null, flash: null}, extra); render(); window.scrollTo(0, 0); };
  const rulesOn = tab => candidateFw().rules.map((r, i) => [r, i]).filter(([r]) => (tab === 'floating' ? !r.in : r.in === tab));
  const proto = r => (!r.protocol || r.protocol === 'any' ? '*' : r.protocol.toUpperCase());
  const forwards = () => (candidateFw().nat || []).map((r, i) => [r, i]).filter(([r]) => r.type === 'dnat');
  const outbound = () => (candidateFw().nat || []).map((r, i) => [r, i]).filter(([r]) => r.type !== 'dnat');
  const dhcpNow = () => (V().stage && V().stage.dhcp !== undefined ? V().stage.dhcp : dhcpServer());
  const gateways = () => (N().gateway ? [{name: `${ifName(ports()[0])}_GW`, port: ports()[0], ip: N().gateway}] : []);
  const PORTS = [['', '(other)'], ['any', 'any'], ['80', 'HTTP (80)'], ['443', 'HTTPS (443)'], ['22', 'SSH (22)'], ['53', 'DNS (53)'], ['25', 'SMTP (25)'],
    ['21', 'FTP (21)'], ['23', 'Telnet (23)'], ['3389', 'MS RDP (3389)'], ['123', 'NTP (123)'], ['161', 'SNMP (161)']];
  const PROTOS = [['any', 'Any'], ['tcp', 'TCP'], ['udp', 'UDP'], ['tcp/udp', 'TCP/UDP', true], ['icmp', 'ICMP']];
  // An address as the rule pages ask it: a type, then the address and its mask.
  const where = (prefix, value) => {
    const [ip, len] = String(value || '').split('/');
    const kind = !value ? 'any' : len === '32' || !len ? 'single' : 'network';
    return {kind, ip: value ? ip : '', len: len || 32};
  };
  // Single host: the address alone (/32), unless its mask can be chosen (OPNsense's « Single host or Network »).
  const readWhere = (form, prefix, what) => {
    const kind = val(form, `#${prefix}Type`), ip = val(form, `#${prefix}`), mask = form.querySelector(`#${prefix}Len`);
    if (!kind || kind === 'any') return '';
    if (kind === 'wanaddr') return ipOf(addressOf(val(form, '#nxIn') || ports()[0])) + '/32';
    return checkNet(`${ip}/${mask && !mask.disabled ? mask.value : 32}`, what);
  };
  const portFrom = form => val(form, '#pfPort') || (['', 'any'].includes(val(form, '#pfPortSel')) ? '' : val(form, '#pfPortSel'));
  function readRule(form, base) {
    const protocol = val(form, '#pfProto'), port = portFrom(form);
    return ruleFrom(base, {name: val(form, '#pfName') || `rule-${candidateFw().rules.length + 1}`, action: val(form, '#pfAct'), in: val(form, '#pfIn'),
      out: val(form, '#pfOut'), source: readWhere(form, 'pfSrc', 'Source'), destination: readWhere(form, 'pfDst', 'Destination'),
      service: protocol === 'any' ? 'any' : protocol === 'icmp' ? 'icmp' : `${protocol}/${port}`.replace(/\/$/, '')});
  }
  const putRule = (index, rule) => { const list = editFw().rules; if (index === null) list.push(rule); else list[index] = rule; };
  const readNat = (form, type) => {
    const p = val(form, '#nxProto'), port = val(form, '#nxPort') || (['', 'any'].includes(val(form, '#nxPortSel')) ? '' : val(form, '#nxPortSel'));
    return natBuild({type, name: val(form, '#nxName'), in: val(form, '#nxIn'), out: val(form, '#nxOut'), source: readWhere(form, 'nxSrc', 'Source'),
      destination: readWhere(form, 'nxDst', 'Destination'), service: p === 'any' ? 'any' : port ? `${p}/${port}` : p, to: val(form, '#nxTo'),
      to_port: val(form, '#nxToPort')});
  };
  function readIface(form, port) {
    const type = val(form, '#pfType'), ip = val(form, '#pfIp');
    if (type === 'staticv4' && !validIp(ip)) throw new Error('A valid IPv4 address must be specified.');
    stage().ifaces[port] = type === 'staticv4' ? `${ip}/${val(form, '#pfLen')}` : '';
  }
  // A route is checked first, then the edited one is replaced: a refused save leaves the list as it was.
  function saveRoute(form, index) {
    const net = val(form, '#pfNet'), gw = val(form, '#pfGw') || val(form, '#pfGwSel');
    if (!validIp(net)) throw new Error('A valid IPv4 destination network must be specified.');
    if (!validIp(gw)) throw new Error('A valid gateway must be specified.');
    if (index !== null) dropRoute(index);
    stage().routes.add.push({network: networkOf(`${net}/${val(form, '#pfNetLen')}`), gateway: gw, port: ''});
  }
  function dropRoute(i) {
    const r = staticRoutes()[i], st = stage();
    if (st.routes.add.includes(r)) st.routes.add.splice(st.routes.add.indexOf(r), 1); else st.routes.del.push(r.network);
  }
  function readDhcp(form, port) {
    const now = dhcpNow();
    if (!form.querySelector('#pfOn').checked) { if (now && now.interface === port) stage().dhcp = null; return; }
    const from = val(form, '#pfFrom'), to = val(form, '#pfTo'), gw = val(form, '#pfGw'), lease = val(form, '#pfLease');
    if (!validIp(from) || !validIp(to)) throw new Error('A valid range must be specified.');
    if (gw && !validIp(gw)) throw new Error('A valid IP address must be specified for the gateway.');
    if (lease && !(Number(lease) >= 60)) throw new Error('The default lease time must be at least 60 seconds.');
    const dns = val(form, '#pfDns').split(/[ ,]+/).filter(Boolean);
    if (dns.some(x => !validIp(x))) throw new Error('A valid IP address must be specified for each of the DNS servers.');
    stage().dhcp = {interface: port, start: from, end: to, router: gw || ipOf(addressOf(port)), dns, lease_seconds: Number(lease) || 7200,
      reservations: (now && now.interface === port && now.reservations) || []};
  }
  function readHost(form) {
    const name = val(form, '#pfHost');
    if (!/^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/.test(name)) throw new Error('The hostname contains invalid characters.');
    stage().name = name !== N().name ? name : null;
  }
  const changed = () => { const s = V().stage; if (!s) return ''; if (s.fw) return 'firewall rule'; if (s.routes.add.length || s.routes.del.length) return 'static route';
    if (Object.keys(s.ifaces).length) return 'interface'; if (s.dhcp !== undefined) return 'DHCP Server'; return 'system'; };
  const apply = () => attempt(async () => { await commit(null); V().flash = 'applied'; });
  // A refused save lists its errors above the form, the typed values stay (the products post back the same values).
  function refuse(root, message) {
    root.querySelector('.input-errors')?.remove();
    const box = document.createElement('div');
    box.className = 'alert alert-danger input-errors';
    box.setAttribute('role', 'alert');
    box.innerHTML = `<p>The following input errors were detected:</p><ul><li>${h(message)}</li></ul>`;
    const header = root.querySelector('.header');
    if (header) header.after(box); else root.prepend(box);
    window.scrollTo(0, 0);
  }
  const submit = (root, work, next) => {
    const form = root.querySelector('form.nl-form');
    form.onsubmit = event => {
      event.preventDefault();
      try { work(form); } catch (error) { refuse(root, error.message); return; }
      next ? next() : render();
    };
  };
  const later = what => `<div class="alert alert-info clearfix" role="alert"><div class="pull-left">${h(what)}<br><small>Network LABS : ce menu existe sur le
    produit réel ; il est montré pour situer la fonction.</small></div></div>`;

  document.addEventListener('click', event => {
    if (!event.target.closest('#topmenu .dropdown')) document.querySelectorAll('#topmenu li.open').forEach(x => x.classList.remove('open'));
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('#topmenu li.open').forEach(x => x.classList.remove('open'));
    if (document.querySelector('.px-app.opnsense .modal.in')) { V().edit = null; render(); }
  });

  /* =============================== pfSense =============================== */
  const PF_MENU = () => [
    ['System', [['Advanced'], ['Certificates'], ['General Setup', 'general'], ['High Availability'], ['Package Manager'], ['Register'], ['Routing', 'routing'],
      ['Setup Wizard'], ['Update'], ['User Manager'], ['User Password Manager'], ['User Settings'], ['-'], ['Logout (admin)', 'logout']]],
    ['Interfaces', [['Assignments', 'assign'], ['-'], ...ports().map(p => [ifName(p), 'if:' + p])]],
    ['Firewall', [['Aliases'], ['NAT', 'nat'], ['Rules', 'rules'], ['Schedules'], ['Traffic Shaper'], ['Virtual IPs']]],
    ['Services', [['Auto Config Backup'], ['Captive Portal'], ['DHCP Relay'], ['DHCP Server', 'dhcp'], ['DHCPv6 Relay'], ['DHCPv6 Server'], ['DNS Forwarder'],
      ['DNS Resolver'], ['Dynamic DNS'], ['IGMP Proxy'], ['NTP'], ['PPPoE Server'], ['Router Advertisement'], ['SNMP'], ['UPnP IGD & PCP'], ['Wake-on-LAN']]],
    ['VPN', [['IPsec', 'vpn'], ['L2TP', 'vpn'], ['OpenVPN', 'vpn']]],
    ['Status', [['Captive Portal'], ['CARP (failover)'], ['Dashboard', 'dashboard'], ['DHCP Leases'], ['DHCPv6 Leases'], ['DNS Resolver'], ['Filter Reload'],
      ['Gateways', 'status-gw'], ['Interfaces', 'status-if'], ['IPsec', 'vpn'], ['NTP'], ['OpenVPN', 'vpn'], ['Queues'], ['Services'], ['System Logs'], ['Traffic Graph'],
      ['UPnP IGD & PCP']]],
    ['Diagnostics', [['ARP Table'], ['Authentication'], ['Backup & Restore'], ['Command Prompt', 'terminal'], ['DNS Lookup'], ['Edit File'], ['Factory Defaults'],
      ['Halt System'], ['Limiter Info'], ['NDP Table'], ['Packet Capture'], ['pfInfo'], ['pfTop'], ['Ping', 'terminal'], ['Reboot'], ['Routes', 'diag-routes'],
      ['S.M.A.R.T. Status'], ['Sockets'], ['States'], ['States Summary'], ['System Activity'], ['Tables'], ['Test Port'], ['Traceroute', 'terminal']]],
    ['Help', [['About this Page'], ['Bug Database'], ['Documentation'], ['FreeBSD Handbook'], ['Paid Support'], ['pfSense Book'], ['Upgrade to pfSense Plus'],
      ['User Forum']]]];
  const pfCredit = () => `<a>pfSense</a> is developed and maintained by <a>Netgate.</a> &copy; ESF 2004 - ${year} <a>View license.</a>`;
  SKINS.pfsense = {
    start: {page: 'dashboard'},
    sheets: [FA, '/ui/pfsense/pfSense.css'],
    login: {sheets: ['/ui/pfsense/bootstrap.min.css', '/ui/pfsense/login.css'], error: 'Username or Password incorrect', draw: pfLogin},
    draw(root) {
      const page = pfPage();
      root.innerHTML = `<nav id="topmenu" class="navbar navbar-static-top navbar-inverse"><div class="container"><div class="navbar-header">
        <a class="navbar-brand" data-go="dashboard"><span class="pf-word">pfSense</span><span style="color:white;font-size:.5em;text-transform:uppercase;letter-spacing:1px;">
        Community Edition</span></a></div><div class="collapse navbar-collapse" id="pf-navbar"><ul class="nav navbar-nav">${PF_MENU().map(([name, items]) =>
          `<li class="dropdown"><a class="dropdown-toggle" role="button" aria-expanded="false">${h(name)} <span class="caret"></span></a><ul class="dropdown-menu" role="menu">${
            items.map(([label, target]) => (label === '-' ? '<li class="divider"></li>' : `<li><a class="navlnk${target ? '' : ' nl-na'}" data-go="${target || 'na'}"
              data-title="${h(name + '/' + label)}">${h(label)}</a></li>`)).join('')}</ul></li>`).join('')}</ul>
        <ul class="nav navbar-nav navbar-right"><li class="dropdown"><a data-go="logout">${fa('right-from-bracket', '', `Logout (admin@${N().name}.home.arpa)`)}</a></li></ul></div></div></nav>
        <div class="container static"><div class="header"><ol class="breadcrumb">${page.crumbs.map((c, i) => (i === 0 ? `<li>${h(c)}</li>` : `<li${
          i === page.crumbs.length - 1 ? ' class="active"' : ''}><a>${h(c)}</a></li>`)).join('')}</ol><ul class="context-links">${(page.links || []).join('')}
          <li><a title="Help for items on this page">${fa('question-circle', 'icon-pointer')}</a></li></ul></div>${pfNotices()}${page.html}</div>
        <footer class="footer"><div class="container"><p class="text-muted">${pfCredit()}</p></div></footer>`;
      root.querySelectorAll('#topmenu .dropdown-toggle').forEach(a => { a.onclick = event => {
        event.stopPropagation();
        const li = a.parentElement, open = li.classList.contains('open');
        root.querySelectorAll('#topmenu li.open').forEach(x => x.classList.remove('open'));
        li.classList.toggle('open', !open);
      }; });
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => {
        const target = a.dataset.go;
        if (target === 'logout') return K.logout();
        if (target === 'terminal') { openTerminal(); return root.querySelectorAll('#topmenu li.open').forEach(x => x.classList.remove('open')); }
        go(target, {title: a.dataset.title || ''});
      }; });
      root.querySelector('.alert .apply')?.addEventListener('click', apply);
      root.querySelector('.alert .close')?.addEventListener('click', () => { V().flash = null; render(); });
      root.querySelectorAll('.widget-heading-icon .nl-fold').forEach(a => { a.onclick = () => {
        const body = a.closest('.panel').querySelector('.panel-body');
        body.classList.toggle('in');
        a.querySelector('i').className = body.classList.contains('in') ? 'fa-solid fa-minus-circle' : 'fa-solid fa-plus-circle';
      }; });
      root.querySelectorAll('.widget-heading-icon .nl-shut').forEach(a => { a.onclick = () => a.closest('.panel').remove(); });
      page.wire?.(root.querySelector('.container.static'));
    },
  };
  function pfNotices() {
    const what = changed();
    if (pending()) {
      return `<div class="alert alert-warning clearfix" role="alert"><div class="pull-left">The ${h(what)} configuration has been changed.<br>The changes must be
        applied for them to take effect.</div><form class="pull-right" onsubmit="return false"><button type="button" class="btn btn-success apply" name="apply"
        value="Apply Changes"><i class="fa-solid fa-check icon-embed-btn"></i>Apply Changes</button></form></div>`;
    }
    if (V().flash === 'applied') {
      return `<div class="alert alert-success clearfix" role="alert"><button type="button" class="close" aria-label="Close"><span aria-hidden="true">&times;</span></button>
        <div class="pull-left">The changes have been applied successfully. The firewall rules are now reloading in the background.<br>Monitor the filter reload progress.</div></div>`;
    }
    return '';
  }
  function pfPage() {
    const page = V().page || 'dashboard';
    if (page.startsWith('if:')) return pfInterface(page.slice(3));
    const pages = {dashboard: pfDashboard, rules: pfRules, 'rule-edit': pfEditRule, nat: pfNat, 'nat-edit': pfEditNat, assign: pfAssign, routing: pfRouting,
      'route-edit': pfEditRoute, dhcp: pfDhcp, general: pfGeneral, 'status-if': pfStatusIf, 'status-gw': pfStatusGw, 'diag-routes': pfDiagRoutes};
    if (pages[page]) return pages[page]();
    const crumbs = (V().title || 'Status/Dashboard').split('/');
    return {crumbs, html: later(page === 'vpn' ? NA.vpn : NA.later)};
  }
  const panel = (title, body, extra = '') => `<div class="panel panel-default"${extra}><div class="panel-heading"><h2 class="panel-title">${title}</h2></div>
    <div class="panel-body">${body}</div></div>`;
  const pfTabs = (tabs, active) => `<ul class="nav nav-pills">${tabs.map(([key, label]) => `<li role="presentation"${key === active ? ' class="active"' : ''}>
    <a data-t="${h(key)}">${h(label)}</a></li>`).join('')}</ul>`;
  const wireTabs = (main, extra = {}) => main.querySelectorAll('.nav-pills [data-t]').forEach(a => { a.onclick = () => { Object.assign(V(), {tab: a.dataset.t, flash: null}, extra); render(); }; });
  // One form-horizontal form: sections of labelled rows, then Save (the products' Form classes).
  const group = (label, control, help = '', required = false) => `<div class="form-group"><label class="col-sm-2 control-label">${
    required ? `<span class="element-required">${h(label)}</span>` : h(label)}</label>${control.startsWith('<div class="col-') ? control
    : `<div class="col-sm-10">${control}${help ? `<span class="help-block">${help}</span>` : ''}</div>`}</div>`;
  const pfForm = (sections, extra = '') => `<form class="form-horizontal nl-form" method="post" autocomplete="off">${sections.map(([title, rows, id]) =>
    `<div class="panel panel-default"${id ? ` id="${id}"` : ''}><div class="panel-heading"><h2 class="panel-title">${h(title)}</h2></div><div class="panel-body">${rows.join('')}</div></div>`)
    .join('')}${extra}<div class="col-sm-10 col-sm-offset-2"><button class="btn btn-primary save" type="submit" value="Save" name="save"><i class="fa-solid fa-save icon-embed-btn">
    </i>Save</button></div></form>`;
  const ipMask = (ipId, ip, lenId, len, low = 1, holder = '') => `<div class="col-sm-4"><div class="input-group">${inp(ipId, ip, holder ? `placeholder="${holder}"` : '')}
    <span class="input-group-addon input-group-inbetween pfIpMask">/</span><select class="form-control pfIpMask" id="${lenId}">${options(masks(low), len)}</select></div></div>`;
  const widget = (title, body, link = '') => `<div class="panel panel-default"><div class="panel-heading"><h2 class="panel-title">${link ? `<a data-go="${link}"> ${h(title)}</a>` : h(title)}
    <span class="widget-heading-icon"><a class="config hidden">${fa('wrench')}</a><a class="nl-fold">${fa('minus-circle')}</a><a class="nl-shut">${fa('times-circle')}</a></span>
    </h2></div><div class="panel-body collapse in">${body}</div></div>`;

  function pfDashboard() {
    const n = N(), d = D(), mem = n.memory_mib || 128, on = running();
    const bar = (pct, id) => `<div class="progress"><div id="${id}" class="progress-bar progress-bar-striped" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0"
      aria-valuemax="100" style="width: ${pct}%"></div></div>`;
    const system = [['Name', `${h(n.name)}.home.arpa`], ['User', 'admin@127.0.0.1 (Local Database)'], ['System', `${h(d.brand)} ${h(d.model)}<br>Network LABS micro-VM`],
      ['Version', '<strong>Network LABS</strong> (Linux micro-VM)<br><span class="nl-hint">The pfSense pages, on the laboratory\'s Linux node.</span>'],
      ['CPU Type', `${h(n.vcpus || 1)} CPU${(n.vcpus || 1) > 1 ? 's' : ''}: 1 package(s)`], ['Uptime', on ? 'Running (lab started)' : 'Lab stopped'],
      ['Current date/time', h(new Date().toString().replace(/ GMT.*$/, ''))], ['DNS server(s)', '<ul style="margin-bottom:0;padding-left:16px"><li>127.0.0.1</li></ul>'],
      ['Last config change', h(new Date().toString().replace(/ GMT.*$/, ''))],
      ['State table size', `${bar(0, 'statePB')}<span>0% (0/${mem * 800})</span> <a>Show states</a>`], ['MBUF Usage', `${bar(on ? 1 : 0, 'mbufPB')}<span>${on ? 1 : 0}% (${on ? 508 : 0}/${mem * 160})</span>`],
      ['Load average', '0.00, 0.00, 0.00'], ['CPU usage', `${bar(on ? 1 : 0, 'cpuPB')}<span>${on ? 1 : 0}%</span>`],
      ['Memory usage', `${bar(on ? 35 : 0, 'memUsagePB')}<span>${on ? 35 : 0}% of ${h(mem)} MiB</span>`], ['Disk usage:', '<table class="table" style="margin:0"><tbody><tr><td>/</td>' +
        `<td style="width:60%">${bar(12, 'diskPB')}</td><td>12% of 1.0GiB - ufs</td></tr></tbody></table>`]];
    const ifs = `<table class="table table-striped table-hover table-condensed"><tbody>${d.ports.map(p => {
      const state = up(p) ? ['arrow-up', 'text-success', 'up'] : p.down ? ['arrow-down', 'text-danger', 'down'] : ['times-circle', 'text-danger', 'no carrier'];
      return `<tr><td title="${h(portName(p.port))}" style="white-space: nowrap;">${fa('sitemap')} <a data-go="if:${h(p.port)}">${h(ifName(p.port))}</a></td>
        <td>${fa(state[0], state[1], state[2])}</td><td>${up(p) ? '1000baseT &lt;full-duplex&gt;' : 'none'}</td><td>${h(ipOf(addressOf(p.port)) || 'n/a')}</td></tr>`; }).join('')}</tbody></table>`;
    const gws = `<table class="table table-striped table-hover table-condensed"><thead><tr><th>Name</th><th>RTT</th><th>RTTsd</th><th>Loss</th><th>Status</th></tr></thead><tbody>${
      gateways().map(g => `<tr><td><span class="gwname">${h(g.name)}</span><br><span class="gwip">${h(g.ip)}</span></td><td>—</td><td>—</td><td>—</td>
        <td class="${on ? 'bg-success' : 'bg-info'}">${on ? 'Online' : 'Unknown'}</td></tr>`).join('') || '<tr><td colspan="5">No gateways found.</td></tr>'}</tbody></table>`;
    const f = candidateFw();
    const rules = `<table class="table table-striped table-hover table-condensed"><tbody><tr><th>Firewall rules</th><td>${f.rules.length}</td></tr><tr><th>NAT entries</th>
      <td>${(f.nat || []).length}</td></tr><tr><th>Static routes</th><td>${staticRoutes().length}</td></tr></tbody></table>`;
    return {crumbs: ['Status', 'Dashboard'], links: [`<li><a title="Available Widgets">${fa('plus', 'icon-pointer')}</a></li>`],
      html: `<div class="row" id="widgetSequence_" ><div class="col-md-6" id="widgets-col1">${widget('System Information', `<table class="table table-hover table-striped table-condensed">
        <tbody>${system.map(([k, v]) => `<tr><th>${k}</th><td>${v}</td></tr>`).join('')}</tbody></table>`)}</div>
        <div class="col-md-6" id="widgets-col2">${widget('Interfaces', ifs, 'status-if')}${widget('Gateways', gws, 'status-gw')}${widget('Firewall Rules', rules, 'rules')}</div></div>`};
  }

  function pfRules() {
    const tab = V().tab || ports()[1] || ports()[0], floating = tab === 'floating', list = rulesOn(tab);
    const tabs = [['floating', 'Floating'], ...ports().map(p => [p, ifName(p)])];
    const rows = list.map(([r, i]) => `<tr id="fr${i}"><td><input type="checkbox" data-c="${i}"></td><td title="traffic is ${r.action === 'accept' ? 'passed' : 'blocked'}">${
      r.action === 'accept' ? fa('check', 'text-success') : fa('times', 'text-danger')}</td><td><a title="States details">0/0 B</a></td>${floating ? `<td>${h(r.out ? ifName(r.out) : 'any')}</td>` : ''}
      <td>IPv4 ${h(proto(r))}</td><td>${h(r.source || '*')}</td><td>*</td><td>${h(r.destination || '*')}</td><td>${h(r.dport || '*')}</td><td>${h(r.out && !floating ? ifName(r.out) : '*')}</td>
      <td>none</td><td></td><td>${h(r.name)}</td><td class="text-nowrap"><a class="fa-solid fa-anchor icon-pointer" title="Move checked rules above this one" data-m="${i}"></a>
      <a class="fa-solid fa-pencil" title="Edit" data-e="${i}"></a><a class="fa-regular fa-clone" title="Copy" data-k="${i}"></a>
      <a class="fa-solid fa-trash-can" title="Delete this rule" data-x="${i}"></a></td></tr>`).join('');
    const head = ['<input type="checkbox" id="selectAll" name="selectAll">', '', 'States', ...(floating ? ['Interfaces'] : []), 'Protocol', 'Source', 'Port', 'Destination', 'Port',
      'Gateway', 'Queue', 'Schedule', 'Description', 'Actions'];
    const empty = `<div class="alert alert-warning" role="alert"><p>${floating ? 'No floating rules are currently defined.' : 'No rules are currently defined for this interface<br>' +
      'All incoming connections on this interface will be blocked until pass rules are added.'} Click the button to add a new rule.</p></div>`;
    return {crumbs: ['Firewall', 'Rules', floating ? 'Floating' : ifName(tab)], links: [`<li><a title="Related status">${fa('sliders', 'icon-pointer')}</a></li>`,
      `<li><a title="Related log entries">${fa('list-alt', 'icon-pointer')}</a></li>`],
      html: `${pfTabs(tabs, tab)}<form id="mainform" method="post" onsubmit="return false"><div class="panel panel-default"><div class="panel-heading"><h2 class="panel-title">
        ${floating ? 'Rules' : 'Rules (Drag to Change Order)'}</h2></div><div id="mainarea" class="table-responsive panel-body"><table id="ruletable" class="table table-hover
        table-striped table-condensed"><thead><tr>${head.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div></div>${list.length ? '' : empty}
        <nav class="action-buttons"><a role="button" class="btn btn-sm btn-success add" title="Add rule to the top of the list" data-at="top"><i class="fa-solid fa-turn-up icon-embed-btn">
        </i>Add</a> <a role="button" class="btn btn-sm btn-success add" title="Add rule to the end of the list"><i class="fa-solid fa-turn-down icon-embed-btn"></i>Add</a>
        <button type="button" class="btn btn-danger btn-sm dels" title="Delete selected rules"${list.length ? '' : ' disabled'}><i class="fa-solid fa-trash-can icon-embed-btn"></i>Delete</button>
        <button type="button" class="btn btn-primary btn-sm" title="Toggle selected rules" disabled><i class="fa-solid fa-ban icon-embed-btn"></i>Toggle</button>
        ${floating ? '' : '<button type="button" class="btn btn-primary btn-sm" title="Copy selected rules" disabled><i class="fa-regular fa-clone icon-embed-btn"></i>Copy</button>'}
        <button type="button" class="btn btn-sm btn-primary order" title="Save rule order" disabled><i class="fa-solid fa-save icon-embed-btn"></i>Save</button>
        <button type="button" class="btn btn-sm btn-warning" title="Add separator" disabled><i class="fa-solid fa-plus icon-embed-btn"></i>Separator</button></nav></form>
        <div class="infoblock"><div class="alert alert-info clearfix" role="alert"><div class="pull-left"><dl class="dl-horizontal responsive"><dt>Legend</dt><dd></dd>
        <dt>${fa('check', 'text-success')}</dt><dd>Pass</dd><dt>${fa('filter')}</dt><dd>Match</dd><dt>${fa('times', 'text-danger')}</dt><dd>Block</dd>
        <dt><i class="fa-regular fa-hand text-warning"></i></dt><dd>Reject</dd><dt>${fa('tasks')}</dt><dd> Log</dd><dt>${fa('cog')}</dt><dd> Advanced filter</dd></dl>
        ${floating ? 'Floating rules are evaluated on a first-match basis (i.e. the action of the first rule to match a packet will be executed) only if the \'quick\' option is checked on a rule.'
          : 'Rules are evaluated on a first-match basis (i.e. the action of the first rule to match a packet will be executed).<br>This means that if block rules are used, it is ' +
            'important to pay attention to the rule order. Everything that isn\'t explicitly passed is blocked by default.'}</div></div></div>`,
      wire(main) {
        wireTabs(main);
        const checks = () => [...main.querySelectorAll('[data-c]:checked')].map(c => Number(c.dataset.c));
        main.querySelector('#selectAll').onchange = e => { main.querySelectorAll('[data-c]').forEach(c => { c.checked = e.target.checked; }); };
        main.querySelectorAll('.add').forEach(b => { b.onclick = () => go('rule-edit', {tab, edit: {index: null, at: b.dataset.at, iface: floating ? '' : tab}}); });
        main.querySelectorAll('[data-e]').forEach(b => { b.onclick = () => go('rule-edit', {tab, edit: {index: Number(b.dataset.e)}}); });
        main.querySelectorAll('[data-k]').forEach(b => { b.onclick = () => go('rule-edit', {tab, edit: {index: null, copy: Number(b.dataset.k)}}); });
        main.querySelectorAll('[data-x]').forEach(b => { b.onclick = () => { editFw().rules.splice(Number(b.dataset.x), 1); render(); }; });
        main.querySelectorAll('[data-m]').forEach(b => { b.onclick = () => {
          const moving = checks(), to = Number(b.dataset.m), all = editFw().rules;
          if (!moving.length || moving.includes(to)) return;
          const picked = moving.map(i => all[i]), rest = all.filter((_, i) => !moving.includes(i));
          rest.splice(rest.indexOf(all[to]), 0, ...picked);
          editFw().rules = rest;
          render();
        }; });
        main.querySelector('.dels').onclick = () => { const out = checks().sort((a, b) => b - a); out.forEach(i => editFw().rules.splice(i, 1)); if (out.length) render(); };
      }};
  }
  function addressRows(prefix, label, value, types) {
    const w = where(prefix, value);
    return group(label, `<div class="col-sm-2"><label class="chkboxlbl"><input type="checkbox" disabled> Invert match</label></div><div class="col-sm-4">
      ${sel(prefix + 'Type', types, w.kind)}</div><div class="col-sm-4"><div class="input-group">${inp(prefix, w.ip, 'placeholder="Source Address"'.replace('Source', label))}
      <span class="input-group-addon input-group-inbetween pfIpMask">/</span><select class="form-control pfIpMask" id="${prefix}Len">${options(masks(), w.len)}</select></div></div>`);
  }
  function pfEditRule() {
    const e = V().edit || {index: null}, f = candidateFw(), base = e.index !== null ? f.rules[e.index] : e.copy !== undefined ? {...f.rules[e.copy], name: f.rules[e.copy].name + '-copy'}
      : {action: 'accept', in: e.iface};
    const types = [['any', 'Any'], ['single', 'Single host or alias'], ['network', 'Network']];
    const port = base.dport ? String(base.dport) : '', known = PORTS.some(([v]) => v === port);
    const portRow = group('Destination Port Range', `<div class="col-sm-2">${sel('pfPortSel', PORTS, known && port ? port : '')}<span class="help-block">From</span></div>
      <div class="col-sm-2">${inp('pfPort', known ? '' : port)}<span class="help-block">Custom</span></div><div class="col-sm-2">${sel('pfPortTo', PORTS, known && port ? port : '', 'disabled')}
      <span class="help-block">To</span></div><div class="col-sm-2">${inp('pfPortToC', '', 'disabled')}<span class="help-block">Custom</span></div>`);
    return {crumbs: ['Firewall', 'Rules', 'Edit'],
      html: pfForm([['Edit Firewall Rule', [
        group('Action', sel('pfAct', [['accept', 'Pass'], ['drop', 'Block'], ['reject', 'Reject', true]], base.action),
          'Choose what to do with packets that match the criteria specified below.<br>Hint: the difference between block and reject is that with reject, a packet (TCP RST or ICMP port ' +
          'unreachable for UDP) is returned to the sender, whereas with block the packet is dropped silently. In either case, the original packet is discarded.', true),
        group('Disabled', chk('pfOff', false, 'Disable this rule', 'disabled'), 'Set this option to disable this rule without removing it from the list.'),
        group('Interface', sel('pfIn', [['', '(Floating)'], ...ports().map(p => [p, ifName(p)])], base.in || ''),
          'Choose the interface from which packets must come to match this rule.', true),
        group('Address Family', sel('pfAf', [['inet', 'IPv4'], ['inet6', 'IPv6', true], ['inet46', 'IPv4+IPv6', true]], 'inet'), 'Select the Internet Protocol version this rule applies to.', true),
        group('Protocol', sel('pfProto', PROTOS, base.protocol || 'any'), 'Choose which IP protocol this rule should match.', true)]],
      ['Source', [addressRows('pfSrc', 'Source', base.source, types)]],
      ['Destination', [addressRows('pfDst', 'Destination', base.destination, types), portRow]],
      ['Extra Options', [group('Log', chk('pfLog', false, 'Log packets that are handled by this rule', 'disabled'), 'Hint: the firewall has limited local log space. Don\'t turn on ' +
        'logging for everything. If doing a lot of logging, consider using a remote syslog server (see the Status: System Logs: Settings page).'),
        group('Description', inp('pfName', base.name || ''), 'A description may be entered here for administrative reference. A maximum of 52 characters will be used in the ruleset and ' +
          'displayed in the firewall log.'),
        group('Advanced Options', '<button class="btn btn-info btn-sm nl-adv" type="button"><i class="fa-solid fa-cog icon-embed-btn"></i>Display Advanced</button>')]],
      ['Advanced Options', [group('Gateway / egress', sel('pfOut', [['', 'Default'], ...ports().map(p => [p, ifName(p)])], base.out || ''),
        'Network LABS: the interface the matched packets leave by (optional).')], 'nl-advanced']]),
      wire(main) {
        const adv = main.querySelector('#nl-advanced');
        if (!base.out) adv.classList.add('hidden');
        main.querySelector('.nl-adv').onclick = () => adv.classList.toggle('hidden');
        const sync = () => {
          const p = val(main, '#pfProto'), ported = p === 'tcp' || p === 'udp';
          main.querySelector('#pfPort').closest('.form-group').classList.toggle('hidden', !ported);
          ['pfSrc', 'pfDst'].forEach(x => { const kind = val(main, `#${x}Type`); main.querySelector('#' + x).disabled = kind === 'any';
            main.querySelector(`#${x}Len`).disabled = kind !== 'network'; });
        };
        main.querySelectorAll('select').forEach(s => s.addEventListener('change', sync));
        sync();
        submit(main, form => {
          const rule = readRule(form, e.index === null ? {} : base);
          if (e.index === null && e.at === 'top') editFw().rules.unshift(rule); else putRule(e.index, rule);
          Object.assign(V(), {page: 'rules', tab: rule.in || 'floating', edit: null});
        });
      }};
  }

  function pfNat() {
    const tab = ['Outbound', 'Port Forward'].includes(V().tab) ? V().tab : 'Port Forward';
    const tabs = [['Port Forward', 'Port Forward'], ['1:1', '1:1'], ['Outbound', 'Outbound'], ['NPt', 'NPt']];
    const acts = i => `<td class="text-nowrap"><a class="fa-solid fa-pencil" title="Edit" data-e="${i}"></a><a class="fa-regular fa-clone" title="Copy" data-k="${i}"></a>
      <a class="fa-solid fa-trash-can" title="Delete" data-x="${i}"></a></td>`;
    const buttons = `<nav class="action-buttons"><a role="button" class="btn btn-sm btn-success add" title="Add rule to the top of the list"><i class="fa-solid fa-turn-up icon-embed-btn"></i>Add</a>
      <a role="button" class="btn btn-sm btn-success add" title="Add rule to the end of the list"><i class="fa-solid fa-turn-down icon-embed-btn"></i>Add</a>
      <button type="button" class="btn btn-danger btn-sm" disabled><i class="fa-solid fa-trash-can icon-embed-btn"></i>Delete</button>
      <button type="button" class="btn btn-primary btn-sm" disabled><i class="fa-solid fa-save icon-embed-btn"></i>Save</button>
      <button type="button" class="btn btn-sm btn-warning" disabled><i class="fa-solid fa-plus icon-embed-btn"></i>Separator</button></nav>`;
    const table = (head, rows, empty) => `<table class="table table-striped table-hover table-condensed"><thead><tr>${head.map(c => `<th>${c}</th>`).join('')}</tr></thead>
      <tbody>${rows.join('') || `<tr><td colspan="${head.length}">${empty}</td></tr>`}</tbody></table>`;
    let html;
    if (tab === 'Outbound') {
      const mode = outbound().length ? 'hybrid' : 'automatic';
      const radio = (value, title, text) => `<div class="col-sm-2"><label class="chkboxlbl"><input type="radio" name="mode" value="${value}"${value === mode ? ' checked' : ' disabled'}>
        ${title}</label><span class="help-block">${text}</span></div>`;
      html = `<form onsubmit="return false">${panel('Outbound NAT Mode', group('Mode', radio('automatic', 'Automatic outbound NAT rule generation.', '(IPsec passthrough included)') +
        radio('hybrid', 'Hybrid Outbound NAT rule generation.', '(Automatic Outbound NAT + rules below)') + radio('advanced', 'Manual Outbound NAT rule generation.',
          '(AON - Advanced Outbound NAT)') + radio('disabled', 'Disable Outbound NAT rule generation.', '(No Outbound NAT rules)')))}
        ${panel('Mappings', table(['', 'Interface', 'Source', 'Source Port', 'Destination', 'Destination Port', 'NAT Address', 'NAT Port', 'Static Port', 'Description', 'Actions'],
          outbound().map(([r, i]) => `<tr><td>${fa('check', 'text-success')}</td><td>${h(ifName(r.out || ports()[0]))}</td><td>${h(r.source || 'any')}</td><td>*</td>
            <td>${h(r.destination || '*')}</td><td>${h(r.dport || '*')}</td><td>${h(r.type === 'masquerade' ? ifName(r.out) + ' address' : r.to)}</td><td>*</td>
            <td>${fa('shuffle', '', 'Randomize source port')}</td><td>${h(r.name)}</td>${acts(i)}</tr>`), 'No outbound mappings defined.'))}${buttons}</form>
        ${panel('Automatic Rules:', table(['', 'Interface', 'Source', 'Source Port', 'Destination', 'Destination Port', 'NAT Address', 'NAT Port', 'Static Port', 'Description'],
          mode === 'disabled' ? [] : ports().slice(1).filter(p => addressOf(p)).map(p => `<tr><td>${fa('check', 'text-success')}</td><td>${h(ifName(ports()[0]))}</td>
            <td>${h(networkOf(addressOf(p)))}</td><td>*</td><td>*</td><td>*</td><td>${h(ifName(ports()[0]))} address</td><td>*</td><td>${fa('shuffle')}</td>
            <td>Auto created rule - ${h(ifName(p))} to ${h(ifName(ports()[0]))}</td></tr>`), 'None'))}`;
    } else {
      html = `<form onsubmit="return false">${panel('Rules', table(['', '', 'Interface', 'Protocol', 'Source Address', 'Source Ports', 'Dest. Address', 'Dest. Ports', 'NAT IP',
        'NAT Ports', 'Description', 'Actions'], forwards().map(([r, i]) => `<tr><td><input type="checkbox"></td><td>${fa('check', 'text-success', 'Rule associated')}</td>
          <td>${h(ifName(r.in || ports()[0]))}</td><td>${h((r.protocol || 'any').toUpperCase())}</td><td>${h(r.source || '*')}</td><td>*</td><td>${h(r.destination || '*')}</td>
          <td>${h(r.dport || '*')}</td><td>${h(r.to || '')}</td><td>${h(r.to_port || r.dport || '*')}</td><td>${h(r.name)}</td>${acts(i)}</tr>`), 'No port forward rules defined.'))}
        ${buttons}</form>`;
    }
    return {crumbs: ['Firewall', 'NAT', tab], html: pfTabs(tabs, tab) + html,
      wire(main) {
        wireTabs(main);
        main.querySelectorAll('.add').forEach(b => { b.onclick = () => go('nat-edit', {tab, edit: {index: null, type: tab === 'Outbound' ? 'masquerade' : 'dnat'}}); });
        main.querySelectorAll('[data-e]').forEach(b => { b.onclick = () => go('nat-edit', {tab, edit: {index: Number(b.dataset.e)}}); });
        main.querySelectorAll('[data-k]').forEach(b => { b.onclick = () => go('nat-edit', {tab, edit: {index: null, copy: Number(b.dataset.k)}}); });
        main.querySelectorAll('[data-x]').forEach(b => { b.onclick = () => dropEntry('nat', Number(b.dataset.x), true).then(render); });
      }};
  }
  function natSource(e) {
    const nat = candidateFw().nat || [];
    if (e.index !== null) return nat[e.index];
    if (e.copy !== undefined) return {...nat[e.copy], name: nat[e.copy].name + '-copy'};
    return {type: e.type, in: ports()[0], out: ports()[0]};
  }
  function pfEditNat() {
    const e = V().edit || {index: null, type: 'dnat'}, r = natSource(e), forward = r.type === 'dnat';
    const port = r.dport ? String(r.dport) : '', known = PORTS.some(([v]) => v === port);
    const ifs = ports().map(p => [p, ifName(p)]);
    const dst = where('nxDst', r.destination);
    const portRows = (selId, inId, label, value, help) => group(label, `<div class="col-sm-3">${sel(selId, PORTS, known && value ? value : '')}<span class="help-block">From port</span></div>
      <div class="col-sm-3">${inp(inId, known ? '' : value)}<span class="help-block">Custom</span></div><div class="col-sm-4"><span class="help-block">${help}</span></div>`);
    const fwd = [group('Interface', sel('nxIn', ifs, r.in || ports()[0]), 'Choose which interface this rule applies to. In most cases "WAN" is specified.', true),
      group('Address Family', sel('nxAf', [['inet', 'IPv4']], 'inet'), 'Select the Internet Protocol version this rule applies to.', true),
      group('Protocol', sel('nxProto', PROTOS.filter(([v]) => v !== 'any'), r.protocol || 'tcp'), 'Choose which protocol this rule should match. In most cases "TCP" is specified.', true),
      group('Destination', `<div class="col-sm-2"><label class="chkboxlbl"><input type="checkbox" disabled> Invert match.</label></div><div class="col-sm-4">${sel('nxDstType',
        [['wanaddr', `${ifName(r.in || ports()[0])} address`], ['single', 'Single host'], ['network', 'Network']], dst.kind === 'any' || !r.destination ? 'wanaddr' : dst.kind)}</div>
        <div class="col-sm-4"><div class="input-group">${inp('nxDst', dst.ip, 'placeholder="Address/mask"')}<span class="input-group-addon input-group-inbetween pfIpMask">/</span>
        <select class="form-control pfIpMask" id="nxDstLen">${options(masks(), dst.len)}</select></div></div>`),
      portRows('nxPortSel', 'nxPort', 'Destination port range', port, 'Specify the port or port range for the destination of the packet for this mapping.'),
      group('Redirect target IP', `<div class="col-sm-4">${sel('nxToType', [['single', 'Address or Alias']], 'single')}</div><div class="col-sm-6">${inp('nxTo', r.to || '',
        'placeholder="Address"')}<span class="help-block">Enter the internal IP address of the server on which to map the ports. e.g.: 192.168.1.12 for IPv4</span></div>`),
      group('Redirect target port', `<div class="col-sm-3">${inp('nxToPort', r.to_port || '')}<span class="help-block">Port</span></div><div class="col-sm-7"><span class="help-block">
        Specify the port on the machine with the IP address entered above. In case of a port range, specify the beginning port of the range (the end port will be calculated
        automatically).</span></div>`),
      group('Description', inp('nxName', r.name || ''), 'A description may be entered here for administrative reference (not parsed).'),
      group('Filter rule association', sel('nxAssoc', [['', 'Add associated filter rule']], ''), 'The "pass" selection does not work properly with Multi-WAN.')];
    const src = where('nxSrc', r.source), out = [group('Interface', sel('nxOut', ifs, r.out || ports()[0]), 'The interface on which traffic is matched as it exits the firewall.', true),
      group('Address Family', sel('nxAf', [['inet', 'IPv4']], 'inet'), 'Select the Internet Protocol version this rule applies to.', true),
      group('Protocol', sel('nxProto', PROTOS, r.protocol || 'any'), 'Choose which protocol this rule should match. In most cases "any" is specified.', true),
      group('Source', `<div class="col-sm-4">${sel('nxSrcType', [['any', 'Any'], ['network', 'Network']], src.kind === 'any' ? 'any' : 'network')}</div><div class="col-sm-4">
        <div class="input-group">${inp('nxSrc', src.ip, 'placeholder="Source Address"')}<span class="input-group-addon input-group-inbetween pfIpMask">/</span>
        <select class="form-control pfIpMask" id="nxSrcLen">${options(masks(), src.len)}</select></div></div>`),
      group('Destination', `<div class="col-sm-4">${sel('nxDstType', [['any', 'Any'], ['network', 'Network']], dst.kind === 'any' ? 'any' : 'network')}</div><div class="col-sm-4">
        <div class="input-group">${inp('nxDst', dst.ip, 'placeholder="Destination Address"')}<span class="input-group-addon input-group-inbetween pfIpMask">/</span>
        <select class="form-control pfIpMask" id="nxDstLen">${options(masks(), dst.len)}</select></div></div>`)];
    const translation = [group('Address', sel('nxType', [['masquerade', 'Interface Address'], ['snat', 'Interface Address (static)']], r.type || 'masquerade'),
      'Connections matching this rule will be mapped to the specified address.'), group('Port or Range', inp('nxXPort', '', 'disabled'), 'Enter the external source Port or Range used for remapping.')];
    const sections = forward ? [['Edit Redirect Entry', fwd]] : [['Edit Advanced Outbound NAT Entry', out], ['Translation', translation],
      ['Misc', [group('Description', inp('nxName', r.name || ''), 'A description may be entered here for administrative reference (not parsed).')]]];
    return {crumbs: ['Firewall', 'NAT', forward ? 'Port Forward' : 'Outbound', 'Edit'], html: pfForm(sections),
      wire(main) {
        const sync = () => ['nxSrc', 'nxDst'].forEach(x => { const t = main.querySelector(`#${x}Type`); if (!t) return;
          main.querySelector('#' + x).disabled = ['any', 'wanaddr'].includes(t.value); main.querySelector(`#${x}Len`).disabled = t.value !== 'network'; });
        main.querySelectorAll('select').forEach(s => s.addEventListener('change', sync));
        sync();
        submit(main, form => {
          const entry = readNat(form, forward ? 'dnat' : val(form, '#nxType'));
          const f = editFw();
          if (e.index === null) f.nat.push(entry); else f.nat[e.index] = entry;
          Object.assign(V(), {page: 'nat', tab: forward ? 'Port Forward' : 'Outbound', edit: null});
        });
      }};
  }

  function pfAssign() {
    const tabs = ['Interface Assignments', 'Interface Groups', 'Wireless', 'VLANs', 'QinQs', 'PPPs', 'GREs', 'GIFs', 'Bridges', 'LAGGs'].map(t => [t, t]);
    return {crumbs: ['Interfaces', 'Interface Assignments'], html: `${pfTabs(tabs, 'Interface Assignments')}<form class="form-horizontal" onsubmit="return false">
      ${panel('Interface Assignments', `<div class="table-responsive"><table class="table table-striped table-hover"><thead><tr><th>Interface</th><th>Network port</th><th></th></tr></thead>
      <tbody>${D().ports.map(p => `<tr><td><a data-go="if:${h(p.port)}">${h(ifName(p.port))}</a></td><td><select class="form-control">${options([[p.port, `${portName(p.port)}${
        p.peer ? ' (' + p.peer + ')' : ''}`]], p.port)}</select></td><td>${ports().indexOf(p.port) > 0 ? `<button type="button" class="btn btn-danger btn-sm" disabled>
        <i class="fa-solid fa-trash-can icon-embed-btn"></i>Delete</button>` : ''}</td></tr>`).join('')}<tr><th>Available network ports:</th><td><select class="form-control" disabled>
        <option>(none)</option></select></td><td><button type="button" class="btn btn-success btn-sm" disabled><i class="fa-solid fa-plus icon-embed-btn"></i>Add</button></td></tr>
      </tbody></table></div>`)}<button type="button" class="btn btn-primary" disabled><i class="fa-solid fa-save icon-embed-btn"></i>Save</button></form><br>
      <div class="infoblock"><div class="alert alert-info clearfix" role="alert"><div class="pull-left">Interfaces that are configured as members of a lagg(4) interface will
      not be shown.<br><br>Wireless interfaces must be created on the Wireless tab before they can be assigned.</div></div></div>`,
      wire(main) { wireTabs(main, {page: 'assign'}); main.querySelectorAll('.nav-pills [data-t]').forEach(a => { if (a.dataset.t !== 'Interface Assignments') a.onclick = () => go('na',
        {title: 'Interfaces/' + a.dataset.t}); }); }};
  }
  function pfInterface(port) {
    const a = addressOf(port), name = ifName(port), first = ports().indexOf(port) === 0;
    const types = [['none', 'None'], ['staticv4', 'Static IPv4'], ['dhcp', 'DHCP', true], ['ppp', 'PPP', true], ['pppoe', 'PPPoE', true], ['pptp', 'PPTP', true], ['l2tp', 'L2TP', true]];
    return {crumbs: ['Interfaces', `${name} (${portName(port)})`], html: pfForm([['General Configuration', [
      group('Enable', chk('pfEnable', true, 'Enable interface', 'disabled')), group('Description', inp('pfDescr', name, 'disabled'),
        'Enter a description (name) for the interface here.'),
      group('IPv4 Configuration Type', sel('pfType', types, a ? 'staticv4' : 'none')), group('IPv6 Configuration Type', sel('pfType6', [['none', 'None']], 'none')),
      group('MAC Address', inp('pfMac', '', 'placeholder="xx:xx:xx:xx:xx:xx" disabled'), 'This field can be used to modify ("spoof") the MAC address of this interface.'),
      group('MTU', inp('pfMtu', '', 'disabled'), 'If this field is blank, the adapter\'s default MTU will be used. This is typically 1500 bytes but can vary in some circumstances.'),
      group('MSS', inp('pfMss', '', 'disabled'), 'If a value is entered in this field, then MSS clamping for TCP connections to the value entered above minus 40 for IPv4 will be in effect.'),
      group('Speed and Duplex', sel('pfMedia', [['', 'Default (no preference, typically autoselect)']], ''), 'Explicitly set speed and duplex mode for this interface.')]],
    ['Static IPv4 Configuration', [group('IPv4 Address', ipMask('pfIp', ipOf(a), 'pfLen', lenOf(a) || 24), '', true),
      group('IPv4 Upstream gateway', `<div class="col-sm-4">${sel('pfGwSel', [['none', 'None'], ...(first ? gateways().map(g => [g.name, `${g.name} - ${g.ip}`]) : [])],
        first && gateways().length ? gateways()[0].name : 'none', 'disabled')}<span class="help-block">If this interface is an Internet connection, select an existing Gateway from the list
        or add a new one using the "Add" button. On local area network interfaces the upstream gateway should be "none".</span></div><div class="col-sm-2"><button type="button"
        class="btn btn-success btn-sm" disabled><i class="fa-solid fa-plus icon-embed-btn"></i>Add a new gateway</button></div>`)], 'nl-static'],
    ['Reserved Networks', [group('Block private networks and loopback addresses', chk('pfPriv', false, '', 'disabled'), 'Blocks traffic from IP addresses that are reserved for ' +
      'private networks per RFC 1918 (10/8, 172.16/12, 192.168/16) and unique local addresses per RFC 4193 (fc00::/7) as well as loopback addresses (127/8).'),
      group('Block bogon networks', chk('pfBogon', false, '', 'disabled'), 'Blocks traffic from reserved IP addresses (but not RFC 1918) or not yet assigned by IANA.')]]]),
    wire(main) {
      const sync = () => main.querySelector('#nl-static').classList.toggle('hidden', val(main, '#pfType') !== 'staticv4');
      main.querySelector('#pfType').onchange = sync;
      sync();
      submit(main, form => readIface(form, port));
    }};
  }
  function pfRouting() {
    const tab = V().tab === 'Static Routes' ? 'Static Routes' : V().tab === 'Gateway Groups' ? 'Gateway Groups' : 'Gateways';
    const tabs = [['Gateways', 'Gateways'], ['Static Routes', 'Static Routes'], ['Gateway Groups', 'Gateway Groups']];
    const rowsOf = (head, rows, empty) => `<div class="table-responsive"><table class="table table-striped table-hover table-condensed table-rowdblclickedit"><thead><tr>${
      head.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody>${rows.join('') || `<tr><td colspan="${head.length}">${empty}</td></tr>`}</tbody></table></div>`;
    let html;
    if (tab === 'Gateways') {
      html = panel('Gateways', rowsOf(['', 'Name', 'Default', 'Interface', 'Gateway', 'Monitor IP', 'Description', 'Actions'], gateways().map(g => `<tr><td>${fa('check', 'text-success')}</td>
        <td>${h(g.name)}</td><td>${fa('globe', '', 'Default gateway')} Default (IPv4)</td><td>${h(ifName(g.port))}</td><td>${h(g.ip)}</td><td>${h(g.ip)}</td>
        <td>Interface ${h(ifName(g.port))} Gateway</td><td><a class="fa-solid fa-pencil" title="Edit gateway"></a></td></tr>`), 'No gateways defined.')) +
        `<nav class="action-buttons"><a role="button" class="btn btn-success btn-sm" disabled><i class="fa-solid fa-plus icon-embed-btn"></i>Add</a></nav>` +
        panel('Default gateway', group('Default gateway IPv4', sel('pfDef', [['', 'Automatic'], ...gateways().map(g => [g.name, g.name])], gateways()[0]?.name || '', 'disabled'),
          'Select a gateway or failover gateway group to use as the default gateway.'), ' style="margin-top:20px"');
    } else if (tab === 'Static Routes') {
      html = panel('Static Routes', rowsOf(['', 'Network', 'Gateway', 'Interface', 'Description', 'Actions'], staticRoutes().map((r, i) => `<tr><td>${fa('check', 'text-success')}</td>
        <td>${h(r.network)}</td><td>${h(r.gateway)}</td><td>${h(r.port ? ifName(r.port) : '')}</td><td></td><td class="text-nowrap"><a class="fa-solid fa-pencil" title="Edit route"
        data-e="${i}"></a><a class="fa-solid fa-trash-can" title="Delete route" data-x="${i}"></a></td></tr>`), 'No routes defined.')) +
        `<nav class="action-buttons"><a role="button" class="btn btn-success btn-sm add"><i class="fa-solid fa-plus icon-embed-btn"></i>Add</a></nav>`;
    } else html = later(NA.later);
    return {crumbs: ['System', 'Routing', tab], html: pfTabs(tabs, tab) + html,
      wire(main) {
        wireTabs(main);
        main.querySelector('.add')?.addEventListener('click', () => go('route-edit', {tab: 'Static Routes', edit: {index: null}}));
        main.querySelectorAll('[data-e]').forEach(b => { b.onclick = () => go('route-edit', {tab: 'Static Routes', edit: {index: Number(b.dataset.e)}}); });
        main.querySelectorAll('[data-x]').forEach(b => { b.onclick = () => { dropRoute(Number(b.dataset.x)); render(); }; });
      }};
  }
  function pfEditRoute() {
    const e = V().edit || {index: null}, r = e.index !== null ? staticRoutes()[e.index] : {network: '', gateway: ''};
    const known = gateways().map(g => [g.ip, `${g.name} - ${g.ip}`]), gwSel = known.some(([ip]) => ip === r.gateway) ? r.gateway : '';
    return {crumbs: ['System', 'Routing', 'Static Routes', 'Edit'], html: pfForm([['Edit Route Entry', [
      group('Destination network', ipMask('pfNet', r.network ? ipOf(r.network) : '', 'pfNetLen', r.network ? lenOf(r.network) : 24, 1, 'Destination network'), '', true),
      group('Gateway', `<div class="col-sm-4">${sel('pfGwSel', [['', '(enter an address)'], ...known], gwSel)}<span class="help-block">Choose which gateway this route applies to,
        e.g. the WAN gateway.</span></div><div class="col-sm-4">${inp('pfGw', gwSel ? '' : r.gateway, 'placeholder="a.b.c.d"')}<span class="help-block">Network LABS: or the next
        hop's address, on the network of one of the interfaces.</span></div>`, '', true),
      group('Disabled', chk('pfRouteOff', false, 'Disable this static route', 'disabled'), 'Set this option to disable this static route without removing it from the list.'),
      group('Description', inp('pfRouteDescr', ''), 'A description may be entered here for administrative reference (not parsed).')]]]),
    wire(main) {
      submit(main, form => {
        saveRoute(form, e.index);
        Object.assign(V(), {page: 'routing', tab: 'Static Routes', edit: null});
      });
    }};
  }
  function pfDhcp() {
    const lan = D().ports.filter(p => addressOf(p.port) && p.port !== ports()[0]), s = dhcpNow();
    const tab = lan.some(p => p.port === V().tab) ? V().tab : (s && lan.some(p => p.port === s.interface) ? s.interface : lan[0]?.port);
    if (!tab) return {crumbs: ['Services', 'DHCP Server'], html: later('The DHCP Server can only be enabled on interfaces configured with a static IPv4 address.')};
    const on = Boolean(s && s.interface === tab), a = addressOf(tab), net = networkOf(a);
    return {crumbs: ['Services', 'DHCP Server', ifName(tab)], html: pfTabs(lan.map(p => [p.port, ifName(p.port)]), tab) + pfForm([
      ['General DHCP Options', [group('DHCP Backend', 'ISC DHCP'), group('Enable', chk('pfOn', on, `Enable DHCP server on ${ifName(tab)} interface`)),
        group('BOOTP', chk('pfBootp', false, 'Ignore BOOTP queries', 'disabled')), group('Deny Unknown Clients', sel('pfDeny', [['', 'Allow all clients']], '', 'disabled'),
          'When set to Allow all clients, any DHCP client will get an IP address within this scope/range on this interface.')]],
      ['Primary Address Pool', [group('Subnet', h(net)), group('Subnet Range', h(rangeOf(a))),
        group('Address Pool Range', `<div class="col-sm-4">${inp('pfFrom', on ? s.start : '')}<span class="help-block">From</span></div><div class="col-sm-4">${inp('pfTo', on ? s.end : '')}
          <span class="help-block">To</span></div>`, '', true)]],
      ['Server Options', [group('DNS Servers', inp('pfDns', on ? (s.dns || []).join(', ') : '', 'placeholder="DNS Server 1"'), 'Leave blank to use the IP address of this firewall ' +
        'interface if DNS Resolver or Forwarder is enabled, the servers configured in General settings or those obtained dynamically.')]],
      ['Other DHCP Options', [group('Gateway', inp('pfGw', on ? s.router || '' : '', `placeholder="${h(ipOf(a))}"`), 'The default is to use the IP address of this firewall interface as ' +
        'the gateway. Specify an alternate gateway here if this is not the correct gateway for the network.'),
        group('Default Lease Time', inp('pfLease', on ? s.lease_seconds : '', 'placeholder="7200"'), 'This is used for clients that do not ask for a specific expiration time. ' +
          'The default is 7200 seconds.')]]]),
    wire(main) {
      wireTabs(main);
      submit(main, form => readDhcp(form, tab));
    }};
  }
  const rangeOf = cidr => {
    if (!cidr) return '';
    const len = lenOf(cidr), base = networkOf(cidr).split('/')[0].split('.').map(Number), n = base.reduce((x, o) => x * 256 + o, 0), size = 2 ** (32 - len);
    const ip = v => [24, 16, 8, 0].map(s => (v >>> s) & 255).join('.');
    return size > 2 ? `${ip(n + 1)} - ${ip(n + size - 2)}` : ip(n);
  };
  function pfGeneral() {
    return {crumbs: ['System', 'General Setup'], html: pfForm([['System', [group('Hostname', inp('pfHost', (V().stage && V().stage.name) || N().name),
      'Name of the firewall host, without domain part.<br>e.g.: <em>firewall</em>'), group('Domain', inp('pfDomain', 'home.arpa', 'disabled'), 'The domain, e.g. <em>mycorp.com, home, office, ' +
      'private, etc.</em><br>Do not use \'local\' as a domain name. It will cause local hosts running mDNS (avahi, bonjour, etc.) to be unable to resolve local hosts not running mDNS.')]],
    ['DNS Server Settings', [group('DNS Server 1', inp('pfDns1', '', 'placeholder="Address" disabled'), 'Address. Enter IP addresses to be used by the system for DNS resolution.'),
      group('DNS Server Override', chk('pfOverride', true, 'Allow DNS server list to be overridden by DHCP/PPP on WAN or remote OpenVPN server', 'disabled'))]],
    ['Localization', [group('Timezone', sel('pfTz', [['Etc/UTC', 'Etc/UTC']], 'Etc/UTC', 'disabled'), 'Select a geographic region name (Continent/Location) to determine the timezone for the firewall.'),
      group('Language', sel('pfLang', [['en_US', 'English']], 'en_US', 'disabled'), 'Choose a language for the webConfigurator')]],
    ['webConfigurator', [group('Theme', sel('pfTheme', [['pfSense.css', 'pfSense']], 'pfSense.css', 'disabled'), 'Choose an alternative css file (if installed) to change the appearance ' +
      'of the webConfigurator.'), group('Top Navigation', sel('pfTop', [['', 'Scrolls with page']], '', 'disabled'), 'The fixed option is intended for large screens only.')]]]),
    wire(main) { submit(main, readHost); }};
  }
  function pfStatusIf() {
    return {crumbs: ['Status', 'Interfaces'], html: D().ports.map(p => {
      const a = addressOf(p.port), first = ports().indexOf(p.port) === 0;
      const rows = [['Status', up(p) ? 'up' : 'no carrier'], ['IPv4 Address', ipOf(a) || 'n/a'], ['Subnet mask IPv4', a ? maskOf(lenOf(a)) : 'n/a'],
        ...(first && N().gateway ? [['Gateway IPv4', `${ifName(p.port)}_GW ${N().gateway}`]] : []), ['MTU', '1500'], ['Media', up(p) ? '1000baseT <full-duplex>' : 'none'],
        ['In/out packets', '0/0 (0 B/0 B)'], ['In/out errors', '0/0'], ['Collisions', '0'], ['Cabled to', p.peer || '—']];
      return panel(`${h(ifName(p.port))} Interface (${h(ifName(p.port).toLowerCase())}, ${h(portName(p.port))})`, `<dl class="dl-horizontal">${rows.map(([k, v]) =>
        `<dt>${h(k)}</dt><dd>${h(v)}</dd>`).join('')}</dl>`); }).join('') +
      `<div class="infoblock"><div class="alert alert-info clearfix" role="alert"><div class="pull-left">Using dial-on-demand will bring the connection up again if any packet
      triggers it. To substantiate this point: disconnecting manually will <strong>not</strong> prevent dial-on-demand from making connections to the outside. Don't use
      dial-on-demand if the line is to be kept disconnected.</div></div></div>`};
  }
  function pfStatusGw() {
    const on = running();
    return {crumbs: ['Status', 'Gateways'], html: pfTabs([['Gateways', 'Gateways'], ['Gateway Groups', 'Gateway Groups']], 'Gateways') + panel('Gateways', `<div class="table-responsive">
      <table class="table table-striped table-hover table-condensed"><thead><tr><th>Name</th><th>Gateway</th><th>Monitor</th><th>RTT</th><th>RTTsd</th><th>Loss</th><th>Status</th>
      <th>Description</th></tr></thead><tbody>${gateways().map(g => `<tr><td>${h(g.name)} ${fa('globe', '', 'Default gateway')}</td><td>${h(g.ip)}</td><td>${h(g.ip)}</td><td>—</td>
      <td>—</td><td>—</td><td class="${on ? 'bg-success' : 'bg-info'}">${on ? 'Online' : 'Unknown'}</td><td>Interface ${h(ifName(g.port))} Gateway</td></tr>`).join('') ||
      '<tr><td colspan="8">No gateways found.</td></tr>'}</tbody></table></div>`)};
  }
  function pfDiagRoutes() {
    const rows = [...D().connected.map(r => [r.network, `link#${ports().indexOf(r.port) + 1}`, 'U', r.port]), ...D().static.map(r => [r.network, r.gateway, 'UGS', r.port])];
    return {crumbs: ['Diagnostics', 'Routes'], html: panel('Routing Table Display Options', group('Resolve names', chk('pfResolve', false, 'Enable', 'disabled'), 'Enabling name resolution ' +
      'may cause the query to take longer.')) + panel('IPv4 Routes', `<table class="table table-striped table-hover table-condensed sortable-theme-bootstrap"><thead><tr><th>Destination</th>
      <th>Gateway</th><th>Flags</th><th>Uses</th><th>Mtu</th><th>Netif</th><th>Expire</th></tr></thead><tbody>${rows.map(([dest, gw, flags, port]) => `<tr><td>${h(dest)}</td><td>${h(gw)}</td>
      <td>${flags}</td><td>0</td><td>1500</td><td>${h(portName(port || ''))}</td><td></td></tr>`).join('')}</tbody></table>`)};
  }
  function pfLogin({hint}) {
    return `<div id="total"><header><div id="headerrow"><div class="row"><div class="col-sm-4"><div id="logodiv" style="text-align:center" class="nowarning"><span class="pf-word">pfSense</span>
      </div></div><div class="col-sm-4 nowarning msgbox text-center text-danger"><h4 class="lg-err"></h4></div><div class="col-sm-4 nowarning msgbox text-center"><span id="hostspan">
      <h4>Login to pfSense</h4></span></div></div></div></header><div style="background: #1e3f75;" class="pagebody"><div class="col-sm-4"></div><div class="col-sm-4 offset-md-4 logoCol">
      <div class="loginCont center-block"><form method="post" autocomplete="off" class="login"><p class="form-title">Sign In</p><input name="usernamefld" id="usernamefld" class="us"
      type="text" placeholder="Username" autocorrect="off" autocapitalize="none"><input name="passwordfld" id="passwordfld" class="pw" type="password" placeholder="Password">
      <input type="submit" name="login" value="Sign In" class="btn btn-success btn-sm go"><small class="lg-hint">${hint}</small></form></div></div><div class="col-sm-4"></div></div>
      <footer id="3"><div id="footertext"><p class="text-muted">${pfCredit()}</p></div></footer></div>`;
  }

  /* =============================== OPNsense =============================== */
  const OPN_MENU = () => {
    const ifs = ports().map(p => [`[${ifName(p)}]`, 'if:' + p]).sort((a, b) => a[0].localeCompare(b[0]));
    return [
      ['Lobby', 'laptop', [['Dashboard', 'dashboard'], ['License'], ['Password'], ['Logout', 'logout']]],
      ['Reporting', 'chart-area', [['Health'], ['Insight'], ['NetFlow'], ['Settings'], ['Traffic'], ['Unbound DNS']]],
      ['System', 'server', [['Access', null, [['Groups'], ['Privileges'], ['Servers'], ['Tester'], ['Users']]], ['Configuration', null, [['Backups'], ['Defaults'], ['History'], ['Wizard']]],
        ['Firmware', null, [['Status'], ['Settings'], ['Changelog'], ['Updates'], ['Plugins'], ['Packages'], ['Reporter'], ['Log File']]],
        ['Gateways', null, [['Configuration', 'gateways'], ['Group'], ['Log File']]], ['High Availability', null, [['Settings'], ['Status']]],
        ['Routes', null, [['Configuration', 'routing'], ['Status', 'diag-routes'], ['Log File']]],
        ['Settings', null, [['Administration'], ['Cron'], ['General', 'general'], ['Logging'], ['Miscellaneous'], ['Tunables']]], ['Snapshots'],
        ['Trust', null, [['Authorities'], ['Certificates'], ['Revocation'], ['Settings']]], ['Log Files', null, [['Audit'], ['Backend'], ['Boot'], ['General'], ['Web GUI']]],
        ['Diagnostics', null, [['Activity'], ['Services']]]]],
      ['Interfaces', 'sitemap', [...ifs, ['Assignments', 'assign'], ['Overview', 'status-if'], ['Settings'], ['Neighbors'], ['Wireless'], ['Point-to-Point'], ['Other Types'],
        ['Virtual IPs', null, [['Settings'], ['Status']]], ['Diagnostics', null, [['ARP Table'], ['DNS Lookup'], ['Netstat'], ['Packet Capture'], ['Ping', 'terminal'], ['Port Probe'],
          ['Trace Route', 'terminal']]]]],
      ['Firewall', 'fire', [['Aliases'], ['Automation'], ['Categories'], ['Groups'], ['NAT', null, [['Port Forward', 'nat:Port Forward'], ['One-to-One'], ['Outbound', 'nat:Outbound'],
        ['NPTv6']]], ['Rules', null, [['Floating', 'rules:floating'], ...ports().map(p => [ifName(p), 'rules:' + p])]], ['Shaper', null, [['Pipes'], ['Queues'], ['Rules']]],
        ['Schedules'], ['Settings', null, [['Advanced'], ['Normalization'], ['Schedules']]], ['Log Files', null, [['Live View'], ['Overview'], ['Plain View']]],
        ['Diagnostics', null, [['Aliases'], ['Sessions'], ['States'], ['Statistics']]]]],
      ['VPN', 'globe', [['IPsec', null, [['Connections', 'vpn'], ['Status Overview', 'vpn']]], ['OpenVPN', null, [['Instances', 'vpn'], ['Status', 'vpn']]],
        ['WireGuard', null, [['Instances', 'vpn'], ['Status', 'vpn']]]]],
      ['Services', 'gear', [['Captive Portal'], ['Dnsmasq DNS & DHCP'], ['ISC DHCPv4', null, [...ports().slice(1).map(p => [`[${ifName(p)}]`, 'dhcp:' + p]), ['Leases'], ['Relay']]],
        ['Intrusion Detection'], ['Monit'], ['Network Time'], ['Unbound DNS']]],
      ['Power', 'plug', [['Reboot'], ['Power Off']]],
      ['Help', 'life-ring', [['Documentation'], ['User Forum'], ['Commercial Support']]]];
  };
  SKINS.opnsense = {
    start: {page: 'dashboard', open: 'Lobby', sel: 'Lobby/Dashboard', title: 'Lobby: Dashboard'},
    sheets: [FA, '/ui/opnsense/main.css'],
    login: {sheets: ['/ui/opnsense/main.css'], error: 'Wrong username or password.', draw: opLogin},
    draw(root) {
      const page = opPage(), v = V();
      const item = (path, label, target, level) => `<a class="list-group-item${v.sel === path ? ' active' : ''}${level === 3 ? ' menu-level-3-item' : ''}${target ? '' : ' nl-na'}"
        data-go="${target || 'na'}" data-path="${h(path)}">${level === 3 ? h(label) : `<div style="display: table;width: 100%;"><div style="display: table-row"><div style="display: table-cell">
        ${h(label)}</div><div style="display: table-cell; text-align:right; vertical-align:middle;"><span></span></div></div></div>`}</a>`;
      const menu = OPN_MENU().map(([top, icon, children]) => {
        const open = v.open === top, chosen = (v.sel || '').startsWith(top + '/');
        return `<a class="list-group-item${chosen ? ' active-menu-title' : ''}" data-g="${h(top)}"><span class="fa-solid fa-${icon} __iconspacer"></span><span style="word-break: keep-all">
          ${h(top)}</span></a><div class="collapse${open ? ' active-menu in' : ''}" id="${h(top)}">${open ? children.map(([label, target, subs]) => {
            const path = `${top}/${label}`;
            if (!subs) return item(path, label, target, 2);
            const deep = (v.open2 || '') === path;
            return `<a class="list-group-item${(v.sel || '').startsWith(path + '/') ? ' active-menu-title' : ''}" data-g="${h(path)}" aria-expanded="${deep}"><div style="display: table;width: 100%;">
              <div style="display: table-row"><div style="display: table-cell">${h(label)}</div><div style="display: table-cell; text-align:right; vertical-align:middle;">
              <span class="fa-solid fa-chevron-${deep ? 'down' : 'right'}" style="font-size:10px"></span></div></div></div></a><div class="collapse${deep ? ' active-menu in' : ''}">${
              deep ? subs.map(([sub, t]) => item(`${path}/${sub}`, sub, t, 3)).join('') : ''}</div>`;
          }).join('') : ''}</div>`;
      }).join('');
      root.innerHTML = `<header class="page-head"><nav class="navbar navbar-default"><div class="container-fluid"><div class="navbar-header"><a class="navbar-brand" data-go="dashboard"
        data-path="Lobby/Dashboard"><span class="op-word"><b>OPN</b>sense</span></a></div><div class="collapse navbar-collapse"><ul class="nav navbar-nav navbar-right">
        <li id="menu_messages"><span class="navbar-text">root@${h(N().name)}.localdomain</span></li><li><span class="navbar-text" style="margin-left: 0">${fa('circle', running() ? 'text-success'
          : 'text-muted', 'Show system status')}</span></li><li><form class="navbar-form" role="search" onsubmit="return false"><div class="input-group"><div class="input-group-addon">
        ${fa('magnifying-glass')}</div><input type="text" style="width: 250px;" class="form-control" tabindex="1" id="menu_search_box" autocomplete="off"></div></form></li></ul></div></div>
        </nav></header><main class="page-content col-sm-9 col-sm-push-3 col-lg-10 col-lg-push-2"><aside id="navigation" class="page-side col-xs-12 col-sm-3 col-lg-2 hidden-xs">
        <div class="row"><nav class="page-side-nav"><div id="mainmenu" class="panel" style="border:0px"><div class="panel list-group" style="border:0px">${menu}</div></div></nav></div></aside>
        <div class="row"><header class="page-content-head"><div class="container-fluid"><ul class="list-inline"><li><h1>${h(page.title || v.title || '')}</h1></li>
        <li class="btn-group-container" id="service_status_container"></li></ul></div></header><section class="page-content-main"><div class="container-fluid"><div class="row">
        <section class="col-xs-12"><div id="messageregion"></div>${opNotices(page)}${page.html}</section></div></div></section><footer class="page-foot"><div class="container-fluid">
        <a>OPNsense</a> (c) 2014-${year} <a>Deciso B.V.</a></div></footer></div></main>`;
      root.querySelectorAll('[data-g]').forEach(a => { a.onclick = () => {
        const g = a.dataset.g;
        if (g.includes('/')) v.open2 = v.open2 === g ? '' : g; else { v.open = v.open === g ? '' : g; v.open2 = ''; }
        render();
      }; });
      root.querySelectorAll('[data-go]').forEach(a => { a.onclick = () => {
        const [target, tab] = a.dataset.go.split(':'), path = a.dataset.path || '';
        if (target === 'logout') return K.logout();
        if (target === 'terminal') return openTerminal();
        const parts = path.split('/'), title = parts.join(': ');
        const keep = {sel: path, title, open: parts[0] || V().open, open2: parts.length > 2 ? parts.slice(0, 2).join('/') : V().open2};
        if (target === 'if' || target === 'dhcp') return go(a.dataset.go, keep);
        go(target, {...keep, tab: tab || null});
      }; });
      root.querySelector('.alert .apply')?.addEventListener('click', apply);
      root.querySelectorAll('.showhelp').forEach(a => { a.onclick = () => a.closest('tr').querySelector('.op-help')?.classList.toggle('hidden'); });
      root.querySelectorAll('.op-fullhelp').forEach(t => { t.onclick = () => {
        const on = t.classList.contains('fa-toggle-off');
        t.className = `fa-solid fa-toggle-${on ? 'on text-success' : 'off text-danger'} op-fullhelp`;
        t.closest('form').querySelectorAll('.op-help').forEach(x => x.classList.toggle('hidden', !on));
      }; });
      page.wire?.(root.querySelector('section.col-xs-12'));
    },
  };
  function opNotices(page) {
    if (pending() && !page.mvc) {
      return `<div class="alert alert-info" role="alert"><button type="button" class="btn btn-primary pull-right apply" name="apply" value="Apply changes">Apply changes</button>
        <div>The ${h(changed())} configuration has been changed.<br>You must apply the changes in order for them to take effect.</div><div class="clearfix"></div></div>`;
    }
    return V().flash === 'applied' ? '<div class="alert alert-info" role="alert">The changes have been applied successfully.</div>' : '';
  }
  function opPage() {
    const page = V().page || 'dashboard';
    if (page.startsWith('if:')) return opInterface(page.slice(3));
    if (page.startsWith('dhcp:')) return opDhcp(page.slice(5));
    const pages = {dashboard: opDashboard, rules: opRules, 'rule-edit': opEditRule, nat: opNat, 'nat-edit': opEditNat, assign: opAssign, routing: opRoutes, gateways: opGateways,
      general: opGeneral, 'status-if': opOverview, 'diag-routes': opRouteStatus};
    if (pages[page]) return pages[page]();
    return {html: later(page === 'vpn' ? NA.vpn : NA.later)};
  }
  // A legacy OPNsense form: one content box, a striped table of sections, the (i) help of each row, Save and Cancel.
  const row = (label, control, help = '') => `<tr><td>${help ? '<a class="showhelp"><i class="fa-solid fa-circle-info"></i></a>'
    : '<i class="fa-solid fa-circle-info text-muted"></i>'} ${h(label)}</td><td>${control}${help ? `<div class="hidden op-help">${help}</div>` : ''}</td></tr>`;
  const opForm = (sections, back) => `<div class="content-box tab-content"><form class="nl-form" method="post" autocomplete="off">${sections.map(([title, rows, id], i) => `<div class="table-responsive"
    ${id ? ` id="${id}"` : ''}><table class="table table-striped opnsense_standard_table_form"><thead><tr><td style="width:22%"><strong>${h(title)}</strong></td><td style="width:78%; text-align:right">${
      i === 0 ? '<small>full help </small><i class="fa-solid fa-toggle-off text-danger op-fullhelp"></i>' : ''}</td></tr></thead><tbody>${rows.join('')}</tbody></table></div>`).join('')}
    <div class="table-responsive"><table class="table table-striped opnsense_standard_table_form"><tbody><tr><td style="width:22%">&nbsp;</td><td style="width:78%">
    <input name="Submit" type="submit" class="btn btn-primary save" value="Save"> <input type="button" class="btn btn-default nl-back" value="Cancel" data-back="${h(back || '')}"></td></tr>
    </tbody></table></div></form></div>`;
  const opBack = (main, page, extra) => main.querySelector('.nl-back')?.addEventListener('click', () => go(page, extra));
  const box = (title, body) => `<div class="content-box"><header class="content-box-head container-fluid"><h3>${h(title)}</h3></header><div class="content-box-main">${body}</div></div>`;
  const opIpMask = (ipId, ip, lenId, len) => `<table style="max-width: 348px"><tr><td style="width: 285px">${inp(ipId, ip)}</td><td><select class="selectpicker form-control"
    id="${lenId}" style="width:auto">${options(masks(), len)}</select></td></tr></table>`;
  function opDashboard() {
    const n = N(), d = D(), on = running(), mem = n.memory_mib || 128;
    const bar = pct => `<div class="progress" style="margin:0"><div class="progress-bar" role="progressbar" style="width:${pct}%"></div></div>`;
    const info = [['Name', `${h(n.name)}.localdomain`], ['Versions', `${h(d.brand)} ${h(d.model)}<br>Network LABS (Linux micro-VM)`], ['Updates', 'Click to check for updates.'],
      ['CPU type', `${h(n.vcpus || 1)} vCPU`], ['Load average', '0.00, 0.00, 0.00'], ['Uptime', on ? 'Running (lab started)' : 'Lab stopped'], ['Current date/time', h(new Date().toString().replace(/ GMT.*$/, ''))],
      ['Last config change', h(new Date().toString().replace(/ GMT.*$/, ''))], ['CPU usage', bar(on ? 2 : 0)], ['Memory usage', `${bar(on ? 30 : 0)}<small>${on ? 30 : 0} % ( of ${h(mem)} MB )</small>`],
      ['Disk usage', `${bar(10)}<small>10 % / [ufs]</small>`]];
    const ifs = `<table class="table table-striped table-condensed"><tbody>${d.ports.map(p => `<tr><td>${fa('sitemap', 'text-muted')} <a data-go="if:${h(p.port)}" data-path="Interfaces/[${
      h(ifName(p.port))}]">${h(ifName(p.port))}</a></td><td>${up(p) ? fa('arrow-up', 'text-success', 'up') : fa('arrow-down', 'text-danger', 'down')}</td>
      <td>${up(p) ? '1000baseT &lt;full-duplex&gt;' : 'no carrier'}</td><td>${h(ipOf(addressOf(p.port)) || '')}</td></tr>`).join('')}</tbody></table>`;
    const gws = `<table class="table table-striped table-condensed"><thead><tr><th>Name</th><th>RTT</th><th>RTTd</th><th>Loss</th><th>Status</th></tr></thead><tbody>${gateways().map(g =>
      `<tr><td>${h(g.name)}<br><small>${h(g.ip)}</small></td><td>~</td><td>~</td><td>~</td><td><span class="label label-${on ? 'success' : 'default'}">${on ? 'Online' : 'Pending'}</span></td>
      </tr>`).join('') || '<tr><td colspan="5">No gateways.</td></tr>'}</tbody></table>`;
    return {title: 'Lobby: Dashboard', html: `<div class="op-widgets"><div>${box('System Information', `<table class="table table-striped table-condensed"><tbody>${info.map(([k, v]) =>
      `<tr><td style="width:30%">${k}</td><td>${v}</td></tr>`).join('')}</tbody></table>`)}</div><div>${box('Interfaces', ifs)}<br>${box('Gateways', gws)}</div></div>`};
  }
  function opRules() {
    const tab = V().tab || ports()[1] || ports()[0], floating = tab === 'floating', list = rulesOn(tab);
    const btn = (cls, icon, title, attrs = '') => `<button type="button" class="btn btn-${cls} btn-xs" title="${title}" ${attrs}>${fa(icon, 'fa-fw')}</button>`;
    const rows = list.map(([r, i]) => `<tr class="rule"><td><input type="checkbox" data-c="${i}"></td><td>${r.action === 'accept' ? fa('play', 'fa-fw text-success', 'pass')
      : fa('xmark', 'fa-fw text-danger', 'block')}${fa('arrow-right-to-bracket', 'fa-fw text-info', 'in')}</td>${floating ? `<td>${h(r.out ? ifName(r.out) : 'any')}</td>` : ''}
      <td>IPv4 ${h(proto(r))}</td><td>${h(r.source || '*')}</td><td>*</td><td>${h(r.destination || '*')}</td><td>${h(r.dport || '*')}</td><td>${h(r.out && !floating ? ifName(r.out) : '*')}</td>
      <td>*</td><td>${h(r.name)}</td><td class="text-nowrap">${btn('default', 'arrow-left', 'Move selected rules before this rule', `data-m="${i}"`)} ${btn('default', 'pencil', 'Edit',
        `data-e="${i}"`)} ${btn('default', 'clone', 'Clone', `data-k="${i}"`)} ${btn('default', 'trash-can', 'Delete', `data-x="${i}"`)}</td></tr>`).join('');
    const span = floating ? 12 : 11;
    return {title: `Firewall: Rules: ${floating ? 'Floating' : ifName(tab)}`, html: `<div class="content-box"><form onsubmit="return false"><div class="table-responsive">
      <table class="table table-striped table-hover" id="rules"><thead><tr><th><input type="checkbox" id="selectAll"></th><th>&nbsp;</th>${floating ? '<th>Interface</th>' : ''}
      <th>Protocol</th><th>Source</th><th>Port</th><th>Destination</th><th>Port</th><th>Gateway</th><th>Schedule</th><th>Description ${fa('circle-question', '', 'Help')}</th>
      <th class="text-nowrap">${btn('primary', 'plus', 'Add', 'data-add="1"')} ${btn('default', 'trash-can', 'Delete selected', 'data-dels="1"')}</th></tr></thead><tbody>
      <tr><td colspan="${span}"><a class="nl-auto" style="cursor:pointer">${fa('chevron-right', 'fa-fw')} Automatically generated rules</a></td></tr>${rows || `<tr><td colspan="${span}">
      <span class="text-muted">No ${floating ? 'floating' : 'interfaces'} rules are currently defined. ${floating ? '' : 'All incoming connections on this interface will be blocked ' +
        'until you add a pass rule.'}</span></td></tr>`}</tbody><tfoot><tr><td colspan="${span}"><table style="width:100%"><tr><td>${fa('play', 'fa-fw text-success')} pass &nbsp;
      ${fa('xmark', 'fa-fw text-danger')} block &nbsp; <i class="fa-regular fa-hand fa-fw text-danger"></i> reject &nbsp; ${fa('arrow-right-to-bracket', 'fa-fw text-info')} in &nbsp;
      ${fa('arrow-right-from-bracket', 'fa-fw')} out &nbsp; ${fa('bolt', 'fa-fw')} first match</td></tr></table></td></tr></tfoot></table></div></form></div>`,
    wire(main) {
      const checks = () => [...main.querySelectorAll('[data-c]:checked')].map(c => Number(c.dataset.c));
      main.querySelector('#selectAll').onchange = e => { main.querySelectorAll('[data-c]').forEach(c => { c.checked = e.target.checked; }); };
      main.querySelector('[data-add]').onclick = () => go('rule-edit', {tab, sel: V().sel, title: V().title, edit: {index: null, iface: floating ? '' : tab}});
      main.querySelectorAll('[data-e]').forEach(b => { b.onclick = () => go('rule-edit', {tab, sel: V().sel, title: V().title, edit: {index: Number(b.dataset.e)}}); });
      main.querySelectorAll('[data-k]').forEach(b => { b.onclick = () => go('rule-edit', {tab, sel: V().sel, title: V().title, edit: {index: null, copy: Number(b.dataset.k)}}); });
      main.querySelectorAll('[data-x]').forEach(b => { b.onclick = () => { editFw().rules.splice(Number(b.dataset.x), 1); render(); }; });
      main.querySelector('[data-dels]').onclick = () => { const out = checks().sort((a, b) => b - a); out.forEach(i => editFw().rules.splice(i, 1)); if (out.length) render(); };
      main.querySelectorAll('[data-m]').forEach(b => { b.onclick = () => {
        const moving = checks(), to = Number(b.dataset.m), all = editFw().rules;
        if (!moving.length || moving.includes(to)) return;
        const picked = moving.map(i => all[i]), rest = all.filter((_, i) => !moving.includes(i));
        rest.splice(rest.indexOf(all[to]), 0, ...picked);
        editFw().rules = rest;
        render();
      }; });
    }};
  }
  function opWhere(prefix, label, value) {
    const w = where(prefix, value);
    return row(label, `<table style="max-width: 348px"><tr><td>${sel(prefix + 'Type', [['any', 'any'], ['network', 'Single host or Network']],
      w.kind === 'any' ? 'any' : 'network')}</td></tr><tr><td>${opIpMask(prefix, w.ip, prefix + 'Len', w.len)}</td></tr></table>`, `Specify the ${label.toLowerCase()} address of this rule, as a host or a network.`);
  }
  function opEditRule() {
    const e = V().edit || {index: null}, f = candidateFw(), base = e.index !== null ? f.rules[e.index] : e.copy !== undefined ? {...f.rules[e.copy], name: f.rules[e.copy].name + '-copy'}
      : {action: 'accept', in: e.iface};
    const port = base.dport ? String(base.dport) : '', known = PORTS.some(([v]) => v === port);
    const back = {tab: V().tab, sel: V().sel, title: V().title};
    return {title: 'Firewall: Rules: Edit', html: opForm([['Edit Firewall rule', [
      row('Action', sel('pfAct', [['accept', 'Pass'], ['drop', 'Block'], ['reject', 'Reject', true]], base.action), 'Choose what to do with packets that match the criteria specified ' +
        'below. Hint: the difference between block and reject is that with reject, a packet (TCP RST or ICMP port unreachable for UDP) is returned to the sender, whereas with ' +
        'block the packet is dropped silently. In either case, the original packet is discarded.'),
      row('Disabled', '<input type="checkbox" disabled> Disable this rule', 'Set this option to disable this rule without removing it from the list.'),
      row('Quick', '<input type="checkbox" checked disabled> Apply the action immediately on match.', 'If a packet matches a rule specifying quick, then that rule is considered the ' +
        'last matching rule and the specified action is taken.'),
      row('Interface', sel('pfIn', [['', '(floating)'], ...ports().map(p => [p, ifName(p)])], base.in || '')),
      row('Direction', sel('pfDir', [['in', 'in']], 'in'), 'Direction of the traffic. The default policy is to filter inbound traffic.'),
      row('TCP/IP Version', sel('pfAf', [['inet', 'IPv4']], 'inet')), row('Protocol', sel('pfProto', PROTOS, base.protocol || 'any'), 'Choose which IP protocol this rule should match.'),
      opWhere('pfSrc', 'Source', base.source), opWhere('pfDst', 'Destination', base.destination),
      row('Destination port range', `<table class="table table-condensed" style="max-width:348px"><thead><tr><th>from:</th><th>to:</th></tr></thead><tbody><tr><td>${sel('pfPortSel', PORTS,
        known && port ? port : '')}</td><td>${sel('pfPortTo', PORTS, known && port ? port : '', 'disabled')}</td></tr><tr><td>${inp('pfPort', known ? '' : port)}</td><td>${inp('pfPortToC', '',
          'disabled')}</td></tr></tbody></table>`, 'Specify the port or port range for the destination of the packet for this rule.'),
      row('Log', '<input type="checkbox" disabled> Log packets that are handled by this rule', 'Hint: the firewall has limited local log space. Don\'t turn on logging for everything.'),
      row('Description', inp('pfName', base.name || ''), 'You may enter a description here for your reference.'),
      row('Gateway', sel('pfOut', [['', 'default'], ...ports().map(p => [p, ifName(p)])], base.out || ''), 'Network LABS: the interface the matched packets leave by (optional).')]]], 'rules'),
    wire(main) {
      const sync = () => {
        const p = val(main, '#pfProto');
        main.querySelector('#pfPort').closest('table').closest('tr').classList.toggle('hidden', !(p === 'tcp' || p === 'udp'));
        ['pfSrc', 'pfDst'].forEach(x => { const kind = val(main, `#${x}Type`); main.querySelector('#' + x).disabled = kind === 'any'; main.querySelector(`#${x}Len`).disabled = kind !== 'network'; });
      };
      main.querySelectorAll('select').forEach(s => s.addEventListener('change', sync));
      sync();
      opBack(main, 'rules', back);
      submit(main, form => {
        const rule = readRule(form, e.index === null ? {} : base);
        putRule(e.index, rule);
        Object.assign(V(), {page: 'rules', tab: rule.in || 'floating', edit: null});
      });
    }};
  }
  function opNat() {
    const tab = V().tab === 'Outbound' ? 'Outbound' : 'Port Forward';
    const btn = (cls, icon, title, attrs = '') => `<button type="button" class="btn btn-${cls} btn-xs" title="${title}" ${attrs}>${fa(icon, 'fa-fw')}</button>`;
    const acts = i => `<td class="text-nowrap">${btn('default', 'pencil', 'Edit', `data-e="${i}"`)} ${btn('default', 'clone', 'Clone', `data-k="${i}"`)} ${btn('default', 'trash-can', 'Delete',
      `data-x="${i}"`)}</td>`;
    const grid = (head, rows, empty) => `<div class="content-box"><form onsubmit="return false"><div class="table-responsive"><table class="table table-striped table-hover"><thead><tr>${
      head.map(c => `<th>${c}</th>`).join('')}<th class="text-nowrap">${btn('primary', 'plus', 'Add', 'data-add="1"')}</th></tr></thead><tbody>${rows.join('') ||
      `<tr><td colspan="${head.length + 1}"><span class="text-muted">${empty}</span></td></tr>`}</tbody></table></div></form></div>`;
    let html;
    if (tab === 'Outbound') {
      const mode = outbound().length ? 'hybrid' : 'automatic';
      const radio = (value, title, text) => `<td style="width:25%"><input type="radio" name="mode" value="${value}"${value === mode ? ' checked' : ' disabled'}> <strong>${title}</strong>
        <br><small>${text}</small></td>`;
      html = `<div class="content-box"><form onsubmit="return false"><div class="table-responsive"><table class="table table-striped"><thead><tr><th colspan="4">Mode:</th></tr></thead>
        <tbody><tr>${radio('automatic', 'Automatic outbound NAT rule generation', '(no manual rules can be used)')}${radio('hybrid', 'Hybrid outbound NAT rule generation',
          '(automatically generated rules are applied after manual rules)')}${radio('advanced', 'Manual outbound NAT rule generation', '(no automatic rules are being generated)')}
        ${radio('disabled', 'Disable outbound NAT rule generation', '(outbound NAT is disabled)')}</tr></tbody></table></div></form></div><br>` +
        grid(['', 'Interface', 'Source', 'Source Port', 'Destination', 'Destination Port', 'NAT Address', 'NAT Port', 'Static Port', 'Description'], outbound().map(([r, i]) =>
          `<tr><td>${fa('play', 'fa-fw text-success')}</td><td>${h(ifName(r.out || ports()[0]))}</td><td>${h(r.source || 'any')}</td><td>*</td><td>${h(r.destination || '*')}</td>
          <td>${h(r.dport || '*')}</td><td>${h(r.type === 'masquerade' ? 'Interface address' : r.to)}</td><td>*</td><td>NO</td><td>${h(r.name)}</td>${acts(i)}</tr>`), 'No manual rules.');
    } else {
      html = grid(['', 'Interface', 'Proto', 'Address', 'Ports', 'Address', 'Ports', 'IP', 'Ports', 'Description'], forwards().map(([r, i]) => `<tr><td>${fa('play', 'fa-fw text-success')}</td>
        <td>${h(ifName(r.in || ports()[0]))}</td><td>${h((r.protocol || 'any').toUpperCase())}</td><td>${h(r.source || '*')}</td><td>*</td><td>${h(r.destination || '*')}</td>
        <td>${h(r.dport || '*')}</td><td>${h(r.to || '')}</td><td>${h(r.to_port || r.dport || '*')}</td><td>${h(r.name)}</td>${acts(i)}</tr>`), 'No port forward rules defined.');
    }
    return {title: `Firewall: NAT: ${tab}`, html,
      wire(main) {
        const keep = {tab, sel: V().sel, title: V().title};
        main.querySelector('[data-add]').onclick = () => go('nat-edit', {...keep, edit: {index: null, type: tab === 'Outbound' ? 'masquerade' : 'dnat'}});
        main.querySelectorAll('[data-e]').forEach(b => { b.onclick = () => go('nat-edit', {...keep, edit: {index: Number(b.dataset.e)}}); });
        main.querySelectorAll('[data-k]').forEach(b => { b.onclick = () => go('nat-edit', {...keep, edit: {index: null, copy: Number(b.dataset.k)}}); });
        main.querySelectorAll('[data-x]').forEach(b => { b.onclick = () => dropEntry('nat', Number(b.dataset.x), true).then(render); });
      }};
  }
  function opEditNat() {
    const e = V().edit || {index: null, type: 'dnat'}, r = natSource(e), forward = r.type === 'dnat', back = {tab: V().tab, sel: V().sel, title: V().title};
    const port = r.dport ? String(r.dport) : '', known = PORTS.some(([v]) => v === port), ifs = ports().map(p => [p, ifName(p)]);
    const dst = where('nxDst', r.destination), src = where('nxSrc', r.source);
    const addr = (prefix, w, types, chosen) => `<table style="max-width: 348px"><tr><td>${sel(prefix + 'Type', types, chosen)}</td></tr><tr><td>${opIpMask(prefix, w.ip, prefix + 'Len', w.len)}
      </td></tr></table>`;
    const portRange = `<table class="table table-condensed" style="max-width:348px"><thead><tr><th>from:</th><th>to:</th></tr></thead><tbody><tr><td>${sel('nxPortSel', PORTS,
      known && port ? port : '')}</td><td>${sel('nxPortTo', PORTS, known && port ? port : '', 'disabled')}</td></tr><tr><td>${inp('nxPort', known ? '' : port)}</td><td>${inp('nxPortToC', '',
        'disabled')}</td></tr></tbody></table>`;
    const rows = forward ? [row('Interface', sel('nxIn', ifs, r.in || ports()[0]), 'Choose which interface this rule applies to. Hint: in most cases, you\'ll want to use WAN here.'),
      row('TCP/IP Version', sel('nxAf', [['inet', 'IPv4']], 'inet')), row('Protocol', sel('nxProto', PROTOS.filter(([v]) => v !== 'any'), r.protocol || 'tcp'),
        'Choose which IP protocol this rule should match. Hint: in most cases, you should specify TCP here.'),
      row('Destination', addr('nxDst', dst, [['wanaddr', `${ifName(r.in || ports()[0])} address`], ['network', 'Single host or Network']], r.destination ? 'network' : 'wanaddr'),
        'Specify the destination address and mask for this rule.'),
      row('Destination port range', portRange, 'When using the TCP or UDP protocols, specify the port or port range for the destination of the packet for this mapping.'),
      row('Redirect target IP', inp('nxTo', r.to || ''), 'Enter the internal IP address of the server on which you want to map the ports. e.g. 192.168.1.12'),
      row('Redirect target port', inp('nxToPort', r.to_port || ''), 'Specify the port on the machine with the IP address entered above.'),
      row('Description', inp('nxName', r.name || ''), 'You may enter a description here for your reference (not parsed).'),
      row('Filter rule association', sel('nxAssoc', [['', 'Add associated filter rule']], ''), '')]
      : [row('Interface', sel('nxOut', ifs, r.out || ports()[0]), 'Choose which interface this rule applies to. Hint: in most cases, you\'ll want to use WAN here.'),
        row('TCP/IP Version', sel('nxAf', [['inet', 'IPv4']], 'inet')), row('Protocol', sel('nxProto', PROTOS, r.protocol || 'any')),
        row('Source address', addr('nxSrc', src, [['any', 'any'], ['network', 'Single host or Network']], src.kind === 'any' ? 'any' : 'network'), 'Enter the source network for the outbound NAT mapping.'),
        row('Destination address', addr('nxDst', dst, [['any', 'any'], ['network', 'Single host or Network']], dst.kind === 'any' ? 'any' : 'network'),
          'Enter the destination network for the outbound NAT mapping.'),
        row('Translation / target', sel('nxType', [['masquerade', 'Interface address'], ['snat', 'Interface address (static)']], r.type || 'masquerade'),
          'Packets matching this rule will be mapped to the IP address given here.'),
        row('Description', inp('nxName', r.name || ''), 'You may enter a description here for your reference (not parsed).')];
    return {title: `Firewall: NAT: ${forward ? 'Port Forward' : 'Outbound'}: Edit`, html: opForm([[forward ? 'Edit Redirect entry' : 'Edit Advanced Outbound NAT entry', rows]]),
      wire(main) {
        const sync = () => ['nxSrc', 'nxDst'].forEach(x => { const t = main.querySelector(`#${x}Type`); if (!t) return;
          main.querySelector('#' + x).disabled = ['any', 'wanaddr'].includes(t.value); main.querySelector(`#${x}Len`).disabled = ['any', 'wanaddr'].includes(t.value); });
        main.querySelectorAll('select').forEach(s => s.addEventListener('change', sync));
        sync();
        opBack(main, 'nat', back);
        submit(main, form => {
          const entry = readNat(form, forward ? 'dnat' : val(form, '#nxType')), f = editFw();
          if (e.index === null) f.nat.push(entry); else f.nat[e.index] = entry;
          Object.assign(V(), {page: 'nat', ...back, tab: forward ? 'Port Forward' : 'Outbound', edit: null});
        });
      }};
  }
  function opAssign() {
    return {title: 'Interfaces: Assignments', html: `<div class="content-box"><form onsubmit="return false"><div class="table-responsive"><table class="table table-striped">
      <thead><tr><th>Interface</th><th>Identifier</th><th>Device</th><th></th></tr></thead><tbody>${D().ports.map((p, i) => `<tr><td><strong><u><span style="cursor:pointer"
      data-go="if:${h(p.port)}" data-path="Interfaces/[${h(ifName(p.port))}]">[${h(ifName(p.port))}]</span></u></strong></td><td>${i === 0 ? 'wan' : i === 1 ? 'lan' : 'opt' + (i - 1)}</td>
      <td><select class="selectpicker form-control">${options([[p.port, `${portName(p.port)}${p.peer ? ' (' + p.peer + ')' : ''}`]], p.port)}</select></td><td>${i > 1
        ? `<button type="button" class="btn btn-default" disabled>${fa('trash-can', 'fa-fw')}</button>` : ''}</td></tr>`).join('')}<tr><td><strong>New interface:</strong></td><td></td>
      <td><select class="selectpicker form-control" disabled><option>(none)</option></select></td><td><button type="button" class="btn btn-primary" disabled>${fa('plus', 'fa-fw')}</button>
      </td></tr><tr><td colspan="4"><button type="button" class="btn btn-primary" disabled>Save</button></td></tr></tbody></table></div></form></div>`,
    wire(main) { main.querySelectorAll('span[data-go]').forEach(a => { a.onclick = () => go(a.dataset.go, {sel: a.dataset.path, title: 'Interfaces: ' + a.textContent, open: 'Interfaces'}); }); }};
  }
  function opInterface(port) {
    const a = addressOf(port), name = ifName(port), i = ports().indexOf(port);
    const types = [['none', 'None'], ['staticv4', 'Static IPv4'], ['dhcp', 'DHCP', true], ['ppp', 'PPP', true], ['pppoe', 'PPPoE', true], ['pptp', 'PPTP', true], ['l2tp', 'L2TP', true]];
    return {title: `Interfaces: [${name}]`, html: opForm([['Basic configuration', [row('Enable', '<input type="checkbox" checked disabled> Enable Interface'),
      row('Lock', '<input type="checkbox" disabled> Prevent interface removal', 'If this option is set, this interface cannot be removed from the assignments.'),
      row('Device', h(portName(port))), row('Identifier', i === 0 ? 'wan' : i === 1 ? 'lan' : `opt${i - 1}`), row('Description', inp('pfDescr', name, 'disabled'),
        'Enter a description (name) for the interface here.'),
      row('Block private networks', '<input type="checkbox" disabled>', 'When set, this option blocks traffic from IP addresses that are reserved for private networks as per RFC 1918.'),
      row('Block bogon networks', '<input type="checkbox" disabled>', 'When set, this option blocks traffic from IP addresses that are reserved but not RFC 1918 or not yet assigned by IANA.'),
      row('IPv4 Configuration Type', sel('pfType', types, a ? 'staticv4' : 'none')), row('IPv6 Configuration Type', sel('pfType6', [['none', 'None']], 'none')),
      row('MAC address', inp('pfMac', '', 'disabled'), 'This field can be used to modify ("spoof") the MAC address of this interface.'),
      row('MTU', inp('pfMtu', '', 'disabled'), 'If you leave this field blank, the adapter\'s default MTU will be used.')]],
    ['Static IPv4 configuration', [row('IPv4 address', opIpMask('pfIp', ipOf(a), 'pfLen', lenOf(a) || 24)), row('IPv4 gateway rules', sel('pfGwSel', [['none', 'Auto-detect'],
      ...(i === 0 ? gateways().map(g => [g.name, `${g.name} - ${g.ip}`]) : [])], i === 0 && gateways().length ? gateways()[0].name : 'none', 'disabled'), 'If this interface is a multi-WAN ' +
      'interface, select an existing gateway from the list. For single WAN interfaces a gateway must be created but set to auto-detect.')], 'nl-static']], 'dashboard'),
    wire(main) {
      const sync = () => main.querySelector('#nl-static').classList.toggle('hidden', val(main, '#pfType') !== 'staticv4');
      main.querySelector('#pfType').onchange = sync;
      sync();
      opBack(main, 'dashboard', {sel: 'Lobby/Dashboard', title: 'Lobby: Dashboard', open: 'Lobby'});
      submit(main, form => readIface(form, port));
    }};
  }
  // OPNsense's newer (MVC) pages: a grid with its command buttons, a modal dialog to edit a row, then Apply below the grid.
  const grid = (id, head, rows, foot) => `<div class="content-box"><div id="${id}-header" class="bootgrid-header container-fluid"><div class="row"><div class="col-sm-12 actionBar">
    <div class="search form-group"><div class="input-group"><span class="icon input-group-addon fa-solid fa-magnifying-glass"></span><input type="text" class="search-field form-control"
    placeholder="Search"></div></div></div></div></div><table id="${id}" class="table table-condensed table-hover table-striped table-responsive bootgrid-table"><thead><tr>${head.map(c =>
      `<th>${c}</th>`).join('')}</tr></thead><tbody>${rows.join('') || `<tr><td colspan="${head.length}" class="no-results">No results found!</td></tr>`}</tbody>${foot}</table>
    <div id="${id}-footer" class="bootgrid-footer container-fluid"><div class="row"><div class="col-sm-6"></div><div class="col-sm-6 infoBar"><div class="infos">Showing ${rows.length ? 1 : 0}
    to ${rows.length} of ${rows.length} entries</div></div></div></div></div>`;
  function opRoutes() {
    const btn = (cls, icon, title, attrs = '') => `<button type="button" class="btn btn-xs btn-${cls}" title="${title}" ${attrs}><span class="fa-solid fa-fw fa-${icon}"></span></button>`;
    const rows = staticRoutes().map((r, i) => `<tr><td><input type="checkbox" class="select-box"></td><td><span class="fa-solid fa-fw fa-check text-success"></span></td><td>${h(r.network)}</td>
      <td>${h(gateways().find(g => g.ip === r.gateway)?.name || r.gateway)}</td><td></td><td class="text-nowrap">${btn('default', 'pencil', 'Edit', `data-e="${i}"`)}
      ${btn('default', 'clone', 'Clone', `data-k="${i}"`)} ${btn('default', 'trash-can', 'Delete', `data-x="${i}"`)}</td></tr>`);
    return {title: 'System: Routes: Configuration', mvc: true, html: `${grid('grid-routes', ['<input type="checkbox" class="select-box">', 'Disabled', 'Network', 'Gateway', 'Description',
      'Commands'], rows, `<tfoot><tr><td></td><td colspan="4"></td><td>${btn('primary', 'plus', 'Add', 'data-add="1"')} ${btn('default', 'trash-can', 'Delete selected')}</td></tr></tfoot>`)}
      <div class="col-md-12"><hr><button class="btn btn-primary apply" type="button"><b>Apply</b></button>${pending() ? ' <span class="text-muted">&nbsp;The changes are not applied yet.</span>'
        : ''}<br><br></div>${V().edit ? opRouteModal() : ''}`,
    wire(main) {
      main.querySelector('.col-md-12 .apply').onclick = apply;
      main.querySelector('[data-add]').onclick = () => { V().edit = {index: null}; render(); };
      main.querySelectorAll('[data-e]').forEach(b => { b.onclick = () => { V().edit = {index: Number(b.dataset.e)}; render(); }; });
      main.querySelectorAll('[data-k]').forEach(b => { b.onclick = () => { V().edit = {index: null, copy: Number(b.dataset.k)}; render(); }; });
      main.querySelectorAll('[data-x]').forEach(b => { b.onclick = () => { dropRoute(Number(b.dataset.x)); render(); }; });
      const modal = main.querySelector('.modal');
      if (!modal) return;
      const close = () => { V().edit = null; render(); };
      modal.querySelectorAll('.close, .nl-cancel').forEach(b => { b.onclick = close; });
      modal.querySelector('.nl-save').onclick = () => {
        const e = V().edit;
        try {
          saveRoute(modal.querySelector('form'), e.index);
          close();
        } catch (error) { modal.querySelector('.nl-err').textContent = error.message; modal.querySelector('.nl-err').classList.remove('hidden'); }
      };
      modal.querySelector('form').onsubmit = event => { event.preventDefault(); modal.querySelector('.nl-save').click(); };
      modal.querySelector('#pfNet')?.focus();
    }};
  }
  function opRouteModal() {
    const e = V().edit, r = e.index !== null ? staticRoutes()[e.index] : e.copy !== undefined ? staticRoutes()[e.copy] : {network: '', gateway: ''};
    const known = gateways().map(g => [g.ip, `${g.name} - ${g.ip}`]), gwSel = known.some(([ip]) => ip === r.gateway) ? r.gateway : '';
    const line = (label, control, help) => `<tr><td><div class="control-label"><a class="showhelp"><i class="fa-solid fa-circle-info"></i></a> <b>${h(label)}</b></div></td><td>${control}
      <div class="hidden op-help"><small>${help}</small></div></td><td><span class="help-block"></span></td></tr>`;
    return `<div class="modal fade in" tabindex="-1" role="dialog" style="display:block"><div class="modal-backdrop fade in" style="position:fixed"></div><div class="modal-dialog"
      style="z-index:1050;position:relative"><div class="modal-content"><div class="modal-header"><button type="button" class="close" aria-label="Close"><span aria-hidden="true">&times;</span>
      </button><h4 class="modal-title">Edit route</h4></div><div class="modal-body"><form autocomplete="off"><div class="table-responsive"><table class="table table-striped table-condensed">
      <colgroup><col class="col-md-3"><col class="col-md-5"><col class="col-md-4"></colgroup><tbody>
      ${line('Disabled', '<input type="checkbox" disabled>', 'Set this option to disable this static route without removing it from the list.')}
      ${line('Network Address', `<div style="display:flex;gap:4px">${inp('pfNet', r.network ? ipOf(r.network) : '', 'placeholder="192.168.50.0"')}<select class="form-control" id="pfNetLen"
        style="width:auto">${options(masks(), r.network ? lenOf(r.network) : 24)}</select></div>`, 'Destination network for this static route')}
      ${line('Gateway', `${sel('pfGwSel', [['', '(enter an address)'], ...known], gwSel)}<div style="margin-top:4px">${inp('pfGw', gwSel ? '' : r.gateway, 'placeholder="a.b.c.d"')}</div>`,
        'Choose which gateway this route applies to, or enter the next hop (Network LABS).')}
      ${line('Description', inp('pfRouteDescr', ''), 'You may enter a description here for your reference (not parsed).')}</tbody></table></div><button type="submit" class="hidden"></button>
      </form><div class="alert alert-danger hidden nl-err" role="alert"></div></div><div class="modal-footer"><button type="button" class="btn btn-default nl-cancel">Cancel</button>
      <button type="button" class="btn btn-primary nl-save">Save</button></div></div></div></div>`;
  }
  function opGateways() {
    const on = running();
    return {title: 'System: Gateways: Configuration', mvc: true, html: grid('grid-gateways', ['<input type="checkbox" class="select-box">', 'Name', 'Interface', 'Protocol', 'Priority',
      'Gateway', 'Monitor IP', 'RTT', 'RTTd', 'Loss', 'Status', 'Description', 'Commands'], gateways().map(g => `<tr><td><input type="checkbox" class="select-box"></td><td>${h(g.name)}
      <small>(active)</small></td><td>${h(ifName(g.port))}</td><td>IPv4</td><td>255 <small>(upstream)</small></td><td>${h(g.ip)}</td><td>${h(g.ip)}</td><td>~</td><td>~</td><td>~</td>
      <td><span class="label label-${on ? 'success' : 'default'}">${on ? 'Online' : 'Pending'}</span></td><td>Interface ${h(ifName(g.port))} Gateway</td><td class="text-nowrap">
      <button type="button" class="btn btn-xs btn-default" disabled><span class="fa-solid fa-fw fa-pencil"></span></button></td></tr>`), '')};
  }
  function opRouteStatus() {
    const rows = [...D().connected.map(r => ['ipv4', r.network, `link#${ports().indexOf(r.port) + 1}`, 'U', r.port]), ...D().static.map(r => ['ipv4', r.network, r.gateway, 'UGS', r.port])];
    return {title: 'System: Routes: Status', mvc: true, html: grid('grid-routes-status', ['Proto', 'Destination', 'Gateway', 'Flags', 'Use', 'MTU', 'Netif', 'Netif (name)', 'Expire'],
      rows.map(([p, dest, gw, flags, port]) => `<tr><td>${p}</td><td>${h(dest)}</td><td>${h(gw)}</td><td>${flags}</td><td>0</td><td>1500</td><td>${h(portName(port || ''))}</td>
      <td>${h(port ? ifName(port) : '')}</td><td></td></tr>`), '')};
  }
  function opOverview() {
    return {title: 'Interfaces: Overview', mvc: true, html: grid('grid-overview', ['Status', 'Device', 'Description', 'Routes', 'IPv4 address', 'IPv6 address', 'Commands'],
      D().ports.map(p => `<tr><td>${up(p) ? fa('circle-check', 'text-success', 'up') : fa('circle-xmark', 'text-danger', 'down')}</td><td>${h(portName(p.port))}</td>
      <td>${h(ifName(p.port))}</td><td>${ports().indexOf(p.port) === 0 && N().gateway ? `<span class="label label-default">default ${h(N().gateway)}</span>` : ''}</td>
      <td>${h(addressOf(p.port) || '')}</td><td></td><td><button type="button" class="btn btn-xs btn-default" title="Details" disabled>${fa('magnifying-glass', 'fa-fw')}</button></td></tr>`), '')};
  }
  function opDhcp(port) {
    const s = dhcpNow(), on = Boolean(s && s.interface === port), a = addressOf(port), name = ifName(port);
    if (!a) return {title: `Services: ISC DHCPv4: [${name}]`, html: later('The DHCP Server can only be enabled on interfaces configured with a static IP address.')};
    return {title: `Services: ISC DHCPv4: [${name}]`, html: opForm([['', [row('Enable', `<input type="checkbox" id="pfOn"${on ? ' checked' : ''}> Enable DHCP server on the ${h(name)} interface`),
      row('Deny unknown clients', '<input type="checkbox" disabled>', 'If this is checked, only the clients defined below will get DHCP leases from this server.'),
      row('Subnet', h(networkOf(a))), row('Subnet mask', h(maskOf(lenOf(a)))), row('Available range', h(rangeOf(a))),
      row('Range', `<table class="table table-condensed" style="max-width:348px"><thead><tr><th>from</th><th>to</th></tr></thead><tbody><tr><td>${inp('pfFrom', on ? s.start : '')}</td>
        <td>${inp('pfTo', on ? s.end : '')}</td></tr></tbody></table>`),
      row('DNS servers', inp('pfDns', on ? (s.dns || []).join(', ') : ''), 'Leave blank to use the system default DNS servers: this interface\'s IP if DNS forwarder or resolver is enabled.'),
      row('Gateway', inp('pfGw', on ? s.router || '' : ''), 'The default is to use the IP on this interface of the firewall as the gateway.'),
      row('Default lease time (seconds)', inp('pfLease', on ? s.lease_seconds : ''), 'This is used for clients that do not ask for a specific expiration time. The default is 7200 seconds.')]]],
    'dashboard'),
    wire(main) {
      opBack(main, 'dashboard', {sel: 'Lobby/Dashboard', title: 'Lobby: Dashboard', open: 'Lobby'});
      submit(main, form => readDhcp(form, port));
    }};
  }
  function opGeneral() {
    return {title: 'System: Settings: General', html: opForm([['System', [row('Hostname', inp('pfHost', (V().stage && V().stage.name) || N().name), 'Name of the firewall host, without ' +
      'domain part.'), row('Domain', inp('pfDomain', 'localdomain', 'disabled'), 'Do not use \'local\' as a domain name. It will cause local hosts running mDNS to be unable to resolve local hosts not running mDNS.'),
    row('Time zone', sel('pfTz', [['Etc/UTC', 'Etc/UTC']], 'Etc/UTC', 'disabled'), 'Select the location closest to you.'),
    row('Language', sel('pfLang', [['en_US', 'English']], 'en_US', 'disabled'), 'Choose a language for the web GUI.'),
    row('Theme', sel('pfTheme', [['opnsense', 'opnsense']], 'opnsense', 'disabled'), 'This will change the look and feel of the GUI.')]],
    ['Networking', [row('DNS servers', inp('pfDns1', '', 'disabled'), 'Enter IP addresses to be used by the system for DNS resolution.'),
      row('DNS server options', '<input type="checkbox" checked disabled> Allow DNS server list to be overridden by DHCP/PPP on WAN')]]], 'dashboard'),
    wire(main) {
      opBack(main, 'dashboard', {sel: 'Lobby/Dashboard', title: 'Lobby: Dashboard', open: 'Lobby'});
      submit(main, readHost);
    }};
  }
  function opLogin({hint}) {
    return `<div class="page-login"><div class="container"><main class="login-modal-container"><header class="login-modal-head" style="height:50px;"><div class="navbar-brand">
      <span class="op-word"><b>OPN</b>sense</span></div></header><div class="login-modal-content"><div class="alert alert-danger hidden lg-errbox" role="alert"><span class="lg-err"></span></div>
      <form class="clearfix" id="iform" name="iform" method="post" autocomplete="off"><div class="form-group"><label for="usernamefld">Username:</label><input id="usernamefld" type="text"
      name="usernamefld" class="form-control user us" tabindex="1" autocapitalize="off" autocorrect="off"></div><div class="form-group"><label for="passwordfld">Password:</label>
      <input id="passwordfld" type="password" name="passwordfld" class="form-control pwd pw" tabindex="2"></div><button type="submit" name="login" value="1" class="btn btn-primary pull-right go">
      Login</button></form><small class="lg-hint">${hint}</small></div></main><div class="login-foot text-center"><a>OPNsense</a> (c) 2014-${year} <a>Deciso B.V.</a></div></div></div>`;
  }
})();
