"""A model of business_settings.merge for tests that hold the business row
themselves (a `state["biz"]` dict) rather than a FakeSB.

It applies the database's merge (business_settings.merge_at, the same rule
as merge_business_settings) to that row's settings and records each call, so
a test can say both what the row holds after and that only the named keys
were sent: the point of the change is that a write never carries the rest of
the object.

    calls = install(monkeypatch, lambda bid: state["biz"])
    ...
    assert calls == [{"id": BIZ, "set": {"founding_church": place}, "drop": [], "under": []}]
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


def install(monkeypatch, row_for: Callable[[str], Optional[Dict[str, Any]]],
            fail: Callable[[], bool] = lambda: False,
            into: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
    """`into`: a test's own ordered call log, which gets ("settings", call)
    beside its other calls."""
    import business_settings
    calls: List[Dict[str, Any]] = []

    def merge(business_id, set=None, drop=(), under=()):
        call = {"id": str(business_id), "set": dict(set or {}), "drop": list(drop or ()),
                "under": list(under or ())}
        calls.append(call)
        if into is not None:
            into.append(("settings", call))
        if fail():
            return None
        row = row_for(str(business_id))
        if row is None:
            return None
        row["settings"] = business_settings.merge_at(row.get("settings"), call["under"],
                                                     call["set"], call["drop"])
        return dict(row["settings"])

    monkeypatch.setattr(business_settings, "merge", merge)
    return calls
