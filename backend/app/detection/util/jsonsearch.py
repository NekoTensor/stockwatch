"""Tolerant JSON handling and the generic "find the product in this blob" search.

The same idea as the extension's `detection/util/json.ts`: we do not know the
shape of any store's embedded state and never will for the long tail, so the
object graph is walked and every node is scored on how much it looks like a
product.
"""

from __future__ import annotations

import json
import re
from collections import deque
from decimal import Decimal
from typing import Any

from app.detection.util.price import to_amount
from app.detection.util.text import clean

MAX_NODES = 25_000
MAX_DEPTH = 14
MAX_JSON_CHARS = 4_000_000

KEYS: dict[str, tuple[str, ...]] = {
    "name": (
        "name", "title", "productName", "productTitle", "displayName",
        "productDisplayName", "itemName", "item_name",
    ),
    "brand": ("brand", "brandName", "manufacturer", "vendor", "item_brand"),
    "price": (
        "price", "salePrice", "sellingPrice", "finalPrice", "discounted", "discountedPrice",
        "currentPrice", "offerPrice", "specialPrice", "unitPrice", "priceValue", "amount", "value",
    ),
    "original_price": (
        "mrp", "listPrice", "originalPrice", "strikedPrice", "strikeOffPrice", "regularPrice",
        "wasPrice", "compareAtPrice", "maxPrice", "basePrice", "oldPrice",
    ),
    "currency": ("currency", "currencyCode", "priceCurrency"),
    "sku": (
        "sku", "skuId", "styleId", "itemId", "item_id", "productId", "productCode",
        "code", "partNumber", "id",
    ),
    "image": (
        "image", "imageUrl", "images", "thumbnail", "primaryImage", "defaultImage", "media", "src",
    ),
    "category": (
        "category", "categoryName", "productType", "item_category", "articleType", "masterCategory",
    ),
    "variants": (
        "sizes", "variants", "skus", "options", "articles", "variations", "sizeOptions",
        "swatches", "shades",
    ),
    "availability": (
        "availability", "inStock", "isAvailable", "available", "stockStatus",
        "inventoryStatus", "isInStock", "sellable",
    ),
    "quantity": (
        "quantity", "stock", "inventory", "availableQuantity", "sellableQuantity",
        "stockCount", "availableCount",
    ),
    "out_of_stock": ("outOfStock", "isOutOfStock", "soldOut", "isSoldOut"),
    "variant_label": (
        "size", "name", "label", "value", "title", "displayName", "sizeName",
        "skuSize", "shade", "color",
    ),
}

_ASSIGNMENT = re.compile(r"=\s*([\[{][\s\S]*?[\]}])\s*;?\s*$")
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def safe_json_loads(raw: str | None) -> Any | None:
    """Parse JSON that may be wrapped in JavaScript, or slightly malformed."""
    if not raw:
        return None
    text = raw.strip()
    if not text or len(text) > MAX_JSON_CHARS:
        return None

    text = text.removeprefix("<!--").removesuffix("-->").strip()

    try:
        return json.loads(text)
    except ValueError:
        pass

    match = _ASSIGNMENT.search(text)
    if match:
        try:
            return json.loads(match.group(1))
        except ValueError:
            pass

    # Trailing commas are the most common hand-written-JSON-LD mistake.
    try:
        return json.loads(_TRAILING_COMMA.sub(r"\1", text))
    except ValueError:
        return None


def _normalise(key: str) -> str:
    return re.sub(r"[_\-\s]", "", key).lower()


def pick(node: dict[str, Any], aliases: tuple[str, ...] | list[str]) -> Any:
    """Case/underscore-insensitive lookup across a list of aliases."""
    lookup = {_normalise(key): value for key, value in node.items()}
    for alias in aliases:
        value = lookup.get(_normalise(alias))
        if value not in (None, ""):
            return value
    return None


def amount_in(node: dict[str, Any], aliases: tuple[str, ...], nested: tuple[str, ...] | None = None) -> Decimal | None:
    """Read money that may be one level deeper than expected.

    ``price: {"mrp": 2299, "discounted": 1149}`` is at least as common as
    ``price: 1149``; a flat lookup finds a dict and gives up.
    """
    raw = pick(node, aliases)
    direct = to_amount(raw)
    if direct is not None:
        return direct
    if isinstance(raw, dict):
        return to_amount(pick(raw, nested or aliases))
    return None


def collect_nodes(root: Any) -> list[dict[str, Any]]:
    """Breadth-first walk with hard caps, cycle-safe."""
    nodes: list[dict[str, Any]] = []
    seen: set[int] = set()
    queue: deque[tuple[Any, int]] = deque([(root, 0)])

    while queue and len(nodes) < MAX_NODES:
        value, depth = queue.popleft()
        if depth > MAX_DEPTH:
            continue

        if isinstance(value, list):
            for item in value:
                if isinstance(item, (dict, list)):
                    queue.append((item, depth + 1))
            continue

        if not isinstance(value, dict):
            continue
        if id(value) in seen:
            continue
        seen.add(id(value))
        nodes.append(value)

        for child in value.values():
            if isinstance(child, (dict, list)):
                queue.append((child, depth + 1))

    return nodes


def _plausible_name(value: Any) -> str | None:
    text = clean(value)
    if not text or not (3 <= len(text) <= 200):
        return None
    if text.startswith(("http://", "https://")):
        return None
    return text


def score_product_node(node: dict[str, Any]) -> int:
    """How strongly a node smells like a product.

    A name alone is worth little (every menu item has one); a name *next to* a
    price is the real signal.
    """
    score = 0

    name = _plausible_name(pick(node, KEYS["name"]))
    if name:
        score += 2

    price = amount_in(node, KEYS["price"])
    if price is not None:
        score += 3
    if name and price is not None:
        score += 2

    if pick(node, KEYS["brand"]) is not None:
        score += 1
    if pick(node, KEYS["sku"]) is not None:
        score += 1
    if pick(node, KEYS["image"]) is not None:
        score += 1
    if amount_in(node, KEYS["original_price"]) is not None:
        score += 1

    variants = pick(node, KEYS["variants"])
    if isinstance(variants, list) and variants:
        score += 2

    declared = str(pick(node, ("@type", "type", "itemType")) or "").lower()
    if "product" in declared:
        score += 3

    return score


def find_product_nodes(root: Any, limit: int = 5) -> list[dict[str, Any]]:
    scored = [(node, score_product_node(node)) for node in collect_nodes(root)]
    ranked = sorted((entry for entry in scored if entry[1] >= 5), key=lambda entry: entry[1], reverse=True)
    return [node for node, _ in ranked[:limit]]


def as_string(value: Any, depth: int = 0) -> str | None:
    """Flatten ``{"name": ...}`` / ``["a", "b"]`` shapes down to a string."""
    if depth > 4:
        return None
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        for item in value:
            found = as_string(item, depth + 1)
            if found:
                return found
        return None
    if isinstance(value, dict):
        return as_string(pick(value, ("name", "value", "title", "label", "@id", "text")), depth + 1)
    return None


def as_image_list(value: Any, depth: int = 0) -> list[str]:
    if depth > 4:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [url for item in value for url in as_image_list(item, depth + 1)]
    if isinstance(value, dict):
        direct = pick(value, ("url", "contentUrl", "src", "imageUrl", "image", "large", "zoom", "default"))
        if direct is not None:
            return as_image_list(direct, depth + 1)
    return []
