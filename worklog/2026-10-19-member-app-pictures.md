---
title: Member app round three, part 2 - the church chooses every picture; only the owner and the people it names can
date: 2026-10-19
agent: Claude Code (Claude Opus 5.5)
asked: '"only the admin or key people like media etc can change those pictures. the only thing people can change is there profile pictures and stuff related to their account. make sense? lets build it"'
status: shipped
prs: [kmj-intake-server#1503]
migrations: []
left_undone: ["the frontend: Settings, Member page gets Colours (family or the church colour alone), Who can change pictures (name people), and Change pictures (opens the preview on Pictures); plus the What's New entry", "part 3: the Bible reader (Old Testament first book picker, highlights, private notes)", "part 4: plans and the church's own devotionals"]
decisions: ["who may change the app's pictures: the owner, from Preview as a member (only the owner can open one), and the contacts the owner names in member_portal.photo_editors; every other member changes only their own profile photo", "an upload is made at most 1600px WebP, checked by the small model with a policy for a church's own pictures (words on a flyer are fine), kept in the public business-assets bucket and added to the media library off the website", "a pick must be one of the church's own photos (media library or hand-built site); anything else is refused", "the photo pool is wide (80) now that photos are matched by name, so a church's whole set can be matched"]
related: [kmj-intake-server worklog/2026-10-19-member-app-colour-family.md, canvas https://claude.ai/artifact/WzjBoY73aPBUkwy1PsEArU]
---
`member_app_pictures.py` lets the church choose every picture in the member app.
- `/my/pictures` lists every spot: the fixed ones, Home's tiles, events by name and groups. It shows what's on each now (chosen, matched by its name, or the default picture).
- `/my/pictures/spot?key=` is the editor from the approved canvas: the look, the church's photos, an upload, or the default picture.
- `/my?edit=pictures` puts a Change button on every picture on Home.
- `POST /my/pictures` saves `member_portal.pictures[key]`.

Only two kinds of session may use any of it: the owner's preview session (`may_edit` returns `owner:<id>`) and a member named in `member_portal.photo_editors`. Everyone else is sent to Home and nothing saves. Rehearsed by letting any member through: 2 tests failed.

The owner names the people with `PATCH /member-portal/{biz}` `{photo_editors}` and picks `{colours: family|church}`. A preview opened with `{next: "pictures"}` lands on Pictures. Tests: `__tests__/test_member_app_pictures.py`. It also covers the review note on #1502: Give, Watch, Connect, Live and Youth each show the church's pick, else their default picture.
