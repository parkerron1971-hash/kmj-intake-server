---
title: "Any lane can point at another provider, with Claude as the fallback"
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "build the best path forward. and approved to do what is needed to get this working well (Kevin, 2026-10-11, Layer Two workstream D)"
status: waiting on review
prs: [kmj-intake-server#1388]
migrations: []
left_undone: ["only design_intent calls post_lane so far; the brain pass and the other background/fast callers move after their own PRs land", "no lane is pointed anywhere else: that needs the replay bench (workstream G) and Kevin's yes", "streaming lanes (opener, headline) are not routable yet"]
decisions: ["the registry sits on chief_models, so CHIEF_MODEL_<LANE> keeps working and Anthropic stays the default", "a half-set lane stays on Claude and says so, never fails closed", "tools, extended thinking, cache markers and non-text blocks keep a call on Claude whatever the config says", "a provider failure falls back to the lane's Claude model in the same call", "the provider's answer is returned in the Anthropic Messages shape, so callers parse it unchanged and the seam meters it"]
related: [2026-10-11-business-brain.md]
---
Layer Two workstream D. lane_registry.route_for(lane) maps a lane to a provider,
model, address and key, from env, on top of chief_models' Claude defaults.
llm_call.post_lane(lane, payload) sends Anthropic lanes exactly like post(); for
an OpenAI-compatible lane it calls /chat/completions, wraps the answer as an
Anthropic message, meters it, and falls back to Claude on any failure.
design_intent is the first caller. Moving a lane off a rented model is now a
config change you can undo.
