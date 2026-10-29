---
title: Home shows a pastor where the church's first news will go
date: 2026-10-23
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23, in the member app as Pastor KMJ after the bell fix: "i don''t see the upgrade. the home area still look the same"'
status: done
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: []
decisions: ["only someone who posts sees it (a pastor, someone the church picked, a group's leader); a member's Home still shows nothing until there's news", "drawn as one of From the church's own rows (the canvas's gold megaphone row), with no All news link while there's no news"]
related: [2026-10-23-news-bell-always.md, 2026-10-23-church-news-post-from-phone.md]
---
Home's two new sections, Celebrating today and From the church (canvas board 1), show only when there's something in them. Love City has no posts and nobody has said yes to being celebrated yet, so Home looked as it did before apart from the bell (live check as Pastor KMJ: no Celebrating today, no From the church). Now, when no news reaches someone who posts, From the church shows one row, "Post the church's first news", that opens Post. `member_portal_news.home_first`; `member_portal` reads `church_news.can_post` only when the news read came back empty. `test_home_shows_a_poster_where_the_first_news_goes` (fails with the row removed). Rendered at phone width with the canvas data and with no news (scratchpad render_news.py `empty`), compared with board 1.
