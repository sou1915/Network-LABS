"""Loopback-only management pages. HTTP threads queue all model access to Tk's thread."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,urlencode
import json,secrets,threading,queue,webbrowser
from .web_api import DeviceAPI,Conflict

class WebPortal:
    def __init__(self,app):
        self.app=app;self.api=DeviceAPI(app);self.token=secrets.token_urlsafe(32)
        self.jobs=queue.Queue();self.closed=False;self.job=None
        portal=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def respond(self,status,data,kind='application/json; charset=utf-8'):
                raw=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
                self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)))
                self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer')
                self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY')
                self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                self.end_headers()
                try:self.wfile.write(raw)
                except (BrokenPipeError,ConnectionResetError):pass
            def allowed_host(self):
                return self.headers.get('Host')==portal.host
            def authenticated(self):
                return secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+portal.token)
            def do_GET(self):
                if not self.allowed_host():return self.respond(403,{'error':'Host refusé.'})
                parsed=urlsplit(self.path)
                if parsed.path=='/':
                    return self.respond(200,Path(__file__).with_name('device_web.html').read_bytes(),'text/html; charset=utf-8')
                if parsed.path in ('/device_faces.css','/device_faces.js','/fortios_policy.js','/fortios_policy.css'):
                    kind='text/css' if parsed.path.endswith('.css') else 'text/javascript'
                    return self.respond(200,Path(__file__).with_name(parsed.path[1:]).read_bytes(),kind+'; charset=utf-8')
                if parsed.path=='/favicon.ico':return self.respond(204,b'','image/x-icon')
                if parsed.path!='/api/state':return self.respond(404,{'error':'Page absente.'})
                if not self.authenticated():return self.respond(401,{'error':'Session locale absente ou expirée.'})
                node=parse_qs(parsed.query).get('node',[''])[0]
                status,data=portal.submit('state',{'node':node});self.respond(status,data)
            def do_POST(self):
                if not self.allowed_host() or self.headers.get('Origin',portal.origin)!=portal.origin:
                    return self.respond(403,{'error':'Origine refusée.'})
                if not self.authenticated():return self.respond(401,{'error':'Session locale absente ou expirée.'})
                parsed=urlsplit(self.path)
                if parsed.path not in ('/api/apply','/api/native','/api/test','/api/cli'):return self.respond(404,{'error':'Action absente.'})
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=262144:return self.respond(413,{'error':'Requête trop volumineuse.'})
                    if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('JSON requis.')
                    data=json.loads(self.rfile.read(length))
                    if not isinstance(data,dict):raise ValueError('Objet JSON requis.')
                except (ValueError,UnicodeError) as error:return self.respond(400,{'error':str(error)})
                status,data=portal.submit(parsed.path.rsplit('/',1)[1],data);self.respond(status,data)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.host='127.0.0.1:'+str(self.server.server_port);self.origin='http://'+self.host
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.1},daemon=True);self.thread.start()
        self.job=app.root.after(20,self.poll)

    def url(self,node,page='overview'):return self.origin+'/#'+urlencode({'node':node,'token':self.token,'page':page})
    def open(self,node,page='overview'):
        url=self.url(node,page)
        threading.Thread(target=webbrowser.open,args=(url,),daemon=True).start()
        return url
    def submit(self,action,data):
        if self.closed:return 503,{'error':'Le logiciel a été fermé.'}
        job={'action':action,'data':data,'ready':threading.Event(),'cancelled':False}
        self.jobs.put(job)
        if not job['ready'].wait(8):
            job['cancelled']=True;return 503,{'error':'Le logiciel ne répond pas. Réessayer après actualisation.'}
        return job['result']
    def poll(self):
        self.job=None
        for _ in range(12):
            try:job=self.jobs.get_nowait()
            except queue.Empty:break
            if job['cancelled']:continue
            try:result=(200,self.api.dispatch(job['action'],job['data']))
            except Conflict as error:result=(409,{'error':str(error)})
            except (ValueError,KeyError,TypeError) as error:result=(400,{'error':str(error)})
            except Exception:result=(500,{'error':'Erreur interne du simulateur.'})
            job['result']=result;job['ready'].set()
        if not self.closed:self.job=self.app.root.after(20,self.poll)
    def close(self):
        if self.closed:return
        self.closed=True
        if self.job is not None:self.app.root.after_cancel(self.job);self.job=None
        while True:
            try:job=self.jobs.get_nowait()
            except queue.Empty:break
            job['result']=(503,{'error':'Le logiciel a été fermé.'});job['ready'].set()
        self.server.shutdown();self.server.server_close()
