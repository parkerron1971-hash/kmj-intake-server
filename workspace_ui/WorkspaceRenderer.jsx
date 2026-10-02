/**
 * WorkspaceRenderer — the one engine.
 *
 * Reads a layout schema and produces the workspace. Every vertical goes
 * through this component and nothing else. There is no salon renderer and
 * no law-firm renderer; if there ever is, the vertical has escaped the data
 * and the whole design is undone.
 *
 * What it does, in order:
 *   1. reads `layout.surfaces` and orders them by role
 *   2. resolves each surface's bindings against the data bundle the
 *      caller supplies — this is the ONLY place bindings are read
 *   3. looks the primitive up in the registry and renders it with plain
 *      resolved values
 *
 * Data arrives as `data[surfaceId][bindingName]` — already fetched,
 * already tenant-scoped, already field-mapped by the server. The renderer
 * does not fetch and neither do the primitives, so nothing in the render
 * tree needs to know whose data it is looking at.
 *
 * Terminology comes from `layout.terminology`, resolved once here and
 * passed down as `term()`. A row whose origin is `user_override` is the
 * practitioner's word and is rendered exactly as they typed it.
 */
import React, { useCallback, useMemo } from 'react';

import { componentFor, ROLES } from './primitiveRegistry.js';

/**
 * `term('project')` -> "Matter" | "Job" | "Engagement" ...
 * Unknown keys come back as the key itself rather than blank, so a missing
 * term reads as an obvious bug instead of a silently empty label.
 */
export function makeTerm(terminology = {}) {
  return function term(key, fallback) {
    const row = terminology[key];
    if (row && typeof row === 'object' && row.value) return row.value;
    if (typeof row === 'string' && row) return row;
    return fallback !== undefined ? fallback : key;
  };
}

function orderSurfaces(surfaces = []) {
  return [...surfaces].sort(
    (a, b) => ROLES.indexOf(a.role) - ROLES.indexOf(b.role),
  );
}

/** Everything the primitive needs, and nothing it could fetch with. */
function propsFor(surface, bundle, term) {
  const bound = bundle || {};
  const props = { options: surface.options || {}, term };
  Object.keys(surface.bindings || {}).forEach((binding) => {
    props[binding] = bound[binding];
  });
  return props;
}

function Surface({ surface, data, term, index, animate }) {
  const Component = componentFor(surface.primitive);

  if (!Component) {
    // A layout that reached the renderer with an unknown primitive got
    // past the server validator, which means the two registries have
    // drifted. Say so loudly rather than rendering an empty box.
    return (
      <section className="wsSurface wsSurface--broken" data-role={surface.role}>
        <h3>{surface.title}</h3>
        <p>This part of your workspace needs an update before it can load.</p>
      </section>
    );
  }

  return (
    <section
      className="wsSurface"
      data-role={surface.role}
      data-primitive={surface.primitive}
      data-surface={surface.id}
      style={animate ? { '--ws-delay': `${index * 140}ms` } : undefined}
    >
      <header className="wsSurface__head">
        <h3>{surface.title}</h3>
      </header>
      <div className="wsSurface__body">
        <Component {...propsFor(surface, data, term)} />
      </div>
    </section>
  );
}

export default function WorkspaceRenderer({
  layout,
  data = {},
  animate = true,
  className = '',
}) {
  const term = useMemo(
    () => makeTerm(layout?.terminology || {}),
    [layout?.terminology],
  );

  const surfaces = useMemo(
    () => orderSurfaces(layout?.surfaces),
    [layout?.surfaces],
  );

  const themeVars = useMemo(() => {
    const palette = layout?.theme?.palette || {};
    const vars = {};
    Object.keys(palette).forEach((key) => {
      vars[`--ws-${key}`] = palette[key];
    });
    if (layout?.theme?.display_font) {
      vars['--ws-display'] = layout.theme.display_font;
    }
    return vars;
  }, [layout?.theme]);

  if (!layout) return null;

  return (
    <div
      className={`wsWorkspace ${className}`.trim()}
      data-archetype={layout.archetype}
      data-animate={animate || undefined}
      style={themeVars}
    >
      {surfaces.map((surface, i) => (
        <Surface
          key={surface.id}
          surface={surface}
          data={data[surface.id]}
          term={term}
          index={i}
          animate={animate}
        />
      ))}
    </div>
  );
}
