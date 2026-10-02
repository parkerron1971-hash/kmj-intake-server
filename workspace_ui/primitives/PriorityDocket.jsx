/**
 * PriorityDocket — rows ordered by urgency in DAYS, not by the clock.
 * Hairline rules, right-aligned metric.
 *
 * Contract (workspace_primitives.PRIMITIVES.priority_docket):
 *   rows  [{ id, title, metric_value, metric_unit?, subtitle?,
 *            stage?, owner? }]                                required
 *
 * Options: sort ('urgency_days' | 'stage'), metric_label, metric_unit,
 *          stages, urgent_threshold_days
 *
 * The two sorts are genuinely different readings of the same rows. Under
 * `urgency_days` the docket is one ranked column and the eye runs down the
 * numbers. Under `stage` it breaks into groups and the finding is a group
 * that has stopped moving. Same primitive, same contract — the vertical
 * lives in the option, not in a second component.
 *
 * Does not fetch.
 */
import React, { useMemo } from 'react';

function formatMetric(value) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  const n = Number(value);
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(1);
}

export default function PriorityDocket({
  rows = [],
  options = {},
  term = (k) => k,
}) {
  const {
    sort = 'urgency_days',
    metric_label: metricLabel = 'Due in',
    metric_unit: metricUnit = 'days',
    stages = [],
    urgent_threshold_days: urgentThreshold = 7,
  } = options;

  const groups = useMemo(() => {
    if (sort !== 'stage') {
      const ordered = [...rows].sort(
        (a, b) => Number(a.metric_value ?? Infinity) - Number(b.metric_value ?? Infinity),
      );
      return [{ key: '__all__', label: null, rows: ordered }];
    }

    // Declared stage order wins. A stage the data uses but the layout did
    // not declare still gets a group rather than vanishing — dropping rows
    // silently is how a docket lies about the size of the book.
    const declared = stages.length ? stages : [];
    const seen = new Set(declared);
    const extra = [];
    rows.forEach((r) => {
      const s = r.stage || 'Unassigned';
      if (!seen.has(s)) { seen.add(s); extra.push(s); }
    });

    return [...declared, ...extra].map((stage) => ({
      key: stage,
      label: stage,
      rows: rows
        .filter((r) => (r.stage || 'Unassigned') === stage)
        .sort((a, b) => Number(b.metric_value ?? 0) - Number(a.metric_value ?? 0)),
    }));
  }, [rows, sort, stages]);

  return (
    <div className="wsDocket" data-sort={sort}>
      <div className="wsDocket__head">
        <span className="wsDocket__metricLabel">{metricLabel}</span>
      </div>

      {groups.map((group) => (
        <section className="wsDocket__group" key={group.key}>
          {group.label ? (
            <header className="wsDocket__groupHead">
              <h4>{group.label}</h4>
              <span>{group.rows.length}</span>
            </header>
          ) : null}

          {group.rows.length === 0 ? (
            <p className="wsDocket__empty">Nothing at this stage.</p>
          ) : (
            <ol className="wsDocket__rows">
              {group.rows.map((row) => {
                const value = Number(row.metric_value);
                // Under a stage sort the number is time-in-stage: high is
                // bad. Under an urgency sort it is time remaining: low is
                // bad. Same column, opposite polarity.
                const urgent = sort === 'stage'
                  ? value >= urgentThreshold
                  : value <= urgentThreshold;

                return (
                  <li className="wsDocket__row" key={row.id} data-urgent={urgent || undefined}>
                    <div className="wsDocket__rowMain">
                      <h5>{row.title}</h5>
                      <p>
                        {row.subtitle}
                        {row.owner ? <span className="wsDocket__owner">{row.owner}</span> : null}
                      </p>
                    </div>
                    <div className="wsDocket__metric">
                      <strong>{formatMetric(row.metric_value)}</strong>
                      <span>{row.metric_unit || metricUnit}</span>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </section>
      ))}

      {rows.length === 0 ? (
        <p className="wsDocket__empty">
          No open {term('projects') || 'work'}.
        </p>
      ) : null}
    </div>
  );
}
