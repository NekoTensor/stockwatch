"""The server-side pipeline, over the same fixtures the extension uses.

If these ever disagree with `extension/tests/detection.test.ts`, the first check
after a product is tracked would report changes that did not happen.
"""

from __future__ import annotations

from decimal import Decimal

from app.detection.pipeline import detect_product
from app.models.enums import StockStatus, VariantType
from tests.conftest import load_fixture


def test_jsonld_offer_per_size():
    snapshot = detect_product(
        load_fixture("jsonld-apparel.html"),
        "https://www.zara.com/in/en/leather-effect-jacket-p07840321.html",
    )

    assert snapshot.name == "Leather Effect Jacket"
    assert snapshot.brand == "Zara"
    assert snapshot.sku == "07840321-800"
    assert snapshot.store_name == "Zara"
    assert snapshot.store_slug == "zara"
    assert snapshot.adapter == "zara"
    assert snapshot.current_price == Decimal("12990.00")
    assert snapshot.currency == "INR"
    assert snapshot.confidence >= 70

    names = [variant.name for variant in snapshot.variants]
    assert names == ["S", "M", "L", "XL"]

    by_name = {variant.name: variant.availability for variant in snapshot.variants}
    assert by_name["S"] is StockStatus.IN_STOCK
    assert by_name["M"] is StockStatus.OUT_OF_STOCK
    assert sum(1 for status in by_name.values() if status is StockStatus.OUT_OF_STOCK) == 3

    # The recommendations rail must not contribute its price.
    assert snapshot.current_price != Decimal("7590.00")


def test_opengraph_plus_dom():
    snapshot = detect_product(
        load_fixture("og-and-dom.html"),
        "https://www2.hm.com/en_in/productpage.1234567001.html",
    )

    assert snapshot.name == "Oversized Hoodie"
    assert snapshot.store_name == "H&M"
    assert snapshot.current_price == Decimal("1999.00")
    assert snapshot.original_price == Decimal("2999.00")
    assert snapshot.discount_percentage == 33

    by_name = {variant.name: variant.availability for variant in snapshot.variants}
    assert by_name == {
        "XS": StockStatus.IN_STOCK,
        "S": StockStatus.IN_STOCK,
        "M": StockStatus.OUT_OF_STOCK,
        "L": StockStatus.IN_STOCK,
        "XL": StockStatus.OUT_OF_STOCK,
    }
    assert all(variant.type is VariantType.SIZE for variant in snapshot.variants)


def test_embedded_state_only():
    snapshot = detect_product(
        load_fixture("embedded-state.html"),
        "https://www.myntra.com/jeans/roadster/roadster-men-blue-jeans/2296012/buy",
    )

    assert snapshot.name == "Roadster Men Blue Slim Fit Jeans"
    assert snapshot.brand == "Roadster"
    assert snapshot.provenance.get("name") == "embedded"
    assert snapshot.current_price == Decimal("1149.00")
    assert snapshot.original_price == Decimal("2299.00")
    assert snapshot.discount_percentage == 50

    by_name = {variant.name: variant.availability for variant in snapshot.variants}
    assert by_name["30"] is StockStatus.OUT_OF_STOCK
    assert by_name["32"] is StockStatus.IN_STOCK
    assert snapshot.product_id == "2296012"


def test_microdata():
    snapshot = detect_product(
        load_fixture("microdata.html"),
        "https://www.example-outdoors.fr/p/trail-shoes-8845",
    )

    assert snapshot.name == "Kalenji Trail Running Shoes"
    assert "Best shoes" not in (snapshot.name or "")  # nested Review, not the product
    assert snapshot.sku == "TRL-8845"
    assert snapshot.current_price == Decimal("59.99")
    assert snapshot.currency == "EUR"
    assert snapshot.store_name == "Example Outdoors"
    assert snapshot.store_slug == "generic"

    by_name = {variant.name: variant.availability for variant in snapshot.variants}
    assert by_name["UK 9"] is StockStatus.OUT_OF_STOCK


def test_unknown_store_dom_only():
    snapshot = detect_product(
        load_fixture("dom-only.html"),
        "https://www.studiobeauty.in/product/velvet-matte-lipstick",
    )

    assert snapshot.name == "Velvet Matte Lipstick"
    assert snapshot.current_price == Decimal("899.00")
    assert snapshot.original_price == Decimal("1299.00")
    assert snapshot.discount_percentage == 31

    names = [variant.name for variant in snapshot.variants]
    assert names == ["Shade 01", "Shade 02", "Shade 03", "Shade 04"]
    assert snapshot.variants[0].type is VariantType.SHADE

    by_name = {variant.name: variant.availability for variant in snapshot.variants}
    assert by_name["Shade 03"] is StockStatus.OUT_OF_STOCK


def test_productgroup_with_several_colourways():
    """The H&M shape: one ProductGroup holding every colour x size combination.

    Guards three failures at once - describing the page with a leaf variant
    instead of the group, letting another colourway set the price, and letting
    another colourway's sold-out size mark this one's as sold out.
    """
    snapshot = detect_product(
        load_fixture("productgroup-colourways.html"),
        "https://www2.hm.com/en_in/productpage.1301837001.html",
    )

    assert snapshot.name == "Slim Fit Ribbed Henley shirt"
    assert "Beige" not in (snapshot.name or "")
    assert snapshot.brand == "H&M"
    assert snapshot.product_id == "1301837"
    assert snapshot.category == "T-shirts & Tops"

    # Navy is cheaper and partly sold out; neither may leak into beige.
    assert snapshot.current_price == Decimal("2299.00")
    assert snapshot.availability is StockStatus.IN_STOCK

    by_name = {variant.name: variant.availability for variant in snapshot.variants}
    assert list(by_name) == ["S", "M", "L"]
    assert by_name["S"] is StockStatus.IN_STOCK
    assert by_name["M"] is StockStatus.OUT_OF_STOCK
    assert by_name["L"] is StockStatus.IN_STOCK
    assert all(variant.type is VariantType.SIZE for variant in snapshot.variants)


def test_size_picker_of_bare_divs_with_hashed_classes():
    """No structured data, no data attributes, no aria labels - just divs."""
    html = """<html><head><title>Ribbed Henley shirt</title></head><body><main>
      <div class="a1b2c3">
        <h1 class="g7h8i9">Ribbed Henley shirt</h1>
        <div class="j0k1l2">Rs. 2,299.00</div>
        <div class="s9t0u1">
          <div class="c3b99d b040a8"><div>S</div></div>
          <div class="c3b99d b040a8"><div>M</div></div>
          <div class="c3b99d b040a8"><div>L</div></div>
          <div class="c3b99d b040a8"><div>XL</div></div>
        </div>
        <button>Add to bag</button>
      </div></main></body></html>"""

    snapshot = detect_product(html, "https://shop.example/en/productpage.99.html")

    assert [variant.name for variant in snapshot.variants] == ["S", "M", "L", "XL"]
    assert snapshot.current_price == Decimal("2299.00")


def test_ordinary_short_text_is_not_mistaken_for_variants():
    html = """<html><body><main>
      <h1>Cotton Shirt</h1><div class="price">Rs. 1,299.00</div>
      <div class="info"><div>New</div><div>Sale</div><div>Care</div><div>Fit</div></div>
      <button>Add to bag</button>
    </main></body></html>"""

    snapshot = detect_product(html, "https://shop.example/p/cotton-shirt-12345")
    assert snapshot.variants == []


def test_amazon_shaped_page_with_no_structured_data():
    """The adapter's selectors plus the generic DOM layer, on the same page.

    Also guards the noise-region boundary bug: a bare `nav` pattern matches
    inside "unavailable", which used to discard every sold-out swatch.
    """
    snapshot = detect_product(load_fixture("amazon-like.html"), "https://www.amazon.in/dp/B0CHX1W1XY")

    assert snapshot.adapter == "amazon"
    assert snapshot.store_name == "Amazon India"
    assert snapshot.name == "Acme Studio Wireless Headphones (Midnight Black)"
    assert snapshot.brand == "Acme"
    assert snapshot.current_price == Decimal("8499.00")
    assert snapshot.original_price == Decimal("12999.00")
    assert snapshot.product_id == "B0CHX1W1XY"

    by_name = {variant.name: variant.availability for variant in snapshot.variants}
    assert by_name["Max"] is StockStatus.OUT_OF_STOCK
    assert by_name["Pro"] is StockStatus.IN_STOCK


def test_adapters_are_an_enhancement_not_a_requirement():
    """Same markup, a hostname no adapter claims."""
    snapshot = detect_product(
        load_fixture("amazon-like.html"), "https://www.some-marketplace.example/dp/B0CHX1W1XY"
    )

    assert snapshot.adapter == "generic"
    assert snapshot.name is not None
    assert "Acme Studio Wireless Headphones" in snapshot.name
    assert snapshot.current_price == Decimal("8499.00")


def test_listing_page_is_refused():
    snapshot = detect_product(
        load_fixture("listing-page.html"),
        "https://www.example-store.com/women/jackets",
    )

    # It may find *a* name, but it must not clear the bar for a product page.
    assert snapshot.confidence < 55


def test_page_globals_from_analytics_payload():
    data_layer = [
        {"event": "gtm.js"},
        {
            "event": "productDetail",
            "ecommerce": {
                "detail": {
                    "products": [
                        {
                            "name": "Merino Wool Crew Neck",
                            "id": "MW-2231",
                            "price": "4499",
                            "brand": "Northbound",
                            "category": "Knitwear",
                        }
                    ]
                }
            },
        },
    ]

    snapshot = detect_product(
        "<html><head><title>Merino Wool Crew Neck</title></head>"
        "<body><main><h1>Merino Wool Crew Neck</h1><button>Add to cart</button></main></body></html>",
        "https://www.northbound.example/p/merino-crew-2231",
        page_globals={"dataLayer": data_layer},
    )

    assert snapshot.name == "Merino Wool Crew Neck"
    assert snapshot.brand == "Northbound"
    assert snapshot.current_price == Decimal("4499.00")


def test_never_claims_stock_it_cannot_verify():
    snapshot = detect_product(
        "<html><head><meta property='og:type' content='product'>"
        "<meta property='og:title' content='Handwoven Cotton Throw'></head>"
        "<body><main><h1>Handwoven Cotton Throw</h1></main></body></html>",
        "https://www.smallweaver.example/product/handwoven-throw",
    )

    assert snapshot.availability is StockStatus.UNKNOWN
    assert snapshot.current_price is None
