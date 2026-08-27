"""
test_workspace_layout_validator.py — the guardrail has to actually reject.

The validator is the only thing standing between a phase-two composed
layout and a practitioner's data. A validator that quietly repairs, or that
returns True on a schema it did not understand, is worse than no validator
at all: it converts a loud failure into a silent one.

So these tests malform a real preset one way at a time and assert the
SPECIFIC check catches it, with the specific code, at the specific path.
Asserting "it failed" would pass even if the wrong check fired for the wrong
reason.

Five malformations named in the brief get their own tests: unknown
primitive, missing required binding, a binding that reaches another
business_id, six surfaces, absent rationale.
"""
from __future__ import annotations

import copy
import json
import os

import pytest

import workspace_field_catalog as catalog
import workspace_layout_validator as validator
import workspace_layouts
import workspace_primitives as registry

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def salon():
    return workspace_layouts.get_preset("salon")


@pytest.fixture
def law():
    return workspace_layouts.get_preset("law_firm")


def _codes(result):
    return [e["code"] for e in result.errors]


def _find(result, code):
    return next((e for e in result.errors if e["code"] == code), None)


def _surface(layout, primitive):
    """Fetch a surface by primitive rather than by index. Presets gained
    surfaces when the benchmark view landed, and positional indexing made
    these tests assert against whichever surface happened to sit there."""
    return next(s for s in layout["surfaces"] if s["primitive"] == primitive)


# ─── the presets themselves ──────────────────────────────────────────

@pytest.mark.parametrize("archetype", workspace_layouts.ARCHETYPES)
def test_every_preset_validates(archetype):
    """If a hand-authored preset stops validating, everything downstream is
    already broken — this is the canary."""
    layout = workspace_layouts.get_preset(archetype)
    result = validator.validate_layout(layout, business_id=TENANT)
    assert result.ok, json.dumps(result.errors, indent=2)


@pytest.mark.parametrize("archetype", workspace_layouts.ARCHETYPES)
def test_every_preset_declares_what_it_left_out(archetype):
    """The brief requires `suppressed` on every preset, with reasons. A
    layout that only says what it kept cannot narrate what it removed."""
    layout = workspace_layouts.get_preset(archetype)
    assert layout["suppressed"], f"{archetype} suppresses nothing"
    for entry in layout["suppressed"]:
        assert registry.exists(entry["primitive"])
        assert len(entry["reason"].strip()) > 20, "a reason, not a shrug"


def test_no_two_archetypes_are_the_same_workspace():
    """The product claim, stated for seven.

    Sharing a primitive is not a failure — that is what a registry is FOR,
    and forcing seven verticals onto seven different primitives would be
    the design failing, not succeeding. Ministry and therapist both lead
    with a week because both genuinely run on one.

    What must never happen is two archetypes being the SAME workspace: same
    primitives, same roles, and the same options driving them. If that ever
    holds, one of the two is a re-skin and should not exist."""
    fingerprints = {}
    for a in workspace_layouts.ARCHETYPES:
        p = workspace_layouts.get_preset(a)
        fingerprints[a] = json.dumps(
            sorted(
                (s["primitive"], s["role"], json.dumps(s.get("options") or {},
                                                       sort_keys=True))
                for s in p["surfaces"]
            ),
            sort_keys=True,
        )
    dupes = [a for a in fingerprints
             if list(fingerprints.values()).count(fingerprints[a]) > 1]
    assert not dupes, f"these archetypes are the same workspace twice: {dupes}"


def test_archetypes_that_share_a_lead_still_differ_in_how_it_reads():
    """Salon and trades both lead with a timeline; ministry and therapist
    both lead with a week. Each pair has to differ in the options that make
    the surface read differently, or the second one is decoration."""
    by_lead = {}
    for a in workspace_layouts.ARCHETYPES:
        p = workspace_layouts.get_preset(a)
        lead = next(s for s in p["surfaces"] if s["role"] == "lead")
        by_lead.setdefault(lead["primitive"], []).append((a, lead.get("options") or {}))

    for primitive, entries in by_lead.items():
        if len(entries) < 2:
            continue
        seen = set()
        for archetype, options in entries:
            key = json.dumps(options, sort_keys=True)
            assert key not in seen, (
                f"{archetype} leads with {primitive} on identical options to "
                f"another archetype — one of them is a re-skin"
            )
            seen.add(key)


def test_no_two_presets_lead_with_the_same_primitive_and_options():
    """Salon and trades both lead with timeline_day — that is deliberate and
    allowed. What is NOT allowed is them being the same board: chairs and
    crews must differ in the options that make them read differently."""
    salon = workspace_layouts.get_preset("salon")["surfaces"][0]["options"]
    trades = workspace_layouts.get_preset("trades")["surfaces"][0]["options"]
    assert salon["lane_noun"] != trades["lane_noun"]
    assert salon["gap_threshold_minutes"] != trades["gap_threshold_minutes"]
    assert (salon["day_start"], salon["day_end"]) != (trades["day_start"], trades["day_end"])


# ─── check 1: primitive_exists ───────────────────────────────────────

def test_unknown_primitive_is_rejected(salon):
    salon["surfaces"][0]["primitive"] = "gantt_chart"
    result = validator.validate_layout(salon, business_id=TENANT)

    assert not result.ok
    err = _find(result, "unknown_primitive")
    assert err is not None, _codes(result)
    assert err["check"] == "primitive_exists"
    assert err["path"] == "surfaces[0].primitive"
    assert err["value"] == "gantt_chart"


def test_unknown_primitive_does_not_cascade(salon):
    """A surface whose primitive is unknown is skipped for checks 2-5.
    Otherwise one typo produces a dozen 'unknown binding' errors that the
    author cannot act on."""
    salon["surfaces"][0]["primitive"] = "gantt_chart"
    result = validator.validate_layout(salon, business_id=TENANT)

    surface_0 = [e for e in result.errors if e["path"].startswith("surfaces[0]")]
    assert len(surface_0) == 1, [e["code"] for e in surface_0]


def test_the_primitive_set_is_closed(salon):
    """The closed-set assertion. Phase one shipped six; `benchmark_panel`
    is the deliberate seventh, added when the metric research showed that a
    figure without its band is noise and metric_row could not carry one
    (it is footer material by contract, and these numbers lead the
    argument). An eighth requires editing this line on purpose."""
    assert set(registry.ids()) == {
        "timeline_day", "priority_docket", "week_grid", "attention_queue",
        "benchmark_panel", "metric_row", "ledger",
    }


def test_benchmark_panel_may_never_lead():
    """A workspace that opens on a scorecard has handed the practitioner a
    report. The panel is a view ON the work; the work leads."""
    assert "lead" not in registry.PRIMITIVES["benchmark_panel"]["allowed_roles"]


@pytest.mark.parametrize("archetype", workspace_layouts.ARCHETYPES)
def test_every_benchmark_row_is_attributable(archetype):
    """A benchmark asserted without a source is a number we made up. Every
    panel binds `reading` and `source`, so the panel can always say where a
    band came from."""
    layout = workspace_layouts.get_preset(archetype)
    for surface in layout["surfaces"]:
        if surface["primitive"] != "benchmark_panel":
            continue
        fields = surface["bindings"]["rows"]["fields"]
        assert "reading" in fields, f"{archetype} panel has no plain-language reading"
        assert "source" in fields, f"{archetype} panel cannot attribute its bands"


def test_every_archetype_carries_a_benchmark_view():
    """The added view is the point of this pass — every vertical gets one."""
    for a in workspace_layouts.ARCHETYPES:
        p = workspace_layouts.get_preset(a)
        assert any(s["primitive"] == "benchmark_panel" for s in p["surfaces"]), a


def test_a_refusal_must_explain_itself(salon):
    """`refused` is the capability-level companion to `suppressed` — the
    therapist's clinical-notes boundary is the case it exists for. An
    unexplained refusal reads as a missing feature."""
    salon["refused"] = [{"what": "Something", "reason": "no"}]
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "missing_refusal_reason") is not None, _codes(result)


def test_the_therapist_refuses_clinical_notes():
    """The narrowed launch (vertical_scope.py) is a legal posture, not a
    backlog item. It has to be visible in the workspace, with its reason."""
    therapist = workspace_layouts.get_preset("therapist")
    refusals = therapist.get("refused") or []
    assert refusals, "therapist must state its clinical boundary"
    text = " ".join(r["reason"] for r in refusals).lower()
    assert "hipaa" in text and "business associate" in text


# ─── check 2: contract_satisfied ─────────────────────────────────────

def test_missing_required_binding_is_rejected(salon):
    del salon["surfaces"][0]["bindings"]["events"]
    result = validator.validate_layout(salon, business_id=TENANT)

    err = _find(result, "missing_required_binding")
    assert err is not None, _codes(result)
    assert err["check"] == "contract_satisfied"
    assert err["path"] == "surfaces[0].bindings.events"


def test_missing_required_field_is_rejected(salon):
    """The binding is present but does not bind a field the primitive
    cannot render without."""
    del salon["surfaces"][0]["bindings"]["events"]["fields"]["start"]
    result = validator.validate_layout(salon, business_id=TENANT)

    err = _find(result, "missing_required_field")
    assert err is not None, _codes(result)
    assert err["path"] == "surfaces[0].bindings.events.fields.start"


def test_unknown_binding_name_is_rejected(salon):
    salon["surfaces"][0]["bindings"]["swimlanes"] = {
        "source": "contacts", "scope": "business", "fields": {"id": "id"},
    }
    result = validator.validate_layout(salon, business_id=TENANT)

    err = _find(result, "unknown_binding")
    assert err is not None, _codes(result)
    assert err["value"] == "swimlanes"


def test_unknown_contract_field_is_rejected(salon):
    salon["surfaces"][0]["bindings"]["events"]["fields"]["colour"] = "role"
    result = validator.validate_layout(salon, business_id=TENANT)

    err = _find(result, "unknown_contract_field")
    assert err is not None, _codes(result)
    assert err["value"] == "colour"


def test_metric_row_rejects_five_figures(law):
    """Two to four figures at rest. Five is a table."""
    _surface(law, "metric_row")["bindings"]["metrics"]["expect_items"] = 5
    result = validator.validate_layout(law, business_id=TENANT)

    err = _find(result, "too_many_items")
    assert err is not None, _codes(result)
    assert err["check"] == "contract_satisfied"


def test_metric_row_rejects_a_single_figure(law):
    _surface(law, "metric_row")["bindings"]["metrics"]["expect_items"] = 1
    result = validator.validate_layout(law, business_id=TENANT)
    assert _find(result, "too_few_items") is not None, _codes(result)


def test_stage_sort_requires_the_stage_field(law):
    """A docket sorted by stage with no stage bound is one undifferentiated
    pile. The consultant preset is the real user of this."""
    consultant = workspace_layouts.get_preset("consultant")
    del _surface(consultant, "priority_docket")["bindings"]["rows"]["fields"]["stage"]
    result = validator.validate_layout(consultant, business_id=TENANT)

    err = _find(result, "missing_conditional_field")
    assert err is not None, _codes(result)
    assert err["path"].endswith(".bindings.rows.fields.stage")


# ─── check 3: fields_resolve ─────────────────────────────────────────

def test_unknown_source_is_rejected(salon):
    salon["surfaces"][0]["bindings"]["events"]["source"] = "stylists"
    result = validator.validate_layout(salon, business_id=TENANT)

    err = _find(result, "unknown_source")
    assert err is not None, _codes(result)
    assert err["check"] == "fields_resolve"
    assert err["value"] == "stylists"


def test_column_that_does_not_exist_is_rejected(salon):
    salon["surfaces"][0]["bindings"]["events"]["fields"]["title"] = "nickname"
    result = validator.validate_layout(salon, business_id=TENANT)

    err = _find(result, "unresolvable_field")
    assert err is not None, _codes(result)
    assert err["value"] == "nickname"


def test_order_by_a_column_that_does_not_exist_is_rejected(salon):
    salon["surfaces"][0]["bindings"]["events"]["order"] = "priority.desc"
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "unresolvable_order_column") is not None, _codes(result)


def test_filter_on_a_column_that_does_not_exist_is_rejected(salon):
    salon["surfaces"][0]["bindings"]["events"]["filter"] = {"archived": False}
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "unresolvable_filter_column") is not None, _codes(result)


def test_field_bound_to_the_wrong_type_is_rejected(salon):
    """`age_days` is an int. Binding it to a name is not a resolution
    failure the renderer can recover from — it is a blank column."""
    salon["surfaces"][1]["bindings"]["items"]["fields"]["age_days"] = "name"
    result = validator.validate_layout(salon, business_id=TENANT)

    err = _find(result, "field_type_mismatch")
    assert err is not None, _codes(result)
    assert "age_days" in err["path"]


def test_unknown_derivation_is_rejected(salon):
    salon["surfaces"][1]["bindings"]["items"]["fields"]["age_days"] = {
        "column": "last_interaction", "derive": "moon_phase",
    }
    result = validator.validate_layout(salon, business_id=TENANT)

    err = _find(result, "unknown_derivation")
    assert err is not None, _codes(result)
    assert err["value"] == "moon_phase"


def test_derivation_on_the_wrong_column_type_is_rejected(salon):
    """days_since reads a date. Applied to a phone number it produces a
    number that means nothing."""
    salon["surfaces"][1]["bindings"]["items"]["fields"]["age_days"] = {
        "column": "phone", "derive": "days_since",
    }
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "derivation_type_mismatch") is not None, _codes(result)


def test_jsonb_leaves_are_allowed_through(law):
    """module_entries.data.* is practitioner-defined. The composer must not
    refuse a field the module spec just created."""
    assert catalog.column_exists("module_entries", "data.anything_at_all")
    result = validator.validate_layout(law, business_id=TENANT)
    assert result.ok, result.errors


# ─── check 4: tenant_scope ───────────────────────────────────────────

def test_binding_that_reaches_another_business_is_rejected(salon):
    """THE test. A layout is authored data, and authored data that names a
    table can name someone else's rows."""
    salon["surfaces"][0]["bindings"]["events"]["filter"]["business_id"] = OTHER_TENANT
    result = validator.validate_layout(salon, business_id=TENANT)

    err = _find(result, "cross_tenant_binding")
    assert err is not None, _codes(result)
    assert err["check"] == "tenant_scope"
    assert err["path"] == "surfaces[0].bindings.events.filter.business_id"
    assert err["value"] == OTHER_TENANT


def test_pinning_to_our_own_business_is_allowed(salon):
    """Redundant, but not an attack."""
    salon["surfaces"][0]["bindings"]["events"]["filter"]["business_id"] = TENANT
    result = validator.validate_layout(salon, business_id=TENANT)
    assert result.ok, result.errors


def test_a_pinned_tenant_with_no_tenant_supplied_is_rejected(salon):
    """Validating with no business_id must TIGHTEN check 4, not relax it —
    a pinned tenant column has nothing legitimate to match against."""
    salon["surfaces"][0]["bindings"]["events"]["filter"]["business_id"] = TENANT
    result = validator.validate_layout(salon, business_id=None)
    assert _find(result, "cross_tenant_binding") is not None, _codes(result)


def test_illegal_scope_is_rejected(salon):
    salon["surfaces"][0]["bindings"]["events"]["scope"] = "platform"
    result = validator.validate_layout(salon, business_id=TENANT)

    err = _find(result, "illegal_scope")
    assert err is not None, _codes(result)
    assert err["value"] == "platform"


def test_missing_scope_is_rejected(salon):
    del salon["surfaces"][0]["bindings"]["events"]["scope"]
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "illegal_scope") is not None, _codes(result)


@pytest.mark.parametrize("smuggled", [
    "neq.cancelled",
    "in.(a,b)",
    "confirmed&business_id=eq.22222222-2222-2222-2222-222222222222",
    "or(business_id.eq.x)",
    "*",
])
def test_postgrest_fragments_in_a_filter_are_rejected(salon, smuggled):
    """A filter value is a literal. The moment it can carry an operator,
    the tenant pin above is decoration."""
    salon["surfaces"][0]["bindings"]["events"]["filter"]["status"] = smuggled
    result = validator.validate_layout(salon, business_id=TENANT)

    err = _find(result, "raw_filter_expression")
    assert err is not None, f"{smuggled!r} got through: {_codes(result)}"


def test_a_list_filter_of_literals_is_allowed(law):
    """The law firm's metric row binds three keys through one IN."""
    assert _surface(law, "metric_row")["bindings"]["metrics"]["filter"]["key"] == [
        "unbilled_amount", "wip_amount", "trust_balance",
    ]
    result = validator.validate_layout(law, business_id=TENANT)
    assert result.ok, result.errors


def test_an_empty_filter_list_is_rejected(law):
    _surface(law, "metric_row")["bindings"]["metrics"]["filter"]["key"] = []
    result = validator.validate_layout(law, business_id=TENANT)
    assert _find(result, "empty_filter_list") is not None, _codes(result)


# ─── check 5: options_in_range ───────────────────────────────────────

def test_option_out_of_range_is_rejected(salon):
    salon["surfaces"][0]["options"]["day_start"] = 47
    result = validator.validate_layout(salon, business_id=TENANT)

    # Two errors are correct here: 47 is outside 0-23, AND it now sits after
    # day_end. Assert on the one we caused rather than on whichever sorts
    # first, so the test can't be satisfied by the wrong finding.
    err = next((e for e in result.errors
                if e["path"] == "surfaces[0].options.day_start"), None)
    assert err is not None, _codes(result)
    assert err["check"] == "options_in_range"
    assert err["code"] == "option_out_of_range"
    assert err["value"] == 47


def test_option_of_the_wrong_type_is_rejected(salon):
    salon["surfaces"][0]["options"]["show_gaps"] = "yes"
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "option_wrong_type") is not None, _codes(result)


def test_a_boolean_does_not_pass_as_an_integer(salon):
    """bool is an int in Python. Without an explicit guard, show_gaps=True
    would satisfy day_start."""
    salon["surfaces"][0]["options"]["day_start"] = True
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "option_wrong_type") is not None, _codes(result)


def test_unknown_option_is_rejected(salon):
    salon["surfaces"][0]["options"]["zoom_level"] = 3
    result = validator.validate_layout(salon, business_id=TENANT)

    err = _find(result, "unknown_option")
    assert err is not None, _codes(result)
    assert err["value"] == "zoom_level"


def test_enum_outside_its_values_is_rejected(salon):
    salon["surfaces"][1]["options"]["age_unit"] = "fortnights"
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "option_out_of_range") is not None, _codes(result)


def test_day_end_before_day_start_is_rejected(salon):
    salon["surfaces"][0]["options"]["day_start"] = 18
    salon["surfaces"][0]["options"]["day_end"] = 9
    result = validator.validate_layout(salon, business_id=TENANT)

    err = _find(result, "option_out_of_range")
    assert err is not None and err["path"].endswith("day_end"), _codes(result)


def test_metric_row_may_never_lead(law):
    """'Footer material, never the hero' is an invariant, not a convention.
    The registry does not list `lead` for metric_row, so a layout that leads
    with numbers cannot validate."""
    assert "lead" not in registry.PRIMITIVES["metric_row"]["allowed_roles"]

    for s in law["surfaces"]:
        s["role"] = "secondary"
    metrics = _surface(law, "metric_row")
    metrics["role"] = "lead"
    metrics["rationale"] = "Numbers first, for the sake of argument."
    result = validator.validate_layout(law, business_id=TENANT)

    err = _find(result, "role_not_allowed")
    assert err is not None, _codes(result)
    assert err["value"] == "lead"


def test_stages_without_a_stage_sort_is_rejected(law):
    _surface(law, "priority_docket")["options"]["stages"] = ["One", "Two"]
    result = validator.validate_layout(law, business_id=TENANT)
    assert _find(result, "option_requires_unmet") is not None, _codes(result)


def test_a_stage_sort_without_stages_is_rejected():
    consultant = workspace_layouts.get_preset("consultant")
    _surface(consultant, "priority_docket")["options"]["stages"] = []
    result = validator.validate_layout(consultant, business_id=TENANT)
    assert _find(result, "option_required_by_peer") is not None, _codes(result)


# ─── check 6: rationale_present ──────────────────────────────────────

def test_absent_rationale_is_rejected(salon):
    del salon["rationale"]
    result = validator.validate_layout(salon, business_id=TENANT)

    err = _find(result, "missing_rationale")
    assert err is not None, _codes(result)
    assert err["check"] == "rationale_present"
    assert err["path"] == "rationale"


def test_empty_rationale_is_rejected(salon):
    salon["rationale"] = "   "
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "missing_rationale") is not None, _codes(result)


def test_absent_suppressed_is_rejected(salon):
    """An empty list is a claim. An absent key is a shrug, and Chief cannot
    narrate a shrug."""
    del salon["suppressed"]
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "missing_suppressed") is not None, _codes(result)


def test_empty_suppressed_list_is_allowed(salon):
    salon["suppressed"] = []
    result = validator.validate_layout(salon, business_id=TENANT)
    assert result.ok, result.errors


def test_suppression_without_a_reason_is_rejected(salon):
    salon["suppressed"][0] = {"primitive": "ledger"}
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "missing_suppression_reason") is not None, _codes(result)


def test_suppressing_a_primitive_the_layout_renders_is_rejected(salon):
    """Claiming to have removed the thing on screen is a lie the narration
    would repeat verbatim."""
    salon["suppressed"].append(
        {"primitive": "timeline_day", "reason": "Not useful here."}
    )
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "suppressed_primitive_in_use") is not None, _codes(result)


def test_lead_surface_must_say_why_it_leads(salon):
    del salon["surfaces"][0]["rationale"]
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "missing_surface_rationale") is not None, _codes(result)


def test_terminology_origin_must_be_known(salon):
    salon["terminology"]["client"]["origin"] = "guessed"
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "unknown_term_origin") is not None, _codes(result)


# ─── check 7: surface_budget ─────────────────────────────────────────

def _pad_to(layout, n):
    """Grow a layout to exactly n surfaces by cloning a non-lead one."""
    template = next(s for s in layout["surfaces"] if s["role"] != "lead")
    i = 0
    while len(layout["surfaces"]) < n:
        clone = copy.deepcopy(template)
        clone["id"] = f"filler_{i}"
        layout["surfaces"].append(clone)
        i += 1
    return layout


def test_one_over_the_budget_is_rejected(salon):
    over = registry.SURFACE_BUDGET + 1
    _pad_to(salon, over)
    assert len(salon["surfaces"]) == over

    result = validator.validate_layout(salon, business_id=TENANT)
    err = _find(result, "surface_budget_exceeded")
    assert err is not None, _codes(result)
    assert err["check"] == "surface_budget"
    assert err["value"] == over


def test_exactly_the_budget_is_allowed(salon):
    _pad_to(salon, registry.SURFACE_BUDGET)
    assert len(salon["surfaces"]) == registry.SURFACE_BUDGET

    result = validator.validate_layout(salon, business_id=TENANT)
    assert result.ok, result.errors


def test_every_preset_fits_the_budget():
    """A preset that already sits at the ceiling leaves phase two no room."""
    for a in workspace_layouts.ARCHETYPES:
        n = len(workspace_layouts.get_preset(a)["surfaces"])
        assert n <= registry.SURFACE_BUDGET, f"{a} declares {n} surfaces"


def test_no_lead_surface_is_rejected(salon):
    salon["surfaces"][0]["role"] = "secondary"
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "no_lead_surface") is not None, _codes(result)


def test_two_lead_surfaces_are_rejected(salon):
    salon["surfaces"][1]["role"] = "lead"
    salon["surfaces"][1]["rationale"] = "Also leads, apparently."
    result = validator.validate_layout(salon, business_id=TENANT)

    err = _find(result, "multiple_lead_surfaces")
    assert err is not None, _codes(result)
    assert err["value"] == 2


def test_duplicate_surface_ids_are_rejected(salon):
    salon["surfaces"][1]["id"] = salon["surfaces"][0]["id"]
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "duplicate_surface_id") is not None, _codes(result)


def test_a_layout_with_no_surfaces_is_rejected(salon):
    salon["surfaces"] = []
    result = validator.validate_layout(salon, business_id=TENANT)
    assert _find(result, "no_surfaces") is not None, _codes(result)


# ─── shape of the rejection itself ───────────────────────────────────

def test_it_rejects_rather_than_repairs(salon):
    """The contract is 'rejects, never silently repairs'. The object handed
    in must come back untouched."""
    salon["surfaces"][0]["options"]["day_start"] = 47
    before = json.dumps(salon, sort_keys=True)

    validator.validate_layout(salon, business_id=TENANT)

    assert json.dumps(salon, sort_keys=True) == before


def test_assert_valid_raises_with_structured_errors(salon):
    salon["surfaces"][0]["primitive"] = "gantt_chart"
    with pytest.raises(validator.LayoutValidationError) as exc:
        validator.assert_valid(salon, business_id=TENANT)

    assert exc.value.errors
    assert exc.value.errors[0]["code"] == "unknown_primitive"


def test_assert_valid_returns_the_layout_unchanged(salon):
    returned = validator.assert_valid(salon, business_id=TENANT)
    assert returned is salon


def test_every_error_carries_the_full_structure(salon):
    salon["surfaces"][0]["primitive"] = "gantt_chart"
    del salon["rationale"]
    result = validator.validate_layout(salon, business_id=TENANT)

    for e in result.errors:
        assert set(e.keys()) == {"check", "code", "path", "message", "value"}
        assert e["check"] in validator.CHECKS
        assert isinstance(e["message"], str) and e["message"]


def test_errors_are_reported_in_check_order(salon):
    """A caller reading top-down should fix causes before symptoms."""
    salon["surfaces"][0]["primitive"] = "gantt_chart"
    del salon["rationale"]
    salon["surfaces"].append(copy.deepcopy(salon["surfaces"][1]))
    salon["surfaces"][-1]["id"] = "dupe_check"

    result = validator.validate_layout(salon, business_id=TENANT)
    order = [validator.CHECKS.index(c) for c in result.checks()]
    assert order == sorted(order), result.checks()


def test_non_dict_layout_is_rejected():
    for junk in (None, [], "salon", 7):
        result = validator.validate_layout(junk, business_id=TENANT)
        assert not result.ok
        assert result.errors[0]["code"] == "layout_not_an_object"


def test_layout_with_no_surfaces_key_is_rejected():
    result = validator.validate_layout(
        {"rationale": "x", "suppressed": []}, business_id=TENANT
    )
    assert _find(result, "missing_surfaces") is not None, _codes(result)


def test_all_seven_checks_are_reachable():
    """A check that no malformation can trigger is a check that isn't
    running. Every one of the seven must be provably reachable."""
    triggered = set()

    def run(mutate):
        layout = workspace_layouts.get_preset("salon")
        mutate(layout)
        for e in validator.validate_layout(layout, business_id=TENANT).errors:
            triggered.add(e["check"])

    def _set_option(l):
        l["surfaces"][0]["options"]["day_start"] = 47

    def _cross_tenant(l):
        l["surfaces"][0]["bindings"]["events"]["filter"]["business_id"] = OTHER_TENANT

    run(lambda l: l["surfaces"][0].__setitem__("primitive", "gantt_chart"))
    run(lambda l: l["surfaces"][0]["bindings"].pop("events"))
    run(lambda l: l["surfaces"][0]["bindings"]["events"].__setitem__("source", "nope"))
    run(_cross_tenant)
    run(_set_option)
    run(lambda l: l.pop("rationale"))
    run(lambda l: l["surfaces"].__setitem__(1, dict(l["surfaces"][0], id="two")))

    assert triggered == set(validator.CHECKS), (
        f"unreachable checks: {set(validator.CHECKS) - triggered}"
    )


# ─── the loader ──────────────────────────────────────────────────────

def test_presets_are_deep_copied():
    """A caller that mutates its layout must not mutate everyone else's."""
    a = workspace_layouts.get_preset("salon")
    a["surfaces"][0]["title"] = "MUTATED"
    b = workspace_layouts.get_preset("salon")
    assert b["surfaces"][0]["title"] != "MUTATED"


def test_unknown_archetype_raises():
    with pytest.raises(KeyError):
        workspace_layouts.get_preset("food_truck")


def test_every_archetype_file_exists():
    here = os.path.dirname(os.path.abspath(workspace_layouts.__file__))
    for a in workspace_layouts.ARCHETYPES:
        assert os.path.exists(os.path.join(here, f"{a}.json"))


def test_summaries_cover_every_archetype():
    summaries = workspace_layouts.summaries()
    assert {s["archetype"] for s in summaries} == set(workspace_layouts.ARCHETYPES)
    for s in summaries:
        assert s["lead_primitive"] in registry.ids()
