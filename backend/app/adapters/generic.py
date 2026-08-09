"""The adapter that handles every store on the internet.

Note what is *not* here: no selectors, no extraction. All of that lives in the
layered pipeline, which runs for every page whichever adapter is chosen. This
adapter only contributes what can be derived from a URL.
"""

from __future__ import annotations

import re

from app.adapters.base import StoreAdapter
from app.detection.layers import PageContext
from app.detection.stores import find_store_definition
from app.detection.urls import looks_like_non_product_url, looks_like_product_url


class GenericAdapter(StoreAdapter):
    slug = "generic"
    label = "Generic"

    def can_handle(self, ctx: PageContext) -> bool:  # noqa: ARG002
        return True

    def is_product_page(self, ctx: PageContext) -> bool | None:
        match = find_store_definition(ctx.hostname)
        if match and any(re.search(pattern, ctx.url, re.I) for pattern in match[0].product_url_patterns):
            return True
        if looks_like_non_product_url(ctx.url):
            return False
        if looks_like_product_url(ctx.url):
            return True
        return None  # no opinion; let the content signals decide
