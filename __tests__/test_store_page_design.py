"""Store page design inheritance — the hosted store wears the site's DNA.

The contract under test:
  • token resolution priority: composed-site DRO tokens (dark editorial
    site → dark editorial store) → brand kit → neutral default, and the
    composed site's design language (mural/monograph/ledger) stamps its
    craft class on the page;
  • every interpolated business string is escaped — a product name
    carrying <script> or quotes renders inert;
  • badges: "Instant download" when a file is attached, "Only X left"
    for low stock, sold-out items render unpurchasable (no add button);
  • checkout mechanics unchanged: same localStorage key, same
    /payments/store-checkout POST of {slug, items:[{offering_id,
    quantity}]} — server-side pricing untouched;
  • thank-you page keeps the download buttons and the webhook-race
    "finalizing" card + capped refresh, restyled on the same tokens;
  • vertical softening: a ministry's store says Resources, not Store.
"""
from __future__ import annotations

import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

from test_i2_gl_sync import FakeSB  # noqa: E402

BIZ = "b1"
SLUG = "kevs"

KIT = {
    "colors": {"primary": "#1a1a2e", "accent": "#c9a84c",
               "background": "#0f0f14"},
    "font_pair": {"heading": "Fraunces", "body": "Source Sans 3"},
    "tagline": "Walk in purpose",
    "logo_url": "https://cdn.example/logo.png",
    "tone_words": ["warm"],
}

ITEMS = [
    {"id": "a", "name": "Devotional", "category": "product",
     "current_price": 25.0, "in_stock": True, "units_left": 3,
     "instant_download": True, "description": "Daily readings"},
    {"id": "b", "name": "Course One", "category": "course",
     "current_price": 99.0, "in_stock": True, "units_left": None,
     "instant_download": False, "image_url": "https://img.example/c.jpg"},
    {"id": "c", "name": "Bundle", "category": "package",
     "current_price": 150.0, "in_stock": False, "units_left": None,
     "instant_download": False},
]

SS = {"tax_rate_pct": 7.5, "flat_shipping_cents": 500}


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    return fb


def _biz(**over):
    b = {"id": BIZ, "name": "Kev Studio", "type": "consultant",
         "settings": {"brand_kit": dict(KIT)}, "stripe_account_id": "acct_1"}
    b.update(over)
    return b


def _site(**over):
    s = {"id": "s1", "business_id": BIZ, "slug": SLUG, "status": "published",
         "site_config": {"language": {"key": "ledger"},
                         "html_source": "canvas"}}
    s.update(over)
    return s


# ─── Token resolution priority ───────────────────────────────────────

def test_brand_kit_tokens_reach_the_page():
    from store_page import render_store_page
    html = render_store_page(SLUG, _biz(), ITEMS, SS)
    assert "--sx-accent: #c9a84c" in html          # kit accent (nested shape)
    assert "--sx-bg: #0f0f14" in html              # kit ground
    assert "'Fraunces'" in html                    # kit heading font
    assert "fonts.googleapis.com" in html


def test_composed_site_language_and_dro_win(fake):
    from store_page import render_store_page
    fake.rows("design_rationales").append({
        "id": "dro1",
        "dro": {"decisions": {
            "palette": {"base": "deep_dark", "temperature": "warm"},
            "typography": {"display_personality": "editorial_serif"},
        }}})
    site = _site(site_config={"language": {"key": "ledger"},
                              "design_rationale_id": "dro1"})
    html = render_store_page(SLUG, _biz(), ITEMS, SS, site=site)
    assert "st-lang-ledger" in html                # language class stamped
    assert "design source: composed_site" in html
    # deep_dark ground (warm temperature nudges its hue, so assert the
    # kit ground was REPLACED rather than pin an exact derived hex).
    assert "--sx-bg: #0f0f14" not in html
    assert "https://kevs.mysolutionist.app" in html   # link back to the site


def test_unpublished_site_falls_back_to_brand_kit():
    from store_page import render_store_page
    html = render_store_page(SLUG, _biz(), ITEMS, SS,
                             site=_site(status="draft"))
    assert "design source: brand_kit" in html
    assert "st-lang-" not in html
    assert "mysolutionist.app/page" not in html


def test_no_brand_no_site_neutral_default():
    from store_page import render_store_page
    html = render_store_page(SLUG, {"id": "b9", "name": "S", "settings": {}},
                             ITEMS, SS)
    assert "design source: default" in html
    assert "--sx-bg:" in html and "--sx-accent:" in html


def test_resolve_fails_open(monkeypatch):
    import store_design
    monkeypatch.setattr(store_design, "_bundle_lite",
                        lambda biz: (_ for _ in ()).throw(RuntimeError("boom")))
    out = store_design.resolve(_site(), _biz())
    assert out["source"] == "default"
    assert out["dna"]["palette"]["bg"]            # still a full token set


# ─── Escaping ────────────────────────────────────────────────────────

def test_hostile_strings_render_inert():
    from store_page import render_store_page
    items = [{"id": "x", "name": 'Evil <script>alert(1)</script> "quoted"',
              "category": "product", "current_price": 10.0, "in_stock": True,
              "units_left": None, "instant_download": False,
              "description": '<img src=x onerror=alert(2)>'}]
    biz = _biz(name='K&M "Studio" <Ltd>')
    biz["settings"]["brand_kit"]["tagline"] = '<b>bold</b> & "sharp"'
    html = render_store_page(SLUG, biz, items, SS)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x onerror" not in html
    assert "K&amp;M &quot;Studio&quot; &lt;Ltd&gt;" in html
    assert "&lt;b&gt;bold&lt;/b&gt;" in html
    # the add-button data attributes carry the escaped name too
    assert 'data-name="Evil &lt;script&gt;' in html


# ─── Badges + stock states ───────────────────────────────────────────

def test_badges_and_stock_states():
    from store_page import render_store_page
    html = render_store_page(SLUG, _biz(), ITEMS, SS)
    assert "Instant download" in html
    assert "Only 3 left" in html
    assert "Sold out" in html
    # sold-out card is unpurchasable: exactly 2 add buttons for 3 items
    assert html.count('class="st-add"') == 2
    # image item renders an <img>, imageless items the category glyph
    assert 'src="https://img.example/c.jpg"' in html
    assert 'class="st-ph"' in html


def test_category_headings_grouped():
    from store_page import render_store_page
    html = render_store_page(SLUG, _biz(), ITEMS, SS)
    assert "Products" in html and "Courses" in html and "Packages" in html


# ─── Checkout contract (byte-compatible with /payments/store-checkout) ─

def test_checkout_mechanics_unchanged():
    from store_page import render_store_page
    html = render_store_page(SLUG, _biz(), ITEMS, SS)
    assert "'sx-cart-' + SLUG" in html              # same cart key
    assert "/payments/store-checkout" in html
    assert "offering_id: id, quantity: cart[id]" in html
    assert 'var SLUG = "kevs";' in html
    assert 'data-id="a"' in html and 'data-price="25.00"' in html
    # tax + shipping notes still server-rendered
    assert "Sales tax (7.5%)" in html
    assert "Flat shipping $5.00" in html


# ─── Router wiring ───────────────────────────────────────────────────

def test_hosted_page_route_serves_design(fake):
    import store_router
    fake.rows("business_sites").append(_site())
    fake.rows("businesses").append(_biz())
    fake.rows("offerings").append({
        "id": "a", "business_id": BIZ, "name": "Devotional",
        "category": "product", "is_active": True, "current_price": 25,
        "inventory_qty": 3})
    resp = store_router.hosted_store_page(SLUG)
    body = resp.body.decode()
    assert resp.headers["X-Solutionist-Source"] == "store"
    assert "st-lang-ledger" in body
    assert "Only 3 left" in body


# ─── Thank-you flow ──────────────────────────────────────────────────

def test_thank_you_downloads_and_finalizing():
    from store_page import render_thank_you
    ty = render_thank_you(SLUG, _biz(), "ord12345678",
                          downloads=[{"name": "Guide", "url": "https://d/l?x=1"}],
                          site=_site())
    assert "Download Guide" in ty
    assert "ORD12345" in ty
    assert "--sx-accent: #c9a84c" in ty            # same tokens as the store
    assert "location.replace" not in ty            # no refresh once ready
    ty2 = render_thank_you(SLUG, _biz(), "ord1", digital_pending=True)
    assert "Finalizing your order" in ty2
    assert "location.replace" in ty2               # webhook-race refresh
    assert "if (n >= 24) return;" in ty2           # capped


# ─── Vertical softening ──────────────────────────────────────────────

def test_ministry_store_says_resources():
    from store_page import render_store_page
    html = render_store_page(SLUG, _biz(type="ministry"), ITEMS, SS)
    assert "Resources" in html
    assert "— Store</title>" not in html
    consultant = render_store_page(SLUG, _biz(), ITEMS, SS)
    assert "— Store</title>" in consultant
