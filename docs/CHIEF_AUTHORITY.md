# Mission Control Chief authority

The model proposes actions. `platform_chief_authority.py` classifies each action outside the model. Unknown actions are denied even if a handler was accidentally registered. Permission edits and approval decisions exist only on owner-authenticated HTTP routes, never as Chief tools.

Defaults: drafts and business notes may be saved; paid creative work and marketing cancellation/pause require review. Email, invitations, trial changes, lead changes and development handoffs always require review. The owner can change the four ordinary permissions in Chief's permissions panel. Marketing publishing keeps its existing exact-post approval.

Each mutation gets a durable owner-bound record containing the exact action, request ID, content hash and 24-hour expiry. Review endpoints accept the record ID, hash and decision, not a replacement action. A conditional database update claims execution once; failed/uncertain external outcomes never automatically retry. A database trigger prohibits rewriting scope or resetting completed records. Email recipient addresses are resolved for review and checked again before delivery. Development proposals cannot select arbitrary local directories.

Direct Dev Desk submissions remain owner-authorized requests. New task records retain the owner, source, scope and scope hash. A trigger prevents later edits to authorized task scope. A Chief-originated handoff references its recorded approval. Follow-up notes and progress reports remain available.

Paid Mission Control chat and creative entry points now check a fresh database aggregate. Accounting errors pause those paid operations. This is a recorded-usage cutoff, not an atomic reservation or a guarantee against in-flight/uninstrumented provider charges. Other application AI routes retain their existing spending policy. Ordinary record access does not depend on this check.

## Independent development boundary

Both Claude builder workflows accept only owner-originated triggers, leave PRs open, and no longer instruct the agent to merge. Production branch rules must additionally require owner/code-owner review with stale approvals dismissed and no agent bypass. CODEOWNERS assigns all deployed code to the owner because any application code can run with application authority. The workflow wording is not the enforcement boundary; GitHub permissions and active branch rules are.

**A local agent running as the owner's Windows account is outside this containment.** It can use whatever personal credentials that account exposes. Solution Space currently launches sessions this way. Completing local containment requires an isolated cloud worker or a restricted OS account with separate credentials; adding prompt instructions or an editable command hook would not solve it. Do not describe the entire desktop as contained until that migration is completed and verified.

## Rollout

1. Rehearse and apply `supabase/APPLY-2026-09-16-chief-authority.sql` after the existing dev-bridge migration. It adds control-plane tables/RPCs and an additive `dev_tasks.authority_record` column.
2. Deploy backend and frontend. On missing permissions storage, action execution fails closed.
3. Install and verify production branch rules separately; repository files cannot activate them.
4. Move unattended Solution Space execution to isolated credentials before claiming complete containment.

Validation: adversarial pytest tests, actual PostgreSQL migration/transition checks through PGlite, frontend typecheck/build, and intercepted browser interactions at desktop/mobile widths. No live email, invitation, build handoff or paid image is used for validation.
