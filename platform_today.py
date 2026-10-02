"""Mission Control → Today: everything that needs Kevin, in one read.

WHY THIS EXISTS. Mission Control grew to eighteen panels, and the
signals that ask for Kevin's attention lived only inside their own
panel: a failed payment in Subscriptions, Chief's pending approvals in
Ask Chief, posts awaiting approval three clicks deep in Marketing, a
watcher's findings in the Agents log (written again every hour, so the
same problem showed up three times). The Overview tiles reported status
("Healthy", "$0"), never work.

This endpoint is the redesign's spine (canvas 2026-10-01): one ranked,
deduplicated queue — people first, then money, then the machines — plus
the pulse numbers, the overnight timeline, what's running and what
shipped. Every source fails soft and independently: a Stripe timeout
costs the coupon line, not the page. `sources_failed` names what was
skipped so the screen can say so instead of implying "all clear".

Owner-only (require_owner). Read-only: nothing here writes or spends.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends

from lead_admin import require_owner, _service_headers, SUPABASE_URL

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/platform", tags=["platform-today"])

HTTP_TIMEOUT = 10.0
SOURCE_TIMEOUT = 8.0
CACHE_SECONDS = 30.0
_cache: Dict[str, Any] = {"at": 0.0, "key": "", "data": None}

# Where "Open in Sentry" lands. The org slug is the real one; the env var
# exists so a moved org doesn't need a deploy.
SENTRY_ISSUES_URL = os.environ.get(
    "SENTRY_ISSUES_URL", "https://solutionist-system-llc.sentry.io/issues/")

LANE_ORDER = {"people": 0, "money": 1, "systems": 2}
TONE_ORDER = {"red": 0, "amber": 1, "blue": 2, "gold": 3}


# ─── Pure helpers (unit-tested) ─────────────────────────────────────────

_DIGITS = re.compile(r"\d+")
_LATEST = re.compile(r"\(latest:.*$", re.IGNORECASE)


def normalize_finding(title: str) -> str:
    """The same problem, reported every hour, differs only in its numbers
    and its '(latest: …)' tail. Collapse both so repeats count as one."""
    t = _LATEST.sub("", (title or "").strip().lower())
    t = _DIGITS.sub("#", t)
    return re.sub(r"\s+", " ", t).strip(" .")


def _strip_agent_prefix(title: str) -> Tuple[str, str]:
    """'Hermes: 13 outbound SMS…' → ('hermes', '13 outbound SMS…')."""
    m = re.match(r"^\s*([A-Za-z][\w -]{1,30}):\s*(.+)$", title or "")
    if m:
        return m.group(1).strip().lower(), m.group(2).strip()
    return "", (title or "").strip()


def group_findings(rows: List[Dict[str, Any]], now: datetime,
                   fresh_hours: int = 24) -> Tuple[List[Dict[str, Any]], int]:
    """Pending watcher findings → one entry per distinct problem.

    Returns (groups, stale_count). A group is fresh if its newest report
    is inside `fresh_hours`; older pending rows are not today's news —
    they are counted so Systems can offer them, not shown on Today."""
    groups: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if (r.get("status") or "") != "pending":
            continue
        agent = (r.get("agent") or "").strip().lower()
        prefix, body = _strip_agent_prefix(r.get("title") or "")
        agent = agent or prefix
        key = f"{agent}|{normalize_finding(body)}"
        at = _parse_ts(r.get("created_at"))
        g = groups.get(key)
        if g is None:
            groups[key] = {"agent": agent, "title": body, "seen": 1,
                           "latest_at": at, "first_at": at,
                           "detail": r.get("detail") or ""}
        else:
            g["seen"] += 1
            if at and (g["latest_at"] is None or at > g["latest_at"]):
                g["latest_at"], g["title"] = at, body
                g["detail"] = r.get("detail") or g["detail"]
            if at and (g["first_at"] is None or at < g["first_at"]):
                g["first_at"] = at
    cutoff = now - timedelta(hours=fresh_hours)
    fresh, stale = [], 0
    for g in groups.values():
        if g["latest_at"] and g["latest_at"] >= cutoff:
            fresh.append(g)
        else:
            stale += 1
    fresh.sort(key=lambda g: g["latest_at"] or now, reverse=True)
    return fresh, stale


def classify_finding(g: Dict[str, Any]) -> Dict[str, Any]:
    """One finding group → a queue item. Keyword rules, deliberately
    plain: the watchers write fixed sentences, and a wrong guess here
    only changes an icon and a button, never hides the finding."""
    title = g["title"]
    low = title.lower()
    agent = g["agent"] or "watcher"
    seen = g["seen"]
    item: Dict[str, Any] = {
        "id": f"finding:{agent}:{normalize_finding(title)[:60]}",
        "kind": "finding", "source": agent.title(), "seen": seen,
        "at": _iso(g["latest_at"]), "since": _iso(g["first_at"]),
        "title": _sentence(title), "detail": "", "lanes": ["systems"],
        "room": "systems", "tone": "amber", "parked": False,
        "action": {"label": "Ask Chief why",
                   "chief": f"Explain this {agent} finding and what I should do: {title}"},
    }
    if "missing env keys" in low or "not configured" in low:
        item.update(parked=True, tone="blue",
                    detail="A setup item, not a fault. It waits here until you want it.",
                    action={"label": "Set up", "nav": "platform-health"})
    elif "server error" in low:
        item.update(tone="red", detail="From the error stream. Sentry has the stack traces.",
                    action={"label": "Open in Sentry", "href": SENTRY_ISSUES_URL})
    elif "client error" in low:
        item.update(detail="Browser errors reported by the app.",
                    action={"label": "Open in Sentry", "href": SENTRY_ISSUES_URL})
    elif "database" in low or "unreachable" in low:
        item.update(tone="red", detail="The platform can't reliably reach its database.",
                    action={"label": "Open System Health", "nav": "platform-health"})
    elif "customer text" in low or "unanswered" in low:
        item.update(lanes=["people"], room="customers",
                    detail="On a practitioner's line. Chief can say which business.",
                    action={"label": "Which business?",
                            "chief": f"Which business has this, and who should answer it? {title}"})
    elif "sms" in low or "text" in low or "twilio" in low:
        item.update(detail="Texting delivery. Hermes watches the Twilio rails.")
    elif "stripe" in low or "webhook" in low:
        item.update(lanes=["money", "systems"], tone="red",
                    detail="Billing events are piling up unprocessed.",
                    action={"label": "Open System Health", "nav": "platform-health"})
    if seen > 1:
        extra = f"Reported {seen}× — counted once here."
        item["detail"] = f"{item['detail']} {extra}".strip()
    return item


def rank(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """People first, then money, then the machines; worst tone first."""
    def key(it: Dict[str, Any]):
        lanes = it.get("lanes") or ["systems"]
        lane = min(LANE_ORDER.get(l, 9) for l in lanes)
        return (lane, TONE_ORDER.get(it.get("tone") or "", 9), -(it.get("seen") or 1))
    return sorted(items, key=key)


def compose_read(needs: List[Dict[str, Any]], parked: List[Dict[str, Any]]) -> Dict[str, str]:
    """Chief's read, composed from the queue rather than generated.

    Deliberately not a model call: this screen loads every time Kevin
    opens Mission Control, and a paid call per open would be the
    metering's single largest line for a paragraph that only restates
    the list. The wording follows the queue, so it is never wrong about
    what's there."""
    people = [i for i in needs if "people" in (i.get("lanes") or [])]
    money = [i for i in needs if "money" in (i.get("lanes") or []) and i not in people]
    machines = [i for i in needs if i not in people and i not in money]
    if not needs:
        tail = " One setup item is parked." if len(parked) == 1 else (
            f" {len(parked)} setup items are parked." if parked else "")
        return {"headline": "All quiet. Nothing needs you this morning.",
                "body": "Every watcher checked in and nothing is waiting on you." + tail}
    parts = []
    if people:
        parts.append(f"{_word(len(people))} {'thing touches' if len(people) == 1 else 'things touch'} real people")
    if money:
        parts.append(f"{_word(len(money)).lower() if parts else _word(len(money))} "
                     f"{'is' if len(money) == 1 else 'are'} about money")
    if machines:
        parts.append(f"{_word(len(machines)).lower() if parts else _word(len(machines))} "
                     f"{'is' if len(machines) == 1 else 'are'} the machines")
    headline = _join(parts) + "."
    first = (people or money or machines)[0]
    # Titles keep their case: they carry business names ("Creative
    # Genius's renewal…"), and lowercasing them read as a typo.
    body = f"Start with this: {first['title'].rstrip('.')}."
    rest = [i for i in needs if i is not first]
    if rest:
        body += f" After that: {rest[0]['title'].rstrip('.')}."
    if len(rest) > 1:
        body += f" {_word(len(rest) - 1)} more below."
    return {"headline": headline[0].upper() + headline[1:], "body": body}


def next_run(times: List[Optional[datetime]], now: datetime,
             default: timedelta = timedelta(hours=1)) -> Optional[datetime]:
    """When a watcher will next run, from how often it has ACTUALLY run.

    Hermes is scheduled hourly, but every process that boots the scheduler
    runs it, so the observed cadence is closer to every 20-30 minutes, and
    "last run + 1 hour" showed a next run that never came. The median gap
    of recent runs is the honest estimate (clamped to 5 minutes-2 hours)."""
    ts = sorted(t for t in times if t)
    if not ts:
        return None
    recent = ts[-7:]
    gaps = [(b - a) for a, b in zip(recent, recent[1:]) if b > a]
    step = sorted(gaps)[len(gaps) // 2] if gaps else default
    step = max(timedelta(minutes=5), min(step, timedelta(hours=2)))
    nxt = ts[-1] + step
    while nxt < now:
        nxt += step
    return nxt


def coverage() -> List[Dict[str, Any]]:
    """What the platform can see — replaces the hand-kept 'blind spots'
    list, which went stale the week Sentry landed and kept telling Chief
    there was no error reporter."""
    return [
        {"id": "backend_errors", "label": "Backend errors", "via": "Sentry",
         "covered": bool((os.environ.get("SENTRY_DSN") or "").strip())},
        {"id": "frontend_errors", "label": "Frontend errors", "via": "Sentry (browser)",
         "covered": True},
        {"id": "ai_cost", "label": "AI cost per business", "via": "Money → Costs",
         "covered": True},
        {"id": "deploy_version", "label": "Which version is live", "via": "deploy check",
         "covered": True},
        {"id": "email_bounces", "label": "Email bounces and spam complaints",
         "via": "Resend webhook", "covered": True},
        {"id": "storage", "label": "Storage used per business", "via": None, "covered": False},
        {"id": "meta_expiry", "label": "Meta token expiry alerts", "via": None, "covered": False},
    ]


def _word(n: int) -> str:
    return ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
            "Nine", "Ten"][n] if 0 <= n <= 10 else str(n)


def _join(parts: List[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _sentence(s: str) -> str:
    s = _LATEST.sub("", s or "").strip()
    return s[:1].upper() + s[1:] if s else s


def _parse_ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d else None


# ─── Sources (each fails soft) ──────────────────────────────────────────

async def _guard(name: str, fn: Callable[[], Awaitable[Any]],
                 failed: List[str], default: Any = None) -> Any:
    try:
        return await asyncio.wait_for(fn(), timeout=SOURCE_TIMEOUT)
    except Exception as e:  # noqa: BLE001 — every source is optional
        logger.warning(f"today: source {name} skipped: {str(e)[:160]}")
        failed.append(name)
        return default


async def _count(c: httpx.AsyncClient, table: str, params: Dict[str, str]) -> int:
    r = await c.head(f"{SUPABASE_URL}/rest/v1/{table}",
                     headers={**_service_headers(), "Prefer": "count=exact", "Range": "0-0"},
                     params=params)
    if r.status_code not in (200, 206):
        raise RuntimeError(f"{table} count {r.status_code}")
    cr = r.headers.get("content-range", "")
    last = cr.split("/")[-1] if "/" in cr else "0"
    return int(last) if last and last != "*" else 0


async def _get(c: httpx.AsyncClient, table: str, params: Dict[str, str]) -> List[Dict[str, Any]]:
    r = await c.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=_service_headers(), params=params)
    if r.status_code >= 400:
        raise RuntimeError(f"{table} read {r.status_code}")
    return r.json() or []


async def _practitioners(c: httpx.AsyncClient) -> Dict[str, int]:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    r = await c.get(f"{SUPABASE_URL}/auth/v1/admin/users",
                    headers={"apikey": key, "Authorization": f"Bearer {key}"},
                    params={"per_page": "500"})
    if r.status_code >= 400:
        raise RuntimeError(f"admin users {r.status_code}")
    body = r.json()
    users = body.get("users", []) if isinstance(body, dict) else body
    return {"total": len(users),
            "signed_in": sum(1 for u in users if u.get("last_sign_in_at"))}


async def _marketing() -> List[Dict[str, Any]]:
    """Solutionist's own marketing: drafts waiting with their deadline, posts
    that missed their time or failed, paused publishing, a plan that could not
    be written (marketing_desk). Until 2026-10-02 this counted the platform
    business's content calendar, a different pipeline, so the weekly plan's
    drafts never reached Today."""
    import marketing_desk
    return marketing_desk.today_items(await marketing_desk.read_state())


_coupon_cache: Dict[str, Any] = {"at": 0.0, "data": None}


async def _coupons() -> Dict[str, Any]:
    """Promotion codes on the platform's Stripe account (BE #1143).
    Stripe is the slowest source here, so it keeps its own 5-minute cache."""
    if _coupon_cache["data"] is not None and time.time() - _coupon_cache["at"] < 300:
        return _coupon_cache["data"]
    from stripe_discounts import list_discounts
    page = await list_discounts()
    now = time.time()
    items = page.get("items") or []
    live, expiring, at_limit = [], [], []
    for p in items:
        cap = p.get("max_redemptions")
        used = int(p.get("times_redeemed") or 0)
        exp = p.get("expires_at")
        usable = (p.get("active") and (p.get("coupon") or {}).get("valid")
                  and (not exp or exp > now) and (not cap or used < cap))
        if usable:
            live.append(p)
            if exp and exp - now <= 3 * 86400:
                expiring.append(p)
            if cap and cap - used <= max(1, cap // 10):
                at_limit.append(p)
    data = {
        "active": len(live),
        "redemptions": sum(int(p.get("times_redeemed") or 0) for p in items),
        "expiring": [{"code": p.get("code"), "expires_at": p.get("expires_at")} for p in expiring],
        "near_limit": [{"code": p.get("code"), "used": p.get("times_redeemed"),
                        "cap": p.get("max_redemptions")} for p in at_limit],
        "top": sorted(({"code": p.get("code"), "used": int(p.get("times_redeemed") or 0),
                        "off": _coupon_label(p.get("coupon") or {})} for p in live),
                      key=lambda x: x["used"], reverse=True)[:3],
        "more": bool(page.get("has_more")),
    }
    _coupon_cache.update(at=time.time(), data=data)
    return data


def _coupon_label(c: Dict[str, Any]) -> str:
    if c.get("percent_off") is not None:
        return f"{c['percent_off']:g}% off"
    if c.get("amount_off") is not None:
        return f"${(c['amount_off'] or 0) / 100:,.0f} off"
    return ""


# ─── The endpoint ───────────────────────────────────────────────────────

@router.get("/today")
async def platform_today(owner=Depends(require_owner)):
    owner_id = str(getattr(owner, "id", "") or "")
    if (_cache["data"] is not None and _cache["key"] == owner_id
            and time.time() - _cache["at"] < CACHE_SECONDS):
        return _cache["data"]
    data = await build_today(owner)
    _cache.update(at=time.time(), key=owner_id, data=data)
    return data


async def build_today(owner) -> Dict[str, Any]:
    import platform_console as pc
    now = datetime.now(timezone.utc)
    owner_id = str(getattr(owner, "id", "") or "")
    failed: List[str] = []

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        since_day = (now - timedelta(hours=36)).isoformat()
        (subs, practitioners, businesses, tickets, unread, findings_rows, runs,
         approvals, marketing, dev_tasks, traffic, coupons) = await asyncio.gather(
            _guard("subscriptions", lambda: pc.subscriptions_summary(_owner=owner), failed, {}),
            _guard("practitioners", lambda: _practitioners(c), failed, {}),
            _guard("businesses", lambda: _count(c, "businesses", {"is_active": "eq.true"}), failed, None),
            _guard("support", lambda: _get(c, "support_tickets", {
                "select": "id,subject,created_at", "status": "eq.open",
                "order": "created_at.desc", "limit": "20"}), failed, None),
            _guard("inbox", lambda: _count(c, "platform_emails", {"read": "eq.false"}), failed, None),
            _guard("findings", lambda: _get(c, "platform_changelog", {
                "select": "id,created_at,agent,category,title,detail,status",
                "status": "eq.pending", "order": "created_at.desc", "limit": "200"}), failed, []),
            _guard("agent_runs", lambda: _get(c, "platform_agent_runs", {
                "select": "agent,started_at,finished_at,ok,findings,summary",
                "started_at": f"gte.{since_day}", "order": "started_at.desc",
                "limit": "60"}), failed, []),
            _guard("approvals", lambda: _get(c, "platform_chief_authorizations", {
                "select": "id,action,status,created_at,expires_at",
                "owner_id": f"eq.{owner_id}", "status": "eq.pending",
                "order": "created_at.desc", "limit": "20"}), failed, None),
            _guard("marketing", _marketing, failed, None),
            _guard("dev_desk", lambda: _get(c, "dev_tasks", {
                "select": "id,title,status,lane,agent,updated_at,created_at",
                "order": "updated_at.desc", "limit": "30"}), failed, None),
            _guard("traffic", lambda: _traffic(owner), failed, None),
            _guard("coupons", _coupons, failed, None),
        )

    anchors = await _guard("anchors", lambda: asyncio.to_thread(_anchor_health), failed, None)
    spend = await _guard("spend", lambda: asyncio.to_thread(_spend), failed, None)

    needs: List[Dict[str, Any]] = []

    # People: payment trouble names a person on the other end.
    for p in (subs or {}).get("payment_issues") or []:
        name = p.get("business_name") or "A business"
        status = (p.get("status") or "").replace("_", " ")
        needs.append({
            "id": f"payment:{p.get('business_id')}", "kind": "payment", "source": "Stripe",
            "title": f"{name}'s renewal didn't go through",
            "detail": f"Subscription is {status}. Their access stays on while you decide.",
            "lanes": ["people", "money"], "room": "customers", "tone": "red",
            "featured": True, "business_id": p.get("business_id"), "seen": 1,
            "action": {"label": "Draft a note with Chief",
                       "chief": (f"Draft a short, warm email from Kevin to the owner of {name}: "
                                 "their Solutionist renewal didn't go through (usually an expired "
                                 "card), nothing has been switched off, and they can update it "
                                 "from Billing. Under 90 words.")},
            "secondary": {"label": "Open their account", "nav": "platform-subscriptions"},
        })
    for t in (subs or {}).get("trial_ending_soon") or []:
        days = t.get("trial_days_left")
        if isinstance(days, (int, float)) and days <= 3:
            needs.append({
                "id": f"trial:{t.get('business_id')}", "kind": "trial", "source": "Billing",
                "title": f"{t.get('business_name') or 'A trial'} ends in {int(days)} "
                         f"day{'s' if int(days) != 1 else ''}",
                "detail": "A good moment for a personal note.", "lanes": ["people", "money"],
                "room": "customers", "tone": "amber", "seen": 1,
                "action": {"label": "Open Subscriptions", "nav": "platform-subscriptions"},
            })
    if tickets:
        n = len(tickets)
        needs.append({
            "id": "support:open", "kind": "support", "source": "Support",
            "title": f"{_word(n) if n <= 10 else n} support ticket{'s' if n != 1 else ''} waiting",
            "detail": f"Newest: {(tickets[0].get('subject') or '').strip()[:90]}",
            "lanes": ["people"], "room": "inbox", "tone": "amber", "seen": 1,
            "count": n, "action": {"label": "Open tickets", "nav": "platform-support"},
        })
    if unread:
        needs.append({
            "id": "inbox:unread", "kind": "inbox", "source": "Inbox",
            "title": f"{unread} unread email{'s' if unread != 1 else ''}",
            "detail": "Mail to the platform's own addresses.", "lanes": ["people"],
            "room": "inbox", "tone": "blue", "seen": 1, "count": unread,
            "action": {"label": "Open Inbox", "nav": "platform-inbox"},
        })
    needs.extend(marketing or [])

    # Money: coupons that are about to stop working.
    for cp in (coupons or {}).get("expiring") or []:
        needs.append({
            "id": f"coupon:expiring:{cp.get('code')}", "kind": "coupon", "source": "Coupons",
            "title": f"Code {cp.get('code')} expires within 3 days",
            "detail": "Extend it or let it lapse on purpose.", "lanes": ["money"],
            "room": "money", "tone": "amber", "seen": 1,
            "action": {"label": "Open Coupons", "nav": "platform-coupons"},
        })
    for cp in (coupons or {}).get("near_limit") or []:
        needs.append({
            "id": f"coupon:limit:{cp.get('code')}", "kind": "coupon", "source": "Coupons",
            "title": f"Code {cp.get('code')} is nearly used up",
            "detail": f"{cp.get('used')} of {cp.get('cap')} redemptions.", "lanes": ["money"],
            "room": "money", "tone": "gold", "seen": 1,
            "action": {"label": "Open Coupons", "nav": "platform-coupons"},
        })

    # Machines: Chief's pending approvals, builds, anchors, watcher findings.
    if approvals:
        n = len(approvals)
        needs.append({
            "id": "approvals:pending", "kind": "approval", "source": "Chief",
            "title": f"Chief is waiting on your yes ({n})",
            "detail": "Actions Chief proposed that need your approval before they run.",
            "lanes": ["systems"], "room": "chief", "tone": "blue", "seen": 1, "count": n,
            "action": {"label": "Review", "nav": "platform-chief"},
        })
    day_ago = now - timedelta(hours=24)
    for t in dev_tasks or []:
        if t.get("status") == "failed" and (_parse_ts(t.get("updated_at")) or now) >= day_ago:
            needs.append({
                "id": f"build:{t.get('id')}", "kind": "build", "source": "Dev Desk",
                "title": f"A build stopped: {(t.get('title') or 'untitled')[:80]}",
                "detail": "The agent reported a failure. The thread has its last words.",
                "lanes": ["systems"], "room": "build", "tone": "amber", "seen": 1,
                "action": {"label": "Open thread", "nav": "platform-dev-desk"},
            })
    for p in (anchors or {}).get("providers") or []:
        if p.get("verdict") == "failing":
            needs.append({
                "id": f"anchor:{p.get('provider')}", "kind": "anchor", "source": "Ledger",
                "title": f"Ledger anchoring is failing on {p.get('provider')}",
                "detail": (p.get("last_error") or "")[:120] or "Recent publishes failed.",
                "lanes": ["systems"], "room": "systems", "tone": "red", "seen": 1,
                "action": {"label": "Open Ledger Anchors", "nav": "platform-anchors"},
            })

    groups, stale = group_findings(findings_rows or [], now)
    parked: List[Dict[str, Any]] = []
    for g in groups:
        item = classify_finding(g)
        (parked if item.pop("parked") else needs).append(item)

    needs = rank(needs)
    if needs and not any(i.get("featured") for i in needs):
        needs[0]["featured"] = True
    elif needs:
        # Only the first featured item is featured; the rest are rows.
        seen_featured = False
        for i in needs:
            if i.get("featured"):
                if seen_featured:
                    i["featured"] = False
                seen_featured = True
        needs.sort(key=lambda i: 0 if i.get("featured") else 1)

    # Pulse
    tr = traffic or {}
    funnel = tr.get("funnel") or []
    pulse = {
        "practitioners": (practitioners or {}).get("total"),
        "signed_in": (practitioners or {}).get("signed_in"),
        "businesses": businesses,
        "mrr_cents": (subs or {}).get("mrr_cents"),
        "active_subscriptions": ((subs or {}).get("by_status") or {}).get("active", 0) if subs else None,
        "payment_issues": len((subs or {}).get("payment_issues") or []) if subs else None,
        "views_30d": tr.get("views"), "visitors_30d": tr.get("sessions"),
        "applied_30d": next((f.get("sessions") for f in funnel
                             if "appl" in (f.get("step") or "").lower()), None),
        "ai_spend_today_cents": (spend or {}).get("today_cents"),
        "ai_daily_cap_cents": (spend or {}).get("cap_cents"),
        "coupons_active": (coupons or {}).get("active"),
        "coupon_redemptions": (coupons or {}).get("redemptions"),
    }

    # Overnight: agent runs + the watchdog's last sweep + server errors
    # bucketed into 15-minute bins from the in-process ring buffer.
    overnight = _overnight(runs or [], now)

    running = _running(runs or [], dev_tasks, findings_rows or [])

    ships: List[Dict[str, Any]] = []
    try:
        week_ago = (now - timedelta(days=7)).isoformat()
        ships = [s for s in await asyncio.wait_for(pc._recent_merged_prs(), SOURCE_TIMEOUT)
                 if (s.get("merged_at") or "") >= week_ago][:8]
    except Exception:
        failed.append("ships")

    return {
        "ok": True,
        "generated_at": now.isoformat(),
        "needs_you": needs,
        "parked": parked,
        "stale_findings": stale,
        "read": compose_read(needs, parked),
        "pulse": pulse,
        "traffic": {
            "by_day": tr.get("by_day") or [],
            "funnel": funnel,
            "referrers": (tr.get("referrers") or [])[:5],
            "devices": tr.get("devices") or [],
            "top_paths": (tr.get("top_paths") or [])[:5],
        } if traffic else None,
        "coupons": coupons,
        "overnight": overnight,
        "running": running,
        "shipped": ships,
        "coverage": coverage(),
        "sources_failed": sorted(set(failed)),
    }


async def _traffic(owner) -> Dict[str, Any]:
    from site_analytics import traffic_summary
    return await traffic_summary(days=30, _=owner)


def _anchor_health() -> Dict[str, Any]:
    import ledger_anchor
    return ledger_anchor.anchor_health(days=7, recent=1)


def _spend() -> Dict[str, Any]:
    import spend_guard
    return {"today_cents": round(spend_guard.today_spend_cents()),
            "cap_cents": round(spend_guard._cap_cents())}


def _overnight(runs: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    events = []
    for r in runs:
        at = _parse_ts(r.get("started_at"))
        if not at:
            continue
        events.append({"at": at.isoformat(), "agent": r.get("agent"),
                       "findings": r.get("findings") if isinstance(r.get("findings"), int)
                       else len(r.get("findings") or []) if isinstance(r.get("findings"), list) else 0,
                       "ok": r.get("ok") is not False, "summary": (r.get("summary") or "")[:140]})
    try:
        import platform_watchdog as wd
        snap = wd.LAST_SWEEP or {}
        if snap.get("ran_at"):
            events.append({"at": snap["ran_at"], "agent": "watchdog",
                           "findings": len(snap.get("findings") or []),
                           "ok": bool(snap.get("ok")), "summary": ""})
        start = now - timedelta(hours=3)
        bins: Dict[int, int] = {}
        for e in wd.recent_errors(400):
            if e.get("level") != "ERROR" or e.get("logger") == "client":
                continue
            at = _parse_ts(e.get("ts"))
            if at is None:
                try:
                    at = datetime.fromtimestamp(float(e.get("ts")), tz=timezone.utc)
                except (TypeError, ValueError):
                    continue
            if at < start:
                continue
            idx = int((at - start).total_seconds() // 900)
            bins[idx] = bins.get(idx, 0) + 1
        errors = [{"at": (start + timedelta(minutes=15 * i)).isoformat(), "count": bins.get(i, 0)}
                  for i in range(12)]
    except Exception:
        errors = []
    upcoming = []
    nxt = next_run([_parse_ts(e["at"]) for e in events if e["agent"] == "hermes"], now)
    if nxt:
        upcoming.append({"at": nxt.isoformat(), "agent": "hermes", "label": "Hermes runs"})
    brief = now.replace(hour=13, minute=0, second=0, microsecond=0)
    if brief <= now:
        brief += timedelta(days=1)
    upcoming.append({"at": brief.isoformat(), "agent": "push_morning_brief",
                     "label": "Morning brief to practitioners"})
    events.sort(key=lambda e: e["at"])
    return {"events": events[-40:], "errors": errors, "upcoming": upcoming}


def _running(runs: List[Dict[str, Any]], dev_tasks: Optional[List[Dict[str, Any]]],
             findings_rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    from platform_console import AGENT_REGISTRY
    last: Dict[str, Dict[str, Any]] = {}
    for r in runs:
        a = r.get("agent")
        if a and a not in last:
            last[a] = r
    try:
        import platform_watchdog as wd
        if (wd.LAST_SWEEP or {}).get("ran_at"):
            last.setdefault("watchdog", {"started_at": wd.LAST_SWEEP["ran_at"],
                                         "ok": wd.LAST_SWEEP.get("ok")})
    except Exception:
        pass
    if "watchdog" not in last:
        # The sweep runs in whichever process's scheduler fired it, so the
        # one serving this request often has no LAST_SWEEP and the
        # watchdog read "idle". Its newest written finding is the next
        # best evidence that it is running.
        for r in findings_rows or []:
            if (r.get("agent") or "").lower() == "watchdog" or (r.get("title") or "").lower().startswith("watchdog:"):
                last["watchdog"] = {"started_at": r.get("created_at"), "ok": True}
                break
    out = [{"id": "watchdog", "name": "Watchdog", "beat": "errors, keys, services",
            "last_at": (last.get("watchdog") or {}).get("started_at"),
            "ok": (last.get("watchdog") or {}).get("ok", True) is not False}]
    for a in AGENT_REGISTRY:
        if a.get("kind") == "brain":
            continue
        lr = last.get(a["id"]) or {}
        out.append({"id": a["id"], "name": a["name"], "beat": a.get("schedule") or "",
                    "last_at": lr.get("started_at"), "ok": lr.get("ok", True) is not False})
    if dev_tasks is not None:
        working = [t for t in dev_tasks if t.get("status") in ("working", "dispatched", "queued")]
        out.append({"id": "dev_desk", "name": "Dev Desk",
                    "beat": f"{len(working)} build{'s' if len(working) != 1 else ''} in flight",
                    "last_at": (working[0].get("updated_at") if working else None),
                    "ok": True, "count": len(working)})
    return out
