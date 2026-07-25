# spec_author.py
# ─────────────────────────────────────────────────────────────────────
# THE SPEC AUTHOR (Director's Cut arc 3).
#
# Kevin's finding (2026-07-24): a hand-written design SPEC — every
# decision already made: which word is gold, what the stats say, what
# the button does — produced the same excellent page from five
# different models. The prompt did the designing; the models did the
# rendering. Vague briefs get filled with the median of the internet;
# a fully-decided spec leaves no gaps for generic to leak in.
#
# This module authors that document from everything the system knows
# (the canvas dossier: facts, brand, section plan, owner's words,
# judge lessons, language + bar) — one CHEAP text-only call. The
# practitioner reads and revises the spec for pennies; only an
# APPROVED spec is worth a paid build, where it leads the canvas
# brief as the law of the page.
#
# Persistence: business_sites.site_config.design_spec =
#   {"text", "status": "draft"|"approved", "authored_at", "model",
#    "revision": int}
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import llm_call
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("spec_author")

SPEC_MAX_TOKENS = 12000  # room to FINISH: both live drafts died
                         # mid-sentence in section 4 at the 6K cap
SPEC_TEMPERATURE = 0.7
# The spec leads the canvas brief — cap what rides downstream so the
# builder's context stays sane even if a model over-writes. Sized
# above the token budget so the char slice never truncates a document
# the model completed (12K tokens ≈ 45K chars worst case).
SPEC_MAX_CHARS = 48000


def _model() -> str:
    m = (os.environ.get("SPEC_AUTHOR_MODEL") or "").strip()
    if m:
        return m
    try:
        import canvas
        return canvas._model()
    except Exception:
        return "claude-sonnet-4-5-20250929"


# ─── The taught anatomy ──────────────────────────────────────────────
# The format is taught as a RUBRIC (the shape of decidedness), never a
# lookup table of content — the standing generalization rule.

_SYSTEM = """You are the DIRECTOR — a senior creative director writing the complete design specification for one business's website. A builder (another craftsperson) will execute your document exactly as written, so the quality of the final page equals the decidedness of your spec.

THE ARCHAEOLOGY — do this FIRST, before writing a word:
You are shown the owner's REAL WORK as images. The design is already inside it — your job is to translate a visual voice that already exists, never to invent a new brand over it. Study the images and extract:
- The palette they ACTUALLY use (exact color families you can see — a brand mark's colors outrank any abstract preference)
- The typography personality they choose in their own pieces (condensed display? script? editorial serif? how big do they go?)
- The energy and density of their layouts (bold and loud? quiet and spare? how much they put on a page)
- Recurring motifs and instincts (dark grounds, glow, texture, type-as-image, portrait treatment)
Then DECLARE your findings at the top of section 2 (BRAND IDENTITY) in 3-5 lines beginning "OBSERVED IN THE WORK:" — and let those observations drive every choice below them. A spec whose palette and type could not be traced back to the owner's own pieces is a failed spec.
THE DECLARATION RULE: if ANY images were provided above, the declaration MUST begin "OBSERVED IN THE WORK:" — "IMAGINED FOR THE WORK:" is permitted ONLY on a zero-image business. When an image labeled THE BRAND MARK is present, your palette section MUST name the mark's actual colors and bind --sx-accent (and any second accent) to them.

THE IMAGINATION — when NO images are provided (a new business with no work yet):
You do not get to design from nothing, and you do not get to retreat to the safe median. A designer without a portfolio mines the client's WORLD instead:
- Build their world in your mind: the physical trade behind the business — its materials, tools, light, and rooms (a barbershop owns chrome, leather, neon, razor steel; a bakery owns flour dust, warm ovens, butcher paper; a faith-driven coach owns stained-glass light and gold on deep tones). Steal the palette and texture from the world they already work in.
- Take their words literally: the owner's tone words, slogan, and interview answers are design material — a business that says "bold" and "legacy" has already chosen a type personality.
- Name 2-3 adjacent masters: real-world aesthetics whose soul fits this business (vintage sign-painting, editorial sport campaigns, quiet-luxury hospitality) and borrow their discipline, never their identity.
- Then invent the brand seed: choose the palette and type AS IF you were designing their brand mark first, and build the site from that mark.
DECLARE it at the top of section 2 in 3-5 lines beginning "IMAGINED FOR THE WORK:" — the world you mined, the masters you leaned on, and why this direction is theirs. Commit as hard as if you'd seen a portfolio: an invented direction argued from their world beats a safe one argued from nothing.
The ladder is absolute: observe the work when it exists; imagine from their world when it doesn't; never skip a rung that exists, and never design from a vacuum.

THE STANDARD OF DECIDEDNESS — the entire point of this document:
A vague brief gets filled with the median of the internet. Your spec leaves NO decision to the builder's defaults. That means:
- Write the ACTUAL words: every headline verbatim, every eyebrow, every stat with its real number and label, every button label. Never "a strong headline about X" — write the headline.
- Name every color BY ROLE AND HEX and say exactly which words/elements carry an accent color. Never "use accents tastefully."
- Name the fonts and which one owns display / body / editorial-accent duty.
- Decide every section's composition in one or two sentences a builder can execute ("two-column: portrait left in a hairline frame; bio right, 2 paragraphs, second one shorter").
- Decide the interactions: what moves, when, and what every hover/click does. One signature interaction maximum; name it.
- Decide the mobile behavior in one line per non-obvious section.

THE MOVES VOCABULARY — the difference between "has a motif" and "is built out of its motif." These are named, proven moves; your spec commits to ONE OR TWO by name and writes exactly where each recurs (a move used once is decoration; used three ways it becomes the site's spine):
- THE THREAD: one drawn line/element that walks the whole page and marks every section as a station on it (vertical rail, lit dots, a horizontal turn inside one section).
- TYPE AS IMAGE: an oversized ghost word behind the hero, outline-stroke display words, numerals as stroked italic monuments that fill on hover.
- THE CEREMONY: a marquee/ticker of the brand promise between sections, a rotating circular text stamp on a portrait, a self-drawing underline on THE word.
- THE EXHIBITION: the work hung like a gallery wall — lead pieces large and full-bleed, rhythmic bands after, one designed typographic tile sitting among the artwork.
- THE ECHO FRAME: portraits and lead images in hairline frames with a second offset frame behind; captions running vertical along the frame edge.
- THE STAGE LIGHT: one warm radial glow that owns the hero and returns once at the close, grain over everything, gradient depth between grounds.
MATERIAL MOVES (audited builder-native, 2026-07-25 — order them by name):
- THE FOIL: metallic type via gradient clipped to the letters (gold, bronze, silver) — a luxury headline that costs nothing.
- THE EMBOSS: pressed-in or raised surfaces from pure inset light and shadow — swatches, seals, cards that read as physical.
- THE TEAR: torn-paper section breaks via inline SVG masks — the hand-made edge between grounds.
MOTION MOVES (the Emergent-class arrivals — all pure CSS/JS, no libraries; the builder cannot load external scripts):
- THE KINETIC HERO: the headline arrives line by MASKED line (overflow-hidden line wrappers, staggered rise), the accent word landing last with its own gesture. One-time, on arrival.
- THE DEPTH: two or three layers drifting at different speeds on scroll (transform-only parallax; subtle, never seasick).
- THE ORBIT: the work turning slowly in 3D space (CSS preserve-3d ring) as the gallery's signature — reserved for businesses whose work IS the show.
- THE PIN: one scroll scene that HOLDS (position: sticky) while its content changes beside it — the modern storytelling beat, used once.
MICRO-DELIGHT is a floor, not a move: every interactive element answers its hover with something small and intentional (a lift, a fill, an underline drawing itself) — 21st-century pages feel alive at the fingertips.
Motion discipline is unchanged and absolute: ONE signature motion moment per page, scroll reveals scroll-position driven, prefers-reduced-motion shows everything instantly.
Choose from this vocabulary or invent a move of equal specificity and NAME it — "tasteful animations" is not a move. The chosen move(s) must appear in section 1 by name, in section 3 at every recurrence, and in section 4 with their exact behavior.

THE COPY GRAMMAR (the DASH LAW — the owner's standing rule): you write every word of the page's copy, so grammar defects are YOUR defects. Never splice a sentence with a dash: no em dashes in headlines, body copy, or captions you author. Rewrite with a period, comma, or colon. A dash survives only inside a proper title the dossier itself carries (an artwork or event name).

THE BRAND COLOR LAW:
When the business has brand colors — visible in a brand mark you were shown, or carried as hexes in the dossier's brand section — those colors ARE the site's accent palette. You may refine a shade within the same hue family (declare the refinement and why), but inventing a NEW accent hue while brand colors exist is a violation on par with inventing a fact. If the brand carries two colors, the second is a real citizen: give it a job (a section family, a label voice), never drop it.

THE ATMOSPHERE RULE (accent scarcity is NOT atmosphere scarcity):
Keeping accents disciplined never licenses a flat, empty ground. The stage itself must be DESIGNED: subtle texture or grain, a warm radial glow behind the hero, gradient depth between sections, one full-width color band as punctuation. These are atmosphere, and they have their own budget — spend it. A page can hold a strict three-touch accent rule AND feel lit, warm, and alive; a page that reads as "flat dark rectangle" has failed the atmosphere budget even if every accent rule was obeyed.

THE GENEROSITY RULE (learned the hard way — the first live spec produced an austere concept poster and the owner rejected it on sight):
A business site is GENEROUS. Rich sections executed cleanly beat austere concept pages, every time. Restraint disciplines COLOR and MOTION — never CONTENT. A visitor should always have something to look at, and every piece of the business should have a home. If the finished page could be described as "minimal," you have failed this business. Your concept is the thread that runs THROUGH a full site — never a substitute for one.

THE COVERAGE LAW (equal in force to the truth law):
Every real asset in the dossier gets a home on the page. Omitting real material is a violation exactly as serious as inventing fake material.
- A fixed NAVIGATION with the business name and section links. Always.
- EVERY real service/offering appears — each with its own cell/card and copy.
- EVERY real portfolio/gallery image appears, referenced by its exact url — real work is the strongest thing on any business site. Never ban imagery when real imagery exists. AUTHOR a proper display caption for each piece (a caption describes what the piece is — it is copy, yours to write; a raw filename is data and must never render as a caption). CAPTION TRUTH: describe only what the labeled image actually shows — a caption bound to the wrong url is a truth violation. NO CONDITIONAL ENTRIES: the inventory is definitive; never write "(if provided — otherwise omit)" rows. Spec what exists, exactly.
- The owner's PORTRAIT appears if provided (about section).
- Every real testimonial/quote appears.
- A CONTACT section with a working inquiry form and every real contact channel. Always.
- A FOOTER. Always.
- Real stats/proof points if provided (never invented — mark a confirm-then-publish placeholder only when the owner has signaled a number exists).

THE DENSITY SKELETON — the default shape of a complete business site (deviate creatively in STYLE, never by omission of FUNCTION). Aim for 8-11 sections:
nav → full-viewport hero (display headline + real proof stats) → a brand moment (ticker/marquee/band) → services grid (all of them) → a second-family strip (method/studio/values) → portfolio with the real work (filters if 5+ pieces) → process steps → about with portrait → contact with form → footer.

STRUCTURE — output the document in exactly this anatomy, plain text with section rules (=====) and numbered sections:
1. OVERVIEW — what this site is, one paragraph. The page's single memorable move, named.
2. BRAND IDENTITY — fonts (role each), full color palette as CSS-variable-style roles with hexes.
3. LAYOUT & SECTIONS (top to bottom) — every section numbered, each with: composition decided, the REAL copy written out, which words carry accents, what imagery goes where (only real provided images or clearly-labeled slots). When the composition WANTS an image the inventory doesn't carry, spec an art-directed DROP SLOT with one line of shot direction in plain words ("DROP SLOT hero_portrait: you at the chair, mid-cut, warm light") — the builder renders it as a fillable frame the owner can click to upload, and your shot directions become the owner's photo shot list. Never fake imagery; real, or a directed drop slot.
4. INTERACTIONS & ANIMATIONS — the definitive list, honoring the INTERACTION GRAMMAR: with 5+ portfolio pieces the gallery opens each piece larger on click (a lightbox with the piece's title; closes on backdrop, button, and Escape) and filters actually filter with a worded empty state; the contact form confirms in words after submit; every clickable answers hover and keyboard focus; scroll reveals are scroll-position driven so fast scrolling can never skip a section.
5. DESIGN RULES (do / don't) — the taste laws for THIS page, including every learned ban from the judge's notes.

TRUTH LAW (absolute): every fact, price, service, testimonial, stat and claim in your spec must come from the DOSSIER below. Real or removed — if the dossier doesn't provide a number, do not invent one. Real portfolio images are listed; reference them by their given names/urls only.

TASTE: commit. The safe generic version of this page is a failure. One move a visitor describes to a friend tomorrow — designed, decided, and named in section 1. Honor the owner's words above everything except truth. If judge lessons are present, every one of them is a ban you design around. Do not reuse the same accent treatment the lessons criticize (no default gold-underline crutch).

OUTPUT: the document only. No preamble, no commentary, no code."""


def _digest_plan(spec_plan: List[Dict[str, Any]]) -> str:
    """The composed section plan as a one-line-per-section digest —
    the Director decides content AROUND this structure (data sections
    render from real rows; creative sections are fully authorable)."""
    if not spec_plan:
        return "(no composed plan yet — propose a section list yourself, 6-9 sections)"
    lines = []
    for i, s in enumerate(spec_plan, 1):
        mid = str(s.get("module") or "?")
        var = str(s.get("variant") or "")
        keys = ", ".join(sorted((s.get("content") or {}).keys())) or "-"
        lines.append(f"{i}. {mid}{f' ({var})' if var else ''} — content fields: {keys}")
    return "\n".join(lines)


def _inventory_digest(ctx: Dict[str, Any],
                      spec_plan: List[Dict[str, Any]]) -> str:
    """Every real asset, itemized — the coverage law applies to each.
    Reuses the atelier's REAL DATA assembly (the pipeline's single
    source of rendered truth) plus the gallery list with urls. The
    first live spec banned all imagery while seven real portfolio
    pieces sat in the database — the Director can't cover an inventory
    it never saw."""
    parts: List[str] = []
    try:
        import atelier
        seen: set = set()
        for s in spec_plan or []:
            mid = str(s.get("module") or "")
            if not mid or mid in seen:
                continue
            seen.add(mid)
            try:
                data = atelier._section_data(mid, s.get("content") or {}, ctx)
            except Exception:
                continue
            if data:
                parts.append(f"[{mid}]\n" + json.dumps(
                    data, ensure_ascii=False, indent=1)[:2600])
    except Exception as e:
        logger.info(f"[spec] inventory via atelier skipped: {e}")
    gallery = ctx.get("gallery") if isinstance(ctx.get("gallery"), list) else []
    lines: List[str] = []
    for i, g in enumerate(gallery[:12], 1):
        if isinstance(g, dict) and (g.get("url") or "").strip():
            lines.append(f"{i}. {g['url']} — "
                         f"{g.get('alt') or g.get('caption') or 'untitled piece'}")
    if lines:
        parts.append("[gallery — EVERY image below appears on the page. "
                     "Names here may be raw filenames: AUTHOR a proper "
                     "display caption for each (captions are copy, not "
                     "facts) while referencing the exact url.]\n"
                     + "\n".join(lines))
    # The practitioner's OWN slot uploads (portrait, hero photo …) — the
    # first live spec never saw the real portrait and stood in a poster
    # for it. Custom uploads are real assets; removed slots are skipped.
    slots = (((ctx.get("site") or {}).get("site_config") or {})
             .get("slots") or {})
    slot_lines: List[str] = []
    for name, rec in sorted(slots.items()):
        if not isinstance(rec, dict) or rec.get("removed"):
            continue
        cu = (rec.get("custom_url") or "").strip()
        if cu:
            slot_lines.append(f"- {name}: {cu} (the owner's own upload)")
    if slot_lines:
        parts.append("[owner's uploaded images — real, use by slot role; "
                     "the *about/portrait* slot is the owner's portrait]\n"
                     + "\n".join(slot_lines))
    # Real contact channels — the first live spec had to leave an
    # "add email/phone" hole because it never saw these.
    contact = ctx.get("contact") if isinstance(ctx.get("contact"), dict) else {}
    ch = [f"- {k}: {v}" for k, v in contact.items()
          if isinstance(v, str) and v.strip()]
    if ch:
        parts.append("[contact channels — every one appears in the "
                     "contact section]\n" + "\n".join(ch))
    return "\n\n".join(parts)


def build_user_prompt(dossier: str, spec_plan: List[Dict[str, Any]],
                      prior_spec: str = "", feedback: str = "",
                      inventory: str = "", discovery: str = "") -> str:
    """Pure prompt assembly (testable, no IO). `dossier` is the canvas
    brief — everything the system knows, already compiled; `inventory`
    is the itemized asset list the coverage law binds to; `discovery`
    is the Discovery dossier digest (Revamp Phase 1) — the practitioner's
    own confirmed answers, taste readings with provenance, and studied
    reference rules."""
    parts = [
        "== THE DOSSIER (everything known about this business — the only "
        "source of facts) ==",
        dossier.strip(),
        "",
    ]
    if discovery.strip():
        parts += [
            "== THE DISCOVERY DOSSIER (the practitioner's own answers and "
            "confirmed taste — provenance matters: 'asked' and 'flipped' "
            "values are their words and outrank 'inferred-confirmed', "
            "which outranks 'recon'; reference `rules` are transferable "
            "disciplines to learn from, `bans` are hard bans) ==",
            discovery.strip(),
            "",
        ]
    if inventory.strip():
        parts += [
            "== THE INVENTORY (every real asset — the coverage law applies "
            "to each item; every one gets a home on the page) ==",
            inventory.strip(),
            "",
        ]
    parts += [
        "== THE CURRENT SECTION PLAN (the page's chapters, in order) ==",
        _digest_plan(spec_plan),
        "",
    ]
    if prior_spec.strip():
        parts += [
            "== THE PRIOR SPEC (you are REVISING, not restarting — keep "
            "every decision the owner didn't question) ==",
            prior_spec.strip()[:SPEC_MAX_CHARS],
            "",
        ]
    if feedback.strip():
        parts += [
            "== THE OWNER'S REVISION NOTES (address every one, precisely) ==",
            feedback.strip()[:1200],
            "",
        ]
    parts.append("Write the complete design specification now.")
    return "\n".join(parts)


def _brand_mark_urls(ctx: Dict[str, Any], business_id: str = "") -> List[str]:
    """THE BRAND MARK — the single most identity-dense artifact, and
    the Brand Color Law's anchor. Lives in businesses.settings.brand_kit
    (logos.primary / logo_url, the Brand Kit upload surface — where the
    owner's 2026-07-24 upload actually landed while the Director kept
    reading only slots+gallery and never saw it). ctx first; service
    fetch fallback; https-only; at most 2."""
    settings: Dict[str, Any] = {}
    try:
        settings = (((ctx.get("bundle") or {}).get("business") or {})
                    .get("settings")) or {}
    except Exception:
        settings = {}
    if not settings and business_id:
        try:
            import sb_clients
            rows = sb_clients.sb_get_as_service(
                f"/businesses?id=eq.{business_id}&select=settings&limit=1") or []
            settings = (rows[0].get("settings") if rows else None) or {}
        except Exception as e:
            logger.info(f"[spec] brand-kit fetch skipped: {e}")
            return []
    bk = settings.get("brand_kit") if isinstance(settings.get("brand_kit"), dict) else {}
    logos = bk.get("logos") if isinstance(bk.get("logos"), dict) else {}
    si = settings.get("site_images") if isinstance(settings.get("site_images"), dict) else {}
    candidates = [logos.get("primary"), bk.get("logo_url"), si.get("logo")]
    candidates += [v for k, v in sorted(logos.items()) if k != "primary"]
    out: List[str] = []
    for v in candidates:
        if isinstance(v, str) and v.strip().lower().startswith("https://") \
                and v.strip() not in out:
            out.append(v.strip())
        if len(out) >= 2:
            break
    return out


def _image_urls(ctx: Dict[str, Any], cap: int = 12) -> List[str]:
    """The owner's real work, for the Director's eyes (THE ARCHAEOLOGY).
    Priority: slot custom uploads (brand mark / portrait / hero — the
    most identity-dense pieces), then gallery, deduped, capped. Pure.

    Cap raised 6→12 (2026-07-24): the first sighted draft's cap cut
    exactly the owner's LOUDEST pieces (the display-type flyers) — the
    Director observed the quiet half of the portfolio and reached for
    Montserrat again. The whole gallery must be seen."""
    urls: List[str] = []
    slots = (((ctx.get("site") or {}).get("site_config") or {})
             .get("slots") or {})
    for _name, rec in sorted(slots.items()):
        if isinstance(rec, dict) and not rec.get("removed"):
            cu = (rec.get("custom_url") or "").strip()
            if cu:
                urls.append(cu)
    gallery = ctx.get("gallery") if isinstance(ctx.get("gallery"), list) else []
    for g in gallery:
        if isinstance(g, dict) and (g.get("url") or "").strip():
            urls.append(g["url"].strip())
    seen: set = set()
    out: List[str] = []
    for u in urls:
        if u.lower().startswith("https://") and u not in seen:
            seen.add(u)
            out.append(u)
        if len(out) >= cap:
            break
    return out


def _call_llm(system: str, user: str, business_id: str,
              image_urls: Optional[List[str]] = None,
              mark_urls: Optional[List[str]] = None) -> Optional[str]:
    """Anthropic call THROUGH THE MODEL LADDER — same discipline as the
    canvas/atelier. The naive first version passed temperature
    unconditionally; with SPEC_AUTHOR_MODEL unset the model resolves to
    ATELIER_MODEL=claude-opus-4-8, which 400s on sampling params — the
    exact silent-atelier killer sampling_kwargs() exists to prevent.
    The ladder also buys invalid-model fallback + timeout retry. Usage
    metered under its own endpoint so spec cost is visible separately."""
    try:
        import model_ladder
        from anthropic import Anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            logger.warning("[spec] no ANTHROPIC_API_KEY — author unavailable")
            return None
        client = llm_call.sdk_client(key=key, timeout=120.0, max_retries=1)

        # THE ARCHAEOLOGY: the owner's real pieces ride the call as
        # url-source image blocks so the Director designs from what it
        # SEES, not from adjectives. Fail-open: a bad url only costs
        # that image (the API skips unfetchable url sources by erroring
        # — so a fetch failure retries once with text only).
        # LABELED EYES (2026-07-24): every image block is preceded by a
        # text label carrying its exact url — without labels the first
        # sighted draft observed correctly but bound its observations
        # to the WRONG urls (a cross tee captioned "working session").
        # Observation without addressability scrambles the spec.
        content: Any = user
        if image_urls or mark_urls:
            blocks: List[Dict[str, Any]] = [
                {"type": "text",
                 "text": "THE OWNER'S REAL WORK — study these first "
                         "(the archaeology). Each image is labeled with "
                         "its EXACT url: bind every observation and "
                         "every caption to that label. Caption ONLY "
                         "images shown here; never invent a caption for "
                         "an image you did not see."}]
            n = 0
            for u in (mark_urls or []):
                n += 1
                blocks.append({"type": "text",
                               "text": f"IMAGE {n} — THE BRAND MARK (the "
                                       f"color authority: the Brand Color "
                                       f"Law binds the site's accent "
                                       f"palette to the exact colors in "
                                       f"this mark) — exact url: {u}"})
                blocks.append({"type": "image",
                               "source": {"type": "url", "url": u}})
            for u in (image_urls or []):
                n += 1
                blocks.append({"type": "text",
                               "text": f"IMAGE {n} — exact url: {u}"})
                blocks.append({"type": "image",
                               "source": {"type": "url", "url": u}})
            blocks.append({"type": "text", "text": user})
            content = blocks

        def _do(model: str, max_tokens: int, timeout: float):
            try:
                return client.messages.create(
                    model=model, max_tokens=max_tokens, system=system,
                    messages=[{"role": "user", "content": content}],
                    timeout=timeout,
                    **model_ladder.sampling_kwargs(model, SPEC_TEMPERATURE))
            except Exception as e:
                # An unfetchable image url 400s the whole request —
                # the spec must never die for a broken image link.
                if content is not user and "image" in str(e).lower():
                    logger.warning(f"[spec] image blocks rejected "
                                   f"({type(e).__name__}) — text-only retry")
                    return client.messages.create(
                        model=model, max_tokens=max_tokens, system=system,
                        messages=[{"role": "user", "content": user}],
                        timeout=timeout,
                        **model_ladder.sampling_kwargs(model, SPEC_TEMPERATURE))
                raise

        msg, used_model = model_ladder.call_with_ladder(
            _do, model=_model(), task="spec_author",
            business_id=business_id, max_tokens=SPEC_MAX_TOKENS)
        if getattr(msg, "stop_reason", "") == "max_tokens":
            # The document was cut mid-sentence — ship it anyway (the
            # owner can revise) but say so LOUDLY; a silent truncation
            # reads as a finished spec.
            logger.warning(f"[spec] document hit the {SPEC_MAX_TOKENS}-token "
                           f"ceiling for {business_id[:8]} — output truncated")
        try:
            from api_usage_logger import log_api_usage_sync
            u = getattr(msg, "usage", None)
            log_api_usage_sync(
                endpoint="/composer/spec", model=used_model or "",
                input_tokens=getattr(u, "input_tokens", 0) or 0,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                business_id=business_id, task_type="spec_author")
        except Exception:
            pass
        return "".join(b.text for b in msg.content
                       if getattr(b, "type", None) == "text")
    except Exception as e:
        logger.warning(f"[spec] author call failed: {type(e).__name__}: {e}")
        return None


def author_spec(business_id: str, ctx: Dict[str, Any],
                dro: Optional[Dict[str, Any]],
                spec_plan: List[Dict[str, Any]],
                prior_spec: str = "", feedback: str = "") -> Optional[str]:
    """One text-only call → the full design document, or None (caller
    surfaces the failure; nothing is persisted here)."""
    try:
        import canvas_brief
        dossier = canvas_brief.compile_canvas_brief(ctx, dro, spec_plan)
    except Exception as e:
        logger.warning(f"[spec] dossier compile failed ({e}) — minimal dossier")
        dossier = "Follow the design rationale. Real data only; never invent facts."
    try:
        inventory = _inventory_digest(ctx, spec_plan)
    except Exception as e:
        logger.info(f"[spec] inventory digest skipped: {e}")
        inventory = ""
    # Revamp Phase 1: the Discovery dossier rides the prompt from day
    # one — confirmed answers, provenance-tagged taste, reference rules.
    disc = ""
    try:
        import discovery as _disc
        _dd = (((ctx.get("site") or {}).get("site_config") or {})
               .get("discovery_dossier"))
        disc = _disc.dossier_digest(_dd)
    except Exception as e:
        logger.info(f"[spec] discovery digest skipped: {e}")
    user = build_user_prompt(dossier, spec_plan, prior_spec, feedback,
                             inventory=inventory, discovery=disc)
    marks = _brand_mark_urls(ctx, business_id)
    work = [u for u in _image_urls(ctx) if u not in marks]
    text = (_call_llm(_SYSTEM, user, business_id,
                      image_urls=work, mark_urls=marks) or "").strip()
    if not text:
        return None
    return text[:SPEC_MAX_CHARS]


# ─── Persistence ─────────────────────────────────────────────────────

# ─── THE SPEC TOKEN BRIDGE (2026-07-24, "old design living inside") ──
# An approved spec names its palette and fonts, but the page's --sx-*
# tokens came from the stored brand DNA — the spec's colors physically
# could not reach the page, and an author that obeyed the spec's hexes
# was killed by the token-only validator (hex literals banned). These
# helpers extract the spec's declared roles and install them as the
# page's tokens LAST, on every path — canvas or module fallback — so
# the approved look survives even a fallback build.

_TOKEN_RE = re.compile(
    r"(--sx-[a-z][a-z0-9-]*)\s*[:=]\s*"
    r"(#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\))")

# Font whitelist: common Google families the shell can safely load.
_FONT_NAMES = (
    "Montserrat", "Open Sans", "Bebas Neue", "Playfair Display",
    "DM Sans", "Inter", "Poppins", "Oswald", "Raleway", "Lato",
    "Archivo", "Space Grotesk", "Manrope", "Fraunces", "Work Sans",
    "Libre Baskerville", "Cormorant Garamond", "Anton", "Sora",
    "Outfit", "Barlow", "Karla", "Rubik", "Crimson Pro",
)
_FONT_RE = re.compile("|".join(re.escape(f) for f in _FONT_NAMES))


def extract_token_overrides(spec_text: str) -> Dict[str, str]:
    """{--sx-token: value} for every color role the spec declares.
    First declaration wins. Font tokens are excluded here (fonts need
    a <link>, handled by extract_font_overrides)."""
    out: Dict[str, str] = {}
    for m in _TOKEN_RE.finditer(spec_text or ""):
        name, val = m.group(1), m.group(2).strip()
        if "font" in name or "display" in name or "body" in name:
            continue
        if name not in out:
            out[name] = val
    return out


def extract_font_overrides(spec_text: str) -> Dict[str, str]:
    """{--sx-font-heading/body: 'Family'} from the spec's font section.
    Heuristic: the first whitelisted family on a display/headline line
    is the heading face; the first on a body line is the body face."""
    out: Dict[str, str] = {}
    for line in (spec_text or "").splitlines():
        low = line.lower()
        m = _FONT_RE.search(line)
        if not m:
            continue
        fam = m.group(0)
        if ("display" in low or "headline" in low) \
                and "--sx-font-heading" not in out:
            out["--sx-font-heading"] = fam
        elif ("body" in low or "copy" in low) \
                and "--sx-font-body" not in out:
            out["--sx-font-body"] = fam
    return out


def spec_override_css(spec_text: str) -> str:
    """The late-cascade override block, or '' when the spec declares
    nothing usable. Also retires the legacy signature-underline chrome
    — the spec owns the page's signature now."""
    colors = extract_token_overrides(spec_text)
    fonts = extract_font_overrides(spec_text)
    if not colors and not fonts:
        return ""
    decls = [f"{k}:{v}" for k, v in colors.items()]
    for tok, fam in fonts.items():
        decls.append(f"{tok}:'{fam}',sans-serif")
    return (
        "<style id=\"sx-spec-overrides\">/* the approved spec's tokens — "
        "installed last so they win every cascade */\n"
        ":root{" + ";".join(decls) + "}\n"
        "body[class*=\"sx-sig-\"] .sxm-reveal h2::after{content:none!important;"
        "display:none!important}\n"
        "</style>")


def _font_link(fonts: Dict[str, str]) -> str:
    fams = sorted({f for f in fonts.values()})
    if not fams:
        return ""
    spec = "&family=".join(
        f.replace(" ", "+") + ":wght@300;400;600;700;800;900" for f in fams)
    return (f'<link rel="stylesheet" '
            f'href="https://fonts.googleapis.com/css2?family={spec}'
            f'&display=swap">')


def apply_spec_overrides(html: str, spec_text: str) -> str:
    """Inject the spec's token overrides (+ font links) before </head>.
    Fail-open: any problem returns the html untouched."""
    try:
        block = spec_override_css(spec_text)
        if not block or "</head>" not in html:
            return html
        inject = _font_link(extract_font_overrides(spec_text)) + block
        return html.replace("</head>", inject + "</head>", 1)
    except Exception as e:
        logger.warning(f"[spec] override injection skipped: {e}")
        return html


def _site_row(business_id: str):
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=id,site_config&limit=1") or []
    return rows[0] if rows else None


def get_spec(business_id: str) -> Optional[Dict[str, Any]]:
    row = _site_row(business_id)
    if not row:
        return None
    spec = (row.get("site_config") or {}).get("design_spec")
    return spec if isinstance(spec, dict) and spec.get("text") else None


def save_spec(business_id: str, text: str,
              status: str = "draft") -> Optional[Dict[str, Any]]:
    """Persist the spec document. Bumps revision when one exists."""
    import sb_clients
    row = _site_row(business_id)
    if not row:
        return None
    cfg = dict(row.get("site_config") or {})
    prior = cfg.get("design_spec") if isinstance(cfg.get("design_spec"), dict) else {}
    spec = {
        "text": text[:SPEC_MAX_CHARS],
        "status": status,
        "authored_at": datetime.now(timezone.utc).isoformat(),
        "model": _model(),
        "revision": int(prior.get("revision") or 0) + 1,
    }
    cfg["design_spec"] = spec
    sb_clients.sb_patch_as_service(
        f"/business_sites?id=eq.{row['id']}", {"site_config": cfg})
    return spec


def set_status(business_id: str, status: str) -> Optional[Dict[str, Any]]:
    import sb_clients
    row = _site_row(business_id)
    if not row:
        return None
    cfg = dict(row.get("site_config") or {})
    spec = cfg.get("design_spec")
    if not isinstance(spec, dict) or not spec.get("text"):
        return None
    spec = dict(spec)
    spec["status"] = status
    cfg["design_spec"] = spec
    sb_clients.sb_patch_as_service(
        f"/business_sites?id=eq.{row['id']}", {"site_config": cfg})
    return spec


def approved_spec_text(business_id: str) -> str:
    """The approved document, or '' — compose_site's one-line read."""
    spec = get_spec(business_id)
    if spec and spec.get("status") == "approved":
        return str(spec.get("text") or "")
    return ""
