from __future__ import annotations

import re


INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore (all|any|the)?\s*(previous|prior|system) instructions",
        r"reveal (environment variables|secrets|api keys)",
        r"change .* score to \d+",
        r"delete previous sources",
    )
]


def classify_untrusted_content(text: str) -> dict[str, object]:
    matches = [pattern.pattern for pattern in INJECTION_PATTERNS if pattern.search(text)]
    return {"untrusted": True, "prompt_injection_suspected": bool(matches), "matched_rules": matches}
