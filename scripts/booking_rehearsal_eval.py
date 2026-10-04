"""Offline scheduling scenarios and CPU timing; no model or database requests.

Run: python scripts/booking_rehearsal_eval.py --out output/booking-rehearsal-eval.json
This measures local computation only, not hosted latency, AI quality or dollar savings.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from booking_rehearsal import BookingPlan, rehearse

BID = "11111111-1111-4111-8111-111111111111"
OID = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2030, 1, 7, 12, tzinfo=timezone.utc)
HOURS = {"timezone": "America/New_York", "weekly": {
    "mon": [{"start": "09:00", "end": "17:00"}]}, "slot_granularity_min": 30}
SERVICE = {"id": OID, "business_id": BID, "is_active": True, "duration_min": 60}


def run_plan(starts, *, availability=None, bookings=None):
    return rehearse(BookingPlan(appointments=[{"offering_id": OID, "start": s} for s in starts]),
                    business_id=BID, availability=availability or HOURS,
                    practitioner_tz=None, offerings=[SERVICE], bookings=bookings or [], now=NOW)


def evaluate():
    scenarios = [
        ("three_appointments_one_overlap", ["2030-01-07T09:00:00-05:00", "2030-01-07T09:30:00-05:00", "2030-01-07T10:00:00-05:00"],
         {}, ["fits", "conflict", "fits"]),
        ("two_chairs_three_simultaneous", ["2030-01-07T09:00:00-05:00"] * 3,
         {"availability": {**HOURS, "concurrent_capacity": 2}}, ["fits", "fits", "conflict"]),
        ("closed_day", ["2030-01-08T09:00:00-05:00"], {}, ["conflict"]),
        ("holiday_block", ["2030-01-07T09:00:00-05:00"],
         {"availability": {**HOURS, "blocks": [{"start": "2030-01-07", "end": "2030-01-07"}]}}, ["conflict"]),
        ("after_hours", ["2030-01-07T16:30:00-05:00"], {}, ["conflict"]),
    ]
    results = []
    for name, starts, options, expected in scenarios:
        result = run_plan(starts, **options)
        actual = [a["status"] for a in result["appointments"]]
        results.append({"name": name, "passed": actual == expected, "expected": expected,
                        "actual": actual, "evidence": result})

    starts = [(NOW.replace(hour=14) + timedelta(hours=i)).isoformat() for i in range(8)]
    # All 500 prior intervals are inspected. This deliberately exercises scans
    # without early conflict exits. It is a synthetic CPU load, not tenant data.
    bookings = [{"id": str(i), "business_id": BID, "status": "active",
                 "appointment_at": (NOW - timedelta(days=i + 1)).isoformat(),
                 "duration_min_at_booking": 60} for i in range(500)]
    run_plan(starts, bookings=bookings)  # warm imports/timezone caches
    timings = []
    for _ in range(30):
        start = perf_counter()
        result = run_plan(starts, bookings=bookings)
        timings.append((perf_counter() - start) * 1000)
        if any(a["status"] != "fits" for a in result["appointments"]):
            raise AssertionError("Non-overlapping benchmark appointments must fit")
    return {
        "mode": "offline_synthetic",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": all(r["passed"] for r in results),
        "scenarios": results,
        "cpu_benchmark": {"runs": len(timings), "existing_bookings": 500,
                          "proposals_per_run": 8, "median_ms": round(statistics.median(timings), 3),
                          "p95_ms": round(sorted(timings)[28], 3),
                          "max_ms": round(max(timings), 3)},
        "external_calls": {"model": 0, "database": 0},
        "limitations": "Local CPU only. Synthetic records. Does not measure live model tool selection, production database access, network latency or dollar savings.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = evaluate()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"mode": report["mode"], "passed": report["passed"],
                      "scenarios": len(report["scenarios"]), "cpu_benchmark": report["cpu_benchmark"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
