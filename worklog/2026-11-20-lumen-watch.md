---
title: "Member app new look (Look 5.1) — Watch: Messages and Series, a message's page, a series, pick up where you left off, Save and Add to calendar"
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, on the Look 5.1 mock: "this is awesome. much better design. lets build this including the new still to build!" About the media pages: "make sure we put full thought on flow and function so what i am seeing is actually how it works."'
status: in review
prs: ["kmj-intake-server (Look 5.1 Watch)"]
migrations: []
left_undone:
  - "Search (the mock's magnifier and 'Search' beside Every message): the app has no message search, so neither is drawn."
  - "How long a message runs, for one nobody on this account has played: the sermons table has no length. The chip, the hero's '38 min' and 'n min left' come only from the member's own player."
  - "The mock's 'Part 4 · This Sunday at 10:30, live' (a part not posted yet), '3 of 4 so far' (a series' planned length) and season names ('Advent', 'Fall'): none is in the data. A series says the months it ran and how many messages."
  - "The mock's sound wave and 'Keeps playing with your screen off': decoration and a promise we can't check on every phone. The phone's lock-screen controls (Media Session) are there."
  - "Back and forward 15 s and our scrubber are for audio. A video plays in its own player (YouTube, Vimeo, Loom, Facebook, our relay), with that player's own controls."
  - "Where you are is remembered for our audio player, YouTube and Vimeo (their players say so). Loom, Facebook and our relay's recordings don't, so those aren't remembered."
  - "Add to calendar has no 'Added' state: the page can't know the phone added it."
  - "The mock's title bar (Watch and the magnifier in place of the church's bar) is the shell's (another piece). Watch's title is in the page under the church's bar, as Connect's is (#1985). If the shell takes the title, drop .lw-t1."
  - "The tab bar stays on a message's page (the mock hides it there): every pushed page in this app keeps it."
  - "Watch live says what today's Next live row says: the app has no record of whether a church streams."
  - "The owner's preview never shows or writes a member's places (its read leaves them out; its saves answer preview)."
  - "Not checked on a real phone: Playwright Chromium and WebKit at 390x844 @2x. Headless Chromium stops painting after Back with motion on, on main too (Home, Connect, Back); not with reduced motion, not in WebKit. Likely the headless browser; worth a look on a real Android phone."
decisions:
  - "Watch wears the member's look (Light, Dark, Same as my phone), as Look 5.1 draws it white. Lumen Next made every page under Watch a cinema; Live (the room and between services) stays one. One line to turn it back: member_lumen_motion.cine. A member who chose Dark gets the cinema's black on Watch; the floating tab bar's cinema colour now only on a dark page."
  - "Watch: the title, Messages | Series as two links (/my/sermons, ?view=series: no script needed). Messages: the latest on a rounded card (its art, 'Latest · <series>, part n', the serif title, speaker · scripture, and its length once her phone has played it), Watch, Listen (only with an audio file), Share, Save; Pick up where you left off (started 20 s in, not within 45 s of the end or 95%, newest first, up to ten, each with the line of how far and 'n min left'; a card she was listening to opens in Listen); Saved; Every message (twelve, then See all n); Watch live at the foot with the office's weekly time ('Sundays at 10:30 AM') and Add to calendar, else the next gathering the way today's row says it. Live now on top while the church is live. Series: two across, the poster, the months it ran and how many messages; a church's own series art keeps its own title (the name goes under it), a photo or generated poster gets the serif name on it."
  - "A message: the player edge to edge with a round Back (history when the page before was ours, else the series or Watch), the top bar hidden on a phone as the live room does. Video in its own player (sermons_public's embed), opening where she left off (YouTube start=, Vimeo #t=, a few seconds back). Listen, or a message with only audio: our player (the art, Listening, the title, back 15, play, forward 15, the scrubber with both times; the browser's own player without a script). 'Series · Part n of m', the serif title, speaker · scripture · date. Listen | Video, Share, Save, Give (the church's Give, when online giving is on), as many across as there are. Tabs, radios so they switch with no script and arrow keys move: About (the summary in the reading face, 'Read Isaiah 9' into the reader at /my/bible/isaiah/9#v6, each chapter once, up to three), Discuss (the questions numbered: one per line, the office's own numbers taken off; 'Talk about it in <group>' for up to two of her groups whose chat is open to her: messaging on, the group's chat not off, everyone may write or she leads it), In this series (every part, part 1 first, how far, a check when watched, Playing on this one). A tab with nothing in it isn't drawn; one left is drawn without tabs."
  - "A series: its art big with Back, 'Series · <months>', the serif title, the description, Keep watching part n (a part she's in the middle of), else Watch part n (the next after the last she watched), else Play part 1; Share; the parts (· New on one preached in the last week that she hasn't started)."
  - "Where she is: on her own record, contacts.metadata.member_watch.p = {sermon id: [seconds, length, when (unix, the server's clock), v or a]}, the newest 20 (no migration). Video and audio keep their own place (a church's audio is often the sermon alone). Saved on pause, when the page is hidden (sendBeacon, else fetch keepalive) and at most once a minute while it plays: POST /my/sermons/progress (the member session through member_portal_church._signed_in, the same-origin check, its own rate limit member_watch 60 per 10 minutes, her own row, the updated_at guard member_lumen_look.save uses, a place within 5 s of the stored one not written again). Read from the record the session already reads (contacts_for_email and contacts_for_phone select watch:metadata->member_watch): no new read. That record is kept 30 s per server copy, so a save forgets it on that copy, and the phone keeps its newest places for ten minutes (localStorage lw:<who>, in the server's clock) and lays them over what the server drew, on load and when the browser shows a kept page: a pause shows on Watch the moment she goes back."
  - "Save: metadata.member_watch.s = {sermon id: when}, the newest 60; POST /my/sermons/save (the same rules; a form without a script, JSON with one). The bookmark flips at once and turns back if it didn't save."
  - "Share: member_lumen_share's helpers (#1986) on the latest and a message (message_link) and a series (link with series_href, the series' id for Your story); its sheet takes the tap, and without a script the link opens the public page. The share sheet's two tests now find Share where Watch draws it."
  - "Add to calendar: GET /my/sermons/live.ics on the church's own address, public. The day, time and time zone the office saved for check-in (church_checkin_settings; check-in's defaults are not a real time, so an unsaved church gets no card), every week (RRULE), with a VTIMEZONE written from the zone's own changes and the live page's link; no end time (we don't know how long it runs). The read is kept ten minutes per server copy; the phone keeps the file an hour. Switched off it answers what the address answered before."
  - "The mini-player: the media element carries data-lm-media data-title data-sub data-thumb data-href; each save is a lm:progress event on window ({id, pos, dur, m, playing}) and the phone's places are localStorage lw:<who>."
  - "Look: member_lumen_watch.CSS in the Lumen sheet before the type block; tokens only (the player's black is the media's in any look); moves only for no-preference; the script its own file (GET /my/watch.<hash>.js, kept a year, as Share's is)."
  - "member_lumen_give's old Watch (watch, live_row and their rules) and the motion sheet's Watch-only rules are gone; the motion script names the new picture classes for a picture that grows into the player."
related: [2026-11-20-lumen-share.md, 2026-11-20-lumen-dark-light.md, 2026-11-19-lumen-next-motion.md, 2026-11-19-member-lumen-give.md, 2026-11-20-lumen-connect.md]
---
`member_lumen_watch.py` (new) holds Watch (`watch_page`), a series
(`series_page`), a message (`message_page`), her places and saves (`state`,
`clean`, `with_progress`, `with_saved`, `save_progress`, `save_saved`), the
two kept reads (`service_slot`, `talk_groups`), the calendar file (`ics`,
`vtimezone`), the routes (`POST /my/sermons/progress`, `POST /my/sermons/save`,
`GET /my/sermons/live.ics`, `GET /my/watch.<hash>.js`), the script and the
CSS. Wired in: `member_portal_sermons` (render_library and render_sermon hand
the new look to it), `member_portal` (the Watch gather gets the service time,
a message with questions her groups; the household read selects her places),
`member_lumen_motion` (cine is Live; the cinema's bar on a dark page only),
`member_lumen_share` (its link helpers; its tests find Share on Watch's pages),
`member_lumen_ui.templates()`, `rate_limit` (member_watch),
`kmj_intake_automation` (the router). Tests:
`__tests__/test_member_lumen_watch.py` (39); the give, motion and dark tests
now pin Live as the cinema and Watch in her look.

**Checked.** Switch off, as bytes against main: 296 Watch pages x scenes (the
library full, loose, audio only and empty; her places on and off; the service
time on and off; live; Light, Dark, Same as my phone), the home harness's 656
and the Bible harness's 295: identical (/my/sermons/live.ics included). Driven
in Chromium and WebKit (a stand-in for YouTube that speaks its messages):
Listen opens where she left off, play, forward 15, pause saves (Origin: the
page's own), reload opens a few seconds back; with the server's copy held 30 s
old, back on Watch the rail shows the new place from the phone, also from a
page the browser kept; YouTube's place saved with v and opened at start=; Save
pressed at once, on her record, in Saved; the tabs and arrow keys; Talk about
it in Young Adults; the phone's share sheet gets the public link; the .ics.
Rehearsed: the preview writing, no rate limit, no updated_at guard, no bound,
the service time or her groups not kept, a no-op written, a leaders-only chat
offered, the new look when off, no share id, the video's place used for audio:
each went red.

**Measured** (the harness over the test fake, database time about 0; main and
this branch alternated page by page; median of 30 warm, Server-Timing total):
Watch 5.1 / 5.7 ms, Series 5.7 / 4.8, a series 4.7 / 5.2, a message 4.4 / 5.0,
Listen 4.4 / 4.6, audio only 3.7 / 3.8, Home 9.4 / 9.4, Live 4.3 / 4.0 (noise).
Size: Watch 30.7 -> 25.2 KB, Series 30.7 -> 14.5, a message 16.1 -> 21.1 (the
tabs and parts), the script 11.8 KB once per phone. Reads: warm, the same as
main on every Watch page; cold, Watch +1 (church_checkin_settings, kept ten
minutes), a message with questions +2 at a church with messaging on
(group_members, groups, kept a minute), nothing else.

Shots (Chromium and WebKit, 390x844 @2x, light and dark, the mock beside):
the session scratchpad's `l5-watch-shots/`.
