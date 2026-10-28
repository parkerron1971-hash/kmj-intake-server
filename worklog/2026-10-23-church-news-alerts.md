---
title: Phone alerts and the week's email for the church's news (part 5 of "Church News & Celebrations")
date: 2026-10-23
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23: "A notification setup and a thread like Facebook where people can say congratulations"; the approved canvas boards 6, 7 and 9; "Continue building"'
status: in progress
prs: [kmj-intake-server (this PR), solutionist-studio (Phone alerts in Settings, Important on New post)]
migrations: [supabase/APPLY-2026-10-23-news-alerts.sql]
left_undone: ["the app keeps no record of when someone opens it, so the week's email carries the posts they haven't seen (none unseen, no email) rather than 'weeks you didn't open the app'", "no church has News alerts on yet: Love City turns it on in News & celebrations, Settings, Phone alerts"]
decisions: ["every News note is member_push kind \"news\": the church's switch, the member's own boxes and quiet hours (now a QUIET_KIND) still decide first", "Important is each member's default; Everything is their choice; a post rings once (alerted_at), a scheduled one when its time comes, never one a day and a half old", "the church's three a day count News posts that rang and its announcements, on its own clock; past three a post goes up without ringing and the Write page says so first", "replies say who answered, never what they said; birthdays are one 9 AM note to the celebrated person's own groups, never to the celebrated, and none when the church picks No alerts", "the week's email is grown-ups only, like the groups' email, and once a week (church_news_digests)", "shared good news now tells its member through the same \"news\" kind (it was announcements)", "Me → Celebrations shows \"What you hear about\" only when the church rings for News, and points to this phone's alerts when it has none set up"]
related: [2026-10-23-church-news-feed.md, 2026-10-23-church-celebrations.md, 2026-10-23-church-news-post-from-phone.md]
---
`news_alerts.py` (who hears a post, the day's three, replies, the 9 AM birthday note, Saturday's email, the 15-minute sweep "news_alerts"), the "news" kind in `member_push`, "What you hear about" on Me → Celebrations (`POST /my/celebrate/alerts`), "Important: ring their phones" on the Write page and the office's New post, and `POST /church/news/settings` taking `alerts` and `celebration_alerts`. The migration was rehearsed on production in a rolled-back probe (a row through every table and trigger) and then applied.

Built to the canvas (boards 6, 7, 9) and looked at side by side at 390 wide. Checks: 16 tests in `test_news_alerts.py` (3 sabotages caught: every post ringing Important members, the day's three ignored, the birthday person told about themselves); `news_alerts_db.mjs` 14 checks on PGlite.
