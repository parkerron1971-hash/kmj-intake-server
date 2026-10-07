---
title: Chief posts a picture (a design, a photo or words) to the connected accounts
date: 2026-10-07
agent: Claude Code (Claude Opus 5.5)
asked: "This will work. let's build this."
status: waiting on Kevin
prs: [kmj-intake-server#1306]
migrations: []
left_undone: ["Not proven live: Chief has not posted a real picture; the first one should go to a test account", "No Post tap for a design in the app yet: Image Studio's own publish still goes the Meta path (B16 retires it); Chief's result shows as its ordinary card", "image latest looks only at designs made in Image Studio (generated or composed) in the last day; an uploaded photo is posted by its id", "A picture never goes to TikTok or YouTube (the shared door's rule: they take only videos); a TikTok photo post is not built", "Marketing suite B3 onward (storage, the desk, sending, the weekly plans) is the rest of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md; B2, the plan gates, is #1304"]
decisions: ["One post function, image_posting.post_image_for; Chief's handler only resolves the picture and the accounts and words the answer, so the desk (B5) can call the same function", "Class C with a written reason, client-facing in policy_engine, never autonomy-eligible, never an agent tool (tag action only)", "Unattended runs are always held, before anything is read: nothing records an owner's approval of a picture post's words, accounts and time; schedule_action refuses to wrap post_image and the time goes with the post", "image_studio.build_actor is bound to the business and the owner only around delivery_jpeg and reset in a finally, restoring any outer actor; storage then refuses any path outside the business's folder", "image latest = the newest ready design of the last 24 hours (not a clip cover, an upload or a website capture); more than one made within ten minutes of the newest is asked about with titles and ids", "Words only leave Instagram out (it needs a picture) and a picture leaves TikTok and YouTube out; the answer says so; nowhere left means nothing posted", "The request id is a uuid5 of the turn, picture, accounts, caption and time; the post id a uuid5 of the request id; the day's duplicate guard is the second line; a failed read of either refuses instead of reading as no earlier post", "The answer says Sent or Scheduled, never Posted, and points to Build, Social Media"]
related: [2026-10-06-chief-post-clip.md, 2026-10-06-post-clip-with-cover.md]
---
New Chief verb `post_image` (chief_social_actions.py), B1 of the marketing
suite plan: "post the flyer to Instagram and Facebook", "schedule that design
for Thursday at 9", "post the latest design". It resolves the picture (by id,
`"image":"latest"`, or none for a words-only post), picks the connected
accounts (all, or the networks named) and calls
`image_posting.post_image_for`: owner check, posting pilot gate, a ready
artwork of this business only, the JPEG made under the build actor, the
shared `send_post` door. Every refusal is plain words with a result and a
label that says nothing was posted. No migration, no endpoint, no scheduler
job, no paid AI call. Tests: `__tests__/test_image_posting.py`,
`__tests__/test_chief_post_image.py` (no live calls).
