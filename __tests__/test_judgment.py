"""The judgment plan (2026-10-03, after the second live test).

The builder had the hand-build process and not yet the judgment: its eyes
passed an empty "How it works" three times (the menu link and the hero's
"Read how it works" landed on blank paper), the loop rebuilt the hero
twice the same way, and five small notes were weighed alike. Pins:

J1 THE VISITOR WALK — the click-through finds links that land on nothing
   (in a real browser), and the inspector reads the page as its visitor.
J2 BIGGEST PROBLEM FIRST — it leads every round and is never the one cut.
J3 CHANGE THE APPROACH — a second rebuild of a section is told to rethink
   it; a third flag stops the spending and leaves it for the owner.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import builder_v2 as v2  # noqa: E402
from test_builder_v2 import _law_passing_doc  # noqa: E402

EP = "https://api.example/contact/biz-1"
SECTIONS = ('<section id="top"><h1>Not a new job.</h1><p>Small study, Main Street.</p>'
            '<a href="#process">Read how it works</a></section>'
            '<section id="prices"><h2>Three ways in</h2><p>Old flat list.</p></section>'
            '<section id="story"><h2>Why I coach</h2><p>Fifteen years in HR.</p></section>')


def _doc():
    return _law_passing_doc(EP, SECTIONS)


def _new(sid, words):
    return f'<section id="{sid}"><h2>{sid}</h2><p>{words}</p></section>'


# ─── J1: the click-through, in a real browser ───────────────────────

def test_the_click_through_finds_links_that_land_on_nothing():
    pw = pytest.importorskip("playwright.sync_api")
    html = ('<html><body><nav><a href="#how">How it works</a><a href="#gone">Pricing</a>'
            '<a href="#">Book</a><a href="https://example.com">Elsewhere</a></nav>'
            '<section id="top"><h1>Not a new job</h1><a href="#how">Read how it works</a>'
            '<a href="#story">Our story</a></section>'
            '<section id="how"><div class="col"><!--SX_BLOCK:process--></div></section>'
            '<section id="story"><h2>Why I coach</h2><p>Fifteen years in corporate HR.</p></section>'
            '<section id="contact"><form><input name="n"></form></section>'
            '</body></html>')
    try:
        with pw.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_content(html)
            got = page.evaluate(v2.VISITOR_JS)
            browser.close()
    except Exception as e:                       # no browser binary on this machine
        pytest.skip(f"chromium unavailable: {e}")
    found = {(w["label"], w["problem"]) for w in got["visitor_walk"]}
    assert ("How it works", "blank") in found
    assert ("Read how it works", "blank") in found
    assert ("Pricing", "missing") in found
    assert ("Book", "nowhere") in found
    assert ("a form", "unsendable") in found
    assert not any(w["label"] in ("Our story", "Elsewhere") for w in got["visitor_walk"])
    items = v2.visitor_walk_findings({"1440": got})
    blank = [i for i in items if i["section"] == "how"]
    assert blank and "lands on #how, which is blank" in blank[0]["what"]
    assert any(i["section"] == "nav" and "Pricing" in i["what"] for i in items)


# ─── J1 + J2: the inspector's questions and answers ─────────────────

def test_the_inspector_walks_as_the_visitor_and_names_the_biggest():
    assert "FIRST, WALK IT AS THE VISITOR" in v2._INSPECTOR
    assert "THEN NAME THE BIGGEST PROBLEM" in v2._INSPECTOR
    assert '"visitor":{"who"' in v2._INSPECTOR and '"biggest":{"section"' in v2._INSPECTOR


def test_the_parser_keeps_the_visitor_and_the_biggest():
    raw = ('{"verdict":"repair","visitor":{"who":"a manager who outgrew the job",'
           '"came_for":"how this works","got_it":"no, the section is blank","next":"book a call",'
           '"stuck":"#process"},"biggest":{"section":"#top","what":"a small headline in a big empty hero",'
           '"why":"nothing tells them in five seconds","fix":"scale the headline"},'
           '"violations":[{"where":"1440","section":"top","what":"small","fix":"bigger"}],"weakest":null}')
    out = v2._parse_inspector(raw)
    assert out["visitor"]["stuck"] == "process" and out["visitor"]["who"].startswith("a manager")
    assert out["biggest"]["section"] == "top" and "small headline" in out["biggest"]["what"]
    calm = v2._parse_inspector('{"verdict":"ship","violations":[],"visitor":{"stuck":"null"},'
                               '"biggest":{"section":"top","what":"nothing much"}}')
    assert calm["biggest"] is None and calm["visitor"]["stuck"] is None


def test_the_plan_orders_biggest_then_blockers_then_the_rest():
    verdict = {"verdict": "repair",
               "violations": [{"where": "x", "section": "story", "what": "wall of text", "fix": "cards"},
                              {"where": "x", "section": "top", "what": "small", "fix": "bigger"}],
               "biggest": {"section": "top", "what": "a small headline", "why": "no idea in 5s",
                           "fix": "scale it"},
               "visitor": {"who": "a manager", "came_for": "prices", "got_it": "no",
                           "next": "book", "stuck": "prices"},
               "weakest": None}
    walk = [{"section": "story", "what": '"Our story" lands on nothing', "fix": "write it"}]
    page, by = v2.plan_vision_repair(verdict, _doc(), [], walk=walk)
    assert list(by) == ["top", "prices", "story"]
    assert by["top"][0].startswith("THE BIGGEST PROBLEM ON THE PAGE")
    assert by["prices"][0].startswith("THE VISITOR GETS STUCK HERE")
    assert by["story"][0].startswith("THE VISITOR WALK")
    # a page-wide biggest leads the whole-page pass
    wide = dict(verdict, biggest={"section": "page", "what": "palette drifts", "why": "x", "fix": "y"})
    page, _by = v2.plan_vision_repair(wide, _doc(), ["MEASURED IN THE RENDER: z"])
    assert page[0].startswith("THE BIGGEST PROBLEM ON THE PAGE")


def _wire(monkeypatch, looks, rounds=3, per_round=3):
    calls = []
    seen = {"n": 0}

    def _inspect(doc, spec, biz, why=None):
        seen["n"] += 1
        return looks[min(seen["n"], len(looks)) - 1]

    def _fake_call(system, user, business_id, spend=None):
        calls.append(user)
        if user.startswith("SECTION REPAIR"):
            sid = user.split('<section id="', 1)[1].split('"', 1)[0]
            return _new(sid, f"rebuilt {sid} {len(calls)}")
        return _doc()

    monkeypatch.setenv("LOOK_FIX_ROUNDS", str(rounds))
    monkeypatch.setenv("LOOK_FIX_SECTIONS", str(per_round))
    monkeypatch.setattr(v2, "_call", _fake_call)
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: x")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: EP)
    monkeypatch.setattr(v2, "eyes_enabled", lambda: True)
    monkeypatch.setattr(v2, "inspect_with_eyes", _inspect)
    return calls


def _flag(*sids, biggest=None):
    return {"verdict": "repair", "weakest": None, "visitor": None,
            "violations": [{"where": "x", "section": s, "what": f"{s} is weak", "fix": "fix"}
                           for s in sids],
            "biggest": ({"section": biggest, "what": f"{biggest} hurts most", "why": "w", "fix": "f"}
                        if biggest else None)}


def test_a_round_that_can_afford_one_section_takes_the_biggest(monkeypatch):
    calls = _wire(monkeypatch, [_flag("story", "top", biggest="top"),
                                {"verdict": "ship", "violations": []}], per_round=1)
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    repairs = [c for c in calls if c.startswith("SECTION REPAIR")]
    assert len(repairs) == 1 and '<section id="top">' in repairs[0]
    assert "THE BIGGEST PROBLEM ON THE PAGE" in repairs[0]
    assert out["report"]["vision"]["rounds"][0]["biggest"]["section"] == "top"


# ─── J3: change the approach on a second try ────────────────────────

def test_a_section_flagged_again_is_rethought_and_a_third_flag_goes_to_the_owner(monkeypatch):
    calls = _wire(monkeypatch, [_flag("top", biggest="top")])
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    repairs = [c for c in calls if c.startswith("SECTION REPAIR")]
    assert len(repairs) == 2, "rebuilt, rethought, then no third paid rebuild"
    assert "SECOND TRY" not in repairs[0]
    assert "SECOND TRY: this section was already rebuilt once, for: THE BIGGEST PROBLEM" in repairs[1]
    assert "Rethink it" in repairs[1]
    assert out["report"]["vision"]["for_the_owner"] == [
        {"section": "top", "what": out["report"]["vision"]["for_the_owner"][0]["what"]}]
    assert out["report"]["vision"]["rounds"][1]["sections"][0]["second_try"] is True


def test_different_sections_each_round_still_run_to_the_round_cap(monkeypatch):
    calls = _wire(monkeypatch, [_flag("top"), _flag("story"), _flag("top")])
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert out["report"]["vision"]["looks"] == 3
    assert [r["round"] for r in out["report"]["vision"]["section_repairs"]] == [1, 2, 3]
    repairs = [c for c in calls if c.startswith("SECTION REPAIR")]
    assert "SECOND TRY" in repairs[2], "top's second rebuild is a rethink"
    assert out["report"]["vision"]["for_the_owner"] == []
