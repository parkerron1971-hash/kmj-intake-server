"""Document checks: the anchored ledger does the job of a signature.

Layer Two, 2026-10-11 (handoff workstream H, step 2). When the system sends a
document as a file (a signed agreement, a contract PDF, a customer
statement), the SHA-256 of the exact bytes goes into that business's audit_log
row as `payload.doc_sha256`. payload is covered by the row hash
(ledger_canonical_v2), and the existing anchoring publishes those hashes'
Merkle roots to Bitcoin and Hedera. So a document's fingerprint is committed
to a public network without any new key, signature scheme or anchoring path.

Anyone can then check a file at /public/verify: the browser hashes the file
locally (the file never leaves the visitor's machine) and sends only the hash.
The answer states facts: which business recorded this exact file, what kind of
document, when, whether that business's chain verifies at that record, and
which public anchor covers it. It never vouches for anyone.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import sb_clients

logger = logging.getLogger("document_ledger")

router = APIRouter(tags=["document-checks"])

# What the public page says a document is. The key is stored in the ledger;
# the words are only for display.
KIND_LABELS: Dict[str, str] = {
    "signed_agreement": "signed agreement",
    "contract_pdf": "contract or proposal",
    "foundation_document": "business document",
    "customer_statement": "customer statement",
    "accountant_package": "financial package for an accountant",
    "revenue_csv": "revenue report",
}

NO_MATCH = "No record of this exact file. Even a one-character change makes a different file."
MAX_MATCHES = 5
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def doc_fields(data: Optional[bytes], *, kind: str, label: str = "") -> Dict[str, Any]:
    """The payload fields for one document. With no bytes, say so plainly
    rather than leaving a record that looks like it was hashed."""
    base = {"doc_kind": kind, "doc_label": " ".join(str(label or "").split())[:120]}
    if not data:
        return {**base, "doc_hashed": False}
    return {**base, "doc_sha256": sha256_hex(data), "doc_bytes": len(data)}


def record_document(business_id: Optional[str], data: Optional[bytes], *, kind: str,
                    label: str = "", actor_type: str = "system",
                    actor_id: Optional[str] = None, target_type: Optional[str] = None,
                    target_id: Optional[str] = None, source: str = "system",
                    summary: Optional[str] = None) -> Optional[str]:
    """One `document_recorded` ledger row for a file that left the system.
    Best-effort: returns the hash, or None; never raises into the caller's
    business flow."""
    if not business_id or not data:
        return None
    try:
        import audit_log
        fields = doc_fields(data, kind=kind, label=label)
        audit_log.record(
            business_id, actor_type=actor_type, actor_id=actor_id,
            verb="document_recorded",
            summary=(summary or f"Recorded the {KIND_LABELS.get(kind, 'document')} sent"),
            payload=fields, target_type=target_type, target_id=target_id,
            source=source)
        return fields["doc_sha256"]
    except Exception as e:
        logger.warning(f"[docs] could not record {kind} for {str(business_id)[:8]}: {e}")
        return None


# ─── The public lookup ──────────────────────────────────────────────────

def _chain_holds_at(business_id: str, sequence: Optional[int],
                    row_hash: Optional[str]) -> Optional[bool]:
    """Does this business's chain verify at this record? None = could not
    be checked right now (said as such, never rounded to yes or no)."""
    if not row_hash or sequence is None:
        return False
    try:
        res = sb_clients.sb_post_as_service("/rpc/ledger_verify", {"p_business_id": business_id})
        report = (res[0] if isinstance(res, list) and res else res) or {}
    except Exception:
        return None
    if not isinstance(report, dict) or "intact" not in report:
        return None
    if report.get("intact"):
        return True
    broken = report.get("broken_at")
    return bool(broken is not None and int(broken) > int(sequence))


def _anchors_for(business_id: str, sequence: Optional[int]) -> List[Dict[str, Any]]:
    """Public anchors whose window covers this record. Local or testnet
    anchors are not evidence anyone outside must accept, so they are left out."""
    if sequence is None:
        return []
    import ledger_anchor
    rows = sb_clients.sb_get_as_service(
        f"/ledger_anchors?business_id=eq.{business_id}"
        f"&first_sequence=lte.{int(sequence)}&last_sequence=gte.{int(sequence)}"
        "&select=id,provider,provider_ref,anchored_at&order=anchored_at.asc&limit=10") or []
    rows = rows if isinstance(rows, list) else []
    ups = ledger_anchor.upgrades_for([r.get("id") for r in rows])
    out = []
    for r in rows:
        provider = r.get("provider") or ""
        if not ledger_anchor.is_independent(provider):
            continue
        up = ups.get(str(r.get("id"))) or {}
        st = ledger_anchor.proof_status(up.get("upgraded_ref") or r.get("provider_ref"), provider)
        block = st.get("bitcoin_block") or up.get("bitcoin_block")
        confirmed = bool(st.get("confirmed") or up.get("confirmed"))
        out.append({
            "network": "Bitcoin" if provider == "opentimestamps" else provider.capitalize(),
            "anchored_at": r.get("anchored_at"),
            "status": "confirmed" if confirmed else "waiting for confirmation",
            "bitcoin_block": block,
            "verify_url": st.get("verify_url"),
        })
    return out


def _business_name(business_id: str) -> str:
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{business_id}&select=name&limit=1") or []
    return str((rows[0] if isinstance(rows, list) and rows else {}).get("name") or "A business")


def lookup(sha: str) -> Dict[str, Any]:
    """Facts about every ledger record of this exact file, and nothing else:
    no payload, no label, no contact data, no neighbouring rows."""
    sha = (sha or "").strip().lower()
    if not _HEX64.fullmatch(sha):
        raise ValueError("Send the file's SHA-256 as 64 hexadecimal characters.")
    rows = sb_clients.sb_get_as_service(
        f"/audit_log?payload->>doc_sha256=eq.{sha}"
        "&select=business_id,sequence,created_at,row_hash,payload"
        f"&order=created_at.asc&limit={MAX_MATCHES}") or []
    rows = rows if isinstance(rows, list) else []
    if not rows:
        return {"match": False, "message": NO_MATCH}
    names: Dict[str, str] = {}
    records = []
    for r in rows:
        bid = str(r.get("business_id") or "")
        if not bid:
            continue
        if bid not in names:
            names[bid] = _business_name(bid)
        kind = str((r.get("payload") or {}).get("doc_kind") or "")
        what = KIND_LABELS.get(kind, "document")
        when = str(r.get("created_at") or "")
        records.append({
            "business": names[bid],
            "document": what,
            "recorded_at": when,
            "ledger_record": r.get("sequence"),
            "chain_verifies_here": _chain_holds_at(bid, r.get("sequence"), r.get("row_hash")),
            "public_anchors": _anchors_for(bid, r.get("sequence")),
            "statement": f"This file matches the {what} {names[bid]} recorded on {when[:10]}.",
        })
    if not records:
        return {"match": False, "message": NO_MATCH}
    return {"match": True, "records": records}


class _CheckBody(BaseModel):
    sha256: str


_SECURE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
}


@router.post("/public/verify/document")
def check_document(body: _CheckBody, request: Request):
    import rate_limit
    if not rate_limit.allow_strict("document_check", rate_limit.trusted_client_ip(request)):
        raise HTTPException(429, "Too many checks from this connection. Try again in a minute.")
    try:
        result = lookup(body.sha256)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return JSONResponse(result, headers=_SECURE_HEADERS)


@router.get("/public/verify", response_class=HTMLResponse)
def verify_page():
    return HTMLResponse(PAGE, headers=_SECURE_HEADERS)



PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Check a document</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font:15px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
background:#f6f7f9;color:#1c1f23;padding:28px 16px}
.wrap{max-width:640px;margin:0 auto}
h1{font-size:21px;font-weight:600}
.sub{color:#6b7280;font-size:13.5px;margin-top:4px}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:20px;margin-top:18px}
.drop{border:2px dashed #cbd2dc;border-radius:10px;padding:28px 16px;text-align:center;cursor:pointer}
.drop:focus-within,.drop.over{border-color:#2563eb;background:#f5f8ff}
.drop label{font-weight:600;cursor:pointer}
input[type=file]{position:absolute;left:-9999px}
.f{display:flex;justify-content:space-between;gap:12px;padding:6px 0;border-bottom:1px solid #f0f1f3;font-size:13.5px}
.f span:first-child{color:#6b7280}
.f span:last-child{text-align:right;overflow-wrap:anywhere}
.yes{color:#2f9e6b;font-weight:600}.no{color:#b45309;font-weight:600}
.note{font-size:12.5px;color:#6b7280;margin-top:10px}
code{font:11.5px ui-monospace,SFMono-Regular,Menlo,monospace;background:#f3f4f6;padding:1px 5px;border-radius:4px;overflow-wrap:anywhere}
a{color:#2563eb}
footer{color:#9aa0a6;font-size:11.5px;margin:24px 0 8px;text-align:center}
</style></head><body><div class="wrap">
<h1>Check a document</h1>
<p class="sub">See whether a file is exactly the one a business on the Solutionist System recorded when it sent it.</p>
<div class="card">
  <div class="drop" id="drop">
    <label for="file">Choose a file</label> or drop it here
    <input type="file" id="file" aria-describedby="privacy">
    <p class="note" id="privacy">Your file stays on this device. This page works out the file's
    fingerprint (its SHA-256) in your browser and sends only that 64-character code.</p>
  </div>
  <div id="out" role="status" aria-live="polite" style="margin-top:16px"></div>
</div>
<footer>A match states facts from the business's record. It is not an opinion about the business.</footer>
</div>
<script>
(function(){
  var out=document.getElementById('out'), input=document.getElementById('file'), drop=document.getElementById('drop');
  function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function row(k,v){return '<div class="f"><span>'+esc(k)+'</span><span>'+v+'</span></div>';}
  async function hashFile(file){
    var buf=await file.arrayBuffer();
    var dig=await crypto.subtle.digest('SHA-256',buf);
    return Array.from(new Uint8Array(dig)).map(function(b){return b.toString(16).padStart(2,'0');}).join('');
  }
  function render(res,hex){
    if(!res.match){out.innerHTML='<p>'+esc(res.message)+'</p><p class="note">Fingerprint checked: <code>'+esc(hex)+'</code></p>';return;}
    out.innerHTML=res.records.map(function(r){
      var chain=r.chain_verifies_here===true?'<span class="yes">Verifies</span>':(r.chain_verifies_here===false?'<span class="no">Does not verify</span>':'Could not be checked right now');
      var anchors=(r.public_anchors||[]).map(function(a){
        var where=a.bitcoin_block?('block '+esc(a.bitcoin_block)):(a.verify_url?'<a href="'+esc(a.verify_url)+'" rel="noopener noreferrer" target="_blank">public record</a>':'');
        return esc(a.network)+', '+esc(a.status)+(where?' ('+where+')':'');
      }).join('<br>')||'Not yet published to a public network (this happens every few hours)';
      return '<p><strong>'+esc(r.statement)+'</strong></p>'+row('Recorded',esc(r.recorded_at)+' UTC')+row('Ledger record','#'+esc(r.ledger_record))+row('Record chain at this point',chain)+row('Public anchor',anchors);
    }).join('<hr style="border:0;border-top:1px solid #e5e7eb;margin:14px 0">')+'<p class="note">Fingerprint checked: <code>'+esc(hex)+'</code></p>';
  }
  async function check(file){
    if(!file){return;}
    out.textContent='Working out the fingerprint…';
    try{
      var hex=await hashFile(file);
      out.textContent='Checking…';
      var r=await fetch('/public/verify/document',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sha256:hex})});
      if(r.status===429){out.textContent='Too many checks from this connection. Try again in a minute.';return;}
      if(!r.ok){out.textContent='The check could not be completed. Try again.';return;}
      render(await r.json(),hex);
    }catch(e){out.textContent='This browser could not read the file. Try another browser.';}
  }
  input.addEventListener('change',function(){check(input.files[0]);});
  drop.addEventListener('dragover',function(e){e.preventDefault();drop.classList.add('over');});
  drop.addEventListener('dragleave',function(){drop.classList.remove('over');});
  drop.addEventListener('drop',function(e){e.preventDefault();drop.classList.remove('over');check(e.dataTransfer.files[0]);});
})();
</script>
</body></html>"""
