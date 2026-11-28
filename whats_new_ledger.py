"""
whats_new_ledger.py: the old What's New list, kept flowing into the database.

Until every PR puts its update in its description (the rework's step 4),
PRs keep appending to the frontend's src/core/updates/whatsNew.ts. This reads
that file from GitHub (module-system, the server's own GITHUB_TOKEN), parses
the WHATS_NEW array and adds each entry the table doesn't have yet to
platform_updates as a published row with source 'ledger' (platform_updates.py).

    sync()                       every 15 minutes (scheduler), and the owner's
    POST /platform/updates/sync-ledger    "do it now" (the first import)

ADD, NEVER OVERWRITE. A row already in the table is left exactly as it is: once
Kevin edits or archives one in Mission Control, the file can't undo that. So
running this again is always safe.

OLD NEWS STAYS OLD (platform_updates.LEDGER_NEW_AFTER): an imported entry dated
on or before the cut-over day never counts as new, so the first import doesn't
hand every login a hundred-odd "new" updates. It is in the Updates list, not on
the card. An entry PRs add after that day is new as usual.

THE PARSER reads the one shape the file has: an array of object literals whose
keys are plain names and whose values are strings ('…', "…" or `…` with no ${})
or lists of strings, with // and /* */ comments between. Anything else stops the
parse with the line it was on; a sync that can't parse writes nothing.

Kill switch: WHATS_NEW_LEDGER_SYNC=off.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

import sb_clients

logger = logging.getLogger(__name__)

REPO = "parkerron1971-hash/solutionist-studio"
PATH = "src/core/updates/whatsNew.ts"
REF = "module-system"
BATCH = 200
LINE_MAX = 160

ID_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]{1,70}$")
PAGE_RE = re.compile(r"^[a-z0-9_-]{1,30}:[a-z0-9_-]{1,60}$")
KEY_RE = re.compile(r"^[a-z0-9_]{1,40}$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def on() -> bool:
    return (os.environ.get("WHATS_NEW_LEDGER_SYNC") or "on").strip().lower() != "off"


# ─── The parser ─────────────────────────────────────────────────────────

class LedgerParseError(ValueError):
    pass


_ESC = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0",
        "'": "'", '"': '"', "`": "`", "\\": "\\", "\n": ""}


class _Reader:
    def __init__(self, text: str, at: int):
        self.s, self.i = text, at

    def line(self) -> int:
        return self.s.count("\n", 0, self.i) + 1

    def fail(self, what: str) -> LedgerParseError:
        return LedgerParseError(f"whatsNew.ts line {self.line()}: {what}")

    def skip(self) -> None:
        """Whitespace and comments."""
        s = self.s
        while self.i < len(s):
            c = s[self.i]
            if c.isspace():
                self.i += 1
            elif s.startswith("//", self.i):
                nl = s.find("\n", self.i)
                self.i = len(s) if nl < 0 else nl + 1
            elif s.startswith("/*", self.i):
                end = s.find("*/", self.i + 2)
                if end < 0:
                    raise self.fail("a comment that never ends")
                self.i = end + 2
            else:
                return

    def peek(self) -> str:
        self.skip()
        return self.s[self.i] if self.i < len(self.s) else ""

    def take(self, ch: str) -> None:
        if self.peek() != ch:
            raise self.fail(f"expected {ch!r}, found {self.s[self.i:self.i + 12]!r}")
        self.i += 1

    def name(self) -> str:
        self.skip()
        m = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*").match(self.s, self.i)
        if not m:
            q = self.peek()
            if q in ("'", '"'):
                return self.string()
            raise self.fail("expected a key")
        self.i = m.end()
        return m.group(0)

    def string(self) -> str:
        self.skip()
        q = self.s[self.i]
        if q not in ("'", '"', "`"):
            raise self.fail("expected a string")
        self.i += 1
        out: List[str] = []
        s = self.s
        while True:
            if self.i >= len(s):
                raise self.fail("a string that never ends")
            c = s[self.i]
            if c == q:
                self.i += 1
                return "".join(out)
            if c == "\n" and q != "`":
                raise self.fail("a line break inside a string")
            if q == "`" and s.startswith("${", self.i):
                raise self.fail("a ${…} inside a template string")
            if c == "\\":
                nxt = s[self.i + 1] if self.i + 1 < len(s) else ""
                if nxt == "u":
                    if s.startswith("{", self.i + 2):
                        end = s.find("}", self.i + 3)
                        out.append(chr(int(s[self.i + 3:end], 16)))
                        self.i = end + 1
                    else:
                        code = int(s[self.i + 2:self.i + 6], 16)
                        self.i += 6
                        # A surrogate pair, as JavaScript writes characters past U+FFFF.
                        if 0xD800 <= code <= 0xDBFF and s.startswith("\\u", self.i):
                            low = int(s[self.i + 2:self.i + 6], 16)
                            if 0xDC00 <= low <= 0xDFFF:
                                code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
                                self.i += 6
                        out.append(chr(code))
                    continue
                if nxt == "x":
                    out.append(chr(int(s[self.i + 2:self.i + 4], 16)))
                    self.i += 4
                    continue
                out.append(_ESC.get(nxt, nxt))
                self.i += 2
                continue
            out.append(c)
            self.i += 1

    def value(self) -> Any:
        c = self.peek()
        if c in ("'", '"', "`"):
            return self.string()
        if c == "[":
            self.i += 1
            items: List[Any] = []
            while self.peek() != "]":
                items.append(self.string())
                if self.peek() == ",":
                    self.i += 1
            self.i += 1
            return items
        raise self.fail(f"an unexpected value {self.s[self.i:self.i + 12]!r}")

    def obj(self) -> Dict[str, Any]:
        self.take("{")
        out: Dict[str, Any] = {}
        while self.peek() != "}":
            key = self.name()
            self.take(":")
            out[key] = self.value()
            if self.peek() == ",":
                self.i += 1
        self.i += 1
        return out


def parse_ledger(text: str) -> List[Dict[str, Any]]:
    """The WHATS_NEW array of whatsNew.ts, as dicts, in file order."""
    m = re.search(r"export\s+const\s+WHATS_NEW\s*(?::[^=]+)?=\s*\[", text)
    if not m:
        raise LedgerParseError("whatsNew.ts: no WHATS_NEW array")
    r = _Reader(text, m.end())
    out: List[Dict[str, Any]] = []
    while r.peek() != "]":
        if not r.peek():
            raise r.fail("the array never ends")
        out.append(r.obj())
        if r.peek() == ",":
            r.i += 1
    return out


# ─── Entry → row ────────────────────────────────────────────────────────

def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def first_line(body: str) -> str:
    """The card's one line for an old entry, which had none: its first
    sentence, cut at a word under LINE_MAX letters."""
    text = _plain(body)
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    line = m.group(1) if m else text
    if len(line) > LINE_MAX:
        cut = line[:LINE_MAX - 1].rsplit(" ", 1)[0].rstrip(",;:")
        line = cut + "…"
    return line


def to_row(e: Dict[str, Any], now: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """The platform_updates row for one ledger entry, or why it was skipped."""
    uid, day = e.get("id"), e.get("date")
    if not isinstance(uid, str) or not ID_RE.match(uid):
        return None, f"bad id {uid!r}"
    if not isinstance(day, str) or not DATE_RE.match(day):
        return None, f"{uid}: bad date"
    title, body = _plain(e.get("title")), str(e.get("body") or "").strip()
    if not title:
        return None, f"{uid}: no title"
    page = e.get("page") if isinstance(e.get("page"), str) and PAGE_RE.match(e["page"]) else None
    keys = lambda k: [x for x in (e.get(k) or []) if isinstance(x, str) and KEY_RE.match(x)]  # noqa: E731
    return {
        "id": uid, "date": day, "status": "published", "source": "ledger",
        "area": (_plain(e.get("area")) or "Everywhere")[:40], "page": page,
        "kinds": keys("kinds"), "areas": keys("areas"), "roles": [], "weight": "normal",
        "title": title[:200], "line": first_line(body)[:300], "body": body[:6000],
        "published_at": now,
    }, None


# ─── The sync ───────────────────────────────────────────────────────────

def fetch_text() -> Optional[str]:
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    headers = {"Accept": "application/vnd.github.raw+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = httpx.get(f"https://api.github.com/repos/{REPO}/contents/{PATH}", params={"ref": REF},
                      headers=headers, timeout=httpx.Timeout(30.0))
    except httpx.HTTPError as e:
        logger.warning(f"[ledger] whatsNew.ts not read: {type(e).__name__}")
        return None
    if r.status_code != 200:
        logger.warning(f"[ledger] whatsNew.ts not read: {r.status_code}")
        return None
    return r.text


def sync(text: Optional[str] = None) -> Dict[str, Any]:
    """Add the entries the table doesn't have. {ok, read, added, skipped[], error?}"""
    if text is None:
        text = fetch_text()
        if text is None:
            return {"ok": False, "error": "whatsNew.ts couldn't be read"}
    try:
        entries = parse_ledger(text)
    except (LedgerParseError, ValueError) as e:
        return {"ok": False, "error": str(e)}
    now = datetime.now(timezone.utc).isoformat()
    rows: List[Dict[str, Any]] = []
    skipped: List[str] = []
    seen_ids = set()
    for e in entries:
        row, why = to_row(e, now)
        if row is None:
            skipped.append(why or "?")
        elif row["id"] in seen_ids:
            skipped.append(f"{row['id']}: listed twice")
        else:
            seen_ids.add(row["id"])
            rows.append(row)
    added = 0
    for i in range(0, len(rows), BATCH):
        res = sb_clients.sb_post_as_service(
            "/platform_updates?on_conflict=id", rows[i:i + BATCH],  # type: ignore[arg-type]
            prefer="resolution=ignore-duplicates,return=representation")
        if res is None:
            return {"ok": False, "read": len(entries), "added": added, "skipped": skipped,
                    "error": "the table refused the rows (is APPLY-2026-11-27-whats-new.sql applied?)"}
        added += len(res) if isinstance(res, list) else 0
    if added:
        import platform_updates
        platform_updates.forget_cache()
    return {"ok": True, "read": len(entries), "added": added, "skipped": skipped}


async def sync_tick() -> None:
    """The scheduler's 15-minute run. Quiet unless something was added or failed."""
    if not on():
        return
    import asyncio
    got = await asyncio.to_thread(sync)
    if not got.get("ok"):
        logger.warning(f"[ledger] sync failed: {got.get('error')}")
    elif got.get("added"):
        logger.info(f"[ledger] added {got['added']} of {got['read']} entries")
