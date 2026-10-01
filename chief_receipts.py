"""Plain completion language from server receipts, never from draft prose."""
from __future__ import annotations

import re


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def receipt_text(receipt):
    """Retain both the target and result; a contact name alone says no outcome."""
    label = _text(receipt.get("label"))
    result = _text(receipt.get("result"))
    if receipt.get("needs_confirmation"):
        # Held results contain model instructions, while labels are read-backs.
        return label
    if receipt.get("type") == "create_task" and result == "added" and "Task:" in label:
        return label  # the existing task narrator supplies the completion verb
    if not label:
        return result
    if not result or result.casefold() in label.casefold():
        return label
    return f"{label.rstrip('.')}: {result}"


def _transition(receipt):
    if receipt.get("type") != "update_contact_status" or receipt.get("failed") or receipt.get("needs_confirmation"):
        return None
    match = re.fullmatch(r"([a-z_]+)\s*\u2192\s*([a-z_]+)", _text(receipt.get("result")))
    name = _text(receipt.get("label"))
    return (match[1], match[2], name) if match and name else None


def receipt_lines(receipts):
    """Group only matching confirmed status transitions; pending results stay pending."""
    groups = {}
    for receipt in receipts:
        transition = _transition(receipt)
        if transition:
            previous, current, name = transition
            groups.setdefault((previous, current), []).append(name)
    emitted, lines = set(), []
    for receipt in receipts:
        transition = _transition(receipt)
        if not transition:
            value = receipt_text(receipt)
            if value:
                lines.append(value)
            continue
        previous, current, _ = transition
        key = (previous, current)
        if key in emitted:
            continue
        emitted.add(key)
        names = groups[key]
        if len(names) == 1:
            lines.append(f"Moved {names[0]} from {previous} to {current}.")
        else:
            count = {2: "two", 3: "three", 4: "four", 5: "five"}.get(len(names), str(len(names)))
            noun = "leads" if previous == "lead" else f"contacts from {previous}"
            lines.append(f"Moved {count} {noun} to {current}: {', '.join(names)}.")
    return lines
