"""business_marketing_outcomes.py — what came through a business's post links.

B6 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md; the platform desk's
marketing_outcomes, for one business. Every post of a business with a site
carries its own short link ({origin}/go/{code}); the redirect behind it tags
the landing page with utm_content=<post id> (business_marketing_links). The
post id is the one join key:

  clicks  marketing_link_clicks (a person's click on the short link; link
          previews and Do Not Track are not counted, and neither is a click
          on a post that never went out)
  visits  site_events of this business whose campaign tags carry the post id,
          counted as distinct sessions (the site's beacon keeps the tags for
          the tab's session; a Do Not Track visitor sends nothing)
  leads   contacts of this business whose recorded attribution carries the
          post id (lead_attribution: only what the form or booking recorded)
  bookings  bookings (module_entries) of this business whose own recorded
          attribution carries the post id: made on a page reached through
          the post's link (2026-10-09, booking_widget_router.
          booking_attribution; the hosted /book page keeps the tags for the
          tab's session)
  paid_cents  what was paid online for those bookings (Stripe's own amount,
          data.amount_charged_cents, once the booking's paid_at is set): a
          deposit counts as what was paid, not the service's price

The window is the last 30 days: the posts that went out in it, and what came
through their links since.

play_scores (B9) reads the same three measures over 120 days and averages
them by play, so the weekly plan can lean on what did well through the
business's own links (marketing_engine._rank, from 3 samples a play).

A RECORDED relationship, never a causal claim (the rule marketing_outcomes
and growth_intelligence follow): "4 visits came through this post's link",
not "this post brought 4 visits". Someone who saw the post and typed the
address in is invisible here.

A read that fails is UNAVAILABLE (None, and named in `sources`), never 0: a
broken read shown as "0 leads" is a lie with a number in it. A read that hit
its row limit is `partial` (a floor). The posts themselves unreadable raises
StoreError, and the route answers 503.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID

import business_marketing_links as links
import business_marketing_store as store
import sb_clients
from business_marketing_desk import channels_of, query_time

logger = logging.getLogger("business_marketing_outcomes")

MEASURES = ("clicks", "visits", "leads", "bookings", "paid_cents")
WINDOW_DAYS = 30
SENT = ("submitted", "published", "partly_published")
POST_COLUMNS = "id,caption,status,run_at,landing_url,tracked_url,link_code,targets,external_urls"
POSTS_LIMIT = 200
BATCH = 100
LIMITS = {"clicks": 5000, "visits": 20000, "leads": 5000, "bookings": 5000}


class _Unread(Exception):
    """One measure's source could not be read."""


def _ids(posts: List[Dict[str, Any]]) -> List[str]:
    """Validated post ids: they are interpolated into PostgREST filters."""
    return [str(UUID(str(p["id"]))) for p in posts]


async def _service(path: str) -> List[Dict[str, Any]]:
    rows = await asyncio.to_thread(sb_clients.sb_get_as_service, path)
    if not isinstance(rows, list):
        raise _Unread(path.split("?")[0])
    return rows


async def _store(path: str) -> List[Dict[str, Any]]:
    try:
        return await store.rows(path)
    except store.StoreError:
        raise _Unread(path.split("?")[0]) from None


async def _batched(read: Callable, path_for: Callable[[str], str], ids: List[str],
                   limit: int) -> Tuple[List[Dict[str, Any]], bool]:
    """Every batch's rows, and whether any batch hit its limit (a floor)."""
    rows, partial = [], False
    for i in range(0, len(ids), BATCH):
        got = await read(path_for(",".join(ids[i:i + BATCH])) + f"&limit={limit}")
        partial = partial or len(got) >= limit
        rows.extend(got)
    return rows, partial


async def _measure(fetch) -> Tuple[List[Dict[str, Any]], str]:
    try:
        rows, partial = await fetch()
    except _Unread as exc:
        logger.warning("marketing results: %s could not be read", exc)
        return [], "unavailable"
    return rows, "partial" if partial else "loaded"


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def headline(totals: Dict[str, Optional[int]], sources: Dict[str, str], *, sent: int, linked: int,
             site_state: str) -> str:
    """One plain sentence for the owner. 'came through', never 'brought'."""
    if not sent:
        if site_state == "none":
            return ("Nothing has gone out from the marketing desk in the last 30 days, and posts carry no link "
                    "until this business has a site or booking page.")
        return "Nothing has gone out from the marketing desk in the last 30 days, so there is nothing to measure yet."
    posts = _count(sent, "post", "posts")
    if not linked:
        if site_state == "none":
            return (f"Your {posts} carried no link because this business has no site or booking page yet, "
                    "so nothing could be counted.")
        return f"None of your {posts} carried a link, so nothing could be counted."
    if any(sources[m] == "unavailable" for m in MEASURES):
        return "Some results could not be read just now. Nothing below is a zero because of that; check again shortly."
    linked_posts = _count(linked, "post", "posts")
    if not totals["clicks"] and not totals["visits"]:
        return f"No one has followed the links in your {linked_posts} from the last 30 days yet."
    # A Do Not Track visitor is a visit without a counted click, and a click
    # whose tab closes before the page loads is a click without a visit: the
    # larger of the two is the honest floor.
    parts = [_count(max(totals["clicks"] or 0, totals["visits"] or 0), "visit", "visits")]
    if totals["leads"]:
        parts.append(_count(totals["leads"], "lead", "leads"))
    if totals["bookings"]:
        parts.append(_count(totals["bookings"], "booking", "bookings"))
    listed = parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"
    floor = "At least " if any(sources[m] == "partial" for m in MEASURES) else ""
    sentence = f"{listed} came through the links in your {linked_posts} from the last 30 days."
    sentence = floor + sentence if floor else sentence[0].upper() + sentence[1:]
    if totals["paid_cents"]:
        sentence += f" {money(totals['paid_cents'])} of it was paid online."
    return sentence


def money(cents: int) -> str:
    """$45, or $45.50."""
    dollars, rest = divmod(int(cents), 100)
    return f"${dollars:,}" + (f".{rest:02d}" if rest else "")


async def _measure_posts(bid: str, ids: List[str],
                         since: datetime) -> Tuple[Dict[str, Dict[str, Optional[int]]], Dict[str, str]]:
    """Clicks, visits, leads, bookings and what was paid for them per post
    (ids: validated post ids) since `since`, and each source's state. A
    source that cannot be read is None for every post, never 0."""
    per: Dict[str, Dict[str, Optional[int]]] = {pid: {m: 0 for m in MEASURES} for pid in ids}
    sources = {m: "loaded" for m in MEASURES}
    if not ids:
        return per, sources
    day = since.date().isoformat()
    stamp = query_time(since)
    import platform_suite
    platform = await platform_suite.is_platform_async(bid)
    if platform:
        # Solutionist's own desk on the suite (B15): its pages are the
        # platform's (site_events with no business) and its leads the
        # platform's own (marketing_leads), as marketing_outcomes reads them.
        # It takes no bookings, so none are read.
        visits_at, leads_at = "business_id=is.null", "/marketing_leads?"
    else:
        visits_at, leads_at = f"business_id=eq.{bid}", f"/contacts?business_id=eq.{bid}&"

    async def no_bookings():
        return [], False

    ((clicks, sources["clicks"]), (events, sources["visits"]), (leads, sources["leads"]),
     (bookings, sources["bookings"])) = await asyncio.gather(
        _measure(lambda: _batched(_store, lambda s: (
            f"/marketing_link_clicks?business_id=eq.{bid}&post_id=in.({s})&day=gte.{day}"
            "&select=post_id,clicks"), ids, LIMITS["clicks"])),
        _measure(lambda: _batched(_service, lambda s: (
            f"/site_events?{visits_at}&data->>utm_content=in.({s})&ts=gte.{stamp}"
            "&select=session_id,data"), ids, LIMITS["visits"])),
        _measure(lambda: _batched(_service, lambda s: (
            f"{leads_at}attribution->>utm_content=in.({s})&created_at=gte.{stamp}"
            "&select=id,attribution"), ids, LIMITS["leads"])),
        _measure(no_bookings if platform else lambda: _batched(_service, lambda s: (
            f"/module_entries?business_id=eq.{bid}&data->attribution->>utm_content=in.({s})"
            f"&created_at=gte.{stamp}&select=id,paid_at,post:data->attribution->>utm_content,"
            "charged:data->>amount_charged_cents"), ids, LIMITS["bookings"])),
    )
    sources["paid_cents"] = sources["bookings"]
    for row in clicks:
        pid = str(row.get("post_id") or "")
        if pid in per:
            per[pid]["clicks"] += int(row.get("clicks") or 0)
    sessions: Dict[str, set] = {}
    for row in events:
        pid = str((row.get("data") or {}).get("utm_content") or "")
        if pid in per and row.get("session_id"):
            sessions.setdefault(pid, set()).add(row["session_id"])
    for pid, seen in sessions.items():
        per[pid]["visits"] = len(seen)
    for row in leads:
        pid = str((row.get("attribution") or {}).get("utm_content") or "")
        if pid in per:
            per[pid]["leads"] += 1
    for row in bookings:
        pid = str(row.get("post") or "")
        if pid in per:
            per[pid]["bookings"] += 1
            if row.get("paid_at"):
                per[pid]["paid_cents"] += _cents(row.get("charged"))
    for pid in per:
        for m in MEASURES:
            if sources[m] == "unavailable":
                per[pid][m] = None
    return per, sources


def _cents(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


# ── what did well, by play (the weekly plan, B9) ──────────────────────

PLAY_WINDOW_DAYS = 120          # the platform desk's window for a play's own results
PLAY_POSTS_LIMIT = 200
SCORED = ("published", "partly_published")


SCORED_MEASURES = ("clicks", "visits", "leads", "bookings")


def score(measured: Optional[Dict[str, Optional[int]]]) -> Optional[float]:
    """One post's result through its own link: a lead counts far more than a
    look, and a booking more than a lead (the platform's weighting,
    marketing_engine._score, with a business's bookings in place of the
    platform's signups). None when a measure is unread."""
    if not measured or any(measured.get(m) is None for m in SCORED_MEASURES):
        return None
    return measured["bookings"] * 8 + measured["leads"] * 4 + max(measured["clicks"], measured["visits"])


async def play_scores(business_id: Any, *, now: Optional[datetime] = None) -> Dict[str, Dict[str, Any]]:
    """{play_id: {samples, average}} over this business's posts that went out
    in the last 120 days with their own link. marketing_engine._rank lets a
    play's own results reorder the week only once it has PROVEN (3) samples;
    with fewer, the default ranking stands. A source that cannot be read
    gives {} (the default ranking), never a guess; the posts unreadable
    raises StoreError."""
    bid = str(UUID(str(business_id)))
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=PLAY_WINDOW_DAYS)
    posts = await store.rows(
        f"/marketing_posts?business_id=eq.{bid}&status=in.({','.join(SCORED)})&play_id=not.is.null"
        f"&tracked_url=not.is.null&run_at=gte.{query_time(since)}&select=id,play_id,run_at"
        f"&order=run_at.desc&limit={PLAY_POSTS_LIMIT}")
    if not posts:
        return {}
    per, sources = await _measure_posts(bid, _ids(posts), since)
    if any(state == "unavailable" for state in sources.values()):
        return {}
    by_play: Dict[str, List[float]] = {}
    for p in posts:
        value = score(per.get(str(p["id"])))
        if value is not None:
            by_play.setdefault(str(p["play_id"]), []).append(value)
    return {play: {"samples": len(v), "average": round(sum(v) / len(v), 2)} for play, v in by_play.items()}


async def for_business(business_id: Any, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Per-post and total results for this business's posts that went out in
    the last 30 days, with each source's state. Raises StoreError when the
    posts cannot be read."""
    bid = str(UUID(str(business_id)))
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=WINDOW_DAYS)
    posts = await store.rows(
        f"/marketing_posts?business_id=eq.{bid}&status=in.({','.join(SENT)})&run_at=gte.{query_time(since)}"
        f"&select={POST_COLUMNS}&order=run_at.desc&limit={POSTS_LIMIT}")
    try:
        site = await asyncio.to_thread(links.site_for, bid)
        site_state = "ready" if site else "none"
    except links.LinksUnavailable:
        site, site_state = None, "unavailable"

    linked_posts = [p for p in posts if p.get("tracked_url")]
    ids = _ids(linked_posts)
    per, sources = await _measure_posts(bid, ids, since)

    totals = {m: (sum(p[m] for p in per.values()) if sources[m] != "unavailable" else None) for m in MEASURES}
    out_posts = []
    for p in posts:
        pid = str(p["id"])
        counted = per.get(pid)
        out_posts.append({
            "id": pid, "caption": p.get("caption") or "", "status": p.get("status"), "run_at": p.get("run_at"),
            "accounts": channels_of(p), "landing_url": p.get("landing_url"),
            "has_link": counted is not None, "link_code": p.get("link_code") if counted is not None else None,
            "external_urls": p.get("external_urls") or [],
            **{m: (counted[m] if counted is not None else None) for m in MEASURES},
        })
    return {
        "business_id": bid, "window_days": WINDOW_DAYS, "since": since.isoformat(),
        "site": {"state": site_state, "origin": links.origin(site)},
        "sent": len(posts), "linked": len(linked_posts),
        "totals": totals, "sources": sources,
        "headline": headline(totals, sources, sent=len(posts), linked=len(linked_posts), site_state=site_state),
        "posts": out_posts, "truncated": len(posts) >= POSTS_LIMIT,
    }
