"""The privacy policy names every outside company that receives business or
customer data, says how Chief learns, and says the Service is not for health
records (2026-10-12).

The list was built from the code and the production settings on 2026-10-12.
When a new provider is wired in, add it to the policy and to PROCESSORS here.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import legal_content

PROCESSORS = [
    "Anthropic", "OpenAI", "ElevenLabs", "OpenRouter", "AI Gateway",
    "Supabase", "Railway", "Vercel", "Twilio", "Resend", "Amazon Web Services",
    "Stripe", "Plaid", "Intuit", "Google", "Meta", "Cloudflare", "DocuSeal",
    "LiveKit", "Post for Me", "Square", "Sentry", "Hedera", "Bitcoin",
]


@pytest.fixture(scope="module")
def privacy():
    return legal_content.render_privacy_html()


@pytest.mark.parametrize("name", PROCESSORS)
def test_every_processor_is_named(privacy, name):
    assert name in privacy


def test_it_says_how_chief_learns(privacy):
    assert "How Chief learns" in privacy
    assert "We do not train AI models on your data" in privacy
    assert "at least three separate" in privacy
    assert "law practices start with it off" in privacy


def test_it_says_the_service_is_not_for_health_records(privacy):
    assert "not designed for protected health information" in privacy
    terms = legal_content.render_terms_html()
    assert "not designed for protected" in terms and "business associate" in terms


def test_the_google_limited_use_promise_is_intact(privacy):
    assert "gmail.readonly" in privacy
    assert "Limited Use" in privacy
    assert "never used for advertising, never sold" in privacy
