"""
module_check.py — the system looks at a MODULE the way a person does.

WHY THIS EXISTS
───────────────
The builder proposes a module, the practitioner accepts it, and nobody
ever looks at it. site_check gave the website a second pair of eyes
(headless Chromium at a phone and a desktop width, geometry measured, a
vision judge on the screenshots); the module surfaces — the thing Chief
actually builds all day — had none of that. Kevin, 9/06: "the quality
and design must go up even further … so it's not plain." A surface
nobody has looked at cannot be called excellent, so this is the first
move: look, measure, judge, and file findings the builder can act on.

HOW IT WORKS
────────────
  1. A short-lived signed PREVIEW TOKEN lets the app render one module
     without a sign-in: the frontend's /preview/module/<token> page
     mounts the real ArchetypeDispatch, and every REST read it makes
     goes through /module-preview/<token>/rest, which answers only the
     four tables the surfaces read, scoped to that one business and
     module. When the module has fewer than SAMPLE_MIN_ROWS entries the
     preview answers with SAMPLE ROWS shaped from the module's own
     fields, so a brand-new module is judged as it will look in use,
     not as an empty grid.
  2. site_check.inspect_pages opens that page at 390 and 1100, measures
     overflow / overlaps / empty headings, screenshots both.
  3. The judge (a vision model) reviews the shots against a MODULE
     rubric: what is wrong (alignment, overlap, cut-off, empty) AND how
     it reads as a designed thing — a hero, a first impression, an
     empty line that says something, a chart you can read — returning
     findings, a design score out of five, and up to three concrete
     next moves in the builder's vocabulary (presentation, params).
  4. The report lives on the job row (chief_jobs.result). inspect_module
     reads the latest one back so Chief can answer "how does it look?"

Runs as the `module_check` chief_jobs kind, enqueued after every accept
and on the check_module action. Never raises: a browser that will not
open or a judge that will not answer is a completed job with an honest
summary.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode

logger = logging.getLogger("module_check")

JOB_KIND = "module_check"
WIDTHS: Tuple[int, ...] = (390, 1100)
TOKEN_TTL_MIN = 20
SAMPLE_MIN_ROWS = 3
SAMPLE_ROWS = 6
MAX_FINDINGS = 10
# intake_forms: the pipeline and booking surfaces ask which public forms
# feed the module (a chip, read-only). First live run: two 403s per page.
PREVIEW_TABLES = ("businesses", "custom_modules", "module_entries", "contacts", "intake_forms")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def enabled() -> bool:
    return (os.environ.get("MODULE_CHECK") or "on").strip().lower() not in ("off", "0", "false", "no")


def revise_enabled() -> bool:
    """The builder may act on the verdict (module_revise). MODULE_REVISE=off keeps checks read-only."""
    return (os.environ.get("MODULE_REVISE") or "on").strip().lower() not in ("off", "0", "false", "no")


REVISE_BELOW = 4                        # a 4/5 or better is left alone


# ─── the preview token ────────────────────────────────────────────────

def _secret() -> bytes:
    s = (os.environ.get("PREVIEW_SECRET") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
         or os.environ.get("SUPABASE_SERVICE_KEY") or "dev-preview-secret")
    return s.encode()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def preview_token(business_id: str, module_id: str, *, sample: bool = True,
                  ttl_min: int = TOKEN_TTL_MIN) -> str:
    """A signed, expiring grant to read ONE module of ONE business."""
    body = json.dumps({"b": business_id, "m": module_id, "s": bool(sample),
                       "exp": int(time.time()) + ttl_min * 60}, separators=(",", ":"))
    payload = _b64(body.encode())
    sig = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload, sig = token.split(".", 1)
        want = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, want):
            return None
        data = json.loads(_unb64(payload))
        if int(data.get("exp") or 0) < time.time():
            return None
        if not data.get("b") or not data.get("m"):
            return None
        return data
    except Exception:
        return None


# ─── sample rows: the module as it will look in use ──────────────────

_FIRST = ["Maya", "Jordan", "Priya", "Marcus", "Elena", "Theo"]
_LAST = ["Reyes", "Okafor", "Nakamura", "Brennan", "Castillo", "Lindqvist"]


def _uuid(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"solutionist-preview/{seed}"))


def sample_contacts(business_id: str, n: int = 4) -> List[Dict[str, Any]]:
    out = []
    for i in range(n):
        name = f"{_FIRST[i % len(_FIRST)]} {_LAST[(i * 3) % len(_LAST)]}"
        out.append({"id": _uuid(f"{business_id}/contact/{i}"), "business_id": business_id,
                    "name": name, "email": f"{name.split()[0].lower()}@example.com",
                    "phone": None, "status": "active", "health_score": 60 + 9 * i,
                    "created_at": _now(), "updated_at": _now(), "preview": True})
    return out


def _sample_value(field: Dict[str, Any], i: int, rnd, contacts: List[Dict[str, Any]],
                  params: Dict[str, Any]) -> Any:
    t = str(field.get("type") or "text")
    name = str(field.get("name") or "")
    label = str(field.get("label") or name or "Value")
    opts = [str(o) for o in (field.get("options") or [])]
    day = datetime.now(timezone.utc) - timedelta(days=(i * 9) % 60)
    if t == "contact_link":
        return contacts[i % len(contacts)]["id"] if contacts else None
    if t == "select":
        return opts[i % len(opts)] if opts else None
    if t == "date":
        return day.strftime("%Y-%m-%d")
    if t == "checkbox":
        return bool(i % 2)
    if t == "rating":
        return 3 + (i % 3)
    if t == "currency":
        return float(150 + 75 * (i % 5))
    if t == "number":
        target = params.get("target")
        if name == params.get("value_field") and isinstance(target, (int, float)):
            # a tracker: values climbing toward the goal
            lo = float(target) * 0.72
            return round(lo + (float(target) - lo) * (i / max(1, SAMPLE_ROWS - 1)), 0)
        return 4 + 3 * i
    if t in ("email",):
        return f"{_FIRST[i % len(_FIRST)].lower()}@example.com"
    if t == "phone":
        return f"(555) 01{i:02d}-4{i:03d}"
    if t == "url":
        return "https://example.com"
    if t == "textarea":
        return f"{label}: first note for this one — added {day.strftime('%b %d')}."
    if t in ("offering_ref", "module_ref"):
        return None
    # text: a title reads like a real one ("Reyes lead"), never "Lead / business name 2" —
    # the judge flagged the stranded trailing number on every card
    noun = str(params.get("item_noun") or params.get("_noun") or "item").strip().lower()
    # The title is whatever the surface treats as the title: the archetype's
    # title_field, a title-ish name, or the first text field (Leads names
    # its title "lead_name" — the judge saw "Lead / business name 2" again).
    if name == params.get("_title_field") or name in ("title", "name", "subject"):
        return f"{_LAST[(i * 3) % len(_LAST)]} {noun}"
    return f"{label} {i + 1}"


def sample_rows(module: Dict[str, Any], contacts: List[Dict[str, Any]],
                n: int = SAMPLE_ROWS) -> List[Dict[str, Any]]:
    """Deterministic rows shaped from the module's fields, one per day
    going back, so every surface has something to draw: a pipeline gets
    cards across its stages, a tracker gets a climb, a dashboard gets
    totals and a trend."""
    import random
    rnd = random.Random(str(module.get("id") or module.get("slug") or "m"))
    fields = [f for f in ((module.get("schema") or {}).get("fields") or []) if isinstance(f, dict)]
    params = dict(module.get("archetype_params") or {})
    params.setdefault("_noun", str(module.get("name") or "item").rstrip("s").lower() or "item")
    first_text = next((f.get("name") for f in fields if f.get("type", "text") == "text" and f.get("name")), None)
    params.setdefault("_title_field", params.get("title_field") or first_text)
    rows = []
    for i in range(n):
        data = {}
        for f in fields:
            if not f.get("name"):
                continue
            v = _sample_value(f, i, rnd, contacts, params)
            if v is not None:
                data[f["name"]] = v
        when = (datetime.now(timezone.utc) - timedelta(days=(i * 9) % 60, hours=i)).isoformat()
        rows.append({"id": _uuid(f"{module.get('id')}/row/{i}"), "module_id": module.get("id"),
                     "business_id": module.get("business_id"), "status": "active",
                     "data": data, "created_at": when, "updated_at": when, "preview": True})
    return rows


# ─── the read the preview page is allowed ────────────────────────────

def answer_rest(token_data: Dict[str, Any], path: str) -> Tuple[int, Any]:
    """Answer one PostgREST-style read for the preview page. Only the
    four tables the surfaces read; every one pinned to the token's
    business (and module). Sample rows stand in for an empty module."""
    import sb_clients
    biz, mod, sample = token_data["b"], token_data["m"], bool(token_data.get("s"))
    if "?" in path:
        table, qs = path.lstrip("/").split("?", 1)
    else:
        table, qs = path.lstrip("/"), ""
    table = table.strip("/")
    if table not in PREVIEW_TABLES:
        return 403, {"error": "not readable in a preview"}
    q = [(k, v) for k, v in parse_qsl(qs, keep_blank_values=True)]

    def _has(key: str) -> Optional[str]:
        for k, v in q:
            if k == key:
                return v
        return None

    if table == "businesses":
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{biz}&select=*&limit=1") or []
        return 200, rows
    q = [(k, v) for k, v in q if k != "business_id"] + [("business_id", f"eq.{biz}")]
    if table == "custom_modules":
        rows = sb_clients.sb_get_as_service(f"/custom_modules?{urlencode(q)}") or []
        return 200, rows
    if table == "intake_forms":
        rows = sb_clients.sb_get_as_service(f"/intake_forms?{urlencode(q)}") or []
        return 200, rows if isinstance(rows, list) else []
    if table == "contacts":
        rows = sb_clients.sb_get_as_service(f"/contacts?{urlencode(q)}") or []
        rows = rows if isinstance(rows, list) else []
        if sample:
            rows = rows + sample_contacts(biz)
        return 200, rows
    # module_entries: only this module
    mid = _has("module_id")
    if mid and mid != f"eq.{mod}":
        return 200, []
    q = [(k, v) for k, v in q if k != "module_id"] + [("module_id", f"eq.{mod}")]
    rows = sb_clients.sb_get_as_service(f"/module_entries?{urlencode(q)}") or []
    rows = rows if isinstance(rows, list) else []
    if sample:
        live = [r for r in rows if r.get("status", "active") == "active"]
        if len(live) < SAMPLE_MIN_ROWS:
            mrows = sb_clients.sb_get_as_service(
                f"/custom_modules?id=eq.{mod}&business_id=eq.{biz}&select=*&limit=1") or []
            if mrows:
                samples = sample_rows(mrows[0], sample_contacts(biz))
                wanted = _has("id")
                if wanted and wanted.startswith("eq."):
                    samples = [r for r in samples if r["id"] == wanted[3:]]
                rows = rows + samples
    return 200, rows


def preview_url(business_id: str, module_id: str, *, sample: bool = True) -> str:
    from app_base import app_base_url
    return f"{app_base_url()}/preview/module/{preview_token(business_id, module_id, sample=sample)}"


# ─── the judge ────────────────────────────────────────────────────────

_MODULE_RUBRIC = """You are reviewing screenshots of ONE screen inside a small-business app — a
module the owner will open every day (a board of jobs, a calendar of
bookings, a tracker of scores, a dashboard of totals) — at a phone width
and a desktop width. You are the designer giving it a second look before
it ships. Two questions, in this order:

A. What is WRONG on the screen (report every one you see):
   1. overlap, collision, text touching an edge, a label on top of another
   2. text cut off, a single orphaned word on its own line, unreadable
      contrast, a number that does not fit its tile
   3. broken or empty: a blank area where content belongs, an empty
      heading, a chart with no marks, a row that renders as raw data
   4. alignment: an element visibly out of line with the thing beside it

B. How it READS as a designed thing (this is what makes it excellent
   instead of plain):
   - Is there a hero — the one number, line or view that answers "how
     am I doing?" in a glance — or does it open as a plain table?
   - Does the first impression have hierarchy: a headline, a supporting
     line, then the detail — or is everything the same weight?
   - Is the empty/first-open state a sentence that means something, or
     "no data"?
   - Do charts and meters read at a glance (labels, scale, a baseline)?
   - Does it feel considered — spacing, tone, a consistent accent — or
     assembled?

Do not comment on copy wording, colour taste, or what you would build
instead. Do not invent problems; an empty findings list with a high
score is a good answer. Return JSON only:
{"findings":[{"severity":"high|medium|low","width":390|1100,
  "what":"one sentence a business owner understands",
  "where":"element, briefly"}],
 "design_score": 1-5,
 "first_impression": "one sentence: what a first-time viewer sees",
 "next": ["up to three concrete moves that would raise the score, each in
          the builder's terms — a hero stat, a tone, an empty line, a
          milestone label, a chart form, tighter spacing"]}"""


def parse_judge(text: str) -> Dict[str, Any]:
    m = re.search(r"\{[\s\S]*\}", text or "")
    out: Dict[str, Any] = {"findings": [], "design_score": None, "first_impression": "", "next": []}
    if not m:
        return out
    try:
        data = json.loads(m.group(0))
    except Exception:
        return out
    for f in (data.get("findings") or []):
        if not isinstance(f, dict) or not str(f.get("what") or "").strip():
            continue
        sev = str(f.get("severity") or "medium").lower()
        if sev not in ("high", "medium", "low"):
            sev = "medium"
        try:
            width = int(f.get("width") or 0)
        except Exception:
            width = 0
        out["findings"].append({"severity": sev, "width": width, "source": "vision",
                                "what": str(f["what"]).strip()[:200],
                                "where": str(f.get("where") or "").strip()[:80]})
    try:
        s = int(data.get("design_score"))
        out["design_score"] = max(1, min(5, s))
    except Exception:
        pass
    out["first_impression"] = str(data.get("first_impression") or "").strip()[:200]
    out["next"] = [str(x).strip()[:160] for x in (data.get("next") or []) if str(x).strip()][:3]
    return out


def judge(page: Dict[str, Any], business_id: str, module: Dict[str, Any]) -> Dict[str, Any]:
    """One vision call over the phone + desktop shots. Empty on any
    failure — the geometry findings stand on their own."""
    empty = {"findings": [], "design_score": None, "first_impression": "", "next": []}
    shots = page.get("shots") or {}
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not shots or not key:
        return empty
    try:
        import llm_call
        content: List[Dict[str, Any]] = [{"type": "text", "text": (
            f"Module: {module.get('name')} — archetype {module.get('archetype') or 'generic'}; "
            f"tone {((module.get('presentation') or {}).get('tone')) or 'default'}.")}]
        for width, jpeg in shots.items():
            content.append({"type": "text", "text": f"Width {width}px:"})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(jpeg).decode()}})
        content.append({"type": "text", "text": "Review per the rubric. JSON only."})
        client = llm_call.sdk_client(key=key)
        msg = client.messages.create(
            model=(os.environ.get("MODULE_JUDGE_MODEL") or "claude-opus-5").strip(),
            max_tokens=1200, system=_MODULE_RUBRIC,
            messages=[{"role": "user", "content": content}], timeout=120.0)
        try:
            from vision_grader import _meter
            _meter(business_id, getattr(msg, "model", "") or "",
                   getattr(getattr(msg, "usage", None), "input_tokens", 0) or 0,
                   getattr(getattr(msg, "usage", None), "output_tokens", 0) or 0)
        except Exception:
            pass
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return parse_judge(text)
    except Exception as e:
        logger.warning(f"[module-check] judge skipped: {type(e).__name__}: {e}")
        return empty


# ─── the run ──────────────────────────────────────────────────────────

def _rank(f: Dict[str, Any]) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(f.get("severity"), 3)


def _look(business_id: str, module: Dict[str, Any], *, vision: bool,
          progress_cb=None, pct: Tuple[int, int] = (10, 90)) -> Dict[str, Any]:
    """One look at a module: open, measure, judge. Returns
    {ok, page, findings, verdict, screenshots, error?}."""
    import site_check
    lo, hi = pct
    span = max(1, hi - lo)
    module_id = str(module.get("id"))
    if progress_cb:
        progress_cb(lo, f"opening {module.get('name')}")
    url = preview_url(business_id, module_id, sample=True)
    pages = site_check.inspect_pages([url], widths=WIDTHS, screenshots=True)
    if pages is None:
        return {"ok": False, "error": "no_browser"}
    page = pages[0]
    if progress_cb:
        progress_cb(lo + int(span * 0.45), "measuring the layout")
    token = url.rsplit("/", 1)[1]

    def _scrub(v: Any) -> Any:
        if not isinstance(v, str):
            return v
        return (v.replace(url, module.get("name") or "module")
                 .replace(token, "<preview>")
                 .replace("/preview/module/" + "<preview>", module.get("name") or "module"))

    findings = site_check.findings_from_geometry(page)
    for f in findings:
        for k in ("where", "what", "detail"):
            if k in f:
                f[k] = _scrub(f[k])
    page["console_errors"] = [_scrub(c) for c in (page.get("console_errors") or [])]
    page["failed_requests"] = [_scrub(c) for c in (page.get("failed_requests") or [])]
    verdict = {"findings": [], "design_score": None, "first_impression": "", "next": []}
    if vision:
        if progress_cb:
            progress_cb(lo + int(span * 0.6), "a designer's look at both widths")
        verdict = judge(page, business_id, module)
        findings.extend(verdict["findings"])
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    shots = site_check._store_shots(business_id, f"mod-{run_id}", [page])
    findings.sort(key=_rank)
    seen, deduped = set(), []
    for f in findings:
        k = (f.get("what"), f.get("where"))
        if k in seen:
            continue
        seen.add(k)
        deduped.append(f)
    return {"ok": True, "page": page, "findings": deduped[:MAX_FINDINGS], "verdict": verdict,
            "screenshots": shots, "url": url}


def _summary(name: str, findings: List[Dict[str, Any]], score: Optional[int]) -> str:
    high = sum(1 for f in findings if f.get("severity") == "high")
    n = len(findings)
    score_txt = f"design {score}/5" if score else "no design score"
    if n == 0:
        return f"{name}: nothing out of place, {score_txt}."
    return (f"{name}: {n} thing{'s' if n != 1 else ''} to look at"
            + (f", {high} that matter{'s' if high == 1 else ''}" if high else "")
            + f"; {score_txt}.")


def run(business_id: str, module_id: str, *, reason: str = "manual", vision: bool = True,
        revise: bool = True, progress_cb=None) -> Dict[str, Any]:
    """Look at one module — and, when the designer scores it below 4 and
    names next moves, let the builder act on them (module_revise), look
    again, and keep the change only if the score went up. Returns the
    report; never raises."""
    import sb_clients
    started = time.time()
    report: Dict[str, Any] = {"ok": False, "reason": reason, "checked_at": _now(),
                              "module_id": module_id, "module": None, "findings": [],
                              "design_score": None, "first_impression": "", "next": [],
                              "summary": "", "screenshots": [], "url": None, "revision": None}
    try:
        if not enabled():
            report["summary"] = "Module checks are switched off."
            report["error"] = "disabled"
            return report
        rows = sb_clients.sb_get_as_service(
            f"/custom_modules?id=eq.{module_id}&business_id=eq.{business_id}&select=*&limit=1") or []
        if not rows:
            report["summary"] = "That module is not on file."
            report["error"] = "no_module"
            return report
        module = rows[0]
        report["module"] = module.get("name")
        will_revise = bool(revise and vision and revise_enabled())
        first = _look(business_id, module, vision=vision, progress_cb=progress_cb,
                      pct=(10, 45) if will_revise else (10, 90))
        if not first.get("ok"):
            report["summary"] = "The check could not open a browser on the server."
            report["error"] = first.get("error") or "no_browser"
            return report
        report["url"] = first["url"].split("/preview/module/")[0] + "/preview/module/…"
        verdict = first["verdict"]
        report["findings"] = first["findings"]
        report["design_score"] = verdict.get("design_score")
        report["first_impression"] = verdict.get("first_impression") or ""
        report["next"] = verdict.get("next") or []
        report["console_errors"] = first["page"].get("console_errors") or []
        report["screenshots"] = first["screenshots"]

        # ─── the loop closes: act on the verdict, look again ────────────
        score = report["design_score"]
        if will_revise and score is not None and score < REVISE_BELOW and report["next"]:
            import module_revise
            if progress_cb:
                progress_cb(50, "revising the design from the verdict")
            prop = module_revise.propose(module, report)
            rev: Dict[str, Any] = {"attempted": True, "applied": False, "kept": False,
                                   "before_score": score, "after_score": None,
                                   "why": prop.get("why") or prop.get("error") or "", "changes": []}
            if prop.get("ok") and not prop.get("unchanged"):
                if module_revise.apply(module_id, prop["archetype_params"], prop["presentation"]):
                    rev["applied"] = True
                    rev["changes"] = prop.get("changes") or []
                    revised = dict(module)
                    revised["archetype_params"] = prop["archetype_params"]
                    revised["presentation"] = prop["presentation"]
                    second = _look(business_id, revised, vision=True, progress_cb=progress_cb, pct=(60, 90))
                    if second.get("ok"):
                        new_score = second["verdict"].get("design_score")
                        rev["after_score"] = new_score
                        if new_score is not None and new_score > score:
                            rev["kept"] = True
                            report["findings"] = second["findings"]
                            report["design_score"] = new_score
                            report["first_impression"] = second["verdict"].get("first_impression") or ""
                            report["next"] = second["verdict"].get("next") or []
                            report["screenshots"] = first["screenshots"] + second["screenshots"]
                    if not rev["kept"]:
                        # put it back exactly as it was
                        b = prop.get("before") or {}
                        module_revise.apply(module_id, b.get("archetype_params") or {},
                                            b.get("presentation") or {})
            report["revision"] = rev
        if progress_cb:
            progress_cb(92, "filing the report")
        report["summary"] = _summary(module.get("name") or "module", report["findings"], report["design_score"])
        rv = report.get("revision") or {}
        if rv.get("kept"):
            report["summary"] += (f" Chief revised the design ({rv['before_score']}→{rv['after_score']}): "
                                  + "; ".join(rv.get("changes") or [rv.get("why") or "presentation"]) + ".")
        elif rv.get("applied"):
            report["summary"] += " A revision was tried and put back — it did not score higher."
        report["ok"] = True
        report["seconds"] = round(time.time() - started, 1)
        n = len(report["findings"])
        high = sum(1 for f in report["findings"] if f["severity"] == "high")
        try:
            import event_spine
            event_spine.emit("module_check_completed", business_id, data={
                "module_id": module_id, "module": module.get("name"), "reason": reason,
                "findings": n, "high": high, "design_score": report["design_score"],
                "summary": report["summary"]}, source="module_check")
        except Exception:
            pass
        logger.info(f"[module-check] {business_id[:8]} {module.get('name')} ({reason}): {report['summary']}")
        return report
    except Exception as e:
        logger.warning(f"[module-check] failed (non-fatal): {type(e).__name__}: {e}")
        report["summary"] = "The check hit a problem and stopped."
        report["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        return report


def latest_report(business_id: str, module_id: str) -> Optional[Dict[str, Any]]:
    """The last finished check for one module, from its job row."""
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/chief_jobs?business_id=eq.{business_id}&kind=eq.{JOB_KIND}"
        f"&params->>module_id=eq.{module_id}&status=eq.done"
        f"&select=result,finished_at&order=created_at.desc&limit=1") or []
    if not isinstance(rows, list) or not rows:
        return None
    res = rows[0].get("result")
    if not isinstance(res, dict) or not res.get("ok"):
        return None
    res = dict(res)
    res["finished_at"] = rows[0].get("finished_at")
    return res


def describe(report: Dict[str, Any]) -> str:
    """One paragraph for Chief: the score, the first impression, the
    findings that matter, and the next moves."""
    if not report:
        return ""
    bits = [report.get("summary") or ""]
    if report.get("first_impression"):
        bits.append(f"First impression: {report['first_impression']}")
    top = [f for f in (report.get("findings") or []) if f.get("severity") in ("high", "medium")][:4]
    if top:
        bits.append("Findings: " + "; ".join(
            f"{f.get('what')} ({f.get('where')}, {f.get('width')}px)" for f in top))
    if report.get("next"):
        bits.append("Next moves: " + "; ".join(report["next"]))
    rv = report.get("revision") or {}
    if rv.get("kept"):
        bits.append(f"Revised by Chief ({rv.get('before_score')}→{rv.get('after_score')}): "
                    + "; ".join(rv.get("changes") or []) + ".")
    return " ".join(b for b in bits if b)
