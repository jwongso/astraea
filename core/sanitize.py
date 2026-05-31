"""Input sanitization - non-overridable security layer.

Strips control characters and rejects obvious prompt injection patterns
before any jurisdiction-specific processing occurs.
"""

import re
import unicodedata

from fastapi import HTTPException

_INJECTION_RE = re.compile(
    r"ignore\s+(previous|all|prior|above)\s+(instructions?|rules?|prompts?)"
    r"|forget\s+(previous|all|prior|above)\s+(instructions?|rules?|prompts?)"
    r"|you\s+are\s+now\s+(a\s+|an\s+)?"
    r"|act\s+as\s+(if\s+)?(you\s+are\s+)?"
    r"|pretend\s+(you|to\s+be)"
    r"|system\s*prompt\s*:"
    r"|<\s*system\s*>",
    re.IGNORECASE,
)


def sanitize_question(text: str, max_chars: int = 1200) -> str:
    """Strip control characters, enforce length, detect prompt injection.

    Raises HTTPException 400 on any violation.
    This function is called by core/api.py before any jurisdiction code runs.
    """
    text = "".join(
        c for c in text
        if unicodedata.category(c) not in ("Cc", "Cf") or c in "\n\t"
    )
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail={"error": "Question must not be empty."})
    if len(text) > max_chars:
        raise HTTPException(
            status_code=400,
            detail={"error": f"Question too long (max {max_chars} characters)."},
        )
    if _INJECTION_RE.search(text):
        raise HTTPException(
            status_code=400,
            detail={"error": "Question contains content that cannot be processed."},
        )
    return text
