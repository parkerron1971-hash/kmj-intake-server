/**
 * WeekGrid — seven day columns, events placed where they fall.
 *
 * Contract (workspace_primitives.PRIMITIVES.week_grid):
 *   week_of  { date }                                        optional
 *   events   [{ id, date, title, time?, subtitle?,
 *               attendance?, kind? }]                        required
 *
 * Options: week_start ('sun' | 'mon'), show_counts, count_noun
 *
 * The seven columns are generated here rather than bound. They are a
 * calendar fact, not tenant data — a layout that could bind them could
 * also ship a six-column week.
 *
 * Does not fetch.
 */
import React, { useMemo } from 'react';

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/* Dates are handled entirely in LOCAL time.
   `new Date('2026-08-23')` parses as UTC midnight, so west of Greenwich
   `.getDay()` answers Saturday for a Sunday and this grid builds the
   wrong seven days — every event then falls outside its own week and the
   board renders empty. `toISOString()` shifts it back the other way.
   Parsing and formatting by hand avoids both. */
function dayKey(value) {
  if (!value) return null;
  const str = String(value);
  return str.includes('T') ? str.split('T')[0] : str.slice(0, 10);
}

function formatKey(date) {
  const m = `${date.getMonth() + 1}`.padStart(2, '0');
  const d = `${date.getDate()}`.padStart(2, '0');
  return `${date.getFullYear()}-${m}-${d}`;
}

function parseDay(value) {
  const [y, m, d] = String(value ?? '').slice(0, 10).split('-').map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d);
}

function startOfWeek(anchor, weekStart) {
  const base = parseDay(anchor) || new Date();
  const offsetTarget = weekStart === 'mon' ? 1 : 0;
  const shift = (base.getDay() - offsetTarget + 7) % 7;
  const start = new Date(base);
  start.setDate(base.getDate() - shift);
  start.setHours(0, 0, 0, 0);
  return start;
}

export default function WeekGrid({
  week_of: weekOf = null,
  events = [],
  options = {},
  term = (k) => k,
}) {
  const {
    week_start: weekStart = 'sun',
    show_counts: showCounts = false,
    count_noun: countNoun = 'attending',
  } = options;

  const days = useMemo(() => {
    const start = startOfWeek(weekOf?.date, weekStart);
    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      return {
        key: formatKey(d),
        label: DAY_NAMES[d.getDay()],
        dayOfMonth: d.getDate(),
      };
    });
  }, [weekOf, weekStart]);

  const byDay = useMemo(() => {
    const map = new Map(days.map((d) => [d.key, []]));
    events.forEach((e) => {
      const key = dayKey(e.date);
      if (map.has(key)) map.get(key).push(e);
    });
    map.forEach((list) => list.sort((a, b) => String(a.time || '').localeCompare(String(b.time || ''))));
    return map;
  }, [days, events]);

  // The uneven shape IS the information — which days carry weight and
  // which are empty. Columns are sized by load rather than evenly, so a
  // three-service Sunday looks like a three-service Sunday.
  const heaviest = Math.max(1, ...days.map((d) => (byDay.get(d.key) || []).length));

  return (
    <div className="wsWeek" data-week-start={weekStart}>
      <ol className="wsWeek__grid">
        {days.map((day) => {
          const dayEvents = byDay.get(day.key) || [];
          const load = dayEvents.length / heaviest;

          return (
            <li
              className="wsWeek__day"
              key={day.key}
              data-empty={dayEvents.length === 0 || undefined}
              style={{ '--ws-load': load.toFixed(2) }}
            >
              <header className="wsWeek__dayHead">
                <span className="wsWeek__dayName">{day.label}</span>
                <span className="wsWeek__dayNum">{day.dayOfMonth}</span>
              </header>

              {dayEvents.length === 0 ? (
                <p className="wsWeek__quiet">—</p>
              ) : (
                <ul className="wsWeek__events">
                  {dayEvents.map((event) => (
                    <li className="wsWeek__event" key={event.id} data-kind={event.kind || 'gathering'}>
                      {event.time ? <time>{event.time}</time> : null}
                      <h5>{event.title}</h5>
                      {event.subtitle ? <p>{event.subtitle}</p> : null}
                      {showCounts && event.attendance != null ? (
                        <span className="wsWeek__count">
                          {event.attendance} {countNoun}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>

      {events.length === 0 ? (
        <p className="wsWeek__empty">
          Nothing on the {term('schedule') || 'calendar'} this week.
        </p>
      ) : null}
    </div>
  );
}
