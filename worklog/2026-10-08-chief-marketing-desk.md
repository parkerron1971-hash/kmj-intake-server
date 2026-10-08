---
title: "Chief works the marketing desk: read, new post, change, skip, the week again, post now (marketing suite B10)"
date: 2026-10-08
agent: Claude Code (Claude Opus 5.5)
asked: "This will work. let's build this."
status: waiting on Kevin
prs: [kmj-intake-server#1339]
migrations: []
left_undone:
  - "Kevin: merge. Nothing changes for a business until MARKETING_DESK covers it (the verbs say 'not switched on yet' and no context block is read); post now also needs MARKETING_DESK_PUBLISHING=on and the posting pilot, exactly as the desk's own Post now"
  - "Not seen live: a chat turn against a real desk. The first live check should be a test business on the desk: 'what's waiting on my desk?', 'put a post on Thursday', 'change it', 'skip it', and (with sending on) 'post it now'"
  - "Frontend: the desk shows source 'chief' posts like any other; a 'from Chief' tag on them, and the level-aware masthead/Today words reaching the phone view, are F4's to check"
  - "B13 (standing permissions) is where Chief may ever approve a kind of post on its own; B10 has no approve verb by design"
decisions:
  - "Same functions, no second write path: marketing_desk -> business_marketing.engine; new post -> create_idea (new source kwarg, 'chief'); change -> edit_slot; skip -> cancel_slot_route; post now -> post_existing_now / create_idea(post_now=True); the week again -> business_marketing_planner.run_route"
  - "Classes: marketing_desk read; marketing_new_post, marketing_edit_post, marketing_skip_post A; marketing_replan C (can start up to five paid flyers; never unprompted); marketing_post_now C (public; CLIENT_FACING; refused unattended before anything is read; a voice turn is held for a spoken yes)"
  - "Native vs tag: the read is a native tool (TOOL_SCHEMAS; on the read-only agent surface too, tripwire 37 -> 38, silent). Every write is a tag: WRITE_TOOL_SCHEMAS is also the outside agent's write list, and desk writes need the owner signed in on this chat turn, which that surface does not carry; the table also keeps out public-shaping writes and spenders, and class C is never a tool"
  - "No approve verb; a guard test fails if one appears or if the module reaches the approve route or RPC"
  - "Owner-only writes (_TURN_USER_ID vs businesses.owner_id through business_marketing._owner_row); members read; every change names post_id + revision and a stale revision changes nothing"
  - "Level: a replan asks for what level_for gives; asking for more names the server's upgrade label, never a plan written in code (a test greps the module for plan names)"
  - "Sent/posted only from the post's status (submitted/published); post now says 'approved, goes out at <time>'"
  - "The turn's MARKETING DESK block rides the per-message tail (appended to growth_turn_block) on marketing-shaped turns only: about 240 tokens with one post, about 500 at its six-post cap; the verb catalog is static text in the per-business cached segment (about 800 tokens)"
  - "Desk wording is level-aware by the run's kind: suggestion 'a suggested post', week 'next week's posts' while writing, openings 'open-chair posts'; a week and a run without a kind read as before"
  - "New post's flyer: the planner's own make_flyer (free composer, cost 0), words held to check_flyer against the business's facts"
related: [2026-10-07-marketing-desk-api.md, 2026-10-07-marketing-weekly-suggestion.md, 2026-10-07-marketing-weekly-plan.md, 2026-10-08-marketing-openings.md, 2026-10-07-chief-post-image.md]
---
B10 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md: Chief reads and works
each business's own marketing desk from chat (chief_marketing_actions.py),
through the desk API's own functions. Six verbs, no approve verb. The desk's
own words (Chief's read, masthead, Needs a look, Today) now name a
suggestion as "a suggested post" instead of "the week". See "Chief works the
desk (B10)" at the end of docs/MARKETING_DESK.md. Before building more here:
B12 (clips in the week) and B13 (standing permissions) are the next marketing
backend steps; B13 is the only place an approval without the owner's tap may
ever come from.
