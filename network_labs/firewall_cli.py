"""Explicit simulator commands; these are not FortiOS, PAN-OS, ASA or pf syntax."""
from .firewall import is_firewall,firewall_rule

class FirewallCommands:
    def firewall_command(self,low,line):
        if not (low.startswith('firewall ') or low in ('show firewall','show firewall sessions','show firewall counters')):
            return None
        if not is_firewall(self.n):
            raise ValueError('Sélectionner un profil Firewall dans le catalogue.')
        if low.startswith('show firewall'):
            if low=='show firewall sessions':
                return '\n'.join(f'{proto.upper()}/{port or "–"} {a} → {b}' for proto,a,b,port in sorted(self.lab.firewall_sessions.get(self.node,set()))) or 'Aucune session du dernier test.'
            if low=='show firewall counters':
                return str(self.lab.firewall_counters.get(self.node,{'allow':0,'deny':0}))
            return f'Transparent LAN | ICMP / TCP / UDP simulés | {self.n.firewall_mode} | default {self.n.firewall_default}\n'+'\n'.join(f'{r["id"]} {r["action"]} {r.get("protocol","icmp")}/{r.get("port",0) or "any"} {r["source"]} → {r["target"]}' for r in sorted(self.n.firewall_rules,key=lambda r:r['id']))+'\nCommandes de simulation, pas une CLI constructeur.'
        words=low.split()
        if len(words)==3 and words[1]=='mode' and words[2] in ('stateful','stateless'):
            self.n.firewall_mode=words[2]
        elif len(words)==3 and words[1]=='default' and words[2] in ('allow','deny'):
            self.n.firewall_default=words[2]
        elif len(words)==4 and words[1:3]==['rule','delete']:
            number=int(words[3])
            if not any(r['id']==number for r in self.n.firewall_rules):
                raise ValueError('ID de règle absent.')
            self.n.firewall_rules=[r for r in self.n.firewall_rules if r['id']!=number]
        elif len(words) in (6,7,8) and words[1]=='rule':
            if len(words)==6:
                rule=firewall_rule(words[2],words[3],words[4],words[5])
            else:
                port=0 if len(words)==7 or words[7]=='any' else words[7]
                rule=firewall_rule(words[2],words[3],words[5],words[6],words[4],port)
            self.n.firewall_rules=[r for r in self.n.firewall_rules if r['id']!=rule['id']]+[rule]
        else:
            raise ValueError('firewall mode stateful|stateless ; firewall default allow|deny ; firewall rule <id> allow|deny <source CIDR|any> <destination CIDR|any> ; firewall rule delete <id>')
        self.lab.firewall_sessions.pop(self.node,None)
        self.changed=True;return ''
