"""Chief knows every room (Wave B, 2026-09-02).

Three sentinels — first visit, the "what is this room" door, the guided
walk — and a THIS ROOM block on every turn that carries a view. The map
must cover every route the app can stand on, fall back gracefully for
the ones it does not name, and never turn a room question into a day-read.
"""
from __future__ import annotations

import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import chief_of_staff as cos  # noqa: E402
import room_orientation as ro  # noqa: E402
from test_business_track import BUILD_PAGES, OPERATE_SUBS  # noqa: E402
from test_first_run_concierge import _ctx as concierge_ctx  # noqa: E402


# ─── the map ────────────────────────────────────────────────────────────

def test_every_navigable_route_has_an_entry():
    for page in BUILD_PAGES:
        assert ro.describe("build", page=page)["known"], f"build/{page}"
    for sub in OPERATE_SUBS:
        assert ro.describe("operate", sub=sub)["known"], f"operate/{sub}"
    for sub in ("dashboard", "briefing", "goals", "revenue", "retention", "reviews", "content",
                "campaigns", "funnel", "timeline", "notes", "getfound", "googleprofile", "ideas"):
        assert ro.describe("grow", sub=sub)["known"], f"grow/{sub}"


def test_every_entry_is_written_for_the_practitioner():
    for key, d in {**{k: v for k, v in ro.ROOMS.items()}, **{k: v for k, v in ro.TABS.items()}}.items():
        assert d["label"] and d["purpose"].endswith(".") and d["next_rule"], key
        for banned in ("archetype", "module_id", "PostgREST", "RLS", "endpoint"):
            assert banned not in d["purpose"] and banned not in d["next_rule"], (key, banned)


def test_unknown_routes_fall_back_to_the_tab_then_to_a_generic_line():
    d = ro.describe("operate", sub="something-new")
    assert d["known"] is False and d["label"] == "Operate"
    d = ro.describe("nowhere")
    assert d["known"] is False and d["label"] == "this page"
    d = ro.describe("build", page="module:1234")
    assert d["known"] is True and "custom solution" in d["label"]
    assert ro.describe("command_center")["label"] == "Home"


def test_room_key_uses_page_for_build_and_sub_elsewhere():
    assert ro.room_key("build", sub="ignored", page="my-site") == "build/my-site"
    assert ro.room_key("operate", sub="contacts", page="ignored") == "operate/contacts"
    assert ro.room_key("home") == "home"


# ─── the sentinels ──────────────────────────────────────────────────────

def test_sentinel_kinds():
    assert ro.sentinel_kind("[SYSTEM:room_first_visit]") == "first_visit"
    assert ro.sentinel_kind("  [SYSTEM:room_orientation]") == "orientation"
    assert ro.sentinel_kind("[SYSTEM:guided_walk]") == "walk"
    assert ro.sentinel_kind("[SYSTEM:opening_greeting:morning]") is None
    assert ro.sentinel_kind("what is this?") is None
    # not greetings — a room question must never trigger the day-read
    for s in ro.SENTINELS:
        assert cos._is_greeting(s) is False


def test_mode_clauses_say_what_the_turn_is():
    assert "ONE sentence" in ro.mode_clause("first_visit", "operate", "contacts")
    o = ro.mode_clause("orientation", "operate", "contacts")
    assert "three things" in o and "RIGHT NOW" in o and "No greeting, no day-read" in o
    w = ro.mode_clause("walk", "home")
    assert "ONE PER TURN" in w and "exactly ONE navigate" in w and "Never describe two rooms" in w
    assert ro.mode_clause(None) == ""


# ─── the prompt ─────────────────────────────────────────────────────────

def test_view_block_carries_this_room():
    view = cos.CurrentContext(tab="operate", sub_tab="contacts")
    block = cos._format_view_block(view, {})
    assert "CURRENTLY VIEWING: OPERATE → contacts" in block
    assert "THIS ROOM: Contacts —" in block
    assert "The one next thing here is usually:" in block


def test_view_block_reads_the_build_page():
    view = cos.CurrentContext(tab="build", page="my-site")
    block = cos._format_view_block(view, {})
    assert "THIS ROOM: My Site" in block


def test_orientation_turn_replaces_the_day_read():
    view = cos.CurrentContext(tab="grow", sub_tab="retention")
    prompt = cos._build_system_prompt(concierge_ctx(), False, view=view, orientation_kind="orientation")
    assert "WHAT IS THIS ROOM" in prompt
    assert "THIS ROOM: Retention" in prompt
    assert "OPENING GREETING MODE" not in prompt


def test_first_visit_and_walk_clauses_land_in_the_prompt():
    view = cos.CurrentContext(tab="build", page="booking")
    p1 = cos._build_system_prompt(concierge_ctx(), False, view=view, orientation_kind="first_visit")
    assert "FIRST VISIT TO A ROOM" in p1 and "Booking" in p1
    p2 = cos._build_system_prompt(concierge_ctx(), False, view=None, orientation_kind="walk")
    assert "GUIDED WALK" in p2


def test_a_normal_turn_has_no_orientation_clause():
    prompt = cos._build_system_prompt(concierge_ctx(), False, view=cos.CurrentContext(tab="home"))
    assert "WHAT IS THIS ROOM" not in prompt and "GUIDED WALK" not in prompt
    assert "THIS ROOM: Home" in prompt
