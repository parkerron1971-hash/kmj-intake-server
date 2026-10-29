# __tests__/test_sender_domain_verified.py
#
# Every email the platform sends goes out from a domain the email service
# has verified. On 2026-10-20 a team invite to Love City's executive pastor
# failed with Resend's 403 "The solutionist.studio domain is not verified":
# team invites, accountant invites, contractor payment notes and reports
# all sent from @solutionist.studio, so none of them ever arrived (the
# invite page fell back to "share this link"). Kevin: "mysolutionist.app
# is good". This scan fails if any source file sends from the unverified
# domain again.

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
UNVERIFIED = re.compile(r"[\w.+-]+@solutionist\.studio\b")
SKIP_DIRS = {"output", "node_modules", ".git", "__pycache__", "__tests__", "static", "sites"}


def test_no_source_file_sends_from_the_unverified_domain():
    found = []
    for path in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in UNVERIFIED.finditer(text):
            found.append(f"{path.relative_to(ROOT)}: {m.group(0)}")
    assert not found, ("email addresses on the unverified solutionist.studio domain (Resend refuses them; "
                       "send from mysolutionist.app): " + ", ".join(found))
