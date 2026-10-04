"""THE OWNER'S REVISION ROUND (2026-10-03, phase 4 of the hand-build plan).

By hand, a finished page goes in front of its owner, they point at the parts
that are not right ("this feels plain", "wrong photo", "that isn't how I
talk"), and those parts get fixed together, then they look again. The
product built the page and handed it over: the only ways to change one part
were Chief's one-section refine (one ask at a time, in words) or a whole
rebuild.

A round is the owner's reactions to the sections of their page, fixed in one
job: each marked section is reworked on the page the previous fix left
(builder_v2.refine_section_doc: one section rebuilt, every law held, the
rest of the page byte for byte), then the page is stored and served once.

THE PRICE. Each build includes REVISION_FREE_SECTIONS fixes (4): the
first round after a build is part of the build, the way a hand-build
includes the owner's first notes. A fix past those is a section rework
(pricing_config.section_rewrite, 120 credits). Only fixes that LANDED are
counted: a section the builder could not improve without breaking a rule is
left as it was and costs nothing. The model calls ride free (units=0) and
one marker row carries the round's price, the way a build is charged.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import sb_clients

logger = logging.getLogger("site_revisions")

# What the owner can say about a section without finding words for it. The
# `ask` is what the builder hears; a note in their own words rides along.
REACTIONS: Dict[str, Dict[str, str]] = {
    "plain": {
        "label": "Feels plain",
        "ask": "It feels plain. Give it a composition with intent in the page's "
               "own look (scale, contrast, an arrangement a designer chose), "
               "keeping every fact it carries.",
    },
    "photo": {
        "label": "Wrong photo",
        "ask": "The photo is wrong for it. Use a different photo from THE REAL "
               "DATA that fits what this section says, or a layout without one "
               "if none fits; never a box standing in for a photo.",
    },
    "wordy": {
        "label": "Too many words",
        "ask": "Too many words. Cut it to what a visitor needs to decide, "
               "keeping every real fact and price.",
    },
    "voice": {
        "label": "Doesn't sound like me",
        "ask": "It doesn't sound like the owner. Rewrite the words in the voice "
               "the blueprint gives, plainer and closer to how they talk.",
    },
    "unclear": {
        "label": "Hard to follow",
        "ask": "It's hard to follow. Make what this section is for, and what to "
               "do next, clear at a glance.",
    },
}

MAX_PER_ROUND = 6
_NOTE_CAP = 240


def free_per_build() -> int:
    try:
        return max(0, min(12, int(os.environ.get("REVISION_FREE_SECTIONS") or 4)))
    except (TypeError, ValueError):
        return 4


def price_per_section() -> int:
    import pricing_config
    return pricing_config.section_rewrite()


def build_key(cfg: Dict[str, Any]) -> str:
    """Which build the stored page came from. A section rework keeps the
    canvas's generated_at, so the free fixes last until the next build."""
    canvas = cfg.get("canvas") if isinstance(cfg.get("canvas"), dict) else {}
    return str(canvas.get("generated_at") or "")


def free_left(cfg: Dict[str, Any]) -> int:
    rev = cfg.get("revisions") if isinstance(cfg.get("revisions"), dict) else {}
    used = int(rev.get("free_used") or 0) if rev.get("build") == build_key(cfg) else 0
    return max(0, free_per_build() - used)


def _plain(html: str) -> str:
    """Visible words: tags out, spaces collapsed, no space left before the
    punctuation an inline tag sat against ("stuck</em>." reads "stuck.")."""
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip()
    return re.sub(r"\s+([.,;:!?’”)])", r"\1", t)


def _clip(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    cut = text[:cap].rsplit(" ", 1)[0].rstrip(",;:—-")
    return cut + "…"


def outline(doc: str) -> List[Dict[str, str]]:
    """The page's sections top to bottom, as the owner sees them: the id the
    builder gave each one and its heading. A section with no heading (a
    quote band, a photo strip) is named by its first words, the way the
    owner would point at it, never "Section 5" (the first live page had
    two of nine with none)."""
    import builder_v2
    out = []
    for sid, a, z in builder_v2.section_spans(doc):
        part = doc[a:z]
        h = re.search(r"<h[1-3]\b[^>]*>(.*?)</h[1-3]>", part, re.IGNORECASE | re.DOTALL)
        label = _plain(h.group(1)) if h else ""
        if not label:
            # its quote, else its first real sentence, else whatever it says
            for tag in ("blockquote", "p"):
                for m in re.finditer(rf"<{tag}\b[^>]*>(.*?)</{tag}>", part, re.IGNORECASE | re.DOTALL):
                    words = _plain(m.group(1))
                    if len(words.split()) >= 4:
                        label = _clip(words, 60)
                        break
                if label:
                    break
        if not label:
            inner = re.sub(r"^<section\b[^>]*>", "", part, flags=re.IGNORECASE)
            label = _clip(_plain(inner), 60)
        if not label:
            # a section with no words at all is named by the link that points
            # at it, the way the owner meets it ("How it works"), and said to
            # be empty, never "Section 5" (the second live test)
            m = re.search(rf'<a\b[^>]*href=["\']#{re.escape(sid)}["\'][^>]*>(.*?)</a>',
                          doc, re.IGNORECASE | re.DOTALL)
            named = _plain(m.group(1)) if m else ""
            label = f"{_clip(named, 50)} (empty right now)" if named else ""
        out.append({"id": sid, "heading": _clip(label, 90)})
    return out[:24]


def suggested(cfg: Dict[str, Any], section_ids: List[str]) -> List[str]:
    """Sections the builder rethought once and still could not get right,
    left for the owner (the judgment plan, J3): the walk-through opens on
    them, the way a designer says "let's look at this one together"."""
    rep = cfg.get("canvas_report") if isinstance(cfg.get("canvas_report"), dict) else {}
    owed = ((rep.get("vision") or {}).get("for_the_owner") or []) if isinstance(rep, dict) else []
    out = []
    for o in owed:
        sid = str((o or {}).get("section") or "") if isinstance(o, dict) else ""
        if sid in section_ids and sid not in out:
            out.append(sid)
    return out


def clean_reactions(raw: Any, section_ids: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """The reactions worth a fix, one per section in page order of arrival:
    a known reaction, a note, or both. A section marked with neither (or
    one the page does not have, when the ids are known) is dropped."""
    out: Dict[str, Dict[str, str]] = {}
    for r in (raw if isinstance(raw, list) else []):
        if not isinstance(r, dict):
            continue
        sid = str(r.get("section") or "").strip()[:60]
        reaction = str(r.get("reaction") or "").strip().lower()
        reaction = reaction if reaction in REACTIONS else ""
        note = re.sub(r"\s+", " ", str(r.get("note") or "")).strip()[:_NOTE_CAP]
        if not sid or not (reaction or note):
            continue
        if section_ids is not None and sid not in section_ids:
            continue
        out[sid] = {"section": sid, "reaction": reaction, "note": note}
    return list(out.values())[:MAX_PER_ROUND]


def instruction_for(reaction: str, note: str) -> str:
    parts = []
    if reaction in REACTIONS:
        parts.append(REACTIONS[reaction]["ask"])
    if note:
        parts.append(f"In their words: \"{note}\"")
    return " ".join(parts)


def _site_row(business_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=id,slug,site_config&limit=1") or []
    return rows[0] if rows else None


def state(business_id: str) -> Dict[str, Any]:
    """What the revision panel shows: the page's sections, the reactions,
    and what a fix costs right now. `ready` is False for a page the new
    builder did not write (module pages keep Chief's one-section refine)."""
    from site_composer import _is_builder_page
    row = _site_row(business_id)
    cfg = dict((row or {}).get("site_config") or {})
    base = {"reactions": [{"key": k, "label": v["label"]} for k, v in REACTIONS.items()],
            "free_per_build": free_per_build(), "price_per_section": price_per_section(),
            "max_per_round": MAX_PER_ROUND}
    if not row or not _is_builder_page(cfg):
        return {"ok": True, "ready": False, "sections": [], "free_left": 0, **base}
    doc = str((cfg.get("canvas") or {}).get("html") or "")
    rev = cfg.get("revisions") if isinstance(cfg.get("revisions"), dict) else {}
    this_build = rev.get("build") == build_key(cfg)
    last = (rev.get("rounds") or [])[-1:] if this_build else []
    sections = outline(doc)
    # what the owner already had fixed since this build is not suggested again
    done = {sid for r in ((rev.get("rounds") or []) if this_build else [])
            if isinstance(r, dict) for sid in (r.get("fixed") or [])}
    worth = [s for s in suggested(cfg, [x["id"] for x in sections]) if s not in done]
    # what the builder chose to ask instead of overriding the blueprint
    # (builder_v2, BLUEPRINT_SETTLED): the owner answers in a note
    rep = cfg.get("canvas_report") if isinstance(cfg.get("canvas_report"), dict) else {}
    asks = [str(q)[:200] for q in ((rep.get("vision") or {}).get("questions") or [])
            if str(q or "").strip()][:3]
    return {"ok": True, "ready": True, "sections": sections, "suggested": worth,
            "questions": asks,
            "free_left": free_left(cfg), "last_round": last[0] if last else None, **base}


def quote(cfg: Dict[str, Any], n: int) -> Dict[str, int]:
    """What a round of n fixes would cost if every one landed."""
    free = min(n, free_left(cfg))
    return {"free": free, "paid": n - free, "credits": (n - free) * price_per_section()}


def run_round(business_id: str, reactions: List[Dict[str, str]],
              progress_cb=None) -> Dict[str, Any]:
    """The revise_sections job body (sync, in the chief_jobs worker thread).

    {ok, fixed[], unchanged[], free_used, credits, url} — ok is True when at
    least one section changed. A section that could not be fixed is named
    with the reason and left exactly as it was."""
    import builder_v2
    import spec_author
    from site_composer import (_is_builder_page, _report_progress,
                               gather_context, refresh_if_composed)

    row = _site_row(business_id)
    cfg = dict((row or {}).get("site_config") or {})
    if not row or not _is_builder_page(cfg):
        return {"ok": False, "error": "this page wasn't made by the site builder, "
                                      "so ask Chief to change one section at a time"}
    canvas = dict(cfg.get("canvas") or {})
    doc = str(canvas.get("html") or "")
    reactions = clean_reactions(reactions, [s["id"] for s in outline(doc)])
    if not reactions:
        return {"ok": False, "error": "mark a section and say what isn't right"}
    ctx = gather_context(business_id)
    spec_text = (spec_author.approved_spec_text(business_id)
                 or str((cfg.get("design_spec") or {}).get("text") or ""))
    headings = {s["id"]: s["heading"] for s in outline(doc)}

    fixed: List[Dict[str, Any]] = []
    unchanged: List[Dict[str, str]] = []
    for i, r in enumerate(reactions):
        name = headings.get(r["section"]) or r["section"]
        _report_progress(progress_cb, 10 + int(75 * i / len(reactions)),
                         f"Fixing {name}" if name else "Fixing a section")
        try:
            out = builder_v2.refine_section_doc(
                doc, spec_text, ctx, business_id, r["section"],
                instruction_for(r["reaction"], r["note"]), units=0)
        except Exception as e:
            logger.warning(f"[revisions] {r['section']} failed for {business_id[:8]}: {e}")
            out = {"ok": False, "error": "the rework didn't come back"}
        if out.get("ok") and out.get("html"):
            doc = out["html"]
            fixed.append({"section": r["section"], "heading": name,
                          "reaction": r["reaction"], "note": r["note"]})
        else:
            unchanged.append({"section": r["section"], "heading": name,
                              "why": _why(out.get("error"))})

    if not fixed:
        return {"ok": False, "fixed": [], "unchanged": unchanged, "free_used": 0,
                "credits": 0,
                "error": "none of the marked sections could be fixed without "
                         "breaking one of the page's rules; nothing changed"}

    _report_progress(progress_cb, 88, "Putting the fixes on the page")
    q = quote(cfg, len(fixed))
    now = datetime.now(timezone.utc).isoformat()
    key = build_key(cfg)
    rev = cfg.get("revisions") if isinstance(cfg.get("revisions"), dict) else {}
    if rev.get("build") != key:
        rev = {"build": key, "free_used": 0, "rounds": []}
    rev = dict(rev)
    rev["free_used"] = int(rev.get("free_used") or 0) + q["free"]
    rev["rounds"] = ([x for x in (rev.get("rounds") or []) if isinstance(x, dict)][-4:]
                     + [{"at": now, "fixed": [f["section"] for f in fixed],
                         "unchanged": [u["section"] for u in unchanged],
                         "free": q["free"], "credits": q["credits"]}])
    canvas["html"] = doc
    cfg["canvas"] = canvas
    cfg["revisions"] = rev
    refines = [x for x in (cfg.get("canvas_refines") or []) if isinstance(x, dict)][-9:]
    refines += [{"section": f["section"], "instruction": instruction_for(f["reaction"], f["note"]),
                 "at": now, "round": True} for f in fixed]
    cfg["canvas_refines"] = refines[-10:]
    sb_clients.sb_patch_as_service(f"/business_sites?id=eq.{row['id']}", {"site_config": cfg})
    _charge(business_id, q["credits"], len(fixed))
    try:
        refresh_if_composed(business_id)
    except Exception as e:
        # stored: the next refresh (any Edit Mode save) serves it
        logger.warning(f"[revisions] re-render failed (stored, not served yet) "
                       f"for {business_id[:8]}: {e}")
    _report_progress(progress_cb, 100, "Done")
    slug = row.get("slug")
    return {"ok": True, "fixed": fixed, "unchanged": unchanged,
            "free_used": q["free"], "credits": q["credits"],
            "free_left": max(0, free_per_build() - rev["free_used"]),
            "url": f"https://{slug}.mysolutionist.app" if slug else None}


def _why(error: Any) -> str:
    """A refusal in the round's words. The one-section refine's errors end
    "so nothing on the page changed", which is false in a round where the
    other marked sections did change: the section is named as unchanged
    instead, so the clause goes."""
    why = str(error or "").strip()
    why = re.sub(r"[.,;]?\s*(so\s+)?nothing on the page changed[.;]?(\s*try again)?\.?$", "",
                 why, flags=re.IGNORECASE).strip().rstrip(".")
    return (why or "it couldn't be improved without breaking one of the page's rules")[:160]


def _charge(business_id: str, credits: int, fixed: int) -> None:
    """One marker row for the round (units may be 0: the round still shows
    in usage, the way a free trial build does)."""
    try:
        from api_usage_logger import log_api_usage_sync
        log_api_usage_sync(
            endpoint="/composer/revise-sections", model="site-revision-marker",
            input_tokens=0, output_tokens=0, business_id=business_id,
            task_type="site_revision", cost_cents_override=0.0, units=int(credits))
        logger.info(f"[revisions] {business_id[:8]}: {fixed} fixed, {credits} credits")
    except Exception as e:
        logger.warning(f"[revisions] marker row failed for {business_id[:8]}: {e}")
