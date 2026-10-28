"""Draw the hero's cutaway church as an isometric SVG: the room from above
the back corner, with the stage, the screen on the stage wall, pews with
people, the projector, the stage display, the stream camera, the TV by the
doors, and the booth at the back. Light runs from the booth to each screen.

usage: python scripts/churchsavvy_art_church.py churchsavvy_site/art-church.svg"""
import math
import pathlib
import random
import sys

S = 10.0
C = math.cos(math.radians(30))
W, D, H, T = 48.0, 62.0, 18.0, 0.9
xs, ys = [], []
out = []


def P(x, y, z):
    px, py = (x - y) * C * S, (x + y) * 0.5 * S - z * S
    xs.append(px)
    ys.append(py)
    return px, py


def pts(ps):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in (P(*p) for p in ps))


def poly(ps, cls):
    out.append(f'<polygon class="{cls}" points="{pts(ps)}"></polygon>')


def line(a, b, cls):
    (x1, y1), (x2, y2) = P(*a), P(*b)
    out.append(f'<line class="{cls}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"></line>')


def box(x0, x1, y0, y1, z0, z1, c):
    poly([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], c + "-r")
    poly([(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)], c + "-f")
    poly([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], c + "-t")


def mat_y0(x, z):
    px, py = P(x, 0.05, z)
    return f"matrix({C:.4f},0.5,0,1,{px:.1f},{py:.1f})"


def mat_x0(y, z):
    px, py = P(0.05, y, z)
    return f"matrix({C:.4f},-0.5,0,1,{px:.1f},{py:.1f})"


def person(x, y, z, cls="pp"):
    hx, hy = P(x, y, z + 1.55)
    sx, sy = P(x, y, z + 0.75)
    out.append(f'<ellipse class="{cls}-s" cx="{sx:.1f}" cy="{sy:.1f}" rx="{0.62 * S:.1f}" ry="{0.5 * S:.1f}"></ellipse>')
    out.append(f'<circle class="{cls}" cx="{hx:.1f}" cy="{hy:.1f}" r="{0.36 * S:.1f}"></circle>')


VERSES = [
    ("PSALM 100:1 · KJV", ["Make a joyful noise", "unto the LORD,", "all ye lands."]),
    ("PSALM 100:2 · KJV", ["Serve the LORD", "with gladness: come", "before his presence."]),
    ("PSALM 100:3 · KJV", ["Know ye that", "the LORD he is God:", "it is he that hath made us."]),
    ("PSALM 100:4 · KJV", ["Enter into his gates", "with thanksgiving,", "and into his courts."]),
    ("PSALM 100:5 · KJV", ["For the LORD is good;", "his mercy is", "everlasting."]),
]

# floor and its grid
poly([(0, 0, 0), (W, 0, 0), (W, D, 0), (0, D, 0)], "fl")
for k in range(1, int(W // 4)):
    line((4 * k, 0, 0), (4 * k, D, 0), "gl")
for k in range(1, int(D // 4)):
    line((0, 4 * k, 0), (W, 4 * k, 0), "gl")
# center aisle runner
poly([(21.6, 17.4, 0.01), (26.4, 17.4, 0.01), (26.4, D, 0.01), (21.6, D, 0.01)], "ais")

# left wall (x = 0) and stage wall (y = 0), cut at their near ends
poly([(0, 0, 0), (0, D, 0), (0, D, H), (0, 0, H)], "wl")
poly([(0, 0, 0), (W, 0, 0), (W, 0, H), (0, 0, H)], "ws")
poly([(0, 0, H), (0, D, H), (-T, D, H), (-T, -T, H)], "wt")
poly([(-T, -T, H), (W, -T, H), (W, 0, H), (0, 0, H)], "wt")
poly([(0, D, 0), (0, D, H), (-T, D, H), (-T, D, 0)], "wc")
poly([(W, 0, 0), (W, 0, H), (W, -T, H), (W, -T, 0)], "wc")
# windows down the left wall
for y0 in (22, 33, 44):
    poly([(0.03, y0, 6), (0.03, y0 + 4.4, 6), (0.03, y0 + 4.4, 14.5), (0.03, y0, 14.5)], "iwin")
    line((0.04, y0 + 2.2, 6), (0.04, y0 + 2.2, 14.5), "iwinl")
    line((0.04, y0, 10.3), (0.04, y0 + 4.4, 10.3), "iwinl")
# doors at the back of the left wall
poly([(0.03, 54.5, 0), (0.03, 60.5, 0), (0.03, 60.5, 7), (0.03, 54.5, 7)], "door")
line((0.04, 57.5, 0), (0.04, 57.5, 7), "doorl")

# the main screen on the stage wall, with its glow
SX0, SX1, SZ0 = 13.0, 35.0, 5.6
SZ1 = SZ0 + (SX1 - SX0) * 9 / 16
poly([(SX0 - 0.8, 0.03, SZ0 - 0.8), (SX1 + 0.8, 0.03, SZ0 - 0.8), (SX1 + 0.8, 0.03, SZ1 + 0.8), (SX0 - 0.8, 0.03, SZ1 + 0.8)], "glow")
poly([(SX0 - 0.3, 0.04, SZ0 - 0.3), (SX1 + 0.3, 0.04, SZ0 - 0.3), (SX1 + 0.3, 0.04, SZ1 + 0.3), (SX0 - 0.3, 0.04, SZ1 + 0.3)], "sfr")
poly([(SX0, 0.05, SZ0), (SX1, 0.05, SZ0), (SX1, 0.05, SZ1), (SX0, 0.05, SZ1)], "iscr")
sw = (SX1 - SX0) * S
out.append(f'<g class="iso-s5" transform="{mat_y0(SX0, SZ1)}">')
for lab, lines in VERSES:
    out.append("<g>")
    out.append(f'<text class="sl-lab" x="{sw / 2:.1f}" y="{2.6 * S:.1f}" text-anchor="middle">{lab}</text>')
    for i, t in enumerate(lines):
        out.append(f'<text class="sl-txt" x="{sw / 2:.1f}" y="{(4.9 + 2.0 * i) * S:.1f}" text-anchor="middle">{t}</text>')
    out.append("</g>")
out.append("</g>")

# the stage display on the left wall, for the people up front
TX0, TX1, TZ0 = 4.5, 11.5, 7.0
TZ1 = TZ0 + (TX1 - TX0) * 9 / 16
poly([(0.04, TX0 - 0.3, TZ0 - 0.3), (0.04, TX1 + 0.3, TZ0 - 0.3), (0.04, TX1 + 0.3, TZ1 + 0.3), (0.04, TX0 - 0.3, TZ1 + 0.3)], "sfr")
poly([(0.05, TX0, TZ0), (0.05, TX1, TZ0), (0.05, TX1, TZ1), (0.05, TX0, TZ1)], "tvs")
out.append(f'<g transform="{mat_x0(TX1, TZ1)}">')
out.append(f'<text class="tv-l" x="{0.6 * S:.1f}" y="{1.2 * S:.1f}">NOW</text>')
out.append(f'<text class="tv-t" x="{0.6 * S:.1f}" y="{2.5 * S:.1f}">Psalm 100</text>')
out.append(f'<text class="tv-c" x="{0.6 * S:.1f}" y="{3.6 * S:.1f}">11:16</text>')
out.append("</g>")

# the TV by the doors
LX0, LX1, LZ0 = 47.5, 53.0, 7.4
LZ1 = LZ0 + (LX1 - LX0) * 9 / 16
poly([(0.04, LX0 - 0.3, LZ0 - 0.3), (0.04, LX1 + 0.3, LZ0 - 0.3), (0.04, LX1 + 0.3, LZ1 + 0.3), (0.04, LX0 - 0.3, LZ1 + 0.3)], "sfr")
poly([(0.05, LX0, LZ0), (0.05, LX1, LZ0), (0.05, LX1, LZ1), (0.05, LX0, LZ1)], "lbs")
out.append(f'<g transform="{mat_x0(LX1, LZ1)}">')
out.append(f'<text class="lb-l" x="{0.5 * S:.1f}" y="{1.1 * S:.1f}">THIS WEEK</text>')
out.append(f'<text class="lb-t" x="{0.5 * S:.1f}" y="{2.15 * S:.1f}">Dinner, Wed</text>')
out.append("</g>")

# the stage platform and its steps
box(4, 44, 0, 15, 0, 1.4, "st")
box(19.5, 28.5, 15, 16.3, 0, 0.93, "st")
box(19.5, 28.5, 16.3, 17.6, 0, 0.47, "st")
# on the stage, back to front
box(7.5, 12.5, 4.2, 5.4, 2.5, 2.8, "kb")
line((8.2, 4.8, 1.4), (11.8, 4.8, 2.5), "stand")
line((11.8, 4.8, 1.4), (8.2, 4.8, 2.5), "stand")
box(36.2, 38.8, 4.0, 5.4, 1.4, 3.3, "amp")
for mx in (17.0, 31.0):
    line((mx, 10.4, 1.4), (mx, 10.4, 5.0), "mic")
    a, b = P(mx, 10.4, 5.0)
    out.append(f'<circle class="mich" cx="{a:.1f}" cy="{b:.1f}" r="{0.32 * S:.1f}"></circle>')
box(22.4, 25.6, 9.0, 11.0, 1.4, 4.6, "lec")
poly([(22.1, 8.8, 4.9), (25.9, 8.8, 4.9), (25.9, 11.2, 4.5), (22.1, 11.2, 4.5)], "lec-top")
for wx in (15.5, 30.0):
    box(wx, wx + 2.4, 13.0, 14.3, 1.4, 2.0, "wdg")
for px in (6.0, 42.0):
    a, b = P(px, 13.0, 1.4)
    out.append(f'<ellipse class="pot" cx="{a:.1f}" cy="{b - 0.5 * S:.1f}" rx="{0.9 * S:.1f}" ry="{1.1 * S:.1f}"></ellipse>')
    out.append(f'<ellipse class="leaf" cx="{a:.1f}" cy="{b - 2.6 * S:.1f}" rx="{1.4 * S:.1f}" ry="{1.7 * S:.1f}"></ellipse>')

# pews, far to near, with people
random.seed(7)
ROWS = [20.5 + 3.15 * k for k in range(10)]
for k, y0 in enumerate(ROWS):
    for x0, x1 in ((4.0, 21.0), (27.0, 44.0)):
        box(x0, x1, y0 + 1.15, y0 + 1.45, 0, 2.9, "pb")
        box(x0, x1, y0, y0 + 1.15, 0, 1.45, "pw")
        n = random.choice([1, 2, 2, 3, 3, 4]) if k < 8 else random.choice([0, 1, 2])
        spots = sorted(random.sample(range(int(x0) + 1, int(x1) - 1, 2), n))
        for sx in spots:
            person(sx + random.uniform(-0.3, 0.3), y0 + 0.7, 1.45)

# the projector on the ceiling, and its light on the screen
PX, PY, PZ = 24.0, 31.0, 16.4
poly([(PX, PY - 0.4, PZ - 0.3), (SX0, 0.06, SZ1), (SX1, 0.06, SZ1), (SX1, 0.06, SZ0)], "pbeam")
line((PX, PY + 0.5, PZ + 0.4), (PX, PY + 0.5, H), "mount")
box(PX - 1.2, PX + 1.2, PY - 0.4, PY + 1.4, PZ - 0.5, PZ + 0.4, "prj")

# the stream camera in the aisle
CX, CY = 24.0, 50.5
for lx, ly in ((23.0, 51.6), (25.0, 51.6), (24.0, 49.2)):
    line((lx, ly, 0), (CX, CY, 4.3), "leg")
box(CX - 0.6, CX + 0.6, CY - 1.0, CY + 0.9, 4.3, 5.2, "cam")
a, b = P(CX + 0.6, CY - 0.6, 5.2)
out.append(f'<circle class="tally" cx="{a:.1f}" cy="{b - 2:.1f}" r="2.6"></circle>')

# the booth at the back: a table, the laptop facing the operator, the operator
box(29.5, 40.5, 56.0, 58.4, 2.3, 2.6, "bt")
box(29.8, 40.2, 56.1, 56.5, 0.4, 2.3, "bp")
box(33.6, 36.6, 56.4, 57.9, 2.6, 2.72, "lp")
poly([(33.6, 56.45, 2.72), (36.6, 56.45, 2.72), (36.6, 56.45, 4.4), (33.6, 56.45, 4.4)], "lps")
a, b = P(35.1, 56.46, 3.55)
out.append(f'<circle class="lpd" cx="{a:.1f}" cy="{b:.1f}" r="2.2"></circle>')
person(35.1, 60.0, 1.6, "op")

# light from the booth to every screen
def path3(points, cls, plen=True):
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in (P(*p) for p in points))
    pl = ' pathLength="100"' if plen else ""
    out.append(f'<path class="{cls}"{pl} d="{d}"></path>')


ROUTES = {
    "room": [(35.1, 56.4, 4.6), (35.1, 56.4, 15.2), (PX, PY + 1.4, 15.2), (PX, PY + 1.4, PZ)],
    "stage": [(33.6, 56.5, 2.6), (2.0, 56.5, 2.6), (2.0, 8.0, 2.6), (0.2, 8.0, TZ0)],
    "stream": [(33.6, 57.2, 2.4), (CX, 57.2, 2.4), (CX, CY + 0.9, 4.6)],
    "lobby": [(33.6, 57.6, 2.5), (1.2, 57.6, 2.5), (1.2, 50.2, LZ0)],
}
for name, r in ROUTES.items():
    path3(r, "cb " + ("hd" if name == "room" else "ln"), plen=False)
for name, r in ROUTES.items():
    path3(r, "pz2")

# labels: a dot on the thing, a leader, a tag
def label(at, dx, dy, text, cls=""):
    ax, ay = P(*at)
    tx, ty = ax + dx, ay + dy
    w = len(text) * 7.4 + 22
    out.append(f'<g class="lb {cls}">')
    out.append(f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{tx:.1f}" y2="{ty:.1f}"></line>')
    out.append(f'<circle cx="{ax:.1f}" cy="{ay:.1f}" r="3.2"></circle>')
    left = tx - w if dx < 0 else tx
    out.append(f'<rect x="{left:.1f}" y="{ty - 13:.1f}" width="{w:.1f}" height="26" rx="13"></rect>')
    out.append(f'<text x="{left + w / 2:.1f}" y="{ty + 4:.1f}" text-anchor="middle">{text}</text>')
    out.append("</g>")
    xs.extend([left, left + w])
    ys.extend([ty - 13, ty + 13])


label((SX1, 0.05, SZ1 - 1.0), 70, -40, "THE ROOM · HDMI")
label((0.05, TX0 + 1.0, TZ1 - 0.5), -60, -48, "THE STAGE · LINK")
label((CX, CY, 5.2), 92, 44, "THE STREAM · LINK")
label((0.05, LX0 + 1.0, LZ1 - 0.3), -66, -30, "THE LOBBY · LINK")
label((35.1, 56.5, 4.4), 96, 30, "THE BOOTH", "bo")

pad = 8
x0, x1, y0, y1 = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
svg = (f'<svg class="iso" viewBox="{x0:.0f} {y0:.0f} {x1 - x0:.0f} {y1 - y0:.0f}" role="img" '
       f'aria-label="A church during a service, from above: the booth at the back sends the service to the room screen, '
       f'the stage display, the stream camera and the TV by the doors">\n' + "\n".join(out) + "\n</svg>\n")
pathlib.Path(sys.argv[1]).write_text(svg, encoding="utf-8")
print("iso svg", f"{x1 - x0:.0f}x{y1 - y0:.0f}", len(svg), "chars")
