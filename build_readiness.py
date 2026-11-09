"""
build_readiness.py — what the next build will and will not have
(2026-08-28, build quality 5/6).

Kevin revised his Blueprint thirteen times before approving it; a first-
time practitioner approves revision 1. MaCnificent Hair Co approved a
Blueprint for a page that then shipped with zero photographs, no brand
mark, and a shop with nothing in it — every one of those gaps was already
in the dossier (`gaps`) and the context (photo count, offerings) before
the approve button was pressed. Nothing said so.

This is the "before you approve" pass: a pure read of the composer
context into plain lines a practitioner can act on, plus revision chips
that prefill the Blueprint's revise notes. No model call, no writes.
"""
import os
from typing import Any, Dict, List, Optional


# PHOTOS FIRST (2026-11-08). Real photos are the one number that separates both
# hand-built pages (14 and 4) from both builder pages (0 and 0) we measured. The
# Coach asks once and the card lists the gap, and a busy owner skips both, so a
# trade whose people or work are its proof gets one real stop at Build it. It is
# a stop, never a wall: building without photos stays one tap away.
PHOTOS_WANTED = 6


def photos_first_on() -> bool:
    return (os.environ.get("SITE_PHOTOS_FIRST") or "off").strip().lower() in ("on", "1", "true", "yes")


def _proof_is_visible(btype: str) -> bool:
    import site_layouts as sl
    return any(rx.search(btype or "") for rx in (
        sl._VISUAL_TRADE_RE, sl._PLACE_TRADE_RE, sl._GATHERING_TRADE_RE, sl._APPOINTMENT_TRADE_RE))


def photo_stop(ctx: Dict[str, Any], photos: int) -> Optional[Dict[str, int]]:
    """{have, want} when this build should stop and ask for photos, else None.
    Plain pages never stop: a law firm's page doesn't turn on its photos."""
    if not photos_first_on() or photos >= PHOTOS_WANTED:
        return None
    try:
        import site_concept
        # a failed read hides the owner's Plain choice, and it reads as empty
        site = ctx.get("site") if isinstance(ctx.get("site"), dict) else {}
        if not site_concept.enabled() or not isinstance(site.get("site_config"), dict):
            return None
        if site_concept.resolve(ctx).get("intensity") == "plain":
            return None
        btype = str((ctx.get("business") or {}).get("type") or "")
        return {"have": photos, "want": PHOTOS_WANTED} if _proof_is_visible(btype) else None
    except Exception:
        return None             # the card still lists the gap in words


def _n(xs: Any) -> int:
    return len(xs) if isinstance(xs, list) else 0


def spec_readiness(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """{photos, brand_mark, portrait, offerings, testimonials,
        session_done, gaps, notes[], chips[]} from a gather_context ctx."""
    ctx = ctx if isinstance(ctx, dict) else {}
    settings = ctx.get("settings") if isinstance(ctx.get("settings"), dict) else {}
    cfg = ((ctx.get("site") or {}).get("site_config") or {}) \
        if isinstance(ctx.get("site"), dict) else {}
    dossier = cfg.get("discovery_dossier") if isinstance(cfg.get("discovery_dossier"), dict) else {}
    gaps = [str(g) for g in (dossier.get("gaps") or []) if isinstance(g, str)]
    photos = _n(ctx.get("gallery"))
    bk = settings.get("brand_kit") if isinstance(settings.get("brand_kit"), dict) else {}
    brand_mark = bool(bk.get("logo_url") or (bk.get("assets") or {}).get("primary"))
    portrait = "portrait_missing" not in gaps and bool(
        ((dossier.get("artifacts") or {}).get("portrait_url")))
    offerings = _n(ctx.get("offerings"))
    testimonials = _n(ctx.get("testimonials"))
    session_done = bool(
        (((dossier.get("meta") or {}).get("coach_session_completed") or {})
         .get("value")))
    store = ctx.get("store") if isinstance(ctx.get("store"), dict) else {}
    store_items = _n(store.get("items")) if store.get("enabled") else 0
    # THE SESSION COUNTS (2026-10-03, the first live test): the card said
    # "no testimonials" over the client story the owner had just told the
    # Coach, and "no services" over the offers and prices they named.
    truth = dossier.get("truth") if isinstance(dossier.get("truth"), dict) else {}
    story = dossier.get("story") if isinstance(dossier.get("story"), dict) else {}
    stated_offers = [o for o in (truth.get("offers") or []) if isinstance(o, dict) and o.get("name")]
    proof = story.get("proof")
    told_story = bool((proof.get("value") if isinstance(proof, dict) else proof) or "")

    notes: List[str] = []
    chips: List[str] = []
    if photos == 0:
        notes.append("No photos in your library yet. The page will be "
                     "typographic — words and type carry it, no empty frames. "
                     "Add photos of your work and redraft to get a gallery.")
        chips.append("Make the hero typographic and lead with what we do, "
                     "not photos")
    elif photos < 3:
        notes.append(f"{photos} photo{'s' if photos != 1 else ''} on file. "
                     "Enough for the hero, not a gallery grid — add more for "
                     "a work section.")
        chips.append("Use the photos we have in the hero; no gallery grid")
    else:
        notes.append(f"{photos} photos on file — the gallery will be real.")
    if not brand_mark:
        notes.append("No logo on file — the header will carry a typographic "
                     "wordmark. Add your mark in Brand to change that.")
        chips.append("Give the wordmark real presence in the header")
    # A SITE THAT CAN'T SAY WHERE IT IS (2026-11-09): only when the context
    # says what is on file; a caller with no contact block doesn't know.
    contact = ctx.get("contact")
    if isinstance(contact, dict) and not str(contact.get("address") or "").strip():
        try:
            import discovery
            import site_layouts
            biz = ctx.get("business") if isinstance(ctx.get("business"), dict) else {}
            btype = str(biz.get("type") or biz.get("business_type") or "")
            if site_layouts.has_a_door(btype, discovery.current_ask(dossier)):
                notes.append("No address on file, so the page can't say where you "
                             "are. Tap Change something and give it, and it goes on "
                             "the page.")
        except Exception:
            pass
    if offerings == 0 and stated_offers:
        named = ", ".join(str(o["name"]) for o in stated_offers[:3])
        # (2026-10-04, Kevin: "what about booking?") the line used to end
        # in "add them as services", a sentence with no door. Chief now
        # sets booking up from these same words (chief_site_design).
        notes.append(f"The page lists what you told the Coach you offer ({named}), "
                     "as you described it. Visitors can't book yet: ask Chief to "
                     "set up booking from what you told the Coach, and the "
                     "page's book buttons will open it.")
    elif offerings == 0:
        notes.append("No services or offerings on file — the page cannot "
                     "list what you sell. Add at least one before building.")
        chips.append("Write the services section from what I tell you here")
    elif offerings <= 2:
        notes.append(f"{offerings} offering{'s' if offerings != 1 else ''} on "
                     "file — the page will lead with those, not a long menu.")
        chips.append("Give each service its own moment instead of a list")
    else:
        notes.append(f"{offerings} offerings on file.")
    if testimonials == 0 and told_story:
        notes.append("No written testimonials yet. The client story you told "
                     "the Coach carries the proof, told in your words.")
    elif testimonials == 0:
        notes.append("No testimonials yet — there will be no proof section "
                     "until clients leave words.")
        chips.append("Replace the testimonials section with a promise in my "
                     "own voice")
    if store_items == 0:
        notes.append("Nothing in the shop — the page will not carry a shop "
                     "section or link.")
    if not session_done:
        notes.append("The Design Session was not finished — the Blueprint "
                     "is drafted from your business profile alone. Finish "
                     "the session with the Coach for a page that sounds "
                     "like you.")
    return {"photos": photos, "photo_stop": photo_stop(ctx, photos),
            "brand_mark": brand_mark, "portrait": portrait,
            "offerings": offerings, "testimonials": testimonials,
            "store_items": store_items, "session_done": session_done,
            "gaps": gaps, "notes": notes[:6], "chips": chips[:4]}
