# design_coach.py
# ─────────────────────────────────────────────────────────────────────
# THE DESIGN COACH (2026-07-25, Kevin's ruling: "turn this into a
# design coach experience... like the strategy coach... the full
# experience").
#
# The discovery system's CONVERSATIONAL door. The compressed form
# collected facts; the coach extracts taste, story, and conviction the
# way a senior creative director does — one question at a time, real
# follow-ups, their words mirrored back — and every learned detail
# lands in the SAME discovery dossier with provenance 'asked' (the
# strongest material the Director can receive).
#
# Architecture rulings:
#   - NOT a chief_chat mode. A dedicated /composer/coach/* door means
#     no injector gating to leak (#153's class is structurally
#     impossible here), no action-tag parsing, and a strict JSON turn
#     contract validated server-side.
#   - STATELESS turns: the frontend carries the transcript; the
#     backend carries the truth (dossier + business facts). Every turn
#     re-reads what is KNOWN so the coach never re-asks (Kevin's
#     standing rule; the prefill-signals discipline).
#   - Salvaged from the Style Interview (now retired): the creative
#     spark (metaphor / surprise / remember / tension) and the story
#     walkthrough (origin / craft / proof / voice / atmosphere) — the
#     best questions it had, asked as dialogue instead of form steps.
#   - Every save rides discovery.apply_practitioner_patch — one
#     dossier, one provenance vocabulary, zero new storage.
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import llm_call
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("design_coach")

# 2026-10-03: 1400 → 2400. Opus 5.5 thinks a little before each turn
# (77-158 tokens in a probe) and thinking counts against this cap; the
# brief turn (reflect_back + saves) is the longest reply. Unused room
# costs nothing.
COACH_MAX_TOKENS = 2400
COACH_TEMPERATURE = 0.7
MAX_TURNS = 60          # transcript cap (user+coach messages)
MAX_MSG_CHARS = 1200    # per-message cap before the prompt

# The session's territory — the coach walks these stations in spirit,
# not as a rigid script. The frontend renders them as the thread.
STATIONS = ("welcome", "world", "story", "taste", "signature",
            "truth", "brief")

_SYSTEM = """You are THE DESIGN COACH inside the Solutionist System — a warm, sharp senior creative director sitting down with a business owner to draw out everything a designer needs to make their site unmistakably THEIRS. You are having a real conversation, not administering a form.

HOW YOU TALK (the coaching craft):
- ONE question at a time. Never a list of questions. Short messages — two or three sentences, then the question.
- FOLLOW UP on what they actually said. Mirror their exact words back ("you said 'it should feel like a homecoming' — tell me more about that"). The second question on a topic is where the gold is.
- Ask about their WORLD, never about design. "Walk me into your shop — what do I see first? what's playing?" beats "what's your aesthetic?" They answer in materials, light, and sound; the designer translates.
- Hunt STORIES and REACTIONS: what clients say when they walk in, the work they're proudest of, the site that made them jealous, what would make them cringe. Stories become copy; cringes become bans.
- Plain language always. Never say motif, palette, typography, hierarchy. Say "the one thing people should screenshot", "the colors that feel like you", "how loud should it read".
- YOUR LANE IS THE BRAND, NOT THE BUSINESS PLAN (the owner's ruling: people must FEEL the difference from the strategy coach). The strategy coach owns audience, offers, pricing, and goals — you NEVER ask those. Every question you ask is about what things LOOK, SOUND, and FEEL like: rooms, light, materials, textures, the colors they reach for, what plays in the background, the piece of work they'd frame, what clients SAY out loud. When a business fact matters, pull it from KNOWN CONTEXT and react to it like a director ("you work with barbers and churches — so chrome, neon, and stained-glass light are already in your world"). The test: if a question could appear in a business-plan interview, it is the wrong question — ask the sensory version instead ("who's your audience?" becomes "when your favorite client walks in, what do they see first?").
- Warm, direct, a little playful. Celebrate specific answers ("THAT — 'installed once, worn for years' — that's a headline"). Push politely past vague ones ("'professional' tells me nothing about YOU — what would your best client say?").

THE OPENING (the first turn of a session — there is no transcript yet):
Greet them like a person walking into your studio, BY NAME when the known context carries one (the business owner's first name; the business name otherwise). One warm line that proves you already know them ("I've seen the Glow Up work — you don't design small"). Then set the frame in one sentence: this is a conversation, not a form; they talk, you listen, and their site gets designed from what they say. Then ONE soft opening question about their world. Never open with a list, a menu of options, or "how can I help".

THE TERRITORY (walk it naturally; skip what's already known; follow heat when they light up):
1. world — their physical trade: the room, materials, light, sounds, tools. This is where their real palette and texture live.
2. story — origin (how it started), craft (what nobody guesses it takes), proof (proudest win), voice (what customers say walking away), atmosphere (the place it feels like).
3. taste — reactions, not vocabulary: this-or-that pairs (use the "pair" field), the one site/brand they admire and WHY in their words, what they'd never want ("cringe" answers — save these as bans).
4. signature — "if a visitor screenshots ONE moment on your page, what is it?" Push until it's concrete.
5. truth — real numbers they're proud of (years, clients, reviews) WITH where each comes from; the one action a visitor should take. THE WORKING DOORS belong here too: when KNOWN CONTEXT lists CONNECTED SYSTEMS (booking, store), confirm each in ONE question pre-filled from that truth ("Booking is live with your services. Should the site carry a Book button front and center?") and save the answer. Never ask about a door the context doesn't list, and never re-explain what a door is — they built it.
6. brief — when the territory is covered (or they're done), reflect the whole session back as a short vivid summary they can confirm.

NEVER RE-ASK what the KNOWN CONTEXT below already contains — reference it instead ("I know you work with coaches and barbers — who's the one client you'd clone?"). If the context shows brand colors or images, react to them like a director would.

SAVING (the whole point — capture as you go):
Every turn, extract anything learned into "saves". Use these dossier sections/fields:
- identity: one_liner, primary_action, brand_persona (list of up to 3 words), first_3s_feel
- world: room, materials, light, sounds (free text, their words)
- story: origin, craft, proof, voice, atmosphere
- taste: each answered pair saved as its OWN field (field is one of ground/density/carrier/edges/era/tone/motion, value is the chosen word); plus admired (what and why, one string) and bans (the cringe answers, one string or list); plus THE GALLERY PICKS: look (the look KEY they tapped, e.g. "neon"), layout (the page layout they tapped, saved without its page- prefix, e.g. "editorial"), motion (the motion key). THE PICK BINDS: a tapped card arrives as a message like "Neon, that's the one." Save it that same turn as {"section": "taste", "field": "look", "value": "neon"}; the build reads this field and speaks that language, so a pick that is not saved is a pick that is lost.
- signature: moment (their words), sharpened (your one-line phrasing of it)
- taste (THE CONCEPT PICK): concept (the card KEY they tapped: plain, signature, world-offer or world-site), concept_idea (the idea in one line, your pitch or their correction of it), concept_offer (when world-offer: the offer's name, from KNOWN CONTEXT or their words). Save all that apply the same turn they tap.
- truth: proven_stats (value is a list of {label, value, proof} objects); offers (what they sell, a list of {name, price, duration, note} objects, each only as they said it: never a price or a length they did not say); hours (when they are open, one line in their words)
- capabilities: booking, store (value "on" or "off" — the owner's answer to whether the SITE carries that door)
Save the practitioner's OWN PHRASING in values — verbatim quotes are design material. Only save what THIS turn established. Empty saves list is fine.

OUTPUT — STRICT JSON, nothing else:
{
  "reply": "your next message to them (plain text, no markdown headers)",
  "chips": ["up to 4 short tap-to-answer suggestions", "..."],        // optional
  "pair": {"key": "ground", "a": "Dark and moody", "b": "Light and airy"},  // optional, when asking a this-or-that
  "gallery": {"kind": "looks", "options": ["<3 to 6 look keys, chosen for THIS business>"]},  // optional, see THE GALLERIES
  "ask": "photos",   // optional — the platform shows an upload card; ONLY when the context says NO PHOTOS YET, and only once
  "saves": [{"section": "story", "field": "voice", "value": "..."}],
  "stage": "world|story|taste|signature|truth|brief",
  "done": false,
  "reflect_back": ["6-10 short vivid lines summarizing the session"]   // ONLY with stage "brief"
}
THE GALLERIES (show, then ask — the Claude Design pattern): when the conversation reaches a LOOK, LAYOUT, or MOTION choice, set "gallery" instead of "pair" — the platform renders each option as a small designed card in the option's own style, tinted with their brand color, and their tap arrives as an ordinary message. Use ONLY these kinds and keys:
- kind "looks" (the design language — the platform shows each as a real full-page design the system can build). The keys, what each is, and who it sings for:
{LOOKS_CATALOG}
- kind "page" (the PAGE LAYOUT: how the whole site is put together; the platform draws each as a wireframe, marks the best fit Recommended and writes each card's reason, so never describe them in words). Keys are page- plus a layout: page-split, page-editorial, page-fullscreen, page-statement, page-grid, page-magazine, page-bento, page-showcase, page-story, page-asymmetric, page-sidebar, page-minimal. Show it ONCE, in the taste station right after the look is chosen: the first three from KNOWN CONTEXT's LAYOUTS THAT FIT THIS BUSINESS, in that order. A layout the material cannot carry is never offered.
- kind "concept" (how far the site's idea goes; the platform shows each as a real rendering of one section at that setting). Keys: plain (no concept: clear, calm, nothing renamed), signature (one object carries one moment, the rest stays plain), world-offer (the idea runs one offer page, a course or a launch, while the home stays calm), world-site (the idea runs the whole site). Add "notes": {"<key>": "one line, for THIS business"} so each card carries its pitch ("signature": "your price list as the felt letterboard on your wall"; "world-offer": "your six-week course as a college semester"). Show it ONCE, in the signature station, after the look is chosen. Put KNOWN CONTEXT's CONCEPT DEFAULT first and say it is the usual choice for their kind of business; offer world-site only alongside world-offer. Plain is always one of the cards. Never pick for them.
- kind "motion" (how the page moves): kinetic-hero (the headline arrives line by masked line), the-thread (one drawn line walks the page and lights each section), depth (layers drift at different speeds as you scroll), quiet (almost still; one soft reveal), marquee (one band of the promise scrolls forever, everything else still), unfold (each section unfolds like paper as you reach it, once).
Offer 3 to 6 looks, exactly 3 page layouts, and 2 to 4 motions, chosen for THIS business — never all eleven, never a default trio.
CHOOSING THE LOOKS: the KNOWN CONTEXT carries LOOKS THAT FIT THIS BUSINESS, ranked by the platform from their trade, their photos and their words. Offer from the top of that list, best fit first, and include one that is a real alternative (a different ground or a different temperature), never six shades of the same thing. Keep the reply ONE short question ("Which of these feels like walking into your shop?") and never describe the options in words: the cards do that. If they say none of them fit, show "looks" ONE more time with the keys you have not shown yet; page layouts and motion are shown at most once per session (when none of the three layouts fit, show the next three from the list one more time).

Rules: chips are answers THEY might tap, not questions. Use "pair" at most every third turn. When stage is "brief", "reply" asks them to confirm the reflect_back (or correct anything), and "done" stays false until they confirm; after their confirmation, respond with done true and a warm send-off saying the Director will draft their blueprint from this.
NEVER write sentences spliced with dashes in reply or saves — use periods, commas, or colons (the owner's standing grammar rule)."""


def _looks_catalog() -> str:
    """The coach's menu of looks, generated from design_languages so the
    coach can never offer a look the builder cannot build (the moves
    lesson of 2026-08-09, applied to the gallery). One line per look:
    key, what it is, who it sings for."""
    try:
        import design_languages
        lines = []
        for key, v in design_languages.LANGUAGES.items():
            lines.append(f"  {key}: {v.get('believes', '').rstrip('.')}. "
                         f"Sings for {v.get('sings', '')}.")
        return "\n".join(lines)
    except Exception:
        return "  mural, ledger, monograph, broadsheet, signal, atelier, neon, hearth, glass, runway, arena"


_SYSTEM = _SYSTEM.replace("{LOOKS_CATALOG}", _looks_catalog())


def suggest_looks(business_type: str, photos: int = 0,
                  prefs: Optional[Dict[str, Any]] = None,
                  words: str = "") -> List[Dict[str, str]]:
    """LOOKS THAT FIT THIS BUSINESS (2026-09-04): a ranked shortlist for
    the coach to offer from, so the gallery is chosen for the trade in
    front of it rather than copied from a worked example. Evidence:
    the rubric's own pick (the same one the build would make), then
    each look's 'sings for' and 'fails' notes scored against the
    business type, the boldness and type answers, and the owner's own
    words. Deterministic, no model call."""
    try:
        import design_languages as dl
    except Exception:
        return []
    prefs = prefs if isinstance(prefs, dict) else {}
    btype = (business_type or "").lower()
    text = " ".join([btype, str(prefs.get("boldness") or ""),
                     str(prefs.get("type_personality") or ""),
                     (words or "").lower()])
    tokens = {t for t in re.findall(r"[a-z]{3,}", text)}
    ctx = {"business": {"type": btype}, "site_prefs": prefs,
           "gallery": [{}] * max(0, int(photos or 0)), "offerings": [],
           "testimonials": []}
    try:
        rubric_key, _ = dl.rubric_select(ctx)
    except Exception:
        rubric_key = None
    scored = []
    for key, v in dl.LANGUAGES.items():
        sings = set(re.findall(r"[a-z]{3,}", str(v.get("sings") or "").lower()))
        fails = set(re.findall(r"[a-z]{3,}", str(v.get("fails") or "").lower()))
        score = 0.0
        score += 2.0 * len(tokens & sings)
        score -= 2.0 * len(tokens & fails)
        if key == rubric_key:
            score += 4.0
        # photo evidence the sheets name in words
        if photos >= 4 and key in ("atelier", "monograph", "runway", "arena", "mural"):
            score += 1.0
        if photos == 0 and key in ("broadsheet", "ledger", "signal"):
            score += 1.0
        scored.append((score, key))
    scored.sort(key=lambda x: (-x[0], list(dl.LANGUAGES).index(x[1])))
    out = []
    for score, key in scored[:6]:
        why = "the build's own pick for this evidence" if key == rubric_key else               f"sings for {str(dl.LANGUAGES[key].get('sings') or '')[:70]}"
        out.append({"key": key, "why": why})
    return out


def looks_that_fit_block(business_type: str, photos: int = 0,
                         prefs: Optional[Dict[str, Any]] = None,
                         words: str = "") -> str:
    ranked = suggest_looks(business_type, photos, prefs, words)
    if not ranked:
        return ""
    return ("LOOKS THAT FIT THIS BUSINESS (ranked by the platform from their "
            "trade, photos and words; offer from the top, best fit first; the "
            "tail is the second round if none fit):\n"
            + "\n".join(f"- {r['key']}: {r['why']}" for r in ranked))


# ─── context assembly (what is already KNOWN — never re-ask) ─────────

def _photo_context(settings: Dict[str, Any]) -> List[str]:
    """THE PHOTO STATION (2026-08-28, build quality 2/6). MaCnificent Hair
    Co sat through a whole session and the build went out with ZERO
    photographs — the coach never knew, so it never asked, and the page
    shipped tinted boxes describing photos that were not there. The
    photo inventory the build will actually use is
    settings.media_library.gallery (+ the brand mark); the coach reads
    the same truth and asks ONCE, at the story stage, with an upload
    card the platform renders ("ask": "photos")."""
    st = settings if isinstance(settings, dict) else {}
    gal = ((st.get("media_library") or {}).get("gallery")) or []
    n = len([g for g in gal if isinstance(g, dict)
             and str(g.get("url") or "").strip()
             and g.get("show_on_website", True)])
    bk = st.get("brand_kit") or {}
    mark = bool(bk.get("logo_url") or (bk.get("assets") or {}).get("primary"))
    out = [f"PHOTOS ON FILE: {n} (the build's entire photo inventory) — "
           f"BRAND MARK: {'on file' if mark else 'none'}"]
    if n == 0:
        out.append(
            "NO PHOTOS YET: the site will be built WITHOUT photographs (a "
            "typographic page) unless they add some. ONCE, at the story "
            "stage, ask for photos of their finished work and set "
            "\"ask\": \"photos\" on that turn — the platform shows an upload "
            "card, the photos land in their library, and the build uses "
            "them. If they say not now, move on and never ask again this "
            "session.")
    return out


# THE PHOTO ASK, GUARANTEED (2026-10-03, the first live test): the quick
# session told the coach to ask for photos on the story turn when there
# are none, and it never did, so the site was built with none. A hand-
# build always asks. The server now sets "ask": "photos" itself, once per
# session, when the business has no photos and the coach did not.
# {business_id: {"photos": n, "asked": bool}}, written by _known_context.
_PHOTO_STATE: Dict[str, Dict[str, Any]] = {}


def _should_ask_photos(business_id: str, messages: List[Dict[str, str]],
                       turn: Dict[str, Any]) -> bool:
    st = _PHOTO_STATE.get(business_id)
    if not st or st.get("photos", 1) > 0 or st.get("asked"):
        return False
    if turn.get("ask") == "photos" or turn.get("done") or turn.get("gallery") \
            or turn.get("stage") == "brief":
        return False
    # The first turn after they have said anything (2026-10-03, the second
    # live test): a returning owner's session was two answers long, a
    # gallery and then the truth question, and waiting for a second
    # answer meant the brief came first and the ask never did.
    said = sum(1 for m in (messages or []) if m.get("role") == "user"
               and str(m.get("content") or "").strip())
    return turn.get("stage") == "story" or said >= 1


def _store_has_products(business_id: str) -> bool:
    """The store door is real only when the store page would show
    something: the same filter the public /store page applies (active,
    shown on the website). business_state hands every business with a
    site a store_url, products or not."""
    try:
        import sb_clients
        rows = sb_clients.sb_get_as_service(
            f"/products?business_id=eq.{business_id}&status=eq.active"
            "&display_on_website=eq.true&select=id&limit=1") or []
        return bool(rows)
    except Exception:
        return False


# THE PAGE LAYOUTS (2026-10-03, the hand-build plan): the rubric's ranking
# for this business, kept a few minutes so the turn that shows the cards
# writes their reasons and the Recommended mark from the same ranking the
# coach was given. {business_id: (monotonic, rows)}
_LAYOUT_RANK: Dict[str, Any] = {}
_LAYOUT_RANK_TTL_S = 600


def _layout_rank(business_id: str, biz: Optional[Dict[str, Any]],
                 dossier: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """site_layouts.rank for this business from a light context: its trade,
    its photos, its live offerings and products, and the dossier. Two small
    reads; fail-open to []."""
    if _site_layouts is None:
        return []
    import time
    import sb_clients
    st = (biz or {}).get("settings") or {}
    gal = ((st.get("media_library") or {}).get("gallery")) or []
    try:
        offerings = sb_clients.sb_get_as_service(
            f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
            "&select=id&limit=40") or []
    except Exception:
        offerings = []
    try:
        products = sb_clients.sb_get_as_service(
            f"/products?business_id=eq.{business_id}&status=eq.active"
            "&display_on_website=eq.true&select=id&limit=40") or []
    except Exception:
        products = []
    testimonials = ((st.get("website_content") or {}).get("testimonials")) or []
    ctx = {"business": {"type": str((biz or {}).get("business_type") or "")},
           "gallery": [g for g in gal if isinstance(g, dict)],
           "offerings": offerings if isinstance(offerings, list) else [],
           "testimonials": testimonials if isinstance(testimonials, list) else [],
           "store": {"enabled": bool(products), "items": products if isinstance(products, list) else []},
           "site": {"site_config": {"discovery_dossier": dossier or {}}}}
    try:
        import site_concept
        recent = site_concept.recent_layouts(business_id)
    except Exception:
        recent = []
    rows = _site_layouts.rank(_site_layouts.signals(ctx, recent))
    _LAYOUT_RANK[business_id] = (time.monotonic(), rows)
    return rows


def layouts_that_fit_block(rows: List[Dict[str, Any]], n: int = 6) -> str:
    if not rows or _site_layouts is None:
        return ""
    lines = ["LAYOUTS THAT FIT THIS BUSINESS (the page's structure, ranked by the platform "
             "from what it actually has; offer the first three as gallery kind \"page\", "
             "in this order):"]
    for r in rows[:n]:
        lines.append(f"- page-{r['key']}: {r['name']}. {_site_layouts.reason_line(r)}")
    return "\n".join(lines)


def _finish_page_gallery(gallery: Dict[str, Any], business_id: str) -> None:
    """The cards' reasons and the Recommended mark come from the rubric,
    not the model: the best-ranked option is Recommended, and each card
    says why it fits in the platform's own words."""
    if _site_layouts is None:
        return
    import time
    cached = _LAYOUT_RANK.get(business_id)
    rows = cached[1] if cached and time.monotonic() - cached[0] < _LAYOUT_RANK_TTL_S else []
    if not rows:
        return
    order = {f"page-{r['key']}": i for i, r in enumerate(rows)}
    by = {f"page-{r['key']}": r for r in rows}
    opts = [o for o in gallery.get("options") or [] if o in by]
    if not opts:
        return
    gallery["notes"] = {o: _site_layouts.reason_line(by[o]) for o in opts}
    gallery["recommended"] = min(opts, key=lambda o: order[o])


def _known_context(business_id: str) -> str:
    parts: List[str] = []
    _biz_row: Optional[Dict[str, Any]] = None
    _dossier: Optional[Dict[str, Any]] = None
    try:
        import sb_clients
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}"
            "&select=name,business_type,settings&limit=1") or []
        if rows:
            b = rows[0]
            _biz_row = b
            parts.append(f"BUSINESS: {b.get('name')} "
                         f"({b.get('business_type') or 'business'})")
            st = b.get("settings") or {}
            owner = str(st.get("owner_name") or st.get("owner") or "").strip()
            if owner:
                parts.append(f"THE OWNER'S NAME: {owner}")
            bk = st.get("brand_kit") or {}
            cols = bk.get("colors") or {}
            if cols:
                parts.append("BRAND COLORS ON FILE: "
                             + json.dumps(cols)[:200])
            parts.extend(_photo_context(st))
            _gal = ((st.get("media_library") or {}).get("gallery")) or []
            _PHOTO_STATE[business_id] = {
                "photos": len([g for g in _gal if isinstance(g, dict)
                               and str(g.get("url") or "").strip()
                               and g.get("show_on_website", True)]),
                "asked": False}
            prefs = st.get("site_prefs") or {}
            if prefs:
                parts.append("EARLIER STYLE ANSWERS (do not re-ask; "
                             "build on them): "
                             + json.dumps(prefs, ensure_ascii=False)[:900])
            try:
                import site_concept
                d_int = site_concept.default_intensity(str(b.get("business_type") or ""))
                parts.append(
                    f"CONCEPT DEFAULT FOR THIS BUSINESS: {d_int} (the platform's "
                    "default for their kind of business: plain for health, legal, "
                    "finance and therapy; signature for everyone else). World is "
                    "only ever their choice.")
            except Exception as e:
                logger.info(f"[coach] concept default skipped: {e}")
            try:
                gal = ((st.get("media_library") or {}).get("gallery")) or []
                fit = looks_that_fit_block(
                    str(b.get("business_type") or ""), len(gal),
                    prefs if isinstance(prefs, dict) else {},
                    json.dumps(st.get("brand_kit") or {})[:300])
                if fit:
                    parts.append(fit)
            except Exception as e:
                logger.info(f"[coach] looks-that-fit skipped: {e}")
    except Exception as e:
        logger.info(f"[coach] business context skipped: {e}")
    try:
        import discovery
        d = discovery.get_dossier(business_id)
        _dossier = d if isinstance(d, dict) else None
        if isinstance(d, dict) and business_id in _PHOTO_STATE:
            _PHOTO_STATE[business_id]["asked"] = bool(
                (d.get("session") or {}).get("photos_asked"))
        digest = discovery.dossier_digest(d) if d else ""
        if digest:
            parts.append("THE DOSSIER SO FAR (already known — reference, "
                         "never re-ask):\n" + digest[:2400])
    except Exception as e:
        logger.info(f"[coach] dossier context skipped: {e}")
    # THE WIRED-SITE CONTRACT (2026-07-26): mirror the platform's truth
    # about which doors are actually live, so the coach CONFIRMS the
    # site connections instead of asking blind — and never offers a
    # door the platform doesn't have.
    try:
        import offering_profiles
        state = offering_profiles.business_state(business_id)
        doors: List[str] = []
        if state.get("booking_enabled") and state.get("booking_url"):
            doors.append("BOOKING is LIVE — customers can book at "
                         + state["booking_url"])
        # THE EMPTY SHOP (2026-10-03, live test on Vertical Test Coach):
        # every business with a site gets a store_url, so the coach told
        # an owner with zero products "your store page is already live"
        # and asked twice whether to link it. The builder already refuses
        # this door when the shop is empty (builder_v2._store_has_products);
        # the coach now asks only about a store with something in it.
        if state.get("store_url") and _store_has_products(business_id):
            doors.append("STORE page exists at " + state["store_url"])
        if doors:
            parts.append("CONNECTED SYSTEMS (the platform's truth — "
                         "confirm which of these the SITE should carry; "
                         "never offer a door not listed here):\n"
                         + "\n".join("- " + s for s in doors))
    except Exception as e:
        logger.info(f"[coach] connected-systems context skipped: {e}")
    try:
        block = layouts_that_fit_block(_layout_rank(business_id, _biz_row, _dossier))
        if block:
            parts.append(block)
    except Exception as e:
        logger.info(f"[coach] layouts-that-fit skipped: {e}")
    return "\n\n".join(parts) or "(nothing known yet — a fresh start)"


# THE QUICK SESSION (2026-10-03). Kevin: when someone asks Chief for a
# site, Chief brings the coach into the chat instead of building from
# nothing (the blueprint exists so a site never comes out generic). A
# practitioner who asked for a site from their phone came for a site, not
# a sit-down: the quick session asks the few questions that move the
# design most and leaves the whole territory one "tell me more" away.
SESSION_MODES = ("deep", "quick")

QUICK_SESSION = (
    "QUICK SESSION. They asked Chief for a site from the chat, and Chief "
    "brought you in. Respect their time: about five questions in all, then "
    "the brief.\n"
    "- One WORLD question: the room, the light, the sounds.\n"
    "- One STORY question: the work they are proudest of, or what clients "
    "say walking out. When the context says NO PHOTOS YET, this is the turn "
    "that asks for photos (\"ask\": \"photos\").\n"
    "- The LOOKS gallery.\n"
    "- The PAGE gallery (kind \"page\": the first three LAYOUTS THAT FIT THIS "
    "BUSINESS), right after the look: how the whole site is put together.\n"
    "- The CONCEPT gallery, right after the page layout.\n"
    "- One question about what they would never want (save it as bans).\n"
    "- One TRUTH question: what people buy from them, what each costs, and "
    "when they are open. Save what they say as truth offers and truth hours, "
    "in their words. Skip it when the KNOWN CONTEXT already lists their "
    "offers with prices.\n"
    "Skip any of these the KNOWN CONTEXT already answers, and never pad to "
    "reach five. No this-or-that pairs, hero shapes or motion in a quick "
    "session unless they ask for more. If they want to go deeper, follow "
    "them: the whole territory is open the moment they ask. Then the brief: "
    "reflect_back and their confirmation, as always. The send-off says "
    "Chief has their blueprint next, back in the chat.")


def session_mode(raw: Any) -> str:
    """'quick' or 'deep' (the default, the full sit-down)."""
    m = str(raw or "").strip().lower()
    return m if m in SESSION_MODES else "deep"


def build_turn_prompt(business_id: str,
                      messages: List[Dict[str, str]],
                      mode: str = "deep") -> List[Dict[str, str]]:
    """The transcript as ladder messages. Two disciplines:

    1. KNOWN CONTEXT rides the first user message (system stays
       constant and cache-friendly).
    2. FORMAT MIRROR (the lost-thread bug, 2026-07-25): prior coach
       turns are re-wrapped in their JSON envelope. The frontend
       stores plain reply text; feeding that back verbatim showed the
       model a transcript of itself speaking PROSE, so by turn two it
       mirrored the prose and dropped the JSON contract. The model
       must only ever see itself speaking JSON."""
    trimmed = [
        {"role": ("assistant" if m.get("role") == "assistant" else "user"),
         "content": str(m.get("content") or "")[:MAX_MSG_CHARS]}
        for m in (messages or [])[-MAX_TURNS:]
        if str(m.get("content") or "").strip()
    ]
    known = _known_context(business_id)
    quick = ("\n\n" + QUICK_SESSION) if session_mode(mode) == "quick" else ""
    lead = ("KNOWN CONTEXT (the platform already knows this — never "
            "re-ask any of it):\n" + known + quick
            + "\n\nRun the session. EVERY reply is the strict JSON of "
              "the contract — no prose outside the JSON, ever.")
    out: List[Dict[str, str]] = [{"role": "user", "content": lead}]
    for m in trimmed:
        if m["role"] == "assistant":
            out.append({"role": "assistant",
                        "content": json.dumps({"reply": m["content"]},
                                              ensure_ascii=False)})
        else:
            out.append({"role": "user", "content": m["content"]})
    # collapse any same-role neighbors (the API wants alternation)
    merged: List[Dict[str, str]] = []
    for m in out:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] += "\n\n" + m["content"]
        else:
            merged.append(dict(m))
    return merged


# ─── the turn contract ───────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)


# THE PICK BINDS (2026-09-04): a tapped gallery card is saved as the
# owner's own answer, by KEY, so design_languages.resolve can read it.
_PICK_FIELDS = {"look": "looks", "hero_shape": "layouts", "motion": "motion",
                "concept": "concept", "layout": "page"}
_PICK_KEYS = {
    "layouts": {"split-stage", "poster", "editorial", "exhibition",
                "monument", "corridor", "letter"},
    "motion": {"kinetic-hero", "the-thread", "depth", "quiet",
               "marquee", "unfold"},
    "concept": {"plain", "signature", "world-offer", "world-site"},
    # THE PAGE LAYOUTS (2026-10-03, the hand-build plan): site_layouts keys,
    # shown on cards as page-<key> and saved bare.
    "page": set(),
}
try:
    import site_layouts as _site_layouts
    _PICK_KEYS["page"] = set(_site_layouts.KEYS)
except Exception:          # the coach still runs without the library
    _site_layouts = None
_PAGE_CARD_KEYS = {f"page-{k}" for k in _PICK_KEYS["page"]}


def _normalize_concept(raw: Any) -> Optional[str]:
    """'World: one offer page, that's the one.' → world-offer. A bare
    'world' means the recommended form, the offer page (Kevin,
    2026-10-01: World lives on one offer page by default)."""
    t = str(raw or "").strip().lower()
    if t in _PICK_KEYS["concept"]:
        return t
    if "world" in t or "whole" in t or "immers" in t:
        if "whole" in t or "entire" in t or "everywhere" in t or "site" in t.replace("offer", ""):
            return "world-site"
        return "world-offer"
    if "signature" in t or "one object" in t:
        return "signature"
    if "plain" in t or "simple" in t or "clean" in t or "no concept" in t:
        return "plain"
    return None


def _normalize_pick(field: str, raw: Any) -> Optional[str]:
    """'Neon, that's the one.' / 'The Poster' / 'neon' → the key, or None."""
    kind = _PICK_FIELDS.get(field)
    if not kind:
        return None
    if kind == "concept":
        return _normalize_concept(raw)
    if kind == "page":
        if _site_layouts is None:
            return None
        text = re.sub(r"^\s*page-", "", str(raw or "").strip(), flags=re.IGNORECASE)
        text = re.sub(r"[,.!].*$", "", text).strip()
        return _site_layouts.normalize(text)
    keys = _look_keys() if kind == "looks" else _PICK_KEYS[kind]
    text = str(raw or "").strip().lower()
    text = re.sub(r"[,.!'’].*$", "", text).strip()          # drop the sentence tail
    bare = re.sub(r"^(the|a)\s+", "", text)
    for t in (text, bare):                                   # "the thread" is a key; "the poster" is not
        cand = t.replace(" ", "-")
        if cand in keys:
            return cand
        for k in keys:
            if k.replace("-", " ") == t:
                return k
    return None


def _look_keys() -> set:
    try:
        import design_languages
        return set(design_languages.LANGUAGES.keys())
    except Exception:
        return {"mural", "monograph", "ledger", "broadsheet", "signal",
                "atelier", "neon", "hearth", "glass", "runway", "arena"}
_ALLOWED_SECTIONS = {"identity", "world", "story", "taste", "signature",
                     "truth", "capabilities"}

# capabilities saves are a contract, not prose: value normalizes to
# on/off; anything unrecognizable is dropped rather than guessed.
_CAPABILITY_FIELDS = {"booking", "store"}
_CAP_ON = {"on", "yes", "true", "1"}
_CAP_OFF = {"off", "no", "false", "0"}


def parse_turn(raw: str) -> Optional[Dict[str, Any]]:
    """Tolerant strict-JSON parse of a coach turn. None = unusable."""
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
    if not isinstance(out, dict) or not str(out.get("reply") or "").strip():
        return None
    out["reply"] = str(out["reply"]).strip()
    out["stage"] = out.get("stage") if out.get("stage") in STATIONS else "world"
    out["done"] = bool(out.get("done"))
    chips = out.get("chips")
    out["chips"] = [str(c)[:80] for c in chips[:4]] \
        if isinstance(chips, list) else []
    pair = out.get("pair")
    out["pair"] = pair if (isinstance(pair, dict) and pair.get("a")
                           and pair.get("b")) else None
    g = out.get("gallery")
    _G_KINDS = {
        "looks": _look_keys(),
        "layouts": {"split-stage", "poster", "editorial", "exhibition",
                    "monument", "corridor", "letter"},
        "motion": {"kinetic-hero", "the-thread", "depth", "quiet",
                   "marquee", "unfold"},
        "concept": set(_PICK_KEYS["concept"]),
        "page": set(_PAGE_CARD_KEYS),
    }
    out["gallery"] = None
    if isinstance(g, dict) and g.get("kind") in _G_KINDS:
        opts = [str(o) for o in (g.get("options") or [])
                if str(o) in _G_KINDS[g["kind"]]]
        if len(opts) >= 2:
            cap = 6 if g["kind"] == "looks" else 4
            out["gallery"] = {"kind": g["kind"], "options": opts[:cap]}
            notes = g.get("notes")
            if isinstance(notes, dict):
                kept = {str(k): str(v).strip()[:90] for k, v in notes.items()
                        if str(k) in out["gallery"]["options"] and str(v or "").strip()}
                if kept:
                    out["gallery"]["notes"] = kept
    rb = out.get("reflect_back")
    out["reflect_back"] = [str(x)[:200] for x in rb[:12]] \
        if isinstance(rb, list) else []
    out["ask"] = "photos" \
        if str(out.get("ask") or "").strip().lower() == "photos" else None
    saves = out.get("saves")
    clean: List[Dict[str, Any]] = []
    for s in (saves if isinstance(saves, list) else []):
        if not isinstance(s, dict):
            continue
        sec = str(s.get("section") or "").strip()
        fld = str(s.get("field") or "").strip()
        if sec not in _ALLOWED_SECTIONS or not fld \
                or s.get("value") in (None, ""):
            continue
        if sec == "capabilities":
            word = str(s["value"]).strip().lower()
            if fld not in _CAPABILITY_FIELDS:
                continue
            if word in _CAP_ON:
                s = {"section": sec, "field": fld, "value": "on"}
            elif word in _CAP_OFF:
                s = {"section": sec, "field": fld, "value": "off"}
            else:
                continue
        if sec == "taste" and fld in _PICK_FIELDS:
            key = _normalize_pick(fld, s["value"])
            if not key:
                continue
            s = {"section": sec, "field": fld, "value": key}
        clean.append({"section": sec, "field": fld, "value": s["value"]})
    out["saves"] = clean[:10]
    return out


def apply_saves(business_id: str, saves: List[Dict[str, Any]]) -> int:
    """Every save lands in THE dossier with provenance 'asked'. Returns
    how many applied. apply_practitioner_patch is pure — read, merge,
    persist here. proven_stats ride the truth door's list shape."""
    if not saves:
        return 0
    try:
        import discovery
    except Exception as e:
        logger.warning(f"[coach] discovery unavailable, saves lost: {e}")
        return 0
    patch: Dict[str, Any] = {}
    n = 0
    for s in saves:
        if s["section"] == "truth" and s["field"] == "proven_stats":
            stats = s["value"] if isinstance(s["value"], list) else [s["value"]]
            patch.setdefault("truth", {})["proven_stats"] = [
                st for st in stats if isinstance(st, dict)]
        elif s["section"] == "truth" and s["field"] == "offers":
            vals = s["value"] if isinstance(s["value"], list) else [s["value"]]
            patch.setdefault("truth", {}).setdefault("offers", []).extend(
                v for v in vals if isinstance(v, (dict, str)))
        elif s["section"] == "truth" and s["field"] == "hours":
            patch.setdefault("truth", {})["hours"] = str(s["value"])
        else:
            patch.setdefault(s["section"], {})[s["field"]] = {
                "value": s["value"], "source": "asked"}
        n += 1
    try:
        # discovery.answer is the write engine: load → merge (pure
        # apply_practitioner_patch) → persist.
        if discovery.answer(business_id, patch) is None:
            logger.warning("[coach] dossier patch found no site row")
            return 0
    except Exception as e:
        logger.warning(f"[coach] dossier patch failed: {e}")
        return 0
    return n


def _persist_session(business_id: str, messages: List[Dict[str, str]],
                     turn: Dict[str, Any]) -> None:
    """EXIT-SAFE PROGRESS (Kevin's ruling: "if we exit out it saves"):
    after every successful turn the whole conversation rides the
    dossier — transcript, stage, and the last turn's interactive
    pieces — so closing the session (or the laptop) loses nothing.
    The frontend resumes from dossier.session on reopen; finish
    clears it. Best-effort: a persist failure never fails the turn.
    dossier_digest whitelists sections, so the transcript never
    bloats the Director's prompt."""
    try:
        import discovery
        from datetime import datetime, timezone
        d = discovery.get_dossier(business_id) or discovery._empty_dossier()
        transcript = [
            {"role": ("assistant" if m.get("role") == "assistant"
                      else "user"),
             "content": str(m.get("content") or "")[:MAX_MSG_CHARS]}
            for m in (messages or [])[-MAX_TURNS:]
            if str(m.get("content") or "").strip()
        ]
        transcript.append({"role": "assistant", "content": turn["reply"]})
        asked = bool((d.get("session") or {}).get("photos_asked")) \
            or turn.get("ask") == "photos"
        d["session"] = {
            "photos_asked": asked,
            "messages": transcript[-MAX_TURNS:],
            "stage": turn.get("stage"),
            "last": {k: turn.get(k) for k in
                     ("chips", "pair", "gallery", "reflect_back")},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        discovery.save_dossier(business_id, d)
    except Exception as e:
        logger.info(f"[coach] session persist skipped (non-fatal): {e}")


# ─── the calls ───────────────────────────────────────────────────────

def _model() -> str:
    m = (os.environ.get("DESIGN_COACH_MODEL") or "").strip()
    if m:
        return m
    try:
        import canvas
        return canvas._model()
    except Exception:
        # Only if canvas cannot be imported. Sonnet 4.5 retires 2026-11-30.
        return "claude-sonnet-5-5"


def run_turn(business_id: str,
             messages: List[Dict[str, str]],
             mode: str = "deep") -> Dict[str, Any]:
    """One coach turn: transcript in → {reply, chips, pair, saves_applied,
    stage, done, reflect_back} out. Loud failures — the frontend shows a
    retry, never a blank. mode 'quick' is the session Chief opens from the
    chat (QUICK_SESSION); anything else is the full sit-down."""
    try:
        from anthropic import Anthropic
        import model_ladder
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return {"error": "coach unavailable (no key)"}
        client = llm_call.sdk_client(key=key, timeout=120.0, max_retries=1)
        turn_msgs = build_turn_prompt(business_id, messages,
                                      mode=session_mode(mode))

        def _do(model: str, max_tokens: int, timeout: float):
            return client.messages.create(
                model=model, max_tokens=max_tokens, system=_SYSTEM,
                messages=turn_msgs, timeout=max(timeout, 120.0),
                **model_ladder.sampling_kwargs(model, COACH_TEMPERATURE))

        msg, used_model = model_ladder.call_with_ladder(
            _do, model=_model(), task="design_coach",
            business_id=business_id, max_tokens=COACH_MAX_TOKENS)
        try:
            from api_usage_logger import log_api_usage_sync
            u = getattr(msg, "usage", None)
            log_api_usage_sync(
                endpoint="/composer/coach/turn", model=used_model or "",
                input_tokens=getattr(u, "input_tokens", 0) or 0,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                business_id=business_id, task_type="design_coach")
        except Exception:
            pass
        raw = "".join(b.text for b in msg.content
                      if getattr(b, "type", None) == "text")
        turn = parse_turn(raw)
        if not turn:
            return {"error": "the coach lost the thread — try again"}
        if (turn.get("gallery") or {}).get("kind") == "page":
            _finish_page_gallery(turn["gallery"], business_id)
        if _should_ask_photos(business_id, messages, turn):
            turn["ask"] = "photos"
        if turn.get("ask") == "photos" and business_id in _PHOTO_STATE:
            _PHOTO_STATE[business_id]["asked"] = True
        applied = apply_saves(business_id, turn.pop("saves", []))
        turn["saves_applied"] = applied
        _persist_session(business_id, messages, turn)
        return turn
    except Exception as e:
        logger.error(f"[coach] turn failed: {type(e).__name__}: {e}")
        return {"error": "the coach is unavailable right now — try again"}


def finish_session(business_id: str) -> Dict[str, Any]:
    """The session's close: derive the taste profile from everything
    gathered, stamp the session complete, and return the digest the
    Blueprint panel opens with."""
    out: Dict[str, Any] = {"ok": True}
    try:
        import discovery
        # the session is complete — clear the resume transcript so the
        # NEXT session starts fresh (the dossier keeps every answer)
        try:
            d = discovery.get_dossier(business_id)
            if d and d.pop("session", None) is not None:
                discovery.save_dossier(business_id, d)
        except Exception:
            pass
        try:
            derived = discovery.derive_taste(business_id)
            out["derived"] = bool(derived)
        except Exception as e:
            logger.info(f"[coach] derive skipped: {e}")
            out["derived"] = False
        try:
            discovery.answer(business_id, {
                "meta": {"coach_session_completed": {
                    "value": True, "source": "asked"}}})
        except Exception:
            pass
        d = discovery.get_dossier(business_id)
        out["digest"] = discovery.dossier_digest(d) if d else ""
    except Exception as e:
        logger.warning(f"[coach] finish degraded: {e}")
        out["digest"] = ""
    return out
