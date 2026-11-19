"""church_schedule_tell.py — the leaders schedule: who is told, and the hourly
sweep (docs/CHURCH_SCHEDULE.md, PR S1-4; church_schedule.py holds the asks).

Kevin, 2026-11-18: "this is for when leaders are planning time off and have
certain obiligations so that we as a church can plan around meeting".

    a new ask ........ whoever it went to hears, once (told_at). A planned
                       one waits out the church's quiet hours; "can't make
                       it" goes at once, quiet hours or not
    an answer ........ the one who asked hears, once (answer_told_at), outside
                       quiet hours. A yes nobody had to give (a "can't make
                       it", the owner's own) tells the asker nothing: they
                       pressed it themselves
    still waiting .... one nudge to whoever it went to, three days after they
                       were told (nudged_at). Never a second
    taken back ....... by the one who asked: whoever it went to hears, when
                       they had been told of it. By the owner or whoever
                       oversees the office: the one who asked hears. Sent
                       straight after the write and never tried again (no
                       column claims it)

WHAT A NOTICE SAYS. Who, and which days, and nothing else: a lock screen is
not private. THE REASON AND THE NOTE THAT CAME WITH AN ANSWER ARE NEVER IN A
NOTICE: not in a push, an email, the church's conversation or a log line.
_bare() drops both from every row at the door, and the sweep never asks the
database for either, so nothing below this line can say them.

An ask that went up for an exception (step 2: past the number who can be away
at once, on a protected day, or overlapping someone they can't be away with)
is told to whoever it went up to, and nobody else: the one over the asker
can't answer it and isn't told of it. Its notice adds only that it is past
the number, on a protected day, or that it overlaps with someone they can't
be away with (up_words): never how many are away, never who, never which day,
and never who the other of a pair is.

A volunteer's ask (S2-5: their day was full for their department, or they
had said yes to serve it) is told to their team's leader with who, which days
and why it came to them: they are on the schedule to serve then, or the day is
already full (volunteer_why). Never which department, how many, or who else.
The volunteer hears the answer in the words of their own page, and their
notice opens My serving.

HOW SOMEONE IS TOLD. One of the church's people: a push to their phone and a
line in their conversation with the church (member_push.send does both, kind
`serving`), and an email only when no phone was reached and they have one. An
office login: a push to the office app and an email. A person who is an office
login (Admin or Manager), and the one person the owner is, are told as that
login. A login whose address couldn't be read is not told this time, and
nothing is claimed for it.

TOLD ONCE. Many replicas run the web service and one runs the worker, so
every "told" is a claim in the database: an update of told_at, answer_told_at
or nudged_at that lands only while the mark is still empty and the ask is
still as it was read, so one caller wins. It is taken before the send and let
go when nothing could be sent, so the next sweep tries again.

THE SWEEP (hourly, on the worker; sweep_tick). Nothing is read while the
switch is off, and before the migration nothing but church_schedule.ready's
own check for its tables. Only the churches
church_assignments._open_churches() gives, each one CHURCH_SCHEDULE is also
open for, and never a sample church. For each:

  * a waiting ask whose `to` is no longer anyone at the nearest step over
    the asker (or is a login that has left the office, or is empty) is sent
    to whoever church_schedule.goes_to gives now, and its told_at cleared so
    they hear. Never one that needs no yes. A FLAGGED ask (step 2: past the
    number, or on a protected day) went up for an exception and is never
    sent back down: it moves only when it no longer sits with someone who
    may give one, and then to whoever church_schedule.goes_up gives
  * a VOLUNTEER'S waiting ask (S2-5) is their team's: it stays while it
    sits with someone at the first step of its team's chain
    (church_schedule_volunteers.stale), and is sent on along that chain only,
    never to the leaders map's step over the volunteer
  * untold asks older than two minutes, and untold "can't make it"s
  * untold answers from the last week
  * the one nudge
  * the reason, and the note that came with the answer, are cleared 90
    days after the last day (a reason can be medical, and the note can say
    why). Only those two: the ask and its answer stay

Every read carries its own state filter (the untold index keeps answered and
withdrawn rows too) and goes page by page.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

from fastapi import HTTPException

import church_over as co
import church_schedule as cs
import sb_clients

logger = logging.getLogger("church_schedule_tell")

KIND = "serving"            # member_push's kind: it lands in the church's conversation (decision 5)
NUDGE_DAYS = 3
REASON_DAYS = 90            # a private reason and an answer's note are kept this long after the last day (decision 14)
SETTLE_SECONDS = 120        # the sweep leaves an ask this new to the write's own notice
ANSWER_DAYS = 7             # an answer nobody could be told of in a week is left untold
MEMBER_PAGE = "/my/lead/dates"      # Dates on the Lead tab (member_portal_dates): where a person asks and answers
MEMBER_LINK = "Open your dates"     # the email's button
# A volunteer (S2-5) asked from My serving, and follows it there: what they
# hear opens that page. Whoever it went to answers on Dates, as anyone does.
SERVING_PAGE = "/my/serving"
SERVING_LINK = "Open My serving"
OFFICE = "The church office"
_NO_NAME = {"", "Someone", "The owner", "An office login"}      # the stand-ins a notice never says
# What a notice may know of an ask. Never `reason`, never `decided_note`.
# `made_by` (the login that entered an ask for someone) is for the sweep
# alone: whoever entered an ask can't answer it, so a flagged one is never
# sent to them. It is in no notice's words. `grp` and `department_id` say a
# volunteer's ask from a leader's (S2-5), and with `team_group_id` (step 2's
# column, read by the sweep only where step 2 is there) whose it is to send
# on: none of the three is in a notice's words either.
FIELDS = ("id,business_id,contact_id,made_by,grp,department_id,kind,starts_on,ends_on,state,flags,to_user_id,"
          "to_contact_id,decided_by_user_id,decided_by_contact_id,decided_at,told_at,answer_told_at,nudged_at,"
          "created_at")
_KEEP = frozenset(FIELDS.split(",")) | {"team_group_id"}


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _bare(ask: Dict[str, Any]) -> Dict[str, Any]:
    """The ask with only what a notice may know (FIELDS). The reason and the
    note that came with the answer stop here, whoever handed the row over."""
    return {k: v for k, v in (ask or {}).items() if k in _KEEP}


# ─── The words ────────────────────────────────────────────────────────

def days(a: Any, b: Any) -> str:
    """'Dec 20 to 27', 'Dec 28 to Jan 3', 'Dec 20': for a lock screen."""
    lo, hi = cs._day(a), cs._day(b)
    if not lo or not hi:
        return "those days"
    if lo == hi:
        return f"{lo:%b} {lo.day}"
    if (lo.year, lo.month) == (hi.year, hi.month):
        return f"{lo:%b} {lo.day} to {hi.day}"
    return f"{lo:%b} {lo.day} to {hi:%b} {hi.day}"


def long_days(a: Any, b: Any) -> str:
    """'Sunday, December 20 to Sunday, December 27': an email is read on
    another day."""
    lo, hi = cs._day(a), cs._day(b)
    if not lo or not hi:
        return "those days"

    def said(d: date) -> str:
        return f"{d:%A}, {d:%B} {d.day}"
    return said(lo) if lo == hi else f"{said(lo)} to {said(hi)}"


def _first(name: str) -> str:
    return (" ".join(str(name or "").split()).split(" ") or [""])[0] or "Someone"


def _hi(name: str) -> str:
    first = _first(name)
    return f"Hi {first}," if first != "Someone" else "Hi there,"


def volunteer_why(ask: Dict[str, Any]) -> str:
    """Why a volunteer's ask came to their team's leader (S2-5), as much as a
    lock screen may say: they are on the schedule to serve then, and/or the
    day is already full. Never which department, how many, or who else."""
    flags = ask.get("flags") or []
    one = str(ask.get("starts_on") or "")[:10] == str(ask.get("ends_on") or "")[:10]
    serving = "They’re on the schedule to serve that day" if one else \
        "They’re on the schedule to serve on one of those days"
    full = "that day is already full" if one else "one of those days is already full"
    if "serving" in flags and "over_limit" in flags:
        return f"{serving}, and {'it’s already full' if one else 'one of them is already full'}"
    if "over_limit" in flags:
        return full[0].upper() + full[1:]
    return serving


def new_words(church: str, to_name: str, asker: str, ask: Dict[str, Any]) -> Dict[str, str]:
    """A new ask, to whoever it went to. "Can't make it" needs no answer."""
    first, when, long = _first(asker), days(ask.get("starts_on"), ask.get("ends_on")), long_days(
        ask.get("starts_on"), ask.get("ends_on"))
    if cs.volunteer(ask):
        # A volunteer's (S2-5): who, which days, and why it came to their
        # team's leader. Nothing else.
        title, why = f"{first} asked for {when}", volunteer_why(ask)
        return {"title": title, "body": f"{why}, so it came to you. Say yes or not this one when you can.",
                "subject": f"{church}: {title}",
                "text": "\n\n".join([_hi(to_name), f"{asker} asked to be away {long}. {why}, so it came to you. "
                                     "It’s waiting for your yes, or not this one.",
                                     "You can answer in the church’s app."])}
    if ask.get("kind") == "cant":
        title = f"{first} can’t make it {when}"
        return {"title": title, "body": "It’s on the calendar. Nothing for you to answer.",
                "subject": f"{church}: {title}",
                "text": "\n\n".join([_hi(to_name), f"{asker} can’t make it {long}. It’s on the church’s calendar "
                                     "already, so there’s nothing for you to answer. You’re hearing so you can "
                                     "plan around it."])}
    short = "short_notice" in (ask.get("flags") or [])
    title = f"{first} asked for {when}"
    up = up_words(ask)
    if up:
        # It went up for an exception (step 2). Who asked, which days, and
        # that it is past the number or on a protected day: nothing else.
        return {"title": title,
                "body": ("Short notice. " if short else "") + f"{up}, so it came to you. Say yes or not this one "
                        "when you can.",
                "subject": f"{church}: {title}",
                "text": "\n\n".join([_hi(to_name), f"{asker} asked to be away {long}." + (" It’s short notice." if short
                                     else "") + f" {up}, so it came to you. It’s waiting for your yes, or not this "
                                     "one.", "You can answer in the church’s app."])}
    return {"title": title,
            "body": ("Short notice. " if short else "") + "Say yes or not this one when you can.",
            "subject": f"{church}: {title}",
            "text": "\n\n".join([_hi(to_name), f"{asker} asked to be away {long}." + (" It’s short notice." if short
                                 else "") + " It’s waiting for your yes, or not this one.",
                                 "You can answer in the church’s app."])}


def up_words(ask: Dict[str, Any]) -> str:
    """Why a flagged ask came up, as much as a lock screen may say: that it
    is past the number, on a protected day, or overlaps with someone they
    can't be away with (a pair, S2-4). Never how many, never which day,
    never who else is away, never who the other of a pair is. '' for an ask
    that isn't flagged."""
    flags = ask.get("flags") or []
    over, kept = "over_limit" in flags, "protected_day" in flags
    if "pair" in flags:
        pair = "overlaps with someone they can’t be away with"
        if over and kept:
            return f"It’s past the number who can be away at once, on a protected day, and {pair}"
        if over:
            return f"It’s past the number who can be away at once, and {pair}"
        if kept:
            return f"It’s on a protected day, and {pair}"
        return f"It {pair}"
    if over and kept:
        return "It’s past the number who can be away at once, and on a protected day"
    if over:
        return "It’s past the number who can be away at once"
    if kept:
        return "It’s on a protected day"
    return "It needs an exception" if cs.flagged(ask) else ""


def answer_words(church: str, asker: str, by: str, ask: Dict[str, Any]) -> Dict[str, str]:
    """The answer, to the one who asked. Never the note that came with it."""
    when, long = days(ask.get("starts_on"), ask.get("ends_on")), long_days(ask.get("starts_on"), ask.get("ends_on"))
    if cs.volunteer(ask):
        # A volunteer's (S2-5): in the words of their own page, My serving.
        if ask.get("state") == "yes":
            return {"title": f"{by} said yes to {when}", "body": "It’s on your away days now.",
                    "subject": f"{church}: yes to {when}",
                    "text": "\n\n".join([_hi(asker), f"{by} said yes to your away days, {long}. Nobody asks you "
                                         "to serve on those days now."])}
        return {"title": f"{by} said not this one for {when}", "body": "Open My serving to see it.",
                "subject": f"{church}: an answer about {when}",
                "text": "\n\n".join([_hi(asker), f"{by} said not this one to your away days, {long}.",
                                     "You can see it on My serving, in the church’s app."])}
    if ask.get("state") == "yes":
        return {"title": f"{by} said yes to {when}", "body": "Your time away is on the calendar.",
                "subject": f"{church}: yes to {when}",
                "text": "\n\n".join([_hi(asker), f"{by} said yes to your time away, {long}. It’s on the church’s "
                                     "calendar now."])}
    return {"title": f"{by} said not this one for {when}", "body": "Open the church’s app to see it.",
            "subject": f"{church}: an answer about {when}",
            "text": "\n\n".join([_hi(asker), f"{by} said not this one to your time away, {long}.",
                                 "You can see it in the church’s app, and ask for other days there."])}


def nudge_words(church: str, to_name: str, asker: str, ask: Dict[str, Any]) -> Dict[str, str]:
    when, long = days(ask.get("starts_on"), ask.get("ends_on")), long_days(ask.get("starts_on"), ask.get("ends_on"))
    title = f"{_first(asker)} is still waiting on {when}"
    return {"title": title, "body": "Say yes or not this one when you can.", "subject": f"{church}: {title}",
            "text": "\n\n".join([_hi(to_name), f"{asker} asked to be away {long}, and is still waiting to hear.",
                                 "You can answer in the church’s app."])}


def back_words(church: str, to_name: str, asker: str, ask: Dict[str, Any]) -> Dict[str, str]:
    """The one who asked took it back, to whoever it had gone to."""
    when, long = days(ask.get("starts_on"), ask.get("ends_on")), long_days(ask.get("starts_on"), ask.get("ends_on"))
    title = f"{_first(asker)} took back {when}"
    return {"title": title, "body": "Nothing for you to do.", "subject": f"{church}: {title}",
            "text": "\n\n".join([_hi(to_name), f"{asker} took back the time away they asked for, {long}. There’s "
                                 "nothing for you to do."])}


def taken_words(church: str, asker: str, by: str, ask: Dict[str, Any]) -> Dict[str, str]:
    """The owner, or whoever oversees the office, took it back: to the one
    who asked."""
    when, long = days(ask.get("starts_on"), ask.get("ends_on")), long_days(ask.get("starts_on"), ask.get("ends_on"))
    title = f"Your time away, {when}, was taken back"
    return {"title": title, "body": f"{by} took it back.", "subject": f"{church}: your time away, {when}, was "
            "taken back",
            "text": "\n\n".join([_hi(asker), f"{by} took back your time away, {long}. It’s no longer waiting, and "
                                 "it’s off the church’s calendar.", "You can ask again in the church’s app."])}


# ─── Who, and how they are reached ────────────────────────────────────

def _open(ch: co.Church) -> bool:
    """Notices go only where the church's own switch is open and its tables
    are there, and never for a sample church (its people are made up)."""
    import sample_church
    return cs.on(ch.business) and not sample_church.skip(ch.business)


def _church_name(ch: co.Church) -> str:
    return cs._plain(ch.business.get("name")) or "Your church"


def _to(ask: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Who the ask names: a login, or one of the church's people; None when
    both are empty."""
    if ask.get("to_user_id"):
        return co.who(co.LOGIN, ask["to_user_id"])
    if ask.get("to_contact_id"):
        return co.who(co.PERSON, ask["to_contact_id"])
    return None


def _to_guard(ask: Dict[str, Any]) -> str:
    """A claim lands only while the ask still names who it named when read:
    one sent on to someone else in between leaves nothing to say."""
    return "".join(f"&{col}=eq.{_q(ask[col])}" if ask.get(col) else f"&{col}=is.null"
                   for col in ("to_user_id", "to_contact_id"))


def _asker_as(ch: co.Church, cid: str) -> Dict[str, str]:
    """How the one who asked is reached: the owner's login for the one
    person the owner is, their office login for an Admin's or Manager's
    person, else as one of the church's people."""
    if ch.owner and ch.owner_person and cid == ch.owner_person:
        return co.who(co.LOGIN, ch.owner)
    uid = ch.person_login.get(cid)
    return co.who(co.LOGIN, uid) if uid else co.who(co.PERSON, cid)


def _login_called(ch: co.Church, uid: str) -> str:
    """A login by a name a notice can say: the owner by the church's own
    name for them; anyone else by their person's first name; never a
    stand-in ("The owner"), never part of an email address."""
    uid = str(uid or "")
    if not uid or not (uid == ch.owner or uid in ch.seats):
        return OFFICE
    cid = ch.login_person.get(uid)
    mine = ch.names([cid]).get(cid, "") if cid else ""
    if uid == ch.owner:
        name = ch.login_name(uid)
        return name if name not in _NO_NAME else (_first(mine) if mine not in _NO_NAME else OFFICE)
    if mine not in _NO_NAME:
        return _first(mine)
    name = cs._plain((ch.seats.get(uid) or {}).get("name"))
    return _first(name) if name and "@" not in name else OFFICE


def _reach(ch: co.Church, who: Dict[str, str]) -> Optional[Dict[str, str]]:
    """{kind, id, name, email} for someone a notice goes to; email '' when
    they have none. None when their address couldn't be read: they aren't
    told this time and nothing is claimed for them."""
    import church_assignments as cas
    import church_leader_tasks as clt
    if who["kind"] == co.LOGIN:
        uid = str(who["id"])
        email = cas._login_email(ch, uid)
        if email is None:
            return None
        cid = ch.login_person.get(uid)
        name = ch.names([cid]).get(cid, "") if cid else ""
        return {"kind": co.LOGIN, "id": uid, "name": "" if name in _NO_NAME else name, "email": email}
    cid = str(who["id"])
    people = clt._contacts(ch.b, [cid])
    if people is None:
        return None
    p = people.get(cid) or {}
    name = p.get("name", "")
    return {"kind": co.PERSON, "id": cid, "name": "" if name in _NO_NAME else name, "email": p.get("email", "")}


def _member_link(business_id: str, page: str = MEMBER_PAGE) -> str:
    import church_follow_up as cfu
    origin = cfu.site_origin(business_id)
    return f"{origin}{page}" if origin else ""


def _page_for(ch: co.Church, ask: Dict[str, Any], to_asker: bool) -> str:
    """Where a person's notice opens: Dates, where an ask is answered and a
    leader's own asks are; for the volunteer who made one (S2-5), My
    serving, where they asked and where it shows."""
    return SERVING_PAGE if to_asker and cs.volunteer(ask) else MEMBER_PAGE


def to_person(biz: Dict[str, Any], cid: str, *, title: str, body: str, ref: str, subject: str, text: str,
              url: str = MEMBER_PAGE, link_label: str = "", email: Optional[str] = None,
              name: str = "") -> Dict[str, int]:
    """Tell one of the church's people: {"rang", "mailed"}. A push and a line
    in their conversation with the church (member_push.send, once a `ref`);
    an email only when no phone was reached and they have an address
    (`email`, read here when it isn't handed in). Never raises."""
    import church_leader_tasks as clt
    import member_push
    b = str(biz.get("id") or "")
    rang = member_push.send(biz, KIND, title=title, body=body, url=url, contact_ids=[str(cid)], ref_id=ref,
                            tag=ref[:60])
    mailed = 0
    if not rang:
        if email is None:
            p = (clt._contacts(b, [str(cid)]) or {}).get(str(cid)) or {}
            email, name = p.get("email", ""), name or p.get("name", "")
        if email:
            try:
                link = _member_link(b, url)
                label = link_label or (SERVING_LINK if url == SERVING_PAGE else MEMBER_LINK)
                html = clt.render_email(biz, text, title, link, label)
                clt.deliver(biz, email, name, subject, html, ref, reply_to=clt._office_email(biz))
                mailed = 1
            except Exception:  # noqa: BLE001 — the caller lets its claim go and the sweep tries again
                logger.warning("leaders schedule: an email didn't go (business %s)", b[:8], exc_info=True)
    return {"rang": int(rang or 0), "mailed": mailed}


def to_login(ch: co.Church, uid: str, *, title: str, body: str, ref: str, subject: str, text: str,
             email: Optional[str] = None, name: str = "") -> Dict[str, int]:
    """Tell an office login: {"rang", "mailed"}. A push to the office app
    and an email to its sign-in address (`email`, read here when it isn't
    handed in; one that can't be read sends nothing at all, so the caller
    claims nothing). Never raises."""
    import church_assignments as cas
    import church_leader_tasks as clt
    import church_office_tasks as cot
    biz, b, uid = ch.business, ch.b, str(uid)
    if email is None:
        email = cas._login_email(ch, uid)
        if email is None:
            return {"rang": 0, "mailed": 0}
    rang = 0
    try:
        import push_notifications
        rang = push_notifications.send_to_user(uid, title=title[:80], body=body[:160], nav=cas.NAV, tag=ref[:60],
                                               business_id=b)
    except Exception:  # noqa: BLE001
        logger.info("leaders schedule: a push didn't go (business %s)", b[:8], exc_info=True)
    mailed = 0
    if email:
        try:
            html = cot.render(biz, text, title, cot._link(b), "Open the church’s app")
            clt.deliver(biz, email, name, subject, html, ref, reply_to=clt._office_email(biz))
            mailed = 1
        except Exception:  # noqa: BLE001
            logger.warning("leaders schedule: an email didn't go (business %s)", b[:8], exc_info=True)
    return {"rang": int(rang or 0), "mailed": mailed}


def _send(ch: co.Church, who: Dict[str, str], words: Dict[str, str], ref: str, page: str = MEMBER_PAGE) -> bool:
    """One notice to one person or login. True when anything went. `page`:
    where a person's notice opens (a login's opens the office app)."""
    kw = dict(title=words["title"], body=words["body"], ref=ref, subject=words["subject"], text=words["text"],
              email=who["email"], name=who["name"])
    got = to_login(ch, who["id"], **kw) if who["kind"] == co.LOGIN else to_person(ch.business, who["id"], url=page,
                                                                                    **kw)
    return bool(got["rang"] or got["mailed"])


# ─── The claim ────────────────────────────────────────────────────────

def _claim(b: str, ask: Dict[str, Any], column: str, stamp: str, guard: str) -> bool:
    """Take this notice: the mark is still empty and the ask is still as it
    was read (`guard`). Many replicas and the worker: one wins."""
    got = sb_clients.sb_patch_as_service(
        f"/church_away_asks?id=eq.{_q(ask['id'])}&business_id=eq.{_q(b)}&{column}=is.null{guard}&select=id",
        {column: stamp}, redact=True)
    return isinstance(got, list) and bool(got)


def _release(b: str, ask: Dict[str, Any], column: str, stamp: str) -> None:
    """Let a claim go (nothing could be sent), only if it is still ours."""
    try:
        sb_clients.sb_patch_as_service(
            f"/church_away_asks?id=eq.{_q(ask['id'])}&business_id=eq.{_q(b)}&{column}=eq.{_q(stamp)}&select=id",
            {column: None}, redact=True)
    except Exception:  # noqa: BLE001
        logger.warning("leaders schedule: a claim wasn't let go (ask %s)", str(ask.get("id"))[:8], exc_info=True)


def _claimed_send(ch: co.Church, ask: Dict[str, Any], column: str, guard: str, who: Dict[str, str],
                  words: Dict[str, str], ref: str, now: datetime, page: str = MEMBER_PAGE) -> str:
    stamp = cs._iso(now)
    if not _claim(ch.b, ask, column, stamp, guard):
        return "taken"
    try:
        sent = _send(ch, who, words, ref, page)
    except Exception:  # noqa: BLE001 — a claim is never left taken for a notice that didn't go
        logger.warning("leaders schedule: a notice failed (ask %s)", str(ask.get("id"))[:8], exc_info=True)
        sent = False
    if not sent:
        _release(ch.b, ask, column, stamp)
        return "unsent"
    return "told"


# ─── The notices ──────────────────────────────────────────────────────

def tell_new(ch: co.Church, ask: Dict[str, Any], *, now: Optional[datetime] = None) -> str:
    """A new ask: whoever it went to hears, once. A planned ask waits out
    the church's quiet hours (the sweep sends it); "can't make it" goes at
    once. The owner's own ask went to nobody and tells nobody.

    Answers with what happened: told | held (quiet hours) | taken (someone
    else told it) | unsent (nothing could be sent: the claim is let go) |
    unread (an address or a name couldn't be read: nothing claimed) | none
    (nobody to tell) | closed."""
    ask = _bare(ask)
    try:
        if not _open(ch):
            return "closed"
        cant = ask.get("kind") == "cant"
        state = ask.get("state")
        # A "can't make it" is told once it is an away date; anything else while it waits.
        if ask.get("told_at") or state != ("yes" if cant else "asked"):
            return "none"
        if not cant and cs.needs_no_yes(ch, ask):
            return "none"
        to = _to(ask)
        if not to or (to["kind"] == co.LOGIN and not cs._in_office(ch, to["id"])):
            return "none"       # nobody is over them, or the sweep sends it on first
        now = now or cs._now()
        import member_push
        if not cant and member_push.quiet_hour(ch.business, now):
            return "held"
        who = _reach(ch, to)
        if who is None:
            return "unread"
        asker = ch.names([ask.get("contact_id")]).get(str(ask.get("contact_id")), "Someone")
        words = new_words(_church_name(ch), who["name"], asker, ask)
        return _claimed_send(ch, ask, "told_at", f"&state=eq.{state}{_to_guard(ask)}", who, words,
                             f"away-new-{ask['id']}-{to['id']}", now)
    except HTTPException:
        return "unread"


def tell_answer(ch: co.Church, ask: Dict[str, Any], *, now: Optional[datetime] = None) -> str:
    """An answer: the one who asked hears, once, outside quiet hours. A yes
    nobody had to give tells nobody. Answers as tell_new does."""
    ask = _bare(ask)
    try:
        if not _open(ch):
            return "closed"
        state = ask.get("state")
        if state not in ("yes", "no") or ask.get("answer_told_at"):
            return "none"
        if not (ask.get("decided_by_user_id") or ask.get("decided_by_contact_id")) or cs.needs_no_yes(ch, ask):
            return "none"
        now = now or cs._now()
        import member_push
        if member_push.quiet_hour(ch.business, now):
            return "held"
        cid = str(ask.get("contact_id") or "")
        who = _reach(ch, _asker_as(ch, cid))
        if who is None:
            return "unread"
        if ask.get("decided_by_user_id"):
            by = _login_called(ch, ask["decided_by_user_id"])
        else:
            c = str(ask["decided_by_contact_id"])
            by = ch.names([c]).get(c, "")
            by = OFFICE if by in _NO_NAME else _first(by)
        asker = who["name"] or ch.names([cid]).get(cid, "")
        words = answer_words(_church_name(ch), asker, by, ask)
        return _claimed_send(ch, ask, "answer_told_at", f"&state=eq.{state}", who, words,
                             f"away-answer-{ask['id']}", now, _page_for(ch, ask, True))
    except HTTPException:
        return "unread"


def tell_withdrawn(ch: co.Church, ask: Dict[str, Any], *, by: Dict[str, Any]) -> str:
    """Taken back, straight after the write, and never tried again (no
    column claims it; the write itself happens once). By the one who asked:
    whoever it went to hears, when they had been told of it. By the owner or
    whoever oversees the office: the one who asked hears. Nobody else."""
    ask = _bare(ask)
    try:
        if ask.get("state") != "withdrawn":
            return "none"
        if not _open(ch):
            return "closed"
        cid = str(ask.get("contact_id") or "")
        church = _church_name(ch)
        if cs._is_asker(ch, by, ask):
            to = _to(ask)
            if not ask.get("told_at") or not to or (to["kind"] == co.LOGIN and not cs._in_office(ch, to["id"])):
                return "none"
            who = _reach(ch, to)
            if who is None:
                return "unread"
            asker = ch.names([cid]).get(cid, "Someone")
            words, ref = back_words(church, who["name"], asker, ask), f"away-back-{ask['id']}-{to['id']}"
        else:
            who = _reach(ch, _asker_as(ch, cid))
            if who is None:
                return "unread"
            taker = _login_called(ch, by["id"]) if by.get("kind") == co.LOGIN else OFFICE
            asker = who["name"] or ch.names([cid]).get(cid, "")
            words, ref = taken_words(church, asker, taker, ask), f"away-taken-{ask['id']}"
            return "told" if _send(ch, who, words, ref, _page_for(ch, ask, True)) else "unsent"
        return "told" if _send(ch, who, words, ref) else "unsent"
    except HTTPException:
        return "unread"


def tell_nudge(ch: co.Church, ask: Dict[str, Any], *, now: Optional[datetime] = None) -> str:
    """Still waiting three days after whoever it went to was told: one
    nudge to them, never a second (nudged_at, which a later `to` keeps)."""
    ask = _bare(ask)
    try:
        if not _open(ch):
            return "closed"
        now = now or cs._now()
        import church_follow_up as cfu
        told = cfu._parse(ask.get("told_at"))
        if ask.get("state") != "asked" or ask.get("nudged_at") or not told \
                or told > now - timedelta(days=NUDGE_DAYS) or cs.needs_no_yes(ch, ask):
            return "none"
        to = _to(ask)
        if not to or (to["kind"] == co.LOGIN and not cs._in_office(ch, to["id"])):
            return "none"
        import member_push
        if member_push.quiet_hour(ch.business, now):
            return "held"
        who = _reach(ch, to)
        if who is None:
            return "unread"
        asker = ch.names([ask.get("contact_id")]).get(str(ask.get("contact_id")), "Someone")
        words = nudge_words(_church_name(ch), who["name"], asker, ask)
        return _claimed_send(ch, ask, "nudged_at", f"&state=eq.asked&told_at=not.is.null{_to_guard(ask)}", who,
                             words, f"away-nudge-{ask['id']}", now)
    except HTTPException:
        return "unread"


# ─── The hourly sweep ─────────────────────────────────────────────────

def _all(path: str, what: str) -> Optional[List[Dict[str, Any]]]:
    """Every row, page by page in id order (never the first 1,000 taken for
    all of them). None when it can't be read whole: nothing of it is acted
    on, and the next hour tries again."""
    try:
        return sb_clients.sb_get_all_as_service(path, key="id", redact=True)
    except sb_clients.PartialRead:
        print(f"[church_schedule_tell] {what} was read in part; next sweep", flush=True)
        return None


def _stale(ch: co.Church, ask: Dict[str, Any], near: List[Dict[str, str]]) -> bool:
    """Whether a waiting ask no longer sits with anyone over the asker: its
    `to` is empty, a login that has left the office, or no longer one of
    those at the nearest step. While it is still one of them it stays where
    it is, whoever the library now lists first: sending it round the step
    would only widen who reads the reason (decision 1)."""
    to = _to(ask)
    if not to or (to["kind"] == co.LOGIN and not cs._in_office(ch, to["id"])):
        return True
    return not any(co.same(to, n) for n in near)


def _move(ch: co.Church, ask: Dict[str, Any], want: Dict[str, str], now: datetime) -> bool:
    """Send a waiting ask on to `want`, and clear told_at so they hear. Only
    while it still waits and still names who it named when read."""
    new = {"to_user_id": want["id"] if want["kind"] == co.LOGIN else None,
           "to_contact_id": want["id"] if want["kind"] == co.PERSON else None}
    got = sb_clients.sb_patch_as_service(
        f"/church_away_asks?id=eq.{_q(ask['id'])}&business_id=eq.{_q(ch.b)}&state=eq.asked{_to_guard(ask)}&select=id",
        {**new, "told_at": None, "updated_at": cs._iso(now)}, redact=True)
    if not isinstance(got, list) or not got:
        return False
    ask.update(new, told_at=None)
    return True


PRIVATE = "or=(reason.not.is.null,decided_note.not.is.null)"     # an ask that still holds either private text


def _clear_reasons(b: str, ids: Iterable[str], cutoff: date) -> int:
    """Clear the reason and the note that came with the answer (it can say
    why, so it is as private), and only those two, on asks whose last day is
    more than REASON_DAYS past. The write names the rule again, so a row
    that changed since it was read is left alone; nothing is asked back but
    ids."""
    done = 0
    for part in co._chunks(ids, co.IDS_PER_READ):
        got = sb_clients.sb_patch_as_service(
            f"/church_away_asks?business_id=eq.{_q(b)}&id=in.({','.join(_q(i) for i in part)})"
            f"&{PRIVATE}&ends_on=lt.{cutoff.isoformat()}&select=id", {"reason": None, "decided_note": None},
            redact=True)
        done += len(got) if isinstance(got, list) else 0
    return done


def _count(stats: Dict[str, int], got: str, told: str) -> None:
    key = told if got == "told" else got
    if key in stats:
        stats[key] += 1


def _sweep_church(biz: Dict[str, Any], todo: Dict[str, List[Dict[str, Any]]], now: datetime,
                  stats: Dict[str, int]) -> None:
    import church_follow_up as cfu
    import church_map
    ch = co.Church(biz)
    b = ch.b
    mine = {k: [_bare(r) for r in rows if str(r.get("business_id")) == b] for k, rows in todo.items() if k != "old"}
    with church_map.once():
        today = cs._today(ch, now)
        near: Dict[str, List[Dict[str, str]]] = {}
        waiting = [a for a in mine.get("waiting", []) if a.get("state") == "asked" and not cs.needs_no_yes(ch, a)]
        # Its days have passed: it still waits for whoever opens it, and nobody is told of it any more.
        waiting = [a for a in waiting if (cs._day(a.get("ends_on")) or today) >= today]
        for a in waiting:
            cid = str(a.get("contact_id") or "")
            if cs.volunteer(a):
                # A volunteer's (S2-5) is their team's, never the leaders
                # map's: it stays while it sits with someone at the first
                # step of its team's chain, and is sent on only when it
                # doesn't (church_schedule_volunteers.stale).
                import church_schedule_volunteers as csv
                want = csv.stale(ch, a)
                if want and _move(ch, a, want, now):
                    stats["moved"] += 1
                continue
            if cs.flagged(a):
                # It went up for an exception (step 2): it stays with whoever
                # may give one, and is NEVER sent back down to the nearest
                # step. Only when it no longer sits with such a person (they
                # left the office, no longer oversee it, or are the login
                # that entered it) is it sent on, to whoever
                # church_schedule.goes_up gives now: never to the login that
                # entered it, who can't answer it.
                if not cs.held_right(ch, a) and _move(ch, a, cs.goes_up(ch, cid, entered=a.get("made_by")), now):
                    stats["moved"] += 1
                continue
            if cid not in near:
                near[cid] = cs.nearest(ch, cid)
            if near[cid] and _stale(ch, a, near[cid]) and _move(ch, a, near[cid][0], now):
                stats["moved"] += 1
        fresh = now - timedelta(seconds=SETTLE_SECONDS)
        for a in waiting:
            made = cfu._parse(a.get("created_at"))
            if not a.get("told_at") and (not made or made <= fresh):
                _count(stats, tell_new(ch, a, now=now), "told")
        for a in mine.get("cant", []):
            if a.get("kind") == "cant" and a.get("state") == "yes" and not a.get("told_at") \
                    and (cs._day(a.get("ends_on")) or today) >= today:
                _count(stats, tell_new(ch, a, now=now), "told")
        for a in mine.get("answered", []):
            _count(stats, tell_answer(ch, a, now=now), "answers")
        for a in waiting:
            if a.get("told_at") and not a.get("nudged_at"):
                _count(stats, tell_nudge(ch, a, now=now), "nudged")
        cutoff = today - timedelta(days=REASON_DAYS)
        old = [str(r["id"]) for r in todo.get("old", []) if str(r.get("business_id")) == b and r.get("id")
               and (cs._day(r.get("ends_on")) or today) < cutoff]
        if old:
            stats["cleared"] += _clear_reasons(b, old, cutoff)


def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Hourly, on the worker (kmj_intake_automation): asks sent on to whoever
    is over the asker now, untold asks and answers told, the one nudge, and
    reasons and answers' notes cleared 90 days after the last day. Quiet (not one read) with the
    switch off, and before the migration (only church_schedule.ready's own
    check). Only the churches church_assignments._open_churches() gives that
    CHURCH_SCHEDULE is open for too; never a sample church. A church that
    fails never stops the others."""
    stats = {"churches": 0, "moved": 0, "told": 0, "answers": 0, "nudged": 0, "cleared": 0, "held": 0,
             "unsent": 0, "unread": 0}
    if cs.mode() == "off" or not cs.ready():
        return stats
    import church_assignments as cas
    import church_follow_up as cfu
    import sample_church
    now = now or cs._now()
    churches = cas._open_churches()
    if churches is not None:
        churches = [b for b in churches if cs.church_open(b["id"])]
        if not churches:
            return stats
    scope = "" if churches is None else f"&business_id=in.({','.join(_q(b['id']) for b in churches)})"
    day = now.date()            # the query's day; each church's own clock decides in _sweep_church
    # Each read names the state it is for: the untold index keeps answered and withdrawn rows too. A
    # volunteer's ask names its team (step 2's column, so read only where step 2 is there).
    team = ",team_group_id" if cs.step2() else ""
    waiting = _all(f"/church_away_asks?state=eq.asked{scope}&select={FIELDS}{team}", "the asks still waiting")
    if waiting is None:
        return stats            # the read failed: next hour
    cant = _all(f"/church_away_asks?state=eq.yes&kind=eq.cant&told_at=is.null"
                f"&ends_on=gte.{(day - timedelta(days=1)).isoformat()}{scope}&select={FIELDS}",
                "the untold can't-make-its") or []
    answered = _all(f"/church_away_asks?state=in.(yes,no)&answer_told_at=is.null"
                    f"&decided_at=gte.{_q(cs._iso(now - timedelta(days=ANSWER_DAYS)))}"
                    f"&or=(decided_by_user_id.not.is.null,decided_by_contact_id.not.is.null){scope}&select={FIELDS}",
                    "the untold answers") or []
    old = _all(f"/church_away_asks?{PRIVATE}&ends_on=lt.{(day - timedelta(days=REASON_DAYS - 1)).isoformat()}"
               f"{scope}&select=id,business_id,ends_on", "the reasons to clear") or []
    work: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for kind, rows in (("waiting", waiting), ("cant", cant), ("answered", answered), ("old", old)):
        for r in rows:
            work.setdefault(str(r.get("business_id")), {})\
                .setdefault(kind, []).append(r)
    if not work:
        return stats
    bizs: Dict[str, Dict[str, Any]] = {str(b["id"]): b for b in churches or []}
    for chunk in co._chunks((b for b in work if b not in bizs), co.IDS_PER_READ):
        for x in sb_clients.sb_get_as_service(f"/businesses?id=in.({','.join(_q(i) for i in chunk)})"
                                              f"&select={cas.BIZ_FIELDS}&limit={co.IDS_PER_READ}") or []:
            bizs[str(x["id"])] = x
    bizs = sample_church.drop_sample_map(bizs)
    for b, todo in work.items():
        biz = bizs.get(b)
        if not biz or not cfu.is_church(biz) or not cs.church_open(b):
            continue
        stats["churches"] += 1
        try:
            _sweep_church(biz, todo, now, stats)
        except Exception:  # noqa: BLE001 — one church never stops the others
            logger.warning("leaders schedule sweep failed for business %s", b[:8], exc_info=True)
    return stats
