"""Ephemeral mutual-TLS lifecycle fixtures with exact DNS SANs and roles."""
from pathlib import Path
import subprocess
from test_native_syslog_tls_integration import certificates


def lifecycle_certificates(folder):
    root=Path(folder);authority,wrong,leaves=certificates(root)
    def openssl(*args):subprocess.run(['openssl',*map(str,args)],check=True,capture_output=True,timeout=15)
    config=root/'issuer.cnf';(root/'index').touch();(root/'serial').write_text('01\n');(root/'issued').mkdir()
    config.write_text('[ca]\ndefault_ca=issuer\n[issuer]\ndatabase='+str(root/'index')+
        '\nserial='+str(root/'serial')+'\nnew_certs_dir='+str(root/'issued')+
        '\ndefault_md=sha256\nunique_subject=no\npolicy=subject\n[subject]\ncommonName=supplied\n')
    for name in ('collector.lab','sender.lab'):
        for version in ('renewed','expired','future'):
            label=version+'-'+name;cert=root/(label+'.pem');key=leaves[name][1];csr=root/(name+'.csr')
            if version=='renewed':
                key=root/(label+'.key');csr=root/(label+'.csr')
                openssl('req','-new','-newkey','rsa:2048','-nodes','-subj','/CN='+name,'-keyout',key,'-out',csr)
                openssl('x509','-req','-in',csr,'-CA',authority,'-CAkey',root/'LabCA.key','-CAcreateserial',
                    '-days','1','-extfile',root/(name+'.ext'),'-out',cert);key.chmod(0o600)
            else:
                year='2000' if version=='expired' else '2099'
                ext=root/(label+'.ext');ext.write_text('[peer]\n'+(root/(name+'.ext')).read_text())
                openssl('ca','-batch','-notext','-config',config,'-cert',authority,'-keyfile',root/'LabCA.key',
                    '-in',csr,'-extfile',ext,'-extensions','peer','-out',cert,'-startdate',year+'0101000000Z','-enddate',year+'0102000000Z')
            leaves[label]=(cert,key)
    return authority,wrong,leaves
