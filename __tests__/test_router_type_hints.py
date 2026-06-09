"""Guard against the 'missing typing import masked by __future__ annotations'
class of bug: with `from __future__ import annotations`, a parameter annotated
with a name that isn't imported (e.g. Optional) imports fine but FastAPI's
get_type_hints() fails at REQUEST time → PydanticUserError → 500.

Asserting get_type_hints resolves for every route endpoint catches it at test
time. (This is exactly what broke POST /gl/process-queue — trace 92d86185.)"""
from __future__ import annotations

import sys
import pathlib
import typing
import importlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

_ROUTERS = ["gl_router", "reports_router", "bills_router", "chief_bookkeeping_router"]


@pytest.mark.parametrize("modname", _ROUTERS)
def test_route_type_hints_resolve(modname):
    mod = importlib.import_module(modname)
    router = getattr(mod, "router")
    failures = []
    for route in router.routes:
        fn = getattr(route, "endpoint", None)
        if fn is None:
            continue
        try:
            typing.get_type_hints(fn)
        except Exception as e:  # NameError / PydanticUserError precursor
            failures.append(f"{modname}.{fn.__name__}: {type(e).__name__}: {e}")
    assert not failures, "Unresolvable endpoint annotations:\n" + "\n".join(failures)


def test_gl_process_queue_biz_resolves_to_optional():
    """The specific regression: process_queue.biz must resolve to Optional[str]."""
    import gl_router
    hints = typing.get_type_hints(gl_router.process_queue)
    assert hints["biz"] == typing.Optional[str]
