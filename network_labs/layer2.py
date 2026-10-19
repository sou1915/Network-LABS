"""Converged single-region MST and VTP v2 advertisement model."""
class Layer2:
    @staticmethod
    def same_region(a,b):
        return a.mst_name==b.mst_name and a.mst_revision==b.mst_revision and a.mst_map==b.mst_map

    def boundary_reason(self,link):
        a,b=self.nodes[link.a],self.nodes[link.b]
        if a.kind!='Switch' or b.kind!='Switch':
            return ''
        if (a.stp_mode=='mst') != (b.stp_mode=='mst') or (a.stp_mode=='mst' and not self.same_region(a,b)):
            return 'MST boundary: multi-region / PVST interworking not modeled (link blocked conservatively).'
        if a.stp_mode=='mst' and (self.operational_mode(link,link.a)!='trunk' or self.operational_mode(link,link.b)!='trunk'):
            return 'MST inter-switch links must be trunks in this model.'
        return ''

    def tree_link_eligible(self,link,vlan):
        a,b=self.nodes[link.a],self.nodes[link.b]
        if a.stp_mode!='mst' or b.stp_mode!='mst':
            return self.eligible(link,vlan)
        pa,pb=self.ends(link)
        if pa.bpduguard:
            pa.errdisabled=True
        if pb.bpduguard:
            pb.errdisabled=True
        return bool(link.enabled and not self.boundary_reason(link) and not any(p.shutdown or p.errdisabled for p in (pa,pb)) and self.channel_state(link)[0] and self.operational_mode(link,link.a)=='trunk' and self.operational_mode(link,link.b)=='trunk')

    def vlan_changed(self,name):
        node=self.nodes[name]
        if node.vtp_mode=='server':
            node.vtp_revision+=1
        self.sync_vtp()

    def sync_vtp(self):
        """Instant modeled advertisements over live trunks; no real VTP packets."""
        servers=sorted((n for n in self.nodes.values() if n.kind=='Switch' and n.vtp_mode=='server' and n.vtp_domain),key=lambda n:(-n.vtp_revision,n.name))
        for server in servers:
            seen=set(); stack=[server.name]
            while stack:
                current=stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                node=self.nodes[current]
                if node.vtp_mode=='off':
                    continue
                if node.vtp_mode!='transparent':
                    if node.vtp_domain!=server.vtp_domain or node.vtp_password!=server.vtp_password or node.vtp_version!=server.vtp_version:
                        continue
                    if node.vtp_revision<server.vtp_revision:
                        node.vlans={**{v:n for v,n in node.vlans.items() if int(v)>1005},**{v:n for v,n in server.vlans.items() if int(v)<=1005}}
                        node.vtp_revision=server.vtp_revision
                for link in self.links:
                    if current not in (link.a,link.b) or not link.enabled:
                        continue
                    other=link.b if current==link.a else link.a
                    if self.nodes[other].kind!='Switch' or self.nodes[other].vtp_mode=='off':
                        continue
                    pa,pb=self.ends(link)
                    if any(p.shutdown or p.errdisabled for p in (pa,pb)) or not self.channel_state(link)[0]:
                        continue
                    if self.operational_mode(link,current)=='trunk' and self.operational_mode(link,other)=='trunk':
                        stack.append(other)
