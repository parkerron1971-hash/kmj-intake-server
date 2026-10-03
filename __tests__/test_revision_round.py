"""
test_revision_round.py — the owner's revision round (2026-10-03, phase 4
of the hand-build plan).

By hand, a finished page goes in front of its owner, they point at what is
not right, and those parts get fixed together. Pins: the panel lists the
page's sections, a reaction or a note is what makes a fix (a bare mark is
dropped), the marked sections are fixed one after another on the page the
last fix left, the page is stored and served once, the build's included
fixes are spent first and only fixes that LANDED are counted, a fix that
could not land leaves its section as it was and costs nothing, and the
paid part of a round checks the credit gate before the job starts.
"""
import asyncio
from types import SimpleNamespace

import pytest

import builder_v2 as bv2
import chief_jobs
import pricing_config
import sb_clients
import site_composer as sc
import site_revisions as sr
import spec_author

DOC = ("<!DOCTYPE html><html lang=\"en\"><head><title>Coach</title></head><body>"
       "<section id=\"top\"><h1>Lead from where you are</h1></section>"
       "<section id=\"offers\"><h2>Ways to work together</h2><p>Coaching.</p></section>"
       "<section id=\"story\"><h2>Why I coach</h2><p>Six years.</p></section>"
       "</body></html>")

BUILT = "2026-10-03T18:00:00+00:00"


def _cfg(**extra):
    cfg = {"canvas": {"html": DOC, "generated_at": BUILT},
           "canvas_report": {"engine": "builder_v2"}, "html_source": "canvas"}
    cfg.update(extra)
    return cfg


@pytest.fixture
def wired(monkeypatch):
    box = {"row": {"id": "site-1", "slug": "coach", "site_config": _cfg()},
           "calls": [], "patches": [], "charges": [], "refreshed": 0,
           "replies": {}}

    def fake_refine(doc, spec, ctx, bid, section, instruction, units=None):
        box["calls"].append({"doc": doc, "section": section,
                             "instruction": instruction, "units": units})
        reply = box["replies"].get(section, "ok")
        if reply != "ok":
            return {"ok": False, "error": reply}
        return {"ok": True, "section": section,
                "html": doc.replace(f'id="{section}">', f'id="{section}" data-fixed="1">')}

    def fake_refresh(bid):
        box["refreshed"] += 1
        return True

    monkeypatch.setattr(sr, "_site_row", lambda bid: box["row"])
    monkeypatch.setattr(bv2, "refine_section_doc", fake_refine)
    monkeypatch.setattr(sc, "gather_context", lambda bid: {})
    monkeypatch.setattr(sc, "refresh_if_composed", fake_refresh)
    monkeypatch.setattr(spec_author, "approved_spec_text", lambda bid: "SPEC")
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body: box["patches"].append(body))
    monkeypatch.setattr(sr, "_charge", lambda bid, credits, n: box["charges"].append(credits))
    monkeypatch.setattr(pricing_config, "section_rewrite", lambda: 120)
    monkeypatch.delenv("REVISION_FREE_SECTIONS", raising=False)
    return box


# ─── what the panel shows ───────────────────────────────────────────

def test_the_panel_lists_the_sections_with_their_headings(wired):
    st = sr.state("biz-1")
    assert st["ready"] is True
    assert st["sections"] == [{"id": "top", "heading": "Lead from where you are"},
                              {"id": "offers", "heading": "Ways to work together"},
                              {"id": "story", "heading": "Why I coach"}]
    assert st["free_left"] == 4 and st["price_per_section"] == 120
    assert {r["key"] for r in st["reactions"]} == set(sr.REACTIONS)


def test_a_page_the_builder_did_not_write_has_no_round(wired):
    wired["row"]["site_config"] = {"html_source": "modules"}
    assert sr.state("biz-1")["ready"] is False
    out = sr.run_round("biz-1", [{"section": "top", "reaction": "plain"}])
    assert out["ok"] is False and "one section at a time" in out["error"]


# ─── what counts as a fix ───────────────────────────────────────────

def test_a_reaction_or_a_note_makes_a_fix_and_a_bare_mark_does_not():
    out = sr.clean_reactions([
        {"section": "top", "reaction": "plain"},
        {"section": "offers", "note": "  put the  prices first "},
        {"section": "story"},                                   # nothing said
        {"section": "story", "reaction": "keep"},               # not a fix
        {"section": "ghost", "reaction": "wordy"},              # not on the page
        "nonsense",
    ], ["top", "offers", "story"])
    assert out == [{"section": "top", "reaction": "plain", "note": ""},
                   {"section": "offers", "reaction": "", "note": "put the prices first"}]


def test_a_round_holds_at_most_six_and_a_section_once():
    raw = [{"section": f"s{i}", "reaction": "plain"} for i in range(9)]
    raw.append({"section": "s0", "reaction": "wordy"})
    out = sr.clean_reactions(raw)
    assert len(out) == sr.MAX_PER_ROUND
    assert out[0] == {"section": "s0", "reaction": "wordy", "note": ""}


def test_the_builder_hears_the_reaction_and_their_own_words():
    ask = sr.instruction_for("photo", "use the one of me at the desk")
    assert ask.startswith("The photo is wrong for it.")
    assert ask.endswith('In their words: "use the one of me at the desk"')
    assert sr.instruction_for("", "bigger") == 'In their words: "bigger"'


# ─── the round ──────────────────────────────────────────────────────

def test_the_marked_sections_are_fixed_in_turn_and_served_once(wired):
    out = sr.run_round("biz-1", [{"section": "top", "reaction": "plain"},
                                 {"section": "story", "note": "shorter"}])
    assert out["ok"] is True
    assert [f["section"] for f in out["fixed"]] == ["top", "story"]
    # the second fix works on the page the first one left
    assert 'id="top" data-fixed="1"' in wired["calls"][1]["doc"]
    # the model calls ride free; the round carries the price
    assert [c["units"] for c in wired["calls"]] == [0, 0]
    assert len(wired["patches"]) == 1 and wired["refreshed"] == 1
    stored = wired["patches"][0]["site_config"]
    assert 'id="story" data-fixed="1"' in stored["canvas"]["html"]
    assert stored["canvas"]["generated_at"] == BUILT


def test_the_builds_included_fixes_are_spent_first(wired):
    out = sr.run_round("biz-1", [{"section": "top", "reaction": "plain"},
                                 {"section": "offers", "reaction": "wordy"}])
    assert out["free_used"] == 2 and out["credits"] == 0 and out["free_left"] == 2
    assert wired["charges"] == [0]
    rev = wired["patches"][0]["site_config"]["revisions"]
    assert rev["build"] == BUILT and rev["free_used"] == 2


def test_fixes_past_the_included_ones_are_section_reworks(wired):
    wired["row"]["site_config"] = _cfg(revisions={"build": BUILT, "free_used": 3})
    out = sr.run_round("biz-1", [{"section": "top", "reaction": "plain"},
                                 {"section": "offers", "reaction": "wordy"}])
    assert out["free_used"] == 1 and out["credits"] == 120
    assert wired["charges"] == [120]


def test_a_new_build_brings_new_included_fixes(wired):
    wired["row"]["site_config"] = _cfg(revisions={"build": "an older build", "free_used": 4})
    assert sr.free_left(wired["row"]["site_config"]) == 4


def test_a_fix_that_could_not_land_costs_nothing_and_says_why(wired):
    wired["row"]["site_config"] = _cfg(revisions={"build": BUILT, "free_used": 4})
    wired["replies"]["offers"] = "the rework broke one of the page's rules, so nothing on the page changed"
    out = sr.run_round("biz-1", [{"section": "top", "reaction": "plain"},
                                 {"section": "offers", "reaction": "wordy"}])
    assert [f["section"] for f in out["fixed"]] == ["top"]
    assert out["unchanged"] == [{"section": "offers", "heading": "Ways to work together",
                                 "why": "the rework broke one of the page's rules"}]
    assert out["credits"] == 120 and wired["charges"] == [120]
    assert 'id="offers" data-fixed' not in wired["patches"][0]["site_config"]["canvas"]["html"]


def test_a_round_where_nothing_landed_changes_nothing(wired):
    wired["replies"]["top"] = "the rework didn't come back"
    out = sr.run_round("biz-1", [{"section": "top", "reaction": "plain"}])
    assert out["ok"] is False and out["credits"] == 0
    assert wired["patches"] == [] and wired["charges"] == [] and wired["refreshed"] == 0


# ─── the job and the endpoint ───────────────────────────────────────

def test_the_round_is_a_job_and_the_build_offers_it():
    assert chief_jobs.KIND_META["revise_sections"]["nav"] == "build:mysite"
    assert "mark" in chief_jobs.KIND_META["rebuild_site"]["done"]


def _start(monkeypatch, cfg, n):
    seen = {"gate": 0, "params": None}
    monkeypatch.setattr(sc, "_require_owner", lambda bid, uid: None)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{"site_config": cfg}])

    async def fake_enqueue(client, **kw):
        seen["params"] = kw["params"]
        return {"id": "job-1"}

    import billing_limits
    monkeypatch.setattr(chief_jobs, "enqueue", fake_enqueue)
    monkeypatch.setattr(billing_limits, "require_units",
                        lambda bid: seen.__setitem__("gate", seen["gate"] + 1))
    body = sc.ReviseSectionsBody(business_id="biz-1", reactions=[
        {"section": f"s{i}", "reaction": "plain"} for i in range(n)])
    out = asyncio.run(sc.start_revise_sections(body, SimpleNamespace(user=SimpleNamespace(id="u1"))))
    return out, seen


def test_an_included_round_starts_without_the_credit_gate(monkeypatch):
    monkeypatch.setattr(pricing_config, "section_rewrite", lambda: 120)
    out, seen = _start(monkeypatch, _cfg(), 3)
    assert out["job_id"] == "job-1" and seen["gate"] == 0
    assert out["quote"] == {"free": 3, "paid": 0, "credits": 0}
    assert len(seen["params"]["reactions"]) == 3


def test_a_paid_round_checks_the_credit_gate_first(monkeypatch):
    monkeypatch.setattr(pricing_config, "section_rewrite", lambda: 120)
    out, seen = _start(monkeypatch, _cfg(revisions={"build": BUILT, "free_used": 4}), 2)
    assert seen["gate"] == 1 and out["quote"]["credits"] == 240


def test_a_refusal_never_says_nothing_changed_when_the_round_changed_things():
    assert sr._why("the rework didn't come back. Nothing on the page changed; try again")         == "the rework didn't come back"
    assert sr._why(None).startswith("it couldn't be improved")


def test_a_section_without_a_heading_is_named_by_its_own_words():
    """The first live page (Vertical Test Coach) had two of nine sections
    with no heading; the panel would have said "Section 2" and "Section 5"."""
    doc = ("<html><body>"
           "<section id=\"band\"><p>More like a study than an office.</p><p>Two armchairs</p></section>"
           "<section id=\"story\"><span>4</span><blockquote>I came in thinking I needed a new job, "
           "and I left knowing what I wanted from this one, which was the point</blockquote></section>"
           "<section id=\"study\"><h2>I watched good people get <em>stuck</em>.</h2></section>"
           "</body></html>")
    assert sr.outline(doc) == [
        {"id": "band", "heading": "More like a study than an office."},
        {"id": "story", "heading": "I came in thinking I needed a new job, and I left knowing…"},
        {"id": "study", "heading": "I watched good people get stuck."},
    ]
