---
title: "Main green again: two member-app tests stop reading the server's clock"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "Main is red and blocks every PR (#2057's run 44973563493): test_a_pastors_post_when_no_devotional_runs and test_the_pastors_reply_follows_messaging_rules (the Sunday moment came first, not the pastor's post), and test_member_mini's test_every_other_page_is_what_it_was[/my/sermons] (a page comparison). Pin the clock in the tests, without changing the product's order unless it's actually wrong, on its own small PR with a worklog."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone: []
decisions:
  - "The pastor's post: the Look 5.1 Home tests' scene is 6:45 PM on the church's own date (since #2052: New York's date, not the server's UTC one). _post dated the post '2 hours before the server's now', which after 8:45 PM in New York is after the scene's evening, so pastor_post rightly ignored it as not yet posted and the service's moment led. The product's order is right; the post is now dated two hours before the scene's evening."
  - "The mini player's page comparison: Watch's state on the page carries the server's clock in whole seconds ({\"now\": ...}, member_lumen_watch), which ticked between the switched-on and switched-off loads in CI (1795312716 vs 1795312717). The comparison now reads that one stamp as 0 on both sides; every other byte must still match."
  - "No product code changed."
related: [2026-11-21-lumen-home-feed-cards.md]
---
Main's three red tests were clocks: two read the server's time where the scene's was meant, one compared a
seconds stamp across two loads. Fixed in the tests only.

Checked: the two Look 5.1 tests fail on main at 02:11 UTC (9:11 PM in New York) and pass with this change;
test_member_mini and test_member_lumen_home5 pass; the member suites with -n 2: 1689 passed.
