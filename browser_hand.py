"""
browser_hand.py — a sandboxed browser Chief can use as a hand, only
where no integration exists.

WHY, AND WHY THIS NARROW. A general agent with computer use can do
anything on any site, which is exactly why it cannot be trusted with a
business's accounts. Solutionist will never build seventy integrations,
so the long tail — a state licensing portal, a supplier site with no
API, a client's insurance form — needs a hand. This is that hand, and
it is deliberately a poor general agent: it works one task, on the
domains the practitioner named, for a bounded number of steps, with
every frame recorded, and it refuses categorically to type where a
credential or a card number would go. Where an integration exists, the
integration is the door; this is not a substitute for one.

HOW A RUN HAPPENS
  1. Chief proposes (use_browser_hand, class C): the task, the start
     page, the allowed domains. The proposal lands in the Approval Queue
     as an agent_queue row on channel "hand". Nothing runs.
  2. The practitioner approves. _do_approve_one sees the channel and
     enqueues a chief_jobs job of kind "browser_hand" — the same job
     runner site builds use, heartbeat and orphan sweep included.
  3. run() drives a headless Chromium: screenshot → ask the model for
     ONE action as JSON → check it against the rules → do it → record
     the frame. Until the model says done, or the step budget, the time
     budget, or a rule stops it.
  4. Every frame is filed in the private storage bucket under the
     business, the steps and the outcome are the job's result, and a
     hand_run_completed event lands on the spine with the summary.

THE RULES (each one is a test)
  * Domains: every navigation, and the page's own URL after every
    action, must be on the allow-list (host or a subdomain of it).
    Off the list → the run stops and says so. Only https.
  * Credentials and payment: before typing, the focused element is
    inspected. A password field, a card/CVC/expiry/account-number
    field, or anything autocomplete'd as a credential is refused; the
    refusal is a recorded step and the model is told. The hand has no
    secrets to type anyway — it is never given any.
  * No downloads, no new tabs, no file uploads. The page is the sandbox.
  * Budgets: max_steps (default 12, ceiling 25) and a wall-clock
    budget (default 180s). Both stop the run with a named reason.
  * Recorded: one JPEG per step, before the action, plus the final
    frame. What the practitioner sees is what the hand saw.

DEPENDENCY INJECTION. run() takes `open_browser` and `ask` so the loop
is testable without Chromium or a model: the tests drive a fake page
and a scripted model through the exact same rules.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger("browser_hand")

MAX_STEPS_CEILING = 25
DEFAULT_MAX_STEPS = 12
DEFAULT_TIME_BUDGET_S = 180
VIEWPORT = {"width": 1280, "height": 800}
JPEG_QUALITY = 55

# Fields the hand will not type into, whatever the model says. Matched
# against the focused element's type / autocomplete / name / id / aria
# label. Broad on purpose: a false refusal costs one step; a true miss
# costs a credential.
_FORBIDDEN_INPUT_TYPES = {"password", "file"}
_FORBIDDEN_AUTOCOMPLETE = re.compile(r"^(cc-|current-password|new-password|one-time-code)")
_FORBIDDEN_NAME = re.compile(
    r"(passw|passcode|pin\b|otp|cvv|cvc|csc|card.?num|cardnumber|ccnum|expir|"
    r"routing|account.?num|iban|swift|ssn|social.?sec|tax.?id|ein\b|"
    r"secret|token|api.?key)", re.I)

_ACTIONS = {"click", "type", "press", "scroll", "goto", "done", "fail"}


# ─── The proposal ───────────────────────────────────────────────────────

def make_spec(task: str, start_url: str, domains: Optional[List[str]] = None,
              max_steps: Optional[int] = None) -> Dict[str, Any]:
    """Validate a proposal. Raises ValueError with a practitioner-readable
    reason. The allow-list is the start page's host plus whatever the
    practitioner named; www. and bare forms of a host are the same host."""
    task = (task or "").strip()
    if len(task) < 8:
        raise ValueError("say what the hand should do, in a sentence")
    if len(task) > 1200:
        raise ValueError("keep the task under 1,200 characters")
    u = urlparse((start_url or "").strip())
    if u.scheme != "https" or not u.netloc:
        raise ValueError("the start page must be an https:// address")
    hosts = {_norm_host(u.hostname or "")}
    for d in domains or []:
        h = _norm_host(str(d).strip().lower().replace("https://", "").replace("http://", "").split("/")[0])
        if h:
            hosts.add(h)
    hosts.discard("")
    steps = int(max_steps or DEFAULT_MAX_STEPS)
    steps = max(1, min(steps, MAX_STEPS_CEILING))
    return {"task": task, "start_url": start_url.strip(),
            "domains": sorted(hosts), "max_steps": steps,
            "time_budget_s": DEFAULT_TIME_BUDGET_S}


def _norm_host(h: str) -> str:
    h = (h or "").lower().strip(".")
    return h[4:] if h.startswith("www.") else h


def host_allowed(url: str, domains: List[str]) -> bool:
    """https only; host equals an allowed domain or is a subdomain of one."""
    try:
        u = urlparse(url)
    except Exception:
        return False
    if u.scheme != "https":
        return False
    h = _norm_host(u.hostname or "")
    if not h:
        return False
    for d in domains:
        d = _norm_host(d)
        if h == d or h.endswith("." + d):
            return True
    return False


def spec_to_body(spec: Dict[str, Any]) -> str:
    """The Approval Queue shows `body`. Plain words first, then the spec
    line the runner reads back (spec_from_body). Both are the same facts."""
    lines = [
        f"Task: {spec['task']}",
        f"Start at: {spec['start_url']}",
        f"Allowed sites: {', '.join(spec['domains'])}",
        f"Budget: up to {spec['max_steps']} steps, about {spec['time_budget_s'] // 60} minutes",
        "",
        "The hand records every screen it sees, never types passwords or "
        "card numbers, and stops the moment it leaves the allowed sites.",
        "",
        "spec: " + json.dumps(spec, separators=(",", ":")),
    ]
    return "\n".join(lines)


def spec_from_body(body: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"^spec:\s*(\{.*\})\s*$", body or "", re.M)
    if not m:
        return None
    try:
        spec = json.loads(m.group(1))
    except Exception:
        return None
    try:
        return make_spec(spec.get("task", ""), spec.get("start_url", ""),
                         spec.get("domains") or [], spec.get("max_steps"))
    except ValueError:
        return None


# ─── The model ──────────────────────────────────────────────────────────

_SYSTEM = """You are a careful hand operating a web browser for a small business owner, one action at a time.
You will be shown a screenshot ({w}x{h}) and the task. Reply with ONE JSON object and nothing else:
  {{"action":"click","x":<int>,"y":<int>,"why":"..."}}
  {{"action":"type","text":"...","why":"..."}}          (types into the focused field; click a field first)
  {{"action":"press","key":"Enter"|"Tab"|"Escape"|"ArrowDown"...,"why":"..."}}
  {{"action":"scroll","dy":<int px, + is down>,"why":"..."}}
  {{"action":"goto","url":"https://...","why":"..."}}     (only within the allowed sites)
  {{"action":"done","summary":"what was accomplished, what the screen shows now"}}
  {{"action":"fail","reason":"why this cannot be completed"}}
Rules you must follow:
- Only the allowed sites: {domains}. Never navigate elsewhere.
- Never type a password, a card number, a CVC, a bank account, an SSN or any code. If the task needs one, reply fail and say so.
- Never buy, pay, sign, submit a legally binding form, or delete anything unless the task says exactly that.
- Prefer reading over acting: when the task is to find information, stop with done and put the information in the summary.
- One action per reply. If the last action did not work, try a different one; do not repeat it.
Task: {task}"""


def _ask_anthropic(spec: Dict[str, Any], frame_jpeg: bytes, history: List[Dict[str, Any]],
                   business_id: str = "") -> Dict[str, Any]:
    """One decision from the model. Returns the parsed action dict, or a
    fail action when the model cannot be reached or does not answer in
    the shape asked for."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {"action": "fail", "reason": "the model is not configured"}
    import llm_call
    content: List[Dict[str, Any]] = []
    if history:
        content.append({"type": "text", "text": "Steps so far:\n" + "\n".join(
            f"{i + 1}. {_describe(h)}" for i, h in enumerate(history[-10:]))})
    content.append({"type": "image", "source": {
        "type": "base64", "media_type": "image/jpeg",
        "data": base64.b64encode(frame_jpeg).decode()}})
    content.append({"type": "text", "text": "Current screen above. Next action as JSON only."})
    model = (os.environ.get("HAND_MODEL") or "").strip()
    if not model:
        try:
            import chief_models
            model = chief_models.model_for("chat")
        except Exception:
            model = "claude-sonnet-5"
    client = llm_call.sdk_client(key=key, task="browser_hand")
    try:
        msg = client.messages.create(
            model=model, max_tokens=300,
            system=_SYSTEM.format(w=VIEWPORT["width"], h=VIEWPORT["height"],
                                  domains=", ".join(spec["domains"]), task=spec["task"]),
            messages=[{"role": "user", "content": content}], timeout=60.0)
    except Exception as e:
        return {"action": "fail", "reason": f"the model did not answer ({type(e).__name__})"}
    try:
        import api_usage_logger
        u = getattr(msg, "usage", None)
        api_usage_logger.log_api_usage_sync(
            endpoint="browser_hand", model=getattr(msg, "model", model),
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            business_id=business_id or None)
    except Exception:
        pass
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    return parse_action(text)


def parse_action(text: str) -> Dict[str, Any]:
    """The model's reply → an action dict. Tolerates code fences and
    prose around the object; anything unparseable is a fail action so a
    confused model cannot make the hand do something it did not say."""
    t = (text or "").strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return {"action": "fail", "reason": "the model did not give an action"}
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return {"action": "fail", "reason": "the model's action was not valid JSON"}
    if not isinstance(obj, dict) or obj.get("action") not in _ACTIONS:
        return {"action": "fail", "reason": "the model asked for an action the hand does not have"}
    return obj


def _describe(step: Dict[str, Any]) -> str:
    a = step.get("action") or {}
    kind = a.get("action")
    note = step.get("note") or ""
    if kind == "click":
        s = f"clicked at ({a.get('x')},{a.get('y')})"
    elif kind == "type":
        s = f"typed {len(str(a.get('text') or ''))} characters"
    elif kind == "press":
        s = f"pressed {a.get('key')}"
    elif kind == "scroll":
        s = f"scrolled {a.get('dy')}px"
    elif kind == "goto":
        s = f"went to {a.get('url')}"
    else:
        s = str(kind)
    if a.get("why"):
        s += f" — {a['why']}"
    return s + (f" [{note}]" if note else "")


# ─── The browser ────────────────────────────────────────────────────────

class _PlaywrightPage:
    """The thin surface run() needs from a page. Real Chromium behind
    open_browser(); the tests supply a fake with the same five methods."""

    def __init__(self, page, browser, pw):
        self._page, self._browser, self._pw = page, browser, pw

    def url(self) -> str:
        return self._page.url

    def goto(self, url: str) -> None:
        self._page.goto(url, wait_until="domcontentloaded", timeout=20000)

    def screenshot(self) -> bytes:
        return self._page.screenshot(type="jpeg", quality=JPEG_QUALITY)

    def focused_field(self) -> Dict[str, str]:
        try:
            return self._page.evaluate("""() => {
                const e = document.activeElement; if (!e) return {};
                return {tag: (e.tagName||'').toLowerCase(), type: (e.getAttribute('type')||'').toLowerCase(),
                        autocomplete: (e.getAttribute('autocomplete')||'').toLowerCase(),
                        name: (e.getAttribute('name')||''), id: (e.id||''),
                        label: (e.getAttribute('aria-label')||''), placeholder: (e.getAttribute('placeholder')||'')};
            }""") or {}
        except Exception:
            return {}

    def act(self, action: Dict[str, Any]) -> None:
        kind = action["action"]
        p = self._page
        if kind == "click":
            p.mouse.click(int(action["x"]), int(action["y"]))
        elif kind == "type":
            p.keyboard.type(str(action.get("text") or ""), delay=15)
        elif kind == "press":
            p.keyboard.press(str(action.get("key") or "Enter"))
        elif kind == "scroll":
            p.mouse.wheel(0, int(action.get("dy") or 400))
        try:
            p.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        p.wait_for_timeout(600)

    def close(self) -> None:
        for closer in (self._browser.close, self._pw.stop):
            try:
                closer()
            except Exception:
                pass


def open_chromium():
    """Headless Chromium with downloads, popups and uploads shut. None when
    Playwright is not installed (the run reports it; nothing crashes)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    pw = sync_playwright().start()
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport=VIEWPORT, accept_downloads=False,
                              java_script_enabled=True)
    page = ctx.new_page()
    # A popup is a second tab the practitioner never sees; close it.
    ctx.on("page", lambda p: p != page and p.close())
    page.on("filechooser", lambda fc: None)   # never picks a file
    return _PlaywrightPage(page, browser, pw)


# ─── Recording ──────────────────────────────────────────────────────────

FRAME_BUCKET = "proposals"   # the private, business-scoped bucket (contract_agent uses it)


def _store_frame(business_id: str, run_id: str, n: int, jpeg: bytes) -> Optional[str]:
    """Upload one frame under the business; return its storage path (the
    reader signs a URL when it wants to look). Never raises."""
    try:
        import httpx
        import storage_links
        base = os.environ.get("SUPABASE_URL", "").rstrip("/")
        if not base:
            return None
        path = f"{business_id}/hand/{run_id}/{n:02d}.jpg"
        headers = {**storage_links.service_headers(), "Content-Type": "image/jpeg",
                   "x-upsert": "true"}
        with httpx.Client(timeout=30.0) as c:
            r = c.post(f"{base}/storage/v1/object/{FRAME_BUCKET}/{path}",
                       headers=headers, content=jpeg)
        if r.status_code >= 400:
            logger.warning(f"[hand] frame upload {path}: {r.status_code} {r.text[:120]}")
            return None
        return path
    except Exception as e:
        logger.warning(f"[hand] frame upload failed: {e}")
        return None


def forbidden_field(field: Dict[str, str]) -> Optional[str]:
    """Why the hand will not type here, or None when it may."""
    if not field:
        return None
    if (field.get("type") or "") in _FORBIDDEN_INPUT_TYPES:
        return f"a {field['type']} field"
    if _FORBIDDEN_AUTOCOMPLETE.match(field.get("autocomplete") or ""):
        return "a credential or card field"
    for k in ("name", "id", "label", "placeholder"):
        if _FORBIDDEN_NAME.search(field.get(k) or ""):
            return "a field that looks like a credential, card or account number"
    return None


# ─── The run ────────────────────────────────────────────────────────────

def run(business_id: str, run_id: str, spec: Dict[str, Any], *,
        open_browser: Callable[[], Any] = open_chromium,
        ask: Optional[Callable[..., Dict[str, Any]]] = None,
        store_frame: Callable[..., Optional[str]] = _store_frame,
        progress_cb: Optional[Callable[[str], None]] = None,
        clock: Callable[[], float] = time.monotonic) -> Dict[str, Any]:
    """Drive one task to its end. Always returns a result dict; never
    raises for anything the hand itself can name:

      { ok, stopped: done|failed|off_domain|max_steps|time_budget|
             no_browser|refused, summary, steps: [{n, url, action, note,
             frame}], frames: int, run_id }
    """
    spec = make_spec(spec.get("task", ""), spec.get("start_url", ""),
                     spec.get("domains") or [], spec.get("max_steps"))
    ask = ask or (lambda s, f, h: _ask_anthropic(s, f, h, business_id=business_id))
    steps: List[Dict[str, Any]] = []
    frames = 0
    started = clock()
    budget = float(spec.get("time_budget_s") or DEFAULT_TIME_BUDGET_S)

    def _done(stopped: str, summary: str, ok: bool) -> Dict[str, Any]:
        return {"ok": ok, "stopped": stopped, "summary": summary, "steps": steps,
                "frames": frames, "run_id": run_id, "domains": spec["domains"],
                "task": spec["task"], "finished_at": datetime.now(timezone.utc).isoformat()}

    page = open_browser()
    if page is None:
        return _done("no_browser", "The browser is not available on this server.", False)
    try:
        if not host_allowed(spec["start_url"], spec["domains"]):
            return _done("off_domain", "The start page is not on the allowed sites.", False)
        try:
            page.goto(spec["start_url"])
        except Exception as e:
            return _done("failed", f"Could not open the start page ({type(e).__name__}).", False)

        for n in range(1, spec["max_steps"] + 1):
            if clock() - started > budget:
                return _done("time_budget", "Ran out of time before finishing.", False)
            url = page.url()
            if not host_allowed(url, spec["domains"]):
                return _done("off_domain", f"Stopped: the page moved to {urlparse(url).hostname}, which is not on the allowed sites.", False)
            jpeg = page.screenshot()
            frame = store_frame(business_id, run_id, n, jpeg)
            frames += 1 if frame else 0
            if progress_cb:
                try:
                    progress_cb(f"step {n} of {spec['max_steps']}")
                except Exception:
                    pass

            action = ask(spec, jpeg, steps)
            kind = action.get("action")
            step = {"n": n, "url": url, "action": action, "note": None, "frame": frame}
            steps.append(step)

            if kind == "done":
                return _done("done", str(action.get("summary") or "Done."), True)
            if kind == "fail":
                return _done("failed", str(action.get("reason") or "The hand could not finish."), False)
            if kind == "goto":
                target = str(action.get("url") or "")
                if not host_allowed(target, spec["domains"]):
                    step["note"] = "refused: not on the allowed sites"
                    continue
                try:
                    page.goto(target)
                except Exception as e:
                    step["note"] = f"could not open ({type(e).__name__})"
                continue
            if kind == "type":
                why = forbidden_field(page.focused_field())
                if why:
                    step["note"] = f"refused: will not type into {why}"
                    continue
            try:
                page.act(action)
            except Exception as e:
                step["note"] = f"did not work ({type(e).__name__})"
        # the budget ran out with the model still acting — record the last frame
        try:
            jpeg = page.screenshot()
            if store_frame(business_id, run_id, spec["max_steps"] + 1, jpeg):
                frames += 1
        except Exception:
            pass
        return _done("max_steps", f"Stopped after {spec['max_steps']} steps without finishing.", False)
    finally:
        try:
            page.close()
        except Exception:
            pass


def frame_urls(business_id: str, result: Dict[str, Any], ttl_s: int = 3600) -> List[str]:
    """Signed links for a run's frames, for the practitioner's eyes only."""
    try:
        import storage_links
    except Exception:
        return []
    out = []
    for s in result.get("steps") or []:
        p = s.get("frame")
        if p:
            u = storage_links.signed_url_sync(FRAME_BUCKET, p, ttl=ttl_s)
            if u:
                out.append(u)
    return out
