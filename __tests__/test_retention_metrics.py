import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from retention_metrics import classify_contact, retention_health
from growth_intelligence import report
import chief_growth_intelligence_actions as chief

NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)


def person(id="a", days=5, health=70, status="active", **extra):
    return {"id": id, "name": "Person " + id, "status": status, "health_score": health,
            "last_interaction": (NOW-timedelta(days=days)).isoformat(), **extra}


@pytest.mark.parametrize("days,health,status,bucket", [
    (29, 40, "active", "current"), (30, 70, "active", "at_risk"),
    (59, 70, "vip", "at_risk"), (60, 90, "active", "lapsed"),
    (1, 39, "active", "at_risk"), (1, 0, "lead", "at_risk"),
    (1, None, "active", "current"), (1, 90, "inactive", "lapsed"),
    (1, 10, "churned", "lapsed"), (70, 10, "active", "lapsed"),
])
def test_one_shared_risk_boundary_and_lapsed_precedence(days, health, status, bucket):
    assert classify_contact(person(days=days, health=health, status=status), NOW)["classification"] == bucket


def test_unknown_history_is_not_invented_and_never_contacted_uses_creation():
    p = person(last_interaction=None, created_at=(NOW-timedelta(days=31)).isoformat())
    row = classify_contact(p, NOW)
    assert row["never_contacted"] and row["days_since_touch"] == 31 and row["classification"] == "at_risk"
    row = classify_contact(person(health=None, last_interaction="bad", created_at="bad"), NOW)
    assert row["health_score"] is None and row["days_since_touch"] is None
    assert not row["reasons"]


def invoice(id, **extra):
    return {"id": id, "contact_id": "a", "status": "paid", "total": 50,
            "paid_at": (NOW-timedelta(days=100-int(id))).isoformat(), **extra}


def test_unpaid_undated_future_and_foreign_currency_never_count_as_repeat_payment():
    invoices = [invoice("1", status="sent"), invoice("2", status="draft"),
                invoice("3", paid_at=None), invoice("4", currency="EUR"),
                invoice("5", paid_at=(NOW+timedelta(days=1)).isoformat())]
    r = report({"contacts": [person()], "invoices": invoices}, {"currency": "USD"}, now=NOW)
    assert r["retention_health"]["repeat_rate"] is None and r["cohorts"] == []
    assert r["retention_health"]["best_clients"] == []
    invoices += [invoice("6"), invoice("7")]
    r = report({"contacts": [person()], "invoices": invoices}, {"currency": "USD"}, now=NOW)
    assert r["retention_health"]["repeat_rate"] == 100
    assert r["retention_health"]["best_clients"][0]["collected"] == 100
    assert r["cohorts"][0]["cells"][0]["returned"] == 1


def test_all_time_rate_and_windowed_repeat_rate_are_deliberately_distinct():
    invoices = [invoice("1", paid_at=(NOW-timedelta(days=200)).isoformat()), invoice("2")]
    r = report({"contacts": [person()], "invoices": invoices}, {}, now=NOW)
    assert r["retention_health"]["repeat_rate"] == 100
    assert [cell["rate"] for cell in r["cohorts"][0]["cells"]] == [0, 0, 0]


def test_counts_reconcile_and_no_person_is_on_both_followup_lists():
    people = [person("a", 1, 35), person("b", 70, 90), person("c", 2, 80), person("d", 2, None)]
    h = retention_health(people, [], NOW)
    assert (h["total_contacts"], h["current_count"], h["at_risk_count"], h["lapsed_count"]) == (4, 3, 1, 1)
    assert h["unknown_health_count"] == 1
    assert not {p["id"] for p in h["at_risk"]} & {p["id"] for p in h["lapsed"]}


def test_chief_recall_uses_same_summary_and_pages_the_complete_followup_list(monkeypatch):
    people = [person(str(i), 31) for i in range(13)]
    r = report({"contacts": people}, {}, now=NOW)
    r.update(preferences={}, records={"actions": [], "costs": [], "attributions": []})
    page = chief.recall_view(r, {"section": "client_health", "offset": 5})
    assert page["summary"]["at_risk_count"] == 13 and page["total"] == 13
    assert len(page["rows"]) == 5 and page["next_offset"] == 10
    assert page["rows"] == r["retention_health"]["at_risk"][5:10]
    assert "at_risk" not in page["summary"]
    async def load(*args): return r
    monkeypatch.setattr(chief, "load_report", load)
    result = asyncio.run(chief.handle_growth_report(None, {"id": "business"}, {"section": "client_health"}))
    assert result["nav"] == {"tab": "grow", "sub": "retention"}
    assert result["growth_section"] == "client_health" and not result.get("failed")


def test_status_and_touch_edits_change_the_same_retention_report():
    p = person(days=45)
    assert report({"contacts": [p]}, {}, now=NOW)["retention_health"]["at_risk_count"] == 1
    p["last_interaction"] = NOW.isoformat()
    assert report({"contacts": [p]}, {}, now=NOW)["retention_health"]["at_risk_count"] == 0
    p["status"] = "inactive"
    assert report({"contacts": [p]}, {}, now=NOW)["retention_health"]["lapsed_count"] == 1


def test_interaction_coverage_compares_instants_across_timezones():
    prefs = {"timezone": "America/New_York", "history_since": "2026-09-01T04:00:00Z"}
    r = report({}, prefs, now=NOW)
    assert r["engagement"]["current_complete"] is True
    assert r["engagement"]["previous_complete"] is False
    prefs["history_since"] = "2026-09-01T04:00:01Z"
    assert report({}, prefs, now=NOW)["engagement"]["current_complete"] is False
