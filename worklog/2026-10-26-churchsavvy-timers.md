---
title: ChurchSavvy's timers from the plan, the service clock and the preacher's ask (round 5, server)
date: 2026-10-26
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-25: "We need to create able to adjust count down clock for sure… there is so much upgrade this needs"; 2026-10-26 on the round 5 canvas: "these are a go. build it"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the booth's timer, the stage, the preacher's phone, the order's planned / took)]
migrations: []
left_undone: ["the lobby on its own (board 26)", "ministry links to send announcements (board 20) and the calendar import"]
decisions: ["an item's timer is its plan's minutes from when it went up; the booth's +1 / Hold rides in the same live `count` the countdown uses, dropped when the item changes", "the ask is live state (`ask`), written by a stage screen's link with no sign-in (POST /worship/screen/{token}/ask, stage screens only, 5 minutes, one waiting at a time); the booth answers yes or no in the same `ask`", "the server keeps the ask through a booth press that didn't carry it, and of two asks the newer wins, so a stale booth can't undo one", "the server keeps the service's log (`log`, a line per item as it goes up, at most 80); the booth never sends one", "no table: it all fits in the live row's state"]
related: [2026-10-26-churchsavvy-countdown-crawl.md, 2026-10-26-churchsavvy-announcements-board.md]
---
`worship_show.py`: `clean_ask`, `carry_ask`, `carry_log` (and `_iso`, a time with its zone); `clean_live` takes `ask` and drops any `log` a booth sends. `worship_show_router.py`: `set_live` carries the ask and the log from the state before; `_put_live` (publish, then save) shared with the new `POST /worship/screen/{token}/ask`. Tests: `__tests__/test_worship_timers.py` (rehearsed red: without `carry_ask` in `set_live`, the booth's next press drops the ask). Canvas UZu4VsoY9KemkUGorz234j board 24.
