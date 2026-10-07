"""business_marketing_store.py — the marketing suite's storage, for every business.

The tables and RPCs live in supabase/APPLY-2026-10-07-marketing-suite.sql
(marketing_desks, marketing_runs, marketing_posts, marketing_link_clicks,
marketing_post_events). This module is the one door to them: the desk API,
the sender and the planner read and write through it. Nothing imports it yet
(B3 of the 2026-10-07 marketing-suite plan); no route or job runs on it.

FAIL CLOSED. Every call goes out as the service role (the backend's own
owner checks come first, in the callers). A read that fails RAISES
StoreUnavailable; it never comes back as "no rows", because an empty desk and
an unreadable desk lead to different decisions (the planner would plan a week
that already exists; the sender would think nothing is due). A refused RPC
(a post changed, a time passed, someone else's post) raises StoreConflict.

THE APPROVAL BINDING. digest(post) is the post's content_hash: the exact
content an owner approves. It covers the post's id and business, the words
(caption and the publish_text that actually goes out, short link included),
where the link goes (landing_url), the media (the artwork ids in order, or the
clip, its review fingerprint and its covers), the accounts (sorted), and the
time and window (run_at, expires_at). Anything else — status, revision, the
approval stamps, errors, delivery results, the Boss opening it was made for —
is not content, so changing it never voids an approval. marketing_approve
copies content_hash to approved_hash; marketing_claim_due sends only while the
two still match, so an edit after approval holds the post until it is
approved again.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

import sb_clients
from platform_marketing import digest as _sha256_json   # the platform desk's canonical JSON hash

logger = logging.getLogger("business_marketing_store")

MIGRATION = "supabase/APPLY-2026-10-07-marketing-suite.sql"

# The CHECK lists in the migration. __tests__/test_business_marketing_store.py
# parses the migration and fails if these drift from it: a value the app
# writes and the database refuses is a write that silently never happened.
POST_STATUSES = ("draft", "approved", "dispatching", "submitted", "published", "partly_published",
                 "failed", "uncertain", "cancelled", "pulled")
POST_SOURCES = ("suggestion", "plan", "owner", "chief", "clip", "opening")
DESIGN_STATUSES = ("none", "designing", "ready", "failed")
APPROVED_VIA = ("owner", "standing")
RUN_KINDS = ("suggestion", "week", "openings")
RUN_TRIGGERS = ("scheduled", "manual")
RUN_STATUSES = ("running", "succeeded", "failed", "skipped")

GO_CODE = re.compile(r"^[a-z2-7]{8}$")
_HEX64 = re.compile(r"^[a-f0-9]{64}$")
MAX_APPROVE = 50
MAX_CLAIM = 100


class StoreError(Exception):
    """A marketing read or write that did not happen. Never "nothing there"."""


class StoreUnavailable(StoreError):
    """The storage could not be reached, read or written (or is not set up)."""


class StoreConflict(StoreError):
    """The database refused: the post changed, its time passed, or it is not this business's."""


# ── pure functions ────────────────────────────────────────────────────

def _uuid(value: Any) -> str:
    return str(UUID(str(value)))


def _utc(value: Any) -> str:
    """One spelling of an instant, whatever form it arrived in (a datetime,
    or PostgREST's ISO string). A time without a zone is refused."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("A post's time needs its time zone.")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _media(media: Any) -> Dict[str, Any]:
    """Pictures (artwork ids, in order: the first is the one people see) or a
    clip (its id, its review fingerprint, and its covers by shape)."""
    m = media or {}
    if not isinstance(m, Mapping):
        raise ValueError("A post's media is an object.")
    if m.get("clip_id"):
        if m.get("artwork_ids"):
            raise ValueError("A post carries a clip or pictures, not both.")
        fingerprint = str(m.get("clip_fingerprint") or "")
        if not _HEX64.match(fingerprint):
            raise ValueError("A clip goes with the review fingerprint it was approved at.")
        covers = m.get("covers") or {}
        if not isinstance(covers, Mapping):
            raise ValueError("A clip's covers are named by shape.")
        return {"clip_id": _uuid(m["clip_id"]), "clip_fingerprint": fingerprint,
                "covers": {str(shape): _uuid(art) for shape, art in covers.items() if art}}
    return {"artwork_ids": [_uuid(a) for a in (m.get("artwork_ids") or [])]}


def _targets(targets: Any) -> List[Dict[str, str]]:
    """The accounts, sorted. Only what names an account: a renamed handle
    (username) is the same account and does not void an approval."""
    if targets is None:
        targets = []
    if not isinstance(targets, (list, tuple)):
        raise ValueError("A post's targets are a list.")
    out = []
    for t in targets:
        if not isinstance(t, Mapping) or not t.get("connection_id"):
            raise ValueError("Each target names its connected account.")
        out.append({"connection_id": _uuid(t["connection_id"]),
                    "platform": str(t.get("platform") or ""),
                    "provider_account_id": str(t.get("provider_account_id") or "")})
    return sorted(out, key=lambda t: (t["platform"], t["provider_account_id"], t["connection_id"]))


def bound_content(post: Mapping[str, Any]) -> Dict[str, Any]:
    """Exactly what an approval of this post binds (see the module doc)."""
    return {
        "id": _uuid(post["id"]),
        "business_id": _uuid(post["business_id"]),
        "caption": post.get("caption") or "",
        "publish_text": post.get("publish_text") or "",
        "landing_url": post.get("landing_url") or None,
        "media": _media(post.get("media")),
        "targets": _targets(post.get("targets")),
        "run_at": _utc(post["run_at"]),
        "expires_at": _utc(post["expires_at"]),
    }


def digest(post: Mapping[str, Any]) -> str:
    """The post's content_hash. Takes a row as it is stored or as PostgREST
    returns it; both give the same hash."""
    return _sha256_json(bound_content(post))


def link_code(post_id: Any) -> str:
    """The post's short-link code: 8 characters from its id.

    Derived rather than random, so a retried save or an edit always lands on
    the same code and the link in an approved caption never drifts from the
    post it names. Its own namespace, so it never equals the platform desk's
    code for the same id."""
    raw = hashlib.sha256(f"marketing-go:{_uuid(post_id)}".encode()).digest()[:5]
    return base64.b32encode(raw).decode().lower()


def run_id_for(business_id: Any, week_of: Any) -> UUID:
    """One run per business per week: a retry, a restart or a second click
    lands on the same row."""
    week = week_of if type(week_of) is date else date.fromisoformat(str(week_of))
    return uuid5(NAMESPACE_URL, f"marketing-week:{_uuid(business_id)}:{week.isoformat()}")


# ── the database ──────────────────────────────────────────────────────

def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=20)


def _detail(response: httpx.Response) -> Dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


async def request(method: str, path: str, body: Any = None) -> Any:
    """One PostgREST call as the service role. Raises instead of returning
    nothing: StoreConflict for a refusal, StoreUnavailable for everything else."""
    base = sb_clients.sb_url()
    try:
        headers = sb_clients.sb_headers_service()
    except RuntimeError:
        headers = None
    if not base or not headers:
        raise StoreUnavailable("Marketing storage is not configured on the server.")
    try:
        async with _client() as client:
            r = await client.request(method, base + "/rest/v1" + path, headers=headers, json=body)
    except httpx.HTTPError:
        raise StoreUnavailable("Marketing storage is unavailable. Please retry.") from None
    if r.status_code >= 400:
        detail = _detail(r)
        if r.status_code == 409 or (r.status_code == 400 and path.startswith("/rpc/")):
            # Our own RAISE EXCEPTION (P0001) is written for people; anything
            # else from Postgres is not, and stays in the log.
            message = detail.get("message") if detail.get("code") == "P0001" else None
            logger.info("marketing store refused %s %s: %s %s", method, path.split("?")[0],
                        r.status_code, detail.get("code"))
            raise StoreConflict(message or "The post changed. Refresh and review again.")
        logger.warning("marketing store %s %s failed: %s %s", method, path.split("?")[0],
                       r.status_code, str(detail.get("code") or "")[:20])
        raise StoreUnavailable(f"Marketing storage could not do that (HTTP {r.status_code}). "
                               f"Check that {MIGRATION} is applied and the server has access.")
    if not r.content:
        return None
    try:
        return r.json()
    except ValueError:
        raise StoreUnavailable("Marketing storage answered with something unreadable.") from None


async def rows(path: str) -> List[Dict[str, Any]]:
    """A GET that must come back as a list of rows (maybe empty)."""
    out = await request("GET", path)
    if not isinstance(out, list):
        raise StoreUnavailable("Marketing storage answered with something unexpected.")
    return out


async def rpc(name: str, args: Mapping[str, Any]) -> Any:
    return await request("POST", f"/rpc/{name}", dict(args))


async def _one(path: str) -> Optional[Dict[str, Any]]:
    found = await rows(path)
    return found[0] if found else None


async def get_desk(business_id: Any) -> Optional[Dict[str, Any]]:
    """The business's desk, or None when it has none yet (never None on failure)."""
    return await _one(f"/marketing_desks?business_id=eq.{_uuid(business_id)}&limit=1")


async def get_run(business_id: Any, run_id: Any) -> Optional[Dict[str, Any]]:
    return await _one(f"/marketing_runs?id=eq.{_uuid(run_id)}&business_id=eq.{_uuid(business_id)}&limit=1")


async def get_post(business_id: Any, post_id: Any) -> Optional[Dict[str, Any]]:
    """One of THIS business's posts, or None (another business's post is None too)."""
    return await _one(f"/marketing_posts?id=eq.{_uuid(post_id)}&business_id=eq.{_uuid(business_id)}&limit=1")


async def claim_run(business_id: Any, week_of: Any, *, kind: str, source: str, replan: bool = False) -> bool:
    """Whether this caller may plan the business's week now (see the migration)."""
    if kind not in RUN_KINDS or source not in RUN_TRIGGERS:
        raise ValueError("Unknown kind of run or source.")
    week = week_of if type(week_of) is date else date.fromisoformat(str(week_of))
    answer = await rpc("marketing_claim_run", {
        "p_run_id": str(run_id_for(business_id, week)), "p_business_id": _uuid(business_id),
        "p_week": week.isoformat(), "p_kind": kind, "p_source": source, "p_replan": bool(replan)})
    if not isinstance(answer, bool):
        raise StoreUnavailable("Marketing storage answered with something unexpected.")
    return answer


async def approve(business_id: Any, items: Iterable[Mapping[str, Any]], *, actor: Any,
                  via: str = "owner") -> int:
    """Approve every one of these exact reviewed versions, or none of them.

    items: [{"id", "revision", "content_hash"}] as the owner saw them. Raises
    StoreConflict if any changed, passed its time, is mid-design or is not
    this business's."""
    if via not in APPROVED_VIA:
        raise ValueError("Unknown kind of approval.")
    batch = []
    for item in items:
        revision = item.get("revision")
        content_hash = str(item.get("content_hash") or "")
        if type(revision) is not int or revision < 1 or not _HEX64.match(content_hash):
            raise ValueError("Each post is approved at the revision and content the owner saw.")
        batch.append({"id": _uuid(item.get("id")), "revision": revision, "content_hash": content_hash})
    if not 1 <= len(batch) <= MAX_APPROVE:
        raise ValueError(f"Approve between 1 and {MAX_APPROVE} posts.")
    answer = await rpc("marketing_approve", {"p_business_id": _uuid(business_id), "p_items": batch,
                                             "p_actor": _uuid(actor), "p_via": via})
    if type(answer) is not int:
        raise StoreUnavailable("Marketing storage answered with something unexpected.")
    return answer


async def claim_due(limit: int = 10) -> List[Dict[str, Any]]:
    """The approved posts that are due, each handed to exactly one caller,
    already marked dispatching. Paused desks hand over nothing."""
    if type(limit) is not int or not 1 <= limit <= MAX_CLAIM:
        raise ValueError(f"Claim between 1 and {MAX_CLAIM} posts.")
    answer = await rpc("marketing_claim_due", {"p_limit": limit})
    if not isinstance(answer, list):
        raise StoreUnavailable("Marketing storage answered with something unexpected.")
    return answer


async def follow(code: str, *, count_click: bool) -> Optional[Dict[str, Any]]:
    """A short link's {business_id, tracked_url}, or None for a code that names
    no post. Counts the click (when asked) only for a post that went out."""
    if not GO_CODE.match(code or ""):
        return None
    answer = await rpc("marketing_follow", {"p_code": code, "p_count_click": bool(count_click)})
    if not isinstance(answer, list):
        raise StoreUnavailable("Marketing storage answered with something unexpected.")
    return answer[0] if answer else None
