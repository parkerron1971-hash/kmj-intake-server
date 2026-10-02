"""
test_workspace_archetypes.py — Chief's one decision, and the override that
makes it safe.

Two things are being guarded. First, that a business described in plain
language lands on the workspace a person would have picked for it — a
barbershop gets chairs, a law firm gets a docket. Second, and more
important, that the practitioner's corrections are permanent: a term they
set survives re-classification, an archetype switch, and a preset refresh,
because a system that quietly renames "Matter" back to "Project" has taught
the practitioner not to trust it.
"""
from __future__ import annotations

import pytest

import workspace_archetypes as wa
import workspace_layouts
from workspace_composer_router import build_layout, merge_terminology


# ─── the pick ────────────────────────────────────────────────────────

@pytest.mark.parametrize("answers,expected", [
    # declared vertical alone is enough
    ({"vertical": "personal_services"}, "salon"),
    ({"vertical": "lawyer"}, "law_firm"),
    ({"vertical": "ministry"}, "ministry"),
    ({"vertical": "consultant"}, "consultant"),
    ({"vertical": "contractor"}, "trades"),
    # aliases resolve through vertical_registry
    ({"vertical": "law_firm"}, "law_firm"),
    ({"vertical": "church"}, "ministry"),
    ({"vertical": "plumber"}, "trades"),
    ({"vertical": "coaching"}, "consultant"),
    # the salon family, which vertical_registry carries no aliases for
    ({"vertical": "barbershop"}, "salon"),
    ({"vertical": "hair_salon"}, "salon"),
])
def test_declared_vertical_decides(answers, expected):
    assert wa.classify(answers)["archetype"] == expected


@pytest.mark.parametrize("text,expected", [
    ("Two chairs, mostly walk-ins, everyone rebooks every four weeks.", "salon"),
    ("Family law. Filings, discovery deadlines, and an IOLTA trust account.", "law_firm"),
    ("Sunday services and midweek small groups; we follow up first-time guests.", "ministry"),
    ("Strategy engagements on retainer, deliverables against a scope of work.", "consultant"),
    ("Two crews in trucks, service calls, deposit up front and balance on completion.", "trades"),
])
def test_free_text_alone_is_enough(text, expected):
    """The vertical picker is often skipped or wrong. Prose has to carry
    the decision on its own."""
    assert wa.classify({"what_you_do": text})["archetype"] == expected


def test_an_empty_intake_still_gets_a_workspace():
    """A blank screen while we wait for better answers is worse than a
    defensible default the practitioner can change in one tap."""
    decision = wa.classify({})
    assert decision["archetype"] == wa.DEFAULT_ARCHETYPE
    assert decision["confidence"] == "none"
    assert decision["archetype"] in workspace_layouts.ARCHETYPES


def test_classify_never_raises_on_junk():
    for junk in ({}, {"vertical": None}, {"vertical": 7},
                 {"what_you_do": ["a", "b"]}, {"unknown_key": "x"}):
        decision = wa.classify(junk)
        assert decision["archetype"] in workspace_layouts.ARCHETYPES


def test_classification_is_deterministic():
    """Same intake, same workspace. A practitioner who re-runs onboarding
    and gets a different building is looking at a bug."""
    answers = {"vertical": "lawyer", "what_you_do": "Estate matters and filings."}
    picks = {wa.classify(answers)["archetype"] for _ in range(20)}
    assert picks == {"law_firm"}


def test_the_vertical_outweighs_a_stray_word():
    """A barber whose bio mentions 'we take a deposit for big colour jobs'
    must not become a trades business."""
    decision = wa.classify({
        "vertical": "personal_services",
        "what_you_do": "We take a deposit for big colour jobs.",
    })
    assert decision["archetype"] == "salon"


def test_confidence_falls_when_the_evidence_is_thin():
    strong = wa.classify({
        "vertical": "lawyer",
        "what_you_do": "Litigation matters, filings, court dates, IOLTA.",
    })
    thin = wa.classify({"what_you_do": "We help people."})
    assert strong["confidence"] == "high"
    assert thin["confidence"] in ("low", "none")


def test_structured_shape_answers_are_read():
    decision = wa.classify({
        "schedules_against": "crews",
        "unit_of_work": "job",
        "billing_shape": "deposit then balance",
    })
    assert decision["archetype"] == "trades"


# ─── showing the work ────────────────────────────────────────────────

def test_the_pick_carries_the_evidence_that_produced_it():
    """The override is only meaningful if the practitioner can see what
    Chief keyed on."""
    decision = wa.classify({
        "vertical": "ministry",
        "typical_week": "Sunday gatherings and midweek small groups.",
    })
    assert decision["evidence"], decision
    assert all(isinstance(e, str) and e for e in decision["evidence"])


def test_evidence_is_not_repeated():
    decision = wa.classify({
        "what_you_do": "Barbershop. A barber shop with chairs and walk-ins.",
    })
    assert len(decision["evidence"]) == len(set(decision["evidence"]))


def test_the_pick_carries_the_presets_rationale():
    decision = wa.classify({"vertical": "lawyer"})
    assert decision["rationale"] == workspace_layouts.get_preset("law_firm")["rationale"]


def test_alternatives_are_always_offered():
    """'The override is always visible' — so every decision ships the full
    set, not just the winner."""
    decision = wa.classify({"vertical": "lawyer"})
    assert {a["archetype"] for a in decision["alternatives"]} == set(
        workspace_layouts.ARCHETYPES
    )


def test_narration_never_leaks_internal_vocabulary():
    """Practitioners must never see archetype slugs, primitive names, or
    the word 'preset'. Chief is showing them a workspace, not a config."""
    leaks = ("archetype", "preset", "schema", "primitive", "timeline_day",
             "priority_docket", "week_grid", "attention_queue", "metric_row",
             "law_firm", "validator", "binding")
    for a in workspace_layouts.ARCHETYPES:
        decision = wa.classify({"vertical": workspace_layouts.get_preset(a)["vertical"]})
        text = wa.narrate(decision).lower()
        for leak in leaks:
            assert leak not in text, f"{a} narration leaked {leak!r}: {text}"


def test_low_confidence_narration_offers_the_runner_up():
    decision = wa.classify({"what_you_do": "We help people with things."})
    text = wa.narrate(decision)
    assert "switch" in text.lower() or "change it" in text.lower()


# ─── terminology: the row that is never overwritten ──────────────────

def test_preset_terminology_starts_as_preset_origin():
    layout = build_layout("law_firm", {})
    assert layout["terminology"]["project"] == {"value": "Matter", "origin": "preset"}


def test_a_user_override_survives_an_archetype_switch():
    """THE rule from the brief. Set once, permanent."""
    stored = {"project": {"value": "Case", "origin": "user_override"}}

    for archetype in workspace_layouts.ARCHETYPES:
        layout = build_layout(archetype, stored)
        assert layout["terminology"]["project"] == {
            "value": "Case", "origin": "user_override",
        }, archetype


def test_a_user_override_survives_reclassification():
    stored = {"contact": {"value": "Parishioner", "origin": "user_override"}}
    decision = wa.classify({"vertical": "ministry"})
    layout = build_layout(decision["archetype"], stored)
    assert layout["terminology"]["contact"]["value"] == "Parishioner"


def test_a_user_override_for_a_term_the_new_preset_has_no_opinion_on_survives():
    """The merge starts from the stored overrides, not from an intersection
    with the preset's keys — otherwise switching to an archetype that never
    mentions 'donor' silently drops the practitioner's word for it."""
    stored = {"donor": {"value": "Partner", "origin": "user_override"}}
    layout = build_layout("salon", stored)
    assert layout["terminology"]["donor"]["value"] == "Partner"


def test_a_preset_origin_row_in_storage_does_not_survive():
    """Only user_override is sticky. A stale preset row from the previous
    archetype must be replaced, or switching would carry old vocabulary
    forward forever."""
    stored = {"project": {"value": "Matter", "origin": "preset"}}
    layout = build_layout("trades", stored)
    assert layout["terminology"]["project"] == {"value": "Job", "origin": "preset"}


def test_a_blank_override_is_ignored():
    stored = {"project": {"value": "   ", "origin": "user_override"}}
    layout = build_layout("trades", stored)
    assert layout["terminology"]["project"]["value"] == "Job"


def test_merge_terminology_tolerates_junk_rows():
    stored = {"project": "Case", "client": None, "contact": 7}
    merged = merge_terminology(
        workspace_layouts.get_preset("trades")["terminology"], stored
    )
    assert merged["project"]["value"] == "Job"


def test_every_preset_names_the_unit_of_work_and_the_person():
    """The terminology map is not decoration — these are the two nouns every
    surface in the app renders."""
    for a in workspace_layouts.ARCHETYPES:
        terms = workspace_layouts.get_preset(a)["terminology"]
        assert "project" in terms, f"{a} does not name its unit of work"
        assert "contact" in terms, f"{a} does not name the person"


def test_the_five_presets_do_not_all_use_the_same_words():
    """Client vs Guest vs Customer, Matter vs Appointment vs Job vs
    Engagement. If these collapse, the workspace is a re-skin."""
    units = {a: workspace_layouts.get_preset(a)["terminology"]["project"]["value"]
             for a in workspace_layouts.ARCHETYPES}
    assert len(set(units.values())) == len(units), units

    people = {workspace_layouts.get_preset(a)["terminology"]["contact"]["value"]
              for a in workspace_layouts.ARCHETYPES}
    assert len(people) >= 3, people


# ─── every built layout is a valid layout ────────────────────────────

@pytest.mark.parametrize("archetype", workspace_layouts.ARCHETYPES)
def test_a_built_layout_still_validates(archetype):
    import workspace_layout_validator as validator
    stored = {"project": {"value": "Thing", "origin": "user_override"}}
    layout = build_layout(archetype, stored)
    result = validator.validate_layout(layout, business_id="biz-1")
    assert result.ok, result.errors


# ─── the constraint must know every preset ───────────────────────────

def test_the_db_constraint_lists_exactly_the_presets_that_exist():
    """The archetype CHECK and workspace_layouts/ must never disagree.

    They did, and it was invisible. The constraint allowed five values
    while seven presets shipped, so `therapist` and `nonprofit` passed
    the app-layer validator and were then rejected by Postgres with
    23514 -- and sb_clients returns None on 4xx, so the rejection never
    reached the practitioner OR the app. A therapist chose their
    workspace, got a success, and nothing was saved. Every load asked
    again.

    Widening the constraint by hand is exactly what was forgotten the
    first time, so this test reads the SQL rather than trusting anyone
    to remember.
    """
    import pathlib
    import re

    sql = pathlib.Path("supabase/APPLY-2026-08-27-workspace-archetype-widen.sql").read_text(
        encoding="utf-8")
    body = sql.split("workspace_archetype IN (", 1)[1].split(")", 1)[0]
    allowed = set(re.findall(r"'([a-z_]+)'", body))

    assert allowed == set(workspace_layouts.ARCHETYPES), (
        "the archetype CHECK and the preset folder disagree — "
        f"only in SQL: {sorted(allowed - set(workspace_layouts.ARCHETYPES))}, "
        f"only on disk: {sorted(set(workspace_layouts.ARCHETYPES) - allowed)}"
    )


def test_every_business_type_classifies_to_a_savable_archetype():
    """Classification that cannot be persisted is worse than none.

    Walks the real `businesses.type` values through the classifier and
    asserts each lands on a preset the database will actually accept.
    """
    import pathlib
    import re

    sql = pathlib.Path("supabase/APPLY-2026-08-27-workspace-archetype-widen.sql").read_text(
        encoding="utf-8")
    body = sql.split("workspace_archetype IN (", 1)[1].split(")", 1)[0]
    allowed = set(re.findall(r"'([a-z_]+)'", body))

    # Every DISTINCT businesses.type present in production on 2026-08-27,
    # read off the live table rather than imagined. `nonprofit` is in
    # there, which is why the too-narrow CHECK was not hypothetical.
    # `therapist` and `contractor` are not live yet but ship as presets,
    # and the two unregistered strings prove the fallback also lands
    # somewhere savable.
    for vertical in ["agency", "coach", "consultant", "course_creator",
                     "creative", "custom", "ecommerce", "lawyer", "ministry",
                     "nonprofit", "personal_services", "saas",
                     "service_provider", "therapist", "contractor",
                     "barbershop", "food_truck"]:
        archetype = wa.classify({"vertical": vertical})["archetype"]
        assert archetype in workspace_layouts.ARCHETYPES, (
            f"{vertical} classifies to {archetype!r}, which has no preset")
        assert archetype in allowed, (
            f"{vertical} classifies to {archetype!r}, which the database "
            f"would reject — the write would fail silently")


def test_only_one_place_writes_the_archetype_column():
    """One write path, so there is no second place to forget.

    There were two `_persist` functions — one in the router, one in the
    Chief actions module — doing the same PATCH. That duplication is how
    the silent-write bug survived: the archetype CHECK rejected two
    presets, sb_clients swallowed the 4xx, and both copies ignored the
    return value. Fixing either one alone would have left the other, and
    the other was the one Chief actually calls.
    """
    import pathlib
    import re

    writers = []
    for path in pathlib.Path(".").glob("workspace_*.py"):
        writers += [(path.name, i) for i, line in
                    enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                    if "workspace_archetype" in line and "sb_patch" in line]
    for path in [pathlib.Path("chief_workspace_actions.py"),
                 pathlib.Path("workspace_composer_router.py")]:
        text = path.read_text(encoding="utf-8")
        # A PATCH whose body sets workspace_archetype, however it is spelled.
        for m in re.finditer(r"sb_patch_as_service\((.{0,400}?)\)\n", text, re.S):
            if "workspace_archetype" in m.group(1):
                writers.append((path.name, text[:m.start()].count("\n") + 1))

    assert len(writers) == 1, (
        "workspace_archetype is written in more than one place: "
        f"{writers} — collapse them onto composer._persist, which is the "
        "only one that proves the write landed")
    assert writers[0][0] == "workspace_composer_router.py", writers


# ─── the live types, and the ones we deliberately refuse ──────────────
# Every value `businesses.type` actually held in production on
# 2026-08-27, with the archetype each is expected to lean at. This is a
# census, not a wishlist: `agency` was the single most common live type
# and carried no lean at all, so six real businesses scored on stray
# keywords alone. A new type reaching production without a decision here
# is exactly the drift this pins down.
#
# The frontend keeps the same census in `canonicalType`
# (solutionist-studio: src/core/intelligence/verticalDesks.ts). Two repos,
# one mapping — when you add a row here, add it there.
LIVE_TYPES_LEAN = {
    "agency": "consultant",
    "creative": "consultant",
    "course_creator": "consultant",
    "service_provider": "consultant",
    "coach": "consultant",
    "consultant": "consultant",
    "lawyer": "law_firm",
    "personal_services": "salon",
    "ministry": "ministry",
    "nonprofit": "nonprofit",
}

# Refused on purpose. Each sells something no archetype reads: orders and
# stock, or subscriptions and churn. `custom` names nothing at all. They
# get the default WITH `confidence: none`, which is the honest answer —
# handing someone a docket built for engagements would be worse than
# admitting we do not know.
DELIBERATELY_UNMAPPED = ("ecommerce", "saas", "custom")


@pytest.mark.parametrize("declared,expected", sorted(LIVE_TYPES_LEAN.items()))
def test_every_live_business_type_leans_somewhere(declared, expected):
    lean = wa.VERTICAL_LEAN.get(declared)
    direct = workspace_layouts.for_vertical(declared)
    assert lean or direct, f"{declared!r} is stored in production with no archetype"
    top = max(lean, key=lean.get) if lean else direct
    assert top == expected
    assert wa.classify({"type": declared})["archetype"] == expected


@pytest.mark.parametrize("declared", DELIBERATELY_UNMAPPED)
def test_a_refused_type_says_so_rather_than_guessing(declared):
    """It still gets a workspace — it just does not claim to be sure."""
    pick = wa.classify({"type": declared})
    assert pick["archetype"] == wa.DEFAULT_ARCHETYPE
    assert pick["confidence"] == "none", (
        f"{declared!r} scored evidence it should not have — a refused type "
        "that reports confidence is a wrong answer wearing a right one"
    )
