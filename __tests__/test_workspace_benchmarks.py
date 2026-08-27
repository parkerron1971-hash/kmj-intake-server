"""
Tests for the benchmark layer — the bands, the per-vertical key map, and
the one finding.

The thing under test here is mostly EDITORIAL. A band asserts to a
practitioner that the median salon rebooks at 52% and that 80% is what a
top performer clears; if that claim is wrong, or has no source attached,
the product is lying with a straight face. So these tests check the shape of
the claim as hard as they check the arithmetic.
"""
import pytest

import workspace_benchmarks as B
import workspace_layouts


# ─── the bands themselves ────────────────────────────────────────────

def test_every_band_carries_a_source():
    """A benchmark without attribution is a number we made up."""
    missing = [k for k, b in B.BANDS.items() if not b.get("source", "").strip()]
    assert not missing, f"unattributed bands: {missing}"


def test_every_band_carries_a_reading():
    """The figure is not the point — what to DO about it is. A bare
    percentage with no reading is a dashboard, and a dashboard is the
    thing this panel exists to not be."""
    missing = [k for k, b in B.BANDS.items() if len(b.get("reading", "")) < 40]
    assert not missing, f"bands with no plain-language reading: {missing}"


def test_every_band_declares_a_direction():
    directions = {b["direction"] for b in B.BANDS.values()}
    assert directions <= {B.HIGHER, B.LOWER}


def test_the_lower_is_better_bands_are_the_ones_we_expect():
    """Naming them explicitly, because a missing flag is a silent bug: the
    panel congratulates a practice for a 22% no-show rate on the grounds
    that 22 is a bigger number than 8."""
    lower = {k for k, b in B.BANDS.items() if b["direction"] == B.LOWER}
    assert "no_show_rate" in lower
    assert any("lockup" in k for k in lower)


def test_a_target_is_never_worse_than_the_published_average():
    """Aiming a practitioner at less than the industry median would be a
    strange thing for this product to do."""
    for key, band in B.BANDS.items():
        avg, target = band.get("average"), band.get("target")
        if avg is None or target is None:
            continue
        if band["direction"] == B.LOWER:
            assert target <= avg, f"{key}: target {target} worse than average {avg}"
        else:
            assert target >= avg, f"{key}: target {target} worse than average {avg}"


def test_a_band_with_no_published_average_says_so_in_its_source():
    """Some metrics genuinely have no industry figure. That is fine, and
    it has to be VISIBLE — the panel shows the source line underneath, so
    the absence has to be stated there rather than left blank."""
    for key, band in B.BANDS.items():
        if band.get("average") is None:
            assert "no industry benchmark" in band["source"].lower(), key


# ─── the per-vertical key map ────────────────────────────────────────

def test_every_key_in_the_map_has_a_band():
    for vertical, keys in B.KEYS_FOR_VERTICAL.items():
        for key in keys:
            assert key in B.BANDS, f"{vertical} names {key!r}, which has no band"


def test_an_unknown_vertical_gets_nothing_rather_than_a_default_set():
    """Measuring a food truck against salon numbers is worse than not
    measuring it at all. The panel simply does not render."""
    assert B.keys_for("food_truck") == []
    assert B.keys_for(None) == []
    assert B.keys_for("") == []


def test_the_map_is_keyed_the_way_the_desks_are_keyed():
    """A second mechanism for 'what vertical is this' is how the two drift
    apart. These are the desk's own keys — salons are `personal_services`,
    not `salon`."""
    assert "personal_services" in B.KEYS_FOR_VERTICAL
    assert "salon" not in B.KEYS_FOR_VERTICAL
    assert "lawyer" in B.KEYS_FOR_VERTICAL
    assert "law_firm" not in B.KEYS_FOR_VERTICAL


def test_keys_are_case_and_space_insensitive():
    assert B.keys_for("  Personal_Services ") == B.keys_for("personal_services")


def test_no_vertical_asks_for_more_than_a_panel_can_hold():
    """Four rows is what the panel draws. A fifth would either scroll or
    silently vanish, and both are worse than choosing."""
    for vertical, keys in B.KEYS_FOR_VERTICAL.items():
        assert len(keys) <= 4, f"{vertical} wants {len(keys)} rows"


# ─── the finding ─────────────────────────────────────────────────────

def _row(key, value):
    return dict(B.BANDS[key], key=key, value=value)


def test_the_finding_is_the_band_furthest_short_of_target():
    rows = [
        _row("utilization", 41),      # target 50 -> 18% short
        _row("realization", 86),      # target 92 -> ~6.5% short
        _row("collection", 91),       # target 95 -> ~4% short
    ]
    assert B.finding_for(rows)["key"] == "utilization"


def test_the_shortfall_is_normalised_across_scales():
    """41 against 50 is a bigger shortfall than 86 against 92, even though
    the raw distance is smaller. Without normalising, the panel always
    leads with whichever metric happens to have the largest units."""
    rows = [_row("utilization", 41), _row("realization", 86)]
    finding = B.finding_for(rows)
    assert finding["key"] == "utilization"
    assert finding["shortfall"] == pytest.approx(0.18, abs=0.001)


def test_a_lower_is_better_band_is_short_when_the_number_is_too_high():
    """A 22% no-show rate against an 8% target is a shortfall, not a win."""
    rows = [_row("no_show_rate", 22), _row("client_retention", 88)]
    finding = B.finding_for(rows)
    assert finding["key"] == "no_show_rate"
    assert finding["shortfall"] > 0


def test_a_lower_is_better_band_beating_its_target_is_not_a_finding():
    rows = [_row("no_show_rate", 5)]
    assert B.finding_for(rows) is None


def test_nothing_measured_yields_no_finding():
    """A finding invented from no data would be the most confident-sounding
    lie on the screen."""
    rows = [dict(B.BANDS["utilization"], key="utilization", value=None)]
    assert B.finding_for(rows) is None
    assert B.finding_for([]) is None


def test_a_business_beating_every_target_gets_no_finding():
    rows = [_row("utilization", 61), _row("collection", 99)]
    assert B.finding_for(rows) is None


def test_the_finding_carries_its_own_reading_and_source():
    """The headline has to be able to say WHY without a second lookup, and
    the citation travels with it — a finding is the most quotable thing on
    the page, so it is the last place an unsourced number may appear."""
    finding = B.finding_for([_row("first_time_fix", 61)])
    assert finding["reading"]
    assert finding["source"]
    assert finding["label"]
    assert finding["target"] is not None


# ─── the presets still line up ───────────────────────────────────────

def test_every_key_a_preset_binds_has_a_band():
    """A preset expecting four rows and getting three renders a panel with
    a hole in it. Caught here rather than on someone's screen."""
    for archetype in workspace_layouts.ARCHETYPES:
        layout = workspace_layouts.get_preset(archetype)
        for surface in layout["surfaces"]:
            if surface["primitive"] != "benchmark_panel":
                continue
            for name, binding in surface["bindings"].items():
                keys = (binding.get("filter") or {}).get("key") or []
                assert keys, f"{archetype}.{name} filters no keys"
                for key in keys:
                    assert key in B.BANDS, f"{archetype} binds {key!r} with no band"

                # A panel that says it will draw four rows and can only
                # fill three renders with a hole in it.
                expected = binding.get("expect_items")
                if expected is not None:
                    assert len(keys) == expected, (
                        f"{archetype} expects {expected} rows from {len(keys)} keys")
