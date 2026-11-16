"""Presentation and console capabilities, separate from the canonical engine grammar."""
from .profiles import PROFILES,profile_role

SKINS={
 'fortigate':('fortios','FortiGate · Dashboard','fortios'),
 'palo-alto':('panos','PAN-OS · Dashboard','panos'),
 'cisco-asa':('asdm','Cisco ASA · ASDM','unavailable'),
 'sophos-fw':('sophos','Sophos · Control center','unavailable'),
 'checkpoint-fw':('checkpoint','Check Point · SmartConsole','unavailable'),
 'sonicwall-fw':('sonicwall','SonicWall · Monitor','unavailable'),
 'juniper-srx':('jweb','Juniper · J-Web','unavailable'),
 'pfsense':('pfsense','pfSense · Status','unavailable'),
 'opnsense':('opnsense','OPNsense · Lobby','unavailable'),
 'synology-ds224':('dsm','DiskStation · Bureau','unavailable'),
 'qnap-ts264':('qts','QTS · Bureau','unavailable'),
 'axis-p3265':('axis','AXIS · Live view','unavailable'),
 'yealink-t54w':('yealink','Yealink · Status','unavailable'),
 'hp-4002dn':('hp','HP · Embedded Web Server','unavailable'),
 'brother-hl5200':('brother','Brother · Web Based Management','unavailable'),
 'mikrotik-crs326':('routeros','RouterOS · WebFig','routeros'),
 'unifi-lite8':('unifi','UniFi Network · Devices','unavailable'),
 'tplink-sg108e':('tplink','Easy Smart · System','unavailable'),
 'netgear-gs108e':('netgear','NETGEAR · System','unavailable'),
 'dlink-dgs1210':('dlink','D-Link · Smart Console','unavailable'),
 'aruba-1930-24':('aruba','Instant On · Local Management','unavailable'),
}

def identity(profile_id):
 p=PROFILES[profile_id];role=profile_role(p)
 if profile_id in SKINS:skin,title,cli=SKINS[profile_id]
 elif p.family in ('windows','linux'):skin=p.family;title='Paramètres Windows' if skin=='windows' else 'Réseau · Linux';cli=p.family
 elif p.brand=='Cisco' and role!='Firewall':skin,title,cli='cisco','Cisco · Device Manager','ios'
 elif p.family=='ios':skin,title,cli='generic','Gestion réseau','ios'
 else:
  skin={'Firewall':'security','NAS':'dsm','Imprimante':'printer','Caméra':'axis','Téléphone IP':'yealink'}.get(role,'generic')
  title=role+' · Gestion LAN';cli='simulator' if p.brand=='Générique' else 'unavailable'
 return {'skin':skin,'title':title,'console':cli,'native':cli in ('ios','windows','linux','fortios','panos','routeros'),
         'notice':'Présentation inspirée de cette famille. Fonctions réseau implémentées uniquement ; aucun firmware constructeur chargé.'}
