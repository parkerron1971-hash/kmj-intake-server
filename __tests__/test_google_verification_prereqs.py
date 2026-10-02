"""What Google's reviewers need from the site before the Gmail connect
can be verified: a Search Console ownership file at the apex, and the
Limited Use disclosure in the privacy policy.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import legal_content  # noqa: E402
import public_site  # noqa: E402


@pytest.fixture
def apex(monkeypatch):
    """The request is for the platform's own domain, not a practitioner site."""
    async def _none(request):
        return None
    monkeypatch.setattr(public_site, "_site_response_or_none", _none)


def test_search_console_file_is_served_at_the_apex(apex):
    token = public_site.GOOGLE_SITE_VERIFICATION_TOKENS[0].replace("google", "", 1)
    resp = asyncio.run(public_site.public_google_site_verification(token, request=None))
    assert resp.status_code == 200
    assert resp.body.decode() == f"google-site-verification: google{token}.html\n"
    assert resp.media_type == "text/plain"


def test_unknown_verification_file_is_a_404_not_the_home_page(apex):
    with pytest.raises(HTTPException) as e:
        asyncio.run(public_site.public_google_site_verification("nobodyasked", request=None))
    assert e.value.status_code == 404


def test_practitioner_sites_are_untouched(monkeypatch):
    """A subdomain request never reaches the token check — the site
    renderer answers, exactly as it does for robots.txt."""
    sentinel = object()

    async def _site(request):
        return sentinel
    monkeypatch.setattr(public_site, "_site_response_or_none", _site)
    out = asyncio.run(public_site.public_google_site_verification("356ece60ef1330cd", request=None))
    assert out is sentinel


def test_privacy_policy_carries_the_limited_use_disclosure():
    src = pathlib.Path(legal_content.__file__).read_text(encoding="utf-8")
    assert "developers.google.com/terms/api-services-user-data-policy" in src
    assert "Limited Use" in src
    assert "gmail.readonly" in src
