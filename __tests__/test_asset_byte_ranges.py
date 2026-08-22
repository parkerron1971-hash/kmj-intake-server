"""The media routes have to answer byte ranges.

Measured on production 2026-08-21: `GET /assets/demo.mp4` with
`Range: bytes=0-999` answered **200 and the whole 8.7MB**. iOS Safari
will not play a <video> whose server ignores Range, and every seek
re-pulls the entire file for everyone else. The home page put that video
behind a pill above the fold, so it is now the first media a phone
touches instead of something nobody scrolled to.

Starlette's own FileResponse grew range support, but in a release newer
than the one `fastapi==0.115.0` pins, so these assertions also guard the
day that pin moves and the hand-written responder could quietly stop
being reached.

The suffix case is the one worth naming: an mp4 player reaches for the
tail of the file first, to find the moov atom, and it asks with
`bytes=-N`. A server that only understands `bytes=N-M` looks like it
works right up until Safari tries to play something.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import public_site

VIDEO = "/assets/demo.mp4"
SIZE = (pathlib.Path(public_site.__file__).resolve().parent
        / "static" / "brand" / "solutionist-demo.mp4").stat().st_size


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(public_site.router)
    return TestClient(app)


def test_plain_get_advertises_range_support(client):
    r = client.get(VIDEO)
    assert r.status_code == 200
    assert r.headers["accept-ranges"] == "bytes"
    assert int(r.headers["content-length"]) == SIZE


def test_a_leading_range_returns_only_those_bytes(client):
    r = client.get(VIDEO, headers={"Range": "bytes=0-999"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 0-999/{SIZE}"
    assert int(r.headers["content-length"]) == 1000
    assert len(r.content) == 1000


def test_an_open_ended_range_runs_to_the_last_byte(client):
    start = SIZE - 500
    r = client.get(VIDEO, headers={"Range": f"bytes={start}-"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes {start}-{SIZE - 1}/{SIZE}"
    assert len(r.content) == 500


def test_a_suffix_range_returns_the_tail(client):
    """`bytes=-N` is how a player finds the moov atom."""
    r = client.get(VIDEO, headers={"Range": "bytes=-2048"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes {SIZE - 2048}-{SIZE - 1}/{SIZE}"
    assert len(r.content) == 2048


def test_the_bytes_are_the_right_bytes(client):
    """A range that reports the correct length but hands back the wrong
    slice would pass every assertion above and still play as garbage."""
    whole = (pathlib.Path(public_site.__file__).resolve().parent
             / "static" / "brand" / "solutionist-demo.mp4").read_bytes()
    r = client.get(VIDEO, headers={"Range": "bytes=1000000-1000255"})
    assert r.status_code == 206
    assert r.content == whole[1000000:1000256]


def test_a_range_past_the_end_is_refused_not_clamped(client):
    r = client.get(VIDEO, headers={"Range": f"bytes={SIZE + 10}-{SIZE + 99}"})
    assert r.status_code == 416
    assert r.headers["content-range"] == f"bytes */{SIZE}"


def test_a_garbled_range_serves_the_whole_file(client):
    """Better a working 200 than a wrong 206."""
    r = client.get(VIDEO, headers={"Range": "furlongs=0-9"})
    assert r.status_code == 200
    assert len(r.content) == SIZE
