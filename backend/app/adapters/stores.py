"""Store adapters.

Every class here is small on purpose. If an adapter starts to look like a
general-purpose extractor, that logic belongs in `detection/layers.py`, where
every store gets it for free.

What legitimately belongs in an adapter:
  * the store's own product-id shape (URL patterns)
  * a brand default, on single-brand stores
  * selectors for a store that publishes no structured data at all (Amazon)
"""

from __future__ import annotations

import re
from decimal import Decimal

from bs4 import Tag

from app.adapters.base import StoreAdapter
from app.detection.layers import PageContext
from app.detection.models import ProductSnapshot, VariantSnapshot
from app.detection.util.availability import from_text as availability_from_text
from app.detection.util.price import parse_price, to_amount
from app.detection.util.text import clean, normalise_key
from app.models.enums import StockStatus, VariantType


class _HostAdapter(StoreAdapter):
    """Shared plumbing: match on hostname suffix."""

    domains: tuple[str, ...] = ()

    def can_handle(self, ctx: PageContext) -> bool:
        host = ctx.hostname
        return any(host == domain or host.endswith(f".{domain}") for domain in self.domains)


class _SingleBrandAdapter(_HostAdapter):
    """A store that sells only its own label.

    Worth encoding: these sites rarely publish a `brand` anywhere, and a card
    that says "ZARA / —" reads worse than one that says "ZARA / Zara".
    """

    brand: str = ""
    id_pattern: str | None = None

    def detect_product(self, ctx: PageContext, base: ProductSnapshot) -> dict[str, object] | None:
        contribution: dict[str, object] = {}

        if self.brand and not base.brand:
            contribution["brand"] = self.brand

        if self.id_pattern and not base.product_id:
            match = re.search(self.id_pattern, ctx.url, re.I)
            if match:
                contribution["product_id"] = match.group(1)

        return contribution or None


class ZaraAdapter(_SingleBrandAdapter):
    slug = "zara"
    label = "Zara"
    domains = ("zara.com",)
    brand = "Zara"
    #: .../leather-effect-jacket-p07840321.html
    id_pattern = r"-p(\d{6,})\.html"

    def is_product_page(self, ctx: PageContext) -> bool | None:
        return bool(re.search(self.id_pattern, ctx.url, re.I)) or None


class HmAdapter(_SingleBrandAdapter):
    slug = "hm"
    label = "H&M"
    domains = ("hm.com", "www2.hm.com")
    brand = "H&M"
    #: .../productpage.0713986001.html
    id_pattern = r"productpage\.(\d{6,})\.html"

    def is_product_page(self, ctx: PageContext) -> bool | None:
        return bool(re.search(self.id_pattern, ctx.url, re.I)) or None


class UniqloAdapter(_SingleBrandAdapter):
    slug = "uniqlo"
    label = "Uniqlo"
    domains = ("uniqlo.com",)
    brand = "Uniqlo"
    id_pattern = r"/products/(E?\d{6,})"


class NikeAdapter(_SingleBrandAdapter):
    slug = "nike"
    label = "Nike"
    domains = ("nike.com",)
    brand = "Nike"
    #: /t/<slug>/<STYLE-COLOUR>, e.g. /t/air-max-90-shoes/CN8490-002
    id_pattern = r"/t/[^/]+/([A-Z0-9]{6,}-[A-Z0-9]{3,})"


class AdidasAdapter(_SingleBrandAdapter):
    slug = "adidas"
    label = "Adidas"
    domains = ("adidas.com", "adidas.co.in", "adidas.co.uk", "adidas.de", "adidas.ae")
    brand = "Adidas"
    #: .../ultraboost-light-shoes/HQ6339.html
    id_pattern = r"/([A-Z]{2}\d{4})\.html"


class MyntraAdapter(_HostAdapter):
    slug = "myntra"
    label = "Myntra"
    domains = ("myntra.com",)

    def detect_product(self, ctx: PageContext, base: ProductSnapshot) -> dict[str, object] | None:
        if base.product_id:
            return None
        #: /jeans/roadster/roadster-men-blue-jeans/2296012/buy
        match = re.search(r"/(\d{5,})/buy", ctx.url)
        return {"product_id": match.group(1)} if match else None

    def is_product_page(self, ctx: PageContext) -> bool | None:
        return bool(re.search(r"/\d{5,}/buy", ctx.url)) or None


class AjioAdapter(_HostAdapter):
    slug = "ajio"
    label = "AJIO"
    domains = ("ajio.com",)

    def detect_product(self, ctx: PageContext, base: ProductSnapshot) -> dict[str, object] | None:
        if base.product_id:
            return None
        match = re.search(r"/p/(\d{6,})", ctx.url)
        return {"product_id": match.group(1)} if match else None

    def is_product_page(self, ctx: PageContext) -> bool | None:
        return bool(re.search(r"/p/\d{6,}", ctx.url)) or None


class NykaaFashionAdapter(_HostAdapter):
    slug = "nykaafashion"
    label = "Nykaa Fashion"
    domains = ("nykaafashion.com", "nykaa.com")

    def detect_product(self, ctx: PageContext, base: ProductSnapshot) -> dict[str, object] | None:
        if base.product_id:
            return None
        match = re.search(r"/p/(\d{4,})", ctx.url)
        return {"product_id": match.group(1)} if match else None

    def is_product_page(self, ctx: PageContext) -> bool | None:
        return bool(re.search(r"/p/\d{4,}", ctx.url)) or None


class AmazonAdapter(_HostAdapter):
    """The one adapter that carries real selectors.

    Amazon publishes no JSON-LD Product and no `product:price:*` tags, so the
    generic layers fall through to heuristics on a page that is mostly
    navigation. These ids have been stable for years and are isolated here so
    that when Amazon does change them, exactly one file needs editing.
    """

    slug = "amazon"
    label = "Amazon"
    domains = (
        "amazon.in", "amazon.com", "amazon.co.uk", "amazon.de", "amazon.fr", "amazon.it",
        "amazon.es", "amazon.ca", "amazon.com.au", "amazon.co.jp", "amazon.ae", "amazon.sg",
        "amazon.nl", "amazon.se", "amazon.pl", "amazon.com.br", "amazon.com.mx",
    )

    TITLE_SELECTORS = ("#productTitle", "#title span")
    PRICE_SELECTORS = (
        "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
        "#corePrice_feature_div .a-price .a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        ".a-price .a-offscreen",
    )
    LIST_PRICE_SELECTORS = (
        "#corePriceDisplay_desktop_feature_div .basisPrice .a-offscreen",
        ".basisPrice .a-offscreen",
        "#listPrice",
        ".priceBlockStrikePriceString",
    )
    IMAGE_SELECTORS = ("#landingImage", "#imgTagWrapperId img", "#main-image", "#ebooksImgBlkFront")
    BRAND_SELECTORS = ("#bylineInfo", "#brand", "a#bylineInfo")
    AVAILABILITY_SELECTORS = ("#availability span", "#availability", "#outOfStock")
    VARIANT_SELECTORS = (
        "#variation_size_name li",
        "#variation_style_name li",
        "#variation_color_name li",
        "#twister li",
    )

    def _first_text(self, ctx: PageContext, selectors: tuple[str, ...]) -> str | None:
        for selector in selectors:
            tag = ctx.soup.select_one(selector)
            if isinstance(tag, Tag):
                text = clean(tag.get_text(" ", strip=True))
                if text:
                    return text
        return None

    def detect_product(self, ctx: PageContext, base: ProductSnapshot) -> dict[str, object] | None:
        contribution: dict[str, object] = {}

        if not base.name:
            title = self._first_text(ctx, self.TITLE_SELECTORS)
            if title:
                contribution["name"] = title

        if not base.brand:
            brand = self._first_text(ctx, self.BRAND_SELECTORS)
            if brand:
                # "Visit the Levi's Store" / "Brand: Levi's"
                brand = re.sub(r"^(visit the|brand:)\s*", "", brand, flags=re.I)
                brand = re.sub(r"\s*store$", "", brand, flags=re.I).strip()
                if brand:
                    contribution["brand"] = brand

        if not base.image_url:
            for selector in self.IMAGE_SELECTORS:
                tag = ctx.soup.select_one(selector)
                if isinstance(tag, Tag):
                    url = tag.get("src") or tag.get("data-old-hires")
                    if url:
                        contribution["image_url"] = str(url)
                        break

        if not base.product_id:
            match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", ctx.url, re.I)
            if match:
                contribution["product_id"] = match.group(1).upper()
                contribution.setdefault("sku", match.group(1).upper())

        return contribution or None

    def detect_price(self, ctx: PageContext, base: ProductSnapshot) -> dict[str, Decimal | str | None] | None:
        if base.current_price is not None:
            return None

        text = self._first_text(ctx, self.PRICE_SELECTORS)
        if not text:
            return None

        amount, currency = parse_price(text)
        if amount is None:
            return None

        contribution: dict[str, Decimal | str | None] = {"current_price": amount}
        if currency:
            contribution["currency"] = currency

        list_text = self._first_text(ctx, self.LIST_PRICE_SELECTORS)
        list_amount = to_amount(list_text) if list_text else None
        if list_amount and list_amount > amount:
            contribution["original_price"] = list_amount

        return contribution

    def detect_availability(self, ctx: PageContext, base: ProductSnapshot) -> StockStatus | None:  # noqa: ARG002
        text = self._first_text(ctx, self.AVAILABILITY_SELECTORS)
        if not text:
            return None
        status = availability_from_text(text)
        return status if status is not StockStatus.UNKNOWN else None

    def detect_variants(self, ctx: PageContext, base: ProductSnapshot) -> list[VariantSnapshot] | None:
        if base.variants:
            return None

        variants: list[VariantSnapshot] = []
        seen: set[str] = set()

        for selector in self.VARIANT_SELECTORS:
            for tag in ctx.soup.select(selector):
                label = clean(tag.get_text(" ", strip=True)) or clean(tag.get("title"))
                if not label or len(label) > 40:
                    continue
                key = normalise_key(label)
                if not key or key in seen:
                    continue
                seen.add(key)

                # Amazon marks a sold-out swatch with `swatchUnavailable`.
                classes = " ".join(tag.get("class") or [])
                unavailable = "unavailable" in classes.lower()

                variants.append(
                    VariantSnapshot(
                        id=str(tag.get("data-defaultasin") or tag.get("data-asin") or label),
                        name=label,
                        type=VariantType.SIZE if "size" in selector else VariantType.GENERIC,
                        availability=StockStatus.OUT_OF_STOCK if unavailable else StockStatus.IN_STOCK,
                        source="adapter",
                    )
                )
            if variants:
                break

        return variants or None

    def is_product_page(self, ctx: PageContext) -> bool | None:
        return bool(re.search(r"/(dp|gp/product)/[A-Z0-9]{10}", ctx.url, re.I)) or None


__all__ = [
    "AdidasAdapter",
    "AjioAdapter",
    "AmazonAdapter",
    "HmAdapter",
    "MyntraAdapter",
    "NikeAdapter",
    "NykaaFashionAdapter",
    "UniqloAdapter",
    "ZaraAdapter",
]
