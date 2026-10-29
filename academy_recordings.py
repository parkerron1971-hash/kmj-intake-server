"""Class recordings (Kevin 2026-10-17, settled: recording on from the start,
"allows for people that need to go back to have that ability").

Once the business's storage is connected (Railway: CLASS_RECORDING_BUCKET,
CLASS_RECORDING_ACCESS_KEY_ID, CLASS_RECORDING_SECRET_ACCESS_KEY,
CLASS_RECORDING_ENDPOINT: a private Cloudflare R2 bucket and a key that can
read and write only it), every live class is recorded from the moment the
teacher starts it, unless the class's owner turned recording off in Course
setup (academy_courses.record_live), and the teacher can stop it for the
night from the console.

LiveKit records the class through our own page (/class-recorder in the app):
what the TV shows (the slides, an answer put up, a shared screen) with the
teacher's camera in the corner and everyone who speaks. The file goes to
the private bucket at classes/<business>/<course>/<session>.mp4. Nobody
reaches it but through a link signed for an hour, handed to a student of
that class (by their class link) or its teaching team (signed in): the
same access check as the live room (academy_live_access, as the caller).

Without the four settings nothing is recorded and nothing says it can be:
the console reads "Not recorded" and Course setup shows no switch.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse

logger = logging.getLogger(__name__)

ENV = ("CLASS_RECORDING_BUCKET", "CLASS_RECORDING_ACCESS_KEY_ID", "CLASS_RECORDING_SECRET_ACCESS_KEY",
       "CLASS_RECORDING_ENDPOINT")
LINK_TTL = 3600
REGION = "auto"  # R2


def settings() -> Optional[Dict[str, str]]:
    """The bucket and its key, or None when any is missing (or the address
    isn't https)."""
    got = {k: (os.environ.get(k) or "").strip() for k in ENV}
    if not all(got.values()) or not got["CLASS_RECORDING_ENDPOINT"].startswith("https://"):
        return None
    return {"bucket": got["CLASS_RECORDING_BUCKET"], "access_key": got["CLASS_RECORDING_ACCESS_KEY_ID"],
            "secret": got["CLASS_RECORDING_SECRET_ACCESS_KEY"],
            "endpoint": got["CLASS_RECORDING_ENDPOINT"].rstrip("/")}


def configured() -> bool:
    return settings() is not None


def recorder_url() -> str:
    """The page LiveKit opens to record a class (the app's /class-recorder)."""
    return (os.environ.get("CLASS_RECORDER_URL") or "https://system.mysolutionist.app/class-recorder").strip()


def object_key(business_id: str, course_id: str, session_id: str) -> str:
    return f"classes/{business_id}/{course_id}/{session_id}.mp4"


def egress_request(room_name: str, key: str, cfg: Dict[str, str]):
    """Record the room through our page to the private bucket, 720p."""
    from livekit import api
    return api.RoomCompositeEgressRequest(
        room_name=room_name, custom_base_url=recorder_url(),
        preset=api.EncodingOptionsPreset.H264_720P_30,
        file_outputs=[api.EncodedFileOutput(
            file_type=api.EncodedFileType.MP4, filepath=key,
            s3=api.S3Upload(access_key=cfg["access_key"], secret=cfg["secret"], region=REGION,
                            endpoint=cfg["endpoint"], bucket=cfg["bucket"], force_path_style=True))])


def presign_get(key: str, cfg: Dict[str, str], *, expires: int = LINK_TTL, now: Optional[datetime] = None,
                region: str = REGION, host: Optional[str] = None, path: Optional[str] = None) -> str:
    """An S3 SigV4 query-signed GET link (path-style, as R2 takes it). `host`
    and `path` default to the bucket's; they're there so the signing can be
    checked against AWS's own published example."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    endpoint = urlparse(cfg["endpoint"])
    host = host or endpoint.netloc
    path = path or f"/{cfg['bucket']}/{quote(key, safe='/~')}"
    amz_date, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    scope = f"{day}/{region}/s3/aws4_request"
    params = {"X-Amz-Algorithm": "AWS4-HMAC-SHA256", "X-Amz-Credential": f"{cfg['access_key']}/{scope}",
              "X-Amz-Date": amz_date, "X-Amz-Expires": str(int(expires)), "X-Amz-SignedHeaders": "host"}
    query = "&".join(f"{quote(k, safe='~')}={quote(v, safe='~')}" for k, v in sorted(params.items()))
    canonical = "\n".join(("GET", path, query, f"host:{host}\n", "host", "UNSIGNED-PAYLOAD"))
    to_sign = "\n".join(("AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()))

    def mac(k: bytes, msg: str) -> bytes:
        return hmac.new(k, msg.encode(), hashlib.sha256).digest()
    k = mac(mac(mac(mac(("AWS4" + cfg["secret"]).encode(), day), region), "s3"), "aws4_request")
    signature = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    scheme = endpoint.scheme or "https"
    return f"{scheme}://{host}{path}?{query}&X-Amz-Signature={signature}"


def ended_fields(info: Any) -> Dict[str, Any]:
    """What a finished recording leaves on its night, from LiveKit's
    egress_ended: ready with its length and size, or failed."""
    from livekit import api
    status = getattr(info, "status", None)
    # LiveKit reports our one file in the older `file` field and leaves
    # `file_results` empty (the first real test recording, 2026-10-20), so
    # either counts. An unset `file` reads as size 0: no recording.
    files = list(getattr(info, "file_results", []) or [])
    file = files[0] if files else getattr(info, "file", None)
    size = int(getattr(file, "size", 0) or 0)
    done = status == api.EgressStatus.EGRESS_COMPLETE and size > 0
    out: Dict[str, Any] = {"recording_status": "ready" if done else "failed",
                           "recording_ended_at": datetime.now(timezone.utc).isoformat()}
    if done:
        out["recording_seconds"] = int((getattr(file, "duration", 0) or 0) // 1_000_000_000)
        out["recording_bytes"] = size
    return out
