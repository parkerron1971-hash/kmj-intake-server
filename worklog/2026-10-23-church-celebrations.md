---
title: Celebrations in the church's news — birthdays, anniversaries, milestones (part 3 of "Church News & Celebrations")
date: 2026-10-23
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23: "Build a celebration of members: Birthdays, Anniversary, Achievements. A notification setup and a thread like Facebook where people can say congratulations"; ask each member first; "Continue building"'
status: in progress
prs: [kmj-intake-server (this PR), solutionist-studio (celebrations office)]
migrations: [supabase/APPLY-2026-10-23-celebrations.sql]
left_undone: ["part 4: Share good news (a member sends it, an admin approves; baptisms come this way), leaders and picked posters posting from their phone, photos", "part 5: phone alerts (a 9 AM note about people in my own groups, Important news, quiet hours), the weekly email", "children aren't celebrated: a child has no member record to say yes", "\"Rather say it quietly? Send a message\" on a celebration isn't there yet (messaging is off at Love City)"]
decisions: ["ask each member first (Kevin); the church can choose 'everyone unless they say no' (settings.news.celebrate)", "the question on Home waits until the office says Ask them (settings.news.ask_members)", "a member with no birthdate gives month and day only (member_celebrations.birthday_md), never a guessed year: the year decides who counts as a teen", "an anniversary needs both spouses' yes; the spouse is chosen from the member's own household", "someone marked passed away stops their birthday and every anniversary of theirs, so a spouse is never shown one alone; today's posts about them come down", "milestones are finished classes for members who said yes; Chief writes them and a pastor or admin posts or skips each", "each day's celebrations are posts made after 7 AM on the church's clock (sweep every 30 min), one per person, kind and day; wishes are their comments, checked like every comment"]
related: [2026-10-23-church-news-feed.md]
---
`celebrations.py` (who is celebrated, the morning sweep, today's posts, the office API: GET /church/news/celebrations, POST settings, milestone, week, stop) and `member_portal_celebrations.py` (Home's "Celebrating today" and the once-only question, a celebration's page with quick wishes, Me → Celebrations, a couple's yes). The feed groups today's birthdays and anniversaries into "Today we celebrate"; milestones are their own card; another day's never show.

Built to the canvas (boards 1, 2, 4, 6) and looked at side by side at 390 wide. Checks: 16 tests in `test_celebrations.py` (2 sabotages caught: a stopped spouse's anniversary still shown, one yes enough for an anniversary); `celebrations_db.mjs` 17 checks on PGlite.
