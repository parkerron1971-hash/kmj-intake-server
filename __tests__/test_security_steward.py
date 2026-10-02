"""The Security steward reports what it finds, and never calls an unchecked area clean."""
from __future__ import annotations

import base64
import importlib.util
import json
import pathlib
from datetime import datetime, timedelta, timezone

_SPEC = importlib.util.spec_from_file_location(
    "security_steward",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "security_steward.py")
ss = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ss)

NOW = datetime(2026, 10, 5, 11, 0, tzinfo=timezone.utc)


def _jwt(role):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'HS256', 'typ': 'JWT'})}.{enc({'role': role, 'iss': 'supabase'})}.c2lnbmF0dXJlLXNpZ25hdHVyZQ"


def test_service_role_key_is_caught_and_anon_key_is_not():
    js = f'const a="{_jwt("anon")}";const b="{_jwt("service_role")}";'
    assert len(ss.service_keys_in(js)) == 1
    assert ss.service_keys_in(f'const a="{_jwt("anon")}"') == []


def test_bundle_scan_follows_one_hop_of_chunks():
    pages = {ss.APP_URL + "/": '<script src="/assets/index-1.js">',
             ss.APP_URL + "/assets/index-1.js": 'import("./main-2.js")',
             ss.APP_URL + "/assets/main-2.js": f'x="{_jwt("service_role")}"'}
    found, missing = ss.bundle_findings(fetch=lambda u: pages.get(u, ""))
    assert missing is None and len(found) == 1 and "main-2.js" in found[0]["what"]


def test_bundle_unreachable_is_unchecked_not_clean():
    def boom(u):
        raise OSError("timeout")
    found, missing = ss.bundle_findings(fetch=boom)
    assert found == [] and "app bundle" in missing


def test_backups_fresh_and_stale():
    fresh = {"backup.yml": NOW - timedelta(hours=3), "restore-drill.yml": NOW - timedelta(days=10)}
    assert ss.backup_findings(last=fresh.get, now=NOW) == ([], None)
    stale = {"backup.yml": NOW - timedelta(days=2), "restore-drill.yml": None}
    found, _ = ss.backup_findings(last=stale.get, now=NOW)
    assert len(found) == 2


def test_no_database_url_is_unchecked():
    found, missing = ss.database_findings(None, [])
    assert found == [] and "SUPABASE_DB_URL" in missing


def test_rls_allowlist_is_respected(monkeypatch):
    answers = iter([["leads_public", "notes"], []])
    monkeypatch.setattr(ss, "_psql", lambda url, sql: next(answers))
    found, missing = ss.database_findings("postgres://x", ["leads_public"])
    assert missing is None and len(found) == 1 and "`notes`" in found[0]["what"]


def test_secret_report_lists_location_never_value(tmp_path):
    rep = tmp_path / "g.json"
    rep.write_text(json.dumps([{"RuleID": "stripe-access-token", "File": "x.py",
                                "StartLine": 7, "Secret": "sk_live_REAL"}]))
    found, missing = ss.secrets_findings(str(rep))
    assert missing is None and "x.py:7" in found[0]["what"]
    assert "sk_live_REAL" not in json.dumps(found)
    assert ss.secrets_findings(str(tmp_path / "missing.json"))[1]
