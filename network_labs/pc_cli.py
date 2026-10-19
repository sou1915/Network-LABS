"""Network-only Windows/Linux adapters; no subprocesses or real operating system."""
from ipaddress import IPv4Address, IPv4Interface
import re
import shlex
from .profiles import PROFILES

class PCCommands:
    def pc_static_address(self,address,gateway=None):
        gateway=self.n.gateway if gateway is None else gateway
        dns=self.n.dns[:]
        self.lab.release_dhcp(self.node)
        self.n.address=address; self.n.gateway=gateway; self.n.dns=dns
        self.n.address_mode='static'; self.changed=True

    def pc_link_up(self):
        link=self.lab.link_for(self.node,'eth0')
        return bool(link and link.enabled and not any(p.shutdown or p.errdisabled for p in self.lab.ends(link)))

    def pc_native(self,low,line):
        family=PROFILES[self.n.profile].family
        if low in ('ver','uname -a'):
            expected='windows' if low=='ver' else 'linux'
            if family!=expected:
                raise ValueError('Commande incompatible avec le profil OS.')
            return PROFILES[self.n.profile].model+' — simulation réseau, aucun noyau OS exécuté.'
        if family=='linux':
            if low in ('ip a','ip addr show','ip addr show dev eth0','ip -br addr','ip link show','ip link show dev eth0'):
                return f'eth0  {"UP" if self.pc_link_up() else "DOWN"}  {self.n.address or "sans IPv4"}  {self.n.mac}'
            if low in ('ip route','ip route show'):
                return (f'default via {self.n.gateway} dev eth0\n' if self.n.gateway else '')+(f'{IPv4Interface(self.n.address).network} dev eth0' if self.n.address else '')
            if low in ('dhclient','sudo dhclient','sudo dhclient eth0'):
                return self.pc('ip dhcp','ip dhcp')
            if low in ('sudo dhclient -r eth0','dhclient -r eth0'):
                return self.pc('ip release','ip release')
            match=re.fullmatch(r'(?:sudo )?ip addr (?:add|replace) (\S+) dev eth0',low)
            if match:
                return self.pc('ip address '+match[1],'ip address '+match[1])
            match=re.fullmatch(r'(?:sudo )?ip route (?:add|replace) default via (\S+)(?: dev eth0)?',low)
            if match:
                return self.pc('ip gateway '+match[1],'ip gateway '+match[1])
            match=re.fullmatch(r'(?:sudo )?ip link set (?:dev )?eth0 (up|down)',low)
            if match:
                self.n.ports['eth0'].shutdown=match[1]=='down'; self.changed=True; return ''
            if re.fullmatch(r'(?:sudo )?ip addr flush dev eth0',low):
                self.lab.release_dhcp(self.node)
                self.n.address_mode='static'; self.changed=True; return ''
            match=re.fullmatch(r'(?:sudo )?resolvectl dns eth0 ((?:\S+\s*)+)',low)
            if match:
                addresses=[str(IPv4Address(ip)) for ip in match[1].split()]
                self.n.dns=addresses; self.changed=True; return ''
            if low=='resolvectl status':
                return 'Link eth0\nDNS Servers: '+(' '.join(self.n.dns) or 'aucun')+'\nRésolution de noms non simulée.'
        if family=='windows':
            if low=='ipconfig /all':
                return self.pc('ipconfig','ipconfig')
            if low=='route print':
                return 'IPv4 Route Table\n'+(f'0.0.0.0/0 via {self.n.gateway}\n' if self.n.gateway else '')+f'Interface Ethernet: {self.n.address or "sans IPv4"}'
            if low in ('netsh interface ipv4 show config','netsh interface ipv4 show addresses'):
                return self.pc('ipconfig','ipconfig')
            if low=='netsh interface ipv4 show dnsservers':
                return 'DNS Ethernet: '+(', '.join(self.n.dns) or 'aucun')
            if low.startswith('netsh interface ipv4 set '):
                parts=shlex.split(line)
                command=parts[4].lower()
                if command not in ('address','dnsservers'):
                    raise ValueError('Netsh simulé : set address / set dnsservers.')
                values={}
                for token in parts[5:]:
                    if '=' not in token:
                        raise ValueError('Utiliser les paramètres nommés : name=Ethernet source=static …')
                    key,value=token.split('=',1); key=key.lower()
                    if key in values:
                        raise ValueError('Paramètre dupliqué : '+key)
                    values[key]=value
                accepted={'name','source','address','mask','gateway'} if command=='address' else {'name','source','address'}
                if set(values)-accepted:
                    raise ValueError('Paramètre netsh non simulé : '+', '.join(sorted(set(values)-accepted)))
                if values.get('name','').lower()!='ethernet':
                    raise ValueError('Interface simulée : name="Ethernet".')
                source=values.get('source','').lower()
                if command=='dnsservers':
                    if source!='static' or 'address' not in values:
                        raise ValueError('DNS simulé : source=static address=<IPv4|none>.')
                    addresses=[] if values['address'].lower()=='none' else [str(IPv4Address(values['address']))]
                    self.n.dns=addresses; self.changed=True; return 'Ok.'
                if source=='dhcp':
                    if set(values)-{'name','source'}:
                        raise ValueError('source=dhcp ne prend pas de paramètres statiques.')
                    return self.pc('ip dhcp','ip dhcp')
                if source!='static' or not {'address','mask'}<=values.keys():
                    raise ValueError('Requis : source=static address=<IPv4> mask=<masque> [gateway=<IPv4>].')
                address=str(IPv4Interface(values['address']+'/'+values['mask']))
                gateway=str(IPv4Address(values['gateway'])) if values.get('gateway') else ''
                self.pc_static_address(address,gateway)
                return 'Ok.'
        return None
