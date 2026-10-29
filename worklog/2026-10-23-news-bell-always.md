---
title: The News bell is on Home even before the church's first post
date: 2026-10-23
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23, signed in to the member app as Pastor KMJ: "I don''t see where I can post"'
status: done
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: []
decisions: ["the bell shows whenever the church's news could be read, with no number until there's something new; a failed read still shows none"]
related: [2026-10-23-church-news-post-from-phone.md]
---
Home showed the bell only when the church already had posts. Love City has none yet, so Home had no way to News, where Post (and Have good news) live: a dead end for the very first post. Pastor KMJ can post (an active Pastor role, picked to post to the whole church, leads a group); a live preview as him showed Post on News and the Write form, so only the way there was missing. `member_portal_news.home_bell` now decides the bell; `test_the_bell_leads_to_news_even_before_the_first_post` (fails on the old rule).
