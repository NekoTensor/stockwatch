"""The detection pipeline, server side.

    store identified
       -> every generic layer runs (independently, failure-isolated)
       -> results merged field-by-field by trust
       -> the store adapter fills any remaining gaps
       -> normalised into one ProductSnapshot
       -> scored, so the caller can tell "found it" from "this isn't a product"

No step above knows the name of a single store. That is the contract, and it is
the same contract the extension keeps.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.detection.layers import (
    Candidate,
    DomSignals,
    PageContext,
    extract_dom,
    extract_embedded,
    extract_jsonld,
    extract_metatags,
    extract_microdata,
    extract_opengraph,
    has_product_og_type,
)
from app.detection.models import ProductSnapshot, VariantSnapshot
from app.detection.stores import identify_store
from app.detection.urls import (
    clean_url,
    looks_like_non_product_url,
    looks_like_product_url,
    normalise_hostname,
    product_id_from_url,
)
from app.detection.util.availability import merge as merge_availability
from app.detection.util.price import currency_from_hostname, quantise
from app.detection.util.text import clean, normalise_key
from app.models.enums import StockStatus

logger = logging.getLogger(__name__)

#: Trust order. Structured data first, rendered pixels last. `meta` sits below
#: `dom` because it is mostly <title>, which is SEO copy.
PRIORITY: dict[str, int] = {
    "jsonld": 100,
    "microdata": 85,
    "embedded": 80,
    "opengraph": 70,
    "dom": 40,
    "meta": 35,
    "url": 30,
    "adapter": 0,  # applied separately: adapters fill gaps, they do not compete
}

SCALAR_FIELDS = (
    "name", "brand", "description", "sku", "product_id", "category",
    "canonical_url", "image_url", "currency", "current_price", "original_price",
)


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value is StockStatus.UNKNOWN


def merge_variant_sets(sets: list[tuple[str, list[VariantSnapshot]]]) -> list[VariantSnapshot]:
    """Best names meet best availability.

    The set with the best combination of size, trust and *known* availability
    becomes the skeleton; the others then fill in availability and SKUs for
    matching names. This is the Zara/H&M case: structured data names the sizes,
    the DOM knows which buttons are greyed out.
    """
    populated = [(source, variants) for source, variants in sets if variants]
    if not populated:
        return []

    def score(entry: tuple[str, list[VariantSnapshot]]) -> float:
        source, variants = entry
        known = sum(1 for variant in variants if variant.availability is not StockStatus.UNKNOWN)
        return PRIORITY.get(source, 0) / 10 + len(variants) + (known / len(variants)) * 6

    primary_source, primary = max(populated, key=score)
    merged = [
        VariantSnapshot(
            id=variant.id,
            name=variant.name,
            type=variant.type,
            availability=variant.availability,
            sku=variant.sku,
            price=variant.price,
            source=variant.source,
        )
        for variant in primary
    ]
    index = {normalise_key(variant.name): variant for variant in merged}

    for source, variants in populated:
        if source == primary_source:
            continue
        for variant in variants:
            target = index.get(normalise_key(variant.name))
            if target is None:
                continue
            if target.availability is StockStatus.UNKNOWN:
                target.availability = variant.availability
                if variant.availability is not StockStatus.UNKNOWN:
                    target.source = variant.source
            elif variant.availability is not StockStatus.UNKNOWN:
                target.availability = merge_availability(target.availability, variant.availability)
            target.sku = target.sku or variant.sku
            target.price = target.price or variant.price

    return merged


def _run_layer(name: str, fn, warnings: list[str]) -> Candidate | None:  # noqa: ANN001
    """One misbehaving layer must never cost us the other five."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Layer %s failed: %s", name, exc)
        warnings.append(f"{name} extraction failed: {exc}")
        return None


def _score_page(
    signals: DomSignals,
    *,
    jsonld: bool,
    microdata: bool,
    embedded: bool,
    og_product: bool,
    url_positive: bool,
    url_negative: bool,
    adapter_verdict: bool | None,
) -> int:
    """Additive: no single signal carries a page, none sinks one alone."""
    score = 0

    if jsonld:
        score += 30
    if microdata:
        score += 18
    if og_product:
        score += 18
    if embedded:
        score += 14

    if signals.has_title:
        score += 10
    if signals.has_price:
        score += 18
    if signals.has_variants:
        score += 10
    if signals.has_buy_button:
        score += 14
    if signals.has_breadcrumb:
        score += 4
    if signals.has_gallery:
        score += 4

    if url_positive:
        score += 10
    if url_negative:
        score -= 25
    # A repeated grid of priced, linked cards is a category page.
    if signals.listing_grid:
        score -= 30

    if adapter_verdict is True:
        score += 15
    elif adapter_verdict is False:
        score -= 30

    return max(0, min(100, score))


def detect_product(
    html: str,
    url: str,
    page_globals: dict[str, Any] | None = None,
) -> ProductSnapshot:
    """Run the whole pipeline over one page."""
    # lxml is markedly faster and far more forgiving of real-world markup than
    # the stdlib parser; the fallback keeps detection working if it is missing.
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001 - parser availability, not page content
        soup = BeautifulSoup(html, "html.parser")

    hostname = normalise_hostname(url)
    store = identify_store(hostname)
    ctx = PageContext(
        soup=soup,
        url=url,
        hostname=hostname,
        store_names=[store.name, store.domain, store.domain.split(".")[0]],
    )

    from app.adapters.registry import registry  # local import avoids a cycle

    adapter = registry.resolve(ctx)
    warnings: list[str] = []

    jsonld = _run_layer("jsonld", lambda: extract_jsonld(ctx), warnings)
    microdata = _run_layer("microdata", lambda: extract_microdata(ctx), warnings)
    embedded = _run_layer("embedded", lambda: extract_embedded(ctx, page_globals), warnings)
    opengraph = _run_layer("opengraph", lambda: extract_opengraph(ctx), warnings)
    metatags = _run_layer("meta", lambda: extract_metatags(ctx), warnings)

    dom_candidate: Candidate | None = None
    signals = DomSignals()
    try:
        dom_candidate, signals = extract_dom(ctx)
    except Exception as exc:  # noqa: BLE001
        logger.warning("DOM layer failed: %s", exc)
        warnings.append(f"dom extraction failed: {exc}")

    candidates = [c for c in (jsonld, microdata, embedded, opengraph, metatags, dom_candidate) if c is not None]
    ordered = sorted(candidates, key=lambda candidate: PRIORITY.get(candidate.source, 0), reverse=True)

    merged: dict[str, Any] = {}
    provenance: dict[str, str] = {}

    for field in SCALAR_FIELDS:
        for candidate in ordered:
            value = candidate.data.get(field)
            if _is_empty(value):
                continue
            merged[field] = value
            provenance[field] = candidate.source
            break

    images: list[str] = []
    for candidate in ordered:
        for image in candidate.data.get("images") or []:
            if image and image not in images:
                images.append(image)

    availability = StockStatus.UNKNOWN
    for candidate in ordered:
        status = candidate.data.get("availability")
        if status and status is not StockStatus.UNKNOWN:
            availability = status
            provenance["availability"] = candidate.source
            break

    variants = merge_variant_sets([(candidate.source, candidate.variants) for candidate in ordered])
    if variants:
        provenance["variants"] = variants[0].source

    snapshot = ProductSnapshot(
        url=clean_url(url),
        store_slug=store.slug,
        store_name=store.name,
        store_domain=store.domain,
        name=clean(merged.get("name")),
        brand=clean(merged.get("brand")),
        category=clean(merged.get("category")),
        description=clean(merged.get("description")),
        product_id=merged.get("product_id"),
        sku=merged.get("sku"),
        image_url=merged.get("image_url"),
        images=images[:8],
        currency=merged.get("currency"),
        current_price=merged.get("current_price"),
        original_price=merged.get("original_price"),
        availability=availability,
        variants=variants,
        provenance=provenance,
        layers_used=[candidate.source for candidate in ordered],
        adapter=adapter.slug,
        warnings=warnings,
    )

    # --- adapter pass: gaps only, unless the adapter declares itself authoritative
    try:
        contributions: list[dict[str, Any]] = []

        product = adapter.detect_product(ctx, snapshot)
        if product:
            contributions.append(product)

        price = adapter.detect_price(ctx, snapshot)
        if price:
            contributions.append(dict(price))

        status = adapter.detect_availability(ctx, snapshot)
        if status and status is not StockStatus.UNKNOWN:
            contributions.append({"availability": status})

        adapter_variants = adapter.detect_variants(ctx, snapshot)
        if adapter_variants:
            contributions.append({"variants": adapter_variants})

        for contribution in contributions:
            for key, value in contribution.items():
                if _is_empty(value):
                    continue
                existing = getattr(snapshot, key, None)
                if _is_empty(existing) or adapter.authoritative:
                    setattr(snapshot, key, value)
                    provenance[key] = "adapter"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Adapter %s failed: %s", adapter.slug, exc)
        warnings.append(f"adapter {adapter.slug} failed: {exc}")

    # --- normalisation
    snapshot.images = [urljoin(url, image) for image in snapshot.images]
    if snapshot.image_url:
        snapshot.image_url = urljoin(url, snapshot.image_url)
    elif snapshot.images:
        snapshot.image_url = snapshot.images[0]

    if not snapshot.product_id:
        derived = product_id_from_url(url)
        if derived:
            snapshot.product_id = derived
            provenance["product_id"] = "url"

    if not snapshot.currency:
        snapshot.currency = store.currency or currency_from_hostname(hostname)
        if snapshot.currency:
            provenance["currency"] = "url"

    snapshot.current_price = quantise(_as_decimal(snapshot.current_price))
    snapshot.original_price = quantise(_as_decimal(snapshot.original_price))
    for variant in snapshot.variants:
        variant.price = quantise(_as_decimal(variant.price))

    # A discount where the "original" is below the current price is a mis-read.
    if (
        snapshot.original_price is not None
        and snapshot.current_price is not None
        and snapshot.original_price <= snapshot.current_price
    ):
        snapshot.original_price = None
        provenance.pop("original_price", None)

    snapshot.confidence = _score_page(
        signals,
        jsonld=jsonld is not None,
        microdata=microdata is not None,
        embedded=embedded is not None,
        og_product=has_product_og_type(soup),
        url_positive=looks_like_product_url(url),
        url_negative=looks_like_non_product_url(url),
        adapter_verdict=adapter.is_product_page(ctx),
    )
    snapshot.provenance = provenance

    if snapshot.variants and all(v.availability is StockStatus.UNKNOWN for v in snapshot.variants):
        snapshot.warnings.append("Variant availability could not be determined on this page.")

    return snapshot


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None
