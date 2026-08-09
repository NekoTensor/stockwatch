"""URL normalisation and the product knowledge a URL carries."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_PARAMS = [
    re.compile(pattern, re.I)
    for pattern in (
        r"^utm_", r"^ic_", r"^gclid$", r"^gclsrc$", r"^dclid$", r"^fbclid$", r"^msclkid$",
        r"^igshid$", r"^ttclid$", r"^srsltid$", r"^_branch_match_id$", r"^_bta_", r"^mc_[ce]id$",
        r"^ref$", r"^ref_$", r"^referrer$", r"^source$", r"^sourceid$", r"^cm_(sp|re|mmc)$",
        r"^pd_rd_", r"^pf_rd_", r"^psc$", r"^th$", r"^qid$", r"^sr$", r"^spm$", r"^tracker$",
        r"^camp$", r"^creative(ASIN)?$", r"^linkCode$", r"^tag$", r"^ascsubtag$",
    )
]

_ID_PATTERNS = (
    re.compile(r"/dp/([A-Z0-9]{10})(?:[/?]|$)", re.I),
    re.compile(r"/gp/product/([A-Z0-9]{10})(?:[/?]|$)", re.I),
    re.compile(r"/itm/(\d+)", re.I),
    re.compile(r"-p(\d{6,})\.html", re.I),
    re.compile(r"/productpage\.(\d{6,})\.html", re.I),
    re.compile(r"/p/([A-Za-z0-9_-]{4,})(?:[/?]|$)", re.I),
    re.compile(r"/product/([A-Za-z0-9_-]{4,})(?:[/?]|$)", re.I),
    re.compile(r"/(\d{5,})/buy(?:[/?]|$)", re.I),
    re.compile(r"[?&](?:pid|productId|product_id|skuId|itemId)=([^&]+)", re.I),
    re.compile(r"/(\d{6,})(?:[/?]|$)"),
)

_PRODUCT_URL_HINTS = (
    re.compile(r"/dp/", re.I),
    re.compile(r"/gp/product/", re.I),
    re.compile(r"/p/", re.I),
    re.compile(r"/products?/", re.I),
    re.compile(r"/pd/", re.I),
    re.compile(r"/itm/", re.I),
    re.compile(r"/buy\b", re.I),
    re.compile(r"-p\d{4,}\.html", re.I),
    re.compile(r"productpage\.\d+\.html", re.I),
    re.compile(r"/[^/]+-\d{5,}(?:\.html)?$", re.I),
)

_NON_PRODUCT_URL = (
    re.compile(r"/cart\b"), re.compile(r"/checkout\b"), re.compile(r"/basket\b"),
    re.compile(r"/bag\b"), re.compile(r"/wishlist\b"), re.compile(r"/orders?\b"),
    re.compile(r"/account\b"), re.compile(r"/login\b"), re.compile(r"/signin\b"),
    re.compile(r"/register\b"), re.compile(r"/search\b"), re.compile(r"/category\b"),
    re.compile(r"/categories\b"), re.compile(r"/collections?/?$"), re.compile(r"/help\b"),
)


def normalise_hostname(url: str) -> str:
    try:
        return re.sub(r"^www\d*\.", "", (urlparse(url).hostname or "").lower())
    except ValueError:
        return ""


def clean_url(url: str) -> str:
    """Strip campaign noise while preserving everything that selects the product."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not any(pattern.match(key) for pattern in _TRACKING_PARAMS)
    ]
    # Amazon bakes navigation history into the path; it changes every visit.
    path = re.sub(r"/ref=[^/]+", "", parsed.path, flags=re.I)

    return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, urlencode(query), ""))


def product_id_from_url(url: str) -> str | None:
    for pattern in _ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def looks_like_product_url(url: str) -> bool:
    parsed = urlparse(url)
    if any(pattern.search(parsed.path) for pattern in _PRODUCT_URL_HINTS):
        return True
    return bool(re.search(r"[?&](pid|productId|product_id|skuId|itemId)=", parsed.query, re.I))


def looks_like_non_product_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if path in {"", "/"}:
        return True
    return any(pattern.search(path) for pattern in _NON_PRODUCT_URL)
