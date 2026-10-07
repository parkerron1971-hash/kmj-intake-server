---
title: Chief posts an approved clip, with its cover, to the connected accounts
date: 2026-10-06
agent: Claude Code (Claude Opus 5.5)
asked: "keep the link, and let Chief post clips"
status: waiting on Kevin
prs: [kmj-intake-server chief-post-clip]
migrations: []
left_undone: ["Not proven live: Chief has not posted a real clip; the first one should go to a test account", "Chief picks covers only as auto (newest ready cover of each shape) or none, never a particular cover by id", "The app shows the result as Chief's ordinary card; a Video Clips style card for the post is not built (the result carries publication and covers for one)"]
decisions: ["One post path: clip_posting.post_clip_for, called by the Post tap endpoint and by Chief; the endpoint's behaviour and tests are unchanged", "Class C with a written reason, client-facing in policy_engine, never autonomy-eligible, never an agent tool (tag action only)", "Unattended runs are always held, mirroring publish_post's gate on the _unattended mark: a clip's approval in Video Clips covers the clip and its own caption, never the accounts, the time or Chief's words, so no recorded approval can cover an unattended clip post", "schedule_action refuses to wrap post_clip; a later time goes with the post (when) to the posting service and can be cancelled in Video Clips", "The acting user is the chat turn's signed-in user (_TURN_USER_ID); the owner check is the service-role read of businesses.owner_id, like the endpoint", "The request id is a uuid5 of the turn id, clip, accounts, caption, time and cover choice; the same-post-today guard is the second line", "Clips resolve among every ready clip of the business (AI and hand-trimmed alike), exact name then part of it, newest first; more than one match is asked about with up to five names", "The result says Sent or Scheduled, never Posted: the networks report back later in Video Clips"]
related: [2026-10-06-post-clip-with-cover.md, 2026-10-06-covers-both-shapes.md, 2026-10-05-clip-covers.md]
---
New Chief verb `post_clip` (chief_clip_actions.py): "post the Separate Them
clip to Instagram and TikTok", "schedule that clip for Thursday at 9". It
resolves the clip by id or name, picks the connected accounts (all, or the
networks named), takes Chief's caption or the clip's own, and calls
`clip_posting.post_clip_for`, which the Post tap endpoint now calls too.
Every refusal is plain words with a result and a label, and says nothing was
posted: not the owner, posting off, no account connected (connect one in
Build, Social Media), not approved or changed since approval (approve it in
Video Clips first), a time in the past.

Before building more here: Chief cannot approve a clip, by design. If Kevin
wants Chief to post on a schedule it set itself, that needs a recorded owner
approval of the post (accounts, words, time), the way content_approval does
for publish_post. Tests: `__tests__/test_chief_post_clip.py` (no live calls).
