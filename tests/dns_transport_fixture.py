"""Controlled wire replies for transport tests; not a production DNS service."""
import socket
import struct


def response(query, mode='answer', truncated=False):
    ident=struct.unpack('!H',query[:2])[0]
    if mode=='bad-id':ident^=1
    question=query[12:]
    if mode=='bad-question':question=question.replace(b'web',b'bad',1)
    flags=0x8380 if truncated else 0x8180
    answer=b'\xc0\x0c'+struct.pack('!HHIH',1,1,60,4)+socket.inet_aton('203.0.113.66' if truncated else '203.0.113.10')
    return struct.pack('!6H',ident,flags,1,1,0,0)+question+answer


WORKER=r'''import json,select,socket,struct,sys,time
address,mode=sys.argv[1:]
u=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);t=socket.socket();t.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
u.bind((address,53))
if mode!='refused':t.bind((address,53));t.listen(4)
print(json.dumps({'ready':True}),flush=True)
def answer(q,tc=False):
 ident=struct.unpack('!H',q[:2])[0]^(1 if mode=='bad-id' else 0);question=q[12:]
 if mode=='bad-question':question=question.replace(b'web',b'bad',1)
 a=b'\xc0\x0c'+struct.pack('!HHIH',1,1,60,4)+socket.inet_aton('203.0.113.66' if tc else '203.0.113.10')
 return struct.pack('!6H',ident,0x8380 if tc else 0x8180,1,1,0,0)+question+a
while True:
 for s in select.select([u] if mode=='refused' else [u,t],[],[],1)[0]:
  if s is u:
   q,peer=u.recvfrom(4096);u.sendto(answer(q,True),peer)
  else:
   c,_=t.accept()
   with c:
    c.settimeout(2)
    def exact(n):
     v=b''
     while len(v)<n:
      p=c.recv(n-len(v))
      if not p:raise ValueError('short query')
      v+=p
     return v
    try:
     q=exact(struct.unpack('!H',exact(2))[0]);p=answer(q)
     if mode=='large':c.sendall(struct.pack('!H',5000));continue
     if mode=='short':c.sendall(struct.pack('!H',len(p))+p[:-1]);continue
     payload=struct.pack('!H',len(p))+p
     for i in range(0,len(payload),3):c.sendall(payload[i:i+3]);time.sleep(.001)
    except (OSError,ValueError):pass
'''
