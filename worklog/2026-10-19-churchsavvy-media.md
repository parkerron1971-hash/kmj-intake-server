---
title: ChurchSavvy library — the church's pictures and videos for Sunday's screens
date: 2026-10-19
agent: Claude Code (Claude Opus 5.5)
asked: '"keep going with step 2 I want the entire thing built" (Kevin, 2026-10-19); the library from round 2: "a place for library stuff ... Videos can get uploaded for video announcements"'
status: in progress
prs: [kmj-intake-server#1511]
migrations: [supabase/APPLY-2026-10-19-worship-media.sql (applied)]
left_undone: ["the Library page and the pickers that use it (solutionist-studio, same arc)", "templates of slides (the services side has templates: worship_services.is_template)"]
decisions: ["the files live in the PUBLIC business-assets bucket: screens play them with no sign-in for hours, and the image studio's links are signed for an hour only", "uploads go straight from the browser to storage (resumable, 6 MB chunks), never through Railway", "nothing is ready until the server reads the stored file back: a picture must open in Pillow, a video must start like MP4/MOV/WebM; a liar is deleted", "20 MB a picture, 100 MB a video (the bucket's own limit), 3 GB a church"]
related: [kmj-intake-server worklog/2026-10-19-churchsavvy-show.md, kmj-intake-server clip_finder.py (the same signed-upload flow), kmj-intake-server member_app_pictures.py]
---
The church's pictures and videos for Sunday's screens: backgrounds, announcement photos, video announcements. `worship_media_router.py` covers the library (any seat), an upload slot (staff; types and sizes are checked before a slot is made), finish (the server reads the stored file back and checks it), and take-out (the file goes too). Every storage helper was checked against real storage with a throwaway picture under Love City's prefix: signed upload, size, read back, opens in Pillow, public link 200 `image/png`, removed.

Checks: 10 pytest (`test_worship_media_router.py`), `__tests__/worship_media_db.mjs` 15 checks, the access ratchet and export list.
