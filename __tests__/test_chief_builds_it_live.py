"""Chief builds it live (Wave B, 2026-09-02).

Kevin's ruling: Chief is proactive, not reactive. Every setup question
carries its why; where Chief has the verb it does the move in the
conversation and says what it built; the first hour ends with something
the practitioner can send someone; the sit-down with Chief is mandatory
but HELD and resurfaced, never a wall. These tests pin the prompt text
and the catalog that carry that.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import business_track_actions as bta  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import vertical_registry  # noqa: E402
from test_business_track import BUILD_PAGES  # noqa: E402


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


# ─── the catalog knows how Chief does each move ─────────────────────────

def test_every_plugin_says_how_chief_does_it():
    for key, spec in bta.PLUGIN_CATALOG.items():
        how = spec.get("chief", "")
        assert how.startswith(("DO IT HERE", "DOOR")), f"{key}: {how[:40]!r}"


def test_the_moves_chief_can_make_itself_name_their_verb():
    assert "create_contact" in bta.PLUGIN_CATALOG["import_contacts"]["chief"]
    assert "create_offering" in bta.PLUGIN_CATALOG["offerings"]["chief"]
    assert "set_availability_day" in bta.PLUGIN_CATALOG["availability"]["chief"]
    # a list has a door of its own
    assert "structure-import" in bta.PLUGIN_CATALOG["import_contacts"]["chief"]


def test_doors_name_a_real_destination():
    for key, spec in bta.PLUGIN_CATALOG.items():
        if spec["chief"].startswith("DOOR"):
            nav = spec["nav"]
            assert f"{nav['tab']}/{nav.get('page') or nav.get('sub')}" in spec["chief"], key


# ─── the first hour ends with something to send ─────────────────────────

def test_every_canonical_vertical_has_a_sendable_artifact():
    for v in vertical_registry.canonical_keys() if hasattr(vertical_registry, "canonical_keys") else vertical_registry.CANONICAL:
        art = bta.sendable_artifact_for(v)
        assert art["label"] and art["keys"], v
        assert all(k in bta.PLUGIN_CATALOG for k in art["keys"]), v
        assert art["nav"]["tab"] == "build" and art["nav"]["page"] in BUILD_PAGES, v


def test_aliases_and_unknowns_still_get_an_artifact():
    assert bta.sendable_artifact_for("counselor") == bta.sendable_artifact_for("therapist")
    assert bta.sendable_artifact_for("law") == bta.sendable_artifact_for("lawyer")
    assert bta.sendable_artifact_for("mobile pet grooming") == bta.SENDABLE_ARTIFACT["custom"]
    assert bta.sendable_artifact_for(None) == bta.SENDABLE_ARTIFACT["custom"]


# ─── the setup block is the proactive contract ──────────────────────────

def _snapshot(done=0):
    items = [
        {"key": "offerings", "title": "Load what you sell", "why": "Prices drive everything.",
         "nav": {"tab": "operate", "sub": "offerings-manager"}, "done": done >= 1, "blocked_by": []},
        {"key": "availability", "title": "Set the hours you actually work", "why": "Booking needs hours.",
         "nav": {"tab": "build", "page": "booking"}, "done": False, "blocked_by": [] if done >= 1 else ["offerings"]},
        {"key": "payments", "title": "Connect how you get paid", "why": "Money that arrives.",
         "nav": {"tab": "build", "page": "integrations"}, "done": False, "blocked_by": []},
    ]
    return {"items": items, "done": done, "total": 3,
            "artifact": bta.sendable_artifact_for("personal_services")}


def test_setup_block_asks_with_the_why_and_does_it_here():
    block = cos._format_setup_block(_snapshot())
    assert "ASK WITH THE WHY" in block
    assert "DO IT HERE" in block
    assert "SAY WHAT YOU BUILT" in block
    assert "one stop per turn" in block          # kept from the concierge contract
    assert "never invent a destination" in block  # kept
    # each undone item carries its how-line from the catalog
    assert "how: DO IT HERE. Ask 'what is the one thing" in block
    assert "how: DO IT HERE. Ask the days and hours" in block
    assert "how: DOOR. navigate build/integrations" in block


def test_setup_block_names_the_sendable_artifact():
    block = cos._format_setup_block(_snapshot())
    assert "THE FIRST HOUR ENDS WITH SOMETHING TO SEND: a booking link" in block
    assert "booking-share" in block


def test_setup_block_all_done_still_congratulates():
    snap = _snapshot(done=3)
    for p in snap["items"]:
        p["done"] = True
    block = cos._format_setup_block(snap)
    assert "congratulate" in block and "ASK WITH THE WHY" not in block


def test_snapshot_carries_the_artifact(monkeypatch):
    import business_track_router as btr
    monkeypatch.setattr(btr, "resolve_plugins", lambda biz: _snapshot()["items"])
    snap = cos._fetch_setup_snapshot({"id": "b1", "type": "coach"})
    assert snap["artifact"]["label"].startswith("a booking link")


# ─── the greeting asks one question, not a list ─────────────────────────

def _ctx():
    return {
        "business": {"id": "b1", "name": "Fade Society", "type": "personal_services",
                     "settings": {"practitioner_name": "Marcus"}, "created_at": _iso(0.2)},
        "contacts": [], "sessions": [], "invoices": [], "queue": [], "insights": [],
        "business_track": None,
    }


def test_first_run_greeting_asks_one_question_with_its_why():
    # The concierge tests carry a full, empty-but-shaped context builder.
    from test_first_run_concierge import _ctx as concierge_ctx
    prompt = cos._build_system_prompt(concierge_ctx(), True, time_of_day="morning",
                                      setup_block=cos._format_setup_block(_snapshot()),
                                      first_run=True)
    assert "THIS BUSINESS IS BRAND NEW" in prompt and "server-verified" in prompt
    assert "Ask ONE question" in prompt
    assert "WITH ITS WHY" in prompt
    assert "Not a menu" in prompt
    assert "twenty-minute conversation" in prompt
    assert "List the top 3 undone plug-ins" not in prompt


# ─── the sit-down is held, not dropped ──────────────────────────────────

def test_a_young_business_that_never_opened_the_sit_down_still_gets_the_offer():
    block = bta.format_business_track_block({"id": "b1", "created_at": _iso(0.5)}, None)
    assert "not started" in block
    assert "THE SIT-DOWN IS HELD, NOT DROPPED" in block
    assert "twenty minutes now, or start with setup" in block
    assert "Never more than once per conversation" in block


def test_the_offer_changes_with_the_day():
    day3 = bta.format_business_track_block({"id": "b1", "created_at": _iso(3.5)}, None)
    assert "Day three onward" in day3
    week = bta.format_business_track_block({"id": "b1", "created_at": _iso(9)}, None)
    assert "It has been a week" in week


def test_an_established_business_is_not_nagged():
    assert bta.format_business_track_block({"id": "b1", "created_at": _iso(45)}, None) == ""
    assert bta.format_business_track_block({"id": "b1"}, None) == ""


def test_an_unfinished_track_keeps_the_offer_and_the_boundary():
    track = {"status": "in_progress", "current_phase": "owner", "phases": {}}
    block = bta.format_business_track_block({"id": "b1", "created_at": _iso(1)}, track)
    assert "NOT the Business Coach" in block
    assert "THE SIT-DOWN IS HELD, NOT DROPPED" in block


def test_a_completed_track_makes_no_offer():
    track = {"status": "completed", "current_phase": "plan", "phases": {},
             "owner_profile": {"summary": "x"}}
    block = bta.format_business_track_block({"id": "b1", "created_at": _iso(1)}, track)
    assert "THE SIT-DOWN IS HELD" not in block


# ─── the coach says what the sit-down is ────────────────────────────────

def test_coach_opening_names_twenty_minutes_and_can_be_held():
    ctx = _ctx()
    ctx["business_track"] = {"status": "in_progress", "current_phase": "owner", "phases": {}}
    prompt = bta.build_business_coach_prompt(ctx, True)
    assert "about twenty minutes" in prompt
    assert "hold it and bring it up again in a couple of days" in prompt
    assert "Choose 4-7" in prompt  # the menu split anchor survives
