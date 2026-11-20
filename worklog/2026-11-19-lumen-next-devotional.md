---
title: Member app Lumen Next — the devotional on the Bible tab, its day, and night reading
date: 2026-11-19
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, on the member app: "where is the devotional section. I didn''t see it". The Lumen Next mock answered with three boards (Bible tab: the devotional on top; A devotional day; A devotional day, night reading), and he said "build this app".'
status: shipped
prs: [kmj-intake-server — Lumen Next devotional]
migrations: []
left_undone:
  - "The mock's 'Remind me' (on the card before the next devotional) is not built: the app has no devotional reminder to keep. The evening text list (/daily, devotional_texts) is a different thing, on for Love City only."
  - "The mock's 'Day 4 of 21' is one 21-day devotional. Each devotional is counted on its own: Love City's 21 days were three 7-day devotionals (Focus, Finance, Fasting Week), so its card and day say 'Day N of 7'. Nothing joins back-to-back devotionals into one count."
  - "A devotional's own page (/my/bible/plans/<id>: its welcome, practices and list of days) keeps today's markup under Lumen's tokens; the mock has no board for it. The day's back arrow goes there."
  - "Listen on the Bible tab card and the day shows when Listen can work (devotional_voice.can_speak), as today's day page. The first Listen of a day makes its reading (about 4 cents, once per version of the words); that was already so."
  - "Not checked on a real phone: Playwright Chromium and WebKit at 390x844, motion on and reduced. Headless WebKit on Windows can't play audio and draws Figtree at one weight; headless Chromium never finishes a page move's arrival with motion on after a link tap (the Lumen motion module, also on main's pages), so the flow opens a fresh tab for its last step."
  - "Not checked against Love City's rows. If nothing is running there now (its Fasting Week was dated to end Nov 15), the card says 'Devotional · 7 days · ended Nov 15' and offers to pick up where you stopped or read it again, until the church publishes or dates the next one."
decisions:
  - "Behind the same switch (member_lumen.page()). With MEMBER_LUMEN=off, 114 page×scene dumps (38 pages × 3 scenes, the devotional's days included) are identical to main's, ignoring clock times; also identical with the night cookie set, and with MEMBER_LUMEN=preview for a member who isn't the platform owner."
  - "No new reads: the Bible tab reads the same rows (member_portal_devotionals.bible_home_data; 8 reads), a day the same 2 (a church-dated devotional) or 3 (one you started), off, on and at night (tests and the harness count them). The card's day title comes from the days already read for the first three devotionals; when the running one isn't among them it says 'Day N today' rather than guess."
  - "The Bible tab: the card sits right under 'The Word', before find. Today's devotional: the church's dated one first, else one you started. 'Devotional · Day 3 of 7', the title with its last word in mint italics, 'Today: <day> · N min', a dot a day (read filled, today ringed, filled once read), Read today (Read again once read) and Listen, which plays the day on the Bible tab itself through the day page's route. Nothing running: the next one the church dated ('Next devotional · starts Tuesday, Nov 24') with 'Until then, read <last> again (7 days, ended Nov 15)'; else the last one that ended (how far you got, Pick up at day N / Read it again); else one to start on your own day. The rail below ('From <church>') leaves out the one on the card."
  - "The deep green (#10261C, mint #BDE3C2, a hairline frame inside) is the devotional's one rich surface, as the mock: the card, the day's bar and its plate. Everything else is calm: the ivory scripture card, the words in the reading face (--lm-read) at 19/33 with a leaf-green drop capital, leaf-green small capitals over each part, hairlines."
  - "A day: no tab bar (like the reader). The bar is green with the back arrow (to the devotional), '<devotional> · Day N', Aa and the moon; the phone's bar colour is the green by day and at night (_shell's new lumen_bar_colour, Lumen only). The church's picture heads the page only when it chose one for the devotional or has a photo named for it (member_app_photos.choose), in colour unless it chose a look; with none, the green plate alone, exactly the mock. Then the scripture (up to three verses, KJV's supplied words upright inside the italic, Read <chapter>), the words, the line to hold, Reflect (the day's question and the private journal), Pray, Do today, Together, the daily checklist, Mark day N as read, the done card ('Day 3 is done. Three in a row.' and when the next opens) with Not done yet, and the days before and after. Every function of today's day page kept: the checklist (rapid taps, one save), the journal saving itself, Listen, Share, the days as links (up to 14; a longer one is a picture of how far), a preview and a failed read saving nothing."
  - "Aa holds the text size and the font, kept on the phone with the Bible reader's ('bb-look'), so a size chosen in one is the size in the other."
  - "Night reading reuses the reader's moon, cookie (lm_night) and lumen_dark: the reader's script is split into its moon-and-line part and its card part (READER_MORE_JS is byte for byte what it was; NIGHT_JS is the moon and line alone). Only the reader and a day read the cookie; the Bible tab stays white."
  - "The day's script is today's DAY_JS on the new markup (same routes, same payloads), so the server stays the one place a day is checked and saved."
  - "CSS in its own block, member_lumen_devotional.CSS, in member_lumen_ui.templates() before the type block; every rule under body.lm, its own classes lm-dd-* and lm-devo-*, its two moves (the done card arriving, its tick popping) only when the phone allows motion."
related: [2026-11-19-lumen-next-bible-classes.md, 2026-11-18-member-lumen-bible-classes.md, 2026-10-19-member-app-devotionals.md]
---
`member_lumen_devotional.py` draws the Bible tab's devotional card (`card()`,
`pick()`) and a devotional's day (`render_day()`); `member_portal_devotionals.render_day`
asks `member_lumen.page()` first and hands over, with the night cookie.

Before building, both repos' worklog/ had the devotionals themselves
(2026-10-19 here and in the frontend, 2026-10-25 /daily) and the Lumen Bible
work (#1960, #1966), whose day page was today's markup made quieter. Home's
"Also for you" devotional tile is another session's; it links to this day.

**Server-Timing.** Measured locally: the Bible harness over the test fake,
so database time is about 0. Median total of 30 warm requests, main / this
branch, both with the switch on, run back to back:

| Page | Main | Branch |
|---|---|---|
| Bible tab | 3.0 ms | 3.3 ms |
| A day (dated) | 2.3 ms | 1.9 ms |
| A day (your own) | 2.5 ms | 2.3 ms |

**Page size.** The Bible tab under Lumen grew from 18.9 KB to 20.9 KB (the
card and its Listen script); a day shrank from 25.0 KB to 22.4 KB.

**Tests.** `__tests__/test_member_lumen_devotional.py` (14), and the Bible
tab test in `test_member_lumen_bible.py` moved to the card. Rehearsed: the
night cookie not passed, the rail keeping the card's devotional, a preview
able to save: each went red.
