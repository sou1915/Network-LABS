"""The package (pyproject.toml) ships every file the application reads, and its two commands exist."""
from pathlib import Path
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackagingTest(unittest.TestCase):
    def setUp(self):
        self.project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))

    def test_every_data_file_is_in_the_package(self):
        shipped = set()
        for package, patterns in self.project['tool']['setuptools']['package-data'].items():
            folder = ROOT.joinpath(*package.split('.'))
            for pattern in patterns:
                shipped.update(path for path in folder.glob(pattern) if path.is_file())
        needed = {path for path in (ROOT / 'network_labs').rglob('*')
                  if path.is_file() and path.suffix not in ('.py', '.pyc') and '__pycache__' not in path.parts}
        self.assertEqual(sorted(str(path.relative_to(ROOT)) for path in needed - shipped), [])

    def test_commands_and_licence(self):
        project = self.project['project']
        self.assertEqual(project['scripts'], {'network-labs': 'network_labs.__main__:main',
                                              'network-labs-lab': 'network_labs.appliances.__main__:main'})
        self.assertEqual(project['license'], 'GPL-3.0-or-later')
        self.assertEqual(project['dependencies'], [])  # the standard library only
        for name in project['license-files']:
            self.assertTrue((ROOT / name).is_file(), name)
        self.assertIn('GNU GENERAL PUBLIC LICENSE', (ROOT / 'LICENSE').read_text(encoding='utf-8')[:200])


if __name__ == '__main__':
    unittest.main()
