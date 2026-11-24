"""service_clips.py — Find my best clips in a service the church streamed
through Solutionist (Kevin 2026-11-24: "both", the second being a "Find clips
in this service" button on each service recording).

THE IDEA
  A service streamed through our relay is already recorded, at full quality,
  in the private media bucket (live/<business>/<session>/, stream_relay).
  Nothing is uploaded or copied for its clips: the service is added to Video
  Clips as a recording (a media_assets source row, origin 'service', no file
  of its own in program-media, byte_size 0) and "Find my best clips" runs on
  it exactly as on an upload, the same plan, hours, review and handoff.

THE ROW
  One per service, id uuid5(NAMESPACE, session id), so pressing the button
  twice, or on two screens, finds the same row. configuration (immutable,
  preserve_media_review) carries origin 'service' and stream_session_id; its
  duration is the service's. Deleting the recording (church_storage
  .remove_recording) stamps source_removed_at on it; the 7-day sweep that
  deletes an upload after its clips are made leaves it alone (the church's
  storage rules keep or remove a service, never Video Clips).

WHAT THE CLIP SERVICE READS (clip_input, at each run's hand-over)
  The full-quality recording while it is kept (full_removed_at empty and the
  service ended less than TRIM_MARGIN before recording_copy's day-14 trim):
  its playlist with every segment signed for JOB_LINK_S, cut here to whole
  segments covering the stretch asked for, so `offset` (where the stretch
  starts in the service) is exact. A stretch whose full-quality bytes would
  pass the clip service's 5 GB, or a service past the trim, reads the
  smaller copy (copy.mp4, ~720p) instead, from `start` to `end`. No copy
  and no full recording: the run fails in words. The clip service reads
  both only from the bucket's host (CLIPPER_COPY_HOSTS), never as an upload.

THE STRETCH
  FindClips.from_seconds / to_seconds (optional, a service only): where the
  sermon starts and ends. The run's hours are the stretch's. A service over
  the 2 hours a run may read needs one. Clips are filed with their times in
  the whole service (the stretch's offset added).

THE SWITCH
  SERVICE_CLIPS: off | owner (the default, the platform owner's churches) |
  on, and only where Find my best clips is (clip_finder.enabled, the plan's
  ai_clips). It decides whether the app shows the button (clip_finder
  .configuration's 'services') and whether a service can be added; a
  service already in Video Clips keeps its runs either way.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid5

from fastapi import HTTPException

import media_library
import sb_clients

ORIGIN = 'service'
NAMESPACE = UUID('6f1d2c4e-3b7a-4e58-9a61-0c5d8e2f7b13')
JOB_LINK_S = 4 * 3600                  # the clip service reads within its hour's limit, with room
MAX_FULL_BYTES = int(4.75 * 1024 ** 3)  # under the clip service's 5 GB, with room for a guess
TRIM_MARGIN = timedelta(days=1)         # this close to the day-14 trim, read the copy
PERMISSION_NOTE = "The church's own service, streamed and recorded through Solutionist."


def mode() -> str:
    m = (os.getenv('SERVICE_CLIPS') or 'owner').strip().lower()
    return m if m in ('off', 'owner', 'on') else 'off'


def switched_on(business_id: Any) -> bool:
    """SERVICE_CLIPS: off | owner (the default: the platform owner's
    churches, member_asks.platform_church) | on. A failed read is a no."""
    m = mode()
    if m == 'off':
        return False
    if m == 'on':
        return True
    import member_asks
    try:
        return bool(member_asks.platform_church(business_id))
    except Exception:  # noqa: BLE001
        return False


def is_service(row: Optional[Dict[str, Any]]) -> bool:
    return bool(row) and (row.get('configuration') or {}).get('origin') == ORIGIN


def session_id_of(row: Dict[str, Any]) -> str:
    return str((row.get('configuration') or {}).get('stream_session_id') or '').lower()


def source_id_for(session_id: Any) -> str:
    return str(uuid5(NAMESPACE, f'service-{str(session_id).lower()}'))


def _now(now: Optional[datetime] = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _at(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(timezone.utc)
    except ValueError:
        return None


def _num(value: Any) -> float:
    try:
        return max(float(value or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


# ── the service ──────────────────────────────────────────────────────

def read_session(business_id: Any, session_id: Any) -> Optional[Dict[str, Any]]:
    """The church's stream session with its copy columns, or None. 503 when
    it couldn't be read."""
    import recording_copy
    import stream_relay_router as sr
    sid, biz = str(session_id).lower(), media_library.key(business_id)
    if not sr.UUID_RE.match(sid):
        return None
    cols = recording_copy.COLS if recording_copy.copy_columns() is True else recording_copy.COLS.split(',copy_state')[0]
    rows = sb_clients.sb_get_as_service(
        f'/stream_sessions?id=eq.{sid}&business_id=eq.{biz}&select={cols}&limit=1')
    if not isinstance(rows, list):
        raise HTTPException(503, "The service couldn't be read just now. Try again.")
    return rows[0] if rows else None


def full_kept(s: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """The full-quality segments are there, and far enough from the day-14
    trim that a run can't lose them mid-read."""
    import recording_copy
    if s.get('full_removed_at'):
        return False
    ended = _at(s.get('ended_at'))
    if ended is None:
        return False
    return ended > _now(now) - timedelta(days=recording_copy.KEEP_FULL_DAYS) + TRIM_MARGIN


def copy_ready(s: Dict[str, Any]) -> bool:
    import recording_copy
    return recording_copy.copy_ready(s)


def why_not(s: Optional[Dict[str, Any]], now: Optional[datetime] = None) -> Optional[str]:
    """Why this service can't give clips, in the church's words, or None."""
    if not s:
        return "That service isn't in this church's recordings."
    if s.get('removed_at'):
        return "This service's recording was deleted."
    if s.get('status') != 'ended':
        return 'This service is still live. Find its clips once it has ended.'
    if _num(s.get('duration_s')) <= 0:
        return "This service has no recording to find clips in."
    if s.get('full_removed_at') and not copy_ready(s):
        return "This service's recording isn't available."
    return None


def _church_day(business_id: str, started: Any) -> str:
    import stream_relay_router as sr
    when = _at(started)
    if when is None:
        return ''
    try:
        when = when.astimezone(sr._church_tz(business_id))
    except Exception:  # noqa: BLE001  (a 503 there: the date on UTC rather than none)
        pass
    return f'{when:%A}, {when:%B} {when.day}'


def name_for(business_id: str, s: Dict[str, Any]) -> str:
    """'The River (service, Sunday, November 22)' when the service has a
    sermon with a title, else 'Service, Sunday, November 22'."""
    day = _church_day(business_id, s.get('started_at'))
    title = ''
    if s.get('sermon_id'):
        rows = sb_clients.sb_get_as_service(
            f"/sermons?id=eq.{media_library.key(s['sermon_id'])}&business_id=eq.{media_library.key(business_id)}"
            '&select=title&limit=1')
        if isinstance(rows, list) and rows:
            title = str(rows[0].get('title') or '').strip()
    if title:
        name = f'{title} (service, {day})' if day else title
    else:
        name = f'Service, {day}' if day else 'Service recording'
    return name[:160]


def add_service(business_id: Any, session_id: Any, user) -> Dict[str, Any]:
    """The service as a Video Clips recording (made once; found again after
    that). The caller is the router; the person needs the clips duty."""
    import clip_finder
    media_library.access(business_id, user)
    if not switched_on(business_id) or not clip_finder.enabled(business_id):
        raise HTTPException(503, "Find my best clips isn't switched on for this business yet.")
    s = read_session(business_id, session_id)
    problem = why_not(s)
    if problem:
        raise HTTPException(404 if not s else 409, problem)
    biz, sid = media_library.key(business_id), str(s['id']).lower()
    asset_id = source_id_for(sid)
    found = media_library.read(f'/media_assets?id=eq.{asset_id}&business_id=eq.{biz}&select=*&limit=1')
    if found:
        return media_library.public(found[0])
    saved = sb_clients.sb_post_as_service('/media_assets', {
        'id': asset_id, 'business_id': biz, 'kind': 'source', 'name': name_for(biz, s), 'status': 'ready',
        'byte_size': 0, 'duration_seconds': _num(s.get('duration_s')), 'created_by': str(user.id),
        'finished_at': _now().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'configuration': {'origin': ORIGIN, 'stream_session_id': sid, 'authorized_to_copy': True,
                          'permission_note': PERMISSION_NOTE}})
    if not saved:
        # Pressed twice at once: the other press made it.
        found = media_library.read(f'/media_assets?id=eq.{asset_id}&business_id=eq.{biz}&select=*&limit=1')
        if not found:
            raise HTTPException(503, "The service couldn't be added to Video Clips. Try again.")
        return media_library.public(found[0])
    clip_finder.audit(business_id, user.id, 'service_add', {'asset_id': asset_id, 'session_id': sid})
    return media_library.public(media_library.one(saved))


def forget_service(business_id: Any, session_id: Any, now: Optional[datetime] = None) -> None:
    """The recording was deleted: its Video Clips row says so (its clips stay)."""
    sb_clients.sb_patch_as_service(
        f'/media_assets?id=eq.{source_id_for(session_id)}&business_id=eq.{media_library.key(business_id)}'
        '&source_removed_at=is.null',
        {'source_removed_at': _now(now).strftime('%Y-%m-%dT%H:%M:%SZ')})


# ── the stretch ──────────────────────────────────────────────────────

def stretch(source: Dict[str, Any], from_seconds: Optional[float], to_seconds: Optional[float]) -> Dict[str, float]:
    """{'start', 'end', 'seconds'} of the service a run reads, before it is
    cut to whole segments. 422 for a stretch outside the service."""
    total = _num(source.get('duration_seconds'))
    start = _num(from_seconds)
    end = min(_num(to_seconds), total) if to_seconds is not None else total
    if start >= total:
        raise HTTPException(422, 'The sermon starts after the service ends. Check the start time.')
    if end - start < 60:
        raise HTTPException(422, 'Choose at least a minute of the service.')
    return {'start': start, 'end': end, 'seconds': end - start}


def _segments(text: str):
    """(head tags, [(seconds, tags+[name])]) of a relay playlist."""
    import stream_relay_router as sr
    head: List[str] = []
    segs: List[tuple] = []
    pending: List[str] = []
    for raw in (text or '').splitlines():
        line = raw.strip()
        if not line or line == '#EXT-X-ENDLIST':
            continue
        if not line.startswith('#'):
            seconds = 0.0
            for tag in pending:
                if tag.startswith('#EXTINF:'):
                    seconds = _num(tag[8:].split(',', 1)[0])
            segs.append((seconds, pending + [line]))
            pending = []
        elif line.split(':', 1)[0] in sr._PLAYLIST_TAGS:
            head.append(line)
        else:
            pending.append(line)
    return head, segs


def cut_playlist(text: str, start: float, end: float):
    """The playlist cut to the whole segments that cover [start, end]: (text
    ending in ENDLIST, offset of its first segment, its seconds). The first
    kept segment loses a resume tag (nothing comes before it now)."""
    head, segs = _segments(text)
    kept, t, offset = [], 0.0, None
    for seconds, lines in segs:
        if t + seconds > start and t < end:
            if offset is None:
                offset = t
            kept.append(lines)
        t += seconds
    if not kept:
        return None, 0.0, 0.0
    kept[0] = [tag for tag in kept[0] if tag != '#EXT-X-DISCONTINUITY']
    out = [line for line in head if line.split(':', 1)[0] not in ('#EXT-X-PLAYLIST-TYPE', '#EXT-X-MEDIA-SEQUENCE',
                                                                     '#EXT-X-DISCONTINUITY-SEQUENCE')]
    if not out or out[0] != '#EXTM3U':
        out.insert(0, '#EXTM3U')
    seconds = 0.0
    for lines in kept:
        out.extend(lines)
        seconds += next((_num(tag[8:].split(',', 1)[0]) for tag in lines if tag.startswith('#EXTINF:')), 0.0)
    out.append('#EXT-X-ENDLIST')
    return '\n'.join(out) + '\n', float(offset or 0.0), seconds


class Unavailable(Exception):
    """The run can't read this service; the message is the church's."""


def clip_input(business_id: str, source: Dict[str, Any], options: Dict[str, Any],
               now: Optional[datetime] = None) -> Dict[str, Any]:
    """What the clip service is sent for this run (merged into POST /jobs):
    {'playlist'} or {'recording_url', 'start', 'end'}, with 'seconds' (what
    it should read) and 'offset' (kept here, where the stretch starts in the
    service; not sent)."""
    import recording_copy
    import stream_relay_router as sr
    s = read_session(business_id, session_id_of(source))
    problem = why_not(s, now)
    if problem:
        raise Unavailable(problem)
    want = stretch(source, options.get('from_seconds'), options.get('to_seconds'))
    total = _num(s.get('duration_s'))
    full_bytes = _num(s.get('bytes')) * want['seconds'] / total if total else 0.0
    folder = recording_copy.folder(business_id, s)
    if folder is None:
        raise Unavailable("This service's recording isn't where it should be.")
    if full_kept(s, now) and full_bytes <= MAX_FULL_BYTES:
        try:
            text = sr._playlist_text(s)
        except HTTPException:
            raise Unavailable("The service's recording couldn't be opened. Try again.") from None
        if text:
            cut, offset, seconds = cut_playlist(text, want['start'], want['end'])
            if cut:
                signed = sr.sign_playlist(cut, folder.rstrip('/'), lambda k: sr.r2_link(k, JOB_LINK_S))
                if '#EXT-X-ENDLIST' not in signed:
                    signed += '#EXT-X-ENDLIST\n'
                return {'playlist': signed, 'seconds': round(seconds, 3), 'offset': offset, 'quality': 'full'}
    if copy_ready(s):
        key = recording_copy.copy_key(business_id, s)
        if key:
            return {'recording_url': sr.r2_link(key, JOB_LINK_S), 'start': round(want['start'], 3),
                    'end': round(want['end'], 3), 'seconds': round(want['seconds'], 3), 'offset': want['start'],
                    'quality': 'copy'}
    if full_bytes > MAX_FULL_BYTES:
        raise Unavailable('That stretch of the service is too big to read at full quality. Say where the sermon '
                          'starts and ends, or try again once its smaller copy is made (within the hour).')
    raise Unavailable("This service's recording isn't available.")


# ── the screen ───────────────────────────────────────────────────────

PREVIEW_LINK_S = 900


def preview(business_id: Any, row: Dict[str, Any]) -> Dict[str, Any]:
    """What Video Clips plays for a service: its smaller copy (an MP4 every
    browser plays) once it is made, else no video and a note. The full
    recording is a playlist a plain <video> can't play everywhere."""
    import recording_copy
    import stream_relay_router as sr
    base = {'expires_in': PREVIEW_LINK_S, 'caption': '', 'destination': ''}
    try:
        s = read_session(business_id, session_id_of(row))
    except HTTPException:
        s = None
    if s and not s.get('removed_at') and copy_ready(s):
        key = recording_copy.copy_key(business_id, s)
        if key:
            return {**base, 'url': sr.r2_link(key, PREVIEW_LINK_S)}
    return {**base, 'url': None,
            'note': "The service's preview appears here within the hour after it ends. You can find its clips now."}
