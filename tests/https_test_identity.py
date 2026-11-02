"""Ephemeral certificates; no private material is checked into the repository."""
from pathlib import Path
import subprocess


def identities(folder, *, valid_ip='192.0.2.10', valid_name='https.lab'):
    root=Path(folder)
    def openssl(*args):subprocess.run(['openssl',*map(str,args)],check=True,capture_output=True,timeout=15)
    def ca(name):
        cert=root/(name+'.pem');key=root/(name+'.key')
        openssl('req','-x509','-newkey','rsa:2048','-nodes','-days','2','-subj','/CN='+name,'-addext','basicConstraints=critical,CA:TRUE','-keyout',key,'-out',cert)
        return cert,key
    authority,authority_key=ca('HTTPS-CA');wrong,_=ca('Other-CA');result={'ca':authority,'wrong_ca':wrong}
    for name,ip,dns in (('valid',valid_ip,valid_name),('wrong','192.0.2.99','wrong.lab')):
        cert=root/(name+'.pem');key=root/(name+'.key');csr=root/(name+'.csr');ext=root/(name+'.ext')
        openssl('req','-new','-newkey','rsa:2048','-nodes','-subj','/CN='+dns,'-keyout',key,'-out',csr)
        ext.write_text('subjectAltName=IP:'+ip+',DNS:'+dns+'\nbasicConstraints=critical,CA:FALSE\nextendedKeyUsage=serverAuth\nkeyUsage=critical,digitalSignature,keyEncipherment\n')
        openssl('x509','-req','-in',csr,'-CA',authority,'-CAkey',authority_key,'-CAcreateserial','-days','1','-extfile',ext,'-out',cert)
        key.chmod(0o600);result[name+'_cert']=cert;result[name+'_key']=key
    return result
