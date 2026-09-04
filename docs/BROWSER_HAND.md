# The browser hand

A sandboxed browser Chief can use as a hand, only where no integration
exists: a state licensing portal, a supplier site with no API, a client's
insurance form. Where an integration exists, the integration is the door.

## How a run happens

1. **Chief proposes.** `use_browser_hand` (class C) validates the ask and
   files a proposal in the Approval Queue on channel `hand`. Nothing runs.
   The body shows the task, the start page, the allowed sites and the
   budget in plain words.
2. **A person approves.** The approvals endpoint and the `approve_draft`
   verb both go through `_do_approve_one`, which sees the channel and
   enqueues a `chief_jobs` job of kind `browser_hand`. One audited door.
3. **The job runs** `browser_hand.run`: screenshot → one JSON action from
   the model → check it against the rules → do it → record the frame.
4. **The result** is the job's `result` (steps, frames, what stopped it),
   a `hand_run_completed` event on the spine, and the usual job recap.

## The rules, each a test in `__tests__/test_browser_hand.py`

- **Domains.** Every navigation and the page's own URL after every action
  must be on the allow-list (the start page's host plus what the
  practitioner named; subdomains included). Off the list, the run stops
  and says which host it reached. `https` only.
- **Credentials and payment.** Before typing, the focused element is
  inspected. Password fields, card / CVC / expiry / account / routing /
  SSN fields, and anything autocompleted as a credential are refused; the
  refusal is a recorded step and the model is told. The hand is never
  given a secret to type.
- **No downloads, no new tabs, no file uploads.**
- **Budgets.** `max_steps` (default 12, ceiling 25) and a wall-clock
  budget (180 s). Both stop the run with a named reason.
- **Recorded.** One JPEG per step, before the action, plus the final
  frame, filed in the private `proposals` bucket under
  `{business_id}/hand/{job_id}/NN.jpg`. `browser_hand.frame_urls` signs
  links for the practitioner.

## What it is not

- Not exposed to the connector (class C is never exposed to agents).
- Not startable by the standing agent (class C is refused when not
  prompted).
- Not a general agent. It works one task on the sites named, and it is
  deliberately poor at everything else.

## Env

- `ANTHROPIC_API_KEY` — the model behind each decision.
- `HAND_MODEL` — optional override; defaults to the chat lane.
- Playwright + Chromium come from `nixpacks.toml`; without them a run
  reports `no_browser` and nothing crashes.
