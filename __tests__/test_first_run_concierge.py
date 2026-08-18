"""
test_first_run_concierge.py — Chief walks a new practitioner through
setup instead of describing it.

THE DESIGN
  The plug-in list (business_track_router.resolve_plugins) was already
  the shared itinerary between the coached session's exit ramp and the
  BUILD checklist — but Chief could not see it, so its setup advice was
  a guess and its "brand new business" greeting was a model judgement
  call. The concierge pass puts the measured list into the prompt
  (SETUP STATUS), makes the launch greeting a server-computed fact
  (first_run), and extends the business-track block so everything the
  practitioner told the coach reaches the operational Chief.

WHAT THESE TESTS PIN
  - The probe-spend gate (_setup_snapshot_wanted): probes only run while
    setup is plausibly in progress, and a dismissed checklist stops them.
  - The SETUP STATUS block: real titles, exact nav JSON, the walk-don't-
    dump rules, and silence when there is no snapshot.
  - Prompt integration: the block lands in the volatile tail (below
    [[CHIEF_CACHE_SPLIT]]), and the launch greeting flips from
    model-judged to server-verified when first_run is computed.
  - The richer business-track block: offerings, tools, the agreed
    plug-in order and the last session summary all reach Chief.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import chief_of_staff as cos
import business_track_actions as bta


def _biz(days_old: float, settings=None) -> dict:
    created = datetime.now(timezone.utc) - timedelta(days=days_old)
    return {
        "id": "b1",
        "name": "Fade Factory",
        "type": "personal_services",
        "created_at": created.isoformat(),
        "settings": settings or {},
    }


# ─── the probe-spend gate ────────────────────────────────────────────

def test_dismissed_checklist_stops_the_probes():
    biz = _biz(1, settings={"checklist_dismissed": True})
    assert not cos._setup_snapshot_wanted(biz, {"status": "in_progress"})


def test_unfinished_track_means_setup_is_in_progress():
    assert cos._setup_snapshot_wanted(_biz(400), {"status": "in_progress"})


def test_completed_track_old_business_skips_the_probes():
    assert not cos._setup_snapshot_wanted(
        _biz(cos.SETUP_SNAPSHOT_MAX_AGE_DAYS + 30), {"status": "completed"})


def test_completed_track_young_business_still_gets_the_concierge():
    assert cos._setup_snapshot_wanted(_biz(3), {"status": "completed"})


def test_no_track_row_falls_back_to_age():
    assert cos._setup_snapshot_wanted(_biz(3), None)
    assert not cos._setup_snapshot_wanted(
        _biz(cos.SETUP_SNAPSHOT_MAX_AGE_DAYS + 30), None)


def test_unparseable_created_at_fails_closed():
    biz = _biz(1)
    biz["created_at"] = "not a date"
    assert not cos._setup_snapshot_wanted(biz, None)


# ─── the SETUP STATUS block ──────────────────────────────────────────

SNAPSHOT = {
    "items": [
        {"key": "import_contacts", "title": "Bring your client list over",
         "why": "The first domino.",
         "nav": {"tab": "operate", "sub": "contacts"},
         "done": False, "blocked_by": []},
        {"key": "payments", "title": "Connect how you get paid",
         "why": "Money that actually arrives.",
         "nav": {"tab": "build", "page": "integrations"},
         "done": True, "blocked_by": []},
        {"key": "site_domain", "title": "Point your domain at your site",
         "why": "Your own address.",
         "nav": {"tab": "build", "page": "my-site"},
         "done": False, "blocked_by": ["site"]},
    ],
    "done": 1,
    "total": 3,
}


def test_no_snapshot_means_no_block():
    assert cos._format_setup_block(None) == ""


def test_block_carries_counts_titles_and_exact_nav():
    block = cos._format_setup_block(SNAPSHOT)
    assert "Connected: 1 of 3" in block
    assert "Bring your client list over" in block
    # Nav must be printed as JSON Chief can copy into a navigate action.
    assert '{"tab": "operate", "sub": "contacts"}' in block
    # Blocked items say what unblocks them instead of hiding.
    assert "best after: site" in block
    # The behavioural contract rides with the data.
    assert "one stop per turn" in block
    assert "never invent a destination" in block.lower() or \
        "never invent a destination" in block


def test_done_items_are_not_listed_as_todo():
    block = cos._format_setup_block(SNAPSHOT)
    todo = block.split("Still to plug in")[1]
    assert "Connect how you get paid" not in todo


def test_all_done_congratulates_instead_of_inventing_chores():
    done = {"items": [dict(i, done=True) for i in SNAPSHOT["items"]],
            "done": 3, "total": 3}
    block = cos._format_setup_block(done)
    assert "congratulate" in block.lower()
    assert "Still to plug in" not in block


# ─── prompt integration ──────────────────────────────────────────────

class _EmptyCtx(dict):
    """_build_system_prompt reads a few dozen context keys unguarded —
    anything unset reads as empty (same pattern as test_growth_doctrine)."""
    def __missing__(self, key):
        return []


def _ctx() -> dict:
    return _EmptyCtx(business=_biz(2))


def test_setup_block_lands_in_the_volatile_tail():
    block = cos._format_setup_block(SNAPSHOT)
    prompt = cos._build_system_prompt(_ctx(), False, setup_block=block)
    assert "SETUP STATUS" in prompt
    # Below the cache split — setup state changes, the cached prefix must not.
    assert prompt.index("[[CHIEF_CACHE_SPLIT]]") < prompt.index("SETUP STATUS")


def test_first_run_greeting_is_server_verified():
    prompt = cos._build_system_prompt(
        _ctx(), True, time_of_day="morning",
        setup_block=cos._format_setup_block(SNAPSHOT), first_run=True)
    assert "THIS BUSINESS IS BRAND NEW" in prompt
    assert "server-verified" in prompt


def test_without_first_run_the_model_judged_fallback_remains():
    prompt = cos._build_system_prompt(_ctx(), True, time_of_day="morning")
    assert "THIS BUSINESS IS BRAND NEW" not in prompt
    # The launch plan still exists for un-snapshotted businesses.
    assert "LAUNCH GREETING" in prompt


def test_first_run_never_leaks_into_non_greeting_turns():
    prompt = cos._build_system_prompt(_ctx(), False, first_run=True)
    assert "LAUNCH GREETING" not in prompt


# ─── the richer business-track block ─────────────────────────────────

FULL_TRACK = {
    "status": "in_progress",
    "current_phase": "plan",
    "business_shape": {"summary": "two-chair barbershop"},
    "audience": {"who": "regulars from the neighbourhood"},
    "money_map": {"how_they_bill": "per cut", "how_they_get_paid": "cash and Venmo"},
    "growth_plan": {"target": "open a second chair", "constraint": "no-shows"},
    "offerings_captured": [{"name": "Fade", "price": 35}],
    "operations_map": {"tools_in_use": ["Square", "Instagram"],
                       "still_manual": ["reminders"],
                       "has_website": True,
                       "website_url": "fadefactory.com"},
    "first_30_days": {"plugins": ["import_contacts", {"key": "payments"}]},
    "phases": {"session_log": [
        {"date": "2026-08-01", "summary": "old entry"},
        {"date": "2026-08-18", "summary": "agreed to start with contacts"},
    ]},
}


def test_chief_hears_everything_the_coach_learned():
    block = bta.format_business_track_block({"id": "b1"}, FULL_TRACK)
    assert "cash and Venmo" in block
    assert "no-shows" in block
    assert "Fade" in block
    assert "Square" in block
    assert "reminders" in block
    assert "fadefactory.com" in block


def test_the_agreed_plugin_order_reaches_chief():
    block = bta.format_business_track_block({"id": "b1"}, FULL_TRACK)
    assert "import_contacts, payments" in block


def test_the_last_session_summary_reaches_chief_not_the_whole_log():
    block = bta.format_business_track_block({"id": "b1"}, FULL_TRACK)
    assert "agreed to start with contacts" in block
    assert "old entry" not in block


def test_sparse_tracks_do_not_crash_the_block():
    block = bta.format_business_track_block(
        {"id": "b1"}, {"status": "in_progress", "current_phase": "owner"})
    assert "BUSINESS TRACK:" in block
