"""
test_refine_section_v2.py — "rework this section" on a page from the new
builder (2026-10-03).

site_composer.refine_section only knew module-composed pages, so an owner
could not ask for one section of a new-builder page to change, and photos
added after a build had no way onto the page short of a full rebuild.
Pins: the section is found by id or by a friendly name, only that section
changes, the laws hold (a rework that breaks one, or draws a stand-in
box, changes nothing), the price rides the one model call, and the job
routes new-builder pages here while module pages keep the atelier path.
"""
from unittest import mock

import builder_v2 as bv2
import site_composer as sc

DOC = ("<!DOCTYPE html><html lang=\"en\"><head><title>Shop</title></head><body>"
       "<section id=\"top\"><h1>Steady hands</h1><p>A shop in Lakewood.</p></section>"
       "<section id=\"work\"><h2>The work</h2><p>Fades and lineups.</p></section>"
       "<section id=\"about\"><h2>Our story</h2><p>Two chairs.</p></section>"
       "</body></html>")

NEW_WORK = ("<section id=\"work\"><h2>The work</h2>"
            "<img src=\"https://x/fade.jpg\" alt=\"A skin fade\"></section>")


def _quiet_laws(monkeypatch, flag=None):
    """Every law passes except one that flags `flag` when it appears."""
    for name in ("check_truth", "check_tenure", "check_connected"):
        monkeypatch.setattr(bv2, name, lambda d, rd: [])
    monkeypatch.setattr(bv2, "check_coverage", lambda d, rd, page="home": [])
    monkeypatch.setattr(bv2, "check_head", lambda d: [])
    monkeypatch.setattr(bv2, "check_interactions", lambda d: [])
    monkeypatch.setattr(bv2, "check_grammar",
                        lambda d: ([f"GRAMMAR: {flag}"] if flag and flag in d else []))
    monkeypatch.setattr(bv2, "assemble_real_data", lambda ctx, bid: "PHOTOS: https://x/fade.jpg")
    monkeypatch.setattr(bv2, "contact_endpoint", lambda bid: "")


# ─── finding the section ────────────────────────────────────────────

def test_resolve_by_id_friendly_name_and_heading():
    assert bv2.resolve_section(DOC, "work") == "work"
    assert bv2.resolve_section(DOC, "#about") == "about"
    assert bv2.resolve_section(DOC, "gallery") == "work"      # friendly name
    assert bv2.resolve_section(DOC, "hero") == "top"
    assert bv2.resolve_section(DOC, "story") == "about"        # synonym, then heading
    assert bv2.resolve_section(DOC, "pricing") is None
    assert bv2.resolve_section(DOC, "") is None


def test_an_unknown_section_is_honest_and_lists_the_real_ones(monkeypatch):
    _quiet_laws(monkeypatch)
    out = bv2.refine_section_doc(DOC, "SPEC", {}, "b1", "pricing", "bolder")
    assert out["ok"] is False and "isn't on the page" in out["error"]
    assert out["sections"] == ["top", "work", "about"]


# ─── the rework ─────────────────────────────────────────────────────

def _processed(monkeypatch):
    """DOC as a finished build carries it: through the same armor once."""
    with mock.patch.object(bv2, "_call", side_effect=lambda *a, **k:
                           "<section id=\"work\"><h2>The work</h2><p>Fades and lineups.</p></section>"):
        return bv2.refine_section_doc(DOC, "SPEC", {}, "b1", "work", "same")["html"]


def _other_sections(doc, skip):
    return {sid: doc[a:z] for sid, a, z in bv2.section_spans(doc) if sid != skip}


def test_only_the_named_section_changes_and_the_price_rides_the_call(monkeypatch):
    _quiet_laws(monkeypatch)
    page = _processed(monkeypatch)
    seen = {}

    def fake_call(system, user, business_id, spend=None, units=None, task_type=""):
        seen.update(units=units, task_type=task_type, user=user)
        return NEW_WORK

    with mock.patch.object(bv2, "_call", side_effect=fake_call):
        out = bv2.refine_section_doc(page, "SPEC", {}, "b1", "gallery",
                                     "use my new photos", units=120)
    assert out["ok"] is True and out["section"] == "work"
    assert "https://x/fade.jpg" in out["html"]
    assert _other_sections(out["html"], "work") == _other_sections(page, "work")
    assert seen["units"] == 120 and seen["task_type"] == "builder_v2_refine"
    assert "use my new photos" in seen["user"]


def test_a_rework_that_breaks_a_law_changes_nothing(monkeypatch):
    _quiet_laws(monkeypatch, flag="BROKEN")
    with mock.patch.object(bv2, "_call",
                           return_value="<section id=\"work\"><p>BROKEN</p></section>"):
        out = bv2.refine_section_doc(DOC, "SPEC", {}, "b1", "work", "x")
    assert out["ok"] is False and "rules" in out["error"]
    assert "html" not in out


def test_a_law_the_page_already_broke_does_not_block_the_rework(monkeypatch):
    _quiet_laws(monkeypatch, flag="Lakewood")       # the hero already trips it
    with mock.patch.object(bv2, "_call", return_value=NEW_WORK):
        out = bv2.refine_section_doc(DOC, "SPEC", {}, "b1", "work", "x")
    assert out["ok"] is True


def test_a_rework_that_draws_a_stand_in_box_changes_nothing(monkeypatch):
    _quiet_laws(monkeypatch)
    box = ("<section id=\"work\"><h2>The work</h2><div class=\"photo-placeholder\">"
           "<p>A fresh fade in warm light</p></div></section>")
    with mock.patch.object(bv2, "_call", return_value=box):
        out = bv2.refine_section_doc(DOC, "SPEC", {}, "b1", "work", "x")
    assert out["ok"] is False and "box" in out["error"]


def test_no_reply_or_a_reply_that_does_not_fit_changes_nothing(monkeypatch):
    _quiet_laws(monkeypatch)
    with mock.patch.object(bv2, "_call", return_value=None):
        assert bv2.refine_section_doc(DOC, "S", {}, "b1", "work", "x")["ok"] is False
    with mock.patch.object(bv2, "_call", return_value="<div>not a section</div>"):
        assert bv2.refine_section_doc(DOC, "S", {}, "b1", "work", "x")["ok"] is False


# ─── the job routes new-builder pages here ──────────────────────────

V2_CFG = {"html_source": "canvas", "canvas_report": {"engine": "builder_v2"},
          "canvas": {"html": DOC}, "design_spec": {"text": "SPEC", "status": "approved"}}


def test_is_builder_page():
    assert sc._is_builder_page(V2_CFG) is True
    assert sc._is_builder_page({**V2_CFG, "html_source": "module-composer"}) is False
    assert sc._is_builder_page({**V2_CFG, "canvas": {"html": ""}}) is False
    assert sc._is_builder_page({**V2_CFG, "canvas_report": {"engine": "canvas"}}) is False


def test_refine_section_on_a_builder_page_stores_the_rework_and_re_renders(monkeypatch):
    patches = []
    monkeypatch.setattr(sc, "gather_context", lambda bid: {"site": {"site_config": V2_CFG}})
    monkeypatch.setattr(sc.sb_clients, "sb_get_as_service",
                        lambda path: [{"id": "row1", "slug": "shop", "site_config": dict(V2_CFG)}])
    monkeypatch.setattr(sc.sb_clients, "sb_patch_as_service",
                        lambda path, body: patches.append((path, body)) or [body])
    refreshed = []
    monkeypatch.setattr(sc, "refresh_if_composed", lambda bid: refreshed.append(bid) or True)
    import spec_author
    monkeypatch.setattr(spec_author, "approved_spec_text", lambda bid: "SPEC")
    import pricing_config
    with mock.patch.object(bv2, "refine_section_doc",
                           return_value={"ok": True, "html": "NEW DOC", "section": "work",
                                         "notes": []}) as rs:
        out = sc.refine_section("b1", "gallery", "use my new photos")
    assert out["ok"] is True and out["section"] == "work"
    assert out["url"] == "https://shop.mysolutionist.app"
    assert rs.call_args.kwargs["units"] == pricing_config.section_rewrite()
    path, body = patches[-1]
    assert path == "/business_sites?id=eq.row1"
    assert body["site_config"]["canvas"]["html"] == "NEW DOC"
    assert body["site_config"]["canvas_refines"][-1]["section"] == "work"
    assert refreshed == ["b1"]


def test_an_honest_failure_writes_nothing(monkeypatch):
    patches = []
    monkeypatch.setattr(sc, "gather_context", lambda bid: {"site": {"site_config": V2_CFG}})
    monkeypatch.setattr(sc.sb_clients, "sb_get_as_service",
                        lambda path: [{"id": "row1", "slug": "shop", "site_config": dict(V2_CFG)}])
    monkeypatch.setattr(sc.sb_clients, "sb_patch_as_service",
                        lambda path, body: patches.append(body))
    import spec_author
    monkeypatch.setattr(spec_author, "approved_spec_text", lambda bid: "SPEC")
    with mock.patch.object(bv2, "refine_section_doc",
                           return_value={"ok": False, "error": "nope", "sections": ["top"],
                                         "violations": ["x"]}):
        out = sc.refine_section("b1", "pricing", "x")
    assert out == {"ok": False, "error": "nope", "sections": ["top"]}
    assert patches == []


def test_module_pages_keep_the_atelier_path(monkeypatch):
    cfg = {"html_source": "module-composer"}
    monkeypatch.setattr(sc, "gather_context", lambda bid: {"site": {"site_config": cfg}})
    import atelier
    monkeypatch.setattr(atelier, "atelier_enabled", lambda: True)
    with mock.patch.object(sc, "_refine_section_v2") as v2:
        out = sc.refine_section("b1", "hero", "bolder")
    v2.assert_not_called()
    assert out["ok"] is False and "no composed page" in out["error"]
