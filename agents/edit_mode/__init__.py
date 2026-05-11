"""Pass 4.0e PART 1 — Inline edit-mode script injection.

Adds a self-contained JavaScript block to the served HTML that enables
practitioner edit mode in the preview iframe. The script communicates
with the parent Studio app via window.postMessage:

  parent → iframe:
    edit_mode_changed   toggle iframe-side editability
    clear_selection     deselect all
    select_target       programmatic selection
    ping                handshake test

  iframe → parent:
    pong                handshake response
    element_clicked     practitioner clicked an editable element
    element_hovered     hover state changed (null when leaving any target)
    edit_saved          inline contenteditable edit ready to persist (PART 2)
    error               surface to the parent UI

The script reads `data-override-target` + `data-override-type` attributes
on rendered elements (emitted by the Builder per the Pass 4.0e prompt
update in PART 2). Without those attributes the script is inert — safe
for pre-PART-2 builds.

Mounting position in the render pipeline (smart_sites._try_serve_builder_html):
  Builder HTML → motion → brand-kit-vars → slot-resolve → override-resolve
                                                              ↓
                                                       edit-mode-inject
                                                              ↓
                                                          serve to iframe

Inject AFTER override resolution so the script sees the final HTML the
practitioner will interact with.
"""
