"""
Which desk a business opens on, and why.

An archetype says which ROOM a business is in. It cannot say what that
room should lead with this fortnight. Two law firms both resolve to
`law_firm`; one is drowning in filings and the other has not been paid
since June, and before variants existed they both got the docket.

The rules these tests hold to:

  * a pick must be JUSTIFIABLE in one sentence, or it is a guess
  * a user override is PERMANENT, exactly like terminology
  * the desk must not FLICKER when a number drifts across a line
  * an unknown variant DEGRADES to a working desk, never to a blank one
"""
from __future__ import annotations

import pytest

import workspace_benchmarks as B
import workspace_layout_picker as P
import workspace_layouts
import workspace_layout_validator as validator


def row(key, value):
    return dict(B.BANDS[key], key=key, value=value)


# ─── the layouts themselves ──────────────────────────────────────────

@pytest.mark.parametrize("variant", workspace_layouts.variants("law_firm"))
def test_every_variant_is_a_valid_layout(variant):
    """A variant is a layout, not a hint. It passes the same seven
    checks as the default or it does not ship."""
    layout = workspace_layouts.get_preset("law_firm", variant=variant)
    result = validator.validate_layout(layout, business_id=None)
    assert result.ok, [e["message"] for e in result.errors]


@pytest.mark.parametrize("variant", workspace_layouts.variants("law_firm"))
def test_every_variant_leads_with_something(variant):
    layout = workspace_layouts.get_preset("law_firm", variant=variant)
    leads = [s for s in layout["surfaces"] if s["role"] == "lead"]
    assert len(leads) == 1, f"{variant} has {len(leads)} lead surfaces"


def test_the_variants_actually_lead_with_different_things():
    """Four desks that all opened on the same surface would be four
    labels, not four desks."""
    leads = {}
    for v in workspace_layouts.variants("law_firm"):
        layout = workspace_layouts.get_preset("law_firm", variant=v)
        lead = [s for s in layout["surfaces"] if s["role"] == "lead"][0]
        leads[v] = lead["id"]
    assert len(set(leads.values())) == len(leads), leads


def test_every_variant_explains_itself():
    """Same rule the presets already follow. A layout with no argument
    behind it is a preference; these are product decisions."""
    for v in workspace_layouts.variants("law_firm"):
        layout = workspace_layouts.get_preset("law_firm", variant=v)
        assert len(layout.get("rationale", "")) > 120, v
        assert layout.get("suppressed"), f"{v} refuses nothing"


def test_variants_never_disagree_about_terminology_or_identity():
    """The desks differ in what they LEAD with, never in what is true.
    A firm that calls a project a Matter calls it that on all four."""
    base = workspace_layouts.get_preset("law_firm")
    for v in workspace_layouts.variants("law_firm"):
        layout = workspace_layouts.get_preset("law_firm", variant=v)
        assert layout["terminology"] == base["terminology"], v
        assert layout["identity"]["key"] == base["identity"]["key"], v
        assert layout["archetype"] == base["archetype"], v


def test_the_default_variant_is_the_plain_file():
    """The default keeps the bare `<archetype>.json` name, which is why
    this whole change touches no existing caller, test or row."""
    plain = workspace_layouts.get_preset("law_firm")
    named = workspace_layouts.get_preset("law_firm", variant="docket")
    assert plain == named


def test_an_archetype_with_one_layout_is_a_real_answer():
    """A variant should exist because a situation demands a different
    lead, not so every vertical has the same number of them."""
    assert workspace_layouts.variants("salon") == []
    assert workspace_layouts.get_preset("salon")["archetype"] == "salon"


# ─── the pick ────────────────────────────────────────────────────────

def test_a_healthy_firm_is_left_alone():
    r = P.pick("law_firm", [row("collection", 96), row("utilization", 49)])
    assert r["variant"] == "docket"
    assert r["origin"] == "default"


def test_collapsed_collection_opens_on_the_money():
    r = P.pick("law_firm", [row("collection", 39), row("utilization", 41)])
    assert r["variant"] == "ledger"
    assert r["origin"] == "chief"
    assert "39" in r["reason"] and "97" in r["reason"]


def test_unrecorded_time_opens_on_the_day():
    r = P.pick("law_firm", [row("collection", 95), row("utilization", 28)])
    assert r["variant"] == "diary"


def test_the_worst_band_wins_not_the_first():
    """Normalised, so bands on different scales compare. 39 against 97
    is a bigger failure than 41 against 50 even though both are short."""
    r = P.pick("law_firm", [row("utilization", 41), row("collection", 39)])
    assert r["variant"] == "ledger"


def test_every_pick_can_justify_itself_in_a_sentence():
    """If it cannot be said in one line it is a guess, and a guess
    should not move somebody's home screen."""
    for value in (39, 60, 80, 96):
        r = P.pick("law_firm", [row("collection", value)])
        assert r["reason"], value
        assert len(r["reason"]) < 260, value


# ─── the guarantees ──────────────────────────────────────────────────

def test_a_user_override_is_never_overruled():
    """Same rule as terminology, same reason: a choice the practitioner
    made carries information we could not compute."""
    r = P.pick("law_firm", [row("collection", 39)],
               stored={"variant": "diary", "origin": "user_override"})
    assert r["variant"] == "diary"
    assert r["origin"] == "user_override"


def test_an_override_still_hears_what_chief_would_have_said():
    """Honoured is not the same as silenced. The surface needs this to
    offer the way back."""
    r = P.pick("law_firm", [row("collection", 39)],
               stored={"variant": "diary", "origin": "user_override"})
    assert r["would_have_picked"] == "ledger"


def test_chief_does_not_overrule_itself_over_a_drift():
    """A desk that reverts the moment a number recovers is a desk that
    flickers, and a practitioner learns to distrust it."""
    r = P.pick("law_firm", [row("collection", 96)],
               stored={"variant": "ledger", "origin": "chief"})
    assert r["variant"] == "ledger"


def test_a_small_shortfall_does_not_move_anything():
    """Below the threshold the default stands. Moving a home screen
    over a two-point drift is a nervous desk."""
    target = B.BANDS["collection"]["target"]
    barely = target * (1 - (P.MOVE_THRESHOLD / 2))
    r = P.pick("law_firm", [row("collection", barely)])
    assert r["variant"] == "docket"


def test_a_stale_variant_degrades_to_a_working_desk():
    """The migration deliberately has NO check constraint on this
    column — a value written by an older build must render something."""
    layout = workspace_layouts.get_preset("law_firm", variant="retired-thing")
    assert layout["archetype"] == "law_firm"
    assert validator.validate_layout(layout, business_id=None).ok


def test_nothing_measured_still_opens_a_desk():
    r = P.pick("law_firm", [])
    assert r["variant"] == "docket"
    assert r["reason"]


def test_every_trigger_names_a_variant_that_exists():
    """A trigger pointing at a layout nobody wrote would move the
    furniture and leave the practitioner nowhere."""
    for archetype, triggers in P.TRIGGERS.items():
        known = workspace_layouts.variants(archetype)
        for key, t in triggers.items():
            assert key in B.BANDS, f"{archetype} triggers on unknown band {key!r}"
            assert t["variant"] in known, (
                f"{archetype}.{key} points at {t['variant']!r}, which does not exist")
            assert len(t["because"]) > 30, f"{archetype}.{key} does not explain itself"


# ─── the pick endpoints ──────────────────────────────────────────────

def test_clearing_the_variant_hands_the_choice_back():
    """The override must not be a one-way door.

    A practitioner who tried a desk once and could never get Chief to
    resume deciding would be worse off than one who was never offered
    the choice. `PUT /workspace/pick` with null clears both columns.
    """
    import workspace_composer_router as router
    assert "variant" in router.SetVariantBody.model_fields
    field = router.SetVariantBody.model_fields["variant"]
    assert field.default is None, "variant must be optional — null is the way back"


def test_the_pick_endpoints_are_owner_gated_like_everything_else():
    import inspect

    import workspace_composer_router as router
    for fn in (router.get_pick, router.set_pick):
        src = inspect.getsource(fn)
        assert "_require_owner" in src, f"{fn.__name__} is not owner-gated"


def test_setting_a_variant_verifies_its_own_write():
    """sb_clients returns None on a 4xx AND on a successful write with no
    body, so the return value cannot tell them apart. That ambiguity
    swallowed two verticals' archetype writes once."""
    import inspect

    import workspace_composer_router as router
    src = inspect.getsource(router.set_pick)
    assert "sb_get_as_service" in src, "set_pick does not read its write back"
    assert "did not persist" in src


def test_an_unknown_variant_is_refused_rather_than_stored():
    """A stale value already on a row degrades to the default, which is
    right. A NEW one arriving over HTTP is a caller bug and should be
    told so rather than written and quietly ignored forever."""
    import inspect

    import workspace_composer_router as router
    src = inspect.getsource(router.set_pick)
    assert "is_variant" in src
    assert "400" in src
