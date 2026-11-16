"""Owned native-only IPv6 HTTP/TLS/SNTP endpoints; not managed guest services."""
SERVICES=r'''
import json,select,socket,ssl,struct,sys,time
address,cert,key,mode=sys.argv[1:]
ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.minimum_version=ssl.TLSVersion.TLSv1_2;ctx.load_cert_chain(cert,key)
listeners=[]
for port in (80,443):
 s=socket.socket(socket.AF_INET6,socket.SOCK_STREAM);s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind((address,port));s.listen(8);listeners.append(s)
u=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM);u.bind((address,123));listeners.append(u)
def stamp():
 n=time.time()+2208988800;return struct.pack('!II',int(n)%(2**32),int((n-int(n))*(2**32)))
print(json.dumps({'ready':True}),flush=True)
while True:
 for s in select.select(listeners,[],[],1)[0]:
  if s is u:
   q,peer=u.recvfrom(1024)
   if len(q)!=48:continue
   t=stamp();origin=q[40:48] if open(mode).read().strip()!='bad' else bytes(8)
   u.sendto(b'\x24\x02'+bytes(22)+origin+t+stamp(),peer)
  else:
   c,_=s.accept();c.settimeout(2)
   try:
    if s.getsockname()[1]==443:c=ctx.wrap_socket(c,server_side=True)
    with c:
     data=b''
     while b'\r\n\r\n' not in data and len(data)<4096:
      p=c.recv(512)
      if not p:break
      data+=p
     if not data:continue
     path=data.split(b' ')[1];status=b'404 Not Found' if path==b'/missing' else b'302 Found' if path==b'/redirect' else b'200 OK'
     c.sendall(b'HTTP/1.0 '+status+b'\r\nLocation: /\r\nConnection: close\r\n\r\n')
   except (OSError,ValueError):c.close()
'''
