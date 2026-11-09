"""A site the owner admires gives the designers its mood, never its identity.

The rule used to be a sentence ("never copy their exact colors") beside the
exact colors. Now the colors, fonts, address and the site's own words stay out
of every prompt, and a check after the build catches what still came out word
for word. Copying is the thing the product must not do for an owner.
"""
import builder_loop as bl
import builder_v2 as v2
import discovery
import reference_analyzer as ra
import site_composer
from agents.composer.drl import passes

_STUDY = {
    "url": "https://www.admired-church.example/",
    "ok": True,
    "palette": {"read": "dark moody with vivid accents",
                "hexes": [{"hex": "#c2125f", "count": 9, "ground": "dark",
                           "saturation": "high", "warmth": "warm"},
                          {"hex": "#1f6feb", "count": 2, "ground": "dark",
                           "saturation": "high", "warmth": "cool"},
                          {"hex": "#111111", "count": 20, "ground": "dark",
                           "saturation": "low", "warmth": "neutral"}]},
    "fonts": [{"family": "Canela Deck", "class": "serif"}],
    "density": {"label": "spare"},
    "title": "Admired Church",
    "description": "A family of believers on the north side of the city",
}
_IDENTITY = ("admired-church", "#c2125f", "#1f6feb", "Canela", "family of believers",
             "Admired Church")

_COPIED = ("We believe every person who walks through our doors deserves a place "
           "to belong and a family to grow with")


def _gone(text):
    assert not [bit for bit in _IDENTITY if bit in text], text


def test_prompts_get_mood_words_only():
    summary = ra.compact_summary([_STUDY])
    assert summary == [{"palette_read": "dark moody with vivid accents",
                        "color_temperature": "warm", "font_classes": ["serif"],
                        "density": "spare"}]
    _gone(passes._reference_analysis_block([_STUDY]))


def test_the_intake_text_names_no_site():
    text = site_composer._assemble_intake_text({"business": {"name": "Studio"}, "site_prefs": {
        "inspiration_urls": [_STUDY["url"]],
        "reference_analysis": {"urls": [_STUDY["url"]], "results": [_STUDY]},
    }})
    assert "dark moody" in text and "layout feels spare" in text
    _gone(text)


def test_the_owners_own_words_about_a_site_still_ride():
    text = site_composer._assemble_intake_text({"business": {"name": "Studio"}, "site_prefs": {
        "inspiration_urls": [_STUDY["url"]],
        "inspiration_notes": "I love how calm it feels",
    }})
    assert "I love how calm it feels" in text
    _gone(text)


def _dossier():
    d = discovery._empty_dossier()
    d["artifacts"]["references"] = [
        {"url": _STUDY["url"], "verdict": "love", "why": "calm",
         "rules": ["hairline dividers; one accent doing one job",
                   "the Admired-Church hero, big and centered"],
         "bans": [], "taste": {"ground": {"value": "dark", "confidence": 0.9}}},
        {"url": "https://stuck.example/", "verdict": "love", "error": "could not capture"}]
    return d


def test_the_digest_keeps_the_lesson_and_drops_which_site():
    d = _dossier()
    digest = discovery.dossier_digest(d)
    assert "hairline dividers" in digest and '"ground"' in digest and "could not capture" in digest
    assert "stuck.example" not in digest
    _gone(digest.replace("hairline", ""))
    # the stored dossier keeps its addresses: a study is not repeated for them
    assert d["artifacts"]["references"][0]["url"] == _STUDY["url"]
    assert len(d["artifacts"]["references"][0]["rules"]) == 2


def test_the_owners_reason_stays_without_the_name():
    ref = {"url": "https://www.apple.com/", "why": "I like how Apple gives each thing room",
           "rules": [], "taste": {"ground": {"value": "light", "confidence": 0.9},
                                  "era": {"value": "like apple", "confidence": 0.2}}}
    out = discovery._reference_for_designer(ref)
    assert out["why"] == "I like how that site gives each thing room"
    assert out["taste"] == {"ground": {"value": "light", "confidence": 0.9}}
    assert ref["why"].startswith("I like how Apple")


def test_a_short_site_name_is_removed_but_not_inside_other_words():
    out = discovery._reference_for_designer({
        "url": "https://cnn.com/", "why": "CNN feels urgent",
        "rules": ["like CNN, one lead story", "acnne is not a word; keep this rule"]})
    assert out["why"] == "that site feels urgent"
    assert out["rules"] == ["acnne is not a word; keep this rule"]


def test_the_builder_cannot_open_an_admired_site(monkeypatch):
    digest = discovery.dossier_digest(_dossier())
    box = bl.ToolBox({}, "biz-1", f"DISCOVERY DOSSIER:\n{digest}", "")
    assert box.allowed_urls == set()
    out = box.look(_STUDY["url"])
    assert len(out) == 1 and "not in the real data" in out[0]["text"]


# ── the check after the build ─────────────────────────────────────────

def _sets(html):
    words = [ra._norm(w) for w in ra._WORD_RE.findall(ra._compared_text(html))]
    return [ra._ngrams(words)]


def test_a_sentence_word_for_word_is_found():
    theirs = _sets(f"<main><p>{_COPIED}.</p><p>Other words about something else.</p></main>")
    ours = f"<main><h2>Come as you are</h2><p>{_COPIED}.</p></main>"
    assert ra.shared_wording(ours, theirs) == [_COPIED]


def test_curly_quotes_and_tags_do_not_hide_it():
    copied = "Nobody here thinks it's too late for you to start again with people who care"
    theirs = _sets(f"<p>{copied}</p>")
    ours = "<p>Nobody <em>here</em> thinks it’s too late for you to start again with people who care</p>"
    assert ra.shared_wording(ours, theirs)


def test_ordinary_phrasing_is_not_copying():
    theirs = _sets("<p>Join us this Sunday morning for worship and a warm welcome today</p>")
    assert ra.shared_wording("<p>Join us this Sunday morning for worship and a warm</p>", theirs) == []


def test_the_owners_own_words_never_count():
    theirs = _sets(f"<p>{_COPIED}</p>")
    assert ra.shared_wording(f"<p>{_COPIED}</p>", theirs, owner_text=_COPIED) == []


def test_shared_scripture_is_not_copying():
    verse = ("For God so loved the world that he gave his one and only Son that "
             "whoever believes in him shall not perish")
    theirs = _sets(f"<p>{verse}</p>")
    assert ra.shared_wording(f"<p>{verse} John 3:16</p>", theirs) == []
    assert ra.shared_wording(f"<blockquote>{verse}</blockquote>", theirs) == []


def test_a_service_time_does_not_excuse_a_copied_paragraph():
    theirs = _sets(f"<p>{_COPIED}</p>")
    for beside in ("Sunday 10:30", "Service 9:00", "Doors 6:30"):
        assert ra.shared_wording(f"<p>{beside}. {_COPIED}</p>", theirs) == [_COPIED]


def test_a_citation_far_from_the_run_does_not_excuse_it():
    theirs = _sets(f"<p>{_COPIED}</p>")
    far = "Our verse this year is Romans 8:28 and we hold to it in everything we do here at the church."
    assert ra.shared_wording(f"<p>{far}</p><p>{_COPIED}</p>", theirs) == [_COPIED]


def test_menus_footers_and_forms_repeat_across_sites():
    line = "Home About Beliefs Sermons Events Give Connect Watch Ministries Visit Contact Staff Blog"
    theirs = _sets(f"<p>{line}</p>")
    for tag in ("nav", "footer", "form"):
        assert ra.shared_wording(f"<{tag}>{line}</{tag}>", theirs) == []


def _page(font="Canela Deck", colors="#c2125f;color:#1f6feb"):
    return f"<html><head><style>body{{font-family:'{font}';color:{colors}}}</style></head><body></body></html>"


def test_the_same_lead_font_and_two_colors_is_recorded():
    found = ra.look_matches(_page(), [_STUDY])
    assert found and found[0]["shared_colors"] == 2 and found[0]["fonts"] == ["canela deck"]


def test_a_font_alone_or_colors_alone_is_not_a_match():
    assert ra.look_matches(_page(colors="#00aa55;color:#7711cc"), [_STUDY]) == []
    assert ra.look_matches(_page(font="Fraunces"), [_STUDY]) == []


def test_black_and_white_are_not_a_shared_look():
    study = dict(_STUDY, palette={"read": "x", "hexes": [
        {"hex": "#111111", "saturation": "low"}, {"hex": "#fafafa", "saturation": "low"}]})
    assert ra.look_matches(_page(colors="#111111;color:#fafafa"), [study]) == []


def _law_passing(body=""):
    endpoint = "https://api.example/contact/biz-1"
    return ("<!DOCTYPE html><html><head><title>Studio</title>"
            '<meta name="description" content="A braiding studio by hand">'
            '<meta property="og:title" content="Studio">'
            '<meta property="og:description" content="A braiding studio">'
            '<meta property="og:image" content="https://x/a.jpg">'
            "<style>body{margin:0}</style></head><body>"
            '<nav><a href="#top">Top</a></nav><main id="top"><h1>Braids worn '
            "like their own kind of magnificent.</h1>" + body + "</main>"
            f'<form method="POST" action="{endpoint}"><input name="name">'
            '<input name="email"><button>Send</button></form>'
            "<footer>Studio</footer></body></html>")


def _build(monkeypatch, first, then=None, ctx=None):
    calls = []

    def _fake_call(system, user, business_id, spend=None):
        calls.append(user)
        return first if len(calls) == 1 else (then or first)

    monkeypatch.setattr(v2, "_call", _fake_call)
    monkeypatch.setattr(v2, "assemble_real_data", lambda c, b: "BUSINESS: Studio")
    monkeypatch.setattr(v2, "contact_endpoint", lambda b: "https://api.example/contact/biz-1")
    monkeypatch.setattr(v2, "eyes_enabled", lambda: False)
    return v2.run_builder_v2("SPEC", ctx or {}, "biz-1"), calls


_CTX = {"site_prefs": {"inspiration_urls": [_STUDY["url"]],
                       "reference_analysis": {"results": [_STUDY]}}}


def test_a_copied_sentence_costs_the_repair_round(monkeypatch):
    monkeypatch.setattr(ra, "reference_word_sets", lambda urls: _sets(f"<p>{_COPIED}</p>"))
    out, calls = _build(monkeypatch, _law_passing(f"<p>{_COPIED}</p>"),
                        _law_passing("<p>Our own words.</p>"), dict(_CTX))
    assert len(calls) == 2 and "TOO CLOSE TO A SITE THE OWNER ADMIRES" in calls[1]
    assert _STUDY["url"] not in calls[1]
    assert out["html"] and not out["report"]["fallbacks"]


def test_a_sentence_that_survives_ships_and_is_reported(monkeypatch):
    monkeypatch.setattr(ra, "reference_word_sets", lambda urls: _sets(f"<p>{_COPIED}</p>"))
    page = _law_passing(f"<p>{_COPIED}</p>")
    out, _calls = _build(monkeypatch, page, page, dict(_CTX))
    assert out["html"] and _COPIED in out["html"] and not out["report"]["fallbacks"]
    closeness = out["report"]["reference_closeness"]
    assert closeness["sites_compared"] == 1 and closeness["shared_wording"] == [_COPIED]


def test_each_build_fetches_those_sites_once(monkeypatch):
    fetches = []
    monkeypatch.setattr(ra, "reference_word_sets", lambda urls: fetches.append(urls) or [])
    ctx = {"site_prefs": dict(_CTX["site_prefs"])}
    _build(monkeypatch, _law_passing(), ctx=ctx)
    _build(monkeypatch, _law_passing(), ctx=ctx)          # the offer page, same ctx
    assert len(fetches) == 1


def test_no_admired_site_means_no_fetch_and_no_report_line(monkeypatch):
    monkeypatch.setattr(ra, "reference_word_sets", lambda urls: (_ for _ in ()).throw(AssertionError("fetched")))
    out, calls = _build(monkeypatch, _law_passing())
    assert len(calls) == 1 and "reference_closeness" not in out["report"]


def test_the_switch_turns_the_check_off(monkeypatch):
    monkeypatch.setenv("REFERENCE_CLOSENESS", "off")
    monkeypatch.setattr(ra, "reference_word_sets", lambda urls: (_ for _ in ()).throw(AssertionError("fetched")))
    out, calls = _build(monkeypatch, _law_passing(f"<p>{_COPIED}</p>"), ctx=dict(_CTX))
    assert len(calls) == 1 and "reference_closeness" not in out["report"]


def test_a_site_that_will_not_open_never_stops_a_build(monkeypatch):
    def boom(urls):
        raise OSError("down")
    monkeypatch.setattr(ra, "reference_word_sets", boom)
    out, calls = _build(monkeypatch, _law_passing(), ctx=dict(_CTX))
    assert out["html"] and len(calls) == 1
    assert out["report"]["reference_closeness"]["sites_compared"] == 0
