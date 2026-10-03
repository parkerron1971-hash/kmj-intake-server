"""
test_vision_grader_whole_page.py — the grader sees the whole page (2026-10-03).

The grader used to screenshot only the first 900px at 390/900/1440, so a
page was scored on its hero alone. Now views further down the page ride
along at 1440 and 390; impact is still read from the first screen only.
"""
import json
from types import SimpleNamespace
from unittest import mock

import vision_grader as vg


# ─── where the views further down sit ────────────────────────────────

def test_a_page_barely_taller_than_a_screen_gets_no_views_further_down():
    assert vg.scroll_stops(900, 4) == []
    assert vg.scroll_stops(950, 4) == []


def test_a_page_just_over_two_screens_gets_one_view_not_two_of_the_same():
    assert vg.scroll_stops(1900, 4) == [1000]


def test_a_long_page_gets_evenly_spaced_views_down_to_the_footer():
    stops = vg.scroll_stops(9000, 4)
    assert stops == [900, 3300, 5700, 8100]
    assert stops[-1] == 9000 - vg.VIEWPORT_H          # the last screen (footer)
    assert len(vg.scroll_stops(30000, 3)) == 3          # the cap holds
    assert vg.scroll_stops(9000, 0) == []


# ─── the judge's message ─────────────────────────────────────────────

def _img(shot):
    return {"type": "image", "data": shot}


def test_first_screens_and_views_further_down_are_labeled_in_order():
    content = vg._content([b"a", b"b", b"c"],
                          [("1440px, further down 1 of 2 (from 900px on a 5,000px page)", b"d"),
                           ("390px, further down 1 of 1 (from 4,100px on a 5,000px page)", b"e")],
                          _img)
    texts = [c["text"] for c in content if c.get("type") == "text"]
    images = [c["data"] for c in content if c.get("type") == "image"]
    assert images == [b"a", b"b", b"c", b"d", b"e"]
    assert texts[:3] == ["FIRST SCREEN — breakpoint 390px:",
                         "FIRST SCREEN — breakpoint 900px:",
                         "FIRST SCREEN — breakpoint 1440px:"]
    assert texts[3].startswith("FURTHER DOWN — 1440px") and texts[4].startswith("FURTHER DOWN — 390px")
    assert texts[-1] == "Grade per the rubric. Verdict JSON only."


def test_with_no_views_further_down_the_message_is_the_first_screens():
    content = vg._content([b"a", b"b", b"c"], None, _img)
    assert sum(1 for c in content if c.get("type") == "image") == 3


def test_the_rubric_reads_impact_from_the_first_screen_and_the_rest_from_the_page():
    r = vg.RUBRIC
    assert "FURTHER DOWN" in r and "judged ONLY from the first-screen images" in r
    for axis in ("BALANCE & COLLISION — across the WHOLE page",
                 "MOTIF VISIBILITY — across the whole page",
                 "RHYTHM — across the whole page"):
        assert axis in r, axis
    assert "STATIC screenshots" in r and "NEVER penalize" in r
    assert "below_fold_note" in r


def test_the_rubric_era_moves_so_old_live_verdicts_are_regraded():
    assert vg.RUBRIC_VERSION == "page-1"


# ─── the verdict ──────────────────────────────────────────────────────

_VERDICT = {"first_viewport_impact": 8, "balance": 9, "motif_visibility": 7, "rhythm": 8,
            "template_smell": 2, "broken": "n", "broken_where": "",
            "below_fold_note": "The letterboard and gallery hold the hero's quality.",
            "notes": ["Tighten the hours table."]}


def test_the_below_fold_note_is_kept_and_optional():
    v = vg._parse_verdict(json.dumps(_VERDICT))
    assert v["below_fold_note"].startswith("The letterboard")
    assert vg.verdict_composite(v) == 30                 # the composite is unchanged
    bare = dict(_VERDICT)
    bare.pop("below_fold_note")
    assert "below_fold_note" not in vg._parse_verdict(json.dumps(bare))


def test_grade_hands_the_views_further_down_to_the_judge(monkeypatch):
    below = [("1440px, further down 1 of 1 (from 900px on a 3,000px page)", b"d")]
    seen = {}

    def _judge(shots, business_id="", standard=None, below=None):
        seen["shots"], seen["below"] = shots, below
        return json.dumps(_VERDICT)

    monkeypatch.setattr(vg, "_capture", lambda html, below=True: ([b"a", b"b", b"c"], below_views))
    below_views = below
    monkeypatch.setattr(vg, "_grade_anthropic", _judge)
    monkeypatch.setitem(__import__("sys").modules, "site_llm",
                        SimpleNamespace(judge_provider=lambda: "anthropic"))
    v = vg.grade("<html></html>", "biz-1")
    assert seen["shots"] == [b"a", b"b", b"c"] and seen["below"] == below
    assert v["rubric"] == "page-1" and v["passes_gate"] is True
    assert v["below_fold_note"]


def test_grade_is_none_when_the_browser_cannot_run(monkeypatch):
    monkeypatch.setattr(vg, "_capture", lambda html, below=True: None)
    assert vg.grade("<html></html>", "biz-1") is None


def test_the_first_screen_contract_canvas_reads_is_unchanged(monkeypatch):
    calls = []

    def _cap(html, below=True):
        calls.append(below)
        return [b"a", b"b", b"c"], []

    monkeypatch.setattr(vg, "_capture", _cap)
    assert vg._screenshot("<html></html>") == [b"a", b"b", b"c"]
    assert calls == [False]                      # no scrolling for the self-review


def test_the_anthropic_judge_sends_every_view(monkeypatch):
    sent = {}

    class _Msgs:
        def create(self, **kw):
            sent.update(kw)
            return SimpleNamespace(model="m", usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                                   content=[SimpleNamespace(type="text", text=json.dumps(_VERDICT))])

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(vg.llm_call, "sdk_client", lambda key=None: SimpleNamespace(messages=_Msgs()))
    with mock.patch.object(vg, "_meter"):
        raw = vg._grade_anthropic([b"a", b"b", b"c"], "biz-1", None,
                                  [("1440px, further down 1 of 1", b"d")])
    assert json.loads(raw)["balance"] == 9
    content = sent["messages"][0]["content"]
    assert sum(1 for c in content if c["type"] == "image") == 4
    assert any(c.get("text", "").startswith("FURTHER DOWN") for c in content)
