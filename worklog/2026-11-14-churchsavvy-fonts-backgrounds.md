---
title: ChurchSavvy fonts, a background library, and a look for a sermon series (server)
date: 2026-11-14
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-14: "background and font choices would be a huge help as well". On the clickable mock (Fonts and backgrounds, idea 3 of 3): "build and merge everything", then "switch it on now"'
status: in progress
prs: [kmj-intake-server (this PR), solutionist-studio (the app: the picker, the library, the series editor, the screens)]
migrations: []
left_undone: ["Kevin reviews and merges both PRs; the server first is safe: a look without the new keys saves and draws exactly as before", "the editing is behind CHURCHSAVVY_SUNDAY_TOOLS (owner first, #1861); the What's New entry goes in the switch-on PR"]
decisions: ["look.fonts is one of FONT_PAIRS (clean, modern, poster, classic, warm, quiet, strong, gentle) or None: the brand's typeface as before; the old look.font stays and still draws when no pair is picked", "a background may be kind design with a design key from BG_DESIGNS (glass, linen, stones, night, light, haze, drift, water, duo), for the look and for a slide's own (clean_bg); the design key is only written for a design, so old backgrounds come back key for key", "DESIGNS gains linen, stones, water and duo; numbers and ring stay the countdown's own (not in BG_DESIGNS); a countdown may wear any of the eleven", "look.series: up to 12 of {id, name, from, to (YYYY-MM-DD, both days count, at most a year), fonts, background}; no two share a day; a series wears only its fonts and background, the rest is the church's", "the effective look: worship_show.look_on(look, day) adds wearing {id, name, from, to}; the router's _worn gives it to the booth's show and every screen's show for the service's day on the church's clock (business_marketing.business_tz; a failed read is a 503, and only a church with series reads it), the lobby for its own today", "GET /worship/look stays the church's own (what Setup edits); a look sent back with wearing (the booth saving a crawl line or the countdown's times on that Sunday's look) keeps the church's own fonts and background in save_look"]
related: [2026-11-14-churchsavvy-sunday-tools.md, 2026-11-14-churchsavvy-countdown.md, 2026-10-26-churchsavvy-slide-backgrounds.md]
---
`worship_show.py`: `FONT_PAIRS` and `clean_fonts`; `_clean_look_bg` (the look's background,
now with a design, shared by the look and each series); `BG_DESIGNS` and the four new
`DESIGNS`; `clean_bg` takes a design; `_clean_series`, `look_on`, `WEARING_KEY`.
`worship_show_router.py`: `_church_zone` and `_worn` (the show for the booth and the screens),
`save_look` keeps the church's own fonts and background when a worn look comes back,
`screen_lobby` wears the series on its own today. No migration: it all fits in the look.

Tests: `__tests__/test_worship_show.py` (an old look and old backgrounds key for key, the eight
pairs, a design behind the words and on a song or point, a series on its first and last
days and not after, 15 refusals), `__tests__/test_worship_show_router.py` (the booth and a
screen's link wear it, a 7:30 PM service on the last day on New York's clock, the clock
that can't be read is a 503 only with a series, a worn look saved back keeps the church's,
the lobby), `__tests__/test_worship_countdown.py` (the list grew; numbers and ring stay the
countdown's). Rehearsed red: without the guard in save_look, without `_worn` on the show,
on UTC instead of the church's clock, and without the lobby's, each test fails.
