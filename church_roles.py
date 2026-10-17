"""church_roles.py — the role library: every role is a church's own title on a job.

Kevin, 2026-10-17: "build functions with definitions and details that helps
chief know the role and what information each role should get. every church
and their catagory … lead pastor, Elders, Assosicate Pastor, Deacons,
Ministers, Youth Pastor/Youth Director … and also a way for people to create
thier own roles and the wiring is the same." Design canvas
BKNqVVNiyxfAGAa7UAVWUC; "build it".

    a JOB ........... the wiring, fixed here (JOBS): what a role may be handed
                      (STREAMS), what it sees, what it never sees
    a ROLE .......... church_role_defs: the church's title on a job, the
                      definition Chief reads (and the invitation shows), what
                      it is handed, who it answers to, the teams under it
    a CHURCH TYPE ... TYPES: the titles a tradition uses, each on its job.
                      Chief guesses the type from the church's name and
                      website (guess_type); the owner can change it.
    the CHAIN ....... reports_to: a late step goes to the person a leader
                      answers to, then one more step up (chain_above)

A role's `key` is what a holder row (church_leader_roles.role) and a
follow-up (church_follow_ups.leader_role) carry. The four keys of the first
version are kept: pastor (the senior role), baptism_minister, welcome_lead,
team_leader.

Every table is server-only; this module and church_follow_up.py are the
doors, always scoped by business_id, through the service role.
"""
from __future__ import annotations

import html as _html
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from fastapi import HTTPException

import sb_clients

logger = logging.getLogger(__name__)


# ─── Streams: what a role can be handed ───────────────────────────────

STREAMS: Dict[str, str] = {
    "leftover": "Anything no one else holds",
    "pastor_ask": "Asks to talk with a pastor, or for pastoral care",
    "care_need": "Care needs on a card: someone sick, in the hospital, grieving, or needing a meal",
    "baptism": "Baptism cards",
    "prayer_shared": "Prayer requests shared with the prayer team",
    "prayer_passed": "Prayer requests passed on by the role they answer to",
    "serve": "Serve with us sign-ups for their team",
    "visit": "Plan your visit cards",
    "connect": "Connect cards",
}
# A ministry or welcome role is handed a team's sign-ups only when the team
# has no leader of its own.
SERVE_OVERSEER_LABEL = "Serve with us sign-ups for the teams under them, when a team has no leader"

SEES_OPTIONS: Dict[str, str] = {
    "reach": "How to reach them, when they asked for a call",
}


# ─── Jobs: the wiring ─────────────────────────────────────────────────

JOB_ORDER = ("senior", "pastoral", "prayer", "care", "ministry", "team", "welcome", "teach", "kids", "office")

JOBS: Dict[str, Dict[str, Any]] = {
    "senior": {
        "label": "Senior pastor",
        "does": "Over the whole church. Gets anything no one else holds, and is the top of every chain.",
        "gets": "Anything no one else holds, and the top of every chain.",
        "sees": "Everything in follow-up and prayer.",
        "never": "Nothing is hidden.",
        "where": "This app and the Lead tab in the member app.",
        "allowed": ["leftover", "pastor_ask", "care_need", "baptism", "prayer_shared"],
        "defaults": ["leftover", "pastor_ask"],
        "locked": ["leftover"],
        "sees_options": [],
        "definition": "{title} shepherds the whole church and oversees every leader. Anything no one else holds "
                      "comes to them, and they are the top of every chain.",
    },
    "pastoral": {
        "label": "Pastoral",
        "does": "Pastoral care, “talk with a pastor” requests, baptisms, and prayer. Prayer always sits under a pastor.",
        "gets": "Requests to talk with a pastor, pastoral care, and baptism cards when the role takes them.",
        "sees": "The people handed to them, what they wrote, how to reach them, and every note.",
        "never": "Giving.",
        "where": "The Lead tab in the member app.",
        "allowed": ["pastor_ask", "care_need", "baptism", "prayer_shared"],
        "defaults": ["pastor_ask"],
        "locked": [],
        "sees_options": [],
        "definition": "{title} shares the pastor’s care of the church: talks with anyone who asks for a pastor, "
                      "and cares for members in need.",
    },
    "prayer": {
        "label": "Prayer",
        "does": "Prayer requests that people agreed to share with the prayer team. Pastors see every one.",
        "gets": "Prayer requests people agreed to share with the prayer team.",
        "sees": "The request and the person’s first name; how to reach them when they asked for a call.",
        "never": "Giving, other cards, pastors-only notes and requests.",
        "where": "The Lead tab in the member app.",
        "allowed": ["prayer_shared", "prayer_passed"],
        "defaults": ["prayer_shared"],
        "locked": [],
        "sees_options": ["reach"],
        "definition": "{title} prays over the prayer requests people shared with the prayer team within a day, "
                      "and tells a pastor at once about anything urgent.",
    },
    "care": {
        "label": "Care",
        "does": "Care needs: visits, meals, the sick and the grieving.",
        "gets": "Care needs on a card: someone sick, in the hospital, grieving, or needing a meal.",
        "sees": "The people handed to them, how to reach them, and the notes on them.",
        "never": "Giving, prayer kept for the pastors, other people’s cards.",
        "where": "The Lead tab in the member app.",
        "allowed": ["care_need", "pastor_ask"],
        "defaults": ["care_need"],
        "locked": [],
        "sees_options": [],
        "definition": "{title} serves the church’s care needs: visits the sick and the grieving, and sees that "
                      "meals reach those who need them.",
    },
    "ministry": {
        "label": "Ministry lead",
        "does": "Over a ministry and its teams. Its teams’ late steps come to them first. Kids and youth need a background check.",
        "gets": "Sign-ups for the teams under them when a team has no leader, and their teams’ late steps.",
        "sees": "Their ministry’s people and teams.",
        "never": "Giving, prayer, people outside their ministry.",
        "where": "The Lead tab in the member app.",
        "allowed": ["serve"],
        "defaults": ["serve"],
        "locked": [],
        "sees_options": [],
        "definition": "{title} leads a ministry and the teams under it, and makes sure everyone who signs up to "
                      "serve there is welcomed onto a team.",
    },
    "team": {
        "label": "Team leader",
        "does": "Serve with us sign-ups for their team.",
        "gets": "Serve with us sign-ups for their team.",
        "sees": "Their team and its sign-ups.",
        "never": "Giving, prayer, anyone off their team.",
        "where": "The Lead tab in the member app.",
        "allowed": ["serve"],
        "defaults": ["serve"],
        "locked": [],
        "sees_options": [],
        "definition": "{title} leads one team: welcomes each new sign-up and has them serving beside them within "
                      "three weeks.",
    },
    "welcome": {
        "label": "Welcome",
        "does": "Plan your visit and connect cards, and every first-time guest.",
        "gets": "Plan your visit and connect cards, and first-time guests.",
        "sees": "The guests handed to them and what they wrote.",
        "never": "Giving, prayer.",
        "where": "The Lead tab in the member app.",
        "allowed": ["visit", "connect", "serve"],
        "defaults": ["visit", "connect"],
        "locked": [],
        "sees_options": [],
        "definition": "{title} makes sure every guest is greeted, and called that week.",
    },
    "teach": {
        "label": "Teachers & group leaders",
        "does": "Who is in their class or group, and who finished. Group leaders can start a live meeting when allowed.",
        "gets": "Who is in their class or group, and who finished.",
        "sees": "Their class or group.",
        "never": "Giving, prayer.",
        "where": "Their class and group pages in the member app.",
        "allowed": [],
        "defaults": [],
        "locked": [],
        "sees_options": [],
        "definition": "{title} teaches a class or leads a group, and walks each person through it to the end.",
    },
    "kids": {
        "label": "Kids & youth workers",
        "does": "Check children in and release them to an approved adult. Background check, and 18 or older.",
        "gets": "Their rooms on Sunday: who is checked in and who may pick them up.",
        "sees": "Children in their rooms; medical notes when needed.",
        "never": "Giving, prayer, adults’ records.",
        "where": "Kids check-in in the member app.",
        "allowed": [],
        "defaults": [],
        "locked": [],
        "sees_options": [],
        "definition": "{title} checks children in and out of their rooms, and releases a child only to an "
                      "approved adult.",
    },
    "office": {
        "label": "Office",
        "does": "Records and money, worked from this app with an office login. Never in the member app.",
        "gets": "The parts of this app their office login opens: records, giving, the calendar.",
        "sees": "What their office login allows.",
        "never": "Anything in the member app’s Lead tab.",
        "where": "This app, with an office login.",
        "allowed": [],
        "defaults": [],
        "locked": [],
        "sees_options": [],
        "definition": "{title} keeps the church’s records and money, from the office.",
    },
}


# ─── Church types: the titles each tradition uses ─────────────────────

def _r(key: str, title: str, job: str, note: str = "", *, handles: Optional[List[str]] = None,
       reports: str = "", covers: str = "church", definition: str = "", teams: str = "") -> Dict[str, Any]:
    return {"key": key, "title": title, "job": job, "note": note, "handles": handles,
            "reports": reports, "covers": covers, "definition": definition, "teams": teams}


_INTERCESSOR_DEF = ("Leads {church} in prayer. Receives the prayer requests people agreed to share with the prayer "
                    "team, prays over each one within a day, and sends a short note back when the person asked for "
                    "one. Gathers the intercessors to pray before services. Tells a pastor at once about anything "
                    "urgent.")
_INTERCESSORS_DEF = "Pray over the prayer requests the {lead} passes to them, within a day."

# Team keywords a ministry or welcome role takes under it when the library
# is first filled (teams = a regex over the church's own team names).
_YOUTH, _KIDS, _WORSHIP = r"youth|teen|student", r"kid|child|nursery", r"worship|praise|music|choir"
_WELCOME = r"welcome|hospitality|usher|greet|guest"


def _prayer_rows(lead_title: str = "Intercessor leader", team_title: str = "Intercessors") -> List[Dict[str, Any]]:
    return [_r("intercessor_leader", lead_title, "prayer", "Oversees prayer under the pastor.",
               handles=["prayer_shared"], definition=_INTERCESSOR_DEF),
            _r("intercessors", team_title, "prayer", handles=["prayer_passed"], reports="intercessor_leader",
               definition=_INTERCESSORS_DEF)]


TYPES: Dict[str, Dict[str, Any]] = {
    "nondenom": {
        "label": "Non-denominational",
        "about": "Usually led by a Lead Pastor with elders beside them, and staff pastors over the ministries.",
        "rows": [
            _r("pastor", "Lead Pastor", "senior"),
            _r("executive_pastor", "Executive Pastor", "pastoral", "Often also given an office login to run staff and operations.", handles=[]),
            _r("associate_pastor", "Associate Pastor", "pastoral", handles=["pastor_ask", "care_need"],
               definition="{title} shares the pastor’s care of the church; the ministry leads answer to them."),
            _r("elders", "Elders", "pastoral", "Pray for and oversee the church with the pastor.", handles=["pastor_ask"],
               definition="The {title} pray for the church and watch over it with the pastor."),
            _r("ministers", "Ministers", "pastoral", handles=["baptism"],
               definition="{title} preach, teach and serve at the pastor’s side. Baptism cards go to them."),
            *_prayer_rows(),
            _r("deacons", "Deacons", "care", definition="{title} serve the church’s practical and care needs."),
            _r("care_team", "Care team", "care", reports="deacons",
               definition="The {title} visit, call and bring meals when someone is sick or grieving."),
            _r("worship_leader", "Worship Leader", "ministry", "Or Worship Pastor.", reports="associate_pastor", teams=_WORSHIP,
               definition="{title} leads Praise and Worship and the teams on the platform."),
            _r("youth_pastor", "Youth Pastor", "ministry", "Background check.", reports="associate_pastor", teams=_YOUTH,
               definition="{title} leads the youth ministry and its leaders."),
            _r("childrens_director", "Children’s Director", "ministry", "Or Kids Pastor. Background check.",
               reports="associate_pastor", teams=_KIDS,
               definition="{title} leads the kids ministry and its check-in leaders."),
            _r("team_leader", "Team leader", "team", covers="team", reports="associate_pastor"),
            _r("welcome_lead", "Welcome Team lead", "welcome", "Also called Connections or Guest Services lead.",
               reports="associate_pastor", teams=_WELCOME),
            _r("class_teachers", "Class teachers", "teach", reports="associate_pastor",
               definition="{title} teach the church’s classes, and see who finished."),
            _r("administrator", "Administrator", "office", definition="{title} runs the calendar, the records and the website."),
            _r("treasurer", "Treasurer", "office", definition="{title} keeps the giving records and pays the bills."),
        ],
    },
    "baptist": {
        "label": "Baptist",
        "about": "The congregation governs; the Pastor leads with a board of deacons, and trustees keep the property and money.",
        "rows": [
            _r("pastor", "Pastor", "senior"),
            _r("associate_ministers", "Associate Ministers", "pastoral", handles=["pastor_ask", "baptism"]),
            _r("deacons", "Deacon Board", "care", "In many Baptist churches deacons also help govern.",
               definition="The {title} serve the church’s care needs and stand with the pastor."),
            _r("deaconesses", "Deaconesses", "care"),
            _r("mothers_board", "Mothers’ Board", "care", "Counsel and prayer for the church."),
            *_prayer_rows("Prayer ministry leader", "Prayer warriors"),
            _r("minister_of_music", "Minister of Music", "ministry", teams=_WORSHIP),
            _r("youth_minister", "Youth Minister", "ministry", "Background check.", teams=_YOUTH),
            _r("team_leader", "Team leader", "team", covers="team"),
            _r("usher_board", "Usher Board president", "team", teams=_WELCOME),
            _r("welcome_lead", "Hospitality ministry lead", "welcome", teams=_WELCOME),
            _r("sunday_school", "Sunday School Superintendent", "teach"),
            _r("trustees", "Trustees", "office", "Property and money."),
            _r("church_clerk", "Church Clerk", "office", "Membership records."),
            _r("treasurer", "Financial Secretary, Treasurer", "office"),
        ],
    },
    "cogic": {
        "label": "COGIC & Pentecostal",
        "about": "A Pastor (often also a Bishop or Superintendent) with ordained Elders, licensed Ministers, and a "
                 "strong prayer and mothers’ tradition.",
        "rows": [
            _r("pastor", "Pastor", "senior", "Often also a Bishop or Superintendent."),
            _r("elders", "Elders", "pastoral", "Ordained ministers.", handles=["pastor_ask", "baptism"]),
            _r("ministers", "Ministers", "pastoral", "Licensed ministers.", handles=["pastor_ask"]),
            _r("church_mother", "Church Mother", "care", "Counsel and prayer for the church.",
               definition="The {title} is a woman of mature faith who counsels the church’s women and young "
                          "families, and stands with the pastor in caring for the flock."),
            _r("missionaries", "Missionaries", "pastoral", "Women who teach, visit and evangelize.", handles=["care_need"]),
            _r("evangelists", "Evangelists", "welcome", "Reach and follow up new people."),
            _r("deacons", "Deacons", "care"),
            *_prayer_rows("Intercessor leader", "Intercessors"),
            _r("armor_bearers", "Armor Bearers", "team", "Serve the pastor directly.", handles=[]),
            _r("worship_leader", "Praise and Worship leader", "ministry", teams=_WORSHIP),
            _r("ypww_president", "YPWW president", "ministry", "Youth. Background check.", teams=_YOUTH),
            _r("team_leader", "Team leader", "team", covers="team"),
            _r("sunday_school", "Sunday School Superintendent", "teach"),
            _r("treasurer", "Treasurer", "office"),
        ],
    },
    "ame": {
        "label": "AME & Methodist",
        "about": "The Bishop appoints the Pastor. Stewards, Stewardesses and Class Leaders carry the church’s care; "
                 "Trustees keep the property.",
        "rows": [
            _r("pastor", "Pastor", "senior", "Appointed by the Bishop."),
            _r("associate_ministers", "Associate Ministers", "pastoral", "And Local Preachers.", handles=["pastor_ask", "baptism"]),
            _r("stewards", "Stewards", "pastoral", "Help the pastor with the church’s spiritual life.", handles=["pastor_ask"]),
            _r("stewardesses", "Stewardesses", "care", "Prepare communion and care for members."),
            _r("class_leaders", "Class Leaders", "care", "Each watches over a class of members.",
               definition="Each of the {title} watches over a class of members: calls them, visits them, and "
                          "tells the pastor who needs care."),
            *_prayer_rows("Prayer leader", "Prayer band"),
            _r("missionary_society", "Missionary Society president", "care"),
            _r("minister_of_music", "Minister of Music", "ministry", teams=_WORSHIP),
            _r("ypd_director", "YPD director", "ministry", "Youth. Background check.", teams=_YOUTH),
            _r("team_leader", "Team leader", "team", covers="team"),
            _r("welcome_lead", "Hospitality lead", "welcome", teams=_WELCOME),
            _r("church_school", "Church School Superintendent", "teach"),
            _r("trustees", "Trustees", "office"),
        ],
    },
    "presby": {
        "label": "Presbyterian",
        "about": "Elders govern together as the Session; deacons lead care and mercy.",
        "rows": [
            _r("pastor", "Pastor (Teaching Elder)", "senior"),
            _r("associate_pastor", "Associate Pastor", "pastoral", handles=["pastor_ask", "baptism"]),
            _r("ruling_elders", "Ruling Elders (the Session)", "pastoral", handles=["pastor_ask"]),
            _r("deacons", "Deacons", "care", "Mercy and practical care."),
            *_prayer_rows("Prayer leader", "Prayer team"),
            _r("christian_ed", "Director of Christian Education", "ministry", reports="associate_pastor"),
            _r("music_director", "Music Director", "ministry", teams=_WORSHIP),
            _r("team_leader", "Team leader", "team", covers="team"),
            _r("welcome_lead", "Welcome Team lead", "welcome", teams=_WELCOME),
            _r("clerk_of_session", "Clerk of Session", "office"),
            _r("treasurer", "Treasurer", "office"),
        ],
    },
    "coc": {
        "label": "Church of Christ",
        "about": "Elders (shepherds) oversee together; there is no “pastor” title. A preaching minister preaches, "
                 "and deacons lead ministries.",
        "rows": [
            _r("pastor", "Elders (Shepherds)", "senior", "Several people share the top of the chain.",
               definition="The {title} oversee the congregation together, and every leader answers to them."),
            _r("preaching_minister", "Preaching Minister", "pastoral", handles=["pastor_ask", "baptism"]),
            _r("youth_minister", "Youth Minister", "ministry", "Background check.", teams=_YOUTH),
            _r("deacons", "Deacons", "ministry", "Each leads a ministry: benevolence, building, education.",
               definition="Each of the {title} leads one of the congregation’s ministries."),
            *_prayer_rows("Prayer leader", "Prayer team"),
            _r("song_leaders", "Song leaders", "team", handles=[]),
            _r("team_leader", "Team leader", "team", covers="team"),
            _r("welcome_lead", "Welcome Team lead", "welcome", teams=_WELCOME),
            _r("bible_class_teachers", "Bible class teachers", "teach"),
        ],
    },
    "liturgical": {
        "label": "Episcopal, Lutheran & Catholic",
        "about": "A Rector, Pastor or Priest with ordained deacons; a vestry or council governs alongside.",
        "rows": [
            _r("pastor", "Rector, Pastor or Priest", "senior"),
            _r("associate_rector", "Associate Rector, Curate or Parochial Vicar", "pastoral", handles=["pastor_ask", "baptism"]),
            _r("deacon_ordained", "Deacon (ordained)", "pastoral", handles=["pastor_ask"]),
            _r("eucharistic_ministers", "Lay Eucharistic Ministers", "care", "Bring communion to the homebound."),
            *_prayer_rows("Prayer chain leader", "Prayer chain"),
            _r("religious_ed", "Director of Religious Education", "ministry"),
            _r("music_director", "Music Director or Organist", "ministry", teams=_WORSHIP),
            _r("altar_guild", "Altar Guild", "team", handles=[]),
            _r("team_leader", "Team leader", "team", covers="team"),
            _r("ocia", "OCIA or Inquirers’ class coordinator", "welcome", "Walks newcomers into membership.", teams=_WELCOME),
            _r("vestry", "Wardens and Vestry, Church or Parish Council", "office"),
        ],
    },
    "other": {
        "label": "Something else",
        "about": "Seventh-day Adventist, an apostolic network, a house church, or your own way: start from the jobs "
                 "and name every role yourself. Chief understands each one by its job.",
        "rows": [
            _r("pastor", "Senior pastor", "senior", "Over the whole church."),
            *_prayer_rows("Prayer leader", "Prayer team"),
            _r("team_leader", "Team leader", "team", covers="team"),
            _r("welcome_lead", "Welcome Team lead", "welcome", teams=_WELCOME),
        ],
    },
}
TYPE_ORDER = ("nondenom", "baptist", "cogic", "ame", "presby", "coc", "liturgical", "other")

# The four keys the first version gave out, as roles, for a church that
# already uses them under a type that names them differently.
LEGACY: Dict[str, Dict[str, Any]] = {
    "pastor": _r("pastor", "Lead Pastor", "senior"),
    "baptism_minister": _r("baptism_minister", "Baptism minister", "pastoral", handles=["baptism"],
                           definition="{title} walks everyone who asks to be baptized through it, from the first "
                                      "talk to the Sunday they are baptized."),
    "welcome_lead": _r("welcome_lead", "Welcome Team lead", "welcome", teams=_WELCOME),
    "team_leader": _r("team_leader", "Team leader", "team", covers="team"),
}


# ─── Chief's guess at the church type ─────────────────────────────────

_TYPE_WORDS: List[Tuple[str, str, str]] = [
    ("cogic", r"\bcogic\b|church of god in christ|pentecostal|apostolic|holiness|assembl(y|ies) of god|full gospel", "Pentecostal"),
    ("ame", r"\bame\b|\ba\.m\.e\.|african methodist|\bcme\b|methodist|wesleyan", "Methodist"),
    ("baptist", r"\bbaptist\b", "Baptist"),
    ("presby", r"presbyterian|\breformed\b", "Presbyterian"),
    ("coc", r"church of christ\b|churches of christ", "Church of Christ"),
    ("liturgical", r"episcopal|anglican|lutheran|catholic|\bparish\b|orthodox", "a liturgical tradition"),
    ("other", r"adventist|seventh.day", "Adventist"),
]


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text or "")
    return _html.unescape(re.sub(r"<[^>]+>", " ", text))


def guess_type(name: str, texts: Iterable[str]) -> Tuple[str, str]:
    """(type key, why) from the church's name first, then its website.
    A name settles it ("Greater Mt. Zion Missionary Baptist Church"); the
    website only when the name says nothing; nothing at all is
    non-denominational, which is most churches that name no tradition."""
    nm = (name or "").casefold()
    for key, rx, said in _TYPE_WORDS:
        if re.search(rx, nm):
            return key, f"Your name says {said}."
    words: Dict[str, int] = {}
    for t in texts:
        low = _strip_html(str(t or ""))[:200000].casefold()
        for key, rx, _said in _TYPE_WORDS:
            n = len(re.findall(rx, low))
            if n:
                words[key] = words.get(key, 0) + n
    if words:
        key = max(words, key=lambda k: words[k])
        if words[key] >= 2:
            said = next(s for k, _r_, s in _TYPE_WORDS if k == key)
            return key, f"Your website speaks of {said} more than once."
    return "nondenom", ("No denomination in your name, your website or its About page, so Chief loaded the titles "
                        "non-denominational churches use.")


# ─── Small helpers ────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _q(value: Any) -> str:
    return quote(str(value), safe="")


def _plain(value: Any) -> str:
    return " ".join(str(value or "").split())


def _uid(value: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} id isn't valid")


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", _plain(title).casefold().replace("’", "").replace("'", "")).strip("_")
    return (s or "role")[:32].strip("_") or "role"


def definition_for(job: str, title: str, church: str = "", lead: str = "") -> str:
    tmpl = JOBS.get(job, JOBS["pastoral"])["definition"]
    return tmpl.format(title=_plain(title) or "This role", church=church or "the church", lead=lead or "leader")


def _fill(text: str, title: str, church: str, lead: str = "Intercessor leader") -> str:
    return (text or "").format(title=_plain(title), church=church or "the church", lead=lead)


def clean_handles(job: str, handles: Optional[Iterable[str]]) -> List[str]:
    """What a role may be handed: only its job's streams, and the locked
    ones always (a senior role always takes what no one else holds)."""
    spec = JOBS[job]
    want = list(spec["defaults"]) if handles is None else [str(h) for h in handles]
    out = [h for h in spec["allowed"] if h in want or h in spec["locked"]]
    return out


def clean_sees(job: str, sees: Optional[Iterable[str]]) -> List[str]:
    spec = JOBS[job]
    want = list(spec["sees_options"]) if sees is None else [str(s) for s in sees]
    return [s for s in spec["sees_options"] if s in want]


# ─── Reads ────────────────────────────────────────────────────────────

_DEF_SELECT = ("id,key,title,job,definition,covers,reports_to,oversees_teams,handles,sees,term_months,needs_class,"
               "status,source,catalog_key,sort,created_at,updated_at")


def defs(business_id: str, *, with_drafts: bool = False) -> Optional[List[Dict[str, Any]]]:
    """The church's roles (active; drafts too when asked), in job order.
    None when the read failed: a caller deciding who gets a person must
    stop rather than read 'no roles'."""
    st = "status=in.(active,draft)" if with_drafts else "status=eq.active"
    rows = _rows(f"/church_role_defs?business_id=eq.{_q(business_id)}&{st}&select={_DEF_SELECT}"
                 "&order=sort.asc,created_at.asc&limit=300")
    if rows is None:
        return None
    for r in rows:
        r["id"] = str(r["id"])
        r["reports_to"] = str(r["reports_to"]) if r.get("reports_to") else None
        r["oversees_teams"] = list(r.get("oversees_teams") or [])
        r["handles"] = list(r.get("handles") or [])
        r["sees"] = list(r.get("sees") or [])
    rank = {j: n for n, j in enumerate(JOB_ORDER)}
    return sorted(rows, key=lambda r: (rank.get(r["job"], 99), int(r.get("sort") or 0)))


def settings(business_id: str) -> Optional[Dict[str, Any]]:
    rows = _rows(f"/church_role_settings?business_id=eq.{_q(business_id)}&select=*&limit=1")
    if rows is None:
        return None
    return rows[0] if rows else {}


def by_key(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {r["key"]: r for r in rows}


def title_of(key: str, rows: Iterable[Dict[str, Any]]) -> str:
    d = by_key(rows).get(key)
    if d:
        return d["title"]
    leg = LEGACY.get(key)
    return leg["title"] if leg else (key or "Leader").replace("_", " ").capitalize()


# ─── Filling the library the first time ───────────────────────────────

def _site_texts(business_id: str) -> List[str]:
    rows = _rows(f"/business_sites?business_id=eq.{_q(business_id)}&select=html_content,site_config&limit=3") or []
    out: List[str] = []
    for r in rows:
        out.append(str(r.get("html_content") or "")[:200000])
        cfg = r.get("site_config")
        if isinstance(cfg, dict):
            out.append(" ".join(str(cfg.get(k) or "") for k in ("title", "tagline", "about", "description")))
    return out


def _team_match(rx: str, team_names: List[str]) -> List[str]:
    if not rx:
        return []
    return [t for t in team_names if re.search(rx, t.casefold())]


def _seed_handles(row: Dict[str, Any], teams_under: List[str]) -> List[str]:
    """What a title is handed when it first comes in: its job's defaults
    (or the title's own), and, for a role with teams under it, those teams'
    sign-ups when a team has no leader."""
    out = clean_handles(row["job"], row["handles"])
    if teams_under and "serve" in JOBS[row["job"]]["allowed"] and "serve" not in out:
        out = clean_handles(row["job"], out + ["serve"])
    return out


def ensure_library(business: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The church's role settings, filling its library the first time:
    Chief's guess at its type, that type's titles (each on its job, with a
    definition and its place in the chain), and any role key it already
    gave someone. Safe to call again: a filled church is left alone, and a
    race only ever adds a role once (unique key per church). None when a
    read failed."""
    biz = str(business["id"])
    st = settings(biz)
    if st is None:
        return None
    if st.get("seeded_at"):
        return st
    church = _plain(business.get("name")) or "the church"
    have = defs(biz, with_drafts=True)
    held = _rows(f"/church_leader_roles?business_id=eq.{_q(biz)}&select=role&limit=500")
    if have is None or held is None:
        return None
    gkey, why = guess_type(church, _site_texts(biz))
    key = st.get("church_type") or gkey
    rows = list(TYPES[key]["rows"])
    present = {r["key"] for r in rows}
    for k in sorted({str(h["role"]) for h in held}):
        if k not in present and k in LEGACY:
            rows.append(LEGACY[k])
            present.add(k)
    import church_follow_up as cfu
    team_names = cfu.teams(biz) or []
    existing = by_key(have)
    created: Dict[str, str] = {k: v["id"] for k, v in existing.items()}
    for n, row in enumerate(rows):
        if row["key"] in existing:
            continue
        made = sb_clients.sb_post_as_service(
            "/church_role_defs?on_conflict=business_id,key", {
                "business_id": biz, "key": row["key"], "title": row["title"], "job": row["job"],
                "definition": _fill(row["definition"] or JOBS[row["job"]]["definition"], row["title"], church,
                                    next((x["title"] for x in rows if x["key"] == "intercessor_leader"), "leader")),
                "covers": row["covers"],
                "handles": _seed_handles(row, _team_match(row["teams"], team_names)),
                "sees": clean_sees(row["job"], None), "oversees_teams": _team_match(row["teams"], team_names),
                "status": "active", "source": "legacy" if row is LEGACY.get(row["key"]) else "catalog",
                "catalog_key": row["key"], "sort": n * 10,
            }, prefer="resolution=ignore-duplicates,return=representation")
        if isinstance(made, list) and made:
            created[row["key"]] = str(made[0]["id"])
    # The chain: each title to the one it answers to (the senior role when
    # it names none), now that every id is known.
    top = created.get("pastor")
    for row in rows:
        rid = created.get(row["key"])
        if not rid or row["key"] in existing or row["job"] == "senior":
            continue
        up = created.get(row["reports"]) if row["reports"] else None
        up = up or top
        if up and up != rid:
            sb_clients.sb_patch_as_service(f"/church_role_defs?id=eq.{_q(rid)}&business_id=eq.{_q(biz)}",
                                           {"reports_to": up, "updated_at": _iso(_now())})
    out = sb_clients.sb_post_as_service("/church_role_settings?on_conflict=business_id", {
        "business_id": biz, "church_type": key, "guessed_type": gkey, "guess_reason": why[:300],
        "set_by": st.get("set_by") or "chief", "set_at": st.get("set_at") or _iso(_now()),
        "seeded_at": _iso(_now()), "updated_at": _iso(_now()),
    }, prefer="resolution=merge-duplicates,return=representation")
    return out[0] if isinstance(out, list) and out else {"church_type": key, "guessed_type": gkey,
                                                          "guess_reason": why, "set_by": "chief"}


# ─── The chain ────────────────────────────────────────────────────────

def overseer(role: Optional[Dict[str, Any]], all_defs: List[Dict[str, Any]], team: str = "") -> Optional[Dict[str, Any]]:
    """The role a holder of `role` answers to. A team's leader answers to
    the ministry or welcome role that has the team under it, else to whoever
    the team leader role answers to."""
    if not role:
        return None
    ids = {d["id"]: d for d in all_defs}
    if team and role.get("covers") == "team":
        t = team.casefold()
        for d in all_defs:
            if d["id"] != role["id"] and any(x.casefold() == t for x in d.get("oversees_teams") or []):
                return d
    return ids.get(role.get("reports_to") or "")


def chain_above(role: Optional[Dict[str, Any]], all_defs: List[Dict[str, Any]], holders: Dict[str, List[Dict[str, Any]]],
                *, team: str = "", skip: Iterable[str] = ()) -> List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    """Each role above `role` that someone holds, nearest first, as (role,
    its active holders). An empty role is passed over; the walk stops at a
    loop or the top. When nothing above is held, the senior roles' holders
    are the top of every chain."""
    skip = set(skip)
    out: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    seen = {role["id"]} if role else set()
    cur = overseer(role, all_defs, team)
    while cur and cur["id"] not in seen:
        seen.add(cur["id"])
        people = [h for h in holders.get(cur["key"], []) if h["contact_id"] not in skip]
        if people:
            out.append((cur, people))
        cur = overseer(cur, all_defs)
    if not out or out[-1][0].get("job") != "senior":
        for d in all_defs:
            if d["job"] == "senior" and d["id"] not in {x[0]["id"] for x in out}:
                people = [h for h in holders.get(d["key"], []) if h["contact_id"] not in skip]
                if people:
                    out.append((d, people))
                    break
    return out


def active_holders(holder_rows: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for h in holder_rows:
        if h.get("status") == "active":
            out.setdefault(str(h["role"]), []).append(h)
    return out


def _descendants(role_id: str, all_defs: List[Dict[str, Any]]) -> set:
    below, frontier = set(), {role_id}
    while frontier:
        nxt = {d["id"] for d in all_defs if d.get("reports_to") in frontier and d["id"] not in below}
        below |= nxt
        frontier = nxt
    return below


# ─── Writes ───────────────────────────────────────────────────────────

_FIELDS = ("title", "job", "definition", "covers", "reports_to", "oversees_teams", "handles", "sees",
           "term_months", "needs_class", "status")


def _clean(biz: str, body: Dict[str, Any], current: Optional[Dict[str, Any]], all_defs: List[Dict[str, Any]],
           team_names: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    job = str(body.get("job") or (current or {}).get("job") or "")
    if job not in JOBS:
        raise HTTPException(400, "Pick the job this role does")
    if current and current.get("job") == "senior" and job != "senior" and \
            sum(1 for d in all_defs if d["job"] == "senior") <= 1:
        raise HTTPException(400, "Every church needs a senior role at the top. Make another one first.")
    if "title" in body or not current:
        title = _plain(body.get("title"))[:80]
        if not title:
            raise HTTPException(400, "Give the role a name")
        out["title"] = title
    if "job" in body or not current:
        out["job"] = job
    if "definition" in body or not current:
        out["definition"] = _plain(body.get("definition"))[:1200] if "definition" in body else ""
    if "covers" in body or not current:
        cov = str(body.get("covers") or ("team" if job == "team" else "church"))
        out["covers"] = cov if cov in ("church", "team", "age", "class") else "church"
    if "reports_to" in body:
        up = body.get("reports_to")
        if up:
            up = _uid(up, "role")
            known = {d["id"] for d in all_defs}
            if up not in known:
                raise HTTPException(400, "That role isn’t one of yours")
            if current and (up == current["id"] or up in _descendants(current["id"], all_defs)):
                raise HTTPException(400, "A role can’t answer to itself or to someone who answers to it")
        out["reports_to"] = up or None
    if "oversees_teams" in body:
        want = [_plain(t) for t in (body.get("oversees_teams") or []) if _plain(t)]
        known = {t.casefold(): t for t in team_names}
        out["oversees_teams"] = [known[t.casefold()] for t in want if t.casefold() in known][:40]
    if "handles" in body or "job" in body or not current:
        out["handles"] = clean_handles(job, body.get("handles") if "handles" in body else
                                       ((current or {}).get("handles") if current and job == current.get("job") else None))
    if "sees" in body or "job" in body or not current:
        out["sees"] = clean_sees(job, body.get("sees") if "sees" in body else None)
    if "term_months" in body:
        tm = body.get("term_months")
        out["term_months"] = int(tm) if tm not in (None, "", 0) and 1 <= int(tm) <= 120 else None
    if "needs_class" in body:
        nc = body.get("needs_class")
        out["needs_class"] = _uid(nc, "class") if nc else None
    if "status" in body:
        s = str(body.get("status") or "active")
        out["status"] = s if s in ("active", "draft") else "active"
    return out


def create_role(business: Dict[str, Any], body: Dict[str, Any], *, by_user: str = "",
                source: str = "custom") -> Dict[str, Any]:
    biz = str(business["id"])
    all_defs = defs(biz, with_drafts=True)
    if all_defs is None:
        raise HTTPException(503, "Your roles couldn’t be checked. Try again in a moment.")
    import church_follow_up as cfu
    patch = _clean(biz, body, None, all_defs, cfu.teams(biz) or [])
    if not patch.get("definition"):
        patch["definition"] = definition_for(patch["job"], patch["title"], _plain(business.get("name")))
    archived = _rows(f"/church_role_defs?business_id=eq.{_q(biz)}&status=eq.archived&select=key&limit=300")
    if archived is None:
        raise HTTPException(503, "Your roles couldn’t be checked. Try again in a moment.")
    taken = {d["key"] for d in all_defs} | {r["key"] for r in archived}
    base = slug(patch["title"])
    key, n = base, 2
    while key in taken:
        key = f"{base[:36]}_{n}"
        n += 1
    if "reports_to" not in patch and patch["job"] != "senior":
        top = next((d for d in all_defs if d["job"] == "senior" and d["status"] == "active"), None)
        patch["reports_to"] = top["id"] if top else None
    rows = sb_clients.sb_post_as_service("/church_role_defs", {
        "business_id": biz, "key": key, "source": source, "created_by": by_user or None,
        "sort": 1000 + len(all_defs) * 10, "status": patch.pop("status", "active"), **patch})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That role didn’t save. Try again.")
    return rows[0]


def update_role(business_id: str, role_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    biz, rid = str(business_id), _uid(role_id, "role")
    all_defs = defs(biz, with_drafts=True)
    if all_defs is None:
        raise HTTPException(503, "Your roles couldn’t be checked. Try again in a moment.")
    cur = next((d for d in all_defs if d["id"] == rid), None)
    if not cur:
        raise HTTPException(404, "That role isn’t here")
    import church_follow_up as cfu
    patch = _clean(biz, {k: v for k, v in body.items() if k in _FIELDS}, cur, all_defs, cfu.teams(biz) or [])
    if patch.get("covers") and patch["covers"] != cur.get("covers"):
        held = _rows(f"/church_leader_roles?business_id=eq.{_q(biz)}&role=eq.{_q(cur['key'])}&status=neq.declined&select=id&limit=1")
        if held is None or held:
            raise HTTPException(400, "Take the people out of this role before changing what it covers")
    if not patch:
        return cur
    rows = sb_clients.sb_patch_as_service(f"/church_role_defs?id=eq.{_q(rid)}&business_id=eq.{_q(biz)}",
                                          {**patch, "updated_at": _iso(_now())})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn’t save. Nothing was changed — try again.")
    return rows[0]


def archive_role(business_id: str, role_id: str) -> Dict[str, Any]:
    """A role with people in it stays until they're taken out (so nobody
    is left leading a role that no longer exists). A draft goes outright."""
    biz, rid = str(business_id), _uid(role_id, "role")
    rows = _rows(f"/church_role_defs?id=eq.{_q(rid)}&business_id=eq.{_q(biz)}&select=id,key,job,status&limit=1")
    if rows is None:
        raise HTTPException(503, "That couldn’t be checked. Try again in a moment.")
    if not rows or rows[0]["status"] == "archived":
        raise HTTPException(404, "That role isn’t here")
    d = rows[0]
    held = _rows(f"/church_leader_roles?business_id=eq.{_q(biz)}&role=eq.{_q(d['key'])}&status=neq.declined&select=id&limit=1")
    if held is None:
        raise HTTPException(503, "That couldn’t be checked. Try again in a moment.")
    if held:
        raise HTTPException(400, "Take the people out of this role first")
    if d["job"] == "senior" and d["status"] == "active":
        others = _rows(f"/church_role_defs?business_id=eq.{_q(biz)}&job=eq.senior&status=eq.active&id=neq.{_q(rid)}&select=id&limit=1")
        if not others:
            raise HTTPException(400, "Every church needs a senior role at the top")
    if d["status"] == "draft":
        ok = sb_clients.sb_delete_as_service(f"/church_role_defs?id=eq.{_q(rid)}&business_id=eq.{_q(biz)}")
        if not ok:
            raise HTTPException(503, "That didn’t save. Try again.")
        return {"deleted": True}
    # Roles that answered to it now answer to whoever it answered to. A
    # read or a write that failed stops the archive: the roles under it
    # must never be cut off the chain by a blip.
    up = _rows(f"/church_role_defs?id=eq.{_q(rid)}&business_id=eq.{_q(biz)}&select=reports_to&limit=1")
    if not up:
        raise HTTPException(503, "That couldn’t be checked. Try again in a moment.")
    moved = sb_clients.sb_patch_as_service(f"/church_role_defs?business_id=eq.{_q(biz)}&reports_to=eq.{_q(rid)}",
                                           {"reports_to": up[0].get("reports_to"), "updated_at": _iso(_now())})
    if not isinstance(moved, list):
        raise HTTPException(503, "That didn’t save. Nothing was changed — try again.")
    out = sb_clients.sb_patch_as_service(f"/church_role_defs?id=eq.{_q(rid)}&business_id=eq.{_q(biz)}",
                                         {"status": "archived", "updated_at": _iso(_now())})
    if not isinstance(out, list) or not out:
        raise HTTPException(503, "That didn’t save. Try again.")
    return {"archived": True}


def set_type(business: Dict[str, Any], type_key: str, add: Iterable[str] = (), *, by_user: str = "") -> Dict[str, Any]:
    """The owner names the church's type, and may add that type's titles
    they pick. Nothing is taken from anyone: a role already in the library
    (by key) is left as it is."""
    biz = str(business["id"])
    if type_key not in TYPES:
        raise HTTPException(400, "That isn’t one of the church types")
    st = ensure_library(business)
    if st is None:
        raise HTTPException(503, "Your roles couldn’t be checked. Try again in a moment.")
    all_defs = defs(biz, with_drafts=True)
    if all_defs is None:
        raise HTTPException(503, "Your roles couldn’t be checked. Try again in a moment.")
    have = by_key(all_defs)
    church = _plain(business.get("name"))
    import church_follow_up as cfu
    team_names = cfu.teams(biz) or []
    rows = {r["key"]: r for r in TYPES[type_key]["rows"]}
    added = 0
    top = next((d for d in all_defs if d["job"] == "senior"), None)
    for k in add:
        row = rows.get(str(k))
        if not row or row["key"] in have:
            continue
        up = have.get(row["reports"]) if row["reports"] else None
        made = sb_clients.sb_post_as_service("/church_role_defs?on_conflict=business_id,key", {
            "business_id": biz, "key": row["key"], "title": row["title"], "job": row["job"],
            "definition": _fill(row["definition"] or JOBS[row["job"]]["definition"], row["title"], church),
            "covers": row["covers"],
            "handles": _seed_handles(row, _team_match(row["teams"], team_names)),
            "sees": clean_sees(row["job"], None), "oversees_teams": _team_match(row["teams"], team_names),
            "reports_to": (up or top or {}).get("id") if row["job"] != "senior" else None,
            "status": "active", "source": "catalog", "catalog_key": row["key"], "created_by": by_user or None,
            "sort": 500 + added * 10,
        }, prefer="resolution=ignore-duplicates,return=representation")
        if isinstance(made, list) and made:
            added += 1
            have[row["key"]] = made[0]
    out = sb_clients.sb_post_as_service("/church_role_settings?on_conflict=business_id", {
        "business_id": biz, "church_type": type_key, "set_by": "owner", "set_at": _iso(_now()),
        "updated_at": _iso(_now())}, prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(out, list) or not out:
        raise HTTPException(503, "That didn’t save. Try again.")
    return {"settings": out[0], "added": added}


# ─── The office's page ────────────────────────────────────────────────

def _view(d: Dict[str, Any], all_defs: List[Dict[str, Any]], holders: List[Dict[str, Any]],
          classes: Dict[str, str]) -> Dict[str, Any]:
    ids = {x["id"]: x for x in all_defs}
    up = ids.get(d.get("reports_to") or "")
    created = d.get("created_at")
    return {
        "id": d["id"], "key": d["key"], "title": d["title"], "job": d["job"], "definition": d.get("definition") or "",
        "covers": d.get("covers") or "church", "reports_to": d.get("reports_to"),
        "reports_to_title": up["title"] if up else None, "oversees_teams": d.get("oversees_teams") or [],
        "handles": d.get("handles") or [], "sees": d.get("sees") or [], "term_months": d.get("term_months"),
        "needs_class": str(d["needs_class"]) if d.get("needs_class") else "",
        "needs_class_title": classes.get(str(d.get("needs_class") or ""), ""),
        "status": d.get("status") or "active", "source": d.get("source") or "custom",
        "is_new": d["key"] in ("intercessor_leader", "intercessors") or d.get("source") in ("custom", "chief"),
        "created_at": created,
        "holders": [{k: h.get(k) for k in ("id", "contact_id", "name", "email", "phone", "status", "scope",
                                           "invited_at", "answered_at", "term_ends_at")}
                    for h in holders if h.get("role") == d["key"]],
    }


def _groups(biz: str) -> List[Dict[str, Any]]:
    groups = _rows(f"/groups?business_id=eq.{_q(biz)}&active=is.true&select=id,name&order=name.asc&limit=200") or []
    if not groups:
        return []
    leads = _rows(f"/group_members?business_id=eq.{_q(biz)}&role=eq.leader&select=group_id,contact_id&limit=1000") or []
    import church_follow_up as cfu
    people = cfu._contacts(biz, {str(x["contact_id"]) for x in leads}) or {}
    out = []
    for g in groups:
        names = [people.get(str(x["contact_id"]), {}).get("name") or "" for x in leads if str(x["group_id"]) == str(g["id"])]
        out.append({"id": str(g["id"]), "name": g.get("name") or "Group", "leaders": [n for n in names if n]})
    return out


def _kids(biz: str) -> List[Dict[str, Any]]:
    rows = _rows(f"/space_leaders?business_id=eq.{_q(biz)}&select=contact_id,space,background_check_on&limit=500") or []
    import church_follow_up as cfu
    people = cfu._contacts(biz, {str(r["contact_id"]) for r in rows}) or {}
    return [{"name": people.get(str(r["contact_id"]), {}).get("name") or "Someone", "space": r.get("space") or "kids",
             "background_check_on": r.get("background_check_on")} for r in rows]


def _office(biz: str) -> List[Dict[str, Any]]:
    rows = _rows(f"/business_users?business_id=eq.{_q(biz)}&status=eq.active&select=invited_email,role&limit=200") or []
    return [{"email": r.get("invited_email") or "", "role": r.get("role") or ""} for r in rows]


def _classes(biz: str) -> List[Dict[str, Any]]:
    rows = _rows(f"/academy_courses?business_id=eq.{_q(biz)}&status=neq.archived&select=id,title&order=title.asc&limit=200") or []
    return [{"id": str(r["id"]), "title": _plain(r.get("title")) or "Class"} for r in rows]


def library(business: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Everything the Leaders & roles page shows. None when a read failed."""
    import church_follow_up as cfu
    biz = str(business["id"])
    st = ensure_library(business)
    if st is None:
        return None
    all_defs = defs(biz, with_drafts=True)
    holders = cfu.roles(biz)
    team_names = cfu.teams(biz)
    if all_defs is None or holders is None or team_names is None:
        return None
    classes = _classes(biz)
    cmap = {c["id"]: c["title"] for c in classes}
    keys = {d["key"] for d in all_defs}
    tkey = st.get("church_type") or st.get("guessed_type") or "nondenom"
    return {
        "church_type": {"key": tkey, "label": TYPES.get(tkey, TYPES["nondenom"])["label"],
                        "guessed": st.get("guessed_type") or tkey, "reason": st.get("guess_reason") or "",
                        "set_by": st.get("set_by") or "chief"},
        "jobs": {k: dict(JOBS[k]) for k in JOB_ORDER},
        "job_order": list(JOB_ORDER),
        "streams": dict(STREAMS, serve_overseer=SERVE_OVERSEER_LABEL),
        "sees_options": SEES_OPTIONS,
        "roles": [_view(d, all_defs, holders, cmap) for d in all_defs],
        "teams": team_names,
        "groups": _groups(biz),
        "kids_leaders": _kids(biz),
        "office": _office(biz),
        "classes": classes,
        "paths": cfu.PATHS,
        "late_ladder": [{"days": dd, "level": lvl, "kind": k} for dd, lvl, k in cfu.LATE_LADDER],
        "types": [{"key": k, "label": TYPES[k]["label"], "about": TYPES[k]["about"],
                   "rows": [{"key": r["key"], "title": r["title"], "job": r["job"], "note": r["note"],
                             "in_library": r["key"] in keys} for r in TYPES[k]["rows"]]} for k in TYPE_ORDER],
        "type_order": list(TYPE_ORDER),
    }


# ─── What Chief reads ─────────────────────────────────────────────────

def chief_lines(business: Dict[str, Any]) -> Optional[List[str]]:
    """The roles as Chief reads them: each title, its job, who holds it,
    who it answers to, what it is handed, and its definition. Names of
    leaders only; never a prayer request, a card's answers or giving."""
    import church_follow_up as cfu
    biz = str(business["id"])
    # A read: it never fills the library (that happens when the office
    # opens Leaders & roles, or a card first comes in).
    st = settings(biz)
    all_defs = defs(biz)
    holders = cfu.roles(biz)
    team_names = cfu.teams(biz)
    if st is None or all_defs is None or holders is None or team_names is None:
        return None
    all_defs = cfu._effective_defs(all_defs, holders)
    if not all_defs:
        return ["The church hasn't set up its roles yet: no one holds a role, so every card goes to the office. "
                "The owner sets them up on Operate → Leaders & roles."]
    tkey = st.get("church_type") or "nondenom"
    ids = {d["id"]: d for d in all_defs}
    lines = [f"Church type: {TYPES.get(tkey, TYPES['nondenom'])['label']}"
             + (" (Chief's guess; the owner hasn't confirmed it)" if st.get("set_by") != "owner" else "") + ".",
             "Roles (each is the church's title on a job; a late step goes to the role it answers to, then one more step up):"]
    for d in all_defs:
        mine = [h for h in holders if h["role"] == d["key"]]
        lead = [h["name"] + (f" ({h['scope']})" if h.get("scope") else "") for h in mine if h["status"] == "active"]
        asked = [h["name"] for h in mine if h["status"] == "invited"]
        up = ids.get(d.get("reports_to") or "")
        gets = "; ".join(STREAMS[s] for s in d.get("handles") or [] if s in STREAMS) or "nothing on its own (the office hands them people)"
        who = ", ".join(lead) if lead else "no one yet"
        lines.append(f"- {d['title']} [job: {JOBS[d['job']]['label']}] held by {who}"
                     + (f"; asked, not yet answered: {', '.join(asked)}" if asked else "")
                     + (f"; answers to {up['title']}" if up else "")
                     + (f"; teams under it: {', '.join(d['oversees_teams'])}" if d.get("oversees_teams") else "")
                     + f". Handed: {gets}. Definition: {d.get('definition') or ''}")
    led = {h["scope"].casefold() for h in holders if h["role"] == "team_leader" and h["status"] == "active" and h.get("scope")}
    if team_names:
        lines.append("Teams (from the Serve with us card): " + "; ".join(
            f"{t} ({'has a leader' if t.casefold() in led else 'no leader: sign-ups go up the chain'})" for t in team_names))
    lines.append("Prayer requests reach a member who leads only when the person agreed to share them with the "
                 "prayer team; requests kept for the pastors, and anything about someone in danger, abuse or a "
                 "death, stay with the pastor. Never repeat a prayer request's words.")
    return lines


def chief_draft(business: Dict[str, Any], title: str, job: str = "", definition: str = "") -> Dict[str, Any]:
    """Chief drafts a role the owner asked for. A draft hands nobody
    anything until the owner saves it on Leaders & roles."""
    title = _plain(title)[:80]
    if not title:
        raise HTTPException(400, "Name the role")
    if job not in JOBS:
        job = job_for_title(title)
    st = ensure_library(business)
    if st is None:
        raise HTTPException(503, "Your roles couldn’t be checked. Try again in a moment.")
    return create_role(business, {"title": title, "job": job, "definition": definition, "status": "draft"},
                       source="chief")


def job_for_title(title: str) -> str:
    """The job a title most likely does, from every tradition's titles,
    then from words in it. Chief's first guess; the owner can change it."""
    t = _plain(title).casefold()
    for k in TYPE_ORDER:
        for r in TYPES[k]["rows"]:
            if r["title"].casefold() == t:
                return r["job"]
    for rx, job in ((r"pastor|bishop|rector|priest|shepherd", "senior" if re.search(r"\b(lead|senior)\b", t) else "pastoral"),
                    (r"elder|minister|chaplain|steward\b|evangel", "pastoral"),
                    (r"interces|prayer", "prayer"),
                    (r"mother|deacon|care|nurse|benevolen|visit", "care"),
                    (r"youth|children|kids|worship|music|director|ministry", "ministry"),
                    (r"usher|greet|welcome|hospitality|connect|guest", "welcome"),
                    (r"teach|class|school|group", "teach"),
                    (r"trustee|treasur|clerk|secretar|admin|finance", "office"),
                    (r"team|leader|captain|armor", "team")):
        if re.search(rx, t):
            return job
    return "care"
