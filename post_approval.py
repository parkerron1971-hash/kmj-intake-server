"""post_approval.py — what makes a scheduled post publishable.

A scheduled `publish_post` runs with nobody watching. The policy engine
does not refuse it: class C unattended is *recorded*, not blocked, which
is a deliberate choice for verbs like recurring invoices where the
practitioner set the recurrence up themselves and the exposure is the
point. Publishing to a public Page is the case where that reasoning runs
out — an invoice reaches one client who expected it, a post reaches
everyone and cannot be unseen.

So the approval is carried by the POST, not by the schedule. Approving
records what was approved: the exact words, the Page, and whether
Instagram was included. At publish time those three are checked again.

The fingerprint is the load-bearing part. Without it, "approved" would
mean "this row was approved once", and editing the body afterwards would
publish text nobody agreed to under an approval that still looked valid.
With it, an edit voids the approval and the post goes back to the queue.

Nothing here blocks a practitioner who asks for a post right now. Asking
IS the approval — this governs only the unattended path.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

APPROVAL_KEY = "approval"


def fingerprint(post: Dict[str, Any]) -> str:
    """Identify the post's PUBLISHED content — the parts a reader sees.

    Deliberately not the whole row: scheduling metadata, tags and
    counters change without changing a word of what goes out, and an
    approval that expired every time an unrelated field moved would
    train people to re-approve without reading.
    """
    parts = [
        (post.get("title") or "").strip(),
        (post.get("body") or "").strip(),
        (post.get("image_url") or "").strip(),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def build(post: Dict[str, Any], *, user_id: str, page_id: str,
          to_instagram: bool, when_iso: str) -> Dict[str, Any]:
    """The record written when a human approves a post."""
    return {
        "at": when_iso,
        "by": str(user_id or ""),
        "page_id": str(page_id or ""),
        "to_instagram": bool(to_instagram),
        "fingerprint": fingerprint(post),
    }


def refusal(post: Dict[str, Any], *, page_id: str,
            to_instagram: bool) -> Optional[str]:
    """Why this post may NOT be published unattended, or None if it may.

    Returns a sentence a practitioner can act on, because it surfaces in
    the scheduler's failure notification and in the audit row.
    """
    ap = post.get(APPROVAL_KEY)
    if not isinstance(ap, dict) or not ap.get("at"):
        return ("this post was never approved, so it was not published on a "
                "schedule. Approve it and it will go out at its next slot.")

    if ap.get("fingerprint") != fingerprint(post):
        return ("this post was edited after it was approved, so the approval "
                "no longer covers what it says. Read it again and re-approve.")

    approved_page = str(ap.get("page_id") or "")
    if approved_page and approved_page != str(page_id or ""):
        return ("this post was approved for a different Page than the one it "
                "was about to go to, so it was held.")

    if to_instagram and not ap.get("to_instagram"):
        return ("Instagram was not part of what was approved for this post, "
                "so it was held. Approve it for Instagram as well.")

    return None
