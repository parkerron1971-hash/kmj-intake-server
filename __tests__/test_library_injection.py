"""THE SERVER WEARS THE LIBRARY (2026-10-07, the build-cost plan, step 2).

The builder used to retype every named object's CSS and script into the
page on every whole-page write. Now it writes only their structure, and
every pass that finishes a page adds the exact styles and script of the
objects actually on it. Pins: only the objects on the page; the library
style sits after the head's meta tags and before the page's own styles
(so the page's rules win and the charset stays first); the script sits
before </body>; idempotent; a page whose objects are gone loses the stale
block; a built page, a reworked section and a draft the builder renders
all wear it; the repair prompts never carry it.
"""
import builder_loop
import builder_v2 as v2
import site_objects as so

EP = "https://api.example/contact/biz-1"
TICKET = ('<div class="sxo-ticket-row"><article class="sxo sxo-ticket sxo-paper" data-sx-object="ticket">'
          '<div class="sxo-ticket-main"><h3 class="sxo-ticket-title">Wheel class</h3></div></article></div>')
PANELS = ('<div class="sxo sxo-panels" data-sx-object="panels"><article class="sxo-panel is-open">'
          '<h3>One</h3></article></div>')


def _page(extra="", head_style="body{margin:0}"):
    return ("<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>Studio</title>"
            '<meta name="description" content="A braiding studio by hand">'
            '<meta property="og:title" content="Studio">'
            '<meta property="og:description" content="A braiding studio">'
            '<meta property="og:image" content="https://x/a.jpg">'
            f"<style>{head_style}</style></head><body>"
            '<nav><a href="#top">Top</a></nav><main id="top"><h1>Braids worn '
            "like their own kind of magnificent.</h1>" + extra + "</main>"
            f'<form method="POST" action="{EP}"><input name="name">'
            '<input name="email"><button>Send</button></form>'
            "<footer>Studio</footer></body></html>")


# ─── the injection ────────────────────────────────────────────────────

def test_only_the_objects_on_the_page_are_worn():
    out = so.inject_library(_page(TICKET))
    assert so.OBJECTS["ticket"].css in out and so.BASE_CSS in out
    assert so.OBJECTS["letter"].css not in out
    assert out.count("data-sx-library") == 1, "the ticket has no script"


def test_the_library_loads_after_the_meta_and_before_the_page_s_own_styles():
    out = so.inject_library(_page(TICKET))
    assert out.index('<meta charset="utf-8">') < out.index("<style data-sx-library>") < out.index("body{margin:0}")


def test_a_script_object_s_script_sits_before_the_body_closes():
    out = so.inject_library(_page(PANELS))
    i = out.index("<script data-sx-library>")
    assert so.OBJECTS["panels"].js in out[i:] and out.index("</body>") > i


def test_the_injection_is_idempotent_and_a_gone_object_leaves_no_block():
    once = so.inject_library(_page(TICKET))
    assert so.inject_library(once) == once
    stale = once.replace(TICKET, "")
    assert "data-sx-library" not in so.inject_library(stale)
    assert so.inject_library(_page()) == _page(), "no object, no change"


# ─── where pages are finished ─────────────────────────────────────────

def _wire(monkeypatch, replies):
    calls = []

    def _fake_call(system, user, business_id, spend=None):
        calls.append(user)
        return replies.pop(0) if replies else _page(TICKET)
    monkeypatch.setattr(v2, "_call", _fake_call)
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: x")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: EP)
    monkeypatch.setattr(v2, "eyes_enabled", lambda: False)
    return calls


def test_a_built_page_wears_the_library_once(monkeypatch):
    _wire(monkeypatch, [_page(TICKET)])
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert out["html"].count("<style data-sx-library>") == 1
    assert so.OBJECTS["ticket"].css in out["html"]


def test_the_repair_prompt_never_carries_the_library(monkeypatch):
    standin = '<div class="slot-frame"><p class="slot-note">Braids from behind, clean parts.</p></div>'
    calls = _wire(monkeypatch, [_page(TICKET + standin), _page(TICKET)])
    v2.run_builder_v2("SPEC", {}, "biz-1")
    assert len(calls) == 2 and "SURGICAL REPAIR" in calls[1]
    assert "data-sx-library" not in calls[1] and 'data-sx-object="ticket"' in calls[1]
    assert "data-sx-library" not in v2.page_part(so.inject_library(_page(TICKET)))


def test_a_reworked_section_wears_the_library(monkeypatch):
    doc = so.inject_library(_page('<section id="prices"><h2>Ways in</h2></section>'))
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: x")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: EP)
    monkeypatch.setattr(v2, "_call", lambda s, u, b, spend=None, units=None, task_type=None:
                        '<section id="prices">' + TICKET + "</section>")
    out = v2.refine_section_doc(doc, "SPEC", {}, "biz-1", "prices", "make it a ticket")
    assert out["ok"], out
    assert so.OBJECTS["ticket"].css in out["html"] and out["html"].count("<style data-sx-library>") == 1


def test_a_draft_the_builder_renders_wears_the_library(monkeypatch):
    seen = []
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: x")
    box = builder_loop.ToolBox({}, "biz-1", "BUSINESS: x", EP,
                               screenshots=lambda html: seen.append(html) or [("1440px top", b"jpeg")])
    box.render(_page(TICKET))
    assert seen and so.OBJECTS["ticket"].css in seen[0]


def test_repair_edits_land_on_the_page_the_model_was_shown(monkeypatch):
    """An edit copied from the shown page (no library block) is placed on
    that same page; the finishing pass wears the library again."""
    import re
    standin = '<div class="slot-frame"><p class="slot-note">Braids from behind, clean parts.</p></div>'

    def _drop(user):
        shown = user.split(v2.page_part(""), 1)[1].split(v2.CACHE_BREAK, 1)[0]
        run = re.search(r'<div class="slot-frame".*?</p></div>', shown, re.DOTALL).group(0)
        return "\n".join(["<<<<<<< SEARCH", run, "=======", "", ">>>>>>> REPLACE"])
    replies = [_page(TICKET + standin), _drop]
    calls = []

    def _fake_call(system, user, business_id, spend=None):
        calls.append(user)
        r = replies.pop(0)
        return r(user) if callable(r) else r
    monkeypatch.setattr(v2, "_call", _fake_call)
    monkeypatch.setattr(v2, "assemble_real_data", lambda ctx, b: "BUSINESS: x")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: EP)
    monkeypatch.setattr(v2, "eyes_enabled", lambda: False)
    out = v2.run_builder_v2("SPEC", {}, "biz-1")
    assert len(calls) == 2 and out["report"]["repair_modes"] == [{"stage": "surgical", "how": "edits"}]
    assert "slot-frame" not in out["html"] and out["html"].count("<style data-sx-library>") == 1
