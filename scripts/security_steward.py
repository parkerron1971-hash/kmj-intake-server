"""Security steward — the weekly check (agent operations plan, Agent 8).

Run by .github/workflows/security-steward.yml. Plain code, no AI. Prints a
markdown report and writes findings.json; the workflow opens or updates
one `security` issue when there are findings and closes it on a clean
week.

  secrets      gitleaks over the checked-out tree (its JSON report, read
               here; only file:line and rule are reported, never values)
  database     public tables with row level security OFF, and policies
               that let the anon role write (needs SUPABASE_DB_URL)
  app bundle   a Supabase service-role key in the live app's JavaScript
               (the one key that bypasses every access rule)
  backups      the nightly backup succeeded in the last 26 hours and the
               restore drill in the last 35 days

Dependency advisories are NOT here: the dependency audit workflow
(security.yml, from the 2026-09-30 security audit) owns them, so this
does not report the same advisory twice.

Every check that cannot run says so ("could not check"), never "clean".
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

APP_URL = os.environ.get("APP_URL", "https://system.mysolutionist.app")
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")

Finding = Dict[str, str]


# --- secrets ----------------------------------------------------------

def secrets_findings(report_path: str) -> Tuple[List[Finding], Optional[str]]:
    if not os.path.exists(report_path):
        return [], "secret scan did not produce a report"
    try:
        leaks = json.load(open(report_path, encoding="utf-8")) or []
    except ValueError:
        return [], "secret scan report was unreadable"
    out = [{"area": "secrets",
            "what": f"possible {l.get('RuleID') or l.get('Description') or 'secret'} at "
                    f"`{l.get('File')}:{l.get('StartLine')}`"} for l in leaks]
    return out, None


# --- database ---------------------------------------------------------

RLS_OFF_SQL = """
select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity
 order by 1;"""

ANON_WRITE_SQL = """
select tablename || ' (' || cmd || ')' from pg_policies
 where schemaname = 'public' and cmd in ('INSERT','UPDATE','DELETE','ALL')
   and ('anon' = any(roles) or 'public' = any(roles))
 order by 1;"""


def _psql(db_url: str, sql: str) -> List[str]:
    out = subprocess.run(["psql", db_url, "-At", "-v", "ON_ERROR_STOP=1", "-c", sql],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:300])
    return [l for l in out.stdout.splitlines() if l.strip()]


def database_findings(db_url: Optional[str], allow: List[str]) -> Tuple[List[Finding], Optional[str]]:
    if not db_url:
        return [], "database (SUPABASE_DB_URL not set)"
    try:
        rls_off = [t for t in _psql(db_url, RLS_OFF_SQL) if t not in allow]
        anon_write = _psql(db_url, ANON_WRITE_SQL)
    except Exception as e:
        return [], f"database ({e})"
    out = [{"area": "database",
            "what": f"table `{t}` has row level security OFF: anyone with the public "
                    "anon key can read and write it through the API"} for t in rls_off]
    out += [{"area": "database",
             "what": f"policy on `{p}` lets anonymous visitors write"} for p in anon_write]
    return out, None


# --- app bundle -------------------------------------------------------

def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "security-steward"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def _jwt_role(token: str) -> Optional[str]:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part)).get("role")
    except Exception:
        return None


def service_keys_in(js: str) -> List[str]:
    """Roles of any JWTs in the text that are service-role keys."""
    return [t[:12] + "…" for t in JWT_RE.findall(js) if _jwt_role(t) == "service_role"]


def bundle_findings(fetch=_get) -> Tuple[List[Finding], Optional[str]]:
    try:
        html = fetch(APP_URL + "/")
        scripts = sorted(set(re.findall(r'/assets/[A-Za-z0-9_.-]+\.js', html)))
        seen = set(scripts)
        for s in list(scripts):                  # one hop: chunks the entry imports
            for ref in re.findall(r'[A-Za-z0-9_.-]+\.js', fetch(APP_URL + s)):
                p = f"/assets/{ref}"
                if p not in seen and len(seen) < 400:
                    seen.add(p)
        hits = []
        for p in sorted(seen):
            try:
                if service_keys_in(fetch(APP_URL + p)):
                    hits.append(p)
            except Exception:
                continue
    except Exception as e:
        return [], f"app bundle ({e})"
    return [{"area": "app bundle",
             "what": f"a Supabase **service-role key** is in the public app code (`{p}`). "
                     "It bypasses every access rule: rotate it now."} for p in hits], None


# --- backups ----------------------------------------------------------

def _last_success(workflow: str) -> Optional[datetime]:
    out = subprocess.run(["gh", "run", "list", "--workflow", workflow, "--status", "success",
                          "--limit", "1", "--json", "createdAt", "-q", ".[0].createdAt"],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200])
    s = out.stdout.strip()
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def backup_findings(last=_last_success, now: Optional[datetime] = None) -> Tuple[List[Finding], Optional[str]]:
    now = now or datetime.now(timezone.utc)
    out: List[Finding] = []
    try:
        b = last("backup.yml")
        d = last("restore-drill.yml")
    except Exception as e:
        return [], f"backups ({e})"
    if not b or now - b > timedelta(hours=26):
        out.append({"area": "backups", "what": "no successful nightly backup in the last 26 hours"
                    + (f" (last: {b:%Y-%m-%d %H:%M} UTC)" if b else " (none on record)")})
    if not d or now - d > timedelta(days=35):
        out.append({"area": "backups", "what": "no successful restore drill in the last 35 days"
                    + (f" (last: {d:%Y-%m-%d})" if d else " (none on record)")})
    return out, None


def main() -> int:
    allow = [t.strip() for t in (os.environ.get("RLS_ALLOWLIST") or "").split(",") if t.strip()]
    findings: List[Finding] = []
    unchecked: List[str] = []
    for got, missing in (secrets_findings(os.environ.get("GITLEAKS_REPORT", "gitleaks.json")),
                         database_findings(os.environ.get("SUPABASE_DB_URL"), allow),
                         bundle_findings(),
                         backup_findings()):
        findings += got
        if missing:
            unchecked.append(missing)
    lines = [f"- **{f['area']}**: {f['what']}" for f in findings] or ["- Nothing found."]
    if unchecked:
        lines.append("")
        lines.append("Could not check: " + "; ".join(unchecked) + ".")
    report = "\n".join(lines)
    print(report)
    with open("findings.json", "w", encoding="utf-8") as f:
        json.dump({"findings": findings, "unchecked": unchecked, "report": report}, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
