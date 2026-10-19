"""Simulation console helpers for endpoint roles and local DNS."""
from ipaddress import IPv4Address
from .profiles import PROFILES,profile_role
from .lan_services import dns_name

class LANCommands:
    def lan_command(self,low,line):
        if low=='show device':
            profile=PROFILES[self.n.profile]
            return f'{profile_role(profile)} | {profile.brand} | {profile.model}\n{profile.scope}'
        if low.startswith('nslookup '):
            words=line.split()
            if len(words) not in (2,3):
                raise ValueError('nslookup <nom> [IPv4 serveur]')
            address,server=self.lab.resolve_name(self.node,words[1],words[2] if len(words)==3 else None)
            return f'Server: {server}\nName: {dns_name(words[1])}\nAddress: {address}\nDNS local simulé : A uniquement, sans paquets/cache/récursion.'
        if low in ('service dns','no service dns') or low.startswith(('dns record ','no dns record ')) or low=='show dns records':
            if profile_role(PROFILES[self.n.profile])!='Serveur':
                raise ValueError('DNS serveur : sélectionner un profil Serveur dans le catalogue.')
            if low=='show dns records':
                return f'DNS service: {self.n.dns_service}\n'+ '\n'.join(f'{name:32} A {address}' for name,address in sorted(self.n.dns_records.items()))
            if low in ('service dns','no service dns'):
                self.n.dns_service=low=='service dns'
            elif low.startswith('no dns record '):
                words=line.split()
                if len(words)!=4:
                    raise ValueError('no dns record <nom>')
                self.n.dns_records.pop(dns_name(words[3]),None)
            else:
                words=line.split()
                if len(words)!=4:
                    raise ValueError('dns record <nom> <IPv4>')
                name=dns_name(words[2]); address=str(IPv4Address(words[3]))
                self.n.dns_records[name]=address
            self.changed=True;return ''
        return None
