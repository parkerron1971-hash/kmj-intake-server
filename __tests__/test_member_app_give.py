"""Giving inside the member app (/my/give, Kevin's phone design
2026-10-14): the give page's own form in the app's look, and a gift made
there comes back to the app on the church address the member is on."""
import pytest

import giving_router as gr
import member_portal as mp


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    # Set per test and put back after: a module-level default would leak
    # into other files' collection (test_product_files_private decides at
    # import whether to call the live bucket).
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test")

BIZ = {"id": "b1", "name": "First Light", "type": "ministry", "stripe_account_id": "acct_123",
       "settings": {"brand_kit": {"colors": {"primary": "#0B2146"}},
                    "giving": {"enabled": True, "funds": ["General", "Building"]}}}
SITE = {"slug": "first-light", "site_config": {"custom_domain": "firstlight.org"}}
ME = {"id": "c1", "name": "Ana <Rivers>", "email": "ana@example.com"}


def test_a_gift_from_the_app_returns_only_to_the_churchs_own_addresses():
    cfg = {"custom_domain": "firstlight.org"}
    assert gr.app_return_base("first-light", cfg, "https://firstlight.org") == "https://firstlight.org"
    assert gr.app_return_base("first-light", cfg, "https://www.firstlight.org") == "https://www.firstlight.org"
    home = f"https://first-light.{gr.PUBLIC_DOMAIN}"
    assert gr.app_return_base("first-light", cfg, f"https://first-light.{gr.PUBLIC_DOMAIN}") == home
    assert gr.app_return_base("first-light", cfg, "https://evil.example") == home       # never a made-up host
    assert gr.app_return_base("first-light", {}, "https://firstlight.org") == home       # no domain set
    assert gr.app_return_base("first-light", None, "") == home


def test_the_app_give_screen_is_the_same_form_in_the_apps_look():
    page = mp.render_give(BIZ, SITE, ME)
    assert 'id="gv-form"' in page and "/public/giving/" in page                       # the same payment path
    assert 'href="/my"' in page and ">Give</h1>" in page and "--mb-fill:" in page        # the app's header and look
    assert 'value="Ana &lt;Rivers&gt;"' in page and 'value="ana@example.com"' in page   # filled in, escaped
    assert "var APP = true, PREVIEW = false, SITE = false" in page
    assert "return_to: APP ? 'app' : (SITE ? 'site' : undefined)" in page
    assert "won't charge" not in page


def test_the_owners_preview_never_charges():
    page = mp.render_give(BIZ, SITE, ME, preview=True)
    assert "PREVIEW = true" in page and "This is a preview, so nothing is charged." in page
    assert "won&#x27;t charge anything" in page or "won't charge anything" in page


def test_the_public_give_page_is_unchanged_for_everyone_else():
    page = gr.render_give_page(BIZ, "https://first-light.example/give", "first-light", api_origin="https://api.example")
    assert 'class="gv-header"' in page and "var APP = false, PREVIEW = false" in page
    assert 'value=""' in page and "--mb-fill" not in page


def test_every_give_button_in_the_app_opens_the_app_screen(monkeypatch):
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: True)
    page = mp._shell(BIZ, None, "Home", "<p>x</p>", tab="home", who=ME)
    assert 'class="mb-tab" href="/my/give"' in page and 'href="/give"' not in page      # Give is a tab
