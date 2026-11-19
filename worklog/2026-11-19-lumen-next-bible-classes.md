---
title: Member app Lumen Next — the reader at night, the ink, Make a card, the certificate moment
date: 2026-11-19
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, on the Lumen Next mock (artifact 2nFp9X3q…): "go with font A and build all the moments". This is the Bible and Classes share: night reading, the ink highlight, the verse card, and the gold-foil certificate.'
status: shipped
prs: [kmj-intake-server — Lumen Next Bible and Classes moments]
migrations: []
left_undone:
  - "Not checked on a real phone. Tested in Playwright Chromium and WebKit at 390x844 with motion on, including mid-animation frames. Not tried: Share handing the card picture to the iPhone share sheet (navigator.share with files), and Save on iOS."
  - "A preview (Settings → Member page → Preview as a member) has no highlighter, so it has no ink and no Make a card. The moon and the line of how far you've read do show. Kevin sees the card and ink only when signed in as himself."
  - "The certificate has no date: academy_member_classes doesn't return when the course was finished, and reading it would be a new read. It shows the church's name, the lesson count, and the certificate code when the course has one."
  - "The mock finishes a lesson inside the app ('Finish lesson 6'). Lessons are taken in the classroom (academy_join.CLASSROOM_BASE), so the moment comes on the member's next visit to Classes."
  - "The card uses --mb-serif and --mb-ui, so it follows whatever fonts the church picks once the fonts change lands."
  - "The devotional pages are untouched: Kevin asked where the devotional section is, and that is a new mock round."
decisions:
  - "Behind the same switch (member_lumen.page()). With MEMBER_LUMEN=off, 96 page×scene dumps are identical to main's, ignoring clock times, which the fake makes as 'now'. They are also identical with the night cookie set: today's reader ignores it."
  - "No new reads: the reader and Classes read the same rows off and on, with or without the night cookie (tests). The card's church photo and logo come from member_app_photos.photos and resolve_theme, which read the business row and site files already in hand."
  - "Night reading: the moon beside Aa in the reader's bar sets the cookie lm_night=1 (Path=/my, a year, SameSite=Lax, Secure on https). The server reads it, so the page arrives dark with no flash. _shell's new lumen_dark adds body.lm-dark and the phone's bar colour (#100E0B), under Lumen only. The bar, the dock, the chapter steps and Aa follow by colour tokens. Only the reader reads the cookie; the Bible tab and Home stay white."
  - "How far you've read: a 2px gold line along the bottom of the reader's bar, scaled with scroll."
  - "Ink: a highlight paints as a background that sweeps from 0 to 100% width over 0.9s, line by line (the mock swept every line at once). It uses today's saved highlights (member_bible_marks), unchanged. With reduced motion it appears at once."
  - "Make a card: a 'Make a card' button in the verse dock opens a sheet. The phone draws the verse on a 1080×1350 canvas in Ivory, Photo (the church's first photo, gray and warm-dark), Night or Church (its colour), with the reference, the translation, the church's name and its logo, or its initials when there is none. Share hands the picture to the phone (Web Share with a file; text where files can't be shared); Save downloads it. Nothing is sent anywhere. A photo or logo from a site that won't let the canvas read it is left out (the Photo look goes away) rather than spoiling the picture."
  - "Certificate: a finished course gets a Certificate button, on the path and in Your classes. The dialog springs in: the seal pops, and the course title shimmers in gold foil with its last word in italics. It shows '<name> finished all N lessons.', '<church> · Classes · No. <code>', Share, and Next course (to Classes you can join) or Done. It opens on its own once, when a course the phone last saw in progress is now finished; the phone keeps that list in localStorage, and with no storage it never opens on its own. No name a church didn't choose (no 'Academy')."
  - "The card sheet and the certificate move themselves to <body> so they sit above the bar, the tabs and the verse dock. Escape closes them from anywhere; Tab stays inside."
  - "CSS lives in member_lumen_bible.CSS and member_lumen_classes.CSS, under body.lm. The test now allows @keyframes, which must be named lm-*."
related: [2026-11-18-member-lumen-bible-classes.md, 2026-11-18-member-lumen.md]
---
The reader's new script, `member_lumen_bible.READER_MORE_JS`, runs beside
today's reader script and leaves it unchanged. The certificate's script is
`member_lumen_classes.CERT_JS`.

**Server-Timing.** Measured locally: the Bible harness over the test fake,
so database time is about 0. Median total of 30 warm requests, off / on:

| Page | Off | On |
|---|---|---|
| Reader | 1.9 ms | 2.3 ms |
| Classes | 1.4 ms | 1.4 ms |
| Bible tab | 4.5 ms | 3.5 ms |

**Page size.** The reader under Lumen grew from about 26 KB to 37 KB
uncompressed, mostly the inline card script. Classes grew from 15 KB to
19.5 KB.

**Tests.** `__tests__/test_member_lumen_bible.py`, five new tests.
