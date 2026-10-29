---
title: Share good news — a member sends it, the owner or an admin posts it (part 4 of "Church News & Celebrations")
date: 2026-10-23
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23: "members can share good news since they have to be approved by me or admins"; "Continue building"'
status: in progress
prs: [kmj-intake-server (this PR), solutionist-studio (Waiting for you in the office)]
migrations: []
left_undone: ["leaders and picked posters posting from their phone (board 7, Write), with photos and the event sign-up", "part 5: phone alerts for news (Important / Everything / Off, quiet hours), the weekly email", "\"Just my groups\" good news shows on News for those groups' people, not on the group's Board (the canvas said \"sees it on its Board\"; one post, one thread)", "the office's own photo upload on a new post"]
decisions: ["approval is the owner's or an admin's (Kevin's words), not any seat that edits", "Not now saves it for later (status declined, 30 days in the office's list) and the member is never told no", "the words are checked like a comment, but a person reads every share first, so harm and unchecked shares wait marked rather than being refused; crisis words also tell the pastor and show 988", "a photo the check turns down, or can't check, means nothing is saved", "at most 3 waiting at once for one member; a member can take back their own before it's posted", "posted, it goes up under the member's name (their face, Celebrate and Love, a congratulations thread); its time on News is when it was posted", "the member's phone gets a note when the church has News notes on; the Sent page says so only when it's true"]
related: [2026-10-23-church-news-feed.md, 2026-10-23-church-celebrations.md]
---
`news_share.py` (share, take back, who may see a photo, the office's Waiting list, `POST /church/news/shared/{id}` for the owner or an admin) and `member_portal_share.py` (board 5: "Tell us what God did.", six kinds, the photo, the whole church or just my groups, Sent, "With your pastors" with Take it back). News gets board 2's "Have good news?" card; a shared post is its own card under the member's name, and its page is the celebration page with the photo. `church_news.reaches` decides who a post is for (whole church, a ministry, or the groups a member chose). Photos are private (`image-originals/{business}/news-photos/`) behind `/my/news/<id>/photo/<n>`.

Built to the canvas (board 5) and looked at side by side at 390 wide: the form, a chosen photo, "Just my groups", Sent, the post in the feed and on its page. Checks: 21 tests in `test_news_share.py` (3 sabotages caught: "just my groups" reaching everyone, a turned-down photo kept, a member-seat approving); `church_news_db.mjs` 45 checks on PGlite.
