"""
test_module_revise.py — the builder acts on the designer's verdict.

The revision is validated like a proposal (a field it invents is
refused), applied, looked at again, and kept only when the score went
up — otherwise put back. Fake model, fake browser, fake judge; the
loop's arithmetic is what is tested.
"""
from __future__ import annotations

import json
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import module_check as mc
import module_revise as mr

BIZ = "11111111-1111-1111-1111-111111111111"
MOD = "22222222-2222-2222-2222-222222222222"


def _pipeline(**over):
    m = {"id": MOD, "business_id": BIZ, "name": "Leads", "slug": "leads", "archetype": "work_pipeline",
         "archetype_params": {"stage_field": "stage", "title_field": "title",
                              "stages": [{"id": "new", "label": "Discovery call"}, {"id": "won", "label": "Signed", "done": True}]},
         "presentation": {},
         "schema": {"fields": [
             {"name": "title", "type": "text", "label": "Lead"},
             {"name": "stage", "type": "select", "label": "Stage", "options": ["new", "won"]},
             {"name": "value", "type": "currency", "label": "Value"},
             {"name": "client", "type": "contact_link", "label": "Client"},
         ], "views": ["list", "board"], "board_column": "stage"}}
    m.update(over)
    return m


REPORT = {"design_score": 3, "first_impression": "A tidy board with no single number.",
          "findings": [{"severity": "medium", "width": 1100, "what": "No hero.", "where": "top"}],
          "next": ["a hero line with the pipeline value", "a warmer empty line"]}


# ─── validation ───────────────────────────────────────────────────────

def test_a_revision_that_names_a_real_field_passes_and_is_normalized():
    ok, err, params, pres = mr.validate(
        _pipeline(), {"stage_field": "stage", "title_field": "title", "value_field": "value",
                      "stages": [{"id": "new", "label": "Discovery call"}, {"id": "won", "label": "Signed", "done": True}]},
        {"empty_line": "The first call is the whole pipeline.", "tone": "warm"})
    assert ok, err
    assert params["value_field"] == "value" and pres["tone"] == "warm"


def test_an_invented_field_or_bad_tone_is_refused():
    ok, err, _, _ = mr.validate(_pipeline(), {"value_field": "amount_owed"}, {})
    assert not ok and "amount_owed" in err
    ok, err, _, _ = mr.validate(_pipeline(), {}, {"tone": "sassy"})
    assert not ok


# ─── the proposal ─────────────────────────────────────────────────────

class _FakeClient:
    def __init__(self, text):
        self.text = text
        self.calls = []

    @property
    def messages(self):
        outer = self

        class _M:
            def create(self, **kw):
                outer.calls.append(kw)
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=outer.text)])
        return _M()


def test_propose_returns_a_validated_change_with_its_reasons(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    import llm_call
    client = _FakeClient(json.dumps({
        "archetype_params": {"stage_field": "stage", "title_field": "title", "value_field": "value",
                             "stages": [{"id": "new", "label": "Discovery call"}, {"id": "won", "label": "Signed", "done": True}]},
        "presentation": {"empty_line": "Every client started as a call.", "tone": "warm"},
        "why": "the board had no number", "changes": ["value becomes the hero", "a warmer empty line"]}))
    monkeypatch.setattr(llm_call, "sdk_client", lambda **kw: client)
    p = mr.propose(_pipeline(), REPORT)
    assert p["ok"] and not p["unchanged"]
    assert p["archetype_params"]["value_field"] == "value" and p["changes"][0].startswith("value")
    assert p["before"]["archetype_params"]["stage_field"] == "stage"
    user = client.calls[0]["messages"][0]["content"]
    assert "value (currency)" in user and "a hero line" in user and "LEVERS" in user


def test_propose_is_honest_when_unchanged_or_invalid(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    import llm_call
    monkeypatch.setattr(llm_call, "sdk_client", lambda **kw: _FakeClient('{"unchanged": true, "why": "no lever"}'))
    p = mr.propose(_pipeline(), REPORT)
    assert p["ok"] and p["unchanged"] and p["why"] == "no lever"
    monkeypatch.setattr(llm_call, "sdk_client", lambda **kw: _FakeClient('{"archetype_params": {"value_field": "ghost"}, "presentation": {}}'))
    p = mr.propose(_pipeline(), REPORT)
    assert not p["ok"] and "revision_invalid" in p["error"]


# ─── the loop ─────────────────────────────────────────────────────────

def _page(url):
    return {"url": url, "widths": {"390": {"overflow_x": False, "broken_images": [], "empty_headings": 0,
                                           "leftover_tokens": [], "overlaps": []},
                                   "1100": {"overflow_x": False, "broken_images": [], "empty_headings": 0,
                                            "leftover_tokens": [], "overlaps": []}},
            "shots": {"390": b"j", "1100": b"j"}, "console_errors": [], "failed_requests": []}


@pytest.fixture
def loop(monkeypatch):
    """A module, a browser that always opens, a judge whose score follows
    whether value_field is set, and a DB that records patches."""
    import sb_clients
    import site_check
    monkeypatch.setenv("PREVIEW_SECRET", "s")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    state = {"module": _pipeline(), "patches": []}

    def get(path):
        if path.startswith("/custom_modules?"):
            return [state["module"]]
        return []

    def patch(path, body):
        state["patches"].append(body)
        state["module"] = {**state["module"], **body}
        return [body]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    monkeypatch.setattr(site_check, "inspect_pages", lambda urls, widths=(), screenshots=True: [_page(urls[0])])
    monkeypatch.setattr(site_check, "_store_shots", lambda b, r, pages: [f"shot-{len(state['patches'])}"])

    def judge(page, b, module):
        hero = bool((module.get("archetype_params") or {}).get("value_field"))
        return {"findings": [] if hero else [{"severity": "medium", "width": 1100, "source": "vision",
                                                "what": "No hero.", "where": "top"}],
                "design_score": 4 if hero else 3, "first_impression": "ok",
                "next": [] if hero else ["a hero line with the pipeline value"]}
    monkeypatch.setattr(mc, "judge", judge)
    return state


GOOD = json.dumps({"archetype_params": {"stage_field": "stage", "title_field": "title", "value_field": "value",
                                        "stages": [{"id": "new", "label": "Discovery call"}, {"id": "won", "label": "Signed", "done": True}]},
                   "presentation": {"tone": "warm"}, "why": "no number", "changes": ["value is the hero"]})


def test_the_loop_revises_looks_again_and_keeps_a_better_score(loop, monkeypatch):
    import llm_call
    monkeypatch.setattr(llm_call, "sdk_client", lambda **kw: _FakeClient(GOOD))
    said = []
    rep = mc.run(BIZ, MOD, progress_cb=lambda p, s: said.append((p, s)))
    assert rep["ok"] and rep["design_score"] == 4
    rv = rep["revision"]
    assert rv["attempted"] and rv["applied"] and rv["kept"] and (rv["before_score"], rv["after_score"]) == (3, 4)
    assert loop["module"]["archetype_params"]["value_field"] == "value"      # the change stayed
    assert len(loop["patches"]) == 1
    assert "Chief revised the design (3→4): value is the hero." in rep["summary"]
    assert rep["findings"] == [] and len(rep["screenshots"]) == 2
    assert any("revising" in s for _, s in said) and [p for p, _ in said] == sorted(p for p, _ in said)
    assert "Revised by Chief (3→4)" in mc.describe(rep)


def test_a_revision_that_does_not_score_higher_is_put_back(loop, monkeypatch):
    import llm_call
    # the reviser changes only the tone: the judge still sees no hero → 3 again
    monkeypatch.setattr(llm_call, "sdk_client", lambda **kw: _FakeClient(json.dumps({
        "archetype_params": _pipeline()["archetype_params"], "presentation": {"tone": "bold"},
        "why": "louder", "changes": ["bold tone"]})))
    rep = mc.run(BIZ, MOD)
    rv = rep["revision"]
    assert rv["applied"] and not rv["kept"] and rv["after_score"] == 3
    assert loop["module"]["presentation"] == {} and len(loop["patches"]) == 2     # applied, then put back
    assert "put back" in rep["summary"] and rep["design_score"] == 3


def test_a_good_score_or_no_next_moves_is_left_alone(loop, monkeypatch):
    loop["module"]["archetype_params"]["value_field"] = "value"       # judge → 4/5, no next
    calls = []
    import llm_call
    monkeypatch.setattr(llm_call, "sdk_client", lambda **kw: (calls.append(1), _FakeClient(GOOD))[1])
    rep = mc.run(BIZ, MOD)
    assert rep["design_score"] == 4 and rep["revision"] is None and not calls and not loop["patches"]


def test_revise_can_be_switched_off(loop, monkeypatch):
    monkeypatch.setenv("MODULE_REVISE", "off")
    rep = mc.run(BIZ, MOD)
    assert rep["design_score"] == 3 and rep["revision"] is None and not loop["patches"]
    monkeypatch.delenv("MODULE_REVISE")
    rep = mc.run(BIZ, MOD, revise=False)
    assert rep["revision"] is None
