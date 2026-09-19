"""Small string helpers used across the reporting exports."""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Lowercase ASCII slug, collapsing runs of non-alphanumerics to a hyphen."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return _NON_ALNUM.sub("-", ascii_only.lower()).strip("-")


def truncate(value: str, limit: int) -> str:
    """Truncate to `limit` characters, appending an ellipsis when it was cut."""
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"
