"""Device drawings: the pre-rendered PNGs exist for every role and size, and the vector drawing stands in without them."""
import os
import unittest
from unittest.mock import patch

from network_labs.appliances import workspace_art


class DeviceArtFilesTest(unittest.TestCase):
    def test_every_role_has_every_size(self):
        for name in ('router', 'switch', 'firewall', 'host-blue', 'host-red', 'server'):
            for scale in workspace_art.ART_SCALES:
                with self.subTest(name=name, scale=scale):
                    self.assertTrue((workspace_art.DEVICE_ART / f'{name}@{round(scale * 100)}.png').is_file())

    def test_ports_spread_across_the_chassis(self):
        node = {'interfaces': {f'eth{i}': '' for i in range(4)}}
        offsets = [workspace_art.port_offset(node, f'eth{i}') for i in range(4)]
        self.assertEqual(offsets, sorted(offsets))
        self.assertAlmostEqual(offsets[0], -offsets[-1])
        self.assertGreaterEqual(offsets[-1] - offsets[0], 50)


@unittest.skipUnless(os.environ.get('DISPLAY'), 'GUI requires X display')
class DeviceArtCanvasTest(unittest.TestCase):
    def test_png_drawing_picks_the_nearest_size_and_falls_back_to_vectors(self):
        import tkinter as tk
        root = tk.Tk()
        try:
            canvas = tk.Canvas(root)
            item = workspace_art.draw_device(canvas, 'router', 50, 50, zoom=1.4)
            self.assertEqual(canvas.type(item), 'image')
            image = workspace_art.device_image(canvas, 'router', 'blue', 1.4)
            self.assertEqual((image.width(), image.height()), (round(128 * 1.45), round(80 * 1.45)))
            with patch.object(workspace_art, 'DEVICE_ART', workspace_art.DEVICE_ART / 'missing'):
                canvas.__dict__.pop('_device_images', None)
                before = len(canvas.find_all())
                workspace_art.draw_device(canvas, 'switch', 50, 50)
                self.assertGreater(len(canvas.find_all()) - before, 10)
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
