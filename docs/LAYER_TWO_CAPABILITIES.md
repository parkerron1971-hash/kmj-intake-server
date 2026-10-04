# Chief's layer-two capabilities

Status: release integration, 2026-10-04. The original local implementation has
been rebased onto current production scheduling behavior. Measured cost/quality
results and natural model selection remain separate from deployment verification.

## Objective

Increase useful work per frontier-model call. Chief supplies intent and judgment;
tested capabilities gather current evidence, compute results, and return compact
answers through the existing action/tool surface. Frontier models remain available
for reasoning. The initial implementation requires no GPU, new provider, model
training, database migration, or package installation.

This extends the inference cache described in `inference_layer.md`. An answer
cache reuses prior output; a capability executes tested logic against fresh input.

## Implemented: booking-plan rehearsal, version 1

`booking_rehearsal.py` exposes `rehearse_booking_plan` as a read action in
`action_registry.py`, `chief_of_staff.ACTION_HANDLERS`, and the existing MCP schema
registry. Chief derives its native read tools from that registry. MCP callers
retain their existing token/business/policy checks; database reads use Chief's
current-context helper. The caller cannot supply or override the business ID.

The tool accepts 1-8 proposed **new** appointments, each with an offering UUID
and an ISO timestamp carrying an explicit UTC offset. Order expresses priority.
It loads the current business settings, active offering durations, and active
booking intervals and outside-calendar busy blocks, then uses the existing
`availability_engine.compute_slots`. The fresh business/owner check precedes the
server-owned busy-block read; other tables retain the caller's current context.
Each fitting proposal consumes provisional capacity when checking later proposals.
No appointment is created, held, changed, or sent to a customer.

Example tool arguments:

```json
{
  "appointments": [
    {
      "offering_id": "22222222-2222-4222-8222-222222222222",
      "start": "2030-01-07T09:00:00-05:00"
    },
    {
      "offering_id": "22222222-2222-4222-8222-222222222222",
      "start": "2030-01-07T09:30:00-05:00"
    }
  ]
}
```

The result contains per-proposal `fits`/`conflict` findings, at most two same-day
alternatives per conflict, effective timezone, checked-at time, capability version,
and separate SHA-256 fingerprints for scheduling rules, service durations, and
existing booking intervals, and outside-calendar blocks. Relevant changes alter the corresponding fingerprint;
row ordering and unrelated business settings do not.

Fingerprints are dependency identifiers, not signatures, authorization, or proof
of a transactionally consistent snapshot. They are not persisted or used for cache
reuse yet. The checked-at time is separate: time passing can invalidate lead-time
eligibility without any database change. Always execute through the normal booking
handlers and recheck current state. Rehearsals bypass Chief's within-turn read
memoization so rechecking the same plan observes new state.

## Limits and failure semantics

- Checks business hours, overrides, blocks, outside calendars, lead time, slot grid, offering duration,
  and the existing engine's shared-capacity semantics. Does not certify per-staff
  or per-room availability, customer eligibility, deposits, or communication consent.
- Only new appointments. Rescheduling, cancellation, staff/room IDs, and extra input
  fields are rejected rather than ignored.
- Requires configured hours and a resolvable timezone from the existing chain.
  Does not convert missing/malformed rules to the booking widget's open default.
- Reuses the existing strict scheduling validator. Arrival windows defer for a
  window-specific check; malformed capacity or hours cannot silently become free slots.
- Inspects at most 500 active dated bookings, paginating until an empty page. Older
  starts remain included so a long booking cannot be omitted. A future improvement
  can use a verified overlap query or database snapshot function for larger calendars.
- A plan may span at most 31 days. Service and booking durations must be 1-1440 minutes.
- Read failures, incomplete/oversized calendars, malformed records, unavailable
  services, or tenant mismatches return `failed: true, status: needs_review`; they
  never become an empty calendar or a claim that a slot is free.
- Reads are non-atomic. Repeated IDs across pages trigger review, but this does not
  detect every concurrent change. The tool provides a preview, never a reservation.
- The complete read has a six-second deadline. Outside-calendar reads are bounded
  to the proposed date range and at most 500 rows. Missing historical booking
  durations defer; the query uses only the deployed `duration_min_at_booking` column.
- DST-invalid candidate times and durations spanning offset changes are excluded
  conservatively. This does not modify the existing availability engine.
- Alternatives are independent suggestions against the plan at that point, not a
  jointly validated replacement plan. Rehearse chosen alternatives together.

## Verification and evaluation

`__tests__/test_booking_rehearsal.py` exercises combined-plan conflicts, shared
capacity, lead times, overrides, blocked dates, timezone/DST handling, dependency
changes, complete pagination, failed reads, input limits, tenant isolation, and
Chief's actual read-tool dispatch. The capability never calls a model and tests
forbid database writes. Its bounded eight-item output fits the existing 6,000
character tool-result budget.

Before claiming production savings, compare representative tasks using the current
Chief path and this capability. Record correctness, corrections, tool/model calls,
input/output tokens, total completion time, and cost per correctly completed task.
The local tests establish behavior and a reduction in repeated snapshot reads;
they do not establish live model selection, user experience, or dollar savings.

### Expanded test run (2026-10-01)

- 473 tests passed across the capability, booking engine, Chief tool loop,
  action registry, MCP, permissions, token/OAuth handling, and related regressions.
- An independent minute-interval oracle checked 200 seeded random calendars and
  1,600 proposed appointments: no accepted proposal exceeded shared capacity.
  Single-capacity results also matched the oracle exactly.
- Both streaming and non-streaming model/tool exchanges exercised the real Chief
  loop and rehearsal handler with scripted model responses. These verify transport
  and execution, not the model's ability to choose the right tool unprompted.
- Testing found and fixed numeric-string timestamps bypassing the explicit-offset
  requirement, and MCP recording structured rehearsal failures as successful calls.
- Five offline scenarios passed. A 30-run local CPU benchmark checking eight
  proposals against 500 synthetic prior bookings measured median 25.821 ms and
  p95 31.219 ms. This excludes database/network/model latency and is not a Railway
  performance or cost measurement.
- Live evaluation could not run: this workspace had no model API key or Supabase
  credentials configured. No production records were used or changed.

Reproduce the scenario and timing report:

```powershell
.venv-security-audit/Scripts/python.exe scripts/booking_rehearsal_eval.py --out output/booking-rehearsal-eval.json
```

Artifacts: `output/booking-rehearsal-eval.json` and
`output/booking-rehearsal-tests.xml`. Timings vary with local system load.

## Next slices

1. Evaluate whether Chief selects this tool appropriately on real, approved test
   cases. Compare grouped rehearsal with multiple individual lookups.
2. Extend the same explicit input/evidence/completion contract to another existing
   operation, using its authoritative calculation and permission code.
3. Persist versioned capability runs and dependencies through the existing outcome
   infrastructure, after reviewing retention and migration requirements.
4. Use business events to invalidate only affected results. Include time-based
   expiry and permissions; a matching fingerprint alone never grants reuse.
5. Let frontier models propose new procedures and tests. Promote procedures only
   after evaluation; never execute arbitrary generated code in the application.

Hosting a generative model or introducing a learned router is independent of this
foundation and is not part of this first slice.

## Release validation (2026-10-04)

Two focused regression runs passed: 275 checks covering dispatch, permissions,
existing appointment checks and tool registration; 333 covering the updated
capability, actual HTTP credential selection, scheduling, MCP and prompt behavior.
The runs overlap on the original capability cases. All five synthetic scenarios
passed. No new provider, package, database migration or feature flag is required.

Production verification must match Railway's active commit to the merged release,
check `/health/ready`, and inspect both Chief and MCP tool registration. The
deployed offline evaluation can run without model or database calls. Successful
or failed handler executions log `capability=rehearse_booking_plan version=1`
with a result status and no customer or tenant content. That event verifies an
actual handler invocation; an answer alone does not prove tool use. The existing
deterministic appointment route remains available and can answer supported
phrasing without calling this new model-facing tool.
