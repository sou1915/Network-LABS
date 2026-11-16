"""CLI adapters for access authorization and modeled multicast."""
import re
import shlex
from .engine import vlan_list

class AccessMulticastCLI:
    def feature_command(self,low,line):
        if self.n.kind!='Switch' or self.mode in ('if','range'):
            return None
        if low in ('aaa new-model','no aaa new-model'):
            self.n.aaa_enabled=not low.startswith('no ')
        elif low in ('aaa authentication dot1x default group radius','no aaa authentication dot1x default group radius'):
            self.n.dot1x_radius=not low.startswith('no ')
        elif low in ('dot1x system-auth-control','no dot1x system-auth-control'):
            self.n.dot1x_enabled=not low.startswith('no ')
        elif low in ('ip igmp snooping','no ip igmp snooping'):
            self.n.igmp_enabled=not low.startswith('no ')
        elif low.startswith(('ip igmp snooping vlan ','no ip igmp snooping vlan ')):
            ids=vlan_list(low.split()[-1])
            self.n.igmp_disabled_vlans=sorted(set(self.n.igmp_disabled_vlans)|set(ids)) if low.startswith('no ') else sorted(set(self.n.igmp_disabled_vlans)-set(ids))
        elif low.startswith('ip igmp snooping unknown-multicast action '):
            action=low.split()[-1]
            if action not in ('drop','flood'):
                raise ValueError('Multicast inconnu: drop ou flood. mrouter non modélisé.')
            self.n.igmp_unknown=action
        else:
            return None
        self.changed=True; return ''

    def feature_port(self,name,low):
        if self.n.kind!='Switch':
            return False
        p=self.n.ports[name]
        match=re.fullmatch(r'(?:authentication|dot1x|access-session) port-control (auto|force-authorized|force-unauthorized)',low)
        if match:
            if p.mode!='access':
                raise ValueError('802.1X: ports access uniquement dans ce modèle.')
            p.auth_control=match[1]
            self.lab.auth_sessions.pop(self.node+'/'+name,None)
        elif low in ('no authentication port-control','no dot1x port-control','no access-session port-control'):
            p.auth_control='force-authorized'; self.lab.auth_sessions.pop(self.node+'/'+name,None)
        elif low in ('dot1x pae authenticator','no dot1x pae authenticator'):
            p.authenticator=not low.startswith('no ')
        else:
            return False
        return True

    def feature_pc(self,low,line):
        if low.startswith('dot1x login '):
            parts=shlex.split(line)
            if len(parts)!=4:
                raise ValueError('Helper PC : dot1x login <utilisateur> <mot-de-passe>.')
            result=self.lab.authenticate(self.node,parts[2],parts[3]); self.changed=True; return result
        if low=='dot1x logoff':
            self.lab.logoff(self.node); self.changed=True; return '802.1X logoff.'
        if low.startswith('igmp join '):
            result=self.lab.join_group(self.node,low.split()[-1]); self.changed=True; return result
        if low.startswith('igmp leave '):
            group=low.split()[-1]
            self.n.groups=[g for g in self.n.groups if g!=group]
            self.changed=True; return 'IGMP membership removed.'
        if low.startswith('multicast '):
            return self.lab.multicast(self.node,low.split()[-1])
        return None

    def feature_show(self,low):
        if low.startswith('show dot1x') or low.startswith('show authentication sessions'):
            if self.n.kind!='Switch':
                raise ValueError('Commande réservée aux switches.')
            lines=['Port        Control             Authorized    User']
            for name,p in self.n.ports.items():
                if name.startswith('po') or '.' in name:
                    continue
                session=self.lab.auth_sessions.get(self.node+'/'+name,{})
                lines.append(f'{name:12}{p.auth_control:20}{str(self.lab.access_allowed(self.node,name)):14}{session.get("user","-")}')
            return '\n'.join(lines)+'\nAAA/RADIUS backend local simulé ; pas de paquets EAPOL/EAP/RADIUS.'
        if low in ('show ip igmp snooping','show ip igmp snooping groups'):
            if self.n.kind!='Switch':
                raise ValueError('IGMP snooping: switch requis.')
            if low=='show ip igmp snooping':
                return f'IGMP snooping enabled: {self.n.igmp_enabled}\nDisabled VLANs: {self.compact(self.n.igmp_disabled_vlans)}\nUnknown multicast: {self.n.igmp_unknown}\nStatic membership model; no querier/timers.'
            lines=['VLAN Group             Ports (modeled memberships)']
            for vlan in sorted(map(int,self.n.vlans)):
                if not self.n.igmp_enabled or vlan in self.n.igmp_disabled_vlans:
                    continue
                groups=sorted({g for n in self.lab.nodes.values() for g in n.groups})
                for group in groups:
                    ports,_=self.lab.snooping_ports(self.node,group,vlan)
                    if ports:
                        lines.append(f'{vlan:<5}{group:18}'+','.join(sorted(ports)))
            return '\n'.join(lines)
        return None
