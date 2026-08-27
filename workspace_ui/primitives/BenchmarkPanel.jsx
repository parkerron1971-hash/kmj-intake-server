/**
 * BenchmarkPanel — the handful of numbers that say whether the business is
 * working, each placed against its industry average and its target.
 *
 * Contract (workspace_primitives.PRIMITIVES.benchmark_panel):
 *   rows  [{ id, label, value, average?, target?, floor?, scale_max?,
 *            unit?, reading?, source?, direction? }]     required, 2-6
 *
 * Options: format, show_average, cascade, cascade_label
 *
 * The band is the whole component. A bare "38%" is noise; 38% sitting to
 * the left of a 52% average and a 50% target, with one line saying what to
 * do about the gap, is a decision. So the meter is not decoration around
 * the number — it is the reason the number is on screen.
 *
 * `direction` handles the metrics where low is good (no-show rate, lockup
 * days). Without it the meter would congratulate a practice for a 22%
 * no-show rate because 22 is a bigger number than the 8% target.
 *
 * `cascade` is for rows that multiply through each other rather than
 * standing alone — utilization x realization x collection is one story in
 * three parts, and reading them as three independent gauges misses that
 * only their product reaches the bank.
 *
 * Does not fetch.
 */
import React, { useMemo } from 'react';

const HIGHER_IS_BETTER = 'higher_better';

function formatValue(value, unit, style) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  const n = Number(value);
  switch (style) {
    case 'percent':
      return `${Number.isInteger(n) ? n : n.toFixed(1)}%`;
    case 'days':
      return `${Math.round(n)}d`;
    case 'duration':
      return `${n}h`;
    case 'currency':
      return n.toLocaleString(undefined, {
        style: 'currency',
        currency: (unit || 'USD').toUpperCase(),
        maximumFractionDigits: 0,
      });
    default:
      return n.toLocaleString(undefined, { maximumFractionDigits: 1 });
  }
}

/**
 * Where a row stands: 'strong' at or past target, 'weak' at or under the
 * floor, 'fair' in between. Returned as a word rather than a colour so the
 * status never travels as colour alone.
 */
export function standingOf(row) {
  const lowerBetter = row.direction && row.direction !== HIGHER_IS_BETTER;
  const { value, target, floor } = row;
  if (value == null) return 'unknown';

  if (target != null) {
    if (lowerBetter ? value <= target : value >= target) return 'strong';
  }
  if (floor != null) {
    if (lowerBetter ? value >= floor : value <= floor) return 'weak';
  }
  return 'fair';
}

/** Percent along the track, clamped so an outlier never escapes the bar. */
function positionOf(value, max) {
  if (value == null || !max) return null;
  return Math.max(0, Math.min(100, (Number(value) / max) * 100));
}

export default function BenchmarkPanel({ rows = [], options = {} }) {
  const {
    format: style = 'percent',
    show_average: showAverage = true,
    cascade = false,
    cascade_label: cascadeLabel = 'of working time survives to cash',
  } = options;

  // Each row carries its own scale so a days figure and a percentage can
  // sit in the same panel without one flattening the other.
  const prepared = useMemo(() => rows.map((row) => {
    const candidates = [row.value, row.average, row.target, row.floor]
      .filter((v) => v != null)
      .map(Number);
    const max = row.scale_max != null
      ? Number(row.scale_max)
      : Math.max(style === 'percent' ? 100 : 1, ...candidates) * (style === 'percent' ? 1 : 1.2);
    return {
      ...row,
      max,
      standing: standingOf(row),
      at: positionOf(row.value, max),
      avgAt: positionOf(row.average, max),
      targetAt: positionOf(row.target, max),
    };
  }), [rows, style]);

  // Only meaningful for a cascade: the product of the rates, which is the
  // number none of the individual rows shows.
  const product = useMemo(() => {
    if (!cascade) return null;
    const rates = prepared
      .map((r) => Number(r.value))
      .filter((n) => !Number.isNaN(n));
    if (rates.length < 2) return null;
    return rates.reduce((acc, n) => acc * (n / 100), 1) * 100;
  }, [cascade, prepared]);

  return (
    <div className="wsBench" data-cascade={cascade || undefined}>
      <ol className="wsBench__rows">
        {prepared.map((row) => (
          <li className="wsBench__row" key={row.id} data-standing={row.standing}>
            <div className="wsBench__head">
              <h5>{row.label}</h5>
              <span className="wsBench__value">
                {formatValue(row.value, row.unit, style)}
              </span>
            </div>

            <div className="wsBench__track" role="img"
                 aria-label={`${row.label}: ${formatValue(row.value, row.unit, style)}`
                   + (row.average != null ? `, industry average ${formatValue(row.average, row.unit, style)}` : '')
                   + (row.target != null ? `, target ${formatValue(row.target, row.unit, style)}` : '')}>
              <span className="wsBench__fill" style={{ width: `${row.at ?? 0}%` }} />
              {showAverage && row.avgAt != null ? (
                <span className="wsBench__tick wsBench__tick--avg"
                      style={{ left: `${row.avgAt}%` }} />
              ) : null}
              {row.targetAt != null ? (
                <span className="wsBench__tick wsBench__tick--target"
                      style={{ left: `${row.targetAt}%` }} />
              ) : null}
            </div>

            <div className="wsBench__scale">
              {showAverage && row.average != null ? (
                <span>Average {formatValue(row.average, row.unit, style)}</span>
              ) : null}
              {row.target != null ? (
                <span>Target {formatValue(row.target, row.unit, style)}</span>
              ) : null}
            </div>

            {row.reading ? <p className="wsBench__reading">{row.reading}</p> : null}
            {row.source ? <cite className="wsBench__source">{row.source}</cite> : null}
          </li>
        ))}
      </ol>

      {product != null ? (
        <p className="wsBench__product">
          <strong>{product.toFixed(0)}%</strong> {cascadeLabel}
        </p>
      ) : null}
    </div>
  );
}
