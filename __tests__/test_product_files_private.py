"""Paid files are only reachable by people who paid.

store_files.py has said "NO public access" since the day it was
written. The bucket was public=true. An anonymous GET of
/object/public/product-files/<path> returned 200 with the file body and
no credentials — so the 300-second signed URL, the rate limit and the
HMAC purchase token in front of it were all decorative, and anyone with
a path could take a paid file without buying it.

Nothing leaked, because the bucket was empty. It would have fired the
first time somebody sold a digital product.

The docstring was not lying so much as unverified, which is the part
worth fixing: a claim about infrastructure that nothing checks drifts
from the infrastructure silently and in whichever direction is worse.
"""
from __future__ import annotations

import ast
import inspect
import os
import pathlib
import sys
import textwrap

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import store_files

SRC = pathlib.Path(store_files.__file__).read_text(encoding="utf-8")


def _code(src: str) -> str:
    """Executable code only — this file's own prose says the very
    strings it asserts are absent."""
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


CODE = _code(SRC)


class TestNothingServesThesePublicly:
    def test_the_module_never_builds_a_public_object_url(self):
        """The one construction that would bypass every gate in this
        file. Checked against code with docstrings stripped, because the
        module docstring now discusses this exact URL shape."""
        assert "object/public" not in CODE

    def test_download_goes_through_a_signed_url(self):
        assert "storage_signed_url" in CODE
        signed = _code(inspect.getsource(store_files.storage_signed_url))
        assert "object/sign" in signed

    def test_the_signed_url_actually_expires(self):
        """A signed URL with no expiry is a public URL with extra steps."""
        signed = inspect.getsource(store_files.storage_signed_url)
        assert "expiresIn" in signed

    def test_the_bucket_name_is_not_duplicated_as_a_literal(self):
        """One constant, so closing the bucket does not have to find
        every place its name was retyped."""
        assert store_files.PRODUCT_BUCKET == "product-files"
        assert CODE.count('"product-files"') + CODE.count("'product-files'") == 1


class TestTheRequirementIsWrittenDownWhereItCanBeFound:
    def test_the_docstring_states_it_as_a_requirement(self):
        """Not decoration: the next person to touch bucket settings has
        to be able to find out that this module depends on private."""
        low = SRC.lower()
        assert "requirement of this module" in low
        assert "public=true" in low        # what it was actually found to be


LIVE = os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")


@pytest.mark.skipif(not LIVE, reason=(
    "needs SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY. This is the only "
    "assertion that can catch the bucket being flipped back to public, "
    "and it does not run in the normal suite — so it is a check you have "
    "to point at production deliberately, not a guarantee you already "
    "have. scripts/close_product_files_bucket.sh is the one that proves "
    "it end to end."))
def test_the_live_bucket_is_private():
    import httpx
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    r = httpx.get(f"{base}/storage/v1/bucket/{store_files.PRODUCT_BUCKET}",
                  headers={"apikey": key, "Authorization": f"Bearer {key}"},
                  timeout=20)
    assert r.status_code == 200, r.text[:200]
    assert r.json().get("public") is False, (
        "product-files is PUBLIC — every paid download is fetchable by "
        "anyone with the path. Run scripts/close_product_files_bucket.sh")
