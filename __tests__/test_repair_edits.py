"""EDITS, NOT THE PAGE (2026-10-07, the build-cost plan, step 3).

Kevin: "maintain the quality with decreasing the cost". A whole-page
repair wrote the whole page back to fix one rule (18 to 28 thousand output
tokens, twice a build; output costs five times input). Pins: the repair
asks for search-and-replace edits; the server places each edit exactly
once (verbatim, or with whitespace allowed to differ) and refuses a
missing or ambiguous one; every other byte of the page is untouched; a
whole-page reply is still accepted; when an edit cannot be placed, ONE
whole-page pass runs as before; the repair prompt keeps the cached shared
parts of step 1.
"""
import builder_v2 as v2

DOC = ("<!DOCTYPE html><html><head><title>t</title><style>:root{--accent:#c0281e}</style></head><body>\n"
       "  <section id=\"top\">\n    <h1>Lead from where you are</h1>\n    <p>Coaching for 400 managers.</p>\n"
       "  </section>\n  <section id=\"prices\">\n    <h2>Ways in</h2>\n  </section>\n</body></html>")


def _edit(find, replace):
    return f"<<<<<<< SEARCH\n{find}\n=======\n{replace}\n>>>>>>> REPLACE"


# ─── placing edits ────────────────────────────────────────────────────

def test_an_edit_replaces_exactly_its_run_and_nothing_else():
    out, how = v2.apply_edits(DOC, _edit("<p>Coaching for 400 managers.</p>", "<p>Coaching for new managers.</p>"))
    assert how == "edits"
    assert out == DOC.replace("Coaching for 400 managers.", "Coaching for new managers.")


def test_a_reindented_search_still_finds_its_place():
    find = '<section id="top">\n<h1>Lead from where you are</h1>'
    out, how = v2.apply_edits(DOC, _edit(find, '<section id="top">\n<h1>Lead from here</h1>'))
    assert how == "edits" and "Lead from here" in out and 'id="prices"' in out


def test_a_missing_or_ambiguous_search_is_refused():
    assert v2.apply_edits(DOC, _edit("<p>Not on the page</p>", "x")) == (None, "edit 1 not found")
    # "</section>" occurs twice: placing it would be a guess
    assert v2.apply_edits(DOC, _edit("</section>", "</div>")) == (None, "edit 1 not found")


def test_several_edits_apply_top_to_bottom_and_an_empty_replace_deletes():
    raw = "\n".join([_edit("--accent:#c0281e", "--accent:#2e7dff"),
                     _edit("    <p>Coaching for 400 managers.</p>\n", "")])
    out, how = v2.apply_edits(DOC, raw)
    assert how == "edits" and "--accent:#2e7dff" in out and "400" not in out
    assert out.count("<section") == 2


def test_an_edit_that_breaks_the_page_is_refused():
    out, how = v2.apply_edits(DOC, _edit("</body></html>", "</body>"))
    assert out is None and how == "not a page"


def test_a_whole_page_reply_is_still_accepted():
    whole = DOC.replace("Ways in", "Three ways in")
    assert v2.apply_edits(DOC, whole) == (whole, "document")
    assert v2.apply_edits(DOC, "```html\n" + whole + "\n```")[1] == "document"
    assert v2.apply_edits(DOC, "I could not do that.") == (None, "no edits")


# ─── the prompt ───────────────────────────────────────────────────────

def test_the_repair_asks_for_edits_and_keeps_the_cached_parts():
    p = v2.build_user_prompt("SPEC", "BUSINESS: x", violations=["number '400' untraced"], prior_doc=DOC)
    blocks = v2._user_blocks(p)
    task = blocks[-1]["text"]
    assert v2.EDITS_PREAMBLE in task and "<<<<<<< SEARCH" in task and ">>>>>>> REPLACE" in task
    assert "Output the corrected complete HTML document only." not in p
    section = v2._user_blocks(v2.build_section_prompt("SPEC", "BUSINESS: x", DOC, "prices", ["x"]))
    assert blocks[0]["text"] == section[0]["text"] and blocks[1]["text"] == section[1]["text"]
    whole = v2.build_user_prompt("SPEC", "BUSINESS: x", violations=["x"], prior_doc=DOC, edits=False)
    assert "Output the corrected complete HTML document only." in whole and "<<<<<<< SEARCH" not in whole


# ─── a build repairs by edits, and falls back once ────────────────────

EP = "https://api.example/contact/biz-1"


def _page(extra=""):
    return ("<!DOCTYPE html><html><head><title>Studio</title>"
            '<meta name="description" content="A braiding studio by hand">'
            '<meta property="og:title" content="Studio">'
            '<meta property="og:description" content="A braiding studio">'
            '<meta property="og:image" content="https://x/a.jpg">'
            "<style>body{margin:0}</style></head><body>"
            '<nav><a href="#top">Top</a></nav><main id="top"><h1>Braids worn '
            "like their own kind of magnificent.</h1>" + extra + "</main>"
            f'<form method="POST" action="{EP}"><input name="name">'
            '<input name="email"><button>Send</button></form>'
            "<footer>Studio</footer></body></html>")


STANDIN = '<div class="slot-frame"><p class="slot-note">Braids from behind, clean parts.</p></div>'


def _shown_page(user):
    """The page as the repair prompt shows it (after the build's own
    armor and edit tags), which is what a model copies its SEARCH from."""
    return user.split(v2.page_part(""), 1)[1].split(v2.CACHE_BREAK, 1)[0]


def _drop_standin(user):
    import re
    run = re.search(r'<div class="slot-frame".*?</p></div>', _shown_page(user), re.DOTALL).group(0)
    return _edit(run, "")


def _wire(monkeypatch, replies):
    calls = []

    def _fake_call(system, user, business_id, spend=None):
        calls.append(user)
        reply = replies.pop(0)
        return reply(user) if callable(reply) else reply
    monkeypatch.setattr(v2, "_call", _fake_call)
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: x")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: EP)
    monkeypatch.setattr(v2, "eyes_enabled", lambda: False)
    return calls


def test_a_build_repairs_by_edits(monkeypatch):
    calls = _wire(monkeypatch, [_page(STANDIN), _drop_standin])
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert len(calls) == 2 and "<<<<<<< SEARCH" in calls[1]
    assert "slot-frame" not in out["html"] and "magnificent" in out["html"]
    assert out["report"]["repair_modes"] == [{"stage": "surgical", "how": "edits"}]
    assert out["report"]["stand_ins"] == []


def test_an_edit_that_misses_falls_back_to_one_whole_page_pass(monkeypatch):
    calls = _wire(monkeypatch, [_page(STANDIN), _edit("<div>not on the page</div>", ""), _page()])
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert len(calls) == 3, "the edit missed: one whole-page pass, no more"
    assert "Output the corrected complete HTML document only." in calls[2]
    assert out["report"]["repair_modes"] == [{"stage": "surgical", "how": "document after edit 1 not found"}]
    assert "slot-frame" not in out["html"]
