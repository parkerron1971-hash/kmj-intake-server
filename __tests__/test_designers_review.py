"""The designer's review (2026-10-01, the concept-layer plan, step 7).

The eyes grade the judged half of the craft canon, name each defect's
section and the weakest section; when every defect lives in named
sections only those sections are rebuilt, and the rest of the page stays
byte for byte. A page-wide defect still gets one whole-page pass."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import builder_v2 as v2  # noqa: E402
from test_builder_v2 import _law_passing_doc  # noqa: E402

EP = "https://api.example/contact/biz-1"
SECTIONS = ('<section id="prices"><h2>The Board</h2><p>Old flat list.</p></section>'
            '<section id="story"><h2>Two Chairs</h2><p>Opened in the spring.</p></section>')
NEW_PRICES = ('<section id="prices"><h2>The Board</h2><p>Rebuilt as a letterboard.</p>'
              '</section>')


def _doc():
    return _law_passing_doc(EP, SECTIONS)


# ─── the tools ───────────────────────────────────────────────────────

def test_the_outline_names_sections_by_id_and_heading():
    out = v2.section_outline(_doc())
    assert "- prices: The Board" in out and "- story: Two Chairs" in out


def test_a_section_reply_is_spliced_only_when_it_is_the_same_section():
    doc = _doc()
    spliced = v2.splice_section(doc, "prices", "```html\n" + NEW_PRICES + "\n```")
    assert spliced and "Rebuilt as a letterboard." in spliced
    assert "Old flat list." not in spliced and "Opened in the spring." in spliced
    assert spliced.replace(NEW_PRICES, "") == doc.replace(SECTIONS.split("</section>")[0] + "</section>", "")
    assert v2.splice_section(doc, "prices", NEW_PRICES.replace('id="prices"', 'id="other"')) is None
    assert v2.splice_section(doc, "prices", NEW_PRICES + NEW_PRICES) is None
    assert v2.splice_section(doc, "prices", "<div>not a section</div>") is None
    assert v2.splice_section(doc, "missing", NEW_PRICES) is None


def test_the_plan_splits_page_wide_from_section_defects():
    verdict = {"verdict": "repair", "violations": [
        {"where": "1440 middle", "section": "prices", "what": "flat list", "fix": "make it sing"},
        {"where": "all", "section": "page", "what": "palette drifts", "fix": "use the tokens"},
        {"where": "390", "section": "nowhere", "what": "x", "fix": "y"}],
        "weakest": {"section": "story", "score": 5, "why": "a wall of text", "fix": "a chair card each"}}
    page, by_section = v2.plan_vision_repair(verdict, _doc(), ["MEASURED IN THE RENDER: sideways"])
    assert len(page) == 3, "measured + 'page' + an unknown section are page-wide"
    assert set(by_section) == {"prices", "story"}
    assert "WEAKEST SECTION (scored 5/10)" in by_section["story"][0]
    calm = {"verdict": "ship", "violations": [], "weakest": {"section": "story", "score": 8}}
    assert v2.plan_vision_repair(calm, _doc(), []) == ([], {})


def test_the_inspector_keeps_the_weakest_section():
    out = v2._parse_inspector('{"verdict":"ship","violations":[],"weakest":'
                              '{"section":"#story","score":"6","why":"flat","fix":"cards"}}')
    assert out["weakest"] == {"section": "story", "score": 6, "why": "flat", "fix": "cards"}
    assert v2._parse_inspector('{"verdict":"ship","violations":[]}')["weakest"] is None


def test_the_inspector_grades_the_judged_canon():
    for must in ("THE IDEA", "ONE SIGNATURE MOMENT", "RHYTHM", "PHONE COMPOSITION",
                 "CONCEPT CLARITY", '"weakest"', '"section"'):
        assert must in v2._INSPECTOR, must
    assert "unique, meaningful id" in v2._SYSTEM


# ─── the run ─────────────────────────────────────────────────────────

def _wire(monkeypatch, verdict, section_reply=NEW_PRICES, rounds=1):
    """verdict: one dict for every look, or a list (one per look; the last
    repeats). rounds pins LOOK_FIX_ROUNDS: 1 is the single look these
    older tests were written for."""
    calls = []
    monkeypatch.setenv("LOOK_FIX_ROUNDS", str(rounds))
    looks = list(verdict) if isinstance(verdict, list) else [verdict]
    seen = {"n": 0}

    def _inspect(doc, spec, biz, why=None):
        seen["n"] += 1
        return looks[min(seen["n"], len(looks)) - 1]

    def _fake_call(system, user, business_id, spend=None):
        calls.append((system, user))
        if user.startswith("SECTION REPAIR"):
            return section_reply
        return _doc()

    monkeypatch.setattr(v2, "_call", _fake_call)
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: x")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: EP)
    monkeypatch.setattr(v2, "eyes_enabled", lambda: True)
    monkeypatch.setattr(v2, "inspect_with_eyes", _inspect)
    return calls


def test_section_defects_rebuild_only_those_sections(monkeypatch):
    verdict = {"verdict": "repair", "violations": [
        {"where": "1440 middle", "section": "prices", "what": "a flat list", "fix": "a letterboard"}],
        "weakest": None}
    calls = _wire(monkeypatch, verdict)
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert len(calls) == 2, "the author, then one section call; no whole-page pass"
    system, user = calls[1]
    assert system.startswith("THIS CALL REPAIRS ONE SECTION")
    assert 'the <section id="prices">' in user and "a flat list" in user
    assert "Rebuilt as a letterboard." in out["html"]
    assert "Opened in the spring." in out["html"]
    assert out["report"]["vision"]["section_repairs"] == [{"section": "prices", "applied": True, "round": 1}]
    assert out["report"]["vision"]["repaired"] is True


def test_a_bad_section_reply_leaves_the_page_alone(monkeypatch):
    verdict = {"verdict": "repair", "violations": [
        {"where": "x", "section": "prices", "what": "flat", "fix": "sing"}], "weakest": None}
    _wire(monkeypatch, verdict, section_reply="<div>oops</div>")
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert "Old flat list." in out["html"]
    assert out["report"]["vision"]["section_repairs"] == [{"section": "prices", "applied": False, "round": 1}]


def test_a_low_scoring_weakest_section_is_rebuilt_even_on_ship(monkeypatch):
    verdict = {"verdict": "ship", "violations": [],
               "weakest": {"section": "prices", "score": 4, "why": "flat", "fix": "a board"}}
    calls = _wire(monkeypatch, verdict)
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert len(calls) == 2 and "WEAKEST SECTION (scored 4/10)" in calls[1][1]
    assert "Rebuilt as a letterboard." in out["html"]


def test_a_page_wide_defect_takes_one_whole_page_pass(monkeypatch):
    verdict = {"verdict": "repair", "violations": [
        {"where": "all", "section": "page", "what": "palette drifts", "fix": "tokens"},
        {"where": "x", "section": "prices", "what": "flat", "fix": "sing"}], "weakest": None}
    calls = _wire(monkeypatch, verdict)
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert len(calls) == 2
    assert not calls[1][1].startswith("SECTION REPAIR")
    assert "palette drifts" in calls[1][1] and "flat" in calls[1][1]
    assert out["report"]["vision"]["section_repairs"] == []


# ─── THE LOOK-AND-FIX LOOP (2026-10-03, phase 3 of the hand-build plan) ─
# Look, fix the weakest sections, look again, until it is right, a round
# changes nothing, the round cap, or the spending cap.

_PRICES_FLAT = {"verdict": "repair", "violations": [
    {"where": "1440 middle", "section": "prices", "what": "a flat list", "fix": "a letterboard"}],
    "weakest": None}
_CLEAN = {"verdict": "ship", "violations": [], "weakest": None}


def test_the_second_look_finds_it_right_and_the_loop_ends(monkeypatch):
    calls = _wire(monkeypatch, [_PRICES_FLAT, _CLEAN], rounds=3)
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert len(calls) == 2                       # the author, one section rebuild
    assert out["report"]["vision"]["looks"] == 2
    assert out["report"]["vision"]["rounds"][1]["verdict"] == "ship"


def test_the_same_section_flagged_every_look_is_rethought_then_left_for_the_owner(monkeypatch):
    """(J3, the judgment plan, 2026-10-03) it used to be rebuilt three times
    the same way; now: rebuilt, rethought, then handed to the owner."""
    calls = _wire(monkeypatch, _PRICES_FLAT, rounds=3)
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert out["report"]["vision"]["looks"] == 3
    repairs = [c[1] for c in calls if c[1].startswith("SECTION REPAIR")]
    assert len(repairs) == 2
    assert "SECOND TRY" not in repairs[0] and "SECOND TRY" in repairs[1]
    assert [r["round"] for r in out["report"]["vision"]["section_repairs"]] == [1, 2]
    assert out["report"]["vision"]["for_the_owner"][0]["section"] == "prices"


def test_a_round_that_changes_nothing_ends_the_loop(monkeypatch):
    calls = _wire(monkeypatch, _PRICES_FLAT, section_reply="<div>oops</div>", rounds=3)
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert out["report"]["vision"]["looks"] == 1 and len(calls) == 2


def test_the_whole_page_pass_runs_once(monkeypatch):
    wide = {"verdict": "repair", "violations": [
        {"where": "all", "section": "page", "what": "palette drifts", "fix": "tokens"}], "weakest": None}
    calls = _wire(monkeypatch, wide, rounds=3)
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert len(calls) == 2                       # the author, one whole-page pass
    assert [r["page_repair"] for r in out["report"]["vision"]["rounds"]] == [True, False]


def test_the_spending_cap_stops_the_later_looks(monkeypatch):
    calls = _wire(monkeypatch, _PRICES_FLAT, rounds=3)
    monkeypatch.setattr(v2, "look_fix_max_cents", lambda: 0)
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert out["report"]["vision"]["looks"] == 1 and len(calls) == 2
    assert any(sk.startswith("look-fix:round-2:cap") for sk in out["report"]["spend"]["skipped"])


def test_the_loop_dials_read_the_environment_within_bounds(monkeypatch):
    monkeypatch.setenv("LOOK_FIX_ROUNDS", "99")
    monkeypatch.setenv("LOOK_FIX_SECTIONS", "0")
    monkeypatch.setenv("LOOK_FIX_MAX_CENTS", "abc")
    assert v2.look_fix_rounds() == 6 and v2.look_fix_sections() == 1
    assert v2.look_fix_max_cents() == 150


def test_the_inspector_judges_the_layout():
    assert "THE LAYOUT: when THE LAYOUT is given" in v2._INSPECTOR
