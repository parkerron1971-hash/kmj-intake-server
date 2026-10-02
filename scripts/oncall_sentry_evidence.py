"""Print the Sentry section of on-call's evidence file (markdown).

Run by .github/workflows/oncall.yml before Claude starts. Needs
SENTRY_AUTH_TOKEN (a user auth token with event:read, org:read,
project:read); without it, says so instead of failing, so the rest of
the evidence still lands.

Why on-call needs this: the 2026-10-01 incident #1137 was diagnosed as
"probably an expired login". Sentry had the real answer the whole time,
in the error message and the breadcrumbs: a 400 for a missing column.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

ORG = os.environ.get("SENTRY_ORG", "solutionist-system-llc")
BASE = f"https://{ORG}.sentry.io/api/0/organizations/{ORG}"


def _get(token: str, path: str):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _event_lines(event: dict) -> list[str]:
    out = []
    if event.get("message"):
        out.append(f"   message: {event['message'][:600]}")
    for entry in event.get("entries") or []:
        if entry.get("type") == "exception":
            for v in (entry.get("data") or {}).get("values") or []:
                out.append(f"   exception: {v.get('type')}: {(v.get('value') or '')[:400]}")
                frames = ((v.get("stacktrace") or {}).get("frames") or [])[-3:]
                for fr in frames:
                    out.append(f"     at {fr.get('filename')}:{fr.get('lineNo')} in {fr.get('function')}")
        if entry.get("type") == "breadcrumbs":
            crumbs = ((entry.get("data") or {}).get("values") or [])[-6:]
            if crumbs:
                out.append("   last breadcrumbs (oldest first):")
            for b in crumbs:
                status = (b.get("data") or {}).get("http.response.status_code")
                url = (b.get("data") or {}).get("url") or ""
                msg = (b.get("message") or "")[:300]
                bits = [b.get("level") or "", b.get("category") or ""]
                if status:
                    bits.append(f"HTTP {status}")
                out.append(f"     - {' '.join(x for x in bits if x)}: {msg or url[:200]}")
    return out


def main() -> int:
    print("## Sentry: unresolved errors seen in the last 24 hours")
    token = (os.environ.get("SENTRY_AUTH_TOKEN") or "").strip()
    if not token:
        print("Not available: the SENTRY_AUTH_TOKEN secret is not set, so this "
              "investigation cannot see error messages, stack traces or breadcrumbs.")
        return 0
    try:
        issues = _get(token, "/issues/?query=is:unresolved&statsPeriod=24h&sort=date&limit=10")
    except (urllib.error.URLError, ValueError) as e:
        print(f"Not available: the Sentry API call failed ({e}).")
        return 0
    if not issues:
        print("None. No unresolved errors in the last 24 hours.")
        return 0
    for i, issue in enumerate(issues):
        proj = (issue.get("project") or {}).get("slug", "?")
        print(f"- **{issue.get('shortId')}** ({proj}) ×{issue.get('count')} "
              f"last seen {issue.get('lastSeen')}: {issue.get('title')}")
        if issue.get("culprit"):
            print(f"   where: {issue['culprit']}")
        print(f"   {issue.get('permalink')}")
        if i < 3:  # the full latest event for the three most recent
            try:
                ev = _get(token, f"/issues/{issue['id']}/events/latest/")
                for line in _event_lines(ev):
                    print(line)
            except (urllib.error.URLError, ValueError, KeyError) as e:
                print(f"   (latest event unavailable: {e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
