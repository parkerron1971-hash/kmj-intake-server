/**
 * MetricRow — two to four figures at rest.
 *
 * Contract (workspace_primitives.PRIMITIVES.metric_row):
 *   metrics  [{ id, label, value, unit?, trend? }]   required, 2-4 items
 *
 * Options: format ('number' | 'currency' | 'duration' | 'percent')
 *
 * Footer material, never the hero. That is enforced upstream — the
 * registry does not list `lead` in this primitive's allowed_roles, so a
 * layout that leads with numbers fails validation rather than shipping.
 * The styling here holds up the same end of the bargain: no cards, no
 * emphasis, nothing that asks to be acted on.
 *
 * Does not fetch.
 */
import React from 'react';

function format(value, unit, style) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  const n = Number(value);

  switch (style) {
    case 'currency': {
      const currency = (unit || 'USD').toUpperCase();
      // Not every "unit" on a currency row is a currency code — the WIP
      // figure is in hours. Fall through rather than throwing.
      if (!/^[A-Z]{3}$/.test(currency)) return `${n.toLocaleString()} ${unit || ''}`.trim();
      return n.toLocaleString(undefined, {
        style: 'currency', currency, maximumFractionDigits: 0,
      });
    }
    case 'duration': {
      const hours = Math.floor(n);
      const mins = Math.round((n - hours) * 60);
      return mins ? `${hours}h ${mins}m` : `${hours}h`;
    }
    case 'percent':
      return `${n.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
    default:
      return n.toLocaleString(undefined, { maximumFractionDigits: 1 });
  }
}

export default function MetricRow({ metrics = [], options = {} }) {
  const { format: style = 'number' } = options;

  // The contract bounds this at 2-4 and the validator enforces it, but the
  // renderer can be handed live data that came back short. Render what
  // arrived; do not pad with placeholders that read as real zeros.
  return (
    <dl className="wsMetrics" data-count={metrics.length}>
      {metrics.map((metric) => (
        <div className="wsMetrics__item" key={metric.id}>
          <dt>{metric.label}</dt>
          <dd>
            <span className="wsMetrics__value">
              {format(metric.value, metric.unit, style)}
            </span>
            {metric.trend ? (
              <span className="wsMetrics__trend" data-trend={metric.trend}>
                {metric.trend}
              </span>
            ) : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}
