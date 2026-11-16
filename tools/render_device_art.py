"""Render the workbench's device drawings as antialiased PNGs (developer tool; needs Pillow).

Each device is drawn at 8x on a 128x80 logical box centred on the device origin, then downsampled, at
every size in SCALES. The app loads the PNGs with Tk alone and falls back to its vector drawing when
they are missing. The drawings are generic and unbranded.

Usage: python3 tools/render_device_art.py [OUTPUT_DIR]   (default: network_labs/appliances/assets/devices)
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

BOX = (128, 80)
SCALES = (0.5, 0.65, 0.8, 1.0, 1.2, 1.45, 1.75)
K = 8  # supersampling factor
OUT = Path(__file__).resolve().parents[1] / 'network_labs' / 'appliances' / 'assets' / 'devices'

CHASSIS = {
    # top face, front top, front bottom, side, outline, badge, emblem
    'router': ('#5d8db0', '#2c5f82', '#122c40', '#0c2131', '#0a1a26', '#163a55', '#ffffff'),
    'switch': ('#f6f9fb', '#e6edf3', '#b4c3d0', '#8e9fae', '#6f7f8d', '#2f86d6', '#ffffff'),
    'firewall': ('#7a6064', '#4b3438', '#241719', '#1b1112', '#140c0d', '#2a1a1c', '#ff6a3d'),
}


def rgb(value, alpha=255):
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5)) + (alpha,)


def mix(a, b, t):
    return '#' + ''.join(f'{round(int(a[i:i + 2], 16) + (int(b[i:i + 2], 16) - int(a[i:i + 2], 16)) * t):02x}' for i in (1, 3, 5))


class Canvas:
    def __init__(self, scale):
        self.s = scale * K
        self.size = (round(BOX[0] * self.s), round(BOX[1] * self.s))
        self.image = Image.new('RGBA', self.size, (0, 0, 0, 0))

    def p(self, x, y):
        return ((x + BOX[0] / 2) * self.s, (y + BOX[1] / 2) * self.s)

    def box(self, a, b, d, e):
        return [*self.p(a, b), *self.p(d, e)]

    def layer(self):
        return Image.new('RGBA', self.size, (0, 0, 0, 0))

    def paste(self, layer, blur=0):
        if blur:
            layer = layer.filter(ImageFilter.GaussianBlur(blur * self.s))
        self.image = Image.alpha_composite(self.image, layer)

    def shape(self, draw_mask, fill=None, gradient=None, outline=None, width=0.6):
        """Fill a shape drawn by draw_mask(ImageDraw, fill) with a colour or a vertical gradient (top, bottom, y0, y1)."""
        mask = Image.new('L', self.size, 0)
        draw_mask(ImageDraw.Draw(mask), 255)
        if gradient:
            top, bottom, y0, y1 = gradient
            ramp = Image.new('RGBA', self.size)
            line = ImageDraw.Draw(ramp)
            start, end = self.p(0, y0)[1], self.p(0, y1)[1]
            for row in range(self.size[1]):
                t = min(1, max(0, (row - start) / max(1, end - start)))
                line.line([(0, row), (self.size[0], row)], fill=rgb(mix(top, bottom, t)))
            layer = self.layer()
            layer.paste(ramp, (0, 0), mask)
        else:
            layer = Image.new('RGBA', self.size, rgb(fill) if isinstance(fill, str) else fill)
            empty = self.layer()
            layer = Image.composite(layer, empty, mask)
        self.paste(layer)
        if outline:
            edge = self.layer()
            draw_mask(ImageDraw.Draw(edge), None, outline=rgb(outline), width=max(1, round(width * self.s)))
            self.paste(edge)

    def rounded(self, a, b, d, e, radius, **kw):
        self.shape(lambda draw, fill, **o: draw.rounded_rectangle(self.box(a, b, d, e), radius * self.s, fill=fill, **o), **kw)

    def polygon(self, points, **kw):
        flat = [self.p(x, y) for x, y in points]
        self.shape(lambda draw, fill, **o: draw.polygon(flat, fill=fill, **o), **kw)

    def ellipse(self, a, b, d, e, **kw):
        self.shape(lambda draw, fill, **o: draw.ellipse(self.box(a, b, d, e), fill=fill, **o), **kw)

    def line(self, points, colour, width, alpha=255):
        layer = self.layer()
        ImageDraw.Draw(layer).line([self.p(x, y) for x, y in points], fill=rgb(colour, alpha), width=max(1, round(width * self.s)),
                                   joint='curve')
        self.paste(layer)

    def shadow(self, a, b, d, e, alpha=70):
        layer = self.layer()
        ImageDraw.Draw(layer).ellipse(self.box(a, b, d, e), fill=(20, 40, 60, alpha))
        self.paste(layer, blur=2.2)

    def led(self, x, y, colour, radius=1.3):
        glow = self.layer()
        halo = radius * 2.4
        ImageDraw.Draw(glow).ellipse(self.box(x - halo, y - halo, x + halo, y + halo), fill=rgb(colour, 110))
        self.paste(glow, blur=1.1)
        self.ellipse(x - radius, y - radius, x + radius, y + radius, fill=colour)
        self.ellipse(x - radius * .45, y - radius * .7, x + radius * .2, y - radius * .05, fill=(255, 255, 255, 150))

    def arrow(self, x0, y0, x1, y1, colour, width=1.5, head=3.2):
        import math
        angle = math.atan2(y1 - y0, x1 - x0)
        back = (x1 - head * math.cos(angle), y1 - head * math.sin(angle))
        self.line([(x0, y0), back], colour, width)
        left = (back[0] + head * .65 * math.sin(angle), back[1] - head * .65 * math.cos(angle))
        right = (back[0] - head * .65 * math.sin(angle), back[1] + head * .65 * math.cos(angle))
        self.polygon([(x1, y1), left, right], fill=colour)

    def result(self, scale):
        target = (round(BOX[0] * scale), round(BOX[1] * scale))
        return self.image.resize(target, Image.LANCZOS)


def chassis(c, role):
    top, front_top, front_bottom, side, edge, badge, emblem = CHASSIS[role]
    c.shadow(-58, 13, 64, 27, alpha=80)
    c.polygon([(-55, -13), (-45, -23), (49, -23), (59, -13)], gradient=(mix(top, '#ffffff', .25), top, -23, -13), outline=edge, width=.5)
    c.line([(-43, -21.6), (47, -21.6)], '#ffffff', .5, alpha=90)
    c.polygon([(55, -13), (59, -13), (61, -16.5), (61, 12), (59, 16), (55, 16)], gradient=(mix(side, '#ffffff', .15), side, -16, 16),
              outline=edge, width=.5)
    c.rounded(-55, -13, 56, 17, 2.2, gradient=(front_top, front_bottom, -13, 17), outline=edge, width=.6)
    c.line([(-53.5, -11.9), (54.5, -11.9)], '#ffffff', .45, alpha=110)
    c.rounded(-54, 13.4, 55, 16.6, 1.2, fill=rgb(mix(front_bottom, '#000000', .35)))
    # Mounting ears with screws.
    for x in (-52.6, 52.6):
        c.ellipse(x - 1.1, -9.6, x + 1.1, -7.4, fill=rgb(mix(front_bottom, '#ffffff', .35)))
        c.ellipse(x - 1.1, 6.4, x + 1.1, 8.6, fill=rgb(mix(front_bottom, '#ffffff', .35)))
    # Role badge.
    c.ellipse(-48.6, -10.2, -30.4, 8, gradient=(mix(badge, '#ffffff', .25), mix(badge, '#000000', .2), -10, 8),
              outline=mix(badge, '#000000', .35) if role == 'switch' else '#3aa0e8' if role == 'router' else '#ff6a3d', width=.7)
    cx, cy = -39.5, -1.1
    if role == 'router':
        for dx, dy in ((0, -5.6), (0, 5.6), (-5.6, 0), (5.6, 0)):
            c.arrow(cx + dx * .25, cy + dy * .25, cx + dx, cy + dy, emblem, width=1.2, head=2.6)
    elif role == 'switch':
        c.arrow(cx - 5.5, cy - 2.4, cx + 5.5, cy - 2.4, emblem, width=1.2, head=2.6)
        c.arrow(cx + 5.5, cy + 2.4, cx - 5.5, cy + 2.4, emblem, width=1.2, head=2.6)
    else:
        for row in range(4):
            offset = 0 if row % 2 == 0 else 2.2
            for col in range(3):
                bx = cx - 6.2 + offset + col * 4.4
                if bx + 3.8 <= cx + 6.4:
                    c.rounded(bx, cy - 6 + row * 3.1, bx + 3.8, cy - 3.6 + row * 3.1, .4, fill=emblem)
    # Ports.
    if role == 'switch':
        for row in range(2):
            for index in range(12):
                px, py = -25 + index * 5.6 + (index // 6) * 1.6, -9 + row * 9.5
                c.rounded(px, py, px + 4.4, py + 5.6, .5, fill='#18232d', outline='#4e5f6c', width=.35)
                c.rounded(px + .9, py + .9, px + 3.5, py + 2.6, .2, fill='#2e3d49')
                c.led(px + 2.2, py - 1.5 if row == 0 else py + 7.2, '#35d07f' if (index * 7 + row) % 5 else '#f2b134', radius=.55)
        for index in range(2):
            px = 46.4
            py = -9 + index * 9.5
            c.rounded(px - 6, py, px + 0.4, py + 5.2, .5, fill='#2a3743', outline='#a7b7c4', width=.35)
    else:
        count = 4 if role == 'firewall' else 6
        for index in range(count):
            px = -24 + index * 8.6
            c.rounded(px, -8.4, px + 6.4, 0.6, .7, fill='#0b1218', outline=mix(front_top, '#ffffff', .35), width=.4)
            c.rounded(px + 1.2, -7.2, px + 5.2, -4.6, .3, fill='#28343e')
            c.led(px + 1.8, 3.6, '#35d07f' if index % 4 != 3 else '#f2b134', radius=.65)
            c.led(px + 4.6, 3.6, '#35d07f', radius=.65)
        c.line([(30, -9.5), (30, 10.5)], mix(front_top, '#ffffff', .25), .4)
        for i in range(5):
            c.rounded(33 + i * 2.2, -8.5, 34 + i * 2.2, 8.5, .5, fill=rgb(mix(front_bottom, '#000000', .45)))
    for i, colour in enumerate(('#35d07f', '#3aa0e8', '#35d07f')):
        c.led(50.2, -7.4 + i * 5.2, colour, radius=.85)


def monitor(c, variant):
    c.shadow(-33, 22, 33, 33, alpha=70)
    c.polygon([(-7, 13), (7, 13), (9.5, 24), (-9.5, 24)], gradient=('#566a7d', '#2b3a49', 13, 24))
    c.rounded(-24, 23, 24, 28, 2.4, gradient=('#4a5c6e', '#223140', 23, 28))
    c.rounded(-36, -32, 36, 16, 2.6, gradient=('#2b3a4a', '#121b25', -32, 16), outline='#0a121a', width=.6)
    top, bottom = ('#ff7a52', '#a8192b') if variant == 'red' else ('#43b4ff', '#0a49b8')
    c.rounded(-32.5, -28.5, 32.5, 10, 1.2, gradient=(top, bottom, -28.5, 10))
    c.polygon([(-32.5, -28.5), (-2, -28.5), (-32.5, 2)], fill=(255, 255, 255, 46))
    if variant == 'red':
        c.ellipse(-10.5, -19.5, 10.5, 1.5, outline='#ffffff', width=1.6, fill=(255, 255, 255, 0))
        c.line([(-4.8, -12.6), (0.2, -9.2), (-4.8, -5.8)], '#ffffff', 1.6)
        c.line([(2, -5), (7, -5)], '#ffffff', 1.6)
    else:
        for a, b, d, e in [(-11.5, -19, -1.2, -9.6), (1.2, -20.4, 12.5, -9.6), (-11.5, -7.2, -1.2, 2.4), (1.2, -7.2, 12.5, 3.8)]:
            c.rounded(a, b, d, e, .5, fill='#d6efff')
    c.rounded(-36, 10.5, 36, 16, 2.6, gradient=('#d8dfe6', '#aeb9c4', 10.5, 16))
    c.led(0, 13.2, '#35d07f', radius=.75)


def server(c):
    c.shadow(-22, 26, 30, 35, alpha=75)
    c.polygon([(-17, -30), (12, -30), (22, -35), (-7, -35)], gradient=('#8a9cab', '#6b7e8d', -35, -30), outline='#243442', width=.5)
    c.polygon([(12, -30), (22, -35), (22, 25), (12, 30)], gradient=('#22394a', '#13222e', -35, 30), outline='#0f1c27', width=.5)
    c.rounded(-17, -30, 12, 30, 1.6, gradient=('#3b5266', '#1a2a37', -30, 30), outline='#0f1c27', width=.6)
    for row in range(4):
        y = -25 + row * 8.6
        c.rounded(-13.4, y, 8.4, y + 6.2, .8, gradient=('#4a6377', '#33495b', y, y + 6.2), outline='#6b8597', width=.35)
        c.rounded(-11.4, y + 2.2, -5, y + 4, .4, fill='#a9bccb')
        c.led(5.4, y + 3.1, '#35d07f' if row != 2 else '#f2b134', radius=.7)
    for row in range(5):
        c.line([(-12, 12.5 + row * 2.6), (7.5, 12.5 + row * 2.6)], '#5f7686', .5)
    c.led(-9.5, 26.3, '#35d07f', radius=.9)


def render(output):
    output.mkdir(parents=True, exist_ok=True)
    drawings = {'router': lambda c: chassis(c, 'router'), 'switch': lambda c: chassis(c, 'switch'),
                'firewall': lambda c: chassis(c, 'firewall'), 'host-blue': lambda c: monitor(c, 'blue'),
                'host-red': lambda c: monitor(c, 'red'), 'server': server}
    for name, draw in drawings.items():
        for scale in SCALES:
            canvas = Canvas(scale)
            draw(canvas)
            canvas.result(scale).save(output / f'{name}@{round(scale * 100)}.png', optimize=True)
    print('rendered', len(drawings) * len(SCALES), 'images into', output)


if __name__ == '__main__':
    render(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)
