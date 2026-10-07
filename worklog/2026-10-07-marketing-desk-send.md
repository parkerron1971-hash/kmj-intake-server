---
title: Sending through Post for Me, plus the delivery watch (marketing suite B5)
date: 2026-10-07
agent: Claude Code (Claude Opus 5.5)
asked: "This will work. let's build this."
status: waiting on Kevin
prs: [kmj-intake-server#PENDING]
migrations: []
left_undone: ["Kevin: set MARKETING_DESK_PUBLISHING=on on the PROCESS_ROLE=worker service (default off: nothing sends, post now refuses); POST_FOR_ME_API_KEY and POST_FOR_ME_PILOT_BUSINESSES must be set there too", "First real send to a test account: proven only against in-memory fakes (PostgREST, Post for Me, storage, push)", "B6 tracked links: publish_text is still the caption with no /go/ link", "Frontend F2: no screen shows submitted/published/partly_published or external_urls yet; the Today item navigates to grow/marketing, a leaf F2 adds", "send_post treats a Post for Me timeout as a refusal (recorded failed); a timeout where the post did go out would read as failed, not uncertain (pre-existing in the shared door)"]
decisions: ["Only send_post hands anything to Post for Me; a clip goes through post_clip_for (covers, its own approval check)", "The publication id is uuid5(post id, 'rev:<revision>'), and the clip request id is the same value, so a retry of one approved version is answered from the door's record and never posted twice", "Errors mirror the platform dispatch: nothing left the server -> approved (retried until the window closes); a check said no or the service refused -> failed in plain words; anything else once the hand-off began -> uncertain", "A pause after the claim puts the post back to approved quietly (the desk says approved posts wait for Resume), instead of failing it as the platform does", "social._targets reads `or []`, so its refusal is confirmed by a second fail-closed read before a post fails as disconnected; the door's two read-ambiguous refusals inside the hand-off retry instead of failing", "The delivery watch also settles uncertain posts (last two days) whose publication exists, so an unrecorded send or a late answer resolves itself", "One Today item + one push per problem, keyed post:revision:status in chief_notifications.action_payload.dedup_key; a failed dedup read says nothing that tick; the owner's own not-sent is not announced (business_marketing.NOT_SENT_NOTE)", "The post's error is plain words naming the accounts; the network's raw error text stays on social_publications (it would otherwise flow into Chief's digest)", "social._refresh's write now runs in a thread (it blocked the event loop for list_publications too)"]
related: [2026-10-07-marketing-desk-api.md, 2026-10-07-marketing-suite-storage.md, 2026-10-07-chief-post-image.md, 2026-10-02-marketing-desk.md]
---
B5 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md (D3). New
business_marketing_dispatch.py: due_tick (every minute) claims due approved
posts with marketing_claim_due and sends each through
social_publish_router.send_post (pictures/words) or clip_posting.post_clip_for
(clips), re-checking content hash, pause, pilot, accounts and clip approval
at send time with image_studio.build_actor bound to the business's owner for
that one post. delivery_tick (every 5 minutes) settles posts through
social._refresh into published / partly_published / failed (uncertain after
2 hours in flight) and tells the owner once per problem by push and a Today
item. Both jobs are registered in kmj_intake_automation.py behind the leader
gate and only run where scheduled jobs run, and both are no-ops until
MARKETING_DESK_PUBLISHING=on. No migration, endpoint, Chief action or
frontend. Tests: __tests__/test_business_marketing_dispatch.py. How it works
is in docs/MARKETING_DESK.md ("Sending and the delivery watch").
