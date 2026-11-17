---
title: A storage allowance per church plan (recordings, class recordings, files)
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "build" (a storage allowance per church instead of keeping service recordings forever)'
status: waiting on Kevin
prs: [kmj-intake-server#1903]
migrations: [supabase/APPLY-2026-11-17-church-storage.sql (NOT applied)]
left_undone:
  - "Kevin: apply supabase/APPLY-2026-11-17-church-storage.sql BEFORE setting CHURCH_STORAGE (the meter reads the new stream_sessions columns)."
  - "Kevin: create an R2 API token with Object Read & Write on the stream media bucket and set STREAM_R2_WRITE_ACCESS_KEY_ID + STREAM_R2_WRITE_SECRET_ACCESS_KEY on kmj-intake-server AND kmj-intake-worker (the daily job runs on the worker). Without it a delete answers 503 'Deleting recordings isn't switched on yet.' and no warnings or removals happen."
  - "Kevin: CHURCH_STORAGE=owner (his churches), then on (a Thursday). Ships off."
  - "The smaller copy of a service two weeks after it (not built)."
  - "MP4 downloads (can_download is always false here)."
  - "Selling +100 GB through Stripe: pricing_config.extra_storage_offer() holds the number; church_storage.extra_bytes() returns 0 and is the one place a purchase joins the allowance; church_storage.ADD_STORAGE_SOLD turns the warnings' 'Make room to keep it.' into 'Make room or add storage to keep it.'"
  - "The frontend storage page (another agent builds it against GET /church/storage and DELETE /church/storage/recordings/{id}; field names are fixed)."
  - "Chief verbs for storage."
  - "The media library's own 20 GB cap in enqueue_media_asset (APPLY-2026-09-07-media-library.sql, -10-05-find-best-clips.sql) is left alone. Its files (bucket program-media, <business id>/...) ARE counted in this allowance's 'files', so a church on a 1 TB plan is still stopped at 20 GB of media library imports."
  - "Pre-existing, not fixed here: deleting a business cascades its stream_sessions rows but leaves its recordings in the media bucket (account_lifecycle deletes Supabase Storage files only). Nothing counts or bills those orphans; a later cleanup could list live/<business id>/ with the write key."
  - "If the recording-end check can't read the files or class recordings, that recording is never held (no hold on a guess); the church still sees its meter. The daily job only follows recordings that were held. The daily job also decides nothing for a church while its files can't be counted, so the migration must be applied before the switch."
decisions:
  - "Allowance per plan (GB = 1024^3 bytes): Small 100, Growing 250, Established 500, Large 1024, env dials LIMIT_CHURCH_<SIZE>_STORAGE_GB; on feature_gates.plan_limits() as storage_gb."
  - "A business not on a church plan (church_texts.church_plan_of) has no allowance; its GET answers {\"enabled\": false} like switched off."
  - "Files are every Supabase Storage object under '<business id>/' in any bucket, summed by church_storage_files_bytes (SECURITY DEFINER, search_path '', service_role only). A missing function is files_counted false, never an error. Class recordings: academy_live_sessions.recording_bytes through academy_courses.business_id (their own bucket, not double counted)."
  - "A failed read decides nothing (review round, 2026-11-17): class_bytes returns None on failure, measure() carries complete=false when files or classes are unread, and that run neither holds, warns, releases, removes nor re-arms for the church (counted as 0 they would look like room, and a released hold is never held again). A failed sessions or sermons read skips the church."
  - "A warning counts only once its office notice is saved (review round): _post returns whether the insert saved; _warn claims (warnings_sent n-1 to n, last_warned_at null), posts, then marks it delivered (last_warned_at); a notice that did not save rolls the claim back, and if even that fails the warning stays claimed-not-delivered, never counts toward the next warning or a removal, and is sent again. Warning 1 restarts the 14 days when it lands. A removal needs three delivered warnings. A heads-up that did not save is re-armed and tried again. All diagnostics are print() (Railway shows print only)."
  - "Warnings and removals also need the write key: nothing tells a church to make room unless it can."
  - "The 80% heads-up is remembered in a new server-only table church_storage_notes (near_noted_at), not in businesses.settings: today's settings work (business_settings.SERVER_KEYS) pins the server keys to an unapplied SQL list, and a daily whole-object settings write per church is the race that lost the founding place. Re-arms below 75% so a church sitting at 80% hears once."
  - "Removal waits for three warnings AND at least 12 hours after the last one, and re-checks 'published' just before deleting. Day 7 and day 13 are measured from the hold (keep_until minus 7 days, minus 1 day); the job runs daily at 09:40 UTC, so in practice warning 2 lands on day 7-8, warning 3 on day 13-14, the removal on day 14-15."
  - "Deleting lists live/<business>/<session>/ with a signed ListObjectsV2 and sends one signed DELETE per object, 16 at a time (a 2-hour service is ~1,800 four-second segments). A recording whose stored playlist_path isn't exactly live/<business>/<session>/index.m3u8 is never deleted. It is marked removed only after every object is gone."
  - "sigv4_presign gained method= and query= (defaults keep the player's GET link byte for byte; AWS's published vector still passes). The DELETE and LIST signatures are pinned to what botocore 1.44.5 signs for the same requests."
  - "An unpublished sermon that carried a removed recording keeps its words; its video_url becomes ''. The Stream panel's recent list leaves out removed recordings where the switch is on (and falls back to the old read if the migration is missing)."
  - "storage_gb on /billing/plans plan_details and the church site's plan cards ('100 GB of storage', '1 TB of storage') only when CHURCH_STORAGE=on, not owner."
  - "The routes are /church/storage...: two segments, like /church/news, so nothing joins site_page_helpers.RESERVED_PAGE_IDS (the other church routers didn't either)."
  - "Account lifecycle: church_storage_notes joins EXPORT_EXCLUDED (a send stamp, cascade on business deletion). The four stream_sessions columns need nothing: the table is already excluded (the relay's run log)."
related: [2026-10-29-church-stream-relay-service.md, 2026-10-18-class-recordings.md, 2026-11-03-church-plans-by-size.md]
---
Every church plan now carries a storage allowance covering all of its files:
service recordings from the stream relay, class recordings and uploaded
files. `church_storage.py` is the meter and the rules, `church_storage_router.py`
the two doors (`GET /church/storage`, `DELETE /church/storage/recordings/{id}`,
manager or owner). When a recording ends with the church already over its
allowance, it is kept 14 days and the office hears three times; after that,
if the church is still over and it isn't a published sermon, it is deleted
and the office hears once. Recording and going live are never stopped. The
80% heads-up says how many Sundays of room are left. All of it is behind
`CHURCH_STORAGE` (off) and the new R2 write key.

Before building more here: read the module docstring of `church_storage.py`,
and keep the GET/DELETE field names (the app is built against them).
