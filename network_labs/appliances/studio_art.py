"""The workbench's devices on the canvas: a black rounded tile with a white line icon (router,
switch, firewall, PC, server), a soft glow under it and a status light at its corner. Drawn with canvas items only (no
image files), so it scales with the zoom and needs nothing beyond Tk."""
import math

BACKGROUND = '#ffffff'



def rounded(canvas, x1, y1, x2, y2, r, **options):
    """A rounded rectangle as one smooth polygon."""
    points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r,
              x1, y1 + r, x1, y1]
    return canvas.create_polygon(points, smooth=True, splinesteps=16, **options)


def _arrow(canvas, x1, y1, x2, y2, s, width, colour, tags):
    canvas.create_line(x1, y1, x2, y2, fill=colour, width=width, capstyle='round', arrow='last',
                       arrowshape=(3.2 * s, 3.6 * s, 1.6 * s), tags=tags)


def glyph(canvas, kind, x, y, size, colour='#ffffff', tags=()):
    """The role's line icon in a SIZE square centred on (x, y), drawn on a 24-unit grid."""
    s = size / 24
    p = lambda u, v: (x + (u - 12) * s, y + (v - 12) * s)
    width = max(1.2, 1.7 * s)
    line = dict(fill=colour, width=width, capstyle='round', joinstyle='round', tags=tags)
    if kind == 'router':
        canvas.create_oval(*p(3.5, 3.5), *p(20.5, 20.5), outline=colour, width=width, tags=tags)
        for (u1, v1, u2, v2) in ((12, 10, 12, 5.8), (12, 14, 12, 18.2), (10, 12, 5.8, 12), (14, 12, 18.2, 12)):
            _arrow(canvas, *p(u1, v1), *p(u2, v2), s, width, colour, tags)
    elif kind == 'switch':
        rounded(canvas, *p(2.5, 5.5), *p(21.5, 18.5), 2.5 * s, outline=colour, fill='', width=width, tags=tags)
        _arrow(canvas, *p(6.5, 10), *p(17.5, 10), s, width, colour, tags)
        _arrow(canvas, *p(17.5, 14), *p(6.5, 14), s, width, colour, tags)
    elif kind == 'firewall':
        shield = [12, 2.8, 19.8, 6, 19.8, 11.5, 18.5, 16.5, 12, 21.2, 5.5, 16.5, 4.2, 11.5, 4.2, 6]
        canvas.create_polygon([c for i in range(0, len(shield), 2) for c in p(shield[i], shield[i + 1])], outline=colour, fill='',
                              width=width, joinstyle='round', tags=tags)
        for v in (10.5, 14.5):
            canvas.create_line(*p(7.5, v), *p(16.5, v), **line)
        for u, v1, v2 in ((12, 6.8, 10.5), (9.8, 10.5, 14.5), (14.2, 10.5, 14.5), (12, 14.5, 17.5)):
            canvas.create_line(*p(u, v1), *p(u, v2), **line)
    elif kind == 'server':
        for top in (3.5, 9.25, 15):
            rounded(canvas, *p(5, top), *p(19, top + 5.5), 1.5 * s, outline=colour, fill='', width=width, tags=tags)
            canvas.create_oval(*p(7.3, top + 2.1), *p(8.7, top + 3.4), fill=colour, outline='', tags=tags)
            canvas.create_line(*p(11, top + 2.75), *p(16.5, top + 2.75), **line)
    else:  # a PC
        rounded(canvas, *p(3, 4.5), *p(21, 16.5), 2 * s, outline=colour, fill='', width=width, tags=tags)
        canvas.create_line(*p(12, 16.5), *p(12, 20), **line)
        canvas.create_line(*p(8.5, 20), *p(15.5, 20), **line)


def mono_tile(canvas, kind, x, y, size, status, tags, selected):
    """The black and white design's device: a black tile, a soft grey shadow, the white icon; its state as a dot at the
    corner, filled black when it runs, hollow when it does not."""
    half, r = size / 2, size * .3
    glow = tuple(tags) + ('glow',)
    for spread, shade in ((5, '#f1f1f1'), (2, '#e2e2e2')):
        rounded(canvas, x - half - spread, y - half - spread + 3, x + half + spread, y + half + spread + 3, r + spread, fill=shade,
                outline='', tags=glow)
    rounded(canvas, x - half, y - half, x + half, y + half, r, fill='#111111', outline='', tags=tags)
    rounded(canvas, x - half + 1, y - half + 1, x + half - 1, y - half + size * .2, r * .8, fill='#2a2a2a', outline='', tags=tags)
    glyph(canvas, kind, x, y + size * .02, size * .54, tags=tags)
    if selected:
        rounded(canvas, x - half - 6, y - half - 6, x + half + 6, y + half + 6, r + 6, outline='#111111', fill='', width=2,
                dash=(4, 3), tags=tags)
    if status is not None:
        d = size * .14
        fill, edge = ('#111111', '#ffffff') if status == 'running' else ('#ffffff', '#111111' if status == 'stopped' else '#9a9a9a')
        canvas.create_oval(x + half - d, y + half - d, x + half + d, y + half + d, fill='#ffffff', outline='#ffffff',
                           width=max(2, size * .05), tags=tags)
        canvas.create_oval(x + half - d * .72, y + half - d * .72, x + half + d * .72, y + half + d * .72, fill=fill,
                           outline='#111111' if fill == '#111111' else edge, width=max(1.5, size * .03), tags=tags)


def tile(canvas, kind, x, y, size=60, status=None, tags=(), selected=False):
    """One device: shadow, black tile, white icon, state dot. KIND: router, switch, firewall, host, server."""
    return mono_tile(canvas, kind, x, y, size, status, tags, selected)


def icon(canvas, name, x, y, size, colour, tags=()):
    """A small line icon for the studio chrome (rail, canvas tools), in a SIZE square centred on (x, y)."""
    s = size / 24
    p = lambda u, v: (x + (u - 12) * s, y + (v - 12) * s)
    width = max(1.3, 1.8 * s)
    line = dict(fill=colour, width=width, capstyle='round', joinstyle='round', tags=tags)
    outline = dict(outline=colour, width=width, tags=tags)
    if name == 'topology':
        for u1, v1, u2, v2 in ((6, 6, 18, 6), (6, 6, 12, 18), (18, 6, 12, 18)):
            canvas.create_line(*p(u1, v1), *p(u2, v2), **line)
        for u, v in ((6, 6), (18, 6), (12, 18)):
            canvas.create_oval(*p(u - 3, v - 3), *p(u + 3, v + 3), fill=canvas.cget('bg'), **outline)
    elif name == 'code':
        for side in (1, -1):
            points = [(12 - 3 * side, 4), (12 - 5 * side, 4), (12 - 6 * side, 5.5), (12 - 6 * side, 10), (12 - 8 * side, 12),
                      (12 - 6 * side, 14), (12 - 6 * side, 18.5), (12 - 5 * side, 20), (12 - 3 * side, 20)]
            canvas.create_line(*[c for u, v in points for c in p(u, v)], smooth=True, **line)
    elif name == 'flag':
        canvas.create_line(*p(6, 3.5), *p(6, 21), **line)
        canvas.create_polygon(*[c for u, v in ((6, 4), (18.5, 4), (15.5, 8.5), (18.5, 13), (6, 13)) for c in p(u, v)], fill='',
                              joinstyle='round', **outline)
    elif name == 'sliders':
        for v, knob in ((6, 15), (12, 8.5), (18, 13)):
            canvas.create_line(*p(4, v), *p(20, v), **line)
            canvas.create_oval(*p(knob - 2.4, v - 2.4), *p(knob + 2.4, v + 2.4), fill=canvas.cget('bg'), **outline)
    elif name == 'mail':
        rounded(canvas, *p(3, 5.5), *p(21, 18.5), 2.2 * s, fill='', **outline)
        canvas.create_line(*p(4, 7), *p(12, 13), *p(20, 7), **line)
    elif name == 'list':
        for v in (6.5, 12, 17.5):
            canvas.create_line(*p(9.5, v), *p(20, v), **line)
            canvas.create_oval(*p(4.6, v - 1.1), *p(6.8, v + 1.1), fill=colour, outline='', tags=tags)
    elif name == 'gear':
        canvas.create_oval(*p(8.6, 8.6), *p(15.4, 15.4), **outline)
        canvas.create_oval(*p(5.2, 5.2), *p(18.8, 18.8), **outline)
        for index in range(8):
            angle = index * math.pi / 4
            canvas.create_line(*p(12 + 6.8 * math.cos(angle), 12 + 6.8 * math.sin(angle)),
                               *p(12 + 9.6 * math.cos(angle), 12 + 9.6 * math.sin(angle)), **dict(line, width=width * 1.6))
    elif name == 'pointer':
        canvas.create_polygon(*[c for u, v in ((7, 3.5), (7, 19), (10.8, 15.4), (13.6, 21), (16, 19.9), (13.3, 14.4), (18.5, 14.2))
                                for c in p(u, v)], fill='', joinstyle='round', **outline)
    elif name == 'cable':
        canvas.create_line(*p(5, 19), *p(10, 19), *p(14, 5), *p(19, 5), smooth=True, **line)
        for u, v in ((4, 19), (20, 5)):
            canvas.create_oval(*p(u - 2.2, v - 2.2), *p(u + 2.2, v + 2.2), fill=colour, outline='', tags=tags)
    elif name == 'trash':
        canvas.create_line(*p(4, 6.5), *p(20, 6.5), **line)
        canvas.create_line(*p(9.5, 6.5), *p(9.5, 4), *p(14.5, 4), *p(14.5, 6.5), **line)
        canvas.create_polygon(*[c for u, v in ((6.5, 6.5), (7.5, 20), (16.5, 20), (17.5, 6.5)) for c in p(u, v)], fill='',
                              joinstyle='round', **outline)
        for u in (10.5, 13.5):
            canvas.create_line(*p(u, 10), *p(u, 16.5), **line)
    elif name in ('minus', 'plus'):
        canvas.create_line(*p(6, 12), *p(18, 12), **line)
        if name == 'plus':
            canvas.create_line(*p(12, 6), *p(12, 18), **line)
    elif name == 'fit':
        for (u, v), (du, dv) in (((4, 4), (1, 1)), ((20, 4), (-1, 1)), ((4, 20), (1, -1)), ((20, 20), (-1, -1))):
            canvas.create_line(*p(u, v + 5 * dv), *p(u, v), *p(u + 5 * du, v), **line)
    elif name == 'refresh':
        canvas.create_arc(*p(5, 5), *p(19, 19), start=40, extent=290, style='arc', **outline)
        canvas.create_polygon(*[c for u, v in ((19.6, 3.2), (19.8, 9.4), (13.8, 8.2)) for c in p(u, v)], fill=colour, outline='',
                              tags=tags)
    elif name in ('left', 'right'):
        side = 1 if name == 'right' else -1
        canvas.create_line(*p(12 - 3 * side, 6), *p(12 + 3 * side, 12), *p(12 - 3 * side, 18), **line)
    elif name == 'search':
        canvas.create_oval(*p(4, 4), *p(16, 16), **outline)
        canvas.create_line(*p(15, 15), *p(20.5, 20.5), **line)


def logo(canvas, x, y, size, font):
    """The application's mark on the rail: a black rounded square with a white N."""
    half = size / 2
    rounded(canvas, x - half, y - half, x + half, y + half, size * .3, fill='#111111', outline='')
    canvas.create_text(x, y + 1, text='N', fill='white', font=(font, int(size * .36), 'bold'))


def kind_of(node, dmz=(), models=None):
    """Which tile a node gets: its role, or « server » for a server model or a host cabled straight to a firewall."""
    model = (models or {}).get(node.get('model'))
    if node['role'] == 'host' and (model and model.get('presentation') == 'server' or node['name'] in dmz
                                   or node['name'].upper().startswith('SRV')):
        return 'server'
    return node['role']


__all__ = ['glyph', 'tile', 'icon', 'logo', 'kind_of', 'rounded']
