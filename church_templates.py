"""church_templates.py — the ready-made directory (docs/CHURCH_LEADERS_STEP2.md §1.1, §2.1-§2.3; PR B4a).

Platform-curated and kept in code, so the PR is the review: there is no
table and no admin screen. A church copies a ready-made as its own draft
(B4b); the platform never writes to a copy again.

    a role ......... `<tradition>.<row>`, built at import from church_roles.TYPES
                     (the rows ensure_library seeds, so its switches are the
                     backfill's), plus six `any.*` roles the departments need
    a department ... a ministry: its area, the office duty that helps it, its
                     leader's role in each tradition, an overseer (the
                     church's senior role, unless a shape picks), the units it
                     suggests as words, a weekly rhythm
    a shape ........ a whole church: its roles with this shape's switch flips,
                     its departments and who oversees each, the pastor's-yes
                     and office-overseer picks, families per shepherd. Never a
                     money level. Who shepherds is read off its roles.
    SEATS .......... one seat across traditions: each tradition's own row,
                     else a stated fallback (Grace's youth seat is its Youth
                     Minister, Love City's its Youth Pastor)
    VERSIONS ....... {key: (version, sha256 of its content)}, pinned: content
                     that changes fails the test until the pin is redone
                     (python church_templates.py, which bumps what changed)
    search(q, kind, tradition) ... a lookup (§2.3): it decides nothing
    card(t, tradition, church) ... what a ready-made says: what it does, who it
                                   answers to, what it sees, what it can do
    here(biz, t, tradition, st) .. what adopting it would add at a church,
                                   read only
    adopt(biz, kind, key, ...) ... the church's own copy (B4b): drafts, in one
                                   change Undo takes back out, and what it
                                   would change on a live row waiting for a yes
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import HTTPException

import church_areas as ca
import church_duties as cd
import church_map as cm
import church_roles as cr

KINDS = ("shape", "department", "role")
ANY, ANY_LABEL = "any", "Any church"


# ─── Roles ────────────────────────────────────────────────────────────

def _role(tradition: str, row: Dict[str, Any], lead: str, words: Iterable[str] = ()) -> Dict[str, Any]:
    handles = cr.clean_handles(row["job"], row["handles"])
    return {"kind": "role", "key": f"{tradition}.{row['key']}", "tradition": tradition, "row": row["key"],
            "title": row["title"], "job": row["job"], "note": row["note"],
            "definition": row["definition"] or cr.JOBS[row["job"]]["definition"], "lead": lead,
            "reports": row["reports"], "covers": row["covers"], "teams": row["teams"], "handles": handles,
            **cr._catalog_switches(row, handles), "office": row["office"], "words": list(words)}


# The six the departments need and no tradition names (§2.2), each on its job's switches.
_ANY_ROWS = [
    (cr._r("media_lead", "Media lead", "team", definition="{title} leads the media team: sound, screens, cameras and "
           "the livestream, with every Sunday’s spots filled."),
     ("media", "sound", "video", "camera", "livestream", "production", "tech", "av", "slides", "lighting")),
    (cr._r("facilities_lead", "Facilities lead", "team", definition="{title} keeps the building safe and working: "
           "repairs, setup, and who has a key."),
     ("facilities", "building", "maintenance", "safety", "security", "custodian", "grounds", "setup")),
    (cr._r("outreach_lead", "Outreach lead", "welcome", definition="{title} leads the church’s outreach in its "
           "community, and sees that each new person met is followed up that week."),
     ("outreach", "evangelism", "evangelist", "community", "street")),
    (cr._r("mens_lead", "Men’s Ministry lead", "ministry", definition="{title} leads the men’s ministry: its "
           "gatherings, its groups and the men who serve in it."), ("men", "brotherhood", "fellowship")),
    (cr._r("womens_lead", "Women’s Ministry lead", "ministry", definition="{title} leads the women’s ministry: its "
           "gatherings, its groups and the women who serve in it."), ("women", "ladies", "sisterhood", "fellowship")),
    (cr._r("missions_lead", "Missions lead", "ministry", definition="{title} leads the church’s missions: the "
           "missionaries it supports, its mission trips, and what it sends them."),
     ("missions", "missionary", "missionaries", "trips", "global")),
]

ROLES: Dict[str, Dict[str, Any]] = {}
for _t in cr.TYPE_ORDER:
    _lead = next((r["title"] for r in cr.TYPES[_t]["rows"] if r["key"] == "intercessor_leader"), "leader")
    for _row in cr.TYPES[_t]["rows"]:
        ROLES[f"{_t}.{_row['key']}"] = _role(_t, _row, _lead)
for _row, _words in _ANY_ROWS:
    ROLES[f"{ANY}.{_row['key']}"] = _role(ANY, _row, "", _words)


def _seat(default: str, **by: str) -> Dict[str, str]:
    """{tradition: role key}: `by`'s row, else the default's row in that
    tradition, else the default. A name `by` gives must exist (KeyError)."""
    row, out = default.split(".", 1)[1], {}
    for t in cr.TYPE_ORDER:
        if t in by:
            out[t] = ROLES[by[t] if "." in by[t] else f"{t}.{by[t]}"]["key"]
        else:
            out[t] = f"{t}.{row}" if f"{t}.{row}" in ROLES else ROLES[default]["key"]
    return out


SEATS: Dict[str, Dict[str, str]] = {
    "pastor": _seat("nondenom.pastor"),
    "associate": _seat("nondenom.associate_pastor", baptist="associate_ministers", cogic="ministers",
                       ame="associate_ministers", coc="preaching_minister", liturgical="associate_rector"),
    "executive": _seat("nondenom.executive_pastor"),
    "elders": _seat("nondenom.elders", ame="stewards", presby="ruling_elders", coc="pastor"),
    "deacons": _seat("nondenom.deacons", liturgical="deacon_ordained"),
    "mother": _seat("cogic.church_mother", baptist="mothers_board"),
    "care_team": _seat("nondenom.care_team"),
    "preacher": _seat("coc.preaching_minister", nondenom="ministers", baptist="associate_ministers", cogic="ministers",
                      ame="associate_ministers", presby="associate_pastor", liturgical="associate_rector"),
    "prayer_lead": _seat("nondenom.intercessor_leader"),
    "prayer_team": _seat("nondenom.intercessors"),
    "team_leader": _seat("nondenom.team_leader"),
    "welcome": _seat("nondenom.welcome_lead", cogic="evangelists", liturgical="ocia"),
    "ushers": _seat("nondenom.team_leader", baptist="usher_board"),
    "worship": _seat("nondenom.worship_leader", baptist="minister_of_music", ame="minister_of_music",
                     presby="music_director", coc="song_leaders", liturgical="music_director"),
    "youth": _seat("nondenom.youth_pastor", baptist="youth_minister", cogic="ypww_president", ame="ypd_director",
                   presby="christian_ed", coc="youth_minister", liturgical="religious_ed"),
    "children": _seat("nondenom.childrens_director", presby="christian_ed", liturgical="religious_ed"),
    "teachers": _seat("nondenom.class_teachers", baptist="sunday_school", cogic="sunday_school", ame="church_school",
                      presby="christian_ed", coc="bible_class_teachers", liturgical="religious_ed"),
    "care_lead": _seat("nondenom.associate_pastor", baptist="associate_ministers", cogic="missionaries", ame="stewards",
                       coc="preaching_minister", liturgical="deacon_ordained"),
    "media": _seat("any.media_lead"),
    "facilities": _seat("any.facilities_lead"),
    "outreach": _seat("any.outreach_lead", cogic="evangelists"),
    "mens": _seat("any.mens_lead"),
    "womens": _seat("any.womens_lead"),
    "missions": _seat("any.missions_lead"),
}


# ─── Departments ──────────────────────────────────────────────────────

def _dept(key: str, name: str, about: str, area: str, duty: str, leader: str, rhythm: str, *, space: str = "",
          serve: Iterable[str] = (), groups: Iterable[str] = (), words: Iterable[str] = (),
          lead_can: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    """`lead_can`: switches its leader's role needs here (a prayer leader leads)."""
    return {"kind": "department", "key": key, "name": name, "about": about, "area": area, "support_duty": duty,
            "leader_seat": leader, "leader": SEATS[leader], "lead_can": dict(lead_can or {}),
            "overseer_seat": "pastor", "overseer": SEATS["pastor"],
            "units": {"space": space or None, "serve": list(serve), "group": list(groups)}, "rhythm": rhythm,
            "words": list(words)}


DEPARTMENTS: Dict[str, Dict[str, Any]] = {d["key"]: d for d in (
    _dept("worship", "Worship & Arts", "Sunday worship: the singers, the musicians and the platform.",
          "worship_media", "production_schedule", "worship", "Rehearsal midweek; the songs set by Thursday.",
          serve=("worship", "praise", "choir", "music", "band"), groups=("choir", "praise", "worship"),
          words=("arts", "music", "choir", "band", "singers", "praise")),
    _dept("media", "Media & Production", "Sound, screens, cameras and the livestream.", "worship_media", "stream",
          "media", "Saturday the stream is tested; on Sunday the booth runs it and files the replay.",
          serve=("media", "sound", "video", "camera", "stream", "production", "tech"),
          words=("sound", "video", "camera", "livestream", "tech", "av", "slides", "lighting")),
    _dept("youth", "Youth", "Teens and the leaders who walk with them. Every leader has a background check.",
          "kids_youth", "youth", "youth", "Youth night each week; its leaders check in with their overseer monthly.",
          space="youth", serve=("youth", "teen", "student"), groups=("youth", "teen", "student"),
          words=("teens", "students", "ypww", "ypd")),
    _dept("children", "Children", "Kids from the nursery up: their rooms on Sunday, check-in and pickup.",
          "kids_youth", "kids", "children", "Rooms open every Sunday; the check-in leaders meet monthly.",
          space="kids", serve=("kid", "children", "nursery"), groups=("kid", "children"),
          words=("kids", "nursery", "check-in")),
    _dept("prayer", "Prayer", "Prayer requests prayed over within a day, and prayer before every service.",
          "people_care", "prayer", "prayer_lead", "Each request prayed over within a day; the team prays before services.",
          serve=("prayer", "intercessor"), groups=("prayer", "intercessor"),
          words=("intercession", "intercessors", "prayer chain", "prayer band"), lead_can={"can_lead": True}),
    _dept("care", "Care & Visitation", "Visits, meals, the hospital and the grieving.", "people_care",
          "care_visits", "care_lead", "The care list read each week; every visit and meal has a person.",
          serve=("care", "visit", "meal", "benevolence"), groups=("care", "grief", "visitation"),
          words=("visits", "hospital", "meals", "benevolence", "sick", "grief", "bereavement")),
    _dept("welcome", "Welcome & Guest Services", "Every guest greeted on Sunday and called that week.",
          "people_care", "first_guests", "welcome", "Each Sunday’s guests have a person by Monday and a call by Wednesday.",
          serve=("welcome", "guest", "hospitality", "connect", "greeter"), groups=("welcome", "connect", "newcomer"),
          words=("guests", "hospitality", "connections", "first time", "newcomers", "visitors")),
    _dept("ushers", "Ushers & Greeters", "The doors, the aisles and the seats on Sunday.", "people_care",
          "serve_schedule", "ushers", "Every Sunday’s doors and aisles have a yes by Friday.",
          serve=("usher", "greeter", "door", "parking"), groups=("usher",),
          words=("doors", "parking", "seating")),
    _dept("outreach", "Outreach & Evangelism", "The church in its community, and each person met followed up.",
          "website_outreach", "events", "outreach", "An outreach each month; each person met followed up that week.",
          serve=("outreach", "evangelism", "community"), groups=("outreach", "evangelism"),
          words=("community", "street", "serve day")),
    _dept("groups", "Classes & Groups", "Classes, Bible studies and small groups, and who finished.",
          "groups_classes", "groups", "teachers", "Groups meet each week; their leaders say who missed three weeks.",
          serve=("teacher",), groups=("class", "study", "discipleship"),
          words=("bible study", "small groups", "sunday school", "discipleship")),
    _dept("mens", "Men’s Ministry", "The men of the church: their gatherings, groups and service.", "groups_classes",
          "events", "mens", "A gathering each month; its leaders check in each quarter.",
          serve=("men",), groups=("men", "brotherhood"), words=("brotherhood", "fellowship")),
    _dept("womens", "Women’s Ministry", "The women of the church: their gatherings, groups and service.",
          "groups_classes", "events", "womens", "A gathering each month; its leaders check in each quarter.",
          serve=("women",), groups=("women", "ladies", "sister"), words=("ladies", "sisters", "sisterhood", "fellowship")),
    _dept("missions", "Missions", "The missionaries the church supports, its mission trips, and what it sends them.",
          "website_outreach", "events", "missions", "Missionaries heard from each month; trips planned a season ahead.",
          serve=("mission",), groups=("mission", "missionary"), words=("missionaries", "mission trips", "global")),
    _dept("facilities", "Facilities & Safety", "The building kept safe and working: repairs, setup and security.",
          "office", "building", "facilities", "A walk-through each month; anything broken or unsafe has an owner that week.",
          serve=("facilities", "building", "maintenance", "security", "safety"),
          words=("building", "maintenance", "security", "safety team", "custodian", "grounds", "setup")),
)}


# ─── Shapes ───────────────────────────────────────────────────────────

def _shape(key: str, label: str, about: str, traditions: Iterable[str], roles: Dict[str, Dict[str, bool]],
           departments: Dict[str, str], *, pastor_yes: Iterable[str], office: Iterable[str], families: int,
           words: Iterable[str] = ()) -> Dict[str, Any]:
    """`roles`: {seat: this shape's switch flips}; `departments`: {department:
    its overseer's seat}. Every seat a department or a pick names is a role too."""
    seats = dict(roles)
    for d, ov in departments.items():
        for s in (DEPARTMENTS[d]["leader_seat"], ov):
            seats.setdefault(s, {})
    for s in (*pastor_yes, *office):
        seats.setdefault(s, {})
    return {"kind": "shape", "key": key, "label": label, "about": about, "traditions": list(traditions),
            "roles": [{"seat": s, "keys": SEATS[s], "flips": dict(f)} for s, f in seats.items()],
            "departments": [{"department": d, "overseer": ov} for d, ov in departments.items()],
            "pastor_yes": list(pastor_yes), "office_overseer": list(office), "families": families,
            "words": list(words)}


_BASE = {"pastor": {}, "prayer_lead": {}, "prayer_team": {}, "team_leader": {}, "welcome": {}}
SHAPES: Dict[str, Dict[str, Any]] = {s["key"]: s for s in (
    _shape("pastor_deacons", "Pastor & deacons", "The pastor leads, and a board of deacons shepherds the families "
           "and oversees the ministries with them.", ("baptist", "nondenom", "cogic", "other"),
           {**_BASE, "deacons": {"can_shepherd": True, "can_oversee": True}},
           {"worship": "pastor", "youth": "deacons", "children": "deacons", "prayer": "pastor", "care": "deacons",
            "welcome": "deacons", "ushers": "deacons"},
           pastor_yes=("pastor",), office=("pastor",), families=12, words=("deacon board", "congregational")),
    _shape("pastor_elders", "Pastor & elders", "The pastor leads with elders beside them. Associate pastors oversee "
           "the ministries, the elders oversee prayer and care, and deacons serve.", ("nondenom", "cogic", "presby"),
           {**_BASE, "associate": {}, "elders": {}, "deacons": {}, "care_team": {}},
           {"worship": "associate", "youth": "associate", "children": "associate", "prayer": "elders",
            "care": "elders", "welcome": "associate", "ushers": "associate", "groups": "elders"},
           pastor_yes=("pastor",), office=("pastor",), families=10, words=("elder board",)),
    _shape("bishop_led", "Bishop-led", "A bishop or presiding pastor over the church, with ordained elders and "
           "ministers, and a church mother over the women and the prayer.", ("cogic", "ame", "other"),
           {**_BASE, "elders": {}, "associate": {}, "mother": {"can_oversee": True}, "deacons": {}},
           {"worship": "elders", "youth": "elders", "children": "mother", "prayer": "mother", "care": "elders",
            "welcome": "elders", "outreach": "elders", "missions": "elders", "mens": "elders", "womens": "mother"},
           pastor_yes=("pastor",), office=("pastor",), families=12,
           words=("bishop", "superintendent", "presiding", "ordained")),
    _shape("elder_led", "Elder-led", "No one is called pastor: the elders oversee the congregation together and every "
           "leader answers to them. A preaching minister preaches, and deacons lead ministries.",
           ("coc", "presby", "other"), {**_BASE, "elders": {}, "preacher": {}, "deacons": {}},
           {"worship": "elders", "youth": "elders", "children": "elders", "prayer": "elders", "care": "elders",
            "welcome": "elders", "groups": "elders", "outreach": "elders", "facilities": "elders"},
           pastor_yes=("elders",), office=("elders",), families=10,
           words=("shepherds", "eldership", "plurality", "preaching minister")),
    _shape("multi_staff", "Multi-staff", "An executive pastor runs the office and staff, associate pastors oversee "
           "the ministries, and elders give the board’s yes on money.", ("nondenom", "presby", "other"),
           {**_BASE, "executive": {}, "associate": {}, "elders": {"can_board_yes": True}, "deacons": {},
            "care_team": {}},
           {"worship": "associate", "media": "associate", "youth": "associate", "children": "associate",
            "prayer": "elders", "care": "associate", "welcome": "associate", "ushers": "associate",
            "groups": "associate", "outreach": "associate", "facilities": "executive"},
           pastor_yes=("pastor",), office=("executive",), families=12,
           words=("executive pastor", "staff", "large church", "associate pastors")),
    _shape("pastor_led", "Pastor-led", "A smaller church: the pastor oversees every ministry, with a few team leads "
           "and a prayer team.", ("nondenom", "baptist", "cogic", "ame", "presby", "liturgical", "other"), dict(_BASE),
           {"worship": "pastor", "children": "pastor", "prayer": "pastor", "welcome": "pastor"},
           pastor_yes=("pastor",), office=("pastor",), families=15,
           words=("small church", "solo pastor", "church plant", "house church")),
)}

ALL: Dict[str, Dict[str, Any]] = {**SHAPES, **DEPARTMENTS, **ROLES}
BY_KIND = {"shape": SHAPES, "department": DEPARTMENTS, "role": ROLES}


def get(kind: str, key: str) -> Optional[Dict[str, Any]]:
    return BY_KIND.get(kind, {}).get(key)


# ─── Versions (§1.1) ──────────────────────────────────────────────────

def digest(t: Dict[str, Any]) -> str:
    body = json.dumps({k: v for k, v in t.items() if k != "version"}, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def stale() -> List[str]:
    """The ready-mades whose content isn't what VERSIONS pins."""
    return [k for k, t in ALL.items() if VERSIONS.get(k, (0, ""))[1] != digest(t)]


# ─── In words ─────────────────────────────────────────────────────────

def _trad(tradition: str) -> str:
    return tradition if tradition in cr.TYPES else "nondenom"


def _label(tradition: str) -> str:
    return ANY_LABEL if tradition == ANY else cr.TYPES[_trad(tradition)]["label"]


def _can(t: Dict[str, Any], flips: Optional[Dict[str, Any]] = None) -> str:
    """What a role can do, in church_map.says' words ("" for nothing)."""
    said = cm.says(cm.Map("", roles={"t": {**t, **(flips or {})}}), {"id": "t", "handles": t["handles"]})
    words = said.split(": ", 1)[1]
    return "" if words == "none" else words


def _role_card(t: Dict[str, Any], tradition: str, church: str = "") -> Dict[str, Any]:
    home = _trad(tradition) if t["tradition"] == ANY else t["tradition"]
    up = None
    if t["job"] != "senior":
        up = (ROLES.get(f"{home}.{t['reports']}") if t["reports"] else None) or ROLES[f"{home}.pastor"]
    job = cr.JOBS[t["job"]]
    return {"kind": "role", "key": t["key"], "version": t["version"], "title": t["title"],
            "tradition": {"key": t["tradition"], "label": _label(t["tradition"])},
            "job": {"key": t["job"], "label": job["label"]}, "note": t["note"],
            "does": cr._fill(t["definition"], t["title"], church, t["lead"] or "leader"),
            "answers_to": up["title"] if up else None, "sees": job["sees"], "never": job["never"],
            "can": _can(t), "switches": {k: t[k] for k in (*cr.SWITCHES, "made_for")}, "handles": t["handles"]}


def _title(seat: str, tradition: str) -> str:
    return ROLES[SEATS[seat][_trad(tradition)]]["title"]


def _dept_card(t: Dict[str, Any], tradition: str) -> Dict[str, Any]:
    duty = cd.CATALOG[t["support_duty"]]
    return {"kind": "department", "key": t["key"], "version": t["version"], "name": t["name"], "about": t["about"],
            "area": {"key": t["area"], "label": ca.AREAS[t["area"]]["label"]},
            "office_help": {"key": t["support_duty"], "label": duty["label"], "does": duty["does"]},
            "leader": {"key": t["leader"][_trad(tradition)], "title": _title(t["leader_seat"], tradition)},
            "overseer": {"key": t["overseer"][_trad(tradition)], "title": _title(t["overseer_seat"], tradition)},
            "units": t["units"], "rhythm": t["rhythm"]}


def seats_of(shape: Dict[str, Any], tradition: str) -> List[Tuple[str, Dict[str, Any]]]:
    """A shape's roles at a church of `tradition`: (role key, its flips here),
    one per role (coc's elders seat is its senior role), with each
    department's lead_can on its leader."""
    out: Dict[str, Dict[str, Any]] = {}
    for r in shape["roles"]:
        out.setdefault(r["keys"][_trad(tradition)], {}).update(r["flips"])
    for d in shape["departments"]:
        dd = DEPARTMENTS[d["department"]]
        out[dd["leader"][_trad(tradition)]].update(dd["lead_can"])
    return list(out.items())


def _shape_card(t: Dict[str, Any], tradition: str) -> Dict[str, Any]:
    roles = seats_of(t, tradition)
    return {"kind": "shape", "key": t["key"], "version": t["version"], "label": t["label"], "about": t["about"],
            "fits": [_label(x) for x in t["traditions"]], "fits_you": _trad(tradition) in t["traditions"],
            "roles": [{"key": k, "title": ROLES[k]["title"], "can": _can(ROLES[k], f), "flips": f} for k, f in roles],
            "departments": [{"key": d["department"], "name": DEPARTMENTS[d["department"]]["name"],
                             "leader": _title(DEPARTMENTS[d["department"]]["leader_seat"], tradition),
                             "overseer": _title(d["overseer"], tradition)} for d in t["departments"]],
            "pastor_yes": [_title(s, tradition) for s in t["pastor_yes"]],
            "office_overseer": [_title(s, tradition) for s in t["office_overseer"]],
            "shepherds": [ROLES[k]["title"] for k, f in roles if {**ROLES[k], **f}["can_shepherd"] is True],
            "families": t["families"]}


def card(t: Dict[str, Any], tradition: str, church: str = "") -> Dict[str, Any]:
    if t["kind"] == "role":
        return _role_card(t, tradition, church)
    return _dept_card(t, tradition) if t["kind"] == "department" else _shape_card(t, tradition)


# ─── Search (§2.3) ────────────────────────────────────────────────────

WORDS: Dict[str, Tuple[str, ...]] = {
    "greeter": ("welcome", "usher", "hospitality", "guest"),
    "music": ("worship", "praise", "choir"),
    "kids": ("children", "nursery"),
    "teens": ("youth", "student", "ypww", "ypd"),
    "sound": ("media", "production"),
    "money": ("treasurer", "trustee", "financial"),
}
_STOP = {"a", "an", "and", "the", "of", "or", "for", "in", "to", "with", "its", "their", "church"}
MATCH = ("title", "name", "like", "says")         # an exact title, a word of its name, a word like it, its words


def words(text: Any) -> List[str]:
    """Casefolded, punctuation out, a plural s dropped (-sses and -ies too)."""
    out = []
    for w in re.findall(r"[^\W_]+", re.sub(r"[’'‘]", "", str(text or "").casefold())):
        if w.endswith("sses"):
            w = w[:-2]
        elif w.endswith("ies") and len(w) > 4:
            w = w[:-3] + "y"
        elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
            w = w[:-1]
        if w not in _STOP:
            out.append(w)
    return out


_SYN = {words(k)[0]: {words(v)[0] for v in vs} for k, vs in WORDS.items()}


def _index(t: Dict[str, Any]) -> Tuple[str, set, set]:
    if t["kind"] == "role":
        title = t["title"]
        name = [title, t["row"].replace("_", " "), _label(t["tradition"]), *t["words"]]
        says = [cr._fill(t["definition"], title, "", t["lead"] or "leader"), t["note"]]
    elif t["kind"] == "department":
        title, name = t["name"], [t["name"], t["key"], *t["words"]]
        says = [t["about"], t["rhythm"], ca.AREAS[t["area"]]["label"], cd.CATALOG[t["support_duty"]]["label"]]
    else:
        title, name, says = t["label"], [t["label"], t["key"].replace("_", " "), *t["words"]], [t["about"]]
    return " ".join(words(title)), set(words(" ".join(name))), set(words(" ".join(says)))


def _match(t: Dict[str, Any], q: List[str]) -> Optional[int]:
    """How a ready-made matches the query's words (MATCH's index), None when it doesn't."""
    exact, name, says = _IDX[t["key"]]
    if not q or " ".join(q) == exact:
        return 0
    worst = 1
    for w in q:
        lvl = 1 if w in name else 2 if _SYN.get(w, set()) & name else 3 if w in says else None
        if lvl is None:
            return None
        worst = max(worst, lvl)
    return worst


def search(q: str = "", kind: str = "", tradition: str = "", church: str = "") -> List[Dict[str, Any]]:
    """The directory's lookup: cards, best first: an exact title, a word of its
    name, a word like one (WORDS), a word in what it says; the church's own
    tradition first within each. One card per role title and job; `also`
    names the other traditions that use it. It decides nothing (rule a)."""
    qw, home = words(q), _trad(tradition)
    hits = []
    for n, t in enumerate(ALL.values()):
        if kind and t["kind"] != kind:
            continue
        m = _match(t, qw)
        if m is None:
            continue
        own = (0 if t["tradition"] == home else 1 if t["tradition"] == ANY else 2) if t["kind"] == "role" else \
            (0 if t["kind"] == "department" or home in t["traditions"] else 2)
        hits.append(((m, own, n), t))
    out: List[Dict[str, Any]] = []
    seen: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for (m, _own, _n), t in sorted(hits, key=lambda x: x[0]):
        if t["kind"] == "role":
            same = seen.get((t["title"].casefold(), t["job"]))
            if same is not None:
                same["also"].append(_label(t["tradition"]))
                same["keys"].append(t["key"])
                continue
        c = {**card(t, tradition, church), "match": MATCH[m] if qw else ""}
        if t["kind"] == "role":
            c.update(also=[], keys=[t["key"]])
            seen[(t["title"].casefold(), t["job"])] = c
        out.append(c)
    return out


# ─── What adopting would add here (§2.4's conflicts, read only) ───────

def tradition_of(biz: Dict[str, Any], st: Dict[str, Any]) -> str:
    """The church's type, else Chief's guess, else its name's (never its
    website: a read only, and nothing is seeded)."""
    return _trad(st.get("church_type") or st.get("guessed_type") or cr.guess_type(biz.get("name") or "", ())[0])


def _fold(v: Any) -> str:
    return " ".join(str(v or "").split()).casefold()


def mine(rows: List[Dict[str, Any]], t: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The church's own copy of `t`, if it has one: the same template_key,
    the same title or name (casefolded), or, for a role, one seeded from the
    same row on the same job (New Hope's Youth Director is its Youth Pastor)."""
    tests = [lambda r: r.get("template_key") == t["key"]]
    if t["kind"] == "department":
        tests.append(lambda r: _fold(r.get("name")) == _fold(t["name"]))
    else:
        tests += [lambda r: _fold(r.get("title")) == _fold(t["title"]),
                  lambda r: r.get("catalog_key") == t["row"] and r.get("job") == t["job"]]
    return next((r for test in tests for r in rows if test(r)), None)


def _reads(biz: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """The church's roles and departments, drafts too, as mine() reads them; a 503 when a read fails."""
    q = cm._q(cm._bid(biz))
    return (cm._need(f"/church_role_defs?business_id=eq.{q}&status=in.(active,draft)&select=id,key,title,job,status,"
                     f"catalog_key,template_key,{','.join(cr.SWITCHES)}&limit=300"),
            cm._need(f"/church_departments?business_id=eq.{q}&status=neq.archived&select=id,name,status,"
                     "template_key&limit=200"))


def _sort(t: Dict[str, Any], home: str, roles: List[Dict[str, Any]], depts: List[Dict[str, Any]],
          name: str = "") -> List[Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]]:
    """(each role and department `t` names, its flips here, the church's own
    copy or None when it has none). A role or a department the church already
    has names only itself: adopting it adds nothing. `name`, a second copy,
    takes `t` itself as new."""
    if t["kind"] == "role":
        things = [(t, {})]
    elif t["kind"] == "department":
        things = [(t, {}), (ROLES[t["leader"][home]], t["lead_can"])]
    else:
        things = [(ROLES[k], f) for k, f in seats_of(t, home)] + [(DEPARTMENTS[d["department"]], {})
                                                                  for d in t["departments"]]
    out = []
    for n, (x, flips) in enumerate(things):
        got = None if n == 0 and name else mine(roles if x["kind"] == "role" else depts, x)
        out.append((x, flips, got))
        if n == 0 and got is not None and t["kind"] != "shape":
            break
    return out


WAITS = ("can_board_yes",)       # what a new copy never gets made with: it waits for a yes (money, the owner's)


def _waiting(x: Dict[str, Any], flips: Dict[str, Any], got: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The flips that wait for a yes: on an active copy, each it doesn't have
    yet; on a new copy, the board's yes (WAITS). A draft of the church's gets
    none, but a draft copy of this ready-made still waits for what a new copy
    would, while it isn't set: a retry after the waiting change failed to
    save rebuilds it (#1728 review)."""
    if got is None:
        return {k: v for k, v in flips.items() if k in WAITS and x.get(k) != v}
    if got.get("status") == "draft" and got.get("template_key") == x["key"]:
        return {k: v for k, v in flips.items() if k in WAITS and got.get(k) != v}
    return {k: v for k, v in flips.items() if got.get("status") == "active" and got.get(k) != v}


def here(biz: Dict[str, Any], t: Dict[str, Any], tradition: str, st: Dict[str, Any]) -> Dict[str, Any]:
    """What adopting `t` would add at this church, read only, as adopt()
    does it: each role and department it names, new or already the church's
    own; and what would wait for a yes: a flip on an active role it already
    has, the board's yes on a new one, and a shape's picks. 503 when a read
    fails."""
    import church_map_batch as batch
    roles, depts = _reads(biz)
    home = _trad(tradition)
    out: Dict[str, List[Dict[str, Any]]] = {"new": [], "yours": [], "waits": []}
    have: Dict[str, Dict[str, Any]] = {}
    for x, flips, got in _sort(t, home, roles, depts):
        item = {"kind": x["kind"], "key": x["key"], "name": x.get("title") or x["name"]}
        if got is None:
            out["new"].append(item)
        else:
            have[x["key"]] = got
            out["yours"].append({**item, "id": str(got["id"]), "yours": got.get("title") or got.get("name"),
                                 "status": got.get("status")})
        for k, v in _waiting(x, flips, got).items():
            was = got or x
            out["waits"].append({"kind": "role", "id": str(got["id"]) if got else None, "money": k == "can_board_yes",
                                 "line": f"{was['title']}: {batch.WORD[k]} {batch._say(k, was.get(k), {})} → "
                                         f"{batch._say(k, v, {})}"})
    if t["kind"] == "shape":
        names = {str(r["id"]): r["title"] for r in roles}
        for f, seats in (("pastor_yes_roles", t["pastor_yes"]), ("office_overseer_roles", t["office_overseer"])):
            want = [have.get(SEATS[s][home]) for s in seats]
            ids = sorted(str(r["id"]) for r in want if r and r.get("status") == "active")
            if len(ids) < len(want) or ids != sorted(map(str, st.get(f) or [])) or st.get(f) is None:
                out["waits"].append({"kind": "settings", "money": False, "line": (
                    f"Your church: {batch.WORD[f]} {batch._say(f, st.get(f), names)} → "
                    + ", ".join(_title(s, home) for s in seats))})
    return out


# ─── Adopting: the church's own copy (§2.4, B4b) ──────────────────────

def _units(x: Dict[str, Any], teams: List[str], groups: List[Dict[str, Any]], taken: set) -> List[Dict[str, Any]]:
    """What a department ready-made suggests hanging from it, each only where
    exactly one of the church's own things matches (its space; one Serve
    team; one group) and no department holds that thing yet. The words
    suggest once; what's stored is the church's thing (§0 rule a)."""
    s = x["units"]
    found = [[{"kind": "space", "ref": "", "label": s["space"]}] if s["space"] else []]
    for kind, have, said in (("serve_option", [("", n) for n in teams], s["serve"]),
                             ("group", [(str(g["id"]), cm._plain(g.get("name"))) for g in groups], s["group"])):
        want = {w for p in said for w in words(p)}
        found.append([{"kind": kind, "ref": ref, "label": "" if ref else label} for ref, label in have
                      if want & set(words(label))])
    out = []
    for hits in found:
        if len(hits) == 1 and cm._ukey(hits[0]) not in taken:
            taken.add(cm._ukey(hits[0]))
            out.append(hits[0])
    return out


def _make(x: Dict[str, Any], flips: Dict[str, Any], name: str, roles: List[Dict[str, Any]], teams: List[str],
          groups: List[Dict[str, Any]], taken: set, church: str) -> Dict[str, Any]:
    """The batch part that makes a new copy of `x`, a draft. A role is made as
    ensure_library makes its row (its handles and the teams under it by the
    church's Serve card; its row's switches with this ready-made's flips, but
    the board's yes, which waits), answering to the church's own copy of the
    role its row names, else the senior's (create_role's rule)."""
    stamp = {"template_key": x["key"], "template_version": x["version"]}
    if x["kind"] == "department":
        return {"kind": "department", "id": None, "set": {
            "name": name or x["name"], "area": x["area"], "support_duty": x["support_duty"], "status": "draft",
            "units": _units(x, teams, groups, taken), **stamp}}
    title, under = name or x["title"], cr._team_match(x["teams"], teams)
    handles = cr._seed_handles(x, under)
    up = next((r for r in roles if x["reports"] and x["reports"] in (r.get("catalog_key"), r.get("key"))), None)
    return {"kind": "role", "id": None, "set": {
        "title": title, "job": x["job"], "definition": cr._fill(x["definition"], title, church, x["lead"] or "leader"),
        "covers": x["covers"], "handles": handles, "oversees_teams": under, **cr._catalog_switches(x, handles),
        **{k: v for k, v in flips.items() if k != "can_board_yes"}, **({"reports_to": str(up["id"])} if up else {}),
        "catalog_key": x["row"], **stamp}}


def _held(bid: str) -> List[Dict[str, Any]]:
    """The parts the church's waiting ready-made changes hold; a 503 when the read fails."""
    rows = cm._need(f"/church_map_changes?business_id=eq.{cm._q(bid)}&status=eq.pending&origin=eq.template"
                    "&select=parts&limit=50")
    return [p for r in rows for p in r.get("parts") or [] if p.get("after")]


def _unsaid(held: List[Dict[str, Any]], parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The parts no change from a ready-made already waits with: adopting the
    same thing again stages nothing twice."""
    import church_map_batch as batch
    return [p for p in parts if not any(
        h["kind"] == p["kind"] and h.get("id") == p["id"] and
        all(f in h["after"] and batch._same(f, h["after"][f], v) for f, v in p["after"].items()) for h in held)]


def adopt(biz: Dict[str, Any], kind: str, key: str, by: Any, *, role: str, tradition: str = "",
          name: str = "") -> Dict[str, Any]:
    """POST /church/map/templates/adopt (§2.4): the church's own copy of a
    ready-made. What it lacks is made as drafts (source 'template', with
    template_key and template_version), in one change (origin 'template')
    that Undo takes back out. What it would change on a live row (a flip an
    active role doesn't have, a shape's picks), and the board's yes on a new
    copy (money), wait as one more change for a yes: it never edits a live
    row. What the church already has is named and left alone, so adopting
    the same thing again makes nothing and logs nothing; `name` makes a
    second copy of a role or a department. A role keeps its row's title (the
    key names the tradition); `tradition` picks a department's or a shape's
    seats, else the church's own. The owner or an admin; an admin's money
    part waits for the owner, as every money change does to be made. {made,
    yours, change, waiting, said}."""
    import church_follow_up as cfu
    import church_map_batch as batch
    batch._open()
    batch._may(role)
    t = get(kind, key)
    if t is None:
        raise HTTPException(404, "That ready-made isn’t here")
    if tradition and tradition not in cr.TYPES:
        cm._bad("That isn’t one of the church types")
    name = cm._plain(name)[:80]
    if name and kind == "shape":
        cm._bad("Name a role or a ministry, not a whole church")
    bid = cm._bid(biz)
    st = cr.settings(bid)
    if st is None:
        raise HTTPException(503, cm.UNREAD)
    home = _trad(tradition or tradition_of(biz, st))
    roles, depts = _reads(biz)
    held = _held(bid)       # read before any draft is written: a failed read stops everything (#1728 review)
    if name and kind == "role" and any(_fold(r["title"]) == _fold(name) for r in roles):
        cm._bad(f"There’s already a role called {name}")
    things, now = _sort(t, home, roles, depts, name), batch._Now(biz)
    new = sorted(((x, f) for x, f, got in things if got is None), key=lambda xf: xf[0]["kind"] != "role")
    ops: List[Dict[str, Any]] = []
    if new:
        teams = cfu.teams(bid)
        if teams is None:
            raise HTTPException(503, cm.UNREAD)
        groups = cm._need(f"/groups?business_id=eq.{cm._q(bid)}&active=eq.true&select=id,name&limit=500")
        taken = {cm._ukey(u) for d in now.m.departments for u in d["units"]}
        ops = [_make(x, f, name if x is t else "", roles, teams, groups, taken, cm._plain(biz.get("name")))
               for x, f in new]
    said = f"Ready-made: {t.get('label') or t.get('name') or t['title']}"
    plan = batch._plan(now, ops, by, role, "template")
    parts = [p for _o, p in plan if p]
    more = {"said": said, "money": batch._money(parts)}     # never money: the board's yes waits
    batch._may(role, more["money"])
    results, err = batch._write(now, plan, by, role, "template")
    if err is not None:
        raise batch._failed(bid, parts, by, "template", err, **more)
    change = batch._log(bid, "applied", parts, by, "template", **more) if parts else None
    ids = {x["key"]: str(got["id"]) for x, _f, got in things if got is not None}
    ids.update({x["key"]: str(r["id"]) for (x, _f), r in zip(new, results)})
    # What waits for a yes, read with the new drafts in.
    now = batch._Now(biz)
    waits = [{"kind": "role", "id": ids[x["key"]], "set": w}
             for x, f, got in things for w in [_waiting(x, f, got)] if w]
    later = [p for _o, p in batch._plan(now, waits, by, role, "template") if p]
    if t["kind"] == "shape":
        picks = {f: list(dict.fromkeys(ids[SEATS[s][home]] for s in seats)) for f, seats in (
            ("pastor_yes_roles", t["pastor_yes"]), ("office_overseer_roles", t["office_overseer"]))}
        # Not checked now: a pick may be a draft this made, which goes live at launch before this is made.
        p = batch._part(now, {"kind": "settings", "id": bid, "set": picks}, now.get("settings", bid),
                        {"settings": {**now.m.settings, **picks}})
        later += [p] if p else []
    later = _unsaid(held, later)
    waiting = batch._log(bid, "pending", later, by, "template", said=said, money=batch._money(later)) if later else None
    if later and waiting is None:
        raise HTTPException(503, "The drafts are in, but what waits for your yes didn’t save. Add it again to finish.")
    made = [{"kind": op["kind"], "key": x["key"], "id": ids[x["key"]],
             "name": op["set"].get("title") or op["set"]["name"]} for (x, _f), op in zip(new, ops)]
    yours = [{"kind": x["kind"], "key": x["key"], "name": x.get("title") or x["name"], "id": str(got["id"]),
              "yours": got.get("title") or got.get("name"), "status": got.get("status")} for x, _f, got in things if got]
    if made:
        line = f"Added {len(made)} draft{'s' if len(made) > 1 else ''}: {', '.join(m['name'] for m in made)}."
    elif t["kind"] != "shape":
        line = f"{yours[0]['name']} is already yours" + (
            "." if _fold(yours[0]["yours"]) == _fold(yours[0]["name"]) else f", as {yours[0]['yours']}.")
    else:
        line = "Everything in it is already yours."
    if waiting:
        line += " What it would change on your live roles waits for your yes."
    return {"made": made, "yours": yours, "change": batch._brief(change), "waiting": batch._brief(waiting),
            "said": line}


_IDX: Dict[str, Tuple[str, set, set]] = {}

# ─── Pinned (python church_templates.py prints these, a changed one a version up) ──
VERSIONS: Dict[str, Tuple[int, str]] = {
    "pastor_deacons": (1, "fc729107013df37fad21e68a9cdcd195b938f79ec69768d83921ac5e61512224"),
    "pastor_elders": (1, "14c83d640855876b5d98d72218e020894499962764e1bb6e9d777b8dab86b98a"),
    "bishop_led": (1, "24de30329b1ff75ee30882d522c2da3bd513f1dea2441ecae946d2532014ec4d"),
    "elder_led": (1, "acdf513f9e57c7505d5fd569e5cf90dfe07524cae8807daa8772aca55888a637"),
    "multi_staff": (1, "2e02515f71bd1245507d065925cce6a1ec2b53fed89163d48ca9bf94845f6870"),
    "pastor_led": (1, "d6544c55d5994f0df83f46da1bdc7e07535083f5a0e1f07488064981c139ae26"),
    "worship": (1, "3802edce3434f22fcc174d518a58947873313a58961641f1e393a3af177fd019"),
    "media": (1, "73b4aa2e9c11bb64dec36f155b1e8381b50862947cda6a91a9b75b74f6c1853b"),
    "youth": (1, "8d958c35eeb97c3318eec287744f6aba8448e60d8f13fe7df8b45b25c06dedc1"),
    "children": (1, "aa5a446c7edf27514f74f9c6a784cfa1ec836c178e0908e754a1060eb37c408a"),
    "prayer": (1, "c9d5977a7511459c314029659c3b9f44f5c5676f455855ba5e72904611d91c01"),
    "care": (1, "fdc011afd9a3a315870df89a85c53c8a407baca8a3f2dceee08c64c962eae504"),
    "welcome": (1, "4b137013e52de185dc4de682d1a1e225c09e23b561107799b041d89633e60eb0"),
    "ushers": (1, "dd1096d1e705d4d0e6cef59f5b75db4a126b5d711ce289d5e048de21eed097ba"),
    "outreach": (1, "b4026b7debf6a5904224c24e05d7659c85a6ddee8c7a63ec111d525c05ee2ac6"),
    "groups": (1, "b3f5a5c97b600cf18e294c5e1abb0b5eddade7d64fd75608b92556fa52084eea"),
    "mens": (1, "dc7939547d318cd080dba1d9eca59e957c176be3a84d76634fda154fdf6f5928"),
    "womens": (1, "c53df216074271567d0800e8b4fe7c8df5dbfc7eb06f392809758fac05512955"),
    "missions": (1, "525284fb4000c3c8814ae2c7a911c0d19d234ad919422f09dc3e07fca3b01de5"),
    "facilities": (1, "8157cb76535d920e6ce6bdf516a19e95f4edc89b12d38aef48cf74312de4f996"),
    "nondenom.pastor": (1, "45b39f7b35982cb58fcb33d69cb7f4515aee0de70a2415f46c0ed1edb2b44f38"),
    "nondenom.executive_pastor": (1, "d1b11904a19442f5bef7fca702f8e3f1cf78d1b569647a97ed094fc81d8ef565"),
    "nondenom.associate_pastor": (1, "1895dd732b2b2dcf8fde3404aea8a113bd57258aeefc3a0a6a5efb8b13dcee88"),
    "nondenom.elders": (1, "160171b4e179e1cc2303a78a5265b9d4c471983df9f0c64fd4b63c85e633d214"),
    "nondenom.ministers": (1, "9e4a9b1f38112b948c3eff0d90a904fe1fcd4f2dec23531ebe0c84c7796e5181"),
    "nondenom.intercessor_leader": (1, "c1897d30b5b3986da7b6b35070b8ce912b98e2663380e9563c90429f06064595"),
    "nondenom.intercessors": (1, "ad0d584eae5c9f8e01c7247cbc01db25a42832436ba508dc373645cc4475961c"),
    "nondenom.deacons": (1, "11e41bc9632d7b2508c9984196185d7a0966db08a34ea7836628ee110db0abf1"),
    "nondenom.care_team": (1, "804d8e2d2f0571a632755e840a2fcff593950a77e42383830e7eb6b219ccaa76"),
    "nondenom.worship_leader": (1, "8a87ad0e021afb470c3b27fc2bca1ecdab6388fff292950424c283901c01ee8b"),
    "nondenom.youth_pastor": (1, "0f734dcef48043380392b11b7438621f5b7fc4f20000eb988a8f30cfe31cdb51"),
    "nondenom.childrens_director": (1, "743268c19b8c4bfadaeed0072efd5291aba3774147d6f5ed5bc8df05e7943491"),
    "nondenom.team_leader": (1, "df009462d7147ee5efaabaeac0b95683874c8d32422cb0c5b636251a70fc679b"),
    "nondenom.welcome_lead": (1, "ec7f14bb939a35695a96deb5f3eb969c04a07105d32e1b8659ae3d6c9d32c329"),
    "nondenom.class_teachers": (1, "b9d010845756992b216926ff4243c9d552bfe6c36c39ca450089da786691c488"),
    "nondenom.administrator": (1, "dd94a583de2b8c727f60e8a52c31efae669e67ad92deea92de953d6ac9d44119"),
    "nondenom.treasurer": (1, "322648bf422b423a3817871a69825f09ff74d95d60206cd4a931396919a995b0"),
    "baptist.pastor": (1, "978d2a6349eb956a219b901ca1633b92eff3c3403bf44182eb2ff68cc9c5cf73"),
    "baptist.associate_ministers": (1, "3a24ee02cc761fcdbddd9734b8dd310eb6f57d8cecb430cd6404852ee79cff70"),
    "baptist.deacons": (1, "08d5069058c6e50ca6a8bdf47666693f4d08a44bec0986d7955402efa7cb3fe0"),
    "baptist.deaconesses": (1, "36dfc706042a700731608948f9dfab4a9e53eb2481afae8aadd3c41bfeefd67c"),
    "baptist.mothers_board": (1, "094eeb3175db6e14efd4a804ce19ea7e8040c50eee3b85a3d64cdedd6a637d29"),
    "baptist.intercessor_leader": (1, "59c4dabfa958485b9145546b671e14984bbbb8335de63835cefa8ec2160d3e34"),
    "baptist.intercessors": (1, "31056ba0e498daca93691e6b8e76f8aa04390d79e919478a1508563e17c6205c"),
    "baptist.minister_of_music": (1, "d356e071ca0875c2a6b92edc291ae2432673ba112bde8a974b628f2f182eb4e2"),
    "baptist.youth_minister": (1, "d9dd48b01079f25168d01e57c07127359b011872ffd9c8fa347ab993c376bd5e"),
    "baptist.team_leader": (1, "b452c0a334665c72d989270311c5ca9f9e854b3ec1dc34b1c9137603b8325341"),
    "baptist.usher_board": (1, "9af9d0117280f89fa7b19cccb5e9ff3127b26f609eee729b606b08186e505f89"),
    "baptist.welcome_lead": (1, "ba2781c6aa6ed522340ad7ffe89cd039fa95502264a4dc3d1d0864ab4d14e7a9"),
    "baptist.sunday_school": (1, "46f6e8629465806fea8c270a5f9c4a267dc9db2e8610e1aba4b17a4c69ccbcce"),
    "baptist.trustees": (1, "40232b394bad8daace4d93bdda1a674402b8ffbb8549dd62f31e9da27a07addd"),
    "baptist.church_clerk": (1, "ba3cfbb7ff27d1fa8fc2dffc775c9e5df8ace19afcbc6b7a4226bc1220682acb"),
    "baptist.treasurer": (1, "36a91e08c143ffee7feae8fdfc30db2103844e8028f590193bf9386a1d2eb599"),
    "cogic.pastor": (1, "c79a5c4d43f712912fe38f9d835dbc5edf3100b79a64a83d855b73f7245a7ef4"),
    "cogic.elders": (1, "cfaa171dda42bd8edba2fbc8c76b87f68c4bb431defacc80ed642a85ed86db87"),
    "cogic.ministers": (1, "bd624875fe6c99a5acc7ba7e38a9cb8bdd162dae1b24442ae178aaa6b822cc08"),
    "cogic.church_mother": (1, "0e61de13e677f07d94b4cfff7f321e7b60f5fe7aaeef1b0afdd486a73d5866e9"),
    "cogic.missionaries": (1, "9f578d19ce069b578d7925eceaffc6a90d65dfef758887372f341e36f622bc80"),
    "cogic.evangelists": (1, "8a9f45d477a3c6b463d8c3cf299b800ca76e880bb7c7a78e012f5809106f223e"),
    "cogic.deacons": (1, "08491d0ba3cc7014573587470d95349290b2d0f1e01617135d13c131961fcf75"),
    "cogic.intercessor_leader": (1, "3139b16efb84eb2b86873149212700c20e772bfb186ea69767a11ae6e727cf26"),
    "cogic.intercessors": (1, "8ec2d134619bb25f7249f6778644d64a8f90422ffe75c4157271fde64e4b25f2"),
    "cogic.armor_bearers": (1, "4919c140310f1224d0db7b470c6754c3cfe30e86b887992fb3e32ad2d64c8a39"),
    "cogic.worship_leader": (1, "89d925e30bb4acf9b9921ff35af7d64987ed8c8513bb4ba1d3db53a4cd10b29d"),
    "cogic.ypww_president": (1, "0aab51670be590dc2bcc175d0f27e8a9578dca7b7987ddcc999c2620020bbaab"),
    "cogic.team_leader": (1, "c4b9b743ae77d19a290688a210bced6ab0fe69bce56d2d1f98bc61e6f8658378"),
    "cogic.sunday_school": (1, "b6df71391b54f120d0429ba1b299af6190db11f49d487d1f0727d829aedd712f"),
    "cogic.treasurer": (1, "5c8f25f0fbc2fa081f1657a538a6755c5a39f6fc363b0eaea27ddfa6c0df2fb1"),
    "ame.pastor": (1, "c1561840e05fe899780d123ccd6f923b9d84e51f8087ee1026447158ed6e7215"),
    "ame.associate_ministers": (1, "5a09459b99592058bf7a0fc11f59cb8d85cbd186fd6733e4378f49acb4687c2f"),
    "ame.stewards": (1, "c5bd1b72cc8cda0916d1e4faee0fb636c8ffae20cd875758d8c829e1b6dc4edd"),
    "ame.stewardesses": (1, "a6f36cff6d06216f4c2aacbf15a056d6c0ab57137ad4589ed0b8025619d90855"),
    "ame.class_leaders": (1, "f6c77caf973c6df63b693de2f4480aaf4d8d0306e287bcdd4459b52d31afa896"),
    "ame.intercessor_leader": (1, "4dac455ae4c00e15bd179d2a87a00bf8214d5039bae3c8346d43b8a576bdd4b5"),
    "ame.intercessors": (1, "6a14698dff56d019632209737a2cccc9d1969d1cd84d89908299a583efa6c434"),
    "ame.missionary_society": (1, "4da14fbe9d5e7aa745a41b8b44663ce76d37874adeee814aa82e9d605f98e987"),
    "ame.minister_of_music": (1, "0e8e73263f6bf3ac9e5d5a1f86112ab6a641b9ecf6471f82b39b43a08a942a87"),
    "ame.ypd_director": (1, "4748c3e1a2776adb3e04f001cc3a838e4831fc334dfa1a12798127bdb8f8f104"),
    "ame.team_leader": (1, "8f3aa2a3dcb2944039b23037979d9e26f81cf144619101a074b4e743e090fecd"),
    "ame.welcome_lead": (1, "e37b23ba8ed2bb71b436527a90c61b4092826f2ca315f690ceb8b3b8a3d5d458"),
    "ame.church_school": (1, "9855452589fbb05a06a1b336b5afb6639f23504b040082e84d834716da7bbc7e"),
    "ame.trustees": (1, "5a0387e983df6e4f315428cd9dafc3c8a020e2005b0a13aa538032f3e1210290"),
    "presby.pastor": (1, "5168d2e61d5a2616be352d64627eaadb5feec108d5771c644db07edc356d53a5"),
    "presby.associate_pastor": (1, "31d040f3fbdb3124503ffdd3d7d8cd436f73f4bb503d7c122e6ee923079d1e5f"),
    "presby.ruling_elders": (1, "21c0dd9e8807fd1128ff3b2fd821ecacb1ca4ec2602104e2c5c21242e54243ee"),
    "presby.deacons": (1, "ba325a55e0c4e6f1e24c06f51dd28cedad079f85fc9a7275d8dee6a1e9176da7"),
    "presby.intercessor_leader": (1, "2661480924ab710f55e8f9816d31dd4bd5269d2afde5d9b73797aa2b069c5ae9"),
    "presby.intercessors": (1, "91ce4b5f90c1dabe0e15c5c30100a94ac25f44221d202d4510c9cfaf96d75517"),
    "presby.christian_ed": (1, "f8859c3a9367f0db357190e505899538a90597ef8440731339bb761ab1c5eeda"),
    "presby.music_director": (1, "f763bdaa48edd0d12f7846e817b94dd92d7940f1b47ce4c47c2667b1f460a811"),
    "presby.team_leader": (1, "0f48364bac37191a0857d03549376ba40a438036f512dc710e6b70535ebd0245"),
    "presby.welcome_lead": (1, "e8d1db0bedb41d1285e39dc10fe91befc363eedb1cee849393a37efa139b2473"),
    "presby.clerk_of_session": (1, "fb28e4095a7934716c44e8f76899db9d0544003d9235c09396842d29f872de1a"),
    "presby.treasurer": (1, "71c7a399f8adac96ad6ba649a94944821ffbbabf1cc3d4994bbd08736457bdb4"),
    "coc.pastor": (1, "d681b1fcbd3a83698406d81b726f9523cca3b04339c3f885f0bd3cff17218535"),
    "coc.preaching_minister": (1, "22cc7a7018dc5737f5ee49bcacfde28d1df1b8a7fbe51369cbb140e00444e677"),
    "coc.youth_minister": (1, "001c576b33ba4f7b1a808ac651191a7fa4517c874b09d4cc7a255726b1404731"),
    "coc.deacons": (1, "2f0794ca1dca00cbf8c2a8dbaf35fab48705b1663e3411f0fc012ad9be8525f0"),
    "coc.intercessor_leader": (1, "6701684fb08da7309da1128e9b5fb8250564512255e5b346ae13fad3f7d4da9c"),
    "coc.intercessors": (1, "abba5e508a27680f4469a5313ba77dc5146b317c9839e94b91e73a82f4548760"),
    "coc.song_leaders": (1, "752fd4c3ad6fe290c1207dcae2bcbd97504d38a36ed45ebe8d7d376a6bb17313"),
    "coc.team_leader": (1, "5479deb664d79748718b3aa63ec6ca4022fbb4f57b9941c34f853bceb1ab9122"),
    "coc.welcome_lead": (1, "0035623c6aba6a2690cfc1c73294ff7798bc0ed86f5214b71bb9916bc7f1b0e8"),
    "coc.bible_class_teachers": (1, "bcd85b88bfb7092df3489a618ae7dda303fb661b9425ea5dc8b7f37c6a58b70b"),
    "liturgical.pastor": (1, "b83e39126dca6727fcdb7abbbb2be63e431a2a7a7e67dabd99ffcad3782549d3"),
    "liturgical.associate_rector": (1, "4e4c87bf2616ae0b354308f2a90e791335fef2c054b317668193a1d69f0e3189"),
    "liturgical.deacon_ordained": (1, "acbe6fee69b2fc47361bbb00af441567284a96614925af8863a3b5b0b77fa06b"),
    "liturgical.eucharistic_ministers": (1, "848206c9eb9aab1e4fb0fcf6f338c0a5556b8887567a21ae7e3f1260ce8c2126"),
    "liturgical.intercessor_leader": (1, "63afbd8928a30f8cb5a27ceae57ff8fb27ca4e0af3042dff1717a22b3b5d0263"),
    "liturgical.intercessors": (1, "94f57b67fde517181d06c6c1c1226122720bc80c0b236021f69febe54fc80c85"),
    "liturgical.religious_ed": (1, "588778e4bd685a0dc66d64c9deee6c60a3fb241e2d78be99a70b8950b47757bc"),
    "liturgical.music_director": (1, "0643fd2562248041adc12595ec0110d29d330d20b59b07ae740b85d729aba36f"),
    "liturgical.altar_guild": (1, "1dc9ec9866b0151da0717223faea0b7b0cb5b9a09943bf827ff7a348c831e2e3"),
    "liturgical.team_leader": (1, "e40eca99a61eca48c174c8ad655ec4e8475888ebe87ec84a19e6227493332e89"),
    "liturgical.ocia": (1, "da252ea05ebfddd86b23e07a8c6c2721e7753478b0e41d021f2c0f3798b58242"),
    "liturgical.vestry": (1, "68d16549b6f3095bf8cfcc6dfb57e330cbe96901f8506d911de5f5476d5b4e28"),
    "other.pastor": (1, "0df335f9debab98e0ec26d9d1da9f6b049aca702b5319a13313be0f77bb35375"),
    "other.intercessor_leader": (1, "f69aafc5fa0581d33950c5a2c35f68f7510348d1b98fb5905cf501a206b46bba"),
    "other.intercessors": (1, "74d4ed4413012276dd4b03092d90ac6dae2c6706d7d53e1b03d4cfc2e9f181ee"),
    "other.team_leader": (1, "cfb95ef931fbb662b084b0d38854a2db8ccfcff0fb1ce7422cf109e92f3b3cbc"),
    "other.welcome_lead": (1, "7aa319de6abbbde41d0c877605dd0d2315e940021b6d62ae338679bbb7ff40ee"),
    "any.media_lead": (1, "55565bca4047baa4c4d1d0cb41654015170606ef69098f4a518065e87cc103ae"),
    "any.facilities_lead": (1, "2f8dbad9edf573af8ce8c7a15240657739ab34343c38289412b5270f34914509"),
    "any.outreach_lead": (1, "3934eb4ac2dd9722bfae5cab4b1839f88a3f39148840efafa485ba6b267350d3"),
    "any.mens_lead": (1, "56a4f37bd1ab0435b64736cda94598f4a67ab0e32c6beae63a52f29236fadd98"),
    "any.womens_lead": (1, "fbef8491b5009ffb65b84032825913595c33dc7e129f96ad0edf995e16c9f0f6"),
    "any.missions_lead": (1, "6886e827c2a20fee0cc245541cb873d7aaeb2e6cc7e5825b3b2c6e7ed63c2bb3"),
}

for _k, _v in ALL.items():
    _v["version"] = VERSIONS.get(_k, (1, ""))[0]
    _IDX[_k] = _index(_v)
assert len(ALL) == len(SHAPES) + len(DEPARTMENTS) + len(ROLES), "a key is used twice across kinds"
del _t, _lead, _row, _words, _k, _v

if __name__ == "__main__":
    for _key, _tmpl in ALL.items():
        _ver, _sha = VERSIONS.get(_key, (0, ""))
        _now = digest(_tmpl)
        print(f'    "{_key}": ({_ver if _sha == _now else _ver + 1}, "{_now}"),')
