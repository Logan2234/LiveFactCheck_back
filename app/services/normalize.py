"""Text normalization shared by the verification cache and claim dedup.

Pure logic — no FastAPI, no I/O. Both features compare utterances/claims for
equality after collapsing the cosmetic differences (case, spacing, trailing
punctuation) that shouldn't count as distinct text.
"""

import re

_WHITESPACE = re.compile(r"\s+")
# Trailing punctuation/quotes that don't change meaning when comparing text.
_TRAILING = " \t\n.,;:!?…\"'»«)]}"


def normalize(text: str) -> str:
    """Lowercase, collapse internal whitespace, strip trailing punctuation.

    Equality-only normalization: two utterances that differ only in case or
    spacing map to the same key. Deliberately conservative — it does NOT do fuzzy
    matching, so "4 %" and "14 %" stay distinct.
    """
    collapsed = _WHITESPACE.sub(" ", text).strip()
    return collapsed.lower().rstrip(_TRAILING)
