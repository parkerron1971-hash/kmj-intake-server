"""Deterministic, provider-independent program outcomes over authorized records.

The caller owns access checks and source loading. This module never fetches data,
calls a model, infers missing measurements, or sends a report outside the system.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Metric(StrictModel):
    key: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    label: str = Field(min_length=1, max_length=120)
    kind: Literal['number', 'milestone'] = 'number'
    direction: Literal['up', 'down'] = 'up'
    unit: str = Field(default='', max_length=30)
    target: Decimal | None = Field(default=None, allow_inf_nan=False)
    reached_values: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def valid_kind(self):
        if self.kind == 'milestone' and (not self.reached_values or self.target is not None):
            raise ValueError('Milestones need explicit reached values and no numeric target.')
        if self.kind == 'number' and self.reached_values:
            raise ValueError('Numeric metrics cannot have milestone values.')
        return self


class Definition(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    cohort: str = Field(min_length=1, max_length=160)
    baseline_start: date
    baseline_end: date
    followup_start: date
    followup_end: date
    metrics: list[Metric] = Field(min_length=1, max_length=12)
    included_statuses: list[str] = Field(default_factory=lambda: ['active', 'completed', 'withdrawn'], min_length=1, max_length=10)

    @model_validator(mode='after')
    def valid_windows(self):
        if not self.baseline_start <= self.baseline_end < self.followup_start <= self.followup_end:
            raise ValueError('Baseline and follow-up windows must be ordered and must not overlap.')
        if len({m.key for m in self.metrics}) != len(self.metrics):
            raise ValueError('Metric keys must be unique.')
        return self


class Participant(StrictModel):
    subject_id: str = Field(min_length=1, max_length=120)
    cohort: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=40)
    source_id: str = Field(min_length=1, max_length=120)


class Observation(StrictModel):
    source_id: str = Field(min_length=1, max_length=120)
    subject_id: str = Field(min_length=1, max_length=120)
    metric: str = Field(min_length=1, max_length=64)
    observed_on: date
    value: str | int | float | Decimal

    @field_validator('value', mode='before')
    @classmethod
    def no_boolean(cls, value):
        if isinstance(value, bool):
            raise ValueError('A boolean is not a measurement.')
        return value


def _number(value):
    if isinstance(value, bool):
        raise ValueError('Boolean values are not numeric measurements.')
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise ValueError('Measurement is not a valid number.') from exc
    if not number.is_finite():
        raise ValueError('Measurements must be finite.')
    if abs(number) > Decimal('1e18'):
        raise ValueError('Measurement is outside the supported numeric range.')
    return number


def _decimal(value):
    if value is None:
        return None
    rounded = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return format(abs(rounded) if rounded == 0 else rounded, 'f')


def _reached(metric, value):
    if value is None:
        return None
    if metric.kind == 'milestone':
        return str(value) in metric.reached_values
    if metric.target is None:
        return None
    return value >= metric.target if metric.direction == 'up' else value <= metric.target


def calculate(definition, participants, observations):
    """Freeze a reproducible result; inputs must already be tenant-authorized.

    First reading in the baseline window and last in the follow-up window are
    used. Conflicting measurements on the same date require correction instead
    of an arbitrary tie-break. Numeric changes are serialized as decimal strings.
    """
    d = Definition.model_validate(definition)
    people = [Participant.model_validate(p) for p in participants]
    if len(people) > 20000 or len(observations) > 200000:
        raise ValueError('Report exceeds the supported source size. Narrow the cohort or period.')
    relevant = [p for p in people if p.cohort == d.cohort]
    if len({p.subject_id for p in relevant}) != len(relevant):
        raise ValueError('A participant appears more than once in this cohort.')
    selected = sorted((p for p in relevant if p.status in d.included_statuses), key=lambda p: p.subject_id)
    subject_ids = {p.subject_id for p in selected}
    metrics = {m.key: m for m in d.metrics}
    groups = {}
    sources = {}
    for raw in observations:
        o = Observation.model_validate(raw)
        if o.subject_id not in subject_ids or o.metric not in metrics:
            continue
        if not (d.baseline_start <= o.observed_on <= d.baseline_end or
                d.followup_start <= o.observed_on <= d.followup_end):
            continue
        metric = metrics[o.metric]
        value = _number(o.value) if metric.kind == 'number' else str(o.value)
        if metric.kind == 'milestone' and not value.strip():
            raise ValueError('A blank milestone is missing data, not a measured status.')
        normalized = {'source_id': o.source_id, 'subject_id': o.subject_id,
                      'metric': o.metric, 'observed_on': o.observed_on.isoformat(), 'value': str(value)}
        if o.source_id in sources and sources[o.source_id] != normalized:
            raise ValueError('A source reference identifies conflicting observations.')
        sources[o.source_id] = normalized
        key = (o.subject_id, o.metric)
        bucket = groups.setdefault(key, {})
        existing = bucket.get(o.observed_on)
        if existing and existing[1] != value:
            raise ValueError('Conflicting observations on the same date must be resolved before reporting.')
        if not existing or o.source_id < existing[0].source_id:
            bucket[o.observed_on] = (o, value)

    reports = []
    for metric in d.metrics:
        rows = []
        changes = []
        baseline_values, followup_values = [], []
        for person in selected:
            series = groups.get((person.subject_id, metric.key), {})
            baseline = sorted(day for day in series if d.baseline_start <= day <= d.baseline_end)
            followup = sorted(day for day in series if d.followup_start <= day <= d.followup_end)
            first = series[baseline[0]] if baseline else None
            last = series[followup[-1]] if followup else None
            paired = first is not None and last is not None
            delta = last[1] - first[1] if paired and metric.kind == 'number' else None
            if delta is not None:
                changes.append(delta)
                baseline_values.append(first[1])
                followup_values.append(last[1])
            row = {'subject_id': person.subject_id, 'enrollment_source_id': person.source_id,
                   'status': person.status, 'paired': paired,
                   'baseline': sources[first[0].source_id] if first else None,
                   'followup': sources[last[0].source_id] if last else None,
                   'change': _decimal(delta),
                   'improvement': _decimal(delta if metric.direction == 'up' else -delta) if delta is not None else None,
                   'baseline_reached': _reached(metric, first[1]) if first else None,
                   'followup_reached': _reached(metric, last[1]) if last else None}
            rows.append(row)
        pairs = [r for r in rows if r['paired']]
        observed_followups = [r for r in rows if r['followup'] is not None]
        total = sum(changes, Decimal(0))
        reports.append({'metric': metric.model_dump(mode='json'), 'participants': rows,
            'included_count': len(selected), 'paired_count': len(pairs),
            'missing_baseline_count': sum(r['baseline'] is None for r in rows),
            'missing_followup_count': len(rows) - len(observed_followups),
            'followup_observed_count': len(observed_followups),
            'followup_reached_count': sum(r['followup_reached'] is True for r in observed_followups) if metric.kind == 'milestone' or metric.target is not None else None,
            'newly_reached_count': sum(r['baseline_reached'] is False and r['followup_reached'] is True for r in pairs) if metric.kind == 'milestone' or metric.target is not None else None,
            'mean_baseline_paired': _decimal(sum(baseline_values, Decimal(0)) / len(changes)) if changes else None,
            'mean_followup_paired': _decimal(sum(followup_values, Decimal(0)) / len(changes)) if changes else None,
            'mean_change_paired': _decimal(total / len(changes)) if changes else None,
            'total_change_paired': _decimal(total) if changes else None,
            'mean_improvement_paired': _decimal((total if metric.direction == 'up' else -total) / len(changes)) if changes else None})
    snapshot = {'schema_version': 1, 'definition': d.model_dump(mode='json'),
                'cohort_count': len(relevant), 'included_count': len(selected),
                'excluded_count': len(relevant) - len(selected),
                'excluded_status_counts': {status: sum(p.status == status for p in relevant)
                    for status in sorted({p.status for p in relevant if p.status not in d.included_statuses})},
                'metrics': reports}
    canonical = json.dumps(snapshot, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return {**snapshot, 'content_hash': hashlib.sha256(canonical.encode()).hexdigest()}
