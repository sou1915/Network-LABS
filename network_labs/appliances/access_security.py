"""Small static access-VLAN template for existing LAN security management."""
from pathlib import Path
from .spec import validate


def access_security_example(rootfs,name='Access-security'):
    rootfs=str(Path(rootfs).resolve())
    clients=[('PC1','10.10.0.10/24','11'),('PC2','10.10.0.20/24','22'),('PC3','10.10.0.30/24','33'),('SRV1','10.10.0.1/24','44')]
    nodes=[{'name':name,'role':'host','runtime':'oci','rootfs':rootfs,'interfaces':{'eth0':address},'interface_macs':{'eth0':'02:00:00:00:10:'+mac}} for name,address,mac in clients]
    nodes.append({'name':'SW1','role':'switch','runtime':'oci','rootfs':rootfs,'interfaces':{'eth'+str(i):'' for i in range(4)},'vlans':[10],'switchports':{'eth'+str(i):{'mode':'access','vlan':10} for i in range(4)}})
    return validate({'version':2,'name':name,'nodes':nodes,'links':[[[client,'eth0'],['SW1','eth'+str(i)]] for i,(client,_,_) in enumerate(clients)]})
