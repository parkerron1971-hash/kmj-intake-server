-- cost_reality_check.sql — what a Chief TURN actually costs, post-2026-08-10.
--
-- WHY THIS EXISTS
-- ---------------
-- pricing_config.MEASURED_CHAT_COST_CENTS = 7.37 was sampled from 640 rows
-- over 2026-07-23..08-10. Two things happened on or after the last day of
-- that window that make the number unsafe to price against:
--
--   1. #485 (2026-08-10) gave the prompt cache a 1-hour TTL. Every turn in
--      the sample predates it, and 627 of the 640 read or wrote ZERO cached
--      tokens. Post-fix cost should be materially LOWER.
--   2. The mid-turn tool loop shipped 2026-08-14 (MAX_TOOL_ROUNDS = 4) and
--      show_plan / show_readout on 2026-08-18. A turn that used to make one
--      model call can now make up to SIX, each carrying the ~34k-token
--      prefix. Post-change cost should be materially HIGHER.
--
-- The two push in opposite directions, so the net is not guessable. Run this.
--
-- THE ROW-VS-TURN TRAP
-- --------------------
-- api_usage has no turn/trace id. _call_claude logs one row per MODEL CALL
-- (chief_of_staff.py:904, 958, 972, 1083, 1127), and the post-action honesty
-- pass calls _call_claude again under the SAME endpoint. So a naive
-- avg(cost_cents) over /chief/backend is a PER-CALL mean, not a per-turn one,
-- and understates a turn by however many calls it made.
--
-- Q2 below sessionizes rows into turns with a 30-second gap rule. That is an
-- approximation, and it is the honest one available: rounds inside a turn are
-- seconds apart, and a practitioner's next message is not.
--
-- USAGE
--   Run in the Supabase SQL editor. Read-only — no writes, no DDL.
--   Every query is bounded to >= 2026-08-10 on purpose (see margin.py: rows
--   before 2026-08-09 undercount, because 23 modules were not yet metering).

\set since '2026-08-10'


-- ═══════════════════════════════════════════════════════════════════════
-- Q1. THE HEADLINE — per-CALL cost by endpoint. This is the shape of the
--     number that produced 7.37c. Keep it only to compare against Q2.
-- ═══════════════════════════════════════════════════════════════════════
SELECT
    endpoint,
    model,
    count(*)                                                   AS calls,
    round(avg(cost_cents)::numeric, 3)                         AS mean_c,
    round((percentile_cont(0.5)  WITHIN GROUP (ORDER BY cost_cents))::numeric, 3) AS p50_c,
    round((percentile_cont(0.95) WITHIN GROUP (ORDER BY cost_cents))::numeric, 3) AS p95_c,
    round(max(cost_cents)::numeric, 3)                         AS max_c,
    round(sum(cost_cents)::numeric / 100, 2)                   AS total_usd
FROM api_usage
WHERE created_at >= :'since'
  AND ok
GROUP BY endpoint, model
ORDER BY sum(cost_cents) DESC;


-- ═══════════════════════════════════════════════════════════════════════
-- Q2. THE NUMBER THAT SHOULD REPLACE 7.37 — per-TURN cost.
--     Rows for one business within 30s of each other are one turn.
-- ═══════════════════════════════════════════════════════════════════════
WITH chat_rows AS (
    SELECT business_id, created_at, cost_cents, model,
           input_tokens, output_tokens,
           cache_read_tokens, cache_creation_tokens
    FROM api_usage
    WHERE created_at >= :'since'
      AND ok
      AND business_id IS NOT NULL
      AND endpoint IN ('/chief/backend', '/chief/backend-fallback',
                       '/chief/draft', '/chief/action-reasoner',
                       '/chief/analyze-hard', '/chief/ask-transaction')
), gapped AS (
    SELECT *,
           CASE WHEN created_at - lag(created_at) OVER w > interval '30 seconds'
                 OR lag(created_at) OVER w IS NULL
                THEN 1 ELSE 0 END AS is_new_turn
    FROM chat_rows
    WINDOW w AS (PARTITION BY business_id ORDER BY created_at)
), turns AS (
    SELECT business_id,
           sum(is_new_turn) OVER (PARTITION BY business_id ORDER BY created_at
                                  ROWS UNBOUNDED PRECEDING) AS turn_no,
           cost_cents, cache_read_tokens, cache_creation_tokens
    FROM gapped
), per_turn AS (
    SELECT business_id, turn_no,
           count(*)                    AS calls_in_turn,
           sum(cost_cents)             AS turn_cents,
           sum(cache_read_tokens)      AS cache_read,
           sum(cache_creation_tokens)  AS cache_write
    FROM turns
    GROUP BY business_id, turn_no
)
SELECT
    count(*)                                                   AS turns,
    round(avg(calls_in_turn)::numeric, 2)                      AS avg_calls_per_turn,
    max(calls_in_turn)                                         AS max_calls_in_one_turn,
    round(avg(turn_cents)::numeric, 3)                         AS mean_c,   -- <<< replaces 7.37
    round((percentile_cont(0.5)  WITHIN GROUP (ORDER BY turn_cents))::numeric, 3) AS p50_c,
    round((percentile_cont(0.95) WITHIN GROUP (ORDER BY turn_cents))::numeric, 3) AS p95_c,
    round((percentile_cont(0.99) WITHIN GROUP (ORDER BY turn_cents))::numeric, 3) AS p99_c,
    round(max(turn_cents)::numeric, 3)                         AS max_c,
    round(100.0 * count(*) FILTER (WHERE cache_read > 0) / nullif(count(*), 0), 1)
                                                               AS pct_turns_hitting_cache
FROM per_turn;


-- ═══════════════════════════════════════════════════════════════════════
-- Q3. DID #485 ACTUALLY WORK? Cache hit rate by prompt_shape.
--     _call_claude writes prompt_shape into task_type precisely so this is
--     a SELECT and not archaeology. Expect 'cached-3seg-1h' to dominate.
--     Any shape with pct_cached near zero is a live cache bug.
-- ═══════════════════════════════════════════════════════════════════════
SELECT
    coalesce(task_type, '(none)')                              AS prompt_shape,
    count(*)                                                   AS calls,
    round(100.0 * count(*) FILTER (WHERE cache_read_tokens > 0)
          / nullif(count(*), 0), 1)                            AS pct_calls_read_cache,
    round(avg(cache_read_tokens)::numeric, 0)                  AS avg_cache_read_tok,
    round(avg(cache_creation_tokens)::numeric, 0)              AS avg_cache_write_tok,
    round(avg(input_tokens)::numeric, 0)                       AS avg_uncached_in_tok,
    round(avg(cost_cents)::numeric, 3)                         AS mean_c,
    round(sum(cost_cents)::numeric / 100, 2)                   AS total_usd
FROM api_usage
WHERE created_at >= :'since'
  AND ok
  AND endpoint LIKE '/chief/%'
GROUP BY 1
ORDER BY sum(cost_cents) DESC;


-- ═══════════════════════════════════════════════════════════════════════
-- Q4. THE RESERVE NUMBER — per-business monthly COGS, by tier.
--     This is what sizes the cap. p95 is the reserve to hold; max is the
--     number the ceiling has to survive.
-- ═══════════════════════════════════════════════════════════════════════
WITH plan_of AS (
    SELECT id AS business_id,
           CASE
             WHEN lower(coalesce(comp_tier, '')) IN ('starter','professional','practice')
                  THEN lower(comp_tier)
             WHEN subscription_status IN ('trialing','active')
                  THEN lower(coalesce(subscription_plan, 'unknown'))
             ELSE 'none'
           END AS plan
    FROM businesses
), monthly AS (
    SELECT u.business_id,
           date_trunc('month', u.created_at) AS month,
           sum(u.cost_cents)                 AS cents
    FROM api_usage u
    WHERE u.created_at >= :'since' AND u.ok AND u.business_id IS NOT NULL
    GROUP BY 1, 2
)
SELECT
    coalesce(p.plan, 'unattributed')                           AS plan,
    count(*)                                                   AS business_months,
    round(avg(m.cents)::numeric / 100, 2)                      AS mean_usd,
    round((percentile_cont(0.5)  WITHIN GROUP (ORDER BY m.cents))::numeric / 100, 2) AS p50_usd,
    round((percentile_cont(0.95) WITHIN GROUP (ORDER BY m.cents))::numeric / 100, 2) AS p95_usd,  -- <<< the reserve
    round(max(m.cents)::numeric / 100, 2)                      AS max_usd
FROM monthly m
LEFT JOIN plan_of p USING (business_id)
GROUP BY 1
ORDER BY 1;


-- ═══════════════════════════════════════════════════════════════════════
-- Q5. WHAT THE DAILY CAP SHOULD BE — the busiest real day per business.
--     DAILY_SPEND_CAP_PER_BUSINESS_USD is 25 today. If p99 here is 3, the
--     cap is 8x looser than anything real, and 30 x 25 = $750/mo is the
--     exposure that buys nothing.
-- ═══════════════════════════════════════════════════════════════════════
WITH daily AS (
    SELECT business_id, date_trunc('day', created_at) AS d,
           sum(cost_cents) AS cents
    FROM api_usage
    WHERE created_at >= :'since' AND ok AND business_id IS NOT NULL
    GROUP BY 1, 2
)
SELECT
    count(*)                                                   AS business_days,
    round(avg(cents)::numeric / 100, 3)                        AS mean_usd,
    round((percentile_cont(0.95) WITHIN GROUP (ORDER BY cents))::numeric / 100, 3) AS p95_usd,
    round((percentile_cont(0.99) WITHIN GROUP (ORDER BY cents))::numeric / 100, 3) AS p99_usd,
    round(max(cents)::numeric / 100, 3)                        AS max_usd,
    count(*) FILTER (WHERE cents >= 2500)                       AS days_that_hit_the_25_cap
FROM daily;


-- ═══════════════════════════════════════════════════════════════════════
-- Q6. THE UNBILLED SURFACE — cost carrying units = 0 or no units at all.
--     /ai/tts and /ai/whisper are priced 0 in pricing_config.unit_weights();
--     at volume they are real money the credit tank does not cover.
-- ═══════════════════════════════════════════════════════════════════════
SELECT
    endpoint,
    count(*)                                                   AS calls,
    round(sum(cost_cents)::numeric / 100, 2)                   AS total_usd,
    round(100.0 * sum(cost_cents)
          / nullif(sum(sum(cost_cents)) OVER (), 0), 1)        AS pct_of_all_cogs
FROM api_usage
WHERE created_at >= :'since'
  AND ok
  AND coalesce(units, 0) = 0
GROUP BY endpoint
ORDER BY sum(cost_cents) DESC;
