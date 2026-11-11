"""Reproducible validation selection and honest held-out synthetic evaluation."""
from __future__ import annotations

from collections import Counter
from itertools import product
import json
from pathlib import Path
import re

from .corpus import TEST, VALIDATION, context_for, training_rows
from .engine import Engine, Policy
from .model import Model, fingerprint


class RuleBaseline:
    """Transparent keyword baseline, using the same context checks/templates."""
    patterns = {
        "hours": r"\b(hours|open|opening|close|closing)\b",
        "pricing": r"\b(price|prices|pricing|cost|costs|rates|charge|fees)\b|how much",
        "booking": r"\b(book|reserve|schedule|reservation)\b",
        "reschedule": r"\b(reschedule|move|shift|postpone|rearrange|switch|change)\b",
        "cancel": r"\b(cancel|canceled|cancelled|remove)\b|call off|no longer need",
    }

    def predict(self, text):
        matched = [label for label, pattern in self.patterns.items() if re.search(pattern, text, re.I)]
        intent = matched[0] if len(matched) == 1 else "complex"
        return {"intent": intent, "score": 1.0, "margin": 1.0, "known_word_fraction": 1.0,
                "scores": {intent: 1.0}, "score_is_calibrated": False}


def measure(engine, rows):
    outputs, failures, local, correct_local, correct = [], [], 0, 0, 0
    routes = Counter()
    for row in rows:
        out = engine.decide(row["text"], business_id="demo-salon", context=context_for(row["context"]))
        is_local = out["route"] != "frontier"
        ok = (out["route"] == row["route"] and (not is_local or out["intent"] == row["intent"]))
        local += is_local
        correct_local += is_local and ok
        correct += ok
        routes[out["route"]] += 1
        result = {"text": row["text"], "context": row["context"],
                  "expected_route": row["route"], "expected_intent": row["intent"],
                  "route": out["route"], "intent": out["intent"], "reason": out["reason"],
                  "correct": ok, "score": round(out["model"]["score"], 5)}
        outputs.append(result)
        if not ok:
            failures.append(result)
    return {"examples": len(rows), "correct_decisions": correct,
            "decision_accuracy": correct / len(rows), "local_decisions": local,
            "correct_local_decisions": correct_local,
            "incorrect_local_decisions": local - correct_local,
            "local_precision": correct_local / local if local else None,
            "local_coverage": local / len(rows), "routes": dict(routes),
            "failures": failures, "results": outputs}


def assert_separate_splits():
    split_texts = [{" ".join(row["text"].casefold().split()) for row in rows}
                   for rows in (training_rows(), VALIDATION, TEST)]
    for a, b in ((0, 1), (0, 2), (1, 2)):
        if split_texts[a] & split_texts[b]:
            raise ValueError("Duplicate utterance across dataset splits")


def train_and_select(output: Path) -> dict:
    assert_separate_splits()
    candidates = []
    for alpha in (0.05, 0.2, 1.0):
        model = Model.train(training_rows(), alpha=alpha)
        for score, margin, coverage in product((0.60, 0.75, 0.85, 0.90, 0.95, 0.99),
                                             (0.20, 0.40, 0.60), (0.40, 0.55, 0.70, 0.85)):
            policy = Policy(score, margin, coverage)
            stats = measure(Engine(model, policy), VALIDATION)
            # Accuracy of accepted local decisions takes priority over coverage.
            # This selects a threshold, it does NOT calibrate the score.
            rank = (-stats["incorrect_local_decisions"], stats["correct_local_decisions"],
                    score, margin, coverage)
            candidates.append((rank, model, policy, stats))
    _, model, policy, stats = max(candidates, key=lambda item: item[0])
    model.artifact["policy"] = Engine(model, policy).settings()
    model.artifact["validation_sha256"] = fingerprint(VALIDATION)
    model.artifact["frozen_test_sha256"] = fingerprint(TEST)
    model.save(output)
    return {"training_examples": len(training_rows()), "validation_examples": len(VALIDATION),
            "alpha": model.artifact["alpha"], "policy": model.artifact["policy"], "validation": stats,
            "artifact_bytes": output.stat().st_size, "paid_calls": 0}


def load_engine(path: Path) -> Engine:
    model = Model.load(path)
    return Engine(model, Policy(**model.artifact["policy"]))


def run_evaluation(path: Path) -> dict:
    assert_separate_splits()
    engine = load_engine(path)
    if engine.model.artifact.get("frozen_test_sha256") != fingerprint(TEST):
        raise ValueError("Test set changed after model selection; retraining is explicit")
    return {"dataset": "hand-authored fictional English appointment messages",
            "limitations": ["Same author for all splits; not an independent customer benchmark",
                            "Uncalibrated scores; unknown requests can still be misclassified",
                            "Only recommendations and draft replies; no real business actions",
                            "Local routes are potential avoided calls, not measured production savings"],
            "training_sha256": engine.model.artifact["training_sha256"],
            "test_sha256": fingerprint(TEST), "policy": engine.settings(),
            "model": measure(engine, TEST), "rules_baseline": measure(Engine(RuleBaseline()), TEST),
            "paid_api_calls": 0, "paid_api_cost_usd": 0}


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
