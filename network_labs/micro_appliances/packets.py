"""Read-only packet decoding for the explainer; never answers/constructs traffic."""
from ipaddress import IPv4Address
import struct

def checksum(data):
    if len(data) % 2:data += b'\0'
    value = sum(struct.unpack('!'+str(len(data)//2)+'H',data))
    while value >> 16:value = (value & 65535) + (value >> 16)
    return (~value) & 65535

def describe(frame):
    out={'time_ms':frame.time_ms,'source':frame.source,'port':frame.source_port,
         'destination':frame.destination,'destination_port':frame.destination_port,'length':len(frame.data)}
    packet=frame.data
    if len(packet)<14:return {**out,'protocol':'Truncated Ethernet'}
    out.update(source_mac=packet[6:12].hex(':'),destination_mac=packet[:6].hex(':'))
    kind=int.from_bytes(packet[12:14],'big')
    if kind==0x0806 and len(packet)>=42:
        op=int.from_bytes(packet[20:22],'big')
        out.update(protocol='ARP',operation='request' if op==1 else 'reply' if op==2 else str(op),source_ip=str(IPv4Address(packet[28:32])),destination_ip=str(IPv4Address(packet[38:42])))
        out['explanation']=f"ARP {out['operation']} : {out['source_ip']} → {out['destination_ip']}."
    elif kind==0x0800 and len(packet)>=34:
        ihl=(packet[14]&15)*4;total=int.from_bytes(packet[16:18],'big');start=14+ihl
        if ihl<20 or len(packet)<14+total:return {**out,'protocol':'Truncated IPv4'}
        payload=packet[start:14+total];proto=packet[23]
        out.update(source_ip=str(IPv4Address(packet[26:30])),destination_ip=str(IPv4Address(packet[30:34])),ip_checksum_ok=checksum(packet[14:start])==0)
        if proto==1 and len(payload)>=8:
            out.update(protocol='ICMP',operation={8:'echo request',0:'echo reply'}.get(payload[0],str(payload[0])),checksum_ok=checksum(payload)==0,payload=payload[8:].hex())
            out['explanation']=f"ICMP {out['operation']} : {out['source_ip']} → {out['destination_ip']}."
        elif proto==6 and len(payload)>=20:
            source_port,destination_port=struct.unpack('!HH',payload[:4]);flags=payload[13]
            header=(payload[12]>>4)*4;data=payload[header:]
            names=[name for mask,name in [(2,'SYN'),(16,'ACK'),(8,'PSH'),(1,'FIN'),(4,'RST')] if flags&mask]
            pseudo=packet[26:34]+b'\0\x06'+len(payload).to_bytes(2,'big')
            out.update(protocol='TCP',flags=names,source_port=source_port,destination_port=destination_port,checksum_ok=checksum(pseudo+payload)==0,payload=data.hex())
            out['explanation']=f"TCP {'+'.join(names)} {source_port} → {destination_port}"+(f' : {len(data)} octets de données.' if data else '.')
        else:out['protocol']='IPv4/'+str(proto)
    else:out['protocol']='Ethernet/'+hex(kind)
    return out
