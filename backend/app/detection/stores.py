"""Store identification from a hostname.

Naming the shop only. Detection never depends on a store being listed here -
an unknown host gets a derived label and the full generic pipeline.

Kept deliberately in sync with `extension/src/stores/registry.ts`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.detection.util.text import title_case


@dataclass(frozen=True, slots=True)
class StoreDefinition:
    slug: str
    name: str
    domains: tuple[str, ...]
    currency: str | None = None
    product_url_patterns: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class StoreIdentity:
    slug: str
    name: str
    domain: str
    known: bool
    currency: str | None = None
    definition: StoreDefinition | None = None


STORES: tuple[StoreDefinition, ...] = (
    StoreDefinition("zara", "Zara", ("zara.com",), None, (r"-p\d{6,}\.html",)),
    StoreDefinition("hm", "H&M", ("hm.com", "www2.hm.com"), None, (r"productpage\.\d+\.html",)),
    StoreDefinition("nykaafashion", "Nykaa Fashion", ("nykaafashion.com",), "INR", (r"/p/\d+",)),
    StoreDefinition("nykaa", "Nykaa", ("nykaa.com",), "INR", (r"/p/\d+",)),
    StoreDefinition("myntra", "Myntra", ("myntra.com",), "INR", (r"/\d+/buy",)),
    StoreDefinition("ajio", "AJIO", ("ajio.com",), "INR", (r"/p/\d+",)),
    StoreDefinition(
        "amazon",
        "Amazon",
        (
            "amazon.in", "amazon.com", "amazon.co.uk", "amazon.de", "amazon.fr", "amazon.it",
            "amazon.es", "amazon.ca", "amazon.com.au", "amazon.co.jp", "amazon.ae", "amazon.sg",
            "amazon.nl", "amazon.se", "amazon.pl", "amazon.com.br", "amazon.com.mx",
        ),
        None,
        (r"/(dp|gp/product)/[A-Z0-9]{10}",),
    ),
    StoreDefinition("flipkart", "Flipkart", ("flipkart.com",), "INR", (r"/p/itm[a-z0-9]+",)),
    StoreDefinition("nike", "Nike", ("nike.com",), None, (r"/t/",)),
    StoreDefinition(
        "adidas", "Adidas", ("adidas.com", "adidas.co.in", "adidas.co.uk", "adidas.de", "adidas.ae"),
        None, (r"/[A-Z0-9]{6}\.html",),
    ),
    StoreDefinition("uniqlo", "Uniqlo", ("uniqlo.com",), None, (r"/products/E\d+",)),
    StoreDefinition("asos", "ASOS", ("asos.com",), None, (r"/prd/\d+",)),
    StoreDefinition(
        "decathlon", "Decathlon", ("decathlon.in", "decathlon.com", "decathlon.co.uk", "decathlon.fr"),
        None, (r"/p/",),
    ),
    StoreDefinition(
        "sephora", "Sephora", ("sephora.com", "sephora.co.uk", "sephora.fr", "sephora.in"),
        None, (r"/product/",),
    ),
    StoreDefinition("meesho", "Meesho", ("meesho.com",), "INR"),
    StoreDefinition("tatacliq", "Tata CLiQ", ("tatacliq.com",), "INR"),
    StoreDefinition("westside", "Westside", ("westside.com",), "INR"),
    StoreDefinition("marksandspencer", "Marks & Spencer", ("marksandspencer.com", "marksandspencer.in")),
    StoreDefinition("shoppersstop", "Shoppers Stop", ("shoppersstop.com",), "INR"),
    StoreDefinition("bewakoof", "Bewakoof", ("bewakoof.com",), "INR"),
    StoreDefinition("snitch", "Snitch", ("snitch.com", "snitch.co.in"), "INR"),
    StoreDefinition("levis", "Levi's", ("levi.in", "levi.com", "levis.in")),
    StoreDefinition("puma", "Puma", ("puma.com",)),
    StoreDefinition("zalando", "Zalando", ("zalando.com", "zalando.co.uk", "zalando.de")),
    StoreDefinition("shein", "SHEIN", ("shein.com", "shein.in")),
    StoreDefinition("lifestylestores", "Lifestyle", ("lifestylestores.com",), "INR"),
    StoreDefinition("pantaloons", "Pantaloons", ("pantaloons.com",), "INR"),
    StoreDefinition("mango", "Mango", ("mango.com", "shop.mango.com")),
    StoreDefinition("ikea", "IKEA", ("ikea.com",)),
    StoreDefinition("croma", "Croma", ("croma.com",), "INR"),
    StoreDefinition("reliancedigital", "Reliance Digital", ("reliancedigital.in",), "INR"),
)

AMAZON_REGIONS = {
    "amazon.in": "Amazon India",
    "amazon.com": "Amazon",
    "amazon.co.uk": "Amazon UK",
    "amazon.de": "Amazon Germany",
    "amazon.fr": "Amazon France",
    "amazon.it": "Amazon Italy",
    "amazon.es": "Amazon Spain",
    "amazon.ca": "Amazon Canada",
    "amazon.com.au": "Amazon Australia",
    "amazon.co.jp": "Amazon Japan",
    "amazon.ae": "Amazon UAE",
    "amazon.sg": "Amazon Singapore",
    "amazon.com.br": "Amazon Brazil",
    "amazon.com.mx": "Amazon Mexico",
}

_TLD_FRAGMENTS = {"co", "com", "net", "org", "gov", "ac", "edu"}
_GENERIC_LABELS = {"shop", "store", "www", "m", "mobile"}


def _matches(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def find_store_definition(hostname: str) -> tuple[StoreDefinition, str] | None:
    """Longest matching domain wins, so "shop.mango.com" beats "mango.com"."""
    best: tuple[StoreDefinition, str] | None = None
    for definition in STORES:
        for domain in definition.domains:
            if _matches(hostname, domain) and (best is None or len(domain) > len(best[1])):
                best = (definition, domain)
    return best


def prettify_hostname(hostname: str) -> str:
    parts = [part for part in hostname.split(".") if part]
    if not parts:
        return "Unknown Store"

    index = max(len(parts) - 2, 0)
    if index >= 1 and parts[index] in _TLD_FRAGMENTS:
        index -= 1

    core = parts[index]
    if core in _GENERIC_LABELS:
        core = next((part for part in parts if part not in _GENERIC_LABELS and part not in _TLD_FRAGMENTS), core)

    return title_case(core.replace("-", " ")) or "Unknown Store"


def identify_store(hostname: str) -> StoreIdentity:
    host = re.sub(r"^www\d*\.", "", hostname.lower())
    match = find_store_definition(host)

    if match is None:
        return StoreIdentity("generic", prettify_hostname(host) or "Unknown Store", host, False)

    definition, domain = match
    name = AMAZON_REGIONS.get(domain, definition.name) if definition.slug == "amazon" else definition.name
    return StoreIdentity(definition.slug, name, host, True, definition.currency, definition)
