# One Solutionist platform, two editions

Status: foundation implemented on a development branch; neither a Connect launch
nor a pricing migration. Decision recorded 2026-09-10 from the product discussion.

## Product decision

The brand is Solutionist. Connect and Complete are working edition names.
Both use one account, business workspace, records, tools, permissions, approvals,
and activity history. Customers can eventually switch without moving their data.

| | Connect | Complete |
|---|---|---|
| Promise | Bring your supported AI to run business work through Solutionist | Use Solutionist with AI supplied |
| Chief | Coordinates delegated work and presents approvals and results | Coordinates work using Solutionist-funded execution |
| Funding | Customer funds supported agent reasoning; a bounded Chief allowance is included | A defined Solutionist AI allowance is included |
| Entry price hypothesis | $49 per month | $79 per month |

These prices are pilot hypotheses. There is no approved allowance or cost model
yet. No new Stripe product, checkout option, automatic repricing, or public offer
is introduced by this foundation. Preserve all current, founder, comp, and
grandfather arrangements. Complete is a working name, not an automatic rename of
every existing subscription.

Initial customer: independent consultant or small service firm. Initial workflow:
find overdue invoices, prepare follow-ups, request approval, send through the
business's connected email account, and record the verified result.

## What exists

- `mcp_server.py`, `mcp_tokens.py`, and `mcp_oauth.py`: external client access,
  business-scoped credentials, read/write scopes, revocation and OAuth.
- `action_registry.py`, `policy_engine.py`, `action_proposals.py`: permitted
  operations and proposals for approval. Direct irreversible actions stay gated.
- Chief jobs and assignments: internal execution and persistent objectives.
- Billing tiers, feature gates, credits, API usage logging, and spend controls.
- Frontend customer Agent Access settings: connect an external client.

The 2026-09-10 public MCP health response reported 34 read and 59 write tools.
That reports the server's inventory, not a signed-in end-to-end acceptance test.
Existing external-client access is not an in-app agent runner. The July personal
agent strategy's "zero MCP code" finding is historical, superseded by the code.

## Delivery sequence

### F0/F1: describe the service separately from the business tier

Implemented in this change:

- `GET /billing/entitlements` keeps its fields and adds `service_profile`.
- The profile separately describes the business tier and limits, current AI
  delivery and monthly plan grant, and external-agent plan inclusions.
- Current offers resolve to `edition: legacy`. Chief delegation is explicitly
  unsupported. Neither edition nor payer is read from business settings.
- Existing feature decisions, price resolution, credit charging, and checkout
  remain authoritative and unchanged. No schema migration is required.
- Endpoint execution tests cover ownership, missing auth/businesses, billing
  variants, and compatibility with the original response fields.

This is a contract to build against, not independent edition enforcement yet.

### F2: prove one supported execution arrangement

Start here next. Select a provider only after proving its documented integration
can serve this experience. Record the current official authentication, runtime,
subscription entitlement, and automation limitations in a dated decision.

Deliver a development harness that starts a bounded task, streams progress,
cancels it, and identifies which account funds it. Establish whether it runs on
the customer's device or an isolated hosted worker. If local, closing the runner
makes it unavailable; do not promise always-on work. Browser account connection
alone does not create execution capacity. Do not collect subscription session
tokens or assume a chat subscription is an unrestricted API budget.

Acceptance: one real supported agent can read a fixture business through scoped
tools and produce a draft. No production customer writes or messages are needed
for this milestone. Document unsupported capabilities and connection loss.

### F3: connect Chief's jobs to the runner

Extend the existing job/assignment lifecycle rather than inventing another queue.
Persist business, actor, provider connection, execution source, permitted tools,
funding source, progress, approval references, results, and deduplication key.
Keep provider credentials outside prompts and preserve tenant isolation.

Task states must cover queued, running, awaiting approval, completed, failed,
cancelled, and interrupted. Reconcile the agent's result with the business
action's actual result. A generated message is not a sent email.

Reject work after credential revocation. A retry must not send twice or apply a
change twice. Reuse policy checks and the approval queue. Basic activity history
and revocation must be accessible to every pilot business. Audit/undo persistence
is currently best-effort in places: evaluate durable recording before widening
unattended execution. Chief-paid fallback requires the user's consent and budget.

Acceptance: the overdue-invoice workflow completes against a test business and
test recipient, including approval denial, interruption, duplicate delivery,
revocation, stale invoice data, and failed send. Until this passes, Connect is
not described as Chief running a customer's agent inside the product.

### F4: meter and rehearse the offer

Separate platform/Chief processing, customer-funded agent processing, and other
services (email, SMS, voice, media, storage, hosting). Do not treat all MCP calls
as free: tools can still incur platform or vendor costs. Record usage source at
the operation boundary, not from an untrusted agent's claim.

Measure cost per completed workflow, active customer cost, completion rate,
support time, and repeat usage. Establish included coordination units, concurrency
and spend limits, overages, and the behavior when an allowance is exhausted.
Do not deduct platform inference credits for reasoning paid by the customer.

Introduce server-controlled offer definitions separating business plan, AI
arrangement, and allowances only after the runtime and cost evidence exist.
Prove mapping conflicts fail safely; unknown prices cannot grant access. Use
billing rehearsal to compare every existing arrangement before migration.

Connect's entry offer should include the reviewed writes needed for the pilot;
the current Professional-only write rule must change through this explicit offer
mapping, not a global relaxation of all Starter access. Current accounts retain
their promised price and features. Edition changes preserve records and require
an explicit subscription flow. Database migrations, if needed, follow the repo's
manual migration process.

### F5: onboarding and controlled launch

One brand, one login, two setup paths: "Use my existing AI" and "Have Solutionist
provide the AI." Show supported providers, connection state, limits, and which
services remain separately billed. Complete setup with a useful verified task.
Support mobile and desktop; do not assume a local desktop runner exists on mobile.

Launch one provider and the invoice workflow to a small pilot cohort. Publish
pricing and edition claims only when checkout, usage limits, switching, support,
and failure recovery are verified. Add more providers and higher tiers based on
pilot evidence. The $99/$199 Connect expansion discussed is not a launch promise.

## API semantics and compatibility

`service_profile.schema_version` is 1. Current `edition` is `legacy` and AI
`delivery` is `solutionist_provided`. These describe the existing offer; they do
not mean an account is currently permitted to execute a task.

`monthly_plan_credits` is the recurring grant for the effective plan, including
the existing founder/comp resolution. It is not remaining credit, the trial
allowance, or the result of a spend check. Null means no resolved plan grant.

External-agent `*_included_in_plan` fields describe purchased plan inclusion.
They are not credential status or effective authorization. Existing top-level
features, subscription checks, grandfathering, MCP enablement, scopes, and policy
checks continue to decide access at the execution boundary. Setting an `edition`
or `ai_delivery` value in customer-editable settings grants nothing.

Old clients can ignore the additive profile. No frontend rollout is required for
F0/F1. Rollback removes the profile addition; no data or subscription conversion
needs reversing. A future version must add explicit server-controlled Connect
resolution rather than inferring Connect from the existence of an MCP token.

## Work deliberately deferred

Multiple agent providers, an agent marketplace, new industry modules, a second
codebase, six pricing cards, and broad marketing redesign are outside this pilot.
The launch test is one customer's useful workflow completed correctly with known
cost and recoverable failures, not the number of connectors exposed.
