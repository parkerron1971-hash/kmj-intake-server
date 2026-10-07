"""Every section is written (2026-10-03, the second live test).

The Director's blueprint for Vertical Test Coach carried a line from the
older canvas pipeline's section plan, "Position the immutable token
exactly here: <!--SX_BLOCK:process-->". That pipeline splices a pre-built
block into the token; builder_v2 splices nothing, so it copied the token
and "How it works" shipped as blank paper, with the nav link and the
hero's "Read how it works" landing on it. Pins: the builder's copy of the
blueprint has no tokens and says it writes every section, an empty
section is found (a token, or no words and no picture), it earns the soft
tier, and the look-and-fix loop always rebuilds it."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import builder_v2 as v2  # noqa: E402
from test_builder_v2 import _law_passing_doc  # noqa: E402

EP = "https://api.example/contact/biz-1"

SPEC = """5. HOW IT WORKS (light paper ground, id="process")
Position the immutable token exactly here: <!--SX_BLOCK:process-->
6. THE CLOSING INVITATION (cta)
- No rewriting, wrapping or restating of the process and contact blocks.
- Hover and focus: nav links draw a 1px underline."""

EMPTY = ('<section id="about"><h2>I left that world on purpose.</h2><p>Fifteen years in HR.</p></section>'
         '<section id="process"><div class="col"><!--SX_BLOCK:process--></div></section>')
FILLED = ('<section id="process"><h2>How it works</h2>'
          '<p>A discovery call, then six weekly sessions in the study.</p></section>')


# ─── the builder's copy of the blueprint ────────────────────────────

def test_the_builder_reads_the_blueprint_without_block_tokens():
    out = v2.spec_for_builder(SPEC)
    assert "SX_BLOCK" not in out
    assert "Write this section yourself, complete, from THE REAL DATA." in out
    assert "No rewriting, wrapping or restating" not in out
    assert out.endswith(v2.WRITES_EVERY_SECTION)
    assert "nav links draw a 1px underline" in out          # the rest stays
    plain = "1. THE HERO\n2. THE STORY"
    assert v2.spec_for_builder(plain) == plain             # no tokens, untouched


# ─── finding an empty section ───────────────────────────────────────

def test_an_empty_section_is_found_and_a_written_one_is_not():
    doc = ('<section id="a"><div><!--SX_BLOCK:process--></div></section>'
           '<section id="b"><div class="seam"></div></section>'
           '<section id="c"><svg viewBox="0 0 10 10"><path d="M0 0"/></svg></section>'
           '<section id="d"><h2>Three ways in</h2><p>Most people start with a call.</p></section>'
           '<section id="e"><form><input name="n"></form></section>')
    assert v2.empty_sections(doc) == ["a", "b"]
    assert v2.check_unfilled(doc)[0].startswith("section #a is empty")


def test_an_empty_section_earns_the_repair_round(monkeypatch):
    calls = []

    def _fake_call(system, user, business_id, spend=None):
        calls.append(user)
        return _law_passing_doc(EP, EMPTY)

    monkeypatch.setattr(v2, "_call", _fake_call)
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: x")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: EP)
    monkeypatch.setattr(v2, "eyes_enabled", lambda: False)
    out = v2.run_builder_v2(SPEC, {}, "biz-1")
    assert len(calls) == 2, "the author, then the repair round the soft tier earned"
    assert "section #process is empty" in calls[1]
    assert "SX_BLOCK" not in calls[0], "the builder never saw the token"
    assert out["report"]["block_tokens_rewritten"] is True


def test_the_loop_rebuilds_an_empty_section_even_when_the_eyes_pass_it(monkeypatch):
    calls = []

    def _fake_call(system, user, business_id, spend=None):
        calls.append(user)
        if "SECTION REPAIR:" in user:
            return FILLED
        return _law_passing_doc(EP, EMPTY)

    monkeypatch.setenv("LOOK_FIX_ROUNDS", "2")
    monkeypatch.setattr(v2, "_call", _fake_call)
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: x")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: EP)
    monkeypatch.setattr(v2, "eyes_enabled", lambda: True)
    monkeypatch.setattr(v2, "inspect_with_eyes",
                        lambda doc, spec, biz, why=None: {"verdict": "ship", "violations": [],
                                                          "weakest": None})
    out = v2.run_builder_v2(SPEC, {}, "biz-1")
    repairs = [c for c in calls if "SECTION REPAIR:" in c]
    assert repairs and 'the <section id="process">' in repairs[0]
    assert "THIS SECTION IS EMPTY" in repairs[0]
    assert "Most people start" not in out["html"] and "six weekly sessions in the study" in out["html"]
    assert v2.empty_sections(out["html"]) == []
