"""Copies the Linux desktops' own icons, fonts and wallpapers into network_labs/appliances/assets/linux, from the Ubuntu 24.04
packages that ship them (each package's copyright file goes beside its files):

    apt-get download yaru-theme-icon adwaita-icon-theme fonts-ubuntu fonts-cantarell ubuntu-wallpapers gnome-backgrounds \\
        nautilus-data gnome-control-center-data gnome-text-editor epiphany-browser-data gnome-console
    for f in *.deb; do mkdir -p x/${f%%_*} && dpkg-deb -x $f x/${f%%_*}; done
    python3 tools/build_linux_assets.py x

Ubuntu's desktop is Yaru (icons CC BY-SA 4.0, Ubuntu Sans fonts); Debian's, Fedora's and Rocky's is GNOME's Adwaita (icons
CC BY-SA 3.0 or LGPL 3, Cantarell). Files are copied unchanged except the wallpapers, resized to 1920 pixels wide."""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'network_labs' / 'appliances' / 'assets' / 'linux'

SYMBOLIC = ['network-wired-symbolic', 'network-wired-disconnected-symbolic', 'audio-volume-high-symbolic', 'system-shutdown-symbolic',
            'view-app-grid-symbolic', 'go-previous-symbolic', 'go-next-symbolic', 'window-close-symbolic', 'window-minimize-symbolic',
            'window-maximize-symbolic', 'open-menu-symbolic', 'edit-find-symbolic', 'emblem-system-symbolic', 'system-lock-screen-symbolic',
            'camera-photo-symbolic', 'night-light-symbolic', 'power-profile-balanced-symbolic', 'weather-clear-night-symbolic',
    'list-add-symbolic',
            'user-home-symbolic', 'user-trash-symbolic', 'user-desktop-symbolic', 'folder-documents-symbolic', 'folder-download-symbolic',
            'folder-music-symbolic', 'folder-pictures-symbolic', 'folder-videos-symbolic', 'document-open-recent-symbolic',
    'starred-symbolic',
            'preferences-system-symbolic']
PLACES = ['folder', 'user-home', 'user-desktop', 'user-trash', 'folder-documents', 'folder-download', 'folder-music', 'folder-pictures',
          'folder-videos', 'folder-templates', 'folder-publicshare', 'network-workgroup']
# GNOME Settings' sidebar: its own symbolic icons (Yaru draws its own for Ubuntu).
PANELS = ['network', 'bluetooth', 'display', 'sound', 'power', 'multitasking', 'appearance', 'applications', 'notifications', 'search',
          'online-accounts', 'sharing', 'mouse', 'keyboard', 'color', 'printers', 'accessibility', 'privacy', 'system']
YARU_APPS = ['org.gnome.Nautilus', 'org.gnome.Settings', 'org.gnome.Terminal', 'org.gnome.TextEditor', 'org.gnome.Epiphany']
GNOME_APPS = {'org.gnome.Nautilus': 'nautilus-data', 'org.gnome.Settings': 'gnome-control-center-data',
              'org.gnome.Console': 'gnome-console',
              'org.gnome.TextEditor': 'gnome-text-editor', 'org.gnome.Epiphany': 'epiphany-browser-data'}


def find(base, name):
    found = sorted(base.rglob(name))
    if not found:
        raise SystemExit(f'{name} not found under {base}')
    return found[0]


def copyright_of(packages, package, target):
    shutil.copyfile(find(packages / package / 'usr/share/doc', 'copyright'), target)


def main(packages):
    if OUT.exists():
        shutil.rmtree(OUT)
    yaru, adwaita, fonts, walls = (OUT / name for name in ('yaru', 'adwaita', 'fonts', 'walls'))
    for folder in (yaru, adwaita, fonts, walls):
        folder.mkdir(parents=True)
    theme = packages / 'yaru-theme-icon/usr/share/icons/Yaru'
    for name in SYMBOLIC:
        shutil.copyfile(find(theme / 'scalable', name + '.svg'), yaru / (name + '.svg'))
    for name in PLACES:
        shutil.copyfile(theme / '48x48@2x/places' / (name + '.png'), yaru / (name + '.png'))
    for name in YARU_APPS:
        shutil.copyfile(theme / '48x48@2x/apps' / (name + '.png'), yaru / (name + '.png'))
    settings = packages / 'gnome-control-center-data/usr/share/icons/hicolor/scalable/apps'
    for name in PANELS:
        own = theme / 'scalable/org.gnome.Settings' / f'org.gnome.Settings-{name}-symbolic.svg'
        shutil.copyfile(own if own.exists() else settings / f'org.gnome.Settings-{name}-symbolic.svg', yaru / f'panel-{name}-symbolic.svg')
    copyright_of(packages, 'yaru-theme-icon', yaru / 'COPYRIGHT.txt')
    copyright_of(packages, 'gnome-control-center-data', yaru / 'COPYRIGHT-gnome-control-center-data.txt')
    theme = packages / 'adwaita-icon-theme/usr/share/icons/Adwaita'
    for name in SYMBOLIC:
        shutil.copyfile(find(theme, name + '.svg'), adwaita / (name + '.svg'))
    for name in PLACES:
        shutil.copyfile(theme / 'scalable/places' / (name + '.svg'), adwaita / (name + '.svg'))
    copyright_of(packages, 'adwaita-icon-theme', adwaita / 'COPYRIGHT.txt')
    for name in PANELS:
        shutil.copyfile(settings / f'org.gnome.Settings-{name}-symbolic.svg', adwaita / f'panel-{name}-symbolic.svg')
    for name, package in GNOME_APPS.items():
        shutil.copyfile(find(packages / package, name + '.svg'), adwaita / (name + '.svg'))
        copyright_of(packages, package, adwaita / f'COPYRIGHT-{package}.txt')
    ubuntu_fonts = packages / 'fonts-ubuntu/usr/share/fonts/truetype/ubuntu'
    shutil.copyfile(ubuntu_fonts / 'UbuntuSans[wdth,wght].ttf', fonts / 'UbuntuSans.ttf')
    shutil.copyfile(ubuntu_fonts / 'UbuntuSansMono[wght].ttf', fonts / 'UbuntuSansMono.ttf')
    copyright_of(packages, 'fonts-ubuntu', fonts / 'COPYRIGHT-fonts-ubuntu.txt')
    for weight in ('Regular', 'Bold'):
        shutil.copyfile(find(packages / 'fonts-cantarell', f'Cantarell-{weight}.otf'), fonts / f'Cantarell-{weight}.otf')
    copyright_of(packages, 'fonts-cantarell', fonts / 'COPYRIGHT-fonts-cantarell.txt')
    from PIL import Image
    for source, package, target in ((packages / 'ubuntu-wallpapers/usr/share/backgrounds/warty-final-ubuntu.png', 'ubuntu-wallpapers',
                                     'ubuntu.jpg'),
                                    (packages / 'gnome-backgrounds/usr/share/backgrounds/gnome/adwaita-l.jpg', 'gnome-backgrounds',
                                     'gnome.jpg')):
        image = Image.open(source).convert('RGB')
        image = image.resize((1920, round(image.height * 1920 / image.width)), Image.LANCZOS)
        image.save(walls / target, quality=86, optimize=True, progressive=True)
        copyright_of(packages, package, walls / f'COPYRIGHT-{package}.txt')
    total = sum(f.stat().st_size for f in OUT.rglob('*') if f.is_file())
    print(f'{OUT.relative_to(ROOT)}: {sum(1 for f in OUT.rglob("*") if f.is_file())} files, {total // 1024} KiB')


if __name__ == '__main__':
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path('x'))
