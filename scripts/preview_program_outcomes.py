"""Render synthetic outcome data for visual QA; never reads production data."""
from pathlib import Path
import sys
import json
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from program_outcomes import calculate
from program_outcomes_pdf import render

definition = {'title': 'Six-week financial empowerment · SYNTHETIC EXAMPLE', 'cohort': 'Fall 2026',
    'baseline_start': '2026-09-07', 'baseline_end': '2026-09-13',
    'followup_start': '2026-10-12', 'followup_end': '2026-10-18',
    'metrics': [{'key': 'credit', 'label': 'Credit score', 'unit': 'points'},
                {'key': 'debt', 'label': 'Debt balance', 'unit': 'USD', 'direction': 'down'},
                {'key': 'milestones', 'label': 'Program-defined readiness milestones', 'kind': 'milestone', 'reached_values': ['complete']}]}
people = [{'subject_id': str(i), 'source_id': f'enrollment-{i}', 'cohort': 'Fall 2026', 'status': 'completed'} for i in range(24)]
readings = []
for i in range(24):
    for metric, a, b, count in [('credit', 600, 642, 20), ('debt', 10000, 8760, 18), ('milestones', 'in_progress', 'complete' if i < 16 else 'in_progress', 22)]:
        for day, value in [('2026-09-07', a), ('2026-10-18', b)]:
            if day == '2026-10-18' and i >= count:
                continue
            readings.append({'subject_id': str(i), 'source_id': f'{i}-{metric}-{day}', 'metric': metric, 'observed_on': day, 'value': value})
snapshot = calculate(definition, people, readings)
report = {'id': '00000000-0000-4000-8000-000000000004', 'snapshot': snapshot, 'content_hash': snapshot['content_hash'], 'status': 'draft', 'created_at': '2026-10-20T12:00:00Z'}
report['configuration'] = {'definition': snapshot['definition'],
    'enrollment': {'module_id': '00000000-0000-4000-8000-000000000010', 'subject_field': 'person', 'cohort_field': 'cohort', 'status_field': 'status'},
    'measurements': [{'module_id': f'00000000-0000-4000-8000-{20 + i:012}', 'metric': metric['key'], 'subject_field': 'person', 'date_field': 'date', 'value_field': 'value'} for i, metric in enumerate(definition['metrics'])]}
folder = Path(__file__).resolve().parents[1] / 'output'
folder.mkdir(exist_ok=True)
pdf = render(report, 'Equity Empowerment Center · Synthetic example')
(folder / 'program-outcomes-sample.pdf').write_bytes(pdf)
(folder / 'program-outcomes-sample.json').write_text(json.dumps(report), encoding='utf-8')
import fitz
with fitz.open(stream=pdf, filetype='pdf') as doc:
    for index, page in enumerate(doc):
        page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(str(folder / f'program-outcomes-page-{index + 1}.png'))
    print(f'Rendered {len(doc)} pages of synthetic data.')
