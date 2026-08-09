"""Text normalisation shared by the extraction layers."""

from __future__ import annotations

import html
import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")

#: Zero-width space, ZWNJ, ZWJ and the BOM. Invisible, but not matched by \s,
#: so they survive naive trimming and then break exact-match comparisons later.
_INVISIBLE = re.compile("[​-‍﻿]")

#: Separators that appear between a product name and the shop's own name.
_TITLE_SEPARATORS = ("|", "–", "—", " - ", "::")

_BOILERPLATE = re.compile(
    r"\s*(shop online|online shopping|buy online|official (site|store|online store)|"
    r"free shipping|official)\s*",
    re.I,
)


def clean(value: object) -> str | None:
    """Collapse whitespace, decode entities, drop zero-width characters."""
    if value is None:
        return None
    if not isinstance(value, str):
        if isinstance(value, (int, float)):
            return str(value)
        return None

    text = _INVISIBLE.sub("", html.unescape(value))
    text = _WHITESPACE.sub(" ", text).strip()
    return text or None


def normalise_key(value: str) -> str:
    """Case/space/punctuation-insensitive key.

    Variants extracted by different layers ("UK 8" from JSON-LD, "uk-8" from a
    button) have to collapse onto the same key, or they show up twice - and,
    worse, a restock on one would not match the stored row for the other.
    """
    folded = unicodedata.normalize("NFKD", value).lower()
    return re.sub(r"[^0-9a-z]", "", folded)


def strip_site_suffix(title: str, store_names: list[str] | None = None) -> str:
    """Turn "Leather Jacket | ZARA" into "Leather Jacket"."""
    names = store_names or []
    out = title

    for sep in _TITLE_SEPARATORS:
        parts = out.split(sep)
        if len(parts) < 2:
            continue
        kept = [
            part
            for part in parts
            if part.strip()
            and not any(normalise_key(part) == normalise_key(name) for name in names if name)
            and not _BOILERPLATE.fullmatch(part)
        ]
        if kept and len(kept) < len(parts):
            out = sep.join(kept)

    out = re.sub(r"^\s*(buy|shop|order)\s+", "", out, flags=re.I)
    out = re.sub(r"\s+(online|online at best prices?|at best prices? in india)\s*$", "", out, flags=re.I)
    return out.strip() or title.strip()


def title_case(value: str) -> str:
    return " ".join(word[:1].upper() + word[1:] for word in re.split(r"[\s\-_]+", value) if word)
