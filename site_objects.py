# site_objects.py
# ─────────────────────────────────────────────────────────────────────
# THE OBJECT LIBRARY (2026-10-01, the concept-layer plan, step 3).
#
# What the liaisongraphics.com study found: the pages people remember
# put their content inside real objects from one idea. The welcome is a
# letter in a sealed envelope; the curriculum is a stack of dated class
# cards; past students are ID cards; the price wears a marker circle and
# splits into four tiles. Our builder had none of these. It could only
# reach them freehand, inside a 64k-token page, every time from scratch.
#
# So: a small library of hand-built objects, the way design_moves is a
# library of named moves. The Director names objects in the blueprint's
# concept sheet ("OBJECTS: ticket, letterboard"); the builder receives
# exactly those objects' source and places and fills them. Same rule as
# the moves: nothing can be named that has no renderer here, and a named
# object always arrives with its source.
#
# THE CONTRACT EVERY OBJECT KEEPS
#   - One root element: class "sxo sxo-<key>" and data-sx-object="<key>".
#   - Colour and type come ONLY from seven tokens the builder maps once in
#     :root (--obj-paper, --obj-ink, --obj-accent, --obj-line,
#     --obj-display, --obj-body, --obj-label), with fallbacks to the usual
#     --sx-* names. No colour literals: tints are color-mix() against
#     those tokens, neutrals are rgba(0,0,0,x) / rgba(255,255,255,x).
#   - A finish (data-finish): paper (the default), inverse, glow, metal.
#     The same seal reads printed in Broadsheet, engraved in Ledger, lit
#     in Neon.
#   - Real text inside, readable by search and screen readers. Decorative
#     parts are aria-hidden.
#   - A phone version in the object's own CSS, and a still state under
#     prefers-reduced-motion. Motion never hides content at rest.
#   - The only url() on a page is the library's own grain texture, and it
#     lives inside data-sx-object elements (Kevin, 2026-10-01: lift the
#     url() ban for library objects only).
#
# The example copy belongs to an imaginary pottery studio running a
# six-week wheel-throwing course, so the contact sheet reads as one world.
# Every word of it is replaced from THE REAL DATA on a real page.
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import re
from typing import Dict, Iterable, List, NamedTuple, Tuple


class SiteObject(NamedTuple):
    key: str
    name: str
    intent: str        # what the object IS (the Director's line)
    use_when: str      # what content it carries, and when not to use it
    aliases: Tuple[str, ...]
    html: str          # a filled example: the structure and class names are the contract
    css: str
    js: str = ""       # merged into the page's one script when present
    phone: str = ""    # what happens at 390px, in words


# Fine paper grain, the one texture the library carries. An SVG
# turbulence tile at low alpha, multiplied over the paper colour.
_GRAIN = ("url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' "
          "width='180' height='180'><filter id='g'><feTurbulence type='fractalNoise' "
          "baseFrequency='.85' numOctaves='2' stitchTiles='stitch'/><feColorMatrix "
          "values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 .07 0'/></filter><rect "
          "width='100%' height='100%' filter='url(%23g)'/></svg>\")")

BASE_CSS = """/* THE OBJECT LIBRARY: shared tokens. Map the seven --obj-* tokens once in :root. */
.sxo{--_paper:var(--obj-paper,var(--sx-surface,var(--sx-bg-2,var(--sx-bg,Canvas))));
  --_ink:var(--obj-ink,var(--sx-text,CanvasText));
  --_accent:var(--obj-accent,var(--sx-accent,LinkText));
  --_line:var(--obj-line,color-mix(in srgb,var(--_ink) 20%,transparent));
  --_display:var(--obj-display,var(--sx-font-display,inherit));
  --_body:var(--obj-body,var(--sx-font-body,inherit));
  --_label:var(--obj-label,var(--_body));
  --_grain:""" + _GRAIN + """;
  --_lift:0 1px 0 rgba(255,255,255,.35) inset,0 24px 48px -24px rgba(0,0,0,.45),0 2px 6px rgba(0,0,0,.12);
  box-sizing:border-box;color:inherit;font-family:var(--_body)}
.sxo *,.sxo *::before,.sxo *::after{box-sizing:border-box}
.sxo[data-finish="inverse"]{--_paper:var(--obj-ink,var(--sx-text,CanvasText));--_ink:var(--obj-paper,var(--sx-surface,var(--sx-bg,Canvas)))}
.sxo-paper{color:var(--_ink);background-color:var(--_paper);background-image:var(--_grain);background-blend-mode:multiply}
.sxo[data-finish="glow"] .sxo-paper,.sxo-paper[data-finish="glow"]{background-image:none;
  box-shadow:0 0 0 1px color-mix(in srgb,var(--_accent) 70%,transparent),0 0 28px color-mix(in srgb,var(--_accent) 35%,transparent)}
.sxo[data-finish="metal"]{--_metal:linear-gradient(135deg,color-mix(in srgb,var(--_accent) 58%,rgba(255,255,255,1)),var(--_accent) 34%,color-mix(in srgb,var(--_accent) 66%,rgba(0,0,0,1)) 68%,color-mix(in srgb,var(--_accent) 78%,rgba(255,255,255,1)))}
.sxo-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.sxo-label{font-family:var(--_label);font-size:12px;letter-spacing:.14em;text-transform:uppercase}"""


def _o(**kw) -> SiteObject:
    return SiteObject(**kw)


OBJECTS: Dict[str, SiteObject] = {}


def _add(obj: SiteObject) -> None:
    OBJECTS[obj.key] = obj


# ── 1. THE LETTER ────────────────────────────────────────────────────
_add(_o(
    key="letter", name="Letter in an envelope",
    intent="a letter on paper sliding out of an envelope, closed with a seal",
    use_when="a welcome, an acceptance, a note from the owner, a promise in "
             "their own voice. Four to eight short lines of real copy. Not for "
             "lists or prices.",
    aliases=("letter", "envelope", "acceptance letter", "note", "welcome note"),
    html="""<figure class="sxo sxo-letter" data-sx-object="letter" data-overlap-ok>
  <span class="sxo-letter-back" aria-hidden="true"></span>
  <div class="sxo-letter-sheet sxo-paper">
    <p class="sxo-letter-date sxo-label">Fall term · Week one</p>
    <p class="sxo-letter-salute">Dear new potter,</p>
    <p>Your seat at the wheel is saved. Over six Thursdays you will center, open, pull and trim, and on the last night you take home four pieces you made with your own hands.</p>
    <p>Bring clothes you do not mind wearing clay in.</p>
    <p class="sxo-letter-sign">See you at the wheel,<span>Mara Quill, studio lead</span></p>
  </div>
  <span class="sxo-letter-front" aria-hidden="true"></span>
</figure>""",
    css=""".sxo-letter{position:relative;max-width:36rem;margin:0 auto;padding:0 6% 14%}
.sxo-letter-sheet{position:relative;z-index:1;padding:clamp(1.5rem,4vw,2.75rem);padding-bottom:clamp(4rem,10vw,6rem);
  box-shadow:var(--_lift);transform:rotate(-.6deg);font-size:clamp(16px,1.15vw,18px);line-height:1.6}
.sxo-letter-sheet p{margin:0 0 .9em}
.sxo-letter-date{color:color-mix(in srgb,var(--_ink) 60%,transparent);margin-bottom:1.4em!important}
.sxo-letter-salute{font-family:var(--_display);font-size:1.35em;line-height:1.2}
.sxo-letter-sign{margin-top:1.4em!important;font-style:italic}
.sxo-letter-sign span{display:block;font-style:normal;font-family:var(--_label);font-size:12px;letter-spacing:.12em;text-transform:uppercase;margin-top:.35em;color:color-mix(in srgb,var(--_ink) 65%,transparent)}
.sxo-letter-back,.sxo-letter-front{position:absolute;left:0;right:0;bottom:0;height:42%;
  background:color-mix(in srgb,var(--_accent) 42%,rgba(0,0,0,1));border-radius:3px}
.sxo-letter-back{z-index:0;height:56%}
.sxo-letter-front{z-index:2;clip-path:polygon(0 0,50% 46%,100% 0,100% 100%,0 100%);
  background:color-mix(in srgb,var(--_accent) 34%,rgba(0,0,0,1));
  box-shadow:0 -1px 0 rgba(255,255,255,.08) inset}
.sxo-letter .sxo-seal{position:absolute;z-index:3;left:50%;bottom:14%;transform:translate(-50%,40%);width:clamp(76px,10vw,108px)}
@media (max-width:600px){.sxo-letter{padding:0}
  .sxo-letter-back,.sxo-letter-front{display:none}
  .sxo-letter-sheet{transform:none;padding-bottom:clamp(1.5rem,4vw,2.75rem)}
  .sxo-letter .sxo-seal{position:relative;left:auto;bottom:auto;transform:none;display:grid;margin:1rem auto 0}}""",
    phone="the envelope folds away; the letter becomes a flat sheet and the seal sits beneath it",
))

# ── 2. THE SEAL ──────────────────────────────────────────────────────
_add(_o(
    key="seal", name="Seal with a text ring",
    intent="a round badge: the name set around a ring, a mark in the middle",
    use_when="the brand's stamp on a letter, a certificate, a hero corner or a "
             "price. Ring text is the business or program name, a star or dot "
             "between repeats. The core is a monogram or one short word.",
    aliases=("seal", "badge", "stamp", "crest", "emblem"),
    html="""<div class="sxo sxo-seal" data-sx-object="seal" data-turn>
  <span class="sxo-sr">Wheelhouse Ceramics, studio seal</span>
  <svg viewBox="0 0 200 200" aria-hidden="true">
    <defs><path id="sxo-ring-1" d="M100,100 m-70,0 a70,70 0 1,1 140,0 a70,70 0 1,1 -140,0"/></defs>
    <circle class="sxo-seal-rim" cx="100" cy="100" r="97"/>
    <circle class="sxo-seal-hair" cx="100" cy="100" r="88"/>
    <circle class="sxo-seal-core-bg" cx="100" cy="100" r="54"/>
    <text class="sxo-seal-ring"><textPath href="#sxo-ring-1" textLength="436" lengthAdjust="spacing">WHEELHOUSE CERAMICS ★ EST. 2019 ★</textPath></text>
  </svg>
  <span class="sxo-seal-core" aria-hidden="true">W</span>
</div>""",
    css=""".sxo-seal{position:relative;display:inline-grid;place-items:center;width:clamp(96px,13vw,168px);aspect-ratio:1}
.sxo-seal svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
.sxo-seal-rim{fill:var(--_accent)}
.sxo-seal-hair{fill:none;stroke:var(--_paper);stroke-width:1.2;opacity:.7}
.sxo-seal-core-bg{fill:var(--_ink)}
.sxo-seal-ring{fill:var(--_paper);font-family:var(--_label);font-size:17px;font-weight:700;letter-spacing:.06em}
.sxo-seal-core{position:relative;font-family:var(--_display);font-size:clamp(28px,4.2vw,56px);line-height:1;color:var(--_paper)}
.sxo-seal[data-finish="metal"] .sxo-seal-rim{fill:color-mix(in srgb,var(--_accent) 80%,rgba(255,255,255,1))}
.sxo-seal[data-finish="metal"]{filter:drop-shadow(0 1px 0 rgba(255,255,255,.5)) drop-shadow(0 6px 12px rgba(0,0,0,.35))}
.sxo-seal[data-finish="glow"]{filter:drop-shadow(0 0 10px color-mix(in srgb,var(--_accent) 60%,transparent))}
.sxo-seal[data-turn] svg{animation:sxo-turn 48s linear infinite}
@keyframes sxo-turn{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.sxo-seal[data-turn] svg{animation:none}}""",
    phone="unchanged; it scales with the viewport and never drops under 96px",
))

# ── 3. THE ID CARD ───────────────────────────────────────────────────
_add(_o(
    key="card-id", name="ID or member card",
    intent="a punched ID card: photo, name, role, a number",
    use_when="the team, the students, the members, the graduates. One card per "
             "real person, photo when the data has one, initials when it does "
             "not. Several cards sit in .sxo-card-row. The card number is one "
             "or two digits (the truth law reads longer numbers as claims).",
    aliases=("id card", "card-id", "member card", "student card", "staff card", "badge card", "id cards"),
    html="""<div class="sxo-card-row">
<article class="sxo sxo-card sxo-paper" data-sx-object="card-id">
  <span class="sxo-card-punch" aria-hidden="true"></span>
  <p class="sxo-card-kind sxo-label">Member · Spring cohort</p>
  <div class="sxo-card-photo"><span aria-hidden="true">JR</span></div>
  <h3 class="sxo-card-name">June Reyes</h3>
  <p class="sxo-card-role">Throws lidded jars</p>
  <p class="sxo-card-no sxo-label">No. 42</p>
</article>
</div>""",
    css=""".sxo-card-row{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:clamp(1rem,2vw,1.5rem)}
.sxo-card{position:relative;display:flex;flex-direction:column;align-items:center;text-align:center;gap:.35rem;
  padding:2.4rem 1.1rem 1.1rem;border-radius:14px;aspect-ratio:54/86;box-shadow:var(--_lift);
  border:1px solid var(--_line)}
.sxo-card::before{content:"";position:absolute;left:0;right:0;top:0;height:30%;border-radius:13px 13px 0 0;
  background:color-mix(in srgb,var(--_accent) 88%,transparent);z-index:0}
.sxo-card>*{flex-shrink:0}
.sxo-card[data-finish="metal"]::before{background:var(--_metal)}
.sxo-card-row>.sxo-card{height:100%}
.sxo-card>*{position:relative;z-index:1}
.sxo-card-punch{position:absolute!important;top:12px;left:50%;width:46px;height:9px;transform:translateX(-50%);
  border-radius:9px;background:color-mix(in srgb,var(--_ink) 55%,rgba(0,0,0,.6));box-shadow:inset 0 1px 2px rgba(0,0,0,.6)}
.sxo-card-kind{color:var(--_paper);margin:0;font-size:11px}
.sxo-card-photo{width:62%;aspect-ratio:1;border-radius:50%;overflow:hidden;display:grid;place-items:center;margin:.5rem 0 .4rem;
  background:color-mix(in srgb,var(--_accent) 18%,var(--_paper));border:4px solid var(--_paper);box-shadow:0 6px 14px rgba(0,0,0,.18)}
.sxo-card-photo img{display:block;width:100%;height:100%;object-fit:cover}
.sxo-card-photo span{font-family:var(--_display);font-size:clamp(28px,3vw,40px);color:var(--_accent)}
.sxo-card-name{font-family:var(--_display);font-size:clamp(19px,1.6vw,23px);line-height:1.1;margin:0}
.sxo-card-role{margin:0;font-size:14px;color:color-mix(in srgb,var(--_ink) 72%,transparent)}
.sxo-card-no{margin:auto 0 0;padding-top:.6rem;border-top:1px dashed var(--_line);width:100%;font-variant-numeric:tabular-nums;font-size:11px;color:color-mix(in srgb,var(--_ink) 60%,transparent)}
@media (max-width:600px){.sxo-card-row{grid-template-columns:none;grid-auto-flow:column;grid-auto-columns:68%;
  overflow-x:auto;scroll-snap-type:x mandatory;padding-bottom:.75rem}
  .sxo-card{scroll-snap-align:start}}""",
    phone="the row becomes a swipeable strip, one and a half cards wide, scrolling inside itself",
))

# ── 4. THE TICKET ────────────────────────────────────────────────────
_add(_o(
    key="ticket", name="Tear-off ticket",
    intent="a ticket with a serial number and a stub you tear off to book",
    use_when="services, classes, events and sessions with a price and a time. "
             "One ticket per real offering; the stub is the booking link when "
             "booking is on. Several sit in .sxo-ticket-row. Serial numbers are "
             "one or two digits (No. 07): the truth law reads longer numbers as "
             "claims.",
    aliases=("ticket", "tickets", "ticket stub", "tear-off ticket", "take a number"),
    html="""<div class="sxo-ticket-row">
<article class="sxo sxo-ticket sxo-paper" data-sx-object="ticket">
  <div class="sxo-ticket-main">
    <p class="sxo-ticket-no sxo-label">No. 07</p>
    <h3 class="sxo-ticket-title">Intro to the wheel</h3>
    <p class="sxo-ticket-meta">3 hours · clay and firing included</p>
  </div>
  <a class="sxo-ticket-stub" href="#book"><span class="sxo-ticket-price">$85</span><span class="sxo-label">Book</span></a>
</article>
</div>""",
    css=""".sxo-ticket-row{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,330px),1fr));gap:clamp(1rem,2vw,1.4rem);
  filter:drop-shadow(0 14px 18px rgba(0,0,0,.22))}
.sxo-ticket{--stub:7.5rem;display:grid;grid-template-columns:1fr var(--stub);min-height:8.5rem;border-radius:6px;
  -webkit-mask:radial-gradient(circle 10px at calc(100% - var(--stub)) 0,rgba(0,0,0,0) 97%,rgba(0,0,0,1)) top/100% 51% no-repeat,
               radial-gradient(circle 10px at calc(100% - var(--stub)) 100%,rgba(0,0,0,0) 97%,rgba(0,0,0,1)) bottom/100% 51% no-repeat;
          mask:radial-gradient(circle 10px at calc(100% - var(--stub)) 0,rgba(0,0,0,0) 97%,rgba(0,0,0,1)) top/100% 51% no-repeat,
               radial-gradient(circle 10px at calc(100% - var(--stub)) 100%,rgba(0,0,0,0) 97%,rgba(0,0,0,1)) bottom/100% 51% no-repeat}
.sxo-row-tilt>.sxo-ticket:nth-child(odd){transform:rotate(-.8deg)}
.sxo-row-tilt>.sxo-ticket:nth-child(even){transform:rotate(.6deg)}
.sxo-ticket-main{padding:1.1rem 1.2rem;display:flex;flex-direction:column;gap:.3rem}
.sxo-ticket-no{color:var(--_accent);margin:0;font-variant-numeric:tabular-nums}
.sxo-ticket-title{font-family:var(--_display);font-size:clamp(20px,1.7vw,25px);line-height:1.08;margin:0}
.sxo-ticket-meta{margin:auto 0 0;font-size:14px;color:color-mix(in srgb,var(--_ink) 70%,transparent)}
.sxo-ticket-stub{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.4rem;text-decoration:none;
  color:var(--_paper);background:var(--_accent);border-left:2px dashed color-mix(in srgb,var(--_paper) 70%,transparent);transition:background .25s}
.sxo-ticket-stub:hover,.sxo-ticket-stub:focus-visible{background:color-mix(in srgb,var(--_accent) 84%,rgba(0,0,0,1))}
.sxo-ticket[data-finish="metal"] .sxo-ticket-stub{background:var(--_metal);text-shadow:0 1px 0 rgba(0,0,0,.35)}
.sxo-ticket-price{font-family:var(--_display);font-size:clamp(26px,2.4vw,34px);line-height:1;font-variant-numeric:tabular-nums}
@media (max-width:600px){.sxo-ticket{--stub:6rem}.sxo-row-tilt>.sxo-ticket{transform:none!important}}""",
    phone="tickets stack one per row, the tilt straightens, the stub narrows and stays the tap target",
))

# ── 5. THE RECEIPT ───────────────────────────────────────────────────
_add(_o(
    key="receipt", name="Receipt",
    intent="a narrow printed receipt with dotted leaders and a torn edge",
    use_when="what is included, a price breakdown, a package's parts, a menu "
             "with prices. Line items and prices come from the data; a total "
             "only when the data carries it.",
    aliases=("receipt", "till receipt", "bill", "price slip"),
    html="""<div class="sxo sxo-receipt sxo-paper" data-sx-object="receipt">
  <p class="sxo-receipt-head">Wheelhouse Ceramics<span>Six-week wheel course</span></p>
  <ul class="sxo-receipt-lines">
    <li><span>Six Thursday classes</span><span>incl.</span></li>
    <li><span>25 lb of stoneware</span><span>incl.</span></li>
    <li><span>Glazes and two firings</span><span>incl.</span></li>
    <li><span>Open studio, Sundays</span><span>incl.</span></li>
  </ul>
  <p class="sxo-receipt-total"><span>Course</span><span>$340</span></p>
  <p class="sxo-receipt-foot">Thank you. Wear old clothes.</p>
</div>""",
    css=""".sxo-receipt{max-width:23rem;margin:0 auto;padding:1.6rem 1.4rem 2.6rem;font-family:var(--_label);font-size:15px;line-height:1.55;
  filter:drop-shadow(0 16px 20px rgba(0,0,0,.2));
  -webkit-mask:linear-gradient(rgba(0,0,0,1) 0 0) top/100% calc(100% - 12px) no-repeat,
               conic-gradient(from -45deg at bottom,rgba(0,0,0,0),rgba(0,0,0,1) 1deg 89deg,rgba(0,0,0,0) 90deg) bottom/18px 12px repeat-x;
          mask:linear-gradient(rgba(0,0,0,1) 0 0) top/100% calc(100% - 12px) no-repeat,
               conic-gradient(from -45deg at bottom,rgba(0,0,0,0),rgba(0,0,0,1) 1deg 89deg,rgba(0,0,0,0) 90deg) bottom/18px 12px repeat-x}
.sxo-receipt-head{text-align:center;text-transform:uppercase;letter-spacing:.12em;font-weight:700;margin:0 0 1rem;
  padding-bottom:.9rem;border-bottom:1px dashed var(--_line)}
.sxo-receipt-head span{display:block;font-weight:400;letter-spacing:.08em;font-size:12px;margin-top:.2rem}
.sxo-receipt-lines{list-style:none;margin:0;padding:0}
.sxo-receipt-lines li,.sxo-receipt-total{display:flex;align-items:baseline;gap:.5ch;margin:0 0 .35rem}
.sxo-receipt-lines li span:first-child,.sxo-receipt-total span:first-child{display:flex;flex:1;gap:.5ch;min-width:0}
.sxo-receipt-lines li span:first-child::after,.sxo-receipt-total span:first-child::after{content:"";flex:1;border-bottom:1px dotted var(--_line);transform:translateY(-.3em)}
.sxo-receipt-lines li span:last-child,.sxo-receipt-total span:last-child{font-variant-numeric:tabular-nums}
.sxo-receipt-total{margin-top:.9rem;padding-top:.8rem;border-top:2px solid var(--_ink);font-weight:700;font-size:17px;text-transform:uppercase;letter-spacing:.06em}
.sxo-receipt-foot{text-align:center;margin:1.2rem 0 0;font-size:13px;color:color-mix(in srgb,var(--_ink) 65%,transparent)}""",
    phone="unchanged; it is already phone-width",
))

# ── 6. THE SCHEDULE CARD ─────────────────────────────────────────────
_add(_o(
    key="schedule-card", name="Dated session card",
    intent="a class or session card: the date in a chip, the topics, the unit's name",
    use_when="a course's weeks, a program's sessions, an event's agenda. Real "
             "dates and topics only. Several sit in .sxo-session-grid; every "
             "other card is filled with the accent.",
    aliases=("schedule card", "schedule-card", "session card", "class card", "class cards", "curriculum", "agenda card"),
    html="""<div class="sxo-session-grid">
<article class="sxo sxo-session" data-sx-object="schedule-card">
  <p class="sxo-session-date"><span class="sxo-label">Sep 04</span><b>Week</b><strong>01</strong></p>
  <ul class="sxo-session-topics"><li>Wedging and centering</li><li>Opening a cylinder</li><li>Studio safety and clean-up</li></ul>
  <p class="sxo-session-unit sxo-label">Finding center</p>
</article>
</div>""",
    css=""".sxo-session-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:clamp(.9rem,1.6vw,1.2rem)}
.sxo-session{display:grid;grid-template-columns:auto 1fr;gap:.3rem 1.4rem;align-items:start;padding:1.15rem 1.35rem;border-radius:16px;
  border:1.5px solid color-mix(in srgb,currentColor 30%,transparent);background:color-mix(in srgb,currentColor 4%,transparent)}
.sxo-session-grid>.sxo-session:nth-child(4n+2),.sxo-session-grid>.sxo-session:nth-child(4n+3){background:var(--_accent);border-color:var(--_accent);color:var(--obj-paper,var(--sx-bg,Canvas))}
.sxo-session-date{grid-row:span 2;display:flex;flex-direction:column;align-items:center;margin:0;line-height:1;min-width:4.5rem;text-align:center}
.sxo-session-date .sxo-label{color:var(--_accent);font-size:11px;margin-bottom:.35rem}
.sxo-session-grid>.sxo-session:nth-child(4n+2) .sxo-session-date .sxo-label,.sxo-session-grid>.sxo-session:nth-child(4n+3) .sxo-session-date .sxo-label{color:inherit;opacity:.8}
.sxo-session-date b{font-family:var(--_display);font-weight:inherit;font-size:clamp(24px,2.2vw,30px);text-transform:uppercase}
.sxo-session-date strong{font-family:var(--_display);font-size:clamp(28px,2.6vw,36px);color:var(--_accent);font-variant-numeric:tabular-nums}
.sxo-session-grid>.sxo-session:nth-child(4n+2) .sxo-session-date strong,.sxo-session-grid>.sxo-session:nth-child(4n+3) .sxo-session-date strong{color:inherit}
.sxo-session-topics{margin:0;padding-left:1.05rem;font-size:15px;line-height:1.5}
.sxo-session-topics li::marker{color:currentColor}
.sxo-session-unit{grid-column:2;justify-self:end;margin:.4rem 0 0;font-size:11px;opacity:.85}
@media (max-width:600px){.sxo-session{grid-template-columns:1fr}
  .sxo-session-date{grid-row:auto;flex-direction:row;gap:.6rem;align-items:baseline;justify-content:flex-start;text-align:left}
  .sxo-session-date .sxo-label{margin:0}
  .sxo-session-unit{grid-column:1;justify-self:start}}""",
    phone="the date chip becomes one line across the top; topics stay 15px",
))

# ── 7. THE FRAME ─────────────────────────────────────────────────────
_add(_o(
    key="frame", name="Frame with a frame-break",
    intent="a picture frame (gilt, plain or offset) with one thing hanging over its edge",
    use_when="the owner's portrait, a hero photo, one proud piece. Needs a real "
             "photo. The frame-break is a small tag or plate that crosses the "
             "edge; it is the page's one allowed overlap.",
    aliases=("frame", "picture frame", "gilt frame", "gilded frame", "portrait frame", "frame-break"),
    html="""<figure class="sxo sxo-frame" data-sx-object="frame" data-frame="gilt" data-overlap-ok>
  <div class="sxo-frame-mat"><img src="https://example.com/portrait.jpg" alt="Mara Quill at the wheel, hands in wet clay" width="800" height="1000"></div>
  <span class="sxo-frame-tag" aria-hidden="true">Est. 2019</span>
  <figcaption class="sxo-frame-plate sxo-label">Mara Quill · Studio lead</figcaption>
</figure>""",
    css=""".sxo-frame{position:relative;margin:0 auto;max-width:30rem;padding-bottom:1.4rem}
.sxo-frame-mat{position:relative;overflow:hidden;aspect-ratio:4/5;background:color-mix(in srgb,var(--_paper) 80%,var(--_ink))}
.sxo-frame-mat img{display:block;width:100%;height:100%;object-fit:cover}
.sxo-frame[data-frame="gilt"] .sxo-frame-mat{border:clamp(14px,2vw,22px) solid transparent;
  border-image:linear-gradient(135deg,color-mix(in srgb,var(--_accent) 55%,rgba(255,255,255,1)),var(--_accent) 28%,
    color-mix(in srgb,var(--_accent) 55%,rgba(0,0,0,1)) 52%,color-mix(in srgb,var(--_accent) 70%,rgba(255,255,255,1)) 74%,var(--_accent)) 1;
  box-shadow:0 0 0 1px rgba(0,0,0,.35),inset 0 0 0 6px rgba(0,0,0,.22),0 30px 50px -20px rgba(0,0,0,.55)}
.sxo-frame[data-frame="plain"] .sxo-frame-mat{border:1px solid var(--_line);padding:clamp(12px,1.6vw,18px);background:var(--_paper);box-shadow:var(--_lift)}
.sxo-frame[data-frame="offset"] .sxo-frame-mat{overflow:visible}
.sxo-frame[data-frame="offset"] .sxo-frame-mat::before{content:"";position:absolute;inset:0;transform:translate(14px,14px);border:2px solid var(--_accent);z-index:-1}
.sxo-frame-tag{position:absolute;right:-6%;bottom:16%;z-index:2;padding:.55rem .9rem;transform:rotate(-7deg);
  background:var(--_accent);color:var(--_paper);font-family:var(--_label);font-size:12px;letter-spacing:.14em;text-transform:uppercase;
  border-radius:3px;box-shadow:0 10px 18px rgba(0,0,0,.3)}
.sxo-frame-tag::before{content:"";position:absolute;left:-36px;top:50%;width:40px;height:1.5px;background:color-mix(in srgb,var(--_ink) 60%,transparent);transform:rotate(-18deg);transform-origin:right}
.sxo-frame-plate{position:absolute;left:50%;bottom:0;z-index:2;transform:translateX(-50%);white-space:nowrap;padding:.5rem 1rem;
  background:var(--_ink);color:var(--_paper);box-shadow:0 8px 16px rgba(0,0,0,.25)}
@media (max-width:600px){.sxo-frame-tag{right:4%;bottom:20%}.sxo-frame-tag::before{display:none}
  .sxo-frame-plate{white-space:normal;text-align:center;max-width:90%}}""",
    phone="the tag tucks inside the frame so nothing crosses the screen edge; the plate wraps",
))

# ── 8. THE MARKER ────────────────────────────────────────────────────
_add(_o(
    key="marker", name="Marker annotation",
    intent="a hand-drawn circle, underline or strike over a word or a price",
    use_when="the one number or word a visitor must not miss: a price, a date, "
             "a promise. Once or twice a page. data-mark is circle, underline "
             "or strike.",
    aliases=("marker", "marker circle", "hand-drawn circle", "underline", "annotation", "pen mark"),
    html="""<span class="sxo sxo-mark" data-sx-object="marker" data-mark="circle">$340<svg class="sxo-mark-ink" viewBox="0 0 200 60" preserveAspectRatio="none" aria-hidden="true"><path pathLength="1" d="M12,33 C12,9 186,5 190,27 C194,52 44,59 16,45 C3,38 7,21 30,14"/></svg></span>
<!-- the other marks: underline d="M4,40 C52,32 120,36 196,28" and strike d="M4,34 C70,26 130,36 196,26" -->""",
    css=""".sxo-mark{position:relative;display:inline-block;white-space:nowrap;color:inherit}
.sxo-mark-ink{position:absolute;left:-14%;top:-30%;width:128%;height:160%;overflow:visible;pointer-events:none}
.sxo-mark[data-mark="underline"] .sxo-mark-ink{left:-2%;top:62%;width:104%;height:50%}
.sxo-mark[data-mark="strike"] .sxo-mark-ink{left:-4%;top:10%;width:108%;height:80%}
.sxo-mark-ink path{fill:none;stroke:var(--_accent);stroke-width:3;stroke-linecap:round;vector-effect:non-scaling-stroke;
  stroke-dasharray:1;stroke-dashoffset:0;transition:stroke-dashoffset .9s cubic-bezier(.6,0,.3,1) .25s}
.js .reveal:not(.in) .sxo-mark-ink path{stroke-dashoffset:1}
@media (prefers-reduced-motion:reduce){.sxo-mark-ink path{transition:none;stroke-dashoffset:0!important}}""",
    phone="unchanged; the mark scales with the word",
))

# ── 9. THE LETTERBOARD ───────────────────────────────────────────────
_add(_o(
    key="letterboard", name="Felt letterboard",
    intent="a felt letterboard in a wooden frame, white plastic letters in the grooves",
    use_when="prices, hours, today's specials, a short menu. Six to ten short "
             "rows; real prices from the data.",
    aliases=("letterboard", "letter board", "felt board", "menu board", "price board"),
    html="""<div class="sxo sxo-board" data-sx-object="letterboard">
  <div class="sxo-board-felt">
    <p class="sxo-board-row sxo-board-title">Open studio hours</p>
    <p class="sxo-board-row sxo-board-gap" aria-hidden="true"></p>
    <p class="sxo-board-row"><span>Tue to Thu</span><span>5 to 9 pm</span></p>
    <p class="sxo-board-row"><span>Saturday</span><span>10 to 4</span></p>
    <p class="sxo-board-row"><span>Sunday</span><span>12 to 5</span></p>
    <p class="sxo-board-row sxo-board-gap" aria-hidden="true"></p>
    <p class="sxo-board-row sxo-board-title">Day pass $25</p>
  </div>
</div>""",
    css=""".sxo-board{--_felt:color-mix(in srgb,var(--_ink) 10%,rgba(0,0,0,1));max-width:34rem;margin:0 auto;padding:clamp(10px,1.4vw,14px);border-radius:4px;
  background:repeating-linear-gradient(100deg,rgba(255,255,255,.05) 0 2px,transparent 2px 9px),
             linear-gradient(135deg,color-mix(in srgb,var(--_accent) 42%,rgba(0,0,0,1)),color-mix(in srgb,var(--_accent) 26%,rgba(0,0,0,1)));
  box-shadow:0 22px 44px -18px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.15)}
.sxo-board-felt{padding:1rem clamp(1rem,3vw,1.6rem);background:repeating-linear-gradient(180deg,var(--_felt) 0 25px,rgba(0,0,0,1) 25px 28px);
  box-shadow:inset 0 3px 12px rgba(0,0,0,.85);font-family:var(--_label);font-weight:700;font-size:15px;line-height:28px;
  letter-spacing:.16em;text-transform:uppercase;color:rgba(255,255,255,.93);text-shadow:0 1px 0 rgba(0,0,0,1),0 0 1px rgba(255,255,255,.4)}
.sxo-board-row{display:flex;justify-content:space-between;gap:1rem;margin:0;min-height:28px}
.sxo-board-row span:last-child{font-variant-numeric:tabular-nums;white-space:nowrap}
.sxo-board-row:nth-child(5n+3){transform:translateX(2px)}
.sxo-board-title{justify-content:center;text-align:center}
@media (max-width:600px){.sxo-board-felt{font-size:13px;letter-spacing:.1em}}""",
    phone="letters tighten a little; rows stay in their grooves",
))

# ── 10. THE CERTIFICATE ──────────────────────────────────────────────
_add(_o(
    key="certificate", name="Certificate",
    intent="a certificate with a double rule, corner ornaments and a seal",
    use_when="what a visitor earns: completion, a credential, a guarantee. "
             "Real program names only; the recipient line is the visitor's.",
    aliases=("certificate", "diploma", "credential", "award"),
    html="""<div class="sxo sxo-cert sxo-paper" data-sx-object="certificate">
  <p class="sxo-cert-kicker sxo-label">Certificate of completion</p>
  <h3 class="sxo-cert-title">Six weeks at the wheel</h3>
  <p class="sxo-cert-line">awarded to <span class="sxo-cert-blank">you, in six Thursdays</span></p>
  <p class="sxo-cert-meta">Wheelhouse Ceramics · Fall term</p>
</div>""",
    css=""".sxo-cert{position:relative;max-width:40rem;margin:0 auto;aspect-ratio:1.414;display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:.6rem;text-align:center;padding:clamp(2rem,6vw,3.5rem);border:1px solid var(--_accent);outline:4px double var(--_accent);outline-offset:-14px;box-shadow:var(--_lift)}
.sxo-cert::before{content:"";position:absolute;inset:24px;pointer-events:none;--c:var(--_accent);
  background:linear-gradient(var(--c),var(--c)) top left/38px 2px no-repeat,linear-gradient(var(--c),var(--c)) top left/2px 38px no-repeat,
    linear-gradient(var(--c),var(--c)) top right/38px 2px no-repeat,linear-gradient(var(--c),var(--c)) top right/2px 38px no-repeat,
    linear-gradient(var(--c),var(--c)) bottom left/38px 2px no-repeat,linear-gradient(var(--c),var(--c)) bottom left/2px 38px no-repeat,
    linear-gradient(var(--c),var(--c)) bottom right/38px 2px no-repeat,linear-gradient(var(--c),var(--c)) bottom right/2px 38px no-repeat}
.sxo-cert::after{content:"";position:absolute;top:18px;left:50%;width:10px;height:10px;transform:translateX(-50%) rotate(45deg);background:var(--_accent)}
.sxo-cert-kicker{color:var(--_accent);margin:0}
.sxo-cert-title{font-family:var(--_display);font-size:clamp(28px,3.6vw,46px);line-height:1.05;margin:0}
.sxo-cert-line{margin:.3rem 0 0;font-style:italic}
.sxo-cert-blank{display:inline-block;font-style:normal;min-width:12ch;border-bottom:1px solid var(--_ink);padding:0 .4em .1em}
.sxo-cert-meta{margin:.4rem 0 0;font-size:14px;color:color-mix(in srgb,var(--_ink) 65%,transparent)}
.sxo-cert .sxo-seal{position:absolute;right:6%;bottom:8%;width:clamp(72px,9vw,104px)}
@media (max-width:600px){.sxo-cert{aspect-ratio:auto;outline-offset:-10px}.sxo-cert .sxo-seal{position:relative;right:auto;bottom:auto;margin-top:.6rem}}""",
    phone="the certificate grows to its content; the seal sits under the text",
))

# ── 11. THE INDEX CARD ───────────────────────────────────────────────
_add(_o(
    key="index-card", name="Ruled index card",
    intent="a ruled index card with a red top line, handwritten-plain",
    use_when="steps of a method, tips, a recipe, short answers to questions. "
             "Several sit in .sxo-index-row and tilt slightly.",
    aliases=("index card", "index-card", "recipe card", "note card", "cards"),
    html="""<div class="sxo-index-row">
<article class="sxo sxo-index sxo-paper" data-sx-object="index-card">
  <h3 class="sxo-index-title">Step two: open</h3>
  <p>Press your thumbs into the center and stop a finger's width from the bottom. Wet hands, slow wheel.</p>
</article>
</div>""",
    css=""".sxo-index-row{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr));gap:clamp(1rem,2vw,1.6rem)}
.sxo-index{--lh:1.65rem;padding:1rem 1.2rem 1.2rem;box-shadow:var(--_lift);font-size:15px;line-height:var(--lh);
  background-image:linear-gradient(transparent calc(var(--lh) * 1.7),color-mix(in srgb,var(--_accent) 70%,transparent) calc(var(--lh) * 1.7) calc(var(--lh) * 1.7 + 2px),transparent 0),
    repeating-linear-gradient(transparent 0 calc(var(--lh) - 1px),color-mix(in srgb,var(--_ink) 14%,transparent) calc(var(--lh) - 1px) var(--lh)),var(--_grain);
  background-position:0 .2rem,0 calc(1rem - 2px),0 0;background-color:var(--_paper)}
.sxo-index-row>.sxo-index:nth-child(3n+1){transform:rotate(-1deg)}
.sxo-index-row>.sxo-index:nth-child(3n+2){transform:rotate(.8deg) translateY(6px)}
.sxo-index-title{font-family:var(--_display);font-size:19px;line-height:var(--lh);margin:0 0 calc(var(--lh) * .7)}
.sxo-index p{margin:0}
@media (max-width:600px){.sxo-index-row>.sxo-index{transform:none!important}}""",
    phone="cards stack straight; the ruling stays on the text lines",
))

# ── 12. THE INSTANT PHOTO ────────────────────────────────────────────
_add(_o(
    key="polaroid", name="Instant photo with tape",
    intent="an instant photo taped to the page, a short caption in the border",
    use_when="real photos of the work, the people, the room, a client with "
             "their words. Needs real photos. Several sit in .sxo-pola-row.",
    aliases=("polaroid", "instant photo", "taped photo", "snapshot"),
    html="""<div class="sxo-pola-row">
<figure class="sxo sxo-pola sxo-paper" data-sx-object="polaroid" data-overlap-ok>
  <span class="sxo-pola-tape" aria-hidden="true"></span>
  <img src="https://example.com/bowl.jpg" alt="A celadon bowl, still wet from the glaze" width="600" height="600">
  <figcaption>June's first bowl, week three</figcaption>
</figure>
</div>""",
    css=""".sxo-pola-row{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,230px),1fr));gap:clamp(1.2rem,2.4vw,2rem);padding:1rem .5rem}
.sxo-pola{position:relative;margin:0;padding:.75rem .75rem 0;box-shadow:var(--_lift)}
.sxo-pola img{display:block;width:100%;height:auto;aspect-ratio:1;object-fit:cover}
.sxo-pola figcaption{padding:.8rem .2rem 1rem;font-family:var(--_label);font-size:14px;line-height:1.35;text-align:center}
.sxo-pola-tape{position:absolute;top:-12px;left:50%;width:42%;height:26px;transform:translateX(-50%) rotate(-3deg);
  background:color-mix(in srgb,var(--_accent) 26%,rgba(255,255,255,.55));box-shadow:0 1px 2px rgba(0,0,0,.12);opacity:.92}
.sxo-pola-row>.sxo-pola:nth-child(odd){transform:rotate(-1.6deg)}
.sxo-pola-row>.sxo-pola:nth-child(even){transform:rotate(1.2deg)}
@media (max-width:600px){.sxo-pola-row>.sxo-pola{transform:rotate(0)}}""",
    phone="photos stack, tilt removed, tape kept",
))

# ── 13. THE BOARDING PASS ────────────────────────────────────────────
_add(_o(
    key="boarding-pass", name="Boarding pass",
    intent="a boarding pass from where the visitor is to where the work takes them",
    use_when="a transformation (before and after), a retreat or trip, a "
             "program with a start and an end. The route is two short words "
             "from the owner's own language; dates from the data.",
    aliases=("boarding pass", "boarding-pass", "pass", "travel pass"),
    html="""<article class="sxo sxo-pass sxo-paper" data-sx-object="boarding-pass">
  <div class="sxo-pass-main">
    <p class="sxo-pass-kicker sxo-label">Boarding pass · Fall term</p>
    <p class="sxo-pass-route"><span><b>LMP</b>a lump of clay</span><svg viewBox="0 0 60 16" aria-hidden="true"><path d="M2 8h50M44 2l8 6-8 6"/></svg><span><b>BWL</b>your first bowl</span></p>
    <dl class="sxo-pass-meta"><div><dt>Departs</dt><dd>Sep 04</dd></div><div><dt>Duration</dt><dd>6 weeks</dd></div><div><dt>Seat</dt><dd>Wheel 07</dd></div></dl>
  </div>
  <a class="sxo-pass-stub" href="#book"><span class="sxo-label">Board</span><span class="sxo-pass-code" aria-hidden="true"></span></a>
</article>""",
    css=""".sxo-pass{--stub:8rem;display:grid;grid-template-columns:1fr var(--stub);max-width:44rem;margin:0 auto;border-radius:14px;
  filter:drop-shadow(0 18px 22px rgba(0,0,0,.25));
  -webkit-mask:radial-gradient(circle 12px at calc(100% - var(--stub)) 0,rgba(0,0,0,0) 97%,rgba(0,0,0,1)) top/100% 51% no-repeat,
               radial-gradient(circle 12px at calc(100% - var(--stub)) 100%,rgba(0,0,0,0) 97%,rgba(0,0,0,1)) bottom/100% 51% no-repeat;
          mask:radial-gradient(circle 12px at calc(100% - var(--stub)) 0,rgba(0,0,0,0) 97%,rgba(0,0,0,1)) top/100% 51% no-repeat,
               radial-gradient(circle 12px at calc(100% - var(--stub)) 100%,rgba(0,0,0,0) 97%,rgba(0,0,0,1)) bottom/100% 51% no-repeat}
.sxo-pass-main{padding:1.3rem 1.5rem 1.4rem;display:flex;flex-direction:column;gap:1rem}
.sxo-pass-kicker{margin:0;color:var(--_accent)}
.sxo-pass-route{display:flex;align-items:center;gap:1rem;margin:0}
.sxo-pass-route span{display:flex;flex-direction:column;font-size:13px;color:color-mix(in srgb,var(--_ink) 70%,transparent)}
.sxo-pass-route b{font-family:var(--_display);font-size:clamp(34px,4vw,50px);line-height:1;color:var(--_ink);letter-spacing:.02em}
.sxo-pass-route svg{flex:1;max-width:120px;height:16px;stroke:var(--_accent);stroke-width:2;fill:none}
.sxo-pass-meta{display:flex;gap:1.6rem;margin:0;flex-wrap:wrap}
.sxo-pass-meta dt{font-family:var(--_label);font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:color-mix(in srgb,var(--_ink) 60%,transparent)}
.sxo-pass-meta dd{margin:.15rem 0 0;font-weight:700;font-variant-numeric:tabular-nums}
.sxo-pass-stub{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.8rem;text-decoration:none;color:var(--_paper);
  background:var(--_accent);border-left:2px dashed color-mix(in srgb,var(--_paper) 70%,transparent)}
.sxo-pass[data-finish="metal"] .sxo-pass-stub{background:var(--_metal);text-shadow:0 1px 0 rgba(0,0,0,.35)}
.sxo-pass-code{width:60%;height:3.2rem;background:repeating-linear-gradient(90deg,var(--_paper) 0 2px,transparent 2px 4px,var(--_paper) 4px 5px,transparent 5px 8px,var(--_paper) 8px 11px,transparent 11px 13px)}
@media (max-width:600px){.sxo-pass{grid-template-columns:1fr;-webkit-mask:none;mask:none}
  .sxo-pass-stub{flex-direction:row;padding:.9rem;border-left:0;border-top:2px dashed color-mix(in srgb,var(--_paper) 70%,transparent)}
  .sxo-pass-code{width:40%;height:2rem}}""",
    phone="the stub moves under the pass and tears along the top instead",
))

# ── 14. THE TYPED CAPTION ────────────────────────────────────────────
_add(_o(
    key="typed-caption", name="Typed caption",
    intent="a caption that types itself out with a blinking cursor, cycling a few lines",
    use_when="the page's one living detail: a countdown line, what is next, a "
             "short promise. Two or three short phrases from the data or the "
             "owner's words, separated by | in data-phrases.",
    aliases=("typed caption", "typed-caption", "typewriter", "typing caption", "typed line"),
    html="""<p class="sxo sxo-typed sxo-label" data-sx-object="typed-caption" data-phrases="The kiln opens Friday...|Fall term starts Sep 04...|Six wheels left...">
  <span class="sxo-sr">The kiln opens Friday. Fall term starts Sep 04. Six wheels left.</span>
  <span class="sxo-typed-text" aria-hidden="true">The kiln opens Friday...</span>
</p>""",
    css=""".sxo-typed{margin:0;font-size:clamp(13px,1.1vw,15px);letter-spacing:.16em;color:var(--_accent)}
.sxo-typed-text::after{content:"_";margin-left:.1em;animation:sxo-blink 1s steps(1) infinite}
@keyframes sxo-blink{50%{opacity:0}}
@media (prefers-reduced-motion:reduce){.sxo-typed-text::after{animation:none}}""",
    js="""document.querySelectorAll('.sxo-typed[data-phrases]').forEach(function(el){var t=el.querySelector('.sxo-typed-text');if(!t||window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;var ph=el.getAttribute('data-phrases').split('|');var i=0,j=ph[0].length,dir=-1;function step(){j+=dir;t.textContent=ph[i].slice(0,Math.max(0,j));if(dir<0&&j<=0){i=(i+1)%ph.length;dir=1;setTimeout(step,450);return;}if(dir>0&&j>=ph[i].length){dir=-1;setTimeout(step,2600);return;}setTimeout(step,dir>0?65:32);}setTimeout(step,2600);});""",
    phone="unchanged",
))

# ── 15. THE INSTALLMENTS ─────────────────────────────────────────────
_add(_o(
    key="installments", name="Price split into tiles",
    intent="one price, then the same price split into equal tiles you can count",
    use_when="a deposit or a payment plan the DATA spells out: the full price, "
             "the number of payments and each amount. Never compute an amount; "
             "every figure comes from the data.",
    aliases=("installments", "payment plan", "price split", "split payments", "tuition tiles"),
    html="""<div class="sxo sxo-split" data-sx-object="installments">
  <p class="sxo-split-full"><span class="sxo-label">The course</span><b>$340</b></p>
  <p class="sxo-split-or sxo-label">or four payments of</p>
  <ol class="sxo-split-tiles"><li><b>$85</b><span>today</span></li><li><b>$85</b><span>Sep 18</span></li><li><b>$85</b><span>Oct 02</span></li><li><b>$85</b><span>Oct 16</span></li></ol>
</div>""",
    css=""".sxo-split{display:flex;flex-direction:column;align-items:center;gap:1rem;text-align:center}
.sxo-split-full{display:flex;flex-direction:column;align-items:center;gap:.35rem;margin:0}
.sxo-split-full b{font-family:var(--_display);font-size:clamp(48px,6vw,84px);line-height:.95;font-variant-numeric:tabular-nums}
.sxo-split-or{margin:0;color:color-mix(in srgb,currentColor 65%,transparent)}
.sxo-split-tiles{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.6rem;width:min(100%,34rem)}
.sxo-split-tiles li{display:flex;flex-direction:column;gap:.25rem;padding:.9rem .4rem;border-radius:10px;border:1.5px solid color-mix(in srgb,var(--_accent) 55%,transparent);
  background:color-mix(in srgb,var(--_accent) 10%,transparent)}
.sxo-split[data-finish="metal"] .sxo-split-tiles li:first-child{background:var(--_metal);text-shadow:0 1px 0 rgba(0,0,0,.35)}
.sxo-split-tiles li:first-child{background:var(--_accent);color:var(--obj-paper,var(--sx-bg,Canvas));border-color:var(--_accent)}
.sxo-split-tiles b{font-family:var(--_display);font-size:clamp(20px,2vw,28px);font-variant-numeric:tabular-nums}
.sxo-split-tiles span{font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.85}
@media (max-width:420px){.sxo-split-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}}""",
    phone="four tiles become two rows of two under 420px",
))

# ── 16. THE SHAPED EDGE ──────────────────────────────────────────────
_add(_o(
    key="edge", name="Shaped section edge",
    intent="a section whose bottom edge is an arc, a wave, a scallop, a tear or a slant",
    use_when="one or two seams between big color fields, never every section. "
             "Put the classes on a <section>; the next section's background "
             "shows through the shape.",
    aliases=("edge", "shaped edge", "arc edge", "wave edge", "wavy edge", "torn edge", "slant edge", "curved seam"),
    html="""<section class="sxo sxo-edge" data-sx-object="edge" data-edge="arc" data-overlap-ok>
  <div class="sxo-edge-inner"><h2>The section above the seam</h2><p>Its bottom edge curves into the next section.</p></div>
</section>""",
    css=""".sxo-edge{--d:clamp(28px,5vw,64px);position:relative;z-index:1;margin-bottom:calc(var(--d) * -1);padding-bottom:calc(var(--d) + 2rem);background:var(--_paper);color:var(--_ink)}
.sxo-edge[data-edge="arc"]{clip-path:ellipse(75% 100% at 50% 0)}
.sxo-edge[data-edge="slant"]{clip-path:polygon(0 0,100% 0,100% calc(100% - var(--d)),0 100%)}
.sxo-edge[data-edge="scallop"]{--r:22px;
  -webkit-mask:linear-gradient(rgba(0,0,0,1) 0 0) top/100% calc(100% - var(--r)) no-repeat,radial-gradient(var(--r) at 50% 0,rgba(0,0,0,1) 97%,rgba(0,0,0,0)) bottom/calc(var(--r) * 2) var(--r) repeat-x;
          mask:linear-gradient(rgba(0,0,0,1) 0 0) top/100% calc(100% - var(--r)) no-repeat,radial-gradient(var(--r) at 50% 0,rgba(0,0,0,1) 97%,rgba(0,0,0,0)) bottom/calc(var(--r) * 2) var(--r) repeat-x}
.sxo-edge[data-edge="torn"]{
  -webkit-mask:linear-gradient(rgba(0,0,0,1) 0 0) top/100% calc(100% - 14px) no-repeat,conic-gradient(from -40deg at bottom,rgba(0,0,0,0),rgba(0,0,0,1) 1deg 79deg,rgba(0,0,0,0) 80deg) bottom/23px 14px repeat-x;
          mask:linear-gradient(rgba(0,0,0,1) 0 0) top/100% calc(100% - 14px) no-repeat,conic-gradient(from -40deg at bottom,rgba(0,0,0,0),rgba(0,0,0,1) 1deg 79deg,rgba(0,0,0,0) 80deg) bottom/23px 14px repeat-x}
.sxo-edge[data-edge="wave"]{--s:clamp(12px,2.2vw,24px);--R:calc(var(--s) * 1.118);
  -webkit-mask:radial-gradient(var(--R) at 50% calc(100% - var(--s) * 1.5),rgba(0,0,0,1) 99%,rgba(0,0,0,0) 101%) calc(50% - 2 * var(--s)) 0/calc(4 * var(--s)) 100%,
               radial-gradient(var(--R) at 50% calc(100% + var(--s) * .5),rgba(0,0,0,0) 99%,rgba(0,0,0,1) 101%) 50% calc(100% - var(--s))/calc(4 * var(--s)) 100% repeat-x;
          mask:radial-gradient(var(--R) at 50% calc(100% - var(--s) * 1.5),rgba(0,0,0,1) 99%,rgba(0,0,0,0) 101%) calc(50% - 2 * var(--s)) 0/calc(4 * var(--s)) 100%,
               radial-gradient(var(--R) at 50% calc(100% + var(--s) * .5),rgba(0,0,0,0) 99%,rgba(0,0,0,1) 101%) 50% calc(100% - var(--s))/calc(4 * var(--s)) 100% repeat-x}
.sxo-edge+*{padding-top:calc(var(--d,48px) + 2rem)}
@media (max-width:600px){.sxo-edge[data-edge="arc"]{clip-path:ellipse(110% 100% at 50% 0)}}""",
    phone="the arc flattens so it never cuts into text on a narrow screen",
))


# ═════════════════════════════════════════════════════════════════════
# THE LIBRARY GROWS (2026-10-04, Kevin: "grow the builder's own layout
# and object library"). Each object below is one I reached for by hand on
# the sites I built myself and the builder had no source for:
#   marquee   Rivers' photo strip, MaCnificent's style band, the
#             marketing site's trade ticker (all three sites)
#   times     Rivers' "when we gather" strip, the next one lit
#   hours     MaCnificent's hours table, today marked, the open-now light
#   timeline  MaCnificent's aftercare stops; the numbered steps on
#             Rivers and the marketing site
#   panels    Rivers' expanding photo panels (ministries)
#   mosaic    Rivers' journey mosaic, one tall photo and three small
#   quote     Rivers' pull quote with the giant mark
#   dock      MaCnificent's phone booking dock; the marketing site's
#             floating action
#   faq       the questions on Rivers' give page and the marketing site
#   stats     the marketing site's count-up strip
# The times and the hours tell the time in the business's own timezone
# (data-tz), never the visitor's guess, and say nothing when they can't.
# ═════════════════════════════════════════════════════════════════════

# A small clock read in the business's timezone: {day: 0-6 (Sunday 0),
# min: minutes since midnight}. Shared by the times strip and the hours.
_CLOCK_JS = ("function now(tz){var o={weekday:'short',hour:'2-digit',minute:'2-digit',hourCycle:'h23'},p;"
             "try{if(tz)o.timeZone=tz;p=new Intl.DateTimeFormat('en-US',o).formatToParts(new Date());}"
             "catch(e){delete o.timeZone;p=new Intl.DateTimeFormat('en-US',o).formatToParts(new Date());}"
             "var g=function(t){for(var i=0;i<p.length;i++)if(p[i].type===t)return p[i].value;return '';};"
             "return {day:['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].indexOf(g('weekday')),"
             "min:(+g('hour'))%24*60+(+g('minute'))};}"
             "function mins(s){var p=String(s||'').split(':');return p.length<2?null:(+p[0])*60+(+p[1]);}")

# ── 17. THE MARQUEE ──────────────────────────────────────────────────
_add(_o(
    key="marquee", name="Drifting marquee band",
    intent="a band of words drifting sideways across the page, a mark between each",
    use_when="the names of real services, styles, ministries or classes from the "
             "data, five to ten short ones, as a seam between two big sections. "
             "Once a page. The visible run is repeated twice for the loop and "
             "hidden from readers; the full list is in the sxo-sr line.",
    aliases=("marquee band", "ticker band", "scrolling band", "drifting band"),
    html="""<div class="sxo sxo-marquee" data-sx-object="marquee">
  <p class="sxo-sr">Wheel throwing, hand building, glaze nights, open studio, kids' clay camp</p>
  <div class="sxo-marquee-track" aria-hidden="true">
    <ul class="sxo-marquee-run"><li>Wheel throwing</li><li>Hand building</li><li>Glaze nights</li><li>Open studio</li><li>Kids' clay camp</li></ul>
    <ul class="sxo-marquee-run"><li>Wheel throwing</li><li>Hand building</li><li>Glaze nights</li><li>Open studio</li><li>Kids' clay camp</li></ul>
  </div>
</div>""",
    css=""".sxo-marquee{position:relative;overflow:hidden;padding:clamp(.9rem,1.6vw,1.3rem) 0;background:var(--_accent);color:var(--_paper);
  -webkit-mask:linear-gradient(90deg,rgba(0,0,0,0),rgba(0,0,0,1) 5%,rgba(0,0,0,1) 95%,rgba(0,0,0,0));
          mask:linear-gradient(90deg,rgba(0,0,0,0),rgba(0,0,0,1) 5%,rgba(0,0,0,1) 95%,rgba(0,0,0,0))}
.sxo-marquee-track{display:flex;width:max-content;animation:sxo-drift var(--speed,46s) linear infinite}
.sxo-marquee:hover .sxo-marquee-track{animation-play-state:paused}
.sxo-marquee-run{display:flex;align-items:center;flex-shrink:0;list-style:none;margin:0;padding:0}
.sxo-marquee-run li{display:flex;align-items:center;white-space:nowrap;font-family:var(--_display);font-size:clamp(22px,2.6vw,38px);line-height:1.1}
.sxo-marquee-run li::after{content:"\\2726";font-size:.45em;margin:0 clamp(1rem,2.4vw,2rem);opacity:.7}
@keyframes sxo-drift{to{transform:translateX(-50%)}}
@media (max-width:600px){.sxo-marquee-run li{font-size:21px}}
@media (prefers-reduced-motion:reduce){.sxo-marquee{-webkit-mask:none;mask:none}
  .sxo-marquee-track{animation:none;width:auto;justify-content:center;padding:0 1rem}
  .sxo-marquee-run{flex-wrap:wrap;justify-content:center;row-gap:.6rem}
  .sxo-marquee-run+.sxo-marquee-run{display:none}}""",
    phone="the words drop to 21px and keep drifting; with reduced motion the band stands still and wraps",
))

# ── 18. THE TIMES STRIP ──────────────────────────────────────────────
_add(_o(
    key="times-strip", name="Weekly times strip",
    intent="a ruled row of the regular weekly times, the next one lit",
    use_when="gatherings, services, classes or open hours that repeat every "
             "week: the day, the time and what happens, exactly as the data "
             "or the owner states them. Two to six items. Each item carries "
             "data-day (0 Sunday to 6 Saturday) and data-time (24-hour HH:MM) "
             "so the strip can light the next one; data-tz on the root is the "
             "business's timezone from THE REAL DATA, or leave it off.",
    aliases=("times strip", "service times", "gathering times", "weekly times",
             "class times", "schedule strip", "weekly schedule"),
    html="""<div class="sxo sxo-times" data-sx-object="times-strip" data-tz="America/Chicago">
  <p class="sxo-times-head sxo-label">Every week at the studio</p>
  <ol class="sxo-times-row">
    <li class="sxo-times-item" data-day="2" data-time="17:00"><span class="sxo-label">Tuesday</span><b>5:00<small>pm</small></b><span class="sxo-times-name">Open studio</span><span class="sxo-times-next"></span></li>
    <li class="sxo-times-item" data-day="4" data-time="18:00"><span class="sxo-label">Thursday</span><b>6:00<small>pm</small></b><span class="sxo-times-name">Wheel class</span><span class="sxo-times-next"></span></li>
    <li class="sxo-times-item" data-day="6" data-time="10:00"><span class="sxo-label">Saturday</span><b>10:00<small>am</small></b><span class="sxo-times-name">Family clay</span><span class="sxo-times-next"></span></li>
    <li class="sxo-times-item" data-day="0" data-time="12:00"><span class="sxo-label">Sunday</span><b>12:00<small>pm</small></b><span class="sxo-times-name">Open studio</span><span class="sxo-times-next"></span></li>
  </ol>
</div>""",
    css=""".sxo-times-head{margin:0 0 .9rem;color:color-mix(in srgb,currentColor 65%,transparent)}
.sxo-times-row{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));
  border-top:1.5px solid currentColor;border-bottom:1px solid color-mix(in srgb,currentColor 25%,transparent)}
.sxo-times-item{display:flex;flex-direction:column;gap:.35rem;padding:1.1rem 1.2rem 1.2rem;border-left:1px solid color-mix(in srgb,currentColor 18%,transparent);transition:background-color .4s}
.sxo-times-item:first-child{border-left:0}
.sxo-times-item b{font-family:var(--_display);font-weight:inherit;font-size:clamp(34px,3.6vw,52px);line-height:1;font-variant-numeric:tabular-nums}
.sxo-times-item small{font-size:.36em;margin-left:.2em;letter-spacing:.08em;text-transform:uppercase}
.sxo-times-name{font-size:15px}
.sxo-times-next{min-height:1.2em;font-family:var(--_label);font-size:11px;letter-spacing:.14em;text-transform:uppercase}
.sxo-times-item.is-next{background:var(--_accent);color:var(--_paper)}
.sxo-times-item.is-next .sxo-label{color:inherit}
@media (max-width:600px){.sxo-times-row{grid-template-columns:repeat(2,minmax(0,1fr))}
  .sxo-times-item{border-top:1px solid color-mix(in srgb,currentColor 18%,transparent);padding:.9rem .9rem 1rem}
  .sxo-times-item:nth-child(odd){border-left:0}
  .sxo-times-item:nth-child(-n+2){border-top:0}}
@media (prefers-reduced-motion:reduce){.sxo-times-item{transition:none}}""",
    js="(function(){" + _CLOCK_JS + "document.querySelectorAll('.sxo-times').forEach(function(el){"
       "var tz=el.getAttribute('data-tz'),n=now(tz),best=null,wait=1e9;if(n.day<0)return;"
       "el.querySelectorAll('.sxo-times-item[data-day][data-time]').forEach(function(it){"
       "var m=mins(it.getAttribute('data-time'));if(m===null)return;"
       "var a=((+it.getAttribute('data-day')-n.day+7)%7)*1440+m-n.min;if(a<0)a+=10080;"
       "if(a<wait){wait=a;best=it;}});if(!best)return;best.classList.add('is-next');"
       "var tag=best.querySelector('.sxo-times-next');if(!tag)return;var d=Math.floor((n.min+wait)/1440),o={month:'short',day:'numeric'};"
       "try{if(tz)o.timeZone=tz;tag.textContent=d===0?'Next \\u00b7 today':d===1?'Next \\u00b7 tomorrow':"
       "'Next \\u00b7 '+new Intl.DateTimeFormat('en-US',o).format(new Date(Date.now()+d*864e5));}catch(e){tag.textContent='Next';}});})();",
    phone="the row becomes two columns of two; the next one stays lit",
))

# ── 19. THE HOURS ────────────────────────────────────────────────────
_add(_o(
    key="hours-card", name="Hours card with an open-now light",
    intent="a week of opening hours on a card, today marked, a light that says open now",
    use_when="the business's opening hours. Every row is a real day from THE "
             "REAL DATA's weekly hours (or the hours the owner stated); "
             "data-day is 0 Sunday to 6 Saturday, an open day carries "
             "data-open and data-close (24-hour HH:MM), a closed day carries "
             "data-closed. data-tz on the root is the business's timezone. "
             "The light stays hidden until it can tell the truth.",
    aliases=("hours card", "hours table", "opening hours", "open-now light", "open now light"),
    html="""<div class="sxo sxo-hours sxo-paper" data-sx-object="hours-card" data-tz="America/Chicago">
  <p class="sxo-hours-head"><span class="sxo-label">Studio hours</span><span class="sxo-hours-now" hidden><i aria-hidden="true"></i><span></span></span></p>
  <table class="sxo-hours-table">
    <caption class="sxo-sr">Studio hours, by day</caption>
    <tbody>
      <tr data-day="1" data-closed><th scope="row">Monday</th><td>Closed</td></tr>
      <tr data-day="2" data-open="17:00" data-close="21:00"><th scope="row">Tuesday</th><td>5 to 9 pm</td></tr>
      <tr data-day="3" data-closed><th scope="row">Wednesday</th><td>Closed</td></tr>
      <tr data-day="4" data-open="17:00" data-close="21:00"><th scope="row">Thursday</th><td>5 to 9 pm</td></tr>
      <tr data-day="5" data-closed><th scope="row">Friday</th><td>Closed</td></tr>
      <tr data-day="6" data-open="10:00" data-close="16:00"><th scope="row">Saturday</th><td>10 am to 4 pm</td></tr>
      <tr data-day="0" data-open="12:00" data-close="17:00"><th scope="row">Sunday</th><td>12 to 5 pm</td></tr>
    </tbody>
  </table>
</div>""",
    css=""".sxo-hours{max-width:26rem;padding:clamp(1.2rem,3vw,1.8rem);border-radius:14px;box-shadow:var(--_lift)}
.sxo-hours-head{display:flex;justify-content:space-between;align-items:center;gap:1rem;margin:0 0 .7rem}
.sxo-hours-now{display:inline-flex;align-items:center;gap:.45rem;font-family:var(--_label);font-size:12px;letter-spacing:.1em;text-transform:uppercase}
.sxo-hours-now[hidden]{display:none}
.sxo-hours-now i{width:9px;height:9px;border-radius:50%;background:color-mix(in srgb,var(--_ink) 35%,transparent)}
.sxo-hours-now.is-open i{background:var(--_accent);box-shadow:0 0 0 4px color-mix(in srgb,var(--_accent) 25%,transparent)}
.sxo-hours-table{width:100%;border-collapse:collapse;font-size:15px}
.sxo-hours-table th,.sxo-hours-table td{padding:.55rem 0;border-bottom:1px dashed var(--_line);text-align:left;font-weight:400}
.sxo-hours-table tr:last-child th,.sxo-hours-table tr:last-child td{border-bottom:0}
.sxo-hours-table td{text-align:right;font-variant-numeric:tabular-nums}
.sxo-hours-table tr.is-today th,.sxo-hours-table tr.is-today td{font-weight:700;color:var(--_accent)}
.sxo-hours-table tr.is-today th::after{content:"Today";margin-left:.6rem;padding:.12rem .45rem;border-radius:999px;vertical-align:.12em;
  font-family:var(--_label);font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;background:var(--_accent);color:var(--_paper)}
@media (max-width:600px){.sxo-hours{max-width:none}}""",
    js="(function(){" + _CLOCK_JS + "document.querySelectorAll('.sxo-hours').forEach(function(el){"
       "var n=now(el.getAttribute('data-tz'));if(n.day<0)return;"
       "var row=el.querySelector('tr[data-day=\"'+n.day+'\"]');if(!row)return;row.classList.add('is-today');"
       "var light=el.querySelector('.sxo-hours-now'),o=mins(row.getAttribute('data-open')),c=mins(row.getAttribute('data-close'));"
       "if(!light||((o===null||c===null)&&!row.hasAttribute('data-closed')))return;"
       "var open=o!==null&&c!==null&&(c>o?(n.min>=o&&n.min<c):(n.min>=o||n.min<c));"
       "light.querySelector('span').textContent=open?'Open now':(o===null?'Closed today':'Closed now');"
       "light.classList.toggle('is-open',open);light.hidden=false;});})();",
    phone="the card spans the screen; the rows stay one per day",
))

# ── 20. THE TIMELINE ─────────────────────────────────────────────────
_add(_o(
    key="timeline", name="Stops on a line",
    intent="three to five stops on one glowing line, each with a ringed dot",
    use_when="how it works, what happens after a visit (aftercare), a "
             "program's phases, the path from first visit to belonging. Real "
             "steps in the owner's order; the small label is a time or a step "
             "word, never an invented date.",
    aliases=("timeline", "process line", "steps on a line", "aftercare timeline", "stops on a line"),
    html="""<div class="sxo sxo-line" data-sx-object="timeline"><ol class="sxo-line-stops">
  <li><span class="sxo-line-dot" aria-hidden="true"></span><p class="sxo-label">First night</p><h3>Find center</h3><p>Wedge your clay and feel it settle under your hands on the wheel.</p></li>
  <li><span class="sxo-line-dot" aria-hidden="true"></span><p class="sxo-label">Week three</p><h3>Trim and foot</h3><p>Turn your leather-hard pots and carve the feet they will stand on.</p></li>
  <li><span class="sxo-line-dot" aria-hidden="true"></span><p class="sxo-label">Week five</p><h3>Glaze night</h3><p>Dip, pour and layer. The kiln does the rest while you sleep.</p></li>
  <li><span class="sxo-line-dot" aria-hidden="true"></span><p class="sxo-label">Last night</p><h3>The kiln opens</h3><p>Take home four pieces you made with your own hands.</p></li>
</ol></div>""",
    css=""".sxo-line{container-type:inline-size}
.sxo-line-stops{position:relative;list-style:none;margin:0;padding:0;display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);gap:clamp(1.2rem,2.4vw,2rem)}
.sxo-line-stops::before{content:"";position:absolute;left:12px;right:0;top:11px;height:2px;
  background:linear-gradient(90deg,var(--_accent),color-mix(in srgb,var(--_accent) 25%,transparent))}
.sxo-line-stops>li{position:relative;padding-top:2.5rem}
.sxo-line-dot{position:absolute;top:0;left:0;width:24px;height:24px;border-radius:50%;background:var(--_accent);
  box-shadow:0 0 0 5px color-mix(in srgb,var(--_accent) 22%,transparent),0 0 18px color-mix(in srgb,var(--_accent) 40%,transparent)}
.sxo-line-stops>li>.sxo-label{margin:0 0 .35rem;color:var(--_accent)}
.sxo-line h3{font-family:var(--_display);font-size:clamp(20px,1.8vw,26px);line-height:1.1;margin:0 0 .4rem}
.sxo-line-stops>li>p:last-child{margin:0;font-size:15px;line-height:1.55;color:color-mix(in srgb,currentColor 82%,transparent)}
@container (max-width:640px){.sxo-line-stops{grid-auto-flow:row;grid-auto-columns:auto;grid-template-columns:1fr;gap:1.6rem;padding-left:2.6rem}
  .sxo-line-stops::before{left:11px;right:auto;top:6px;bottom:6px;width:2px;height:auto;
    background:linear-gradient(180deg,var(--_accent),color-mix(in srgb,var(--_accent) 25%,transparent))}
  .sxo-line-stops>li{padding-top:0}
  .sxo-line-dot{left:-2.6rem}}""",
    phone="in any column narrower than 640px (every phone) the line runs down the left and the stops stack beside it",
))

# ── 21. THE PANELS ───────────────────────────────────────────────────
_add(_o(
    key="panels", name="Expanding photo panels",
    intent="tall photo panels side by side; the open one widens and tells its story",
    use_when="three to five real things that each have a real photo: "
             "ministries, rooms, services, programs. Each panel's name is its "
             "button; one short paragraph and a link inside. Needs a real photo "
             "per panel. Without the page's js class every panel shows open.",
    aliases=("photo panels", "expanding panels", "accordion panels", "photo accordion"),
    html="""<div class="sxo sxo-panels" data-sx-object="panels">
  <article class="sxo-panel is-open">
    <img src="https://example.com/wheel.jpg" alt="Hands pulling up the wall of a cylinder on the wheel" width="900" height="1200">
    <button class="sxo-panel-tab" type="button" aria-expanded="true"><span>Wheel classes</span></button>
    <div class="sxo-panel-body"><h3>Wheel classes</h3><p>Six Thursdays from centering to the kiln, with a wheel of your own each night.</p><a href="#classes">See the classes</a></div>
  </article>
  <article class="sxo-panel">
    <img src="https://example.com/handbuild.jpg" alt="Coils of clay stacked into a tall vase" width="900" height="1200">
    <button class="sxo-panel-tab" type="button" aria-expanded="false"><span>Hand building</span></button>
    <div class="sxo-panel-body"><h3>Hand building</h3><p>Pinch, coil and slab at the long table. No wheel needed.</p><a href="#handbuilding">How it works</a></div>
  </article>
  <article class="sxo-panel">
    <img src="https://example.com/kiln.jpg" alt="Glazed bowls cooling on a kiln shelf" width="900" height="1200">
    <button class="sxo-panel-tab" type="button" aria-expanded="false"><span>Open studio</span></button>
    <div class="sxo-panel-body"><h3>Open studio</h3><p>Sunday afternoons for anyone who has taken a class.</p><a href="#hours">See the hours</a></div>
  </article>
</div>""",
    css=""".sxo-panels{display:grid;gap:.75rem}
.sxo-panel{position:relative;overflow:hidden;min-height:340px;border-radius:18px;background:var(--_ink)}
.sxo-panel img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.sxo-panel::after{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(180deg,rgba(0,0,0,0) 35%,rgba(0,0,0,.8))}
.sxo-panel-body{position:absolute;left:0;right:0;bottom:0;z-index:2;padding:clamp(1.2rem,2.4vw,2rem);color:rgba(255,255,255,1)}
.sxo-panel-body h3{font-family:var(--_display);font-size:clamp(24px,2.4vw,36px);line-height:1.05;margin:0 0 .5rem}
.sxo-panel-body p{margin:0 0 .9rem;max-width:42ch;font-size:15px;line-height:1.5}
.sxo-panel-body a{color:inherit;font-family:var(--_label);font-size:12px;letter-spacing:.14em;text-transform:uppercase;text-underline-offset:.35em}
.sxo-panel-tab{display:none}
.js .sxo-panels{display:flex;gap:.75rem;height:clamp(420px,62vh,620px)}
.js .sxo-panel{flex:1 1 0;min-width:0;min-height:0}
.js .sxo-panels.is-ready .sxo-panel{transition:flex-grow .6s cubic-bezier(.6,0,.2,1)}
.js .sxo-panel.is-open{flex-grow:4.2}
.js .sxo-panel-tab{position:absolute;inset:0;z-index:3;display:flex;align-items:flex-end;justify-content:center;width:100%;padding:1.4rem 0;
  border:0;background:none;color:rgba(255,255,255,1);cursor:pointer;font:inherit}
.js .sxo-panel-tab span{writing-mode:vertical-rl;transform:rotate(180deg);white-space:nowrap;font-family:var(--_label);font-size:13px;letter-spacing:.16em;text-transform:uppercase}
.js .sxo-panel.is-open .sxo-panel-tab{display:none}
.js .sxo-panels.is-ready .sxo-panel-body{transition:opacity .4s .25s}
.js .sxo-panel:not(.is-open) .sxo-panel-body{opacity:0;visibility:hidden}
.sxo-panel-tab:focus-visible{outline:2px solid rgba(255,255,255,1);outline-offset:-8px}
@media (max-width:800px){.js .sxo-panels{flex-direction:column;height:auto}
  .js .sxo-panel{flex:none;height:78px}
  .js .sxo-panels.is-ready .sxo-panel{transition:height .5s cubic-bezier(.6,0,.2,1)}
  .js .sxo-panel.is-open{height:390px}
  .js .sxo-panel-tab{align-items:center;justify-content:flex-start;padding:0 1.2rem}
  .js .sxo-panel-tab span{writing-mode:horizontal-tb;transform:none}}
@media (prefers-reduced-motion:reduce){.js .sxo-panels.is-ready .sxo-panel,.js .sxo-panels.is-ready .sxo-panel-body{transition:none}}""",
    js="(function(){document.querySelectorAll('.sxo-panels').forEach(function(g){"
       "var ps=[].slice.call(g.querySelectorAll('.sxo-panel'));function open(p){ps.forEach(function(q){"
       "var on=q===p;q.classList.toggle('is-open',on);var b=q.querySelector('.sxo-panel-tab');"
       "if(b)b.setAttribute('aria-expanded',on?'true':'false');});}"
       "var hover=window.matchMedia('(hover:hover) and (min-width:801px)').matches;"
       "ps.forEach(function(p){var b=p.querySelector('.sxo-panel-tab');if(!b)return;"
       "b.addEventListener('click',function(){open(p);var a=p.querySelector('.sxo-panel-body a');if(a)a.focus({preventScroll:true});});"
       "if(hover)p.addEventListener('mouseenter',function(){open(p);});});"
       "requestAnimationFrame(function(){requestAnimationFrame(function(){g.classList.add('is-ready');});});});})();",
    phone="the panels stack as 78px bars with their names; the open one grows to 390px",
))

# ── 22. THE MOSAIC ───────────────────────────────────────────────────
_add(_o(
    key="mosaic", name="Photo mosaic",
    intent="one tall photo beside three smaller ones, fitted into one block",
    use_when="four real photos that belong together: the room, the work, the "
             "people at one gathering. The lead photo is the strongest one. "
             "Captions only from the data.",
    aliases=("photo mosaic", "photo cluster"),
    html="""<div class="sxo sxo-mosaic" data-sx-object="mosaic">
  <figure class="sxo-mosaic-lead"><img src="https://example.com/studio.jpg" alt="The studio at dusk, six wheels under hanging lights" width="900" height="1200"><figcaption>The studio on a Thursday</figcaption></figure>
  <figure><img src="https://example.com/hands.jpg" alt="Clay-covered hands cupping a bowl" width="800" height="800"></figure>
  <figure><img src="https://example.com/shelf.jpg" alt="Greenware drying on wooden shelves" width="800" height="800"></figure>
  <figure><img src="https://example.com/glaze.jpg" alt="Buckets of glaze in a row" width="1200" height="600"></figure>
</div>""",
    css=""".sxo-mosaic{display:grid;grid-template-columns:1.25fr 1fr 1fr;grid-template-rows:repeat(2,clamp(160px,18vw,260px));gap:clamp(.5rem,1vw,.8rem)}
.sxo-mosaic figure{position:relative;margin:0;overflow:hidden;border-radius:14px;background:color-mix(in srgb,currentColor 8%,transparent)}
.sxo-mosaic img{display:block;width:100%;height:100%;object-fit:cover;transition:transform .8s cubic-bezier(.2,.7,.2,1)}
.sxo-mosaic figure:hover img{transform:scale(1.04)}
.sxo-mosaic-lead{grid-row:span 2}
.sxo-mosaic figure:last-child{grid-column:span 2}
.sxo-mosaic figcaption{position:absolute;left:.75rem;bottom:.75rem;max-width:calc(100% - 1.5rem);padding:.35rem .6rem;border-radius:6px;
  background:rgba(0,0,0,.58);color:rgba(255,255,255,1);font-family:var(--_label);font-size:12px;letter-spacing:.06em}
@media (max-width:600px){.sxo-mosaic{grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:none}
  .sxo-mosaic-lead{grid-row:auto;grid-column:1/-1;aspect-ratio:4/3}
  .sxo-mosaic figure:not(.sxo-mosaic-lead){grid-column:auto;aspect-ratio:1}}
@media (prefers-reduced-motion:reduce){.sxo-mosaic img{transition:none}}""",
    phone="the lead photo runs full width; the other three sit under it as squares",
))

# ── 23. THE PULL QUOTE ───────────────────────────────────────────────
_add(_o(
    key="pull-quote", name="Pull quote with a giant mark",
    intent="one client's words set large, a giant quotation mark behind them",
    use_when="one real testimonial in the client's own words, with their name "
             "as the data gives it. Never a quote the data does not hold, never "
             "edited into new claims. One or two a page.",
    aliases=("pull quote", "testimonial quote", "big quote", "giant quote mark"),
    html="""<figure class="sxo sxo-quote" data-sx-object="pull-quote">
  <span class="sxo-quote-mark" aria-hidden="true">&ldquo;</span>
  <blockquote><p>I came in to make one mug. Six weeks later I have a shelf of bowls and a Thursday night I will not give up.</p></blockquote>
  <figcaption><b>June Reyes</b><span class="sxo-label">Fall term student</span></figcaption>
</figure>""",
    css=""".sxo-quote{position:relative;max-width:52rem;margin:0;padding:clamp(1.5rem,4vw,3rem) 0 0 clamp(1.2rem,3vw,2.4rem);border-left:3px solid var(--_accent)}
.sxo-quote-mark{position:absolute;left:clamp(.4rem,1.5vw,1rem);top:-.16em;font-family:var(--_display);font-size:clamp(120px,14vw,220px);line-height:1;
  color:color-mix(in srgb,var(--_accent) 32%,transparent);pointer-events:none;user-select:none}
.sxo-quote blockquote{position:relative;margin:0}
.sxo-quote blockquote p{margin:0;font-family:var(--_display);font-size:clamp(24px,2.8vw,40px);line-height:1.2;text-wrap:balance}
.sxo-quote figcaption{display:flex;flex-direction:column;gap:.25rem;margin-top:1.2rem}
.sxo-quote figcaption b{font-size:16px}
.sxo-quote figcaption .sxo-label{color:color-mix(in srgb,currentColor 65%,transparent)}
@media (max-width:600px){.sxo-quote{padding-left:1rem}.sxo-quote blockquote p{font-size:22px}}""",
    phone="the words drop to 22px; the mark scales with them",
))

# ── 24. THE PHONE DOCK ───────────────────────────────────────────────
_add(_o(
    key="dock", name="Phone action dock",
    intent="a frosted bar fixed to the bottom of a phone screen: one line and the one action",
    use_when="the page's one action on a phone (book, visit, call, order), "
             "once the opening has scrolled away. The line is a real fact "
             "(the next time, the price, the hours); the action links where the "
             "page's main action links. Phones only; once a page.",
    aliases=("phone dock", "booking dock", "action dock", "sticky action bar"),
    html="""<div class="sxo sxo-dock" data-sx-object="dock">
  <p class="sxo-dock-line"><b>Fall term</b><span>Thursdays, 6 to 9 pm</span></p>
  <a class="sxo-dock-go" href="#book">Book a seat</a>
</div>""",
    css=""".sxo-dock{display:none}
.sxo-dock-line{display:flex;flex-direction:column;min-width:0;margin:0;font-size:13px;line-height:1.3}
.sxo-dock-line b{font-family:var(--_display);font-size:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sxo-dock-line span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:color-mix(in srgb,var(--_ink) 72%,transparent)}
.sxo-dock-go{flex-shrink:0;display:inline-flex;align-items:center;min-height:44px;padding:0 1.1rem;border-radius:12px;
  background:var(--_accent);color:var(--_paper);font-weight:700;font-size:15px;text-decoration:none}
@media (max-width:768px){
  .sxo-dock{position:fixed;left:.6rem;right:.6rem;bottom:calc(.6rem + env(safe-area-inset-bottom,0px));z-index:60;display:flex;align-items:center;
    justify-content:space-between;gap:.8rem;padding:.55rem .55rem .55rem 1rem;border-radius:16px;color:var(--_ink);
    background:color-mix(in srgb,var(--_paper) 84%,transparent);-webkit-backdrop-filter:blur(14px) saturate(1.4);backdrop-filter:blur(14px) saturate(1.4);
    box-shadow:0 12px 30px -10px rgba(0,0,0,.45),0 0 0 1px var(--_line);transition:transform .45s cubic-bezier(.2,.8,.2,1),opacity .3s,visibility 0s}
  .js .sxo-dock:not(.is-shown){transform:translateY(calc(100% + 1.5rem));opacity:0;visibility:hidden;
    transition:transform .45s cubic-bezier(.2,.8,.2,1),opacity .3s,visibility 0s .45s}
  body:has(.sxo-dock){padding-bottom:calc(5.5rem + env(safe-area-inset-bottom,0px))}}
@media (prefers-reduced-motion:reduce){.sxo-dock,.js .sxo-dock:not(.is-shown){transition:none}}""",
    js="(function(){var d=document.querySelector('.sxo-dock');if(!d)return;"
       "function f(){d.classList.toggle('is-shown',window.scrollY>window.innerHeight*0.6);}"
       "window.addEventListener('scroll',f,{passive:true});f();})();",
    phone="this is the phone: it rises once the opening scrolls away; on a desktop it is not shown",
))

# ── 25. THE QUESTIONS ────────────────────────────────────────────────
_add(_o(
    key="faq", name="Questions that open",
    intent="questions in a ruled list; each opens to its answer, a plus that turns to a cross",
    use_when="real questions with real answers: THE REAL DATA's faq rows, or "
             "what the owner said. Three to eight. Never an answer the data "
             "does not support (no invented policies, prices or guarantees).",
    aliases=("faq", "faqs", "questions and answers", "question accordion"),
    html="""<div class="sxo sxo-faq" data-sx-object="faq">
  <details open><summary>Do I need any experience?</summary><p>None. The first night starts with wedging and centering, and the wheel is yours for three hours.</p></details>
  <details><summary>What should I wear?</summary><p>Clothes you do not mind getting clay on, and short nails if you can.</p></details>
  <details><summary>Can I miss a week?</summary><p>Yes. Make it up at open studio on Sunday afternoon.</p></details>
</div>""",
    css=""".sxo-faq{max-width:48rem;border-top:1.5px solid currentColor}
.sxo-faq details{border-bottom:1px solid color-mix(in srgb,currentColor 22%,transparent)}
.sxo-faq summary{display:flex;justify-content:space-between;align-items:center;gap:1rem;padding:1.15rem 0;cursor:pointer;list-style:none;
  font-family:var(--_display);font-size:clamp(18px,1.6vw,22px);line-height:1.25}
.sxo-faq summary::-webkit-details-marker{display:none}
.sxo-faq summary::after{content:"";flex-shrink:0;width:28px;height:28px;border-radius:50%;border:1.5px solid color-mix(in srgb,currentColor 40%,transparent);
  background:linear-gradient(currentColor,currentColor) center/11px 1.5px no-repeat,linear-gradient(currentColor,currentColor) center/1.5px 11px no-repeat;
  transition:transform .3s,background-color .3s,border-color .3s}
.sxo-faq details[open] summary::after{transform:rotate(45deg);border-color:var(--_accent);background-color:color-mix(in srgb,var(--_accent) 18%,transparent)}
.sxo-faq summary:focus-visible{outline:2px solid var(--_accent);outline-offset:4px}
.sxo-faq details p{max-width:62ch;margin:0 0 1.2rem;font-size:16px;line-height:1.6;color:color-mix(in srgb,currentColor 85%,transparent)}
@media (max-width:600px){.sxo-faq summary{font-size:17px;padding:1rem 0}}
@media (prefers-reduced-motion:reduce){.sxo-faq summary::after{transition:none}}""",
    phone="the questions drop to 17px; every one stays a full-width tap target",
))

# ── 26. THE STATS ────────────────────────────────────────────────────
_add(_o(
    key="stat-strip", name="Count-up figures",
    intent="three or four big figures in a ruled row, each counting up as it comes into view",
    use_when="only the owner's proven stats or counts THE REAL DATA gives, "
             "verbatim (the truth law checks every number). The page holds the "
             "real figure; the count-up only plays toward it. data-count is "
             "the figure's whole number.",
    aliases=("stat strip", "count-up figures", "count-up", "stat row"),
    html="""<dl class="sxo sxo-stats" data-sx-object="stat-strip">
  <div><dt>Wheels in the studio</dt><dd data-count="12">12</dd></div>
  <div><dt>Weeks in a term</dt><dd data-count="6">6</dd></div>
  <div><dt>Firings each term</dt><dd data-count="2">2</dd></div>
</dl>""",
    css=""".sxo-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));gap:0 clamp(1rem,2vw,2rem);margin:0;border-top:1.5px solid currentColor}
.sxo-stats>div{display:flex;flex-direction:column-reverse;justify-content:flex-end;gap:.4rem;padding-top:1.2rem}
.sxo-stats dd{margin:0;font-family:var(--_display);font-size:clamp(44px,5.4vw,80px);line-height:.95;font-variant-numeric:tabular-nums;color:var(--_accent)}
.sxo-stats dt{max-width:22ch;font-size:14px;line-height:1.4;color:color-mix(in srgb,currentColor 80%,transparent)}
@media (max-width:600px){.sxo-stats{grid-template-columns:repeat(2,minmax(0,1fr));row-gap:1rem}.sxo-stats dd{font-size:44px}}""",
    js="(function(){if(window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;"
       "var els=[].slice.call(document.querySelectorAll('.sxo-stats dd[data-count]'));"
       "function run(el){var end=+el.getAttribute('data-count'),txt=el.textContent,t0=null;"
       "if(!(end>0)||!/\\d/.test(txt))return;function step(t){if(t0===null)t0=t;var k=Math.min(1,(t-t0)/1200),"
       "v=Math.round(end*(1-Math.pow(1-k,3)));el.textContent=txt.replace(/[\\d,]+/,String(v));"
       "if(k<1)requestAnimationFrame(step);else el.textContent=txt;}requestAnimationFrame(step);}"
       "function check(){els=els.filter(function(el){if(el.getBoundingClientRect().top<window.innerHeight*0.85){run(el);return false;}return true;});"
       "if(!els.length)window.removeEventListener('scroll',check);}"
       "window.addEventListener('scroll',check,{passive:true});check();})();",
    phone="two figures to a row at 44px",
))


OBJECT_KEYS: List[str] = list(OBJECTS)

_ALIAS_INDEX: List[Tuple[str, str]] = sorted(
    ((alias.lower(), key) for key, o in OBJECTS.items()
     for alias in (key,) + o.aliases),
    key=lambda kv: -len(kv[0]))

_OBJECTS_LINE_RE = re.compile(r"^\s*[-*•]?\s*OBJECTS?\s*[:\-—]\s*(.+)$",
                              re.IGNORECASE | re.MULTILINE)


def object_names_in(spec_text: str) -> List[str]:
    """The objects a blueprint commits to, read from its OBJECTS: line(s)
    in the concept sheet. Only that line counts: "ticket" in a headline is
    copy, not a commitment. Longest alias first, so "id card" beats
    "card"; order follows the blueprint."""
    found: List[str] = []
    for m in _OBJECTS_LINE_RE.finditer(spec_text or ""):
        line = m.group(1).lower()
        hits: List[Tuple[int, str]] = []
        taken: List[Tuple[int, int]] = []
        for alias, key in _ALIAS_INDEX:
            for am in re.finditer(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", line):
                span = (am.start(), am.end())
                if any(a < span[1] and span[0] < b for a, b in taken):
                    continue
                taken.append(span)
                hits.append((am.start(), key))
        for _, key in sorted(hits):
            if key not in found:
                found.append(key)
    return found


def page_objects(html: str) -> List[str]:
    """The library objects a built page actually carries."""
    keys = re.findall(r"data-sx-object\s*=\s*[\"']([a-z-]+)[\"']", html or "")
    return [k for k in dict.fromkeys(keys) if k in OBJECTS]


def director_block() -> str:
    """The Director's catalog, generated from the same registry the
    builder is handed, so an object cannot be named without a renderer."""
    lines = [
        "THE OBJECT LIBRARY: hand-built objects the builder has working source "
        "for. A concept puts content inside objects from its own world; name "
        "them by key on the concept sheet's OBJECTS line, with a finish "
        "(paper, inverse, glow, metal) that suits the design language "
        "(printed paper for Broadsheet or Atelier, metal for Ledger or "
        "Monograph, glow for Neon or Glass). Inverse turns objects into solid "
        "panels in the ink colour: use it on a light ground only; on a dark "
        "ground choose paper (light objects) or glow. Name only objects whose "
        "content the data can fill.",
    ]
    for key, o in OBJECTS.items():
        lines.append(f"- {key}: {o.intent}. USE FOR: {o.use_when}")
    lines.append("An object that is not on this list cannot be built; describe "
                 "what you want with an object that is.")
    return "\n".join(lines)


def builder_block(keys: Iterable[str]) -> str:
    """The source for exactly the named objects, or '' when none are
    named. Shared tokens first, then each object's structure, styles,
    script and phone behavior."""
    picked = [k for k in OBJECT_KEYS if k in set(keys or ())]
    if not picked:
        return ""
    lines = [
        "== THE OBJECTS YOUR BLUEPRINT NAMES: WORKING SOURCE ==",
        "Build each named object from its source below. KEEP the structure, "
        "the class names and the data-sx-object attribute; REPLACE every word "
        "of the example copy (it belongs to an imaginary pottery studio) with "
        "this business's real data; repeat an element (a ticket, a card, a "
        "row) once per real item. Map the seven object tokens ONCE in :root "
        "to your own tokens: --obj-paper, --obj-ink, --obj-accent, --obj-line, "
        "--obj-display, --obj-body, --obj-label. Set data-finish on the root "
        "when the blueprint names a finish. Copy the CSS into your <style> "
        "unchanged apart from sizes and spacing; the shared block below "
        "is needed once. This CSS is the one place a url() may appear (the "
        "library's paper grain). Any script line goes inside your one script.",
        "",
        "--- SHARED (once per page)",
        BASE_CSS,
        "",
    ]
    for key in picked:
        o = OBJECTS[key]
        lines.append(f"--- {key}: {o.intent}")
        lines.append("STRUCTURE:")
        lines.append(o.html)
        lines.append("CSS:")
        lines.append(o.css)
        if o.js:
            lines.append("SCRIPT (inside your one script):")
            lines.append(o.js)
        if o.phone:
            lines.append(f"ON A PHONE: {o.phone}.")
        lines.append("")
    return "\n".join(lines).rstrip()


def contact_sheet_html(themes: Iterable[Dict[str, str]]) -> str:
    """Every object in every theme on one page, for the bench's eyes."""
    themes = list(themes)
    fonts = sorted({t.get("font_link", "") for t in themes if t.get("font_link")})
    css = [BASE_CSS] + [o.css for o in OBJECTS.values()]
    panels = []
    for t in themes:
        tokens = ";".join(f"{k}:{v}" for k, v in t.items()
                          if k.startswith("--"))
        cells = []
        finish = t.get("finish") or "paper"
        for key, o in OBJECTS.items():
            html = o.html
            if finish != "paper":
                html = html.replace('data-sx-object="', f'data-finish="{finish}" data-sx-object="')
            if key == "letter":
                html = html.replace('<span class="sxo-letter-front" aria-hidden="true"></span>',
                                    '<span class="sxo-letter-front" aria-hidden="true"></span>'
                                    + OBJECTS["seal"].html.replace(" data-turn", "")
                                    .replace("sxo-ring-1", "sxo-ring-l" + t["name"]), 1)
            if key == "seal":
                html = html.replace("sxo-ring-1", "sxo-ring-s" + t["name"])
            if key == "marker":
                html = f'<p class="cs-big">Six weeks for {html}, clay included.</p>'
            cells.append(f'<div class="cs-cell cs-{key}"><p class="cs-tag">{key}</p>{html}</div>')
        panels.append(f'<section class="cs-theme" style="{tokens}"><h2 class="cs-h">{t["name"]}</h2>'
                      f'<div class="cs-grid">{"".join(cells)}</div></section>')
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Object library</title>" + "".join(fonts)
            + "<style>body{margin:0}.cs-theme{padding:48px 4vw;background:var(--sx-bg);color:var(--sx-text)}"
              ".cs-h{font:700 13px/1 monospace;letter-spacing:.2em;text-transform:uppercase;margin:0 0 24px;opacity:.6}"
              ".cs-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,460px),1fr));gap:48px 40px;align-items:start}"
              ".cs-cell{min-width:0}.cs-tag{font:12px/1 monospace;opacity:.5;margin:0 0 14px}"
              ".cs-big{font-family:var(--obj-display);font-size:34px;line-height:1.2;margin:16px 0}"
              ".cs-edge{grid-column:1/-1}.cs-edge .sxo-edge+*{padding-top:0}"
              + "\n".join(css) + "</style></head><body>"
            + "".join(panels)
            + "<script>document.documentElement.className+=' js';"
            + "".join(o.js for o in OBJECTS.values() if o.js)
            + "</script></body></html>")


_FONTS = ("<link rel='stylesheet' href='https://fonts.googleapis.com/css2?family=Fraunces:wght@600"
          "&family=Source+Sans+3:wght@400;700&family=IBM+Plex+Mono:wght@400;700&family=Anton"
          "&family=Barlow:wght@400;700&family=Space+Mono:wght@400;700&family=Archivo+Black"
          "&family=DM+Sans:wght@400;700&family=Cormorant+Garamond:wght@600&family=Playfair+Display:wght@700"
          "&family=Space+Grotesk:wght@400;700&family=Bebas+Neue&display=swap'>")


def _theme(name, bg, text, paper, ink, accent, display, body, label, finish="paper"):
    return {"name": name, "finish": finish, "--sx-bg": bg, "--sx-text": text,
            "--obj-paper": paper, "--obj-ink": ink, "--obj-accent": accent,
            "--obj-display": display, "--obj-body": body, "--obj-label": label}


# One theme per design language, in that language's colours and type, each
# wearing the finish design_languages.OBJECT_FINISH gives it.
CONTACT_THEMES: List[Dict[str, str]] = [
    _theme("mural", "#f2c230", "#1c1a17", "#fffdf6", "#1c1a17", "#e8432f",
           "'Archivo Black',Impact,sans-serif", "'DM Sans',system-ui,sans-serif", "'Space Mono',monospace"),
    _theme("monograph", "#141414", "#e8e6e1", "#efeee9", "#161616", "#b89a5a",
           "'Cormorant Garamond',Georgia,serif", "'DM Sans',system-ui,sans-serif", "'IBM Plex Mono',monospace", "metal"),
    _theme("broadsheet", "#f4efe4", "#1d1b18", "#fbf8f1", "#1d1b18", "#c0281e",
           "'Playfair Display',Georgia,serif", "'Source Sans 3',system-ui,sans-serif", "'IBM Plex Mono',monospace"),
    _theme("signal", "#f3f3f0", "#111111", "#ffffff", "#2347d9", "#111111",
           "'Space Grotesk',system-ui,sans-serif", "'Space Grotesk',system-ui,sans-serif", "'Space Mono',monospace", "inverse"),
    _theme("atelier", "#ece7dd", "#2a2622", "#f8f5ef", "#2a2622", "#8a7b62",
           "'Cormorant Garamond',Georgia,serif", "'DM Sans',system-ui,sans-serif", "'IBM Plex Mono',monospace"),
    _theme("neon", "#0b0b0d", "#f2efe8", "#17171b", "#f2efe8", "#ff3d6e",
           "'Anton',Impact,sans-serif", "'Barlow',system-ui,sans-serif", "'Space Mono',monospace", "glow"),
    _theme("hearth", "#2a1d17", "#f3e7d8", "#f6ecdf", "#2a1d17", "#d9864a",
           "'Fraunces',Georgia,serif", "'DM Sans',system-ui,sans-serif", "'IBM Plex Mono',monospace"),
    _theme("glass", "#0a0c10", "#e8edf5", "#141821", "#e8edf5", "#4c8dff",
           "'Space Grotesk',system-ui,sans-serif", "'DM Sans',system-ui,sans-serif", "'IBM Plex Mono',monospace", "glow"),
    _theme("runway", "#0d0d0d", "#f2f2f2", "#f2f2f2", "#0d0d0d", "#8c8c8c",
           "'Bebas Neue',Impact,sans-serif", "'DM Sans',system-ui,sans-serif", "'IBM Plex Mono',monospace"),
    _theme("arena", "#16161a", "#f4f1ea", "#f4f1ea", "#16161a", "#ff6a1a",
           "'Anton',Impact,sans-serif", "'Barlow',system-ui,sans-serif", "'Space Mono',monospace"),
    _theme("ledger", "#121417", "#e9e4d8", "#e9e4d8", "#16181b", "#a88a4e",
           "'Fraunces',Georgia,serif", "'Source Sans 3',system-ui,sans-serif", "'IBM Plex Mono',monospace", "metal"),
]
CONTACT_THEMES[0]["font_link"] = _FONTS
