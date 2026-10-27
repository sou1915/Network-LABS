import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from network_labs.appliances.manifests import list_manifests, render
from network_labs.appliances.spec import example
from network_labs.appliances.__main__ import main


class NativeManifestTests(unittest.TestCase):
    def test_valid_invalid_symlinks_and_private_content(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); data = json.dumps(example('/rootfs'))
            (root / 'my lab.json').write_text(data)
            (root / 'bad.json').write_text('{"private":"do-not-expose-this"}')
            (root / 'alias.json').symlink_to(root / 'my lab.json')
            (root / 'noise.txt').write_text(data)
            report = list_manifests(root); text = render(report)
            self.assertEqual([r['file'] for r in report['files']], ['alias.json', 'bad.json', 'my lab.json'])
            self.assertEqual([r['status'] for r in report['files']], ['unavailable_or_invalid', 'unavailable_or_invalid', 'valid_manifest'])
            self.assertEqual(report['files'][2]['name'], 'micro-lan')
            self.assertIn("start './my lab.json'", text)
            self.assertNotIn('do-not-expose-this', text)
            self.assertIn('ne vérifie pas', text)

    def test_special_names_cannot_inject_terminal_or_option(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); data = json.dumps(example('/rootfs'))
            (root / '-name.json').write_text(data)
            (root / 'escape\x1b[31m.json').write_text(data)
            text = render(list_manifests(root))
            self.assertIn('start ./-name.json', text)
            self.assertNotIn('\x1b', text)
            self.assertIn('Nom non imprimable', text)

    def test_empty_directory_and_cli_error_guidance(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('pathlib.Path.cwd', return_value=Path(folder)), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['manifests', '--json']), 0)
            self.assertEqual(json.loads(output.getvalue())['files'], [])
            with redirect_stderr(io.StringIO()) as error:
                self.assertEqual(main(['start', str(Path(folder) / 'missing.json')]), 1)
            self.assertIn('appliances manifests', error.getvalue())
            self.assertNotIn('CHEMIN_MANIFEST', error.getvalue())
