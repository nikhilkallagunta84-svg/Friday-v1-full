from __future__ import annotations

import re

# Matches a phone number that has at least 7 digits total when stripped of
# formatting (covers NANP 10-digit, E.164 +CC..., and short codes longer than 6).
# Permissive on purpose so transcripts auto-redact stray numbers the LLM repeats.
_PHONE_NUMBER_RE = re.compile(
    r"(?:(?<!\d)|(?<=\s))"            # word boundary that allows leading '+'
    r"\+?\d[\d\s\-().]{6,}\d"          # at least 7 digit-bearing characters
    r"(?!\d)"
)

SENSITIVE_PATTERNS = [
    re.compile(r"\bpassword\b"),
    re.compile(r"\bpasscode\b"),
    re.compile(r"\blogin\s+code\b"),
    re.compile(r"\brecovery\s+code\b"),
    re.compile(r"\btwo[-\s]?factor\b"),
    re.compile(r"\b2fa\b"),
    re.compile(r"\bmfa\b"),
]

VISUAL_SENSITIVE_PATTERNS = SENSITIVE_PATTERNS + [
    re.compile(r"\bcaptcha\b"),
    re.compile(r"\bsecurity\s+question\b"),
]

_REDACT_RULES = [
    (re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b(?:sk|re)_[A-Za-z0-9_\-]{8,}\b"), "[REDACTED_SECRET]"),
    (re.compile(r"\b[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[REDACTED_CARD]"),
]

_REDACT_LABELED_SECRET = re.compile(
    r"\b(password|passcode|token|secret|api\s*key)\b\s*[:=]?\s*[^\s,;]+",
    re.IGNORECASE,
)


def contains_sensitive_text(text: str) -> bool:
    lowered = text.lower()
    return any(p.search(lowered) for p in SENSITIVE_PATTERNS)


def contains_visual_sensitive_text(text: str) -> bool:
    lowered = text.lower()
    return any(p.search(lowered) for p in VISUAL_SENSITIVE_PATTERNS)


def redact_sensitive_text(text: str) -> str:
    clean = str(text)
    for pattern, replacement in _REDACT_RULES:
        clean = pattern.sub(replacement, clean)
    clean = _REDACT_LABELED_SECRET.sub(
        lambda m: f"{m.group(1)} {'[REDACTED_SECRET]' if 'api' in m.group(1).lower() else '[REDACTED]'}",
        clean,
    )
    # Mask any phone-number-shaped runs to their last 4 digits.
    clean = _PHONE_NUMBER_RE.sub(lambda m: redact_phone_number(m.group(0)), clean)
    return clean


def redact_phone_number(number: str) -> str:
    """Mask a phone number to ``***-***-1234`` form.

    Keeps the last 4 digits so logs remain useful for identifying which call
    happened without exposing the full number. Numbers shorter than 4 digits
    return a fully-redacted placeholder.
    """

    if not isinstance(number, str):
        return "***-***-****"
    digits = re.sub(r"\D+", "", number)
    if not digits:
        return "***-***-****"
    if len(digits) < 4:
        return "***-***-****"
    return f"***-***-{digits[-4:]}"
