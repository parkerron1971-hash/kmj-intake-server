"""
The band registry: assembles every vertical's module into the two maps
the rest of the product reads.

Adding a vertical is adding a module and one line to MODULES. Nothing
else changes, which is precisely what lets eight agents work at once.
"""
from typing import Any, Dict, List

from workspace_benchmarks.bands import (
    consultant, lawyer, ministry, nonprofit, salon, therapist, trades,
)

MODULES = [salon, trades, therapist, ministry, consultant, nonprofit, lawyer]

BANDS: Dict[str, Dict[str, Any]] = {}
KEYS_FOR_VERTICAL: Dict[str, List[str]] = {}

for _m in MODULES:
    _clash = set(_m.BANDS) & set(BANDS)
    if _clash:
        # Two verticals claiming one key would make the panel's reading
        # depend on import order, which is the worst kind of bug to find:
        # the number is right and the sentence under it is another
        # industry's. Fail at import instead.
        raise RuntimeError(
            f"{_m.__name__} redefines band(s) already registered: {sorted(_clash)}")
    BANDS.update(_m.BANDS)
    for _v in _m.VERTICALS:
        if _v in KEYS_FOR_VERTICAL:
            raise RuntimeError(f"{_v!r} is claimed by two band modules")
        KEYS_FOR_VERTICAL[_v] = list(_m.KEYS)
    _unknown = [k for k in _m.KEYS if k not in _m.BANDS]
    if _unknown:
        raise RuntimeError(f"{_m.__name__}.KEYS names bands it does not define: {_unknown}")

del _m, _v, _clash, _unknown
