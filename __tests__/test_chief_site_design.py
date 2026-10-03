"""
test_chief_site_design.py — a site request goes to the Design Coach first
(2026-10-03).

Kevin: the blueprint exists to capture the client's style so Chief never
builds a generic site, and when someone asks Chief for a site, Chief brings
the Coach into the chat. Pins: the rebuild gate (only an approved blueprint
builds), the two UI verbs and their frontend events, the PRACTITIONER SITE
lines, and the prompt's new order of moves.
"""
import asyncio
from unittest import mock

import chief_site_design as csd


def _spec(status):
    return {"text": "THE SPEC", "status": status}


# ─── the rebuild gate ───────────────────────────────────────────────

def test_an_approved_blueprint_opens_the_gate():
    with mock.patch.object(csd, "_spec", return_value=_spec("approved")):
        assert csd.rebuild_gate("b1") is None


def test_a_drafted_blueprint_points_at_the_card():
    with mock.patch.object(csd, "_spec", return_value=_spec("draft")):
        why = csd.rebuild_gate("b1")
    assert "show_blueprint" in why and "Build it" in why


def test_no_blueprint_points_at_the_coach():
    with mock.patch.object(csd, "_spec", return_value=None):
        why = csd.rebuild_gate("b1")
    assert "start_design_session" in why


# ─── the PRACTITIONER SITE lines ────────────────────────────────────

def _site(cfg):
    return {"slug": "x", "site_config": cfg}


def test_site_lines_say_where_the_design_stands():
    none = csd.site_design_lines(_site({}), {})
    assert "none yet" in none[0] and "start_design_session" in none[0]
    draft = csd.site_design_lines(_site({"design_spec": _spec("draft")}), {})
    assert "drafted" in draft[0] and "show_blueprint" in draft[0]
    ok = csd.site_design_lines(_site({"design_spec": _spec("approved")}), {})
    assert "approved" in ok[0]


def test_a_hand_built_site_gets_no_design_lines():
    assert csd.site_design_lines(_site({"html_source": "manual"}), {}) == []


def _settings(*urls, hidden=()):
    gal = [{"url": u} for u in urls] + [{"url": u, "show_on_website": False} for u in hidden]
    return {"media_library": {"gallery": gal}}


def _v2(html):
    return {"canvas_report": {"engine": "builder_v2"}, "canvas": {"html": html}}


def test_photos_not_on_the_site_are_counted_for_a_new_builder_page():
    cfg = _v2('<img src="https://a/1.jpg">')
    st = _settings("https://a/1.jpg", "https://a/2.jpg", "https://a/3.jpg",
                   hidden=("https://a/4.jpg",))
    assert csd.photos_not_on_site(st, cfg) == 2
    lines = csd.site_design_lines(_site(cfg), st)
    assert any("Photos not on the site yet: 2" in ln and "refine_section" in ln
               for ln in lines)


def test_module_composed_pages_do_not_count_photos():
    """A module-composed page re-renders the library on refresh."""
    cfg = {"canvas_report": {"engine": "canvas"}, "canvas": {"html": ""}}
    assert csd.photos_not_on_site(_settings("https://a/1.jpg"), cfg) == 0
    assert csd.photos_not_on_site(_settings("https://a/1.jpg"), _v2("")) == 0


# ─── the verbs ──────────────────────────────────────────────────────

BIZ = {"id": "biz-1", "owner_id": "u1"}


def test_start_design_session_opens_the_coach_quick_by_default():
    with mock.patch.object(csd, "_hand_built_block", return_value=None):
        out = asyncio.run(csd.handle_start_design_session(None, BIZ, {}))
    assert out["result"] and out["label"]
    ev = out["frontend_event"]
    assert ev["name"] == csd.SESSION_EVENT
    assert ev["detail"]["mode"] == "quick" and ev["detail"]["business_id"] == "biz-1"
    assert "Do not start a build" in out["result"]


def test_start_design_session_deep_and_brief_notes_ride_the_event():
    with mock.patch.object(csd, "_hand_built_block", return_value=None):
        out = asyncio.run(csd.handle_start_design_session(
            None, BIZ, {"mode": "deep", "brief_notes": "tagline: steady hands"}))
    assert out["frontend_event"]["detail"]["mode"] == "deep"
    assert out["frontend_event"]["detail"]["brief_notes"] == "tagline: steady hands"


def test_a_hand_built_site_gets_no_design_session():
    with mock.patch.object(csd, "_hand_built_block",
                           return_value="this site is the hand-built edition"):
        out = asyncio.run(csd.handle_start_design_session(None, BIZ, {}))
    assert out["result"].startswith("Not opened")
    assert "frontend_event" not in out and out["label"]


def test_show_blueprint_without_one_sends_them_to_the_coach():
    with mock.patch.object(csd, "_spec", return_value=None):
        out = asyncio.run(csd.handle_show_blueprint(None, BIZ, {}))
    assert "start_design_session" in out["result"] and out["label"]
    assert "frontend_event" not in out


def test_show_blueprint_shows_the_card_and_never_builds():
    with mock.patch.object(csd, "_spec", return_value=_spec("draft")), \
            mock.patch.object(csd, "_card_summary", return_value="idea: a counter"):
        out = asyncio.run(csd.handle_show_blueprint(None, BIZ, {}))
    assert out["frontend_event"]["name"] == csd.CARD_EVENT
    assert "idea: a counter" in out["result"]
    assert "only when they tap Build it" in out["result"]


# ─── wiring ─────────────────────────────────────────────────────────

def test_both_verbs_are_registered_as_ui_directives():
    import chief_of_staff as cos
    import action_registry
    for verb in ("start_design_session", "show_blueprint"):
        assert verb in cos.ACTION_HANDLERS
        assert action_registry.REGISTRY[verb]["effect"] == action_registry.UI


def test_the_site_block_carries_the_design_line():
    import chief_of_staff as cos
    ctx = {"site": {"slug": "shop", "status": "published", "site_config": {}},
           "business": {"settings": {}}}
    assert "Design blueprint: none yet" in cos._format_site_info(ctx)


def test_the_website_block_brings_in_the_coach_before_any_build():
    import chief_of_staff  # noqa: F401  (chief_prompt imports from it)
    import chief_prompt
    block = chief_prompt._build_website_block()
    assert "start_design_session" in block and "show_blueprint" in block
    assert "revise_spec" in block
    # the old one-line style question is gone: the Coach owns the style
    assert "Modern and clean? Warm and welcoming?" not in block
    assert block.index("start_design_session") < block.index("Build it")
