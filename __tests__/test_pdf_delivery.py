"""Downloading a document you just approved.

Three separate faults sat on top of each other in this path, and the
symptom for all three was the same useless string — "PDF generation
failed" — so none of them was distinguishable from the others.

  1. `/agents/contract/pdf` required a contact_id, and the queue row
     hid its Download button without one. Every nonprofit governance
     document (board list, conflict-of-interest policy, whistleblower
     policy, document retention policy, nondiscrimination statement,
     mission & history) is prepared for the business itself and carries
     no contact, so not one of them could be downloaded at all.

  2. The upload went out under the ANON key. The 2026-08-09 write
     lockdown had replaced the proposals insert policy with one scoped
     to `authenticated` + business access, which anon fails:
     "new row violates row-level security policy". Verified against
     live storage, not inferred.

  3. The returned URL was `/storage/v1/object/public/proposals/...`,
     and the 2026-08-10 vault migration set that bucket `public =
     false`. A public URL on a private bucket does not answer 403 — it
     answers 400 "Bucket not found", which reads like the bucket was
     deleted. foundation_agent had the same fault on
     `business-documents`, so "Open PDF" on a Foundation Track
     document led to a JSON error page too.

(2) and (3) broke every download in the app, proposals included, on
2026-08-10. (1) is why the nonprofit documents never had one.
"""

import inspect
import io
import pathlib
import sys
import tokenize

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import contract_agent as ca  # noqa: E402
import foundation_agent as fa  # noqa: E402
import storage_links  # noqa: E402


def _code(fn) -> str:
    """Source with comments and strings stripped out.

    These tests assert on what the function DOES, and every one of them
    describes the old broken URL in a comment right beside the fix. A
    plain substring search over the source would match the explanation
    and pass — or here, fail — on prose. Only tokens count.
    """
    src = inspect.getsource(fn)
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def _names(fn) -> str:
    """Source with comments stripped but string literals KEPT — for
    assertions about URLs and messages the function actually emits."""
    src = inspect.getsource(fn)
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and tok.string.lstrip("rbfu")[:3] in ('"""', "'''"):
            continue  # a docstring, not a value
        out.append(tok.string)
    return " ".join(out)


# ── 1. The counterparty is optional ──────────────────────────────────

def test_pdf_request_does_not_require_a_contact():
    assert not ca.PdfRequest.model_fields["contact_id"].is_required()
    req = ca.PdfRequest(business_id="b1", proposal_body="x", subject="Board List")
    assert req.contact_id is None


def test_the_handler_only_fetches_a_contact_when_it_has_one():
    """A required fetch is what made this 404 — the guard has to be on
    the fetch itself, not on a truthiness check further down."""
    src = inspect.getsource(ca.contract_pdf)
    fetch = src.index("/contacts?id=eq.")
    guard = src.index("if req.contact_id:")
    assert guard < fetch, "the contact fetch is not behind the guard"


def test_a_document_with_no_contact_is_addressed_to_the_business():
    """Not "Recipient". The party it is FOR is the business, and its
    legal name is what belongs on the Prepared-for line."""
    src = inspect.getsource(ca.contract_pdf)
    assert "business_identity.get_identity" in src
    assert "legal_name" in src


def test_the_storage_path_still_starts_with_the_business_id():
    """Both storage policies key on the FIRST path segment via
    storage_business_id(). A contactless path that dropped it, or put
    anything else first, would be refused by RLS."""
    src = inspect.getsource(ca._upload_pdf_to_supabase)
    assert 'f"{business_id}/{contact_id}/' in src
    call = inspect.getsource(ca.contract_pdf)
    assert 'req.contact_id or "general"' in call


# ── 2. The upload is service-role, not anon ──────────────────────────

def test_the_upload_does_not_use_the_anon_key():
    """Live storage refuses it: 403, "new row violates row-level
    security policy". The bucket's insert policy is `authenticated`
    plus a business check, and the backend holds no user JWT here."""
    code = _code(ca._upload_pdf_to_supabase)
    assert "_supabase_anon" not in code
    assert "storage_links . service_headers" in code


# ── 3. Delivery is a signed URL, from every minting site ─────────────

def test_the_contract_endpoint_returns_a_signed_url():
    assert "storage_links . signed_url" in _code(ca._upload_pdf_to_supabase)
    assert "object/public" not in _names(ca._upload_pdf_to_supabase)


def test_the_foundation_renderer_returns_a_signed_url():
    assert "storage_links . signed_url" in _code(fa.render_document_pdf)
    assert "object/public" not in _names(fa.render_document_pdf)


def test_an_unsignable_link_says_the_file_was_saved():
    """The bytes are already filed at that point. Reporting it as a
    failed render sends the practitioner to generate it again — and
    spend the credit again — for a document that exists."""
    for fn in (ca._upload_pdf_to_supabase, fa.render_document_pdf):
        src = inspect.getsource(fn)
        assert "sign" in src.lower()
        assert "saved" in src.lower() or "filed in your Documents" in src


# ── The guard that would have caught this on 2026-08-10 ──────────────

_PRIVATE_BUCKETS = ("proposals", "business-documents")


def test_no_module_builds_a_public_url_for_a_private_bucket():
    """The regression, stated as a rule.

    `public = false` on a bucket and a hand-concatenated
    `/object/public/<bucket>/` URL are a contradiction that nothing in
    the stack reports — Supabase answers "Bucket not found" and the app
    calls it a generation failure. Anything that needs to hand out a
    link to one of these two goes through storage_links.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for py in root.glob("*.py"):
        if py.name == "storage_links.py":
            continue
        raw = py.read_text(encoding="utf-8", errors="replace")
        try:
            # Joined with NO separator and then stripped of whitespace,
            # because since 3.12 tokenize splits an f-string into its
            # pieces (PEP 701): `object/public/{PDF_BUCKET}` arrives as
            # four tokens, so a spaced join makes the interpolated form
            # unmatchable — which is exactly how this guard first sat
            # green over a reverted fix.
            text = "".join(
                t.string for t in
                tokenize.generate_tokens(io.StringIO(raw).readline)
                if t.type != tokenize.COMMENT)
        except (tokenize.TokenError, IndentationError, SyntaxError):
            text = raw  # unparseable file: fall back to the literal read
        text = "".join(text.split())
        for bucket in _PRIVATE_BUCKETS:
            if f"object/public/{bucket}" in text:
                offenders.append(f"{py.name} -> {bucket}")
        # ...and the interpolated form, which a search for the bucket's
        # literal name misses entirely.
        for const in ("DOCS_BUCKET", "PDF_BUCKET"):
            if "object/public/{" + const + "}" in text:
                offenders.append(f"{py.name} -> interpolated {const}")
    assert not offenders, f"public URL on a private bucket: {offenders}"


def test_the_ttl_is_bounded():
    """A signed URL is a bearer token for a client record. Long enough
    for a human pause, short enough not to be a durable credential."""
    assert 300 <= storage_links.SIGNED_URL_TTL_SECONDS <= 3600
