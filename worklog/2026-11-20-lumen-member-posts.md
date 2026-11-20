---
title: "Member app new look (Look 5.1) — members post: in their own groups, or to the whole church through a pastor"
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, approving Look 5.1: "this is awesome. much better design. lets build this including the new still to build!" His rules for posting: leaders post anytime; members post freely inside their own groups; posts to the whole church go through a pastor who approves first; every member post is checked like comments; each church can turn member posting off.'
status: in review
prs: ["kmj-intake-server (members post, Look 5.1)"]
migrations: []
left_undone:
  - "Home's composer ('Share a praise or a prayer…', contract 2) isn't on main yet: Home's Look 5.1 feed (another helper's PR) draws it pointing at /my/news/share. Once that lands, its link becomes /my/post (a one-line follow-up if this merges first)."
  - "Mission Control: the posting switch has no control in Settings → Member page yet (the owner turns it from their preview's composer). The safety officers' held list shows a held post through the held-comment row, so its words read 'X's comment was held by the check · On \"their own post in <group>\"'; the row carries kind 'post' for a frontend follow-up to say 'post'."
  - "Members' group posts don't ring phones (alerted_at is set when they're saved) and have no Share (contract 1). The week's News email still lists them for the group's people, like any post they haven't seen."
  - "A held post shows to its writer on the group's page only (not on their Home feed)."
  - "Not checked on a real phone: Playwright Chromium and WebKit at 390x844 @2x, reduced motion."
decisions:
  - "Where a member's group post lives: church_posts, as a leader's News for a group already does (group_id; source 'member'), so only the group's people see it (church_news.reaches) on the group's page and in their Home and News, with Love / Amen / Praying and comments as on any post. Kinds: Praise ('praise'), Photo ('photos', 1 to 4 photos checked as News photos for a church audience that includes teens: member_portal_write._photos). The writer picks comments on, prayers only or off. No migration: the table has every column it needs."
  - "Prayer request to a group: the group's own prayer wall (group_prayer.ask: its check, crisis words to a pastor first). To the whole church: Praise and Photo are good news in the existing queue (news_share.share: what happened, one photo, the owner or an admin posts it); a Prayer request goes to the pastors (member_portal_church.save_prayer, private), where /my/prayer's go."
  - "The check (msg_screen), like a comment: 'ok' shows; 'harm' is saved as waiting with attach.held, shows only to its writer on the group's page (marked, with the held wording 'A safety officer looks at this one before it shows.'), and goes to the safety officers beside the held comments (church_news' held list and its words; Let it through posts it, Keep it hidden takes it down; the same route); 'self_harm' the same, plus the pastor told (care_alert) and 988 shown. If the check can't run, nothing posts."
  - "Who may post in a group: someone in it, at this church; the church's switch on (settings.member_portal.member_posts, on unless turned off, as comments are); the church's two safety officers in place (as comments and group chat need). Teens follow messaging's rules: a birthdate on record (we must know who's a teen), a teen needs messaging on for them, a group with a teen needs two approved adult leaders (member_messaging_rules.group_chat), and no photos go into a group with a teen in it (as chat photos)."
  - "Taking one down: its writer or a leader of its group (POST /my/post/remove); the office through News (any post)."
  - "The composer at /my/post (the new look only; off it goes Home): who's posting, Praise · Prayer request · Photo, who sees it (each of their groups, or 'The whole church (a pastor approves)'), what happened (for the whole church), the words, photos, comments, the check's promise, Post. The group page's box opens it with that group picked; Back returns to the group. While posting is off (or before the two officers) the groups aren't offered and the page says so; good news and prayer still go to the pastors."
  - "The switch: the church owner, from their preview's composer (Members posting in their groups · Turn off / Turn on), the picture spots' and pastor note's way in; settings read right before the write; the kept church forgotten. Nobody else can turn it."
  - "Every write: this church's address and the same site, a live session (never the preview), the per-person limit, the new look showing to that session (except taking a post down, which always works), scoped to the member's own groups and church."
  - "The good-news queue reads only the whole church's (group_id is null), so a held group post never shows there (news_share: the member's waiting list, its count of three, the office's Waiting for you)."
  - "A group's Posts tab: the Board's posts and the group's own (member_posts.group_feed) by time; a leader's 'Post an announcement to the Board' under the box; reactions and comments answer in place (News' and Home's scripts) and their no-script forms come back to the group."
related: [2026-11-20-lumen-connect.md, 2026-10-23-church-news-feed.md]
---
`member_posts.py` (new): who may post (`on`, `closed`, `rules`), posting
(`to_group`, `to_church`), taking down (`remove`), the group's posts
(`group_feed`), the held ones for the officers (`held_posts`, `decide_held`),
the switch (`save_switch`), the composer (`render`, `serve`) and its routes
(`POST /my/post`, `/my/post/remove`, `/my/post/switch`). Wired in:
`member_portal` (GET /my/post), `kmj_intake_automation` (the router),
`member_portal_groups` (the box opens the composer; the group's own posts on the
Posts tab, read alongside the gathering and the study; the writer's and the
leaders' Take it down), `church_news` (the held list and its route carry held
posts), `news_share` (the whole church's only), `member_portal_news` (a react
or comment form comes back to a group), `member_lumen_connect.CSS` (the
composer). Tests: `__tests__/test_member_posts.py` (22).

**Checked.** Switch off: 1,509 page x scene dumps identical to main (this work's
harness, 558: Connect, the groups, the composer and its errors, News, under six
scenes, one with members' posts; the dark work's Home harness, 656, and Bible
harness, 295), but one: the Share good news page under the scene that has a
held group post, where main lists it as waiting with the pastors (a held group
post can't exist on main; this is the queue fix above). MEMBER_LUMEN=preview for
a member who isn't the platform owner: the same 557 and the same one.

**Measured** (harness over the test fake; main and this branch interleaved, median
of 60 warm, Server-Timing total): a group's page on 6.9 / 8.9 ms with three posts
of the group's own to draw (off 6.2 / 6.2), Home 15.0 / 15.1, News 10.3 / 10.2.
Reads: a group's Posts tab adds the group's posts read (1), and only when it has
posts of its own, what Home reads to draw them (reactions, comments, people, the
group's name, who's a pastor: 6) and whether comments are open (the two
officers' reads in production); read alongside the gathering and study reads.
Every other page and tab the same as main; the composer 12 cold, 2 warm.

Shots (Chromium and WebKit, 390x844 @2x, light and dark): the session
scratchpad's `l5-connect-shots/pr2/` (the group with members' posts and a held
one, the composer from a group, Photo picked, posting off) and `side-by-side/`.
