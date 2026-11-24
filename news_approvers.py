"""
news_approvers.py — who approves the good news members share, and where.

Kevin, 2026-11-24, on the approved canvas "Good News Approvals"
(Ktoy4b4qXoCDPCDoRmCGxj): "send a post request to the pastor's or assigned
leader to approve post in the app serve tab area." His go-ahead: "build it".

WHO APPROVES
  * the pastors: the church's owner (settings.church_owner_contact_id, their
    own member record) and every active owner or admin office login that is
    tied to a member record (business_users.contact_id)
  * the leaders the office picks (settings.news.approvers: contact ids, at
    most PICKED_MAX), from its leaders and group leaders
  A picked leader approves alone; whoever answers first decides (the update
  only lands on a row still waiting). Good news whose words the check
  marked as about self-harm (attach.flag 'care') is for the pastors only:
  picked leaders neither hear about it nor see it.

WHERE
  * a note on their phones when one comes in (notify; settings.news.
    approver_alerts, on unless the office turns it off). It goes as the
    church's Serving note where the church has those on, else as News, and
    it waits out quiet hours like every News note
  * the member app's Serve page, "To approve" on top (member_portal_serving:
    Post it, Edit first, Not now), and what someone else answered in the
    last TAKEN_HOURS, with who
  * the office, as before: News & celebrations → Waiting for you (news_share)
    and a card on Home (count)

Everything that decides goes through settle(), the office's button and the
app's alike, so a post is told to its writer and rings the members who
chose Everything the same way from both.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import sb_clients

logger = logging.getLogger("news_approvers")

PICKED_KEY = "approvers"          # settings.news.approvers
ALERTS_KEY = "approver_alerts"    # settings.news.approver_alerts (False when off)
PICKED_MAX = 12
TAKEN_HOURS = 6                   # what someone else answered stays this long, with who
WAITING_READ = 20
PASTOR, LEADER = "pastor", "leader"


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    """news_share's clock, so the office's button and the app's write the
    same times (and a test's fixed clock holds for both)."""
    import news_share
    return news_share._now()


def _news(business: Dict[str, Any]) -> Dict[str, Any]:
    s = (business or {}).get("settings")
    n = s.get("news") if isinstance(s, dict) else None
    return n if isinstance(n, dict) else {}


def picked(business: Dict[str, Any]) -> List[str]:
    """The leaders the office picked, in the order it picked them."""
    raw = _news(business).get(PICKED_KEY)
    out: List[str] = []
    for c in raw if isinstance(raw, list) else []:
        c = str(c or "").lower()
        if c and c not in out:
            out.append(c)
    return out[:PICKED_MAX]


def alerts_on(business: Dict[str, Any]) -> bool:
    return _news(business).get(ALERTS_KEY) is not False


def owner_contact(business: Dict[str, Any]) -> str:
    s = (business or {}).get("settings")
    return str((s or {}).get("church_owner_contact_id") or "").lower() if isinstance(s, dict) else ""


def office_contacts(business_id: str) -> Optional[List[str]]:
    """The member records of the church's owner and admin office logins.
    None when the read failed."""
    rows = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{_q(business_id)}&status=eq.active&role=in.(owner,admin)"
        f"&contact_id=not.is.null&select=contact_id&limit=50")
    if rows is None:
        return None
    return sorted({str(r["contact_id"]).lower() for r in rows if r.get("contact_id")})


def pastors(business: Dict[str, Any]) -> Optional[List[str]]:
    office = office_contacts(str(business["id"]))
    if office is None:
        return None
    own = owner_contact(business)
    return ([own] if own else []) + [c for c in office if c != own]


def role(business: Dict[str, Any], me_id: str) -> Optional[str]:
    """PASTOR, LEADER or '' for this member; None when the read failed."""
    me_id = str(me_id or "").lower()
    if not me_id:
        return ""
    if me_id == owner_contact(business):
        return PASTOR
    office = office_contacts(str(business["id"]))
    if office is None:
        return None
    if me_id in office:
        return PASTOR
    return LEADER if me_id in picked(business) else ""


def may_see(role_: Optional[str], post: Dict[str, Any]) -> bool:
    """A picked leader never sees good news the check marked as about
    self-harm; the pastors see everything waiting."""
    if role_ == PASTOR:
        return True
    att = post.get("attach") if isinstance(post.get("attach"), dict) else {}
    return role_ == LEADER and att.get("flag") != "care"


# ─── the note ────────────────────────────────────────────────────────


def notify(business: Dict[str, Any], post: Dict[str, Any], writer: str) -> int:
    """Tell the approvers a member shared good news. How many phones it
    reached; 0 quietly when the church turned it off or push isn't set up.
    Never raises."""
    try:
        return _notify(business, post, writer)
    except Exception:  # noqa: BLE001 — the good news is saved; the note is best effort
        logger.warning("good news approver note failed", exc_info=True)
        return 0


def _notify(business: Dict[str, Any], post: Dict[str, Any], writer: str) -> int:
    import member_push
    if not alerts_on(business):
        return 0
    att = post.get("attach") if isinstance(post.get("attach"), dict) else {}
    who = pastors(business)
    if who is None:
        return 0
    if att.get("flag") != "care":
        who = who + [c for c in picked(business) if c not in who]
    poster = str(post.get("posted_by") or "").lower()
    who = [c for c in who if c != poster]
    if not who:
        return 0
    first = (str(writer or "").split() or ["A member"])[0]
    what = str(post.get("title") or "good news")
    what = what[:1].lower() + what[1:]
    body = (f"{first} shared good news. Read it first, then post it or save it for later."
            if att.get("flag") else f"{first} shared: {what}. Tap to read it and post it for the church.")
    kinds = member_push.church_kinds(business.get("settings"))
    kind = "serving" if "serving" in kinds else "news"
    return member_push.send(business, kind, title="Good news is waiting for you", body=body,
                            url="/my/serving#approve", contact_ids=who, ref_id=f"good-news-ask:{post['id']}",
                            tag=f"good-news-ask-{post['id']}", wait=True)


# ─── what waits, in the app ──────────────────────────────────────────


def _decider(business: Dict[str, Any], decided_by: str, people: Dict[str, Dict[str, Any]]) -> str:
    """Who answered: a member record ('contact:<id>', from the app) or an
    office login (its user id)."""
    d = str(decided_by or "")
    if d.startswith("contact:"):
        return (people.get(d[len("contact:"):].lower()) or {}).get("name") or "Someone"
    if not d:
        return "Someone"
    if d == str(business.get("owner_id") or ""):
        own = people.get(owner_contact(business)) or {}
        s = business.get("settings") if isinstance(business.get("settings"), dict) else {}
        return own.get("name") or s.get("practitioner_name") or "Your pastor"
    try:
        import business_users_router as bur
        seat = bur.seat_person(str(business["id"]), d) or {}
    except Exception:  # noqa: BLE001 — a name is a nicety
        seat = {}
    return seat.get("name") or "Someone in the office"


def for_me(business: Dict[str, Any], me_id: str) -> Optional[Dict[str, Any]]:
    """What waits for this member to approve, and what someone else answered
    lately: {"role", "waiting": [...], "taken": [...]}. {} for a member who
    doesn't approve; None when a read failed."""
    import church_news as cn
    import news_share as ns
    r = role(business, me_id)
    if r is None:
        return None
    if not r:
        return {}
    b = _q(business["id"])
    since = _q((_now() - timedelta(days=ns.SAVED_DAYS)).isoformat())
    base = f"/church_posts?business_id=eq.{b}&source=eq.member&removed_at=is.null&group_id=is.null"
    rows = sb_clients.sb_get_as_service(
        f"{base}&status=eq.waiting&created_at=gte.{since}&select=id,title,body,attach,posted_by,created_at"
        f"&order=created_at.asc&limit={WAITING_READ}")
    lately = _q((_now() - timedelta(hours=TAKEN_HOURS)).isoformat())
    gone = sb_clients.sb_get_as_service(
        f"{base}&status=in.(posted,declined)&decided_at=gte.{lately}&decided_by=neq.{_q('contact:' + str(me_id))}"
        f"&select=id,title,body,attach,posted_by,status,decided_at,decided_by&order=decided_at.desc&limit=10")
    if rows is None or gone is None:
        return None
    rows = [p for p in rows if may_see(r, p)]
    gone = [p for p in gone if may_see(r, p)]
    ids = [p.get("posted_by") for p in rows + gone]
    ids += [str(p.get("decided_by"))[len("contact:"):] for p in gone if str(p.get("decided_by") or "").startswith("contact:")]
    ids.append(owner_contact(business))
    people = cn._people(str(business["id"]), [i for i in ids if i])
    if people is None:
        return None
    people = {k.lower(): v for k, v in people.items()}
    if "owner_id" not in business and any(not str(p.get("decided_by") or "").startswith("contact:") for p in gone):
        # The member app's church row may not carry the owner's login: read
        # it, so the pastor's own answer from the office reads as theirs.
        own = sb_clients.sb_get_as_service(f"/businesses?id=eq.{b}&select=owner_id&limit=1") or []
        business = {**business, "owner_id": (own[0].get("owner_id") if own else None)}

    def card(p: Dict[str, Any]) -> Dict[str, Any]:
        att = p.get("attach") if isinstance(p.get("attach"), dict) else {}
        return {"id": str(p["id"]), "name": (people.get(str(p.get("posted_by") or "").lower()) or {}).get("name") or "A member",
                "what": p.get("title") or "Good news", "body": p.get("body") or "",
                "photos": len(ns.pics_of(p)), "flag": att.get("flag") or "",
                "for": "their groups" if att.get("groups") else "the whole church",
                "created_at": p.get("created_at") or ""}
    return {"role": r, "waiting": [card(p) for p in rows],
            "taken": [{**card(p), "status": p.get("status"), "decided_at": p.get("decided_at") or "",
                       "by": _decider(business, str(p.get("decided_by") or ""), people)} for p in gone]}


def one(business: Dict[str, Any], me_id: str, post_id: str) -> Optional[Dict[str, Any]]:
    """One waiting post this member may approve, as for_me's card; {} when
    it isn't there (or isn't theirs to see); None when a read failed."""
    got = for_me(business, me_id)
    if got is None:
        return None
    return next((c for c in got.get("waiting") or [] if c["id"] == str(post_id)), {})


def count(business: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The office Home's card: how many wait for the whole church, the
    newest's time and the first few writers. None when a read failed."""
    import church_news as cn
    import news_share as ns
    b = _q(business["id"])
    since = _q((_now() - timedelta(days=ns.SAVED_DAYS)).isoformat())
    rows = sb_clients.sb_get_as_service(
        f"/church_posts?business_id=eq.{b}&source=eq.member&status=eq.waiting&removed_at=is.null&group_id=is.null"
        f"&created_at=gte.{since}&select=id,title,posted_by,created_at&order=created_at.desc&limit=60")
    if rows is None:
        return None
    people = cn._people(str(business["id"]), [r.get("posted_by") for r in rows[:3]]) or {}
    return {"waiting": len(rows), "newest_at": rows[0]["created_at"] if rows else None,
            "first": [{"name": (people.get(str(r.get("posted_by") or "")) or {}).get("name") or "A member",
                       "what": r.get("title") or "Good news"} for r in rows[:3]]}


def leader_desk(business: Dict[str, Any], me_id: str) -> Optional[Dict[str, Any]]:
    """A picked leader's Home strip, in desk_counts' shape (member_portal_
    lumen): only the good news, never what's marked as about self-harm.
    {} for anyone the office didn't pick; None when the read failed."""
    import news_share as ns
    if str(me_id or "").lower() not in picked(business):
        return {}
    since = _q((_now() - timedelta(days=ns.SAVED_DAYS)).isoformat())
    rows = sb_clients.sb_get_as_service(
        f"/church_posts?business_id=eq.{_q(business['id'])}&source=eq.member&status=eq.waiting&removed_at=is.null"
        f"&group_id=is.null&created_at=gte.{since}&select=id,attach,created_at&order=created_at.desc&limit=60")
    if rows is None:
        return None
    rows = [r for r in rows if may_see(LEADER, r)]
    return {"good": len(rows), "good_more": len(rows) >= 60,
            "good_at": str(rows[0].get("created_at") or "") if rows else "",
            "held_posts": 0, "held_comments": 0, "held_more": False}


# ─── deciding: the office's button and the app's ─────────────────────


def settle(business: Dict[str, Any], post_id: str, action: str, *, decided_by: str,
           body: Optional[str] = None, drop_photo: bool = False,
           statuses: Tuple[str, ...] = ("waiting", "declined")) -> Tuple[str, Optional[Dict[str, Any]], bool]:
    """Post it (as written or edited) or Not now. (code, post, told):
    code posted, later, gone (already decided, or not there), empty (an
    edit with no words), error (a read or write failed)."""
    import chat_photos
    import church_news as cn
    import news_alerts
    import news_share as ns
    biz_id = str(business["id"])
    st = ",".join(statuses)
    rows = sb_clients.sb_get_as_service(
        f"/church_posts?id=eq.{_q(post_id)}&business_id=eq.{_q(biz_id)}&source=eq.member&group_id=is.null"
        f"&status=in.({st})&removed_at=is.null&select=id,status,title,attach,posted_by&limit=1")
    if rows is None:
        return "error", None, False
    if not rows:
        return "gone", None, False
    now = _now().isoformat()
    if action == "later":
        patch: Dict[str, Any] = {"status": "declined", "decided_at": now, "decided_by": decided_by}
    else:
        patch = {"status": "posted", "publish_at": now, "decided_at": now, "decided_by": decided_by}
        if body is not None:
            text = ns.clean(body)
            if not text:
                return "empty", None, False
            patch["body"] = text[:ns.TEXT_MAX]
    dropped: List[str] = []
    if drop_photo and action != "later":
        att = dict(rows[0].get("attach") if isinstance(rows[0].get("attach"), dict) else {})
        dropped = [str(p["path"]) for p in ns.pics_of(rows[0]) if str(p["path"]).startswith(f"{biz_id}/news-photos/")]
        att.pop("pics", None)
        patch["attach"] = att
    done = sb_clients.sb_patch_as_service(
        f"/church_posts?id=eq.{_q(post_id)}&business_id=eq.{_q(biz_id)}&status=in.({st})", patch)
    if done is None:
        return "error", None, False
    if not done:
        return "gone", None, False
    for path in dropped:
        chat_photos.drop(path)
    if action == "later":
        return "later", done[0], False
    post = {**rows[0], **done[0]}
    told = ns._tell(business, post)
    # Members who chose Everything hear about it too (news_alerts).
    news_alerts.alert_later(business, post)
    return "posted", post, told
