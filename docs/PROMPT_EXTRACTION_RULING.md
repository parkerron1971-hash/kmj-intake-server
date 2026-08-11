# Do NOT extract the module-spec prompt into skills

**Ruling, 2026-08-11.** `module_spec_generator._SYSTEM_PROMPT` stays at
~17.8KB. The `build_skills/` mechanism (BE #519) is for **adding**
knowledge Chief doesn't have, not for slimming this prompt.

This was investigated properly — an eval harness was built, a clean 36/36
baseline measured against live Sonnet, and the prompt structurally mapped.
The conclusion is that the premise was wrong, not that the work was hard.

## What the prompt is actually made of

| block | size | share |
|---|---|---|
| `ARCHETYPE` — `booking_calendar` detail | ~8,000 ch | 45% |
| `ARCHETYPE` — `work_pipeline` + `event_roster` + `fallback_generic` | ~3,000 ch | 17% |
| `VERTICAL AWARENESS` + `MUST NOT DO` | ~2,470 ch | 14% |
| `DESIGN PRINCIPLES` | 837 ch | 5% |
| `DECOMPOSITION` | 561 ch | 3% |
| `WORKFLOWS` | 522 ch | 3% |
| preamble, `PUBLIC_DISPLAY`, envelope rules | ~2,400 ch | 13% |

## Why it can't move

**The model picks its archetype and fills that archetype's params in ONE
call.** Skill selection is keyword-based and runs *before* generation, so
the detail has to be present before we know which archetype it will
choose. There is no point in the flow where "it chose booking_calendar,
now load the booking_calendar rules" can happen.

That is fatal for the biggest block. `_ARCHETYPE_PARAM_MODELS`:

```
booking_calendar   required params: ['primary_date_field']
fallback_generic   required params: None
work_pipeline      required params: None
event_roster       required params: None
```

If the booking keywords miss and the model still picks `booking_calendar`
— which it will, because "when to pick" has to stay in the palette
regardless — it emits no `primary_date_field`, Pydantic rejects the whole
`ProposalEnvelope`, and **Chief builds nothing**.

That is not hypothetical. It is exactly the failure #525 fixed: the
skills told the model to emit triggers without stating their shape, it
guessed the keys, and the entire proposal was rejected. Extraction would
reintroduce that class deliberately, at 45% of the prompt.

**The other 31% is universal.** `DESIGN PRINCIPLES`, `DECOMPOSITION`,
`WORKFLOWS`, `VERTICAL AWARENESS` apply to every build. There is no
condition under which a build doesn't need them, so there is no selector
that could gate them.

**What's left is ~3,000 ch (17%)** — the three archetypes whose params are
all optional, where a missed selection degrades gracefully instead of
failing. That's the only safe extraction available, and it is not worth a
paid eval round and a new failure surface to save 17% of one prompt.

## What would change this

A **two-pass generation**: call once to choose the archetype, then again
with only that archetype's detail loaded. That makes selection a fact
rather than a guess, and unlocks the full 62%.

It also doubles the model calls per proposal. Worth costing against
`chat_price` before anyone builds it — the prompt being large is not
currently causing a problem, and "the file is big" is not a bug.

## What the investigation did produce

Not nothing — the harness that answered this found four real defects on
its first three runs:

1. **BE #525** — skills asked for triggers without stating the shape;
   the model emitted `{"event": ...}` and Chief built **nothing**. A
   regression #519 had shipped, live, undetected by any test.
2. **BE #526** — Chief only produced triggers when a skill asked, because
   both reference examples showed `"triggers": []`. `equipment` lost its
   overdue trigger to this.
3. **BE #526** — the `feedback` case pulled `booking-module`, because
   `"rating"` is not a substring of `"rated"`. It scored 6/6 while holding
   the wrong playbook — a hole in the instrument, not just the skill.
4. **BE #527** — the `vague` case asserted a refusal rule that lives in
   the frontend AI tab, not this path. It scored a *rising* number for
   *worse-looking* behaviour, and both readings were meaningless.

`scripts/module_build_eval.py` stays. It is now the thing to run before
any change to the generator, its prompt, or the skills.

## Standing baseline

**36/36**, measured 2026-08-11 against `main` at `420dd3d`:

| case | score | skill | notable |
|---|---|---|---|
| booking | 9/9 | booking-module | `offering_ref`, `overdue` + `new_entry` |
| pipeline | 7/7 | pipeline-module | `currency`, board, `last_moved` |
| feedback | 7/7 | feedback-module | `rating` |
| equipment | 8/8 | *(none)* | `overdue` with no skill — the #526 fix |
| vague | 5/5 | *(none)* | built `Tasks`, reported `confidence: low` |

Temperature is 0.4, so re-running the same code will not reproduce this
exactly. Compare per-case, and treat a one-point move as noise.
