# sunday_serving_alerts.py — ChurchSavvy Planning, step 3: asks and reminders
# reach people (design canvas Ct88v7pxpq5a4PGYX3MuQQ, board 6 "Nobody forgets
# their Sunday" and board 8's "How I hear").
#
# Every 15 minutes (kmj_intake_automation "serving_alerts"), church by church,
# never between 9 PM and 7 AM on the church's own clock: a note that would
# land then waits for the first sweep after 7.
#   * the ask: the sweep after a leader asks sends it, so a month filled by
#     mistake can be taken back before anyone's phone buzzes; a Sunday more
#     than ASK_AHEAD_DAYS away waits until it's that close
#   * no answer in NUDGE_DAYS: one more ask, never a third
#   * still no answer OFFICE_DAYS before Sunday: the office hears, with who
#     else could take it (the team leader's own view comes with the Lead tab)
#   * someone asked to cover hears once for each ask
#   * a Sunday they said yes to: a week before, the day before after 6 PM,
#     and that morning when the call time is at least an hour off; a reminder
#     whose moment passed is skipped, never sent late
# Phone alerts are member_push kind "serving": the church's switch and the
# member's own box both decide. An email copy of every ask and of the day
# before goes to grown-ups who keep it (serve_prefs.email, on unless turned
# off), and to anyone the phone alert didn't reach: an ask always reaches
# them one way or another. The church's switch covers the email too.
#
# ChurchSavvy's "Email asks and reminders" (settings.churchsavvy.planning_email,
# Setup → Planning; canvas UZu4VsoY9KemkUGorz234j board 15) makes email a
# whole channel, for a church whose volunteers have no app: every step goes
# by email. Every serving email answers with one tap and no sign-in
# (serve_links: Yes, Can't, another Sunday; "See your Sunday"), and ends
# with "Stop these emails", which stops this church's serving emails and
# nothing else. Once someone stops them, nothing is emailed to them, not
# even an ask their phone missed.
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

import sb_clients
import sunday_planning as sp
import sunday_serving as sv
from sunday_planning import _ids, _q, _read

logger = logging.getLogger(__name__)

KIND = "serving"
ASK_AHEAD_DAYS = 21
NUDGE_DAYS = 2
OFFICE_DAYS = 5
WEEK_DAYS = 7
DAY_BEFORE_HOUR = 18
MORNING_HOUR = 7
EMAIL_STEPS = ("ask", "nudge", "cover", "day")
ALL_STEPS = ("ask", "nudge", "cover", "week", "day", "morning")   # an email church: email is the whole channel
ASK_STEPS = ("ask", "nudge", "cover")
_SELECT = ("id,service_id,position_id,slot,contact_id,status,asked_by,asked_at,answered_at,notified_at,nudged_at,"
           "leader_told_at,week_sent_at,day_sent_at,morning_sent_at,swap_to,swap_asked_at,swap_told_at")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _at(v: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _day(at: datetime) -> str:
    return f"{at.strftime('%b')} {at.day}"


def _clock(hhmm: Optional[str]) -> str:
    """"10:15" → "10:15", "18:00" → "6:00"; a church's call times are said
    the way people say them."""
    if not hhmm:
        return ""
    h, m = int(hhmm[:2]), hhmm[3:5]
    return f"{(h % 12) or 12}:{m}"


def _first(name: Optional[str]) -> str:
    return (name or "Someone").strip().split(" ")[0] or "Someone"


# ─── what's due ──────────────────────────────────────────────────────


def due(row: Dict[str, Any], at: datetime, now: datetime, zone, call: Optional[datetime]) -> List[str]:
    """The steps this row is due for right now, latest first; a reminder
    whose moment has passed comes back as "skip:<step>" so it's marked and
    never sent late."""
    out: List[str] = []
    if at <= now:
        return out
    here = now.astimezone(zone)
    sunday = at.astimezone(zone)
    if row["status"] == "asked" and row.get("contact_id"):
        told = _at(row.get("notified_at"))
        if not told and at - now <= timedelta(days=ASK_AHEAD_DAYS):
            out.append("ask")
        elif told and not row.get("nudged_at") and now - told >= timedelta(days=NUDGE_DAYS):
            out.append("nudge")
        # A late ask gets a day to be answered before the office hears.
        if (told and not row.get("leader_told_at") and at - now <= timedelta(days=OFFICE_DAYS)
                and now - told >= timedelta(days=1)):
            out.append("office")
    if row["status"] == "yes":
        if row.get("swap_to") and row.get("swap_asked_at") and not row.get("swap_told_at"):
            out.append("cover")
        morning = datetime.combine(sunday.date(), time(MORNING_HOUR), tzinfo=zone)
        eve = datetime.combine(sunday.date() - timedelta(days=1), time(DAY_BEFORE_HOUR), tzinfo=zone)
        week = at - timedelta(days=WEEK_DAYS)
        said = _at(row.get("answered_at")) or _at(row.get("asked_at")) or now
        if not row.get("morning_sent_at") and now >= morning:
            ok = call is None or call - now >= timedelta(hours=1)
            out.append("morning" if ok else "skip:morning")
        if not row.get("day_sent_at") and now >= eve:
            out.append("day" if here.date() < sunday.date() else "skip:day")
        if not row.get("week_sent_at") and now >= week:
            # A yes given inside the week already knows; the day before says it again.
            out.append("week" if now < eve and said < week else "skip:week")
    return out


# ─── saying it ───────────────────────────────────────────────────────


def words(step: str, ctx: Dict[str, Any]) -> Dict[str, str]:
    """(title, body) for one note. Board 6's own words where it has them;
    nothing private (why someone can't) ever goes on a lock screen."""
    place, day, call = ctx["place"], ctx["day"], ctx["call"]
    be_there = f"Be there by {call}. " if call else ""
    if step == "ask":
        return {"title": f"Can you serve on {place}, {day}?",
                "body": f"{ctx['asker']} asked. {be_there}Tap Yes or Can't."}
    if step == "nudge":
        return {"title": f"Can you serve on {place}, {day}?",
                "body": f"{ctx['asker']} is still hoping to hear. {be_there}Tap Yes or Can't."}
    if step == "cover":
        return {"title": f"Can you cover {place}, {day}?",
                "body": f"{ctx['from']} asked you to cover for them. {be_there}Tap Yes or Can't."}
    if step == "week":
        return {"title": f"Next Sunday you're on {place}", "body": f"{day}{f' · be there by {call}' if call else ''}."}
    if step == "day":
        on_with = ctx.get("with") or []
        body = (f"{sp_and(on_with)} {'is' if len(on_with) == 1 else 'are'} on with you." if on_with
                else f"{ctx['team']}, {ctx['title']}.")
        return {"title": f"Tomorrow: {place}, {ctx['time']}", "body": body}
    return {"title": f"Today: {place}, {ctx['time']}", "body": f"{ctx['team']}, {ctx['title']}. Thank you for serving."}


def sp_and(names: List[str]) -> str:
    names = [_first(n) for n in names]
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _claim(biz_id: str, row: Dict[str, Any], column: str, now: datetime) -> bool:
    """Mark one step said, only if nobody did: a second sweep, a take-back or
    a new answer in between all leave nothing to say."""
    who = row.get("swap_to") if column == "swap_told_at" else row.get("contact_id")
    guard = (f"&{column}=is.null&status=eq.{_q(row['status'])}"
             + (f"&swap_to=eq.{_q(who)}" if column == "swap_told_at" else f"&contact_id=eq.{_q(who)}"))
    got = sb_clients.sb_patch_as_service(
        f"/serve_assignments?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz_id)}{guard}&select=id",
        {column: now.isoformat()})
    return bool(got)


COLUMN = {"ask": "notified_at", "nudge": "nudged_at", "office": "leader_told_at", "cover": "swap_told_at",
          "week": "week_sent_at", "day": "day_sent_at", "morning": "morning_sent_at"}


def email_church(biz: Dict[str, Any]) -> bool:
    """ChurchSavvy's "Email asks and reminders" is on: email is the whole
    channel here."""
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    cs = settings.get("churchsavvy") if isinstance(settings.get("churchsavvy"), dict) else {}
    return cs.get("planning_email") is True


def tell(biz: Dict[str, Any], step: str, to: str, ctx: Dict[str, Any], person: Optional[Dict[str, Any]],
         email_ok: bool, app: Optional[str], stopped: bool = False) -> Dict[str, int]:
    import member_push
    w = words(step, ctx)
    url = f"/my/serving/{ctx['id']}" if step in ASK_STEPS else f"/my/serving/{ctx['id']}/pack"
    rang = member_push.send(biz, KIND, title=w["title"], body=w["body"], url=url, contact_ids=[to],
                            tag=f"serving-{ctx['id']}")
    mailed = 0
    steps = ALL_STEPS if email_church(biz) else EMAIL_STEPS
    if step in steps and person and not stopped and (email_ok or not rang):
        import group_email
        if group_email._adult(person):
            try:
                asyncio.run(_email(biz, person, step, w, f"{app}{url}" if app else None, ctx))
                mailed = 1
            except Exception:  # noqa: BLE001 — one address never stops the rest
                logger.warning("serving alerts: one email failed", exc_info=True)
    return {"rang": rang, "mailed": mailed}


def _ghost(label: str, url: str) -> str:
    """The second button (Can't this time): outlined, so Yes leads."""
    import html as _html
    e = _html.escape
    return ('<table role="presentation" cellpadding="0" cellspacing="0" style="margin:-12px 0 16px;">'
            '<tr><td style="border-radius:10px;border:1.5px solid #cbd0e0;">'
            f'<a href="{e(url)}" style="display:inline-block;padding:13px 26px;font-family:Arial,Helvetica,sans-serif;'
            f'font-size:16px;font-weight:700;line-height:1;color:#0a1033;text-decoration:none;border-radius:10px;">'
            f'{e(label)}</a></td></tr></table>')


def _text_link(label: str, url: str) -> str:
    import html as _html
    e = _html.escape
    return (f'<p style="margin:0 0 20px;font-family:Arial,Helvetica,sans-serif;font-size:14px;">'
            f'<a href="{e(url)}" style="color:#1d45f2;font-weight:600;text-decoration:none;">{e(label)}</a></p>')


def email_parts(biz: Dict[str, Any], person: Dict[str, Any], step: str, w: Dict[str, str], app_link: Optional[str],
                ctx: Dict[str, Any]) -> Dict[str, Any]:
    """The words and the links of one serving email (board 12): Yes leads,
    Can't under it, then "another Sunday"; a reminder opens their Sunday.
    Every link is signed for this person and works without signing in."""
    import serve_links
    church = (biz.get("name") or "").strip() or "Your church"
    biz_id, cid = str(biz["id"]), str(person["id"])
    t = serve_links.answer_token(biz_id, cid, ctx["id"], ctx["at"])
    stop = serve_links.stop_token(biz_id, cid)
    body = w["body"].replace(" Tap Yes or Can't.", "").replace("Tap Yes or Can't.", "")
    if step in ASK_STEPS:
        cta = ("Yes, I'm in", serve_links.page_url(t, ans="yes"))
        after = (_ghost("Can't this time", serve_links.page_url(t, ans="no"))
                 + _text_link("Can't that day, but I could do another", serve_links.page_url(t, ans="other")))
    else:
        cta = ("See your Sunday", serve_links.page_url(t))
        after = ""
    if app_link:
        after += _text_link(f"Or open it in {church}'s app", app_link)
    return {"message": "\n\n".join([w["title"], body]), "cta": cta, "after": after,
            "stop_page": serve_links.page_url(stop, stop="1"), "one_click": serve_links.one_click_url(stop),
            "disclaimer": f"You serve on the {ctx['team']} team at {church}.", "church": church, "preheader": body[:90]}


async def _email(biz: Dict[str, Any], person: Dict[str, Any], step: str, w: Dict[str, str], link: Optional[str],
                 ctx: Dict[str, Any]) -> None:
    import os
    import academy_join
    import email_layout
    import email_sender
    email = str(person.get("email") or "").strip()
    if not academy_join.valid_email(email):
        return
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    p = email_parts(biz, person, step, w, link, ctx)
    html = email_layout.render_html(
        p["message"], business_name=p["church"], brand=email_layout.brand_of(settings), sig=None,
        unsubscribe_url=p["stop_page"], unsubscribe_label="Stop these emails", preheader=p["preheader"],
        cta=p["cta"], after_cta=p["after"], disclaimer=p["disclaimer"], footer_note="Sent with ChurchSavvy")
    await email_sender.send_via_resend(
        to_email=email, to_name=person.get("name") or None,
        from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
        from_name=p["church"], subject=w["title"][:150], body=html, reply_to=None,
        business_id=str(biz["id"]), idempotency_key=f"serving-{step}-{ctx['id']}-{person['id']}",
        unsubscribe_url=p["one_click"])


async def _office(biz_id: str, title: str, body: str, key: str, person_id: Optional[str]) -> bool:
    try:
        import httpx
        import notification_engine
        async with httpx.AsyncClient(timeout=20) as client:
            await notification_engine.create_urgent_alert(
                client, biz_id, title, body, dedup_key=key, dedup_hours=24 * 7,
                suggested_action="Open Who serves when", related_contact_id=person_id)
        return True
    except Exception:
        logger.warning("serving alerts: office alert failed for business %s", biz_id[:8], exc_info=True)
        return False


# ─── the sweep ───────────────────────────────────────────────────────


def _churches() -> List[Dict[str, Any]]:
    """Churches that switched Serving on in the member app, and churches
    that switched on ChurchSavvy's "Email asks and reminders"."""
    out: Dict[str, Dict[str, Any]] = {}
    for where in (f"settings->member_portal->notifications->>{KIND}=eq.true",
                  "settings->churchsavvy->>planning_email=eq.true"):
        for b in sb_clients.sb_get_as_service(f"/businesses?{where}&select=id,name,settings,owner_id&limit=5000") or []:
            out[str(b["id"])] = b
    return list(out.values())


def church_tick(biz: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, int]:
    import group_email
    import member_push
    out = {"asks": 0, "nudges": 0, "covers": 0, "reminders": 0, "office": 0, "emails": 0}
    now = now or _now()
    if member_push.quiet_hour(biz, now):
        return out
    biz_id = str(biz["id"])
    zone = sp._zone(biz_id)
    services = sv._services(biz_id, zone, now, now + timedelta(days=ASK_AHEAD_DAYS + 1))
    if not services:
        return out
    rows = _read(f"/serve_assignments?business_id=eq.{_q(biz_id)}&service_id=in.({_ids(services)})"
                 f"&status=in.(asked,yes)&select={_SELECT}")
    if not rows:
        return out
    teams, _ = sp._teams(biz_id)
    place = {p["id"]: (p, t) for t in teams for p in t["places"]}
    work = []
    for r in rows:
        s = services.get(str(r["service_id"]))
        pt = place.get(str(r["position_id"]))
        if not s or not pt:
            continue
        p, t = pt
        hhmm = sp._hhmm(t.get("call_time"))
        call = (datetime.combine(s["at"].date(), time(int(hhmm[:2]), int(hhmm[3:5])), tzinfo=zone) if hhmm else s["at"])
        steps = due(r, s["at"], now, zone, call)
        if steps:
            work.append((r, s, p, t, hhmm, steps))
    if not work:
        return out
    ids = {str(r["contact_id"]) for r, *_ in work} | {str(r["swap_to"]) for r, *_ in work if r.get("swap_to")}
    people = {str(c["id"]): c for c in (group_email._people(biz_id, sorted(ids)) or [])}
    prefs = {str(x["contact_id"]): x for x in _read(
        f"/serve_prefs?business_id=eq.{_q(biz_id)}&contact_id=in.({_ids(ids)})&select=contact_id,email,email_stopped_at")}
    app = group_email.app_url(biz_id)
    for r, s, p, t, hhmm, steps in work:
        leaders = [x["name"] for x in t["people"] if x.get("leader")]
        asker = r.get("asked_by") or ""
        if not asker or asker == sp.FILLED_BY:
            asker = _first(leaders[0]) if leaders else ((biz.get("name") or "").strip() or "The church")
        ctx = {"id": str(r["id"]), "at": s["at"], "place": p["name"], "team": t["name"], "title": s["title"],
               "day": _day(s["at"]), "call": _clock(hhmm), "time": _clock(hhmm or s["at"].strftime("%H:%M")),
               "asker": asker,
               "from": _first((people.get(str(r["contact_id"])) or {}).get("name"))}
        if "day" in steps:
            ctx["with"] = [x for x in _with(biz_id, r, t, people) if x]
        for step in steps:
            skip = step.startswith("skip:")
            name = step[5:] if skip else step
            if not _claim(biz_id, r, COLUMN[name], now) or skip:
                continue
            if name == "office":
                if asyncio.run(_office_note(biz_id, r, s, p, people)):
                    out["office"] += 1
                continue
            to = str(r["swap_to"]) if name == "cover" else str(r["contact_id"])
            pref = prefs.get(to) or {}
            sent = tell(biz, name, to, ctx, people.get(to), pref.get("email") is not False, app,
                        stopped=bool(pref.get("email_stopped_at")))
            out["emails"] += sent["mailed"]
            key = {"ask": "asks", "nudge": "nudges", "cover": "covers"}.get(name, "reminders")
            out[key] += 1
    return out


def _with(biz_id: str, row: Dict[str, Any], team: Dict[str, Any], people: Dict[str, Dict[str, Any]]) -> List[str]:
    """The others on the same team that Sunday: "Luis and Marcus are on with you"."""
    pids = [p["id"] for p in team["places"]]
    rows = _read(f"/serve_assignments?business_id=eq.{_q(biz_id)}&service_id=eq.{_q(row['service_id'])}"
                 f"&position_id=in.({_ids(pids)})&status=eq.yes&select=contact_id")
    others = [str(x["contact_id"]) for x in rows if str(x.get("contact_id")) != str(row["contact_id"])]
    names = sp._people(biz_id, others)
    return [names[c]["name"] for c in others if c in names]


async def _office_note(biz_id: str, row: Dict[str, Any], svc: Dict[str, Any], place: Dict[str, Any],
                       people: Dict[str, Dict[str, Any]]) -> bool:
    who = _first((people.get(str(row["contact_id"])) or {}).get("name"))
    try:
        board = sp._Board(biz_id, svc["day"], 1, month_reach=True)
        others = [c["name"] for c in board.candidates(str(row["service_id"]), str(row["position_id"]))
                  if c["ok"] and c["trained"] == "trained" and c["contact_id"] != str(row["contact_id"])][:3]
    except Exception:  # noqa: BLE001 — the note still goes, without names
        others = []
    could = (f" {sp_and(others)} could take it." if others else "")
    return await _office(biz_id, f"No answer yet: {place['name']}, {_day(svc['at'])}",
                         f"{who} hasn't answered.{could}", f"serving-office-{row['id']}-{row['contact_id']}",
                         str(row["contact_id"]))


def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Every 15 minutes, across churches that switched Serving on."""
    out: Dict[str, int] = {}
    if sp.mode() == "off":
        return out
    for biz in _churches():
        try:
            for k, v in church_tick(biz, now).items():
                out[k] = out.get(k, 0) + v
        except Exception:
            logger.warning("serving alerts: one church failed", exc_info=True)
    return out
