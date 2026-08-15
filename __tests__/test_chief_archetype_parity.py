"""A vertical with a profile must also have a thinking lens.

CHIEF_ARCHETYPE_LABELS carried a comment claiming its keys were
"identical keys to vertical_intelligence's distinct-profile verticals".
That was prose, not a check, and it was wrong for three of them:
nonprofit, therapist and contractor each had a full intelligence
profile — voice, hallmarks, taboo, offerings — and still fell through
to CHIEF_ARCHETYPE_FALLBACK, the "I don't recognize your archetype,
let me interview you" lens.

The practitioner-visible symptom is Chief interviewing a therapist
about how they work while already holding a profile that says to keep
clinical language out of every reply.

Two verticals fall through ON PURPOSE — service_provider and custom are
the generic buckets, and diagnosing beats assuming for those. That
exemption is the only one, and it is asserted here so adding a third
generic bucket is a deliberate edit rather than a silent widening.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos
import vertical_intelligence as vi

# The only verticals allowed to reach CHIEF_ARCHETYPE_FALLBACK.
DELIBERATELY_GENERIC = {"service_provider", "custom"}


def test_every_profiled_vertical_has_an_archetype_lens():
    profiled = set(vi.VERTICAL_INTELLIGENCE.keys())
    lensed = set(cos.CHIEF_ARCHETYPE_LABELS.keys())
    missing = profiled - lensed - DELIBERATELY_GENERIC
    assert not missing, (
        f"{sorted(missing)} have a vertical_intelligence profile but no "
        "archetype lens, so Chief will interview a practitioner it already "
        "understands"
    )


def test_labels_and_shifts_cover_the_same_verticals():
    """A label with no shift is a named lens that changes no thinking."""
    labels = set(cos.CHIEF_ARCHETYPE_LABELS.keys())
    shifts = set(cos.CHIEF_ARCHETYPE_SHIFTS.keys())
    assert labels == shifts, (
        f"label-only: {sorted(labels - shifts)}; "
        f"shift-only: {sorted(shifts - labels)}"
    )


def test_no_archetype_lens_without_a_profile():
    """The reverse drift: a lens for a vertical nothing else knows about."""
    orphans = set(cos.CHIEF_ARCHETYPE_LABELS.keys()) - set(vi.VERTICAL_INTELLIGENCE.keys())
    assert not orphans, f"archetype lens with no intelligence profile: {sorted(orphans)}"


def test_the_generic_buckets_still_fall_through():
    """The exemption must stay an exemption, not become the rule."""
    for generic in DELIBERATELY_GENERIC:
        assert generic in vi.VERTICAL_INTELLIGENCE, (
            f"{generic} is exempted here but no longer has a profile — "
            "this test's premise moved"
        )
        assert generic not in cos.CHIEF_ARCHETYPE_LABELS, (
            f"{generic} gained an archetype lens; if that is intended, take "
            "it out of DELIBERATELY_GENERIC rather than leaving this stale"
        )


def test_the_new_lenses_carry_their_vertical_s_boundary():
    """Each lens must name the thing that vertical must not do.

    Not a style check — these three are the ones that were missing, and
    a lens that omits the boundary is how a therapist archetype ends up
    reasoning clinically.
    """
    shifts = cos.CHIEF_ARCHETYPE_SHIFTS
    assert "restricted" in shifts["nonprofit"].lower()
    assert "guarantee" in shifts["nonprofit"].lower()

    therapist = shifts["therapist"].lower()
    assert "clinical" in therapist
    assert "session content" in therapist

    contractor = shifts["contractor"].lower()
    assert "license" in contractor
    assert "quote" in contractor
