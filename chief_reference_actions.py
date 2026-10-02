"""Chief looks at a website the owner points at (2026-09-22).

Kevin asked Chief "can you see this website — I want my site to look
like it" and it could not: the chat turn had web search (text results)
and nothing that opens a page. The Design Session already had real
eyes — `discovery.study_reference` screenshots a page at phone and
desktop width and a vision model reads it into transferable rules, bans
and a taste reading. This is that same study, as a Chief action, saved
to the same place (the site's discovery dossier), so the Design
Session, the Blueprint author and the builder all get it without the
owner pasting the link twice.

What Chief can say afterwards is only what the study returned: the
receipt carries the rules and the reading, and the answer check holds
the narration to it.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from urllib.parse import urlsplit

# A study is two page loads and one vision call. Enough for a real
# design conversation; not a crawler.
DAILY_STUDIES = 12

_TASTE_WORDS = {
    "ground": "background", "density": "spacing", "carrier": "carried by",
    "edges": "edges", "era": "era", "tone": "tone", "motion": "motion",
}


def _reading(taste: Dict[str, Any]) -> List[str]:
    out = []
    for key, word in _TASTE_WORDS.items():
        v = taste.get(key)
        value = v.get("value") if isinstance(v, dict) else v
        if isinstance(value, str) and value.strip():
            out.append(f"{word}: {value.strip()}")
    return out


def _studies_today(dossier: Dict[str, Any]) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=1)
    n = 0
    for ref in ((dossier or {}).get("artifacts") or {}).get("references") or []:
        try:
            if datetime.fromisoformat(str(ref.get("studied_at"))) >= since:
                n += 1
        except (TypeError, ValueError):
            continue
    return n


def summarize(entry: Dict[str, Any]) -> str:
    """The receipt text: what the study saw, in the owner's terms."""
    host = urlsplit(entry.get("url") or "").hostname or entry.get("url") or "the site"
    if entry.get("error"):
        return (f"I could not see {host}: {entry['error']}. No design notes came from it. "
                f"A public page that loads without a login works best, or send screenshots.")
    lines = [f"Studied {host} at phone and desktop width "
             f"({'a site you like' if entry.get('verdict') == 'love' else 'a site you dislike'})."]
    reading = _reading(entry.get("taste") or {})
    if reading:
        lines.append("The feel: " + "; ".join(reading) + ".")
    if entry.get("rules"):
        lines.append("What to borrow: " + "; ".join(entry["rules"]) + ".")
    if entry.get("bans"):
        lines.append("What to avoid: " + "; ".join(entry["bans"]) + ".")
    lines.append("Saved to your site's design notes. The Design Session, your Blueprint "
                 "and the site builder use it from here.")
    return " ".join(lines)


async def handle_study_website(client, biz, action):
    import discovery
    from website_image_references import public_url
    try:
        url = public_url(action.get("url", ""))
    except ValueError as e:
        return {"type": "study_website", "failed": True, "label": "Website not studied",
                "result": str(e)}
    verdict = "hate" if str(action.get("verdict") or "").lower().startswith(("h", "dis")) else "love"
    why = str(action.get("why") or "").strip()[:200]
    business_id = str(biz["id"])
    dossier = await asyncio.to_thread(discovery.get_dossier, business_id) or {}
    if _studies_today(dossier) >= DAILY_STUDIES:
        return {"type": "study_website", "failed": True, "label": "Website not studied",
                "result": f"That is {DAILY_STUDIES} websites studied today, the daily limit. "
                          "The ones already studied are saved to your site's design notes."}
    entry = await asyncio.to_thread(discovery.study_reference, business_id, url, verdict, why)
    text = summarize(entry)
    host = urlsplit(url).hostname or url
    if entry.get("error"):
        return {"type": "study_website", "failed": True, "label": f"Could not see {host}",
                "result": text, "reference": entry}
    return {"type": "study_website", "label": f"Studied {host}", "result": text,
            "reference": {k: entry.get(k) for k in ("url", "verdict", "rules", "bans", "taste")},
            "nav": None}
