"""The first screen is a poster on Signature and World pages, and stays calm on
Plain ones.

Measured 2026-11-08, biggest words on the first screen on a computer: 201px and
196px on the two hand-built pages, 72px and 95px on the two builder pages. The
type floor only set minimums for reading, so nothing asked for a bold opening.
"""
import builder_v2 as v2
import craft_laws as cl


def _m(computer, phone):
    return {"1440": {"opening_px": computer, "opening": 'h1 "Not a new job."'},
            "390": {"opening_px": phone, "opening": 'h1 "Not a new job."'}}


def test_it_is_off_until_switched_on(monkeypatch):
    monkeypatch.delenv("SITE_BOLD_OPENING", raising=False)
    assert cl.opening_block("signature") == ""
    assert cl.opening_findings(_m(40, 20), "signature") == []


def test_the_bar_sits_between_the_builder_pages_and_the_hand_built_ones(monkeypatch):
    monkeypatch.setenv("SITE_BOLD_OPENING", "on")
    assert cl.opening_findings(_m(201, 52), "signature") == []      # Love City
    assert cl.opening_findings(_m(196, 64), "world") == []          # KMJ
    coach = cl.opening_findings(_m(72, 44), "signature")
    assert len(coach) == 2 and "at 390px" in coach[0] and "at 1440px" in coach[1]
    macnificent = cl.opening_findings(_m(95, 48), "signature")
    assert len(macnificent) == 1 and "at 1440px" in macnificent[0]


def test_plain_pages_stay_calm(monkeypatch):
    monkeypatch.setenv("SITE_BOLD_OPENING", "on")
    assert cl.opening_block("plain") == "" and cl.opening_block("") == ""
    assert cl.opening_findings(_m(40, 20), "plain") == []
    assert cl.opening_findings(_m(40, 20), "") == []


def test_a_finding_keeps_the_words_and_names_the_size(monkeypatch):
    monkeypatch.setenv("SITE_BOLD_OPENING", "on")
    found = cl.opening_findings(_m(72, 60), "signature")[0]
    assert "72px" in found and "115px" in found and "keeping its words" in found


def test_a_width_with_no_bar_or_no_reading_is_skipped(monkeypatch):
    monkeypatch.setenv("SITE_BOLD_OPENING", "on")
    assert cl.opening_findings({"768": {"opening_px": 40}, "1440": {}, "390": "x"}, "world") == []


def test_the_builder_is_told_only_on_a_page_held_to_it(monkeypatch):
    monkeypatch.setenv("SITE_BOLD_OPENING", "on")
    signature = v2.build_user_prompt("0. THE CONCEPT\nINTENSITY: Signature\nIDEA: x\n", "BUSINESS: Studio")
    plain = v2.build_user_prompt("0. THE CONCEPT\nINTENSITY: Plain\n", "BUSINESS: Studio")
    assert "THE OPENING (measured" in signature
    assert "THE OPENING (measured" not in plain
    monkeypatch.delenv("SITE_BOLD_OPENING")
    assert "THE OPENING (measured" not in v2.build_user_prompt(
        "0. THE CONCEPT\nINTENSITY: Signature\nIDEA: x\n", "BUSINESS: Studio")


def test_the_measure_ignores_ghost_words_and_counts_library_names():
    js = cl.RENDER_JS
    assert "opening_px" in js
    assert """el.closest('[aria-hidden="true"]') && !el.closest('[data-sx-object]')""" in js
    # measured against the page, so a walk that scrolled still reads the first screen
    assert "box.top + window.scrollY" in js


def test_an_opening_scene_answers_for_itself(monkeypatch):
    """scene-lines fits its type to the screen, so a repair could not move it."""
    monkeypatch.setenv("SITE_BOLD_OPENING", "on")
    m = {"390": {"opening_px": 38, "opening_scene": True}, "1440": {"opening_px": 146, "opening_scene": True}}
    assert cl.opening_findings(m, "signature") == []


def test_only_the_home_page_is_told_since_only_it_is_measured(monkeypatch):
    monkeypatch.setenv("SITE_BOLD_OPENING", "on")
    spec = "0. THE CONCEPT\nINTENSITY: World\nIDEA: x\n"
    assert "THE OPENING (measured" in v2.build_user_prompt(spec, "BUSINESS: Studio")
    assert "THE OPENING (measured" not in v2.build_user_prompt(spec, "BUSINESS: Studio", page_brief="THE OFFER PAGE")
