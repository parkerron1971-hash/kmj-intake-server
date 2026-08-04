# __tests__/test_conflicts_router.py
#
# Conflict-of-interest check. Pins the matching ladder (the part a
# lawyer's professional conduct rides on), the sweep over both corpora,
# the noise floor ("Lee" must not hit "fleet"), the owner gate, and the
# check-is-the-record event write.

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import conflicts_router as cr  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


class _User:
    id = "owner1"
    email = "owner1@x.com"


class _Stranger:
    id = "intruder"
    email = "evil@x.com"


BIZ = "b1"


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    fb.rows("businesses").append({"id": BIZ, "owner_id": "owner1", "name": "Reyes Law"})
    fb.rows("contacts").extend([
        {"id": "c1", "business_id": BIZ, "name": "Dana Whitfield",
         "email": "dana@x.com", "phone": "555-010-2233", "role": "client",
         "status": "active", "tags": []},
        {"id": "c2", "business_id": BIZ, "name": "John Smith",
         "email": None, "phone": None, "role": None,
         "status": "inactive", "tags": ["former client"]},
        {"id": "c3", "business_id": BIZ, "name": "Marisol Vega-Ortiz",
         "email": None, "phone": None, "role": None,
         "status": "active", "tags": []},
    ])
    fb.rows("custom_modules").append(
        {"id": "m1", "business_id": BIZ, "name": "Matters", "archetype": "work_pipeline"})
    fb.rows("module_entries").extend([
        {"id": "e1", "module_id": "m1", "status": "closed",
         "data": {"title": "Whitfield v. Acme Corp", "stage": "closed",
                  "parties": ["Dana Whitfield", "Acme Corporation"]}},
        {"id": "e2", "module_id": "m1", "status": "active",
         "data": {"title": "Estate of Holloway", "notes": "opposing counsel: Smith & Vale LLP"}},
    ])
    return fb


# ─── Matching ladder ─────────────────────────────────────────────────

def test_ladder_exact_strong_possible():
    assert cr.match_strength("Dana Whitfield", "Dana Whitfield") == "exact"
    assert cr.match_strength("dana whitfield", "DANA  WHITFIELD") == "exact"
    assert cr.match_strength("Dana Whitfield", "Dana M. Whitfield") == "strong"
    assert cr.match_strength("John A. Smith", "John Smith") == "strong"
    assert cr.match_strength("Jon Smyth", "John Smith") == "possible"     # fuzzy full
    assert cr.match_strength("Whitfeild", "Whitfield") == "possible"      # misspelled token
    assert cr.match_strength("Smith", "John Smith") == "possible"         # surname sweep
    assert cr.match_strength("Marisol Vega", "Marisol Vega-Ortiz") == "strong"


def test_ladder_noise_floor():
    assert cr.match_strength("Lee", "fleet street holdings") is None      # substring ≠ word
    assert cr.match_strength("Kim", "Kimberly Ross") is None              # token ≠ prefix
    assert cr.match_strength("Dana Whitfield", "Acme Corporation") is None
    assert cr.match_strength("", "anything") is None
    assert cr.match_strength("al", "al pacino") == "possible"             # short whole word OK
    assert cr.match_strength("al", "royal albert hall") is None           # never a substring


def test_walk_and_label():
    data = {"title": "Whitfield v. Acme", "nested": {"who": ["Dana", 42]}}
    strings = cr._walk_strings(data)
    assert "Whitfield v. Acme" in strings and "Dana" in strings
    assert cr._entry_label(data) == "Whitfield v. Acme"
    assert cr._entry_label({"x": 1}) == "(untitled entry)"


# ─── Route surface ───────────────────────────────────────────────────

def test_route_exists_and_authed():
    from auth_supabase import require_user
    paths = {r.path for r in cr.router.routes}
    assert "/conflicts/check" in paths
    for r in cr.router.routes:
        assert require_user in [d.call for d in r.dependant.dependencies]


# ─── Endpoint ────────────────────────────────────────────────────────

def test_check_sweeps_contacts_and_entries_and_logs(fake):
    body = cr.CheckBody(business_id=BIZ,
                        names=["Acme Corporation", "Dana Whitfield"])
    out = asyncio.run(cr.conflicts_check(body, _User()))
    assert out["ok"] and out["logged"]

    by_query = {r["query"]: r["hits"] for r in out["results"]}
    # Adverse party found inside a matter's data — the case that matters.
    acme = by_query["Acme Corporation"]
    assert any(h["source"] == "entry" and h["label"] == "Whitfield v. Acme Corp"
               for h in acme)
    # Existing client found as contact (exact) AND in the matter.
    dana = by_query["Dana Whitfield"]
    assert dana[0]["source"] == "contact" and dana[0]["strength"] == "exact"
    assert any(h["source"] == "entry" for h in dana)
    assert dana == sorted(dana, key=lambda h: {"exact": 0, "strong": 1, "possible": 2}[h["strength"]])

    # The check IS the record — event written with the queries.
    events = fake.rows("events")
    assert len(events) == 1
    assert events[0]["event_type"] == "conflict_check"
    assert events[0]["data"]["queries"] == ["Acme Corporation", "Dana Whitfield"]
    assert events[0]["data"]["total_hits"] == out["total_hits"] > 0


def test_check_logs_even_when_clean(fake):
    out = asyncio.run(cr.conflicts_check(
        cr.CheckBody(business_id=BIZ, names=["Zebulon Frost"]), _User()))
    assert out["total_hits"] == 0
    assert out["results"][0]["hits"] == []
    assert len(fake.rows("events")) == 1   # clean checks still go on the record


def test_check_finds_former_clients_by_tag_and_phone(fake):
    out = asyncio.run(cr.conflicts_check(
        cr.CheckBody(business_id=BIZ, names=["former client", "5550102233"]), _User()))
    by_query = {r["query"]: r["hits"] for r in out["results"]}
    assert any(h["id"] == "c2" and "tags" in h["matched_on"]
               for h in by_query["former client"])
    assert any(h["id"] == "c1" and "phone" in h["matched_on"]
               and h["strength"] == "exact"
               for h in by_query["5550102233"])


def test_check_guards(fake):
    with pytest.raises(HTTPException) as e:
        asyncio.run(cr.conflicts_check(
            cr.CheckBody(business_id=BIZ, names=["Dana"]), _Stranger()))
    assert e.value.status_code == 403

    with pytest.raises(HTTPException) as e:
        asyncio.run(cr.conflicts_check(
            cr.CheckBody(business_id=BIZ, names=["  ", ""]), _User()))
    assert e.value.status_code == 400

    with pytest.raises(HTTPException) as e:
        asyncio.run(cr.conflicts_check(
            cr.CheckBody(business_id=BIZ, names=[f"n{i}" for i in range(11)]), _User()))
    assert e.value.status_code == 400
    assert fake.rows("events") == []       # nothing logged on rejected input
