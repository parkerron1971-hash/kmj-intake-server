# __tests__/test_branded_pdf.py
#
# Brand Studio -> the paper. Pins the line classifier (the old
# numbered-list regex rendered every contract clause as a BULLET), the
# brand-kit extraction, and a real reportlab build with logo + special
# characters.

import base64
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import contract_agent as ca  # noqa: E402


def test_classifier_knows_clauses_from_lists():
    assert ca._classify_line("1. SCOPE OF ENGAGEMENT") == ("heading", "1. SCOPE OF ENGAGEMENT")
    assert ca._classify_line("12. GENERAL TERMS")[0] == "heading"
    assert ca._classify_line("GENERAL TERMS") == ("heading", "GENERAL TERMS")
    assert ca._classify_line("ACCEPTED AND AGREED")[0] == "heading"
    # sentence-cased numbered lines are genuine list items
    assert ca._classify_line("1. We will deliver the goods promptly.")[0] == "numbered"
    assert ca._classify_line("(a) Entire agreement. This document is...")[0] == "subclause"
    assert ca._classify_line("- item one")[0] == "bullet"
    assert ca._classify_line("Plain paragraph.")[0] == "para"
    assert ca._classify_line("   ")[0] == "blank"
    assert ca._classify_line("## Heading") == ("heading", "Heading")


def test_brand_from_business_extraction():
    b = ca.brand_from_business({"settings": {"brand_kit": {
        "colors": {"primary": "2E7DFF"},
        "font_pair": {"heading": "Playfair Display"},
        "logo_url": "https://x/logo.png"}}})
    assert b == {"accent": "#2E7DFF", "serif": True, "logo_url": "https://x/logo.png"}
    # sans kit, hash-prefixed color, assets.primary fallback for the logo
    b2 = ca.brand_from_business({"settings": {"brand_kit": {
        "colors": {"primary": "#0B1D3A"},
        "font_pair": {"heading": "Inter Tight"},
        "assets": {"primary": "https://x/a.png"}}}})
    assert b2["accent"] == "#0B1D3A" and b2["serif"] is False
    assert b2["logo_url"] == "https://x/a.png"
    # no kit / junk color -> shipped defaults, never a crash
    assert ca.brand_from_business({})["accent"] == ca.PDF_ACCENT
    assert ca.brand_from_business({"settings": {"brand_kit": {
        "colors": {"primary": "tomato"}}}})["accent"] == ca.PDF_ACCENT


_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ"
    "DwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

_CONTRACT_BODY = (
    "Dear Dana,\n\nThank you.\n\n"
    "1. SCOPE OF ENGAGEMENT\n\nWork with A & B <fast>.\n\n"
    "2. GENERAL TERMS\n\n(a) Entire agreement. Everything.\n"
    "(b) Severability. The rest survives.\n\n"
    "ACCEPTED AND AGREED\n\nBy: ____________")


def test_build_pdf_branded_and_default():
    pdf = ca._build_pdf("Reyes Law", "Alicia Reyes", "Dana Whitfield", None,
                        "Engagement Letter", _CONTRACT_BODY,
                        accent_hex="#2E7DFF", serif=True, logo_bytes=_TINY_PNG)
    assert pdf.startswith(b"%PDF")
    # defaults + no logo + garbage logo bytes all still produce paper
    assert ca._build_pdf("B", "P", "C", None, "S", _CONTRACT_BODY).startswith(b"%PDF")
    assert ca._build_pdf("B", "P", "C", None, "S", _CONTRACT_BODY,
                         logo_bytes=b"not an image").startswith(b"%PDF")
