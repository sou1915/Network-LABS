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


def lifecycle_identities(folder):
    """Offline signed validity/purpose controls plus a new leaf and key."""
    root=Path(folder);result=identities(root)
    def openssl(*args):subprocess.run(['openssl',*map(str,args)],check=True,capture_output=True,timeout=15)
    database=root/'index';database.touch();(root/'serial').write_text('01\n')
    issued=root/'issued';issued.mkdir()
    config=root/'issuer.cnf'
    config.write_text('[ca]\ndefault_ca=issuer\n[issuer]\n'+
        'database='+str(database)+'\nserial='+str(root/'serial')+'\nnew_certs_dir='+str(issued)+
        '\ndefault_md=sha256\nunique_subject=no\npolicy=subject\n[subject]\ncommonName=supplied\n')
    for name,start,end,purpose in (
            ('expired','20000101000000Z','20000102000000Z','serverAuth'),
            ('future','20990101000000Z','20990102000000Z','serverAuth'),
            ('client-only',None,None,'clientAuth')):
        ext=root/(name+'.ext');ext.write_text('[server]\nsubjectAltName=IP:192.0.2.10,DNS:https.lab\n'+
            'basicConstraints=critical,CA:FALSE\nextendedKeyUsage='+purpose+'\nkeyUsage=critical,digitalSignature,keyEncipherment\n')
        cert=root/(name+'.pem')
        dates=['-startdate',start,'-enddate',end] if start else ['-days','1']
        openssl('ca','-batch','-notext','-config',config,'-cert',result['ca'],'-keyfile',root/'HTTPS-CA.key',
                '-in',root/'valid.csr','-extfile',ext,'-extensions','server','-out',cert,*dates)
        result[name+'_cert']=cert;result[name+'_key']=result['valid_key']
    key=root/'renewed.key';csr=root/'renewed.csr';cert=root/'renewed.pem'
    openssl('req','-new','-newkey','rsa:2048','-nodes','-subj','/CN=https.lab','-keyout',key,'-out',csr)
    openssl('x509','-req','-in',csr,'-CA',result['ca'],'-CAkey',root/'HTTPS-CA.key','-CAcreateserial',
            '-days','1','-extfile',root/'valid.ext','-out',cert)
    key.chmod(0o600);result['renewed_cert']=cert;result['renewed_key']=key
    return result
