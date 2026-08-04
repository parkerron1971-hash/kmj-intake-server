# __tests__/test_doc_intelligence.py
#
# Document Intelligence pass 1 — the /docintel surface. Pins the parts
# that carry the security and money weight: the tenant path check, the
# owner gate, the units gate being consulted, the extension → content
# block routing, JSON-parse armor, and the contact-timeline event.

import asyncio
import json
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import doc_intelligence_router as di  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


class _User:
    id = "owner1"
    email = "owner1@x.com"


class _Stranger:
    id = "intruder"
    email = "evil@x.com"


BIZ = "b1"


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    fb.rows("businesses").append({
        "id": BIZ, "owner_id": "owner1", "name": "Reyes Law",
        "business_type": "lawyer"})
    fb.rows("contacts").append({
        "id": "c9", "business_id": BIZ, "name": "Dana Whitfield"})
    return fb


@pytest.fixture
def wired(fake, monkeypatch):
    """Everything expensive faked: storage download, the model, the
    usage logger, the units gate. Returns a recorder dict."""
    rec = {"units": [], "usage": [], "payloads": []}

    monkeypatch.setattr(di.billing_limits, "require_units",
                        lambda biz: rec["units"].append(biz))

    async def fake_download(client, path):
        return b"%PDF-1.4 fake"
    monkeypatch.setattr(di, "_download", fake_download)

    class _Resp:
        status_code = 200
        def json(self):
            return {
                "model": "claude-sonnet-4-5",
                "usage": {"input_tokens": 11, "output_tokens": 22},
                "content": [{"type": "text", "text": json.dumps({
                    "document_type": "engagement letter",
                    "summary": "A two-page engagement letter.",
                    "parties": ["Reyes Law", "Dana Whitfield"],
                    "key_points": ["Flat fee"],
                    "dates": [{"date": "March 1, 2026", "label": "effective date"}],
                    "obligations": ["Client pays retainer within 10 days"],
                    "red_flags": [],
                    "verdict": "Mostly identical.",
                    "differences": [], "only_in_a": [], "only_in_b": [],
                })}],
            }

    async def fake_apost(client, payload=None, **kw):
        rec["payloads"].append(payload)
        return _Resp()
    monkeypatch.setattr(di.llm_call, "apost", fake_apost)
    monkeypatch.setattr(di.llm_call, "api_key", lambda: "k")

    async def fake_log(**kw):
        rec["usage"].append(kw)
    monkeypatch.setattr(di, "log_api_usage", fake_log)
    return rec


# ─── Pure helpers ────────────────────────────────────────────────────

def test_check_path_enforces_tenant_prefix():
    assert di._check_path(BIZ, f"{BIZ}/general/1-a.pdf") == f"{BIZ}/general/1-a.pdf"
    with pytest.raises(HTTPException) as e:
        di._check_path(BIZ, "b2/general/1-a.pdf")
    assert e.value.status_code == 403
    with pytest.raises(HTTPException):
        di._check_path(BIZ, f"{BIZ}/../b2/x.pdf")
    # leading slash is normalized, not rejected
    assert di._check_path(BIZ, f"/{BIZ}/general/a.pdf") == f"{BIZ}/general/a.pdf"


def test_content_block_routing():
    assert di._content_block("b/x.pdf", b"%PDF")["type"] == "document"
    assert di._content_block("b/x.png", b"\x89PNG")["type"] == "image"
    blk = di._content_block("b/1234567890123-notes.txt", "hi there".encode())
    assert blk["type"] == "text" and "notes.txt" in blk["text"] and "hi there" in blk["text"]
    with pytest.raises(HTTPException) as e:
        di._content_block("b/x.docx", b"PK")
    assert e.value.status_code == 415


def test_analyzable_and_names():
    assert di.analyzable("b/general/1-contract.pdf")
    assert di.analyzable("b/general/1-scan.jpeg")
    assert di.analyzable("b/general/1-notes.md")
    assert not di.analyzable("b/general/1-deck.pptx")
    assert di._filename("b/general/1722700000000-Lease Agreement.pdf") == "Lease Agreement.pdf"
    assert di._contact_id_from_path("b", "b/contacts/c9/1-x.pdf") == "c9"
    assert di._contact_id_from_path("b", "b/general/1-x.pdf") is None


def test_parse_json_armor():
    assert di._parse_json('{"a": 1}') == {"a": 1}
    assert di._parse_json('Here you go:\n```json\n{"a": 1}\n```\nEnjoy!') == {"a": 1}
    assert di._parse_json('prose before {"a": {"b": 2}} prose after') == {"a": {"b": 2}}
    with pytest.raises(HTTPException) as e:
        di._parse_json("I cannot help with that")
    assert e.value.status_code == 502


# ─── Route surface ───────────────────────────────────────────────────

def test_routes_exist_and_are_authed():
    from auth_supabase import require_user
    paths = {r.path for r in di.router.routes}
    assert "/docintel/analyze" in paths
    assert "/docintel/compare" in paths
    for r in di.router.routes:
        deps = [d.call for d in r.dependant.dependencies]
        assert require_user in deps, f"{r.path} is missing require_user"


# ─── Endpoints ───────────────────────────────────────────────────────

def test_analyze_happy_path_logs_units_usage_and_event(fake, wired):
    body = di.AnalyzeBody(business_id=BIZ,
                          path=f"{BIZ}/contacts/c9/1722700000000-engagement.pdf")
    out = asyncio.run(di.docintel_analyze(body, _User()))
    assert out["ok"] and out["mode"] == "summary"
    assert out["filename"] == "engagement.pdf"
    assert out["result"]["parties"] == ["Reyes Law", "Dana Whitfield"]
    # gates + metering consulted
    assert wired["units"] == [BIZ]
    assert wired["usage"] and wired["usage"][0]["business_id"] == BIZ
    assert wired["usage"][0]["task_type"] == "docintel_summary"
    # contact-scoped → timeline event
    events = fake.rows("events")
    assert len(events) == 1 and events[0]["event_type"] == "document_analyzed"
    assert events[0]["contact_id"] == "c9"
    # contact name reached the system prompt (context-aware analysis)
    sysmsg = wired["payloads"][0]["system"]
    assert "Dana Whitfield" in sysmsg and "Reyes Law" in sysmsg


def test_analyze_rejects_non_owner_and_bad_modes(fake, wired):
    body = di.AnalyzeBody(business_id=BIZ, path=f"{BIZ}/general/1-a.pdf")
    with pytest.raises(HTTPException) as e:
        asyncio.run(di.docintel_analyze(body, _Stranger()))
    assert e.value.status_code == 403

    bad = di.AnalyzeBody(business_id=BIZ, path=f"{BIZ}/general/1-a.pdf", mode="translate")
    with pytest.raises(HTTPException) as e:
        asyncio.run(di.docintel_analyze(bad, _User()))
    assert e.value.status_code == 400

    ask = di.AnalyzeBody(business_id=BIZ, path=f"{BIZ}/general/1-a.pdf", mode="ask")
    with pytest.raises(HTTPException) as e:
        asyncio.run(di.docintel_analyze(ask, _User()))
    assert e.value.status_code == 400
    # none of the failures consumed a unit
    assert wired["units"] == []


def test_analyze_ask_carries_question(fake, wired):
    body = di.AnalyzeBody(business_id=BIZ, path=f"{BIZ}/general/1-lease.pdf",
                          mode="ask", question="When can I terminate?")
    out = asyncio.run(di.docintel_analyze(body, _User()))
    assert out["ok"]
    content = wired["payloads"][0]["messages"][0]["content"]
    joined = " ".join(b.get("text", "") for b in content if b.get("type") == "text")
    assert "When can I terminate?" in joined
    # general (non-contact) docs write no timeline event
    assert fake.rows("events") == []


def test_compare_happy_and_same_path_rejected(fake, wired):
    body = di.CompareBody(business_id=BIZ,
                          path_a=f"{BIZ}/general/1722700000001-v1.pdf",
                          path_b=f"{BIZ}/general/1722700000002-v2.pdf")
    out = asyncio.run(di.docintel_compare(body, _User()))
    assert out["ok"] and out["mode"] == "compare"
    assert out["filename_a"] == "v1.pdf" and out["filename_b"] == "v2.pdf"
    assert "verdict" in out["result"]
    # both documents rode in the same message
    content = wired["payloads"][0]["messages"][0]["content"]
    assert sum(1 for b in content if b["type"] == "document") == 2

    same = di.CompareBody(business_id=BIZ,
                          path_a=f"{BIZ}/general/1-v1.pdf",
                          path_b=f"{BIZ}/general/1-v1.pdf")
    with pytest.raises(HTTPException) as e:
        asyncio.run(di.docintel_compare(same, _User()))
    assert e.value.status_code == 400


def test_analyze_503_without_api_key(fake, wired, monkeypatch):
    monkeypatch.setattr(di.llm_call, "api_key", lambda: "")
    body = di.AnalyzeBody(business_id=BIZ, path=f"{BIZ}/general/1-a.pdf")
    with pytest.raises(HTTPException) as e:
        asyncio.run(di.docintel_analyze(body, _User()))
    assert e.value.status_code == 503
