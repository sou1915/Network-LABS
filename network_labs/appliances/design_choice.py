"""The saved choice of design (classic, studio or mono) and the one asked for by the environment. Kept apart from design.py,
which fixes the design when it loads: the launcher reads the saved choice here, then sets the environment, before the
workbench's modules (and design.py) load."""
import json
import os
from pathlib import Path

DESIGNS = ('classic', 'studio', 'mono')
SETTINGS = Path.home() / '.config' / 'network-labs' / 'ui.json'


def asked():
    """The design NETWORK_LABS_DESIGN asks for, or None."""
    wanted = os.environ.get('NETWORK_LABS_DESIGN', '').strip().lower()
    return wanted if wanted in DESIGNS else None


def chosen():
    """The design asked for (environment first, then the saved setting), or None when nothing was asked."""
    if asked():
        return asked()
    try:
        saved = json.loads(SETTINGS.read_text(encoding='utf-8')).get('design')
    except (OSError, ValueError, AttributeError):
        return None
    return saved if saved in DESIGNS else None


def save_choice(design):
    """Remember DESIGN for the next start (and for a restart: the environment wins over the file)."""
    if design not in DESIGNS:
        raise ValueError(f'design inconnu : {design}')
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    try:
        settings = json.loads(SETTINGS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        settings = {}
    settings = settings if isinstance(settings, dict) else {}
    settings['design'] = design
    SETTINGS.write_text(json.dumps(settings, indent=2) + '\n', encoding='utf-8')
    os.environ['NETWORK_LABS_DESIGN'] = design
