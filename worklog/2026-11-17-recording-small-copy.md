---
title: A smaller copy of each service recording, which is also its Download button
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "build" (two promises: "Two weeks after a service, its recording is saved again at a smaller size (about 1.3 GB instead of 6), and it still looks right on a phone. Clips get cut before then, from the full-quality copy." and "Every recording gets a Download button, so deleting never means losing it.")'
status: waiting on Kevin
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-11-17-recording-small-copy.sql (NOT applied)]
left_undone:
  - "Kevin: apply supabase/APPLY-2026-11-17-recording-small-copy.sql (after APPLY-2026-11-17-church-storage.sql), BEFORE setting the switch."
  - "Kevin: the write key (STREAM_R2_WRITE_ACCESS_KEY_ID + _SECRET_ACCESS_KEY) must already be on kmj-intake-server AND kmj-intake-worker (it isn't yet; #1903's step)."
  - "Kevin: on the clip service (solutionist-clipper) set CLIPPER_COPY_HOSTS to the media bucket's host, the hostname of STREAM_R2_ENDPOINT (<account>.r2.cloudflarestorage.com). Without it /health says copies false and the worker starts none."
  - "Kevin: CHURCH_STORAGE_SMALL_COPY=owner on kmj-intake-server AND kmj-intake-worker (CHURCH_STORAGE must be on for that church too), then on (a Thursday). Ships off."
  - "Merging this deploys the clip service (clipper_worker/ changed): check its /health says busy false first, a deploy stops a running clip job."
  - "Not built: a manual 'make the copy again' for a recording whose three tries failed (reset copy_state/copy_tries by hand: update stream_sessions set copy_state = null, copy_tries = 0 where id = ...)."
  - "Not built: relay recordings as clip sources. Nothing turns one into a clip today (clips come from media library uploads); when something does, it must read the full-quality recording while full_removed_at is null and copy.mp4 after (module docstring, CLIPS)."
  - "The Stream panel's recent list still links managers to the watch page, which plays the copy from day 14; nothing else in the app changes. The storage page's Download button (solutionist-studio StorageCard) was already built and shows once can_download is true and a row has an https download_url."
decisions:
  - "The copy: H.264 libx264 veryfast, about 720p (fits 1280x720 landscape or 720x1280 portrait, never upscaled, aspect kept), 1500k (maxrate 2000k, bufsize 3000k), keyframe every 120 frames, AAC 96k stereo, +faststart. A 70 s 1080p30 7 Mbps test with a resume in it came out 1280x720 at 1.63 Mbps, 70.0 s: 1.4 GB per two hours (1.3 GiB)."
  - "Stored as live/<business>/<session>/copy.mp4, the recording's own folder, so church_storage's delete removes it with everything else."
  - "The clip service gets the recording's playlist in the request body, every segment signed with the READ key for 4 h, EXT-X-ENDLIST added (a relay that crashed leaves none, and ffmpeg would read it as live from its last segments), plus a PUT signed with the WRITE key for 4 h. Not the API's /stream-relay/media URL: then ffmpeg would follow whatever the playlist names, the API host would join the allow-list, and an unfinished playlist would read as live."
  - "The clip service checks every segment line and the upload link against a NEW allow-list, CLIPPER_COPY_HOSTS (the bucket's host only); clip jobs keep CLIPPER_SOURCE_HOSTS, so allowing copies never widens what a clip job may fetch. No tag may carry URI= (keys, maps) and no variant playlists."
  - "ffmpeg skips an unreadable segment and exits 0, so a copy fails on 'Failed to open segment' / 'failed too many times' in its log (-seg_max_retry 3); 'Packet corrupt' and timestamp discontinuity lines at a resume are normal and pass."
  - "Clips go first, twice over: the worker never starts a copy while a clip run from the last 2 hours is queued or working (or that read fails), and the clip service stops a running copy when POST /jobs arrives (job.yielded, waits up to 30 s for the lock). A yielded copy goes back uncounted. POST /copies while anything runs is a 409, which the worker treats as later."
  - "Ready means checked: the API HEADs copy.mp4 with the read key and its size must equal what the clip service uploaded (which also compared the bucket's ETag with the file's MD5), and its ffprobe length must be within 2% (10 s at least) of duration_s, which is the relay's sum of EXTINF. Otherwise the try fails and the object is deleted. Three tries, an hour apart."
  - "Recordings made before the switch go on are copied too, oldest first, one at a time; any that ended more than 14 days ago lose their full-quality segments on the tick after their copy is checked. At ~30 minutes a copy, a church with 10 old services is caught up in an afternoon."
  - "Day 14 = 14 days after ended_at. The trim re-HEADs the copy at copy_bytes first (a copy missing or changed is marked failed and made again, the full recording stays), lists the folder with the write key, deletes only .ts and .m3u8 directly in it (never copy.mp4, nothing deeper, not ffmpeg's .tmp), then sets full_removed_at. A check in the migration refuses full_removed_at without a ready copy."
  - "The watch page plays the copy from day 14 when it is ready (also while the trim is pending) and always once full_removed_at is set, whatever the switch says, so turning the switch off never breaks a published sermon. Same access rules (live, a published sermon, or a manager's ?t=); the copy link is a presigned GET with the read key for 4 h, like a segment link; no hls.js on that page; the CSP is unchanged (media-src already lists the bucket's origin)."
  - "The meter (church_storage.stored_bytes): bytes + copy_bytes while the full recording exists, copy_bytes after; copy_bytes is set only while ready. The copy therefore adds ~1.3 GB per recording for its first 14 days, which can tip a church near full over the line. bytes_per_sunday keeps the full size. The storage page's per-recording bytes and the delete's freed_bytes are the same stored bytes."
  - "The copy columns are read only once they exist (recording_copy.copy_columns: a probe; '42703'/'PGRST204' means not applied, cached 10 minutes; any other failure is 'can't tell' and the meter decides nothing). Not tied to the switch, so a copy made while it was on is still counted after it goes off."
  - "can_download is true where the switch is on for the church (and the relay's read key is set); download_url is a presigned GET for an hour with response-content-disposition attachment; filename=\"<Church> <YYYY-MM-DD>.mp4\" (the service's start on the church's clock, ASCII-folded, with filename*= UTF-8 when the name has other letters) and response-content-type video/mp4. download_url is always present on a row (null when there's no ready copy)."
  - "Signatures for PUT, HEAD and the attachment GET are pinned to what botocore 1.44.5 signs (the same script reproduces #1903's pinned DELETE). r2_link gained method=, query=, when=; its default GET is byte for byte the same."
  - "The worker tick runs every 2 minutes (leader-gated, max_instances 1): follow the copy under way, trim up to 3 recordings, then start one copy if nothing else runs. Every state change is conditional on copy_job and the state it leaves; claims are conditional on copy_tries; a recording the church deletes mid-copy has its job stopped and any copy that landed deleted."
related: [2026-11-17-church-storage-allowance.md, 2026-11-17-church-tier-fences.md, 2026-10-29-church-stream-relay-service.md, 2026-10-05-clipper-service.md]
---
Every ended service recording gets one smaller MP4, made by the clip service
and kept beside the recording's segments. The church's storage page offers it
as the Download button. Fourteen days after the service, the full-quality
segments are deleted and the copy stays (about 1.3 GB instead of 6), and the
watch page plays the copy. `recording_copy.py` is the job and the rules;
`clipper_worker/service.py` gained `POST/GET/DELETE /copies/{id}`;
`church_storage.stored_bytes` is the meter's new count. All of it is behind
`CHURCH_STORAGE_SMALL_COPY` (off), the write key and the clip service's
`CLIPPER_COPY_HOSTS`.

Before building more here: read the module docstring of `recording_copy.py`,
and keep the copy at `live/<business>/<session>/copy.mp4` (the delete path
relies on it sharing the folder).
