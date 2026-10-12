# Layer Two: the business brain

2026-10-11. Kevin's philosophy: rent the engine, own the brain. Claude and the
other frontier models are layer one. Layer two is what we own, and every
better layer-one model arrives as a free upgrade to it.

## The loop

One loop around one object, the **business brain**:

1. **Notice.** Every Chief turn has a turn id (the app's `request_id`). It
   joins the turn's model calls (`api_usage`), its archive row
   (`chief_conversations`), its drafts (`agent_queue`, which keeps Chief's
   original when the owner edits it) and their outcomes (`chief_moves`).
2. **Reflect.** The nightly brain pass (`chief_brain_pass.py`, 07:40 UTC)
   reads each active business's day on Haiku 5.5. It is capped at 3¢ per
   run, carries no tools and is read-and-propose only.
3. **Propose.** At most two rules a night go to the owner's Approval Queue as
   `propose_adopt_business_rule`. They are never repeated once active, pending
   or declined.
4. **Approve.** The owner taps Yes or Not now. A rule can also come from the
   owner's own words in chat (`adopt_business_rule`) or from the What Chief
   knows page (`/brain/{business_id}`).
5. **Remember.** Rules are owner facts with a polarity in the private
   operating profile (`business_learning.py`). They are capped at 25 and
   render first. The nightly digest sits in the per-business cached prompt
   segment.
6. **Prove.** Each distinct brain (profile revision + rules + digest + model
   lanes) is one append-only, fingerprinted row in `business_brain_versions`.
   Chief's ledger rows carry the AI context in `payload._ai`. The ledger hash
   (`ledger_canonical_v2`) covers payload, and the six-hourly Merkle anchoring
   publishes it to Bitcoin and Hedera.

## Principles kept

- Authority stays in the rails: nothing here gives a model the ability to act.
  The nightly pass never reaches `_execute_actions`. A rule changes what Chief
  says and drafts, not what it may do.
- Model-agnostic: the brain is text and structure, so any model can read it.
- No cross-tenant leakage: every read in the pass and on the page is
  `business_id=eq.<one business>`. Rules never feed the cross-business
  pattern counts.
- Metered: the pass goes through `llm_call` with `task=brain_pass`, and the
  spend guard applies.
- Portable: `business_brain_versions` is exported and deleted with the
  business.

## Switches

- `CHIEF_BRAIN_PASS=off` stops the nightly pass.
- `POLICY_UNATTENDED_C=allow` restores label-only handling of unattended
  irreversible actions (default: refuse unless the owner set it up).

## Routing a lane to another provider

`lane_registry.route_for` decides each lane's provider; `llm_call.post_lane`
calls it, falls back to the lane's Claude model on any failure, and keeps any
call that uses caching, thinking, tools or images on Claude. Setting a lane
takes four env vars (see `.env.example`), and one more condition: the
provider's host must be listed in `CHIEF_SUBPROCESSOR_HOSTS`, the record that
the privacy policy names it as a subprocessor. Every lane carries a business's
data, so an unlisted or non-https host keeps the lane on Claude. Today no lane
is moved and the list is empty.

## Not built yet

- The brain replacing parts of the five-minute business snapshot. That waits
  for a week of real digests, so they can be judged against the blocks they
  would replace, measured on KMJ behind a switch.
- The offline replay bench for lane graduation (workstream G): the evidence
  a lane is ready to move.
- Public agent identity (KYA-OS Level 1 on the MCP server, did:web for the
  business). This waits until a client or partner needs it.
- Any learning use of the interaction record. That waits for consent language
  that covers it.

See also `docs/plans/SELF_HOSTED_SMALL_MODEL_2026-10-11.md` and
`docs/LAYER_TWO_CAPABILITIES.md`.
