"""Trends exports name each month, as the screen does (2026-11-03).

Kevin asked whether Giving trends was "for this year". It's the last 12
months, so the PDF and CSV say which twelve: "Dec 2025" ... "Nov 2026 (so
far)", a church's columns in its words, a 12-month total in the PDF, and
momentum naming the months it compares. Sample numbers only.
"""
from __future__ import annotations

import io
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import pdf_reports
import report_words as rw
import reports_router

KEYS = ["2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05",
        "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"]
INS = [0, 8200, 7600, 9100, 10400, 8800, 7900, 8600, 11200, 9700, 10100, 1400]
OUTS = [0, 6100, 6900, 7200, 6800, 9400, 7100, 7700, 8300, 7900, 8800, 650]
TRENDS = {
    "ok": True, "report": "trends", "as_of": "2026-11-03",
    "monthly": [{"month": k, "revenue": i, "expenses": o, "net": i - o} for k, i, o in zip(KEYS, INS, OUTS)],
    "momentum": {"revenue_last3_avg": 10333.33, "revenue_prior3_avg": 8433.33, "revenue_change_pct": 22.5,
                 "expenses_last3_avg": 8333.33, "expenses_prior3_avg": 8066.67, "expenses_change_pct": -3.3},
    "seasonality": [],
}


@pytest.mark.parametrize("key, label", [
    ("2026-11", "Nov 2026"), ("2025-12", "Dec 2025"), ("2026-01-15", "Jan 2026"),
    ("2026-00", "2026-00"), ("2026-13", "2026-13"), ("soon", "soon"), (None, ""),
])
def test_month_label(key, label):
    assert rw.month_label(key) == label


def test_day_label():
    assert rw.day_label("2026-11-03") == "Nov 3, 2026"
    assert rw.day_label("2026-11") == "2026-11"


@pytest.mark.parametrize("keys, span", [
    (["2026-08", "2026-09", "2026-10"], "Aug–Oct"),
    (["2025-11", "2025-12", "2026-01"], "Nov 2025–Jan 2026"),
    (["2026-10"], "Oct 2026"),
    ([], ""),
])
def test_month_span(keys, span):
    assert rw.month_span(keys) == span


def test_the_csv_names_months_and_marks_this_one_so_far():
    rows = reports_router._csv_rows("trends", TRENDS, "church")
    assert rows[0] == ["Month", "Giving & income", "Spending", "Left over"]
    assert [r[0] for r in rows[1:]][:2] == ["Dec 2025", "Jan 2026"]
    assert rows[-1][0] == "Nov 2026 (so far)" and rows[-1][1:] == [1400, 650, 750]


def test_a_business_csv_keeps_its_words():
    rows = reports_router._csv_rows("trends", TRENDS, "business")
    assert rows[0] == ["Month", "Revenue", "Expenses", "Net"]
    assert rows[1][0] == "Dec 2025"
    assert reports_router._csv_rows("trends", TRENDS)[0] == rows[0]   # no voice: business


def test_a_nonprofit_reads_contributions():
    assert reports_router._csv_rows("trends", TRENDS, "nonprofit")[0][1] == "Contributions & income"


def test_the_pdf_header_says_which_twelve_months():
    assert reports_router._period_label("trends", TRENDS) == \
        "Last 12 months: Dec 2025 – Nov 2026 (as of Nov 3, 2026)"
    # Other reports keep their header.
    assert reports_router._period_label("balance_sheet", {"as_of": "2026-11-03"}) == "As of 2026-11-03"


def _pdf_text(voice):
    pypdf = pytest.importorskip("pypdf")
    meta = pdf_reports.build_meta(business_name="Sample Church", settings={},
                                  report_title=rw.title("trends", "Trends", voice),
                                  period_label=reports_router._period_label("trends", TRENDS))
    meta["voice"] = voice
    pdf = pdf_reports.render("trends", TRENDS, meta)
    return "\n".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)


def test_the_church_pdf_names_months_totals_and_momentum():
    text = _pdf_text("church")
    for want in ("Dec 2025", "Jan 2026", "Nov 2026 (so far)", "Giving & income", "Spending",
                 "Left over", "12 months", "$93,000.00", "MOMENTUM", "AUG", "OCT", "MAY", "JUL",
                 "up 22.5%", "down 3.3%", "Nov isn't in it yet"):
        assert want in text, want
    assert "2026-11" not in text and "2025-12" not in text and "TRAILING" not in text


def test_the_business_pdf_keeps_its_words():
    text = _pdf_text("business")
    assert "Revenue" in text and "Expenses" in text and "Nov 2026 (so far)" in text
    assert "Giving & income" not in text


def test_an_empty_trends_pdf_still_renders():
    meta = pdf_reports.build_meta(business_name="Sample", settings={}, report_title="Trends", period_label="")
    meta["voice"] = "church"
    assert pdf_reports.render("trends", {"report": "trends", "monthly": [], "momentum": {}}, meta)[:4] == b"%PDF"
