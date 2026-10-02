from copy import deepcopy

import pytest

from program_outcomes import calculate


def definition(**overrides):
    return {'title': 'Program outcomes', 'cohort': 'Fall',
            'baseline_start': '2026-09-01', 'baseline_end': '2026-09-07',
            'followup_start': '2026-10-01', 'followup_end': '2026-10-14',
            'metrics': [{'key': 'credit', 'label': 'Credit score', 'target': '680'}], **overrides}


def person(subject='one', **overrides):
    return {'subject_id': subject, 'source_id': 'enrollment-' + subject,
            'cohort': 'Fall', 'status': 'active', **overrides}


def reading(source, value, day, subject='one', metric='credit'):
    return {'source_id': source, 'subject_id': subject, 'metric': metric,
            'observed_on': day, 'value': value}


def test_pairs_same_people_and_exposes_missing_measurements():
    report = calculate(definition(), [person(), person('two'), person('three')], [
        reading('a', 600, '2026-09-01'), reading('b', 650, '2026-10-01'),
        reading('c', 700, '2026-09-02', 'two'), reading('d', 750, '2026-10-02', 'three')])
    metric = report['metrics'][0]
    assert metric['paired_count'] == 1
    assert metric['included_count'] == 3
    assert metric['missing_baseline_count'] == metric['missing_followup_count'] == 1
    assert metric['mean_change_paired'] == '50.00'
    assert metric['mean_baseline_paired'] == '600.00'
    assert metric['mean_followup_paired'] == '650.00'


def test_baseline_is_never_reused_as_followup():
    metric = calculate(definition(), [person()], [reading('a', 700, '2026-09-01')])['metrics'][0]
    assert metric['paired_count'] == 0
    assert metric['mean_change_paired'] is None
    assert metric['followup_reached_count'] == 0
    assert metric['participants'][0]['followup'] is None


def test_first_baseline_and_last_followup_within_windows_only():
    data = [reading('pre', 400, '2026-08-31'), reading('a', 600, '2026-09-01'),
            reading('b', 620, '2026-09-03'), reading('mid', 640, '2026-09-20'),
            reading('c', 650, '2026-10-01'), reading('d', 680, '2026-10-14'),
            reading('future', 800, '2026-10-15')]
    metric = calculate(definition(), [person()], data)['metrics'][0]
    assert metric['mean_change_paired'] == '80.00'
    assert metric['newly_reached_count'] == 1
    assert metric['participants'][0]['baseline']['source_id'] == 'a'
    assert metric['participants'][0]['followup']['source_id'] == 'd'


def test_debt_uses_decimal_balances_and_downward_improvement():
    d = definition(metrics=[{'key': 'debt', 'label': 'Debt balance', 'direction': 'down', 'unit': 'USD'}])
    metric = calculate(d, [person()], [reading('a', '10000.10', '2026-09-01', metric='debt'),
                                     reading('b', '9750.05', '2026-10-01', metric='debt')])['metrics'][0]
    assert metric['mean_change_paired'] == '-250.05'
    assert metric['mean_improvement_paired'] == '250.05'
    assert metric['followup_reached_count'] is None


def test_milestone_uses_organization_defined_values():
    d = definition(metrics=[{'key': 'readiness', 'label': 'Program readiness', 'kind': 'milestone',
                            'reached_values': ['counselor_review_complete']}])
    metric = calculate(d, [person()], [reading('a', 'in_progress', '2026-09-01', metric='readiness'),
        reading('b', 'counselor_review_complete', '2026-10-01', metric='readiness')])['metrics'][0]
    assert metric['newly_reached_count'] == 1
    assert metric['mean_change_paired'] is None


def test_withdrawals_remain_in_population_unless_explicitly_excluded():
    people = [person(), person('two', status='withdrawn'), person('other', cohort='Spring')]
    included = calculate(definition(), people, [])
    excluded = calculate(definition(included_statuses=['active']), people, [])
    assert included['cohort_count'] == included['included_count'] == 2
    assert excluded['cohort_count'] == 2
    assert excluded['included_count'] == excluded['excluded_count'] == 1
    assert excluded['excluded_status_counts'] == {'withdrawn': 1}


@pytest.mark.parametrize('value', [True, 'NaN', 'Infinity', '-Infinity', 'not measured', '1e100'])
def test_invalid_numeric_readings_are_not_silently_coerced(value):
    with pytest.raises(ValueError):
        calculate(definition(), [person()], [reading('bad', value, '2026-09-01')])


def test_conflicting_same_day_values_require_correction():
    with pytest.raises(ValueError, match='Conflicting observations'):
        calculate(definition(), [person()], [reading('a', 600, '2026-09-01'), reading('b', 650, '2026-09-01')])


def test_source_reference_cannot_identify_two_different_values():
    with pytest.raises(ValueError, match='source reference'):
        calculate(definition(), [person()], [reading('a', 600, '2026-09-01'), reading('a', 650, '2026-10-01')])


def test_duplicate_cohort_enrollment_is_rejected():
    with pytest.raises(ValueError, match='more than once'):
        calculate(definition(), [person(), person(source_id='second-enrollment')], [])


@pytest.mark.parametrize('overrides', [{'baseline_end': '2026-10-01'}, {'followup_end': '2026-09-01'}])
def test_invalid_and_overlapping_windows_are_rejected(overrides):
    with pytest.raises(ValueError):
        calculate(definition(**overrides), [person()], [])


def test_hash_stable_across_order_and_changes_when_reported_data_changes():
    data = [reading('a', 600, '2026-09-01'), reading('b', 680, '2026-10-01')]
    first = calculate(definition(), [person(), person('two')], data)
    reordered = calculate(definition(), [person('two'), person()], list(reversed(data)))
    changed_data = deepcopy(data)
    changed_data[1]['value'] = 690
    changed = calculate(definition(), [person(), person('two')], changed_data)
    assert first == reordered
    assert first['content_hash'] != changed['content_hash']
    assert data[1]['value'] == 680


def test_empty_cohort_is_explicit_and_not_zero_improvement():
    report = calculate(definition(), [], [])
    assert report['included_count'] == 0
    assert report['metrics'][0]['mean_change_paired'] is None
