"""
Every Solutionist site, legible to a customer's agent (2026-09-04).

Three surfaces, one source of truth: JSON-LD in every served head, the
manifest + llms.txt on the site's origin, and the cheap JSON API on the
API host. The tests are weighted toward the claims the structured data
must NEVER make — a hidden price, 24/7 hours for a business that never
set any, a booking door for a vertical the client layer refuses.
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_site as ag


# ─── fixtures ────────────────────────────────────────────────────────

WEEKLY = {"timezone": "America/New_York",
          "weekly": {"mon": [{"start": "09:00", "end": "17:00"}],
                     "tue": [{"start": "09:00", "end": "12:00"},
                             {"start": "13:00", "end": "17:00"}],
                     "wed": [], "thu": [{"start": "09:00", "end": "17:00"}],
                     "fri": [{"start": "09:00", "end": "15:00"}],
                     "sat": [], "sun": []}}

BIZ = {"id": "biz-1", "name": "Bloom Studio", "type": "salon", "owner_id": "own-1",
       "settings": {"contact_phone": "216-555-0100", "contact_email": "hi@bloom.test",
                    "address": "12 Main St", "brand_kit": {"tagline": "Hair that holds."},
                    "link_page": {"phone": "IGNORED", "social_profiles":
                                  {"instagram": "https://instagram.com/bloom"}},
                    "availability": WEEKLY}}
SITE = {"slug": "bloom", "site_config": {"custom_domain": "bloom.test"}}
PROFILE = {"phone": "IGNORED-TOO", "address_city": "Cleveland", "address_state": "OH",
           "timezone": "America/Chicago"}

OFFERINGS = [
    {"id": "o-cut", "name": "Cut & style", "slug": "cut", "category": "service",
     "description": "Wash, cut, finish.", "current_price": 45, "currency": "usd",
     "duration_min": 45, "show_price_to_customer": True},
    {"id": "o-color", "name": "Color consult", "slug": "color", "category": "session",
     "description": None, "current_price": 120, "currency": "USD",
     "duration_min": 60, "show_price_to_customer": False},
    {"id": "o-oil", "name": "Argan oil", "slug": "oil", "category": "product",
     "description": "100ml", "current_price": 22, "currency": "USD",
     "duration_min": None, "show_price_to_customer": True},
]


def facts():
    return ag.resolve_facts(BIZ, SITE, PROFILE)


# ─── facts: one precedence, stated ───────────────────────────────────

def test_facts_prefer_the_page_over_the_profile():
    f = facts()
    assert f["phone"] == "216-555-0100", "settings.contact_phone beats link_page and profile"
    assert f["origin"] == "https://bloom.test", "the custom domain is the origin"
    assert f["booking_url"] == "https://bloom.test/book"
    assert f["timezone"] == "America/New_York", "availability.timezone beats the profile"
    assert f["city"] == "Cleveland" and f["region"] == "OH"
    assert f["same_as"] == ["https://instagram.com/bloom"]


def test_facts_fall_back_to_the_subdomain_and_the_profile():
    f = ag.resolve_facts({"id": "b", "name": "X", "settings": {}},
                         {"slug": "x", "site_config": {}}, PROFILE)
    assert f["origin"] == "https://x.mysolutionist.app"
    assert f["phone"] == "IGNORED-TOO"
    assert f["timezone"] == "America/Chicago"


# ─── hours: the engine's, never a guess ──────────────────────────────

def test_opening_hours_come_from_the_booking_availability():
    spec = ag.opening_hours(WEEKLY)
    days = [(s["dayOfWeek"].rsplit("/", 1)[1], s["opens"], s["closes"]) for s in spec]
    assert ("Monday", "09:00", "17:00") in days
    assert ("Tuesday", "09:00", "12:00") in days and ("Tuesday", "13:00", "17:00") in days
    assert not any(d[0] in ("Wednesday", "Saturday", "Sunday") for d in days)
    assert all(s["@type"] == "OpeningHoursSpecification" for s in spec)


def test_open_default_makes_no_hours_claim():
    """The engine treats 'nothing configured' as bookable 24/7. That is
    a booking rule, not a fact to print about the business."""
    assert ag.opening_hours(None) == []
    assert ag.opening_hours({}) == []
    assert ag.hours_lines({}) == []


def test_hours_lines_say_closed_days():
    lines = ag.hours_lines(WEEKLY)
    assert "Wednesday: closed" in lines
    assert "Tuesday: 09:00–12:00, 13:00–17:00" in lines


# ─── offerings: a hidden price is absent, not null ───────────────────

def test_hidden_price_is_absent():
    pub = ag.public_offering(OFFERINGS[1])
    assert "price" not in pub and "currency" not in pub
    shown = ag.public_offering(OFFERINGS[0])
    assert shown["price"] == 45 and shown["currency"] == "USD"


def test_bookable_needs_a_slot_category_and_a_duration():
    assert ag.public_offering(OFFERINGS[0])["bookable"] is True
    assert ag.public_offering(OFFERINGS[2])["bookable"] is False, "a product is not booked by the slot"
    assert ag.public_offering({**OFFERINGS[0], "duration_min": None})["bookable"] is False


# ─── JSON-LD ─────────────────────────────────────────────────────────

def test_jsonld_graph_shape():
    doc = ag.business_jsonld(facts(), OFFERINGS)
    assert doc["@context"] == "https://schema.org"
    biz, *nodes = doc["@graph"]
    assert biz["@type"] == "LocalBusiness" and biz["@id"] == "https://bloom.test/#business"
    assert biz["telephone"] == "216-555-0100" and biz["email"] == "hi@bloom.test"
    assert biz["address"]["addressLocality"] == "Cleveland"
    assert biz["openingHoursSpecification"]
    assert biz["potentialAction"]["@type"] == "ReserveAction"
    assert biz["potentialAction"]["target"]["urlTemplate"] == "https://bloom.test/book"
    assert {n["@type"] for n in nodes} == {"Service", "Product"}
    assert len(biz["makesOffer"]) == 3


def test_jsonld_offering_nodes_keep_the_price_rule():
    doc = ag.business_jsonld(facts(), OFFERINGS)
    by_name = {n["name"]: n for n in doc["@graph"][1:]}
    assert by_name["Cut & style"]["offers"]["price"] == 45
    assert by_name["Cut & style"]["duration"] == "PT45M"
    assert by_name["Cut & style"]["potentialAction"]["@type"] == "ReserveAction"
    assert "offers" not in by_name["Color consult"], "a hidden price stays hidden"
    assert "potentialAction" not in by_name["Argan oil"]
    assert by_name["Argan oil"]["offers"]["url"] == "https://bloom.test/store"


def test_render_escapes_a_closing_script_in_content():
    """A description that says </script> must not close the block."""
    doc = ag.business_jsonld(facts(), [{**OFFERINGS[0], "description": "x</script><b>y"}])
    tag = ag.render_jsonld_tag(doc)
    assert tag.count("</script>") == 1
    assert "<\\/script>" in tag
    assert ag._MARK in tag


_PAGE = ('<html><head><title>T</title>'
         '<script type="application/ld+json">{"@context":"https://schema.org",'
         '"@type": "LocalBusiness","name":"Old","openingHours":"09:00–17:00"}</script>'
         '<script type="application/ld+json">{"@type":"Article","headline":"News"}</script>'
         '</head><body>hi</body></html>')


def test_injection_replaces_the_builders_localbusiness_and_keeps_articles():
    tag = ag.render_jsonld_tag(ag.business_jsonld(facts(), OFFERINGS))
    out = ag.inject_jsonld(_PAGE, tag)
    assert out.count("application/ld+json") == 2, "ours + the Article; the stale one is gone"
    assert '"name":"Old"' not in out
    assert '"Article"' in out
    assert out.index(ag._MARK) < out.index("</head>")


def test_injection_is_idempotent():
    tag = ag.render_jsonld_tag(ag.business_jsonld(facts(), OFFERINGS))
    once = ag.inject_jsonld(_PAGE, tag)
    assert ag.inject_jsonld(once, tag) == once


def test_injection_never_raises_and_returns_the_page_on_failure(monkeypatch):
    monkeypatch.setattr(ag, "_load_bundle", lambda b: (_ for _ in ()).throw(RuntimeError("db")))
    assert ag.inject_into_page(_PAGE, "biz-1") == _PAGE
    monkeypatch.setattr(ag, "_load_bundle", lambda b: None)
    assert ag.inject_into_page(_PAGE, "biz-1") == _PAGE


def test_public_site_runs_the_injection_in_augment_html():
    import inspect
    import public_site as ps
    src = inspect.getsource(ps._augment_html)
    assert "agent_site.inject_into_page" in src
    assert src.index("_inject_brand_meta(") < src.index("agent_site.inject_into_page")


def test_public_site_serves_the_manifest_and_llms_on_both_branches():
    import inspect
    import public_site as ps
    for fn in (ps._serve_site_by_slug, ps._serve_site_by_custom_domain):
        src = inspect.getsource(fn)
        assert "/.well-known/agent.json" in src, fn.__name__
        assert "/llms.txt" in src, fn.__name__
        assert "_agent_artifact(" in src, fn.__name__


# ─── manifest + llms.txt ─────────────────────────────────────────────

def test_manifest_advertises_booking_only_when_open():
    m = ag.manifest(facts(), OFFERINGS, booking_open=True)
    assert m["schema"] == ag.MANIFEST_SCHEMA
    assert m["capabilities"]["book"] is True
    assert m["endpoints"]["book"]["url"].endswith("/public/agent/bloom/book")
    assert m["endpoints"]["availability"]["url"].endswith("/public/agent/bloom/availability")
    assert m["booking_page"] == "https://bloom.test/book"
    assert m["capabilities"]["pay"] is False and m["capabilities"]["message_business"] is False

    closed = ag.manifest(facts(), OFFERINGS, booking_open=False)
    assert closed["capabilities"]["book"] is False
    assert "book" not in closed["endpoints"] and "availability" not in closed["endpoints"]
    assert closed["endpoints"]["services"]


def test_manifest_offerings_follow_the_price_rule():
    m = ag.manifest(facts(), OFFERINGS, booking_open=True)
    by = {o["name"]: o for o in m["offerings"]}
    assert "price" not in by["Color consult"] and by["Cut & style"]["price"] == 45


def test_llms_txt_reads_like_a_fact_sheet():
    text = ag.llms_txt(facts(), OFFERINGS, booking_open=True)
    assert text.startswith("# Bloom Studio")
    assert "Phone: 216-555-0100" in text
    assert "- Cut & style — 45 min — USD 45: Wash, cut, finish." in text
    assert "- Color consult — 60 min" in text and "USD 120" not in text
    assert "Wednesday: closed" in text
    assert "Book online: https://bloom.test/book" in text
    assert ".well-known/agent.json" in text
    closed = ag.llms_txt(facts(), OFFERINGS, booking_open=False)
    assert "not offered" in closed and "Book online" not in closed


# ─── the API ─────────────────────────────────────────────────────────

class _Verdict:
    def __init__(self, allowed=True, reason="ok"):
        self.allowed = allowed
        self.reason = reason


@pytest.fixture
def api(monkeypatch):
    bundle = {"facts": facts(), "offerings": OFFERINGS, "booking_open": True, "biz": BIZ}
    monkeypatch.setattr(ag, "_bundle_by_slug", lambda s: bundle if s == "bloom" else None)
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda bucket, key: True)
    import policy_engine
    monkeypatch.setattr(policy_engine, "evaluate_client",
                        lambda *a, **k: _Verdict(True, "client:agent"))
    app = FastAPI()
    app.include_router(ag.router)
    return TestClient(app), bundle


def test_services_endpoint(api):
    client, _ = api
    r = client.get("/public/agent/bloom/services")
    assert r.status_code == 200
    body = r.json()
    assert body["business"]["name"] == "Bloom Studio"
    assert body["booking"]["open"] is True and body["booking"]["page"] == "https://bloom.test/book"
    names = {o["name"] for o in body["offerings"]}
    assert names == {"Cut & style", "Color consult", "Argan oil"}


def test_unknown_slug_is_404(api):
    client, _ = api
    assert client.get("/public/agent/nobody/services").status_code == 404


def test_the_limiter_fails_closed(api, monkeypatch):
    client, _ = api
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda bucket, key: False)
    assert client.get("/public/agent/bloom/services").status_code == 429


def test_the_client_policy_is_asked_as_an_agent(api, monkeypatch):
    client, _ = api
    seen = {}
    import policy_engine

    def _eval(business_id, *, verb, actor, biz_row=None, **k):
        seen.update(verb=verb, actor=actor)
        return _Verdict(False, "A client-facing portal is not available for this practice.")
    monkeypatch.setattr(policy_engine, "evaluate_client", _eval)
    r = client.get("/public/agent/bloom/services")
    assert r.status_code == 403
    assert seen == {"verb": "client_view_booking_config", "actor": "client_agent"}
    assert "not available" in r.json()["detail"]


def test_availability_is_bounded_and_per_offering(api, monkeypatch):
    client, _ = api
    calls = {}

    def _slots(**kw):
        calls.update(kw)
        return [{"start_utc": "2026-09-14T13:00:00+00:00",
                 "start_local": "2026-09-14T09:00:00", "duration_min": 45}]
    import availability_engine
    monkeypatch.setattr(availability_engine, "compute_slots", _slots)
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [])

    r = client.get("/public/agent/bloom/availability",
                   params={"offering_id": "o-cut", "from": "2026-09-14", "to": "2026-09-20"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slots"][0]["start_utc"].startswith("2026-09-14")
    assert body["timezone"] == "America/New_York"
    assert calls["offering_duration_min"] == 45
    assert calls["from_date"] == date(2026, 9, 14) and calls["to_date"] == date(2026, 9, 20)

    too_long = client.get("/public/agent/bloom/availability",
                          params={"offering_id": "o-cut", "from": "2026-09-01", "to": "2026-09-30"})
    assert too_long.status_code == 400
    not_bookable = client.get("/public/agent/bloom/availability",
                              params={"offering_id": "o-oil"})
    assert not_bookable.status_code == 400
    missing = client.get("/public/agent/bloom/availability", params={"offering_id": "nope"})
    assert missing.status_code == 404


def test_availability_is_refused_when_booking_is_closed(api):
    client, bundle = api
    bundle["booking_open"] = False
    r = client.get("/public/agent/bloom/availability", params={"offering_id": "o-cut"})
    assert r.status_code == 404
    bundle["booking_open"] = True


def test_book_rides_the_walk_in_flow_and_names_the_agent(api, monkeypatch):
    client, _ = api
    import booking_widget_router as bw
    seen = {}

    async def _book_anon(business_id, body, request):
        seen["business_id"] = business_id
        seen["body"] = body
        return {"ok": True, "appointment_id": "appt-1", "token": "tok.sig"}
    monkeypatch.setattr(bw, "book_anon", _book_anon)
    monkeypatch.setattr(bw, "_bookings_module",
                        lambda b: {"id": "m1", "archetype_params": {"primary_date_field": "when"}})
    ledger = []
    import audit_log
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: ledger.append((a, k)) or True)

    r = client.post("/public/agent/bloom/book", json={
        "name": "Ada Lovelace", "email": "ada@example.com", "offering_id": "o-cut",
        "start": "2026-09-14T13:00:00Z", "agent": "ChatGPT", "notes": "first visit"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["appointment_id"] == "appt-1"
    assert body["manage_url"] == "https://bloom.test/book?token=tok.sig"

    assert seen["business_id"] == "biz-1"
    sent = seen["body"]
    assert sent.name == "Ada Lovelace" and sent.offering_id == "o-cut"
    assert sent.data["when"] == "2026-09-14T13:00:00Z"
    assert sent.data["appointment_at"] == "2026-09-14T13:00:00Z"
    assert sent.data["booked_via"] == "agent:ChatGPT"
    assert sent.data["notes"] == "first visit"
    assert sent.sms_consent is False
    assert sent.quoted_price is None, "no price is quoted, so no drift gate can refuse"

    (biz_id,), kw = ledger[0]
    assert biz_id == "biz-1"
    assert kw["actor_type"] == "client" and kw["actor_id"] == "agent:ChatGPT"
    assert kw["authorized_by"] == "client:agent" and kw["source"] == "agent_site"
    assert kw["target_id"] == "appt-1"


def test_book_requires_an_agent_name_and_a_real_start(api):
    client, _ = api
    base = {"name": "Ada", "email": "ada@example.com", "offering_id": "o-cut",
            "start": "2026-09-14T13:00:00Z"}
    assert client.post("/public/agent/bloom/book", json=base).status_code == 422
    assert client.post("/public/agent/bloom/book",
                       json={**base, "agent": "X", "start": "next tuesday"}).status_code == 422
    assert client.post("/public/agent/bloom/book",
                       json={**base, "agent": "X", "email": "nope"}).status_code == 422


def test_book_refuses_a_product_and_a_closed_business(api):
    client, bundle = api
    body = {"name": "Ada", "email": "ada@example.com", "offering_id": "o-oil",
            "start": "2026-09-14T13:00:00Z", "agent": "X"}
    assert client.post("/public/agent/bloom/book", json=body).status_code == 404
    bundle["booking_open"] = False
    assert client.post("/public/agent/bloom/book",
                       json={**body, "offering_id": "o-cut"}).status_code == 404
    bundle["booking_open"] = True


def test_router_is_registered_before_the_catch_all():
    src = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert src.index("agent_site_router") < src.index("app.include_router(public_site_router)")


def test_rate_bucket_exists_and_is_strict_capable():
    import rate_limit
    assert "agent_site" in rate_limit._LIMITS
