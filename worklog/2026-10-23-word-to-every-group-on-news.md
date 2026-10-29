---
title: A word to every group can go on News too
date: 2026-10-23
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23: "to fold into new feed should be an option for group page situation. so if I want to post to new feed i can choose so or not because not everyone possibly is in a group."'
status: done
prs: [kmj-intake-server (this PR), solutionist-studio (the Groups page choice)]
migrations: []
left_undone: []
decisions: ["Kevin's call: keep the Groups page's word to every group, and let it go on News too when he chooses (off unless he does)", "only a word to every group; a word to the group leaders only never goes on News", "with nobody in a group yet, a word that goes on News still posts there (the groups part is skipped)", "on News it's an office post for the whole church, and it rings like any office post (news_alerts)"]
related: [2026-10-23-church-news-feed.md, 2026-10-23-church-news-alerts.md]
---
`POST /church/groups/word` takes `news`: the same words also become a whole-church News post (`church_news.insert`, source office), and the answer carries `news_post_id`. Three tests in `test_church_groups_office.py` (a sabotage letting a leaders-only word reach News was caught).
