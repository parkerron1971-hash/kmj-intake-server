---
title: ChurchSavvy's countdown counts for minutes, starts by itself, and has designs in the church's colors (server)
date: 2026-11-14
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-14: "countdown clock should be a clock that can be started either we start or a pre service clock starts it that a person can set. countdown clock should be clock that we can set like 5 min or 15 min etc... we should also be able to create different background graphics for it." On the clickable mock: "build and merge everything"'
status: shipped-on-merge
prs: [kmj-intake-server#1863, solutionist-studio#1570]
migrations: []
left_undone: ["CHURCHSAVVY_SUNDAY_TOOLS owner -> on (Thursday, both services); the job runs whatever the switch says unless it is off", "a slide background from the same designs (the next build: bg kind \"design\" reusing worship_show.DESIGNS and the app's show/designs)"]
decisions: ["designs are keys only on the server (worship_show.DESIGNS: glass, light, numbers, ring, haze, drift, night); the screens draw them in the church's brand primary and accent, so the next build reuses the same list for every slide's background", "a countdown item gains design (one of DESIGNS or null for the church's look, as before) and big_last (the last ten seconds in big numbers); a design with look picture reads as big; saved countdowns keep drawing as they did", "a countdown for minutes when nothing in the plan is up is an on-the-spot countdown: adhoc kind countdown, one slide {to (with its zone), title, the same fields a planned countdown has}; adhoc gains show (all | room | online)", "the church's own countdown lives in the look: look.countdown = {design, title, welcome, big_last, times}, times up to 6 of {id, on, days (0 is Sunday), at HH:MM, minutes 1-120, where all|room|online}; no two on the same day and minute", "the schedule sits in the look (one per church, saved by Setup like the crawl's lines), not on a lobby screen: the lobby's week is per screen and keeps its own countdown before each service", "no Lobby TV only: a lobby that runs its own week already counts down to each service; one that follows the booth shows the room's countdown", "worship_count_auto.sweep_tick, every minute on the leader: a time goes up from its minute for 3 minutes on the church's clock (business_marketing.business_tz, the lobby's), counting to the time plus its minutes, marked auto {id, at} so the booth says Started by itself", "it wears the plan's countdown when a service starts within 45 minutes of its end, else the church's own; with no plan to move into, zero shows the logo", "once a day: the day is claimed in the look's row (look.count_fired, server-only, compare-and-set on updated_at) before the live row is written (compare-and-set on rev); save_look carries the claim and clean_look never returns it", "the override rule (busy): it goes up over nothing, off air, the logo or black, a welcome loop, or a countdown that ended 2+ minutes ago; it leaves a countdown counting or held, and anything else the booth pressed in the last 30 minutes", "a read that fails skips the church that minute (no UTC guess); a sample church never gets one; CHURCHSAVVY_SUNDAY_TOOLS=off or WORSHIP_SONGS=off stops it", "GET /worship/live checks the saved row every 5 seconds, so a state written by another copy (the scheduler's) reaches a booth whose copy has no screen waiting"]
related: [2026-10-26-churchsavvy-countdown-crawl.md, 2026-10-26-churchsavvy-timers.md, 2026-10-26-churchsavvy-lobby.md, 2026-10-26-churchsavvy-slide-backgrounds.md, 2026-11-14-churchsavvy-sunday-tools.md]
---
`worship_show.py`: `DESIGNS` and `clean_design` (the shared list), `_clean_countdown`
takes `design` and `big_last` and `compile_item` puts them on the slide;
`clean_count_slide` and the `countdown` kind of `ADHOC_KINDS` (one slide), `show` on
anything on the spot, `auto` kept only with an on-the-spot countdown;
`clean_count_look` (the church's countdown and its times, `look.countdown`), `FIRED_KEY`.
`worship_show_router.py`: `save_look` keeps the server's claim; `get_live` reads through
`_fresh`. `worship_count_auto.py`: the job (`due`, `busy`, `count_slide`, `start_one`,
`sweep_tick`), registered in `kmj_intake_automation.py` as `worship_count_auto`, every
minute. No migration: it fits in the look, the live row and the service's items.

Tests: `__tests__/test_worship_countdown.py` (designs, on the spot, the times),
`__tests__/test_worship_count_auto.py` (the job: its clock, its window, once a day, two
copies, a booth pressing in between, the busy rule case by case, the plan's countdown,
failed reads, the switch), `__tests__/test_worship_show_router.py` (a stale page keeps
the claim; the booth hears a row written elsewhere). Rehearsed red: without the claim
check the countdown came back at 10:16 over the booth's logo; without the carry in
save_look a stale page handed the time back.
