# __tests__/test_business_track.py
#
# THE BUSINESS TRACK — the established-business intake.
#
# What these pin, and why each one is here rather than being obvious:
#
#   * the phase table and the column map agree (a phase whose column is
#     missing saves into nowhere, silently)
#   * the plug-in catalog is CLOSED — every key the coach may recommend
#     has a real done-probe and a real destination. This is the
#     dead-weight rule expressed as a test: a catalog entry without a
#     probe becomes a checklist card that can never be ticked, and one
#     without a nav target becomes a card that dead-ends on someone's
#     first day.
#   * `needs` prerequisites reference keys that exist
#   * completed_phases does NOT count the empty {} / [] column defaults —
#     get that wrong and a brand-new track reports 8/8 complete
#   * the coach prompt actually renders, and carries the write verbs it
#     claims to. The whole design rests on the coach writing to real
#     stores mid-conversation; a prompt that lost those lines would still
#     hold a pleasant conversation and capture nothing.
#   * both coaches are gated as coaches everywhere the operational
#     injectors are skipped (the leak class of #153/#164)

import inspect

import pytest

import business_track_actions as bta
import business_track_router as btr


# ─── phases ──────────────────────────────────────────────────────────

def test_every_phase_has_a_column_a_label_and_a_goal():
    for p in bta.BUSINESS_PHASES:
        assert p in bta.BUSINESS_PHASE_COLUMN, f"{p} saves into nowhere"
        assert p in bta.BUSINESS_PHASE_LABELS, f"{p} has no label"
        assert p in bta.BUSINESS_PHASE_GOALS, f"{p} tells the coach nothing"


def test_phase_columns_are_distinct():
    cols = list(bta.BUSINESS_PHASE_COLUMN.values())
    assert len(cols) == len(set(cols)), "two phases share a column — one overwrites the other"


def test_no_orphan_entries_in_the_phase_maps():
    for m in (bta.BUSINESS_PHASE_COLUMN, bta.BUSINESS_PHASE_LABELS, bta.BUSINESS_PHASE_GOALS):
        assert set(m) == set(bta.BUSINESS_PHASES)


# ─── completed_phases ────────────────────────────────────────────────

def test_a_fresh_track_has_completed_nothing():
    # The columns default to {} and [] in Postgres. A truthiness test on
    # the raw column would call every phase done the moment the row is
    # created, and the practitioner would open a dashboard claiming Chief
    # already knew a business he had never asked about.
    fresh = {c: ({} if c != "offerings_captured" else [])
             for c in bta.BUSINESS_PHASE_COLUMN.values()}
    assert bta.completed_phases(fresh) == []
    assert bta.completed_phases(None) == []
    assert bta.completed_phases({}) == []


def test_a_populated_phase_counts():
    track = {c: {} for c in bta.BUSINESS_PHASE_COLUMN.values()}
    track["business_shape"] = {"summary": "barbershop, 6 years"}
    track["offerings_captured"] = [{"name": "Fade", "price": 35}]
    assert set(bta.completed_phases(track)) == {"business", "offerings"}


# ─── the plug-in catalog ─────────────────────────────────────────────

def test_every_catalog_entry_is_shaped_and_reachable():
    for key, spec in bta.PLUGIN_CATALOG.items():
        for field in ("title", "why", "nav", "verticals", "needs", "weight"):
            assert field in spec, f"{key} is missing {field}"
        assert spec["nav"].get("tab"), f"{key} has no destination — it would dead-end"
        assert spec["nav"].get("page"), f"{key} has no page — it would dead-end"
        assert spec["title"].strip() and spec["why"].strip()
        assert isinstance(spec["needs"], list)


def test_every_catalog_key_has_a_done_probe():
    # THE dead-weight guarantee. Without a probe a plug-in can never be
    # ticked off, so it sits on the checklist forever telling someone to
    # do a thing they already did.
    missing = set(bta.PLUGIN_CATALOG) - set(btr.PROBES)
    assert not missing, f"no done-probe for: {sorted(missing)}"


def test_no_probe_without_a_catalog_entry():
    orphans = set(btr.PROBES) - set(bta.PLUGIN_CATALOG)
    assert not orphans, f"probe with nothing to probe: {sorted(orphans)}"


def test_prerequisites_reference_real_plugins():
    for key, spec in bta.PLUGIN_CATALOG.items():
        for need in spec["needs"]:
            assert need in bta.PLUGIN_CATALOG, f"{key} needs unknown plug-in '{need}'"
            assert need != key, f"{key} requires itself"


def test_prerequisites_are_not_circular():
    def walk(key, seen):
        for need in bta.PLUGIN_CATALOG[key]["needs"]:
            assert need not in seen, f"prerequisite cycle through {need}"
            walk(need, seen | {need})
    for key in bta.PLUGIN_CATALOG:
        walk(key, {key})


def test_vertical_filter_returns_real_keys_heaviest_first():
    for vertical in ("coach", "barber", "lawyer", "ministry", "contractor", ""):
        keys = bta.plugins_for_vertical(vertical)
        assert keys, f"{vertical!r} got an empty plug-in list"
        assert all(k in bta.PLUGIN_CATALOG for k in keys)
        weights = [bta.PLUGIN_CATALOG[k]["weight"] for k in keys]
        assert weights == sorted(weights, reverse=True)


def test_the_universal_plugins_reach_every_vertical():
    # Importing your people and loading your prices are not vertical
    # concerns — every business needs both, and they lead the list.
    for vertical in ("coach", "barber", "lawyer", "ministry", "therapist",
                     "contractor", "nonprofit", "consultant", "unknown_vertical"):
        keys = bta.plugins_for_vertical(vertical)
        assert keys[0] == "import_contacts"
        assert "offerings" in keys
        assert "payments" in keys


# ─── the coach prompt ────────────────────────────────────────────────

def _ctx(track=None, biz_type="coach"):
    return {
        "business": {
            "id": "b1", "name": "Shift Coaching", "type": biz_type,
            "settings": {"practitioner_name": "Kevin"},
            "voice_profile": {"tone": "warm"},
        },
        "business_track": track or {},
    }


def test_prompt_renders_for_greeting_and_mid_conversation():
    for greeting in (True, False):
        p = bta.build_business_coach_prompt(_ctx(), greeting)
        assert len(p) > 3000
        assert "Business Coach" in p


def test_prompt_carries_the_write_verbs_it_depends_on():
    # The design rests on these: a prompt that lost them would converse
    # well and capture nothing, which is exactly the failure this whole
    # arc replaced.
    p = bta.build_business_coach_prompt(_ctx(), False)
    for verb in ("create_offering", "update_business_profile_field",
                 "update_practitioner_profile_field", "remember", "create_goal",
                 "save_business_phase", "advance_business_phase",
                 "business_session_summary", "complete_business_track"):
        assert verb in p, f"the coach was never told about {verb}"


def test_prompt_only_offers_plugins_that_exist():
    p = bta.build_business_coach_prompt(_ctx(), False)
    menu = p.split("Choose 4-7")[0]
    for key in bta.plugins_for_vertical("coach"):
        assert key in menu, f"{key} missing from the coach's menu"


def test_prompt_asks_the_vertical_questions_that_were_previously_decorative():
    # vertical_intelligence has written per-vertical onboarding questions
    # all along; before this arc they were fetched by the frontend and
    # rendered as preview text under "How coachs typically configure
    # this", and nobody ever asked them.
    import vertical_intelligence as vi
    questions = vi.get_onboarding_questions("coach")
    assert questions, "fixture assumption broken: coach has no vertical questions"
    p = bta.build_business_coach_prompt(_ctx(), False)
    assert questions[0]["prompt"] in p


def test_prompt_never_re_asks_what_is_already_captured():
    track = {"business_shape": {"summary": "six years, two chairs"}}
    p = bta.build_business_coach_prompt(_ctx(track), False)
    assert "never ask for any of this again" in p.lower()
    assert "six years, two chairs" in p


def test_unknown_vertical_does_not_break_the_prompt():
    p = bta.build_business_coach_prompt(_ctx(biz_type="not_a_real_vertical"), True)
    assert len(p) > 3000


# ─── wiring ──────────────────────────────────────────────────────────

def test_handlers_are_registered_and_classified():
    import chief_of_staff
    import action_registry
    for verb, fn in bta.HANDLERS.items():
        assert chief_of_staff.ACTION_HANDLERS.get(verb) is fn, \
            f"{verb} is not wired into the dispatcher"
        assert action_registry.classification(verb) is not None, \
            f"{verb} is unclassified — default-deny would refuse it"
        # All four only move the track row. If one ever becomes the kind
        # of composite complete_strategy_track is (it GENERATES A SITE),
        # this assertion is the thing that should stop it going out
        # silently classified as harmless.
        assert action_registry.effect(verb) == "write"
        assert not action_registry.is_sensitive(verb), \
            f"{verb} is now sensitive — reclassify it deliberately"


def test_both_coaches_are_treated_as_coaches():
    import chief_of_staff as cos
    assert "business_coach" in cos.COACH_MODES
    assert "strategy_coach" in cos.COACH_MODES
    # The per-turn operational injectors are skipped on `is_coach_mode`.
    # If that ever narrows back to a literal == "strategy_coach", the
    # Business Coach starts seeing Chief-of-Staff action instructions
    # riding inside the practitioner's own words.
    src = inspect.getsource(cos.chief_chat) if hasattr(cos, "chief_chat") else ""
    if src:
        assert 'in COACH_MODES' in src


def test_both_coaches_ride_the_deep_lane():
    import chief_models
    assert chief_models.lane_for_chat("business_coach", "") == "deep"
    assert chief_models.lane_for_chat("strategy_coach", "") == "deep"
    assert chief_models.lane_for_chat("", "") == "chat"


def test_business_sentinels_read_as_greeting_and_pause():
    import chief_of_staff as cos
    assert cos._is_greeting(cos.BUSINESS_COACH_OPEN_SENTINEL)
    assert cos._is_greeting(cos.BUSINESS_COACH_PAUSE_SENTINEL)
    assert cos._is_coach_pause(cos.BUSINESS_COACH_PAUSE_SENTINEL)
    assert not cos._is_coach_pause(cos.BUSINESS_COACH_OPEN_SENTINEL)
    # The strategy sentinels must keep working exactly as before.
    assert cos._is_greeting(cos.COACH_OPEN_SENTINEL)
    assert cos._is_coach_pause(cos.COACH_PAUSE_SENTINEL)


def test_business_track_is_exported_with_the_account():
    # A business-scoped table missing from BUSINESS_CHILD_TABLES makes the
    # account export silently incomplete — this list has drifted before.
    import account_lifecycle
    assert "business_tracks" in account_lifecycle.BUSINESS_CHILD_TABLES


def test_the_operational_chief_says_nothing_when_there_is_no_track():
    assert bta.format_business_track_block({"id": "b1"}, None) == ""


def test_the_operational_chief_is_told_what_the_coach_learned():
    block = bta.format_business_track_block(
        {"id": "b1"},
        {"business_shape": {"summary": "two-chair barbershop"},
         "audience": {"who": "regulars from the neighbourhood"},
         "current_phase": "money", "status": "in_progress"})
    assert "two-chair barbershop" in block
    assert "regulars from the neighbourhood" in block
    assert "NOT the Business Coach" in block


# ─── contact import ──────────────────────────────────────────────────

def test_import_never_writes_a_notes_column():
    # `notes` appears in Chief's UPDATABLE_CONTACT_FIELDS but is NOT a
    # column on contacts — notes are events rows. Sending it would
    # PGRST204 the entire batch, the same class of bug already documented
    # for lifecycle_stage in booking_widget_router.
    import contacts_import_router as cir
    src = inspect.getsource(cir.import_contacts)
    payload = src.split('payload: Dict[str, Any] = {')[1].split('}')[0]
    assert '"notes"' not in payload
    assert "metadata" in payload


def test_import_statuses_match_what_chief_accepts():
    import contacts_import_router as cir
    import chief_of_staff
    assert cir.VALID_STATUSES == set(chief_of_staff.VALID_CONTACT_STATUSES)
