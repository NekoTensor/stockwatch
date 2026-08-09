"""The extraction layers, server side.

Same six layers and the same priority order as the extension. They are grouped
in one module here because, unlike the browser build, there is no bundle-size
reason to split them and reading them together makes the ordering obvious.

Each layer returns a ``Candidate``: a partial snapshot plus the name of the
layer that produced it. The pipeline merges candidates field by field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from app.detection.models import VariantSnapshot
from app.detection.util import availability as avail
from app.detection.util.jsonsearch import (
    KEYS,
    amount_in,
    as_image_list,
    as_string,
    find_product_nodes,
    pick,
    safe_json_loads,
)
from app.detection.util.price import (
    CURRENCY_MARKER,
    PRICE_PATTERN,
    currency_from_hostname,
    currency_from_text,
    parse_amount,
    to_amount,
)
from app.detection.util.text import clean, normalise_key, strip_site_suffix
from app.models.enums import StockStatus, VariantType


@dataclass(slots=True)
class Candidate:
    source: str
    data: dict[str, Any] = field(default_factory=dict)
    variants: list[VariantSnapshot] = field(default_factory=list)


@dataclass(slots=True)
class PageContext:
    soup: BeautifulSoup
    url: str
    hostname: str
    store_names: list[str] = field(default_factory=list)


# --------------------------------------------------------------- helpers ----

_PRODUCT_TYPES = re.compile(r"(^|/)(Product|ProductModel|ProductGroup|IndividualProduct)$", re.I)

_VARIANT_TOKEN = re.compile(
    r"^(XXS|XS|S|M|L|XL|XXL|XXXL|[2-5]XL)$"
    r"|^(UK|US|EU|INDS?|IND)\s?\d{1,2}(\.5)?$"
    r"|^\d{1,2}(\.5)?$"
    r"|^\d{2,3}\s?(CM|MM|IN|INCH|INCHES)$"
    r"|^\d{1,4}\s?(GB|TB|MB)$"
    r"|^\d{1,4}\s?(ML|L|G|KG|OZ)$"
    r"|^(SHADE|COLOU?R|TONE)\s?\d+$"
    r"|^\d{2}\s?/\s?\d{2}$"
    r"|^(ONE ?SIZE|FREE ?SIZE|OS|STANDARD|REGULAR)$",
    re.I,
)

_VARIANT_CONTAINER_HINT = re.compile(
    r"(size|variant|variation|swatch|shade|colou?r|option|selector|picker|capacity|storage|fit|length)", re.I
)

# The token boundaries are load-bearing. A bare `nav` alternative matches inside
# "unavailable", which silently discarded every sold-out swatch on Amazon as
# though it were navigation. Boundaries are "not a letter or digit" rather than
# \b, because `_` is a word character and `mini_bag` would otherwise slip through.
_NOISE_TOKENS = (
    "recommend", "related", "similar", "also-?like", "you-?may", "carousel",
    "cross-?sell", "up-?sell", "footer", "header", "nav", "menu", "cart",
    "basket", "mini-?bag", "wishlist", "recently-?viewed", "sponsor", "advert", "banner",
)
_NOISE_CONTAINER = re.compile(
    rf"(?:^|[^a-z0-9])(?:{'|'.join(_NOISE_TOKENS)})(?:[^a-z0-9]|$)", re.I
)

#: Class names come in kebab-case, snake_case *and* camelCase
#: (`swatchUnavailable`). Inserting a separator at each camel boundary lets one
#: kebab-oriented pattern match all three conventions.
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")


def _class_of(tag: Tag) -> str:
    return _CAMEL_BOUNDARY.sub(r"\1-\2", " ".join(tag.get("class") or []))

_DISABLED_CLASS = re.compile(
    r"(^|[\s_-])(disabled|is-disabled|unavailable|is-unavailable|out-of-stock|outofstock|sold-?out|"
    r"soldout|crossed|strike|not-available|inactive|greyed|grayed)([\s_-]|$)",
    re.I,
)

_STRIKE_CLASS = re.compile(
    r"(strike|struck|line-?through|mrp|was-?price|old-?price|list-?price|original|compare|regular|"
    r"slashed|basis-?price)",
    re.I,
)

_PRICE_ATTR_HINT = re.compile(r"(price|amount|cost|mrp|value|final|selling|offer|deal|sale)", re.I)

_BAD_IMAGE = re.compile(
    r"(logo|sprite|icon|placeholder|loader|spinner|blank|pixel|1x1|avatar|badge|flag|payment|banner)", re.I
)


def _attrs_of(tag: Tag) -> str:
    parts = [tag.get("id") or "", " ".join(tag.get("class") or []), tag.get("data-testid") or ""]
    return " ".join(str(part) for part in parts)


def _in_noise_region(tag: Tag) -> bool:
    node: Tag | None = tag
    hops = 0
    while node is not None and hops < 14:
        if node.name in {"nav", "footer", "header", "aside", "script", "style", "noscript"}:
            return True
        if _NOISE_CONTAINER.search(_attrs_of(node)):
            return True
        node = node.parent if isinstance(node.parent, Tag) else None
        hops += 1
    return False


def _text_of(tag: Tag | None) -> str:
    if tag is None:
        return ""
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()


def _dom_distance(a: Tag, b: Tag, cap: int = 25) -> int:
    ancestors: dict[int, int] = {}
    node: Tag | None = a
    depth = 0
    while node is not None and depth <= cap:
        ancestors[id(node)] = depth
        node = node.parent if isinstance(node.parent, Tag) else None
        depth += 1

    node = b
    depth = 0
    while node is not None and depth <= cap:
        up = ancestors.get(id(node))
        if up is not None:
            return up + depth
        node = node.parent if isinstance(node.parent, Tag) else None
        depth += 1

    return cap * 2


def _is_disabled_like(tag: Tag) -> bool:
    if tag.has_attr("disabled"):
        return True
    if tag.get("aria-disabled") == "true":
        return True

    for attr in ("data-available", "data-in-stock"):
        value = tag.get(attr)
        if value is not None and re.fullmatch(r"(false|0|no)", str(value), re.I):
            return True
    for attr in ("data-out-of-stock", "data-sold-out"):
        value = tag.get(attr)
        if value is not None and re.fullmatch(r"(true|1|yes)", str(value), re.I):
            return True

    if _DISABLED_CLASS.search(_class_of(tag)):
        return True

    inner = tag.find("input")
    if isinstance(inner, Tag) and inner.has_attr("disabled"):
        return True

    style = str(tag.get("style") or "")
    return "line-through" in style


def _is_struck_through(tag: Tag) -> bool:
    if tag.name in {"s", "del", "strike"}:
        return True
    if _STRIKE_CLASS.search(_class_of(tag)):
        return True
    return "line-through" in str(tag.get("style") or "")


def _accessible_label(tag: Tag) -> str:
    direct = _text_of(tag)
    if direct:
        return direct
    for attr in ("aria-label", "title", "data-value", "data-size", "value", "alt"):
        value = tag.get(attr)
        if value and str(value).strip():
            return str(value).strip()
    inner = tag.find("input")
    if isinstance(inner, Tag) and inner.get("value"):
        return str(inner["value"]).strip()
    return ""


def _variant_type(label_hint: str, sample: str) -> VariantType:
    hint = f"{label_hint} {sample}".lower()
    if "shade" in hint:
        return VariantType.SHADE
    if re.search(r"colou?r", hint):
        return VariantType.COLOR
    if re.search(r"\b\d+\s?(gb|tb|mb)\b", hint) or re.search(r"capacity|storage|memory", hint):
        return VariantType.CAPACITY
    if re.search(r"\b\d+\s?(ml|l|g|kg|oz)\b", hint):
        return VariantType.CAPACITY
    if "length" in hint:
        return VariantType.LENGTH
    if re.search(r"flavou?r|scent", hint):
        return VariantType.FLAVOR
    if re.search(r"\bsize\b|\bfit\b", hint):
        return VariantType.SIZE
    if _VARIANT_TOKEN.match(sample):
        return VariantType.SIZE
    return VariantType.GENERIC


# ------------------------------------------------------------- 1. JSON-LD ----


def _types_of(node: dict[str, Any]) -> list[str]:
    raw = node.get("@type") or node.get("type")
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str)]
    return []


def _flatten_jsonld(root: Any, depth: int = 0, out: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    out = out if out is not None else []
    if depth > 6:
        return out
    if isinstance(root, list):
        for item in root:
            _flatten_jsonld(item, depth + 1, out)
        return out
    if not isinstance(root, dict):
        return out

    out.append(root)
    for key in ("@graph", "mainEntity", "itemListElement", "hasVariant", "isVariantOf", "item"):
        if key in root:
            _flatten_jsonld(root[key], depth + 1, out)
    return out


def _collect_offers(node: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def push(value: Any, depth: int = 0) -> None:
        if depth > 3:
            return
        if isinstance(value, list):
            for item in value:
                push(item, depth + 1)
            return
        if not isinstance(value, dict):
            return
        result.append(value)
        if "offers" in value:  # AggregateOffer
            push(value["offers"], depth + 1)

    push(node.get("offers") or node.get("offer"))
    return result


def _offer_price(offer: dict[str, Any]) -> Decimal | None:
    direct = to_amount(pick(offer, ("price", "lowPrice", "highPrice")))
    if direct is not None:
        return direct
    spec = offer.get("priceSpecification")
    if isinstance(spec, dict):
        return to_amount(pick(spec, ("price", "minPrice", "maxPrice")))
    if isinstance(spec, list):
        for item in spec:
            if isinstance(item, dict):
                value = to_amount(pick(item, ("price", "minPrice", "maxPrice")))
                if value is not None:
                    return value
    return None


def extract_jsonld(ctx: PageContext) -> Candidate | None:
    """schema.org Product in a JSON-LD script. The highest-trust layer."""
    products: list[dict[str, Any]] = []

    for script in ctx.soup.find_all("script", attrs={"type": re.compile(r"ld\+json|json\+ld", re.I)}):
        parsed = safe_json_loads(script.string or script.get_text())
        if parsed is None:
            continue
        for node in _flatten_jsonld(parsed):
            if any(_PRODUCT_TYPES.search(t) for t in _types_of(node)):
                products.append(node)

    if not products:
        return None

    def score(node: dict[str, Any]) -> int:
        value = 0
        if as_string(node.get("name")):
            value += 2
        if _collect_offers(node):
            value += 3
        if any(key in node for key in ("sku", "productID", "mpn")):
            value += 1
        if "image" in node:
            value += 1
        if "brand" in node:
            value += 1
        if isinstance(node.get("hasVariant"), list):
            value += 2
        node_url = as_string(pick(node, ("url", "@id")))
        if node_url and re.sub(r"^https?://[^/]+", "", node_url) in ctx.url:
            value += 3
        return value

    node = max(products, key=score)
    offers = _collect_offers(node)

    prices = [price for price in (_offer_price(offer) for offer in offers) if price is not None]
    current_price = min(prices) if prices else None
    currency = next(
        (as_string(pick(offer, ("priceCurrency", "currency"))) for offer in offers if pick(offer, ("priceCurrency", "currency"))),
        None,
    )
    list_price = next(
        (
            value
            for value in (to_amount(pick(offer, ("listPrice", "highPrice", "strikePrice"))) for offer in offers)
            if value is not None
        ),
        None,
    )

    statuses = [avail.from_schema(as_string(pick(offer, ("availability",)))) for offer in offers]
    if StockStatus.IN_STOCK in statuses:
        availability = StockStatus.IN_STOCK
    elif StockStatus.OUT_OF_STOCK in statuses:
        availability = StockStatus.OUT_OF_STOCK
    else:
        availability = StockStatus.UNKNOWN

    variants = _variants_from_group(node) or _variants_from_offers(offers)
    images = as_image_list(node.get("image"))[:8]

    return Candidate(
        source="jsonld",
        data={
            "name": as_string(pick(node, ("name",))),
            "brand": as_string(pick(node, ("brand", "manufacturer"))),
            "description": as_string(pick(node, ("description",))),
            "sku": as_string(pick(node, ("sku", "mpn"))),
            "product_id": as_string(pick(node, ("productID", "productId", "gtin13", "gtin", "sku"))),
            "category": as_string(pick(node, ("category",))),
            "image_url": images[0] if images else None,
            "images": images,
            "currency": currency.upper() if currency else None,
            "current_price": current_price,
            "original_price": list_price,
            "availability": availability,
        },
        variants=variants,
    )


def _variants_from_offers(offers: list[dict[str, Any]]) -> list[VariantSnapshot]:
    """Several named offers is a variant matrix: one offer per size."""
    if len(offers) < 2:
        return []

    variants: list[VariantSnapshot] = []
    seen: set[str] = set()

    for offer in offers:
        label = as_string(pick(offer, ("name", "sku", "gtin13", "gtin", "mpn")))
        if not label:
            continue
        key = normalise_key(label)
        if not key or key in seen:
            continue
        seen.add(key)
        variants.append(
            VariantSnapshot(
                id=as_string(pick(offer, ("sku", "@id", "mpn"))) or label,
                name=label,
                type=_variant_type("", label),
                availability=avail.from_schema(as_string(pick(offer, ("availability",)))),
                sku=as_string(pick(offer, ("sku",))),
                price=_offer_price(offer),
                source="jsonld",
            )
        )

    # Offer names that are all long SKU strings are noise, not sizes.
    short = sum(1 for variant in variants if len(variant.name) <= 12)
    return variants if short >= len(variants) / 2 else []


def _variants_from_group(node: dict[str, Any]) -> list[VariantSnapshot]:
    """ProductGroup -> hasVariant -> Product[] is the explicit modern encoding."""
    raw = node.get("hasVariant")
    if not isinstance(raw, list):
        return []

    variants: list[VariantSnapshot] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        axis = as_string(pick(item, ("size", "color", "colour", "pattern", "material"))) or as_string(
            pick(item, ("name",))
        )
        if not axis:
            continue
        offers = _collect_offers(item)
        variants.append(
            VariantSnapshot(
                id=as_string(pick(item, ("sku", "productID", "@id"))) or axis,
                name=axis,
                type=VariantType.SIZE if "size" in item else VariantType.COLOR if "color" in item else VariantType.GENERIC,
                availability=avail.from_schema(as_string(pick(offers[0], ("availability",)))) if offers else StockStatus.UNKNOWN,
                sku=as_string(pick(item, ("sku",))),
                price=_offer_price(offers[0]) if offers else None,
                source="jsonld",
            )
        )
    return variants


# ----------------------------------------------------------- 2. Microdata ----


def _prop_value(tag: Tag) -> str | None:
    name = tag.name.lower()
    if name == "meta":
        return clean(tag.get("content"))
    if name in {"img", "source", "iframe"}:
        return clean(tag.get("src") or tag.get("content"))
    if name in {"a", "link", "area"}:
        return clean(tag.get("href"))
    if name == "time":
        return clean(tag.get("datetime") or _text_of(tag))
    if name == "data":
        return clean(tag.get("value") or _text_of(tag))
    return clean(tag.get("content") or _text_of(tag))


def extract_microdata(ctx: PageContext) -> Candidate | None:
    """schema.org expressed as itemscope/itemprop attributes."""
    scopes = [
        tag
        for tag in ctx.soup.find_all(attrs={"itemscope": True})
        if re.search(r"/Product$|/Product\b", str(tag.get("itemtype") or ""), re.I)
    ]
    if not scopes:
        return None

    scope = max(scopes, key=lambda tag: len(tag.find_all(attrs={"itemprop": True})))
    follow = {"offers", "brand", "priceSpecification"}
    props: dict[str, list[str]] = {}

    def visit(element: Tag) -> None:
        for child in element.find_all(recursive=False):
            if not isinstance(child, Tag):
                continue
            prop = child.get("itemprop")
            is_scope = child.has_attr("itemscope")

            if prop and not is_scope:
                value = _prop_value(child)
                if value:
                    props.setdefault(str(prop), []).append(value)

            if is_scope:
                # Only descend into nested entities we asked for; an embedded
                # Review's `name` is not the product's name.
                if prop and str(prop) in follow:
                    visit(child)
                continue

            visit(child)

    visit(scope)

    def first(key: str) -> str | None:
        values = props.get(key)
        return values[0] if values else None

    price_text = first("price") or first("lowPrice")
    current_price = to_amount(price_text)
    currency = (first("priceCurrency") or "").upper() or (currency_from_text(price_text) if price_text else None)
    images = props.get("image", [])[:8]
    name = first("name")

    if not name and current_price is None:
        return None

    return Candidate(
        source="microdata",
        data={
            "name": name,
            "brand": first("brand"),
            "description": first("description"),
            "sku": first("sku") or first("mpn"),
            "product_id": first("productID") or first("sku"),
            "category": first("category"),
            "image_url": images[0] if images else None,
            "images": images,
            "currency": currency or None,
            "current_price": current_price,
            "original_price": to_amount(first("highPrice")),
            "availability": avail.from_schema(first("availability")),
        },
    )


# ------------------------------------------------------- 3. Embedded JSON ----

_WINDOW_ASSIGNMENT = re.compile(
    r"(?:window|self|globalThis)\.(?:__[A-Za-z0-9_]+__|__[A-Za-z0-9_]+|[A-Za-z_$][\w$]*)\s*=\s*([\[{])"
)


def _extract_balanced(text: str, start: int) -> str | None:
    """Pull one balanced literal out of a larger script, string-aware."""
    opener = text[start]
    if opener not in "{[":
        return None
    closer = "}" if opener == "{" else "]"

    depth = 0
    in_string: str | None = None
    escaped = False

    for index in range(start, min(len(text), start + 3_000_000)):
        char = text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            continue

        if char in "\"'":
            in_string = char
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    return None


def _inline_blobs(soup: BeautifulSoup) -> list[Any]:
    blobs: list[Any] = []

    for script in soup.find_all("script"):
        script_type = str(script.get("type") or "")
        script_id = str(script.get("id") or "")
        if script_id == "__NEXT_DATA__" or re.fullmatch(r"application/json", script_type, re.I):
            parsed = safe_json_loads(script.string or script.get_text())
            if parsed is not None:
                blobs.append(parsed)

    for script in soup.find_all("script", src=False):
        text = script.string or script.get_text()
        if not text or not (40 < len(text) < 3_000_000):
            continue
        match = _WINDOW_ASSIGNMENT.search(text)
        if not match:
            continue
        literal = _extract_balanced(text, match.start(1))
        if literal:
            parsed = safe_json_loads(literal)
            if parsed is not None:
                blobs.append(parsed)

    return blobs


def _variant_availability(entry: dict[str, Any]) -> StockStatus:
    status = avail.from_flag(pick(entry, KEYS["availability"]))
    status = avail.merge(status, avail.from_flag(pick(entry, KEYS["quantity"])))
    negative = pick(entry, KEYS["out_of_stock"])
    if negative is not None:
        status = avail.merge(status, avail.from_negative_flag(negative))
    return status


def _variants_from_node(node: dict[str, Any]) -> list[VariantSnapshot]:
    raw = pick(node, KEYS["variants"])
    if not isinstance(raw, list) or not raw or len(raw) > 200:
        return []

    group_label = next(
        (key for key in node if re.sub(r"[_\-\s]", "", key).lower() in {v.lower() for v in KEYS["variants"]}),
        "",
    )
    variants: list[VariantSnapshot] = []
    seen: set[str] = set()

    for item in raw:
        entry: dict[str, Any] = {}
        if isinstance(item, (str, int, float)):
            label = clean(str(item))
        elif isinstance(item, dict):
            entry = item
            label = as_string(pick(item, KEYS["variant_label"]))
        else:
            continue

        if not label or len(label) > 40:
            continue
        key = normalise_key(label)
        if not key or key in seen:
            continue
        seen.add(key)

        variants.append(
            VariantSnapshot(
                id=as_string(pick(entry, ("skuId", "sku", "id", "code"))) or label,
                name=label,
                type=_variant_type(group_label, label),
                availability=_variant_availability(entry),
                sku=as_string(pick(entry, ("skuId", "sku"))),
                price=to_amount(pick(entry, KEYS["price"])),
                source="embedded",
            )
        )

    return variants


def extract_embedded(ctx: PageContext, page_globals: dict[str, Any] | None = None) -> Candidate | None:
    """Product read out of the page's own JSON state. No per-store paths."""
    blobs: list[Any] = _inline_blobs(ctx.soup)
    if page_globals:
        blobs.extend(value for value in page_globals.values() if value is not None)
    if not blobs:
        return None

    nodes = [node for blob in blobs for node in find_product_nodes(blob, 3)]
    if not nodes:
        return None

    merged: dict[str, Any] = {}
    variants: list[VariantSnapshot] = []

    for node in nodes[:3]:
        images = as_image_list(pick(node, KEYS["image"]))[:8]
        price_raw = pick(node, KEYS["price"])
        price_object = price_raw if isinstance(price_raw, dict) else None

        currency = as_string(pick(node, KEYS["currency"])) or (
            as_string(pick(price_object, KEYS["currency"])) if price_object else None
        )
        original = amount_in(node, KEYS["original_price"]) or (
            to_amount(pick(price_object, KEYS["original_price"])) if price_object else None
        )

        data = {
            "name": as_string(pick(node, KEYS["name"])),
            "brand": as_string(pick(node, KEYS["brand"])),
            "sku": as_string(pick(node, ("sku", "skuId", "styleId"))),
            "product_id": as_string(pick(node, KEYS["sku"])),
            "category": as_string(pick(node, KEYS["category"])),
            "image_url": images[0] if images else None,
            "images": images,
            "currency": currency.upper() if currency and re.fullmatch(r"[A-Za-z]{3}", currency) else None,
            "current_price": amount_in(node, KEYS["price"]),
            "original_price": original,
            "availability": _variant_availability(node),
        }

        for key, value in data.items():
            if value in (None, "", [], StockStatus.UNKNOWN):
                continue
            merged.setdefault(key, value)

        node_variants = _variants_from_node(node)
        if len(node_variants) > len(variants):
            variants = node_variants

    if not merged.get("name") and merged.get("current_price") is None:
        return None

    return Candidate(source="embedded", data=merged, variants=variants)


# --------------------------------------------------------- 4. OpenGraph -----


def _meta(soup: BeautifulSoup, *keys: str) -> str | None:
    for key in keys:
        for attr in ("property", "name", "itemprop"):
            tag = soup.find("meta", attrs={attr: re.compile(rf"^{re.escape(key)}$", re.I)})
            if isinstance(tag, Tag):
                value = clean(tag.get("content"))
                if value:
                    return value
    return None


def extract_opengraph(ctx: PageContext) -> Candidate | None:
    soup = ctx.soup
    title = _meta(soup, "og:title")
    price_amount = _meta(soup, "product:price:amount", "og:price:amount", "product:sale_price:amount")

    if not title and not price_amount:
        return None

    currency = _meta(soup, "product:price:currency", "og:price:currency", "product:sale_price:currency")
    if not currency and price_amount:
        currency = currency_from_text(price_amount)

    images = [
        clean(tag.get("content"))
        for tag in soup.find_all("meta", attrs={"property": re.compile(r"^og:image(:secure_url)?$", re.I)})
    ]
    images = [image for image in images if image][:8]

    return Candidate(
        source="opengraph",
        data={
            "name": title,
            "description": _meta(soup, "og:description"),
            "brand": _meta(soup, "product:brand", "og:brand"),
            "category": _meta(soup, "product:category"),
            "product_id": _meta(soup, "product:retailer_item_id", "product:item_group_id"),
            "sku": _meta(soup, "product:retailer_item_id"),
            "image_url": images[0] if images else None,
            "images": images,
            "currency": currency.upper() if currency else None,
            "current_price": to_amount(price_amount),
            "original_price": to_amount(_meta(soup, "product:original_price:amount", "product:list_price:amount")),
            "availability": avail.from_schema(_meta(soup, "product:availability", "og:availability")),
        },
    )


def has_product_og_type(soup: BeautifulSoup) -> bool:
    return "product" in (_meta(soup, "og:type") or "").lower()


# ---------------------------------------------------------- 5. Meta tags ----


def extract_metatags(ctx: PageContext) -> Candidate | None:
    soup = ctx.soup

    canonical = soup.find("link", attrs={"rel": re.compile(r"^canonical$", re.I)})
    canonical_url = clean(canonical.get("href")) if isinstance(canonical, Tag) else None

    raw_title = _meta(soup, "twitter:title") or clean(soup.title.string if soup.title else None)
    name = strip_site_suffix(raw_title, ctx.store_names) if raw_title else None

    price_text = None
    for index in (1, 2, 3, 4):
        label = _meta(soup, f"twitter:label{index}")
        if label and re.search(r"price|mrp|cost", label, re.I):
            price_text = _meta(soup, f"twitter:data{index}")
            break

    image = _meta(soup, "twitter:image", "twitter:image:src")
    amount = to_amount(price_text) if price_text else None

    if not name and amount is None and not image:
        return None

    return Candidate(
        source="meta",
        data={
            "name": name,
            "description": _meta(soup, "twitter:description", "description"),
            "canonical_url": canonical_url,
            # Deliberately not falling back to og:site_name: on a marketplace
            # that reports the brand of a Nike shoe as "Myntra".
            "brand": _meta(soup, "brand", "product:brand"),
            "image_url": image,
            "images": [image] if image else [],
            "current_price": amount,
            "currency": currency_from_text(price_text) if price_text else None,
        },
    )


# ------------------------------------------------------ 6. DOM heuristics ----

_TITLE_SELECTORS = [
    'h1[itemprop="name"]',
    "[itemprop='name']",
    "h1[class*=product]",
    "[class*=product-name]",
    "[class*=productName]",
    "[class*=product-title]",
    "[class*=pdp-title]",
    "[class*=pdp-name]",
    "h1",
]


def _product_scope(soup: BeautifulSoup) -> Tag:
    for selector in (
        "[class*=product-detail]",
        "[class*=productDetail]",
        "[id*=product-detail]",
        "[class*=pdp]",
        "[id*=pdp]",
        "[data-testid*=product]",
        "main",
        "article",
    ):
        for tag in soup.select(selector):
            if len(_text_of(tag)) > 40:
                return tag
    return soup.body or soup


def _find_title(soup: BeautifulSoup) -> Tag | None:
    for selector in _TITLE_SELECTORS:
        for tag in soup.select(selector):
            if _in_noise_region(tag):
                continue
            text = _text_of(tag)
            if 3 <= len(text) <= 200:
                return tag
    return None


@dataclass(slots=True)
class DomSignals:
    has_title: bool = False
    has_price: bool = False
    has_buy_button: bool = False
    has_variants: bool = False
    has_breadcrumb: bool = False
    has_gallery: bool = False
    listing_grid: bool = False


_BUY_BUTTON = re.compile(
    r"\b(add to (cart|bag|basket)|add to my bag|buy now|buy it now|order now|add item|shop now)\b", re.I
)
_NOTIFY_BUTTON = re.compile(r"\b(notify me|email me|remind me|coming soon|join the waitlist|back in stock)\b", re.I)


def _page_availability(scope: Tag) -> tuple[StockStatus, bool]:
    has_buy = False
    buy_enabled = False
    notify = False

    for tag in scope.find_all(["button", "a", "input"], limit=600):
        label = f"{_text_of(tag)} {tag.get('aria-label') or ''} {tag.get('value') or ''}"
        if _BUY_BUTTON.search(label):
            has_buy = True
            if not _is_disabled_like(tag):
                buy_enabled = True
        if _NOTIFY_BUTTON.search(label):
            notify = True

    if buy_enabled:
        return StockStatus.IN_STOCK, has_buy
    if has_buy or notify:
        return StockStatus.OUT_OF_STOCK, has_buy
    return StockStatus.UNKNOWN, has_buy


def _looks_like_listing_grid(soup: BeautifulSoup) -> bool:
    """Three or more sibling cards, each with its own price and link.

    A category page has every individual signal a product page has; what differs
    is repetition.
    """

    def is_card(tag: Tag) -> bool:
        text = _text_of(tag)
        if not text or len(text) > 400:
            return False
        if not CURRENCY_MARKER.search(text) or not PRICE_PATTERN.search(text):
            return False
        return tag.find(["a", "h2", "h3", "h4", "img"]) is not None

    for container in soup.find_all(["ul", "ol", "section", "div", "main"], limit=2500):
        children = [child for child in container.find_all(recursive=False) if isinstance(child, Tag)]
        if len(children) < 3 or _in_noise_region(container):
            continue

        by_tag: dict[str, list[Tag]] = {}
        for child in children:
            by_tag.setdefault(child.name, []).append(child)

        for siblings in by_tag.values():
            if len(siblings) >= 3 and sum(1 for tag in siblings if is_card(tag)) >= 3:
                return True

    return False


def extract_dom(ctx: PageContext) -> tuple[Candidate, DomSignals]:
    soup = ctx.soup
    scope = _product_scope(soup)
    title_tag = _find_title(soup)
    name = _text_of(title_tag) if title_tag else None

    # --- prices
    raw_candidates: list[tuple[Tag, Decimal, str | None, bool]] = []
    for tag in scope.find_all(True, limit=8000):
        text = _text_of(tag)
        if not text or len(text) > 40:
            continue
        if not CURRENCY_MARKER.search(text) and not re.fullmatch(r"[\d.,\s]+", text):
            continue
        if not PRICE_PATTERN.search(text) or _in_noise_region(tag):
            continue

        amount = parse_amount(text)
        if amount is None or amount <= 0 or amount > 100_000_000:
            continue
        currency = currency_from_text(text)
        if not currency and not CURRENCY_MARKER.search(text):
            continue

        raw_candidates.append((tag, amount, currency, _is_struck_through(tag)))

    # Keep only the innermost match: "12,990" beats its wrapper "MRP 12,990".
    innermost = [
        entry
        for entry in raw_candidates
        if not any(other[0] is not entry[0] and other[0] in entry[0].descendants for other in raw_candidates)
    ]

    def price_score(entry: tuple[Tag, Decimal, str | None, bool]) -> int:
        tag, _amount, _currency, struck = entry
        score = 0
        attrs = f"{_attrs_of(tag)} {_attrs_of(tag.parent) if isinstance(tag.parent, Tag) else ''}"
        if _PRICE_ATTR_HINT.search(attrs):
            score += 4
        if title_tag is not None:
            distance = _dom_distance(tag, title_tag)
            score += 4 if distance <= 6 else 2 if distance <= 12 else (-2 if distance > 20 else 0)
        if struck:
            score -= 5
        if re.fullmatch(r"[^\d]*[\d.,\s]+", _text_of(tag)):
            score += 2
        return score

    ranked = sorted(innermost, key=price_score, reverse=True)
    live = [entry for entry in ranked if not entry[3]]
    struck_list = [entry for entry in ranked if entry[3]]

    current_price = original_price = None
    currency = None
    if ranked:
        current = live[0] if live else ranked[0]
        current_price = current[1]
        currency = current[2] or next((entry[2] for entry in ranked if entry[2]), None) or currency_from_hostname(
            ctx.hostname
        )

        candidate_original = next((entry for entry in struck_list if entry[1] > current[1]), None)
        if candidate_original is None:
            candidate_original = next(
                (
                    entry
                    for entry in live[1:]
                    if current[1] < entry[1] < current[1] * 20 and _dom_distance(entry[0], current[0]) <= 8
                ),
                None,
            )
        original_price = candidate_original[1] if candidate_original else None

    # --- variants
    variants = _dom_variants(scope)

    # --- images
    images = _dom_images(scope, title_tag, ctx.url, name)

    status, has_buy = _page_availability(scope)

    signals = DomSignals(
        has_title=bool(name),
        has_price=current_price is not None,
        has_buy_button=has_buy,
        has_variants=bool(variants),
        has_breadcrumb=bool(soup.select("[class*=breadcrumb], nav[aria-label*=readcrumb]")),
        has_gallery=len(images) > 1,
        listing_grid=_looks_like_listing_grid(soup),
    )

    return (
        Candidate(
            source="dom",
            data={
                "name": name,
                "brand": _dom_brand(scope, title_tag),
                "category": _dom_category(soup),
                "image_url": images[0] if images else None,
                "images": images,
                "currency": currency,
                "current_price": current_price,
                "original_price": original_price,
                "availability": status,
            },
            variants=variants,
        ),
        signals,
    )


def _dom_variants(scope: Tag) -> list[VariantSnapshot]:
    groups: dict[int, tuple[Tag, list[Tag]]] = {}

    for tag in scope.find_all(["button", "label", "li", "a", "div", "span", "option"], limit=1500):
        if tag.name in {"a", "div", "span"} and not tag.has_attr("data-value"):
            continue
        if _in_noise_region(tag):
            continue
        label = clean(_accessible_label(tag))
        if not label or len(label) > 24:
            continue
        parent = tag.parent
        if not isinstance(parent, Tag):
            continue
        groups.setdefault(id(parent), (parent, []))[1].append(tag)

    best: tuple[int, list[VariantSnapshot]] | None = None

    for parent, members in groups.values():
        if not (2 <= len(members) <= 60):
            continue

        labels = [clean(_accessible_label(tag)) or "" for tag in members]
        token_hits = sum(1 for label in labels if _VARIANT_TOKEN.match(label))
        container_attrs = f"{_attrs_of(parent)} {parent.get('aria-label') or ''}"
        container_hit = bool(_VARIANT_CONTAINER_HINT.search(container_attrs))
        short_labels = all(len(label) <= 16 for label in labels)

        if not (token_hits / len(members) >= 0.5 or (container_hit and short_labels and token_hits >= 1)):
            continue

        seen: set[str] = set()
        variants: list[VariantSnapshot] = []
        for tag in members:
            name = clean(_accessible_label(tag))
            if not name:
                continue
            key = normalise_key(name)
            if not key or key in seen:
                continue
            seen.add(key)
            variants.append(
                VariantSnapshot(
                    id=str(tag.get("data-value") or tag.get("value") or tag.get("id") or name),
                    name=name,
                    type=_variant_type(container_attrs, name),
                    availability=StockStatus.OUT_OF_STOCK if _is_disabled_like(tag) else StockStatus.IN_STOCK,
                    source="dom",
                )
            )

        if len(variants) < 2:
            continue
        score = len(variants) + token_hits * 2 + (4 if container_hit else 0)
        if best is None or score > best[0]:
            best = (score, variants)

    return best[1] if best else []


def _dom_images(scope: Tag, title_tag: Tag | None, base_url: str, name: str | None) -> list[str]:
    words = [word for word in (name or "").lower().split() if len(word) > 3]
    scored: list[tuple[str, int]] = []

    for tag in scope.find_all(["img", "source"], limit=400):
        url = (
            tag.get("src")
            or (str(tag.get("srcset") or "").split(",")[0].strip().split(" ")[0] or None)
            or tag.get("data-src")
            or tag.get("data-original")
            or tag.get("data-lazy-src")
        )
        if not url or str(url).startswith("data:") or _BAD_IMAGE.search(str(url)):
            continue
        if _in_noise_region(tag):
            continue

        alt = str(tag.get("alt") or "").lower()
        if _BAD_IMAGE.search(alt):
            continue

        score = 0
        if re.search(r"(product|gallery|zoom|main|hero|primary|media)", _attrs_of(tag), re.I):
            score += 3
        if words and any(word in alt for word in words):
            score += 3
        if title_tag is not None and _dom_distance(tag, title_tag) <= 12:
            score += 2
        try:
            if int(str(tag.get("width") or 0)) >= 300:
                score += 2
        except ValueError:
            pass

        scored.append((urljoin(base_url, str(url)), score))

    seen: set[str] = set()
    ordered: list[str] = []
    for url, _score in sorted(scored, key=lambda entry: entry[1], reverse=True):
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered[:8]


def _dom_brand(scope: Tag, title_tag: Tag | None) -> str | None:
    for selector in ("[itemprop=brand]", "[class*=brand]", "[data-testid*=brand]", "a[href*='/brand']"):
        for tag in scope.select(selector):
            if _in_noise_region(tag):
                continue
            if title_tag is not None and _dom_distance(tag, title_tag) > 14:
                continue
            text = clean(_text_of(tag))
            if text and 2 <= len(text) <= 40:
                return text
    return None


def _dom_category(soup: BeautifulSoup) -> str | None:
    crumbs = [
        text
        for text in (clean(_text_of(tag)) for tag in soup.select("[class*=breadcrumb] li, [class*=breadcrumb] a"))
        if text and len(text) <= 60
    ]
    if len(crumbs) < 2:
        return None
    return crumbs[-2]
