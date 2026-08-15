"""Prefilling the OFFICIAL W-9 — and refusing to ship a blank that looks filled.

WHY THIS FORM AND NOT THE OTHERS. A W-9 never goes to the IRS; it goes
to the funder or payer who asked for it, so filling it in and handing it
over IS the workflow. Form 990/990-PF must be e-filed (Taxpayer First
Act) and Forms 1023/1024/1024-A only through Pay.gov, so a downloadable
filled PDF would not be filable — those get a link, never a download.

THE FAILURE THIS FILE EXISTS FOR. The form's field names are opaque
(f1_01 … f1_15) and unstable across revisions, and Line 3a is one field
with seven kid widgets that each have their OWN on-state — writing "/1"
to the Other box leaves it "/Off" while reporting success. A fill that
silently writes nothing returns a pristine blank the practitioner signs
and sends to a funder.

That is not hypothetical: it happened while building this, and the
readback is what caught it. So the tests below care far more about
refusing than about succeeding.

No test here touches the network — the blank is a fixture built locally,
so CI never depends on irs.gov being up.
"""
from __future__ import annotations

import io
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import irs_forms

PROFILE = {
    "legal_name": "The Blind Divine, Inc.",
    "ein": "87-1234567",
    "address_line1": "118 W Main St",
    "address_line2": "Suite 4",
    "address_city": "Madison",
    "address_state": "WI",
    "address_zip": "53703",
    "entity_type": "nonprofit",
}


def _acroform(names_and_types) -> bytes:
    """A real AcroForm carrying the given field names.

    Built by hand rather than by committing a copy of the IRS form: a
    committed blank goes stale the moment the IRS revises it, and one of
    the tests below asserts no form PDF is ever checked in.
    """
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject, DictionaryObject, NameObject, NumberObject,
        TextStringObject,
    )

    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    page = w.pages[0]

    fields = ArrayObject()
    annots = ArrayObject()
    for name, ftype in names_and_types:
        d = DictionaryObject()
        d[NameObject("/Type")] = NameObject("/Annot")
        d[NameObject("/Subtype")] = NameObject("/Widget")
        d[NameObject("/FT")] = NameObject(ftype)
        d[NameObject("/T")] = TextStringObject(name)
        d[NameObject("/V")] = (NameObject("/Off") if ftype == "/Btn"
                               else TextStringObject(""))
        d[NameObject("/Rect")] = ArrayObject(
            [NumberObject(10), NumberObject(10), NumberObject(200), NumberObject(30)])
        ref = w._add_object(d)
        fields.append(ref)
        annots.append(ref)

    page[NameObject("/Annots")] = annots
    acro = DictionaryObject()
    acro[NameObject("/Fields")] = fields
    w._root_object[NameObject("/AcroForm")] = w._add_object(acro)

    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _blank_w9() -> bytes:
    """A stand-in carrying exactly the real form's field names."""
    return _acroform([
        (name, "/Btn" if key == "other_box" else "/Tx")
        for key, name in irs_forms.W9_FIELDS.items()
    ])


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Nothing in this file may reach irs.gov.

    Guarded at the SOCKET rather than at _fetch, so _fetch's own error
    handling stays testable — stubbing _fetch would have made the
    "irs.gov returned HTML" case untestable."""
    class _Boom:
        def __init__(self, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k):
            raise AssertionError("a test tried to reach the network")
    import httpx
    monkeypatch.setattr(httpx, "Client", _Boom)
    irs_forms._cache.clear()


# ── The values we choose to write ────────────────────────────────────

def test_only_recorded_facts_are_filled():
    v = irs_forms.w9_values(PROFILE, business_name="The Blind Divine")
    assert v["name"] == "The Blind Divine, Inc."
    assert v["address"] == "118 W Main St Suite 4"
    assert v["city_state_zip"] == "Madison, WI 53703"
    assert v["ein_prefix"] == "87" and v["ein_rest"] == "1234567"


def test_line_4_codes_and_the_signature_are_never_filled():
    """A wrong exempt-payee code on a SIGNED form is the organisation's
    problem. We do not guess at determinations, and we never sign."""
    v = irs_forms.w9_values(PROFILE)
    for never in ("exempt_code", "fatca", "signature", "date", "ssn"):
        assert never not in v
    # and the map itself offers no such field to fill
    assert not any(k in irs_forms.W9_FIELDS
                   for k in ("signature", "date", "exempt_code"))


def test_line_2_stays_empty_when_the_trading_name_matches():
    """Repeating Line 1 into Line 2 is a common way to make a form wrong."""
    v = irs_forms.w9_values(PROFILE, business_name="the blind divine, inc.")
    assert "business_name" not in v


def test_line_2_is_filled_when_the_dba_differs():
    v = irs_forms.w9_values(PROFILE, business_name="The Blind Divine")
    assert v["business_name"] == "The Blind Divine"


def test_a_partial_ein_is_left_blank_entirely():
    """A half-written EIN looks answered. Empty is honest; wrong is not."""
    for bad in ("87-123", "", None, "not-an-ein", "87-12345678"):
        v = irs_forms.w9_values({**PROFILE, "ein": bad})
        assert "ein_prefix" not in v and "ein_rest" not in v, bad


def test_a_nonprofit_gets_other_with_the_correct_on_state():
    """Line 3a's kids each have their own on-state — /7 is Other.

    Writing /1 here leaves the box /Off while looking like it worked."""
    v = irs_forms.w9_values(PROFILE)
    assert v["other_box"] == irs_forms.W9_OTHER_ON == "/7"
    assert "501(c)(3)" in v["other_desc"]


def test_a_non_nonprofit_gets_no_classification_at_all():
    """We restate what they told us; we do not classify anyone."""
    v = irs_forms.w9_values({**PROFILE, "entity_type": "llc"})
    assert "other_box" not in v and "other_desc" not in v


def test_an_empty_profile_fills_nothing():
    assert irs_forms.w9_values({}) == {}


# ── Refusing, which matters more than succeeding ─────────────────────

def test_it_refuses_when_there_is_nothing_to_fill(monkeypatch):
    monkeypatch.setattr(irs_forms, "_fetch", lambda url: _blank_w9())
    with pytest.raises(irs_forms.FormUnavailable):
        irs_forms.fill_w9({})


def test_a_renamed_field_refuses_instead_of_returning_a_blank(monkeypatch):
    """The revision-change case. A form whose boxes silently did not take
    is the worst outcome — it looks answered all the way to the funder."""
    renamed = _acroform([("somethingElse[0]", "/Tx")])
    monkeypatch.setattr(irs_forms, "_fetch", lambda url: renamed)

    with pytest.raises(irs_forms.FormUnavailable) as e:
        irs_forms.fill_w9(PROFILE)
    assert "changed shape" in str(e.value)


def test_a_value_that_does_not_take_refuses(monkeypatch):
    """Fields all present, write reports success, values do not land.

    Exactly the checkbox bug, generalised: verified by READING BACK
    rather than by trusting the writer."""
    monkeypatch.setattr(irs_forms, "_fetch", lambda url: _blank_w9())

    import pypdf
    real = pypdf.PdfWriter.update_page_form_field_values

    def _noop(self, page, fields, *a, **k):
        return None  # accept the call, write nothing

    monkeypatch.setattr(pypdf.PdfWriter, "update_page_form_field_values", _noop)
    try:
        with pytest.raises(irs_forms.FormUnavailable) as e:
            irs_forms.fill_w9(PROFILE)
        assert "did not accept" in str(e.value)
    finally:
        monkeypatch.setattr(pypdf.PdfWriter, "update_page_form_field_values", real)


def test_a_non_pdf_response_refuses(monkeypatch):
    import httpx

    class _R:
        status_code = 200
        content = b"<html>service unavailable</html>"

    monkeypatch.setattr(irs_forms, "_cache", {})
    monkeypatch.setattr(httpx, "Client", lambda **k: _FakeClient(_R()))
    with pytest.raises(irs_forms.FormUnavailable) as e:
        irs_forms._fetch(irs_forms.W9_URL)
    assert "did not return a PDF" in str(e.value)


class _FakeClient:
    def __init__(self, resp): self._r = resp
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get(self, *a, **k): return self._r


# ── The blank is fetched, never committed ────────────────────────────

def test_the_form_is_fetched_from_the_stable_irs_path():
    """Bundling a copy goes stale — a requester can reject a superseded
    revision, and this path always serves the current one."""
    assert irs_forms.W9_URL == "https://www.irs.gov/pub/irs-pdf/fw9.pdf"
    assert "irs-dft" not in irs_forms.W9_URL, "that is a DRAFT form, not for filing"


def test_no_form_pdf_is_committed_to_the_repo():
    root = pathlib.Path(__file__).resolve().parent.parent
    stray = [p.name for p in root.glob("*.pdf")] + [p.name for p in root.glob("fw9*")]
    assert not stray, f"a form copy was committed and will go stale: {stray}"
