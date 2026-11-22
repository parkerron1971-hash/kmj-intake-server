"""
member_plan_prefs.py — read a plan with your group, and a reminder at your hour.

The last step of Kevin's approved Plans design (2026-11-21, "go ahead"):
"Read it with your group: pick a group when you start; the day's 'together'
question lands in that group's chat" and "a reminder at the hour you choose".
A member keeps both choices per plan in member_plan_prefs
(supabase/APPLY-2026-11-21-member-plan-prefs.sql). Until that file is applied
the table isn't there, and everything here is quietly absent: no read-with
row, no Remind me, no "Send to <group>", no sweep; every page as before
(Postgres 42P01 / PostgREST PGRST205 is kept as "not applied yet" for
MISSING_SECONDS, member_moments' rule).

    POST /my/bible/plans/with     form {plan, group}  read it with this group
                                  ('' = on my own)
    POST /my/bible/plans/remind   form {plan, at}     remind me at HH:MM on
                                  the church's clock ('' = no reminder)
    remind_tick()                 every quarter hour: today's reminders

Both routes: the member's session, same-site (member_portal._same_origin),
the member-action rate limit, a plan the member can read, a group that is one
of theirs with its chat open to them (member_lumen_watch.talk_groups), a time
on a quarter hour outside the church's quiet hours; only the member's own
row. Nothing is posted to any chat: "Send to <group>" opens the group's chat
with the question in the box (member_portal_messaging's ?say=), and the
member sends it or not, under the chat's own rules.

Reads on member pages, all kept (member_cache.Kept): the member's choices
MEMBER_SECONDS per member, keyed with the plans version on their phone
(member_lumen_plans.VERSION_COOKIE, which a save changes), and how many of a
group read a plan with it GROUP_SECONDS per group and plan.

The reminder (remind_tick): a member asked for it, on the plan's page, so it
isn't a note on the church's behalf and needs no church switch of its own.
It goes only where the church's member app sends alerts at all
(member_push.ready and at least one kind switched on), only to a member who
hasn't turned every alert off, never in the church's quiet hours (such a time
isn't offered), only on a day the plan is running and today's day isn't read
yet, at most once a day (reminded_on, claimed before it sends), to the phones
where the member turned alerts on. PLAN_REMINDERS=off stops it.
"""
from __future__ import annotations

import logging
import os
import re
import time as clock
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import sb_clients

logger = logging.getLogger("member_plan_prefs")
router = APIRouter(tags=["member-portal"])

MISSING_SECONDS = 300.0
MEMBER_SECONDS = 30.0
GROUP_SECONDS = 60.0
TABLE = "member_plan_prefs"
# How long after its time a reminder may still go (a late tick, a busy loop).
LATE_MINUTES = 45
_PLAN = re.compile(r"(reading:[a-z0-9-]{1,40}|devotional:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
_AT = re.compile(r"([01][0-9]|2[0-3]):(00|15|30|45)")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


# ─── is the table there ──────────────────────────────────────────────

_STATE = {"missing_until": 0.0}


def _no_table(err: Optional[Dict[str, Any]]) -> bool:
    if not err:
        return False
    code = str(err.get("code") or "")
    return code in ("42P01", "PGRST205") or "42P01" in str(err.get("message") or "") \
        or (err.get("status") == 404 and code.startswith("PGRST"))


def missing() -> bool:
    return clock.monotonic() < _STATE["missing_until"]


def _saw(rows: Any) -> None:
    if rows is not None:
        return
    try:
        err = sb_clients.last_error()
    except Exception:  # noqa: BLE001  (a fake client says nothing)
        err = None
    if isinstance(err, dict) and _no_table(err):
        _STATE["missing_until"] = clock.monotonic() + MISSING_SECONDS


def _read(path: str) -> Optional[Any]:
    if missing():
        return None
    rows = sb_clients.sb_get_as_service(path)
    _saw(rows)
    return rows


# ─── kept reads ──────────────────────────────────────────────────────

_MINE = None
_GROUPS = None


def _stores():
    global _MINE, _GROUPS
    if _MINE is None:
        import member_cache
        _MINE = member_cache.Kept("plan_prefs", MEMBER_SECONDS)
        _GROUPS = member_cache.Kept("plan_prefs_groups", GROUP_SECONDS)
    return _MINE, _GROUPS


def forget_everything() -> None:
    """For the tests (conftest)."""
    if _MINE is not None:
        _MINE.clear()
        _GROUPS.clear()
    _STATE["missing_until"] = 0.0


def mine(business_id: Any, contact_id: Any, ver: str = "") -> Optional[Dict[str, Dict[str, Any]]]:
    """{plan: {"group_id", "remind_at" ("HH:MM" or None)}} for the member,
    or None (the table isn't there yet, or the read failed: leave the rows
    out). Kept MEMBER_SECONDS, keyed with the phone's plans version."""
    m, _ = _stores()
    key = (str(business_id), str(contact_id), ver)
    hit, got = m.get(key)
    if hit:
        return got
    rows = _read(f"/{TABLE}?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}"
                 "&select=plan,group_id,remind_at&limit=200")
    if not isinstance(rows, list):
        return None
    out = {str(r["plan"]): {"group_id": str(r["group_id"]) if r.get("group_id") else None,
                            "remind_at": str(r["remind_at"])[:5] if r.get("remind_at") else None} for r in rows}
    m.put(key, out, tag=f"{business_id}|{contact_id}")
    return out


def reading_with(business_id: Any, group_id: Any, plan: str) -> Optional[int]:
    """How many of the group read this plan with it (the member among them),
    or None. Kept GROUP_SECONDS per group and plan."""
    _, g = _stores()
    key = (str(business_id), str(group_id), plan)
    hit, got = g.get(key)
    if hit:
        return got
    rows = _read(f"/{TABLE}?business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}&plan=eq.{_q(plan)}"
                 "&select=contact_id&limit=2000")
    if not isinstance(rows, list):
        return None
    g.put(key, len(rows), tag=str(business_id))
    return len(rows)


def forget(business_id: Any, contact_id: Any) -> None:
    m, g = _stores()
    tag = f"{business_id}|{contact_id}"
    m.forget(lambda _k, t: t == tag)
    g.forget(lambda _k, t: t == str(business_id))


def save(business_id: str, contact_id: str, plan: str, change: Dict[str, Any]) -> bool:
    """Merge one change ({"group_id"} or {"remind_at"}) into the member's
    row for the plan, keeping the other choice."""
    now = sb_clients.sb_get_as_service(
        f"/{TABLE}?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}&plan=eq.{_q(plan)}"
        "&select=group_id,remind_at&limit=1")
    _saw(now)
    if not isinstance(now, list):
        return False
    row = {"group_id": None, "remind_at": None, **(now[0] if now else {})}
    row.update(change)
    rows = sb_clients.sb_post_as_service(
        f"/{TABLE}?on_conflict=business_id,contact_id,plan",
        {"business_id": business_id, "contact_id": contact_id, "plan": plan, "group_id": row["group_id"],
         "remind_at": row["remind_at"], "updated_at": datetime.now(timezone.utc).isoformat()},
        prefer="return=representation,resolution=merge-duplicates")
    return isinstance(rows, list) and bool(rows)


# ─── the hours a reminder may be set to ──────────────────────────────


def hours_open(business: Dict[str, Any]) -> List[str]:
    """The quarter hours outside the church's quiet hours, "HH:MM"."""
    import member_push
    return [f"{h:02d}:{m:02d}" for h in range(24) if not member_push.is_quiet_hour(h, business) for m in (0, 15, 30, 45)]


def say_time(at: str) -> str:
    """'19:30' → '7:30 PM'."""
    h, m = int(at[:2]), int(at[3:5])
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


# ─── on the pages ────────────────────────────────────────────────────


def choices(biz: Dict[str, Any], me: Dict[str, Any], request: Any, plan: str, *, preview: bool = False):
    """What a plan's page and its day need: (the member's choice for this
    plan or {}, their groups to read with, the group they read it with or
    None); None when the table isn't there yet or a read failed (the rows are
    left out)."""
    import member_lumen_plans as mlp
    import member_lumen_watch as mlw
    if preview:
        return None
    got = mine(biz["id"], me["id"], mlp.version(request))
    if got is None:
        return None
    pick = got.get(plan) or {}
    groups = mlw.talk_groups(biz, me)
    with_g = next((g for g in groups if g["id"] == pick.get("group_id")), None)
    return pick, groups, with_g


def rows_html(biz: Dict[str, Any], plan: str, got, *, started: bool) -> str:
    """The plan page's Remind me and who you read with (screen 2), as forms
    that work without script. '' when there is nothing to show."""
    import member_lumen_ui as lm
    if not got:
        return ""
    pick, groups, with_g = got
    at = pick.get("remind_at")
    opts = "".join(f'<option value="{h}"{" selected" if h == at else ""}>{say_time(h)}</option>'
                   for h in hours_open(biz))
    remind = (f'<form class="lm-pp-opt" method="post" action="/my/bible/plans/remind"><input type="hidden" name="plan" '
              f'value="{plan}"><span class="lm-pp-optt"><b>Remind me</b><small>'
              f'{("Every day at " + say_time(at)) if at else "An alert on your phone at the hour you pick"}</small></span>'
              f'<label class="mp-sr" for="lm-pp-at">Remind me at</label><select id="lm-pp-at" name="at">'
              f'<option value=""{" selected" if not at else ""}>Off</option>{opts}</select>'
              f'<button class="lm-btn sm ghost" type="submit">Save</button></form>') if started else ""
    chips = ""
    if groups:
        cur = with_g["id"] if with_g else ""
        btn = (lambda gid, name: f'<button type="submit" name="group" value="{gid}" aria-pressed="{"true" if gid == cur else "false"}">'
               f'{lm._e(name)}</button>')
        chips = (f'<form class="lm-pp-with" method="post" action="/my/bible/plans/with"><input type="hidden" name="plan" '
                 f'value="{plan}"><p class="lm-pp-wk">Read it with</p><div class="lm-pp-chips">{btn("", "On my own")}'
                 + "".join(btn(g["id"], g["name"]) for g in groups) + "</div></form>")
    return remind + chips


def together_line(biz: Dict[str, Any], plan: str, with_g: Optional[Dict[str, Any]], count: Optional[int]) -> str:
    """The Plans tab's line under Continue: "<group> is reading this" and
    how many, only from what was read."""
    import member_lumen_ui as lm
    if not with_g:
        return ""
    name = lm._e(with_g["name"])
    head = f"{name} is reading this · {count} of you" if count and count > 1 else f"You're reading this with {name}"
    return (f'<a class="lm-pl-tog" href="/my/groups/{lm._e(with_g["id"])}/chat">{lm.ic("people", 20)}<span><b>'
            f'{head}</b><small>The day\'s question goes to your group\'s chat when you send it</small></span></a>')


def send_button(with_g: Optional[Dict[str, Any]], question: str) -> str:
    """"Send to <group>": the group's chat, the question in the box, unsent."""
    import member_lumen_ui as lm
    import member_portal_messaging as mpm
    if not with_g or not question:
        return ""
    href = mpm.with_say(f"/my/groups/{with_g['id']}/chat", question[:mpm.SAY_MAX])
    return f'<a class="lm-dy-send" href="{lm._e(href)}">{lm.ic("people", 16)}Send to {lm._e(with_g["name"])}</a>'


# ─── the routes ──────────────────────────────────────────────────────


async def _member_write(request: Request, field: str):
    """The checks both routes share: (church, me, plan, value, back) or a
    response to return."""
    import asyncio
    import member_lumen_plans as mlp
    import member_portal as mp
    import member_portal_church as mpc
    import member_portal_devotionals as mpd
    from member_portal import _SECURE_HEADERS
    form = await request.form()
    plan = str(form.get("plan") or "")
    value = str(form.get(field) or "")
    if not _PLAN.fullmatch(plan):
        return RedirectResponse("/my/bible?tab=plans", status_code=303, headers=_SECURE_HEADERS)
    key = plan.split(":", 1)[1]
    if plan.startswith("reading:") and not mlp.meta(key):
        return RedirectResponse("/my/bible?tab=plans", status_code=303, headers=_SECURE_HEADERS)
    back = f"/my/bible/plans/{key}"

    def go(**q: str) -> RedirectResponse:
        qs = "&".join(f"{k}={v}" for k, v in q.items())
        return RedirectResponse(back + (f"?{qs}" if qs else ""), status_code=303, headers=_SECURE_HEADERS)
    if not mp._same_origin(request):
        return go(err="error")
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return go(err="preview" if unavailable == "preview" else "error")
    if not me:
        return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    if plan.startswith("devotional:"):
        import devotionals as dv
        dev, ok = await asyncio.to_thread(dv.one, church["business"]["id"], key)
        if not ok:
            return go(err="error")
        if not dev:
            return RedirectResponse("/my/bible?tab=plans", status_code=303, headers=_SECURE_HEADERS)
    if not mpc._allowed(church, me):
        return go(err="slow")
    return church, me, plan, value, go


@router.post("/my/bible/plans/with", include_in_schema=False)
async def read_with(request: Request):
    """Read this plan with one of my groups, or on my own."""
    import asyncio
    import member_lumen_watch as mlw
    got = await _member_write(request, "group")
    if not isinstance(got, tuple):
        return got
    church, me, plan, gid, go = got
    biz = church["business"]
    if gid:
        groups = await asyncio.to_thread(mlw.talk_groups, biz, me)
        if not _UUID.fullmatch(gid) or gid not in {g["id"] for g in groups}:
            return go(err="error")
    if not await asyncio.to_thread(save, str(biz["id"]), str(me["id"]), plan, {"group_id": gid or None}):
        return go(err="error")
    import member_portal_devotionals as mpd
    forget(biz["id"], me["id"])
    return mpd._wrote(go(done="with"), biz["id"], me["id"])


@router.post("/my/bible/plans/remind", include_in_schema=False)
async def remind(request: Request):
    """Remind me every day at this time (the church's clock), or not."""
    import asyncio
    got = await _member_write(request, "at")
    if not isinstance(got, tuple):
        return got
    church, me, plan, at, go = got
    biz = church["business"]
    if at and (not _AT.fullmatch(at) or at not in hours_open(biz)):
        return go(err="error")
    if not await asyncio.to_thread(save, str(biz["id"]), str(me["id"]), plan, {"remind_at": at or None}):
        return go(err="error")
    import member_portal_devotionals as mpd
    forget(biz["id"], me["id"])
    return mpd._wrote(go(done="remind" if at else "remind_off"), biz["id"], me["id"])


# ─── the reminder sweep ──────────────────────────────────────────────


def _due(at: str, local: datetime) -> bool:
    """Whether a reminder at `at` ("HH:MM") goes now: from its time to
    LATE_MINUTES after it."""
    start = datetime.combine(local.date(), time(int(at[:2]), int(at[3:5])), tzinfo=local.tzinfo)
    return start <= local < start + timedelta(minutes=LATE_MINUTES)


def _today_day(business_id: str, contact_id: str, plan: str, started: Optional[date], today: date,
               devs: Dict[str, Any]) -> Optional[Tuple[int, str, str, str]]:
    """(day number, the plan's title, the day's title, its address) when the
    plan runs today and today's day isn't read yet; else None."""
    import devotionals as dv
    import member_lumen_plans as mlp
    import member_portal_devotionals as mpd
    import reading_plans as rp
    kind, key = plan.split(":", 1)
    if kind == "reading":
        p = mlp.own(key, started)
        n = rp.day_number(p, today) if p else None
        if not n:
            return None
        done = rp.read_days(business_id, contact_id, p)
        if done is None or n in done:
            return None
        m = mlp.meta(key) or {}
        return n, m.get("title") or p["title"], mlp.day_title(key, n), f"/my/bible/plans/{key}/{n}"
    if key not in devs:
        devs[key] = dv.one(business_id, key)[0]
    dev = devs[key]
    if not dev:
        return None
    days = mpd.progress(business_id, contact_id, key)
    if days is None:
        return None
    st = mpd.state(dev, None if dev.get("starts_on") else started, {d for d, r in days.items() if r.get("done_at")}, today)
    n = st["now"]
    if st["kind"] != "running" or not n or n in st["done"]:
        return None
    day = (dev.get("days") or [{}])[n - 1] if len(dev.get("days") or []) >= n else {}
    return n, dev.get("title") or "your devotional", (day.get("title") or f"Day {n}").strip(), f"/my/bible/plans/{key}/{n}"


def _claim(business_id: str, contact_id: str, plan: str, today: date) -> bool:
    got = sb_clients.sb_patch_as_service(
        f"/{TABLE}?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}&plan=eq.{_q(plan)}"
        f"&or=(reminded_on.is.null,reminded_on.lt.{today.isoformat()})", {"reminded_on": today.isoformat()})
    return isinstance(got, list) and bool(got)


def _silenced(business: Dict[str, Any], contact_id: str) -> Optional[bool]:
    """Whether the member turned off every alert the church sends (None: unknown)."""
    import member_push
    offered = member_push.church_kinds(business.get("settings")) - set(member_push.OWN_PAGE_KINDS)
    off = member_push.turned_off(str(business["id"]), contact_id)
    if off is None:
        return None
    return bool(offered) and offered <= set(off)


def remind_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Today's reminders, for every church: each to the phones of a member
    whose time has come, at most once a day. Never raises."""
    out = {"due": 0, "sent": 0}
    try:
        return _remind_tick(now or datetime.now(timezone.utc), out)
    except Exception:  # noqa: BLE001
        logger.warning("plan reminders: sweep failed", exc_info=True)
        return out


def _remind_tick(now: datetime, out: Dict[str, int]) -> Dict[str, int]:
    import business_marketing
    import member_push
    import member_portal_devotionals as mpd
    import push_notifications as pn
    import sample_church
    if (os.environ.get("PLAN_REMINDERS") or "on").strip().lower() == "off" or not member_push.ready():
        return out
    rows = _read(f"/{TABLE}?remind_at=not.is.null&select=business_id,contact_id,plan,remind_at,reminded_on&limit=5000")
    if not isinstance(rows, list) or not rows:
        return out
    by_church: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_church.setdefault(str(r["business_id"]), []).append(r)
    for bid, people in by_church.items():
        got = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(bid)}&select=id,name,settings,owner_id,is_sample&limit=1")
        if not isinstance(got, list) or not got:
            continue
        business = got[0]
        if sample_church.skip(business):
            continue
        if not (member_push.church_kinds(business.get("settings")) - set(member_push.OWN_PAGE_KINDS)):
            continue
        try:
            local = now.astimezone(business_marketing.business_tz(business))
        except Exception:  # noqa: BLE001  (no clock to read: nothing goes)
            continue
        if member_push.is_quiet_hour(local.hour, business):
            continue
        today = local.date()
        due = [r for r in people if r.get("remind_at") and _due(str(r["remind_at"])[:5], local)
               and str(r.get("reminded_on") or "") != today.isoformat()]
        if not due:
            continue
        devs: Dict[str, Any] = {}
        for r in due:
            cid, plan = str(r["contact_id"]), str(r["plan"])
            out["due"] += 1
            starts = mpd.starts(bid, cid)
            if starts is None or (plan.startswith("reading:") and plan not in starts):
                continue
            day = _today_day(bid, cid, plan, starts.get(plan), today, devs)
            if not day or _silenced(business, cid) is not False:
                continue
            if not _claim(bid, cid, plan, today):
                continue
            n, title, name, url = day
            subs = sb_clients.sb_get_as_service(
                f"/member_push_subscriptions?business_id=eq.{_q(bid)}&contact_id=eq.{_q(cid)}"
                "&select=id,contact_id,endpoint,subscription&limit=20") or []
            payload = {"title": (business.get("name") or "Your church")[:member_push.TITLE_MAX],
                       "body": f"Day {n} of {title} is ready: {name}"[:member_push.BODY_MAX],
                       "url": url, "tag": f"plan-{plan}"[:60]}
            for s in subs:
                if pn._send_one(s, payload, table="member_push_subscriptions"):
                    out["sent"] += 1
    print(f"[plan reminders] due {out['due']}, sent {out['sent']}", flush=True)
    return out
