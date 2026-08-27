/**
 * Ledger — debits and credits with a running balance.
 *
 * Contract (workspace_primitives.PRIMITIVES.ledger):
 *   entries          [{ id, date, description, debit?, credit?,
 *                       balance? }]                          required
 *   opening_balance  { value }                               optional
 *
 * Options: currency, max_visible
 *
 * `balance` is optional in the contract because no ledger table stores a
 * running balance — it is an artifact of row order. When it is unbound the
 * primitive accumulates from `opening_balance`, oldest first, which is the
 * only way to get it right.
 *
 * Does not fetch.
 */
import React, { useMemo } from 'react';

function money(value, currency) {
  if (value == null || Number.isNaN(Number(value))) return '';
  return Number(value).toLocaleString(undefined, {
    style: 'currency',
    currency: (currency || 'USD').toUpperCase(),
    maximumFractionDigits: 2,
  });
}

export default function Ledger({
  entries = [],
  opening_balance: openingBalance = null,
  options = {},
}) {
  const { currency = 'USD', max_visible: maxVisible = 10 } = options;

  const rows = useMemo(() => {
    // Accumulate oldest-first so the running balance is arithmetically
    // real, then present newest-first, which is how a ledger is read.
    const oldestFirst = [...entries].sort(
      (a, b) => String(a.date || '').localeCompare(String(b.date || '')),
    );

    let running = Number(openingBalance?.value ?? 0);
    const withBalance = oldestFirst.map((entry) => {
      if (entry.balance != null) {
        running = Number(entry.balance);
      } else {
        running += Number(entry.debit || 0) - Number(entry.credit || 0);
      }
      return { ...entry, running };
    });

    return withBalance.reverse();
  }, [entries, openingBalance]);

  const visible = rows.slice(0, maxVisible);
  const closing = rows.length ? rows[0].running : Number(openingBalance?.value ?? 0);

  return (
    <div className="wsLedger">
      <div className="wsLedger__closing">
        <span>Balance</span>
        <strong data-negative={closing < 0 || undefined}>{money(closing, currency)}</strong>
      </div>

      <table className="wsLedger__table">
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Detail</th>
            <th scope="col" className="wsLedger__num">Debit</th>
            <th scope="col" className="wsLedger__num">Credit</th>
            <th scope="col" className="wsLedger__num">Balance</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((entry) => (
            <tr key={entry.id}>
              <td>{String(entry.date || '').slice(0, 10)}</td>
              <td>{entry.description}</td>
              <td className="wsLedger__num">{money(entry.debit, currency)}</td>
              <td className="wsLedger__num">{money(entry.credit, currency)}</td>
              <td className="wsLedger__num wsLedger__running">{money(entry.running, currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {rows.length > visible.length ? (
        <p className="wsLedger__more">{rows.length - visible.length} earlier entries</p>
      ) : null}

      {rows.length === 0 ? (
        <p className="wsLedger__empty">Nothing owed and nothing outstanding.</p>
      ) : null}
    </div>
  );
}
