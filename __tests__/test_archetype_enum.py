"""
test_archetype_enum.py — the archetype enum stays closed and stays honest.

The readiness audit found the enum stuck at two members: booking_calendar and
fallback_generic. Every vertical's signature workflow therefore rendered as a
generic table with a banner saying an archetype was owed — the discipline was
being followed, it just had nothing to dispatch to.

work_pipeline is the third, and it is ONE archetype covering four verticals'
workflows because those four turned out to be the same shape:

  lawyer      Matter      contractor  Job
  creative    Project     consultant  Engagement

These tests guard the two ways that goes wrong: a suggestion pointing at an
archetype that does not exist (dispatch silently falls back and the
practitioner gets a table), and work_pipeline quietly becoming the dumping
ground for every module nobody wants to build properly.
"""
from __future__ import annotations

import pytest

import module_spec_generator as msg
import vertical_intelligence as vi
import vertical_registry


def _all_suggestions():
    for vertical in vertical_registry.canonical_keys():
        for m in vi.get_module_suggestions(vertical):
            yield vertical, m


# ─── the enum is real ────────────────────────────────────────────────

def test_event_roster_is_registered():
    assert "event_roster" in msg.ARCHETYPE_METADATA


def test_event_roster_is_suggestable():
    assert "event_roster" in msg.suggestable_archetypes()


def test_event_roster_is_not_single_instance():
    """A church runs a weekly serving roster AND one-off event RSVPs. Both
    are this archetype and both must be able to exist."""
    assert "event_roster" not in msg._SINGLE_INSTANCE_ARCHETYPES


@pytest.mark.parametrize("vertical,slug", [
    ("ministry",  "event-rsvp"),
    ("ministry",  "serving-roster"),
    ("nonprofit", "event-rsvp"),
    ("nonprofit", "volunteer-roster"),
])
def test_occasions_use_the_roster(vertical, slug):
    """The audit found ministries had event RSVP on the generic fallback and
    NO volunteer roster suggestion at all. Both now exist."""
    match = next((m for m in vi.get_module_suggestions(vertical)
                  if m.get("slug") == slug), None)
    assert match, f"{vertical} no longer suggests {slug}"
    assert match["archetype"] == "event_roster"


def test_roster_and_pipeline_are_not_the_same_archetype():
    """The distinction that justifies two archetypes: work_pipeline is many
    items each holding ONE stage; event_roster is ONE occasion holding MANY
    people. If a future sweep collapses them, this is the tripwire."""
    assert "event_roster" != "work_pipeline"
    assert msg.ARCHETYPE_METADATA["event_roster"]["label"] !=         msg.ARCHETYPE_METADATA["work_pipeline"]["label"]


def test_no_occasion_suggestion_landed_on_the_pipeline():
    """RSVPs and rosters must never be routed to work_pipeline — that would
    render every attendee as a card in an 'attending' column."""
    for vertical, m in _all_suggestions():
        slug = m.get("slug") or ""
        if "rsvp" in slug or "roster" in slug:
            assert m["archetype"] == "event_roster", (
                f"{vertical}/{slug} is an occasion but uses "
                f"{m['archetype']}")


def test_work_pipeline_is_registered():
    assert "work_pipeline" in msg.ARCHETYPE_METADATA


def test_work_pipeline_is_suggestable():
    """An archetype Chief cannot suggest is one no business will ever get."""
    assert "work_pipeline" in msg.suggestable_archetypes()


def test_fallback_is_never_suggestable():
    """The whole point of fallback_generic is that it means 'no archetype
    fits yet'. Suggesting it would be suggesting a gap."""
    assert "fallback_generic" not in msg.suggestable_archetypes()


def test_work_pipeline_is_not_single_instance():
    """booking_calendar is single-instance because a business has one
    calendar. That reasoning does not carry: a firm can legitimately run
    Matters AND a separate Referrals pipeline."""
    assert "work_pipeline" not in msg._SINGLE_INSTANCE_ARCHETYPES


# ─── suggestions point at archetypes that exist ──────────────────────

def test_every_suggested_archetype_is_registered():
    """The failure this catches is quiet: dispatch falls back to a generic
    table and the practitioner never learns the suggestion was broken."""
    bad = [(v, m.get("slug"), m.get("archetype"))
           for v, m in _all_suggestions()
           if m.get("archetype") not in msg.ARCHETYPE_METADATA]
    assert not bad, f"suggestions naming unknown archetypes: {bad}"


def test_every_suggestion_names_an_archetype_at_all():
    missing = [(v, m.get("slug")) for v, m in _all_suggestions()
               if not m.get("archetype")]
    assert not missing, f"suggestions with no archetype: {missing}"


# ─── the four that moved ─────────────────────────────────────────────

@pytest.mark.parametrize("vertical,slug", [
    ("lawyer",     "matter-tracker"),
    ("contractor", "jobs"),
    ("contractor", "estimates"),
    # project-tracker belongs to CONSULTANT, not creative. I assumed creative
    # when writing this and the test caught it — worth leaving the note,
    # because "the creative vertical tracks projects" is the obvious wrong
    # guess and the next person will make it too.
    ("consultant", "project-tracker"),
])
def test_staged_work_uses_the_pipeline(vertical, slug):
    """These four are the same shape — work moving through stages — and are
    the reason the archetype exists."""
    match = next((m for m in vi.get_module_suggestions(vertical)
                  if m.get("slug") == slug), None)
    assert match, f"{vertical} no longer suggests {slug}"
    assert match["archetype"] == "work_pipeline"


@pytest.mark.parametrize("vertical,slug", [
    ("lawyer",     "intake-form"),
    ("therapist",  "superbills"),
])
def test_other_shapes_were_left_alone(vertical, slug):
    """A form and a receipt log are NOT staged work. Sweeping them in would
    make work_pipeline the dumping ground for anything unbuilt, which is how
    a closed enum stops meaning anything."""
    match = next((m for m in vi.get_module_suggestions(vertical)
                  if m.get("slug") == slug), None)
    assert match, f"{vertical} no longer suggests {slug}"
    assert match["archetype"] == "fallback_generic"


def test_fallback_suggestions_still_exist():
    """If NOTHING falls back any more, the banner that marks an owed
    archetype has stopped doing its job — more likely a sweep than real
    coverage."""
    fallbacks = [m for _, m in _all_suggestions()
                 if m.get("archetype") == "fallback_generic"]
    assert fallbacks, "every suggestion claims a real archetype — suspicious"


# ─── metadata shape ──────────────────────────────────────────────────

@pytest.mark.parametrize("key", [
    "config_surface", "daily_use_surface", "chief_can_suggest", "label",
])
def test_metadata_is_complete(key):
    for name, meta in msg.ARCHETYPE_METADATA.items():
        assert key in meta, f"{name} archetype metadata is missing {key}"


def test_unknown_archetype_resolves_to_the_fallback_and_does_not_raise():
    assert msg.archetype_metadata("not_a_real_archetype") == \
        msg.ARCHETYPE_METADATA["fallback_generic"]
    assert msg.archetype_metadata(None) == msg.ARCHETYPE_METADATA["fallback_generic"]


# ─── the enum ITSELF, not just the metadata (G03) ────────────────────
# The gap this file previously missed: ARCHETYPE_METADATA held four
# archetypes while the Literal the validator dispatches on held TWO —
# metadata-only assertions stayed green while work_pipeline and
# event_roster were unreachable. These assert on every copy of the enum
# so they cannot drift apart again.

from typing import get_args

EXPECTED_ARCHETYPES = {
    "fallback_generic", "booking_calendar", "work_pipeline", "event_roster",
    "agreement_ledger", "progress_tracker",
}


def test_the_literal_enum_holds_every_archetype():
    """This is the assertion whose absence made the gap invisible. A spec
    with archetype='work_pipeline' failed Pydantic validation at the
    Literal — before _validate_archetype ever ran."""
    assert set(get_args(msg.ArchetypeEnum)) == EXPECTED_ARCHETYPES


def test_enum_metadata_and_param_models_agree():
    """Three copies of the same closed set. Any drift between them is a
    silent unreachable archetype (Literal short), a KeyError at dispatch
    (param model missing), or a suggestion for nothing (metadata short)."""
    literal = set(get_args(msg.ArchetypeEnum))
    assert literal == set(msg.ARCHETYPE_METADATA.keys())
    assert literal == set(msg._ARCHETYPE_PARAM_MODELS.keys())


@pytest.mark.parametrize("name", sorted(EXPECTED_ARCHETYPES))
def test_prompt_palette_offers_every_archetype(name):
    """The LLM can only pick what the palette describes. work_pipeline
    existing in the enum but not the prompt = the model never emits it."""
    assert name in msg._SYSTEM_PROMPT, (
        f"{name} is in the enum but the LLM prompt palette never mentions it")


def test_prompt_has_no_unrendered_format_braces():
    """_SYSTEM_PROMPT is passed raw to the API (never .format()'d), so
    doubled braces would reach the model as literal '{{'."""
    assert "{{" not in msg._SYSTEM_PROMPT
    assert "}}" not in msg._SYSTEM_PROMPT


def test_booking_calendar_stays_the_only_single_instance():
    assert msg._SINGLE_INSTANCE_ARCHETYPES == frozenset({"booking_calendar"})


# ─── specs for the new archetypes actually validate ──────────────────

def _pipeline_spec(**overrides):
    base = {
        "slug": "matters", "name": "Matters", "description": "Active matters",
        "intake_excerpt": "track my matters", "reasoning": "staged work",
        "archetype": "work_pipeline",
        "archetype_params": {
            "stages": [
                {"id": "intake", "label": "Intake"},
                {"id": "active", "label": "Active"},
                {"id": "waiting", "label": "Waiting"},
                {"id": "closed", "label": "Closed", "done": True},
            ],
            "stage_field": "stage", "title_field": "title",
            "contact_field": "contact_id", "date_field": "next_deadline",
            "value_field": "matter_value", "item_noun": "Matter",
        },
        "schema": {"fields": [
            {"name": "title", "type": "text", "label": "Matter", "required": True},
            {"name": "stage", "type": "select", "label": "Stage",
             "options": ["intake", "active", "waiting", "closed"]},
            {"name": "contact_id", "type": "contact_link", "label": "Client"},
            {"name": "next_deadline", "type": "date", "label": "Next deadline"},
            {"name": "matter_value", "type": "number", "label": "Value"},
        ], "default_view": "board", "views": ["list", "board"],
            "board_column": "stage"},
    }
    base.update(overrides)
    return base


def _roster_spec(**overrides):
    base = {
        "slug": "event-rsvp", "name": "Event RSVPs",
        "description": "Who's coming to what",
        "intake_excerpt": "track RSVPs and volunteers",
        "reasoning": "one occasion, many people",
        "archetype": "event_roster",
        "archetype_params": {
            "title_field": "title", "date_field": "event_date",
            "location_field": "location", "capacity_field": "capacity",
            "signups_field": "signups",
            "roles": [
                {"id": "greeter", "label": "Greeter", "needed": 2},
                {"id": "sound", "label": "Sound"},
            ],
            "occasion_noun": "Event",
        },
        "schema": {"fields": [
            {"name": "title", "type": "text", "label": "Event", "required": True},
            {"name": "event_date", "type": "date", "label": "Date"},
            {"name": "location", "type": "text", "label": "Location"},
            {"name": "capacity", "type": "number", "label": "Capacity"},
        ]},
    }
    base.update(overrides)
    return base


def test_a_work_pipeline_spec_validates():
    spec = msg.ModuleSpec.model_validate(_pipeline_spec())
    assert spec.archetype == "work_pipeline"
    assert spec.archetype_params["stage_field"] == "stage"
    assert [s["id"] for s in spec.archetype_params["stages"]][-1] == "closed"


def test_an_event_roster_spec_validates():
    spec = msg.ModuleSpec.model_validate(_roster_spec())
    assert spec.archetype == "event_roster"
    assert spec.archetype_params["roles"][0]["needed"] == 2


def test_bare_params_are_fine_for_both():
    """Every param is optional by design — the frontend resolveParams()
    degrades to defaults. An unconfigured module must validate."""
    for build in (_pipeline_spec, _roster_spec):
        spec = msg.ModuleSpec.model_validate(build(archetype_params={}))
        assert spec.archetype in EXPECTED_ARCHETYPES


def test_dangling_pipeline_field_ref_is_rejected():
    with pytest.raises(Exception, match="not in schema.fields"):
        msg.ModuleSpec.model_validate(_pipeline_spec(
            archetype_params={"stage_field": "no_such_field"}))


def test_dangling_roster_field_ref_is_rejected():
    with pytest.raises(Exception, match="not in schema.fields"):
        msg.ModuleSpec.model_validate(_roster_spec(
            archetype_params={"date_field": "no_such_field"}))


def test_roster_signups_field_needs_no_schema_field():
    """signups is an entry.data array the roster UI manages — no FieldType
    can declare it, so requiring a schema field would reject every valid
    roster spec."""
    spec = msg.ModuleSpec.model_validate(_roster_spec(
        archetype_params={"signups_field": "signups"}))
    assert spec.archetype_params["signups_field"] == "signups"


def test_duplicate_stage_ids_are_rejected():
    with pytest.raises(Exception, match="duplicate ids"):
        msg.ModuleSpec.model_validate(_pipeline_spec(archetype_params={
            "stages": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]}))


# ─── end to end: a validated spec materializes with its archetype ────

import sb_clients as _sbc


def _materialize_harness(monkeypatch, spec_dict, biz_type):
    """Fake the Supabase seam under materialize_spec. Returns the list of
    (path, payload) POSTs so the test can inspect the custom_modules row."""
    posts = []

    def fake_get(path):
        if path.startswith("/module_specs"):
            return [{"id": "s1", "business_id": "b1", "status": "draft",
                     "draft_json": spec_dict}]
        if path.startswith("/businesses"):
            return [{"type": biz_type}]
        if path.startswith("/custom_modules?id=eq."):
            return [posts[0][1]] if posts else []
        return []  # no existing module by slug; no workflow defs

    def fake_post(path, payload):
        posts.append((path, payload))
        return [{"id": "m1", **payload}]

    monkeypatch.setattr(_sbc, "sb_get_as_service", fake_get)
    monkeypatch.setattr(_sbc, "sb_post_as_service", fake_post)
    monkeypatch.setattr(_sbc, "sb_patch_as_service", lambda *a, **k: [])
    return posts


def test_work_pipeline_materializes_end_to_end(monkeypatch):
    """The full lawyer path below the LLM: a spec that came through
    Pydantic validation (as propose does) lands in custom_modules with
    archetype + params intact — what ArchetypeDispatch renders from."""
    validated = msg.ModuleSpec.model_validate(_pipeline_spec())
    spec_dict = validated.model_dump(by_alias=True, exclude_none=False)
    posts = _materialize_harness(monkeypatch, spec_dict, "lawyer")

    res = msg.materialize_spec("s1")
    assert res["ok"] is True, res
    cm = next(p for path, p in posts if path == "/custom_modules")
    assert cm["archetype"] == "work_pipeline"
    assert cm["archetype_params"]["stage_field"] == "stage"
    assert cm["archetype_fallback_reason"] is None


def test_event_roster_materializes_end_to_end(monkeypatch):
    validated = msg.ModuleSpec.model_validate(_roster_spec())
    spec_dict = validated.model_dump(by_alias=True, exclude_none=False)
    posts = _materialize_harness(monkeypatch, spec_dict, "ministry")

    res = msg.materialize_spec("s1")
    assert res["ok"] is True, res
    cm = next(p for path, p in posts if path == "/custom_modules")
    assert cm["archetype"] == "event_roster"
    assert cm["archetype_params"]["roles"][0]["id"] == "greeter"


def test_second_work_pipeline_is_not_blocked(monkeypatch):
    """work_pipeline is NOT single-instance — a firm can run Matters AND a
    Referrals pipeline. The single-instance guard must not fire even when
    one pipeline already exists."""
    validated = msg.ModuleSpec.model_validate(
        _pipeline_spec(slug="referrals", name="Referrals"))
    spec_dict = validated.model_dump(by_alias=True, exclude_none=False)
    posts = _materialize_harness(monkeypatch, spec_dict, "lawyer")

    res = msg.materialize_spec("s1")
    assert res["ok"] is True
    assert res.get("error") != "multi_module_not_supported"
    assert any(path == "/custom_modules" for path, _ in posts)


# ─── proactive suggestions carry the archetype through (G03 bonus bug) ─

import chief_proactive_suggestions as cps


def test_explicit_archetype_wins_over_the_slug_heuristic():
    """The bug: vertical_intelligence declared archetype on every
    suggestion, and the emit path STRIPPED it and re-derived via a
    booking-words-only heuristic — so matter-tracker (work_pipeline)
    resolved to fallback_generic and was filtered. Explicit must win."""
    assert cps._resolve_archetype(
        {"module_slug": "matter-tracker", "archetype": "work_pipeline"}
    ) == "work_pipeline"
    assert cps._resolve_archetype(
        {"module_slug": "serving-roster", "archetype": "event_roster"}
    ) == "event_roster"


def test_heuristic_is_only_the_fallback_for_archetypeless_rows():
    """business_type_module_blueprint rows carry no archetype column yet —
    those still resolve through the conservative slug heuristic."""
    assert cps._resolve_archetype({"module_slug": "bookings"}) == "booking_calendar"
    assert cps._resolve_archetype({"module_slug": "inventory"}) == "fallback_generic"
    assert cps._resolve_archetype(
        {"module_slug": "bookings", "archetype": ""}) == "booking_calendar"


def _emit_harness(monkeypatch):
    inserted = []

    def fake_get(path):
        return []  # no actives, no blueprint rows, no modules, no dupes

    def fake_post(path, payload):
        inserted.append(payload)
        return [{"id": f"sug-{len(inserted)}", **payload}]

    monkeypatch.setattr(_sbc, "sb_get_as_service", fake_get)
    monkeypatch.setattr(_sbc, "sb_post_as_service", fake_post)
    return inserted


def test_a_lawyer_gets_a_work_pipeline_suggestion(monkeypatch):
    """Before the fix this emitted only the booking suggestion: the
    matter-tracker row lost its archetype and fell to the NT8e filter."""
    inserted = _emit_harness(monkeypatch)
    n = cps.maybe_emit_proactive_suggestions({"id": "b1", "type": "lawyer"})
    assert n >= 2
    archetypes = {r["archetype"] for r in inserted}
    assert "work_pipeline" in archetypes


def test_a_ministry_gets_event_roster_suggestions(monkeypatch):
    """Before the fix ministries got ZERO proactive module suggestions —
    nothing in their profile matched the booking-words heuristic."""
    inserted = _emit_harness(monkeypatch)
    n = cps.maybe_emit_proactive_suggestions({"id": "b1", "type": "ministry"})
    assert n >= 1
    assert "event_roster" in {r["archetype"] for r in inserted}


def test_fallback_generic_suggestions_are_still_filtered(monkeypatch):
    """Passing the archetype through must NOT open the door to suggesting
    the fallback — lawyer's intake-form (fallback_generic) stays unemitted."""
    inserted = _emit_harness(monkeypatch)
    cps.maybe_emit_proactive_suggestions({"id": "b1", "type": "lawyer"})
    assert "fallback_generic" not in {r["archetype"] for r in inserted}


# ─── agreement_ledger (2026-09-01) ───────────────────────────────────
# The blueprint audit found six verticals tracking a signature by hand in
# a generic table: creative/service_provider agreements, lawyer
# engagement-letters, course_creator terms, fitness_wellness waivers,
# financial_educator disclosures. Same shape as each other and as nothing
# else in the enum — a document attached to a person that is either
# signed or is not, and that sometimes stops being valid.


def test_agreement_ledger_is_registered_and_suggestable():
    assert "agreement_ledger" in msg.ARCHETYPE_METADATA
    assert "agreement_ledger" in msg.suggestable_archetypes()


def test_agreement_ledger_is_not_single_instance():
    """A gym runs liability waivers AND photo-release consents; a firm runs
    engagement letters AND NDAs. Both are this archetype."""
    assert "agreement_ledger" not in msg._SINGLE_INSTANCE_ARCHETYPES


def test_agreement_ledger_is_not_the_pipeline():
    """The distinction that justifies a fifth archetype: a signature is a
    FACT WITH A DATE, not a stage. Modelling it as a pipeline would make
    'signed' a column you drag into, which is exactly wrong — nobody drags
    a client into having signed."""
    assert (msg.ARCHETYPE_METADATA["agreement_ledger"]["label"]
            != msg.ARCHETYPE_METADATA["work_pipeline"]["label"])


def _agreement_spec(**overrides):
    base = {
        "slug": "waivers", "name": "Waivers",
        "description": "Liability waivers and when they lapse",
        "intake_excerpt": "everyone signs a waiver before their first session",
        "reasoning": "a document that is signed or is not, and expires",
        "archetype": "agreement_ledger",
        "archetype_params": {
            "title_field": "waiver_type", "party_field": "contact_id",
            "signed_field": "signed_date", "expires_field": "expires",
            "expiring_soon_days": 30, "item_noun": "Waiver",
        },
        "schema": {"fields": [
            {"name": "waiver_type", "type": "text", "label": "Waiver", "required": True},
            {"name": "contact_id", "type": "contact_link", "label": "Client"},
            {"name": "signed_date", "type": "date", "label": "Signed"},
            {"name": "expires", "type": "date", "label": "Expires"},
        ], "default_view": "list", "views": ["list"]},
    }
    base.update(overrides)
    return base


def test_an_agreement_ledger_spec_validates():
    spec = msg.ModuleSpec.model_validate(_agreement_spec())
    assert spec.archetype == "agreement_ledger"
    assert spec.archetype_params["signed_field"] == "signed_date"


def test_bare_agreement_params_are_fine():
    """Every param optional — the frontend resolveParams() degrades to the
    conventional names. An unconfigured module must validate."""
    spec = msg.ModuleSpec.model_validate(_agreement_spec(archetype_params={}))
    assert spec.archetype == "agreement_ledger"


def test_dangling_agreement_field_ref_is_rejected():
    """Higher stakes than the other archetypes' dangling refs: a
    signed_field naming a missing key does not render a blank column, it
    reads as 'nobody has signed anything' and turns the whole module into
    one long unsigned list."""
    with pytest.raises(Exception, match="not in schema.fields"):
        msg.ModuleSpec.model_validate(_agreement_spec(
            archetype_params={"signed_field": "no_such_field"}))


def test_nonsense_warning_window_is_rejected():
    for bad in (0, -5):
        with pytest.raises(Exception, match="positive"):
            msg.ModuleSpec.model_validate(_agreement_spec(
                archetype_params={"expiring_soon_days": bad}))


def test_agreement_ledger_materializes_end_to_end(monkeypatch):
    validated = msg.ModuleSpec.model_validate(_agreement_spec())
    spec_dict = validated.model_dump(by_alias=True, exclude_none=False)
    posts = _materialize_harness(monkeypatch, spec_dict, "fitness_wellness")

    res = msg.materialize_spec("s1")
    assert res["ok"] is True, res
    cm = next(p for path, p in posts if path == "/custom_modules")
    assert cm["archetype"] == "agreement_ledger"
    assert cm["archetype_params"]["expires_field"] == "expires"
    assert cm["archetype_fallback_reason"] is None
