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
from typing import Any, Dict, List


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
    if offerings == 0:
        notes.append("No services or offerings on file — the page cannot "
                     "list what you sell. Add at least one before building.")
        chips.append("Write the services section from what I tell you here")
    elif offerings <= 2:
        notes.append(f"{offerings} offering{'s' if offerings != 1 else ''} on "
                     "file — the page will lead with those, not a long menu.")
        chips.append("Give each service its own moment instead of a list")
    else:
        notes.append(f"{offerings} offerings on file.")
    if testimonials == 0:
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
    return {"photos": photos, "brand_mark": brand_mark, "portrait": portrait,
            "offerings": offerings, "testimonials": testimonials,
            "store_items": store_items, "session_done": session_done,
            "gaps": gaps, "notes": notes[:6], "chips": chips[:4]}
