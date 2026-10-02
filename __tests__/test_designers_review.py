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

def _wire(monkeypatch, verdict, section_reply=NEW_PRICES):
    calls = []

    def _fake_call(system, user, business_id, spend=None):
        calls.append((system, user))
        if user.startswith("SECTION REPAIR"):
            return section_reply
        return _doc()

    monkeypatch.setattr(v2, "_call", _fake_call)
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: x")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: EP)
    monkeypatch.setattr(v2, "eyes_enabled", lambda: True)
    monkeypatch.setattr(v2, "inspect_with_eyes", lambda doc, spec, biz, why=None: verdict)
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
    assert out["report"]["vision"]["section_repairs"] == [{"section": "prices", "applied": True}]
    assert out["report"]["vision"]["repaired"] is True


def test_a_bad_section_reply_leaves_the_page_alone(monkeypatch):
    verdict = {"verdict": "repair", "violations": [
        {"where": "x", "section": "prices", "what": "flat", "fix": "sing"}], "weakest": None}
    _wire(monkeypatch, verdict, section_reply="<div>oops</div>")
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert "Old flat list." in out["html"]
    assert out["report"]["vision"]["section_repairs"] == [{"section": "prices", "applied": False}]


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
    assert "section_repairs" not in out["report"]["vision"]
