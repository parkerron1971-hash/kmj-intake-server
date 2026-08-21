"""THE SOURCING DESK stage 1 — the citation gate, and the two gates on cost.

The test that matters most here is that an INVENTED vendor cannot reach a
practitioner. The rule is "no citation, no card", and it is enforced by a
set intersection against the URLs Anthropic's search tool actually
returned — not by a line in a prompt. A prompt instruction is a request;
these tests are about the guarantee.

The second cluster is money: a sourcing run costs real searches and two
model calls, so the daily circuit breaker must fire BEFORE the meter, and
a run that finds nothing must not pay for a second pass.
"""
from __future__ import annotations

import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import HTTPException

import llm_call
import sourcing_engine as se
import sourcing_router as sr


class _Resp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self._payload


def _search_block(*urls):
    return {"type": "web_search_tool_result",
            "content": [{"type": "web_search_result", "url": u} for u in urls]}


def _text_block(t):
    return {"type": "text", "text": t}


# ─── Harvesting what the search really returned ──────────────────────

def test_harvest_collects_result_urls():
    data = {"content": [_text_block("notes"),
                        _search_block("https://northwind.com/wholesale",
                                      "https://acme.com/trade")]}
    assert se._harvest_sources(data) == ["https://northwind.com/wholesale",
                                         "https://acme.com/trade"]


@pytest.mark.parametrize("broken", [
    # The documented error shape: a single error OBJECT, not a list.
    {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"},
    # The shape that actually raises if it reaches a for-loop.
    None,
    # And a scalar, for good measure.
    "max_uses_exceeded",
])
def test_a_search_tool_ERROR_does_not_blow_up_a_paid_request(broken):
    """Server-tool errors don't raise — they come back as HTTP 200 whose
    result content is not a list of results. A null one reaches a
    for-loop as a TypeError, in the middle of something the practitioner
    has already paid for; an error object would iterate as its keys and
    yield nothing at all, which is wrong but silent. Both must survive,
    and the good result alongside them must still be harvested."""
    data = {"content": [
        {"type": "web_search_tool_result", "content": broken},
        _search_block("https://real.com/a"),
    ]}
    assert se._harvest_sources(data) == ["https://real.com/a"]


def test_harvest_deduplicates_the_same_page():
    data = {"content": [_search_block("https://www.northwind.com/wholesale/",
                                      "https://northwind.com/wholesale")]}
    assert len(se._harvest_sources(data)) == 1


# ─── THE CITATION GATE ───────────────────────────────────────────────

def test_an_invented_vendor_is_dropped():
    """The failure this exists to stop: a plausible company with a
    plausible address that no search result ever mentioned."""
    sources = ["https://northwind.com/wholesale"]
    cands = [
        {"name": "Northwind Supply", "website": "northwind.com",
         "source_url": "https://northwind.com/wholesale", "why": "", "moq": "",
         "region": "", "contact_route": ""},
        {"name": "Ghost Manufacturing", "website": "ghostmfg.com",
         "source_url": "https://ghostmfg.com/wholesale", "why": "", "moq": "",
         "region": "", "contact_route": ""},
    ]
    kept, dropped = se._surviving(cands, sources)
    assert [c["name"] for c in kept] == ["Northwind Supply"]
    assert dropped == 1


def test_a_candidate_with_no_citation_at_all_is_dropped():
    kept, dropped = se._surviving(
        [{"name": "Nameless", "website": "x.com", "source_url": "",
          "why": "", "moq": "", "region": "", "contact_route": ""}],
        ["https://real.com/a"])
    assert kept == []
    assert dropped == 1


def test_a_real_citation_survives_www_slash_and_tracking_params():
    """Failing closed on cosmetic URL differences would reject honest
    citations while catching no invented ones — an invented URL does not
    accidentally share a host AND path with a real result."""
    kept, dropped = se._surviving(
        [{"name": "Northwind", "website": "northwind.com",
          "source_url": "https://www.northwind.com/wholesale/?utm_source=x",
          "why": "", "moq": "", "region": "", "contact_route": ""}],
        ["https://northwind.com/wholesale"])
    assert dropped == 0
    assert len(kept) == 1


def test_the_stored_url_is_the_SEARCHES_url_not_the_models_retyping():
    kept, _ = se._surviving(
        [{"name": "Northwind", "website": "northwind.com",
          "source_url": "https://www.northwind.com/wholesale/?utm_source=x",
          "why": "", "moq": "", "region": "", "contact_route": ""}],
        ["https://northwind.com/wholesale"])
    assert kept[0]["source_url"] == "https://northwind.com/wholesale"


def test_one_card_per_company():
    sources = ["https://northwind.com/a", "https://northwind.com/b"]
    cands = [
        {"name": "Northwind", "website": "https://northwind.com",
         "source_url": "https://northwind.com/a", "why": "", "moq": "",
         "region": "", "contact_route": ""},
        {"name": "Northwind Supply Co", "website": "https://northwind.com",
         "source_url": "https://northwind.com/b", "why": "", "moq": "",
         "region": "", "contact_route": ""},
    ]
    kept, dropped = se._surviving(cands, sources)
    assert len(kept) == 1
    assert dropped == 1


def test_the_list_is_capped_rather_than_unbounded():
    sources = [f"https://v{i}.com/x" for i in range(20)]
    cands = [{"name": f"V{i}", "website": f"v{i}.com",
              "source_url": f"https://v{i}.com/x", "why": "", "moq": "",
              "region": "", "contact_route": ""} for i in range(20)]
    kept, _ = se._surviving(cands, sources)
    assert len(kept) == se.MAX_CANDIDATES


# ─── End to end, with the model faked ────────────────────────────────

def test_a_dropped_candidate_is_said_out_loud(monkeypatch):
    """A silent trim reads as 'this is everything there is'."""
    calls = []

    def fake_post(payload, **kw):
        calls.append(payload)
        if len(calls) == 1:
            return _Resp({"content": [
                _text_block("Found Northwind and maybe others."),
                _search_block("https://northwind.com/wholesale")]})
        return _Resp({"content": [_text_block(json.dumps({
            "candidates": [
                {"name": "Northwind", "website": "northwind.com",
                 "source_url": "https://northwind.com/wholesale", "why": "fits",
                 "moq": "", "region": "US", "contact_route": "form"},
                {"name": "Ghost Mfg", "website": "ghost.com",
                 "source_url": "https://ghost.com/made-up", "why": "fits",
                 "moq": "", "region": "US", "contact_route": "form"},
            ],
            "coverage_note": "Apparel blanks are well covered.",
        }))]})

    monkeypatch.setattr(llm_call, "post", fake_post)
    out = se.search_vendors(need="blank hoodies")
    assert [c["name"] for c in out["candidates"]] == ["Northwind"]
    assert out["dropped_count"] == 1
    assert out["proposed_count"] == 2
    assert "couldn't be traced back" in out["coverage_note"]


def test_no_search_results_means_no_second_call_is_paid_for(monkeypatch):
    calls = []

    def fake_post(payload, **kw):
        calls.append(payload)
        return _Resp({"content": [_text_block("I couldn't find anything.")]})

    monkeypatch.setattr(llm_call, "post", fake_post)
    out = se.search_vendors(need="something extremely niche")
    assert len(calls) == 1, "paid for an extraction over zero sources"
    assert out["candidates"] == []
    assert out["coverage_note"]


def test_a_model_failure_returns_an_answer_not_a_500(monkeypatch):
    monkeypatch.setattr(llm_call, "post", lambda payload, **kw: _Resp(None, status=529))
    out = se.search_vendors(need="blank hoodies")
    assert out["candidates"] == []
    assert "try again" in out["coverage_note"].lower()


def test_pass_one_actually_asks_for_a_web_search(monkeypatch):
    """The whole feature is the live search. A payload that forgot the
    tool would still return prose and look like it worked."""
    seen = {}

    def fake_post(payload, **kw):
        seen.setdefault("first", payload)
        return _Resp({"content": [_text_block("x")]})

    monkeypatch.setattr(llm_call, "post", fake_post)
    se.search_vendors(need="blank hoodies")
    tools = seen["first"].get("tools") or []
    assert any(t.get("type", "").startswith("web_search") for t in tools)
    assert tools[0]["max_uses"] == se._MAX_SEARCHES


# ─── The two gates on cost ───────────────────────────────────────────

class _U:
    id = "owner"


BIZ = "biz1"


def _stub_biz(monkeypatch, search_count):
    def _get(path):
        if path.startswith("/businesses"):
            return [{"id": BIZ, "owner_id": "owner", "name": "Kev's", "industry": "retail"}]
        if path.startswith("/sourcing_searches"):
            return [{"id": f"s{i}"} for i in range(search_count)]
        return []
    monkeypatch.setattr(sr.sb_clients, "sb_get_as_service", _get)


def test_the_daily_cap_fires_BEFORE_the_meter(monkeypatch):
    """Order matters: metering a capped business would charge them for a
    search they are not going to get."""
    _stub_biz(monkeypatch, sr.DAILY_SEARCH_CAP)
    metered = []
    monkeypatch.setattr(sr.billing_limits, "require_units",
                        lambda biz: metered.append(biz))
    monkeypatch.setattr(sr.sourcing_engine, "search_vendors",
                        lambda **kw: pytest.fail("ran a search past the cap"))

    with pytest.raises(HTTPException) as e:
        sr.run_search(BIZ, sr.SearchBody(need="blank hoodies"), user=_U())
    assert e.value.status_code == 429
    assert metered == [], "metered a business that was already capped"


def test_under_the_cap_it_meters_and_runs(monkeypatch):
    _stub_biz(monkeypatch, 1)
    metered = []
    monkeypatch.setattr(sr.billing_limits, "require_units",
                        lambda biz: metered.append(biz))
    monkeypatch.setattr(sr.sourcing_engine, "search_vendors", lambda **kw: {
        "candidates": [], "sources": [], "coverage_note": "n",
        "proposed_count": 0, "dropped_count": 0, "model": "m"})
    monkeypatch.setattr(sr.sb_clients, "sb_post_as_service",
                        lambda p, b, **kw: [{"id": "new", **b}])
    out = sr.run_search(BIZ, sr.SearchBody(need="blank hoodies"), user=_U())
    assert out["ok"]
    assert metered == [BIZ]


def test_a_failed_receipt_does_not_lose_the_answer(monkeypatch):
    """They already paid for the search. Failing the response because the
    row would not save charges them and shows them nothing."""
    _stub_biz(monkeypatch, 0)
    monkeypatch.setattr(sr.billing_limits, "require_units", lambda biz: None)
    monkeypatch.setattr(sr.sourcing_engine, "search_vendors", lambda **kw: {
        "candidates": [{"name": "Northwind"}], "sources": ["u"],
        "coverage_note": "n", "proposed_count": 1, "dropped_count": 0,
        "model": "m"})

    def _boom(p, b, **kw):
        raise RuntimeError("supabase is having a day")
    monkeypatch.setattr(sr.sb_clients, "sb_post_as_service", _boom)

    out = sr.run_search(BIZ, sr.SearchBody(need="blank hoodies"), user=_U())
    assert out["ok"]
    assert out["search"]["candidates"] == [{"name": "Northwind"}]


def test_an_empty_need_is_refused_before_anything_is_spent(monkeypatch):
    _stub_biz(monkeypatch, 0)
    monkeypatch.setattr(sr.billing_limits, "require_units",
                        lambda biz: pytest.fail("metered an empty search"))
    with pytest.raises(HTTPException) as e:
        sr.run_search(BIZ, sr.SearchBody(need="  "), user=_U())
    assert e.value.status_code == 400


def test_a_non_owner_cannot_spend_the_businesss_money(monkeypatch):
    monkeypatch.setattr(sr.sb_clients, "sb_get_as_service",
                        lambda path: [{"id": BIZ, "owner_id": "somebody-else"}])

    class _Other:
        id = "intruder"

    with pytest.raises(HTTPException) as e:
        sr.run_search(BIZ, sr.SearchBody(need="blank hoodies"), user=_Other())
    assert e.value.status_code == 403
