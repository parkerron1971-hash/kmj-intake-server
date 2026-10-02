/**
 * primitiveRegistry — the client half of the single source of truth.
 *
 * Mirrors workspace_primitives.py. Six entries, keyed by the same slugs the
 * layout schemas use, so `surface.primitive` is a lookup and never a
 * switch statement. The moment this file grows a `if (archetype === ...)`
 * the design has failed.
 *
 * Nothing here declares contracts — the server owns those, and the server
 * validates against them. This map exists to answer one question: given a
 * primitive slug, which component renders it.
 *
 * Keep the key set identical to the server's registry. The parity test
 * (__tests__/test_workspace_ui_parity.py) reads both and fails if they
 * drift, which is the only thing stopping a layout that validates on the
 * server from rendering a blank box in the app.
 */
import AttentionQueue from './primitives/AttentionQueue.jsx';
import BenchmarkPanel from './primitives/BenchmarkPanel.jsx';
import Ledger from './primitives/Ledger.jsx';
import MetricRow from './primitives/MetricRow.jsx';
import PriorityDocket from './primitives/PriorityDocket.jsx';
import TimelineDay from './primitives/TimelineDay.jsx';
import WeekGrid from './primitives/WeekGrid.jsx';

export const PRIMITIVES = {
  timeline_day: TimelineDay,
  priority_docket: PriorityDocket,
  week_grid: WeekGrid,
  attention_queue: AttentionQueue,
  benchmark_panel: BenchmarkPanel,
  metric_row: MetricRow,
  ledger: Ledger,
};

/** Surface roles, most prominent first. Mirrors workspace_primitives.ROLES. */
export const ROLES = ['lead', 'secondary', 'footer'];

export function componentFor(primitiveId) {
  return PRIMITIVES[primitiveId] || null;
}

export function primitiveIds() {
  return Object.keys(PRIMITIVES);
}
