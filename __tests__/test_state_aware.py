# __tests__/test_state_aware.py
#
# State awareness, both halves. Deterministic: full state names, venue
# units (Louisiana has Parishes, Alaska Boroughs), and the protected-
# disclosure safe harbor in every confidentiality home. Advisory: the
# state_notes pass is practitioner-facing metadata — fail-soft, never
# on the paper.

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import doc_templates as dt  # noqa: E402
import doc_templates_router as dtr  # noqa: E402


def test_venue_units():
    assert dt.venue_unit("LA") == "Parish"
    assert dt.venue_unit("Louisiana") == "Parish"
    assert dt.venue_unit("AK") == "Borough"
    assert dt.venue_unit("MI") == "County"
    assert dt.venue_unit("") == "County"


def test_venue_clause_renders_parish():
    t = dt.TEMPLATE_INDEX["engagement_letter"]
    v = dt.build_vars(t, {"scope": "s", "fee": "$1", "fee_model": "flat_fee",
                          "state": "LA", "venue_county": "Orleans"},
                      business_name="B", practitioner_name="P",
                      client_name="C", date_str="D")
    body = dt.assemble(t, v, {}, include_review_note=False)
    assert "laws of Louisiana" in body
    assert "Orleans Parish" in body and "Orleans County" not in body


def test_safe_harbor_in_every_confidentiality_home():
    harbor = "reporting suspected unlawful conduct"
    homes = 0
    for t in dt.TEMPLATES:
        for s in t["sections"]:
            if harbor in (s.get("text") or ""):
                homes += 1
    assert homes >= 3  # engagement letter, mutual block (creative), NDA


def test_state_notes_fail_soft_and_off_paper(monkeypatch):
    # no state → no call, no notes
    t = dt.TEMPLATE_INDEX["mutual_nda"]
    v = dt.build_vars(t, {"purpose": "eval"}, business_name="B",
                      practitioner_name="P", client_name="C", date_str="D")
    out = asyncio.run(dtr._state_notes({"id": "b1", "name": "B", "type": None},
                                       t, v, user_id="u"))
    assert out is None

    # state set but model down → soft None, never a raise
    monkeypatch.setattr(dtr.llm_call, "api_key", lambda: "k")

    async def boom(client, payload=None, **kw):
        raise RuntimeError("network down")
    monkeypatch.setattr(dtr.llm_call, "apost", boom)
    v2 = dt.build_vars(t, {"purpose": "eval", "state": "MI"},
                       business_name="B", practitioner_name="P",
                       client_name="C", date_str="D")
    out2 = asyncio.run(dtr._state_notes({"id": "b1", "name": "B", "type": None},
                                        t, v2, user_id="u"))
    assert out2 is None

    # healthy model → notes come back as metadata; the assembled body
    # never contains them
    class _Resp:
        status_code = 200
        def json(self):
            return {"model": "m", "usage": {},
                    "content": [{"type": "text",
                                 "text": "- Michigan caps late fees.\nConfirm with a Michigan attorney."}]}

    async def ok(client, payload=None, **kw):
        return _Resp()
    monkeypatch.setattr(dtr.llm_call, "apost", ok)

    async def silent_log(**kw):
        pass
    monkeypatch.setattr(dtr, "log_api_usage", silent_log)
    out3 = asyncio.run(dtr._state_notes({"id": "b1", "name": "B", "type": "creative"},
                                        t, v2, user_id="u"))
    assert out3 and "Michigan" in out3
    body = dt.assemble(t, v2, {}, include_review_note=False)
    assert "caps late fees" not in body
