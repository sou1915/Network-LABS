# Third-party notices

Network LABS is licensed under the GNU General Public License, version 3 or (at your option) any later version
([LICENSE](LICENSE)). It ships, beside its own code, the files below, each under its own licence. They are separate
works aggregated with Network LABS (fonts, icons, stylesheets, pictures); their licences allow it and stay theirs.
Where a file was changed, the change is described in the detailed notes:
[network_labs/appliances/assets/README.md](network_labs/appliances/assets/README.md) (sources, versions, SHA-256).

| What | Where | From | Licence |
|---|---|---|---|
| Inter font (the application's text) | `assets/InterVariable.ttf` | rsms/inter | SIL OFL 1.1 ([text](network_labs/appliances/assets/INTER-LICENSE.txt)) |
| Selawik font (Windows pages) | `assets/Selawik-*.woff2` | microsoft/Selawik 1.01 | SIL OFL 1.1 ([text](network_labs/appliances/assets/SELAWIK-LICENSE.txt)) |
| Cascadia Mono font (Windows Terminal) | `assets/CascadiaMono-Regular.woff2` | microsoft/cascadia-code 2407.24 | SIL OFL 1.1 ([text](network_labs/appliances/assets/CASCADIA-LICENSE.txt)) |
| Fluent UI System Icons (Windows pages) | `native_windows_icons.js` (generated) | microsoft/fluentui-system-icons 1.1.347 | MIT ([text](network_labs/appliances/assets/FLUENT-ICONS-LICENSE.txt)) |
| Ethernet and NetworkOffline glyph redraws | `native_products_windows.js` | Microsoft's Segoe Fluent Icons article | CC BY 4.0, © Microsoft |
| WinUI 3 and Windows Community Toolkit design values | `native_products_windows.js` (values only) | microsoft/microsoft-ui-xaml, CommunityToolkit/Windows | MIT |
| Yaru icons (Ubuntu PCs) | `assets/linux/yaru/` | Ubuntu package `yaru-theme-icon` | CC BY-SA 4.0 (copyright files beside them) |
| Adwaita icons (Debian, Fedora, Rocky PCs) | `assets/linux/adwaita/` | Ubuntu package `adwaita-icon-theme` | CC BY-SA 3.0 or LGPL 3 |
| GNOME application and Settings icons | `assets/linux/*/panel-*`, app icons | `gnome-control-center-data`, `nautilus-data`, `gnome-console`, `gnome-text-editor`, `epiphany-browser-data` | GPL 2+ / GPL 3+ (copyright files beside them) |
| Ubuntu Sans and Ubuntu Sans Mono fonts | `assets/linux/fonts/UbuntuSans*.ttf` | Ubuntu package `fonts-ubuntu` | Ubuntu Font Licence 1.0 |
| Cantarell font | `assets/linux/fonts/Cantarell-*.otf` | Ubuntu package `fonts-cantarell` | SIL OFL 1.1 |
| Ubuntu and GNOME default wallpapers (resized) | `assets/linux/walls/` | `ubuntu-wallpapers`, `gnome-backgrounds` | CC BY-SA 4.0, CC BY-SA 3.0 |
| pfSense stylesheets, Bootstrap 3.4.1, Roboto | `assets/pfsense/` | pfsense/pfsense | Apache 2.0 ([text](network_labs/appliances/assets/pfsense/LICENSE)); Bootstrap MIT; Roboto Apache 2.0 |
| OPNsense theme and Source Sans Pro | `assets/opnsense/` | opnsense/core | BSD 2-Clause ([text](network_labs/appliances/assets/opnsense/LICENSE)); fonts SIL OFL 1.1 |
| Font Awesome Free 6.5.1 | `assets/fontawesome/` | as shipped by pfSense | icons CC BY 4.0, fonts SIL OFL 1.1, code MIT ([text](network_labs/appliances/assets/fontawesome/LICENSE.txt)) |

`assets/` stands for `network_labs/appliances/assets/`; scripts are in `network_labs/`.

## Downloaded at setup, not stored in this repository

`network-labs-lab setup --download` downloads, verified by SHA-256: the official Firecracker release (Apache 2.0) and
a Linux guest kernel (GPL 2.0) from its publisher. The guest disk is built on your computer from your own system's
packages (BusyBox, iptables, BIRD, FRR: GPL 2.0 or later); Network LABS does not redistribute them.

## Trademarks

Product names (Cisco, Juniper, Fortinet, Palo Alto Networks, pfSense, OPNsense, Microsoft Windows, Ubuntu, Debian,
Fedora, Rocky Linux and the others in the device library) are trademarks of their owners. Network LABS is not affiliated
with or endorsed by any of them. Its device pages copy the layout and wording of those products for teaching; no vendor
logo or picture is copied, except the Windows logo drawn on the Windows pages' Start button, which is Microsoft's
trademark. Remove it before any commercial or public redistribution if you do not have Microsoft's permission.
