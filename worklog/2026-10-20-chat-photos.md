---
title: Photos in a group's chat
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-20: "let''s continue so we can finish up". From the approved canvas "Church Groups, Together" (board Chat: the pantry photo, "From Saturday''s pantry. We filled 40 boxes!"; board Settings: "Photos and polls · Photos are checked too. Leaders can hide one and tell the safety team.")'
status: shipped
prs: [kmj-intake-server#1548]
migrations: [supabase/APPLY-2026-10-20-chat-photos.sql (applied)]
left_undone: ["photos in a chat with a teen in it stay off until Kevin decides (the conservative default)", "the office app's Safety console shows a reported photo as the word Photo; officers see the picture in the member app's Safety room"]
decisions: ["anyone who can write in a group's chat, or the leaders' room, adds a photo from the composer's + with an optional caption; never in a private chat, never in a chat with a teen in it", "a photo is a message: its caption is the text (Photo when there's none), checked like any message; a harmful caption holds the whole photo", "the picture is made upright, at most 1600px, WebP (camera and location data dropped) and looked at by a model before it's kept; one it turns down is never kept, and if the check can't run nothing is posted; 20 an hour per member", "stored privately under the church's own chat-photos/<chat> folder; GET /my/messages/<chat>/photo/<id> hands a 10-minute signed link only to the chat's members (the sender alone while held), or a safety officer for a held or reported one or after their logged look", "a leader's Take down and a member's Report work as on any message; the Safety room shows the picture; the file goes when retention deletes the message", "the group's leaders turn photos and polls off together on the People tab (groups.chat_extras)"]
related: [2026-10-20-chat-polls.md, 2026-10-20-group-chat.md]
---
`chat_photos.py` (new): `prepare`, `screen` (member_photos.screen with the chat POLICY), `store`, `drop`, `attach`, `for_messages`, `link_for`, `img`, `form`, PHOTO_CSS. `member_portal_messaging`: send takes a `photo` upload; GET /my/messages/{tid}/photo/{mid}; `retention_tick` drops the files of deleted messages. `member_portal_groups`: photo bubbles (tap for the picker, Open for full size), the + tray's Photo, `?make=photo`, the switch now reads Photos and polls. `member_portal_safety`: held, reported and whole-chat photos. `rate_limit`: chat_photos. `member_portal_church`: the words. `account_lifecycle`: msg_photos exported, never re-imported (the files themselves live in Storage).

Checks: 23 tests in `test_chat_photos.py` (25 sabotages tried, 24 caught; the one left is a teen sender, which "a teen is in this chat" already covers); `chat_photos_db.mjs` 13 checks on PGlite, in CI. Rollback probe on the live database, then applied. Rendered at 390 and 1280.
