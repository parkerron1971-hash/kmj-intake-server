"""A trainable multinomial Naive Bayes classifier using the standard library.

Scores are uncalibrated classifier scores, NOT probabilities of correctness.
Only training examples contribute to vocabulary, counts and priors.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata

VERSION = 1
STOP = set("a an the i me my we our you your it is are be to for of on at in please can could would do does what when how much have has want need like thanks thank hello hi hey and with this that some am as".split())


def words(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).casefold().replace("\u2019", "'")
    return [w for w in re.findall(r"[a-z]+(?:'[a-z]+)?", text) if w not in STOP]


def features(text: str) -> Counter:
    terms = words(text)
    return Counter(terms + [a + "~" + b for a, b in zip(terms, terms[1:])])


def fingerprint(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


class Model:
    def __init__(self, artifact: dict):
        if artifact.get("version") != VERSION:
            raise ValueError("Unsupported model artifact version")
        self.artifact = artifact
        self.vocabulary = set(artifact["vocabulary"])
        self.labels = sorted(artifact["log_prior"])

    @classmethod
    def train(cls, rows: list[dict], alpha: float = 1.0) -> "Model":
        if not rows or alpha <= 0:
            raise ValueError("Training requires examples and positive smoothing")
        counts: dict[str, Counter] = {}
        documents = Counter()
        for row in rows:
            label = row["intent"]
            counts.setdefault(label, Counter()).update(features(row["text"]))
            documents[label] += 1
        vocabulary = sorted(set().union(*(set(c) for c in counts.values())))
        if len(documents) < 2 or not vocabulary:
            raise ValueError("Need at least two classes and a nonempty vocabulary")
        weights, priors = {}, {}
        for label, count in counts.items():
            denominator = sum(count.values()) + alpha * len(vocabulary)
            weights[label] = {term: math.log((count[term] + alpha) / denominator)
                              for term in vocabulary}
            priors[label] = math.log(documents[label] / len(rows))
        return cls({"version": VERSION, "algorithm": "multinomial_naive_bayes",
                    "training_sha256": fingerprint(rows), "training_examples": len(rows),
                    "class_counts": dict(documents), "alpha": alpha,
                    "vocabulary": vocabulary, "log_prior": priors, "weights": weights})

    def predict(self, text: str) -> dict:
        extracted = features(text)
        known = {term: min(n, 3) for term, n in extracted.items() if term in self.vocabulary}
        logits = {label: self.artifact["log_prior"][label] + sum(
            self.artifact["weights"][label][term] * n for term, n in known.items())
            for label in self.labels}
        peak = max(logits.values())
        exp = {label: math.exp(score - peak) for label, score in logits.items()}
        total = sum(exp.values())
        scores = {label: value / total for label, value in exp.items()}
        ranked = sorted(scores, key=lambda label: (-scores[label], label))
        terms = set(words(text))
        coverage = len(terms & self.vocabulary) / len(terms) if terms else 0.0
        return {"intent": ranked[0], "score": scores[ranked[0]],
                "margin": scores[ranked[0]] - scores[ranked[1]],
                "known_word_fraction": coverage, "scores": scores,
                "score_is_calibrated": False}

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.artifact, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Model":
        return cls(json.loads(path.read_text(encoding="utf-8")))
