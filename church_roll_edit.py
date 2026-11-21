"""church_roll_edit.py — changing the roll: a person's page edits in place,
adding people and whole families, Tidy up, and merging two records.

Kevin, 2026-11-20: "the ability to edited names and enter new people is
off", then on the mock (artifact 8UafD2wJsRm9cq5HhoB9h7) "build and push to
churches as well". His follow-up the same day: a number with no name stays
in its own list until it has a profile, and the people who are members are
recognized as members and not lost.

What that means here:

    NAMELESS ... a contact whose name is only a phone number (someone texted
                 in from a number nobody knew) is `noname`. The roll keeps
                 them out of the people, the counts and the lenses (the
                 page shows them as their own list) until somebody names
                 them, and naming one makes them a guest, never a member
    MEMBERS .... Member is never set by anything automatic. A member counts
                 as CONFIRMED when the office marked them a member here
                 (metadata.member_confirmed), the church register has the
                 day they joined, they came over in an import as a member,
                 or they lead (a leader role or a group they lead). Tidy up
                 lists the members with none of those once, to keep or make
                 a guest
    MATCHING ... naming a number offers the people already on the roll it
                 might be (the page searches as the office types); "this is
                 Danielle" merges the number's record into hers, so a member
                 whose phone was never on file isn't split in two
    NOTHING IS DELETED. A merged record is kept, hidden from the roll
                 (status inactive, metadata.merged_into), with anything that
                 couldn't be moved still on it. "Added by mistake" is a
                 reason on an inactive record, not a delete

Writes go as the server (service role) behind the roll's own gate
(church_roll._gate: a church, the owner or a staff seat of manager and up,
the People & care or Office areas): a staff login's own JWT write is
swallowed by row security. Every change is logged as an event on the person.

Switch: CHURCH_ROLL_EDIT off | owner (the platform owner only) | on, default
on (every church). Off, the person's page is read-only again and says so
through `can_edit`.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Query

import church_families
import church_roll as cr
import sb_clients
from auth_supabase import UserSession
from business_access import business_access

router = APIRouter(prefix="/church/roll", tags=["church"])

STATUS_IN = {"guest": "lead", "member": "active", "leader": "vip", "inactive": "inactive"}
RANK = {"vip": 3, "active": 2, "lead": 1, "inactive": 0, "churned": 0}
GENDERS = {"woman", "man", ""}
MARITAL = {"single", "married", "widowed", "divorced", ""}
FOUND = {"friend": "Friend or family", "online": "Online", "drove_by": "Drove by", "event": "An event"}
ADD_STATUS = {"first_time": "lead", "coming_back": "lead", "member": "active"}
MOST_PEOPLE = 12              # one Add people sheet
MOST_HISTORY = 50
PARTICLES = {"de", "la", "del", "della", "der", "van", "von", "da", "di", "du", "le", "dos", "das", "y", "bin", "ibn", "al",
             "of", "the", "and", "for", "in"}       # "Elevation of Grace": a ministry's small words stay small
SUFFIX_UP = {"ii", "iii", "iv", "vi"}
SUFFIX_CAP = {"jr": "Jr", "sr": "Sr", "jr.": "Jr.", "sr.": "Sr."}
# The tables whose rows point at a person and move on a merge. Anything
# not here, or refused (two rows for the same group would collide), stays
# on the kept-but-hidden record: nothing is lost, it is only not moved.
MOVE: Tuple[Tuple[str, str], ...] = (
    ("events", "contact_id"), ("sms_messages", "contact_id"), ("attendance", "contact_id"),
    ("invoices", "contact_id"), ("church_follow_ups", "contact_id"), ("group_members", "contact_id"),
    ("household_adults", "contact_id"), ("children", "contact_id"), ("church_leader_roles", "contact_id"),
    ("serve_trained", "contact_id"), ("serve_assignments", "contact_id"), ("church_shepherds", "shepherd_contact_id"),
    ("church_pledges", "contact_id"), ("agent_queue", "contact_id"),
)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TWO_RE = re.compile(r"^([A-Za-z][A-Za-z'’\-]*)\s+(?:and|&)\s+([A-Za-z][A-Za-z'’\-]*)\s+([A-Za-z][A-Za-z'’\- ]*)$", re.I)
GUESS_SAID = re.compile(r"\b(?:this is|it'?s|it is|my name is|i am|i'm|im)\s+([A-Za-z][a-z'’\-]{1,20})\b", re.I)
GUESS_SIGNED = re.compile(r"(?:^|\s)[-–—~]\s*([A-Za-z][a-z'’\-]{1,20})\s*[.!]?\s*$")
NOT_NAMES = {"a", "an", "the", "not", "here", "coming", "going", "good", "fine", "ok", "okay", "yes", "no", "so",
             "just", "me", "interested", "ready", "late", "out", "on", "at", "in", "sorry", "back", "done", "on",
             "your", "you", "my", "from", "with", "for", "to", "there", "running", "still", "also", "really",
             "pastor", "church", "god", "jesus", "amen", "thanks", "thank", "blessed", "praying", "texting"}


# ─── The switch ───────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_ROLL_EDIT") or "on").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: Any) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (getattr(user, "email", "") or "").strip().lower() == owner
    return False


def _gate(biz: Dict[str, Any], session: UserSession) -> Tuple[str, Any, str]:
    b, user, role = cr._gate(biz, session)
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    return b, user, role


# ─── Small things ─────────────────────────────────────────────────────

_q = cr._q
_plain = cr._plain


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _meta(c: Dict[str, Any]) -> Dict[str, Any]:
    m = c.get("metadata")
    return dict(m) if isinstance(m, dict) else {}


is_number = cr.is_number


def _text(v: Any, most: int) -> str:
    return _plain(v)[:most]


def _iso_day(v: Any, what: str) -> Optional[str]:
    """'' or None clears; else a real date, YYYY-MM-DD."""
    s = _plain(v)
    if not s:
        return None
    try:
        d = date.fromisoformat(s[:10])
    except ValueError:
        raise HTTPException(400, f"That {what} isn’t a date. Pick one from the calendar.")
    if not (1900 <= d.year <= 2100):
        raise HTTPException(400, f"That {what} isn’t a date we can keep.")
    return d.isoformat()


def _email(v: Any) -> Optional[str]:
    s = _plain(v)
    if not s:
        return None
    if len(s) > 200 or not EMAIL_RE.match(s):
        raise HTTPException(400, "That email doesn’t look right. Check it and try again.")
    return s


def _phone(v: Any) -> Optional[str]:
    s = _plain(v)
    if not s:
        return None
    if len(s) > 40 or sum(ch.isdigit() for ch in s) < 7:
        raise HTTPException(400, "That number looks too short. Check it and try again.")
    return s


def _last10(v: Any) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())[-10:]


def _contact(b: str, cid: str) -> Dict[str, Any]:
    rows = cr._need(f"/contacts?business_id=eq.{_q(b)}&id=eq.{_q(cid)}"
                    "&select=id,name,email,phone,birthdate,status,tags,metadata,created_at&limit=1")
    if not rows:
        raise HTTPException(404, "They aren’t on this church’s roll.")
    return rows[0]


def _save(b: str, cid: str, fields: Dict[str, Any]) -> None:
    saved = sb_clients.sb_patch_as_service(f"/contacts?id=eq.{_q(cid)}&business_id=eq.{_q(b)}", fields)
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn’t save. Nothing changed. Try again in a moment.")


def _event(b: str, cid: str, kind: str, data: Dict[str, Any]) -> None:
    try:
        sb_clients.sb_post_as_service("/events", {"business_id": b, "contact_id": cid, "event_type": kind,
                                                  "data": data, "source": "church_roll"}, prefer="return=minimal")
    except Exception:
        pass                    # the change stands without its line


def _forget(b: str) -> None:
    cr._cache.pop(str(b), None)


def _child_row(b: str, cid: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(f"/children?business_id=eq.{_q(b)}&contact_id=eq.{_q(cid)}"
                                        "&select=id,household_id,grade,birthdate,active&limit=1")
    return rows[0] if isinstance(rows, list) and rows else None


def _household_of(b: str, cid: str) -> str:
    rows = sb_clients.sb_get_as_service(f"/household_adults?business_id=eq.{_q(b)}&contact_id=eq.{_q(cid)}"
                                        "&select=household_id&limit=1")
    if isinstance(rows, list) and rows:
        return str(rows[0].get("household_id") or "")
    kid = _child_row(b, cid)
    return str(kid.get("household_id") or "") if kid else ""


def _household(b: str, hid: str) -> Dict[str, Any]:
    rows = cr._need(f"/households?business_id=eq.{_q(b)}&id=eq.{_q(cr._uuid(hid))}&select=id,name&limit=1")
    if not rows:
        raise HTTPException(404, "That family isn’t on this church’s roll.")
    return rows[0]


# ─── Names ────────────────────────────────────────────────────────────

def _case_word(w: str, first: bool) -> str:
    low = w.lower()
    if not first and low in PARTICLES:
        return low
    if low in SUFFIX_UP:
        return low.upper()
    if low in SUFFIX_CAP:
        return SUFFIX_CAP[low]
    out = []
    for part in re.split(r"([\-'’])", w):
        if not part or part in "-'’":
            out.append(part)
            continue
        p = part[0].upper() + part[1:]
        if len(p) > 3 and p.lower().startswith("mc"):
            p = "Mc" + p[2].upper() + p[3:]
        out.append(p)
    return "".join(out)


def cased(name: str) -> str:
    """A name with its small-letter words capitalised (o'neal → O'Neal,
    mcallister → McAllister, de la Cruz keeps its particles), and a name in
    all capitals put into ordinary case. Words already capitalised stay as
    they were typed (DeShawn, LaToya)."""
    words = _plain(name).split(" ")
    shout = len(_plain(name)) > 3 and _plain(name).upper() == _plain(name) and any(ch.isalpha() for ch in name)
    out = []
    for i, w in enumerate(words):
        if not w:
            continue
        if shout:
            w = w.lower()
        if w[:1].isalpha() and w[:1].islower() or shout:
            out.append(_case_word(w, i == 0))
        else:
            out.append(w)
    return " ".join(out)


def needs_case(name: str) -> bool:
    n = _plain(name)
    return bool(n) and not is_number(n) and cased(n) != n


def split_two(name: str) -> Optional[Tuple[str, str]]:
    """'Liyah And Meyah Tornes' → ('Liyah Tornes', 'Meyah Tornes')."""
    m = TWO_RE.match(_plain(name))
    if not m:
        return None
    a, b2, last = m.group(1), m.group(2), _plain(m.group(3))
    return f"{a} {last}", f"{b2} {last}"


def guess_name(texts: Iterable[str]) -> str:
    """A first name the texts themselves give ('this is Renee', '- Renee'),
    or ''. A guess for the office to accept or ignore, never saved alone."""
    for t in texts:
        s = _plain(t)
        for rx in (GUESS_SAID, GUESS_SIGNED):
            m = rx.search(s)
            if m:
                w = m.group(1).strip("'’-")
                if w and w.lower() not in NOT_NAMES and len(w) >= 2:
                    return w[0].upper() + w[1:].lower()
    return ""


def _parts(c: Dict[str, Any]) -> Tuple[str, str]:
    """Their first and last name as the roll reads them."""
    name, m = _plain(c.get("name")), _meta(c)
    if is_number(name):
        return "", ""
    first = cr.first_of(name, _plain(m.get("first_name")))
    last = cr.last_name(name, _plain(m.get("last_name")))
    if last == first and len(name.split(" ")) == 1:
        last = ""
    if first and name.lower().startswith(first.lower()) and last and name.lower().endswith(last.lower()):
        return first, last
    words = name.split(" ")
    return words[0], " ".join(words[1:])


# ─── A person's page: what it edits ───────────────────────────────────

def _said(b: str, cid: str, tz: Any) -> Tuple[Optional[Dict[str, str]], str]:
    rows = sb_clients.sb_get_as_service(
        f"/sms_messages?business_id=eq.{_q(b)}&contact_id=eq.{_q(cid)}&direction=eq.inbound"
        "&select=message,created_at&order=created_at.asc&limit=20")
    rows = rows if isinstance(rows, list) else []
    texts = [_plain(r.get("message")) for r in rows if _plain(r.get("message"))]
    if not texts:
        return None, ""
    first = next(r for r in rows if _plain(r.get("message")))
    at = cr._parse(first.get("created_at"))
    words = texts[0]
    said = {"t": words[:160] + ("…" if len(words) > 160 else ""), "d": cr.short(at.astimezone(tz).date()) if at else ""}
    return said, guess_name(texts)


def confirmed_by(c: Dict[str, Any], *, leads: bool, joined: bool) -> bool:
    m = _meta(c)
    return bool(leads or joined or m.get("member_confirmed") or m.get("imported_at") or m.get("imported_from")
                or str(c.get("source") or "").lower().startswith("import"))


def edit_block(ctx: Dict[str, Any], cid: str) -> Dict[str, Any]:
    """What the person's page edits: their values as stored, in the page's
    words. Read fresh, so a save shows at once."""
    b = ctx["biz_id"]
    c = _contact(b, cid)
    m = _meta(c)
    name = _plain(c.get("name"))
    noname = is_number(name)
    first, last = _parts(c)
    stored = cr.STATUS.get(str(c.get("status") or "").lower(), "member")
    kid = _child_row(b, cid)
    child = None
    if kid:
        care = sb_clients.sb_get_as_service(f"/child_care_notes?business_id=eq.{_q(b)}&child_id=eq.{_q(kid['id'])}"
                                            "&select=allergies&limit=1")
        child = {"id": str(kid["id"]), "grade": _plain(kid.get("grade")),
                 "allergies": _plain(care[0].get("allergies")) if isinstance(care, list) and care else ""}
    said, guess = _said(b, cid, ctx["tz"]) if noname else (None, "")
    p = ctx["by_id"].get(cid) or {}
    return {
        "first": first, "last": last, "goes_by": _plain(m.get("goes_by")),
        "status": stored,
        "mobile": _plain(c.get("phone")), "email": _plain(c.get("email")),
        "address": cr._address(m),
        "birthday": str(c.get("birthdate") or "")[:10] or (str(kid.get("birthdate") or "")[:10] if kid else ""),
        "gender": _plain(m.get("gender")).lower() if _plain(m.get("gender")).lower() in GENDERS else "",
        "marital": _plain(m.get("marital_status")).lower() if _plain(m.get("marital_status")).lower() in MARITAL else "",
        "anniversary": _plain(m.get("anniversary"))[:10],
        "emergency": _plain(m.get("emergency_contact")),
        "inactive_reason": _plain(m.get("inactive_reason")),
        "noname": noname,
        "confirmed": bool(p.get("confirmed")),
        "said": said, "guess": guess,
        "child": child,
        "household_id": (p.get("family") or {}).get("id") or "",
    }


# ─── Editing a person ─────────────────────────────────────────────────

def _leave_family(b: str, cid: str, *, keep: str = "") -> None:
    """Take an adult out of their family (every family but `keep`, the one
    they just joined). A delete that fails is a 503, never "saved"."""
    path = f"/household_adults?business_id=eq.{_q(b)}&contact_id=eq.{_q(cid)}"
    if keep:
        path += f"&household_id=neq.{_q(keep)}"
    if not sb_clients.sb_delete_as_service(path):
        raise HTTPException(503, "They’re still in their old family. Try again in a moment."
                            if keep else "They’re still in that family. Try again in a moment.")


def _family(b: str, c: Dict[str, Any], ask: Dict[str, Any]) -> str:
    """Join, start or leave a family. A move writes the new family first and
    takes the old row out after, so a failure never leaves someone in no
    family at all."""
    cid = str(c["id"])
    kid = _child_row(b, cid)
    if ask.get("leave"):
        if kid:
            raise HTTPException(400, "A child stays in a family. Move them to another family instead.")
        _leave_family(b, cid)
        return "family"
    if ask.get("join"):
        hid = str(_household(b, ask["join"])["id"])
        if kid:
            saved = sb_clients.sb_patch_as_service(f"/children?id=eq.{_q(kid['id'])}&business_id=eq.{_q(b)}",
                                                   {"household_id": hid})
            if not isinstance(saved, list) or not saved:
                raise HTTPException(503, "They didn’t move. Try again in a moment.")
            return "family"
        if _household_of(b, cid) != hid and not church_families.join_family(b, hid, [c], []):
            raise HTTPException(503, "They didn’t join that family. Nothing changed. Try again in a moment.")
        _leave_family(b, cid, keep=hid)
        return "family"
    if ask.get("start") is not None:
        if kid:
            raise HTTPException(400, "A child joins a family that has an adult in it.")
        name = _text(ask.get("start"), 120) or f"The {_parts(c)[1] or _plain(c.get('name'))} family"
        hid = church_families.make_family(b, name, [c], [])
        if not hid:
            raise HTTPException(503, "That family didn’t save. Nothing changed. Try again in a moment.")
        _leave_family(b, cid, keep=str(hid))
        return "family"
    raise HTTPException(400, "Say which family: join one, start one, or leave.")


def apply_edit(b: str, c: Dict[str, Any], body: Dict[str, Any], user: Any) -> List[str]:
    cid = str(c["id"])
    m = _meta(c)
    fields: Dict[str, Any] = {}
    saved: List[str] = []
    was_number = is_number(c.get("name"))
    before_status = str(c.get("status") or "")

    if any(k in body for k in ("first", "last", "goes_by")):
        first0, last0 = _parts(c)
        first = _text(body.get("first", first0), 60)
        last = _text(body.get("last", last0), 60)
        if "first" in body or "last" in body:
            if not first:
                raise HTTPException(400, "A first name is needed.")
            fields["name"] = f"{first} {last}".strip()
            m["first_name"], m["last_name"] = first, last
            saved.append("name")
            if was_number and "status" not in body:
                # Named at last: a guest, never a member by default.
                fields["status"] = "lead"
        if "goes_by" in body:
            m["goes_by"] = _text(body.get("goes_by"), 40)
            saved.append("goes_by")

    if "status" in body:
        s = str(body.get("status") or "")
        if s not in STATUS_IN:
            raise HTTPException(400, "Pick Guest, Member, Leader or Inactive.")
        fields["status"] = STATUS_IN[s]
        if s in ("member", "leader"):
            m["member_confirmed"] = {"by": str(getattr(user, "id", "") or ""), "at": _now().isoformat()}
        if s == "inactive":
            m["inactive_reason"] = _text(body.get("inactive_reason"), 60)
            m["inactive_on"] = date.today().isoformat()
        else:
            m.pop("inactive_reason", None)
            m.pop("inactive_on", None)
        saved.append("status")

    if "mobile" in body:
        fields["phone"] = _phone(body.get("mobile"))
        saved.append("mobile")
    if "email" in body:
        fields["email"] = _email(body.get("email"))
        saved.append("email")
    if "birthday" in body:
        fields["birthdate"] = _iso_day(body.get("birthday"), "birthday")
        saved.append("birthday")
    if "address" in body:
        a = _text(body.get("address"), 300)
        if a:
            m["address"] = a
        else:
            m.pop("address", None)
        saved.append("address")
    if "gender" in body:
        g = _plain(body.get("gender")).lower()
        if g not in GENDERS:
            raise HTTPException(400, "Pick Woman, Man or Not said.")
        m["gender"] = g
        saved.append("gender")
    if "marital" in body:
        v = _plain(body.get("marital")).lower()
        if v not in MARITAL:
            raise HTTPException(400, "Pick single, married, widowed or divorced.")
        m["marital_status"] = v
        saved.append("marital")
    if "anniversary" in body:
        m["anniversary"] = _iso_day(body.get("anniversary"), "anniversary") or ""
        saved.append("anniversary")
    if "emergency" in body:
        m["emergency_contact"] = _text(body.get("emergency"), 160)
        saved.append("emergency")

    if fields or saved:
        fields["metadata"] = m
        _save(b, cid, fields)

    # A child's own record: grade on the child row, allergies in the care notes.
    if "grade" in body or "allergies" in body:
        kid = _child_row(b, cid)
        if not kid:
            raise HTTPException(400, "Grade and allergies are kept for a child in a family.")
        if "grade" in body:
            done = sb_clients.sb_patch_as_service(f"/children?id=eq.{_q(kid['id'])}&business_id=eq.{_q(b)}",
                                                  {"grade": _text(body.get("grade"), 20)})
            if not isinstance(done, list) or not done:
                raise HTTPException(503, "The grade didn’t save. Try again in a moment.")
            saved.append("grade")
        if "allergies" in body:
            words = _text(body.get("allergies"), 200)
            have = sb_clients.sb_get_as_service(f"/child_care_notes?child_id=eq.{_q(kid['id'])}&select=child_id&limit=1")
            if isinstance(have, list) and have:
                ok = sb_clients.sb_patch_as_service(f"/child_care_notes?child_id=eq.{_q(kid['id'])}&business_id=eq.{_q(b)}",
                                                    {"allergies": words, "updated_by": str(getattr(user, "id", "") or "") or None})
            else:
                ok = sb_clients.sb_post_as_service("/child_care_notes", {"child_id": str(kid["id"]), "business_id": b,
                                                                         "allergies": words})
            if not isinstance(ok, list):
                raise HTTPException(503, "The allergies didn’t save. Try again in a moment.")
            saved.append("allergies")

    if isinstance(body.get("family"), dict):
        saved.append(_family(b, c, body["family"]))

    if "status" in fields and fields["status"] != before_status:
        _event(b, cid, "contact_status_changed", {"from": before_status, "to": fields["status"],
                                                   **({"reason": m.get("inactive_reason")} if fields["status"] == "inactive" else {})})
    if saved:
        _event(b, cid, "contact_edited", {"changes": saved, "edited_by": "church_roll"})
    return saved


# ─── Adding people ────────────────────────────────────────────────────

def add_people(b: str, body: Dict[str, Any], user: Any) -> Dict[str, Any]:
    people = body.get("people")
    if not isinstance(people, list) or not people:
        raise HTTPException(400, "Add at least one person.")
    if len(people) > MOST_PEOPLE:
        raise HTTPException(400, f"Add up to {MOST_PEOPLE} people at once.")
    status = ADD_STATUS.get(str(body.get("status") or "first_time"))
    if not status:
        raise HTTPException(400, "Say whether they’re first-time guests, coming back, or members.")
    found = str(body.get("found") or "")
    if found and found not in FOUND:
        raise HTTPException(400, "Pick how they found us from the list.")
    first_sunday = _iso_day(body.get("first_sunday"), "first Sunday")
    fam = body.get("family") if isinstance(body.get("family"), dict) else None
    join = str(body.get("join_household") or "")
    hid_join = str(_household(b, join)["id"]) if join else ""
    address = _text((fam or {}).get("address"), 300)

    # Check every row before anything is written.
    rows: List[Dict[str, Any]] = []
    for p in people:
        if not isinstance(p, dict):
            raise HTTPException(400, "Each person needs a first name.")
        kind = "child" if p.get("kind") == "child" else "adult"
        use = str(p.get("use_id") or "")
        first, last = _text(p.get("first"), 60), _text(p.get("last"), 60)
        if not use and not first:
            raise HTTPException(400, "Each person needs a first name.")
        rows.append({"use": cr._uuid(use) if use else "", "first": first, "last": last, "kind": kind,
                     "mobile": _phone(p.get("mobile")) if kind == "adult" else None,
                     "email": _email(p.get("email")) if kind == "adult" else None,
                     "birthday": _iso_day(p.get("birthday"), "birthday"),
                     "allergies": _text(p.get("allergies"), 200) if kind == "child" else ""})

    stamp = {"by": str(getattr(user, "id", "") or ""), "at": _now().isoformat()}
    made: List[Dict[str, Any]] = []
    for r in rows:
        if r["use"]:
            c = _contact(b, r["use"])
            fill: Dict[str, Any] = {}
            if r["mobile"] and not _plain(c.get("phone")):
                fill["phone"] = r["mobile"]
            if r["email"] and not _plain(c.get("email")):
                fill["email"] = r["email"]
            if r["birthday"] and not c.get("birthdate"):
                fill["birthdate"] = r["birthday"]
            if fill:
                _save(b, str(c["id"]), fill)
                c.update(fill)
            made.append({**r, "row": c})
            continue
        meta: Dict[str, Any] = {"first_name": r["first"], "last_name": r["last"], "added_on_roll": stamp}
        if address:
            meta["address"] = address
        if found:
            meta["found_us"] = FOUND[found]
        if first_sunday:
            meta["first_sunday"] = first_sunday
        if status == "active":
            meta["member_confirmed"] = stamp
        new = sb_clients.sb_post_as_service("/contacts", {
            "business_id": b, "name": f"{r['first']} {r['last']}".strip(), "phone": r["mobile"], "email": r["email"],
            "birthdate": r["birthday"], "status": status, "tags": ["child"] if r["kind"] == "child" else [],
            "source": "church_roll", "metadata": meta})
        if not isinstance(new, list) or not new:
            if made:
                raise HTTPException(503, f"{len(made)} of {len(rows)} were added before the rest didn’t save. "
                                         "Check the roll before adding again.")
            raise HTTPException(503, "Nobody was added. Try again in a moment.")
        made.append({**r, "row": new[0]})
        _event(b, str(new[0]["id"]), "contact_added", {"by": "church_roll", "status": status,
                                                        **({"found_us": FOUND[found]} if found else {})})

    adults = [x["row"] for x in made if x["kind"] == "adult"]
    kids = [x["row"] for x in made if x["kind"] == "child"]
    hid: Optional[str] = None
    warning = ""
    if hid_join:
        hid = hid_join if church_families.join_family(b, hid_join, adults, kids) else None
        warning = "" if hid else "They’re on the roll, but they didn’t join the family. Add them from their page."
    elif fam is not None or len(made) > 1 or kids:
        if kids and not adults:
            warning = "A child joins a family with an adult in it. Add them to a family from their page."
        else:
            last = next((x["last"] for x in made if x["last"]), "") or _parts(made[0]["row"])[1]
            name = _text((fam or {}).get("name"), 120)
            name = (name if name.lower().startswith("the ") else f"The {name} family") if name else f"The {last or 'new'} family"
            hid = church_families.make_family(b, name, adults, kids)
            warning = "" if hid else "They’re on the roll, but the family didn’t save. Add them to a family from their page."
    if hid:
        missed = []
        for x in made:
            if x["kind"] == "child" and x["allergies"]:
                kid = _child_row(b, str(x["row"]["id"]))
                ok = kid and sb_clients.sb_post_as_service("/child_care_notes", {
                    "child_id": str(kid["id"]), "business_id": b, "allergies": x["allergies"]})
                if not (isinstance(ok, list) and ok):
                    missed.append(x["first"] or "a child")
        if missed:
            # An allergy that didn't save is never silent.
            warning = (f"{' and '.join(missed)}’s allergies didn’t save. Add them on "
                       f"{'their pages' if len(missed) > 1 else 'their page'} before Sunday.")
    return {"ids": [str(x["row"]["id"]) for x in made], "household_id": hid, **({"warning": warning} if warning else {})}


# ─── Merging two records ──────────────────────────────────────────────

def _move_register(b: str, drop: str, keep: str) -> bool:
    rows = sb_clients.sb_get_as_service(f"/church_register_entries?business_id=eq.{_q(b)}&contact_ids=cs.{{{drop}}}"
                                        "&select=id,contact_ids,people&limit=500")
    if not isinstance(rows, list):
        return False
    ok = True
    for e in rows:
        ids = [keep if str(x) == drop else str(x) for x in (e.get("contact_ids") or [])]
        ids = list(dict.fromkeys(ids))
        people = [{**p, "contact_id": keep} if isinstance(p, dict) and str(p.get("contact_id") or "") == drop else p
                  for p in (e.get("people") or [])]
        done = sb_clients.sb_patch_as_service(f"/church_register_entries?id=eq.{_q(e['id'])}&business_id=eq.{_q(b)}",
                                              {"contact_ids": ids, "people": people})
        ok = ok and isinstance(done, list)
    return ok


def merge(b: str, keep_id: str, drop_id: str, *, use_number: bool = False) -> Dict[str, Any]:
    keep_id, drop_id = cr._uuid(keep_id), cr._uuid(drop_id)
    if keep_id == drop_id:
        raise HTTPException(400, "Pick two different people.")
    keep, drop = _contact(b, keep_id), _contact(b, drop_id)
    if _meta(keep).get("merged_into") or _meta(drop).get("merged_into"):
        raise HTTPException(409, "One of them was already merged. Refresh the roll.")
    km, dm = _meta(keep), _meta(drop)
    fields: Dict[str, Any] = {}
    others = [x for x in (km.get("other_phones") or []) if isinstance(x, str)]
    kp, dp = _plain(keep.get("phone")), _plain(drop.get("phone"))
    if dp and _last10(dp) != _last10(kp):
        if not kp or use_number:
            fields["phone"] = dp
            if kp:
                others.append(kp)
        else:
            others.append(dp)
    if others:
        km["other_phones"] = list(dict.fromkeys(others))[:6]
    if not _plain(keep.get("email")) and _plain(drop.get("email")):
        fields["email"] = _plain(drop.get("email"))
    if not keep.get("birthdate") and drop.get("birthdate"):
        fields["birthdate"] = drop["birthdate"]
    if is_number(keep.get("name")) and not is_number(drop.get("name")):
        fields["name"] = _plain(drop.get("name"))
    for k, v in dm.items():
        if k not in km and k not in ("merged_into", "merged_at", "inactive_reason", "inactive_on", "not_same"):
            km[k] = v
    ks, ds = str(keep.get("status") or ""), str(drop.get("status") or "")
    if RANK.get(ds, 0) > RANK.get(ks, 0) and not (ds == "active" and is_number(drop.get("name"))):
        fields["status"] = ds
    fields["metadata"] = km
    _save(b, keep_id, fields)

    # Hidden and marked first: a failure after this leaves rows still to
    # move, never a visible half-merged record that a retry merges again.
    dm.update({"merged_into": keep_id, "merged_at": _now().isoformat(), "inactive_reason": "merged"})
    _save(b, drop_id, {"status": "inactive", "metadata": dm})

    moved, left = [], []
    for table, col in MOVE:
        done = sb_clients.sb_patch_as_service(f"/{table}?business_id=eq.{_q(b)}&{col}=eq.{_q(drop_id)}", {col: keep_id})
        (moved if isinstance(done, list) else left).append(table)
    (moved if _move_register(b, drop_id, keep_id) else left).append("church_register_entries")
    _event(b, keep_id, "contact_merged", {"from": drop_id, "from_name": _plain(drop.get("name")), "moved": moved, "left": left})
    return {"ok": True, "kept": keep_id, "left": left}


# ─── Tidy up ──────────────────────────────────────────────────────────

def _line(p: Dict[str, Any]) -> str:
    s = p.get("sundays") or ""
    here, of = sum(1 for k in s if k in "PO"), sum(1 for k in s if k != "N")
    bits = [cr.STATUS_WORD.get(p.get("status"), "")]
    if p.get("family", {}).get("name"):
        bits.append(p["family"]["name"])
    bits.append(f"{here} of {of} Sundays" if of else "no Sundays yet")
    if not p.get("phone") and not p.get("email"):
        bits.append("no phone or email")
    return " · ".join(b2 for b2 in bits if b2)


def _maybe_same(a: Dict[str, Any], c: Dict[str, Any], why: str) -> bool:
    """Two records sharing a phone or an email are one person only when the
    first names agree or one has no name: a family shares a phone, and
    Jordan and Jayla Price are two people. Never two people in one family."""
    if a["family"]["id"] and a["family"]["id"] == c["family"]["id"]:
        return False
    if why == "same name" or a.get("noname") or c.get("noname"):
        return True
    fa, fc = (a.get("first") or "").lower(), (c.get("first") or "").lower()
    return bool(fa and fc) and (fa[:3] == fc[:3] or fa.startswith(fc) or fc.startswith(fa))


def tidy_lists(ctx: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """What Tidy up lists, from the roll just read: the numbers with no name,
    names in small letters, records that hold two people, people who may be
    on twice, and members with no reason on file."""
    live = [p for p in ctx["people"] if not p.get("_merged")]
    numbers = [{"id": p["id"], "phone": p["phone"] or p["name"], "status": p["status"]} for p in live if p.get("noname")]
    named = [p for p in live if not p.get("noname")]
    caps = [{"id": p["id"], "name": p["name"], "fixed": cased(p["name"])} for p in named if needs_case(p["name"])]
    two = []
    for p in named:
        s = split_two(p["name"])
        if s:
            two.append({"id": p["id"], "name": p["name"], "a": s[0], "b": s[1]})
    same: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str]] = set()
    by: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for p in live:
        if p["status"] == "inactive" and not p.get("noname"):
            continue
        if len(_last10(p.get("phone"))) == 10:
            by.setdefault(("same mobile", _last10(p["phone"])), []).append(p)
        if p.get("email"):
            by.setdefault(("same email", p["email"].lower()), []).append(p)
        if not p.get("noname") and len(p["name"].split(" ")) > 1:
            by.setdefault(("same name", p["name"].lower()), []).append(p)
    for (why, _), group in by.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, c = group[i], group[j]
                key = tuple(sorted((a["id"], c["id"])))
                if key in seen or c["id"] in (a.get("_not_same") or ()) or a["id"] in (c.get("_not_same") or ()):
                    continue
                if not _maybe_same(a, c, why):
                    continue
                seen.add(key)
                # The record to keep is the one with more on it: a name, then Sundays.
                if (a.get("noname"), -sum(1 for k in a["sundays"] if k in "PO")) > (c.get("noname"), -sum(1 for k in c["sundays"] if k in "PO")):
                    a, c = c, a
                same.append({"a": {"id": a["id"], "name": a["name"], "line": _line(a)},
                             "b": {"id": c["id"], "name": c["name"], "line": _line(c)},
                             "why": why})
    confirm = [{"id": p["id"], "name": p["name"], "line": _line(p) + " · no joined date or reason on file"}
               for p in named if p["status"] == "member" and not p.get("confirmed")]
    return {"numbers": numbers, "caps": caps, "two": two, "same": same[:100], "confirm": confirm}


def tidy_counts(ctx: Dict[str, Any]) -> Dict[str, int]:
    return {k: len(v) for k, v in tidy_lists(ctx).items()}


def _said_many(b: str, ids: List[str], tz: Any) -> Dict[str, Tuple[Optional[Dict[str, str]], str]]:
    out: Dict[str, Tuple[Optional[Dict[str, str]], str]] = {}
    texts: Dict[str, List[Tuple[Any, str]]] = {}
    for chunk in cr._chunks(ids, 80):
        rows = sb_clients.sb_get_as_service(
            f"/sms_messages?business_id=eq.{_q(b)}&contact_id=in.({','.join(chunk)})&direction=eq.inbound"
            "&select=contact_id,message,created_at&order=created_at.asc&limit=1000")
        for r in rows if isinstance(rows, list) else []:
            if _plain(r.get("message")):
                texts.setdefault(str(r.get("contact_id")), []).append((r.get("created_at"), _plain(r["message"])))
    for cid, items in texts.items():
        at = cr._parse(items[0][0])
        words = items[0][1]
        out[cid] = ({"t": words[:160] + ("…" if len(words) > 160 else ""),
                     "d": cr.short(at.astimezone(tz).date()) if at else ""}, guess_name(t for _, t in items))
    return out


# ─── Routes ───────────────────────────────────────────────────────────

@router.patch("/person/{contact_id}")
def edit_person(contact_id: str, body: Dict[str, Any] = Body(...), business_id: str = Query(...),
                biz: Dict[str, Any] = Depends(business_access(cr.MIN_ROLE)),
                session: UserSession = Depends(sb_clients.authed_request)):
    """Change one person where the page shows them."""
    b, user, _ = _gate(biz, session)
    c = _contact(b, cr._uuid(contact_id))
    if _meta(c).get("merged_into"):
        raise HTTPException(409, "That record was merged into another. Refresh the roll.")
    saved = apply_edit(b, c, body if isinstance(body, dict) else {}, user)
    _forget(b)
    return {"ok": True, "saved": saved}


@router.get("/person/{contact_id}/history")
def person_history(contact_id: str, kind: str = Query("notes"), business_id: str = Query(...),
                   biz: Dict[str, Any] = Depends(business_access(cr.MIN_ROLE)),
                   session: UserSession = Depends(sb_clients.authed_request)):
    """A person's notes, texts or emails, newest first."""
    b, _, _ = cr._gate(biz, session)
    cid = cr._uuid(contact_id)
    c = _contact(b, cid)
    import church_shepherd_signals as sig
    rule = sig.sunday_rule(biz)
    tz = rule[0] if rule else timezone.utc
    first = _parts(c)[0] or _plain(c.get("name"))

    def day(ts: Any) -> Tuple[Optional[datetime], str]:
        at = cr._parse(ts)
        if not at:
            return None, ""
        d = at.astimezone(tz).date()
        return at, (cr.short(d) if d.year == _now().astimezone(tz).year else f"{cr.short(d)}, {d.year}")

    items: List[Tuple[datetime, Dict[str, str]]] = []
    if kind == "notes":
        rows = cr._need(f"/events?business_id=eq.{_q(b)}&contact_id=eq.{_q(cid)}&event_type=eq.contact_note"
                        f"&select=data,source,created_at&order=created_at.desc&limit={MOST_HISTORY}")
        for r in rows:
            data = r.get("data") if isinstance(r.get("data"), dict) else {}
            at, d = day(r.get("created_at"))
            if at and _plain(data.get("note")):
                items.append((at, {"d": d, "t": _plain(data.get("note"))[:2000],
                                   "by": _plain(data.get("by") or data.get("by_name") or "")}))
    elif kind == "texts":
        rows = cr._need(f"/sms_messages?business_id=eq.{_q(b)}&contact_id=eq.{_q(cid)}&status=neq.failed"
                        f"&select=direction,message,created_at&order=created_at.desc&limit={MOST_HISTORY}")
        for r in rows:
            at, d = day(r.get("created_at"))
            if at:
                who = "The church" if r.get("direction") == "outbound" else first
                items.append((at, {"d": d, "t": f"{who}: {_plain(r.get('message'))[:600]}", "by": ""}))
    elif kind == "emails":
        ev = sb_clients.sb_get_as_service(f"/events?business_id=eq.{_q(b)}&contact_id=eq.{_q(cid)}&event_type=eq.email_sent"
                                          f"&select=data,created_at&order=created_at.desc&limit={MOST_HISTORY}")
        for r in ev if isinstance(ev, list) else []:
            data = r.get("data") if isinstance(r.get("data"), dict) else {}
            at, d = day(r.get("created_at"))
            if at:
                items.append((at, {"d": d, "t": _plain(data.get("subject")) or "An email", "by": ""}))
        q = sb_clients.sb_get_as_service(f"/agent_queue?business_id=eq.{_q(b)}&contact_id=eq.{_q(cid)}&status=eq.sent"
                                         f"&select=subject,created_at&order=created_at.desc&limit={MOST_HISTORY}")
        for r in q if isinstance(q, list) else []:
            at, d = day(r.get("created_at"))
            if at and not any(abs((at - x).total_seconds()) < 120 and v["t"] == (_plain(r.get("subject")) or "An email")
                              for x, v in items):
                items.append((at, {"d": d, "t": _plain(r.get("subject")) or "An email", "by": ""}))
    else:
        raise HTTPException(400, "Pick notes, texts or emails.")
    items.sort(key=lambda x: x[0], reverse=True)
    return {"items": [v for _, v in items[:MOST_HISTORY]]}


@router.post("/people")
def add(body: Dict[str, Any] = Body(...), business_id: str = Query(...),
        biz: Dict[str, Any] = Depends(business_access(cr.MIN_ROLE)),
        session: UserSession = Depends(sb_clients.authed_request)):
    """Add one person or a whole family."""
    b, user, _ = _gate(biz, session)
    out = add_people(b, body if isinstance(body, dict) else {}, user)
    _forget(b)
    return out


@router.post("/merge")
def merge_route(body: Dict[str, Any] = Body(...), business_id: str = Query(...),
                biz: Dict[str, Any] = Depends(business_access(cr.MIN_ROLE)),
                session: UserSession = Depends(sb_clients.authed_request)):
    """Two records for one person become one. The other is kept, hidden."""
    b, _, _ = _gate(biz, session)
    out = merge(b, str(body.get("keep") or ""), str(body.get("drop") or ""), use_number=bool(body.get("use_number")))
    _forget(b)
    return out


@router.get("/tidy")
def tidy(business_id: str = Query(...),
         biz: Dict[str, Any] = Depends(business_access(cr.MIN_ROLE)),
         session: UserSession = Depends(sb_clients.authed_request)):
    """What Tidy up lists, each with what to do about it."""
    b, _, _ = _gate(biz, session)
    ctx = cr._cached(biz, fresh=True)
    lists = tidy_lists(ctx)
    said = _said_many(b, [n["id"] for n in lists["numbers"]], ctx["tz"])
    for n in lists["numbers"]:
        s, g = said.get(n["id"], (None, ""))
        n["said"], n["said_on"], n["guess"] = (s or {}).get("t", ""), (s or {}).get("d", ""), g
    return lists


def _tidy_ctx(biz: Dict[str, Any]) -> Dict[str, Any]:
    return cr._cached(biz, fresh=True)


@router.post("/tidy/caps")
def tidy_caps(body: Dict[str, Any] = Body(default={}), business_id: str = Query(...),
              biz: Dict[str, Any] = Depends(business_access(cr.MIN_ROLE)),
              session: UserSession = Depends(sb_clients.authed_request)):
    """Capitalise the names in small letters (the ones ticked, or all)."""
    b, _, _ = _gate(biz, session)
    want = {str(x) for x in (body.get("ids") or [])} if isinstance(body, dict) and body.get("ids") is not None else None
    fixed = 0
    for row in tidy_lists(_tidy_ctx(biz))["caps"]:
        if want is not None and row["id"] not in want:
            continue
        c = _contact(b, row["id"])
        m = _meta(c)
        for k in ("first_name", "last_name"):
            if _plain(m.get(k)):
                m[k] = cased(_plain(m[k]))
        saved = sb_clients.sb_patch_as_service(f"/contacts?id=eq.{_q(row['id'])}&business_id=eq.{_q(b)}",
                                               {"name": cased(_plain(c.get("name"))), "metadata": m})
        if isinstance(saved, list) and saved:
            fixed += 1
            _event(b, row["id"], "contact_edited", {"changes": ["name"], "edited_by": "church_roll", "why": "capitals"})
    _forget(b)
    return {"fixed": fixed}


@router.post("/tidy/split")
def tidy_split(body: Dict[str, Any] = Body(...), business_id: str = Query(...),
               biz: Dict[str, Any] = Depends(business_access(cr.MIN_ROLE)),
               session: UserSession = Depends(sb_clients.authed_request)):
    """One record holding two people becomes two, in one family."""
    b, user, _ = _gate(biz, session)
    c = _contact(b, cr._uuid(body.get("id")))
    pair = split_two(c.get("name"))
    if not pair:
        raise HTTPException(400, "That name doesn’t hold two people.")
    a, b2 = pair
    m = _meta(c)
    af, al = a.split(" ", 1)
    bf, bl = b2.split(" ", 1)
    m["first_name"], m["last_name"] = af, al
    _save(b, str(c["id"]), {"name": a, "metadata": m})
    new = sb_clients.sb_post_as_service("/contacts", {
        "business_id": b, "name": b2, "status": c.get("status") or "lead", "tags": c.get("tags") or [],
        "source": "church_roll", "birthdate": None,
        "metadata": {"first_name": bf, "last_name": bl, "split_from": str(c["id"]),
                     "added_on_roll": {"by": str(getattr(user, "id", "") or ""), "at": _now().isoformat()}}})
    if not isinstance(new, list) or not new:
        raise HTTPException(503, f"{a} kept the record, but {b2} wasn’t added. Add them with Add people.")
    nid = str(new[0]["id"])
    hid = _household_of(b, str(c["id"]))
    kid = _child_row(b, str(c["id"]))
    if hid:
        church_families.join_family(b, hid, [] if kid else [new[0]], [new[0]] if kid else [])
    else:
        church_families.make_family(b, f"The {al} family", [c, new[0]], [])
    _event(b, str(c["id"]), "contact_edited", {"changes": ["name"], "edited_by": "church_roll", "why": "split", "into": nid})
    _forget(b)
    return {"ids": [str(c["id"]), nid]}


@router.post("/tidy/not-same")
def tidy_not_same(body: Dict[str, Any] = Body(...), business_id: str = Query(...),
                  biz: Dict[str, Any] = Depends(business_access(cr.MIN_ROLE)),
                  session: UserSession = Depends(sb_clients.authed_request)):
    """Two people Tidy up thought were one are two: it won't ask again."""
    b, _, _ = _gate(biz, session)
    a, c = _contact(b, cr._uuid(body.get("a"))), _contact(b, cr._uuid(body.get("b")))
    for x, y in ((a, c), (c, a)):
        m = _meta(x)
        m["not_same"] = list(dict.fromkeys([*(m.get("not_same") or []), str(y["id"])]))[-50:]
        _save(b, str(x["id"]), {"metadata": m})
    _forget(b)
    return {"ok": True}


@router.post("/tidy/numbers-guests")
def tidy_numbers_guests(business_id: str = Query(...),
                        biz: Dict[str, Any] = Depends(business_access(cr.MIN_ROLE)),
                        session: UserSession = Depends(sb_clients.authed_request)):
    """Every number with no name that is filed as a member becomes a guest."""
    b, _, _ = _gate(biz, session)
    filed = 0
    for p in _tidy_ctx(biz)["people"]:
        if p.get("noname") and p["status"] in ("member", "leader"):
            saved = sb_clients.sb_patch_as_service(f"/contacts?id=eq.{_q(p['id'])}&business_id=eq.{_q(b)}", {"status": "lead"})
            if isinstance(saved, list) and saved:
                filed += 1
                _event(b, p["id"], "contact_status_changed", {"from": "active", "to": "lead", "why": "no name yet"})
    _forget(b)
    return {"filed": filed}


@router.post("/tidy/confirm")
def tidy_confirm(body: Dict[str, Any] = Body(...), business_id: str = Query(...),
                 biz: Dict[str, Any] = Depends(business_access(cr.MIN_ROLE)),
                 session: UserSession = Depends(sb_clients.authed_request)):
    """Keep someone as a member (the office says so), or make them a guest."""
    b, user, _ = _gate(biz, session)
    c = _contact(b, cr._uuid(body.get("id")))
    apply_edit(b, c, {"status": "member" if body.get("keep") else "guest"}, user)
    _forget(b)
    return {"ok": True}
