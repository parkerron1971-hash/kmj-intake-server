/**
 * TimelineDay — one day, hours down the side, events placed by start time
 * and sized by duration. Open gaps are flagged.
 *
 * Contract (workspace_primitives.PRIMITIVES.timeline_day):
 *   events  [{ id, lane_id?, start, duration_minutes, title,
 *              subtitle?, state? }]                          required
 *   lanes   [{ id, label, subtitle? }]                       OPTIONAL
 *   day     { date }                                         optional
 *
 * Options: day_start, day_end, gap_threshold_minutes, show_gaps, lane_noun
 *
 * TWO SHAPES, ONE COMPONENT. Bind `lanes` and the day splits into parallel
 * tracks — a trades crew board does this, because contractors are real rows
 * in a real table. Leave it unbound and the day draws as ONE track,
 * undivided. A salon takes the second shape: nothing in this system stores
 * a named member of staff, so a lane per stylist would draw a screen that
 * does not exist behind it. The layout schema picks the shape; this file
 * has no opinion about which vertical gets which.
 *
 * This component does NOT fetch. Every value arrives resolved from the
 * renderer, which is the only thing that knows about bindings, sources or
 * tenants. A primitive that could fetch would need to know whose data it
 * was looking at, and that is exactly the knowledge we are keeping out of
 * the render layer.
 */
import React, { useMemo } from 'react';

const MIN_PER_HOUR = 60;

/** "2026-08-26T14:30:00Z" | "14:30" -> minutes since midnight. */
function toMinutes(value) {
  if (value == null) return null;
  if (typeof value === 'number') return value;
  const str = String(value);
  const time = str.includes('T') ? str.split('T')[1] : str;
  const [h, m] = time.split(':');
  const hours = Number(h);
  const mins = Number(m);
  if (Number.isNaN(hours) || Number.isNaN(mins)) return null;
  return hours * MIN_PER_HOUR + mins;
}

function label(minutes) {
  const h = Math.floor(minutes / MIN_PER_HOUR);
  const suffix = h < 12 ? 'am' : 'pm';
  const display = h % 12 === 0 ? 12 : h % 12;
  return `${display}${suffix}`;
}

/**
 * Gaps between consecutive events on one track, plus the gap before the
 * first and after the last. An empty track is one gap the length of the
 * day — which is the single most actionable thing this component can say.
 *
 * On an undivided day this is doing real work rather than bookkeeping: two
 * appointments that overlap close the gap between them exactly once,
 * because `cursor` only ever moves forward.
 */
function gapsFor(events, dayStart, dayEnd, threshold) {
  const bounds = events
    .map((e) => {
      const start = toMinutes(e.start);
      if (start == null) return null;
      return [start, start + (Number(e.duration_minutes) || 0)];
    })
    .filter(Boolean)
    .sort((a, b) => a[0] - b[0]);

  const gaps = [];
  let cursor = dayStart * MIN_PER_HOUR;

  bounds.forEach(([start, end]) => {
    if (start - cursor >= threshold) gaps.push({ from: cursor, to: start });
    cursor = Math.max(cursor, end);
  });

  const close = dayEnd * MIN_PER_HOUR;
  if (close - cursor >= threshold) gaps.push({ from: cursor, to: close });

  return gaps;
}

/** One track's blocks — gaps and events together, in clock order. */
function blocksFor(events, gaps) {
  const blocks = [];
  events.forEach((event) => {
    const at = toMinutes(event.start);
    if (at != null) blocks.push({ kind: 'event', at, event });
  });
  gaps.forEach((gap) => blocks.push({ kind: 'gap', at: gap.from, gap }));
  return blocks.sort((a, b) => a.at - b.at);
}


export default function TimelineDay({
  lanes = [],
  events = [],
  day = null,
  options = {},
  term = (k) => k,
}) {
  const {
    day_start: dayStart = 8,
    day_end: dayEnd = 20,
    gap_threshold_minutes: threshold = 30,
    show_gaps: showGaps = true,
    lane_noun: laneNoun = 'Resource',
  } = options;

  const span = Math.max(1, (dayEnd - dayStart) * MIN_PER_HOUR);
  const hours = useMemo(
    () => Array.from({ length: dayEnd - dayStart + 1 }, (_, i) => dayStart + i),
    [dayStart, dayEnd],
  );

  /**
   * The tracks to draw. With lanes bound, one per lane, each holding the
   * events that name it. With lanes unbound, exactly one track holding
   * every event — and no header, because there is nothing to name.
   */
  const tracks = useMemo(() => {
    if (!lanes.length) {
      return [{ id: '__day__', label: null, subtitle: null, events }];
    }
    const map = new Map(lanes.map((l) => [String(l.id), []]));
    events.forEach((e) => {
      const key = String(e.lane_id);
      if (map.has(key)) map.get(key).push(e);
    });
    return lanes.map((lane) => ({
      id: lane.id,
      label: lane.label,
      subtitle: lane.subtitle,
      events: map.get(String(lane.id)) || [],
    }));
  }, [lanes, events]);

  const divided = lanes.length > 0;
  const pct = (minutes) => ((minutes - dayStart * MIN_PER_HOUR) / span) * 100;

  return (
    <div
      className="wsTimeline"
      data-lane-count={lanes.length}
      data-divided={divided ? 'yes' : 'no'}
    >
      <div className="wsTimeline__head">
        {/* An undivided day has no resource to count, so it says what it
            is instead of pluralising a noun nothing is grouped by. */}
        <span className="wsTimeline__laneNoun">
          {divided ? `${laneNoun}s` : term('today') || 'Today'}
        </span>
        {day?.date ? <time className="wsTimeline__date">{day.date}</time> : null}
      </div>

      <div className="wsTimeline__body">
        {/* Hours run down the side. On a narrow screen the whole grid
            rotates to a stacked list instead — see the CSS. */}
        <div className="wsTimeline__hours" aria-hidden="true">
          {hours.map((h) => (
            <div className="wsTimeline__hour" key={h} style={{ top: `${pct(h * MIN_PER_HOUR)}%` }}>
              <span>{label(h * MIN_PER_HOUR)}</span>
            </div>
          ))}
        </div>

        <div className="wsTimeline__lanes">
          {tracks.map((track) => {
            const gaps = showGaps
              ? gapsFor(track.events, dayStart, dayEnd, threshold)
              : [];

            return (
              <section className="wsTimeline__lane" key={track.id}>
                {track.label ? (
                  <header className="wsTimeline__laneHead">
                    <h4>{track.label}</h4>
                    {track.subtitle ? <p>{track.subtitle}</p> : null}
                  </header>
                ) : null}

                <div className="wsTimeline__track">
                  {/* Gaps and events interleave in clock order. On a wide
                      screen every block is absolutely positioned, so DOM
                      order is invisible — but a stacked small-screen form
                      drops that positioning, and two separate groups then
                      read as every gap first and all the work after it.
                      Source order has to be the true order, for the
                      stacked layout and for a screen reader alike. */}
                  {blocksFor(track.events, gaps).map((block) => {
                    if (block.kind === 'gap') {
                      const { gap } = block;
                      return (
                        <div
                          className="wsTimeline__gap"
                          key={`gap-${gap.from}`}
                          style={{ top: `${pct(gap.from)}%`, height: `${((gap.to - gap.from) / span) * 100}%` }}
                        >
                          <span>{Math.round(gap.to - gap.from)} min open</span>
                        </div>
                      );
                    }
                    const { event, at } = block;
                    const duration = Number(event.duration_minutes) || 0;
                    return (
                      <article
                        className="wsTimeline__event"
                        key={event.id}
                        data-state={event.state || 'scheduled'}
                        style={{ top: `${pct(at)}%`, height: `${(duration / span) * 100}%` }}
                      >
                        <span className="wsTimeline__eventTime">{label(at)}</span>
                        <h5>{event.title}</h5>
                        {event.subtitle ? <p>{event.subtitle}</p> : null}
                      </article>
                    );
                  })}

                  {track.events.length === 0 ? (
                    <p className="wsTimeline__empty">
                      Nothing booked — {term('appointments') || 'appointments'} all day
                    </p>
                  ) : null}
                </div>
              </section>
            );
          })}
        </div>
      </div>
    </div>
  );
}
