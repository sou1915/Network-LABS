"""First launch: check this computer, fetch the pinned micro-VM pieces, build one guest disk, remember the paths.

prepare() never asks for privileges. It checks for KVM, Firecracker and the image tools. It can download
the pinned official Firecracker release and guest kernel, verified by SHA-256 before use. It builds one
guest disk with everything the labs and scenarios use (guest agent, iptables for firewalls, BIRD for
OSPF), and saves the kernel and disk paths the workbench offers. Anything that needs root (installing
Firecracker under /usr/local/bin, system packages) is printed as the exact command to run.
"""
import hashlib
import io
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request

FIRECRACKER = {'version': 'v1.10.1',
               'url': 'https://github.com/firecracker-microvm/firecracker/releases/download/v1.10.1/firecracker-v1.10.1-x86_64.tgz',
               'sha256': '36112969952b0e34fadcfca769d48a55dc22cbba99af17e02bd0e24fc35adc77',
               'members': {'release-v1.10.1-x86_64/firecracker-v1.10.1-x86_64': 'firecracker',
                           'release-v1.10.1-x86_64/jailer-v1.10.1-x86_64': 'jailer'}}
KERNEL = {'name': 'vmlinux-5.10.223',
          'url': 'https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.10/x86_64/vmlinux-5.10.223',
          'sha256': '22847375721aceea63d934c28f2dfce4670b6f52ec904fae19f5145a970c1e65'}
# The Network LABS guest kernel (Firecracker's CI kernel plus 802.1Q, bonding and macvlan), published with its source by
# .github/workflows/guest-kernel-release.yml (release guest-kernel-5.10.223-nl1, booted on KVM with VLAN switches, routers
# and hosts before it was published). setup downloads it instead of Firecracker's kernel: VLAN labs work without
# building anything. A new build gets a new release tag and its own SHA-256 here.
GUEST_KERNEL = {'name': 'vmlinux-5.10.223-network-labs',
                'url': 'https://github.com/sou1915/Network-LABS/releases/download/guest-kernel-5.10.223-nl1/vmlinux-5.10.223-network-labs',
                'sha256': '32547911df87852c5570310649b450cc7adb9fd139764a1073eaf8b4653b94b2'}
IMAGE = 'guest-full.ext4'
IMAGE_MIB = 128
IMAGE_LABEL = 'Disque des micro-VM (agent, iptables, BIRD, FRR, keepalived, dnsmasq, chrony)'
# chrony also becomes this machine's own NTP client (in place of systemd-timesyncd, as on Ubuntu 25.10); keepalived's
# service starts only with a configuration of its own; dnsmasq-base is the program alone, without a service.
PACKAGES = 'busybox-static e2fsprogs gcc libc6-dev iptables bird2 frr keepalived dnsmasq-base chrony'
TOOLS = {'busybox': 'busybox', 'mke2fs': 'mke2fs', 'debugfs': 'debugfs', 'gcc': 'gcc',
         'iptables (legacy)': ('xtables-legacy-multi', 'iptables-legacy'), 'bird': 'bird', 'birdc': 'birdc',
         'FRR zebra': '/usr/lib/frr/zebra', 'FRR bgpd': '/usr/lib/frr/bgpd', 'vtysh': 'vtysh',
         'keepalived': '/usr/sbin/keepalived', 'dnsmasq': '/usr/sbin/dnsmasq', 'chronyd': '/usr/sbin/chronyd',
         'chronyc': '/usr/bin/chronyc'}


def data_dir():
    base = os.environ.get('XDG_DATA_HOME') or str(Path.home() / '.local' / 'share')
    return Path(base) / 'network-labs'


def _which(names):
    for name in (names,) if isinstance(names, str) else names:
        if name.startswith('/'):
            if Path(name).is_file():
                return name
            continue
        found = shutil.which(name) or next((str(Path(d) / name) for d in ('/usr/sbin', '/sbin') if (Path(d) / name).is_file()), None)
        if found:
            return found
    return None


def _sha256(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _download(url, sha256, limit=256 * 1024 * 1024):
    """The verified bytes of URL; ValueError if the checksum differs (nothing is kept)."""
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Téléchargement trop volumineux : ' + url)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError('Somme SHA-256 inattendue pour ' + url + ' : fichier refusé.')
    return data


def _write(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        stream.write(data)
    os.chmod(stream.name, mode)
    os.replace(stream.name, path)


def fetch_firecracker(folder, fetch=_download):
    """Firecracker and jailer from the pinned release, into FOLDER/bin; returns the folder."""
    archive = fetch(FIRECRACKER['url'], FIRECRACKER['sha256'])
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
        for member, name in FIRECRACKER['members'].items():
            entry = tar.getmember(member)  # only the two known files are read, by exact name
            if not entry.isfile():
                raise ValueError('Archive Firecracker inattendue.')
            _write(Path(folder) / 'bin' / name, tar.extractfile(entry).read(), 0o755)
    return Path(folder) / 'bin'


def kernel_release():
    """The kernel setup downloads: the Network LABS one once its checksum is pinned, else Firecracker's."""
    return GUEST_KERNEL if GUEST_KERNEL['sha256'] else KERNEL


def fetch_kernel(folder, fetch=_download):
    release = kernel_release()
    target = Path(folder) / release['name']
    _write(target, fetch(release['url'], release['sha256']))
    return target


def image_stamp():
    """What the guest disk was built from: the agent source and this builder (a change means rebuild)."""
    here = Path(__file__).parent
    sources = sorted((here / 'guest').glob('*.c')) + [here / 'guest_image.py', Path(__file__)]  # agent.c and its parts
    return hashlib.sha256(b''.join(path.read_bytes() for path in sources)).hexdigest()[:16]


def build_image(folder, tools):
    """One guest disk with the agent, iptables, BIRD, FRR, keepalived, dnsmasq and chrony, replaced atomically when the
    agent changed."""
    from .guest_image import build
    folder = Path(folder)
    target, stamp = folder / IMAGE, folder / (IMAGE + '.stamp')
    if target.is_file() and stamp.is_file() and stamp.read_text().strip() == image_stamp():
        return target, False
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder, prefix='.build-') as work:
        fresh = Path(work) / IMAGE
        build(tools['busybox'], fresh, size_mib=IMAGE_MIB, mke2fs=tools['mke2fs'], debugfs=tools['debugfs'], with_agent=True,
              cc=tools['gcc'], with_firewall=True, iptables=tools['iptables (legacy)'], with_routing=True, bird=tools['bird'],
              birdc=tools['birdc'], with_services=True,
              services={name: tools[name] for name in ('keepalived', 'dnsmasq', 'chronyd', 'chronyc')})
        os.replace(fresh, target)
    stamp.write_text(image_stamp() + '\n')
    return target, True


def prepare(download=False, kernel=None, rebuild=False, folder=None, fetch=_download):
    """Check and prepare this computer: {'steps': [{id, title, ok, detail, fix}], 'kernel', 'disk', 'ready'}."""
    folder = Path(folder) if folder else data_dir()
    steps = []

    def step(key, title, ok, detail, fix=''):
        steps.append({'id': key, 'title': title, 'ok': bool(ok), 'detail': detail, 'fix': '' if ok else fix})
        return ok

    kvm = Path('/dev/kvm').exists()
    step('kvm', 'Virtualisation KVM', kvm, '/dev/kvm présent' if kvm else '/dev/kvm absent',
         'Activer la virtualisation (Intel VT-x / AMD-V) dans le BIOS, ou utiliser une machine Linux qui expose /dev/kvm.')

    firecracker = _which('firecracker')
    note = ''
    if not firecracker and download:
        try:
            staged = fetch_firecracker(folder, fetch)
            note = f'téléchargé et vérifié dans {staged}'
        except (OSError, ValueError, KeyError, tarfile.TarError) as error:
            note = f'téléchargement impossible : {error}'
    staged = folder / 'bin' / 'firecracker'
    install = f'sudo install {folder}/bin/firecracker {folder}/bin/jailer /usr/local/bin/'
    step('firecracker', f'Firecracker {FIRECRACKER["version"]}', firecracker,
         firecracker or note or 'absent du PATH',
         install if staged.is_file() else 'Relancer avec --download, puis : ' + install)

    tools = {label: _which(names) for label, names in TOOLS.items()}
    missing = [label for label, path in tools.items() if not path]
    step('tools', 'Outils de construction du disque', not missing,
         'tous présents' if not missing else 'manquants : ' + ', '.join(missing), f'sudo apt install {PACKAGES}')

    release = kernel_release()
    kernel = Path(kernel) if kernel else (Path(os.environ['NETWORK_LABS_MICROVM_KERNEL'])
                                          if os.environ.get('NETWORK_LABS_MICROVM_KERNEL') else folder / release['name'])
    note = ''
    if not kernel.is_file() and download and kernel == folder / release['name']:
        try:
            fetch_kernel(folder, fetch)
            note = 'téléchargé et vérifié'
        except (OSError, ValueError) as error:
            note = f'téléchargement impossible : {error}'
    publisher = 'Network LABS, avec VLAN 802.1Q' if release is GUEST_KERNEL else 'officiel Firecracker'
    step('kernel', 'Noyau des micro-VM', kernel.is_file(), f'{kernel}' + (f' ({note})' if note else ''),
         f'Relancer avec --download (noyau {publisher}, vérifié), ou indiquer --kernel CHEMIN.')
    if release is not GUEST_KERNEL:
        step('vlan-kernel', 'Noyau Network LABS (VLAN 802.1Q, facultatif)', True,
             'Pour les scénarios campus/VLAN : tools/guest_kernel/build.sh construit un noyau avec 802.1Q.')

    disk = folder / IMAGE
    if not missing:
        try:
            if rebuild and disk.is_file():
                (folder / (IMAGE + '.stamp')).unlink(missing_ok=True)
            disk, built = build_image(folder, tools)
            step('image', IMAGE_LABEL, True, f'{disk} ({"construit" if built else "à jour"})')
        except (OSError, ValueError) as error:
            step('image', IMAGE_LABEL, False, str(error), f'sudo apt install {PACKAGES}')
    else:
        step('image', IMAGE_LABEL, False, 'outils manquants', f'sudo apt install {PACKAGES}')

    ready = all(s['ok'] for s in steps)
    if kernel.is_file() and disk.is_file():
        from .progress import remember_paths
        remember_paths(str(kernel), str(disk))
    return {'steps': steps, 'kernel': str(kernel), 'disk': str(disk), 'ready': ready}


def report(result):
    """The checklist as text for a terminal."""
    lines = []
    for item in result['steps']:
        lines.append(f'{"✔" if item["ok"] else "✖"} {item["title"]} — {item["detail"]}')
        if item['fix']:
            lines.append(f'    → {item["fix"]}')
    lines.append('')
    lines.append('Prêt : les labs micro-VM et les scénarios peuvent démarrer.' if result['ready'] else
                 'Pas encore prêt : suivre les → ci-dessus, puis relancer « setup ».')
    lines.append(f'Noyau : {result["kernel"]}')
    lines.append(f'Disque : {result["disk"]}')
    return '\n'.join(lines)
