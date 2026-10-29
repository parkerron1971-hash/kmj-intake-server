---
title: Posting News from a phone, and Sign me up from a post (part 4b of "Church News & Celebrations")
date: 2026-10-23
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23: "leaders should be able to post to their own ministry anyways but if I pick them for this, they can post to the entire church. like an admin."; "Continue building"'
status: in progress
prs: [kmj-intake-server (this PR), solutionist-studio (New post: photos, a link, Sign me up)]
migrations: []
left_undone: ["\"Important: ring their phones\" waits for part 5 (phone alerts for news, at most 3 a day, quiet hours)", "a photo uploaded in the office but never posted stays in the church's folder (no sweep yet)", "a post's audience and kind can't be changed in an edit; take it down and post again"]
decisions: ["who posts where is church_news.can_post: pastors and the people the office picked, the whole church; a group's leader, their own groups; checked again when the form comes in, never trusted from it", "a leader's words aren't run through the comment check (the office's aren't either); every photo is, and one turned down or unchecked posts nothing", "Chief's sign-up offer is the page's own reading of the words (sign up, register, RSVP, save your spot) plus an event that's chosen or named; nothing is sent to a model", "Sign me up goes through member_rsvp, the same path as Events, so capacity, privacy and past events hold", "the post's own page shows every photo; the feed shows two and how many more"]
related: [2026-10-23-church-news-feed.md, 2026-10-23-church-share-good-news.md]
---
`member_portal_write.py` (board 7: Posting as yourself, Who it's for with how many people, What kind, Headline, Message, Add photos / Event / Sermon / Link, Chief's "Add the sign-up", Pin, Comments, Now or Sunday 7 AM, "It's out.", Edit) and `POST /my/news/signup`. News shows Post to people who can post. A post shows a link card, every photo on its own page, and Sign me up under its event ("You're signed up" once they are). The office gets `POST /church/news/photo` and `_attach` takes a link, the sign-up and its own folder's photos only.

Built to the canvas (board 7) and looked at side by side at 390 wide: the form, Chief's offer (it found Baptism Sunday from the headline), after Add the sign-up ("Event · Baptism Sunday"), It's out, Edit, and News with Post and Sign me up. Checks: 15 tests in `test_news_write.py` (3 sabotages caught: a leader posting to the whole church, Sign me up on a post that doesn't offer it, another church's photo carried by a post).
