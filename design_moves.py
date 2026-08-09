"""
design_moves.py — THE MOVES, with renderers behind them.

WHY THIS MODULE EXISTS (2026-08-09 design review). The Director was taught
a thirteen-move vocabulary — THE THREAD, THE STAGE LIGHT, THE FOIL and ten
more — and committed specs to those moves by name. A grep of the entire
render path (canvas, atelier, builder_v2, canvas_brief, art_direction,
drl/passes, site_modules) found **zero** implementations of any of them.

The consequence was not a dropped instruction, it was a loop:

  1. the spec commits to THE STAGE LIGHT — "one warm radial glow"
  2. no author has ever been taught the technique
  3. the atelier/canvas colour validator BANS the natural way to write it
     (non-neutral `rgba()`), and on a violation DISCARDS THE WHOLE CHUNK,
     hero included, so the build ships from module templates
  4. the judge correctly reports "STAGE LIGHT not visible in any breakpoint"
  5. that note is recycled into the next brief under the heading
     "repeat none of these" — an absence complaint handed back as a ban
  6. repeat, at a full build's cost each time

THE ASYMMETRY THAT MADE IT ABSURD: `color-mix(in srgb, var(--sx-accent)
26%, transparent)` — the one legal way to tint with the brand accent —
appears 134 times in site_modules/ and ZERO times in any authoring prompt.
The deterministic templates build exactly the glow the spec asks for while
the AI authors are forbidden from every alternative and told about none.
So every AI-authored surface was structurally flatter than the template it
replaced.

WHAT THIS MODULE IS. One list, in one place, that is BOTH the Director's
vocabulary and the builders' capability. `director_block()` feeds
spec_author's system prompt; `builder_block()` feeds the atelier, canvas
and builder_v2 authoring prompts. They cannot drift, because a move that
has no primitive cannot appear in either — the test suite asserts it.

EVERY PRIMITIVE BELOW IS VALIDATOR-LEGAL. Verified against
atelier_validator.validate_fragment, which means:
  · no hex literals            · no rgb()/hsl()/lab()/lch()/oklch()
  · rgba() ONLY as rgba(0,0,0,x) / rgba(255,255,255,x)
  · no url(), no data:, no @import
Tinting is done with color-mix() against the --sx-* tokens the platform
already emits. Two moves are deliberately re-expressed because their
"natural" technique is banned: THE TEAR uses clip-path rather than an SVG
mask url(), and the grain inside THE STAGE LIGHT is a repeating gradient
rather than a data-URI texture.
"""
from __future__ import annotations

from typing import Dict, List, NamedTuple


class Move(NamedTuple):
    group: str          # STRUCTURAL | MATERIAL | MOTION
    intent: str         # what the move IS — the Director's line
    recur: str          # how it earns its place (a move used once is decoration)
    css: str            # the primitive. Validator-legal. `.scope` = the author's root


MOVES: Dict[str, Move] = {

    # ── STRUCTURAL ───────────────────────────────────────────────────
    "THE THREAD": Move(
        group="STRUCTURAL",
        intent="one drawn line that walks the whole page and marks every "
               "section as a station on it",
        recur="a rail in three sections minimum, with a lit node at each "
              "station; it must cross a section boundary to read as a thread",
        css=""".scope .sx-thread{position:absolute;left:2rem;top:0;bottom:0;width:1px;
  background:linear-gradient(180deg,transparent,
    color-mix(in srgb,var(--sx-accent) 55%,transparent) 12%,
    color-mix(in srgb,var(--sx-accent) 55%,transparent) 88%,transparent);}
.scope .sx-thread-node{position:absolute;left:2rem;width:9px;height:9px;
  border-radius:50%;transform:translateX(-4px);
  background:var(--sx-accent);
  box-shadow:0 0 0 4px color-mix(in srgb,var(--sx-accent) 18%,transparent);}""",
    ),

    "TYPE AS IMAGE": Move(
        group="STRUCTURAL",
        intent="an oversized ghost word behind the composition; display type "
               "used as picture, not as label",
        recur="one ghost word per chapter, alternating which edge it bleeds "
              "off; same family, same weight, three appearances",
        css=""".scope .sx-ghost{position:absolute;z-index:0;pointer-events:none;
  font-size:clamp(6rem,22vw,17rem);font-weight:800;line-height:.8;
  letter-spacing:-.04em;white-space:nowrap;
  color:color-mix(in srgb,var(--sx-text) 13%,transparent);}
.scope .sx-ghost-outline{color:transparent;
  -webkit-text-stroke:1px color-mix(in srgb,var(--sx-text) 22%,transparent);}""",
    ),

    "THE CEREMONY": Move(
        group="STRUCTURAL",
        intent="the brand promise given its own stage between chapters — a "
               "marquee band, a stamp, an underline that draws itself",
        recur="once between two chapters and once at the close; never three "
              "times in a row",
        css=""".scope .sx-ceremony{overflow:hidden;padding-block:1.1rem;
  border-block:1px solid color-mix(in srgb,var(--sx-text) 12%,transparent);
  background:color-mix(in srgb,var(--sx-accent) 6%,transparent);}
.scope .sx-ceremony-run{display:inline-block;white-space:nowrap;
  font-size:.8rem;letter-spacing:.28em;text-transform:uppercase;
  color:color-mix(in srgb,var(--sx-text) 62%,transparent);
  animation:sx-marquee 26s linear infinite;}
@keyframes sx-marquee{from{transform:translateX(0)}to{transform:translateX(-50%)}}
@media (prefers-reduced-motion:reduce){.scope .sx-ceremony-run{animation:none}}""",
    ),

    "THE EXHIBITION": Move(
        group="STRUCTURAL",
        intent="the work hung like a gallery wall — a lead piece large, "
               "rhythmic bands after, one typographic tile among the artwork",
        recur="one lead, then a band of three, then the tile; the rhythm is "
              "the move, not the images",
        css=""".scope .sx-exhibit{display:grid;gap:1px;
  grid-template-columns:repeat(6,1fr);
  background:color-mix(in srgb,var(--sx-text) 10%,transparent);}
.scope .sx-exhibit-lead{grid-column:span 6;aspect-ratio:16/7;}
.scope .sx-exhibit-band{grid-column:span 2;aspect-ratio:4/5;}
.scope .sx-exhibit-tile{grid-column:span 2;display:flex;align-items:center;
  padding:1.4rem;background:var(--sx-bg);
  font-size:1.05rem;line-height:1.3;}
@media (max-width:768px){.scope .sx-exhibit-band,
  .scope .sx-exhibit-tile{grid-column:span 3}}""",
    ),

    "THE ECHO FRAME": Move(
        group="STRUCTURAL",
        intent="images in a hairline frame with a second frame offset behind; "
               "captions running vertically along the edge",
        recur="the portrait, then one gallery lead, then the close image",
        css=""".scope .sx-echo{position:relative;display:inline-block;}
.scope .sx-echo::before{content:"";position:absolute;inset:0;
  transform:translate(14px,14px);
  border:1px solid color-mix(in srgb,var(--sx-accent) 42%,transparent);
  pointer-events:none;}
.scope .sx-echo>*{position:relative;
  border:1px solid color-mix(in srgb,var(--sx-text) 18%,transparent);}
.scope .sx-echo-caption{position:absolute;right:-2.2rem;top:0;
  writing-mode:vertical-rl;font-size:.68rem;letter-spacing:.2em;
  text-transform:uppercase;
  color:color-mix(in srgb,var(--sx-text) 55%,transparent);}""",
    ),

    "THE STAGE LIGHT": Move(
        group="STRUCTURAL",
        intent="one warm radial glow that owns the hero and returns once at "
               "the close, with grain over everything and gradient depth "
               "between grounds",
        recur="hero, then once at the close. THE LIGHT MUST LAND ON THE WORK "
              "— a glow centred on empty ground is the failure mode, and it "
              "must not be hidden on mobile while the glow stays",
        # A CORE plus a SPILL. A single flat radial reads as fog, not a lamp
        # — that is what shipped and what the judge marked down.
        css=""".scope{position:relative;isolation:isolate;overflow:hidden;}
.scope .sx-stage-spill,.scope .sx-stage-core{position:absolute;z-index:-2;
  pointer-events:none;border-radius:50%;}
.scope .sx-stage-spill{width:80vw;height:80vh;right:-8%;top:-18%;
  background:radial-gradient(closest-side,
    color-mix(in srgb,var(--sx-accent) 24%,transparent),transparent 70%);}
.scope .sx-stage-core{width:20rem;height:20rem;right:14%;top:10%;
  background:radial-gradient(circle,
    color-mix(in srgb,var(--sx-accent) 34%,transparent),transparent 58%);}
.scope .sx-grain{position:absolute;inset:0;z-index:-1;pointer-events:none;
  opacity:.05;background-image:repeating-linear-gradient(45deg,
    rgba(255,255,255,.5) 0 1px,transparent 1px 3px),
    repeating-linear-gradient(-45deg,rgba(0,0,0,.5) 0 1px,transparent 1px 3px);
  background-size:3px 3px;}""",
    ),

    # ── MATERIAL ─────────────────────────────────────────────────────
    "THE FOIL": Move(
        group="MATERIAL",
        intent="metallic type — a gradient clipped to the letters. A luxury "
               "headline that costs nothing",
        recur="THE word in the hero, and the same word class once more later; "
              "never on a full sentence",
        css=""".scope .sx-foil{
  background:linear-gradient(92deg,var(--sx-accent),
    color-mix(in srgb,var(--sx-accent) 45%,var(--sx-text)) 55%,var(--sx-accent));
  -webkit-background-clip:text;background-clip:text;color:transparent;
  -webkit-text-fill-color:transparent;}""",
    ),

    "THE EMBOSS": Move(
        group="MATERIAL",
        intent="pressed-in or raised surfaces built from inset light and "
               "shadow alone — swatches, seals, cards that read as physical",
        recur="the seal, then the card set; two surfaces minimum or it reads "
              "as a stray shadow",
        css=""".scope .sx-emboss{
  background:color-mix(in srgb,var(--sx-text) 4%,transparent);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.10),
             inset 0 -1px 0 rgba(0,0,0,.45),
             0 1px 0 rgba(255,255,255,.05);}
.scope .sx-deboss{
  box-shadow:inset 0 2px 4px rgba(0,0,0,.55),
             inset 0 -1px 0 rgba(255,255,255,.06);}""",
    ),

    "THE TEAR": Move(
        group="MATERIAL",
        intent="a torn or cut edge between grounds — the hand-made seam "
               "instead of a ruled line",
        recur="between two chapters, then mirrored once; the same angle both "
              "times so it reads as one hand",
        # Re-expressed: the spec's SVG-mask url() is banned by the validator.
        # clip-path gives the same seam and is legal.
        css=""".scope .sx-tear{position:relative;
  clip-path:polygon(0 2.2rem,12% 1.1rem,29% 2.6rem,47% .9rem,
    68% 2.4rem,85% 1.2rem,100% 2.3rem,100% 100%,0 100%);}
.scope .sx-tear-up{clip-path:polygon(0 0,100% 0,100% calc(100% - 2.3rem),
    85% calc(100% - 1.2rem),68% calc(100% - 2.4rem),47% calc(100% - .9rem),
    29% calc(100% - 2.6rem),12% calc(100% - 1.1rem),0 calc(100% - 2.2rem));}""",
    ),

    # ── MOTION ───────────────────────────────────────────────────────
    "THE KINETIC HERO": Move(
        group="MOTION",
        intent="the headline arrives line by masked line, the accent word "
               "landing last with its own gesture. One time, on arrival",
        recur="the hero only. This is the page's one signature motion moment",
        # NEVER animate a property the page also sets elsewhere: an animation
        # with fill-mode:forwards outranks inline styles for ever. The live
        # KMJ page lost its cursor-drift signature to exactly that.
        css=""".scope .sx-line{display:block;overflow:hidden;}
.scope .sx-line>span{display:block;transform:translateY(110%);
  animation:sx-rise .82s cubic-bezier(.22,1,.36,1) forwards;}
.scope .sx-line:nth-child(2)>span{animation-delay:.10s}
.scope .sx-line:nth-child(3)>span{animation-delay:.20s}
@keyframes sx-rise{to{transform:translateY(0)}}
@media (prefers-reduced-motion:reduce){
  .scope .sx-line>span{animation:none;transform:none}}""",
    ),

    "THE DEPTH": Move(
        group="MOTION",
        intent="two or three layers drifting at different speeds on scroll — "
               "subtle, never seasick",
        recur="the hero field and one later chapter; transform only",
        css=""".scope .sx-par{will-change:transform;}
.scope .sx-par-slow{transform:translate3d(0,calc(var(--sx-scroll,0) * .04px),0);}
.scope .sx-par-mid{transform:translate3d(0,calc(var(--sx-scroll,0) * .09px),0);}
@media (prefers-reduced-motion:reduce){
  .scope .sx-par-slow,.scope .sx-par-mid{transform:none}}""",
    ),

    "THE ORBIT": Move(
        group="MOTION",
        intent="the work turning slowly in 3D space as the gallery's "
               "signature — reserved for businesses whose work IS the show",
        recur="the gallery only, once",
        css=""".scope .sx-orbit{perspective:1200px;}
.scope .sx-orbit-ring{position:relative;transform-style:preserve-3d;
  animation:sx-turn 38s linear infinite;}
.scope .sx-orbit-ring>*{position:absolute;inset:0;backface-visibility:hidden;}
@keyframes sx-turn{to{transform:rotateY(360deg)}}
.scope .sx-orbit:hover .sx-orbit-ring{animation-play-state:paused}
@media (prefers-reduced-motion:reduce){
  .scope .sx-orbit-ring{animation:none}}""",
    ),

    "THE PIN": Move(
        group="MOTION",
        intent="one scroll scene that HOLDS while its content changes beside "
               "it — the modern storytelling beat",
        recur="once. A second pin turns a beat into a gimmick",
        # A held scene is motion to the reader even though nothing animates
        # — the ground moves under a fixed element. Release it for anyone
        # who asked for less motion, same as the animated moves.
        css=""".scope .sx-pin-wrap{display:grid;grid-template-columns:1fr 1fr;
  gap:3rem;align-items:start;}
.scope .sx-pin{position:sticky;top:14vh;align-self:start;}
@media (max-width:860px){.scope .sx-pin-wrap{grid-template-columns:1fr}
  .scope .sx-pin{position:static}}
@media (prefers-reduced-motion:reduce){.scope .sx-pin{position:static}}""",
    ),
}

MOVE_NAMES: List[str] = list(MOVES)


def _grouped() -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for name, m in MOVES.items():
        out.setdefault(m.group, []).append(name)
    return out


def director_block() -> str:
    """The Director's vocabulary — generated from the SAME list the builders
    are taught, so a move can never again be specified without a renderer."""
    lines = [
        "THE MOVES VOCABULARY — the difference between \"has a motif\" and "
        "\"is built out of its motif.\" These are named moves with REAL "
        "renderers behind them: every one below has a working CSS primitive "
        "the builder has been taught. Your spec commits to ONE OR TWO by "
        "name and writes exactly where each recurs (a move used once is "
        "decoration; used three ways it becomes the site's spine):",
    ]
    for group, names in _grouped().items():
        label = {"STRUCTURAL": "", "MATERIAL": "MATERIAL MOVES:",
                 "MOTION": "MOTION MOVES (pure CSS; the builder cannot load "
                           "external scripts):"}.get(group, f"{group}:")
        if label:
            lines.append(label)
        for n in names:
            m = MOVES[n]
            lines.append(f"- {n}: {m.intent}. RECURRENCE: {m.recur}.")
    lines.append(
        "Choose from this vocabulary or invent a move of equal specificity "
        "and NAME it — \"tasteful animations\" is not a move. Naming a move "
        "commits the builder to its primitive, so name only what you want "
        "built. The chosen move(s) must appear in section 1 by name, in "
        "section 3 at every recurrence, and in section 4 with their exact "
        "behavior.")
    return "\n".join(lines)


def builder_block(scope_hint: str = "your root class") -> str:
    """The primitives, for an authoring prompt.

    This is the half that never existed. The author was asked for "a warm
    radial glow" in adjectives, given no technique, and forbidden from the
    obvious one — so it produced flat grounds and the judge marked it down
    for the absence."""
    head = [
        "== THE MOVES — WORKING PRIMITIVES ==",
        "When the spec names a move, you build it with the primitive below. "
        "These are validator-legal: they tint with color-mix() against the "
        f"--sx-* tokens (NEVER a hex literal, NEVER rgb()/hsl(), rgba() only "
        f"as rgba(0,0,0,x)/rgba(255,255,255,x), NEVER url()). Replace "
        f"`.scope` with {scope_hint}. Adapt geometry to the composition; keep "
        "the technique.",
        "",
        "THE TINTING RULE, because it is the one nobody guesses: to use the "
        "brand accent at partial strength write "
        "color-mix(in srgb, var(--sx-accent) 26%, transparent). That is how "
        "every glow, wash, hairline and tinted ground on this platform is "
        "built. A flat var(--sx-accent-soft) fill is not a glow.",
        "",
    ]
    body = []
    for name, m in MOVES.items():
        body.append(f"--- {name} — {m.intent}")
        body.append(m.css)
        body.append("")
    return "\n".join(head + body).rstrip()


def move_names_in(text: str) -> List[str]:
    """Which moves a spec document actually commits to. Used to check that
    what the Director named is what the page got."""
    up = (text or "").upper()
    return [n for n in MOVE_NAMES if n in up]
