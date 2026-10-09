---
title: Desk posts take up to ten pictures, and the composer posts approved clips
date: 2026-10-09
agent: Claude Code (Claude Opus 5.5)
asked: "work on this in order (Kevin, 2026-10-09; first three: video posts through the desk, Build → Social Media's older composer, Post in Create on Chief's flyer card)"
status: done
prs: [kmj-intake-server#1360, solutionist-studio#1182, solutionist-studio#1184]
migrations: []
left_undone: ["Build → Social Media's old composer still shows; it folds into Create in the next frontend PR, once the carousel (solutionist-studio#1184) is live", "a phone video posts through Create → Clips (upload, a clip of up to 90 seconds, its rights checks and approval), not straight from Post: a desk post binds an approved clip, never a raw upload"]
decisions: ["/ideas and /slot/edit take artwork_ids (1-10, the owner's order, the same id once); artwork_id stays the one-picture form; both, or pictures with a clip, is a 422", "a network that shows fewer pictures gets the first ones at send time (business_marketing_dispatch.PICTURE_CAPS: X 4, LinkedIn 9, Pinterest 1); the post and its publication record keep every approved picture", "the composer offers clips that are ready, stored, not skipped and approved at their current fingerprint, and sends that fingerprint, so a clip changed since is refused (solutionist-studio#1182, no backend change: /ideas already took clip_id)"]
related: [2026-10-08-marketing-open-to-all.md]
---
Item A of Kevin's list (video posts through the desk) was frontend only:
`/ideas` already took `clip_id` + `clip_fingerprint` (B12), so
solutionist-studio#1182 (merged 2026-10-09 10:57 UTC) added the business's
approved clips to Create → Post and the desk's New post.

Item B (Build → Social Media's older composer) needs Create to do what that
composer did before it can go: a carousel of up to ten photos. This PR is
the server half (artwork_ids, per-network caps at send time);
solutionist-studio#1184 is the picker. The old composer's straight video
upload is covered by Create → Clips (a clip of the upload, approved), then
Create → Post. `social_publications` had no rows at all on 2026-10-09, so
nobody had posted through the old composer yet.
