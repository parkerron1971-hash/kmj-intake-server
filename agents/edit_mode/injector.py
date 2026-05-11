"""Pass 4.0e PART 1 — Inject the edit-mode script into served HTML.

Pure-function module. inject_edit_mode_script(html) returns the html with
a single <script> block appended to <head>, just like brand_kit_renderer
does for CSS variables. The script is self-contained — no external deps,
no external network calls.

Idempotent: a prior edit-mode-script block is stripped before injection
so re-renders don't accumulate.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


# Self-contained edit-mode script. Lives as a Python string literal so
# it can be unit-tested without a browser. Style + behavior matches the
# Pass 4.0e PART 1 spec. Single dollar signs inside JS are fine — Python
# doesn't interpolate from f-strings here (no leading f).
_EDIT_MODE_SCRIPT = """
(function() {
  if (window.__solutionistEditModeReady) return;
  window.__solutionistEditModeReady = true;

  var editModeActive = false;
  var selectedPaths = new Set();
  var selectionOrder = new Map();

  // Parent origin filter — Studio app may be tauri://localhost,
  // http://localhost:5173 (vite), or whatever the practitioner uses.
  // Outbound postMessage uses '*' (the iframe can't know parent origin
  // in advance); inbound is filtered to known studio origins below.
  var ALLOWED_PARENT_ORIGINS = [
    'tauri://localhost',
    'http://localhost:5173',
    'http://localhost:1420',
    'https://tauri.localhost',
    'http://tauri.localhost'
  ];

  // Style injection — hover + selected outline + numbered badge.
  var style = document.createElement('style');
  style.setAttribute('data-edit-mode-style', '1');
  style.textContent = [
    '[data-override-target] { transition: outline 0.15s ease; }',
    'body.edit-mode-active [data-override-target]:hover {',
    '  outline: 1px dashed var(--brand-signal, #C6952F);',
    '  outline-offset: 2px;',
    '  cursor: pointer;',
    '}',
    'body.edit-mode-active [data-override-target].selected {',
    '  outline: 2px solid var(--brand-signal, #C6952F);',
    '  outline-offset: 2px;',
    '  position: relative;',
    '}',
    'body.edit-mode-active [data-override-target].selected::after {',
    '  content: attr(data-selection-order);',
    '  position: absolute;',
    '  top: -10px;',
    '  right: -10px;',
    '  background: var(--brand-signal, #C6952F);',
    '  color: var(--brand-text-on-signal, #0F172A);',
    '  width: 22px;',
    '  height: 22px;',
    '  border-radius: 50%;',
    '  display: flex;',
    '  align-items: center;',
    '  justify-content: center;',
    '  font-size: 11px;',
    '  font-weight: 800;',
    '  pointer-events: none;',
    '  z-index: 999;',
    '  line-height: 1;',
    '}',
    'body.edit-mode-active [data-override-target].chief-edit-pulse {',
    '  animation: chiefEditPulse 2s ease-out;',
    '}',
    '@keyframes chiefEditPulse {',
    '  0%   { outline-width: 2px; outline-color: var(--brand-signal, #C6952F); }',
    '  35%  { outline-width: 4px; outline-color: var(--brand-signal, #C6952F); }',
    '  100% { outline-width: 2px; outline-color: var(--brand-signal, #C6952F); }',
    '}'
  ].join('\\n');
  document.head.appendChild(style);

  function postToParent(msg) {
    try { window.parent.postMessage(msg, '*'); } catch (e) { /* parent gone */ }
  }

  function updateSelectionVisual() {
    var nodes = document.querySelectorAll('[data-override-target]');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var path = el.getAttribute('data-override-target');
      if (selectedPaths.has(path)) {
        el.classList.add('selected');
        el.setAttribute('data-selection-order', String(selectionOrder.get(path)));
      } else {
        el.classList.remove('selected');
        el.removeAttribute('data-selection-order');
      }
    }
  }

  function handleClick(e) {
    if (!editModeActive) return;
    var el = e.target.closest ? e.target.closest('[data-override-target]') : null;
    if (!el) return;
    e.preventDefault();
    e.stopPropagation();
    var path = el.getAttribute('data-override-target');
    var type = el.getAttribute('data-override-type') || 'text';
    var rect = el.getBoundingClientRect();
    postToParent({
      type: 'element_clicked',
      target_path: path,
      target_type: type,
      modifier_keys: {
        shift: !!e.shiftKey,
        ctrl: !!e.ctrlKey,
        meta: !!e.metaKey,
        alt: !!e.altKey
      },
      element_data: {
        tag: el.tagName.toLowerCase(),
        content: (el.textContent || '').slice(0, 1000),
        current_src: el.getAttribute('src') || null,
        current_background: el.style.background || null
      },
      dom_position: {
        x: Math.round(rect.left),
        y: Math.round(rect.top),
        w: Math.round(rect.width),
        h: Math.round(rect.height)
      }
    });
  }

  var lastHover = null;
  function handleHover(e) {
    if (!editModeActive) return;
    var el = e.target.closest ? e.target.closest('[data-override-target]') : null;
    var path = el ? el.getAttribute('data-override-target') : null;
    if (path === lastHover) return;
    lastHover = path;
    postToParent({ type: 'element_hovered', target_path: path });
  }

  function originAllowed(origin) {
    // Empty origin can happen for null/file/sandbox contexts — accept
    // (parent will still filter on the inbound side). Otherwise check
    // against the allowlist.
    if (!origin) return true;
    for (var i = 0; i < ALLOWED_PARENT_ORIGINS.length; i++) {
      if (ALLOWED_PARENT_ORIGINS[i] === origin) return true;
    }
    return false;
  }

  window.addEventListener('message', function(event) {
    if (!originAllowed(event.origin)) return;
    var msg = event.data;
    if (!msg || typeof msg !== 'object' || !msg.type) return;

    switch (msg.type) {
      case 'ping':
        postToParent({ type: 'pong', token: msg.token || null });
        break;

      case 'edit_mode_changed':
        editModeActive = !!msg.enabled;
        if (editModeActive) {
          document.body.classList.add('edit-mode-active');
        } else {
          document.body.classList.remove('edit-mode-active');
          selectedPaths.clear();
          selectionOrder.clear();
          updateSelectionVisual();
        }
        break;

      case 'clear_selection':
        selectedPaths.clear();
        selectionOrder.clear();
        updateSelectionVisual();
        break;

      case 'select_target':
        if (!msg.target_path) break;
        if (msg.multi) {
          if (selectedPaths.has(msg.target_path)) {
            selectedPaths.delete(msg.target_path);
            selectionOrder.delete(msg.target_path);
            // Renumber remaining selections so display order stays 1..N.
            var i = 1;
            var keys = Array.from(selectionOrder.keys());
            keys.sort(function(a, b) { return selectionOrder.get(a) - selectionOrder.get(b); });
            selectionOrder.clear();
            for (var j = 0; j < keys.length; j++) {
              selectionOrder.set(keys[j], j + 1);
            }
          } else {
            selectedPaths.add(msg.target_path);
            selectionOrder.set(msg.target_path, selectedPaths.size);
          }
        } else {
          selectedPaths.clear();
          selectionOrder.clear();
          selectedPaths.add(msg.target_path);
          selectionOrder.set(msg.target_path, 1);
        }
        updateSelectionVisual();
        break;

      case 'chief_edit_applied':
        // Pulse the element that Chief just modified.
        if (!msg.target_path) break;
        var el = document.querySelector('[data-override-target="' + msg.target_path.replace(/"/g, '') + '"]');
        if (el) {
          el.classList.add('chief-edit-pulse');
          setTimeout(function() { el.classList.remove('chief-edit-pulse'); }, 2000);
        }
        break;

      default:
        break;
    }
  }, false);

  document.body.addEventListener('click', handleClick, true);
  document.body.addEventListener('mouseover', handleHover, true);
})();
"""


# Strip any prior edit-mode script block so re-renders don't accumulate.
# Tag both via a sentinel comment line so the regex is anchored.
_PRIOR_BLOCK_RE = re.compile(
    r'<script[^>]*data-edit-mode-script="1"[^>]*>.*?</script>',
    re.IGNORECASE | re.DOTALL,
)
_HEAD_OPEN_RE = re.compile(r"<head\b[^>]*>", re.IGNORECASE)


def inject_edit_mode_script(html: str) -> str:
    """Append the edit-mode script to <head>. Idempotent — drops any
    prior block first. Soft-fails to the input HTML on any error
    so a script-injection bug never breaks the site render."""
    if not html or not isinstance(html, str):
        return html or ""
    try:
        # Drop prior block (idempotency).
        html = _PRIOR_BLOCK_RE.sub("", html)
        block = (
            '<script data-edit-mode-script="1">\n'
            + _EDIT_MODE_SCRIPT.strip()
            + '\n</script>'
        )
        m = _HEAD_OPEN_RE.search(html)
        if not m:
            # No <head> — prepend at top of document so the script still
            # runs (rare; Builder always emits <head>).
            return block + "\n" + html
        insert_at = m.end()
        return html[:insert_at] + "\n" + block + html[insert_at:]
    except Exception as e:
        logger.warning(f"[edit_mode.injector] inject failed, serving HTML unchanged: {e}")
        return html
