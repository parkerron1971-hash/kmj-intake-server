"""Legacy hand proposal parsing and historical frames; execution moved to errands.

The old screenshot/JSON loop is retired. New proposals create kind=portal errands
and use the shared browser controller. Historical jobs remain readable.
"""
from __future__ import annotations
import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
FRAME_BUCKET = 'proposals'

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
        "Chief records masked steps and stops outside the exact approved sites. "
        "Logins pause for Secure Entry; this portal task cannot make payments.",
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


def run(business_id,run_id,spec,*,progress_cb=None,**unused):
    """Do not reinterpret an old queued job as a new execution grant."""
    return {'ok':False,'stopped':'retired','summary':
        'Chief computer replaced the old hand. Review a new portal errand before running.',
        'steps':[],'frames':0,'run_id':run_id,'task':spec.get('task','')}

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
