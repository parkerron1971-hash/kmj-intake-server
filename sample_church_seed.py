"""
sample_church_seed.py — the sample church gets its records (BE-2, 2026-11-15).

BE-1 (sample_church.py) makes the sample's `businesses` row; this fills it.
sample_church_data.build() says WHAT Grace Street Fellowship holds (pure, no
I/O); this writes it, once, safely:

  provision(sample, home)   sample_church.seed_hook. ensure() calls it on
                            every /billing/access load, so it answers in no
                            time (and with no read) unless the sample is due.
  due(sample)               sample_church.seed_due: why this sample needs
                            seeding now, or None.

WHEN A SAMPLE IS DUE
  pending   just made (BE-1's marker).
  seeding   claimed, but the claim is older than STALE_CLAIM_S: the seeder
            died (a deploy cut it short). Taken over.
  failed    the last run failed; tried again after a backoff that doubles
            with each attempt (RETRY_BASE_S .. RETRY_MAX_S).
  ready     the seed's VERSION changed, it is older than MAX_AGE_DAYS, or
            the church's week or month turned since (its "last Sunday" or
            "this month" would now read empty). Re-seeded in place.
  ending    never (sample_church.end() is deleting it).

ONE SEEDER, EVER
  The claim is a conditional PATCH: businesses?id=<sample>&is_sample=is.true
  &settings->sample_church->>status=eq.<what we read>[&...->>run=eq.<run>],
  setting status "seeding" with a fresh run id. Postgres re-checks the WHERE
  on a row a racing UPDATE just changed, so of two loads (on any replicas)
  exactly one gets the row back; the other sees [] and leaves. The winner
  checks the claim is still its own before each table and stops if not (a
  takeover, or end() marked it "ending").

RESTARTABLE, AND ONE PATH FOR ALL OF IT (write())
  A first seed, a refresh and a retry after a crash are the same pass, after
  re-reading the row and confirming it IS a sample and is not its home:
  every row of the sample's in the rewritten tables is deleted (scoped by
  business_id=<the sample> and nothing else) and written again; in the four
  stable tables (contacts, giving_services, giving_counts, invoices) only the
  rows no longer wanted are deleted, by id and still by business_id, the
  people and counts are upserted and only missing gifts inserted. The ids
  are uuid5(sample id, what), so a run is the same rows every time; a gift's
  id is its own content, and a gift depends only on its own date.
  WHY THE GIFTS ARE KEPT: deleting an invoice writes the tamper-evident
  audit_log (audit_invoices_delete) and the GL queue (gl_enq_invoices_ins).
  A weekly wipe would write ~2,000 audit rows a week per sample; this way a
  refresh removes only the gifts that passed a year. The GL drain skips a
  sample's queue rows (gl_engine.process_queue): a made-up church keeps no
  books, so no chart of accounts or journal entries are ever made for it.

QUIET BY CONSTRUCTION
  The sample's settings switch every send off (sample_church_data.settings),
  rows the hourly sweeps would pick up are stamped as already told (tasks,
  serving, posts, follow-ups past the late ladder, events handled, the
  shepherding sweep's Monday notes), and nothing is written to a table that
  sends or schedules work (FORBIDDEN_TABLES; a test pins it). BE-3 adds the
  guards on every path; until it lands, no tester should be listed.

THE SWITCH — SAMPLE_CHURCH_SEED:
  on    (default) seed in a background thread; the load answers at once and
        the app's "Setting up Grace Street Fellowship" screen asks again.
  sync  seed in the caller's thread (scripts, a run-through).
  off   never seed (the sample stays pending). The tests' default.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import sb_clients
import sample_church_data as data_mod

logger = logging.getLogger("sample_church_seed")

# sample_church imports this module at its foot (seed_hook / seed_due), so
# this one never imports it at the top: the key is the same constant, and
# the version is read from it when needed.
KEY = "sample_church"           # == sample_church.SETTINGS_KEY (a test pins it)
STALE_CLAIM_S = 600            # a seed takes about a minute; ten is a dead one
MAX_AGE_DAYS = 6
RETRY_BASE_S = 120
RETRY_MAX_S = 1800
CHUNK = 400                    # rows per bulk insert
DELETE_PAGE = 80               # ids per delete (they ride in the URL)
DEFAULT_TZ = "America/New_York"
_MODES = ("on", "sync", "off")

# Tables the seed must never write: each one sends, schedules or spends
# (texts, emails, pushes, Chief's timed actions, journeys, agents).
FORBIDDEN_TABLES = (
    "chief_scheduled_actions", "campaign_sends", "campaigns", "devotional_texts",
    "member_push_subscriptions", "member_push_sends", "member_push_held", "push_subscriptions",
    "journey_sends", "workflow_runs", "rule_runs", "agent_queue", "agent_runs",
    "agent_assignments", "connected_agents", "lifecycle_email_deliveries", "giving_statement_sends",
    "sms_messages", "sms_numbers", "sms_bindings", "sms_consents", "sms_keywords", "sms_opt_outs",
    "texting_registrations", "church_mail", "church_mailboxes", "email_replies", "invite_tokens",
    "business_users", "member_login_codes", "chief_jobs", "chief_errands", "gl_sync_queue",
)

# This process's seeds in flight (one thread per sample here; the claim
# keeps the other replicas out).
_RUNNING: set = set()
_RUNNING_LOCK = threading.Lock()


class SeedError(RuntimeError):
    """A write the seed needed came back refused or short."""


class Superseded(RuntimeError):
    """The claim is no longer ours (taken over, or the sample is ending)."""


def version() -> int:
    """The seed's version (sample_church.SEED_VERSION): a ready sample made
    by another version is seeded again."""
    import sample_church
    return sample_church.SEED_VERSION


def mode() -> str:
    raw = (os.environ.get("SAMPLE_CHURCH_SEED") or "on").strip().lower()
    return raw if raw in _MODES else "off"


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _marker(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    m = ((row or {}).get("settings") or {}).get(KEY)
    return dict(m) if isinstance(m, dict) else {}


def _zone(name: Any) -> Optional[ZoneInfo]:
    try:
        return ZoneInfo(str(name)) if name else None
    except Exception:  # noqa: BLE001 — an unknown name is no clock
        return None


def anchor(today: date) -> str:
    """The church week and month a seed was made for: its last Sunday and
    this month. When either turns, last Sunday and this month's giving would
    read empty, so the sample is seeded again."""
    return f"{data_mod.last_sunday(today).isoformat()}/{today.strftime('%Y-%m')}"


def retry_after_s(attempts: int) -> int:
    return int(min(RETRY_MAX_S, RETRY_BASE_S * (2 ** max(0, int(attempts or 1) - 1))))


def due(sample_row: Optional[Dict[str, Any]], now: Optional[datetime] = None) -> Optional[str]:
    """Why this sample needs seeding now (pending, stale_claim, retry,
    version, age, week), or None. Reads nothing: the row in hand decides,
    so ensure() pays nothing for a sample that is fine."""
    if not sample_row or sample_row.get("is_sample") is not True:
        return None
    now = now or _now()
    m = _marker(sample_row)
    status = str(m.get("status") or "pending")
    if status == "pending":
        return "pending"
    if status == "seeding":
        at = _parse(m.get("claimed_at"))
        return "stale_claim" if at is None or (now - at).total_seconds() > STALE_CLAIM_S else None
    if status == "failed":
        at = _parse(m.get("failed_at"))
        wait = retry_after_s(int(m.get("attempts") or 1))
        return "retry" if at is None or (now - at).total_seconds() >= wait else None
    if status == "ready":
        if m.get("version") != version():
            return "version"
        at = _parse(m.get("seeded_at"))
        if at is None or now - at > timedelta(days=MAX_AGE_DAYS):
            return "age"
        zone = _zone(m.get("tz"))
        if m.get("anchor") and zone is not None and m["anchor"] != anchor(now.astimezone(zone).date()):
            return "week"
        return None
    return None   # ending, or a status this seed never writes


# ─── The claim ────────────────────────────────────────────────────────

_ROW_SELECT = "id,owner_id,name,type,settings,is_active,is_sample,sample_of"


def _read(sample_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{_q(sample_id)}&is_sample=is.true&select={_ROW_SELECT}&limit=1")
    if not isinstance(rows, list) or not rows:
        return None
    return rows[0]


def _is_a_sample(row: Optional[Dict[str, Any]]) -> bool:
    """Only ever seed (and so delete inside) a row that IS a sample of some
    other business."""
    return bool(row and row.get("is_sample") is True and row.get("id")
                and row.get("sample_of") and str(row["sample_of"]) != str(row["id"]))


def _where(sample_id: str, m: Dict[str, Any]) -> str:
    """The claim's WHERE: this sample, still a sample, still in the state we read."""
    status = str(m.get("status") or "pending")
    path = (f"/businesses?id=eq.{_q(sample_id)}&is_sample=is.true"
            f"&settings->{KEY}->>status=eq.{_q(status)}")
    if m.get("run"):
        path += f"&settings->{KEY}->>run=eq.{_q(m['run'])}"
    return path


def _patch_marker(row: Dict[str, Any], where_marker: Dict[str, Any], new_marker: Dict[str, Any],
                  extra: Optional[Dict[str, Any]] = None) -> bool:
    """Write settings.sample_church (and `extra` settings keys) only while the
    marker still reads `where_marker`. True when this call changed the row."""
    settings = dict(row.get("settings") or {})
    if extra:
        settings.update(extra)
    settings[KEY] = new_marker
    got = sb_clients.sb_patch_as_service(_where(str(row["id"]), where_marker), {"settings": settings})
    return isinstance(got, list) and len(got) == 1


def claim(row: Dict[str, Any], run: str, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Mark the sample "seeding" for `run`, or None when another seeder got
    there first. Keeps the slug a sample already has (its site's address)."""
    now = now or _now()
    m = _marker(row)
    # Every key this seed doesn't own is kept (BE-3's last_seen_at, which the
    # daily cleanup measures idle from; created_at).
    new = {**m, "version": version(), "status": "seeding", "run": run,
           "claimed_at": now.isoformat(), "attempts": int(m.get("attempts") or 0) + 1,
           "slug": m.get("slug") or f"sample-{secrets.token_hex(5)}"}
    for k in ("error", "failed_at"):
        new.pop(k, None)
    return new if _patch_marker(row, m, new) else None


def _still_mine(sample_id: str, run: str) -> Dict[str, Any]:
    row = _read(sample_id)
    m = _marker(row)
    if not row or m.get("run") != run or m.get("status") != "seeding":
        raise Superseded(f"{str(sample_id)[:8]} is no longer this run's to seed")
    return row


# ─── Clearing and writing ─────────────────────────────────────────────

def _key_of(table: str) -> str:
    return data_mod.TABLE_KEYS.get(table, "id")


def _guard(table: str) -> None:
    if table in FORBIDDEN_TABLES or table not in data_mod.TABLES:
        raise SeedError(f"refusing to touch {table}")


def clear(sample_id: str, tables: List[str]) -> int:
    """Delete the sample's own rows from `tables`, children first. Scoped by
    business_id=<the sample> and nothing else; the caller has just re-read
    the row and confirmed it is a sample (never its home)."""
    sid = str(sample_id)
    n = 0
    for table in reversed(tables):
        _guard(table)
        if not sb_clients.sb_delete_as_service(f"/{table}?business_id=eq.{_q(sid)}"):
            raise SeedError(f"clearing {table} failed")
        n += 1
    return n


def ids_of(sample_id: str, table: str) -> set:
    """The ids the sample already has in a stable table (every one, paged)."""
    _guard(table)
    rows = sb_clients.sb_get_all_as_service(f"/{table}?business_id=eq.{_q(sample_id)}&select=id", strict=True)
    return {str(r["id"]) for r in rows or []}


def drop_ids(sample_id: str, table: str, ids: List[str]) -> int:
    """Delete these rows of the sample's, by id, a page at a time. Still
    scoped by business_id=<the sample>, so an id can never reach another
    business's row."""
    _guard(table)
    ids = sorted(str(i) for i in ids)
    for i in range(0, len(ids), DELETE_PAGE):
        page = ",".join(_q(x) for x in ids[i:i + DELETE_PAGE])
        if not sb_clients.sb_delete_as_service(f"/{table}?business_id=eq.{_q(sample_id)}&id=in.({page})"):
            raise SeedError(f"removing old rows from {table} failed")
    return len(ids)


def _uniform(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """PostgREST's bulk insert needs every object to carry the same keys
    (PGRST102: "All object keys must match"), or the whole chunk is lost."""
    keys = sorted({k for r in rows for k in r})
    return [{k: r.get(k) for k in keys} for r in rows]


def insert(table: str, rows: List[Dict[str, Any]], *, upsert: bool = False) -> int:
    """Bulk insert (or upsert by id) in chunks; every chunk must come back whole."""
    _guard(table)
    key = _key_of(table)
    prefer = "resolution=merge-duplicates,return=representation" if upsert else "return=representation"
    done = 0
    for i in range(0, len(rows), CHUNK):
        chunk = _uniform(rows[i:i + CHUNK])
        path = f"/{table}?select={key}" + ("&on_conflict=id" if upsert else "")
        got = sb_clients.sb_post_as_service(path, chunk, prefer=prefer)
        if not isinstance(got, list) or len(got) != len(chunk):
            err = sb_clients.last_error() or {}
            raise SeedError(f"{table} rows {i}..{i + len(chunk)}: {err.get('code') or 'no answer'} "
                            f"{str(err.get('message') or '')[:160]}")
        done += len(chunk)
    return done


def write(sample_id: str, run: str, built: Dict[str, Any]) -> Dict[str, int]:
    """Make the sample's tables say what `built` says, in one pass that is
    the same for a first seed, a refresh and a retry after a crash:

      1. delete every row of the sample's in the rewritten tables, children
         first (all but STABLE_TABLES);
      2. in the stable tables, delete only the rows that are no longer
         wanted (a gift that passed a year, a person a new seed version
         dropped), gifts before their counts before the people;
      3. write, parents first: the people and the counts by upsert, gifts
         only where they are missing, everything else fresh.

    A gift is never rewritten: it is either the same row (left alone) or a
    new one, so a weekly refresh writes the audit log only for the gifts it
    really removes. The claim is checked before each table."""
    tables = [t for t, _ in built["tables"]]
    want = {t: rows for t, rows in built["tables"]}
    stable = [t for t in tables if t in data_mod.STABLE_TABLES]
    _still_mine(sample_id, run)
    clear(sample_id, [t for t in tables if t not in data_mod.STABLE_TABLES])
    have: Dict[str, set] = {}
    removed = 0
    for table in reversed(stable):
        _still_mine(sample_id, run)
        have[table] = ids_of(sample_id, table)
        gone = have[table] - {str(r["id"]) for r in want[table]}
        removed += drop_ids(sample_id, table, list(gone))
        have[table] -= gone
    counts: Dict[str, int] = {"_removed": removed}
    for table in tables:
        _still_mine(sample_id, run)
        rows = want[table]
        if table == "invoices":
            rows = [r for r in rows if str(r["id"]) not in have[table]]
            counts[table] = insert(table, rows)
        elif table in data_mod.STABLE_TABLES:
            counts[table] = insert(table, rows, upsert=True)
        else:
            counts[table] = insert(table, rows)
    return counts


# ─── The website ──────────────────────────────────────────────────────

STATIC = Path(__file__).resolve().parent / "static" / "sample_church"
PHOTO_ROUTE = "/assets/sample-church"
_PHOTO_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def public_base() -> str:
    return (os.environ.get("PUBLIC_BASE_URL") or os.environ.get("RAILWAY_PUBLIC_URL")
            or "https://kmj-intake-server-production.up.railway.app").rstrip("/")


def photos_on_disk(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The fixture's photos whose file is really there. A missing one is left
    out, never shown broken: the site is whole with none."""
    return [p for p in cfg.get("photos") or []
            if _PHOTO_NAME.match(str(p.get("name") or "")) and (STATIC / f"{p['name']}.jpg").is_file()]


def credits(photos: List[Dict[str, Any]]) -> str:
    names = sorted({str(p["photographer"]) for p in photos})
    if not names:
        return ""
    who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"Photos by {who} on Unsplash."


_NOINDEX = '<meta name="robots" content="noindex,nofollow,noarchive">'
_BANNER = ('<div role="note" style="position:relative;z-index:50;background:#d9a84e;color:#14110b;'
           'font:500 13px/1.4 Inter,system-ui,sans-serif;text-align:center;padding:8px 16px">'
           'A made-up sample church. Nothing here is real, and nothing you send from it goes anywhere.</div>')


def site_html(cfg: Dict[str, Any], today: date, tz: str) -> str:
    """The sample's website, from the site kit's bulletin layout: the
    fixture's words and facts, the photos that are on disk (with their
    credits in the footer), marked noindex, with a "made-up" note on top."""
    import copy
    import site_kit
    photos = photos_on_disk(cfg)
    base = public_base()
    gallery = [{"url": f"{base}{PHOTO_ROUTE}/{p['name']}.jpg", "alt": p.get("alt") or ""} for p in photos]
    facts = cfg.get("facts") or {}
    fx = {"business": {"name": data_mod.NAME, "type": "church"}, "contact": facts.get("contact") or {},
          "gallery": gallery, "events": facts.get("events") or [], "ministries": facts.get("ministries") or [],
          "testimonials": [], "practitioner_name": f"Pastor {data_mod.PASTOR}",
          "discovery_dossier": {"identity": {"team": facts.get("team") or []}}, "year": str(today.year)}
    w = copy.deepcopy(cfg.get("words") or {})
    w["layout"] = cfg.get("layout") or "bulletin"
    w["tz"] = tz
    w.setdefault("album", {})["captions"] = {g["url"]: p.get("caption") or "" for g, p in zip(gallery, photos)}
    line = " ".join(x for x in ((w.get("footer") or {}).get("line"), credits(photos)) if x)
    w.setdefault("footer", {})["line"] = line
    html = site_kit.assemble(fx, w, layout=w["layout"])
    html = html.replace("<head>", "<head>" + _NOINDEX, 1)
    return re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + _BANNER, html, count=1)


# ─── One run ──────────────────────────────────────────────────────────

def _tz(row: Dict[str, Any], home: Optional[Dict[str, Any]]) -> str:
    """The church's clock: the sample's own (BE-1 copied the home's), the
    home's, the owner's profile (business_marketing.business_tz), else Eastern."""
    for src in (row, home or {}):
        s = src.get("settings") if isinstance(src.get("settings"), dict) else {}
        av = s.get("availability") if isinstance(s.get("availability"), dict) else {}
        for name in (av.get("timezone"), s.get("timezone"), s.get("tz")):
            if _zone(name):
                return str(name)
    try:
        import business_marketing
        z = business_marketing.business_tz({**row, "settings": {}})
        if z and str(z) != "UTC":
            return str(z)
    except Exception:  # noqa: BLE001 — a clock we can't read is Eastern
        pass
    return DEFAULT_TZ


def prepare(sample_id: str, slug: str, tz: str, today: date) -> Dict[str, Any]:
    """build(), plus the site's HTML (the one part that reads files)."""
    built = data_mod.build(today=today, tz=tz, business_id=sample_id, slug=slug)
    for table, rows in built["tables"]:
        if table == "business_sites":
            for r in rows:
                r["html_content"] = site_html(r["site_config"], today, tz)
    return built


def run_seed(sample_row: Dict[str, Any], home_row: Optional[Dict[str, Any]] = None,
             *, now: Optional[datetime] = None) -> str:
    """Claim and seed one sample, in this thread. Answers what happened:
    ready | not_due | taken | refused | superseded | failed. Never raises."""
    sid = str((sample_row or {}).get("id") or "")
    run = uuid.uuid4().hex
    try:
        fresh = _read(sid) if sid else None
        if not _is_a_sample(fresh):
            logger.warning(f"[sample] seed refused for {sid[:8]}: not a sample")
            return "refused"
        if home_row and str(home_row.get("id") or "") == sid:
            return "refused"
        why = due(fresh, now)
        if not why:
            return "not_due"
        mine = claim(fresh, run, now)
        if not mine:
            return "taken"
        print(f"[sample] seeding {sid[:8]} ({why}, run {run[:8]})", flush=True)
        started = time.monotonic()
        tz = _tz(fresh, home_row)
        today = (now or _now()).astimezone(ZoneInfo(tz)).date()
        built = prepare(sid, mine["slug"], tz, today)
        counts = write(sid, run, built)
        row = _still_mine(sid, run)
        now_marker = _marker(row)
        ready = {**now_marker, "version": version(), "status": "ready", "run": run, "slug": mine["slug"],
                 "seeded_at": _now().isoformat(), "tz": tz, "anchor": anchor(today),
                 "today": today.isoformat(), "digest": built["digest"], "counts": counts, "attempts": 0}
        ready.pop("claimed_at", None)
        if not _patch_marker(row, now_marker, ready, extra=built["settings"]):
            raise Superseded("the ready marker lost its race")
        print(f"[sample] seeded {sid[:8]}: {sum(v for k, v in counts.items() if not k.startswith('_'))} rows "
              f"written in {time.monotonic() - started:.1f}s", flush=True)
        return "ready"
    except Superseded as e:
        print(f"[sample] seed of {sid[:8]} stopped: {e}", flush=True)
        return "superseded"
    except Exception as e:  # noqa: BLE001 — a failed seed is retried, never raised
        print(f"[sample] seed of {sid[:8]} failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
        _mark_failed(sid, run, e)
        return "failed"


def _mark_failed(sample_id: str, run: str, err: Exception) -> None:
    try:
        row = _read(sample_id)
        m = _marker(row)
        if not row or m.get("run") != run or m.get("status") != "seeding":
            return
        failed = {**m, "status": "failed", "failed_at": _now().isoformat(),
                  "error": f"{type(err).__name__}: {str(err)[:160]}"}
        _patch_marker(row, m, failed)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[sample] could not mark {sample_id[:8]} failed: {type(e).__name__}")


def _background(sample_row: Dict[str, Any], home_row: Optional[Dict[str, Any]]) -> None:
    sid = str(sample_row.get("id") or "")
    try:
        run_seed(sample_row, home_row)
    finally:
        with _RUNNING_LOCK:
            _RUNNING.discard(sid)


def provision(sample_row: Dict[str, Any], home_row: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """sample_church.seed_hook. Answers at once (no read) unless the sample is
    due; then seeds it in a background thread (or here, in sync mode). Never
    raises. Returns what it did: None (nothing due, or switched off),
    "started", "running" (already seeding in this process), or run_seed's
    answer in sync mode."""
    try:
        m = mode()
        if m == "off" or not due(sample_row):
            return None
        if m == "sync":
            return run_seed(sample_row, home_row)
        sid = str(sample_row.get("id") or "")
        with _RUNNING_LOCK:
            if sid in _RUNNING:
                return "running"
            _RUNNING.add(sid)
        try:
            threading.Thread(target=_background, args=(dict(sample_row), dict(home_row or {}) or None),
                             name=f"sample-seed-{sid[:8]}", daemon=True).start()
        except Exception:
            with _RUNNING_LOCK:
                _RUNNING.discard(sid)
            raise
        return "started"
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[sample] provision failed for {str((sample_row or {}).get('id'))[:8]}: "
                       f"{type(e).__name__}: {e}")
        return None
