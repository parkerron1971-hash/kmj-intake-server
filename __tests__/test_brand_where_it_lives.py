"""
test_brand_where_it_lives.py — which surfaces still wear an older look,
and the booking page finally wearing the brand at all.

What must hold:
  • "When did the look change" is the newest history entry whose colours,
    faces or tagline DIFFER — not the last save. An override or the font
    lock saves too, and must not mark the website as behind.
  • The website is judged by site_config.html_generated_at (the render
    stamp), never by updated_at; a site built another way is not judged.
  • Timestamps are compared as times, not strings ("Z" vs "+00:00").
  • The booking page reads the REAL kit shape (colors.*, font_pair.*).
"""
import brand_engine
import booking_page_renderer as bpr


def _kit(primary="#1e3a34", heading="Fraunces", tagline="Lead the next chapter."):
    return {"colors": {"primary": primary, "secondary": "#7a8f7e", "accent": "#d9793b",
                       "background": "#f6f1e8", "text": "#1b1f1d"},
            "font_pair": {"heading": heading, "body": "Work Sans"}, "tagline": tagline}


def test_the_look_changed_when_the_last_different_version_was_replaced():
    biz = {"settings": {"brand_kit": _kit()}, "brand_kit_history": [
        {"kit": {**_kit(), "published_overrides": {"copyright_line": "x"}}, "saved_at": "2026-09-20T10:00:00Z"},
        {"kit": _kit(primary="#2a4b44"), "saved_at": "2026-09-12T09:00:00Z"},
        {"kit": _kit(primary="#3b4a6b"), "saved_at": "2026-08-30T09:00:00Z"},
    ]}
    assert brand_engine.look_changed_at(biz) == "2026-09-12T09:00:00Z", \
        "an override save must not count as a new look"


def test_no_older_look_means_unknown():
    assert brand_engine.look_changed_at({"settings": {"brand_kit": _kit()}, "brand_kit_history": []}) is None
    assert brand_engine.look_changed_at({"settings": {}}) is None


def _wired(monkeypatch, *, site_rows, image_rows, print_materials=None):
    biz = {"id": "b1", "settings": {"brand_kit": _kit(), "print_materials": print_materials or {}},
           "brand_kit_history": [{"kit": _kit(primary="#2a4b44"), "saved_at": "2026-09-12T09:00:00Z"}]}
    monkeypatch.setattr(brand_engine, "_safe_get_one", lambda *a: biz)

    def fake_get(path):
        if path.startswith("/business_sites"):
            return site_rows
        if path.startswith("/image_artworks"):
            return image_rows
        raise AssertionError(path)

    monkeypatch.setattr(brand_engine.sb_clients, "sb_get_as_service", fake_get)
    return brand_engine.where_it_lives("b1")


def test_a_site_rendered_before_the_new_look_is_behind(monkeypatch):
    out = _wired(monkeypatch, site_rows=[{"status": "published", "html_source": "module-composer",
                                          "generated_at": "2026-09-10T08:00:00+00:00"}], image_rows=[])
    assert out["website"]["status"] == "behind"


def test_a_site_rendered_after_is_in_step_even_with_mixed_formats(monkeypatch):
    # "…Z" vs "…+00:00" and different fraction digits: compared as times.
    out = _wired(monkeypatch, site_rows=[{"status": "published", "html_source": "canvas",
                                          "generated_at": "2026-09-12T09:00:00.5+00:00"}], image_rows=[])
    assert out["website"]["status"] == "in_step"


def test_a_site_built_another_way_is_not_judged(monkeypatch):
    out = _wired(monkeypatch, site_rows=[{"status": "published", "html_source": "manual",
                                          "generated_at": "2026-01-01T00:00:00Z"}], image_rows=[])
    assert out["website"]["status"] == "not_composed"
    out = _wired(monkeypatch, site_rows=[], image_rows=[])
    assert out["website"]["status"] == "no_site"


def test_print_pieces_and_images_made_before_the_look_are_counted(monkeypatch):
    out = _wired(monkeypatch, site_rows=[],
                 image_rows=[{"created_at": "2026-09-01T00:00:00Z"}, {"created_at": "2026-09-20T00:00:00Z"}],
                 print_materials={
                     "business_card": {"html": "<div/>", "generated_at": "2026-09-01T00:00:00.000Z"},
                     "one_pager": {"html": "<div/>", "generated_at": "2026-09-25T00:00:00.000Z"},
                 })
    assert out["print"] == {"total": 2, "behind": ["Business card"]}
    assert out["images"] == {"total": 2, "behind": 1}


# ─── The booking page wears the brand ─────────────────────────────────

def test_the_booking_page_reads_the_real_kit_shape():
    biz = {"settings": {"brand_kit": _kit(), "booking_page": {"published": True}}}
    css = bpr._css_vars(bpr._brand_kit(biz))
    assert "--accent: #d9793b" in css
    assert "--surface: #f6f1e8" in css
    assert "--text-primary: #1b1f1d" in css
    assert "--font-heading: Fraunces, Georgia, serif" in css
    assert "#a78bfa" not in css, "the purple default must not win over a real kit"


def test_the_old_shape_still_wins_where_it_exists():
    biz = {"settings": {"brand_kit": {**_kit(), "accent": "#ff8800"}}}
    assert "--accent: #ff8800" in bpr._css_vars(bpr._brand_kit(biz))


def test_a_font_name_never_puts_a_quote_into_the_stylesheet():
    biz = {"settings": {"brand_kit": {"font_pair": {"heading": "Owner's Font\"; x", "body": "Work Sans"}}}}
    css = bpr._css_vars(bpr._brand_kit(biz))
    assert "&#x27;" not in css and "&quot;" not in css and ";x" not in css.replace(" ", "")
