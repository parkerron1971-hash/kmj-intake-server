"""Material intelligence for Video Studio: what IS this picture?

Chief used to see a 1200 px thumbnail labelled "untrusted visual reference"
and had to guess whether it was a logo, a screenshot, a photo or a flyer.
The renderer then put the picture wherever the plan said, black tile and
all. This module looks first, deterministically, with PIL only:

- kind: logo | screenshot | photo | document
- flat_bg: the picture sits on one flat colour (a logo tile, a product shot
  on white). A flat-background logo gets a transparent copy so the mark
  floats in the opener instead of arriving inside a black square.
- focus: where the subject is (centre of edge energy), used as
  object-position for cover crops so faces and products stay in frame.
- quiet: the side of the picture with the least detail (left, right, top,
  bottom) where a title can sit without fighting the image, or None when
  the whole picture is busy and text should not go over it at all.
- grid_reference: a copy with a 10 % grid and axis labels drawn on it, so
  the planner can give callout coordinates it can actually see.

Nothing here is a model call; it runs in milliseconds per picture.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageOps

FLAT_TOLERANCE = 18        # per-channel distance for "same colour" on the border
FLAT_SHARE = .9            # share of border pixels that must match
BUSY_ENERGY = 26.0         # mean edge energy above which a region is "busy"


def _edges(im):
    g = ImageOps.grayscale(im).filter(ImageFilter.FIND_EDGES)
    return g


def _region_energy(edges, box):
    region = edges.crop(box)
    hist = region.histogram()
    total = sum(hist) or 1
    return sum(i * n for i, n in enumerate(hist)) / total


def _border_colour(im):
    """Dominant border colour and the share of border pixels close to it."""
    w, h = im.size
    px = im.convert('RGB').load()
    samples = []
    step = max(1, (w + h) // 400)
    for x in range(0, w, step):
        samples.append(px[x, 0]); samples.append(px[x, h - 1])
    for y in range(0, h, step):
        samples.append(px[0, y]); samples.append(px[w - 1, y])
    if not samples: return (0, 0, 0), 0.0
    # mode by coarse bucket
    buckets = {}
    for c in samples:
        key = tuple(v // 24 for v in c)
        buckets[key] = buckets.get(key, 0) + 1
    key = max(buckets, key=buckets.get)
    dominant = tuple(min(255, v * 24 + 12) for v in key)
    close = sum(1 for c in samples if all(abs(c[i] - dominant[i]) <= FLAT_TOLERANCE for i in range(3)))
    return dominant, close / len(samples)


def analyze(path):
    with Image.open(path) as source:
        im = source.convert('RGB')
        im.thumbnail((640, 640))
        w, h = im.size
        aspect = w / h
        dominant, share = _border_colour(im)
        flat_bg = share >= FLAT_SHARE
        # colour richness: photos use many colours, UI and logos few
        small = im.resize((96, 96))
        quantised = {tuple(v // 16 for v in c) for c in small.getdata()}
        richness = len(quantised) / (96 * 96)
        edges = _edges(im)
        energy = _region_energy(edges, (0, 0, w, h))
        lum = ImageOps.grayscale(im).resize((32, 32))
        mean_lum = sum(lum.getdata()) / 1024
        if flat_bg and .75 <= aspect <= 1.34 and richness < .12: kind = 'logo'
        elif mean_lum > 205 and richness < .08 and energy > 8: kind = 'document'
        elif richness < .10: kind = 'screenshot'
        else: kind = 'photo'
        # focus = centre of mass of edge energy (subject), in percent
        e = edges.resize((32, 32)); data = list(e.getdata()); tot = sum(data) or 1
        fx = sum((i % 32 + .5) * v for i, v in enumerate(data)) / tot / 32 * 100
        fy = sum((i // 32 + .5) * v for i, v in enumerate(data)) / tot / 32 * 100
        # quiet zone: least edge energy among the four side bands (45 % each)
        bands = {'left': (0, 0, int(w * .45), h), 'right': (int(w * .55), 0, w, h),
                 'top': (0, 0, w, int(h * .45)), 'bottom': (0, int(h * .55), w, h)}
        energies = {k: _region_energy(edges, b) for k, b in bands.items()}
        quiet_side = min(energies, key=energies.get)
        quiet = quiet_side if energies[quiet_side] < BUSY_ENERGY else None
    return {'kind': kind, 'flat_bg': flat_bg, 'bg_hex': '#%02X%02X%02X' % dominant, 'richness': round(richness, 3),
            'energy': round(energy, 1), 'focus': [round(fx), round(fy)], 'quiet': quiet, 'aspect': round(aspect, 2)}


def transparent_copy(path, target, tolerance=FLAT_TOLERANCE + 10):
    """Write a PNG with the flat border colour flood-filled to transparent
    from all four corners. Interior areas of the same colour that do not
    touch the border are kept (the counters of letters stay filled)."""
    with Image.open(path) as source:
        im = source.convert('RGBA')
    dominant, _ = _border_colour(im)
    w, h = im.size
    px = im.load()
    seen = bytearray(w * h)
    stack = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    while stack:
        x, y = stack.pop()
        if x < 0 or y < 0 or x >= w or y >= h: continue
        i = y * w + x
        if seen[i]: continue
        seen[i] = 1
        r, g, b, a = px[x, y]
        if not all(abs(v - dominant[k]) <= tolerance for k, v in enumerate((r, g, b))): continue
        px[x, y] = (r, g, b, 0)
        stack.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    # trim to the mark with a little air so it centres in the opener ring
    bbox = im.getchannel('A').getbbox()
    if bbox:
        pad = int(max(bbox[2] - bbox[0], bbox[3] - bbox[1]) * .08)
        im = im.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(w, bbox[2] + pad), min(h, bbox[3] + pad)))
    im.save(target, format='PNG')
    return target


def grid_reference(path, target, size=1400):
    """The planner's copy of a screenshot: a 10 % grid with x/y labels so
    callout coordinates come from what the model can see, not a guess."""
    with Image.open(path) as source:
        im = source.convert('RGB')
        im.thumbnail((size, size))
    w, h = im.size
    d = ImageDraw.Draw(im, 'RGBA')
    for i in range(1, 10):
        x = int(w * i / 10); y = int(h * i / 10)
        d.line((x, 0, x, h), fill=(255, 80, 80, 150), width=1)
        d.line((0, y, w, y), fill=(255, 80, 80, 150), width=1)
        d.text((x + 3, 2), f'x{i * 10}', fill=(255, 255, 255, 230))
        d.text((2, y + 2), f'y{i * 10}', fill=(255, 255, 255, 230))
    im.save(target, format='JPEG', quality=82)
    return target
