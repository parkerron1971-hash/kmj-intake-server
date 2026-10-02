"""
test_spend_guard_day_start.py — the daily window's timestamp survives a
query string. isoformat() gives "+00:00", and a plus in a URL is a space,
which PostgREST rejects; the guard then fails open and reads zero spend.
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import spend_guard


def test_day_start_is_url_safe_and_utc_midnight():
    v = spend_guard._utc_day_start_iso()
    assert "+" not in v and " " not in v
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T00:00:00Z", v), v
