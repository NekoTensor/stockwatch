"""Money parsing and store identification.

Mirrors `extension/tests/price.test.ts` and `stores.test.ts` case for case. The
two implementations must agree, or a product's first monitored check would
report a price change that never happened.
"""

from __future__ import annotations

from decimal import Decimal

from app.detection.stores import identify_store, prettify_hostname
from app.detection.urls import (
    clean_url,
    looks_like_non_product_url,
    looks_like_product_url,
    product_id_from_url,
)
from app.detection.util.availability import from_flag, from_schema, from_text, merge
from app.detection.util.price import currency_from_hostname, parse_amount, parse_price
from app.models.enums import StockStatus


class TestParseAmount:
    def test_indian_grouping(self):
        assert parse_amount("12,990") == Decimal("12990")
        assert parse_amount("1,24,999") == Decimal("124999")

    def test_us_grouping(self):
        assert parse_amount("1,299.99") == Decimal("1299.99")

    def test_european_grouping(self):
        assert parse_amount("1.299,99") == Decimal("1299.99")
        assert parse_amount("1.500") == Decimal("1500")

    def test_lone_separator_with_two_digits_is_a_decimal_point(self):
        assert parse_amount("59,99") == Decimal("59.99")
        assert parse_amount("59.99") == Decimal("59.99")

    def test_space_as_thousands_separator(self):
        assert parse_amount("2 499") == Decimal("2499")

    def test_no_number(self):
        assert parse_amount("Sold out") is None


class TestParsePrice:
    def test_amount_and_currency(self):
        assert parse_price("₹12,990") == (Decimal("12990"), "INR")
        assert parse_price("Rs. 2,499/-") == (Decimal("2499"), "INR")
        assert parse_price("$1,299.99") == (Decimal("1299.99"), "USD")
        assert parse_price("59,99 €") == (Decimal("59.99"), "EUR")

    def test_specific_dollar_beats_bare_dollar(self):
        assert parse_price("A$149.00")[1] == "AUD"

    def test_ignores_surrounding_prose(self):
        assert parse_price("MRP ₹3,999 (incl. of all taxes)")[0] == Decimal("3999")

    def test_rejects_zero(self):
        assert parse_price("₹0") == (None, None)


def test_currency_from_hostname():
    assert currency_from_hostname("amazon.in") == "INR"
    assert currency_from_hostname("asos.co.uk") == "GBP"
    assert currency_from_hostname("myntra.com") is None


class TestStores:
    def test_known_stores_across_subdomains(self):
        assert identify_store("www.zara.com").name == "Zara"
        assert identify_store("www2.hm.com").name == "H&M"
        assert identify_store("m.myntra.com").name == "Myntra"
        assert identify_store("www.ajio.com").slug == "ajio"

    def test_amazon_regions(self):
        assert identify_store("amazon.in").name == "Amazon India"
        assert identify_store("www.amazon.co.uk").name == "Amazon UK"
        assert identify_store("amazon.com").name == "Amazon"

    def test_most_specific_domain_wins(self):
        assert identify_store("shop.mango.com").slug == "mango"
        assert identify_store("www.adidas.co.in").slug == "adidas"

    def test_unknown_store_still_gets_a_name(self):
        identity = identify_store("shop.some-boutique.co.uk")
        assert identity.known is False
        assert identity.slug == "generic"
        assert identity.name == "Some Boutique"

    def test_prettify(self):
        assert prettify_hostname("example.com") == "Example"
        assert prettify_hostname("store.velvet-lane.in") == "Velvet Lane"


class TestUrls:
    def test_strips_campaign_params_but_keeps_selectors(self):
        cleaned = clean_url("https://www.myntra.com/x/2296012/buy?utm_source=email&size=32")
        assert "size=32" in cleaned
        assert "utm_source" not in cleaned

    def test_removes_amazon_ref_segment(self):
        assert clean_url("https://www.amazon.in/dp/B0CHX1W1XY/ref=sr_1_3?psc=1") == (
            "https://www.amazon.in/dp/B0CHX1W1XY"
        )

    def test_product_ids(self):
        assert product_id_from_url("https://www.amazon.in/dp/B0CHX1W1XY") == "B0CHX1W1XY"
        assert product_id_from_url("https://www.zara.com/in/en/jacket-p07840321.html") == "07840321"
        assert product_id_from_url("https://www2.hm.com/en_in/productpage.1234567001.html") == "1234567001"

    def test_product_vs_listing(self):
        assert looks_like_product_url("https://www.ajio.com/p/441088931")
        assert looks_like_non_product_url("https://www.ajio.com/")
        assert looks_like_non_product_url("https://www.ajio.com/search?q=jeans")


class TestAvailability:
    def test_schema_vocabulary(self):
        assert from_schema("https://schema.org/InStock") is StockStatus.IN_STOCK
        assert from_schema("http://schema.org/OutOfStock") is StockStatus.OUT_OF_STOCK
        assert from_schema("SoldOut") is StockStatus.OUT_OF_STOCK

    def test_sold_out_phrases_are_checked_first(self):
        assert from_text("Notify me when available") is StockStatus.OUT_OF_STOCK
        assert from_text("Add to bag") is StockStatus.IN_STOCK

    def test_counts(self):
        assert from_flag(0) is StockStatus.OUT_OF_STOCK
        assert from_flag(4) is StockStatus.IN_STOCK
        assert from_flag(None) is StockStatus.UNKNOWN

    def test_unknown_never_becomes_out_of_stock(self):
        assert from_schema("SomethingWeHaveNeverSeen") is StockStatus.UNKNOWN
        assert from_text("Ships from and sold by Example") is StockStatus.UNKNOWN
        assert merge(StockStatus.UNKNOWN, StockStatus.UNKNOWN) is StockStatus.UNKNOWN
        assert merge(StockStatus.UNKNOWN, StockStatus.IN_STOCK) is StockStatus.IN_STOCK
        assert merge(StockStatus.OUT_OF_STOCK, StockStatus.UNKNOWN) is StockStatus.OUT_OF_STOCK

    def test_disagreement_resolves_optimistically(self):
        assert merge(StockStatus.OUT_OF_STOCK, StockStatus.IN_STOCK) is StockStatus.IN_STOCK
