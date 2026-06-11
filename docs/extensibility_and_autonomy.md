# Extensibility Layer + Autonomous Chief — Strategy Spec v1 (Arc 20 Phase A)

**Status:** Strategy spec for Kevin's review — NO code in this phase. Phase B implements only after Kevin's rulings on tiers, capabilities, and sequencing.
**Author:** Claude Code, 2026-06-10.
**Posture:** Kevin has ruled BOTH directions are being built; this spec's job is the *how* — security, structure, and order — not the *whether*.

---

## 0. The discovery that reshapes this spec

Before designing anything, I audited the codebase against the wishlist. The headline:

**Solutionist already has the skeleton of both directions.** This is not a greenfield bet — it's an exposure-and-governance project:

| Vision component | What already exists in the codebase |
|---|---|
| "When X happens, trigger Y" rules | **`workflow_engine.py`** (Living Growth Phase 3): event triggers + shallow-equality conditions + multi-step actions + a **confirmation gate** (`requires_confirmation` pauses a run) + run draining. `ModuleTrigger` on custom modules (`new_entry` / `overdue` / `field_change` → action + template). |
| Custom practitioner functionality | **Custom modules** (schema + archetype dispatch + `ModuleAgentConfig`) — practitioners already define their own data structures with per-module agent behavior. |
| "Chief proposes, practitioner approves" | **Phase G proposal pattern** (`chief_bookkeeping_proposals`, 6 types, approve/reject/learning-signals) — the autonomous-graduation substrate is shipped and battle-tested on real books. |
| Granular consent | Sticky-with-source (`practitioner` pins beat `inferred`), the trust-layer 4-question discipline, period soft/hard locks — consent *patterns* exist; they need generalizing, not inventing. |
| Isolation | RLS everywhere + the SECURITY DEFINER helper discipline + per-business scoping on every table + grandfather/metering chokepoints (`billing_limits`, `usage_metering`). |
| Action vocabulary | Chief of Staff's action handlers (create_invoice, create_goal, publish_post, …) — a real, bounded verb set autonomous agents can be limited to. |
| Audit | `api_usage`, `period_edit_overrides`, admin action logs, proposal rows with reasoning — the "why did Chief do this" answer already has homes. |

**Implication:** the right v1 is not "build an extensibility platform." It is **"put a practitioner-facing door, a governance layer, and an audit spine on the engine that already runs."** That collapses risk, cost, and time-to-validation dramatically.

**Anthropic feature reality (stop-condition surface):** mid-conversation system-message injection is achievable today with the standard Messages API (system content can change per call; the cache question is a prompt-architecture problem we control). MCP is GA and stable. **"Claude Managed Agents" with self-hosted sandboxes** — I'm architecting against the Claude **Agent SDK** pattern (agent loop on OUR Railway infrastructure), which is available today and gives the same security shape Kevin described (data never leaves the environment). If/when Anthropic's managed-agent hosting with self-hosted sandboxes is the better runtime, the design below slots it in without rework — the boundary contract (§2.2) is runtime-agnostic. **Kevin: verify current availability of managed-agent hosting on the Anthropic platform before Phase B sequencing; nothing below depends on it.**

---

# Part 1 — Extensibility Layer

## 1.1 Building-block taxonomy (what exists → what's exposable)

| Building block | Expose? | Guardrails required | What practitioners want to customize | Risk if practitioner logic touches it |
|---|---|---|---|---|
| **Workflow engine** (triggers/conditions/steps) | ✅ Tier 1+2 core | Action allow-list; per-business event scope; rate limits; confirmation gate default-ON for outbound actions | "When a client books X, send template Y"; "when invoice overdue 7d, draft reminder"; the therapist's "anxiety mention → flagged note" | Runaway loops (rule triggers event that triggers rule) → cycle detection + per-run budget |
| **Chief action vocabulary** (create_invoice, draft_email, …) | ✅ as the ONLY verbs rules/agents may use | Each verb carries a permission scope + reversibility class (§2.4); no raw DB verbs ever | Composing verbs into their methodology's workflows | A verb that writes money data (invoice, GL) must stay proposal-gated regardless of rule author |
| **Custom modules** (schema + archetype dispatch) | ✅ already practitioner-facing | Schema validation (exists); module-scoped triggers only | Their own intake/tracking structures (already happening) | Low — already sandboxed by construction |
| **Proposal pattern** (Phase G) | ✅ as the universal output channel | None new — it IS the guardrail | "My rules can suggest, I approve" | None — this is the safety valve |
| **Note templates / terminology** (vertical_terminology, dictionary.ts) | ✅ Tier 1 (per-business overrides) | Length/content validation; no script injection into rendered surfaces | Their own vocabulary (therapist: "session note" templates) | XSS in rendered templates → sanitize at render, not at save |
| **Archetype engine / business-type dispatch** | ⚠️ Tier 2 read-only, Tier 3 read-only | Practitioners may READ which archetype applies + override *parameters*, never dispatch logic | Tuning thresholds ("overdue" = 14d not 7d) | Letting extensions change dispatch = chameleon core forked per tenant → roadmap chaos. **Don't.** |
| **Trust layer / access enforcement (RLS, consent)** | ❌ NEVER exposed as a block | N/A — it's the cage, not a toy inside it | Nothing legitimate | Any extension API that can express "read business_id != mine" is a CVE. The API simply has no such parameter (§1.3). |
| **Client memory / contact data** | ⚠️ via consent-scoped accessors only | Field-level consent classes (§1.3.2); extensions declare which classes they read | "Use the client's goals in reminders" | The single biggest leak surface — hence consent classes + audit per execution |
| **External connections** (consultant's PM tool) | ✅ Tier 2 inbound webhooks; Tier 3 outbound | Signed inbound (HMAC); outbound via per-extension allow-listed domains + secret vault | Pull PM-tool data into Chief context | Server-side request forgery + secret leakage → domain allow-list + secrets never readable back |
| **Metering/billing (`usage_metering`, `billing_limits`)** | ❌ read-only self-view only | N/A | Seeing their own usage | Extensions that could mute metering = revenue leak |

## 1.2 Three-tier design

### Tier 1 — Visual Rule Builder (no-code; everyone; **builds on workflow_engine**)
- **Surface:** "Automations" tab. Sentence-builder UI: *WHEN* [event from a fixed catalog: booking created, invoice overdue N days, client message contains keyword, module entry field changes, form submitted] *IF* [conditions on the event's own fields] *THEN* [1–3 actions from the Chief verb allow-list] — with **"ask me first"** (proposal) vs **"just do it"** toggle per action, where "just do it" is only offered for reversibility-class-A verbs (§2.4).
- **Blocks exposed:** workflow triggers, condition matcher, ~12 curated verbs (draft email → proposal, send template email, create task, flag/annotate contact, create module entry, notify practitioner, schedule follow-up, apply tag, draft invoice → proposal).
- **Security model:** sandboxed by construction — the UI cannot express anything the engine's allow-list doesn't contain; every execution runs server-side under the business's scope (service-role queries are always business_id-pinned, as today); cycle detection (a rule's actions are tagged with rule-id provenance; an event caused by rule R cannot re-trigger R, and chain depth caps at 3); per-business execution budget (e.g., 500 rule-runs/day, soft).
- **Audit:** every run writes `extension_runs` (rule, trigger event snapshot, actions taken/proposed, outcome) — practitioner-visible "What my automations did" feed.
- **Rollback:** rules are versioned rows; disable = one toggle; every class-A action records its undo handle (§2.4).

### Tier 2 — Config Workflows (low-code; power practitioners)
- **Surface:** JSON (not YAML — one parser, better errors) authored in-app with schema validation + dry-run ("test against my last 30 events"). Same engine, fuller grammar: multi-step sequences, branching conditions, delay steps, variables from event payloads, **inbound webhook triggers** (per-rule signed URL), template interpolation.
- **Blocks exposed:** Tier 1 + webhook-in, the full (still allow-listed) verb set, read-accessors for consented client-data classes, archetype parameters (read + numeric overrides).
- **Security:** JSON Schema validation at save (reject unknown keys — no forward-smuggling); same server-side sandbox; webhook secrets generated per-rule, rotatable; interpolation is data-only (no expression evaluation — **no user-supplied code executes in v1, period**; that's the line that keeps Tier 2 out of sandbox-infrastructure territory).
- **Audit/rollback:** same `extension_runs` + config version history with one-click revert.

### Tier 3 — Developer API/SDK (devs who serve practitioners)
- **Surface:** REST under `/ext/v1/*`: CRUD on rules/configs, read consented data via the same accessors, fire custom events (`POST /ext/v1/events`), receive outbound webhooks, manage module schemas. Thin TypeScript SDK later.
- **Auth:** per-business **scoped API tokens** (practitioner mints in Settings; scopes = consent classes + verb classes; revocable; hashed at rest). A token is *of* a business — cross-business access is unrepresentable.
- **Security:** rate limits per token (reuse the metering spine); same allow-listed verbs (the API is a remote control for the same engine, NOT a new capability plane); outbound webhook payloads exclude restricted-class fields unless the token scope includes them.
- **Audit:** every API call → `api_usage`-style log with token id; practitioner sees third-party activity on their data.
- **Rollback:** token revoke kills everything downstream instantly.

**The unifying principle: one engine, three doors.** Tier 1/2/3 differ in authoring ergonomics, never in capability ceiling or security model. Anything expressible at Tier 3 is governed identically to Tier 1. This is what keeps the access-enforcement layer un-compromisable by construction.

## 1.3 Access-enforcement protection (load-bearing)

1. **Cross-business isolation by unrepresentability.** Extension execution context carries exactly one business_id (from the rule's row). Accessors take no business parameter — they close over the context. RLS remains the second wall (SECURITY DEFINER helper discipline per the hotfix lesson); the API shape is the first.
2. **Client-memory consent classes.** Client data fields group into classes: `contact_basics` (name, email), `engagement` (bookings, invoices), `notes_sensitive` (session notes, flags, memory), `financial` (their payment history). Extensions DECLARE classes at save; practitioners see the declaration ("this automation reads session notes"). **Client-facing consent** (the "client owns 'Chief can use my X for Y'" model): v1 = practitioner attests; v1.5 = client-visible disclosure on booking/intake surfaces ("this practice uses automation on engagement data") with per-client opt-out flag that accessors honor. Full per-client consent UX is real product surface — sketched, sequenced behind validation.
3. **Audit trail:** `extension_runs` (above) + retention; the trust-layer question "why did this happen?" answers with: rule version + trigger snapshot + condition trace + action results.
4. **Kill switches, three levels:** per-rule toggle (practitioner) → per-business "pause all automations" (practitioner, one button) → platform global `EXTENSIONS_ENABLED=off` + per-extension platform disable (Kevin, Launch-Console style).

## 1.4 Marketplace v2 (sketch only — explicitly deferred)
Install = copying a *rule/config template* (not code — there is no code) into your business with your own consent grants re-prompted. Vetting: platform review of declared classes + verbs (cheap because the grammar is closed). Revenue: 80/20 creator/platform on paid templates, free tier for community templates; creator payouts ride the existing Connect rails. Versioning: installed copies pin a version; updates prompt. Deprecation: platform disable + practitioner notification. **Build trigger:** only after Tier 1 validation passes AND ≥3 practitioners organically ask to share rules.

## 1.5 Validation strategy (adopted as ruled)
Ship **Tier 1 only** first. Instrument: % of active practitioners with ≥1 enabled rule, runs/week, proposal-vs-auto mix. **≥20% adoption in 60 days → fund Tier 2+3. <5% → stop; fold the best rule ideas into core features instead.** The workflow engine remains valuable either way (Chief itself uses it) — that's why building Tier 1 on it is a no-regret move.

---

# Part 2 — Autonomous Chief

## 2.1 Mid-conversation system messages (the quick win)
**Today:** Chief's system prompt is assembled per call (business context + GL block + learning digest); long sessions carry the whole history and context updates force full-prompt rebuilds — cache-hostile and stale-prone.
**Change:** restructure the prompt into a **stable cached core** (identity, trust rules, archetype voice — rarely changes, explicitly cache-markered) + a **dynamic state block** delivered as a system-role update appended at the conversation's current position (not by rewriting the head). When the practitioner's state changes mid-task (invoice paid, period closed, rule fired), Chief gets a compact `STATE UPDATE:` system message — the cached prefix stays intact.
**Where it helps most (audited):** (1) bookkeeping sessions where books change under the conversation (reconciliation while sync runs); (2) the Chief drawer staying open across navigation; (3) post-action confirmation ("invoice sent" arriving as state, not as re-fetched context); (4) usage/cap state ("you're at 90%") without prompt rebuilds.
**Risk:** low; pure prompt architecture; no new permissions. **This ships first.**

## 2.2 Self-hosted agents (Agent SDK on Railway)
**Architecture:** an `agent_runtime` worker on Railway (same private network) running the Claude Agent SDK loop. Agents get: (a) a **tool belt that is exactly the Chief verb allow-list** — the same verbs, same reversibility classes, same proposal fallback; (b) data access through the same consent-scoped accessors as extensions (§1.3); (c) a per-run context pinned to one business. No filesystem, no network egress except allow-listed integrations, no raw SQL — the sandbox is the API surface, enforced server-side, with RLS behind it.
**Boundaries:** agents CAN: draft/send template emails (scope-granted), schedule/reschedule within practitioner-set windows, create tasks/entries, run bookkeeping analyzers, prepare content drafts. Agents CANNOT: touch money movement (payments, transfers, refunds — always proposal), alter periods/GL directly (proposal), change settings/billing/team, message clients in regulated-sensitive contexts (§5), or act on a business whose practitioner hasn't enabled autonomy.
**Permission scopes (granular consent, per business):** `send_email_templates`, `send_email_freeform`, `manage_schedule`, `publish_content`, `manage_tasks`, `bookkeeping_proposals_auto_approve(category)`. Each independently grantable/revocable in Settings → Chief Autonomy; each grant logged.
**Audit:** every autonomous run writes `agent_runs` (intent, pre-action reasoning, scopes used, actions + undo handles, outcome) — feeding the same "What Chief did" feed as extensions. Pre-action reasoning is MANDATORY (trust layer: the "why" is written *before* the act, like the DRL).
**Rollback:** every class-A action records its undo (cancel booking, unpublish post, delete draft); class-B actions (sent email) get a 60-second outbox delay = recall window, then logged-irreversible.

## 2.3 MCP tunnels
**Purpose:** Chief/agents reach private services (Railway internal APIs, Supabase functions, the practitioner's connected tools) without public exposure.
**Architecture:** MCP servers run **inside** the Railway private network; the agent runtime connects over the private mesh (no public ingress). For practitioner-side private tools (the consultant's self-hosted PM tool): an outbound-only tunnel client the practitioner runs, registering with our MCP gateway over an authenticated WebSocket — their service is never publicly exposed either. Auth: per-business MCP credentials minted from the same scoped-token system as Tier 3 (one auth model everywhere); connections are business-pinned; the gateway enforces scope before forwarding.
**Security boundary:** the MCP gateway is the choke point — tool catalogs are per-business, every call logged to `agent_runs`, and the gateway strips/blocks any tool result that would exceed the run's consent classes.

## 2.4 Autonomous action safety model
- **Pre-authorization:** scopes above; nothing autonomous without an explicit grant; grants are per-business and expire-able (optional 90-day re-confirm).
- **Confidence threshold + graduation:** an action category becomes auto-eligible only when (a) the practitioner granted the scope AND (b) the category's *proposal approval rate ≥80% over ≥20 proposals* for THAT business (the Phase G data already accumulating). Below that, Chief proposes. Confidence per action: the agent self-reports; below 0.8 → propose regardless of grant.
- **Reversibility classes:** **A** = cleanly undoable (schedule, tasks, drafts, unpublish) — auto-eligible. **B** = recall-window (outbound email: 60s delayed send) — auto-eligible with scope. **C** = irreversible or money-touching (payments, GL posts, period closes, refunds, anything leaving compliance trails) — **proposal-only forever** (not a tuning knob).
- **Big red button:** "Pause Chief autonomy" per business (instant, kills queued runs) + platform-global `CHIEF_AUTONOMY=off`.
- **Liability (recommended position, Kevin rules):** practitioner owns client-facing outcomes of *granted* scopes (the grant UX says so explicitly, with examples); the PLATFORM owns containment failures (action outside granted scope, wrong business, class-C executed without approval — these are bugs, on us, and the audit trail proves which occurred). Mirror it in ToS; pair with the recall window + caps so worst-case granted-scope harm is small. This matches how practitioners already think about staff: you own what you delegated; the agency owns sending you someone who ignored instructions.

## 2.5 Implementation order (recommended)
1. **Mid-conversation system messages** — days, not weeks; immediate quality/cost win; zero new permissions.
2. **Expanded proposal pattern** (Phase G → scheduling, content, email domains) — generates the graduation DATA autonomy needs, with zero autonomy risk. *(This is the validation strategy executing itself.)*
3. **MCP gateway + internal MCP servers** — the plumbing agents will stand on; useful immediately for Chief's own tool reach.
4. **Agent runtime + scopes + class-A/B autonomy** — the actual autonomous Chief, landing on a bed of graduation data, consent UX, and audit spine that already exist by then.
**Why this order:** each step is independently valuable, independently shippable, and each de-risks the next. Inverting (agents first) would mean building consent/audit/graduation under deadline pressure with live autonomous actions — the exact way trust gets burned once and never recovered.

---

# Part 3 — Sequencing both directions

**Recommendation: interleave, with extensibility's Tier 1 carrying the lead.**

1. Mid-conversation system messages (autonomy step 1 — the quick win, ships alone).
2. **Tier 1 Visual Rule Builder** (extensibility) + **expanded proposals** (autonomy step 2) — *the same PR family*: both are workflow_engine + proposal-pattern work. This is the convergence the audit revealed: the rule builder's "ask me first" actions ARE proposals; the proposal expansion IS the rule builder's action set. Building them together costs ~60% of building them separately.
3. Validation window (60 days of Tier 1 + proposal data).
4. Then, informed by data: MCP gateway → agent runtime (autonomy) and/or Tier 2 (extensibility) per what the validation says.

**Why extensibility leads:** Kevin's stated goal is practitioner-validated roadmap data; Tier 1 produces it fastest. Autonomy's graduation model *needs* that same data. And practitioners meeting "Chief acts alone" AFTER months of "my rules + Chief's proposals never surprised me" is the trust on-ramp; the reverse order has no on-ramp.

# Part 4 — Cross-cutting

- **Trust layer everywhere:** rules store rationale at authoring ("what this automation is for" — one required sentence) + condition traces per run; agents write pre-action reasoning; both feed one practitioner-visible activity feed. The DRL pattern (reason first, act second, audit forever) is the house style now.
- **Pricing (surfaced for Kevin):** recommend rule *executions* are free (they're the product being sticky) but **agent runs and rule steps that invoke Claude count as Chief interactions** under the locked metering (an autonomous Chief that works while you sleep consuming your allotment is exactly the "revenue scales with success" thesis — and the 2× cap keeps it safe). Tier 3 API: included in Practice, add-on below it. Marketplace rev-share per §1.4 when it exists. **Decision needed only before agent GA, not before Phase B starts.**
- **Migration path:** everything opt-in per business (Automations tab starts empty; autonomy starts with zero scopes). Zero behavior change for current practitioners until they touch the new surfaces. Feature-gated (`extensibility`: professional? — Kevin's call; lean: Tier 1 for ALL tiers since it drives the validation data, gate Tier 2/3 + autonomy scopes at Professional+).

# Part 5 — Honest risks

1. **The wall practitioners will hit:** Tier 1's closed verb grammar can't express "compute something custom" (scores, formulas) or true external API calls — they WILL ask within weeks. The answer is Tier 2's webhook-out + Tier 3, *not* loosening Tier 1; budget for the disappointment in copy ("that's coming in Advanced workflows").
2. **Misfire severity is asymmetric:** wrong-client email is the nightmare (reputation, confidentiality). Hence: template-email scope separate from freeform; recipient resolution double-checked against the triggering event's contact; recall window; and contact-mismatch is a hard abort, never a confidence judgment.
3. **Regulated verticals:** therapist/lawyer client communication carries professional-ethics weight (confidentiality, solicitation rules, in some cases mandated-reporting context). Recommendation: autonomous *client-facing* communication ships **disabled by vertical default** for therapist/lawyer/nonprofit-counseling types (proposal-only), practitioner can enable with an explicit acknowledgment screen. Also: the therapist's "auto-flag anxiety mentions" example is *internal* annotation — fine at Tier 1; it's outbound communication that's gated.
4. **Trust is one-shot:** the first autonomous mistake a practitioner sees defines the feature. That's why graduation thresholds are per-business (Chief earns autonomy from EACH practitioner), why the activity feed over-communicates, and why v1 autonomy is class-A/B only.
5. **Platform-risk honesty:** an extensibility layer makes Solutionist harder to absorb but also harder to change — every exposed surface becomes a compatibility promise. Mitigation: version the grammar from day one (`"rule_version": 1`), keep the verb list curated-small, and reserve the right (in ToS and in code) to migrate rules forward.

## Stop-condition check (none block, two surfaced)
- **No fundamental extensibility↔autonomy tension found — the opposite:** they share the engine, the verbs, the proposal channel, and the audit spine (hence Part 3's interleave). The one interaction rule needed: agent-caused events DO trigger practitioner rules, but carry provenance and count against the same chain-depth cap, so a rule and an agent can't ping-pong.
- **Surfaced:** Anthropic managed-agent hosting availability (architecture doesn't depend on it; verify before Phase B step 4). · Per-client consent UX (v1.5 scope, real product design work — sequenced behind validation, not skipped).

*End of Phase A spec. Phase B awaits Kevin's rulings: which tiers, which autonomy steps, sequencing confirmation, and the two pricing calls.*
