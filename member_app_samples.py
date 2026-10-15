"""
member_app_samples.py — sample content for the owner's preview of the
member app.

Kevin, 2026-10-14: "even though things are not filled because we haven't
made anything, I still want to show a better view, because if people
don't have a clue what they want but want to see the app layout, we need
to have something in line." So in Preview as a member (Settings → Member
page), each spot the church hasn't filled yet shows a sample in the real
layout, tagged Sample, with where to add the real thing.

ONLY the preview: member_portal.serve swaps these in when the session is
the owner's preview (sess["preview"]) and the church's own list is
EMPTY (a failed read stays a failed read). A member never sees a sample,
and anything the church has added replaces its sample. Every item carries
"sample": True so the renderers tag it; the preview already refuses every
write, so tapping a sample's button saves nothing.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

# Where the owner adds each thing, in the app's own words.
WHERE = {
    "events": "Add your services and events in Operate, This week, and the next one shows here.",
    "sermons": "Post a sermon in Grow, Reach, Sermons, and it takes this spot.",
    "groups": "Add groups in Operate, People, Groups, and members find and join them here.",
    "week": "A member's own events and groups show here once they say they're coming or join one.",
    "plan": "Choose a Bible reading plan in Settings, Member page, and members read along here.",
}

# Stable ids (the member app only opens ids shaped like these).
_EV = ("5a000000-0000-4000-8000-0000000000e1", "5a000000-0000-4000-8000-0000000000e2",
       "5a000000-0000-4000-8000-0000000000e3")
_GR = ("5a000000-0000-4000-8000-0000000000a1", "5a000000-0000-4000-8000-0000000000a2",
       "5a000000-0000-4000-8000-0000000000a3", "5a000000-0000-4000-8000-0000000000a4")
_SE = ("5a000000-0000-4000-8000-0000000000c1", "5a000000-0000-4000-8000-0000000000c2",
       "5a000000-0000-4000-8000-0000000000c3")
_SM = ("5a000000-0000-4000-8000-0000000000d1", "5a000000-0000-4000-8000-0000000000d2",
       "5a000000-0000-4000-8000-0000000000d3", "5a000000-0000-4000-8000-0000000000d4",
       "5a000000-0000-4000-8000-0000000000d5")


def fill(found: Any, kind: str, preview: bool) -> Any:
    """What the page shows: the church's own list, or — in the owner's
    preview, and only when that list read fine and is EMPTY — the samples.
    A failed read (None) is never dressed up as samples."""
    if not preview:
        return found
    if kind == "occasions" and found == []:
        return occasions()
    if kind == "groups" and isinstance(found, dict) and not found.get("mine") and not found.get("open"):
        return groups()
    if kind == "library" and isinstance(found, dict) and not found.get("sermons"):
        return library()
    return found


def is_sample(item: Any) -> bool:
    return isinstance(item, dict) and bool(item.get("sample"))


def _next(weekday: int, today: date) -> date:
    """The next given weekday (Mon=0), today counted when it matches."""
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def _occasion(eid: str, title: str, d: date, where: str, attending: int, mine=None) -> Dict[str, Any]:
    return {"entry_id": eid, "module_id": "sample", "title": title, "date": d.isoformat(),
            "date_label": f"{d.strftime('%A, %B')} {d.day}", "location": where, "capacity": None,
            "attending": attending, "spots_left": None, "full": False, "occasion_noun": "event",
            "roles": [], "mine": mine, "sample": True}


def occasions(today: Optional[date] = None) -> List[Dict[str, Any]]:
    today = today or date.today()
    sunday = _next(6, today)
    out = [_occasion(_EV[0], "Sunday Worship", sunday, "Sanctuary", 38),
           _occasion(_EV[1], "Prayer Night", _next(2, today + timedelta(days=1)), "Sanctuary", 14,
                     mine={"status": "yes", "role": None}),
           _occasion(_EV[2], "Community Food Drive", _next(5, today + timedelta(days=1)), "Fellowship Hall", 22)]
    out.sort(key=lambda o: o["date"])
    # Home leads with the next service, as a real church's Sunday would.
    out.sort(key=lambda o: o["entry_id"] != _EV[0])
    return out


def groups() -> Dict[str, List[Dict[str, Any]]]:
    def g(i, name, kind, meets, where, about, leader, role=None):
        item = {"id": _GR[i], "name": name, "kind": kind, "about": about, "meets": meets, "location": where,
                "leaders": [leader], "full": False, "sample": True}
        if role:
            item.update({"role": role, "host": False, "youth": False, "live": None, "chat_on": False})
        return item
    return {"mine": [g(0, "Tuesday Night Group", "Small group", "Tuesdays 7 pm", "Room 4",
                       "A study, a meal and real friends.", "Marcus", role="member")],
            "open": [g(1, "Newcomers Class", "Class", "Sundays 9:45 am", "Room 2",
                       "Four weeks to meet the pastors and find your place.", "Ana"),
                     g(2, "Worship Team", "Serving team", "Thursdays 6 pm", "Sanctuary",
                       "Singers and players, every level.", "Tasha"),
                     g(3, "Young Adults", "Small group", "Mondays 7 pm", "Coffee shop",
                       "Ages 18 to 30. Dinner and a study.", "Jordan")]}


def library(today: Optional[date] = None) -> Dict[str, List[Dict[str, Any]]]:
    today = today or date.today()
    last_sunday = today - timedelta(days=(today.weekday() + 1) % 7)

    def s(i, series, title, weeks_ago, scripture, summary="", questions=""):
        return {"id": _SM[i], "series_id": series, "title": title,
                "preached_on": (last_sunday - timedelta(weeks=weeks_ago)).isoformat(), "speaker": "Your pastor",
                "scripture": scripture, "summary": summary, "questions": questions, "video_url": "",
                "audio_url": "", "published": True, "sample": True}
    return {
        "series": [{"id": _SE[0], "title": "Light Has Come", "description": "A sample series.", "sample": True},
                   {"id": _SE[1], "title": "Rooted", "description": "", "sample": True},
                   {"id": _SE[2], "title": "The Good Life", "description": "", "sample": True}],
        "sermons": [s(0, _SE[0], "Hope Has a Name", 0, "Isaiah 9:6",
                      "This is where your sermon's summary goes: two or three sentences a member can take into their week.",
                      "What gives you hope this week?\nWho could you share that hope with?"),
                    s(1, _SE[0], "A Light in the Dark", 1, "John 1:5"),
                    s(2, _SE[1], "Planted by Water", 2, "Psalm 1:3"),
                    s(3, _SE[2], "Enough", 3, "Philippians 4:11-13"),
                    s(4, None, "A Word for the Week", 4, "Psalm 23")],
    }


def plan_today() -> Dict[str, Any]:
    return {"day": 12, "of": 30, "label": "Psalm 23", "title": "30 Days in the Psalms",
            "href": "/my/bible/psalms/23", "sample": True}
