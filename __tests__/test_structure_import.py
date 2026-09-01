"""Structure Import, Stage 0 — the rubric and the two endpoints.

What matters here, in order: a sheet of PEOPLE never becomes a module;
the rubric reads VALUES not headers; dropped columns are NAMED; a dry
run writes nothing; a real run creates the module, proves it exists,
and only then lands rows; and an edited proposal that hands back a
`select` with no options is refused before anything is written.
"""
from __future__ import annotations

import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import structure_import as si  # noqa: E402
import structure_import_router as sir  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402

BIZ = "b1"


class _Owner:
    id = "owner1"
    email = "owner@x.com"


class _Stranger:
    id = "intruder"
    email = "evil@x.com"


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)

    # PostgREST accepts a LIST body as a bulk insert; the run endpoint
    # inserts entries in chunks that way. FakeSB.post models one row.
    def post(p, b, prefer="rep"):
        if isinstance(b, list):
            return [fb.post(p, x, prefer)[0] for x in b]
        return fb.post(p, b, prefer)

    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append({"id": BIZ, "owner_id": "owner1", "name": "Northside Cuts", "type": "barber"})
    fb.rows("contacts").extend([
        {"id": "c1", "business_id": BIZ, "name": "Dana Whitfield", "email": "dana@x.com", "phone": None},
        {"id": "c2", "business_id": BIZ, "name": "Marcus Lee", "email": "marcus@x.com", "phone": None},
        {"id": "c3", "business_id": BIZ, "name": "Priya Nair", "email": None, "phone": None},
    ])
    return fb


# ─── Fixtures: sheets ─────────────────────────────────────────────────

def people_sheet():
    return {"name": "Clients.csv",
            "headers": ["Client Name", "Email", "Phone", "Stage", "Birthday"],
            "sample_rows": [
                ["Dana Whitfield", "dana@x.com", "555-010-2233", "Active", ""],
                ["Marcus Lee", "marcus@x.com", "555-010-9911", "Active", ""],
                ["Kim Ortiz", "kim@x.com", "", "Paused", ""],
                ["Lee Park", "lee@x.com", "", "Active", ""],
                ["Ana Souza", "ana@x.com", "", "Paused", ""],
                ["Tom Reyes", "tom@x.com", "", "Active", ""],
            ], "total_rows": 412}


def jobs_sheet(stage_values=None):
    stages = stage_values or ["Estimate", "Scheduled", "In progress", "Invoiced", "Estimate",
                              "Scheduled", "In progress", "Invoiced", "Estimate", "Scheduled",
                              "In progress", "Invoiced"]
    rows = []
    for i, st in enumerate(stages):
        rows.append([f"Job {i + 1}", ["Dana Whitfield", "Marcus Lee", "Priya Nair", "Someone New"][i % 4],
                     st, f"2026-09-{(i % 28) + 1:02d}", f"${(i + 1) * 100}.00",
                     f"{i + 10} Oak St", "" ])
    return {"name": "Jobs.csv",
            "headers": ["Job", "Customer", "Stage", "Due", "Quote", "Site address", "Unused"],
            "sample_rows": rows, "total_rows": len(rows)}


def schedule_sheet():
    rows = [[f"2026-09-{i + 1:02d} 10:00", ["Dana Whitfield", "Marcus Lee", "Priya Nair"][i % 3], "Fade"]
            for i in range(8)]
    return {"name": "Appointments.csv", "headers": ["When", "Client", "Service"],
            "sample_rows": rows, "total_rows": 8}


def roster_sheet():
    rows = []
    for ev in ("Sunday Service", "Youth Night", "Picnic"):
        for who in ("Dana Whitfield", "Marcus Lee", "Priya Nair", "Sam Hill"):
            rows.append([ev, who, "2026-09-07"])
    return {"name": "Signups.csv", "headers": ["Event", "Name", "Date"],
            "sample_rows": rows, "total_rows": len(rows)}


# ─── Rubric ──────────────────────────────────────────────────────────

def test_a_sheet_of_people_goes_to_contacts_never_a_module():
    p = si.propose([people_sheet()], contacts=[])
    s = p["sheets"][0]
    assert s["verdict"] == "existing_surface" and s["target"] == {"kind": "contacts"}
    mapped = {c["field"]["name"]: c["header"] for c in s["columns"] if c["decision"] == "map"}
    assert mapped["name"] == "Client Name" and mapped["email"] == "Email" and mapped["phone"] == "Phone"
    assert mapped["status"] == "Stage"
    # The column with no home is DROPPED BY NAME, not counted.
    assert "Clients.csv: Birthday" in p["dropped"]
    assert "people" in s["reason"].lower()


def test_jobs_become_a_pipeline_with_the_stages_read_from_the_values():
    p = si.propose([jobs_sheet()], contacts=[])
    s = p["sheets"][0]
    assert s["verdict"] == "new_module"
    spec = s["target"]["spec"]
    assert spec["archetype"] == "work_pipeline"
    assert spec["archetype_fallback_reason"] is None
    params = spec["archetype_params"]
    assert [st["label"] for st in params["stages"]] == ["Estimate", "Scheduled", "In progress", "Invoiced"]
    assert params["stage_field"] == "stage" and params["date_field"] == "due"
    assert params["value_field"] == "quote" and params["location_field"] == "site_address"
    assert spec["schema"]["board_column"] == "stage" and "board" in spec["schema"]["views"]
    types = {f["name"]: f["type"] for f in spec["schema"]["fields"]}
    assert types["stage"] == "select" and types["due"] == "date" and types["quote"] == "currency"
    assert "Jobs.csv: Unused" in p["dropped"]
    assert not any(f["type"] in ("file", "offering_ref") for f in spec["schema"]["fields"])
    assert si.validate_module_schema(spec["schema"]) == []


def test_people_the_business_already_knows_become_a_link_not_a_string():
    known = [{"name": "Dana Whitfield", "email": "dana@x.com"},
             {"name": "Marcus Lee", "email": "marcus@x.com"},
             {"name": "Priya Nair", "email": None}]
    p = si.propose([jobs_sheet()], contacts=known)
    spec = p["sheets"][0]["target"]["spec"]
    cust = next(f for f in spec["schema"]["fields"] if f["name"] == "customer")
    assert cust["type"] == "contact_link"
    col = next(c for c in p["sheets"][0]["columns"] if c["header"] == "Customer")
    assert col["confidence"] == "low"          # 75% matched — practitioner confirms
    assert "match people already in your list" in col["note"]
    assert spec["archetype_params"]["contact_field"] == "customer"


def test_one_date_and_a_person_is_a_schedule():
    p = si.propose([schedule_sheet()], contacts=[])
    spec = p["sheets"][0]["target"]["spec"]
    assert spec["archetype"] == "booking_calendar"
    assert spec["archetype_params"]["primary_date_field"] == "when"
    assert spec["schema"]["calendar_field"] == "when" and "calendar" in spec["schema"]["views"]


def test_many_rows_sharing_one_occasion_is_a_roster():
    p = si.propose([roster_sheet()], contacts=[])
    spec = p["sheets"][0]["target"]["spec"]
    assert spec["archetype"] == "event_roster"
    assert spec["archetype_params"]["title_field"] == "event"


def test_a_plain_list_falls_back_and_says_which_archetype_it_missed():
    sheet = {"name": "Inventory.csv", "headers": ["Item", "Qty", "Supplier"],
             "sample_rows": [[f"Item {i}", str(i * 3), "Acme"] for i in range(6)], "total_rows": 6}
    p = si.propose([sheet], contacts=[])
    spec = p["sheets"][0]["target"]["spec"]
    assert spec["archetype"] == "fallback_generic"
    assert spec["archetype_fallback_reason"]
    types = {f["name"]: f["type"] for f in spec["schema"]["fields"]}
    assert types["qty"] == "number" and types["item"] == "text"


def test_a_sheet_with_nothing_in_it_is_ignored_with_a_reason():
    sheet = {"name": "Empty.csv", "headers": ["A", "B"], "sample_rows": [["", ""]], "total_rows": 1}
    p = si.propose([sheet], contacts=[])
    assert p["sheets"][0]["verdict"] == "ignore" and p["sheets"][0]["reason"]


def test_past_twenty_fields_the_rest_fold_into_notes_and_are_named():
    headers = [f"Col {i}" for i in range(25)]
    rows = [[f"v{i}-{r}" for i in range(25)] for r in range(6)]
    p = si.propose([{"name": "Wide.csv", "headers": headers, "sample_rows": rows, "total_rows": 6}], [])
    s = p["sheets"][0]
    fields = s["target"]["spec"]["schema"]["fields"]
    assert len(fields) == si.MAX_FIELDS + 1
    assert fields[-1]["type"] == "textarea" and "Col 24" in fields[-1]["placeholder"]
    assert s["folded"] == [f"Col {i}" for i in range(20, 25)]


def test_two_sheets_that_reference_each_other_get_a_module_ref():
    jobs = jobs_sheet()
    invoices = {"name": "Invoices.csv", "headers": ["Invoice", "Job", "Amount", "Sent"],
                "sample_rows": [[f"INV-{i}", f"Job {i + 1}", f"${i * 50}.00", f"2026-08-{i + 1:02d}"]
                                for i in range(8)], "total_rows": 8}
    p = si.propose([jobs, invoices], contacts=[])
    inv = p["sheets"][1]["target"]["spec"]
    job_field = next(f for f in inv["schema"]["fields"] if f["name"] == "job")
    assert job_field["type"] == "module_ref" and job_field["module_slug"] == "jobs"


def test_select_needs_repeats_a_column_of_unique_names_is_text():
    c = si.classify_column("Title", [f"Unique {i}" for i in range(10)])
    assert c["type"] == "text"
    c2 = si.classify_column("Status", ["Open", "Closed"] * 5)
    assert c2["type"] == "select" and c2["options"] == ["Open", "Closed"]


def test_validator_refuses_what_an_import_cannot_fill():
    bad = {"fields": [{"name": "stage", "type": "select", "label": "Stage"}], "views": ["list"]}
    assert any("has no options" in e for e in si.validate_module_schema(bad))
    bad2 = {"fields": [{"name": "doc", "type": "file", "label": "Doc"}], "views": ["list"]}
    assert any("cannot fill" in e for e in si.validate_module_schema(bad2))
    bad3 = {"fields": [{"name": "j", "type": "module_ref", "label": "Job"}], "views": ["list"]}
    assert any("names no module" in e for e in si.validate_module_schema(bad3))


# ─── Propose endpoint ────────────────────────────────────────────────

def test_propose_gates_and_caps(fake):
    body = sir.ProposeBody(source_name="Airtable", sheets=[sir.SheetIn(**people_sheet())])
    with pytest.raises(HTTPException) as e:
        sir.propose(BIZ, body, _Stranger())
    assert e.value.status_code == 403
    out = sir.propose(BIZ, body, _Owner())
    assert out["ok"] and out["proposal_id"] and out["credits_spent"] == 0
    assert out["sheets"][0]["verdict"] == "existing_surface"
    too_many = sir.ProposeBody(sheets=[sir.SheetIn(**people_sheet()) for _ in range(si.MAX_SHEETS + 1)])
    with pytest.raises(HTTPException) as e2:
        sir.propose(BIZ, too_many, _Owner())
    assert e2.value.status_code == 400


def test_propose_reads_the_business_contacts_for_links(fake):
    body = sir.ProposeBody(sheets=[sir.SheetIn(**jobs_sheet())])
    out = sir.propose(BIZ, body, _Owner())
    spec = out["sheets"][0]["target"]["spec"]
    assert next(f for f in spec["schema"]["fields"] if f["name"] == "customer")["type"] == "contact_link"


# ─── Run endpoint ────────────────────────────────────────────────────

def _run_body(proposal, rows, dry_run):
    return sir.RunBody(
        proposal_id=proposal["proposal_id"],
        sheets=[sir.RunSheet(sheet=s["sheet"], verdict=s["verdict"],
                             headers=rows[s["sheet"]]["headers"], target=s["target"],
                             columns=s["columns"], import_hints=s.get("import_hints") or {})
                for s in proposal["sheets"]],
        rows={k: v["rows"] for k, v in rows.items()},
        dry_run=dry_run)


def test_dry_run_writes_nothing_and_says_what_it_would_do(fake):
    js = jobs_sheet()
    proposal = sir.propose(BIZ, sir.ProposeBody(sheets=[sir.SheetIn(**js)]), _Owner())
    rows = {"Jobs.csv": {"headers": js["headers"], "rows": js["sample_rows"] + [["", "", "", "", "", "", ""]]}}
    before = (len(fake.rows("custom_modules")), len(fake.rows("module_entries")))
    out = sir.run(BIZ, _run_body(proposal, rows, dry_run=True), _Owner())
    assert out["dry_run"] is True
    s = out["sheets"][0]
    assert s["module_action"] == "would_create" and s["module_slug"] == "jobs"
    assert s["summary"]["to_create"] == 12 and s["summary"]["skipped"] == 1
    assert (len(fake.rows("custom_modules")), len(fake.rows("module_entries"))) == before


def test_real_run_creates_the_module_then_the_rows(fake):
    js = jobs_sheet()
    proposal = sir.propose(BIZ, sir.ProposeBody(sheets=[sir.SheetIn(**js)]), _Owner())
    rows = {"Jobs.csv": {"headers": js["headers"], "rows": js["sample_rows"]}}
    out = sir.run(BIZ, _run_body(proposal, rows, dry_run=False), _Owner())
    s = out["sheets"][0]
    assert s["module_action"] == "created" and s["summary"]["created"] == 12
    mod = fake.rows("custom_modules")[0]
    assert mod["slug"] == "jobs" and mod["archetype"] == "work_pipeline" and mod["business_id"] == BIZ
    assert mod["schema"]["board_column"] == "stage"
    entries = fake.rows("module_entries")
    assert len(entries) == 12 and all(e["module_id"] == mod["id"] for e in entries)
    first = entries[0]["data"]
    assert first["stage"] == "Estimate" and first["quote"] == 100.0 and first["due"] == "2026-09-01"
    # Running it again reuses the module rather than building a twin.
    again = sir.run(BIZ, _run_body(proposal, rows, dry_run=True), _Owner())
    assert again["sheets"][0]["module_action"] == "reused"


def test_a_people_sheet_runs_through_the_contacts_import(fake, monkeypatch):
    import contacts_import_router as cir
    seen = {}

    def fake_import(business_id, body, user):
        seen["rows"] = [r.model_dump() for r in body.rows]
        seen["dry_run"] = body.dry_run
        return {"ok": True, "summary": {"to_create": len(body.rows), "matched": 0, "skipped": 0,
                                        "total": len(body.rows)}, "results": []}

    monkeypatch.setattr(cir, "import_contacts", fake_import)
    ps = people_sheet()
    proposal = sir.propose(BIZ, sir.ProposeBody(sheets=[sir.SheetIn(**ps)]), _Owner())
    rows = {"Clients.csv": {"headers": ps["headers"], "rows": ps["sample_rows"]}}
    out = sir.run(BIZ, _run_body(proposal, rows, dry_run=True), _Owner())
    assert out["sheets"][0]["module_slug"] == "contacts"
    assert seen["dry_run"] is True and len(seen["rows"]) == 6
    assert seen["rows"][0]["name"] == "Dana Whitfield" and seen["rows"][0]["email"] == "dana@x.com"
    assert seen["rows"][0]["status"] == "active"
    assert fake.rows("custom_modules") == []


def test_an_edited_proposal_with_a_bare_select_is_refused_before_any_write(fake):
    """The rehearsal the spec asks for: strip a select's options and
    prove the run refuses — a passing import is also what a validator
    that never runs looks like."""
    js = jobs_sheet()
    proposal = sir.propose(BIZ, sir.ProposeBody(sheets=[sir.SheetIn(**js)]), _Owner())
    spec = proposal["sheets"][0]["target"]["spec"]
    for f in spec["schema"]["fields"]:
        if f["type"] == "select":
            f.pop("options", None)
    rows = {"Jobs.csv": {"headers": js["headers"], "rows": js["sample_rows"]}}
    with pytest.raises(HTTPException) as e:
        sir.run(BIZ, _run_body(proposal, rows, dry_run=False), _Owner())
    assert e.value.status_code == 422
    assert any("has no options" in x for x in e.value.detail["errors"])
    assert fake.rows("custom_modules") == [] and fake.rows("module_entries") == []


def test_a_module_that_cannot_be_read_back_lands_zero_rows(fake, monkeypatch):
    import sb_clients
    real_post = sb_clients.sb_post_as_service

    def post(path, body, prefer="rep"):
        if path.startswith("/custom_modules"):
            return None                      # a 4xx: sb_post_as_service returns None
        return real_post(path, body, prefer)  # the list-aware fake from the fixture

    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    js = jobs_sheet()
    proposal = sir.propose(BIZ, sir.ProposeBody(sheets=[sir.SheetIn(**js)]), _Owner())
    rows = {"Jobs.csv": {"headers": js["headers"], "rows": js["sample_rows"]}}
    with pytest.raises(HTTPException) as e:
        sir.run(BIZ, _run_body(proposal, rows, dry_run=False), _Owner())
    assert e.value.status_code == 500
    assert fake.rows("module_entries") == []


def test_run_needs_manager_and_row_cap(fake):
    js = jobs_sheet()
    proposal = sir.propose(BIZ, sir.ProposeBody(sheets=[sir.SheetIn(**js)]), _Owner())
    rows = {"Jobs.csv": {"headers": js["headers"], "rows": js["sample_rows"]}}
    with pytest.raises(HTTPException) as e:
        sir.run(BIZ, _run_body(proposal, rows, dry_run=True), _Stranger())
    assert e.value.status_code == 403
    big = {"Jobs.csv": {"headers": js["headers"], "rows": [js["sample_rows"][0]] * (sir.MAX_ROWS_PER_SHEET + 1)}}
    with pytest.raises(HTTPException) as e2:
        sir.run(BIZ, _run_body(proposal, big, dry_run=True), _Owner())
    assert e2.value.status_code == 400


def test_roster_rows_group_into_one_entry_per_occasion(fake):
    rs = roster_sheet()
    proposal = sir.propose(BIZ, sir.ProposeBody(sheets=[sir.SheetIn(**rs)]), _Owner())
    assert proposal["sheets"][0]["import_hints"]["person_field"] == "name"
    rows = {"Signups.csv": {"headers": rs["headers"], "rows": rs["sample_rows"]}}
    out = sir.run(BIZ, _run_body(proposal, rows, dry_run=False), _Owner())
    entries = fake.rows("module_entries")
    assert len(entries) == 3
    picnic = next(e for e in entries if e["data"]["event"] == "Picnic")
    assert [s["name"] for s in picnic["data"]["signups"]] == ["Dana Whitfield", "Marcus Lee", "Priya Nair", "Sam Hill"]
    assert out["sheets"][0]["summary"]["created"] == 3


def test_router_is_registered():
    src = (_here.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert "structure_import_router" in src and "app.include_router(structure_import_router)" in src
