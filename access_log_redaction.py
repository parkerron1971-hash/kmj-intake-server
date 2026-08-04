"""Keeping credentials that live in a URL path out of the server logs.

THE PROBLEM. Two route families carry a bearer credential as a path
segment, because both are opened by clicking a link and a link has
nowhere else to put one:

    /public/audit/{token}                       — auditor read links
    /public/store/download/{order}/{token}/{id} — customer file downloads

uvicorn's access log writes the full request path for every request, so
each of those requests deposited a complete, working credential into
Railway's log stream. For an audit link that credential is good for the
30–180 day window baked into its signature, and it grants exactly what
it was minted for: read access to a practice's action ledger.

The secure-headers work on the portal (no-store, no referrer,
frame-ancestors none) stopped the token leaking sideways to other
sites. It never touched our own logs, which is the copy that persists,
gets shipped to third-party log viewers, and outlives the session.

THE FIX is deliberately dumb: rewrite the credential out of the log
record before it is formatted. It runs at logging time rather than at
request time, so it catches the access log, anything that propagates to
the root handlers, and — via `scrub_sentry_event` — the error reports
too. Nothing upstream has to remember to be careful.

STILL NEEDED AFTER THE SESSION EXCHANGE. `/public/audit/{token}` is now
an entry route that trades the token for a cookie and redirects, so the
credential reaches us on exactly ONE request per session instead of
every page view and every download. One request is still one log line
holding a working credential, so this filter is what makes that hop
safe rather than merely rare. The store-download route has no such
exchange and relies on this outright.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

# Each pattern keeps the identifying prefix — the log is still useful for
# "how many auditors read the ledger today" — and destroys the secret.
# Written as a list so adding a route is one line, not a new mechanism.
_REDACTIONS = (
    # /public/audit/<token> and /public/audit/<token>/export
    re.compile(r"(/public/audit/)[^/?\s\"]+"),
    # /public/store/download/<order>/<token>/<offering>
    re.compile(r"(/public/store/download/[^/?\s\"]+/)[^/?\s\"]+"),
)

_MASK = r"\1<redacted>"


def redact(text: str) -> str:
    """The whole policy, in one testable function."""
    for rx in _REDACTIONS:
        text = rx.sub(_MASK, text)
    return text


class RedactCredentialPaths(logging.Filter):
    """Rewrites request paths in place as records pass through.

    uvicorn logs access lines as a format string plus an args tuple, so
    the path is an ARG, not the message — formatting has not happened
    yet when a filter runs. Every string arg is scanned rather than the
    known index, because that index is a uvicorn implementation detail
    and a version bump should not quietly reopen this.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.args, tuple):
                scrubbed = tuple(
                    redact(a) if isinstance(a, str) else a for a in record.args)
                if scrubbed != record.args:
                    record.args = scrubbed
            elif isinstance(record.args, dict):
                record.args = {
                    k: (redact(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()}
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
        except Exception:
            # A logging filter that raises can take down the handler and
            # with it every log line. Never worth it: pass the record
            # through unchanged and keep serving.
            pass
        return True


def install() -> None:
    """Attach the filter everywhere a request path can reach a log.

    Both hooks are needed. A filter on the `uvicorn.access` LOGGER runs
    for records logged through it; a filter on the root HANDLERS runs
    for everything that propagates up, including uvicorn configurations
    that do not use that logger name. Attaching twice is harmless — the
    substitution is idempotent, and `<redacted>` matches no pattern.
    """
    f = RedactCredentialPaths()
    for name in ("uvicorn.access", "gunicorn.access"):
        lg = logging.getLogger(name)
        if not any(isinstance(x, RedactCredentialPaths) for x in lg.filters):
            lg.addFilter(f)
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(x, RedactCredentialPaths) for x in handler.filters):
            handler.addFilter(f)


def scrub_sentry_event(event: Dict[str, Any], _hint: Any = None) -> Optional[Dict[str, Any]]:
    """`before_send` for sentry_sdk.

    `send_default_pii=False` withholds headers and cookies but NOT the
    request URL or the transaction name, and for these routes the URL
    IS the credential. Without this, turning error tracking on would
    ship live audit links to a third party.
    """
    try:
        req = event.get("request")
        if isinstance(req, dict):
            for key in ("url", "query_string"):
                if isinstance(req.get(key), str):
                    req[key] = redact(req[key])
        if isinstance(event.get("transaction"), str):
            event["transaction"] = redact(event["transaction"])
    except Exception:
        pass
    return event
