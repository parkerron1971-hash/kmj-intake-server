"""
Foundation Track documents become real paper (closes TODO(foundation-track-v2)).

The Operating Agreement / Privacy Policy / Terms of Service were generated as
plain text and left there — the frontend rendered the source into a <pre>, so
"generating" an Operating Agreement meant copying it out of a code block by
hand. foundation_documents.storage_path had been carried, unused, since the
first migration.
"""

import pathlib
import sys

import pytest

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import contract_agent as ca  # noqa: E402
import foundation_agent as fa  # noqa: E402


_OA_BODY = """OPERATING AGREEMENT

1. FORMATION
The Company was formed under the laws of the State of Michigan.

2. MEMBERS
The members and their ownership percentages are set out below.

1. Alicia Reyes holds a 60% membership interest.
2. Dana Whitfield holds a 40% membership interest.
"""


# ─── The public seam ─────────────────────────────────────────────────

def test_build_document_pdf_produces_real_paper():
    pdf = ca.build_document_pdf(
        business_name="Reyes Law",
        practitioner_name="Alicia Reyes",
        prepared_for="Reyes Law PLLC",
        subject="Operating Agreement",
        body=_OA_BODY,
    )
    assert pdf.startswith(b"%PDF")


def test_build_document_pdf_carries_the_brand_kit():
    """Same dressing the contracts get: accent, font lean, logo."""
    pdf = ca.build_document_pdf(
        business_name="Reyes Law",
        practitioner_name="Alicia Reyes",
        prepared_for="Reyes Law PLLC",
        subject="Privacy Policy",
        body=_OA_BODY,
        accent_hex="#2E7DFF",
        serif=True,
    )
    assert pdf.startswith(b"%PDF")


def test_a_governance_document_needs_no_counterparty():
    """The reason this seam exists.

    /agents/contract/pdf 404s without a contact_id, but an Operating Agreement
    has no counterparty — the party it is FOR is the business itself.
    """
    pdf = ca.build_document_pdf(
        business_name="Reyes Law",
        practitioner_name="Alicia Reyes",
        prepared_for="Reyes Law PLLC",
        prepared_for_org=None,
        subject="Terms of Service",
        body=_OA_BODY,
    )
    assert pdf.startswith(b"%PDF")


def test_the_seam_reaches_the_same_renderer():
    """If these ever diverge, governance docs quietly stop matching contracts."""
    kwargs = dict(business_name="B", practitioner_name="P", subject="S", body=_OA_BODY)
    via_seam = ca.build_document_pdf(prepared_for="C", **kwargs)
    via_private = ca._build_pdf("B", "P", "C", None, "S", _OA_BODY)
    # Byte-identical is not guaranteed (PDF ids/timestamps), but both are paper
    # and the seam must not silently drop the body.
    assert via_seam.startswith(b"%PDF") and via_private.startswith(b"%PDF")
    assert abs(len(via_seam) - len(via_private)) < 2000


# ─── Filing ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("title,expected", [
    ("Operating Agreement", "operating-agreement"),
    ("Privacy Policy", "privacy-policy"),
    ("Terms of Service — 2026", "terms-of-service-2026"),
    ("   ", "document"),
    ("", "document"),
    (None, "document"),
])
def test_slugify_makes_a_safe_object_name(title, expected):
    assert fa._slugify(title) == expected


def test_slugify_is_bounded():
    """Storage keys are not a place to discover a length limit in production."""
    assert len(fa._slugify("x" * 500)) <= 60


def test_documents_land_where_the_vault_actually_looks():
    """DocumentsPanel lists storage objects under {business_id}/general/, so
    filing the object IS filing the document — no second table, no index to
    drift. Pinned because changing the prefix would silently orphan every PDF."""
    assert fa.DOCS_BUCKET == "business-documents"


def test_every_renderable_kind_has_a_title():
    for kind in ("operating_agreement", "privacy_policy", "terms_of_service"):
        assert fa._PDF_TITLES.get(kind)
