"""Rebuild the optional guest artifact with Cargo; never modifies host networking."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path

root=Path(__file__).resolve().parents[2]
guest=Path(__file__).with_name('guest')
cargo=shutil.which('cargo')
if not cargo:raise SystemExit('Cargo is required to rebuild the guest. See docs/MICRO_APPLIANCES.md.')
env=os.environ.copy()
cargo_home=Path(env.get('CARGO_HOME',str(Path.home()/'.cargo'))).resolve()
flags=['-C','link-arg=-zstack-size=65536','--remap-path-prefix='+str(cargo_home)+'=/cargo','--remap-path-prefix='+str(root)+'=/network-labs']
env['CARGO_ENCODED_RUSTFLAGS']='\x1f'.join(flags)
subprocess.run([cargo,'build','--release','--locked'],cwd=guest,env=env,check=True)
artifact=root/'network_labs/micro_appliances/device.wasm'
shutil.copyfile(guest/'target/wasm32-unknown-unknown/release/network_labs_micro_device.wasm',artifact)
digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
artifact.with_suffix('.wasm.sha256').write_text(digest+'  device.wasm\n')
inputs=['guest/src/lib.rs','guest/Cargo.toml','guest/Cargo.lock','guest/.cargo/config.toml','build_guest.py']
manifest={'abi':1,'target':'wasm32-unknown-unknown','rustc':subprocess.check_output(['rustc','--version'],text=True).strip(),
          'smoltcp':'0.14.0','artifact_sha256':digest,
          'inputs':{name:hashlib.sha256((guest.parent/name).read_bytes()).hexdigest() for name in inputs}}
artifact.with_name('build.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Built',artifact.name,artifact.stat().st_size,'bytes;',digest)
