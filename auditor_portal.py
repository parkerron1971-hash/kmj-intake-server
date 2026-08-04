"""
auditor_portal.py — the outside reviewer's window onto one ledger.

Two surfaces:
  * owner-gated management (/audit/links) — mint, list, revoke;
  * the public read — no Solutionist account, nothing but a signed link
    that expires and can be pulled.

THE CREDENTIAL DOES NOT STAY IN THE URL. /public/audit/{token} is an
ENTRY route: it resolves the link, sets a short-lived scoped cookie and
303s to /public/audit/view, which is what the auditor actually reads.
The token-bearing URL therefore never renders a page, never loads an
asset, and never sits in the address bar — so what ends up in browser
history, in a bookmark, in a screenshot or over someone's shoulder is a
URL that grants nothing. Every request still re-checks revocation
against the table, because a cookie that outlived a revoked link would
turn "revoke" into "revoke in twelve hours".

THE RULE, INHERITED: report, never reassure. This page shows the chain's
state and the rows, and it never summarises them into a claim. An
auditor is precisely the reader who must not be handed a conclusion.

WHAT AN AUDITOR CAN SEE: the same columns every other ledger surface
returns (audit_log.LEDGER_SELECT) — verb, actor, outcome, timing,
sequence, authorized_by, subject_refs. It does NOT include payload or
result, so record CONTENTS never leave through this door. If a future
change widens that select list, it widens it HERE too, which is exactly
why there is one constant and not four queries.

EVERY VIEW IS LOGGED. Opening this page writes a row to the ledger it is
reading. Who looked, and when, is part of the record — the Etherscan
idea inverted: not public to everyone, but accountable to the practice.
"""
from __future__ import annotations

import html
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("auditor_portal")

router = APIRouter(tags=["auditor"])

# The auditor has no app session and never will, so the link must point
# at the BACKEND page, not the app shell. Pointing it at app.solutionist
# .studio sent the one person this feature exists for to a login screen.
_PUBLIC_BASE = (os.environ.get("PUBLIC_API_BASE")
                or "https://kmj-intake-server-production.up.railway.app")

# Never cached, never framed, no Referer leak. Still every bit as
# necessary now that the credential is a cookie rather than a path
# segment: no-store keeps the ledger out of a shared machine's disk
# cache, and the framing rules keep this page out of someone else's
# chrome. Applied to the ENTRY redirect too, so the one response that
# does see the token is not cacheable either.
_SECURE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
}


# ─── Owner-gated management ─────────────────────────────────────────

class MintBody(BaseModel):
    business_id: str
    label: str = "unnamed"
    ttl_days: int = 30
    window_start: Optional[str] = None
    window_end: Optional[str] = None


def _require_owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    """Minting a credential is an OWNER act, deliberately stricter than
    reading the ledger. mcp_server sets the precedent: a credential that
    can mint credentials is a privilege-escalation ladder, so the mint
    door is narrower than the read door."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id,settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "only the owner can share ledger access")
    return rows[0]


@router.post("/audit/links")
def mint_link(body: MintBody, user: AuthedUser = Depends(require_user)):
    """Mint a reviewer link. The plaintext is returned ONCE."""
    biz_row = _require_owner(body.business_id, user)
    import auditor_links
    try:
        token, row = auditor_links.mint(
            body.business_id, label=body.label,
            ttl_seconds=max(1, int(body.ttl_days or 30)) * 86400,
            window_start=body.window_start, window_end=body.window_end,
            created_by=(user.email or str(user.id)))
    except RuntimeError as e:
        # No secret configured — say so honestly rather than minting
        # something unverifiable.
        raise HTTPException(503, str(e))

    try:
        import audit_log
        audit_log.record(
            body.business_id, actor_type="user", actor_id=str(user.id),
            verb="ledger:link_minted", summary=f"Auditor link: {row['label']}",
            payload={"jti": row["jti"], "expires_at": row["expires_at"]},
            source="audit", authorized_by="owner")
    except Exception:
        pass

    return {
        "ok": True,
        "url": f"{_PUBLIC_BASE}/public/audit/{token}",
        "jti": row["jti"], "label": row["label"],
        "expires_at": row["expires_at"],
        "note": ("Copy this link now — it is stored only as a hash and "
                 "cannot be shown again. Revoking it is instant."),
    }


@router.get("/audit/links")
def list_links(biz: str, user: AuthedUser = Depends(require_user)):
    _require_owner(biz, user)
    import auditor_links
    return {"ok": True, "links": auditor_links.list_links(biz)}


@router.delete("/audit/links/{jti}")
def revoke_link(jti: str, biz: str, user: AuthedUser = Depends(require_user)):
    _require_owner(biz, user)
    import auditor_links
    ok = auditor_links.revoke(biz, jti)
    try:
        import audit_log
        audit_log.record(biz, actor_type="user", actor_id=str(user.id),
                         verb="ledger:link_revoked", ok=ok,
                         payload={"jti": jti}, source="audit",
                         authorized_by="owner")
    except Exception:
        pass
    return {"ok": ok}


class RedactBody(BaseModel):
    business_id: str
    subject_type: str
    subject_id: str
    reason: str = "data_subject_erasure"


@router.post("/audit/redact")
def redact_subject(body: RedactBody, user: AuthedUser = Depends(require_user)):
    """Honour one person's erasure request without destroying the record.

    A therapist's client, a lawyer's client, asks to be erased. Their
    details sit inside the practice's ledger because the trigger tier
    copies row contents. Until now the only removal path erased the
    whole practice's history — so the request could not be honoured at
    all without the practice destroying its own audit trail.

    This clears the CONTENTS of every row that touched that subject and
    leaves the FACT of each action standing: when, who, which verb,
    which sequence. row_hash is deliberately not recomputed, so the
    chain still links and the removed data stays provable to anyone who
    holds a copy — erasure without losing provability.

    Owner-only: it is the practice's legal obligation, and it is the one
    operation that can empty rows in an append-only table.
    """
    _require_owner(body.business_id, user)
    subject_type = str(body.subject_type or "").strip()[:40]
    subject_id = str(body.subject_id or "").strip()[:80]
    if not subject_type or not subject_id:
        raise HTTPException(400, "subject_type and subject_id are required")
    try:
        res = sb_clients.sb_post_as_service("/rpc/ledger_redact_subject", {
            "p_business_id": body.business_id,
            "p_subject_type": subject_type,
            "p_subject_id": subject_id,
            "p_reason": str(body.reason or "data_subject_erasure")[:120],
            "p_requested_by": (user.email or str(user.id)),
        })
    except Exception as e:
        logger.error(f"[ledger] redaction failed for {body.business_id}: {e}")
        raise HTTPException(503, "The erasure could not be completed. Nothing was changed.")
    if res is None:
        raise HTTPException(503, "The erasure could not be completed. Nothing was changed.")
    count = int(res if isinstance(res, int) else (res or 0))

    try:
        import audit_log
        audit_log.record(
            body.business_id, actor_type="user", actor_id=str(user.id),
            verb="ledger:redacted",
            summary=f"Erasure honoured for {subject_type} {subject_id[:8]}",
            payload={"subject_type": subject_type, "rows_redacted": count},
            source="audit", authorized_by="owner")
    except Exception:
        pass

    return {
        "ok": True, "rows_redacted": count,
        "note": ("The contents are gone. The record that those actions "
                 "happened remains, and the ledger still verifies — the "
                 "removal is declared, not hidden."
                 if count else
                 "Nothing in the ledger held data for that record. The "
                 "request is on file either way."),
    }


# ─── The public read ────────────────────────────────────────────────

def _resolve_or_404(token: str, request: Request) -> Dict[str, Any]:
    """Rate limit BEFORE verification (cheap pre-gate against brute
    force), then resolve. Every failure returns the same 404 — a link
    that is expired, revoked, forged or simply wrong must be
    indistinguishable from the outside."""
    import rate_limit
    # trusted_client_ip, not client_ip: the first X-Forwarded-For hop is
    # client-supplied, so a scripted token search could mint a fresh
    # bucket per request simply by varying the header.
    if not rate_limit.allow_strict("auditor_link",
                                   rate_limit.trusted_client_ip(request)):
        raise HTTPException(429, "Too many requests")
    import auditor_links
    ctx = auditor_links.resolve(token)
    if not ctx:
        raise HTTPException(404, "link not found")
    # A second budget, per LINK. Every view appends an undeletable row
    # under a per-tenant advisory lock, so one leaked credential could
    # otherwise flood a tenant's ledger and serialise its writes.
    if not rate_limit.allow_strict("auditor_link_jti", ctx["jti"]):
        raise HTTPException(429, "Too many requests")
    return ctx


def _load(ctx: Dict[str, Any], limit: int = 500) -> Dict[str, Any]:
    import audit_log
    import ledger_report
    biz = ctx["business_id"]
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "link not found")
    data = ledger_report.build(
        rows[0], limit=limit,
        since=ctx.get("window_start"), until=ctx.get("window_end"),
        include_db=True)
    # The view itself joins the record being viewed.
    try:
        audit_log.record(
            biz, actor_type="agent", actor_id=f"auditor:{ctx['jti'][:8]}",
            verb="ledger:viewed_by_auditor",
            summary="An auditor link opened the ledger",
            payload={"jti": ctx["jti"]}, source="auditor_link",
            authorized_by="auditor_link")
    except Exception:
        pass
    return data


# ─── Entry: trade the token for a session, then get it out of the URL ─
#
# THE ONLY route that ever sees the credential. It renders nothing —
# it resolves, sets a cookie and redirects — so the token-bearing URL
# never has a page body, never loads an asset, and never lingers in the
# address bar. What the auditor reads, bookmarks, and leaves in their
# history is `/public/audit/view`.
#
# 303, not 302: the redirect must be a GET regardless of how the entry
# was reached, and 303 is the one that says so rather than relying on
# universal-but-unspecified browser behaviour.
_SESSION_GONE = (
    "This review session has ended. Open the original link the practice "
    "sent you to start a new one — the link itself is still valid until "
    "it expires or the practice revokes it.")


def _session(request: Request) -> Optional[Dict[str, Any]]:
    """The session path. Same rate-limit budgets as the link path: every
    view appends an undeletable ledger row under a per-tenant advisory
    lock, and moving the credential to a cookie must not quietly remove
    the flood protection that guarded that."""
    import rate_limit
    import auditor_links
    if not rate_limit.allow_strict("auditor_link",
                                   rate_limit.trusted_client_ip(request)):
        raise HTTPException(429, "Too many requests")
    ctx = auditor_links.resolve_session(
        request.cookies.get(auditor_links.SESSION_COOKIE) or "")
    if not ctx:
        return None
    if not rate_limit.allow_strict("auditor_link_jti", ctx["jti"]):
        raise HTTPException(429, "Too many requests")
    return ctx


@router.get("/public/audit/view")
def auditor_view(request: Request):
    ctx = _session(request)
    if not ctx:
        # A browser gets a page, not a JSON blob. This is the one reader
        # the whole feature exists for, and "the session ended, your
        # link still works" is a very different message from "gone" —
        # without it an expired cookie reads as a revoked link and the
        # auditor calls the practice.
        return HTMLResponse(content=_render_gone(), status_code=410,
                            headers=_SECURE_HEADERS)
    return HTMLResponse(content=_render(_load(ctx)), headers=_SECURE_HEADERS)


@router.get("/public/audit/view/export")
def auditor_view_export(request: Request, format: str = "csv"):
    ctx = _session(request)
    if not ctx:
        raise HTTPException(410, _SESSION_GONE)
    return _export(ctx, format)


@router.get("/public/audit/{token}")
def auditor_entry(token: str, request: Request):
    ctx = _resolve_or_404(token, request)
    import auditor_links
    value, max_age = auditor_links.mint_session(ctx)
    if not value:
        raise HTTPException(404, "link not found")
    r = RedirectResponse("/public/audit/view", status_code=303,
                         headers=_SECURE_HEADERS)
    r.set_cookie(
        auditor_links.SESSION_COOKIE, value,
        max_age=max_age,
        # Scoped to this surface alone: the cookie is never attached to
        # any other endpoint on the domain, so it cannot ride along with
        # a request it was not minted for.
        path="/public/audit",
        httponly=True,      # script on any page cannot read it
        secure=True,        # never travels in the clear
        # Lax, not Strict: the auditor arrives by clicking a link in an
        # email client, and Strict would withhold the cookie on exactly
        # that cross-site top-level navigation. Lax still blocks it on
        # cross-site POSTs and subresource loads, which is the CSRF
        # surface that matters for a cookie-authenticated page.
        samesite="lax",
    )
    return r


def _export(ctx: Dict[str, Any], format: str = "csv") -> Response:
    data = _load(ctx)
    import ledger_report
    base = f"ledger-verification-{data['generated_at'][:10]}"
    if (format or "csv").lower() == "pdf":
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{ctx['business_id']}&select=settings&limit=1") or [{}]
        try:
            pdf = ledger_report.to_pdf(data, rows[0], generated_by="auditor link")
        except ImportError:
            raise HTTPException(503, "PDF unavailable. Use format=csv.")
        return Response(content=pdf, media_type="application/pdf",
                        headers={**_SECURE_HEADERS,
                                 "Content-Disposition": f'attachment; filename="{base}.pdf"'})
    return Response(content=ledger_report.to_csv(data), media_type="text/csv",
                    headers={**_SECURE_HEADERS,
                             "Content-Disposition": f'attachment; filename="{base}.csv"'})


def _e(v: Any) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def _render_gone() -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Review session ended</title><style>
body{{margin:0;background:#0f1115;color:#e8eaed;
 font:15px/1.65 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}}
.wrap{{max-width:520px;margin:0 auto;padding:64px 20px}}
.card{{background:#171a21;border:1px solid #262b36;border-radius:12px;padding:24px}}
h1{{font-size:19px;margin:0 0 10px}}
p{{color:#9aa0a6;font-size:13.5px;margin:0}}
</style></head><body><div class="wrap"><div class="card">
<h1>This review session has ended</h1>
<p>{_e(_SESSION_GONE)}</p>
</div></div></body></html>"""


def _render(d: Dict[str, Any]) -> str:
    v = d.get("verification") or {}
    hashed = int(v.get("hashed") or 0)
    intact = bool(v.get("intact")) and hashed > 0

    if hashed == 0:
        state_word, tone = "Not verifiable", "#9aa0a6"
        state_line = ("No record here carries a cryptographic fingerprint yet, "
                      "so nothing can be proven unaltered either way.")
    elif intact:
        state_word, tone = "Unaltered", "#2f9e6b"
        state_line = (f"{hashed} records carry fingerprints and each one matches. "
                      "Altering any of them would break every record after it.")
    else:
        state_word, tone = "Broken", "#c0392b"
        state_line = (f"Record #{_e(v.get('broken_at'))} does not match its own "
                      f"fingerprint. {_e(v.get('reason') or '')}")

    facts = [
        ("Records in range", v.get("checked", 0)),
        ("Carrying a fingerprint", hashed),
        ("Sequence range",
         f"#{v.get('first_sequence')} – #{v.get('last_sequence')}"
         if v.get("first_sequence") is not None else "—"),
    ]
    if v.get("unverifiable_rows"):
        facts.append(("Cannot be proven",
                      f"{v['unverifiable_rows']} (recorded before the chain began)"))
    if v.get("gaps"):
        facts.append(("Sequence gaps after",
                      ", ".join(f"#{g}" for g in v["gaps"])))
    fact_html = "".join(
        f"<div class='f'><span>{_e(a)}</span><b>{_e(b)}</b></div>" for a, b in facts)

    erasures = v.get("erasures") or []
    er_html = ""
    if erasures:
        items = "".join(
            f"<li>{_e(str(e.get('erased_at'))[:10])} — {_e(e.get('rows_erased'))} "
            f"record(s) removed"
            + (f" (#{_e(e.get('first_sequence'))}–#{_e(e.get('last_sequence'))})"
               if e.get("first_sequence") is not None else "")
            + (f" · {_e(e.get('reason'))}" if e.get("reason") else "")
            + "</li>" for e in erasures)
        er_html = (
            "<h2>Erasures on record</h2><ul class='er'>" + items + "</ul>"
            "<p class='note'>A deletion request removes records permanently. "
            "The gap it leaves is deliberate and stays visible — it is not "
            "evidence of tampering, and it is not hidden either.</p>")

    rows = []
    for e in (d.get("entries") or []):
        refs = " ".join(
            f"<code>{_e(r.get('type'))}:{_e(str(r.get('id'))[:8])}</code>"
            for r in (e.get("subject_refs") or []) if isinstance(r, dict))
        rows.append(
            "<tr>"
            f"<td class='sq'>{_e(e.get('sequence'))}</td>"
            f"<td class='w'>{_e(str(e.get('created_at') or '')[:19])}</td>"
            f"<td>{_e(e.get('actor_id') or e.get('actor_type'))}</td>"
            f"<td><code>{_e(e.get('verb'))}</code></td>"
            f"<td>{_e(e.get('authorized_by') or '')}</td>"
            f"<td class='{'ok' if e.get('ok') else 'bad'}'>"
            f"{'ok' if e.get('ok') else 'FAILED'}</td>"
            f"<td>{refs}</td>"
            "</tr>")

    rng = d.get("range") or {}
    window = ""
    if rng.get("since") or rng.get("until"):
        window = (f"<p class='note'>This link is limited to "
                  f"{_e((rng.get('since') or 'the start')[:10])} → "
                  f"{_e((rng.get('until') or 'now')[:10])}.</p>")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Action Ledger — {_e(d.get('business_name'))}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font:15px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
background:#f6f7f9;color:#1c1f23;padding:28px 16px}}
.wrap{{max-width:1000px;margin:0 auto}}
h1{{font-size:21px;font-weight:600}}
.sub{{color:#6b7280;font-size:13px;margin-top:3px}}
.card{{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:18px;margin-top:18px}}
.state{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.pill{{font-weight:700;font-size:12px;letter-spacing:.08em;text-transform:uppercase;
padding:4px 10px;border-radius:99px;color:#fff;background:{tone}}}
.f{{display:flex;justify-content:space-between;gap:12px;padding:6px 0;
border-bottom:1px solid #f0f1f3;font-size:13.5px}}
.f span{{color:#6b7280}}
h2{{font-size:14px;text-transform:uppercase;letter-spacing:.06em;color:#6b7280;
margin:22px 0 8px}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
th{{text-align:left;color:#6b7280;font-weight:600;padding:7px 8px;
border-bottom:1px solid #e5e7eb;white-space:nowrap}}
td{{padding:7px 8px;border-bottom:1px solid #f2f3f5;vertical-align:top}}
tr:nth-child(even) td{{background:#fafbfc}}
code{{font:11.5px ui-monospace,SFMono-Regular,Menlo,monospace;background:#f3f4f6;
padding:1px 5px;border-radius:4px}}
.ok{{color:#2f9e6b}} .bad{{color:#c0392b;font-weight:600}}
.sq{{color:#9aa0a6}} .w{{white-space:nowrap;color:#6b7280}}
.note{{font-size:12.5px;color:#6b7280;margin-top:9px;line-height:1.55}}
.er{{margin:6px 0 0 18px;font-size:13px}}
.scroll{{overflow-x:auto}}
.btn{{display:inline-block;margin-right:8px;margin-top:12px;padding:7px 13px;
border:1px solid #d1d5db;border-radius:8px;color:#1c1f23;text-decoration:none;
font-size:13px;font-weight:600;background:#fff}}
footer{{color:#9aa0a6;font-size:11.5px;margin:24px 0 8px;text-align:center}}
</style></head><body><div class="wrap">
<h1>{_e(d.get('business_name'))} — Action Ledger</h1>
<div class="sub">Read-only review access · generated {_e(d.get('generated_at', '')[:19])} UTC</div>

<div class="card">
  <div class="state"><span class="pill">{_e(state_word)}</span>
  <span style="font-size:13.5px">{state_line}</span></div>
  <div style="margin-top:12px">{fact_html}</div>
  {er_html}
  {window}
  <a class="btn" href="/public/audit/view/export?format=csv">Download CSV</a>
  <a class="btn" href="/public/audit/view/export?format=pdf">Download PDF</a>
</div>

<div class="card">
  <h2 style="margin-top:0">Actions ({_e(d.get('entry_count', 0))})</h2>
  <div class="scroll"><table>
  <tr><th>Seq</th><th>When (UTC)</th><th>Actor</th><th>Action</th>
      <th>Permitted by</th><th>Outcome</th><th>Touched</th></tr>
  {''.join(rows) or '<tr><td colspan="7">No records in this range.</td></tr>'}
  </table></div>
  <p class="note">This record is append-only. The database refuses edits and
  deletions to it, including from the platform operator. Each record carries a
  fingerprint of the one before it, so altering any record breaks every record
  after it — that is what the state above reports. Your visit has been recorded
  in this same ledger.</p>
</div>

<footer>Solutionist System · this link expires and can be revoked by the practice at any time</footer>
</div></body></html>"""
