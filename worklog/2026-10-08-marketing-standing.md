---
title: "Solutionist: standing permissions for marketing posts (marketing suite B13)"
date: 2026-10-08
agent: Claude Code (Claude Opus 5.5)
asked: "This will work. let's build this."
status: waiting on Kevin
prs: [kmj-intake-server#1341]
migrations: []
left_undone:
  - "Kevin: nothing is approved on a standing OK until MARKETING_DESK covers a Solutionist (practice) business (the design tick is where Chief approves), and nothing sends unless MARKETING_DESK_PUBLISHING=on. First live check: a comped practice test business, grant marketing_post from the desk's door (POST /agents/chief/standing), let a week draft and settle, confirm the week's Today item says 'Chief approved N posts', then take one back"
  - "Not seen live: the marketing_post_events reads (filter snapshot->>source=eq.plan and the JSON-path select aliases). A 400 there reads as a failed read: Chief neither asks nor retires, never a guess"
  - "F6 (the Solutionist view) must show GET /engine's `standing` block (grant switches per kind, the open question, held reasons), the take-back button (POST /posts/{id}/take-back) and approved_via on each post; nothing in the frontend reads any of it yet"
  - "An owner's revoke from the door or chat puts the waiting posts back within 2 minutes (the design tick's sweep), not in the same request; the sender's own check covers the gap"
  - "Chief asks once per kind ever (settings.autonomy.standing_offered); after a retire it does not ask again, the owner turns it back on from the desk"
decisions:
  - "Kinds: marketing_post = source 'plan' (Chief's weekly flyer posts), post_clip = source 'clip' (B12). The suggestion, opening, owner and chief sources and Post now are never covered"
  - "Extended standing_permissions (MARKETING_KINDS beside ELIGIBLE), not forked: same storage, door, grant/revoke/decline and audit. The marketing kinds never ride the proposal paths (filing_extras, release_one, offer_after_approval, sweep_revocations are ELIGIBLE-only), so Chief's own post_clip proposal is never covered by the week's clip grant"
  - "Gate: feature_gates.plan_includes(marketing_autopilot) (+ ai_clips for post_clip) AND policy_engine.client_facing_autonomy == 'enabled'; covers() adds grant by the current owner, STANDING_PERMISSIONS not off, automations not paused. Checked at grant (door, owner-only), approval (approve_run), send (dispatch, approved_via 'standing'), and every 2 min (lapse_sweep in the design tick)"
  - "Chat never grants a marketing kind (owner taps on the desk); chat may revoke one only on the owner's own turn"
  - "Chief approves in tell_week, once the week has settled (none designing), one marketing_approve call per post with p_via 'standing' and p_actor = the owner. Only posts as Chief meant them: flyer ready with no note (an unsure flyer or a words-only fallback waits), clip still kept and approved at its fingerprint, accounts connected and able, due >= 1 h away"
  - "Lapse at send time: the post goes back to a DRAFT (approval dropped, revision + 1, content unchanged, note starting \"Chief's standing OK\"), the rest of its kind too, owner told once (Today item + push). Unreadable business: held (back to approved, retried), never sent"
  - "Ask/retire are read off marketing_post_events (B3's trigger), never a counter: approvals_from works out each approval's fate (sent, posted_now, edited, skipped, not_sent, withdrawn, failed, pulled, waiting). Ask: last 3 owner approvals of the kind each of Chief's draft unchanged (hash once the flyer settled) and not edited/skipped after. Retire: last 3 settled standing approvals since the grant (by when each settled) all edited/taken back/skipped/not sent; a sent or posted-now one ends the run"
  - "Take back (new route) counts as an override for retire; the brief listed edit, skip and not-sent"
  - "Weekly tell: the planner's one Today item + push per week now says 'Chief approved N posts for next week under your standing OK' and how many more wait"
  - "No migration: kind is not a column (grants live in businesses.settings.autonomy jsonb); approved_via already allows 'standing'; marketing_approve already takes p_via"
related: [2026-10-08-marketing-clips.md, 2026-10-07-marketing-weekly-plan.md, 2026-10-07-marketing-desk-send.md, 2026-10-07-marketing-plan-gates.md]
---
B13 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md (D6). At the autopilot
level (Practice) the owner can let Chief approve its weekly flyer posts and
the clip posts it folds into the week. business_marketing_standing.py is the
desk's half (covers, approve_run, send_check, lapse_sweep, the history, the
ask and the retire, the desk block); standing_permissions.py gained the two
marketing kinds; the planner's tell_week approves and tells, the design tick
sweeps, the sender re-checks, and business_marketing.py gained the take-back
route, the `standing` block on GET /engine and the hooks on approve, edit,
skip and not-sent. Tests: __tests__/test_business_marketing_standing.py (no
live calls). Docs: docs/MARKETING_DESK.md, "Standing permissions (B13)".
