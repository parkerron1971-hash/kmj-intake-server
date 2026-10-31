# Prototype results — October 12, 2026

**Paid inference/API charges: $0. Added Railway hosting: $0.**
Training and testing ran on the existing Windows computer. No external model,
dataset download, customer record, or production endpoint was used.

## Decisions on 60 test messages excluded from training and selection

| Metric | Trained model + checks | Keyword rules + same checks |
|---|---:|---:|
| Handled locally | 20 / 60 | 30 / 60 |
| Incorrect local decisions | 0 / 20 | 4 / 30 |
| Handed off | 40 / 60 | 30 / 60 |
| Correct route and local intent | 49 / 60 (81.7%) | 51 / 60 (85.0%) |

The model handled fewer cases locally and made fewer local mistakes on this
small set. Its 11 remaining errors were unnecessary handoffs of straightforward
requests. It does **not** beat the rules baseline on overall routing accuracy.
These results suggest a possible precision/coverage tradeoff worth testing, not
proof of a production advantage or a reliable 33% cost saving.

Training used 120 fictional examples. Smoothing and policy were selected on
30 separate validation examples (10 local decisions, all correct there).
Model and test hashes are recorded in the JSON reports. No tuning used the test
results. All splits have the same author and domain; this is a development
benchmark, not independent evidence of customer accuracy. Zero errors in only
20 accepted examples is a small sample, not a guarantee of error-free operation.

## Performance on this computer

Windows 11, Python 3.13.5, 22 logical CPUs reported by the OS. One process, no
GPU. The direct decision loop is serial.

| Measurement | Result |
|---|---:|
| Trained artifact | 73,155 bytes |
| Whole Python process after warmup | 37.6 MiB resident |
| Peak process memory including HTTP load generator | 41.8 MiB |
| Direct decisions measured | 10,000 |
| Direct decision latency, median / 95th percentile | 0.027 / 0.090 ms |
| Direct CPU time per decision | 0.044 ms |
| Local HTTP requests | 1,500, zero errors |
| HTTP, 10 concurrent requests | about 1,004 requests/sec; p95 11.5 ms |
| HTTP, 25 concurrent requests | about 981 requests/sec; p95 27.2 ms |

The HTTP test ran 500 requests at each concurrency level of 1, 10 and 25.
This was a short burst against a local demo server. The client and server
shared the same process; no real database, internet latency, authentication,
frontier response, or production workload was included. It establishes neither
Railway throughput nor a supported number of customers.

## What this says about the earlier cost estimate

The model itself is small enough to make a low-cost CPU deployment plausible.
The earlier $6-$10/month for 500 light users remains a **planning budget**, not
a measured Railway quote. Runtime overhead, other services, storage, traffic,
replicas, and frontier-model calls still determine the bill. Accuracy on real
work is the more important unanswered question at this stage.

## Functional checks

20 tests passed: learned weights, artifact provenance, read-only behavior,
no networking from inference, all three routes, supplied-fact replies,
missing/stale facts, tenant mismatches, ambiguous messages, invalid input,
HTTP round trips, request size/host/origin restrictions, and concurrent requests.

Raw evidence:

- [Training and validation report](artifacts/training-report.json)
- [Every held-out prediction, including errors and baseline](artifacts/evaluation-report.json)
- [Timing, memory and HTTP load report](artifacts/benchmark-report.json)
