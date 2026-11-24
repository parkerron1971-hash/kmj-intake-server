---
title: "Approved good news on Home, News under the Home tab, and alerts on for every church"
date: 2026-11-24
agent: Claude Code (Claude Opus 5.5)
asked: 'post have a tab that seems not accessible ... post and main post from certain leaders should be allowed to see on home tab ... make sure every person has the ability to turn on notification in the app. Then, on the canvas 1hEhJN7ysjiWyTUyctm5b6: build it'
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone: []
decisions:
  - "Home (church_news.home_view): good news a pastor approved shows in What's happening like any post. Birthdays, anniversaries and milestones stay in Celebrating today."
  - "The new look files News, a post and New post under the Home tab (member_lumen_ui.TAB_OF news: home). Under Connect they lit a tab that had no way to the posts."
  - "Alerts: member_push.church_kinds treats announcements, news, messages, prayer and groups as on unless a church saved one False, from member_push.DEFAULT_ON_FROM (planned for Thursday 2026-11-26; Kevin moved it to 2026-11-24, the same day: \"make sure every church can have access now\"). That opens Me → Notifications and the Notifications page for every member. MEMBER_ALERTS_DEFAULTS on/off overrides the date; unit tests run it off (__tests__/conftest.py) and test_member_alerts_default turns it on."
  - "Home gets a Turn on notifications row (member_push.lumen_home_card) after the greeting, only on a phone that can take notifications and hasn't been asked, until Not now (it shares Me's card's Not now)."
  - "Also: To approve on My serving no longer adds an empty line when nothing waits (test_sunday_planning_holds' byte-for-byte check, skipped in CI's clone, caught it locally)."
related: [2026-11-24-good-news-approvers.md]
---
Kevin's three asks from the same afternoon. From 2026-11-24, every church's members can turn on notifications. Churches
that never switched alerts on start ringing for important posts, messages, prayer and group news. Each church can
still turn a kind off, and each member unchecks what they don't want.
