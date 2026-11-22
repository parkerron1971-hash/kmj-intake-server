"""church_sheet.py — one sheet per person: everything a login can see and do,
in one place (step one of the artifact "One sheet per person",
WE3jy89EXadQSjz9t8A2FV).

Kevin, 2026-11-17: "my wife suggested that we create a check list that would
work like they can uncheck and check certain things on the person they setup
and chief could see those checks and know the level of permission they have",
then "yes to all and build it".

Step one changes no rule. A login was described in six places (its level, its
areas, its lane, its duties, the keys, its job description); the sheet reads
them together and sets the first four through the writes they already had:

    its level ....... business_users.role: Viewer, Member, Manager or Admin
                      (church_areas.set_login, in the same row write as the
                      areas and the job; the sheet sets it since 2026-11-18,
                      before that only the invite did)
    its job ......... business_users.lane: one of the five starting jobs or
                      one of the church's own (church_job_defs). A label and a
                      starting point; it never changes anyone by itself
    its areas ....... business_users.areas (church_areas.set_login, the
                      Logins & areas write)
    its duties ...... church_duties.move, one duty at a time, logged there
    what's guarded .. read only here: who gave what and the bank, kids'
                      medical notes, pastors-only notes, inviting logins; who
                      holds each today and why (church_keys keeps the locks)
    its description . read only here (church_job_descriptions writes it)
    what Chief knows  plain sentences from the same scope Chief keeps to
                      (chief_areas): what it does for this login and what it
                      sends elsewhere

Who:
  read ...... the owner or an Admin, anyone's; whoever "sets up jobs and
              people's sheets" (church_job_defs.GRANT), a Manager login's or
              below; anyone, their own
  change .... the owner (anyone's but their own), an Admin or a holder (a
              Manager login's or below, never their own). A holder never
              switches on Giving & money or a money duty, never moves the
              lanes' oversight, and never gives or takes the grant; what a
              holder changes is told to the owner
  the grant . given and taken away by the owner or an Admin, to a Manager
              login, as a tick on the sheet's duties

  GET    /church/sheet?business_id=&user_id=
  PUT    /church/sheet        {business_id, user_id, level?, job?, areas?, duties?: {add, remove},
                               money?: {level: null|see|work|lead, who_gave, bank}}
                              (`money`: giving as its own tick, church_money_ticks; the owner's
                              change is saved, an Admin's or a holder's is sent to the owner as a
                              request and opens nothing)
  GET    /church/sheet/jobs?business_id=      the jobs, always (see below)
  POST   /church/jobs         {business_id, label, does, description, role, areas, duties}
  PUT    /church/jobs/{key}   the same body (one of the church's own)
  DELETE /church/jobs/{key}?business_id=

GET /church/jobs is the job descriptions' roster (church_job_descriptions);
it carries `jobs` too, but only where that page opens, so /church/sheet/jobs
is the read that always answers. A change that leaves a login with more (an
area it is shown, a duty it holds, however the change was asked) asks for the
password again, as an invite does; one that leaves it with less never does:
change() works out what the login has before and after. Switched with Logins & areas (CHURCH_AREAS). A read that fails is
a 503, never an empty sheet.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request

import church_areas
import church_duties as cd
import church_job_defs as cj
import church_over as co
import sb_clients
from auth_supabase import UserSession
from business_access import assert_access, business_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/church", tags=["church"])

LOW = ("manager", "member", "viewer")
NOT_CHURCH = "A person's sheet is for a church's office."
NOT_YOURS = ("A person's sheet is read by the owner, an Admin, or whoever sets up jobs and people's sheets. "
             "You can read your own.")
OWN_SHEET = "Nobody changes their own sheet. The owner or an Admin changes yours."
ADMINS_SHEET = "Only the owner changes an Admin's sheet."
OWNERS_SHEET = "The owner's sheet doesn't change: the owner sees and does everything."
NOT_AN_EDITOR = ("Only the owner, an Admin, or whoever sets up jobs and people's sheets changes a sheet. "
                 "Ask the owner to give you that.")
GIVING_LOCKED = "Giving & money opens only for an Admin login. Only the owner or an Admin can switch it on."
MONEY_DUTY = "A money job goes only to an Admin login. Only the owner or an Admin gives one."
GRANT_LOCKED = f"Only the owner or an Admin can give or take away “{cj.GRANT_LABEL}”."
OVERSIGHT_LOCKED = "Only the owner or an Admin moves the monthly report and Over the lanes."
BACK_TO_GUESS = "Only the owner or an Admin can send a login back to Chief's guess: it can open the whole church."
ADMIN_JOB = "That job is an Admin login. Only the owner makes someone an Admin."
KEEPS_ALL_WHY = "An Admin login sees the whole church and does every duty."
NO_OFFICE_JOBS = "A Member or Viewer login doesn't do office jobs. Make them a Manager login first."

# A login's level, lowest first (business_users.role). The sheet sets it
# since 2026-11-18 (Kevin, on whether the sheet should change a login's
# level: "everything else, I agree"); until then only the invite did.
LEVELS: Tuple[str, ...] = ("viewer", "member", "manager", "admin")
LEVEL_RANK = {k: n for n, k in enumerate(LEVELS, 1)}
LEVEL_LABEL = {"viewer": "Viewer", "member": "Member", "manager": "Manager", "admin": "Admin"}
LEVEL_MEANS = {
    "viewer": "Reads, and changes nothing.",
    "member": "Works its own records in its areas.",
    "manager": "Works any record in its areas, and can do office duties.",
    "admin": "Sees the whole church, giving and settings included.",
}
ADMIN_LEVEL = "Only the owner makes someone an Admin."
ADMIN_JOB_NEEDS_LEVEL = "That job is an Admin login. Set their level to Admin with it."
HOLDERS_LEVEL = ("{name} sets up jobs and people's sheets. Only the owner or an Admin lowers their level, "
                 "because that takes it away.")
PICK_AREAS = ("Pick the areas {name} works in before moving them down from Admin. A login with no areas "
              "sees the whole church.")
NOT_A_LEVEL = "Pick one of the login levels: Viewer, Member, Manager or Admin."

# What Chief does for a login that works an area, and the same thing as what
# it sends elsewhere for a login that doesn't. Each names a verb placed in
# that area in chief_areas.VERBS (a test holds them together).
EXAMPLES: Tuple[Tuple[str, str, str], ...] = (
    ("worship_media", "publish_sermon", "Put Sunday's sermon up"),
    ("people_care", "create_contact", "Add a guest and follow up with them"),
    ("giving_money", "giving_statement", "Read what was given, or make a giving statement"),
    ("groups_classes", "create_course", "Start a class"),
    ("website_outreach", "edit_site_text", "Change the website"),
    ("office", "ask_into_role", "Ask someone into a role"),
)
EVERYONES = ("Add a task, a note or a meeting", "Draft an email or a text to someone")


def _q(v: Any) -> str:
    return church_areas._q(v)


def _uuid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v or "")))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} isn't valid")


def _join(words: List[str]) -> str:
    words = [w for w in words if w]
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _label(area: str) -> str:
    return church_areas.AREAS[area]["label"]


def _business(biz: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz)}&select=id,name,type,owner_id,settings&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "The church couldn't be read just now. Try again.")
    if not rows:
        raise HTTPException(404, "business not found")
    import church_follow_up as cfu
    if not cfu.is_church(rows[0]):
        raise HTTPException(404, NOT_CHURCH)
    return rows[0]


# ─── Who may ──────────────────────────────────────────────────────────

def standing(ch: co.Church, viewer: str, target: str) -> Dict[str, Any]:
    """What `viewer` is to `target`'s sheet: {viewer_role, target_role,
    editor, is_self, can_read, can_edit, why_not}. 403 for someone with no
    login here; 404 for a sheet of someone who has none."""
    vrole, trole = ch.role(viewer), ch.role(target)
    if not vrole:
        raise HTTPException(403, NOT_YOURS)
    if not trole:
        raise HTTPException(404, "That login isn't on this church.")
    ed = cj.editor(ch.b, viewer, vrole)
    is_self = viewer == target
    can_read = is_self or ed in ("owner", "admin") or (ed == "holder" and trole in LOW)
    why = None
    if is_self:
        why = OWNERS_SHEET if vrole == "owner" else OWN_SHEET
    elif not ed:
        why = NOT_AN_EDITOR
    elif trole == "owner":
        why = OWNERS_SHEET
    elif trole == "admin" and ed != "owner":
        why = ADMINS_SHEET
    return {"viewer_role": vrole, "target_role": trole, "editor": ed, "is_self": is_self, "can_read": can_read,
            "can_edit": why is None, "why_not": why}


def locks(st: Dict[str, Any]) -> Dict[str, Any]:
    """What this editor may not toggle on this sheet: {locked_areas,
    locked_duties, locked_why, limits}. `limits` are the sentences a holder
    reads; the owner and the Admins read none."""
    trole, ed = st["target_role"], st["editor"]
    why: Dict[str, str] = {}
    money = [k for k, d in cd.CATALOG.items() if d["money"]]
    if not st["can_edit"]:
        said = st["why_not"] or NOT_AN_EDITOR
        why = {k: said for k in list(church_areas.AREA_ORDER) + list(cd.CATALOG) + [cj.GRANT]}
    elif trole in church_areas.KEEPS_ALL:
        why = {k: KEEPS_ALL_WHY for k in list(church_areas.AREA_ORDER) + list(cd.CATALOG) + [cj.GRANT]}
    else:
        why[church_areas.FINANCE_ONLY] = GIVING_LOCKED
        if trole != "manager":
            why.update({k: NO_OFFICE_JOBS for k in list(cd.CATALOG) + [cj.GRANT]})
        else:
            why.update({k: MONEY_DUTY for k in money})
            if ed == "holder":
                why.update({k: OVERSIGHT_LOCKED for k in cd.OVERSIGHT})
                why[cj.GRANT] = GRANT_LOCKED
    limits: List[str] = []
    if ed == "holder" and st["can_edit"]:
        limits = [GIVING_LOCKED, GRANT_LOCKED, OVERSIGHT_LOCKED,
                  "Only the owner makes someone an Admin or gives them an Admin job.",
                  "You can't change your own sheet, an Admin's or the owner's."]
    return {"locked_areas": [a for a in church_areas.AREA_ORDER if a in why],
            "locked_duties": [k for k in list(cd.CATALOG) + [cj.GRANT] if k in why],
            "locked_why": why, "limits": limits}


def _level_refusal(st: Dict[str, Any], level: str) -> Optional[str]:
    """Why this editor can't set this level on this person, in one sentence;
    None when they can. standing() has already said whose sheet this editor
    changes at all (never their own, never the owner's, an Admin's only for
    the owner), so what is left is the one level that is the owner's to give."""
    if level == "admin" and st["editor"] != "owner":
        return ADMIN_LEVEL
    return None


def level_options(st: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The four levels in order, each with whether this editor may set it on
    this person and, when not, why. Empty for a sheet that is read only and
    for the owner, who has no level."""
    if not st["can_edit"] or st["target_role"] not in LEVELS:
        return []
    out = []
    for k in LEVELS:
        why = _level_refusal(st, k)
        out.append({"key": k, "label": LEVEL_LABEL[k], "means": LEVEL_MEANS[k], "allowed": why is None,
                    "why": why or "", "current": k == st["target_role"]})
    return out


# ─── Reading one sheet ────────────────────────────────────────────────

def _person(ch: co.Church, st: Dict[str, Any], target: str) -> Dict[str, Any]:
    seat = ch.seats.get(target) or {}
    owner = target == ch.owner
    email = ""
    if owner:
        try:
            email = ch.owner_email
        except HTTPException:
            email = ""
    else:
        email = (seat.get("invited_email") or "").strip()
    return {"user_id": target, "name": ch.login_name(target), "email": email, "role": st["target_role"],
            "status": "active", "is_owner": owner, "is_self": st["is_self"]}


def _job(ch: co.Church, target: str, picked: Optional[List[str]]) -> Dict[str, Any]:
    seat = ch.seats.get(target) or {}
    key = seat.get("lane") or None
    if key:
        label = cj.label_of(ch.b, key)
        if label:
            return {"key": key, "label": label, "custom": key not in church_areas.LANES}
    key = church_areas.lane_of(seat.get("role"), picked, ch.b)
    return {"key": key, "label": church_areas.LANES[key]["label"] if key else None, "custom": False}


def _areas(business: Dict[str, Any], ch: co.Church, target: str) -> Dict[str, Any]:
    if ch.role(target) in church_areas.KEEPS_ALL:
        return {"picked": None, "shown": None, "by": "all", "why": "Sees the whole church", "guess": []}
    seat = ch.seats.get(target) or {}
    raw = seat.get("areas")
    picked = [a for a in church_areas.AREA_ORDER if a in raw] if isinstance(raw, list) else None
    row = next((x for x in church_areas.build(business)["logins"] if x["user_id"] == target), None)
    if not row:
        raise HTTPException(503, "Their areas couldn't be read just now. Try again.")
    return {"picked": picked or None, "shown": row["areas"], "by": row["by"], "why": row["why"],
            "guess": row["guess"]}


def _duties(business: Dict[str, Any], ch: co.Church, target: str, names: bool = True) -> List[Dict[str, Any]]:
    """The whole catalog as this person's ticks, then the grant as one more.
    `names` false leaves out who else does each (a Member or Viewer login
    reading its own sheet: the duties page is a Manager's and up)."""
    page = cd.build(business)
    held = ch.held(target)
    out = []
    for d in page["duties"]:
        out.append({"key": d["key"], "label": d["label"], "area": d["area"], "held": d["key"] in held,
                    "others": [h["name"] for h in d["holders"]
                               if names and h["user_id"] != target and h.get("active")],
                    "money": bool(d["money"]), "follows_job": bool(d["follows_lanes"]), "does": d["does"]})
    holders = cj.grant_holders(ch.b)
    if holders is None:
        raise HTTPException(503, "Who sets up jobs couldn't be read just now. Try again.")
    trole = ch.role(target)
    managers = sorted(u for u in holders if ch.role(u) == "manager")
    out.append({"key": cj.GRANT, "label": cj.GRANT_LABEL, "area": "office",
                "held": trole in church_areas.KEEPS_ALL or target in managers,
                "others": [ch.login_name(u) for u in managers if names and u != target],
                "money": False, "follows_job": False, "does": cj.GRANT_DOES, "grant": True})
    return out


def _guarded(ch: co.Church, target: str, shown: Optional[List[str]]) -> List[Dict[str, Any]]:
    """What is guarded, whether this person holds it today, and why, in one
    sentence each. Read only: church_keys keeps the locks, and money opens to
    the owner, an Admin and the accountant (giving_records.require_finance)."""
    import church_keys
    trole = ch.role(target)
    first = ch.login_name(target).split(" ")[0] or "They"
    full = trole in church_areas.KEEPS_ALL
    try:
        rows = church_keys._keeper_rows(ch.b) if church_keys.mode() != "off" else []
    except HTTPException:
        rows = None

    def one(key: str, label: str, area: str, base: bool, open_to: str) -> Dict[str, Any]:
        if rows is None:
            return {"key": key, "label": label, "area": area, "holds": False,
                    "how": "Who keeps this couldn't be read just now."}
        keepers = church_keys.active_keepers(ch.b, area, rows) if area in church_keys.GUARDED else set()
        if keepers:
            names = _join(sorted(ch.login_name(u) for u in keepers))
            if target in keepers:
                return {"key": key, "label": label, "area": area, "holds": True,
                        "how": f"{first} keeps {_label(area)}, so it is open to them."}
            return {"key": key, "label": label, "area": area, "holds": False,
                    "how": f"{names} keeps {_label(area)}. {first} asks for a key, and a yes opens it for an hour."}
        return {"key": key, "label": label, "area": area, "holds": base,
                "how": f"Nobody keeps {_label(area)} yet, so it has no lock of its own: it is open to {open_to}."}

    def works(a: str) -> bool:
        return full or shown is None or a in shown

    money = "the owner, an Admin login and the church's accountant"
    gave, bank = full, full
    try:
        # Giving as its own tick (church_money_ticks): while it is on for this
        # church the owner also gives these two on the sheet, so the sentence
        # says so and a holder's ticks count. A read that fails says what the
        # seat alone gives, as with the switch off.
        import church_money_ticks as cmt
        if cmt.open_for(ch.b):
            money = ("the owner, an Admin login, the church's accountant and whoever the owner gives it to "
                     "under Giving on their sheet")
            held = cmt.holder(ch.b, target) or {}
            gave = full or held.get("who_gave") is True
            bank = full or held.get("bank") is True
    except Exception:  # noqa: BLE001 — wording only; the gate decides access
        pass
    return [
        one("who_gave", "Who gave, and how much", "giving_money", gave, money),
        one("bank", "The bank and payouts", "giving_money", bank, money),
        one("kids_medical", "Kids' medical and custody notes", "kids_youth", works("kids_youth"),
            "whoever can open Kids & youth"),
        one("pastors_notes", "Pastors-only notes and prayer", "people_care", works("people_care"),
            "whoever can open People & care"),
        {"key": "logins", "label": "Inviting and removing logins", "area": "office",
         "holds": trole in ("owner", "admin", "manager"),
         "how": ("A Manager login and up invites a login and removes one below its own level. Only the owner or "
                 "an Admin invites an Admin.")},
    ]


def _description(ch: co.Church, viewer: str, target: str) -> Dict[str, Any]:
    """Their written job description, where the viewer may read it. Read
    only here; a part that can't be read is left blank, never a failed sheet."""
    blank = {"title": None, "text": None, "written": False, "can_write": False}
    try:
        import church_job_descriptions as cjd
        if cjd.ready() is not True:
            return blank
        J = cjd.Jobs(ch)
        e = cjd.person(J, None, target)
        under = cjd.under_keys(ch, co.who(co.LOGIN, viewer))
        title, _written = cjd.title_of(ch, e)
        row = e["row"] if cjd.can_read(ch, viewer, e, under) else None
        return {"title": title or None, "text": (row or {}).get("description") or None, "written": bool(e["row"]),
                "can_write": cjd.can_write(ch, viewer, e, under)}
    except HTTPException:
        return blank
    except Exception:  # noqa: BLE001 — the sheet never fails for the description
        logger.warning("church sheet: a job description wasn't read (business %s)", ch.b[:8], exc_info=True)
        return blank


def chief_words(ch: co.Church, target: str, shown: Optional[List[str]], job: Dict[str, Any],
                duties: List[Dict[str, Any]], guarded: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """What Chief knows about this login, in plain sentences, from the same
    scope Chief keeps to (chief_areas.refusal reads a login's areas): what it
    does for them and what it sends to someone else."""
    import chief_areas
    name = ch.login_name(target)
    first = name.split(" ")[0] or name
    trole = ch.role(target)
    full = trole in church_areas.KEEPS_ALL or shown is None or chief_areas.mode() == "off"
    areas = list(church_areas.AREA_ORDER) if full else list(shown or [])
    summary: List[str] = []
    if trole == "owner":
        summary.append(f"{name} is the owner. Chief does everything for the owner.")
    elif trole == "admin":
        summary.append(f"{name} has an Admin login. Chief works across the whole church for them, money too.")
    elif full:
        summary.append(f"Nothing places {name} yet, so Chief keeps to no area for them. Give them their areas.")
    elif areas:
        summary.append(f"{name} works in {_join([_label(a) for a in areas])}.")
    else:
        summary.append(f"{name} has no area switched on. Chief helps with their own tasks, notes and meetings.")
    if job.get("label"):
        summary.append(f"Their job is {job['label']}.")
    mine = [d["label"] for d in duties if d["held"] and not d.get("grant")]
    if trole not in church_areas.KEEPS_ALL and mine:
        shown_d = mine[:4]
        more = len(mine) - len(shown_d)
        summary.append(f"{first} does {_join(shown_d)}" + (f" and {more} more duties." if more > 0 else "."))
    if trole not in church_areas.KEEPS_ALL and any(d.get("grant") and d["held"] for d in duties):
        summary.append(f"{first} sets up the church's jobs and people's sheets: never an Admin job, Giving & "
                       "money or their own sheet.")
    held = [g["label"] for g in guarded if g["holds"] and g["key"] != "logins"]
    summary.append(f"Guarded things open to {first}: {_join(held).lower()}." if held
                   else f"Nothing guarded is open to {first}.")
    money_ok = trole in church_areas.KEEPS_ALL
    will = list(EVERYONES)
    wont: List[str] = []
    for area, verb, words in EXAMPLES:
        needs = chief_areas.VERBS.get(verb) or ()
        ok = money_ok if area == "giving_money" else (full or any(a in areas for a in needs))
        if ok:
            will.append(words)
        elif area == "giving_money":
            wont.append(f"{words}: Giving & money opens only to the owner, an Admin and the accountant.")
        else:
            wont.append(f"{words}: that is {_label(area)}. Chief says who has it.")
    return {"summary": summary, "will": will, "wont": wont}


def compose(business: Dict[str, Any], viewer: str, target: str) -> Dict[str, Any]:
    """One person's sheet for one viewer. 403 when it isn't theirs to read."""
    import church_map
    ch = co.Church(business)
    st = standing(ch, viewer, target)
    if not st["can_read"]:
        raise HTTPException(403, NOT_YOURS)
    with church_map.once():
        areas = _areas(business, ch, target)
        duties = _duties(business, ch, target, names=st["viewer_role"] in ("owner", "admin", "manager"))
        job = _job(ch, target, areas["picked"])
        guarded = _guarded(ch, target, areas["shown"])
        return {
            "ok": True, "can_edit": st["can_edit"], "editor": st["editor"],
            "person": _person(ch, st, target), "job": job, "areas": areas, "duties": duties, "guarded": guarded,
            "description": _description(ch, viewer, target),
            "chief": chief_words(ch, target, areas["shown"], job, duties, guarded),
            # The jobs (their descriptions too) are the office's: a Manager and up.
            "jobs": cj.jobs(ch.b) if st["viewer_role"] in ("owner", "admin", "manager") else [], **locks(st),
            "level_options": level_options(st),
            # Giving as its own tick (church_money_ticks): None while it is
            # switched off for this church, and the app shows nothing new.
            "money": _money_block(business, ch, st, target),
        }


def _money_block(business: Dict[str, Any], ch: co.Church, st: Dict[str, Any], target: str) -> Optional[Dict[str, Any]]:
    import church_money_ticks
    return church_money_ticks.block(business, ch, st, target)


# ─── Changing one sheet ───────────────────────────────────────────────

def _duty_plan(ch: co.Church, business: Dict[str, Any], target: str, add: List[str], remove: List[str]
               ) -> List[Tuple[str, List[str]]]:
    """Who does each changed duty afterwards, as church_duties.move takes it:
    everyone who does it now, with this person added or taken out. A duty
    this person does by their job alone can't be taken from them here (naming
    nobody hands it back to the job): the Duties tab names who does it."""
    page = {d["key"]: d for d in cd.build(business)["duties"]}
    plan: List[Tuple[str, List[str]]] = []
    for key in add:
        d = page[key]
        now = [h["user_id"] for h in d["holders"] if h.get("active")]
        if target not in now:
            plan.append((key, sorted(set(now) | {target})))
    for key in remove:
        d = page[key]
        now = [h["user_id"] for h in d["holders"] if h.get("active")]
        if target not in now:
            continue
        rest = sorted(set(now) - {target})
        if not rest:
            raise HTTPException(400, f"{ch.login_name(target)} is the only one who does “{d['label']}”. Say who "
                                     "does it instead on the Duties tab, then take it off this sheet.")
        plan.append((key, rest))
    return plan


def _shown(picked: Optional[List[str]], guess: List[str]) -> Optional[List[str]]:
    """What a login is shown with these picked areas, as
    church_areas.login_view decides it: the pick; with none, Chief's guess;
    with neither, the whole church (None)."""
    if isinstance(picked, list) and picked:
        return [a for a in church_areas.AREA_ORDER if a in picked]
    if guess:
        return [a for a in church_areas.AREA_ORDER if a in guess]
    return None


def _exec_person(ch: co.Church, target: str) -> bool:
    """Whether this login's person holds a role that oversees the office
    (church_duties.overseer_keys) and said yes, whatever the login's level
    is today: church_duties._exec_users' answer for this one seat, the rule
    holds() itself reads. A login moved up to Manager is seen with the
    Executive Pastor's lane it would then have."""
    seat = ch.seats.get(target)
    return bool(seat) and target in cd._exec_users(ch.b, [seat])


def _held(ch: co.Church, target: str, role: Optional[str], lane: Any, picked: Optional[List[str]],
          shown: Optional[List[str]], moved: Dict[str, List[str]], is_exec: bool = False) -> frozenset:
    """The duties a login holds with this level, this job, these areas and
    these moves: church_duties.standing's rule, worked out for a login as it
    is or as a change would leave it. The owner and the Admins hold every
    duty; a Manager its lane's (the stored one, else the lane its picked
    areas are exactly, and the Executive Pastor's where their person holds
    that role: `is_exec`), or with no lane the duties in the areas it is
    shown, until a duty moves; never money. A Member or a Viewer holds none."""
    if role in church_areas.KEEPS_ALL:
        return cd.ALL
    if role != "manager":
        return frozenset()
    lanes = set()
    ln = cd._seat_lane({"role": role, "lane": lane, "areas": picked})
    if ln:
        lanes.add(ln)
    if is_exec:
        lanes.add(cd.EXEC)
    by_area = None
    if not lanes and cd.own_job_seat({"lane": lane}):
        by_area = frozenset()           # one of the church's own jobs: only the duties given on the sheet
    elif not lanes:
        every = frozenset(k for k, d in cd.CATALOG.items() if not d["money"] and k not in cd.OVERSIGHT)
        by_area = every if (shown is None or church_areas.mode() != "on") else frozenset(
            k for k in every if cd.CATALOG[k]["area"] in shown)
    return cd._manager_duties(lanes, target, moved, by_area)


def _str_list(v: Any, what: str) -> List[str]:
    """A list of plain words from a request, or a 400."""
    if v is None:
        return []
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise HTTPException(400, f"Send {what} as a list of names.")
    return list(v)


def effect(business: Dict[str, Any], ch: co.Church, target: str, *, level: Any = church_areas.KEEP,
           areas: Any = church_areas.KEEP, job: Any = church_areas.KEEP,
           moves: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """What one write would leave a login with, beside what it has now,
    without writing anything: its level, its job, the areas it is shown and
    the duties it holds, before and after, and what grew and what shrank.

    This is the one place "does this give them more?" is answered, for a
    person's sheet and for the two older writes that change the same things
    (the Logins & areas route's areas, and through church_duties.gives_more
    the Duties tab's moves). It judges by RESULT, never by how the change
    was asked: taking an area off can re-spell a lane and bring that lane's
    duties; sending a login back to Chief's guess can open the whole church;
    a higher level brings what that level holds.

    `level` a new level, `areas` a clean list or None (back to the guess),
    `job` a job's key or None; each left out is kept as it is. `moves` are
    duty -> the logins who do it afterwards."""
    keep = church_areas.KEEP
    seat = ch.seats.get(target) or {}
    role_now = ch.role(target)
    role_then = role_now if level is keep else level
    stored_areas = seat.get("areas")
    picked_now = ([a for a in church_areas.AREA_ORDER if a in stored_areas] or None) if isinstance(
        stored_areas, list) else None
    lane_now = seat.get("lane") or None
    now = _areas(business, ch, target)
    shown_now, guess = now["shown"], now["guess"]
    picked_then = picked_now if areas is keep else areas
    lane_then = lane_now
    if job is not keep or areas is not keep:
        lane_then = church_areas.lane_after(role_then, lane_now, stored_areas, areas=areas, job=job,
                                            own=church_areas.own_job(ch.b, lane_now), business_id=ch.b)
    shown_then = None if role_then in church_areas.KEEPS_ALL else _shown(picked_then, guess)
    moved_then = dict(ch.moved)
    for key, to in (moves or {}).items():
        if to:
            moved_then[key] = list(to)
        else:
            moved_then.pop(key, None)
    is_exec = _exec_person(ch, target) if "manager" in (role_now, role_then) else False
    held_now = _held(ch, target, role_now, lane_now, picked_now, shown_now, ch.moved, is_exec)
    held_then = _held(ch, target, role_then, lane_then, picked_then, shown_then, moved_then, is_exec)
    # "The whole church" for a login an area can be picked for never opens
    # Giving; an Admin login's whole church does.
    every_area = set(church_areas.AREA_ORDER) - {church_areas.FINANCE_ONLY}

    def area_set(role: Optional[str], shown: Optional[List[str]]) -> Set[str]:
        if role in church_areas.KEEPS_ALL:
            return set(church_areas.AREA_ORDER)
        return every_area if shown is None else set(shown)
    areas_now, areas_then = area_set(role_now, shown_now), area_set(role_then, shown_then)
    rank_now, rank_then = LEVEL_RANK.get(role_now or "", 0), LEVEL_RANK.get(role_then or "", 0)
    return {
        "role_now": role_now, "role_then": role_then, "level_up": rank_then > rank_now,
        "level_down": rank_then < rank_now, "stored_areas": stored_areas,
        "picked_now": picked_now, "picked_then": picked_then, "lane_now": lane_now, "lane_then": lane_then,
        "shown_now": shown_now, "shown_then": shown_then,
        "more_areas": [a for a in church_areas.AREA_ORDER if a in areas_then - areas_now],
        "less_areas": [a for a in church_areas.AREA_ORDER if a in areas_now - areas_then],
        "more_duties": [k for k in cd.CATALOG if k in held_then - held_now],
        "less_duties": [k for k in cd.CATALOG if k in held_now - held_then],
    }


def _plainly_less(business_id: str, seat: Dict[str, Any], areas: Any) -> bool:
    """Whether picking these areas for this login is plainly taking some
    away, from the login's own row alone: it has picked areas now, every
    area sent is one of them, and the lane its duties follow
    (church_duties._seat_lane) is the same before and after. Then it is
    shown no area it wasn't (a pick is what a login is shown) and holds no
    duty it didn't (the same lane's, or with no lane the duties in fewer
    areas), so nothing else needs reading. Anything else is not plain, and
    the full reckoning (effect) answers."""
    stored = seat.get("areas")
    if not isinstance(areas, list) or not areas or not isinstance(stored, list) or not stored:
        return False
    if not set(areas) <= set(stored):
        return False
    role, lane = seat.get("role"), seat.get("lane")
    after = church_areas.lane_after(role, lane, stored, areas=areas, own=church_areas.own_job(business_id, lane))
    return cd._seat_lane({"role": role, "lane": lane, "areas": stored}) == cd._seat_lane(
        {"role": role, "lane": after, "areas": areas})


def areas_write_widens(business_id: str, target: str, *, areas: Any, job: Any = church_areas.KEEP,
                       seat: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the Logins & areas write (church_areas.place_login) would leave
    this login with more than it has: an area it is shown or a duty it holds.
    The same answer a person's sheet gives for the same change. False for a
    business that isn't a church (it has no areas to give); a read that fails
    is a 503, never a "no". With the login's row (`seat`: role, areas, lane)
    and no job named, areas that are plainly a subset of the ones picked are
    answered from the row alone (_plainly_less), without the whole map."""
    if seat is not None and job is church_areas.KEEP and _plainly_less(business_id, seat, areas):
        return False
    import church_follow_up as cfu
    import church_map
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{_q(business_id)}&select=id,name,type,owner_id,settings&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "The church couldn't be read just now. Try again.")
    if not rows or not cfu.is_church(rows[0]):
        return False
    ch = co.Church(rows[0])
    with church_map.once():
        e = effect(rows[0], ch, target, areas=areas, job=job)
    return bool(e["more_areas"] or e["more_duties"])


def change(business: Dict[str, Any], viewer: str, target: str, body: Dict[str, Any], *,
           widening=None) -> Dict[str, Any]:
    """Change a person's sheet: its level, its job, its areas, its duties,
    each through the write it already had. Everything that can refuse is
    checked before anything is written, and the writes go in an order that
    can only ever leave the login with less if one of them fails: the grant
    taken away first, then the level, the areas and the job in ONE row
    write (church_areas.set_login), then the duties, then a grant given.

    Whether a change gives the login more is judged by its RESULT, never by
    how it was asked (effect()): what the login is shown and the duties it
    holds now are worked out, then what they would be after the write, and
    anything that grew, a higher level too, is "more". `widening` (the
    route's password check, which raises) is called once before any write
    when anything grew; a change that leaves the login with less asks for
    nothing. A holder's ceiling is applied to the result too: nothing it
    leaves the login with may be one of the things only the owner or an
    Admin gives.

    The level: the owner sets any; an Admin or a holder sets Viewer, Member
    or Manager on a Manager login or below, never Admin. A login that
    becomes an Admin sees the whole church and does every duty, so areas and
    duties sent with it are left as they are stored (there again if it is
    ever moved back). A login moved down from Admin must be left with areas
    (sent, or already stored): one with none would see the whole church; a
    job that is an Admin login's (the Treasurer's) comes off it. A login
    that stops being a Manager no longer sets up jobs and sheets: that
    grant goes in the same save, before the level. And it never comes back
    with the level: any move to Manager clears a grant row left on the
    login, unless the owner or an Admin gives the grant in that same save.
    Returns {widens, summary, changed, owner_told}."""
    body = body if isinstance(body, dict) else {}
    keep = church_areas.KEEP
    ch = co.Church(business)
    st = standing(ch, viewer, target)
    if not st["can_edit"]:
        raise HTTPException(403, st["why_not"] or NOT_AN_EDITOR)
    trole, ed = st["target_role"], st["editor"]
    name = ch.login_name(target)
    said: List[str] = []

    # ── What was asked: each part's shape, and who may ──
    # The level.
    level_set = "level" in body and body.get("level") is not None
    level = trole
    if level_set:
        level = body.get("level")
        if not isinstance(level, str) or level not in LEVELS:
            raise HTTPException(400, NOT_A_LEVEL)
        why = _level_refusal(st, level)
        if why:
            raise HTTPException(403, why)
    level_changes = level != trole
    becomes_admin = level == "admin" and trole != "admin"
    # The rules for the rest are the ones for the level the login will have.
    st_then = {**st, "target_role": level}
    lk = locks(st_then)

    # The job.
    job_set = "job" in body
    job_key = None
    job_label = None
    if job_set and body.get("job") is not None:
        job = cj.find(ch.b, body.get("job")) if isinstance(body.get("job"), str) else None
        if not job:
            raise HTTPException(400, "That isn't one of this church's jobs.")
        if job["role"] == "admin" and level != "admin":
            if ed != "owner":
                raise HTTPException(403, ADMIN_JOB)
            raise HTTPException(400, ADMIN_JOB_NEEDS_LEVEL)
        job_key, job_label = job["key"], job["label"]

    # The areas. Sent with a level that makes an Admin, they are left as stored.
    areas_set = "areas" in body and not becomes_admin
    areas = None
    if areas_set:
        if level in church_areas.KEEPS_ALL:
            raise HTTPException(400, KEEPS_ALL_WHY)
        raw = body.get("areas")
        if raw is None and ed == "holder":
            raise HTTPException(403, BACK_TO_GUESS)
        if isinstance(raw, list) and church_areas.FINANCE_ONLY in raw:
            raise HTTPException(403 if ed == "holder" else 400, GIVING_LOCKED)
        areas = church_areas.clean_login_areas(raw)

    # The duties, and the grant among them.
    duties = body.get("duties")
    if duties is None:
        duties = {}
    if not isinstance(duties, dict):
        raise HTTPException(400, "Send the duties to give and to take away as two lists.")
    add = _str_list(duties.get("add"), "the duties to give")
    remove = _str_list(duties.get("remove"), "the duties to take away")
    known = set(cd.CATALOG) | {cj.GRANT}
    if any(k not in known for k in add + remove) or set(add) & set(remove):
        raise HTTPException(400, "One of those isn't a duty here.")
    if becomes_admin:
        add, remove = [], []            # an Admin does every duty: nothing to give or take
    elif level_changes and level != "manager":
        remove = []                     # below Manager a login holds none: nothing left to take off
    grant = True if cj.GRANT in add else False if cj.GRANT in remove else None
    add, remove = [k for k in add if k != cj.GRANT], [k for k in remove if k != cj.GRANT]
    for k in add + remove + ([cj.GRANT] if grant is not None else []):
        if k in lk["locked_duties"]:
            raise HTTPException(403 if ed == "holder" else 400, lk["locked_why"][k])
    plan = _duty_plan(ch, business, target, add, remove) if add or remove else []
    for key, to in plan:
        # Everything church_duties.move would refuse is asked here, before
        # the first write: the level is saved before the duties move, and a
        # move that then said no would leave the level changed alone.
        if len(to) > cd.MAX_HOLDERS:
            raise HTTPException(400, f"“{cd.CATALOG[key]['label']}” already names {cd.MAX_HOLDERS} logins, the "
                                     "most a duty takes. Take one off it on the Duties tab first.")
        for u in to:
            cd._uuid(u, "login")
        # The target is checked at the level this save leaves it with (a
        # Member made a Manager here can be given a duty in the same save).
        why = cd._check(ch.b, business, [u for u in to if u != target], key)
        if not why and target in to:
            why = cd._why_not(business, {target: {"role": level}}, target, key)
        if why:
            raise HTTPException(400, why)
    # The grant is a row naming the login; it counts only while the login
    # is a Manager. So a row can outlast the grant (a login moved down, a
    # save that failed half way), and must never bring it back.
    holders = None
    if grant is not None or (level_changes and "manager" in (trole, level)):
        holders = cj.grant_holders(ch.b)
        if holders is None:              # unread before anything is written, never after
            raise HTTPException(503, "Who sets up jobs couldn't be read just now. Nothing changed. Try again.")
    has_row = bool(holders) and target in holders
    held_grant = has_row and trole == "manager"
    if grant is not None:
        if ed not in ("owner", "admin"):
            raise HTTPException(403, GRANT_LOCKED)
        if level != "manager":
            raise HTTPException(400, "Give that to a Manager login. An Admin sets up jobs and sheets already, and "
                                     "a Member or Viewer login doesn't.")
    # A login that stops being a Manager stops setting up jobs and sheets.
    if held_grant and level_changes and ed == "holder":
        raise HTTPException(403, HOLDERS_LEVEL.format(name=name))
    # Whether the row is there afterwards: as the owner or an Admin said in
    # this save; else gone with any move to or from Manager; else as it is.
    want_row = has_row
    if grant is not None:
        want_row = grant
    elif level_changes and "manager" in (trole, level):
        want_row = False
    gives_grant = grant is True and not held_grant
    takes_grant = held_grant and not want_row
    clears_row = has_row and not want_row
    # A job that is an Admin login's (the Treasurer's) comes off a login
    # moved down from Admin, unless this save names another.
    job_arg = job_key if job_set else keep
    if trole == "admin" and level != "admin" and not job_set:
        lane_was = (ch.seats.get(target) or {}).get("lane")
        was = cj.find(ch.b, lane_was, gone=True) if lane_was else None
        if was and was.get("role") == "admin":
            job_arg = None

    # ── What the login has now, and what this would leave it with ──
    e = effect(business, ch, target, level=level if level_changes else keep,
               areas=areas if areas_set else keep, job=job_arg,
               moves={key: to for key, to in plan})
    # One of the church's own jobs brings only the duties given on the sheet
    # (church_duties.own_job_seat): none from its areas, none from a starting
    # job its areas happen to spell. So that a save onto one doesn't quietly
    # take away what a Manager's sheet showed ticked, a duty they did is
    # given to them by name, with everyone who does it now. NARROWLY (the
    # review of 2026-11-18: kept wide, an Admin moved down to one area left
    # with 44 duties): only for a login that was ALREADY a Manager before
    # this save; never a money duty or the lanes' oversight; only a duty in
    # an area they are shown AFTER this save, and never when the save leaves
    # them seeing the whole church. Everything else they did comes off, and
    # the record says so. A duty that can't be named for them (it already
    # names the most logins it takes) comes off too.
    kept_plan: List[Tuple[str, List[str]]] = []
    if (e["role_now"] == "manager" and e["role_then"] == "manager" and cd.own_job_seat({"lane": e["lane_then"]})
            and e["shown_then"] is not None):
        planned = {key for key, _to in plan}
        keeping = [k for k in e["less_duties"]
                   if k not in remove and k not in planned and not cd.CATALOG[k]["money"]
                   and k not in cd.OVERSIGHT and cd.CATALOG[k]["area"] in e["shown_then"]]
        if keeping:
            page = {d["key"]: d for d in cd.build(business)["duties"]}
            for k in keeping:
                doing = [h["user_id"] for h in page[k]["holders"] if h.get("active")]
                to = sorted(set(doing) | {target})
                if len(to) > cd.MAX_HOLDERS or cd._check(ch.b, business, [u for u in to if u != target], k):
                    continue
                kept_plan.append((k, to))
            if kept_plan:
                e = effect(business, ch, target, level=level if level_changes else keep,
                           areas=areas if areas_set else keep, job=job_arg,
                           moves={key: to for key, to in plan + kept_plan})
    kept_duties = [k for k, _to in kept_plan]
    stored_areas = e["stored_areas"]
    more_areas, more_duties = e["more_areas"], e["more_duties"]
    less_areas, less_duties = e["less_areas"], e["less_duties"]
    # Moved down from Admin, a login must be left with areas of its own.
    if trole == "admin" and level != "admin" and not e["picked_then"]:
        raise HTTPException(400, PICK_AREAS.format(name=name))

    # A holder's ceiling, on the result: nothing this leaves the login with
    # may be something only the owner or an Admin gives.
    if ed == "holder":
        for k in more_areas + more_duties:
            if k in lk["locked_why"] and (k in lk["locked_areas"] or k in lk["locked_duties"]):
                raise HTTPException(403, lk["locked_why"][k])
        if e["shown_then"] is None and e["shown_now"] is not None:
            raise HTTPException(403, BACK_TO_GUESS)

    # Giving as its own tick: checked here with everything else, before
    # the first write. The owner's own raise is "more" (the password, always);
    # an Admin's or a holder's is only a request to the owner, opens nothing
    # and asks for no password.
    import church_money_ticks as cmt
    money = cmt.plan(business, ch, st, viewer, target, body, level)
    money_more = bool(money and money["kind"] == "grant" and money["more"])

    widens = bool(more_areas or more_duties or e["level_up"] or gives_grant or money_more)
    if widens and widening is not None:
        widening()

    # ── The words for the record, from what really changes ──
    if level_changes:
        said.append(f"level: {LEVEL_LABEL[level]} (was {LEVEL_LABEL.get(trole, trole)})"
                    + (", so they see the whole church, giving included" if becomes_admin else ""))
    if e["lane_then"] != e["lane_now"]:
        label = job_label or (cj.label_of(ch.b, e["lane_then"]) if e["lane_then"] else None)
        said.append(f"job: {label}" if label else "no job")
    if more_areas:
        said.append("added " + _join([_label(a) for a in more_areas]))
    if less_areas:
        said.append("took off " + _join([_label(a) for a in less_areas]))
    if areas_set and areas is None and isinstance(stored_areas, list):
        said.append("areas back to Chief's guess")

    def _duty_words(keys: List[str]) -> str:
        labels = [f"“{cd.CATALOG[k]['label']}”" for k in keys]
        return _join(labels[:4]) + (f" and {len(labels) - 4} more" if len(labels) > 4 else "")
    if more_duties:
        said.append("gave " + _duty_words(more_duties))
    if less_duties:
        said.append("took away " + _duty_words(less_duties))
    if kept_duties:
        said.append("kept " + _duty_words(kept_duties) + " by name")

    # ── Everything checked: the writes, in the order that fails safe ──
    # 0. The duties kept by name, FIRST. Each names the same people who do
    #    it now (this login among them, by their areas or their old job), so
    #    until the job below is written nothing about who does what has
    #    changed: a move that fails here stops the save with the level, the
    #    areas and the job untouched. (The duties module writes one duty a
    #    call; there is no all-at-once write to ask for.)
    if money and money["first"]:
        cmt.apply(money, business, viewer, ch.login_name(viewer), target)
        said.append(money["said"])
    for key, to in kept_plan:
        try:
            cd.move(business, key, to, viewer)
        except HTTPException:
            raise HTTPException(503, "That didn't save. Their level, job and areas are as they were. Try again.")
    # 1. The grant taken away, BEFORE the level. Written after it, a save
    #    that failed here left the login moved down with the row still
    #    there, and the next move back to Manager made them a holder again.
    if clears_row:
        if takes_grant:
            cj.set_grant(business, target, False, viewer)
            said.append(f"took away “{cj.GRANT_LABEL}”")
        elif cj.drop_grant(ch.b, target) is False:
            # A row left from before (they weren't a Manager): nobody's
            # grant is being taken, but it must be gone before they are one.
            raise HTTPException(503, "That didn't save. Nothing changed. Try again.")
    # 2. The level, the areas and the job, in one row write: never a new
    #    level with the old areas.
    if level_changes and not cmt.role_lowered(ch.b, target, trole, level):
        # A login moved down keeps no more giving than the owner gave it at
        # the level it will have (an Admin's row is cleared, a Viewer's is
        # lowered to See), BEFORE the level is written. If that can't be
        # saved, the level isn't either.
        raise HTTPException(503, "That didn't save. Their level, job and areas are as they were. Try again.")
    if level_changes or areas_set or job_arg is not keep:
        church_areas.set_login(ch.b, target, level, areas=areas if areas_set else keep, job=job_arg,
                               level=level if level_changes else keep)
    # 3. The duties (each checked above, for the level just saved).
    for key, to in plan:
        cd.move(business, key, to, viewer)
    # 4. The grant given, last: only ever to a login that is a Manager now.
    if want_row and not has_row:
        cj.set_grant(business, target, True, viewer)
    if gives_grant:
        said.append(f"gave “{cj.GRANT_LABEL}”")
    # 5. Giving, raised or asked for, LAST: the level it rides on is saved.
    #    If this one write fails, everything above is saved and recorded,
    #    and the refusal says which part to try again.
    money_failed: Optional[HTTPException] = None
    if money and not money["first"]:
        try:
            cmt.apply(money, business, viewer, ch.login_name(viewer), target)
            said.append(money["said"])
        except HTTPException as err:
            money_failed = err
    try:
        import chief_areas
        chief_areas.forget(ch.b)
        church_areas._forget(ch.b, target)
        cd._forget(ch.b)
    except Exception:  # noqa: BLE001 — Chief reads the new sheet within the minute either way
        pass
    summary = f"changed {name}'s sheet: " + "; ".join(said) if said else ""
    if said:
        cj.changed(business, "sheet", viewer, ed or "", ch.login_name(viewer), summary, subject=target,
                   detail={"level": level if level_changes else None,
                           "job": body.get("job") if job_set else None, "areas": areas if areas_set else None,
                           "duties": {"add": add, "remove": remove}, "grant": grant,
                           "more": {"areas": more_areas, "duties": more_duties},
                           "less": {"areas": less_areas, "duties": less_duties},
                           "kept_by_name": kept_duties,
                           "money": ({"kind": money["kind"], "wants": money["wants"], "was": money["now"]}
                                     if money and money_failed is None else None)})
    if money_failed is not None:
        raise HTTPException(money_failed.status_code,
                            (str(money_failed.detail) + " Everything else on the sheet saved.") if said
                            else money_failed.detail)
    asked = bool(money and money["kind"] == "ask")
    # A holder's change is sent to the owner (cj.changed); the app says so.
    out = {"widens": widens, "summary": summary, "changed": bool(said),
           "owner_told": bool(said) and (ed == "holder" or asked)}
    if money:
        out["money_asked"] = asked
    return out


# ─── The jobs, for the people who set them up ─────────────────────────

def jobs_view(business: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """The jobs and what this login may do with them: {jobs, can_manage,
    can_make_admin_job}."""
    ch = co.Church(business)
    role = ch.role(user_id)
    if role not in ("owner", "admin", "manager"):
        # The route's own gate said a Manager and up; this is that again, on
        # this church's own rows, the way standing() checks a sheet's reader.
        raise HTTPException(403, "The church's jobs are read by its office seats: a Manager and up.")
    ed = cj.editor(ch.b, user_id, role)
    # The duty list a job's form ticks from, so whoever sets up jobs needs no
    # other page's read for it (the duties page is not theirs to open).
    duties = [{"key": d["key"], "label": d["label"], "area": d["area"], "money": bool(d["money"]),
               "does": d["does"]} for d in cd.build(business)["duties"]]
    return {"jobs": cj.jobs(ch.b), "can_manage": ed is not None, "can_make_admin_job": ed == "owner",
            "duties": duties}


def _jobs_editor(body_biz: Any, user: Any) -> Tuple[Dict[str, Any], str, str]:
    """(the church, the editor's kind, their name) for a write to the jobs;
    403 for a login that sets none up."""
    church_areas._gate(user)
    biz = _uuid(body_biz, "church")
    assert_access(biz, user, "member")
    business = _business(biz)
    ch = co.Church(business)
    ed = cj.editor(biz, str(user.id), ch.role(str(user.id)))
    if not ed:
        raise HTTPException(403, "Only the owner, an Admin, or whoever sets up jobs and people's sheets makes or "
                                 "changes a job. Ask the owner to give you that.")
    return business, ed, ch.login_name(str(user.id))


def save_job(business: Dict[str, Any], ed: str, by: str, by_name: str, body: Dict[str, Any],
             key: Optional[str] = None) -> Dict[str, Any]:
    """Make one of the church's own jobs, or change one (with `key`):
    the routes' and Chief's one path. Recorded; told to the owner when a
    holder did it."""
    got = cj.update(business, key, body, by, ed) if key else cj.create(business, body, by, ed)
    cj.changed(business, "job", by, ed, by_name, cj.summary_of("update" if key else "create", got["job"]),
               job_key=got["job"]["key"], detail={"before": got.get("before"), "after": got["job"]})
    return got


def remove_job(business: Dict[str, Any], ed: str, by: str, by_name: str, key: str) -> Dict[str, Any]:
    got = cj.remove(business, key, by, ed)
    cj.changed(business, "job", by, ed, by_name, cj.summary_of("remove", got["job"]), job_key=got["job"]["key"],
               detail={"before": got["job"], "after": None})
    return got


# ─── Routes ───────────────────────────────────────────────────────────

def _church_access(min_role: str):
    """business_access, after the business id is known to be a UUID: that
    dependency puts the id into a PostgREST path as it came, where a value
    ending in an encoded # would drop the filters after it."""
    inner = business_access(min_role)

    async def dep(business_id: str, session: UserSession = Depends(sb_clients.authed_request)) -> Dict[str, Any]:
        _uuid(business_id, "church")
        return await inner(business_id, session)
    return dep


@router.get("/sheet")
def get_sheet(business_id: str, user_id: str, session: UserSession = Depends(sb_clients.authed_request),
              biz: Dict[str, Any] = Depends(_church_access("viewer"))):
    """One person's sheet. The owner or an Admin reads anyone's; whoever sets
    up jobs and sheets, a Manager login's or below; anyone, their own."""
    church_areas._gate(session.user)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, NOT_CHURCH)
    return compose(biz, str(session.user.id), _uuid(user_id, "login"))


@router.put("/sheet")
def put_sheet(body: Dict[str, Any], request: Request, session: UserSession = Depends(sb_clients.authed_request)):
    """Change a person's sheet, then answer with it as it is now. A change
    that leaves someone with more (an area they're shown, a duty they hold)
    asks for the password again, as an invite does, whoever is acting; one
    that leaves them with less never does."""
    user = session.user
    church_areas._gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"), "church")
    target = _uuid(body.get("user_id"), "login")
    assert_access(biz, user, "member")
    business = _business(biz)
    import ledger_unlock
    got = change(business, str(user.id), target, body, widening=lambda: ledger_unlock.require_unlock(
        request, str(user.id), ledger_unlock.SCOPE_ACCESS, business_id=biz))
    return {**compose(business, str(user.id), target), "changed": got["changed"], "summary": got["summary"],
            "owner_told": got["owner_told"], "money_asked": got.get("money_asked", False)}


@router.get("/sheet/jobs")
def list_jobs(business_id: str, session: UserSession = Depends(sb_clients.authed_request),
              biz: Dict[str, Any] = Depends(_church_access("manager"))):
    """The starting jobs and the church's own, and whether this login may
    set them up. A Manager seat and up."""
    church_areas._gate(session.user)
    import church_follow_up as cfu
    if not cfu.is_church(biz):
        raise HTTPException(404, NOT_CHURCH)
    return jobs_view(biz, str(session.user.id))


@router.post("/jobs")
def post_job(body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """A new job of the church's own."""
    body = body or {}
    business, ed, name = _jobs_editor(body.get("business_id"), session.user)
    return {"ok": True, "job": save_job(business, ed, str(session.user.id), name, body)["job"]}


@router.put("/jobs/{key}")
def put_job(key: str, body: Dict[str, Any], session: UserSession = Depends(sb_clients.authed_request)):
    """Change one of the church's own jobs. Nobody who holds it changes."""
    body = body or {}
    business, ed, name = _jobs_editor(body.get("business_id"), session.user)
    return {"ok": True, "job": save_job(business, ed, str(session.user.id), name, body, key)["job"]}


@router.delete("/jobs/{key}")
def delete_job(key: str, business_id: str, session: UserSession = Depends(sb_clients.authed_request)):
    """Take one of the church's own jobs off the list. Whoever holds it keeps
    their areas and duties, and their job still reads as its title."""
    business, ed, name = _jobs_editor(business_id, session.user)
    remove_job(business, ed, str(session.user.id), name, key)
    return {"ok": True}
