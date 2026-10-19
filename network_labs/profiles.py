"""Device catalogue. Profiles describe simulation scope, never vendor firmware."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Profile:
    id: str
    brand: str
    model: str
    kind: str
    family: str = 'ios'
    creatable: bool = True
    scope: str = 'Moteur pédagogique partagé ; pas de firmware constructeur.'
    role: str = ''

PROFILES = {p.id:p for p in [
    Profile('generic-pc','Générique','PC réseau','PC','generic'),
    Profile('windows-10','Microsoft','Windows 10','PC','windows'),
    Profile('windows-11','Microsoft','Windows 11','PC','windows'),
    Profile('windows-server','Microsoft','Windows Server 2022','PC','windows',role='Serveur'),
    Profile('linux-ubuntu','Canonical','Ubuntu','PC','linux'),
    Profile('linux-debian','Debian','Debian','PC','linux'),
    Profile('linux-rocky','Rocky','Rocky Linux','PC','linux'),
    Profile('generic-switch','Générique','Switch 24 ports','Switch'),
    Profile('cisco-2960','Cisco','Catalyst 2960 · 24 FE + 2 GE','Switch'),
    Profile('cisco-9200l','Cisco','Catalyst 9200L · 24 GE + 4 uplinks','Switch'),
    Profile('cisco-ios-router','Cisco','Routeur IOS (1 uplink simulé)','Routeur'),
    Profile('generic-router','Générique','Routeur 802.1Q','Routeur'),
    *[Profile(i,b,m,k,'reference',False,'Référence catalogue : CLI et fonctions constructeur non implémentées.') for i,b,m,k in [
        ('aruba-6100','HPE Aruba','CX 6100','Switch'),
        ('juniper-ex','Juniper','EX2300','Switch'),
        ('arista-7050','Arista','7050','Switch'),
        ('huawei-s5700','Huawei','S5700','Switch'),
        ('mikrotik-crs','MikroTik','CRS / RouterOS','Switch'),
        ('mikrotik-ccr','MikroTik','CCR / RouterOS','Routeur'),
        ('fortigate','Fortinet','FortiGate','Firewall'),
        ('palo-alto','Palo Alto','PA Series','Firewall'),
    ]]
]}

# Endpoints share the LAN IPv4 model; product services and extra hardware ports are excluded.
ENDPOINT_SCOPE='Adaptateur LAN unique simulé : IPv4, DHCP, DNS client, ping, VLAN d’accès. Console de simulation, pas de CLI constructeur. '
for identity,brand,model,role,limits in [
    ('server-linux','Générique','Serveur Linux','Serveur','DNS local A disponible ; pas de fichiers/HTTP/AD.'),
    ('server-windows','Microsoft','Windows Server · LAN','Serveur','DNS local A disponible ; pas d’Active Directory.'),
    ('generic-printer','Générique','Imprimante réseau','Imprimante','Pas de travaux d’impression.'),
    ('hp-4002dn','HP','LaserJet Pro 4002dn','Imprimante','Pas de travaux d’impression.'),
    ('generic-nas','Générique','Stockage NAS','NAS','Pas de SMB/NFS, disques ou agrégation réseau.'),
    ('synology-ds224','Synology','DiskStation DS224+','NAS','Un seul port simulé ; pas de DSM/SMB/NFS.'),
    ('generic-camera','Générique','Caméra IP','Caméra','Pas de vidéo/RTSP ni alimentation PoE.'),
    ('axis-p3265','Axis','P3265-LVE','Caméra','Pas de vidéo/RTSP ni alimentation PoE.'),
    ('generic-phone','Générique','Téléphone IP','Téléphone IP','VLAN data uniquement ; pas de SIP, voix ou port PC passthrough.'),
    ('yealink-t54w','Yealink','SIP-T54W','Téléphone IP','Un seul port simulé ; pas de SIP, voix, Wi-Fi ou passthrough.'),
    ('generic-iot','Générique','Capteur Ethernet','IoT','Pas de protocole applicatif, MQTT ou radio.'),
    ('generic-laptop','Générique','Portable Ethernet','Portable','Connexion filaire uniquement.'),
]:
    family='linux' if identity=='server-linux' else 'windows' if identity=='server-windows' else 'lab'
    PROFILES[identity]=Profile(identity,brand,model,'PC',family,True,ENDPOINT_SCOPE+limits,role)

for identity,brand,model,role in [
    ('generic-ap','Générique','Point d’accès Wi-Fi','Point d’accès'),
    ('generic-wlc','Générique','Contrôleur WLAN','Contrôleur WLAN'),
    ('generic-l3-switch','Générique','Switch L3 / SVI','Switch L3'),
    ('generic-hub','Générique','Hub Ethernet','Hub'),
]:
    PROFILES[identity]=Profile(identity,brand,model,'Switch','reference',False,'Référence : moteur spécifique non implémenté ; création indisponible.',role)


for identity,brand,model in [
    ('fw-stateful','Générique','Firewall stateful LAN'),
    ('fw-stateless','Générique','Filtre stateless LAN'),
    ('fortigate','Fortinet','FortiGate · profil transparent LAN'),
    ('palo-alto','Palo Alto','PA Series · profil transparent LAN'),
    ('cisco-asa','Cisco','ASA · profil transparent LAN'),
    ('pfsense','Netgate','pfSense · profil transparent LAN'),
    ('opnsense','Deciso','OPNsense · profil transparent LAN'),
    ('sophos-fw','Sophos','Firewall · profil transparent LAN'),
    ('checkpoint-fw','Check Point','Quantum · profil transparent LAN'),
    ('sonicwall-fw','SonicWall','TZ · profil transparent LAN'),
    ('juniper-srx','Juniper','SRX · profil transparent LAN'),
]:
    PROFILES[identity]=Profile(identity,brand,model,'Switch','lab-firewall',True,'Deux ports LAN transparents ; règles IPv4 source/destination sur tests ICMP, stateful/stateless. Console de simulation uniquement. Pas de NAT, VPN, IPS/IDS, antivirus, TCP/UDP, routage ou inspection applicative.', 'Firewall')
for identity,title in [('fw-ngfw','NGFW / inspection applicative'),('fw-utm','UTM / antivirus et filtrage web'),('fw-waf','WAF / protection HTTP'),('fw-proxy','Proxy applicatif'),('fw-host','Firewall hôte / endpoint'),('fw-routed','Firewall routé / zones L3')]:
    PROFILES[identity]=Profile(identity,'Générique',title,'Switch','reference',False,'Référence : inspection L7/services spécifiques non implémentés.','Firewall spécialisé')


def profile_role(profile):
    return profile.role or {'PC':'Poste','Switch':'Switch','Routeur':'Routeur'}.get(profile.kind,profile.kind)


def default_profile(kind):
    return {'PC':'generic-pc','Switch':'generic-switch','Routeur':'generic-router'}[kind]


def profile_ports(profile_id,kind):
    if profile_id in PROFILES and PROFILES[profile_id].role=='Firewall':
        return ['gi0/1','gi0/2']
    if profile_id=='cisco-2960':
        return [f'fa0/{i}' for i in range(1,25)]+['gi0/1','gi0/2']
    if profile_id=='cisco-9200l':
        return [f'gi1/0/{i}' for i in range(1,25)]+[f'gi1/1/{i}' for i in range(1,5)]
    return [f'gi0/{i}' for i in range(1,25)] if kind=='Switch' else ['gi0/0'] if kind=='Routeur' else ['eth0']
