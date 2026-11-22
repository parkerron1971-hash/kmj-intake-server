---
title: "Member app new look (Look 5.1): the owner's desk strip on Home"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin's Home plan (2026-11-21, 'yes to everything'), the last piece: the owner's 'Post the church's first news' becomes part of a small desk strip, only for the owner/officers: good news or member posts waiting, a held comment or post. Use counts Home already has, or that member_cache keeps. Link to the office's News room or the existing member-side approve page, whichever exists."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "Safety officers who aren't the owner don't get the strip. The only place to decide a held comment or post, or to post waiting good news, is the office's News room, which needs an office login; a church member named a safety officer may not have one, so the strip would send them to a door they can't open. There is no member-side approve page."
  - "Leaders' own moments the check held (member_moments.held) aren't counted: they are a third read, and the office lists them in the same place the Review button opens."
decisions:
  - "Who: the church's owner, their preview or their own member record (settings.church_owner_contact_id, as member_moments.may_take_down): member_portal_lumen.is_owner, no read. Nobody else reads anything for it."
  - "What: member_portal_lumen.desk_counts, the counts the office's News room lists as Waiting for you: good news members shared for the whole church still waiting (church_posts, source member, status waiting, no group, the last 30 days as news_share.office_list shows them), members' group posts the check held (the same rows with a group and attach.held, as member_posts.held_posts), and comments the check held (church_post_comments, status held). Two reads, kept a minute per church in a member_cache.Kept; a failed read leaves the counts out and isn't kept (never 'nothing waits')."
  - "The strip (member_lumen_home.desk), after This week and the asks, before the composer: '1 good news post is waiting' / 'It came in today. Approve it and Love City's feed begins. Only you see this.' (at a church with posts: 'Approve it to post it.'), '2 comments and 1 post are held' / 'The check held them for a safety officer to read.', each with Review to the office's News room (APP_BASE_URL/?nav=operate:news, the office's own deep link). At a church with no news yet and nothing waiting, the owner's 'Post the church's first news' (/my/news/write) is the strip's row instead of the feed's; anyone else who may post still finds it in the feed. Nothing waiting: no strip."
  - "CSS only in member_lumen_home.CSS: the church's soft tint, a hairline between rows, the Review pill in the page's own colour (inverted in the dark look); every rule under .lm with the page's tokens."
related: [2026-11-21-lumen-home-feed-cards.md, 2026-11-21-lumen-home-sunday-pass.md]
---
The church's owner sees what waits for them in the office's News room at the top of Home, and the church's
first news when it has none yet. Nobody else sees or reads anything for it.

Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps each (Home harness 656,
Bible harness 295), main (22f48f48) and this branch dumped back to back: same 951, differ 0 in both modes. Reads with the
switch on (warm), per page and table in four looks: Home harness 1956 / 1956 over 328 page-looks, no page differs
(the harness's member isn't the owner, and a test pins that nobody else reads for the strip); Bible harness, only
the group feed's known run-to-run noise. The owner's first Home: two reads more (the waiting posts, the held
comments), kept a minute per church. Member suites with -n 2: 1697 passed (8 new in
__tests__/test_member_lumen_home_desk.py). Also: the Look 5.1 tests' pastor's post is dated from the scene's evening, not the
server's clock (after 8:45 PM in New York, since #2052 moved the scene onto the church's date, '2 hours ago' fell after the
scene's 6:45 PM). Shots before and after (Chromium and WebKit, light and dark, 390x844
@2x, the owner at a church with no posts and one good news post waiting, plus the same church for a member) in
the session scratchpad's home-build-shots/pr4-desk/.
