"""Transparent LAN firewall for modeled IPv4 transactions. No OS or L7 inspection."""
from ipaddress import IPv4Address,IPv4Network
from .profiles import PROFILES,profile_role

def is_firewall(node):
    return profile_role(PROFILES[node.profile])=='Firewall'

def firewall_rule(number,action,source,target,protocol='icmp',port=0):
    number=int(number)
    if not 1<=number<=65535 or action not in ('allow','deny'):
        raise ValueError('Règle : ID 1..65535 et action allow/deny.')
    port=int(port)
    if protocol not in ('icmp','tcp','udp','tcpudp','any') or not 0<=port<=65535 or (protocol in ('icmp','any') and port):
        raise ValueError('Protocole icmp/tcp/udp/tcpudp/any et port 0..65535 (0 = tous).')
    def network(value):
        return str(IPv4Network('0.0.0.0/0' if value=='any' else value,strict=False))
    return {'id':number,'action':action,'source':network(source),'target':network(target),'protocol':protocol,'port':port}

class Firewall:
    def firewall_check(self,hops,source,target,protocol='icmp',port=0):
        source,target=str(IPv4Address(source)),str(IPv4Address(target))
        visited=set()
        for _,a,b,_ in hops:
            for name in (a,b):
                node=self.nodes[name]
                if name in visited or not is_firewall(node):
                    continue
                visited.add(name)
                state=self.firewall_sessions.setdefault(name,set())
                reverse=(protocol,target,source,port)
                reason='session retour' if node.firewall_mode=='stateful' and reverse in state else None
                action='allow' if reason else node.firewall_default
                if not reason:
                    reason='politique par défaut'
                    for rule in sorted(node.firewall_rules,key=lambda r:r['id']):
                        if (rule.get('protocol','icmp') in (protocol,'any') or (rule.get('protocol')=='tcpudp' and protocol in ('tcp','udp'))) and rule.get('port',0) in (0,port) and IPv4Address(source) in IPv4Network(rule['source']) and IPv4Address(target) in IPv4Network(rule['target']):
                            action=rule['action'];reason='règle '+str(rule['id']);break
                counts=self.firewall_counters.setdefault(name,{'allow':0,'deny':0})
                counts[action]+=1
                self.firewall_log.append(f'{name}: {action} {protocol.upper()}/{port or '–'} {source} → {target} ({reason})')
                if action=='deny':
                    raise ValueError(self.firewall_log[-1])
                if node.firewall_mode=='stateful':
                    state.add((protocol,source,target,port))
