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
