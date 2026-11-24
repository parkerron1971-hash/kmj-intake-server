---
title: "Good news approvals: the pastors and picked leaders approve from Serve, with a phone note"
date: 2026-11-24
agent: Claude Code (Claude Opus 5.5)
asked: 'send a post request to the pastor''s or assigned leader to apporve post in the app serve tab area. Then, on the canvas Ktoy4b4qXoCDPCDoRmCGxj: build it' 
status: in progress
prs: ["kmj-intake-server (this PR)", "solutionist-studio (office Home card + Who approves good news, next)"]
migrations: []
left_undone:
  - "The office side (solutionist-studio): the Home card ('2 good news posts are waiting', GET /church/news/shared/count) and News settings → Who approves good news (POST /church/news/approvers, settings.approver_alerts), drawn on the canvas's boards 5 and 6. A separate FE PR."
  - "A Home cue for admins who aren't the owner: their phone note and the Serve page work, but Home's strip and the Serve door's count are the owner's and the picked leaders' only (an admin's member record needs a business_users read on every Home load)."
decisions:
  - "Who approves: the church's owner (settings.church_owner_contact_id), every active owner or admin office login tied to a member record (business_users.contact_id), and up to 12 leaders the office picks (settings.news.approvers). Kevin's default from the canvas: a picked leader approves alone; whoever answers first decides (the update lands only on a row still waiting)."
  - "Words the check marked as about self-harm (attach.flag 'care') stay with the pastors: picked leaders get no note, don't see it on Serve, and can't decide it."
  - "The note: member_push, the church's Serving kind where it has those on, else News; waits out quiet hours; settings.news.approver_alerts (on unless the office turns it off). It opens /my/serving#approve."
  - "Serve: To approve on top of My serving (member_serving_approve), with Post it / Edit first / Not now; Edit first is /my/serving/approve/<id> (the words in a box, the photo kept or left off). Someone who approves but has no Sunday team, or a church that doesn't schedule Sundays, gets My serving with only that on it. What someone else answered in the last 6 hours stays, with who, and no buttons. Not now from the app is final there; the office can still post a saved one."
  - "One step decides for the office and the app: news_approvers.settle (the office's POST /church/news/shared/{id} goes through it now), so the writer's note and the Everything alerts are the same from both. The app writes decided_by 'contact:<id>'; the office, its user id."
  - "Home: the owner's desk strip's good news row now says 'Approve it in Serve' and opens Serve (held comments and posts still go to the office). A picked leader gets that row too (news_approvers.leader_desk). The Serve door says 'N to approve'."
  - "An approver sees a waiting post's photo (news_share.photo_link)."
related: [2026-11-21-lumen-home-desk.md, 2026-11-20-lumen-share.md]
---
Good news a member shares for the whole church used to wait only in the office's News room, with no note to anyone.
Now the pastors and the leaders the office picks hear about it on their phones and approve it from the member app's
Serve page. Tests: __tests__/test_news_approvers.py (22). The member, serving, news and ownership suites pass (903).
