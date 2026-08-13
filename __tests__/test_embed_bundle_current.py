"""Site-builder audit follow-up (2026-08-13) — the shipped booking widget
must know about the features the backend serves it.

static/embed.js is a COMMITTED BUILD ARTIFACT, refreshed by a hand-copy
documented only in a comment (public_site.py, "Refresh procedure (until
we wire CI build-and-upload)"). Nothing enforced the copy, so it rotted:
the bundle served to every real visitor was built 2026-06-06, while the
source gained deposits, no-show fees, arrival windows, SMS consent and
tipping over the following two months.

The result was a practitioner configuring a deposit in BUILD that no
customer could ever be asked for. The backend would happily accept
fields the shipped widget never sent.

This is the alarm for that. Each feature below is implemented in this
repo AND rendered by the widget source; if the bundle stops mentioning
one, the copy is stale again. It reads the artifact rather than trusting
the build, because trusting the build is precisely what failed.

When this fails, the fix is:
    1. in solutionist-studio:  npm run build:embed
    2. cp dist-embed/embed.js  kmj-intake-server/static/embed.js
    3. commit
"""
from __future__ import annotations

import pathlib

BUNDLE = pathlib.Path(__file__).resolve().parent.parent / "static" / "embed.js"

# marker -> what a visitor loses if the bundle predates it
REQUIRED = {
    "sms_consent": "the SMS-consent checkbox (consent recorded at booking)",
    "deposit_cents": "deposit-to-book (the deposit is never collected)",
    "no_show_fee_cents": "the no-show fee notice (card-on-file policy)",
    "arrival_window_min": "arrival windows (visitor sees exact times instead)",
    "book-anon": "anonymous booking submit — the widget's whole purpose",
    "config-anon": "widget config load — nothing renders without it",
}


def _bundle_text() -> str:
    assert BUNDLE.exists(), f"shipped widget missing at {BUNDLE}"
    return BUNDLE.read_text(encoding="utf-8", errors="ignore")


def test_bundle_is_present_and_substantial():
    text = _bundle_text()
    assert len(text) > 100_000, (
        "embed.js looks truncated — it is a full React bundle, not a stub")


def test_bundle_carries_every_feature_the_backend_serves():
    """The staleness alarm. A missing marker means the committed bundle
    predates a feature this repo already supports."""
    text = _bundle_text()
    missing = {m: why for m, why in REQUIRED.items() if m not in text}
    assert not missing, (
        "static/embed.js is STALE — rebuild it (npm run build:embed in "
        "solutionist-studio, copy dist-embed/embed.js here). Visitors are "
        "currently missing: "
        + "; ".join(f"{m} → {why}" for m, why in missing.items()))


def test_backend_still_implements_what_the_bundle_is_checked_against():
    """Keeps the alarm honest in the other direction. If a feature is
    dropped from the backend, this list should shrink with it rather
    than pinning the bundle to something no longer served — an assertion
    nobody can satisfy is as useless as no assertion."""
    root = pathlib.Path(__file__).resolve().parent.parent
    sources = [
        root / "booking_widget_router.py",
        root / "availability.py",
    ]
    blob = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in sources if p.exists())
    for marker in ("sms_consent", "deposit_cents", "no_show_fee_cents",
                   "arrival_window_min"):
        assert marker in blob, (
            f"{marker} is asserted against the bundle but no longer appears in "
            "the booking backend — drop it from REQUIRED or restore it")
