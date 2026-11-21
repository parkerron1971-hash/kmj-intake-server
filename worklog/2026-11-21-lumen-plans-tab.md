---
title: "Member app new look: the Bible tab's Plans as Kevin's design draws it, and six topic plans"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin approved 'Plans built from what Love City already writes' (go ahead): the Plans tab with Continue (the plan in progress, its day row, N days in a row), the church's devotionals as covers, 'What are you walking through?' topic tiles, and the 'Read the whole Bible' shelf. Topic plans are new content: short scripture-only plans, 5 to 7 days, written once in code like the built-in reading plans."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "The 'with your group' line under Continue and the reminder: they need somewhere to keep the member's choice, so they come with the group-and-reminder step (a migration file of its own)."
  - "A devotional's page in the new design, Start over, and the day in steps: the next steps. A devotional's cover still opens today's devotional page and day."
  - "A reading plan's or a topic plan's day opens the Bible reader at its first passage; the day page that shows every passage with Mark done comes with the day in steps."
decisions:
  - "Topic plans (topic_plans.py): Anxiety, Healing, Purpose, Marriage, Money, Grief, seven days each, a plain title a day naming the passage and one or two well-known passages; every passage is read from the app's own Bible in the member's translation. They behave like the built-in reading plans: started on the member's own day in member_plan_starts ('reading:topic-anxiety'), a day opens each day, ticks in reading_progress (plan_key 'topic-anxiety'). Both tables' checks already allow the keys: no migration."
  - "The tiles are colour and an icon, no photos (nothing of Love City's ships as a platform-wide picture). A topic keeps its own colour whatever the church's."
  - "From <church>: the devotional's picture spot (or a church photo named for it, as today's covers choose) always drawn in the church's colour with the title in serif; with no picture a cover made of the church's colour. Up to eight; See all opens the full list."
  - "Continue: a running devotional the church dated, else one the member started, else their own latest reading or topic plan, else the church's reading plan. Its day row is real progress (seven circles at most, today ringed); 'N days in a row' shows only from two and only where the days could be read."
  - "A plan's page for reading plans and topic plans (member_lumen_plans.render_plan), started or not, so every tile and cover opens something: Start, Continue day N, You finished it, every day (a long plan the two weeks around today and up to 14 to catch up), a tick per day on the reading plans' own route, Stop back to Plans. Off, these addresses do what they did (an unknown plan, a reading plan not started: today's redirects)."
  - "Reads: everything the tab reads is kept (member_cache.Kept): the church's devotionals and the Continue devotional's days a minute per church, the member's starts, days done and the Continue plan's ticks 30 s per member. Every write to a member's plans (start, stop, a tick, a devotional's day) forgets them on its server copy and gives the phone a new plans version cookie (lm_pl, part of the key), so the next page on any server copy reads afresh. Off, no cookie is written."
  - "CSS only through member_lumen_ui.templates(): member_lumen_plans.CSS right after the devotional's block, so the order still ends share, mini, fonts. Every rule under body.lm, the page's tokens; the hero and covers are their own dark plates with white words, so Light, Dark and Same as my phone read the same."
related: [2026-11-20-lumen-bible-tabs.md, 2026-11-21-lumen-tab-tops.md]
---
The Bible tab's Plans in the new look, as the approved design draws it, with six topic plans every church gets.

Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps each (Home harness 656,
Bible harness 295): same 951, differ 0 against main, both. Reads with the switch on, per page and table, in four
looks: Home harness 1984 / 1984 over 328 page-looks; Bible harness (its 59 pages plus the Plans tab and three plan
pages) 1358 on main, 1280 here over 248 page-looks. Coming back to Plans reads nothing (main read 4 each time:
devotionals, devotional_progress, member_plan_starts, reading_progress); a plan's page reads nothing coming back
(main 2). A first visit reads the same tables once (and the Continue devotional's days when the catalog has none).
Member suites with the Bible and devotional ones: 1652 passed, one page comparison in test_member_mini flaked once
and passed on rerun (it passes alone on main and here). Shots before and after (Chromium and WebKit, light and dark,
390x844 @2x, the Bible harness with Love City's Consecrate Your Focus seeded from the design page's day titles and
scriptures) in the session scratchpad's plans-build-shots/pr1/.
