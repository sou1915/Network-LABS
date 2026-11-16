"""Native campus template matching the user's reference layout (Linux roles)."""
from pathlib import Path
from .spec import validate


def campus_example(rootfs,name='Campus-entreprise'):
    rootfs=str(Path(rootfs).resolve())
    def node(name,role,interfaces,**extra):return dict(name=name,role=role,runtime='oci',rootfs=rootfs,interfaces=interfaces,**extra)
    trunk=lambda vids:dict(mode='trunk',native_vlan=1,allowed=[1,*vids])
    access=lambda vid:dict(mode='access',vlan=vid)
    nodes=[
        node('R1','router',{'eth0':'10.0.0.1/30','eth1':'','eth2':''},forwarding=True,
             subinterfaces={f'{port}.{vid}':dict(parent=port,vlan=vid,address=f'192.168.{vid}.1/24') for port,vid in [('eth1',10),('eth2',20),('eth2',30)]},
             routes=[dict(destination='172.16.0.0/24',gateway='10.0.0.2',interface='eth0')]),
        node('FW1','firewall',{'eth0':'10.0.0.2/30','eth1':'172.16.0.1/24'},forwarding=True,gateway='10.0.0.1',
             firewall=dict(default='drop',stateful=True,rules=[])),
        node('SW1','switch',{'eth0':'','eth1':'','eth2':''},vlans=[1,10],switchports={'eth0':trunk([10]),'eth1':access(10),'eth2':access(10)}),
        node('SW2','switch',{'eth0':'','eth1':'','eth2':'','eth3':''},vlans=[1,20,30],switchports={'eth0':trunk([20,30]),'eth1':access(20),'eth2':access(20),'eth3':access(30)}),
    ]
    for i,vid in [(1,10),(2,10),(3,20),(4,20),(5,30)]:
        nodes.append(node(f'PC{i}','host',{'eth0':f'192.168.{vid}.{10 if i%2 else 11}/24'},gateway=f'192.168.{vid}.1'))
    nodes.append(node('SRV1','host',{'eth0':'172.16.0.10/24'},gateway='172.16.0.1'))
    links=[[['R1','eth0'],['FW1','eth0']],[['R1','eth1'],['SW1','eth0']],[['R1','eth2'],['SW2','eth0']],
           [['SW1','eth1'],['PC1','eth0']],[['SW1','eth2'],['PC2','eth0']],
           [['SW2','eth1'],['PC3','eth0']],[['SW2','eth2'],['PC4','eth0']],[['SW2','eth3'],['PC5','eth0']],
           [['FW1','eth1'],['SRV1','eth0']]]
    return validate(dict(version=1,name=name,nodes=nodes,links=links))
