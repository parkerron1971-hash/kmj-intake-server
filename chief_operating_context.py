"""One fresh, evidence-labelled operating profile for unattended work."""
from __future__ import annotations
import business_learning


def current_context(business):
    # Load explicitly: a failed read must not silently become permission to
    # work without an owner's latest correction. No cross-turn cache.
    row = business_learning.load(business['id'])
    if not row:
        return ''
    block = business_learning.context_block(business, max_chars=6000, profile_row=row)
    return ('\n\nCURRENT BUSINESS RULES (revision ' + str(row['revision']) + '):\n' + block +
            '\nOwner corrections govern this work. Assumptions and research are not owner approval. '
            'A remembered rule does not prove that a calendar, offering or other live record was changed. '
            'Read the affected records before acting; propose resolving any conflict.')
