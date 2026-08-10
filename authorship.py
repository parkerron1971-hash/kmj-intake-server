"""
authorship.py — which machine decided this?

The action ledger answers "who did what, when, and did it work".
actor_type says whether a human or Chief acted; 37 of the first 61 rows
are actor_type='chief'. What it could not say is WHICH model produced
the decision.

"An AI did it" is not a provenance claim. "claude-sonnet-5 did it, on
this date" is. When a practitioner disputes an action a year from now,
the model that made it will have been superseded twice, and the ledger
is the only place that could still say which one it was.

The model is not passed as a parameter for the same reason the billing
tenant is not (see billing_context): the code that WRITES a ledger row
is several frames away from the code that chose a model, and threading
an argument through every one of those chains is a change every future
caller then has to remember to repeat. So it travels out-of-band, and
audit_log.record() reads it without being told.

Deliberately narrow: this records a fact about provenance and decides
nothing. Nothing reads it to grant permission.
"""
from __future__ import annotations

import contextlib
import logging
from contextvars import ContextVar
from typing import Iterator, Optional

logger = logging.getLogger("authorship")

_MODEL: ContextVar[Optional[str]] = ContextVar("authoring_model", default=None)


def current_model() -> Optional[str]:
    """The model whose reasoning is producing the current work, or None.

    None means NOT RECORDED, which is not the same as "no model was
    involved" — that distinction is actor_type's job, and conflating the
    two is how an audit trail starts telling comfortable stories.
    """
    try:
        return _MODEL.get()
    except Exception:      # pragma: no cover - defensive
        return None


def set_model(model: Optional[str]) -> None:
    """Request-scoped form, for a handler that owns the whole task."""
    if not model:
        return
    try:
        _MODEL.set(str(model)[:120])
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("[authorship] could not set model: %s", e)


@contextlib.contextmanager
def authored_by(model: Optional[str]) -> Iterator[None]:
    """Scope authorship to a block, restoring whatever was there before.

    Never raises: failing to record provenance must not fail the work
    being recorded. A missing model is a no-op rather than an error —
    plenty of ledger rows are written by scheduled jobs and human
    actions where no model was involved, and those should stay NULL
    rather than inherit the last one that happened to run.
    """
    if not model:
        yield
        return
    token = None
    try:
        token = _MODEL.set(str(model)[:120])
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("[authorship] could not enter context: %s", e)
    try:
        yield
    finally:
        if token is not None:
            try:
                _MODEL.reset(token)
            except Exception:  # pragma: no cover - defensive
                pass
