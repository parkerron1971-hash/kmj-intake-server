"""Aggregate-only PDF rendering of a frozen outcome report; no model calls."""
from html import escape

import pdf_reports


def _body(report, s, money_cell, accent, stripe, rule, danger, colors, Table,
          TableStyle, Paragraph, Spacer, inch, meta):
    snap = report['snapshot']
    d = snap['definition']
    p = lambda value, style='row': Paragraph(escape(str(value)), s[style])
    story = [p('Approved snapshot' if report['status'] == 'approved' else 'DRAFT — NOT APPROVED', 'section'),
             p(f"Cohort: {d['cohort']}"),
             p(f"Baseline: {d['baseline_start']} to {d['baseline_end']}"),
             p(f"Follow-up: {d['followup_start']} to {d['followup_end']}"),
             p(f"Included: {snap['included_count']} of {snap['cohort_count']} enrolled; excluded: {snap['excluded_count']}."),
             p('Included enrollment statuses: ' + ', '.join(d['included_statuses']), 'meta')]
    if snap['excluded_status_counts']:
        story.append(p('Excluded statuses: ' + ', '.join(f'{k}: {v}' for k, v in snap['excluded_status_counts'].items()), 'meta'))
    for m in snap['metrics']:
        metric = m['metric']
        story.append(p(metric['label'], 'section'))
        values = [('Participants with paired readings', f"{m['paired_count']} / {m['included_count']}"),
                  ('Missing baseline / follow-up', f"{m['missing_baseline_count']} / {m['missing_followup_count']}")]
        if metric['kind'] == 'number':
            def value(key):
                v = m[key]
                return 'No paired readings' if v is None else f"{v} {metric['unit']}".strip()
            values += [('Average baseline (paired)', value('mean_baseline_paired')),
                       ('Average follow-up (paired)', value('mean_followup_paired')),
                       ('Average change (follow-up minus baseline)', value('mean_change_paired'))]
            if metric['target'] is not None:
                values.append(('Organization-defined target', ('At least ' if metric['direction'] == 'up' else 'At most ') + str(metric['target']) + ' ' + metric['unit']))
        else:
            values.append(('Organization-defined milestone values', ', '.join(metric['reached_values'])))
        if m['followup_reached_count'] is not None:
            values += [('Reached at follow-up / observed follow-ups', f"{m['followup_reached_count']} / {m['followup_observed_count']}"),
                       ('Newly reached / paired participants', f"{m['newly_reached_count']} / {m['paired_count']}")]
        table = Table([[p(a), p(b)] for a, b in values], colWidths=[3.5 * inch, 2.4 * inch])
        table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, stripe]),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7), ('TOPPADDING', (0, 0), (-1, -1), 7)]))
        story += [table, Spacer(1, .1 * inch)]
    story += [p('Snapshot reference', 'section'), p(str(report['id']), 'meta'),
              p('SHA-256: ' + report['content_hash'], 'meta'),
              p('Created: ' + str(report.get('created_at', '')), 'meta')]
    if report['status'] == 'approved':
        story.append(p('Approved: ' + str(report.get('approved_at', '')), 'meta'))
    return story


def render(report, business_name):
    pdf_reports.register_builder('program_outcomes', _body)
    meta = pdf_reports.build_meta(business_name=business_name, settings=None,
        report_title='Program Outcomes', period_label=escape(report['snapshot']['definition']['title']),
        basis_label='Frozen report snapshot', notes=(
            'First baseline and last follow-up readings within the specified windows are compared for the same '
            'participants. Missing readings are never zero. Each metric uses its own denominator. '
            'These are recorded outcomes, not evidence that the program caused the change. '
            'Participant identities and individual readings are excluded from this PDF. '
            'Approval records review of the snapshot; distribution requires a separate decision.'))
    meta['currency_label'] = ''
    return pdf_reports.render('program_outcomes', report, meta)
