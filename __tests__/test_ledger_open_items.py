"""The three items disclosed as open when the ledger arc shipped.

Each was a place where a stated guarantee was not actually enforced:
the provable tier could skip silently, a read credential was written to
the server log, and the account export still returned record contents.

The lesson these tests are written against is the one from the previous
audit: a test that reads the SELECT LIST passes while the invariant is
broken. So where a behaviour can be exercised, it is exercised — the
export test runs the real endpoint through a fake PostgREST that
honours `select`, and asserts on the DOCUMENT, not on a string in the
source.
"""
from __future__ import annotations

import logging
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

_SQL = (_here.parent / "supabase"
        / "APPLY-2026-08-03-ledger-capture-fails-closed.sql").read_text(encoding="utf-8")


# ─── 1. The provable tier can no longer skip in silence ──────────────

def test_the_trigger_no_longer_swallows_everything():
    """`exception when others then null` is the whole bug: the business
    write commits, the ledger row does not, and nothing anywhere says
    so. No sequence gap (sequences are only assigned to rows that made
    it), no tombstone, no alert."""
    fn = _SQL.split("create or replace function public.audit_row_change")[1]
    handler = fn.split("exception when others then")[1].split("end $$")[0]
    assert "null;" not in handler.split("raise")[0], \
        "the handler must not swallow the failure"
    assert "raise exception" in handler, "a failed capture must fail the write"


def test_the_underlying_error_goes_to_the_log_not_the_caller():
    """The forensic detail has to survive the rollback, so it goes to
    the Postgres log. It must NOT go to the caller: that message crosses
    a tenant boundary."""
    fn = _SQL.split("create or replace function public.audit_row_change")[1]
    handler = fn.split("exception when others then")[1]
    assert "get stacked diagnostics" in handler
    assert "raise warning" in handler
    caller_msg = handler.split("raise exception")[1].split("using")[0]
    for internal in ("v_msg", "v_state", "sqlerrm", "sqlstate"):
        assert internal not in caller_msg, \
            f"{internal} must not reach the caller's error message"


def test_the_caller_is_told_nothing_was_written():
    """A write that fails is only safe if the person is sure it failed.
    'Try again' is wrong advice if a partial record survived."""
    fn = _SQL.split("create or replace function public.audit_row_change")[1]
    msg = fn.split("raise exception")[-1]
    assert "Nothing was written" in msg


def test_an_unattributable_row_is_refused_rather_than_skipped():
    """All eight audited tables declare business_id NOT NULL, so this
    branch is unreachable today. It was a silent `return` — meaning the
    first table attached with a nullable tenant would have gone quietly
    unrecorded. Failing at attach time is the cheap moment to find out."""
    fn = _SQL.split("create or replace function public.audit_row_change")[1]
    branch = fn.split("if v_biz is null then")[1].split("end if;")[0]
    assert "raise exception" in branch
    assert "return" not in branch


def test_the_cost_of_failing_closed_is_written_down():
    """audit_log is now on the critical path for eight tables. That is a
    real trade and the file has to say so, or the next person removes
    the raise to fix an outage without knowing what they are removing."""
    # Un-wrap first. A comment block is hard-wrapped at 72 columns, so a
    # raw substring search here is a coin flip on where the line broke —
    # exactly the brittle-prose assertion that has bitten this suite
    # before.
    head = " ".join(
        _SQL.split("create or replace function")[0].replace("--", " ").split())
    assert "critical path" in head
    assert "FAIL CLOSED" in head
    assert "deliberate trade" in head


# ─── 2. The credential stops appearing in the access log ─────────────

def test_the_audit_token_is_removed_from_a_path():
    import access_log_redaction as alr
    out = alr.redact("/public/audit/eyJzY29wZSI6ImxlZGdlciJ9.c2lnbmF0dXJl")
    assert "eyJzY29wZSI6ImxlZGdlciJ9" not in out
    assert out == "/public/audit/<redacted>"


def test_the_export_suffix_survives_but_the_token_does_not():
    """The log stays useful — you can still count auditor reads and see
    which ones exported — while the secret is gone."""
    import access_log_redaction as alr
    assert alr.redact("/public/audit/TOKEN123/export") == \
        "/public/audit/<redacted>/export"


def test_the_store_download_token_goes_too():
    """Same class, same fix: the middle segment is the credential, the
    order and offering ids are not."""
    import access_log_redaction as alr
    assert alr.redact("/public/store/download/ord_1/SECRET/off_2") == \
        "/public/store/download/ord_1/<redacted>/off_2"


def test_ordinary_paths_are_untouched():
    import access_log_redaction as alr
    for path in ("/audit", "/public/site/acme", "/health", "/audit/verify"):
        assert alr.redact(path) == path


def test_redaction_is_idempotent():
    """install() attaches the filter in two places on purpose; a record
    can pass through twice."""
    import access_log_redaction as alr
    once = alr.redact("/public/audit/TOKEN")
    assert alr.redact(once) == once


def test_the_filter_scrubs_uvicorn_style_args_not_just_the_message():
    """uvicorn logs the access line as a format string plus an args
    tuple, so at filter time the path is an ARG and the message is still
    '%s - "%s %s HTTP/%s" %d'. A filter that only rewrote record.msg
    would pass every real access line straight through."""
    import access_log_redaction as alr
    rec = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", "/public/audit/SECRETTOKEN", "1.1", 200),
        None)
    alr.RedactCredentialPaths().filter(rec)
    assert "SECRETTOKEN" not in rec.getMessage()
    assert "<redacted>" in rec.getMessage()
    # The rest of the line still has to be readable.
    assert "1.2.3.4:5" in rec.getMessage() and "200" in rec.getMessage()


def test_the_filter_never_drops_a_record_even_on_bad_input():
    """A logging filter that raises can take out the handler and with it
    every log line the process would have written."""
    import access_log_redaction as alr
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "m", None, None)
    rec.args = object()          # not a tuple, not a dict
    assert alr.RedactCredentialPaths().filter(rec) is True


def test_install_is_idempotent_and_reaches_the_access_logger():
    import access_log_redaction as alr
    alr.install()
    alr.install()
    filters = logging.getLogger("uvicorn.access").filters
    hits = [f for f in filters if isinstance(f, alr.RedactCredentialPaths)]
    assert len(hits) == 1


def test_install_runs_at_import_and_again_at_startup():
    """Two hooks, because uvicorn's logging dictConfig REPLACES a
    logger's filter list. Which one lands last depends on start order,
    and a security control whose failure mode is silence does not get to
    depend on that."""
    src = (_here.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert src.count("_install_log_redaction()") >= 2
    startup = src.split("async def startup():")[1][:900]
    assert "_install_log_redaction()" in startup


def test_sentry_cannot_ship_a_live_audit_link():
    """send_default_pii=False withholds headers and cookies but not the
    request URL, and for these routes the URL is the credential."""
    import access_log_redaction as alr
    event = {"request": {"url": "https://x/public/audit/SECRET",
                         "query_string": ""},
             "transaction": "/public/audit/SECRET"}
    out = alr.scrub_sentry_event(event)
    assert "SECRET" not in out["request"]["url"]
    assert "SECRET" not in out["transaction"]

    src = (_here.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert "before_send=scrub_sentry_event" in src


# ─── 3. The account export stops returning record contents ───────────

class _FakePostgrest:
    """Honours `select` the way PostgREST does, so the assertion can be
    made against the returned DOCUMENT rather than against the query
    string we happened to send."""

    def __init__(self):
        self.rows = {
            "businesses": [{"id": "b1", "owner_id": "u1", "name": "Practice"}],
            "audit_log": [{
                "id": "a1", "business_id": "b1", "verb": "db:contacts_update",
                "actor_type": "user", "actor_id": "u1", "ok": True,
                "error": None, "summary": "Update on contacts",
                "source": "db_trigger", "created_at": "2026-08-03T00:00:00Z",
                "target_type": "contacts", "target_id": "c1", "sequence": 7,
                "authorized_by": "rls", "subject_refs": [], "verb_registered": True,
                "prev_hash": "aa", "row_hash": "bb", "redacted_at": None,
                # The two that must never come back.
                "payload": {"after": {"name": "Jane Doe",
                                      "email": "jane@example.com",
                                      "notes": "panic attacks, weekly"}},
                "result": {"ok": True},
            }],
            "contacts": [{"id": "c1", "business_id": "b1", "name": "Jane Doe"}],
        }

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        table = url.rsplit("/", 1)[-1]
        rows = self.rows.get(table, [])
        sel = (params or {}).get("select", "*")
        if sel != "*":
            keep = sel.split(",")
            rows = [{k: v for k, v in r.items() if k in keep} for r in rows]
        return type("R", (), {"status_code": 200, "json": lambda self_: rows,
                              "text": ""})()


@pytest.fixture
def exported(monkeypatch):
    import account_lifecycle as al
    fake = _FakePostgrest()
    monkeypatch.setattr(al.httpx, "AsyncClient", lambda **kw: fake)
    monkeypatch.setattr(al, "BUSINESS_CHILD_TABLES", ["contacts", "audit_log"])
    import asyncio
    user = type("U", (), {"id": "u1", "email": "u@x.com"})()
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        al.export_account(user))


def test_the_export_document_carries_no_record_contents(exported):
    """THE test. The previous version of this invariant was pinned by
    checking a select list, and it passed while contents leaked through
    a different column. So: run the endpoint, read the answer."""
    rows = exported["businesses"][0]["tables"]["audit_log"]
    assert rows, "the ledger should still be exported"
    for row in rows:
        assert "payload" not in row
        assert "result" not in row
    assert "panic attacks" not in str(exported), \
        "no record contents anywhere in the document"


def test_the_export_still_carries_the_chain(exported):
    """Portability is the point: the practitioner should be able to hand
    this file to someone who can verify the chain without us."""
    row = exported["businesses"][0]["tables"]["audit_log"][0]
    for col in ("sequence", "prev_hash", "row_hash", "verb", "created_at"):
        assert col in row


def test_the_underlying_tables_are_still_whole(exported):
    """Nothing is actually lost by dropping payload: it was a copy of
    rows that travel in the same document under their own names."""
    assert exported["businesses"][0]["tables"]["contacts"][0]["name"] == "Jane Doe"


def test_the_export_reads_through_the_named_constant():
    """One place to widen, so a column cannot be added for the export
    and forgotten on the auditor link."""
    import account_lifecycle as al
    from audit_log import LEDGER_EXPORT_SELECT, LEDGER_SELECT
    assert al._TABLE_SELECT["audit_log"] is LEDGER_EXPORT_SELECT
    assert LEDGER_EXPORT_SELECT.startswith(LEDGER_SELECT)
    for banned in ("payload", "result"):
        assert banned not in LEDGER_EXPORT_SELECT
