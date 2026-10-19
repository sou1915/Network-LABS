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

PROFILES = {p.id:p for p in [
    Profile('generic-pc','Générique','PC réseau','PC','generic'),
    Profile('windows-10','Microsoft','Windows 10','PC','windows'),
    Profile('windows-11','Microsoft','Windows 11','PC','windows'),
    Profile('windows-server','Microsoft','Windows Server 2022','PC','windows'),
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

def default_profile(kind):
    return {'PC':'generic-pc','Switch':'generic-switch','Routeur':'generic-router'}[kind]


def profile_ports(profile_id,kind):
    if profile_id=='cisco-2960':
        return [f'fa0/{i}' for i in range(1,25)]+['gi0/1','gi0/2']
    if profile_id=='cisco-9200l':
        return [f'gi1/0/{i}' for i in range(1,25)]+[f'gi1/1/{i}' for i in range(1,5)]
    return [f'gi0/{i}' for i in range(1,25)] if kind=='Switch' else ['gi0/0'] if kind=='Routeur' else ['eth0']
