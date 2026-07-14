"""
test_vertical_registry.py — guards the vertical taxonomy against drift.

The five vertical maps drifted apart historically (a key added to one but
not the others → silently generic behavior). vertical_registry.CANONICAL is
now the single source of truth. This test asserts the importable Python maps
agree with it, so a future edit that adds a vertical to intelligence or
terminology WITHOUT registering it fails here instead of shipping a
half-wired vertical.

Only the Python/importable maps are checked (Chief intelligence, terminology,
family). The SQL/TS maps (DB constraint, onboarding picker, blueprint seed)
live in .sql/.tsx and are documented in the registry's coverage notes; they
are reconciled by the vertical-completion arcs, not asserted here.
"""
import vertical_registry as reg
import vertical_intelligence as vi
import vertical_terminology as vt


_ALIAS = reg.alias_to_canonical()


def _canonical_or_alias(keys):
    """Every key must resolve to a canonical vertical (be canonical or a
    registered alias). Returns the set of offenders."""
    return {k for k in keys if k not in _ALIAS}


def test_intelligence_keys_are_registered():
    """No Chief-intelligence profile for a vertical the registry doesn't know."""
    offenders = _canonical_or_alias(vi.VERTICAL_INTELLIGENCE.keys())
    assert not offenders, (
        f"vertical_intelligence has unregistered keys {offenders}. "
        f"Add them to vertical_registry.CANONICAL (or as an alias).")


def test_terminology_keys_are_registered():
    """No terminology override for a vertical the registry doesn't know."""
    offenders = _canonical_or_alias(vt.VERTICAL_TERMS.keys())
    assert not offenders, (
        f"vertical_terminology has unregistered keys {offenders}. "
        f"Add them to vertical_registry.CANONICAL (or as an alias).")


def test_intel_coverage_matches_registry():
    """Every canonical vertical NOT listed as an intel KNOWN_GAP must have a
    real (non-GENERIC) Chief-intelligence profile. Catches a vertical that
    silently falls back to generic voice."""
    missing = []
    for key in reg.canonical_keys():
        gap = reg.KNOWN_GAPS.get(key, {})
        if "intel" in gap:
            continue  # documented gap (incl. intentionally-GENERIC verticals)
        prof = vi.VERTICAL_INTELLIGENCE.get(key)
        if prof is None or prof is vi.GENERIC:
            missing.append(key)
    assert not missing, (
        f"these canonical verticals have no real intelligence profile "
        f"(fall back to GENERIC) and aren't recorded as a KNOWN_GAP: {missing}")


def test_terminology_covers_canonical():
    """Every canonical vertical NOT a terminology KNOWN_GAP has a terminology
    entry (its own key or an alias key present in VERTICAL_TERMS)."""
    missing = []
    for key in reg.canonical_keys():
        gap = reg.KNOWN_GAPS.get(key, {})
        if "terminology" in gap:
            continue
        aliases = [key] + reg.CANONICAL[key].get("aliases", [])
        if not any(a in vt.VERTICAL_TERMS for a in aliases):
            missing.append(key)
    assert not missing, (
        f"these canonical verticals have no terminology entry and aren't a "
        f"KNOWN_GAP: {missing}")


def test_resolve_and_family_consistent():
    """resolve() maps aliases home; family_of delegates to vertical_family."""
    assert reg.resolve("coaching") == "coach"
    assert reg.resolve("law firm") == "lawyer"
    assert reg.resolve("church") == "ministry"
    assert reg.resolve("Non-Profit") == "nonprofit"
    assert reg.resolve("wat") == "custom"
    assert reg.family_of("ministry") == "nonprofit"
    assert reg.family_of("lawyer") == "legal"
    assert reg.family_of("coach") == "general"


def test_nonprofit_profile_now_real():
    """Leg 1 added the nonprofit profile — it must not be GENERIC."""
    prof = vi.VERTICAL_INTELLIGENCE.get("nonprofit")
    assert prof is not None and prof is not vi.GENERIC
    names = [o["name"] for o in prof["offering_suggestions"]]
    assert "Sponsorship" in names
