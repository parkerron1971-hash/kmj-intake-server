# site_photo_list.py
# ─────────────────────────────────────────────────────────────────────
# THE PHOTO LIST (2026-10-01, the concept-layer plan, step 8).
#
# The liaisongraphics.com pages are carried by photography of the founder
# inside the idea: a graduate in regalia at two laptops, a portrait in a
# gilded frame. We cannot shoot those. We can tell the owner exactly what
# to shoot. The builder already writes a hidden drop slot with one line of
# shot direction wherever a page wants a photo it does not have; the
# concept sheet writes a PHOTO LIST in the idea's own words. Until now
# nobody handed that list to the owner, so a slot waited in the Studio
# for someone who did not know it was there.
#
# file_task() turns what is still missing into ONE practitioner task
# ("Photos for your site"), updated in place on every build, never
# duplicated, and left alone once there is nothing left to shoot. A plain
# tasks row: no model call, no Chief turn, no assignment cap.
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("site_photo_list")

TASK_TITLE = "Photos for your site"
MAX_SHOTS = 8

_DROP_RE = re.compile(
    r"<(\w+)\b([^>]*\bclass=\"[^\"]*\bsx-drop\b[^\"]*\"[^>]*)>(.*?)</\1>",
    re.IGNORECASE | re.DOTALL)


def shot_list(html: str) -> List[Tuple[str, str]]:
    """[(slot, direction)] for every drop slot still empty on the page."""
    out: List[Tuple[str, str]] = []
    for m in _DROP_RE.finditer(html or ""):
        attrs = m.group(2)
        if re.search(r"\bsx-filled\b", attrs):
            continue
        slot = re.search(r'data-sx-slot\s*=\s*"([^"]+)"', attrs)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(3))).strip()
        if text:
            out.append(((slot.group(1) if slot else "photo"), text[:200]))
    seen, uniq = set(), []
    for slot, text in out:
        if text.lower() not in seen:
            seen.add(text.lower())
            uniq.append((slot, text))
    return uniq[:MAX_SHOTS]


def sheet_shots(sheet: Optional[Dict[str, str]]) -> List[str]:
    """The concept sheet's PHOTO LIST, one shot per item."""
    raw = str((sheet or {}).get("photo_list") or "")
    return [s.strip(" .") for s in re.split(r"\s*[;|]\s*|\s+·\s+", raw) if s.strip(" .")][:MAX_SHOTS]


def description(shots: List[Tuple[str, str]], extra: List[str]) -> str:
    lines = ["Your site has a place waiting for each of these. Take them on a "
             "phone in good light, then open Website, tap the empty frame, and "
             "upload. They go live the moment you add them.", ""]
    for i, (_slot, text) in enumerate(shots, 1):
        lines.append(f"{i}. {text}")
    have = [t.lower() for _, t in shots]
    more = [s for s in extra
            if not any(s.lower() in t or t in s.lower() for t in have)]
    if more:
        lines += ["", "For the look of the site, if you can:"]
        lines += [f"- {s}" for s in more]
    return "\n".join(lines)[:1800]


def file_task(business_id: str, html: str,
              sheet: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Create or refresh the one photo task. Returns 'created', 'updated',
    or None (nothing to shoot, or the write failed). Never raises."""
    try:
        shots = shot_list(html)
        if not shots:
            return None
        import sb_clients
        body = description(shots, sheet_shots(sheet))
        open_rows = sb_clients.sb_get_as_service(
            f"/tasks?business_id=eq.{business_id}&title=eq.{TASK_TITLE.replace(' ', '%20')}"
            "&status=neq.done&select=id,description&limit=1") or []
        if open_rows:
            if (open_rows[0].get("description") or "") != body:
                sb_clients.sb_patch_as_service(
                    f"/tasks?id=eq.{open_rows[0]['id']}", {"description": body})
            return "updated"
        due = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
        res = sb_clients.sb_post_as_service("/tasks", {
            "business_id": business_id, "title": TASK_TITLE, "description": body,
            "status": "todo", "priority": "medium", "due_date": due,
        })
        return "created" if res else None
    except Exception as e:
        logger.info(f"[photo-list] task skipped: {e}")
        return None
