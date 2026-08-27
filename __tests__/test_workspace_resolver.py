"""
test_workspace_resolver.py — the resolver holds the service-role key.

Everything else in the composer is guarded by RLS *and* an app-layer owner
check. This module bypasses RLS by design, which makes it the one place
where a bad layout could actually read another tenant's rows. So these
tests are less about "does it return data" and more about "what does it
refuse".

The queries are asserted as strings. That looks brittle and is deliberate:
the tenant pin, the escaping and the column allow-list are all visible in
the query text, and a regression that drops any of them would otherwise
pass a test that only checked the returned rows.
"""
from __future__ import annotations

import datetime as dt

import pytest

import workspace_layouts
import workspace_resolver as R

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def captured(monkeypatch):
    """Capture every query the resolver issues, return no rows."""
    calls = []

    def fake_get(path):
        calls.append(path)
        return []

    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake_get)
    return calls


def _rows(monkeypatch, rows):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: rows)


def _binding(**over):
    d = {
        "source": "contacts",
        "scope": "business",
        "fields": {"id": "id", "title": "name"},
    }
    d.update(over)
    return d


def _spec(shape="collection"):
    return {"shape": shape, "required": True, "fields": {}}


# ─── the boundary ────────────────────────────────────────────────────

def test_the_tenant_pin_is_always_applied(captured):
    R._resolve_binding("items", _binding(), _spec(), TENANT)
    assert f"business_id=eq.{TENANT}" in captured[0]


def test_the_pin_comes_from_the_argument_not_the_descriptor(captured):
    """Even a descriptor that pins our OWN tenant must not be the source of
    truth — the id in the query has to be the one the caller authorised."""
    R._resolve_binding("items", _binding(filter={"business_id": TENANT}),
                       _spec(), TENANT)
    assert captured[0].count("business_id=eq.") == 1
    assert f"business_id=eq.{TENANT}" in captured[0]


def test_a_cross_tenant_binding_is_refused(captured):
    """THE test. Refused, not silently overridden — a layout pinning
    someone else's tenant is corrupt or hostile and either deserves a stop."""
    with pytest.raises(R.ResolveError) as exc:
        R._resolve_binding("items", _binding(filter={"business_id": OTHER}),
                           _spec(), TENANT)
    assert OTHER in str(exc.value)
    assert not captured, "no query should have been issued"


def test_a_cross_tenant_binding_aborts_the_whole_resolve(captured):
    """resolve() degrades gracefully on most failures, but not this one:
    a boundary being tested must reach the caller, not become an empty
    panel nobody notices."""
    layout = workspace_layouts.get_preset("salon")
    lead = layout["surfaces"][0]
    lead["bindings"]["events"]["filter"]["business_id"] = OTHER
    with pytest.raises(R.ResolveError):
        R.resolve(layout, TENANT)


def test_an_illegal_scope_is_refused(captured):
    with pytest.raises(R.ResolveError):
        R._resolve_binding("items", _binding(scope="platform"), _spec(), TENANT)
    assert not captured


def test_an_unknown_source_is_refused(captured):
    with pytest.raises(R.ResolveError):
        R._resolve_binding("items", _binding(source="secrets"), _spec(), TENANT)
    assert not captured


def test_a_column_outside_the_catalog_is_refused(captured):
    with pytest.raises(R.ResolveError):
        R._resolve_binding("items", _binding(fields={"id": "id", "title": "ssn"}),
                           _spec(), TENANT)
    assert not captured


def test_it_does_not_trust_a_validated_layout(captured):
    """The validator is a separate function a caller can forget to run.
    The resolver re-checks the catalog itself rather than assuming."""
    bad = _binding(source="contacts", fields={"id": "id", "x": "password"})
    with pytest.raises(R.ResolveError):
        R._resolve_binding("items", bad, _spec(), TENANT)


@pytest.mark.parametrize("smuggled", [
    "confirmed&business_id=eq." + OTHER,
    "active,or(business_id.eq.x)",
    "*",
    "a)&select=*",
])
def test_filter_values_cannot_carry_a_query(captured, smuggled):
    """The moment a value can carry `&` or `(` unescaped it can carry a
    second filter, and the tenant pin stops being a boundary."""
    with pytest.raises(R.ResolveError):
        R._resolve_binding("items", _binding(filter={"status": smuggled}),
                           _spec(), TENANT)
    assert not captured


def test_only_the_columns_the_binding_reads_are_selected(captured):
    R._resolve_binding("items", _binding(fields={"id": "id", "title": "name"}),
                       _spec(), TENANT)
    select = [p for p in captured[0].split("&") if p.startswith("select=")][0]
    assert select == "select=business_id,id,name"
    assert "email" not in select and "phone" not in select


def test_a_limit_cannot_be_unbounded(captured):
    R._resolve_binding("items", _binding(limit=99999), _spec(), TENANT)
    assert f"limit={R.MAX_LIMIT}" in captured[0]


def test_order_is_rebuilt_from_the_catalog_not_passed_through(captured):
    R._resolve_binding("items", _binding(order="last_interaction.asc"),
                       _spec(), TENANT)
    assert "order=last_interaction.asc" in captured[0]


def test_ordering_by_an_unknown_column_is_refused(captured):
    with pytest.raises(R.ResolveError):
        R._resolve_binding("items", _binding(order="salary.desc"), _spec(), TENANT)


# ─── mapping and derivations ─────────────────────────────────────────

def test_rows_are_mapped_onto_the_contract(monkeypatch):
    _rows(monkeypatch, [{"id": "c1", "name": "Georgia Sutcliffe"}])
    rows = R._resolve_binding("items", _binding(), _spec(), TENANT)
    assert rows == [{"id": "c1", "title": "Georgia Sutcliffe"}]


def test_days_since_is_computed_at_read_time(monkeypatch):
    ten_days = (dt.date.today() - dt.timedelta(days=10)).isoformat()
    _rows(monkeypatch, [{"id": "c1", "last_interaction": ten_days}])
    rows = R._resolve_binding("items", _binding(fields={
        "id": "id",
        "age_days": {"column": "last_interaction", "derive": "days_since"},
    }), _spec(), TENANT)
    assert rows[0]["age_days"] == 10


def test_days_until_is_negative_for_a_passed_date(monkeypatch):
    past = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    _rows(monkeypatch, [{"id": "m1", "created_at": past}])
    rows = R._resolve_binding("rows", _binding(source="module_entries", fields={
        "id": "id",
        "metric_value": {"column": "created_at", "derive": "days_until"},
    }), _spec(), TENANT)
    assert rows[0]["metric_value"] == -3


def test_cents_become_an_amount(monkeypatch):
    _rows(monkeypatch, [{"id": "i1", "amount_due_cents": 4820000}])
    rows = R._resolve_binding("rows", _binding(source="invoices", fields={
        "id": "id",
        "value": {"column": "amount_due_cents", "derive": "cents_to_amount"},
    }), _spec(), TENANT)
    assert rows[0]["value"] == 48200.0


def test_a_timestamp_splits_into_date_and_time(monkeypatch):
    _rows(monkeypatch, [{"id": "s1", "scheduled_for": "2026-08-26T14:30:00+00:00"}])
    rows = R._resolve_binding("events", _binding(source="sessions", fields={
        "id": "id",
        "date": {"column": "scheduled_for", "derive": "date_part"},
        "time": {"column": "scheduled_for", "derive": "time_part"},
    }), _spec(), TENANT)
    assert rows[0]["date"] == "2026-08-26"
    assert rows[0]["time"] == "14:30"


def test_a_jsonb_leaf_is_read_through_the_declared_column(monkeypatch):
    _rows(monkeypatch, [{"id": "m1", "data": {"matter_name": "Okonjo v. Ridgeline"}}])
    rows = R._resolve_binding("rows", _binding(source="module_entries", fields={
        "id": "id", "title": "data.matter_name",
    }), _spec(), TENANT)
    assert rows[0]["title"] == "Okonjo v. Ridgeline"


def test_a_missing_jsonb_leaf_is_none_not_a_crash(monkeypatch):
    _rows(monkeypatch, [{"id": "m1", "data": {}}])
    rows = R._resolve_binding("rows", _binding(source="module_entries", fields={
        "id": "id", "title": "data.matter_name",
    }), _spec(), TENANT)
    assert rows[0]["title"] is None


def test_an_unparseable_date_derives_to_none_not_a_crash(monkeypatch):
    _rows(monkeypatch, [{"id": "c1", "last_interaction": "never"}])
    rows = R._resolve_binding("items", _binding(fields={
        "id": "id",
        "age_days": {"column": "last_interaction", "derive": "days_since"},
    }), _spec(), TENANT)
    assert rows[0]["age_days"] is None


def test_a_scalar_binding_returns_one_value_not_a_list(monkeypatch):
    _rows(monkeypatch, [{"scheduled_for": "2026-08-23T09:00:00Z"},
                        {"scheduled_for": "2026-08-24T09:00:00Z"}])
    got = R._resolve_binding("week_of", _binding(source="sessions", fields={
        "date": {"column": "scheduled_for", "derive": "date_part"},
    }), _spec("scalar"), TENANT)
    assert got == {"date": "2026-08-23"}


def test_an_empty_scalar_binding_is_none(captured):
    got = R._resolve_binding("week_of", _binding(source="sessions",
                                                 fields={"date": "scheduled_for"}),
                             _spec("scalar"), TENANT)
    assert got is None


# ─── providers ───────────────────────────────────────────────────────

def test_benchmarks_come_from_the_provider_not_a_query(captured, monkeypatch):
    """The bands are editorial content in code. No table is read for them —
    only the per-tenant values, through their own path."""
    import workspace_benchmarks
    monkeypatch.setattr(workspace_benchmarks, "_values_for",
                        lambda bid: {"rebooking_rate": 38})
    rows = R._resolve_binding("rows", {
        "source": "business_benchmarks", "scope": "business",
        "filter": {"key": ["rebooking_rate", "chair_utilization"]},
        "fields": {"id": "key", "value": "value"},
    }, _spec(), TENANT)

    assert [r["key"] for r in rows] == ["rebooking_rate", "chair_utilization"]
    assert rows[0]["value"] == 38
    assert rows[0]["average"] == 52          # from the band, not the DB
    assert rows[0]["source"], "a band must carry its citation"
    assert rows[1]["value"] is None, "an uncomputed value is None, not hidden"


def test_every_band_carries_a_source():
    """A benchmark asserted without attribution is a number we made up."""
    import workspace_benchmarks
    for key, band in workspace_benchmarks.BANDS.items():
        assert band["source"].strip(), f"{key} has no source"
        assert band["reading"].strip(), f"{key} has no plain-language reading"


def test_every_key_a_preset_binds_has_a_band():
    """A layout asking for a benchmark that does not exist would render a
    silently shorter panel."""
    import workspace_benchmarks
    for archetype in workspace_layouts.ARCHETYPES:
        layout = workspace_layouts.get_preset(archetype)
        for surface in layout["surfaces"]:
            if surface["primitive"] != "benchmark_panel":
                continue
            for key in surface["bindings"]["rows"]["filter"]["key"]:
                assert key in workspace_benchmarks.BANDS, (
                    f"{archetype} binds {key!r} with no band declared")


def test_benchmark_values_failing_does_not_take_the_panel_down(monkeypatch):
    """A missing view must degrade to 'not measured yet', never to a blank
    home screen."""
    import sb_clients
    def boom(path):
        raise RuntimeError("relation does not exist")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", boom)

    import workspace_benchmarks
    rows = workspace_benchmarks.rows_for(TENANT, ["rebooking_rate"])
    assert len(rows) == 1
    assert rows[0]["value"] is None
    assert rows[0]["average"] == 52


# ─── the whole layout ────────────────────────────────────────────────

@pytest.mark.parametrize("archetype", workspace_layouts.ARCHETYPES)
def test_every_preset_resolves_without_raising(archetype, captured):
    """Each shipped preset must be executable, not merely valid."""
    layout = workspace_layouts.get_preset(archetype)
    data = R.resolve(layout, TENANT)
    for surface in layout["surfaces"]:
        assert surface["id"] in data
        for binding in surface["bindings"]:
            assert binding in data[surface["id"]]


@pytest.mark.parametrize("archetype", workspace_layouts.ARCHETYPES)
def test_every_query_is_tenant_pinned(archetype, captured):
    """Not one query may leave without the pin — this is the assertion that
    matters most, run across every binding the product ships."""
    R.resolve(workspace_layouts.get_preset(archetype), TENANT)
    assert captured, "a preset that issues no queries is suspicious"
    for path in captured:
        assert f"business_id=eq.{TENANT}" in path, path


def test_one_broken_surface_does_not_blank_the_page(monkeypatch):
    """A missing table is a degraded panel, not a blank home screen. A
    practitioner learns nothing from an empty page."""
    layout = workspace_layouts.get_preset("salon")
    layout["surfaces"][1]["bindings"]["items"]["source"] = "nonexistent"

    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [])

    data = R.resolve(layout, TENANT)
    assert data["floor_today"]["events"] == []     # the lead still resolved
    assert data["rebook_lapsed"]["items"] == []    # the broken one is empty


def test_resolve_needs_a_business_id():
    with pytest.raises(R.ResolveError):
        R.resolve(workspace_layouts.get_preset("salon"), "")
