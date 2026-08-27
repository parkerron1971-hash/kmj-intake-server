"""
One identity per vertical, read by both surfaces.

There used to be two answers to "what colour is a law firm". The desk
said gold; the composer preset said blue. That was true for SEVEN OF
SEVEN verticals. These tests exist so it cannot become true again.
"""
from __future__ import annotations

import glob
import io
import json

import pytest

import workspace_identity as I
import workspace_layouts


def _presets():
    for f in sorted(glob.glob("workspace_layouts/*.json")):
        yield json.load(io.open(f, encoding="utf-8"))


# ─── the reference, not the copy ─────────────────────────────────────

def test_no_preset_carries_its_own_palette():
    """A preset names an identity; it must not hold one.

    Each used to carry a 13-key palette of which 9 were byte-identical
    across all seven. That duplication is what let the composer drift
    away from the desk without anyone noticing.
    """
    offenders = [p["archetype"] for p in _presets()
                 if "theme" in p or "palette" in p]
    assert not offenders, f"presets carrying their own palette: {offenders}"


def test_every_preset_resolves_an_identity():
    for p in _presets():
        assert p.get("identity"), f"{p['archetype']} names no identity"
        assert p["identity"] in I.IDENTITIES, (
            f"{p['archetype']} names identity {p['identity']!r}, which does not exist")


def test_the_loader_attaches_the_resolved_identity_and_tokens():
    for archetype in workspace_layouts.ARCHETYPES:
        layout = workspace_layouts.get_preset(archetype)
        assert isinstance(layout["identity"], dict), archetype
        assert layout["identity"].get("mark"), archetype
        assert layout.get("identity_tokens"), archetype


# ─── identity is more than a hue ─────────────────────────────────────

def test_every_vertical_is_structurally_distinct():
    """Colour is the weakest differentiator, and two verticals here
    deliberately have none at all. If the structural combination were
    not unique, those two would be indistinguishable."""
    combos = {}
    for a in I.ARCHETYPE_TO_IDENTITY:
        d = I.for_archetype(a)
        combo = (d["density"], d["edge"], d["rule"], d["texture"], d["figure"])
        assert combo not in combos, (
            f"{a} and {combos[combo]} are structurally identical: {combo}")
        combos[combo] = a


def test_the_display_faces_stay_a_system_not_a_collection():
    """The desk caps display faces at three, in writing. The presets had
    drifted to five named families, which is a font collection."""
    used = {I.for_archetype(a)["display"] for a in I.ARCHETYPE_TO_IDENTITY}
    assert used <= set(I.FACES), used
    assert len(I.FACES) == 3, "the cap moved — was that deliberate?"


# ─── the two deliberate refusals ─────────────────────────────────────

@pytest.mark.parametrize("vertical", ["personal_services", "nonprofit"])
def test_the_verticals_that_defer_colour_still_defer_it(vertical):
    """A salon owner and a charity both arrive with a brand they did not
    ask us to overpaint. The desk refuses to impose one, in writing. The
    composer used to impose orange and pink respectively.

    If a future change gives either of these an accent, it should have
    to argue with this test first.
    """
    assert I.IDENTITIES[vertical]["accent"] is None, (
        f"{vertical} has been given an imposed accent — the desk "
        "deliberately leaves this to the practitioner's own design")


def test_a_deferring_vertical_emits_no_accent_token():
    for a, key in I.ARCHETYPE_TO_IDENTITY.items():
        toks = I.tokens(a)
        has = "--wk-accent" in toks
        want = I.IDENTITIES[key]["accent"] is not None
        assert has == want, f"{a}: accent token {has}, identity says {want}"


# ─── every identity is explained ─────────────────────────────────────

def test_every_identity_says_why_it_looks_the_way_it_does():
    """A palette with no argument behind it is a preference. These are
    product decisions and they carry their reasoning, the same way each
    preset's `suppressed` entries do."""
    for a in I.ARCHETYPE_TO_IDENTITY:
        why = I.for_archetype(a).get("why", "")
        assert len(why) > 80, f"{a} does not explain its design"


def test_tokens_are_all_css_custom_properties():
    for a in I.ARCHETYPE_TO_IDENTITY:
        for k in I.tokens(a):
            assert k.startswith("--wk-"), f"{a}: {k} is not a custom property"
