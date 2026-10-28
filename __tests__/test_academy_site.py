"""The website's class list and class pages (step 4 of the Class Schedule).

People see when a class meets, how its lessons open and what each week
holds before they join; a program leads the list as one journey.
"""
import asyncio
import os
from datetime import datetime, timezone

import academy_join as aj
import academy_site as site
import public_site as ps

BIZ = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"
FOUNDATION = "c480f7f0-740d-4c78-9578-12f7e0150102"
FORMATION = "65276e60-f8a4-48fe-b22b-a86a6cf78635"
NEW_MEMBERS = "11111111-2222-4333-8444-555555555555"
NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)

FOUNDATION_ROW = {"id": FOUNDATION, "title": "The Making: Foundation", "description": "The ground everything else stands on.",
                  "status": "published", "drip_mode": "weekly", "opens_from": "2030-10-24T23:00:00+00:00", "opens_tz": "America/Chicago",
                  "product_id": None, "self_join": True}
LESSONS = [{"id": f"l{i}", "title": t, "duration_minutes": 45, "lesson_type": "text", "drip_offset_days": 0}
           for i, t in enumerate(["New Life & Identity", "The Word", "The Holy Spirit", "The Church"])]
ITEMS = [
    {"id": "h1", "kind": "homework", "title": "Write your story in three sentences", "lesson_id": "l0", "project_id": None, "position": 0},
    {"id": "d1", "kind": "discussion", "title": "What changed?", "lesson_id": "l0", "project_id": None, "position": 1},
    {"id": "g1", "kind": "gathering", "title": "Serve day", "lesson_id": "l1", "project_id": None, "position": 2, "starts_at": "2030-11-02T14:00:00+00:00"},
    {"id": "p1", "kind": "project", "title": "My story", "lesson_id": None, "project_id": None, "position": 3},
    {"id": "s1", "kind": "homework", "title": "Pick it", "lesson_id": "l1", "project_id": "p1", "position": 4},
    {"id": "s2", "kind": "homework", "title": "Draft it", "lesson_id": "l2", "project_id": "p1", "position": 5},
    {"id": "h2", "kind": "homework", "title": "Read John 1-7", "lesson_id": "l1", "project_id": None, "position": 6},
    {"id": "h3", "kind": "homework", "title": "Pray with someone", "lesson_id": "l2", "project_id": None, "position": 7},
]
# Thursdays 6 PM in Chicago: 23:00 UTC until daylight saving ends on Nov 3, 2030, then midnight.
SESSIONS = [{"lesson_id": f"l{i}", "starts_at": at, "status": "scheduled"} for i, at in enumerate(
    ["2030-10-24T23:00:00+00:00", "2030-10-31T23:00:00+00:00", "2030-11-08T00:00:00+00:00", "2030-11-15T00:00:00+00:00"])]


def test_when_a_together_class_meets_is_said_on_its_own_clock():
    assert site.when_line(FOUNDATION_ROW, "UTC", NOW) == "Thursdays 6 PM, from Oct 24"
    assert site.when_line({**FOUNDATION_ROW, "opens_from": "2020-10-22T23:00:00+00:00"}, "UTC", NOW) == "Thursdays 6 PM, since Oct 22"
    assert site.when_line({"drip_mode": "weekly"}, "UTC", NOW) == "One lesson a week, start any time"
    assert site.when_line({"drip_mode": "none"}, "UTC", NOW) == "Start any time"


def test_the_pace_and_what_it_asks_read_plainly():
    assert site.pace_line(FOUNDATION_ROW, 4) == "One lesson a week, together · 4 weeks"
    assert site.pace_line({"drip_mode": "none"}, 7) == "All 7 lessons open when you join"
    assert site.pace_line({"drip_mode": "weekly"}, 4) == "One lesson a week from the day you join · 4 weeks"
    assert site.involves_line(ITEMS, 4) == "Weekly homework, 1 discussion, one project and one gathering"
    assert site.involves_line([], 4) == ""


def test_each_week_carries_its_class_night_and_what_else_happens():
    rows = site.week_rows(FOUNDATION_ROW, LESSONS, ITEMS, SESSIONS, "UTC")
    assert [r["date"] for r in rows] == ["Thu Oct 24", "Thu Oct 31", "Thu Nov 7", "Thu Nov 14"]
    assert rows[0]["tags"] == [("live", "Class Thu 6 PM"), ("homework", "Write your story in three sentences"), ("discussion", "Discussion")]
    assert ("project", "My story, step 1") in rows[1]["tags"] and ("gathering", "Serve day Sat 9 AM") in rows[1]["tags"]
    assert ("project", "My story, step 2") in rows[2]["tags"]
    assert not any(t for r in rows for t in r["tags"] if t[1] == "My story"), "the project row itself is never a week's tag"


def test_a_class_counted_from_joining_has_no_dates():
    rows = site.week_rows({"drip_mode": "weekly"}, LESSONS, [], [], "UTC")
    assert all(r["date"] == "" for r in rows)


def test_a_tracks_name_drops_its_programs():
    assert site.track_name("The Making: Foundation", "The Making") == "Foundation"
    assert site.track_name("New Members Orientation", "The Making") == "New Members Orientation"


def _fake(monkeypatch, store):
    async def fake_sb(client, path):
        for key, rows in store.items():
            if path.startswith(key):
                return rows(path) if callable(rows) else rows
        return []

    async def fake_brand(client, biz):
        return "Love City Church", "#C2125F", {}, {}

    monkeypatch.setattr(ps, "_sb_service", fake_sb)
    monkeypatch.setattr(ps, "_academy_brand", fake_brand)
    monkeypatch.setattr(ps, "_academy_skin", lambda *a: ("#C2125F", ""))
    monkeypatch.setattr(ps, "_inject_brand_meta", lambda html, biz: html)
    monkeypatch.setattr(ps, "_academy_zone", lambda biz: "America/Chicago")
    monkeypatch.setattr(aj, "next_class_line", lambda biz, cid: "Thursday, October 24 at 6 PM")


def test_the_class_page_shows_week_by_week_before_anyone_joins(monkeypatch):
    seen = []

    def items(path):
        seen.append(path)
        return ITEMS

    _fake(monkeypatch, {
        "/academy_courses": [FOUNDATION_ROW], "/academy_lessons": LESSONS, "/academy_schedule_items": items,
        "/academy_live_sessions": SESSIONS,
        "/academy_program_courses": [{"position": 0, "teacher_name": "Pastor Kevin",
                                      "academy_programs": {"title": "The Making", "academy_program_courses": [{}, {}, {}, {}]}}],
    })
    page = asyncio.run(ps._serve_academy(None, BIZ, f"/academy/{FOUNDATION}", standalone=False)).body.decode()
    assert "status=eq.published" in seen[0], "drafts never reach the website"
    assert "The Making &middot; track 1 of 4" in page and "<h1>Foundation</h1>" in page
    assert "Week by week" in page and "Thu Oct 24" in page and "Class Thu 6 PM" in page and "My story, step 1" in page
    assert page.count("Class Thu 6 PM") == 4, "6 PM on the class's clock every week, across daylight saving"
    assert "Thursdays 6 PM, from Oct 24" in page and "with Pastor Kevin" in page
    assert 'action="/academy/' in page, "the sign-up form is still there"
    _save("class-page.html", page)


def test_the_class_list_leads_with_the_program_and_says_when_each_meets(monkeypatch):
    formation = {**FOUNDATION_ROW, "id": FORMATION, "title": "The Making: Formation", "description": "Habits that hold.",
                 "opens_from": "2030-11-22T00:00:00+00:00"}
    members = {"id": NEW_MEMBERS, "title": "New Members Orientation", "description": "Welcome home.", "status": "published",
               "drip_mode": "none", "opens_from": None, "opens_tz": None, "product_id": None, "self_join": True}
    _fake(monkeypatch, {
        "/academy_courses": [FOUNDATION_ROW, formation, members],
        "/academy_lessons": [{"course_id": FOUNDATION, "duration_minutes": 45}] * 4 + [{"course_id": NEW_MEMBERS, "duration_minutes": 20}] * 7
                            + [{"course_id": FORMATION, "duration_minutes": 45}] * 4,
        "/academy_schedule_items": [{**i, "course_id": FOUNDATION} for i in ITEMS],
        "/academy_live_sessions": [{"course_id": FOUNDATION, "starts_at": s["starts_at"]} for s in SESSIONS],
        "/academy_programs": [{"id": "pg", "title": "The Making", "finish_title": "Graduation", "finish_at": "2031-03-05T00:00:00+00:00",
                               "academy_program_courses": [{"course_id": FOUNDATION, "position": 0}, {"course_id": FORMATION, "position": 1}]}],
        "/businesses": [{"type": "ministry"}],
    })
    page = asyncio.run(ps._serve_academy(None, BIZ, "/academy", standalone=False)).body.decode()
    assert "<h1>Classes</h1>" in page and "Each one says when it meets" in page
    assert "A program · 2 tracks" in page and "Start with Foundation" in page and "Oct 24 – Nov 14" in page
    assert "Thursdays 6 PM, from Nov 21" in page
    assert "Thursdays 6 PM, from Oct 24" in page and "One lesson a week, together · 4 weeks" in page
    assert "All 7 lessons open when you join" in page and "Weekly homework" in page
    assert "learn at your own pace" not in page
    _save("class-list.html", page)



def test_a_church_with_nothing_published_yet_says_classes(monkeypatch):
    _fake(monkeypatch, {"/businesses": [{"type": "ministry"}]})
    page = asyncio.run(ps._serve_academy(None, BIZ, "/academy", standalone=False)).body.decode()
    assert "New classes are on the way" in page and "New courses" not in page
    _fake(monkeypatch, {"/businesses": [{"type": "coaching"}]})
    page = asyncio.run(ps._serve_academy(None, BIZ, "/academy", standalone=False)).body.decode()
    assert "New courses are on the way" in page


def _save(name, html):
    out = os.environ.get("ACADEMY_SITE_OUT")
    if out:
        os.makedirs(out, exist_ok=True)
        open(os.path.join(out, name), "w", encoding="utf-8").write(html)
