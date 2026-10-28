"""Draw the hands-on section's room, seen from the back of the sanctuary,
as two SVG layers (viewBox 1440 x 640) that sit behind and in front of the
HTML screens: the back layer is the wall, the uplights, the truss and its
light; the front layer is the stage and the people in their rows.

usage: python scripts/churchsavvy_art_stage.py churchsavvy_site/art-stage-back.svg churchsavvy_site/art-stage-front.svg"""
import pathlib
import random
import sys

VB = 'viewBox="0 0 1440 640" preserveAspectRatio="xMidYMid slice"'


def f(v):
    return f"{v:.1f}"


# ---------- back layer ----------
b = [f'<svg class="stg-back" {VB} aria-hidden="true">',
     '<defs>'
     '<linearGradient id="cs-beam" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#C9D4FF" stop-opacity=".20"></stop><stop offset="1" stop-color="#C9D4FF" stop-opacity="0"></stop></linearGradient>'
     '<filter id="cs-blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="34"></feGaussianBlur></filter>'
     '</defs>',
     '<rect width="1440" height="640" fill="#07080D"></rect>']
for x in range(0, 1441, 16):
    b.append(f'<line class="slat" x1="{x}" y1="0" x2="{x}" y2="400"></line>')
for cx in (300, 560, 880, 1140):
    b.append(f'<ellipse class="upl" cx="{cx}" cy="388" rx="170" ry="90" filter="url(#cs-blur)"></ellipse>')
b.append('<ellipse class="upl2" cx="720" cy="230" rx="420" ry="200" filter="url(#cs-blur)"></ellipse>')
# truss
b.append('<rect class="truss" x="120" y="8" width="1200" height="3"></rect><rect class="truss" x="120" y="22" width="1200" height="3"></rect>')
for i in range(0, 50):
    x0 = 120 + i * 24
    b.append(f'<line class="trl" x1="{x0}" y1="11" x2="{x0 + 12}" y2="22"></line><line class="trl" x1="{x0 + 12}" y1="22" x2="{x0 + 24}" y2="11"></line>')
for lx, tx in ((230, 300), (380, 520), (560, 640), (880, 800), (1060, 920), (1210, 1140)):
    b.append(f'<polygon class="sbeam" points="{lx - 7},44 {lx + 7},44 {tx + 80},430 {tx - 80},430"></polygon>')
    b.append(f'<rect class="fix" x="{lx - 9}" y="25" width="18" height="20" rx="3"></rect><circle class="lens" cx="{lx}" cy="44" r="5"></circle>')
b.append("</svg>")

# ---------- front layer ----------
F = [f'<svg class="stg-front" {VB} aria-hidden="true">']
# the stage: top surface, lip, steps
F.append('<polygon class="s-top" points="220,398 1220,398 1336,456 104,456"></polygon>')
F.append('<line class="s-edge" x1="104" y1="456" x2="1336" y2="456"></line>')
F.append('<rect class="s-lip" x="104" y="456" width="1232" height="26"></rect>')
F.append('<rect class="s-step" x="626" y="482" width="188" height="12"></rect><rect class="s-step2" x="610" y="494" width="220" height="12"></rect>')
F.append('<line class="s-edge" x1="626" y1="482" x2="814" y2="482"></line><line class="s-edge" x1="610" y1="494" x2="830" y2="494"></line>')
# glow of the screen on the stage floor
F.append('<ellipse class="s-glow" cx="720" cy="420" rx="360" ry="26"></ellipse>')
# plants at the corners
for px in (176, 1264):
    F.append(f'<rect class="sil" x="{px - 16}" y="420" width="32" height="34" rx="4"></rect>')
    for dx, dy, rx, ry in ((-18, -8, 22, 30), (16, -12, 22, 32), (0, -30, 20, 30), (-4, -2, 26, 18)):
        F.append(f'<ellipse class="leaf2" cx="{px + dx}" cy="{410 + dy}" rx="{rx}" ry="{ry}"></ellipse>')
# keyboard on its stand
F.append('<line class="silw" x1="384" y1="452" x2="456" y2="412"></line><line class="silw" x1="456" y1="452" x2="384" y2="412"></line>')
F.append('<rect class="sil" x="362" y="402" width="116" height="12" rx="2"></rect>')
# amp and a guitar stand
F.append('<rect class="sil" x="1012" y="404" width="74" height="48" rx="4"></rect><circle class="grille" cx="1049" cy="428" r="14"></circle>')
# wedges at the front edge
for wx in (512, 868):
    F.append(f'<polygon class="sil" points="{wx},452 {wx + 60},452 {wx + 52},436 {wx + 10},440"></polygon>')
# mics
for mx in (612, 828):
    F.append(f'<ellipse class="sil" cx="{mx}" cy="452" rx="14" ry="3"></ellipse><line class="silw" x1="{mx}" y1="452" x2="{mx}" y2="380"></line>'
             f'<line class="silw" x1="{mx}" y1="384" x2="{mx + (14 if mx < 720 else -14)}" y2="374"></line>'
             f'<rect class="sil" x="{mx + (12 if mx < 720 else -20)}" y="368" width="8" height="12" rx="4"></rect>')
# the lectern, with its reading light
F.append('<ellipse class="lamp" cx="720" cy="362" rx="44" ry="10"></ellipse>')
F.append('<polygon class="sil" points="688,374 752,374 744,454 696,454"></polygon>')
F.append('<polygon class="sil" points="678,364 762,364 756,376 684,376"></polygon>')
F.append('<line class="s-edge" x1="678" y1="364" x2="762" y2="364"></line>')
# the aisle runner
F.append('<polygon class="aisle" points="700,506 740,506 820,640 620,640"></polygon>')

# people, far row to near row, an aisle down the middle
random.seed(11)
ROWS = [(522, 8.6, 40), (552, 11.0, 52), (590, 13.6, 66), (636, 16.4, 82), (690, 19.4, 100)]
hands = {(1, 5), (2, 9), (1, 14), (3, 4)}
for k, (y, r, aisle) in enumerate(ROWS):
    step = r * 2.85
    for side in (-1, 1):
        x = 720 + side * (aisle + r * 1.6)
        i = 0
        while (side < 0 and x > -40) or (side > 0 and x < 1480):
            if random.random() > 0.12:
                jx = x + random.uniform(-0.25, 0.25) * r
                rr = r * random.uniform(0.9, 1.08)
                jy = y + random.uniform(-0.18, 0.18) * r
                if (k, i) in hands and side > 0:
                    F.append(f'<line class="arm" x1="{f(jx + 1.1 * rr)}" y1="{f(jy + 1.5 * rr)}" x2="{f(jx + 1.7 * rr)}" y2="{f(jy - 2.4 * rr)}" stroke-width="{f(0.62 * rr)}"></line>'
                             f'<circle class="ppl" cx="{f(jx + 1.75 * rr)}" cy="{f(jy - 2.7 * rr)}" r="{f(0.42 * rr)}"></circle>')
                F.append(f'<path class="ppl" d="M{f(jx - 1.95 * rr)},{f(jy + 3.6 * rr)} C{f(jx - 1.95 * rr)},{f(jy + 1.4 * rr)} {f(jx - 1.15 * rr)},{f(jy + 1.08 * rr)} {f(jx)},{f(jy + 1.08 * rr)} '
                         f'C{f(jx + 1.15 * rr)},{f(jy + 1.08 * rr)} {f(jx + 1.95 * rr)},{f(jy + 1.4 * rr)} {f(jx + 1.95 * rr)},{f(jy + 3.6 * rr)} Z"></path>')
                F.append(f'<circle class="ppl" cx="{f(jx)}" cy="{f(jy)}" r="{f(rr)}"></circle>')
            x += side * step
            i += 1
F.append("</svg>")

pathlib.Path(sys.argv[1]).write_text("\n".join(b) + "\n", encoding="utf-8")
pathlib.Path(sys.argv[2]).write_text("\n".join(F) + "\n", encoding="utf-8")
print("back", sum(len(x) for x in b), "front", sum(len(x) for x in F))
