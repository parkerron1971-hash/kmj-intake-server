---
title: Member app new look (Lumen) — Give, Watch and Live, and solid bars
date: 2026-11-19
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, on the member app: Give "looks generic and not top tier. this should be update to be the best", and live has "no wow factor". He approved the "clean Lumen" mock, version 29, accent level 2. Port Give, Watch and Live to it (look and layout, never the mock''s made-up content), keep every giving flow exactly as it works, and make the Lumen tab bar opaque (text showed through it, clearly in WebKit).'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Give's 'Your giving · 2026' block has no total or month bars: those need the year's gifts (member_portal.gifts_for, not cached), a new read on every Give. It links to Me (each gift and the statement) and Recurring gifts instead."
  - "The thank-you sheet can't say '$100 to Tithes every month': after Stripe the page has only ?thanks=1. It says today's banner words under 'Thank you, <first name>.'"
  - "No amount is picked at first (the mock shows $100 picked): today's form starts empty and Give stays 'Give' until an amount is chosen, so the large amount reads $0 in grey until then."
  - "Watch's live row says 'Live now' without '124 here': the count is read only in the room. The room shows it on the video (its own read, as today)."
  - "Chat faces are initials on the family colours (the chat has no photos). Series art is the church's own, else today's generated poster, kept 16:9 so a church's artwork isn't cropped (the mock's posters are made up)."
  - "A series, a message and /my/gifts keep today's markup under Lumen's white tokens and bars."
  - "LIVE_ROOM=off (the rollback, render_live while live) is today's live page under Lumen's tokens."
  - "Not checked on a real phone: Playwright Chromium and WebKit at 390x844 with reduced motion, and 1280 wide in Chromium."
decisions:
  - "Give keeps giving_router.render_give_page: the same document, embedded Stripe decision, amounts, funds, frequencies, fee cover, card or bank, and the same script byte for byte (a test checks). The page takes three more app keys only the new look passes: form (the new form's markup, called like _give_body), body (the body tag's attributes) and bar (the Lumen top bar, before <main>). Without them the page is byte for byte as it was (the public /give included)."
  - "The new form draws every id, gv- class, data-cents/data-freq/data-pay value the script reads (a test compares it with _give_body's and checks every getElementById). Funds are chips that set the same hidden <select id=gv-fund>; the script still sends that. The member's name and email ride in the form as today; with an email on record they fold under 'Receipt to …' (Change opens them)."
  - "GIVE_JS (the new look only) keeps the large amount and the fund · how-often line in step after the page's own script fills the form from a link (?amount=&fund=&frequency=, which the live room's Give sheet uses), and opens the thank-you <dialog> holding the same #gv-thanks when the script marks it shown; Done takes ?thanks off the address."
  - "Give's Lumen frame is member_portal.lumen_chrome: the same top bar, body class, tab bar (with the early loading) and scroll script _shell draws, from _marks (the brand and the picture, now one function _shell uses too)."
  - "Watch: member_lumen_give.watch reads exactly what today's Watch reads (library, live, the next gathering). A series (?series=) keeps today's page."
  - "The live room keeps every id ROOM_JS reads except lv-clock (the clock chip is now 'Live · N here' on the video; the script skips a missing clock). The count's id (lv-herewrap) moved onto the chip, so the poll's setN keeps it fresh; a failed count read leaves it hidden, never '0 here'. Give moves into the box beside the heart while the chat is open, and stays with I'm here when it's closed or the member is paused. On a phone the room starts at the video with a round Back on it (the top bar hides, :has, as the room's own CSS already relies on); on a computer the top bar stays."
  - "Between services: the church's photo (or default art), Between services, the next service, the latest message, the verse and prayer, from member_portal_lumen's pieces."
  - "CSS is its own block, member_lumen_give.CSS, the last part of member_lumen_ui.templates() after the Bible's and Classes' (member_app_ui's lumen sheet is built from that), every rule under body.lm. Only the lumen sheet's hash moved."
  - "Bars: the Lumen tab bar is var(--bg) with a 1px top border and no backdrop filter (it was --bar, white at 82%). The scrolled Lumen top bar is solid too (same see-through in WebKit). (A main tab's sliding title landing on the church's name was fixed in #1960, the Bible and Classes PR.)"
  - "Off is byte for byte today's look: 216 member pages (12 scenes: giving on/off × LIVE_ROOM on/off × normal day, Sunday, live; 18 pages each, Give and the thank-you, Watch, a series, a message and the room among them) plus the public /give page, compared against origin/main through the harness, all identical."
related: [2026-11-18-member-lumen.md, 2026-11-18-member-app-tabs-fast.md, 2026-11-18-member-app-stopwatch.md]
---
`member_lumen_give.py` holds Give, Watch and Live in the new look and their CSS block.
Tests: `__tests__/test_member_lumen_give.py`.

Measured locally (the foundation's harness over the test fake, so database time is ~0;
5 warm-ups then the median of 30 Server-Timing totals, off / on): Give 2.2 / 3.1 ms (the
new top bar's brand lookup, which every other tab already pays), Give before online giving
2.0 / 2.2, Watch 4.0 / 3.5, Watch while live 3.5 / 3.2, the live room 2.8 / 3.3, between
services 3.2 / 4.2, Home 7.0 / 7.2. Medians move about a millisecond run to run. Reads per
page are the same off and on (a test counts them): Give 2, the room 4, the rest 0 beyond the
library, live and calendar readers both sides call.

Instant send in the room checked in Chromium and WebKit, on and off: the message is in the
chat the moment Send is tapped (faded), the box clears, the server's answer settles it;
hearts and the Prayer and Give sheets open.

Before building, worklog/ had the foundation's notes (2026-11-18-member-lumen.md) listing
Give, Watch and Live as follow-ups; nothing else on them.
