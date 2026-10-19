"""Declarative text labs and atomic CLI import. Never executes host shell commands."""
from dataclasses import dataclass
import copy
import re
import shlex
from .engine import Lab,Node,port_name,vlan_list
from .cli import Session
from .profiles import PROFILES

@dataclass
class Issue:
    line: int
    section: str
    message: str

    def __str__(self):
        return f'Ligne {self.line} [{self.section}] : {self.message}'

class LabTextError(ValueError):
    def __init__(self,issues):
        self.issues=issues
        super().__init__('\n'.join(map(str,issues)))

@dataclass
class ImportResult:
    lab: Lab
    commands: int
    warnings: list

    @property
    def summary(self):
        return f'{len(self.lab.nodes)} équipements • {len(self.lab.links)} câbles • {self.commands} commandes validées'

KINDS={'pc':'PC','switch':'Switch','routeur':'Routeur','router':'Routeur'}
PROMPT=re.compile(r'^[A-Za-z0-9_-]+(?:\([^)]*\))?[#>]\s*(.*)$')

def split_document(text):
    sections=[]; current=None; issues=[]
    for number,raw in enumerate(text.lstrip('\ufeff').splitlines(),1):
        line=raw.strip()
        if not line or line.startswith(('#','!',';')):
            continue
        if line.startswith('[') and line.endswith(']'):
            heading=line[1:-1].strip()
            if heading.lower() in ('devices','links','radius'):
                kind,target=heading.lower(),None
            elif heading.lower().startswith('config '):
                kind,target='config',heading.split(maxsplit=1)[1].strip()
            else:
                issues.append(Issue(number,heading,'Section inconnue : devices, links, radius ou config NOM.'))
                current=None; continue
            current=(kind,target,number,[]); sections.append(current)
        elif current is None:
            issues.append(Issue(number,'document','Déclarer une section [devices], [links] ou [config NOM].'))
        else:
            current[3].append((number,line))
    return sections,issues


def apply_commands(lab,target,lines,issues,deferred,section_line=1):
    if target not in lab.nodes:
        issues.append(Issue(lines[0][0] if lines else section_line,'config '+target,'Équipement non déclaré.'))
        return 0
    session=Session(lab,target)
    session.mode='config' if lab.nodes[target].kind!='PC' else 'user'
    count=0
    for number,line in lines:
        match=PROMPT.fullmatch(line)
        if match:
            line=match[1]
        if not line:
            continue
        low=line.lower()
        # Wrappers are accepted as well as configuration-only bodies.
        if lab.nodes[target].kind!='PC':
            if low in ('enable','en'):
                session.mode='priv'; continue
            if re.fullmatch(r'conf(?:igure)?\s+t(?:erminal)?',low):
                session.mode='config'; continue
        if lab.nodes[target].kind=='PC' and (low in ('ip dhcp','ipconfig /renew') or low.startswith(('dot1x login ','igmp join '))):
            deferred.append((number,target,line)); count+=1; continue
        result=session.execute(line)
        if result.startswith('%'):
            issues.append(Issue(number,'config '+target,result))
            break
        count+=1
    # A raw running-config file need not include its final `end`.
    if session.mode=='mst':
        session.commit_mst()
    return count


def parse_lab(text):
    sections,issues=split_document(text)
    if not sections and not issues:
        issues.append(Issue(1,'document','Document vide.'))
    lab=Lab(); lab.defer_protocols=True
    command_count=0; deferred=[]
    for kind,_,heading,lines in sections:
        if kind!='devices':
            continue
        for number,line in lines:
            try:
                parts=shlex.split(line,comments=True)
                if len(parts) not in (2,4):
                    raise ValueError('Format : NOM TYPE [X Y]. Types : PC, Switch, Routeur.')
                name,kind_name=parts[:2]
                if not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,31}',name):
                    raise ValueError('Nom : lettre puis lettres/chiffres/_/-, 32 caractères maximum.')
                profile=PROFILES.get(kind_name.lower())
                if kind_name.lower() not in KINDS and not (profile and profile.creatable):
                    raise ValueError('Type inconnu : '+kind_name)
                index=len(lab.nodes)
                x,y=(map(int,parts[2:]) if len(parts)==4 else (150+(index%4)*240,120+(index//4)*180))
                if not -100000<=x<=100000 or not -100000<=y<=100000:
                    raise ValueError('Position hors limites.')
                lab.add(Node(name,profile.kind if profile else KINDS[kind_name.lower()],x,y,profile=profile.id if profile else ''))
            except ValueError as e:
                issues.append(Issue(number,'devices',str(e)))
    for kind,_,heading,lines in sections:
        if kind=='radius':
            for number,line in lines:
                try:
                    parts=shlex.split(line,comments=True)
                    if len(parts)!=2:
                        raise ValueError('Format : utilisateur "mot de passe".')
                    if not hasattr(lab,'radius_users'):
                        raise ValueError('RADIUS stub non disponible dans cette version.')
                    if parts[0] in lab.radius_users:
                        raise ValueError('Utilisateur RADIUS dupliqué.')
                    lab.radius_users[parts[0]]=parts[1]
                except ValueError as e:
                    issues.append(Issue(number,'radius',str(e)))
        if kind!='links':
            continue
        for number,line in lines:
            try:
                parts=shlex.split(line,comments=True)
                if len(parts) not in (2,4,5):
                    raise ValueError('Format : NODE:PORT NODE:PORT [access|trunk VLANs] [down].')
                a,ap=parts[0].rsplit(':',1); b,bp=parts[1].rsplit(':',1)
                mode,vlans=(parts[2].lower(),vlan_list(parts[3])) if len(parts)>=4 else ('access',[1])
                if len(parts)==5 and parts[4].lower()!='down':
                    raise ValueError('Option de câble inconnue : '+parts[4])
                lab.connect(a,b,mode,vlans,port_name(ap),port_name(bp),enabled=len(parts)!=5,configure=len(parts)>=4)
            except (ValueError,KeyError) as e:
                issues.append(Issue(number,'links',str(e)))
    for kind,target,heading,lines in sections:
        if kind=='config':
            command_count+=apply_commands(lab,target,lines,issues,deferred,heading)
    lab.defer_protocols=False
    if not issues:
        lab.sync_vtp()
        for number,target,line in deferred:
            session=Session(lab,target)
            result=session.execute(line)
            if result.startswith('%'):
                issues.append(Issue(number,'config '+target,result))
    if issues:
        raise LabTextError(issues)
    warnings=[]
    if not lab.nodes:
        raise LabTextError([Issue(1,'devices','Aucun équipement déclaré.')])
    if not lab.links:
        warnings.append('Aucun câble déclaré.')
    return ImportResult(lab,command_count,warnings)


def import_device_config(text,lab,target):
    if target not in lab.nodes:
        raise LabTextError([Issue(1,'config','Choisir un équipement existant.')])
    candidate=copy.deepcopy(lab); candidate.defer_protocols=True
    lines=[(n,line.strip()) for n,line in enumerate(text.lstrip('\ufeff').splitlines(),1) if line.strip() and not line.lstrip().startswith(('!','#',';'))]
    issues=[]; deferred=[]
    count=apply_commands(candidate,target,lines,issues,deferred)
    candidate.defer_protocols=False
    if not issues:
        candidate.sync_vtp()
        for number,node,line in deferred:
            result=Session(candidate,node).execute(line)
            if result.startswith('%'):
                issues.append(Issue(number,'config '+node,result))
    if issues:
        raise LabTextError(issues)
    return ImportResult(candidate,count,[])


def export_lab(lab):
    output=['# Network LABS text format v1', '# Export de la configuration courante ; pas un fichier IOS multi-vendeur.', '[devices]']
    for n in lab.nodes.values():
        output.append(f'{n.name} {n.profile} {n.x} {n.y}')
    output.extend(['','[links]'])
    for link in lab.links:
        output.append(f'{link.a}:{link.a_port} {link.b}:{link.b_port}'+(' access 1 down' if not link.enabled else ''))
    if getattr(lab,'radius_users',{}):
        output.extend(['','[radius]'])
        output.extend(shlex.quote(user)+' '+shlex.quote(password) for user,password in lab.radius_users.items())
    for n in lab.nodes.values():
        output.extend(['',f'[config {n.name}]'])
        if n.kind=='PC':
            if n.hostname:
                output.append('hostname '+n.hostname)
            if n.dns_service:
                output.append('service dns')
            output.extend(f'dns record {name} {address}' for name,address in sorted(n.dns_records.items()))
            if n.dot1x_user:
                output.append('dot1x login '+shlex.quote(n.dot1x_user)+' '+shlex.quote(n.dot1x_password))
            if getattr(n,'address_mode','static')=='dhcp':
                output.append('ip dhcp')
            elif n.address:
                output.append('ip address '+n.address)
                if n.gateway:
                    output.append('ip gateway '+n.gateway)
                if n.dns:
                    output.append('ip dns '+' '.join(n.dns))
            output.extend('igmp join '+group for group in n.groups)
            if n.ports['eth0'].shutdown:
                # Canonical helper is independent of the selected OS profile.
                output.append('ip link down')
        else:
            config=Session(lab,n.name).running_config().splitlines()
            # VTP clients cannot create VLANs; restore the database before enabling client mode.
            config=[line for line in config if not line.startswith('vtp mode ')]
            if n.kind=='Switch':
                config.insert(0,'vtp mode transparent')
                if config and config[-1]=='end':
                    config.pop()
                config.extend(['vtp mode '+n.vtp_mode,'end'])
            output.extend(config)
    return '\n'.join(output)+'\n'
