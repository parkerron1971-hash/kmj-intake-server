---
title: ChurchSavvy lower thirds by themselves, from the booth over anything, and lower third designs (server)
date: 2026-11-15
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-15: "could we also have a way to place lower thirds if we need to do lower thirds by itself. for example if we created a lower third or like the background but prefer lower thirds having that option." On the plan: "let''s do it you can just start building" (no mock)'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the app: the plan item, the booth, Setup, every screen)]
migrations: [supabase/APPLY-2026-11-15-worship-screen-words.sql (applied 2026-11-15, SQL editor; read back)]
left_undone: []
decisions: ["a lower third item, kind third: {name (needed, 60), sub (80)}, one line each; its own background (BG_ITEM_KINDS) is drawn behind it in the room", "as_third on song, scripture and text items, written only when true, rides on every slide it makes", "look.lower_third.style is one of LT_STYLES (bar, shadow, glass, stripe, tag, band); bar and shadow unchanged; look.thirds up to MAX_THIRDS 10 of {id, name, sub}", "the booth's lower third is live state, like the crawl: third {name, sub, show all|room|online, at, seconds 3-600 or null, id}; a press that says nothing of it keeps it (carry_third), null takes it down, the auto countdown keeps it", "a room screen's or LED wall's words: worship_screens.words {as: slides|thirds|see_through}; read with the column and without it once PostgREST says 42703 (a minute at a time, like sunday_planning)", "save_look refuses a look past worship_settings' 8000-byte check with words saying what to take out (it was a 503)"]
related: [2026-11-14-churchsavvy-fonts-backgrounds.md, 2026-10-26-churchsavvy-countdown-crawl.md, 2026-11-15-churchsavvy-words-shadow.md]
---
`worship_show.py`: the `third` item kind (`clean_third_words`, `compile_item`'s one `third`
slide), `AS_THIRD_KINDS` and `as_third`, `LT_STYLES` and `_clean_lower_third`, `_clean_thirds`
(`look.thirds`), `clean_live_third` and `carry_third` (`clean_live`'s `third`), `clean_words`
(`WORDS_AS`). `worship_show_router.py`: the screens' tolerant reads and writes
(`_screens_call`), `_clean_screen`/`_screen_out` `words`, `set_live` carries the lower third
when a press doesn't send it, `save_look`'s size guard. `worship_count_auto.py` keeps a lower
third over the countdown that starts by itself. `sunday_order._name` calls a lower third item
by its name line in Sunday Planning's order (not "Words on screen").

Tests: `__tests__/test_worship_lower_thirds.py` (15), `__tests__/worship_show_db.mjs` (the
column). Rehearsed red: without the carry in set_live, without the column fallback, and
without the carry in the auto countdown, each fails.
