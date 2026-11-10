"""THE KIT IN A REAL BUILD (2026-11-10, Kevin: "make the kit available for it
to be used"). The composer asks the kit first; when the blueprint's layout is
one the kit has, the page is assembled from finished sections. Any miss, and
the builder writes it as before.
"""
import re
from unittest import mock

import builder_v2
import site_composer
import site_kit as kit

ENDPOINT = "https://kmj-intake-server-production.up.railway.app/sites/b-kit/contact-submit"

CTX = {
    "business": {"id": "b-kit", "name": "Marrow & Steel", "type": "barbershop", "slug": "marrow"},
    "design_spec_text": "0. THE CONCEPT\nLAYOUT: booking - every service books in one tap\n",
    "site": {"site_config": {"discovery_dossier": {"identity": {"team": [{"name": "Deshawn Ellis", "role": "Owner"}]}}}},
    "offerings": [{"name": "Skin Fade", "current_price": 45, "duration_min": 45, "description": "Down to skin."},
                  {"name": "Classic Cut", "price": 35, "duration_min": 30}],
    "testimonials": [{"text": "Only person I trust with a fade.", "author": "Marcus T."}],
    "gallery": [{"url": "https://example.org/a.jpg", "alt": "A fade"}, {"url": "/local.jpg"}],
    "booking": {"enabled": True, "url": "/book"},
    "contact": {"email": "hi@marrow.test", "phone": "(216) 555-0148", "address": "14812 Detroit Ave",
                "hours": "", "submit_url": ENDPOINT},
    "bundle": {"practitioner": {"name": "Deshawn Ellis"}},
}

WORDS = {"hero": {"lines": ["Sharp fades.", "Clean lineups."], "accent_word": "Sharp"},
         "board": {"headline": "Every price on the wall"}, "visit": {"headline": "Come by"},
         "nav": [{"label": "Prices", "target": "board"}]}


# ─── the switch ──────────────────────────────────────────────────────

def test_the_switch_defaults_to_the_owner_and_reads_three_ways(monkeypatch):
    monkeypatch.delenv("SITE_KIT", raising=False)
    assert kit.mode() == "owner"
    monkeypatch.setenv("SITE_KIT", "nonsense")
    assert kit.mode() == "off"
    monkeypatch.setenv("SITE_KIT", "on")
    assert kit.enabled_for("anything")
    monkeypatch.setenv("SITE_KIT", "off")
    assert not kit.enabled_for("anything")


def test_owner_mode_is_only_the_platform_owners_businesses(monkeypatch):
    monkeypatch.setenv("SITE_KIT", "owner")
    import church_checks
    import sb_clients
    with mock.patch.object(sb_clients, "sb_get_as_service", return_value=[{"owner_id": "u1"}]):
        with mock.patch.object(church_checks, "is_platform_owner", return_value=True):
            assert kit.enabled_for("b1")
        with mock.patch.object(church_checks, "is_platform_owner", return_value=False):
            assert not kit.enabled_for("b1")
    with mock.patch.object(sb_clients, "sb_get_as_service", side_effect=RuntimeError("down")):
        assert not kit.enabled_for("b1")                              # a failed read is a no


# ─── a real build's context ──────────────────────────────────────────

def test_a_real_builds_context_reads_into_the_kit():
    fx = kit.fx_from_ctx(CTX, "b-kit")
    assert fx["offerings"][0]["price"] == 45 and fx["offerings"][1]["price"] == 35
    assert fx["testimonials"] == [{"quote": "Only person I trust with a fade.", "name": "Marcus T.", "role": ""}]
    assert [g["url"] for g in fx["gallery"]] == ["https://example.org/a.jpg"]
    assert fx["booking_url"] == "/book" and fx["form_endpoint"] == ENDPOINT
    off = kit.fx_from_ctx({**CTX, "booking": {"enabled": False, "url": "/book"}}, "b-kit")
    assert off["booking_url"] == ""


# ─── the build ───────────────────────────────────────────────────────

def _build(words=WORDS, ctx=CTX, mode="on"):
    with mock.patch.dict("os.environ", {"SITE_KIT": mode}):
        with mock.patch.object(kit, "write_words", return_value=words):
            return kit.build(ctx, "b-kit")


def test_the_kit_builds_a_page_with_a_working_form():
    html, report = _build()
    assert html and report["engine"] == "site_kit" and report["layout"] == "booking"
    assert f'fetch("{ENDPOINT}"' in html                               # the form survived the armor
    assert report["mechanical"]["scripts_dropped"] == []
    assert "<form" in html and 'name="email"' in html
    assert "data-override-target=" in html                             # owners can edit its words
    assert "$45" in html


def test_the_form_script_passes_the_builders_own_armor():
    d = kit.facts(kit.fx_from_ctx(CTX, "b-kit"), {})
    form = kit.contact_form(d, {})
    out, dropped = builder_v2.armor_scripts(form, allowed_fetch=ENDPOINT)
    assert dropped == [] and f'fetch("{ENDPOINT}"' in out


def test_no_endpoint_means_no_form_and_the_kit_stands_down():
    ctx = {**CTX, "contact": {**CTX["contact"], "submit_url": "https://evil.example/collect"}}
    with mock.patch.object(builder_v2, "contact_endpoint", return_value="not a url"):
        html, report = _build(ctx=ctx)
    assert html is None and report["fallbacks"][0]["stage"] == "laws"


def test_the_kit_stays_out_when_off_or_the_layout_isnt_in_it():
    assert _build(mode="off") == (None, None)
    assert _build(ctx={**CTX, "design_spec_text": "LAYOUT: bento - many facts"}) == (None, None)
    assert _build(ctx={**CTX, "design_spec_text": ""}) == (None, None)


def test_a_failed_words_call_hands_the_page_to_the_builder():
    with mock.patch.dict("os.environ", {"SITE_KIT": "on"}):
        with mock.patch.object(kit, "write_words", side_effect=RuntimeError("timeout")):
            html, report = kit.build(CTX, "b-kit")
    assert html is None and report["fallbacks"][0]["stage"] == "exception"


# ─── the composer asks the kit first ─────────────────────────────────

def test_the_composer_takes_the_kits_page():
    with mock.patch.object(kit, "build", return_value=("<html>kit</html>", {"engine": "site_kit"})):
        with mock.patch.object(builder_v2, "run_builder_v2") as v2:
            html, report = site_composer._run_builder_v2(CTX, "b-kit")
    assert html == "<html>kit</html>" and report["engine"] == "site_kit"
    v2.assert_not_called()


def test_the_composer_runs_the_builder_when_the_kit_stands_down():
    with mock.patch.object(kit, "build", return_value=(None, {"engine": "site_kit", "fallbacks": ["x"]})):
        with mock.patch.object(builder_v2, "enabled", return_value=True):
            with mock.patch.object(builder_v2, "run_builder_v2",
                                   return_value={"html": "<html>v2</html>", "report": {"engine": "builder_v2"}}):
                html, report = site_composer._run_builder_v2(CTX, "b-kit")
    assert html == "<html>v2</html>" and report["engine"] == "builder_v2"


def test_a_kit_crash_never_stops_a_build():
    with mock.patch.object(kit, "build", side_effect=RuntimeError("boom")):
        with mock.patch.object(builder_v2, "enabled", return_value=False):
            assert site_composer._run_builder_v2(CTX, "b-kit") == (None, None)


def test_church_layouts_build_through_the_same_path():
    ctx = {**CTX, "business": {"id": "b-kit", "name": "Cedar Church", "type": "church"},
           "design_spec_text": "LAYOUT: bulletin - set times", "offerings": [],
           "contact": {**CTX["contact"], "hours": "Sundays 10:30am"}}
    html, report = _build(words={"gatherings": [{"day": 0, "time": "10:30", "label": "Sunday worship"}],
                                 "hero": {"lines": ["Come as", "you are"]}}, ctx=ctx)
    assert html and report["layout"] == "bulletin"
    assert re.search(r"Sunday", html) and f'fetch("{ENDPOINT}"' in html
