---
title: Member app new look — Light, Dark or Same as my phone
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, on the member app''s new look (Lumen): "the new look need to allow dark or light option ... in settings giving the member option to have dark or light look."'
status: shipped
prs: [kmj-intake-server — Lumen dark and light]
migrations: []
left_undone:
  - "Stripe's own payment form on Give (embedded Checkout, after tapping Give) keeps Stripe's light style in Dark: its colours are the Stripe account's branding, not the page's."
  - "MEMBER_APP_FAST=off (the whole sheet inline, the way back): a handful of today's rules that use the church's colour directly (rgba tints of the button colour) keep their light shades in Dark. The default (the shared sheet) has none of this."
  - "Youth and Kids keep their own looks (Youth is already black; Kids its cream). The pages before sign-in keep today's look."
  - "The Bible's devotional covers with no photo (peach, lavender, mint) stay those colours in Dark, as book covers do; the ivory verse card stays ivory (as on the board)."
  - "Not checked on a real phone: Playwright Chromium and WebKit at 390x844, with the phone set light and dark. Headless WebKit on Windows draws Figtree at one weight."
decisions:
  - "Where: Me (the member's own page, from their picture at the top right), between Your giving and the list. One control, Look: Light · Dark · Same as my phone, three radios in one group (arrow keys move between them), the look they have now checked. Picking one turns the page at once and saves in the background ('Saved'; if it doesn't save, the page turns back and says so). Without script, a Save button posts and Me comes back in the new look."
  - "Who gets what: the member's own choice wins. Until they choose, the church's base (settings.member_portal.base): Black, and a church that never picked one (today's default is black), is Dark; White, Light gray and Dark gray are Light, as asked. Same as my phone is CSS (prefers-color-scheme) on body.lm-auto: nothing flashes."
  - "Kept on the member's own record, contacts.metadata.member_look (no migration), written like the member's photo (guarded by updated_at; only the signed-in member's own row; member_portal_church._signed_in gives the session and the same-origin check; the member action rate limit). Read from the record the session already reads (look:metadata->member_look added to the household read): no new read. That record is kept 30 s per server copy, so the save also sets lm_look (look, when, a hash of whose) on /my, which wins for two minutes after a save and then hands back to the record: a change on another phone reaches this one. The owner's preview never writes as the member: the cookie alone, on the owner's browser."
  - "The colours: one dark layer over the white page (member_lumen_ui.DARK_TOKENS), the approved board's near-black (#0A0A0B, surfaces #161618/#202023/#2E2E32, words #F4F2EE/#AAA7A1/#8F8C86: at least 14.5:1, 6.7:1 and 4.8:1 on the page and its two surfaces). The church's colour for words is its lit shade (4.5:1 on black) lightened in oklab the way the reader does; its button colour stays the church's unless it's too deep for near-black (then a lifted one from the palette's own dark-base rule, only on that church's dark pages: member_lumen_look.dark_tokens). Family inks their dark shades, hairlines white at 10%, tints of the church colour over near-black (12/8/16/26%), photos untouched. Written once and used twice (member_lumen_ui.dark): under body.lm.lm-dark, and under body.lm.lm-auto in a prefers-color-scheme: dark query."
  - "Every Lumen surface got its dark rules where the light ones had fixed colours: the group faces and group art with no photo (mint becomes a deep teal), Classes' live line, the gold button's words, the logo plate's ring, Home's badge ring. Home's own dark block (#1977, never switched on) is the look's now. Give draws its own document: lumen_chrome and lumen_head_look give it the look's class and bar."
  - "The reader's moon (the Bible reader and a devotional's day): the reader's own switch on top of the look, on this phone (lm_night: 1 night, 0 day, none: follow the look). Dark starts the reader at night; Same as my phone leaves it to the phone. Tapping the moon to what the look would give anyway clears the cookie (the reader follows the look again). Choosing a look on Me clears it. The reader's night stays its warm night (#100E0B), now scoped to the reader and a devotional's day; its quietest words lifted from #80786B to #857D70 (4.4 to 4.7:1). Watch and Live stay the cinema whatever the look."
  - "The phone's bar matches: #ffffff Light, #0A0A0B Dark (the reader's #100E0B, the cinema's #050506), two bars by media for Same as my phone. The page's edge (html) matches too."
  - "MEMBER_LUMEN=off: every page × scene byte for byte main's (935 dumps: 80 pages × 8 scenes on the home harness, 59 × 5 on the Bible harness with the moon cookie 1, 0 and none), also with the member's stored look Dark and both cookies set. Switch on: Light chosen is identical to nothing chosen at a white church (935 dumps), and differs from main only on Me (the control) and the reader and a devotional's day (the moon's script)."
  - "Reads: the same reads per page on main and in every look (139 pages, 818 reads, Light/Dark/Same as my phone/nothing chosen). Server-Timing medians within the run-to-run noise (about 1 ms on the local harness); Dark pays about 0.2 ms only on a church whose colour needs lifting."
related: [2026-11-19-lumen-home-top.md, 2026-11-19-lumen-next-devotional.md, 2026-11-19-lumen-next-motion.md, 2026-11-19-member-lumen-home-feed.md]
---
`member_lumen_look.py` decides the look (`resolve`, `decide`, `page_look`),
saves it (`save`, `POST /my/look`) and draws Me's control (`control`);
`member_portal._shell` puts it on every new-look page; the dark layer is
`member_lumen_ui.DARK_TOKENS` and each block's own dark rules, each passed
through `member_lumen_ui.dark()` so Same as my phone gets the same rules.

**Server-Timing.** Local, the home and Bible harnesses over the test fake
(database time about 0). Median total of 30 warm requests, switch on,
servers alternated page by page:

| Page | Main | Light | Dark |
|---|---|---|---|
| Home | 7.0 ms | 6.0 ms | 7.1 ms |
| Me | 2.8 ms | 2.8 ms | 3.2 ms |
| Connect | 4.5 ms | 4.2 ms | 4.2 ms |
| Give | 2.5 ms | 2.9 ms | 3.3 ms |
| Messages | 6.8 ms | 8.0 ms | 7.6 ms |
| Watch | 3.6 ms | 3.9 ms | 4.4 ms |
| Bible | 6.0 ms | 5.8 ms | 6.0 ms |
| Reader | 3.5 ms | 3.8 ms | 4.3 ms |
| Devotional day | 4.2 ms | 4.0 ms | 4.5 ms |

A first run gave Home 8.2/7.9/8.0 and Messages 6.8/6.8/7.8: the spread is
noise. Page size: unchanged except Me (+2.1 KB, the control and its script)
and the reader and a day (+0.5 KB, the moon's script). The Lumen sheet grew
by the dark layer and its twin.

**Tests.** `__tests__/test_member_lumen_dark.py` (31). The Lumen fixtures
now say Ana picked Light (their church's base is black, which is Dark until
a member chooses). Rehearsed: no twin for Same as my phone, a save without
the member's id, no cookie bridge, no lifted button colour, the moon's cookie
kept on a save, the preview writing, the look never decided, the moon not
told the look, the rate limit off: each went red. Driven in Chromium and
WebKit: the control turns the page at once and saves, Back shows the new
look, Same as my phone follows the phone both ways, the moon by day and back.
