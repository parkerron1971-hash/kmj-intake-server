"""chief_source() — the text the prompt tests read.

Until 2026-09-04 twenty test files read chief_of_staff.py as source to
assert on prompt literals. The prompt composers now live in
chief_prompt.py; the literals are the same, in two files. This joins
them so every existing assertion reads exactly what it read before.
"""
import inspect


def chief_source() -> str:
    import chief_of_staff
    import chief_prompt
    return inspect.getsource(chief_of_staff) + "\n" + inspect.getsource(chief_prompt)
