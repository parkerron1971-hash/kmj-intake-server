---
title: "Member app new look (Look 5.1) — Share: the share sheet, story pictures, and Share wired into the message page, Watch, Coming up and the reader"
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Look 5.1 approved by Kevin ("this is awesome. much better design. lets build this including the new still to build!"): members share the church''s own content out to their own socials (messages, events, verses, moments) with a public link and a "Your story" picture; member posts, prayers and family photos never.'
status: in review
prs: ["kmj-intake-server (Look 5.1 Share)"]
migrations: []
left_undone:
  - "Moments: no moments record exists yet. kind=moment takes <message|series|event>:<id> and shows that thing; a moment with no public page gets no share."
  - "A series page has no share yet (it is still today's markup; the Watch helper rebuilds it). The kind, its public link (/sermons#sm-s-<id>, the public library's heading) and its story picture are ready."
  - "Events link the public events page (/events), which has no page per event; the share text carries the event's name."
  - "Verses link the church's site (/), with the verse written in the message; the story picture prints KJV, WEB, BSB or ASV (the reader's public-domain texts); a licensed version asked for falls back to KJV."
  - "Fonts: the faces' latin files, latin-ext when a name needs letters past Latin-1; nothing else (no Greek, no Cyrillic)."
  - "Not checked on a real phone: navigator.share with a file (Your story) and the sms: link only run on a phone. Chromium and WebKit (Playwright, 390x844 @2x) checked the sheet, focus, Escape, the dim, the swipe's code path is untested by a finger."
decisions:
  - "One global script for every new-look page with a share control, from its own file (/my/share.<hash>.js, kept a year, deferred); _shell adds the tag only when the page's markup has 'lm-share'. The sheet's markup is built by the script on the first tap, so no page carries it."
  - "Contract 1 plus two optional attributes: data-share-id (the story picture's id; a message's is read from its /sermons/<id> link) and data-share-text (words for the message, a verse). member_lumen_share.link()/attrs() write it, escaped, and refuse anything that isn't a church kind."
  - "The sheet: the card (picture, title, line), Your story (the PNG fetched as the sheet opens, handed to navigator.share with the file, else saved), Text a friend (sms:?&body= title + link), Copy link (toast 'Link copied'; a verse copies the verse and link), More apps (navigator.share title + url, else copy), one line on where the link opens. Closes on the dim, a swipe down, Escape while the sheet has the focus (its own listener; no page-wide keydown). Dialog role, aria-modal, labelled; focus into the sheet, Tab kept inside, focus back to the control."
  - "Story pictures: GET /my/story/<kind>/<id>.png, 1080x1920 PNG, Pillow with the self-hosted woff2 faces in the church's pairing (member_lumen_fonts). Looked up by id AND this church (another church's id is a 404); messages published, series with a published message, events public while the public events page is on, verses from bible_text. Signed-in member or the owner's preview, where the new look shows; rate limit member_story 40 per 10 minutes per member; a failed read is 503 and never kept. Kept: the looked-up thing five minutes, the PNG by what it shows (48 MB per server copy), Cache-Control private 10 minutes with an ETag."
  - "Pictures on a story: only the church's own: its site's files from disk, or its own folder of our public storage (the Supabase host, /storage/v1/object/public/, this church's id in the path); never another host, so nothing inside the network can be asked for. 12 MB and 40 megapixels at most; JPEG/PNG/WebP only. An event's picture must already be public on the church's website (its media library shown there, its site's files): a picture uploaded only into the app stays in the app. Members' photos are never in reach (they're signed links in a private bucket)."
  - "The layout: the picture under a calm scrim of the church's deep colour (a veil behind the name as deep as the picture is bright, clear through the middle, deep under the words), the church's mark and name, the small capitals in the church's lit colour, the title in the heading face (balanced lines), its line, a short rule, the public link as words; everything inside a story's safe area. A verse: the church's deep colour with one soft light, a large quote mark, the verse in the reading face's italic, its reference and version."
  - "Wired in (new look only): the message page's Share (today's button and SHARE_SCRIPT gone there), Watch's latest-message Share, Coming up (a quiet share icon beside a public occasion's title while the public events page is on; upcoming_for now marks each occasion public or not), the reader's Share (the tapped verse, data-share-from=reader). Today's look keeps its button and script byte for byte."
  - "Behind MEMBER_LUMEN. Off is byte for byte main's (dumps below). No migration."
related: [2026-11-20-lumen-tidy-ups.md, 2026-11-20-lumen-dark-light.md, 2026-11-19-member-lumen-give.md, 2026-11-19-lumen-next-bible-classes.md]
---
`member_lumen_share.py` (new) holds the markup contract (`attrs`, `link`,
`message_link`, the public links, `event_shareable`, `event_picture`), the
sheet (`SHEET`, `NOTES`, the script `JS_TEXT` at `/my/share.<hash>.js`,
`page_js`), the CSS, and the story pictures (`lookup`, `lookup_kept`,
`church_marks`, `picture_bytes`, `open_picture`, `render`, `picture`, the
route). Wired in: `member_portal._shell` (the script on a page with a share),
`member_portal_sermons.render_sermon` and `member_lumen_give.watch` (Share),
`member_portal_church` (Coming up's share, `upcoming_for`'s public mark),
`member_lumen_bible.render_chapter` (the dock's Share), `member_lumen_ui.templates()`
(the CSS before the type block), `rate_limit` (member_story),
`kmj_intake_automation` (the router). Tests: `__tests__/test_member_lumen_share.py`
(22); the reader and Watch tests now pin the sheet in place of today's button.

**Checked.** Switch off: 951 page x scene dumps (the Home harness's 656, the
Bible harness's 295) identical to main (normalised for clock times and
random ids); MEMBER_LUMEN=preview for a member who isn't the platform owner,
the same 951 identical. On: only the readers, Watch and the message pages
differ from main (the sheet's address aside).

**Measured** (harness over the test fake; Server-Timing total, median of 30
warm, light look): Home 12.0 / 10.8 ms, Watch 6.4 / 6.5 (interleaved, 120
each), a message 4.8 / 4.7, Coming up 4.2 / 4.1, the reader 5.1 / 4.9. Reads
per page (warm, switch on): Home harness 496 / 496 over 82 pages, Bible
harness 341 / 341 over 59, no page different. A message page is 0.3 KB
smaller (its inline share script became the shared file).

Shots (Chromium and WebKit, 390x844 @2x, light and dark, reduced motion,
the mock's a-share frame beside): the session scratchpad's
`l5-share-shots/side-by-side/`, the raw ones in `l5-share-shots/r2/`.
