"""The blueprint is settled (2026-10-03, after the proof build).

The proof page matched 28 of its blueprint's 32 promises, and two misses
came from the builder's own review overriding decisions it could not see:
the eyes read the first 2,400 characters of a 19,000-character blueprint,
the section rebuilder the first 6,000, the whole-page repair none at all.
"No length or price shown: neither is on file" became "Fee on request",
and the struck "new job" saved for the story was copied into the hero.
Pins: every look and every repair carries the whole blueprint and the
settled rule; a doubted decision becomes a question for the owner, which
the walk-through shows, instead of a fix that undoes it.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import builder_v2 as v2  # noqa: E402
from test_builder_v2 import _law_passing_doc  # noqa: E402

EP = "https://api.example/contact/biz-1"
# a blueprint whose decision sits far past the old excerpts, as the real one did
BLUEPRINT = ("0. THE CONCEPT\nIDEA: a page from a used book.\n" + ("filler line. " * 900)
             + "\nDECIDED AND DECLINED\n1. First step named: the discovery call. "
               "No length or price shown: neither is on file.\n")
DOC = _law_passing_doc(EP, '<section id="begin"><h2>Three ways in</h2><p>Discovery call, start here.</p></section>')


def test_the_decision_far_down_the_blueprint_reaches_every_look_and_repair():
    assert BLUEPRINT.index("No length or price shown") > 10000
    assert "No length or price shown" in v2.eyes_blueprint_block(BLUEPRINT)
    section = v2.build_section_prompt(BLUEPRINT, "BUSINESS: x", DOC, "begin", ["make it sing"])
    assert "No length or price shown" in section and v2.BLUEPRINT_SETTLED in section
    page = v2.build_user_prompt(BLUEPRINT, "BUSINESS: x", violations=["palette drifts"], prior_doc=DOC)
    assert "No length or price shown" in page and v2.BLUEPRINT_SETTLED in page


def test_the_eyes_are_told_the_blueprint_is_settled_and_to_ask_instead():
    assert "THE BLUEPRINT IS SETTLED" in v2._INSPECTOR
    assert "Never propose a fix that undoes one of its decisions" in v2._INSPECTOR
    assert '"ask_owner"' in v2._INSPECTOR
    out = v2._parse_inspector('{"verdict":"ship","violations":[],"ask_owner":"Is the discovery call free?"}')
    assert out["ask_owner"] == "Is the discovery call free?"
    assert v2._parse_inspector('{"verdict":"ship","violations":[],"ask_owner":"null"}')["ask_owner"] is None


def test_the_eyes_questions_reach_the_report_once(monkeypatch):
    looks = [{"verdict": "repair", "weakest": None, "visitor": None, "biggest": None,
              "ask_owner": "Is the discovery call free?",
              "violations": [{"where": "x", "section": "begin", "what": "flat", "fix": "sing"}]},
             {"verdict": "ship", "violations": [], "ask_owner": "Is the discovery call free?"}]
    seen = {"n": 0}

    def _inspect(doc, spec, biz, why=None):
        seen["n"] += 1
        return looks[min(seen["n"], len(looks)) - 1]

    def _fake_call(system, user, business_id, spend=None):
        if user.startswith("SECTION REPAIR"):
            return '<section id="begin"><h2>Three ways in</h2><p>Rebuilt.</p></section>'
        return DOC

    monkeypatch.setenv("LOOK_FIX_ROUNDS", "3")
    monkeypatch.setattr(v2, "_call", _fake_call)
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: x")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: EP)
    monkeypatch.setattr(v2, "eyes_enabled", lambda: True)
    monkeypatch.setattr(v2, "inspect_with_eyes", _inspect)
    out = v2.run_builder_v2(BLUEPRINT, {}, "biz-1")
    assert out["report"]["vision"]["questions"] == ["Is the discovery call free?"]


def test_the_walk_through_shows_the_builders_questions(monkeypatch):
    import site_revisions as sr
    cfg = {"canvas": {"html": DOC, "generated_at": "t"}, "html_source": "canvas",
           "canvas_report": {"engine": "builder_v2",
                             "vision": {"questions": ["Is the discovery call free?"]}}}
    monkeypatch.setattr(sr, "_site_row", lambda bid: {"id": "s", "slug": "x", "site_config": cfg})
    assert sr.state("biz-1")["questions"] == ["Is the discovery call free?"]


def test_the_eyes_send_the_whole_blueprint_to_the_model(monkeypatch):
    sent = {}

    class _Msg:
        content = [type("B", (), {"type": "text", "text": '{"verdict":"ship","violations":[]}'})()]
        usage = None
        stop_reason = "end_turn"

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                sent.update(kw)
                return _Msg()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(v2, "_screenshot_walk", lambda html: [("1440px top", b"jpeg")])
    monkeypatch.setattr(v2.llm_call, "sdk_client", lambda **kw: _Client())
    out = v2.inspect_with_eyes(DOC, BLUEPRINT, "biz-1")
    assert out and out["verdict"] == "ship"
    first = sent["messages"][0]["content"][0]["text"]
    assert "No length or price shown" in first and first.startswith("THE APPROVED BLUEPRINT")
