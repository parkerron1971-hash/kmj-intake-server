# Business decision prototype

A small trained model that recommends **routine reply**, **ask for information**,
or **frontier-model handoff**. Runs locally with Python 3.10+ and the standard
library. No package installation, GPU, API key, database, or cloud service needed.

This is an experiment for Kevin's business AI add-on, not a production Chief
integration. All examples and business facts are fictional. Nothing is sent,
booked, cancelled, charged, or passed to a paid model. `frontier` is a returned
decision, not an external API call. The existing app and Railway configuration
are unchanged.

## Try it

From the repository root:

```powershell
python -m prototypes.business_decision demo
python -m prototypes.business_decision predict --message "Can I move my appointment to Friday?"
python -m prototypes.business_decision predict --message "What are your opening hours?"
python -m prototypes.business_decision predict --message "Cancel my visit but refund the deposit too"
```

The first message produces:

```json
{
  "route": "ask",
  "intent": "reschedule",
  "reply": "Available options: Friday 10am; Friday 2pm. Which works for you?",
  "reason": "slot_selection_required",
  "read_only": true,
  "paid_calls": 0
}
```

Full output also includes the model's uncalibrated scores. A score of 0.99 does
**not** mean a 99% chance of being right.

## Local HTTP demo

```powershell
python -m prototypes.business_decision serve
```

In another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8766/decide -Method Post -ContentType application/json -Body '{"message":"What are your opening hours?"}'
```

`GET /health` reports readiness. The server binds only to 127.0.0.1, rejects
cross-origin/browser requests and unknown demo businesses, and keeps its fictional
facts on the server. It is a bounded development demo, not an internet-facing
server. Stop with Ctrl+C.

## What is learned, and what is ordinary code?

- `model.py`: supervised multinomial Naive Bayes. Training learns vocabulary,
  per-intent word/bigram weights and class priors from 120 labeled examples.
  Saved as inspectable JSON, about 73 KB; no executable model serialization.
- `engine.py`: checks the model score, ambiguity, unfamiliar words, business
  context, freshness, and required information. Templates use supplied facts.
- `corpus.py`: 120 training, 30 validation, and 60 separately authored test
  messages. Smoothing and routing thresholds are selected on validation only.
  The test set is fingerprinted before training and not used in selection.
- `artifacts/model.json`: trained weights and selected policy, not a prompt to
  another AI. The rules-only baseline does not use these weights.

The model recognizes five appointment-business intents plus a complex category.
It does not extract dates, authenticate customers, authorize actions, read a live
calendar, remember conversations, or learn automatically from customer traffic.
For a real adapter, the calling app must provide authenticated, tenant-scoped,
current facts and availability already filtered to the requested date/service.

## Measured results, October 12, 2026

See [RESULTS.md](RESULTS.md) for results and limits, and `artifacts/` for raw
training, evaluation, and benchmark reports, including every test prediction.

```powershell
python -m unittest prototypes.business_decision.test_prototype -v
python -m prototypes.business_decision train --out prototypes/business_decision/artifacts/training-report.json
python -m prototypes.business_decision evaluate --out prototypes/business_decision/artifacts/evaluation-report.json
python -m prototypes.business_decision benchmark --out prototypes/business_decision/artifacts/benchmark-report.json
```

Training overwrites the local artifact. Evaluation never updates weights or
thresholds. Benchmarks make bounded loopback HTTP requests only; no paid provider
is contacted. Reports include all failures rather than filtering to successes.

## Before a production decision

Use an independently labeled, permissioned evaluation set representative of the
actual business workflow; the current dataset is small, English-only, fictional,
and authored by the same assistant across all splits. Compare with an improved
rules baseline at the same error tolerance. Assess model scores on that dataset
before treating any as calibrated confidence. Keep permissions and writes in
the existing application; routing confidence never grants authority.

The current privacy policy says business/customer data is not used for training.
This prototype trains exclusively on fictional examples. Adding real data is a
separate product and data-governance decision, not an automatic next step.

For Railway, a future authenticated internal service could share one loaded
model across web and worker. Measure it there before relying on a user-count or
monthly-cost promise. This task creates no Railway service or recurring bill.

Technical reference: [Naive Bayes, including score limitations](https://scikit-learn.org/stable/modules/naive_bayes.html).
