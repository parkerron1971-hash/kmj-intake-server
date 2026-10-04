# builder_v2.py
# ─────────────────────────────────────────────────────────────────────
# REVAMP PHASE 2 — BUILDER V2 (docs/REVAMP_TARGET.md Layer 4, signed).
#
# ONE mind, ONE call, the whole page — the claude.ai/Emergent mechanism
# proven in the local renders — executing the APPROVED SPEC as law.
# The contract armor runs AFTER authorship, never fighting it:
#
#   MECHANICAL (deterministic, zero model calls — Amendment 1):
#     - THE ANNOTATOR: a real DOM walk injects any missing
#       data-override-target stamps so Edit Mode always works.
#       Editability is the platform's guarantee, not the model's job.
#     - JS ARMOR: scripts scanned against the banned list; a bad
#       script is dropped, never fatal.
#     - EXTERNAL-REQUEST ARMOR: only Google-Fonts links and https
#       images survive; everything else is stripped.
#   AUTHORSHIP LAWS (repair-worthy — deterministic):
#     - TRUTH: every digit-run in visible text must trace to the data.
#     - COVERAGE: every inventory image present by url; nav, contact
#       form (posting to the real endpoint), and footer present.
#     - DASH LAW / HEAD+SHARE / INTERACTION GRAMMAR / REVEAL SAFETY
#       (Kevin's review, 2026-07-25): no dash-spliced copy; real
#       title/description/og:image; galleries open closer (lightbox);
#       no IntersectionObserver-only reveals (the reveal-skip bug).
#     - ONE surgical law repair; repair fails again → fallback (None)
#       and the old path takes over, wearing the spec's tokens via the
#       bridge.
#   THE EYES (Arc 2 — the vision loop, SITE_V2_VISION_LOOP, default on):
#     - The builder WALKS its own render (scroll top/middle/bottom at
#       390 + 1440, one ultrawide look) and measures the screenshots
#       against the spec + the standing checklist (alignment, blank
#       sections, caption truth, grammar, legibility, spec fidelity).
#     - ONE vision repair, surgical. Quality is never fatal: eyes
#       unavailable or repair breaks a law → the law-passing document
#       ships and the report says exactly what happened.
#
# Gated on SITE_BUILDER_V2=on (default OFF). The v2 document joins
# render_and_persist at the same seam the canvas uses (_canvas_html),
# so slot population, overrides, the token bridge, the easel step and
# the judge all apply unchanged. Model-portable by construction: the
# prompt carries no model-specific syntax; model/limits live in env
# (BUILDER_V2_MODEL / BUILDER_V2_MAX_TOKENS) and every call rides the
# model_ladder.
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import llm_call
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("builder_v2")

# THE CEILING (2026-08-29, the builder bench). Opus 5 and Fable 5 both
# returned EXACTLY 28,000 output tokens on KMJ's Blueprint — the cap —
# cut before </html>, unparseable, and the build fell to the module
# engine after paying for the whole thing. The 5-family spends part of
# its budget thinking; the same page finished whole under 64k with a
# streaming call. 4.8's pages ran 20-22k and are untouched by this.
V2_MAX_TOKENS_DEFAULT = 64000
# THE HARD BUDGET: output tokens one build may spend across every call
# (author, continuation, repair, vision repair). When the next call
# would cross it, the build keeps the best document it has and the
# report says which round was skipped — never a re-roll into the same
# wall, never a second charge for nothing.
V2_OUTPUT_BUDGET_DEFAULT = 120000
V2_TEMPERATURE = 0.8

# The builder thinks at HIGH effort on every model. Opus 5 defaults to
# high; Opus 5.5 defaults to medium, so switching BUILDER_V2_MODEL to it
# without this would quietly make every build shallower (2026-09-22).
# Where the model takes no effort setting this adds nothing.
BUILDER_EFFORT = (os.environ.get("BUILDER_V2_EFFORT") or "high").strip().lower()


def _gen_kwargs(model: str, temperature: Optional[float]) -> Dict[str, Any]:
    """Sampling and effort for one builder call, each only where the
    model accepts it (a rejected one is a 400, not a no-op)."""
    import model_ladder
    return {**model_ladder.sampling_kwargs(model, temperature),
            **model_ladder.sdk_effort_kwargs(model, BUILDER_EFFORT)}
# 2026-10-01 (Kevin, the concept-layer plan): 300 KB sent richer pages to
# the fallback engine whole. Library objects (letters, seals, tickets,
# boarding passes) carry real markup, so the ceiling is 450 KB.
DOC_MAX_BYTES = 450 * 1024

_ALLOWED_LINK_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")
# AUDIT FIX (flight one): the 2-digit rule attacked the DESIGN — the
# spec's own section numerals (01, 02…) and the copyright year were
# flagged as invented facts, firing repairs that pressured the author
# to strip its own design language. CLAIMS are 3+ digit runs; 1-2
# digit ordinals are layout, and the current year is a date, not a
# claim. (Trade-off accepted: an invented 2-digit stat now passes the
# automated trace — the judge and the owner remain its referees.)
_DIGIT_RUN_RE = re.compile(r"\d{3,}")
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)

_JS_BANNED = (
    "eval(", "new Function", "fetch(", "XMLHttpRequest", "import(",
    "WebSocket", "document.write", "localStorage", "sessionStorage",
)


def contact_endpoint(business_id: str) -> str:
    """The one url the page's script is allowed to fetch: the platform's
    own contact-submit endpoint (a JSON POST — a native form post can't
    reach it, so the script MUST carry this call for the form to work)."""
    return (f"https://kmj-intake-server-production.up.railway.app"
            f"/sites/{business_id}/contact-submit")


def enabled() -> bool:
    return (os.environ.get("SITE_BUILDER_V2") or "").strip().lower() in (
        "on", "1", "true", "yes")


def _model() -> str:
    m = (os.environ.get("BUILDER_V2_MODEL") or "").strip()
    if m:
        return m
    try:
        import canvas
        return canvas._model()
    except Exception:
        return "claude-sonnet-4-5-20250929"


def _max_tokens() -> int:
    try:
        return max(8000, int(os.environ.get("BUILDER_V2_MAX_TOKENS")
                             or V2_MAX_TOKENS_DEFAULT))
    except ValueError:
        return V2_MAX_TOKENS_DEFAULT


def _output_budget() -> int:
    try:
        return max(_max_tokens(), int(os.environ.get("BUILDER_V2_OUTPUT_BUDGET")
                                      or V2_OUTPUT_BUDGET_DEFAULT))
    except ValueError:
        return V2_OUTPUT_BUDGET_DEFAULT


def new_spend() -> Dict[str, Any]:
    """The build's running receipt: every model call this build made,
    in one place, so the budget is a number and the report can say
    what a page cost. cost_cents comes from api_usage_logger's price
    table (the one that also writes the api_usage row)."""
    return {"calls": 0, "input_tokens": 0, "output_tokens": 0,
            "cost_cents": 0.0, "skipped": []}


def _record_spend(spend: Optional[Dict[str, Any]], model: str,
                  usage: Any) -> None:
    if spend is None:
        return
    i = int(getattr(usage, "input_tokens", 0) or 0)
    o = int(getattr(usage, "output_tokens", 0) or 0)
    spend["calls"] += 1
    spend["input_tokens"] += i
    spend["output_tokens"] += o
    try:
        from api_usage_logger import _compute_cost_cents
        spend["cost_cents"] = round(spend["cost_cents"]
                                    + _compute_cost_cents(model, i, o, 0, 0), 4)
    except Exception:
        pass


def _budget_left(spend: Optional[Dict[str, Any]]) -> bool:
    if spend is None:
        return True
    return spend["output_tokens"] < _output_budget()


CONTINUE_PROMPT = ("Your document was cut off by the output limit. Continue "
                   "EXACTLY from the last character you wrote — no preamble, "
                   "no repetition of anything already written, no code fence — "
                   "until the document ends with </html>.")


# ─── the prompt (model-portable: plain instructions, no syntax) ──────

_SYSTEM = """You are a master web designer-craftsperson building ONE complete production web page in a single pass. You hold the whole page in mind at once — every decision coherent with every other. You were chosen because one sighted mind beats a pipeline of blind stages.

THE LAW OF THE PAGE is the approved design specification the owner has read and signed. Execute it exactly: its sections, its written copy, its named signature move, its color and font roles. Where the spec is silent, decide with craft in the spec's spirit — never retreat to a generic median.

HARD RULES (a validator checks each; violations cost a repair round):
1. Output ONE complete HTML document: <!DOCTYPE html> through </html>. Inline <style>. At most one <script> (a single IIFE, DOM-only: class toggles, listeners on elements you rendered; the page must stay fully coherent with JS disabled). THE SCRIPT'S ONE NETWORK CALL: the contact-form submit of rule 9 is the only fetch permitted, written with the endpoint url inline as a string literal — fetch("<the given endpoint>", …). A security pass strips the ENTIRE script if it contains any other fetch, XMLHttpRequest, eval, storage, or dynamic import — and with the script go your reveals, lightbox, and filters. Nothing else on the page may touch the network.
2. TRUTH: every fact, number, price, and claim on the page appears in the REAL DATA below. Nothing invented — a stat the data doesn't prove renders as a clearly-marked editable placeholder, never a made-up figure.
3. COVERAGE: every listed image appears (exact url in src); a fixed navigation; a working contact form posting to the given endpoint (method="POST", the given action url, name/email fields at minimum); a footer. Every real service/offering has a home, with its price and, when the data carries duration_min, its duration in minutes beside the price.
4. EXTERNAL REQUESTS: Google Fonts stylesheet links, the provided https image urls, and the one contact-form fetch of rule 9 ONLY. No other external scripts, styles, frames, or calls.
5. EDITABILITY: stamp data-override-target="v2/f1", "v2/f2", … on headings, paragraphs, and captions as you write them (a platform pass guarantees any you miss — stamping well keeps the labels meaningful). Every top-level <section> carries a unique, meaningful id (id="prices", id="story"): the navigation anchors to it, the review names it, and a repair can rebuild that one section without touching the rest.
6. MOBILE: a real responsive pass in the same document — media queries so every section holds at 390px. What breaks on a phone fails the whole page. The page must also hold on wide screens (1900px+): content keeps an intentional measure, backgrounds and motifs extend, nothing stretches thin or drifts off-grid.
7. The spec's color hexes and font names are law — write them directly in your CSS, once, as :root custom properties named as the spec names them; everything below :root is a var() reference or a color-mix() against those tokens, never a second literal.
8. COPY GRAMMAR (the DASH LAW): never splice a sentence with a dash. No em dashes, no " - " splices in headings, paragraphs, or list copy — rewrite with a period, comma, or colon. A dash may appear only inside a proper title supplied by the data (an artwork or event name).
9. INTERACTION GRAMMAR — controls do what they promise: a gallery of images opens each piece larger on click (a lightbox: element id="lightbox", dimmed backdrop, the artwork with its title, closes on backdrop click, a close button, and Escape); category filters actually filter and an empty result states so in words, never blank space; the contact form intercepts submit and POSTs JSON {name, email, phone, message} via fetch to the given endpoint (the url inline as a string literal — the endpoint reads JSON, so a bare native form post cannot reach it), disables the button while sending, then shows a visible confirmation state in place; every clickable element answers hover AND keyboard focus; anything that opens can be closed.
10. REVEAL SAFETY: if content starts hidden for a scroll reveal, the reveal must be scroll-position driven (on scroll, anything whose top has passed the reveal line becomes visible), so fast scrolling can NEVER leave a section invisible. Never rely on an IntersectionObserver alone. Honor prefers-reduced-motion by showing everything.
11. INVENTORY-SHAPED LAYOUT: compose the gallery/grid to the number of images that actually exist. Two images get a two-image composition; never a grid with holes, never a repeated image as filler.
11b. ART-DIRECTED DROP SLOTS: when the composition WANTS an image the inventory doesn't have (a hero portrait, a third gallery piece), author a placeholder the owner can fill: <div class="sx-drop" data-sx-slot="short_name">…</div> containing ONE line of shot direction in plain words ("You at the chair, mid-cut, warm light" — you are telling them what to photograph). Style: a dashed 1px frame in the accent color at low opacity, the design's crop and position already decided, so a dropped-in photo inherits your intention. Your CSS MUST include `.sx-drop{display:none}` and `body.sx-studio .sx-drop{display:flex;…}` — the public page never shows an empty frame; the owner's Studio reveals them. Never fake an image, never leave a hole: real, or an art-directed drop slot.
11c. NO VISIBLE STAND-INS: a photo the inventory lacks is INVISIBLE to the visitor. Never author a "filled" or "art-directed" placeholder that reads as intentional — no tinted or textured box, no framed panel, no caption-only frame, no italic line describing the photograph that should be there. The hidden .sx-drop of 11b is the ONLY stand-in; its shot direction never appears outside it. HERO without a hero photo: a typographic hero — display type carries the composition and rule 15's presence is a ghost word or the signature motif, never an empty frame. WORK/GALLERY with fewer than two real photos: no photo grid at all — say what you make and how it feels in words, with drop slots the Studio reveals. A visitor must never be able to tell a photo is missing.
11d. ONE PLACE PER PHOTO: each real photo appears once on the page (the lightbox copy doesn't count). When more places want a photo than the inventory has, the extra places get a hidden .sx-drop (11b) or a typographic treatment — never the same photo twice.
12. ALIGNMENT LAW: photographic subjects fill their frames (cover-fit, deliberate crop anchor); edges align to the type they sit beside; nothing floats small inside an oversized border. LAYERING ON PURPOSE: when you overlap elements deliberately (a cut-out crossing a section edge, a nameplate over a photo, an object breaking its frame, ghost type behind a headline), put data-overlap-ok on the outer element of the layered piece. The render is measured, and any other overlap of text on text counts as a collision.
13. HEAD + SHARE: a real <title>, a meta description written from the data, and og:title / og:description / og:image (the strongest image url from the data) so a shared link looks intentional.
14. CONNECTED DOORS: the data's CONNECTED SYSTEMS block lists working doors the owner turned on (booking, store, events) with their exact urls — each appears on the page as a REAL link twice over: in the navigation, and as a devoted moment styled to the spec (a Book action, a shop section, an Upcoming Events moment that invites the visitor to see the dates and RSVP). Use the exact url given. Never invent a door the block doesn't carry; never render a dead placeholder for one it does.
15. FILLED SPACE: the hero's off-axis half holds a presence (real work in the light, a ghost word, the signature motif) — never bare ground beside the headline. Gaps between sections carry the page's connective architecture; no featureless band taller than half a viewport. Execution notes: staggered cascades via transition-delay stepped by item index on the same scroll-driven reveal class; sequential fills (steps, thread stations) keyed to scroll position; ghost type is aria-hidden and never traps selection; a marquee is CSS-only, slow, and frozen under prefers-reduced-motion; a cursor-following glow is desktop-only, subtle, transform-based.
16. THE TYPE FLOOR (measured on the render; a miss costs a repair round): exactly one <h1> (the hero headline), headings stepping down one level at a time. Set a type scale with clamp() and keep to it. Display sizes tighten their tracking (-0.01em to -0.03em); uppercase labels open theirs (0.08em or more). Running text is 16px or larger on a phone and never under 14px; nothing a visitor reads is under 11px. Body copy holds a 45 to 75 character measure (max-width in ch). Headings get text-wrap: balance and paragraphs text-wrap: pretty. Digits that line up (prices, hours, durations, stats) get font-variant-numeric: tabular-nums. When a face offers an optical-size axis, request it in the Google Fonts url (opsz) and set font-optical-sizing: auto. Buttons, inputs and selects inherit the page's fonts (font: inherit). No paragraph longer than three lines is centered. At most two type families, three with a utility face. Write straight quotes freely: a typographer pass sets real quotes, apostrophes and ranges after you.
17. THE CONCEPT: the blueprint's section 0 sets how far the page's idea goes, and the page obeys it. PLAIN: nothing renamed, no objects. SIGNATURE: the one object and the one or two renamed labels it names, nothing more. WORLD: the navigation and section names use its VOCABULARY, its OBJECTS hold the content, its LIVING DETAIL moves once. Every in-world label keeps its plain word, visible beneath it (a small line) or in the link's aria-label, so a first-time visitor never has to guess. A concept never hides what a thing is or what it costs. When section 0 says SCOPE: offer, this page is the home: it stays at SIGNATURE and links to the offer page.
18. THE LAYOUT: section 0's LAYOUT line names one of twelve page layouts, and THE LAYOUT block in the build message gives its skeleton, structure and phone plan. Build that architecture: it decides how the page is put together (columns, the size of the opening, how the sections stack), while the spec decides what goes in it and the design language how it looks. The render is measured against the layout, and a clear miss costs a repair round.

CRAFT FLOOR: generous, complete pages beat austere concepts; restraint disciplines color and motion, never content. Light the stage (glow, texture, gradient depth) — never a flat rectangle. One signature moment, executed exactly as the spec draws it. POLISH: a themed ::selection color, :focus-visible states, honest alt text on every image, aspect-ratio reserved on media so nothing jumps while loading, loading="lazy" below the fold. ONE PHOTO TREATMENT: every content photo wears one treatment defined once from the tokens (a grade, a tint, or a duotone through filter or a mix-blend overlay in the accent), applied by one class, so photos taken on different days read as one shoot. The brand mark is never treated.

OUTPUT: the HTML document only. No commentary, no code fences."""



# THE PRIMITIVES (2026-08-09 design review) — see design_moves.
# The atmosphere techniques the spec names were never taught to any
# author, while the colour validator banned the natural syntax.
# 2026-10-01 (the concept-layer plan): the system prompt keeps the colour
# voice and the tinting rule; the CSS for the moves a blueprint names
# rides that build's own message (build_user_prompt). All thirteen
# primitives in front of every build was 8,300 characters for the one or
# two a blueprint commits to, and the invariant the moves tests guard
# holds either way: a named move always arrives with its primitive.
import design_moves as _dm
_SYSTEM = _SYSTEM + chr(10)*2 + _dm.tinting_block(color_law="hexes").replace(
    "no url().", "no url() (the one exception: the object library's own paper "
    "grain, inside data-sx-object elements).")
_SYSTEM = _SYSTEM + "\n\n== TWO HARD RULES ON WHAT THE PAGE DOES WITHOUT HELP ==\n\n1. THE PAGE MUST SURVIVE WITHOUT JAVASCRIPT.\nScroll-reveal is the classic way to ship a blank page. If you write\n`.reveal{opacity:0}` and clear it from script, then ANY script error, a\nblocked asset, or a crawler that does not execute JS sees your nav and a\nblack rectangle. On the live site this hid 14 elements below the hero.\nSo: gate every reveal on a class the script itself adds, and give a\nno-script escape.\n\n   <script>document.documentElement.className+=' js'</script>  (put it in <head>)\n   .js .reveal{opacity:0;transform:translateY(14px)}\n   .js .reveal.in{opacity:1;transform:none}\n   <noscript><style>.reveal{opacity:1!important;transform:none!important}</style></noscript>\n\nNever write a bare `.reveal{opacity:0}`. Content is visible by default and\nJS may only take it away.\n\n2. THE BRAND MARK IS NOT A PORTFOLIO PIECE.\nUse the BRAND MARK url from the real-data block for the header logo, and\nnothing else. If no mark was supplied, set a typographic wordmark. A\ngallery image in the header is a broken brand: it shipped once as a\n1200x675 campaign flyer squashed into a 59x34 box. Give the mark its own\nbox with object-fit: contain so it keeps its aspect ratio.\n"

# THE BLUEPRINT IS SETTLED (2026-10-03, the proof build): the page matched
# 28 of the blueprint's 32 promises, and two of the misses came from the
# builder's own review overriding a decision it could not see. The eyes
# read the first 2,400 characters of a 19,000-character blueprint, the
# section rebuilder the first 6,000, and the whole-page repair none at
# all, so "No length or price shown: neither is on file" became "Fee on
# request", and the struck "new job" the blueprint saved for the story was
# copied into the hero. A designer reviewing a page knows what was agreed
# with the client: every look and every repair now carries the whole
# blueprint, and a note never undoes one of its decisions.
BLUEPRINT_CAP = 24000
BLUEPRINT_SETTLED = (
    "THE BLUEPRINT IS SETTLED: the owner approved it. Its concept, its section "
    "plan, what it decided and declined, and its rules are decisions, not "
    "suggestions. A repair note never undoes one: if a note asks for something "
    "the blueprint declined or placed elsewhere (a price or length it chose not "
    "to show, an object it put in one section copied into another, a ghost word "
    "on the other edge), keep the blueprint and fix only how well the page "
    "carries it out.")


def _blueprint(spec_text: str) -> str:
    return (spec_text or "").strip()[:BLUEPRINT_CAP]


def eyes_blueprint_block(spec_text: str) -> str:
    """What the eyes read first: the whole approved blueprint, settled."""
    return ("THE APPROVED BLUEPRINT (agreed with the owner; its decisions are "
            "settled, judge how well the page carries them out):\n" + _blueprint(spec_text))


def build_user_prompt(spec_text: str, real_data: str,
                      violations: Optional[List[str]] = None,
                      prior_doc: str = "", page_brief: str = "") -> str:
    """Pure prompt assembly (testable). With violations + prior_doc it
    becomes the ONE surgical repair prompt (Amendment 1: minimal edits,
    never a fresh re-roll)."""
    if violations:
        return "\n".join([
            "SURGICAL REPAIR — your page failed validation on these exact "
            "points. Fix ONLY what each violation requires; every other "
            "byte of the document stays as you wrote it. Do not redesign, "
            "do not rewrite unaffected sections.",
            "",
            "VIOLATIONS:",
            *[f"- {v}" for v in violations[:12]],
            "",
            BLUEPRINT_SETTLED,
            "",
            "THE APPROVED BLUEPRINT (settled; the law of the page):",
            _blueprint(spec_text),
            "",
            "THE REAL DATA (the only source of facts):",
            real_data.strip()[:12000],
            "",
            "YOUR DOCUMENT:",
            prior_doc,
            "",
            "Output the corrected complete HTML document only.",
        ])
    parts = [
        "== THE APPROVED SPEC (the law of the page — the owner read and "
        "approved this document) ==",
        spec_text.strip(),
        "",
    ]
    if page_brief.strip():
        parts += [page_brief.strip(), ""]
    primitives = _dm.primitives_block(_dm.move_names_in(spec_text))
    if primitives:
        parts += [primitives, ""]
    # THE OBJECTS (2026-10-01): the library objects the blueprint's concept
    # sheet names arrive with their working source, the way named moves
    # arrive with their primitives.
    try:
        import site_objects
        objects = site_objects.builder_block(site_objects.object_names_in(spec_text))
    except Exception as e:
        logger.info(f"[v2] object library skipped: {e}")
        objects = ""
    if objects:
        parts += [objects, ""]
    # THE LAYOUT (2026-10-03, the hand-build plan): the architecture the
    # blueprint's concept sheet chose, with its working recipe.
    layout = layout_block_for(spec_text)
    if layout:
        parts += [layout, ""]
    parts += [
        "== THE REAL DATA (the only facts you may render; every image url "
        "listed here must appear on the page) ==",
        real_data.strip()[:16000],
        "",
        "Build the complete page now.",
    ]
    return "\n".join(parts)


def layout_key_for(spec_text: str) -> Optional[str]:
    """The layout the blueprint's concept sheet names, or None."""
    try:
        import site_concept
        import site_layouts
        return site_layouts.key_from_sheet(site_concept.parse_sheet(spec_text or ""))
    except Exception as e:
        logger.info(f"[v2] layout unreadable: {e}")
        return None


def layout_block_for(spec_text: str) -> str:
    try:
        import site_layouts
        return site_layouts.builder_block(layout_key_for(spec_text))
    except Exception as e:
        logger.info(f"[v2] layout block skipped: {e}")
        return ""


def layout_findings(spec_text: str, measures: Optional[Dict[str, Any]]) -> List[str]:
    """Clear misses between the render and the blueprint's layout."""
    try:
        import site_layouts
        return site_layouts.render_findings(layout_key_for(spec_text), measures)
    except Exception as e:
        logger.info(f"[v2] layout check skipped: {e}")
        return []


def _stated_truth(ctx: Dict[str, Any]) -> Dict[str, Any]:
    dd = (((ctx.get("site") or {}).get("site_config") or {})
          .get("discovery_dossier")) if isinstance(ctx.get("site"), dict) else None
    truth = (dd or {}).get("truth") if isinstance(dd, dict) else None
    return truth if isinstance(truth, dict) else {}


def stated_offers_block(ctx: Dict[str, Any]) -> str:
    """WHAT THE OWNER SAID THEY OFFER (2026-10-03, the hand-build plan):
    the offers, prices and hours the owner gave the Design Coach. Real
    facts in their words, so the page lists them the way a hand-build
    would, instead of "there's no package menu"."""
    truth = _stated_truth(ctx)
    lines: List[str] = []
    for o in (truth.get("offers") or [])[:12]:
        if not isinstance(o, dict) or not str(o.get("name") or "").strip():
            continue
        bits = [str(o.get(k)).strip() for k in ("price", "duration") if str(o.get(k) or "").strip()]
        note = str(o.get("note") or "").strip()
        lines.append(f"- {o['name']}" + (f": {', '.join(bits)}" if bits else "")
                     + (f" ({note})" if note else ""))
    hours = truth.get("hours")
    hv = str((hours.get("value") if isinstance(hours, dict) else hours) or "").strip()
    out: List[str] = []
    if lines:
        out.append("WHAT THE OWNER SAID THEY OFFER (in the design session, in their "
                   "words; real: give each its own home with its price and length "
                   "exactly as stated, and never a price they did not say):\n"
                   + "\n".join(lines))
    if hv:
        out.append(f"HOURS THE OWNER STATED: {hv}")
    return "\n\n".join(out)


def check_stated_offers(html: str, ctx: Dict[str, Any]) -> List[str]:
    """Each offer the owner named has a home on the page (soft tier)."""
    text = _visible_text(html).lower()
    out: List[str] = []
    for o in (_stated_truth(ctx).get("offers") or [])[:12]:
        name = str((o or {}).get("name") or "").strip() if isinstance(o, dict) else ""
        if name and name.lower() not in text:
            out.append(f"the owner's offer '{name}' is not on the page; give it a home "
                       "with its price and length exactly as they said them")
    return out[:4]


# ─── real data assembly ──────────────────────────────────────────────

def assemble_real_data(ctx: Dict[str, Any], business_id: str) -> str:
    """Everything true, in one block: business facts, offerings,
    testimonials, contact endpoint + channels, every image url, the
    discovery dossier digest."""
    parts: List[str] = []
    biz = ctx.get("business") or {}
    parts.append(f"BUSINESS: {biz.get('name') or ''} — type: "
                 f"{biz.get('type') or ''}")
    # THE OWNER'S WORDS (2026-09-04, the barbershop bench): the Director
    # read the practitioner's own prompt; the builder never did. What they
    # said about themselves ("I've been cutting 14 years") is a fact they
    # stated, and the page's author should hold it as one.
    owner = str(ctx.get("owner_brief") or "").strip()
    if owner:
        try:
            import canvas_brief
            cap = int(canvas_brief.OWNER_BRIEF_MAX_CHARS)
        except Exception:
            cap = 2400
        parts.append("THE OWNER'S WORDS (their own prompt for this build, "
                     "verbatim — facts they state about themselves are on "
                     "file):\n" + owner[:cap])
    contact = ctx.get("contact") if isinstance(ctx.get("contact"), dict) else {}
    ch = {k: v for k, v in contact.items()
          if isinstance(v, str) and v.strip()}
    if ch:
        parts.append("CONTACT CHANNELS: " + json.dumps(ch, ensure_ascii=False))
    parts.append("CONTACT FORM ENDPOINT (the form's action): "
                 + contact_endpoint(business_id))
    try:
        import atelier
        for mid in ("offerings", "testimonials", "statband", "faq", "store"):
            try:
                data = atelier._section_data(mid, {}, ctx)
            except Exception:
                continue
            if data:
                parts.append(f"[{mid}]\n"
                             + json.dumps(data, ensure_ascii=False)[:3000])
    except Exception as e:
        logger.info(f"[v2] section data skipped: {e}")
    # every image, by url
    imgs: List[str] = []
    slots = (((ctx.get("site") or {}).get("site_config") or {})
             .get("slots") or {})
    for name, rec in sorted(slots.items()):
        if isinstance(rec, dict) and not rec.get("removed") \
                and (rec.get("custom_url") or "").strip():
            imgs.append(f"- {rec['custom_url'].strip()} (owner upload: {name})")
    for g in (ctx.get("gallery") or []):
        if isinstance(g, dict) and (g.get("url") or "").strip():
            note = g.get("alt") or g.get("caption") or ""
            imgs.append(f"- {g['url'].strip()}"
                        + (f" ({note})" if note else ""))
    if imgs:
        parts.append("IMAGES (every one appears on the page, exact urls):\n"
                     + "\n".join(dict.fromkeys(imgs)))
    # THE BRAND MARK (2026-08-09, Kevin: "my logo doesn't get on the site").
    # The inventory above is slots + gallery, and the owner's logo lives in
    # NEITHER — it is uploaded to businesses.settings.brand_kit. The word
    # "logo" appeared zero times in this file, canvas.py and atelier.py, so
    # no page author had ever been handed one. The Director COULD see it
    # (spec_author sends it as a vision block) and wrote specs referencing a
    # mark in the header; the builder, holding only portfolio pieces,
    # drafted a 1200x675 campaign flyer into a 59x34 header slot and
    # shipped it as the brand.
    try:
        import brand_mark
        parts.append(brand_mark.real_data_block(
            ctx, business_id, (biz.get("name") or "")))
    except Exception as e:
        logger.info(f"[v2] brand mark skipped: {e}")
    try:
        import discovery
        dd = (((ctx.get("site") or {}).get("site_config") or {})
              .get("discovery_dossier"))
        digest = discovery.dossier_digest(dd)
        if digest:
            parts.append("DISCOVERY DOSSIER (the owner's confirmed answers):\n"
                         + digest)
    except Exception:
        pass
    stated = stated_offers_block(ctx)
    if stated:
        parts.append(stated)
    block = connected_systems_block(business_id, ctx)
    if block:
        parts.append(block)
    # THE OFFER PAGE (2026-10-01): a World concept scoped to one offer is
    # built as its own page; the home page links to it.
    offer = ctx.get("offer_page") if isinstance(ctx.get("offer_page"), dict) else {}
    if offer.get("path"):
        try:
            import site_pages
            parts.append(site_pages.offer_line(offer["path"], offer.get("name") or ""))
        except Exception as e:
            logger.info(f"[v2] offer line skipped: {e}")
    # ONE SET OF FACTS (2026-08-29): the same block the Director read, so
    # a founding year the Blueprint states is traceable here and the
    # truth law never deletes a true sentence again.
    try:
        import site_facts
        parts.append(site_facts.facts_block(site_facts.build_facts(ctx, business_id)))
    except Exception as e:
        logger.info(f"[v2] facts block skipped: {e}")
    return "\n\n".join(parts)


_CONNECTED_LINE_RE = re.compile(
    r"^- (BOOKING|STORE|EVENTS): ON — .*?(https://\S+)", re.MULTILINE)
_STORE_OFF_LINE_RE = re.compile(r"^- STORE: OFF\b", re.MULTILINE)
# a link to a shop that is not there: /store or /shop as a path on any
# origin (the author invents it on the site's own), or a bare #store
_DEAD_STORE_HREF_RE = re.compile(
    r"href\s*=\s*[\"'](?:https?://[^\"'/]+)?/(?:store|shop)(?:[/?#\"'])",
    re.IGNORECASE)
_STORE_SECTION_RE = re.compile(
    r"<section\b[^>]*\b(?:id|class)\s*=\s*[\"'][^\"']*\b(?:store|shop)\b",
    re.IGNORECASE)


def connected_systems_block(business_id: str,
                            ctx: Optional[Dict[str, Any]] = None) -> str:
    """THE WIRED-SITE CONTRACT: the working doors the page MUST carry.
    A door is ON when the platform has it live AND the owner hasn't
    turned it off in the dossier (silence defaults to wired — a working
    system unreachable from the site is the dead-weight rule violated
    at platform scale). Format is law: check_connected parses these
    exact lines."""
    try:
        import offering_profiles
        state = offering_profiles.business_state(business_id)
    except Exception as e:
        logger.info(f"[v2] connected-systems probe skipped: {e}")
        return ""
    caps: Dict[str, Any] = {}
    try:
        dd = ((((ctx or {}).get("site") or {}).get("site_config") or {})
              .get("discovery_dossier")) or {}
        caps = dd.get("capabilities") or {}
    except Exception:
        caps = {}

    def _off(name: str) -> bool:
        leaf = caps.get(name)
        return isinstance(leaf, dict) and \
            str(leaf.get("value")).strip().lower() == "off"

    lines: List[str] = []
    if state.get("booking_enabled") and state.get("booking_url") \
            and not _off("booking"):
        lines.append(f"- BOOKING: ON — every book/schedule action links "
                     f"to {state['booking_url']}")
    if state.get("store_url") and not _off("store") \
            and _store_has_products(ctx):
        lines.append(f"- STORE: ON — the shop moment links to "
                     f"{state['store_url']}")
    elif state.get("store_url"):
        # THE DEAD DOOR (2026-08-28, MaCnificent Hair Co): with no
        # products the store line was simply absent, and the author
        # invented "The shop — browse and order online" linking to
        # /store on the site's own origin — a shop with nothing in it.
        # Say OFF out loud; check_connected enforces it.
        lines.append("- STORE: OFF — there is nothing in the shop yet. "
                     "No shop section, no shop link, no /store url "
                     "anywhere on the page.")
    if state.get("events_enabled") and state.get("events_url") \
            and not _off("events"):
        lines.append(f"- EVENTS: ON — the Upcoming Events moment and an Events "
                     f"link in the navigation link to {state['events_url']} "
                     f"— visitors see the dates and RSVP there")
    if not lines:
        return ""
    return ("CONNECTED SYSTEMS (working doors the owner turned on — "
            "each url below MUST appear on the page as a real link; "
            "never invent a door not listed here):\n" + "\n".join(lines))


def _store_has_products(ctx: Optional[Dict[str, Any]]) -> bool:
    """A store door only counts when something is actually in it — an
    empty shop page linked from the site is its own dead end."""
    try:
        import atelier
        data = atelier._section_data("store", {}, ctx or {})
        return bool(data)
    except Exception:
        return False


# ─── the stand-in law (2026-08-28, MaCnificent Hair Co) ──────────────
# The first build for a business with no photos shipped its hero and
# every gallery tile as a "filled art-directed placeholder": a tinted,
# braid-textured box with an italic line describing the photograph that
# should have been there. Rule 11b had said the public page never shows
# an empty frame — the author obeyed the letter (its .sx-drop was hidden)
# and wrote a SECOND, visible stand-in beside it. The eyes saw it ("an
# empty caramel-tinted box containing only a caption") and the vision
# repair could not conjure photographs. So: a deterministic law that
# names the pattern, feeds the repair, and — because a stand-in is a
# quality defect, not a lie — never sends the build to the fallback.

_STANDIN_TAG_RE = re.compile(r"<(\w+)\b[^>]*\bclass=\"([^\"]*)\"[^>]*>",
                             re.IGNORECASE)
_STANDIN_TOKEN_RE = re.compile(
    r"(?:^|[-_])(?:slot|placeholder|standin|stand-in|photo-?(?:frame|box))"
    r"(?:[-_]|$)", re.IGNORECASE)
_DROP_OPEN_RE = re.compile(r"<(\w+)\b[^>]*\bclass=\"[^\"]*\bsx-drop\b[^\"]*\"[^>]*>",
                           re.IGNORECASE)
_STANDIN_WORD_RE = re.compile(r"[A-Za-z']{4,}")


def _drop_spans(html: str) -> List[Tuple[int, int]]:
    """(start, end) of every .sx-drop element, nesting-aware."""
    spans: List[Tuple[int, int]] = []
    for m in _DROP_OPEN_RE.finditer(html):
        tag = m.group(1).lower()
        depth, pos = 1, m.end()
        tag_re = re.compile(rf"</?{tag}\b", re.IGNORECASE)
        while depth and pos < len(html):
            n = tag_re.search(html, pos)
            if not n:
                pos = len(html)
                break
            depth += -1 if html[n.start() + 1] == "/" else 1
            pos = n.end()
        spans.append((m.start(), pos))
    return spans


def _in_spans(i: int, spans: List[Tuple[int, int]]) -> bool:
    return any(a <= i < z for a, z in spans)


def check_stand_ins(html: str) -> List[str]:
    """Deterministic: visible stand-ins for missing photographs.
    (1) any non-<img> element whose class names a slot / placeholder /
        stand-in / photo-frame OUTSIDE a hidden .sx-drop;
    (2) a CAPTION ECHO: the shot direction inside an .sx-drop repeated as
        visible copy beside it (a description of a photo that is not
        there). Each finding names the fix; the list is capped so the
        repair prompt stays surgical."""
    problems: List[str] = []
    spans = _drop_spans(html)
    seen_classes: List[str] = []
    for m in _STANDIN_TAG_RE.finditer(html):
        if m.group(1).lower() == "img" or _in_spans(m.start(), spans):
            continue
        tokens = m.group(2).split()
        if "sx-drop" in tokens:
            continue
        hit = next((t for t in tokens if _STANDIN_TOKEN_RE.search(t)), None)
        if hit and hit not in seen_classes:
            seen_classes.append(hit)
    if seen_classes:
        problems.append(
            "VISIBLE STAND-IN: elements classed "
            + ", ".join(f"'{c}'" for c in seen_classes[:4])
            + " are visible frames or captions standing in for photographs "
              "the inventory does not have. A missing photo is INVISIBLE to "
              "the visitor: remove these stand-ins (keep only the hidden "
              ".sx-drop). If this is the hero, make the hero typographic — "
              "display type plus a ghost word or the signature motif, no "
              "frame. If a gallery has fewer than two real photos, compose "
              "it without a photo grid.")
    # caption echo
    echoed = 0
    for a, z in spans:
        direction = _STANDIN_WORD_RE.findall(re.sub(r"<[^>]+>", " ", html[a:z]))
        keys = {w.lower() for w in direction}
        if len(keys) < 4:
            continue
        lo, hi = max(0, a - 2500), min(len(html), z + 2500)
        outside = "".join(
            html[i:j] for i, j in _outside_pieces(lo, hi, spans))
        words = {w.lower() for w in
                 _STANDIN_WORD_RE.findall(re.sub(r"<[^>]+>", " ", outside))}
        if len(keys & words) >= max(4, int(len(keys) * 0.6)):
            echoed += 1
    if echoed:
        problems.append(
            f"CAPTION ECHO: {echoed} drop slot(s) have their shot direction "
            "repeated as VISIBLE copy beside them — a description of a "
            "photograph that is not on the page. Delete the visible copy; "
            "the direction lives only inside the hidden .sx-drop.")
    return problems


def _outside_pieces(lo: int, hi: int,
                    spans: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """[lo, hi) minus every drop span — the visible neighbourhood."""
    pieces: List[Tuple[int, int]] = []
    cur = lo
    for a, z in sorted(spans):
        if z <= lo or a >= hi:
            continue
        if a > cur:
            pieces.append((cur, a))
        cur = max(cur, z)
    if cur < hi:
        pieces.append((cur, hi))
    return pieces


# ─── the repeated-photo law (2026-10-03, the real test build) ─────────
# The first real build after the concept layer shipped the same photo of
# the chair by the window twice: once in the gallery and again as the
# About portrait. The eyes caught the hero photo repeated in the gallery
# and rebuilt that section, but nothing deterministic counts photos, so
# the second repeat walked through. Each photo appears once; a place that
# wants a photo the inventory cannot spare gets a hidden .sx-drop (11b)
# or a typographic treatment. Soft tier: a repeat is a quality defect,
# never a fallback.

_IMG_SRC_RE = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*([\"'])(.*?)\1", re.IGNORECASE | re.DOTALL)
_STYLE_ATTR_RE = re.compile(r"\bstyle\s*=\s*(\"[^\"]*\"|'[^']*')", re.IGNORECASE)
_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
_CSS_URL_RE = re.compile(r"url\(\s*[\"']?(https?://[^\"')\s]+)", re.IGNORECASE)
# a copy no visitor sees as a second use: the lightbox, a dialog, anything
# aria-hidden, a template or a noscript fallback
_HIDDEN_HOST_RE = re.compile(
    r"<(?!(?:img|input|br|hr|meta|link|source|area|col|embed|wbr|track|param)\b)"
    r"(\w+)\b(?=[^>]*(?:\brole\s*=\s*[\"']dialog[\"']|\bid\s*=\s*[\"']lightbox[\"']"
    r"|\baria-hidden\s*=\s*[\"']true[\"']))[^>]*>"
    r"|<(template|noscript)\b[^>]*>",
    re.IGNORECASE)


def _hidden_spans(html: str) -> List[Tuple[int, int]]:
    """(start, end) of every element a visitor never sees as a second use
    of a photo, nesting-aware (same walk as _drop_spans)."""
    spans: List[Tuple[int, int]] = []
    for m in _HIDDEN_HOST_RE.finditer(html):
        tag = (m.group(1) or m.group(2)).lower()
        depth, pos = 1, m.end()
        tag_re = re.compile(rf"</?{tag}\b", re.IGNORECASE)
        while depth and pos < len(html):
            n = tag_re.search(html, pos)
            if not n:
                pos = len(html)
                break
            depth += -1 if html[n.start() + 1] == "/" else 1
            pos = n.end()
        spans.append((m.start(), pos))
    return spans


def _photo_name(url: str) -> str:
    tail = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1] or url
    return tail[:48]


def check_repeated_photos(html: str) -> List[str]:
    """Deterministic: a real photo used more than once on the visible page.
    Counts every <img src> and inline style url() outside a hidden host
    (lightbox, dialog, aria-hidden, template, noscript); a url in a
    <style> block counts once however many rules repeat it (a phone
    @media override is one picture, not two). data: URIs (the library
    grain) never count. One finding per repeated photo, capped at three,
    naming the sections it sits in so the repair knows where to look."""
    import html as _html_mod
    hidden = _hidden_spans(html)
    uses: Dict[str, List[int]] = {}

    def _add(raw: str, at: int) -> None:
        url = _html_mod.unescape((raw or "").strip())
        if not url or url.lower().startswith("data:"):
            return
        uses.setdefault(url, []).append(at)

    for m in _IMG_SRC_RE.finditer(html):
        if not _in_spans(m.start(), hidden):
            _add(m.group(2), m.start())
    for m in _STYLE_ATTR_RE.finditer(html):
        if _in_spans(m.start(), hidden):
            continue
        for u in _CSS_URL_RE.finditer(_html_mod.unescape(m.group(1))):
            _add(u.group(1), m.start())
    css_urls: Dict[str, int] = {}
    for b in _STYLE_BLOCK_RE.finditer(html):
        for u in _CSS_URL_RE.finditer(b.group(1)):
            css_urls.setdefault(u.group(1), b.start())
    for url, at in css_urls.items():
        _add(url, at)

    sections = section_spans(html)

    def _where(at: int) -> str:
        return next((f"#{sid}" for sid, a, z in sections if a <= at < z), "")

    problems: List[str] = []
    for url, ats in uses.items():
        if len(ats) < 2:
            continue
        places = []
        for at in ats:
            w = _where(at)
            if w and w not in places:
                places.append(w)
        where = f" (in {' and '.join(places)})" if places else ""
        problems.append(
            f"REPEATED PHOTO: the same photo ({_photo_name(url)}) appears "
            f"{len(ats)} times on the page{where}. Each photo appears once. "
            "Keep it in the place it serves best; where another place wants a "
            "photo the inventory cannot spare, use a hidden .sx-drop slot "
            "(rule 11b) or a typographic treatment instead of reusing it.")
        if len(problems) >= 3:
            break
    return problems


def check_connected(html: str, real_data: str) -> List[str]:
    """Deterministic contract check: every ON door's url appears in the
    document. A missing door costs a repair round, exactly like a
    missing image (the coverage law's sibling)."""
    problems: List[str] = []
    for name, url in _CONNECTED_LINE_RE.findall(real_data):
        if url not in html:
            problems.append(
                f"CONNECTED DOOR MISSING: {name} is ON but its url "
                f"({url}) appears nowhere on the page — add it as a "
                "real link in the nav and as a devoted moment.")
    if _STORE_OFF_LINE_RE.search(real_data):
        dead_links = len(_DEAD_STORE_HREF_RE.findall(html))
        dead_sections = len(_STORE_SECTION_RE.findall(html))
        if dead_links or dead_sections:
            problems.append(
                "DEAD DOOR: the shop is OFF (nothing in it yet) but the "
                f"page carries {dead_links} shop link(s) and "
                f"{dead_sections} shop section(s). Remove the shop "
                "section and every link to /store or /shop; do not "
                "replace them with a placeholder.")
    return problems


# ─── mechanical armor (deterministic, zero model calls) ─────────────

_ANNOT_TAG_RE = re.compile(
    r"<(h1|h2|h3|h4|p|li|blockquote|figcaption)(\s[^>]*)?>",
    re.IGNORECASE)


def annotate_editability(html: str) -> Tuple[str, int]:
    """THE ANNOTATOR (Amendment 1): guarantee data-override-target on
    every text-bearing element the model missed. Returns (html, added).

    AUDIT FIX (2026-07-24, flight one): the first version re-serialized
    the WHOLE document through bs4, which lowercases case-sensitive SVG
    attributes (viewBox, preserveAspectRatio) — silently breaking any
    inline-SVG signature move (the spec's DOTS line) before the judge
    ever saw it. Now a surgical regex injects the attribute into the
    matched opening tags ONLY — every other byte of the document is
    untouched."""
    try:
        existing = set(re.findall(r'data-override-target\s*=\s*["\']([^"\']+)',
                                  html))
        state = {"n": 0, "counter": 0}

        def _inject(m: re.Match) -> str:
            tag_open = m.group(0)
            if "data-override-target" in tag_open:
                return tag_open
            state["counter"] += 1
            target = f"v2/auto_{state['counter']}"
            while target in existing:
                state["counter"] += 1
                target = f"v2/auto_{state['counter']}"
            existing.add(target)
            state["n"] += 1
            return (tag_open[:-1]
                    + f' data-override-target="{target}">')

        out = _ANNOT_TAG_RE.sub(_inject, html)
        return out, state["n"]
    except Exception as e:
        logger.warning(f"[v2] annotator skipped: {e}")
        return html, 0


def armor_scripts(html: str,
                  allowed_fetch: str = "") -> Tuple[str, List[str]]:
    """Drop any <script> containing a banned call; report what fell.

    allowed_fetch: the ONE url a fetch( may target — the platform's own
    contact-submit endpoint (a JSON endpoint; the form is dead without
    it). Only the inline string-literal form is permitted, so the probe
    can verify the target without executing anything: fetch("<url>" or
    fetch('<url>'. Any other fetch — variable, template, other url —
    still drops the whole script."""
    dropped: List[str] = []

    def _check(m: re.Match) -> str:
        body = m.group(1) or ""
        probe = body
        if allowed_fetch:
            for quote in ('"', "'"):
                probe = probe.replace(
                    f"fetch({quote}{allowed_fetch}{quote}", "")
        for ban in _JS_BANNED:
            if ban in probe:
                dropped.append(ban)
                return ""
        return m.group(0)

    out = re.sub(r"<script[^>]*>(.*?)</script>", _check, html,
                 flags=re.DOTALL | re.IGNORECASE)
    return out, dropped


def armor_violations(dropped: List[str], endpoint: str) -> List[str]:
    """A dropped script is a LAW violation, not a silent event — the
    page's reveal states orphan into permanent invisibility when the
    runtime falls (the 2026-07-25 blank-page bug). The violation carries
    the reason so the surgical repair fixes the cause, not a symptom."""
    return [
        f'SCRIPT REMOVED BY THE SECURITY ARMOR: your <script> used "{ban}", '
        "which is banned, so the ENTIRE script was stripped — the page "
        "shipped with no JavaScript, and every hidden-for-reveal element "
        "stays invisible forever. Rewrite the single script without it. "
        "The ONLY permitted network call is the contact form submit: "
        f'fetch("{endpoint}", …) with the url written inline exactly as '
        "that string literal. Everything else must be DOM-only."
        for ban in dropped
    ]


def armor_external(html: str) -> Tuple[str, List[str]]:
    """Strip non-whitelisted external <link>/<iframe>/external <script
    src>. Google Fonts links survive; https images are untouched (img
    tags aren't requests we initiate logic through)."""
    stripped: List[str] = []

    def _link(m: re.Match) -> str:
        tag = m.group(0)
        href = (re.search(r'href\s*=\s*["\']([^"\']+)', tag) or [None, ""])[1]
        if any(h in href for h in _ALLOWED_LINK_HOSTS) or href.startswith("#") \
                or not href.startswith("http"):
            return tag
        stripped.append(href[:80])
        return ""

    out = re.sub(r"<link\b[^>]*>", _link, html, flags=re.IGNORECASE)

    def _script_src(m: re.Match) -> str:
        stripped.append("external script")
        return ""
    out = re.sub(r"<script\b[^>]*\bsrc\s*=[^>]*>\s*</script>", _script_src,
                 out, flags=re.IGNORECASE)

    def _iframe(m: re.Match) -> str:
        stripped.append("iframe")
        return ""
    out = re.sub(r"<iframe\b.*?</iframe>", _iframe, out,
                 flags=re.DOTALL | re.IGNORECASE)
    return out, stripped


# ─── authorship checks (truth + coverage) ────────────────────────────

def _visible_text(html: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html,
               flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"<[^>]+>", " ", t)


def check_truth(html: str, real_data: str) -> List[str]:
    """Every 3+ digit run in visible text must appear in the data (the
    fact-trace, page-wide) — with the current year exempt (a copyright
    line is a date, not a claim)."""
    from datetime import datetime, timezone
    data_runs = set(_DIGIT_RUN_RE.findall(real_data))
    year = str(datetime.now(timezone.utc).year)
    problems: List[str] = []
    for run in dict.fromkeys(_DIGIT_RUN_RE.findall(_visible_text(html))):
        if run == year:
            continue
        if run not in data_runs:
            problems.append(f"number '{run}' on the page but not in the "
                            f"REAL DATA — real or removed")
        if len(problems) >= 6:
            break
    return problems


_FACTS_FOUNDED_RE = re.compile(r"^- Founded: (\d{4}) \((\d+) years in business\)", re.MULTILINE)
_FACTS_NO_YEAR_RE = re.compile(r"^- Founded: NOT ON FILE", re.MULTILINE)
_FACTS_STATED_RE = re.compile(r"^- Years the owner stated[^:]*: (.+)$", re.MULTILINE)


def check_tenure(html: str, real_data: str) -> List[str]:
    """'N years' on the page is a claim the 3+-digit trace cannot see.
    It must match the years on file in THE FACTS; with no founding year
    on file it is invented. Silent when the data carries no facts block
    at all (older callers)."""
    m = _FACTS_FOUNDED_RE.search(real_data or "")
    if m:
        facts = {"years_in_business": int(m.group(2))}
    elif _FACTS_NO_YEAR_RE.search(real_data or ""):
        facts = {"years_in_business": None}
    else:
        return []
    # the owner's own stated tenure is on file too (site_facts.stated_years)
    sm = _FACTS_STATED_RE.search(real_data or "")
    if sm:
        facts["stated_years"] = [int(x) for x in re.findall(r"(\d{1,2}) years", sm.group(1))]
    import site_facts
    return site_facts.tenure_claims(_visible_text(html), facts)


def check_coverage(html: str, real_data: str, page: str = "home") -> List[str]:
    """page="offer" (2026-10-01): the offer page carries the offer, not the
    whole inventory, so every-image and the contact form are home-page
    laws; navigation and a footer are every page's."""
    problems: List[str] = []
    for m in re.finditer(r"^- (https://\S+)", real_data, re.MULTILINE):
        if page != "home":
            break
        url = m.group(1)
        if url not in html:
            problems.append(f"required image missing: {url}")
    if not re.search(r"<nav\b|role\s*=\s*[\"']navigation[\"']", html,
                     re.IGNORECASE):
        problems.append("no <nav> — a fixed navigation is required")
    endpoint = re.search(r"CONTACT FORM ENDPOINT[^\n]*:\s*(\S+)", real_data)
    if page == "home" and endpoint and endpoint.group(1) not in html:
        problems.append(f"contact form must post to {endpoint.group(1)}")
    if page == "home" and not re.search(r"<form\b", html, re.IGNORECASE):
        problems.append("no <form> — the working inquiry form is required")
    if not re.search(r"<footer\b", html, re.IGNORECASE):
        problems.append("no <footer>")
    return problems[:12]


_COPY_TAG_RE = re.compile(
    r"<(h1|h2|h3|h4|p|li|blockquote)(?:\s[^>]*)?>(.*?)</\1>",
    re.IGNORECASE | re.DOTALL)


def check_grammar(html: str) -> List[str]:
    """THE DASH LAW (Kevin's review, 2026-07-25): dash-spliced sentences
    are a defect, not a style. Em dashes (and spaced hyphen splices) in
    headings/paragraph/list copy are flagged with the exact sentence so
    the repair is surgical. figcaption is exempt — artwork/event titles
    carry dashes as titles, not sentences."""
    problems: List[str] = []
    for m in _COPY_TAG_RE.finditer(html):
        text = re.sub(r"<[^>]+>", " ", m.group(2))
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        if "—" in text or re.search(r"\w\s[-–]\s\w", text):
            problems.append(
                "DASH LAW: copy uses a dash splice — rewrite with a "
                f"period, comma, or colon: \"{text[:90]}\"")
        if len(problems) >= 5:
            break
    return problems


def check_head(html: str) -> List[str]:
    """HEAD + SHARE: a shared link must look intentional."""
    problems: List[str] = []
    title = re.search(r"<title[^>]*>([^<]*)</title>", html, re.IGNORECASE)
    if not title or not title.group(1).strip():
        problems.append("no <title> — a real page title is required")
    if not re.search(r'<meta\s[^>]*name=["\']description["\']', html,
                     re.IGNORECASE):
        problems.append("no meta description — write one from the data")
    if not re.search(r'<meta\s[^>]*property=["\']og:image["\']', html,
                     re.IGNORECASE):
        problems.append("no og:image — promote the strongest image url "
                        "so a shared link shows the work")
    return problems


def check_interactions(html: str) -> List[str]:
    """INTERACTION GRAMMAR, the deterministically checkable half:
    a page carrying a real gallery (5+ content images) must let each
    piece be seen closer (id=\"lightbox\" or a <dialog>); hidden-until-
    reveal content driven by IntersectionObserver alone is the reveal-
    skip bug class — a scroll fallback is required."""
    problems: List[str] = []
    imgs = len(re.findall(r"<img\b", html, re.IGNORECASE))
    if imgs >= 5 and not (
            re.search(r'id=["\']lightbox["\']', html, re.IGNORECASE)
            or re.search(r"<dialog\b", html, re.IGNORECASE)):
        problems.append(
            "gallery present but no way to see a piece closer — add a "
            'lightbox (id="lightbox": click a gallery image to open it '
            "large with its title; closes on backdrop click, a close "
            "button, and Escape)")
    if "IntersectionObserver" in html and "opacity:0" in html.replace(" ", "") \
            and not re.search(r"addEventListener\(\s*['\"]scroll", html):
        problems.append(
            "REVEAL SAFETY: hidden-for-reveal content is driven by an "
            "IntersectionObserver with no scroll fallback — fast "
            "scrolling can skip sections forever. Reveal on scroll "
            "position (anything whose top passed the reveal line becomes "
            "visible), or drop the hidden state.")
    has_runtime = bool(re.search(r"<script[^>]*>\s*\S", html,
                                 re.IGNORECASE | re.DOTALL))
    if not has_runtime and "opacity:0" in html.replace(" ", ""):
        problems.append(
            "REVEAL SAFETY: the stylesheet sets reveal states to "
            "opacity:0 but no script exists on the page to add the "
            "shown class, so those sections never appear. Include the "
            "runtime script, or author the page with every section "
            "visible by default.")
    return problems


def _parse_doc(raw: str) -> Optional[str]:
    if not raw:
        return None
    text = _FENCE_RE.sub("", raw).strip()
    i = text.lower().find("<!doctype")
    if i < 0:
        i = text.lower().find("<html")
    if i < 0:
        return None
    j = text.lower().rfind("</html>")
    if j < 0:
        return None
    doc = text[i:j + len("</html>")]
    return doc if len(doc.encode()) <= DOC_MAX_BYTES else None


# ─── THE EYES (Director's Cut Arc 2 — the vision loop) ──────────────
# The builder looks at its own rendered work BEFORE anyone else does:
# screenshots taken the way a visitor would see them (scrolled through,
# not teleported), measured against the spec and the standing checklist
# of non-negotiables, then ONE surgical repair. The loop is the last
# line of defense, never the teacher — everything teachable lives in
# the system prompt and the deterministic checks above.

VISION_WALK_WIDTHS = (390, 1440)     # full walk: top / middle / bottom
VISION_WIDE_WIDTH = 2560             # ultrawide: above the fold only
# THE SETTLE (2026-08-29, the proof build): the walk teleports to a scroll
# stop and shot after 700ms — inside the page's own staggered reveal
# (transition-delay stepped by item index, as rule 15 asks). The eyes
# then reported "an entire viewport is blank — reveal-skip bug" on a page
# whose tiles were simply still fading in, and a vision repair would
# have been paid for on a defect that did not exist. Wait for the
# cascade.
VISION_SETTLE_MS = 1600
# THE INSPECTOR'S CAP: Opus 5 answered the checklist in more than 1200
# tokens (it reasons inside its budget), came back cut mid-JSON, and the
# eyes silently reported "did not run". Room to finish a six-item verdict.
INSPECTOR_MAX_TOKENS = 4000


# THE MEASURED RENDER (2026-10-01, the concept-layer plan): site_check
# measured overflow, empty headings and collisions on the LIVE site, but
# the build never ran it, so a page that scrolled sideways on a phone
# shipped and was only reported afterwards. The eyes' walk already has
# the page open at 390 and 1440; it now runs the same audit there (free,
# no model call) and the findings ride the vision repair. Kept beside the
# walk rather than in its return value so every caller of
# _screenshot_walk (the tool loop, the tests) sees the same shape.
_MEASURES: Dict[str, Dict[str, Any]] = {}
_MEASURES_KEEP = 8
_TEXTISH_RE = re.compile(r"^(?:h[1-6]|p|li|blockquote|a|button|input|textarea|form)\b")


def _doc_key(html: str) -> str:
    import hashlib
    return hashlib.sha1((html or "").encode("utf-8", "ignore")).hexdigest()


def _record_measure(html: str, width: int, data: Any) -> None:
    if not isinstance(data, dict):
        return
    key = _doc_key(html)
    if key not in _MEASURES and len(_MEASURES) >= _MEASURES_KEEP:
        _MEASURES.pop(next(iter(_MEASURES)))
    _MEASURES.setdefault(key, {}).setdefault(str(width), {}).update(data)


def _measure_page(page: Any, html: str, width: int) -> None:
    """Geometry (site_check's audit) and the craft floor (craft_laws),
    measured on the open page once the hero has settled. Free; never
    fatal."""
    try:
        import site_check
        _record_measure(html, width, page.evaluate(site_check._AUDIT_JS))
    except Exception as e:
        logger.info(f"[v2:eyes] geometry skipped at {width}px: {e}")
    try:
        import craft_laws
        _record_measure(html, width, page.evaluate(craft_laws.RENDER_JS))
    except Exception as e:
        logger.info(f"[v2:eyes] craft measure skipped at {width}px: {e}")
    try:
        import site_layouts
        _record_measure(html, width, page.evaluate(site_layouts.RENDER_JS))
    except Exception as e:
        logger.info(f"[v2:eyes] layout measure skipped at {width}px: {e}")
    if width >= 1024:
        try:
            _record_measure(html, width, page.evaluate(VISITOR_JS))
        except Exception as e:
            logger.info(f"[v2:eyes] visitor walk skipped at {width}px: {e}")


def walk_measurements(html: str) -> Optional[Dict[str, Any]]:
    """What the last walk of this exact document measured, by width, or
    None when it was not walked (no playwright, eyes off). Read once."""
    return _MEASURES.pop(_doc_key(html), None)


def render_findings(measures: Optional[Dict[str, Any]]) -> List[str]:
    """Measured defects worth a repair round, in the builder's words.
    Only what is certainly wrong: content wider than the screen, a
    heading with no words, and text colliding with text. An image under
    a caption or a photo behind a headline is usually layering on
    purpose, so those overlaps are left to the eyes and to
    data-overlap-ok."""
    out: List[str] = []
    for width, m in sorted((measures or {}).items(), key=lambda kv: int(kv[0])):
        if not isinstance(m, dict):
            continue
        if m.get("overflow_x"):
            out.append(f"at {width}px the page is {m.get('scroll_width')}px wide: "
                       "something is wider than the screen, so the page scrolls "
                       "sideways. Find the element and constrain it.")
        if m.get("empty_headings"):
            out.append(f"at {width}px {m['empty_headings']} heading(s) render "
                       "with no text. Give each words or remove it.")
        hits = []
        for o in (m.get("overlaps") or []):
            a, b = str(o.get("a") or ""), str(o.get("b") or "")
            if _TEXTISH_RE.match(a) and _TEXTISH_RE.match(b):
                hits.append(f"{a} over {b}")
        if hits:
            out.append(f"at {width}px text collides with text: "
                       + "; ".join(hits[:3])
                       + ". Separate them, or mark deliberate layering with "
                         "data-overlap-ok.")
    return out[:6]


def eyes_enabled() -> bool:
    return (os.environ.get("SITE_V2_VISION_LOOP") or "on").strip().lower() \
        in ("on", "1", "true", "yes")


def _screenshot_walk(html: str) -> Optional[List[Tuple[str, bytes]]]:
    """Render and WALK the page like a visitor: for each width, scroll
    top → middle → bottom (firing the page's own scroll handlers, so a
    reveal-skip bug shows up as a blank section) and shoot each stop.
    Plus one ultrawide above-the-fold shot. Returns [(label, jpeg)] or
    None when playwright is unavailable."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        logger.info("[v2:eyes] playwright not installed — vision loop "
                    "skipped")
        return None
    shots: List[Tuple[str, bytes]] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for width in VISION_WALK_WIDTHS:
                    page = browser.new_page(
                        viewport={"width": width, "height": 900})
                    page.set_content(html, wait_until="networkidle",
                                     timeout=25000)
                    total = page.evaluate(
                        "document.documentElement.scrollHeight")
                    stops = [0, max(0, total // 2 - 450),
                             max(0, total - 900)]
                    names = ("top", "middle", "bottom")
                    for name, y in zip(names, stops):
                        page.evaluate(f"window.scrollTo(0, {y})")
                        page.wait_for_timeout(VISION_SETTLE_MS)   # the cascade settles
                        shots.append((f"{width}px {name}",
                                      page.screenshot(type="jpeg",
                                                      quality=55)))
                        if name == "top":
                            _measure_page(page, html, width)
                    page.close()
                page = browser.new_page(
                    viewport={"width": VISION_WIDE_WIDTH, "height": 1000})
                page.set_content(html, wait_until="networkidle",
                                 timeout=25000)
                page.wait_for_timeout(500)
                shots.append((f"{VISION_WIDE_WIDTH}px top (ultrawide)",
                              page.screenshot(type="jpeg", quality=55)))
                page.close()
            finally:
                browser.close()
    except Exception as e:
        logger.warning(f"[v2:eyes] screenshot walk failed: "
                       f"{type(e).__name__}: {e}")
        return None
    return shots


_INSPECTOR = """You are the builder of this page inspecting your own rendered work before it ships. You are looking for DEFECTS a paying owner would see, not restating taste. Screenshots show the page as a visitor scrolls it, at phone and desktop widths plus one ultrawide look.

THE BLUEPRINT IS SETTLED. It was agreed with the owner: its concept, its section plan (what each section holds, and where its objects, marks and ghost words go), what it decided and declined, and its rules. Judge how faithfully and how well the page carries it out. Never propose a fix that undoes one of its decisions (a price or length it chose not to show, an object it placed in one section moved or copied into another, a ghost word on the other edge). Where the page departs from the blueprint, the fix is to bring it back. When you believe a decision itself costs the visitor, do not fix it: ask the owner one short question in "ask_owner".

FIRST, WALK IT AS THE VISITOR. From the spec, decide who this page is for. Read the views top to bottom as that person and answer three questions: what did they come for; did they get it, and where on the page; what do they do next, and does that path work. Where they would get stuck or turn away is a violation in that section, and it outranks anything cosmetic.

THEN NAME THE BIGGEST PROBLEM: the one thing that most hurts this page for that visitor, the one a designer would fix before anything else. Judge it by what it costs the visitor, not by how easy it is to name. It is also one of the violations.

Measure against THE CHECKLIST (each item is a law, not a suggestion):
- ALIGNMENT: photographic subjects fill their frames; nothing floats small inside an oversized border; edges line up with neighboring type; nothing overlaps, collides, or gets cut off.
- COMPLETENESS: no blank/empty sections at any scroll stop (a section that never appeared = the reveal-skip bug). No grid holes, no dead space where content should be.
- STAND-INS: no box, frame, tinted or textured panel standing in for a photograph, and no caption describing an image that is not there. A missing photo is invisible to the visitor — a hero without a photo is typographic, a gallery without photos is not a grid.
- FILLED SPACE: the hero's off-axis half holds a designed presence, not bare ground beside the headline; no scroll stop shows a featureless band taller than half the viewport between sections.
- CAPTION TRUTH: every caption/title visibly matches the artwork it sits under.
- COPY GRAMMAR: no dash-spliced sentences visible in headings or body copy.
- LEGIBILITY: text readable against its ground at every width; small type not lost.
- MOBILE (390px): nothing crowded, cropped, or broken; rhythm holds.
- ULTRAWIDE: the page keeps an intentional measure; nothing stretches thin or drifts.
- SPEC FIDELITY: the named signature move is visible and executed; the spec's palette and type are what actually rendered; each section holds what the section plan gives it, with its objects, marks and ghost words where the plan puts them.
- THE IDEA: the hero says what this business is; a stranger knows in five seconds.
- ONE SIGNATURE MOMENT: it is visible, and the sections around it are quiet enough to let it lead.
- RHYTHM: no two neighboring sections share the same shape (the same heading-number-paragraph opening, the same three cards). A page where every section opens the same way has defaulted.
- PHONE COMPOSITION: at 390px the headline survives, objects simplify, nothing collides or shrinks to unreadable.
- CONCEPT CLARITY: when the page wears a concept, it never hides what a thing is or what it costs, and in-world labels keep their plain words.
- THE LAYOUT: when THE LAYOUT is given, the page reads as that architecture (its columns, its opening, how its sections stack); a page that fell back to a generic stack of bands has missed it.

Each violation names its "section": the id from SECTIONS ON THE PAGE, or "page" when it spans the page. Then name the WEAKEST section, the one a designer would rebuild first, with a score from 1 to 10 against everything above.

Output STRICT JSON only:
{"verdict":"ship"|"repair","visitor":{"who":"<who the page is for>","came_for":"<what they came for>","got_it":"<yes, partly or no, and where>","next":"<their next step, and whether it works>","stuck":"<section id where they get stuck, or null>"},"biggest":{"section":"<id or page>","what":"<the problem>","why":"<what it costs the visitor>","fix":"<the fix>"},"ask_owner":"<one short question for the owner about a decision, or null>","violations":[{"where":"<section/breakpoint>","section":"<id or page>","what":"<the defect, concrete>","fix":"<the minimal surgical fix>"}],"weakest":{"section":"<id>","score":<1-10>,"why":"<one sentence>","fix":"<what the rebuilt section does instead>"}}
Rules: at most 6 violations, ranked by what they cost the visitor. Cosmetic taste differences are NOT violations. An empty violations list means verdict "ship", and then "biggest" is null. JSON only, no commentary."""


def _parse_inspector(raw: str) -> Optional[Dict[str, Any]]:
    """Parse the inspector's strict-JSON verdict; tolerant of fences."""
    if not raw:
        return None
    text = _FENCE_RE.sub("", raw).strip()
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        out = json.loads(text[i:j + 1])
    except Exception:
        return None
    if not isinstance(out, dict) or out.get("verdict") not in ("ship",
                                                               "repair"):
        return None
    vs = out.get("violations")
    out["violations"] = [v for v in (vs if isinstance(vs, list) else [])
                         if isinstance(v, dict) and v.get("what")][:6]
    if not out["violations"]:
        out["verdict"] = "ship"
    w = out.get("weakest")
    if isinstance(w, dict) and str(w.get("section") or "").strip():
        try:
            score = int(w.get("score"))
        except (TypeError, ValueError):
            score = None
        out["weakest"] = {"section": str(w["section"]).strip().lstrip("#"),
                          "score": score, "why": str(w.get("why") or "")[:240],
                          "fix": str(w.get("fix") or "")[:240]}
    else:
        out["weakest"] = None
    vis = out.get("visitor")
    if isinstance(vis, dict):
        stuck = str(vis.get("stuck") or "").strip().lstrip("#")
        out["visitor"] = {k: str(vis.get(k) or "")[:240]
                          for k in ("who", "came_for", "got_it", "next")}
        out["visitor"]["stuck"] = (stuck if stuck and stuck.lower() not in ("null", "none")
                                   else None)
    else:
        out["visitor"] = None
    big = out.get("biggest")
    if isinstance(big, dict) and str(big.get("what") or "").strip() \
            and out["verdict"] == "repair":
        out["biggest"] = {"section": str(big.get("section") or "page").strip().lstrip("#") or "page",
                          "what": str(big.get("what") or "")[:240],
                          "why": str(big.get("why") or "")[:240],
                          "fix": str(big.get("fix") or "")[:240]}
    else:
        out["biggest"] = None
    ask = str(out.get("ask_owner") or "").strip()
    out["ask_owner"] = ask[:200] if ask and ask.lower() not in ("null", "none") else None
    return out


def inspect_with_eyes(doc: str, spec_text: str, business_id: str,
                      why: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """Screenshot walk → one vision call → verdict dict, or None when
    the eyes can't run (no playwright / no key / unparseable) — never
    fatal, never a second look. `why` (2026-08-29) receives the reason
    for a None, so the report never says "did not run" without saying
    what closed them."""
    def _why(reason: str) -> None:
        if why is not None:
            why["reason"] = reason
    shots = _screenshot_walk(doc)
    if not shots:
        _why("no screenshots (playwright unavailable or the render failed)")
        return None
    try:
        import base64
        from anthropic import Anthropic
        import model_ladder
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            _why("no ANTHROPIC_API_KEY")
            return None
        content: List[Dict[str, Any]] = [
            {"type": "text", "text": eyes_blueprint_block(spec_text)}]
        outline = section_outline(doc)
        if outline:
            content.append({"type": "text", "text": "SECTIONS ON THE PAGE (id: "
                            "heading), top to bottom:\n" + outline})
        try:
            import site_layouts
            _lk = layout_key_for(spec_text)
            if _lk:
                _L = site_layouts.LAYOUTS[_lk]
                content.append({"type": "text", "text": f"THE LAYOUT: {_L['name']}. "
                                f"{_L['structure']} PHONE: {_L['phone']}"})
        except Exception:
            pass
        for label, shot in shots:
            content.append({"type": "text", "text": f"View — {label}:"})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(shot).decode()}})
        content.append({"type": "text",
                        "text": "Inspect per the checklist. JSON only."})
        client = llm_call.sdk_client(key=key, timeout=180.0, max_retries=1)

        def _do(model: str, max_tokens: int, timeout: float):
            return client.messages.create(
                model=model, max_tokens=max_tokens, system=_INSPECTOR,
                messages=[{"role": "user", "content": content}],
                timeout=max(timeout, 180.0),
                **_gen_kwargs(model, 0.2))

        msg, used_model = model_ladder.call_with_ladder(
            _do, model=_model(), task="builder_v2_eyes",
            business_id=business_id, max_tokens=INSPECTOR_MAX_TOKENS)
        try:
            from api_usage_logger import log_api_usage_sync
            u = getattr(msg, "usage", None)
            log_api_usage_sync(
                endpoint="/composer/builder-v2-eyes",
                model=used_model or "",
                input_tokens=getattr(u, "input_tokens", 0) or 0,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                business_id=business_id, task_type="builder_v2_eyes")
        except Exception:
            pass
        raw = "".join(b.text for b in msg.content
                      if getattr(b, "type", None) == "text")
        verdict = _parse_inspector(raw)
        if verdict is None:
            stop = getattr(msg, "stop_reason", None)
            _why(f"unparseable verdict (stop_reason={stop}, {len(raw)} chars)"
                 + (" — the reply hit the inspector's cap" if stop == "max_tokens" else ""))
            logger.warning(f"[v2:eyes] verdict unparseable for {business_id[:8]}: "
                           f"stop={stop} head={raw[:80]!r}")
        return verdict
    except Exception as e:
        _why(f"{type(e).__name__}: {e}")
        logger.warning(f"[v2:eyes] inspection failed (non-fatal): "
                       f"{type(e).__name__}: {e}")
        return None


# ─── the run ─────────────────────────────────────────────────────────

def _stream_message(client, *, model: str, max_tokens: int, system: str,
                    messages: List[Dict[str, Any]], timeout: float,
                    sampling: Dict[str, Any]):
    """One STREAMING generation, returned as the final Message (same
    shape the non-streaming call returned, so the ladder, the usage log
    and the text join are untouched). Streaming is what lets a five-
    minute page finish: a non-streaming request is a single HTTP
    response the connection must hold open for the whole generation."""
    with client.messages.stream(model=model, max_tokens=max_tokens,
                                system=system, messages=messages,
                                timeout=timeout, **sampling) as s:
        for _ in s.text_stream:
            pass
        return s.get_final_message()


def _call(system: str, user: str, business_id: str,
          spend: Optional[Dict[str, Any]] = None,
          units: Optional[int] = None,
          task_type: str = "builder_v2") -> Optional[str]:
    """One authoring call. `units` is the credit price written onto the
    first usage row (None lets usage_metering price it from the endpoint,
    which is 0: build-internal calls ride the build's own marker). A
    standalone, billable call (refine_section_doc) passes its price."""
    try:
        from anthropic import Anthropic
        import model_ladder
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return None
        # Flight one lesson: the full-page pass is ONE giant generation;
        # a tight timeout forced the ladder's reduced-tokens retry and
        # shipped a SQUEEZED page ("headline feels compressed"). Give
        # the first attempt real room — a slow masterpiece beats a fast
        # miniature.
        client = llm_call.sdk_client(key=key, timeout=900.0, max_retries=1)
        turns: List[Dict[str, Any]] = [{"role": "user", "content": user}]

        def _do(model: str, max_tokens: int, timeout: float):
            return _stream_message(
                client, model=model, max_tokens=max_tokens, system=system,
                messages=turns, timeout=max(timeout, 900.0),
                sampling=_gen_kwargs(model, V2_TEMPERATURE))

        msg, used_model = model_ladder.call_with_ladder(
            _do, model=_model(), task="builder_v2",
            business_id=business_id, max_tokens=_max_tokens())
        _record_spend(spend, used_model or "", getattr(msg, "usage", None))
        try:
            from api_usage_logger import log_api_usage_sync
            u = getattr(msg, "usage", None)
            log_api_usage_sync(
                endpoint="/composer/builder-v2", model=used_model or "",
                input_tokens=getattr(u, "input_tokens", 0) or 0,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                business_id=business_id, task_type=task_type, units=units)
        except Exception:
            pass
        text = "".join(b.text for b in msg.content
                       if getattr(b, "type", None) == "text")
        # THE CUT SENTENCE: a response that hit the cap is CONTINUED from
        # its last character — one more turn, same model — never re-rolled
        # into the same wall. (An assistant turn followed by a user turn
        # is an ordinary conversation, accepted by every model family;
        # assistant-prefill is not.)
        if getattr(msg, "stop_reason", None) == "max_tokens" and text.strip() \
                and _budget_left(spend):
            logger.warning(f"[v2] {used_model} hit max_tokens — continuing "
                           f"the document, not re-rolling it")
            turns = [{"role": "user", "content": user},
                     {"role": "assistant", "content": text},
                     {"role": "user", "content": CONTINUE_PROMPT}]
            try:
                more = _stream_message(
                    client, model=used_model or _model(), max_tokens=_max_tokens(),
                    system=system, messages=turns, timeout=900.0,
                    sampling=_gen_kwargs(used_model or _model(),
                                                          V2_TEMPERATURE))
                _record_spend(spend, used_model or "", getattr(more, "usage", None))
                try:
                    from api_usage_logger import log_api_usage_sync
                    u2 = getattr(more, "usage", None)
                    log_api_usage_sync(
                        endpoint="/composer/builder-v2", model=used_model or "",
                        input_tokens=getattr(u2, "input_tokens", 0) or 0,
                        output_tokens=getattr(u2, "output_tokens", 0) or 0,
                        business_id=business_id, task_type="builder_v2_continue")
                except Exception:
                    pass
                text += "".join(b.text for b in more.content
                                if getattr(b, "type", None) == "text")
            except Exception as e:
                logger.warning(f"[v2] continuation failed ({type(e).__name__}: {e}) "
                               "— keeping the cut document")
        return text
    except Exception as e:
        logger.error(f"[v2] build call failed on every rung: "
                     f"{type(e).__name__}: {e}")
        return None


# ─── THE DESIGNER'S REVIEW (2026-10-01, the concept-layer plan) ──────
# The vision repair used to resend the whole document for any defect the
# eyes saw, paying for a full page to fix one band and risking the
# sections that were already right. When every defect lives in named
# sections, only those sections are rebuilt, and the rest of the page
# stays byte for byte. A page-wide defect still gets the whole-page pass.

WEAKEST_REBUILD_BELOW = 7        # the weakest section is rebuilt when it scores under this
MAX_SECTION_REPAIRS = 2          # sections rebuilt per look (LOOK_FIX_SECTIONS overrides)

# THE LOOK-AND-FIX LOOP (2026-10-03, the hand-build plan, phase 3). By
# hand, a page is looked at, its weakest parts fixed, and looked at again
# until it is right; the builder used to look once, fix at most two
# sections, and stop. Now it looks up to LOOK_FIX_ROUNDS times, fixes the
# weakest sections each round, and stops when a look finds nothing to
# fix, when a round changes nothing, or when the rounds after the first
# have spent LOOK_FIX_MAX_CENTS (so no build runs away). The whole-page
# vision repair stays a once-per-build tool.


def _dial_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.environ.get(name) or default)))
    except (TypeError, ValueError):
        return default


def look_fix_rounds() -> int:
    return _dial_int("LOOK_FIX_ROUNDS", 3, 1, 6)


def look_fix_sections() -> int:
    return _dial_int("LOOK_FIX_SECTIONS", 3, 1, 6)


def look_fix_max_cents() -> int:
    return _dial_int("LOOK_FIX_MAX_CENTS", 150, 0, 2000)

_SECTION_SYSTEM = ("THIS CALL REPAIRS ONE SECTION OF A FINISHED PAGE. Where the "
                   "rules below say document or page, read section: you output ONE "
                   "<section> element and nothing else.\n\n" + "{SYSTEM}")


def _section_id(open_tag: str) -> str:
    m = re.search(r'\bid\s*=\s*["\']([^"\']+)', open_tag)
    return m.group(1) if m else ""


def section_spans(doc: str) -> List[Tuple[str, int, int]]:
    """(id, start, end) for every top-level <section> with an id."""
    try:
        import site_pages
        out = []
        for a, z in site_pages.top_sections(doc or ""):
            open_tag = re.match(r"<section\b[^>]*>", doc[a:z], re.IGNORECASE).group(0)
            sid = _section_id(open_tag)
            if sid:
                out.append((sid, a, z))
        return out
    except Exception:
        return []


def section_outline(doc: str) -> str:
    lines = []
    for sid, a, z in section_spans(doc):
        h = re.search(r"<h[1-3]\b[^>]*>(.*?)</h[1-3]>", doc[a:z], re.IGNORECASE | re.DOTALL)
        heading = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h.group(1))).strip() if h else ""
        lines.append(f"- {sid}: {heading[:70] or '(no heading)'}")
    return "\n".join(lines[:24])


def build_section_prompt(spec_text: str, real_data: str, doc: str, sid: str,
                         issues: List[str]) -> str:
    span = next(((a, z) for i, a, z in section_spans(doc) if i == sid), None)
    current = doc[span[0]:span[1]] if span else ""
    return "\n".join([
        f"SECTION REPAIR: rebuild ONE section of your page, the <section id=\"{sid}\">. "
        "Every other byte of the page is final and stays exactly as it is.",
        "",
        "WHAT TO FIX IN THIS SECTION:",
        *[f"- {x}" for x in issues[:6]],
        "",
        BLUEPRINT_SETTLED,
        "",
        f"Return ONLY the complete replacement element: it starts with <section, keeps "
        f"id=\"{sid}\", uses the page's existing classes, tokens and fonts, keeps every "
        "data-override-target it already has, and ends with </section>. New styles go in a "
        "<style> element inside the section. No commentary, no code fences.",
        "",
        "THE APPROVED BLUEPRINT (settled; this section's plan is in it):",
        _blueprint(spec_text),
        "",
        "THE REAL DATA (the only source of facts):",
        (real_data or "").strip()[:10000],
        "",
        "THE WHOLE PAGE (context; do not return it):",
        doc,
        "",
        "THE SECTION TO REBUILD:",
        current,
    ])


def splice_section(doc: str, sid: str, raw: str) -> Optional[str]:
    """The page with section `sid` replaced by the model's element, or None
    when the reply is not one balanced <section id=sid>."""
    text = _FENCE_RE.sub("", raw or "").strip()
    i = text.lower().find("<section")
    j = text.lower().rfind("</section>")
    if i < 0 or j < i:
        return None
    new = text[i:j + len("</section>")]
    try:
        import site_pages
        tops = site_pages.top_sections(new)
    except Exception:
        return None
    if len(tops) != 1 or tops[0] != (0, len(new)):
        return None
    if _section_id(re.match(r"<section\b[^>]*>", new, re.IGNORECASE).group(0)) != sid:
        return None
    span = next(((a, z) for i2, a, z in section_spans(doc) if i2 == sid), None)
    if not span:
        return None
    return doc[:span[0]] + new + doc[span[1]:]


# ─── EVERY SECTION IS WRITTEN (2026-10-03, the second live test) ──────
# The Director's blueprint carried a line from the older canvas pipeline's
# section plan: "Position the immutable token exactly here:
# <!--SX_BLOCK:process-->". That pipeline splices a pre-built block into
# the token; this builder writes the whole page and splices nothing, so it
# copied the token and "How it works" shipped as 372px of blank paper,
# with the nav link and the hero's "Read how it works" landing on it. By
# hand, that section is simply written. The builder's copy of the
# blueprint now says so, and an empty section is a finding that earns a
# section rebuild.

_BLOCK_TOKEN = re.compile(r"<!--\s*SX_BLOCK:([\w-]+)(?::\d+)?\s*-->")
_TOKEN_INSTRUCTION = re.compile(
    r"(?:Position|Place|Put|Keep)\s+the\s+immutable\s+(?:token|block)[^\n<]*?"
    r"<!--\s*SX_BLOCK:[\w:-]+\s*-->", re.IGNORECASE)
_NO_RESTATING = re.compile(r"^[ \t]*-?[ \t]*No rewriting, wrapping or restating of the[^\n]*\n?",
                           re.IGNORECASE | re.MULTILINE)
WRITES_EVERY_SECTION = (
    "THIS BUILDER WRITES EVERY SECTION: the blueprint's section plan may speak "
    "of immutable blocks or placeholder tokens from an older pipeline that "
    "spliced pre-built blocks in. Nothing is spliced here. Write every section "
    "in the plan yourself, complete, from THE REAL DATA, and never leave a "
    "placeholder or an HTML comment where content belongs.")
EMPTY_SECTION_FIX = (
    "THIS SECTION IS EMPTY: a placeholder sat where its content belongs and "
    "the links to it land on blank space. Write it complete from THE REAL DATA "
    "and its brief in the blueprint, in the page's own look.")


def spec_for_builder(spec_text: str) -> str:
    """The blueprint as this builder must read it: no block tokens, no
    "do not restate the blocks" line, and the note that it writes every
    section. A blueprint without tokens passes through unchanged."""
    t = spec_text or ""
    if "SX_BLOCK" not in t:
        return t
    t = _TOKEN_INSTRUCTION.sub("Write this section yourself, complete, from THE REAL DATA.", t)
    t = _BLOCK_TOKEN.sub(lambda m: f"(the {m.group(1)} section, which you write)", t)
    t = _NO_RESTATING.sub("", t)
    return t.rstrip() + "\n\n" + WRITES_EVERY_SECTION


def empty_sections(html: str) -> List[str]:
    """Top-level sections a visitor sees as blank: a block token left in
    them, or no words and no picture, form or drawing at all."""
    out: List[str] = []
    for sid, a, z in section_spans(html or ""):
        part = html[a:z]
        if "SX_BLOCK" in part:
            out.append(sid)
            continue
        if re.search(r"<(img|svg|video|picture|iframe|form|canvas)\b", part, re.IGNORECASE):
            continue
        text = re.sub(r"<(script|style)\b.*?</\1>|<!--.*?-->", " ", part,
                      flags=re.IGNORECASE | re.DOTALL)
        if len(re.sub(r"<[^>]+>", " ", text).split()) < 3:
            out.append(sid)
    return out


def check_unfilled(html: str) -> List[str]:
    return [f"section #{sid} is empty (a placeholder sat where its content "
            "belongs): write it complete from THE REAL DATA, or every link to it "
            "lands on blank space" for sid in empty_sections(html)]


# ─── THE JUDGMENT PLAN (2026-10-03, after the second live test) ──────
# The system had the hand-build process and not yet the judgment: its
# eyes passed an empty "How it works" three times (the menu link and
# the hero's "Read how it works" landed on blank paper), the loop rebuilt
# the hero twice the same way, and five small notes were weighed alike.
# Three questions a designer asks while looking now ride every look:
#   J1 THE VISITOR WALK: click everything (free, below) and read the page
#      as the customer it is for (the inspector's "visitor" answer).
#   J2 BIGGEST PROBLEM FIRST: the one thing that most hurts the page for
#      that visitor is fixed first, and a round never drops it.
#   J3 CHANGE THE APPROACH ON A SECOND TRY: a section flagged again after
#      a rebuild is rethought, not polished; flagged a third time, the
#      builder stops spending on it and leaves it for the owner's walk.

# Every link and form on the page, followed the way a visitor would: does
# it go somewhere, and does it land on something with words? Runs in the
# eyes' open page at desktop width; free, no model call. Buttons are left
# alone (a script may own them, which a static read cannot see), and so
# are links to other pages, sites, mail and phone.
VISITOR_JS = r"""() => {
  const words = (el) => ((el && el.innerText) || '').trim().split(/\s+/).filter(Boolean).length;
  const media = (el) => !!(el && el.querySelector('img,svg,video,picture,iframe,canvas,form'));
  const where = (el) => {
    let s = el.closest('section[id]');
    while (s && s.parentElement && s.parentElement.closest('section[id]')) s = s.parentElement.closest('section[id]');
    if (s) return s.id;
    if (el.closest('footer')) return 'footer';
    if (el.closest('header,nav')) return 'nav';
    return '';
  };
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    const label = ((a.innerText || a.getAttribute('aria-label') || '').trim()).slice(0, 60);
    const href = (a.getAttribute('href') || '').trim();
    if (!label || seen.has(label + '|' + href)) continue;
    seen.add(label + '|' + href);
    const from = where(a);
    if (!href || href === '#' || /^javascript:/i.test(href)) {
      out.push({label, from, to: href, problem: 'nowhere'});
      continue;
    }
    if (href.charAt(0) !== '#') continue;
    const id = decodeURIComponent(href.slice(1));
    const t = document.getElementById(id);
    if (!t) { out.push({label, from, to: id, problem: 'missing'}); continue; }
    const sec = t.closest('section') || t;
    if (words(t) < 3 && !media(t) && words(sec) < 3 && !media(sec)) {
      out.push({label, from, to: sec.id || id, problem: 'blank'});
    }
  }
  for (const f of document.querySelectorAll('form')) {
    if (!f.querySelector('button, input[type=submit], input[type=image]')) {
      out.push({label: 'a form', from: where(f), to: '', problem: 'unsendable'});
    }
  }
  return {visitor_walk: out.slice(0, 12)};
}"""


def visitor_walk_findings(measures: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    """What the click-through found, as repair items: {section, what, fix}.
    A link that lands on a blank section is fixed IN that section (write
    it so the link delivers); a link that goes nowhere or points at
    nothing is fixed where the link lives."""
    out: List[Dict[str, str]] = []
    seen = set()
    for _w, m in sorted((measures or {}).items(), key=lambda kv: int(kv[0])):
        for w in ((m or {}).get("visitor_walk") or []) if isinstance(m, dict) else []:
            if not isinstance(w, dict):
                continue
            label = str(w.get("label") or "a link")[:60]
            src = str(w.get("from") or "")
            to = str(w.get("to") or "")
            where = f"#{src}" if src and src not in ("nav", "footer") else (src or "the page")
            kind = w.get("problem")
            if kind == "blank":
                item = {"section": to, "what": f'"{label}" (in {where}) lands on #{to}, which is blank',
                        "fix": "write that section so the link delivers what it promises"}
            elif kind == "missing":
                item = {"section": src, "what": f'"{label}" (in {where}) points at #{to}, which is not on the page',
                        "fix": "point it at the section that answers it, or remove the link"}
            elif kind == "nowhere":
                item = {"section": src, "what": f'"{label}" (in {where}) goes nowhere',
                        "fix": "give it a real destination on the page, or remove it"}
            elif kind == "unsendable":
                item = {"section": src, "what": f"a form in {where} has no button to send it",
                        "fix": "give the form a send button"}
            else:
                continue
            key = (item["section"], item["what"])
            if key not in seen:
                seen.add(key)
                out.append(item)
    return out[:8]


def second_try_line(before: List[str]) -> str:
    """J3: what a second rebuild of the same section is told."""
    was = "; ".join(str(b) for b in before)[:420]
    return ("SECOND TRY: this section was already rebuilt once, for: " + was + ". "
            "The eyes still flag it, so polishing the same composition did not "
            "work. Rethink it: a different arrangement, a different place for the "
            "eye to land first, a different scale or order of its parts. Keep "
            "every fact, the page's look and the section's job.")


def plan_vision_repair(verdict: Optional[Dict[str, Any]], doc: str,
                       page_items: List[str],
                       walk: Optional[List[Dict[str, str]]] = None,
                       empty: Optional[List[str]] = None) -> Tuple[List[str], Dict[str, List[str]]]:
    """(page-wide items, {section id: items}), in the order a designer
    fixes them (J2): the biggest problem first, then whatever stops the
    visitor (where they get stuck, a link that lands on nothing, an empty
    section), then the rest. A round that can afford only some sections
    takes them in this order, so it never drops the biggest. Anything the
    eyes could not place in a section on this page is page-wide."""
    ids = {sid for sid, _, _ in section_spans(doc)}
    page = list(page_items)
    v = verdict or {}
    repair = v.get("verdict") == "repair"
    first: Dict[str, List[str]] = {}
    blockers: Dict[str, List[str]] = {}
    rest: Dict[str, List[str]] = {}
    big = v.get("biggest") if repair and isinstance(v.get("biggest"), dict) else None
    if big:
        item = (f"THE BIGGEST PROBLEM ON THE PAGE (fix this first): {big.get('what')} "
                f"— WHAT IT COSTS THE VISITOR: {big.get('why')} — FIX: {big.get('fix')}")
        if big.get("section") in ids:
            first.setdefault(big["section"], []).append(item)
        else:
            page.insert(0, item)
    vis = v.get("visitor") if repair and isinstance(v.get("visitor"), dict) else None
    if vis and vis.get("stuck") in ids:
        blockers.setdefault(vis["stuck"], []).append(
            f"THE VISITOR GETS STUCK HERE: {vis.get('who') or 'the visitor'} came for "
            f"{vis.get('came_for') or 'what the page offers'}; got it: {vis.get('got_it')}; "
            f"next step: {vis.get('next')}. Make this section get them there.")
    for sid in empty or []:
        if sid in ids:
            blockers.setdefault(sid, []).insert(0, EMPTY_SECTION_FIX)
    for w in walk or []:
        item = f"THE VISITOR WALK: {w.get('what')} — FIX: {w.get('fix')}"
        if w.get("section") in ids:
            blockers.setdefault(w["section"], []).append(item)
        else:
            page.append(item)
    if repair:
        for x in v.get("violations") or []:
            item = (f"SEEN IN THE RENDER ({x.get('where', 'page')}): {x.get('what')} "
                    f"— FIX: {x.get('fix', 'minimal edit')}")
            sid = str(x.get("section") or "").strip().lstrip("#")
            if sid in ids:
                rest.setdefault(sid, []).append(item)
            else:
                page.append(item)
    w = v.get("weakest")
    if isinstance(w, dict) and w.get("section") in ids and isinstance(w.get("score"), int) \
            and w["score"] < WEAKEST_REBUILD_BELOW:
        rest.setdefault(w["section"], []).append(
            f"THE WEAKEST SECTION (scored {w['score']}/10): {w.get('why')} "
            f"— REBUILD IT SO: {w.get('fix')}")
    by_section: Dict[str, List[str]] = {}
    for group in (first, blockers, rest):
        for sid, items in group.items():
            by_section.setdefault(sid, []).extend(items)
    return page, by_section


# ─── REWORK ONE SECTION ON THE OWNER'S WORD (2026-10-03) ─────────────
# site_composer.refine_section (the Chief job and the Studio's "rework
# this section") only knew module-composed pages, so on a page from this
# builder an owner could not ask for one section to change, and photos
# added after the build had no way onto the page short of a full rebuild.
# Same machinery as the designer's review: one section rebuilt, the rest
# of the page byte for byte, every law held.

_SECTION_SYNONYMS = {
    "hero": ("top", "hero", "intro", "home"),
    "work": ("work", "gallery", "portfolio", "photos", "projects"),
    "gallery": ("gallery", "work", "portfolio", "photos"),
    "photos": ("gallery", "work", "portfolio", "photos"),
    "about": ("about", "story", "team", "us"),
    "prices": ("prices", "services", "menu", "offerings", "pricing"),
    "services": ("services", "prices", "offerings", "menu"),
    "offerings": ("offerings", "services", "prices", "menu"),
    "reviews": ("reviews", "testimonials", "quotes", "praise"),
    "testimonials": ("testimonials", "reviews", "quotes"),
    "contact": ("contact", "visit", "find", "location", "hours"),
    "cta": ("cta", "book", "join", "start"),
}


def resolve_section(doc: str, key: str) -> Optional[str]:
    """The id of the top-level <section> the owner means: the exact id,
    then a friendly name ('gallery' finds id="work"), then an id that
    contains the word, then a section whose heading carries it."""
    spans = section_spans(doc)
    ids = [sid for sid, _, _ in spans]
    k = re.sub(r"[^a-z0-9-]", "", str(key or "").strip().lower().lstrip("#"))
    if not k or not ids:
        return None
    if k in ids:
        return k
    for alias in _SECTION_SYNONYMS.get(k, ()):
        if alias in ids:
            return alias
    for sid in ids:
        if k in sid.lower():
            return sid
    for sid, a, z in spans:
        h = re.search(r"<h[1-3]\b[^>]*>(.*?)</h[1-3]>", doc[a:z], re.IGNORECASE | re.DOTALL)
        if h and k in re.sub(r"<[^>]+>", " ", h.group(1)).lower():
            return sid
    return None


def refine_section_doc(doc: str, spec_text: str, ctx: Dict[str, Any],
                       business_id: str, section: str, instruction: str,
                       units: Optional[int] = None) -> Dict[str, Any]:
    """Rework ONE section of a finished page under the owner's instruction.

    {ok: True, html, section, notes[]} or {ok: False, error[, sections]}.
    The candidate wears the same mechanical armor as a build and must not
    add a law violation or a visible stand-in the page did not already
    have; anything else is a refusal that leaves the page unchanged.
    `units` is the price, charged on the one model call."""
    spec_text = spec_for_builder(spec_text)
    sid = resolve_section(doc, section)
    if not sid:
        return {"ok": False, "error": f"section '{section}' isn't on the page",
                "sections": [s for s, _, _ in section_spans(doc)]}
    real_data = assemble_real_data(ctx, business_id)
    endpoint = contact_endpoint(business_id)
    mech: Dict[str, Any] = {}

    def _mechanical(d: str) -> str:
        d, dropped = armor_scripts(d, allowed_fetch=endpoint)
        d, _stripped = armor_external(d)
        d, _typeset = _craft().typographer(d)
        d, _added = annotate_editability(d)
        mech["scripts_dropped"] = dropped
        return d

    def _laws(d: str) -> List[str]:
        return (check_truth(d, real_data) + check_tenure(d, real_data)
                + check_coverage(d, real_data, page="home")
                + check_grammar(d) + check_head(d) + check_interactions(d)
                + check_connected(d, real_data)
                + armor_violations(mech.get("scripts_dropped") or [], endpoint))

    issues = [f"THE OWNER'S REQUEST, IN THEIR WORDS: {instruction}",
              "Change what they asked for and nothing else: keep the section's "
              "job on the page, every real fact, and the page's look.",
              "Photos: use only image urls in THE REAL DATA, each photo once on "
              "the page; never a visible box standing in for one."]
    raw = _call(_SECTION_SYSTEM.replace("{SYSTEM}", _SYSTEM),
                build_section_prompt(spec_text, real_data, doc, sid, issues),
                business_id, spend=new_spend(), units=units,
                task_type="builder_v2_refine")
    if not raw:
        return {"ok": False, "error": "the rework didn't come back. Nothing on "
                                      "the page changed; try again"}
    cand = splice_section(doc, sid, raw)
    if not cand:
        return {"ok": False, "error": "the reworked section didn't fit the page. "
                                      "Nothing on the page changed"}
    cand = _mechanical(cand)
    before = set(_laws(doc))
    broke = [v for v in _laws(cand) if v not in before]
    if broke:
        logger.warning(f"[v2-refine] {sid} rework refused: {broke[:3]}")
        return {"ok": False, "error": "the rework broke one of the page's rules, "
                                      "so nothing on the page changed",
                "violations": broke[:5]}
    stand_before = set(check_stand_ins(doc))
    if [s for s in check_stand_ins(cand) if s not in stand_before]:
        return {"ok": False, "error": "the rework drew a box where a photo should "
                                      "be, so nothing on the page changed"}
    soft = _craft().check_html(cand, real_data)
    # the repeated-photo law (#1218) joins the notes wherever it is present
    repeated = globals().get("check_repeated_photos")
    if callable(repeated):
        soft += repeated(cand)
    soft_before = set(_craft().check_html(doc, real_data))
    return {"ok": True, "html": cand, "section": sid,
            "notes": [s for s in soft if s not in soft_before][:5]}


def _concept_sheet(spec_text: str) -> Dict[str, str]:
    try:
        import site_concept
        return site_concept.parse_sheet(spec_text)
    except Exception as e:
        logger.info(f"[v2] concept sheet unreadable: {e}")
        return {}


def _concept_findings(html: str, sheet: Dict[str, str]) -> List[str]:
    try:
        import site_concept
        return site_concept.check_page(html, sheet)
    except Exception as e:
        logger.info(f"[v2] concept check skipped: {e}")
        return []


def _craft():
    """craft_laws, imported late so a missing module can never stop a
    build (the floor is quality, not a gate)."""
    try:
        import craft_laws
        return craft_laws
    except Exception as e:                     # pragma: no cover
        logger.warning(f"[v2] craft floor unavailable: {e}")

        class _Off:
            RENDER_JS = "() => ({})"

            @staticmethod
            def typographer(d):
                return d, 0

            @staticmethod
            def check_html(d, rd=""):
                return []

            @staticmethod
            def render_findings(m):
                return []
        return _Off


def house_style(home_html: str) -> str:
    """What an offer page must wear exactly: the home page's styles, font
    links, header and footer (capped so the brief stays sane)."""
    h = home_html or ""
    styles = "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style>", h,
                                   re.DOTALL | re.IGNORECASE))[:60000]
    fonts = "\n".join(re.findall(r"<link\b[^>]*fonts\.googleapis\.com[^>]*>", h,
                                  re.IGNORECASE))[:2000]
    header = (re.search(r"<header\b.*?</header>", h, re.DOTALL | re.IGNORECASE)
              or re.search(r"<nav\b.*?</nav>", h, re.DOTALL | re.IGNORECASE))
    footer = re.search(r"<footer\b.*?</footer>", h, re.DOTALL | re.IGNORECASE)
    return "\n".join([
        "FONT LINKS:", fonts,
        "STYLES (reuse these rules and class names; add rules only for this page's own sections):",
        styles,
        "HEADER (reuse it, pointing its links at the home page's sections with /#id):",
        header.group(0)[:8000] if header else "(none)",
        "FOOTER (reuse it):",
        footer.group(0)[:6000] if footer else "(none)",
    ])


def offer_page_brief(path: str, name: str, house: str) -> str:
    return "\n".join([
        "== THIS CALL BUILDS THE OFFER PAGE, NOT THE HOME PAGE ==",
        f"Build ONE complete page: the offer page{(' for ' + name) if name else ''} "
        f"that the blueprint's section 6 describes, served at {path}. It runs the "
        "section 0 concept at WORLD intensity: its vocabulary, its objects, its "
        "living detail. The home page (section 3) is already built; do not rebuild "
        "it. Link back to it (href=\"/\") from the header.",
        "Wear the house style below EXACTLY: the same :root tokens, the same fonts, "
        "the same header and footer, so a visitor never feels they left the site.",
        "The every-image law is the home page's: show only the images this offer "
        "needs. The one action (book, enroll, ask) is a real link or the contact form.",
        "",
        "== THE HOUSE STYLE (from the home page already built) ==",
        house,
    ])


def run_builder_v2(spec_text: str, ctx: Dict[str, Any], business_id: str,
                   progress_cb=None, page: str = "home",
                   house: str = "") -> Dict[str, Any]:
    """ONE call → armor → (one scoped repair) → document or None.
    None = the old path takes over (and still wears the spec's tokens
    via the bridge). The report always returns — loud failures."""
    report: Dict[str, Any] = {"engine": "builder_v2", "model": _model(),
                              "mechanical": {}, "violations": [],
                              "repaired": False, "fallbacks": [],
                              "spend": new_spend()}
    spend = report["spend"]
    if "SX_BLOCK" in (spec_text or ""):
        report["block_tokens_rewritten"] = True
    spec_text = spec_for_builder(spec_text)

    def _progress(pct: int, stage: str):
        try:
            if progress_cb:
                progress_cb(pct, stage)
        except Exception:
            pass

    real_data = assemble_real_data(ctx, business_id)
    sheet = _concept_sheet(spec_text)
    offer = ctx.get("offer_page") if isinstance(ctx.get("offer_page"), dict) else {}
    page_brief = ""
    if page == "offer":
        report["page"] = "offer"
        page_brief = offer_page_brief(offer.get("path") or "/offer",
                                      offer.get("name") or "", house)
        # the offer page IS the World page: hold it to the world rules
        sheet = dict(sheet, scope="site", intensity="world") if sheet else sheet
    report["concept"] = {k: sheet.get(k) for k in ("intensity", "scope", "idea", "objects")
                         if sheet.get(k)}
    _layout = layout_key_for(spec_text) if page == "home" else None
    if _layout:
        report["concept"]["layout"] = _layout
    _progress(48, "One mind builds the whole page")
    # THE BUILDER WITH TOOLS (2026-08-29): when the loop is on, the
    # authoring step can look at the owner's images, pull whole sections
    # of real data, read the vocabulary, and RENDER its own draft to see
    # it and its laws before handing in. Everything below — armor, laws,
    # the surgical repair, the eyes — is unchanged.
    doc: Optional[str] = None
    try:
        import builder_loop
        if builder_loop.enabled() and page == "home":
            _progress(48, "The builder looks, renders, corrects")
            looped = builder_loop.run_loop(spec_text, ctx, business_id, spend,
                                           progress_cb=_progress)
            report["loop"] = looped.get("report")
            doc = looped.get("html")
            if not doc:
                report["fallbacks"].append({
                    "stage": "loop",
                    "detail": "the tool loop produced no document — one-pass author"})
    except Exception as e:
        logger.warning(f"[v2] tool loop crashed (non-fatal — one-pass author): "
                       f"{type(e).__name__}: {e}")
        report["fallbacks"].append({"stage": "loop",
                                    "detail": f"{type(e).__name__}: {e}"})
    if not doc:
        raw = _call(_SYSTEM, build_user_prompt(spec_text, real_data,
                                               page_brief=page_brief),
                    business_id, spend=spend)
        doc = _parse_doc(raw or "")
    if not doc:
        report["fallbacks"].append({"stage": "author",
                                    "detail": "no parseable document"})
        return {"html": None, "report": report}

    endpoint = contact_endpoint(business_id)

    def _mechanical(d: str) -> str:
        d, dropped = armor_scripts(d, allowed_fetch=endpoint)
        d, stripped = armor_external(d)
        d, typeset = _craft().typographer(d)
        d, added = annotate_editability(d)
        report["mechanical"] = {"scripts_dropped": dropped,
                                "externals_stripped": stripped,
                                "typography_fixes": typeset,
                                "override_targets_added": added}
        return d

    def _soft(d: str) -> List[str]:
        # THE SOFT TIER: quality defects that earn the repair round and
        # never the fallback: visible stand-ins (11c), the craft floor
        # (one h1, alt text, type families, likely typos) and the page
        # held to its concept sheet (objects, the plain-word rule).
        out = (check_stand_ins(d) + check_repeated_photos(d)
               + check_unfilled(d)
               + _craft().check_html(d, real_data)
               + _concept_findings(d, sheet))
        if page == "home":
            out += check_stated_offers(d, ctx)
        if page == "home" and offer.get("path"):
            try:
                import site_pages
                out += site_pages.check_offer_link(d, offer["path"])
            except Exception:
                pass
        return out

    def _laws(d: str) -> List[str]:
        # armor_violations reads the drops _mechanical just recorded for
        # this same doc — a dropped script must fail the law gate loudly
        # (silently shipping it is the 2026-07-25 blank-sections bug).
        return (check_truth(d, real_data) + check_tenure(d, real_data)
                + check_coverage(d, real_data, page=page)
                + check_grammar(d) + check_head(d) + check_interactions(d)
                + check_connected(d, real_data)
                + armor_violations(
                    report["mechanical"].get("scripts_dropped") or [],
                    endpoint))

    doc = _mechanical(doc)
    violations = _laws(doc)
    # THE SOFT TIER: stand-ins (11c) cost the same repair round as a law,
    # but a stand-in is a quality defect, not an invented fact — it never
    # sends a build to the fallback engine. Whatever survives the repair
    # is reported (report["stand_ins"]) and handed to the eyes.
    stand_ins = _soft(doc)
    if (violations or stand_ins) and not _budget_left(spend):
        # THE HARD BUDGET: no repair round left in the purse. Stand-ins
        # ride the report; hard laws still cannot ship (below).
        spend["skipped"].append("repair")
        report["violations"] = violations + stand_ins
        report["fallbacks"].append({
            "stage": "repair",
            "detail": f"output budget reached ({spend['output_tokens']} tokens) "
                      "— repair round skipped"})
        if violations:
            return {"html": None, "report": report}
    elif violations or stand_ins:
        report["violations"] = violations + stand_ins
        _progress(56, "Surgical repair")
        raw2 = _call(_SYSTEM,
                     build_user_prompt(spec_text, real_data,
                                       violations=violations + stand_ins,
                                       prior_doc=doc),
                     business_id, spend=spend)
        doc2 = _parse_doc(raw2 or "")
        if doc2:
            doc2 = _mechanical(doc2)
            v2 = _laws(doc2)
            if not v2:
                report["repaired"] = True
                doc = doc2
            elif violations:
                report["fallbacks"].append({
                    "stage": "repair",
                    "detail": "still failing after one repair: "
                              + "; ".join(v2[:4])})
                return {"html": None, "report": report}
            else:
                report["fallbacks"].append({
                    "stage": "repair",
                    "detail": "stand-in repair broke a law — keeping the "
                              "law-passing document"})
        elif violations:
            report["fallbacks"].append({"stage": "repair",
                                        "detail": "repair unparseable"})
            return {"html": None, "report": report}
        else:
            report["fallbacks"].append({"stage": "repair",
                                        "detail": "stand-in repair unparseable "
                                                  "— keeping the document"})
    report["stand_ins"] = check_stand_ins(doc)
    report["repeated_photos"] = check_repeated_photos(doc)
    report["craft"] = _craft().check_html(doc, real_data)

    # THE EYES (Arc 2), NOW A LOOP (2026-10-03, phase 3 of the hand-build
    # plan): look, fix the weakest sections, look again. Quality violations
    # are never fatal: if the eyes can't run, or a repair breaks a law, the
    # law-passing document ships and the report says so.
    report["vision"] = {"ran": False, "verdict": None, "violations": [],
                        "rounds": [], "section_repairs": [], "for_the_owner": [],
                        "questions": []}
    if eyes_enabled():
        rounds = look_fix_rounds()
        per_round = look_fix_sections()
        cap_cents = look_fix_max_cents()
        page_repair_used = False
        # J3: what each section was already rebuilt for (applied rebuilds)
        tried: Dict[str, List[List[str]]] = {}
        cents_at_first_look = float(spend.get("cost_cents") or 0)
        for rnd in range(1, rounds + 1):
            if rnd > 1:
                extra = float(spend.get("cost_cents") or 0) - cents_at_first_look
                if extra >= cap_cents:
                    spend["skipped"].append(f"look-fix:round-{rnd}:cap")
                    break
                if not _budget_left(spend):
                    spend["skipped"].append(f"look-fix:round-{rnd}:budget")
                    break
            _progress(min(80, 62 + 6 * (rnd - 1)),
                      "The builder inspects its own work" if rnd == 1
                      else "The builder looks at the page again")
            why: Dict[str, str] = {}
            verdict = inspect_with_eyes(doc, spec_text, business_id, why=why)
            _m = walk_measurements(doc)
            measured = render_findings(_m) + _craft().render_findings(_m)
            if page == "home":
                measured += layout_findings(spec_text, _m)
            walk = visitor_walk_findings(_m)
            weakest = (verdict or {}).get("weakest") if verdict else None
            rec: Dict[str, Any] = {
                "round": rnd, "verdict": (verdict or {}).get("verdict"),
                "weakest": weakest, "measured": len(measured),
                "violations": len((verdict or {}).get("violations") or []),
                "biggest": (verdict or {}).get("biggest"),
                "stuck": ((verdict or {}).get("visitor") or {}).get("stuck"),
                "walk": [w["what"] for w in walk],
                "sections": [], "page_repair": False}
            report["vision"]["rounds"].append(rec)
            # a decision the eyes doubt is the owner's to answer, not theirs
            # to undo; the walk-through shows it (site_revisions.state)
            ask = (verdict or {}).get("ask_owner")
            if ask and ask not in report["vision"]["questions"] \
                    and len(report["vision"]["questions"]) < 3:
                report["vision"]["questions"].append(ask)
            if rnd == 1:
                if not verdict and why.get("reason"):
                    report["vision"]["reason"] = why["reason"]
                report["vision"]["measured"] = measured
                if verdict:
                    report["vision"]["ran"] = True
                    report["vision"]["verdict"] = verdict.get("verdict")
                    report["vision"]["violations"] = verdict.get("violations", [])
                    report["vision"]["weakest"] = weakest
                    report["vision"]["visitor"] = verdict.get("visitor")
            if not verdict and not measured and not walk:
                break                                  # nothing to look with
            page_items, by_section = plan_vision_repair(
                verdict, doc, [f"MEASURED IN THE RENDER: {m}" for m in measured],
                walk=walk, empty=empty_sections(doc))
            if page_items and page_repair_used:
                # the whole-page pass was spent: what is page-wide now
                # rides along with the section rebuilds, or the look ends
                if not by_section:
                    break
                page_items = []
            if not page_items and not by_section:
                break                                  # the look found it right
            changed = False
            if by_section and not page_items:
                # THE DESIGNER'S REVIEW: only the named sections are rebuilt.
                _progress(min(84, 66 + 6 * (rnd - 1)),
                          "Rebuilding the sections the eyes flagged")
                rebuilt_here = 0
                for sid, items in by_section.items():
                    if rebuilt_here >= per_round:
                        break
                    if len(tried.get(sid) or []) >= 2:
                        # J3: rethought once already and still flagged —
                        # stop spending on it; it is the owner's to look at
                        if sid not in [o["section"] for o in report["vision"]["for_the_owner"]]:
                            report["vision"]["for_the_owner"].append(
                                {"section": sid, "what": str(items[0])[:240]})
                        continue
                    if not _budget_left(spend):
                        spend["skipped"].append(f"section-repair:{sid}")
                        break
                    asked = list(items)
                    if tried.get(sid):
                        asked = [second_try_line(tried[sid][-1])] + asked
                    rebuilt_here += 1
                    raw_s = _call(_SECTION_SYSTEM.replace("{SYSTEM}", _SYSTEM),
                                  build_section_prompt(spec_text, real_data, doc, sid, asked),
                                  business_id, spend=spend)
                    cand = splice_section(doc, sid, raw_s or "")
                    applied = False
                    if cand:
                        cand = _mechanical(cand)
                        if not _laws(cand):
                            doc, applied = cand, True
                    if applied:
                        tried.setdefault(sid, []).append([str(i)[:200] for i in items[:2]])
                    rec["sections"].append({"section": sid, "applied": applied,
                                            "second_try": len(tried.get(sid) or []) >= 2})
                    report["vision"]["section_repairs"].append(
                        {"section": sid, "applied": applied, "round": rnd})
                    changed = changed or applied
            else:
                if not _budget_left(spend):
                    spend["skipped"].append("vision-repair")
                    report["fallbacks"].append({
                        "stage": "vision-repair",
                        "detail": "output budget reached — keeping the law-passing document"})
                    break
                _progress(min(84, 66 + 6 * (rnd - 1)), "Vision repair: fixing what the eyes found")
                page_repair_used = True
                rec["page_repair"] = True
                # page-wide: one whole-page pass carries everything, the
                # section items included
                seen = list(page_items)
                for items in by_section.values():
                    seen += items
                # a stand-in or a craft miss the surgical round left behind
                # rides the vision repair too
                seen += [f"STILL ON THE PAGE: {x}" for x in report["stand_ins"]]
                seen += [f"STILL ON THE PAGE: {x}" for x in report.get("craft") or []]
                raw3 = _call(_SYSTEM,
                             build_user_prompt(spec_text, real_data,
                                               violations=seen,
                                               prior_doc=doc),
                             business_id, spend=spend)
                doc3 = _parse_doc(raw3 or "")
                if doc3:
                    doc3 = _mechanical(doc3)
                    if not _laws(doc3):
                        doc, changed = doc3, True
                    else:
                        report["fallbacks"].append({
                            "stage": "vision-repair",
                            "detail": "vision repair broke a law — "
                                      "keeping the law-passing document"})
                else:
                    report["fallbacks"].append({
                        "stage": "vision-repair",
                        "detail": "vision repair unparseable — keeping "
                                  "the law-passing document"})
            if changed:
                report["vision"]["repaired"] = True
                report["stand_ins"] = check_stand_ins(doc)
                report["craft"] = _craft().check_html(doc, real_data)
            else:
                break                                  # a round that changed nothing ends the loop
        report["vision"]["looks"] = len(report["vision"]["rounds"])
    return {"html": doc, "report": report}
