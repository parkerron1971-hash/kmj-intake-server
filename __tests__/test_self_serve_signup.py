"""The doors open (2026-08-24).

Until now three separate gates stood between a visitor and a paid
subscription, and only the third one was visible:

  1. the marketing site sold a PRIVATE BETA — every button said "Apply
     for Access" and led to a lead form, never to a checkout;
  2. `launch_access.invite_only()` defaulted ON, so business creation
     returned 403 invite_only to anyone without a token;
  3. the app's own sign-up screen routed "Create account" to a waitlist
     (fixed in the solutionist-studio repo, not here).

These tests hold the first two open, and hold the one number the whole
promise rests on — the trial length — identical on the page and on the
subscription. A site that says 7 days while checkout grants 14 is not a
copy bug; it is the first thing a customer disputes.
"""
from __future__ import annotations

import os
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import launch_access  # noqa: E402
import marketing_pages as mp  # noqa: E402
import stripe_billing as sb  # noqa: E402


PAGES = {
    "/": mp.render_home,
    "/features": mp.render_features,
    "/compare": mp.render_compare,
    "/faq": mp.render_faq,
    "/about": mp.render_about,
    "/get-started": mp.render_get_started,
}

BETA_LANGUAGE = ["private beta", "Private beta", "Apply for Access",
                 "apply for access", "beta pricing", "Beta pricing"]


# ─── 1. The site sells a subscription ────────────────────────────────

@pytest.mark.parametrize("path", sorted(PAGES))
def test_no_page_still_says_beta(path):
    html = PAGES[path]()
    for phrase in BETA_LANGUAGE:
        assert phrase not in html, f"{path} still says {phrase!r}"


@pytest.mark.parametrize("path", sorted(PAGES))
def test_every_page_has_a_door_to_the_trial(path):
    """Not one page may be a dead end: whatever a visitor is reading,
    the way in is on it."""
    assert 'href="/start' in PAGES[path]()


@pytest.mark.parametrize("path", sorted(PAGES))
def test_no_token_survives_into_the_page(path):
    """`__TRIAL_FREE__` renders through the shell like the contact
    sentinel does. A page bypassing _render_shell would ship the raw
    token to a customer."""
    html = PAGES[path]()
    assert mp.TRIAL_TOKEN not in html
    assert mp.CONTACT_TOKEN not in html


def test_each_price_card_opens_its_own_tier():
    html = mp._price_cards_html()
    for plan in ("starter", "professional", "practice"):
        assert f'href="/start?plan={plan}"' in html


def test_the_form_is_a_conversation_not_a_gate():
    """/get-started keeps the lead form — it feeds lead_admin, the Meta
    CAPI Lead event and attribution — but it stopped being the only way
    in, so it must not read like an application."""
    html = mp.render_get_started()
    assert 'id="lead-form"' in html          # still there
    assert 'href="/start"' in html           # no longer the only door
    assert "Apply" not in html


# ─── 2. The trial is one number, in two places ───────────────────────

def test_the_page_quotes_what_checkout_actually_grants(monkeypatch):
    class _U:
        id, email = "u1", "e@example.com"

    for days in ("7", "14", "30"):
        monkeypatch.setenv("BILLING_TRIAL_DAYS", days)
        granted = sb._subscription_data({"id": "b1"}, _U())["trial_period_days"]
        assert granted == int(days)
        assert mp._trial_free_phrase() == f"{days} days free"
        assert f"{days} days free" in mp.render_home()


def test_seven_days_is_the_default(monkeypatch):
    class _U:
        id, email = "u1", "e@example.com"

    monkeypatch.delenv("BILLING_TRIAL_DAYS", raising=False)
    assert mp._trial_days() == 7
    assert sb._subscription_data({"id": "b1"}, _U())["trial_period_days"] == 7


def test_a_trial_of_zero_does_not_render_as_zero_days_free(monkeypatch):
    """Turning the trial off is a supported setting; the copy has to
    survive it rather than promise '0 days free'."""
    monkeypatch.setenv("BILLING_TRIAL_DAYS", "0")
    assert "0 days" not in mp._trial_free_phrase()
    assert "days free" not in mp.render_home()


def test_a_junk_trial_setting_falls_back_rather_than_crashing(monkeypatch):
    monkeypatch.setenv("BILLING_TRIAL_DAYS", "soon")
    assert mp._trial_days() == 7


# ─── 3. The launch gate is open, and still closable ──────────────────

def test_invite_only_is_off_by_default(monkeypatch):
    monkeypatch.delenv("LAUNCH_INVITE_ONLY", raising=False)
    assert launch_access.invite_only() is False


def test_the_kill_switch_still_closes_the_doors(monkeypatch):
    """The flip has to be reversible from Railway alone — no deploy."""
    monkeypatch.setenv("LAUNCH_INVITE_ONLY", "on")
    assert launch_access.invite_only() is True


# ─── 4. /start — the one door, and what it carries ───────────────────

@pytest.fixture(scope="module")
def client():
    os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
    import kmj_intake_automation
    return TestClient(kmj_intake_automation.app, follow_redirects=False)


HOST = {"host": "mysolutionist.app"}


def test_start_sends_you_to_the_app(client):
    r = client.get("/start", headers=HOST)
    assert r.status_code == 302
    assert r.headers["location"] == "https://system.mysolutionist.app/"


def test_start_carries_the_campaign_across_the_origin_hop(client):
    """An ad landing on mysolutionist.app used to lose its utm tags at
    the border — the app reads its OWN url, and sessionStorage does not
    cross origins. This is the only reason /start exists as a redirect
    instead of a plain link."""
    r = client.get("/start?utm_source=meta&utm_campaign=aug&gclid=xyz", headers=HOST)
    loc = r.headers["location"]
    assert "utm_source=meta" in loc and "utm_campaign=aug" in loc and "gclid=xyz" in loc


def test_start_carries_which_price_was_clicked(client):
    loc = client.get("/start?plan=professional", headers=HOST).headers["location"]
    assert "plan=professional" in loc


def test_start_forwards_nothing_it_was_not_asked_to(client):
    """The query string is attacker-controlled and lands in a redirect
    Location. Only the campaign whitelist and a real tier key ride."""
    loc = client.get("/start?plan=evil&next=//example.com&x=1&utm_source=ok",
                     headers=HOST).headers["location"]
    assert loc.startswith("https://system.mysolutionist.app/")
    assert "utm_source=ok" in loc
    for leak in ("plan=evil", "example.com", "x=1", "next="):
        assert leak not in loc


def test_start_is_not_stolen_from_a_practitioner_site(client, monkeypatch):
    """On a practitioner's own domain /start is THEIR page — the same
    rule /login already follows. Without this, publishing a /start page
    on your own site would silently bounce your visitors to OUR signup.

    The practitioner branch reads business_sites, so the site lookup is
    stubbed: what is under test is which branch the host picks, not
    what the renderer returns."""
    import public_site
    seen = {}

    async def _fake_site(request, renderer):
        seen["host"] = public_site.public_host(request)
        from fastapi.responses import HTMLResponse
        return HTMLResponse("<h1>their page</h1>")

    monkeypatch.setattr(public_site, "_platform_page_or_site", _fake_site)
    r = client.get("/start", headers={"host": "somebarber.com"})
    assert seen.get("host") == "somebarber.com", "took the platform branch"
    assert r.status_code == 200
    assert "system.mysolutionist.app" not in (r.headers.get("location") or "")


def test_start_still_redirects_on_the_platform_host_with_that_stub(client, monkeypatch):
    """Guards the test above: prove the stub would have been hit if the
    host branch were wrong, so a passing assertion means something."""
    import public_site
    called = []

    async def _fake_site(request, renderer):
        called.append(1)
        from fastapi.responses import HTMLResponse
        return HTMLResponse("")

    monkeypatch.setattr(public_site, "_platform_page_or_site", _fake_site)
    r = client.get("/start", headers=HOST)
    assert not called, "platform host must not fall to the site renderer"
    assert r.status_code == 302


# ─── 5. One switch, both repos ───────────────────────────────────────
# The app's front door is in a different repo and a different deploy.
# Without a public read of this flag, LAUNCH_INVITE_ONLY would only be
# half a kill switch: the server would refuse business creation while
# the app kept cheerfully offering signup.

def test_open_is_public(client):
    r = client.get("/access/open")
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["ok"] is True
    assert set(body) == {"ok", "invite_only", "trial_days"}


def test_open_reports_the_doors(client, monkeypatch):
    monkeypatch.delenv("LAUNCH_INVITE_ONLY", raising=False)
    assert client.get("/access/open").json()["invite_only"] is False
    monkeypatch.setenv("LAUNCH_INVITE_ONLY", "on")
    assert client.get("/access/open").json()["invite_only"] is True


def test_open_quotes_the_same_trial_as_checkout(client, monkeypatch):
    class _U:
        id, email = "u1", "e@example.com"

    monkeypatch.setenv("BILLING_TRIAL_DAYS", "21")
    assert client.get("/access/open").json()["trial_days"] == 21
    assert sb._subscription_data({"id": "b1"}, _U())["trial_period_days"] == 21


def test_open_leaks_nothing_about_who_is_asking(client):
    """It is unauthenticated, so it must answer with policy only — no
    invite tokens, no counts, no emails."""
    body = client.get("/access/open").text.lower()
    for leak in ("token", "email", "seats", "grandfather", "waitlist"):
        assert leak not in body
