"""Masking of secrets and personal data in logs.

The OpenScale runner already masks the exact value of every secret vault variable. The SDK masks again inside the
script, so values read with `secret=True` or the API token never reach print() in clear, and offers helpers for
personal data that must not be logged in full (LGPD/GDPR).
"""

from __future__ import annotations

import re

MASK = "••••••"


class Masker:
    def __init__(self):
        self._values: list[str] = []

    def add(self, value) -> None:
        v = str(value or "")
        if len(v) >= 4 and v not in self._values:
            self._values.append(v)
            self._values.sort(key=len, reverse=True)

    def mask(self, text: str) -> str:
        for v in self._values:
            text = text.replace(v, MASK)
        return text


def mask_phone(value) -> str:
    """'5592986081234' → '***1234'. Groups and short values become 'grupo'/'***'."""
    s = str(value or "").strip()
    if "@g.us" in s:
        return "grupo"
    digits = re.sub(r"\D", "", s)
    return f"***{digits[-4:]}" if len(digits) >= 8 else "***"


def mask_email(value) -> str:
    """'ana.souza@example.com' → 'a***@example.com'."""
    s = str(value or "").strip()
    if "@" not in s:
        return "***"
    user, domain = s.split("@", 1)
    return f"{user[:1]}***@{domain}"
