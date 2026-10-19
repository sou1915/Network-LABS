"""Mode-aware help and common IOS-style abbreviations; not a full IOS grammar."""
class CLIEditing:
    @staticmethod
    def expand(word,choices):
        if word.lower() in choices:
            return word.lower()
        matches=[c for c in choices if c.startswith(word.lower())]
        if len(matches)>1:
            raise ValueError('Ambiguous command: '+word)
        return matches[0] if matches else word

    def normalize_command(self,line):
        words=line.split()
        if not words or self.n.kind=='PC':
            return line
        config=self.mode not in ('user','priv')
        first=['hostname','interface','vlan','exit','end','no','do','spanning-tree','switchport','description','shutdown','channel-group','ip','encapsulation','network','default-router','dns-server','lease','vtp','name','revision','instance','service','aaa','dot1x','authentication','access-session'] if config else ['enable','disable','show','write','copy','clear','configure','ping','exit']
        words[0]=self.expand(words[0],first)
        if words[0] in ('no','do') and len(words)>1:
            return words[0]+' '+self.normalize_command(' '.join(words[1:]))
        def at(i,choices):
            if len(words)>i:
                words[i]=self.expand(words[i],choices)
        if words[0]=='configure':
            at(1,['terminal'])
        elif words[0]=='interface':
            if len(words)>1 and 'range'.startswith(words[1].lower()):
                at(1,['range'])
        elif words[0]=='show':
            if len(words)>1 and words[1].lower() in ('int','interface'):
                words[1]='interfaces'
            if len(words)>1 and words[1].lower()=='run':
                words[1]='running-config'
            at(1,['interfaces','vlan','spanning-tree','etherchannel','mac','port-security','running-config','startup-config','ip','dtp','vtp','capabilities','version','cdp','lldp','pending','dot1x','authentication'])
            if len(words)>1:
                command=words[1]
                if command=='interfaces':
                    at(2,['status','trunk','switchport']); at(3,['switchport'])
                elif command=='spanning-tree':
                    at(2,['mst','vlan']); at(3,['configuration']) if len(words)>3 and not words[3].isdigit() else None
                elif command=='etherchannel':
                    at(2,['summary'])
                elif command=='mac':
                    at(2,['address-table']); at(3,['dynamic'])
                elif command=='ip':
                    at(2,['interface','route','dhcp','arp','verify'])
                    at(3,['brief']) if len(words)>2 and words[2]=='interface' else None
                elif command in ('cdp','lldp'):
                    at(2,['neighbors'])
                elif command=='vtp':
                    at(2,['status'])
                elif command=='dtp':
                    at(2,['interface'])
        elif words[0]=='vtp':
            at(1,['mode','domain','password','version'])
        elif words[0]=='channel-group':
            at(2,['mode']); at(3,['active','passive','on','auto','desirable'])
        elif words[0]=='switchport':
            at(1,['mode','access','trunk','port-security','nonegotiate'])
            if len(words)>1:
                if words[1]=='mode':
                    at(2,['access','trunk','dynamic']); at(3,['auto','desirable'])
                elif words[1]=='access':
                    at(2,['vlan'])
                elif words[1]=='trunk':
                    at(2,['allowed','native']); at(3,['vlan'])
                elif words[1]=='port-security':
                    at(2,['maximum','violation','mac-address'])
                    if len(words)>2 and words[2]=='violation':
                        at(3,['shutdown','restrict','protect'])
        elif words[0]=='spanning-tree':
            at(1,['mode','mst','vlan','portfast','bpduguard','cost','port-priority'])
            if len(words)>1:
                if words[1]=='mode':
                    at(2,['pvst','rapid-pvst','mst'])
                elif words[1] in ('mst','vlan'):
                    if words[1]=='mst' and len(words)>2 and not words[2].isdigit():
                        at(2,['configuration'])
                    else:
                        at(3,['root','priority']); at(4,['primary','secondary']) if len(words)>3 and words[3]=='root' else None
                elif words[1]=='bpduguard':
                    at(2,['enable'])
        return ' '.join(words)

    def help_patterns(self):
        shows=['show dot1x','show authentication sessions','show ip igmp snooping','show ip igmp snooping groups','show running-config','show startup-config','show interfaces status','show interfaces trunk','show interfaces <interface> switchport','show vlan brief','show spanning-tree','show spanning-tree vlan <id>','show spanning-tree mst <instance>','show spanning-tree mst configuration','show etherchannel summary','show mac address-table','show port-security','show ip interface brief','show ip route','show ip dhcp pool','show ip dhcp binding','show ip dhcp snooping binding','show ip arp inspection statistics','show dtp interface <interface>','show vtp status','show capabilities']
        if self.n.kind=='PC':
            from .profiles import PROFILES
            family=PROFILES[self.n.profile].family
            native={'windows':['ver','ipconfig /all','ipconfig /renew','ipconfig /release','route print','netsh interface ipv4 set address name=Ethernet source=static address=<IPv4> mask=<mask> gateway=<IPv4>','netsh interface ipv4 set address name=Ethernet source=dhcp','netsh interface ipv4 set dnsservers name=Ethernet source=static address=<IPv4>','netsh interface ipv4 show dnsservers'],
                    'linux':['uname -a','ip addr show','ip route','ip link show','sudo ip addr replace <CIDR> dev eth0','sudo ip route replace default via <IPv4> dev eth0','sudo ip link set dev eth0 down','sudo ip link set dev eth0 up','sudo ip addr flush dev eth0','sudo resolvectl dns eth0 <IPv4>','resolvectl status','sudo dhclient eth0','sudo dhclient -r eth0']}.get(family,[])
            return native+['help','ipconfig','ip address <CIDR>','ip gateway <IPv4>','ip dns <IPv4>','ip dhcp','ip release','ip link up','ip link down','ping <IPv4>','dot1x login <user> <password>','dot1x logoff','igmp join <group>','igmp leave <group>','multicast <group>','show capabilities']
        common=['exit','end','help']
        if self.mode in ('user','priv'):
            return shows+['enable','disable','configure terminal','write memory','copy running-config startup-config','clear mac address-table dynamic']+common
        if self.mode=='mst':
            return ['name <region>','revision <number>','instance <id> vlan <list>','no instance <id>','show pending']+common
        if self.mode=='dhcp':
            return ['network <network> <mask>','default-router <IPv4>','dns-server <IPv4>','lease <days> <hours> <minutes>']+common
        if self.mode=='vlan':
            return ['name <VLAN-name>']+common
        if self.mode in ('if','range'):
            commands=['description <text>','shutdown','no shutdown']
            commands+=['switchport mode access','switchport mode trunk','switchport mode dynamic auto','switchport mode dynamic desirable','switchport access vlan <id>','switchport trunk allowed vlan <list>','switchport trunk native vlan <id>','switchport nonegotiate','switchport port-security','spanning-tree portfast','spanning-tree bpduguard enable','spanning-tree cost <number>','channel-group <id> mode active','channel-group <id> mode passive','ip dhcp snooping trust','ip arp inspection trust','ip verify source','authentication port-control auto','authentication port-control force-authorized','dot1x pae authenticator'] if self.n.kind=='Switch' else ['encapsulation dot1Q <VLAN>','ip address <IPv4> <mask>','no ip address']
            return commands+['do '+s for s in shows]+common
        return ['aaa new-model','aaa authentication dot1x default group radius','dot1x system-auth-control','ip igmp snooping','no ip igmp snooping','ip igmp snooping unknown-multicast action drop','hostname <name>','vlan <id>','no vlan <id>','interface <interface>','interface range <range>','spanning-tree mode mst','spanning-tree mode rapid-pvst','spanning-tree mst configuration','spanning-tree mst <id> priority <number>','spanning-tree vlan <id> priority <number>','vtp mode server','vtp mode client','vtp mode transparent','vtp domain <name>','vtp version 2','ip dhcp snooping','ip dhcp snooping vlan <list>','ip arp inspection vlan <list>','ip dhcp pool <name>','ip dhcp excluded-address <first> <last>']+['do '+s for s in shows]+common

    def context_help(self,prefix=''):
        prefix=prefix.strip()
        try:
            prefix=self.normalize_command(prefix).lower() if prefix else ''
        except ValueError as e:
            return '% '+str(e)
        patterns=self.help_patterns()
        if prefix.startswith('show'):
            patterns=CLIEditing.help_patterns_for_show(self)
        selected=[p for p in patterns if p.lower().startswith(prefix)]
        return '\n'.join('  '+p for p in selected) or '% No matching supported commands. Use show capabilities for limitations.'

    @staticmethod
    def help_patterns_for_show(session):
        saved=session.mode
        session.mode='priv'
        try:
            return [p for p in session.help_patterns() if p.startswith('show')]
        finally:
            session.mode=saved

    def completion_candidates(self,value):
        typed=value.lower().split()
        results=[]
        patterns=self.help_patterns()
        if typed and ('show'.startswith(typed[0]) or typed[0]=='sh'):
            patterns=self.help_patterns_for_show(self)
        for pattern in patterns:
            literal=pattern.split(' <',1)[0]
            words=literal.split()
            if len(typed)<=len(words) and all(b.startswith(a) or (a=='int' and b=='interfaces') or (a=='run' and b=='running-config') for a,b in zip(typed,words)):
                results.append(literal+(' ' if '<' in pattern else ''))
        return sorted(set(results))
