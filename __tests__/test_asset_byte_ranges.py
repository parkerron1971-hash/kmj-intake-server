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

BRAND = pathlib.Path(public_site.__file__).resolve().parent / "static" / "brand"

# Both routes, and film.mp4 first because it is the one the site plays.
# The original suite only covered demo.mp4; when the site swapped to the
# new cut on 2026-08-22 that left the archive URL guarded and the live one
# bare, which is exactly backwards.
ROUTES = [
    ("/assets/film.mp4", "solutionist-film.mp4"),
    ("/assets/demo.mp4", "solutionist-demo.mp4"),
]


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(public_site.router)
    return TestClient(app)


@pytest.fixture(params=ROUTES, ids=[r[0] for r in ROUTES])
def video(request):
    url, name = request.param
    return url, (BRAND / name).stat().st_size


def test_plain_get_advertises_range_support(client, video):

    url, size = video
    r = client.get(url)
    assert r.status_code == 200
    assert r.headers["accept-ranges"] == "bytes"
    assert int(r.headers["content-length"]) == size


def test_a_leading_range_returns_only_those_bytes(client, video):

    url, size = video
    r = client.get(url, headers={"Range": "bytes=0-999"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 0-999/{size}"
    assert int(r.headers["content-length"]) == 1000
    assert len(r.content) == 1000


def test_an_open_ended_range_runs_to_the_last_byte(client, video):

    url, size = video
    start = size - 500
    r = client.get(url, headers={"Range": f"bytes={start}-"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes {start}-{size - 1}/{size}"
    assert len(r.content) == 500


def test_a_suffix_range_returns_the_tail(client, video):
    """`bytes=-N` is how a player finds the moov atom."""

    url, size = video
    r = client.get(url, headers={"Range": "bytes=-2048"})
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes {size - 2048}-{size - 1}/{size}"
    assert len(r.content) == 2048


def test_the_bytes_are_the_right_bytes(client, video):
    """A range that reports the correct length but hands back the wrong
    slice would pass every assertion above and still play as garbage."""

    url, size = video
    whole = (BRAND / dict(ROUTES)[url]).read_bytes()
    r = client.get(url, headers={"Range": "bytes=1000000-1000255"})
    assert r.status_code == 206
    assert r.content == whole[1000000:1000256]


def test_a_range_past_the_end_is_refused_not_clamped(client, video):

    url, size = video
    r = client.get(url, headers={"Range": f"bytes={size + 10}-{size + 99}"})
    assert r.status_code == 416
    assert r.headers["content-range"] == f"bytes */{size}"


def test_a_garbled_range_serves_the_whole_file(client, video):
    """Better a working 200 than a wrong 206."""

    url, size = video
    r = client.get(url, headers={"Range": "furlongs=0-9"})
    assert r.status_code == 200
    assert len(r.content) == size
