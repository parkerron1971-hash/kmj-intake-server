# Jev decision integration

Implemented on the isolated backend branch `feat/jev-decisions`, based on
`origin/main` 73b5f44 (September 22, 2026). No database migration or frontend
deployment is required. No shadow mode: the owner requested direct active use.

## Behavior

For eligible background events, Jev chooses among five code-owned plans:
lead follow-up, booking review, payment review, contract review and connected-agent
result review. A validated, high-confidence choice replaces the agent's initial
generative planning call. Chief's existing tool loop then reads the records,
performs permitted work and writes its recap. Jev does not generate action
parameters, accept assignments, certify payment status or execute tools.

Unknown, conflicting, mixed-family or low-confidence results use the existing
planning call. The same fallback applies to missing configuration, outages,
timeouts, rate limits and invalid responses. No events are suppressed and event
acknowledgement/replay semantics are unchanged. The existing business autonomy,
pause, budget and execution controls still apply.

Urgency and owner-attention assessments are stored for evaluation; they do not
change scheduler ordering or trigger notifications in this release.

## Provider connection

Vercel AI Gateway is the default. The backend remains on Railway and calls
`https://ai-gateway.vercel.sh/typesafe/v1/systemone` with
`model=typesafe-ai/jev`. This documented TypeSafe-compatible route preserves
Choice/Score confidence and Noul answers, sharing the adapter with direct access.
No JavaScript SDK, new runtime or additional frontend server is needed.

[Official Gateway compatibility API](https://vercel.com/docs/ai-gateway/sdks-and-apis/typesafe)
and [TypeSafe API](https://docs.typesafe.ai/api).

Direct TypeSafe is available with `CHIEF_DECISIONS_PROVIDER=typesafe`, using
`jev-1.13.0` at `https://api.typesafe.ai/v1/systemone`. Provider changes are
explicit; failures do not silently send data to a different provider.

Gateway reports the alias `typesafe-ai/jev`; this integration does not pretend
that alias proves an immutable underlying model version. Direct access pins
1.13.0. The returned model must match the configured route. Review routing
results when the Gateway model changes.

## Activation

Configure these values on the Railway web AND scheduler services:

```dotenv
CHIEF_DECISIONS=on
CHIEF_DECISIONS_PROVIDER=vercel
AI_GATEWAY_API_KEY=<server secret>
CHIEF_DECISIONS_BUSINESSES=<your business UUID>
CHIEF_DECISIONS_TIMEOUT_SECONDS=2
CHIEF_DECISIONS_MIN_CONFIDENCE=0.85
```

The business must also have its existing standing Chief agent enabled. An empty
business list enables nobody; wildcard values do not enable all tenants. The
repository example defaults off so a code release alone never exports new data.

For direct access, change provider to `typesafe` and configure
`TYPESAFE_API_KEY`. Never use a VITE_ variable for either credential.

The existing authenticated owner-only `GET /agents/chief/agent?business_id=...`
now includes `decisions.status`, provider, model and question revision. Status
reports configuration readiness, not a successful live provider connection.

Roll back with `CHIEF_DECISIONS=off`; the old planning path resumes. No schema
rollback or loss of job history is involved.

## Bounds and evidence

- One compact request per homogeneous event batch, maximum 12 events.
- Only selected text/boolean fields are sent; identity, credential, amount,
  date and arbitrary nested fields are excluded. Selected free text can still
  contain personal information: this is minimization, not a PHI/PII anonymizer.
- Explicit event-to-business matching; unsupported event types are rejected.
- Selected text uses existing injection attempt detection; this is not a
  complete prompt-injection defence. Authorization remains deterministic.
- Workflow confidence AND winning probability must meet the configured floor;
  sufficient-context probability must be at least 0.9. Thresholds are provisional
  until measured on representative examples, not claimed accuracy guarantees.
- Full answer keys, types, probability ranges/sums, winning choice and score
  consistency are validated. Raw provider errors never enter the logs.
- Default provider budget is two seconds; at most one retry for 429/529 that
  fits the remaining budget. Retry-After is never shortened. Existing budget
  lookup and best-effort usage logging have separate one-second bounds.
- Four concurrent evaluations per process; three failures open that provider's
  circuit for 60 seconds. These controls are per replica, not global rate limits.
- Existing `api_usage` receives input/output usage and internal cost with zero
  additional customer credits. Gateway's reported actual USD cost is preferred;
  absent cost metadata uses a conservative $0.042/M input estimate. Provider
  timeouts without usage cannot establish exact billed token counts.
- Validated decision distributions, revision, route, elapsed time, attempts and
  adoption are included in existing agent-run detail and audit payloads alongside
  actual actions, failures and idle state. No new table is needed.
- The event input taint reset was moved before event defusing, preserving this
  run's detected taint rather than clearing it just before execution.

## Verification and live smoke

Offline tests use HTTP MockTransport and mocked persistence. They verify both
provider contracts, all plan families, low confidence, malformed responses,
tenant isolation, credential absence, deadlines, cancellation, circuit breaking,
metering, owner-only status and the real agent/tool-dispatch path.

Run the focused suite:

```text
python -m pytest __tests__/test_decision_service.py __tests__/test_chief_agent.py -q
```

Run tests with no live credentials or dotenv loading. The implementation session
used a sanitized Python environment and disabled dotenv loading before pytest.

For a live connection check after configuring the provider key in the process:

```text
python scripts/jev_eval.py --live --provider vercel --out ../jev-live-report.json
```

The script uses five synthetic business events and one hostile-text fixture.
It strips unrelated credentials and substitutes local budget/persistence hooks.
It cannot execute business tools or write production records. This is a small
connection smoke test, not a measured production accuracy benchmark.

No live key was present during implementation. Deployment and live provider
validation remain to be performed; offline test results do not certify them.

Local verification (2026-09-22): 196 focused and adjacent regression tests passed. Changed Python modules compile and git diff --check passes. Existing Protobuf/FastAPI deprecation warnings were reported. Full repository CI, browser/database migration checks and live provider inference were not run; this change has no frontend or migration.
