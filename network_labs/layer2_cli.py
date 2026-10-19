"""CLI for modeled VTP v2 and single-region MST."""
import copy
import re
from .engine import vlan_list

class Layer2Commands:
    def commit_mst(self):
        pending=self.mst_pending
        self.n.mst_name=pending['name']; self.n.mst_revision=pending['revision']; self.n.mst_map=pending['map']
        self.changed=True

    def layer2_command(self,low,line):
        if self.n.kind!='Switch':
            return None
        if low in ('no vtp domain','no vtp password'):
            if low=='no vtp domain':
                self.n.vtp_domain=''; self.n.vtp_revision=0
            else:
                self.n.vtp_password=''
            self.lab.sync_vtp(); self.changed=True; return ''
        if low.startswith('vtp '):
            parts=line.split(maxsplit=2)
            if len(parts)!=3:
                raise ValueError('Incomplete command. vtp mode|domain|password|version <value>')
            command,value=parts[1].lower(),parts[2]
            if command=='mode':
                value=value.lower()
                if value not in ('server','client','transparent','off'):
                    raise ValueError('VTP mode: server, client, transparent, off.')
                self.n.vtp_mode=value
            elif command=='domain':
                if not 1<=len(value)<=32:
                    raise ValueError('VTP domain: 1..32 caractères.')
                if self.n.vtp_domain!=value:
                    self.n.vtp_revision=0
                self.n.vtp_domain=value
            elif command=='password':
                if not 1<=len(value)<=32:
                    raise ValueError('VTP password: 1..32 caractères.')
                self.n.vtp_password=value
            elif command=='version':
                if value!='2':
                    raise ValueError('Only VTP v2 is modeled.')
                self.n.vtp_version=2
            else:
                raise ValueError('VTP command not implemented.')
            self.lab.sync_vtp(); self.changed=True
            return ''
        if low=='spanning-tree mst configuration':
            self.mst_pending={'name':self.n.mst_name,'revision':self.n.mst_revision,'map':copy.deepcopy(self.n.mst_map)}
            self.mode='mst'; return ''
        if self.mode=='mst':
            if low.startswith('name '):
                name=line[5:]
                if not 1<=len(name)<=32:
                    raise ValueError('MST name: 1..32 caractères.')
                self.mst_pending['name']=name
            elif low.startswith('revision '):
                revision=int(low.split()[-1])
                if not 0<=revision<=65535:
                    raise ValueError('MST revision: 0..65535.')
                self.mst_pending['revision']=revision
            else:
                match=re.fullmatch(r'(no )?instance (\d+)(?: vlan ([\d,-]+))?',low)
                if not match:
                    raise ValueError('MST: name, revision, instance <0..4094> vlan <liste>, exit.')
                instance=int(match[2])
                if not 0<=instance<=4094 or (not match[1] and not match[3]):
                    raise ValueError('Invalid MST instance/mapping.')
                mapping=self.mst_pending['map']
                if match[1]:
                    ids=vlan_list(match[3]) if match[3] else [int(v) for v,i in mapping.items() if i==instance]
                    for v in ids:
                        if mapping.get(str(v))==instance:
                            mapping.pop(str(v),None)
                else:
                    for v in vlan_list(match[3]):
                        if instance==0:
                            mapping.pop(str(v),None)
                        else:
                            mapping[str(v)]=instance
            return ''  # Pending configuration commits on exit/end.
        if low=='spanning-tree mode mst':
            self.n.stp_mode='mst'; self.changed=True; return ''
        match=re.fullmatch(r'spanning-tree mst (\d+) (priority (\d+)|root (primary|secondary))',low)
        if match:
            instance=int(match[1]); value=int(match[3]) if match[3] else 24576 if match[4]=='primary' else 28672
            if not 0<=instance<=4094 or not 0<=value<=61440 or value%4096:
                raise ValueError('Invalid MST instance/priority.')
            if match[4]=='primary':
                lowest=min((int(n.priorities.get('mst:'+str(instance),32768)) for n in self.lab.nodes.values() if n.kind=='Switch'),default=32768)
                value=min(24576,max(0,lowest-4096))
            self.n.priorities['mst:'+str(instance)]=value
            self.changed=True; return ''
        return None

    def layer2_show(self,low):
        if low=='show vtp status':
            return f'VTP Version capable: 2 (modeled)\nVTP Operating Mode: {self.n.vtp_mode}\nVTP Domain Name: {self.n.vtp_domain or "<none>"}\nConfiguration Revision: {self.n.vtp_revision}\nNumber of existing VLANs: {len(self.n.vlans)}\nAdvertisements calculated over trunks; no VTP frames/timers.'
        if low=='show pending' and self.mode=='mst':
            return 'Pending MST configuration:\n'+self.format_mst(self.mst_pending)
        if low=='show spanning-tree mst configuration':
            return self.format_mst({'name':self.n.mst_name,'revision':self.n.mst_revision,'map':self.n.mst_map})
        match=re.fullmatch(r'show spanning-tree mst(?: (\d+))?',low)
        if match or (low=='show spanning-tree' and self.n.stp_mode=='mst'):
            if self.n.stp_mode!='mst':
                raise ValueError('MST is not enabled on this switch.')
            ids=[int(match[1])] if match and match[1] else sorted({0,*self.n.mst_map.values()})
            output=[]
            for instance in ids:
                vlan=next((v for v in range(1,4095) if self.n.mst_map.get(str(v),0)==instance),None)
                if vlan is None:
                    continue
                info=self.lab.stp(vlan).get(self.node)
                if not info:
                    continue
                output.append(f'MST{instance} / Region {self.n.mst_name or "<unnamed>"}\nRoot: {info["root"]}  Cost: {info["cost"]}')
                output.extend(f'{p:12} {role:5} {state:5}' for p,(role,state) in info['ports'].items())
            return '\n'.join(output)+'\nSingle-region converged model. Boundary/CIST interworking is not implemented.'
        return None

    @staticmethod
    def format_mst(config):
        lines=[f'Name: {config["name"] or "<unnamed>"}',f'Revision: {config["revision"]}']
        for instance in sorted(set(config['map'].values())):
            lines.append(f'Instance {instance}: VLANs '+','.join(sorted((v for v,i in config['map'].items() if i==instance),key=int)))
        lines.append('Unmapped VLANs: instance 0')
        return '\n'.join(lines)
