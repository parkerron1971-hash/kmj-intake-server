"""The document says who issued it.

The renderer already carried the Brand Studio logo, accent and font
lean — and then stopped. The header was a logo, a business name, a
practitioner name and a date. Nothing said where the business is, how
to reach it, or which page of a six-page policy you were holding.

That is fine for an emailed proposal and wrong for everything the
nonprofit work added. A conflict-of-interest policy is signed by each
board member and filed. A retention schedule is printed and kept. A
donation acknowledgment is handed to a donor's accountant. Every one of
those leaves the app as paper, and paper with no return address is not
a document from a business — it looks generated.

So: an address block opposite the name, and "Page 2 of 6" once there is
more than one page.
"""

import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import contract_agent as ca  # noqa: E402

_BIZ = {
    "id": "b1",
    "name": "Riverbend Community Trust",
    "settings": {"contact_email": "office@riverbend.org",
                 "site_url": "https://riverbend.org/"},
}
_IDENT = {
    "legal_name": "Riverbend Community Trust, Inc.",
    "ein": "84-1234567",
    "address_line1": "412 Grand River Avenue",
    "address_line2": "Suite 3",
    "address_city": "Lansing", "address_state": "MI", "address_zip": "48906",
    "phone": "(517) 555-0142",
}


def _text(pdf: bytes, page: int = 0) -> str:
    from pypdf import PdfReader
    import io
    return PdfReader(io.BytesIO(pdf)).pages[page].extract_text() or ""


def _pages(pdf: bytes) -> int:
    from pypdf import PdfReader
    import io
    return len(PdfReader(io.BytesIO(pdf)).pages)


def _doc(body: str, **kw) -> bytes:
    return ca.build_document_pdf(
        business_name="Riverbend Community Trust",
        practitioner_name="Dana Whitfield",
        prepared_for="Riverbend Community Trust, Inc.",
        subject="Conflict of Interest Policy", body=body, **kw)


# ── What goes in the block ───────────────────────────────────────────

def test_the_block_carries_address_phone_email_and_site():
    lines = ca.letterhead_lines(_BIZ, _IDENT)
    joined = " | ".join(lines)
    for expected in ("412 Grand River Avenue", "Lansing, MI 48906",
                     "(517) 555-0142", "office@riverbend.org", "riverbend.org"):
        assert expected in joined, expected


def test_a_suite_keeps_its_own_line():
    """Joined to the street it reads as part of the road name."""
    lines = ca.letterhead_lines(_BIZ, _IDENT)
    assert "Suite 3" in lines
    assert "412 Grand River Avenue" in lines


def test_the_site_loses_its_scheme():
    """A bare domain sits in an address block; `https://` reads as a URL
    someone pasted in."""
    lines = ca.letterhead_lines(_BIZ, _IDENT)
    assert "riverbend.org" in lines
    assert not any(x.startswith("http") for x in lines)


def test_the_ein_is_not_on_the_letterhead():
    """It belongs in the body of the documents that need it — a
    §170(f)(8) donation acknowledgment states it where a donor's
    accountant looks. On a proposal emailed to a prospect it is a tax ID
    disclosed for no reason.
    """
    assert "84-1234567" not in " ".join(ca.letterhead_lines(_BIZ, _IDENT))


def test_a_business_that_has_told_us_nothing_gets_no_block():
    """Not an empty box, not the word "None" — the header keeps the
    shape it had before there was a contact block at all."""
    assert ca.letterhead_lines({}, {}) == []
    assert ca.letterhead_lines({"settings": {}}, None) == []
    pdf = _doc("A line.", letterhead=[])
    assert pdf.startswith(b"%PDF")


# ── That it reaches the page ─────────────────────────────────────────

def test_the_block_renders_on_the_first_page():
    pdf = _doc("1. PURPOSE\nTo protect the organization's interest.",
               letterhead=ca.letterhead_lines(_BIZ, _IDENT))
    text = _text(pdf)
    for expected in ("412 Grand River Avenue", "Lansing, MI 48906",
                     "(517) 555-0142", "office@riverbend.org"):
        assert expected in text, expected


def test_the_block_survives_an_ampersand_in_an_address():
    """Every string here goes through Paragraph's inline-markup parser.
    A raw & is what crashes it."""
    ident = {**_IDENT, "address_line1": "1 Marsh & Fen Road"}
    pdf = _doc("A line.", letterhead=ca.letterhead_lines(_BIZ, ident))
    assert "Marsh & Fen" in _text(pdf)


# ── Pagination ───────────────────────────────────────────────────────

_LONG = "\n".join(f"{i}. SECTION {i}\n" + ("Body text for this section. " * 12)
                  for i in range(1, 14))


def test_a_multi_page_document_is_paginated():
    pdf = _doc(_LONG, letterhead=ca.letterhead_lines(_BIZ, _IDENT))
    n = _pages(pdf)
    assert n > 1, "the fixture stopped being long enough to page"
    assert "Page 1 of %d" % n in _text(pdf, 0)
    assert "Page %d of %d" % (n, n) in _text(pdf, n - 1)


def test_a_one_page_document_is_not():
    """"Page 1 of 1" on a single sheet is noise."""
    pdf = _doc("A single short line.", letterhead=ca.letterhead_lines(_BIZ, _IDENT))
    assert _pages(pdf) == 1
    assert "Page 1 of" not in _text(pdf)


def test_the_total_is_the_real_total():
    """A one-pass render can print "Page 3" but not "of 6" — the count
    isn't known until the story is laid out. Getting the total wrong is
    worse than having none, so assert the last page agrees with pypdf."""
    pdf = _doc(_LONG, letterhead=ca.letterhead_lines(_BIZ, _IDENT))
    n = _pages(pdf)
    assert f"of {n}" in _text(pdf, 0)
    assert f"of {n + 1}" not in _text(pdf, 0)


# ── Every renderer gets the same header ──────────────────────────────

def test_all_three_pdf_paths_pass_a_letterhead():
    """The queue's Download button, Chief's contract_pdf action and the
    Foundation Track renderer are three separate build calls. A header
    that appears on one and not the others is the drift nobody reports.
    """
    import inspect
    import chief_contract_actions as cca
    import foundation_agent as fa
    for fn in (ca.contract_pdf, cca.handle_contract_pdf, fa.render_document_pdf):
        src = inspect.getsource(fn)
        assert "letterhead_lines(" in src, fn.__name__
