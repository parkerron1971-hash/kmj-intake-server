/**
 * AttentionQueue — an ordered list of things waiting on a person, each
 * carrying how long it has waited.
 *
 * Contract (workspace_primitives.PRIMITIVES.attention_queue):
 *   items  [{ id, title, age_days, subtitle?, action_label? }]  required
 *
 * Options: age_unit ('days' | 'weeks'), escalate_after_days, max_visible
 *
 * Age is the whole point. A queue without it is just a list, and a list
 * does not tell you that the person at the bottom has been waiting nine
 * weeks.
 *
 * Does not fetch.
 */
import React, { useMemo } from 'react';

function ageLabel(days, unit) {
  const n = Number(days);
  if (Number.isNaN(n)) return '—';
  if (unit === 'weeks') {
    const weeks = Math.floor(n / 7);
    if (weeks < 1) return `${Math.max(0, Math.round(n))}d`;
    return `${weeks}w`;
  }
  return `${Math.max(0, Math.round(n))}d`;
}

export default function AttentionQueue({
  items = [],
  options = {},
  term = (k) => k,
}) {
  const {
    age_unit: ageUnit = 'days',
    escalate_after_days: escalateAfter = 30,
    max_visible: maxVisible = 8,
  } = options;

  const ordered = useMemo(
    () => [...items].sort((a, b) => Number(b.age_days ?? 0) - Number(a.age_days ?? 0)),
    [items],
  );

  const visible = ordered.slice(0, maxVisible);
  const hidden = ordered.length - visible.length;

  return (
    <div className="wsQueue">
      <ol className="wsQueue__list">
        {visible.map((item) => {
          const overdue = Number(item.age_days ?? 0) >= escalateAfter;
          return (
            <li className="wsQueue__item" key={item.id} data-overdue={overdue || undefined}>
              <div className="wsQueue__main">
                <h5>{item.title}</h5>
                {item.subtitle ? <p>{item.subtitle}</p> : null}
              </div>
              <div className="wsQueue__age">
                <strong>{ageLabel(item.age_days, ageUnit)}</strong>
                {item.action_label ? <span>{item.action_label}</span> : null}
              </div>
            </li>
          );
        })}
      </ol>

      {hidden > 0 ? (
        <p className="wsQueue__more">
          {hidden} more waiting
        </p>
      ) : null}

      {ordered.length === 0 ? (
        <p className="wsQueue__empty">
          Nobody waiting. Every {term('contact') || 'person'} has been followed up.
        </p>
      ) : null}
    </div>
  );
}
