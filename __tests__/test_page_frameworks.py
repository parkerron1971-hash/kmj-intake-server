# Frameworks arc — the skeleton decision. The enforcement contract is
# what matters: one representation per content type, framework order,
# portrait seated only when a portrait exists, fail-open.
import page_frameworks as pf


def _spec(*mids):
    return [{"module": m, "variant": "standard", "content": {}} for m in mids]


def test_duplicate_sections_collapse_to_one():
    # The live process-times-three defect.
    spec = _spec("hero", "process", "about", "process", "process", "contact")
    out = pf.apply_framework(spec, {}, None)
    assert [s["module"] for s in out].count("process") == 1


def test_interstitials_keep_up_to_two():
    spec = _spec("hero", "interstitial", "about", "interstitial",
                 "interstitial", "contact")
    out = pf.apply_framework(spec, {}, None)
    assert [s["module"] for s in out].count("interstitial") == 2


def test_storefront_selected_on_products():
    key, _ = pf.select_framework({"products": [{}, {}, {}]}, None)
    assert key == "storefront"


def test_gallery_studio_selected_on_photos():
    key, _ = pf.select_framework({"gallery": [{}] * 5}, None)
    assert key == "gallery_studio"


def test_editorial_selected_on_dro_language():
    dro = {"decisions": {"whitespace": {"philosophy": "editorial rhythm"}}}
    key, _ = pf.select_framework({}, dro)
    assert key == "editorial_monolith"


def test_order_follows_framework_and_contact_anchors():
    ctx = {"gallery": [{}] * 5}
    spec = _spec("contact", "about", "gallery", "hero", "offerings")
    out = pf.apply_framework(spec, ctx, None)
    mids = [s["module"] for s in out]
    assert mids[0] == "hero" and mids[-1] == "contact"
    assert mids.index("gallery") < mids.index("about")  # gallery_studio


def test_portrait_seated_only_with_photo():
    spec = _spec("hero", "about", "contact")
    ctx = {"business": {"type": "coach"}}
    out = pf.apply_framework(spec, ctx, None)
    about = next(s for s in out if s["module"] == "about")
    assert about["variant"] == "standard"  # no photo -> untouched
    ctx2 = {"business": {"type": "coach"}, "about_photo": "x.jpg"}
    out2 = pf.apply_framework(_spec("hero", "about", "contact"), ctx2, None)
    about2 = next(s for s in out2 if s["module"] == "about")
    assert about2["variant"] == "portrait"


def test_kill_switch_and_fail_open(monkeypatch):
    spec = _spec("about", "hero")
    monkeypatch.setenv("PAGE_FRAMEWORKS", "off")
    assert pf.apply_framework(spec, {}, None) == spec
    monkeypatch.delenv("PAGE_FRAMEWORKS")
    assert pf.apply_framework(None, {}, None) is None  # surprise input


def test_ctx_gets_the_breadcrumb():
    ctx = {"products": [{}, {}]}
    pf.apply_framework(_spec("hero", "contact"), ctx, None)
    assert ctx.get("framework_key") == "storefront"
    assert ctx.get("framework_label")
