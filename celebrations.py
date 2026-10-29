"""
celebrations.py — birthdays, anniversaries and milestones in the church's news.

Kevin, 2026-10-23: "Build a celebration of members: Birthdays, Anniversary,
Achievements. A notification setup and a thread like Facebook where people
can say congratulations etc... we can use that as like a church news
thread." Part 3 of the approved canvas "Church News & Celebrations"
(Hfrz3Y174kbDmJv1G4puVq), and his call the same day: ask each member first.

  Who is celebrated
    * a birthday: the member said yes (member_celebrations.birthday), or the
      church chose "everyone unless they say no" (settings.news.celebrate =
      'all') and the member didn't say no. The day only, never the year or
      an age. A record with no birthdate takes a month and day from the
      member (birthday_md), never a guessed year.
    * an anniversary: BOTH spouses said yes (member_anniversaries).
    * a milestone: finishing a class, for a member who said yes to
      milestones; Chief writes it and a pastor or admin posts it (the office's
      Waiting for you). Nothing about a person goes up on its own.
    * nobody the office stopped (stopped = 'passed' when someone has died:
      their birthday and every anniversary of theirs stop, so a spouse is
      never shown an anniversary alone).
    * children aren't celebrated: a child has no member record to say yes.

  Each morning (sweep_tick, every 30 minutes; once a church's clock passes
  7 AM) the day's celebrations become posts: kind 'celebration', the person
  (and for an anniversary the other spouse), the day (celebrate_on), at 7 AM
  on the church's clock. One per person, kind and day (a unique index), so a
  second run changes nothing. Wishes are the post's comments, checked like
  every comment (church_news.comment).

Office API (any seat reads; a seat that edits acts; an admin sets):
  GET  /church/news/celebrations             this week's, what's on file, milestones waiting
  POST /church/news/celebrations/settings    ask members / everyone unless they say no / milestones
  POST /church/news/celebrations/milestone   post a milestone, or skip it
  POST /church/news/celebrations/week        "This week we celebrate", for Sunday at 7 AM
  POST /church/news/celebrations/stop        stop celebrating someone (they passed away, or asked)
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("celebrations")
router = APIRouter(tags=["church-news"])

MORNING = time(7, 0)
MILESTONE_DAYS = 30
MD = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ids(xs) -> str:
    return ",".join(_q(x) for x in sorted({str(x) for x in xs if x}))


def news_settings(business: Dict[str, Any]) -> Dict[str, Any]:
    s = (business or {}).get("settings") or {}
    news = s.get("news") if isinstance(s, dict) and isinstance(s.get("news"), dict) else {}
    return {"celebrate": "all" if news.get("celebrate") == "all" else "ask",
            "ask_members": bool(news.get("ask_members")),
            "milestone_classes": news.get("milestone_classes") is not False}


def local_now(business: Dict[str, Any], now: Optional[datetime] = None) -> datetime:
    import group_gatherings as gg
    now = now or _now()
    tz = gg.zone(business)
    return now.astimezone(tz) if tz is not None else now


def _md_of(birthdate: Any, md: Any) -> Optional[Tuple[int, int]]:
    if birthdate:
        try:
            d = date.fromisoformat(str(birthdate)[:10])
            return d.month, d.day
        except ValueError:
            pass
    if md and MD.match(str(md)):
        m, d = str(md).split("-")
        return int(m), int(d)
    return None


def falls_on(md: Optional[Tuple[int, int]], day: date) -> bool:
    """A Feb 29 day is celebrated on Feb 28 in a year without one."""
    if not md:
        return False
    m, d = md
    if (m, d) == (day.month, day.day):
        return True
    if (m, d) == (2, 29) and (day.month, day.day) == (2, 28):
        try:
            date(day.year, 2, 29)
            return False
        except ValueError:
            return True
    return False


# ─── who ─────────────────────────────────────────────────────────────


def prefs(business_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/member_celebrations?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}"
        f"&select=birthday,birthday_md,milestones,answered_at,stopped&limit=1")
    if rows is None:
        return None
    return rows[0] if rows else {"birthday": None, "birthday_md": None, "milestones": False, "answered_at": None, "stopped": None}


def save_prefs(business_id: str, contact_id: str, **changes: Any) -> bool:
    row = {"business_id": str(business_id), "contact_id": str(contact_id), "updated_at": _now().isoformat(), **changes}
    ok = sb_clients.sb_post_as_service("/member_celebrations?on_conflict=business_id,contact_id", row,
                                       prefer="resolution=merge-duplicates,return=representation")
    return ok is not None


def anniversaries_of(business_id: str, contact_id: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(
        f"/member_anniversaries?business_id=eq.{_q(business_id)}&or=(a_id.eq.{_q(contact_id)},b_id.eq.{_q(contact_id)})"
        f"&select=id,a_id,b_id,married_on,a_yes,b_yes,show_years&limit=5")
    return rows


def spouses_for(business_id: str, contact_id: str) -> Optional[List[Dict[str, Any]]]:
    """The other adults in this member's household: who an anniversary can be with."""
    mine = sb_clients.sb_get_as_service(
        f"/household_adults?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}&select=household_id&limit=10")
    if mine is None:
        return None
    if not mine:
        return []
    others = sb_clients.sb_get_as_service(
        f"/household_adults?business_id=eq.{_q(business_id)}&household_id=in.({_ids(m['household_id'] for m in mine)})"
        f"&contact_id=neq.{_q(contact_id)}&select=contact_id&limit=20")
    if others is None:
        return None
    if not others:
        return []
    people = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{_q(business_id)}&id=in.({_ids(o['contact_id'] for o in others)})&select=id,name,birthdate")
    if people is None:
        return None
    import member_messaging_rules as rules
    return [p for p in people if (rules.age(p.get("birthdate")) or 99) >= 18]


def _stopped(business_id: str) -> Optional[set]:
    rows = sb_clients.sb_get_as_service(
        f"/member_celebrations?business_id=eq.{_q(business_id)}&stopped=not.is.null&select=contact_id&limit=50000")
    return None if rows is None else {str(r["contact_id"]) for r in rows}


def due(business: Dict[str, Any], days: List[date]) -> Optional[List[Dict[str, Any]]]:
    """Who is celebrated on each of `days`: [{day, sub: birthday|anniversary,
    person_id, partner_id, years}]. None when a read failed."""
    biz_id = str(business["id"])
    b = _q(biz_id)
    st = news_settings(business)
    stopped = _stopped(biz_id)
    choices = sb_clients.sb_get_as_service(
        f"/member_celebrations?business_id=eq.{b}&select=contact_id,birthday,birthday_md&limit=50000")
    couples = sb_clients.sb_get_as_service(
        f"/member_anniversaries?business_id=eq.{b}&a_yes=is.true&b_yes=is.true&select=a_id,b_id,married_on,show_years&limit=20000")
    if stopped is None or choices is None or couples is None:
        return None
    said = {str(c["contact_id"]): c for c in choices}
    if st["celebrate"] == "all":
        people = sb_clients.sb_get_as_service(f"/contacts?business_id=eq.{b}&birthdate=not.is.null&select=id,birthdate&limit=50000")
        if people is None:
            return None
        ids = {str(p["id"]) for p in people} | {k for k, c in said.items() if c.get("birthday_md")}
        want = [i for i in ids if (said.get(i) or {}).get("birthday") is not False]
    else:
        want = [k for k, c in said.items() if c.get("birthday") is True]
        people = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{b}&id=in.({_ids(want)})&select=id,birthdate&limit=50000") if want else []
        if people is None:
            return None
    born = {str(p["id"]): p.get("birthdate") for p in people}
    import member_messaging_rules as rules
    out: List[Dict[str, Any]] = []
    for day in days:
        for cid in want:
            if cid in stopped:
                continue
            # A child has no say here; only adults (or no birthdate on file).
            a = rules.age(born.get(cid))
            if a is not None and a < 18:
                continue
            if falls_on(_md_of(born.get(cid), (said.get(cid) or {}).get("birthday_md")), day):
                out.append({"day": day, "sub": "birthday", "person_id": cid, "partner_id": None, "years": None})
        for c in couples:
            if str(c["a_id"]) in stopped or str(c["b_id"]) in stopped:
                continue
            try:
                wed = date.fromisoformat(str(c["married_on"])[:10])
            except ValueError:
                continue
            if falls_on((wed.month, wed.day), day) and day.year > wed.year:
                out.append({"day": day, "sub": "anniversary", "person_id": str(c["a_id"]), "partner_id": str(c["b_id"]),
                            "years": (day.year - wed.year) if c.get("show_years") else None})
    return out


# ─── each morning ────────────────────────────────────────────────────


def _churches() -> List[str]:
    """Churches with anyone to celebrate: someone said yes, a couple did, or
    the church celebrates everyone unless they say no."""
    ids = set()
    for path in ("/member_celebrations?birthday=is.true&select=business_id&limit=50000",
                 "/member_anniversaries?a_yes=is.true&b_yes=is.true&select=business_id&limit=50000",
                 "/businesses?settings->news->>celebrate=eq.all&select=id&limit=5000"):
        rows = sb_clients.sb_get_as_service(path)
        for r in rows or []:
            ids.add(str(r.get("business_id") or r.get("id")))
    return sorted(i for i in ids if i)


def make_today(business: Dict[str, Any], now: Optional[datetime] = None) -> int:
    """Today's celebrations as posts, once the church's clock passes 7 AM.
    How many were made (0 when it's early, or they already are)."""
    here = local_now(business, now)
    if here.time() < MORNING:
        return 0
    who = due(business, [here.date()])
    if not who:
        return 0
    at = datetime.combine(here.date(), MORNING, tzinfo=here.tzinfo).astimezone(timezone.utc).isoformat()
    rows = [{"business_id": str(business["id"]), "kind": "celebration", "title": "", "body": "", "source": "chief",
             "status": "posted", "comments": "on", "publish_at": at, "celebrate_on": here.date().isoformat(),
             "person_id": w["person_id"], "partner_id": w["partner_id"],
             "attach": {"sub": w["sub"], **({"years": w["years"]} if w["years"] else {})}} for w in who]
    made = sb_clients.sb_post_as_service("/church_posts?on_conflict=business_id,kind,person_id,celebrate_on", rows,
                                         prefer="resolution=ignore-duplicates,return=representation")
    return len(made) if isinstance(made, list) else 0


def sweep_tick(now: Optional[datetime] = None) -> int:
    made = 0
    for biz_id in _churches():
        try:
            rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,settings,owner_id&limit=1")
            if rows:
                made += make_today(rows[0], now)
        except Exception:
            logger.warning("celebrations: one church failed", exc_info=True)
    return made


# ─── reading for the pages ──────────────────────────────────────────


def today_posts(business: Dict[str, Any], me_id: str) -> Optional[List[Dict[str, Any]]]:
    """Today's celebrations and milestones, decorated like any post (the
    person, reactions, wishes), birthdays first."""
    import church_news as cn
    here = local_now(business)
    start = datetime.combine(here.date(), time(0, 0), tzinfo=here.tzinfo).astimezone(timezone.utc).isoformat()
    b = _q(business["id"])
    rows = sb_clients.sb_get_as_service(
        f"/church_posts?business_id=eq.{b}&status=eq.posted&removed_at=is.null&kind=in.(celebration,milestone,good_news)"
        f"&or=(celebrate_on.eq.{here.date().isoformat()},created_at.gte.{_q(start)})"
        f"&select={cn.POST_SELECT},celebrate_on,partner_id&order=created_at.asc&limit=60")
    if rows is None:
        return None
    # People only (the week's "This week we celebrate" post is a post, not a person).
    rows = [r for r in rows if cn.is_live(r) and r.get("person_id")
            and (r.get("kind") != "celebration" or str(r.get("celebrate_on")) == here.date().isoformat())]
    if not rows:
        return []
    partners = cn._people(str(business["id"]), [r.get("partner_id") for r in rows]) or {}
    done = cn._decorate(str(business["id"]), rows, me_id)
    if done is None:
        return None
    for r in done:
        r["partner"] = partners.get(str(r.get("partner_id") or "")) or {}
        r["sub"] = (r.get("attach") or {}).get("sub") or ("milestone" if r.get("kind") == "milestone" else "good_news")
    order = {"birthday": 0, "anniversary": 1, "milestone": 2, "good_news": 3}
    return sorted(done, key=lambda r: order.get(r["sub"], 9))


# ─── the office ──────────────────────────────────────────────────────


def _get(path: str) -> List[Dict[str, Any]]:
    import church_news as cn
    return cn._get(path)


_RANK = {"viewer": 1, "member": 2, "manager": 3, "admin": 4, "owner": 5}


def _need(business_id: str, user: AuthedUser, minimum: str) -> str:
    import kids_router
    role = kids_router.role_for(business_id, user)
    if _RANK.get(role or "", 0) < _RANK[minimum]:
        raise HTTPException(403, "Your seat can see celebrations. Someone who can edit acts on them."
                            if minimum != "viewer" else "This seat can't see celebrations.")
    return role or ""


def office_view(business: Dict[str, Any]) -> Dict[str, Any]:
    import church_news as cn
    biz_id = str(business["id"])
    b = _q(biz_id)
    here = local_now(business)
    week_days = [here.date() + timedelta(days=i) for i in range(7)]
    coming = due(business, week_days)
    if coming is None:
        raise cn._unavailable()
    names = cn._people(biz_id, [c["person_id"] for c in coming] + [c["partner_id"] for c in coming]) or {}
    week = [{"day": c["day"].isoformat(), "sub": c["sub"], "person_id": c["person_id"], "partner_id": c["partner_id"],
             "years": c["years"], "name": (names.get(c["person_id"]) or {}).get("name") or "",
             "partner": (names.get(c["partner_id"] or "") or {}).get("name") or ""} for c in coming]
    with_date = _get(f"/contacts?business_id=eq.{b}&birthdate=not.is.null&select=id&limit=100000")
    choices = _get(f"/member_celebrations?business_id=eq.{b}&select=contact_id,birthday,birthday_md,milestones,stopped&limit=100000")
    couples = _get(f"/member_anniversaries?business_id=eq.{b}&select=a_yes,b_yes&limit=100000")
    everyone = _get(f"/contacts?business_id=eq.{b}&select=id&limit=100000")
    on_file = len({str(c["id"]) for c in with_date} | {str(c["contact_id"]) for c in choices if c.get("birthday_md")})
    # Milestones: a class finished lately by someone who said yes to milestones,
    # not posted or skipped yet.
    st = news_settings(business)
    milestones: List[Dict[str, Any]] = []
    yes_ms = {str(c["contact_id"]) for c in choices if c.get("milestones") and not c.get("stopped")}
    if st["milestone_classes"] and yes_ms:
        since = _q((_now() - timedelta(days=MILESTONE_DAYS)).isoformat())
        done = _get(f"/academy_enrollments?business_id=eq.{b}&completed_at=gte.{since}&contact_id=in.({_ids(yes_ms)})"
                    f"&select=id,course_id,contact_id,completed_at&limit=500")
        had = _get(f"/church_posts?business_id=eq.{b}&kind=eq.milestone&select=attach&limit=5000")
        decided = {str((h.get("attach") or {}).get("enrollment") or "") for h in had}
        done = [d for d in done if str(d["id"]) not in decided]
        if done:
            courses = _get(f"/academy_courses?business_id=eq.{b}&id=in.({_ids(d['course_id'] for d in done)})&select=id,title")
            titles = {str(c["id"]): c.get("title") or "a class" for c in courses}
            who = cn._people(biz_id, [d["contact_id"] for d in done]) or {}
            for d in done:
                name = (who.get(str(d["contact_id"])) or {}).get("name") or "Someone"
                milestones.append({"enrollment_id": d["id"], "contact_id": d["contact_id"], "name": name,
                                   "course": titles.get(str(d["course_id"]), "a class"), "completed_at": d["completed_at"],
                                   "draft": milestone_text(name, titles.get(str(d["course_id"]), "a class"))})
    # Who said yes to anything (and who the office stopped): Settings' list.
    couple_ids = set()
    for c in _get(f"/member_anniversaries?business_id=eq.{b}&a_yes=is.true&b_yes=is.true&select=a_id,b_id&limit=100000"):
        couple_ids |= {str(c["a_id"]), str(c["b_id"])}
    listed = {str(c["contact_id"]) for c in choices if c.get("birthday") is True or c.get("milestones") or c.get("stopped")} | couple_ids
    listed_people = cn._people(biz_id, sorted(listed)) or {}
    stop_of = {str(c["contact_id"]): c.get("stopped") for c in choices}
    people = sorted(({"contact_id": i, "name": (listed_people.get(i) or {}).get("name") or "", "stopped": stop_of.get(i)}
                     for i in listed if (listed_people.get(i) or {}).get("name")), key=lambda x: x["name"].lower())
    sunday = next_sunday(here)
    weekly = _get(f"/church_posts?business_id=eq.{b}&kind=eq.celebration&person_id=is.null&celebrate_on=eq.{sunday.isoformat()}"
                  f"&status=in.(posted,waiting)&removed_at=is.null&select=id&limit=1")
    return {
        "week": week,
        "on_file": {"people": len(everyone), "birthdays": on_file,
                    "anniversaries": sum(1 for c in couples if c.get("a_yes") and c.get("b_yes")),
                    "said_yes": sum(1 for c in choices if c.get("birthday") is True and not c.get("stopped")),
                    "answered": sum(1 for c in choices if c.get("birthday") is not None)},
        "milestones": milestones,
        "people": people,
        "settings": st,
        "sunday": sunday.isoformat(),
        "weekly_post": bool(weekly),
        "weekly_text": weekly_text(week),
    }


def next_sunday(here: datetime) -> date:
    """The coming Sunday; today when it's Sunday before 7 AM."""
    d = here.date()
    ahead = (6 - d.weekday()) % 7
    if ahead == 0 and here.time() >= MORNING:
        ahead = 7
    return d + timedelta(days=ahead)


def _first(name: str) -> str:
    return (name or "").strip().split(" ")[0] or "Someone"


def _and(xs: List[str]) -> str:
    xs = [x for x in xs if x]
    return xs[0] if len(xs) == 1 else (", ".join(xs[:-1]) + " and " + xs[-1]) if xs else ""


def weekly_text(week: List[Dict[str, Any]]) -> str:
    """'This week we celebrate Keisha, Dana and Marcus, and the Grants turn 20.'"""
    births = [_first(w["name"]) for w in week if w["sub"] == "birthday"]
    pairs = []
    for w in week:
        if w["sub"] == "anniversary":
            last = (w["name"] or "").strip().split(" ")[-1] if " " in (w["name"] or "").strip() else ""
            who = f"the {last}s" if last else f"{_first(w['name'])} and {_first(w['partner'])}"
            pairs.append(f"{who} turn {w['years']}" if w.get("years") else f"{who} celebrate their anniversary")
    if not births and not pairs:
        return ""
    lead = f"This week we celebrate {_and(births)}" if births else "This week"
    tail = f", and {_and(pairs)}" if births and pairs else (f" {_and(pairs)}" if pairs else "")
    return f"{lead}{tail}."


def milestone_text(name: str, course: str) -> str:
    return f"{_first(name)} finished {course}. Celebrate with them!"


@router.get("/church/news/celebrations")
def office(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    import church_news as cn
    import kids_router
    biz = kids_router._uuid(business_id, "business_id")
    _need(biz, user, "viewer")
    return office_view(cn._business(biz))


class SettingsIn(BaseModel):
    business_id: str
    celebrate: Optional[Literal["ask", "all"]] = None
    ask_members: Optional[bool] = None
    milestone_classes: Optional[bool] = None


@router.post("/church/news/celebrations/settings")
def settings(body: SettingsIn, user: AuthedUser = Depends(require_user)):
    import church_news as cn
    import kids_router
    biz_id = kids_router._uuid(body.business_id, "business_id")
    _need(biz_id, user, "admin")
    business = cn._business(biz_id)
    s = business.get("settings") if isinstance(business.get("settings"), dict) else {}
    news = dict(s.get("news") if isinstance(s.get("news"), dict) else {})
    for k in ("celebrate", "ask_members", "milestone_classes"):
        v = getattr(body, k)
        if v is not None:
            news[k] = v
    if sb_clients.sb_patch_as_service(f"/businesses?id=eq.{_q(biz_id)}", {"settings": {**s, "news": news}}) is None:
        raise cn._unavailable()
    return {"ok": True}


class MilestoneIn(BaseModel):
    business_id: str
    enrollment_id: str
    post: bool = True
    text: str = ""


@router.post("/church/news/celebrations/milestone")
def milestone(body: MilestoneIn, user: AuthedUser = Depends(require_user)):
    """Post a milestone (a pastor or the office says so), or skip it."""
    import church_news as cn
    import kids_router
    biz_id = kids_router._uuid(body.business_id, "business_id")
    eid = kids_router._uuid(body.enrollment_id, "enrollment")
    _need(biz_id, user, "member")
    business = cn._business(biz_id)
    rows = _get(f"/academy_enrollments?id=eq.{_q(eid)}&business_id=eq.{_q(biz_id)}&completed_at=not.is.null"
                f"&select=id,contact_id,course_id&limit=1")
    if not rows:
        raise HTTPException(404, "That class isn't finished, or isn't yours.")
    e = rows[0]
    yes = prefs(biz_id, e["contact_id"])
    if not yes or not yes.get("milestones") or yes.get("stopped"):
        raise HTTPException(409, "They haven't said yes to celebrating milestones.")
    had = _get(f"/church_posts?business_id=eq.{_q(biz_id)}&kind=eq.milestone&attach->>enrollment=eq.{_q(eid)}&select=id&limit=1")
    if had:
        raise HTTPException(409, "That milestone was already decided.")
    course = _get(f"/academy_courses?id=eq.{_q(e['course_id'])}&business_id=eq.{_q(biz_id)}&select=title&limit=1")
    title = (course[0].get("title") if course else "") or "a class"
    person = (cn._people(biz_id, [e["contact_id"]]) or {}).get(str(e["contact_id"])) or {}
    text = " ".join((body.text or milestone_text(person.get("name") or "", title)).split())[:cn.BODY_MAX]
    row = cn.insert(biz_id, {
        "kind": "milestone", "title": f"{(person.get('name') or 'Someone').strip()} finished {title}", "body": text,
        "person_id": str(e["contact_id"]), "source": "chief", "office_user": user.id,
        "status": "posted" if body.post else "declined", "decided_at": _now().isoformat(), "decided_by": user.id,
        "comments": "on", "attach": {"enrollment": str(eid)}})
    if not row:
        raise cn._unavailable()
    return {"ok": True, "posted": body.post}


class WeekIn(BaseModel):
    business_id: str
    text: str = ""


@router.post("/church/news/celebrations/week")
def week_post(body: WeekIn, user: AuthedUser = Depends(require_user)):
    """'This week we celebrate …', scheduled for the coming Sunday at 7 AM."""
    import church_news as cn
    import kids_router
    biz_id = kids_router._uuid(body.business_id, "business_id")
    _need(biz_id, user, "member")
    business = cn._business(biz_id)
    view = office_view(business)
    if view["weekly_post"]:
        raise HTTPException(409, "This Sunday's celebration post is already set.")
    text = " ".join((body.text or view["weekly_text"]).split())[:cn.BODY_MAX]
    if not text:
        raise HTTPException(409, "Nobody who said yes has a birthday or anniversary this week.")
    here = local_now(business)
    sunday = date.fromisoformat(view["sunday"])
    at = datetime.combine(sunday, MORNING, tzinfo=here.tzinfo).astimezone(timezone.utc)
    row = cn.insert(biz_id, {
        "kind": "celebration", "title": "This week we celebrate", "body": text, "source": "chief", "office_user": user.id,
        "status": "posted", "comments": "on", "celebrate_on": sunday.isoformat(),
        "publish_at": at.isoformat() if at > _now() else None,
        "attach": {"sub": "week", "people": [w["person_id"] for w in view["week"]]}})
    if not row:
        raise cn._unavailable()
    return {"ok": True, "publish_at": at.isoformat()}


class StopIn(BaseModel):
    business_id: str
    contact_id: str
    reason: Literal["passed", "office"]
    start: bool = False


@router.post("/church/news/celebrations/stop")
def stop(body: StopIn, user: AuthedUser = Depends(require_user)):
    """Stop every celebration of someone: they passed away (their birthday and
    every anniversary of theirs stop), or they asked the office. `start`
    takes the office's stop away again."""
    import church_news as cn
    import kids_router
    biz_id = kids_router._uuid(body.business_id, "business_id")
    cid = kids_router._uuid(body.contact_id, "person")
    _need(biz_id, user, "admin")
    if not _get(f"/contacts?id=eq.{_q(cid)}&business_id=eq.{_q(biz_id)}&select=id&limit=1"):
        raise HTTPException(404, "That person isn't one of your people.")
    changes = ({"stopped": None, "stopped_at": None} if body.start
               else {"stopped": body.reason, "stopped_at": _now().isoformat()})
    if not save_prefs(biz_id, cid, **changes):
        raise cn._unavailable()
    if not body.start:
        # Today's posts about them come down too.
        here = local_now(cn._business(biz_id))
        sb_clients.sb_patch_as_service(
            f"/church_posts?business_id=eq.{_q(biz_id)}&kind=eq.celebration&celebrate_on=gte.{here.date().isoformat()}"
            f"&or=(person_id.eq.{_q(cid)},partner_id.eq.{_q(cid)})",
            {"status": "removed", "removed_at": _now().isoformat()})
    return {"ok": True}
