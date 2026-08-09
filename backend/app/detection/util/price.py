"""Money parsing — the Python twin of the extension's `lib/price.ts`.

The two implementations are tested against the same cases (see
`tests/test_price.py` here and `extension/tests/price.test.ts` there), because a
disagreement between them would show up as a phantom price change on the first
check after a product is tracked.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

#: Longest run of digits and separators. Permissive on purpose: writing out
#: grouping rules means picking a locale, and "1,24,999" (Indian lakh grouping)
#: is not the same grammar as "1,299".
PRICE_PATTERN = re.compile(r"\d[\d.,\s']*\d|\d")

CURRENCY_MARKER = re.compile(
    r"[₹$€£¥₩₽₺฿₫₴₱₦]|\b(?:INR|USD|EUR|GBP|JPY|CNY|AED|SAR|SGD|AUD|CAD|CHF|SEK|NOK|DKK|"
    r"PLN|ZAR|MYR|IDR|PHP|THB|TRY|VND|KRW|RUB|BRL|MXN|NZD|HKD|Rs\.?|RM|Rp)\b",
    re.IGNORECASE,
)

#: Ordered longest-first so "A$" beats "$" and a bare dollar sign is last.
_CURRENCY_TOKENS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bA\$|\bAU\$", re.I), "AUD"),
    (re.compile(r"\bCA?\$", re.I), "CAD"),
    (re.compile(r"\bNZ\$", re.I), "NZD"),
    (re.compile(r"\bS\$|\bSGD\b", re.I), "SGD"),
    (re.compile(r"\bHK\$", re.I), "HKD"),
    (re.compile(r"\bR\$", re.I), "BRL"),
    (re.compile(r"\bMX\$|\bMXN\b", re.I), "MXN"),
    (re.compile(r"₹|\bRs\.?\b|\bINR\b|\bRupees?\b", re.I), "INR"),
    (re.compile(r"€|\bEUR\b", re.I), "EUR"),
    (re.compile(r"£|\bGBP\b", re.I), "GBP"),
    (re.compile(r"\bCN¥|\bRMB\b|\bCNY\b", re.I), "CNY"),
    (re.compile(r"¥|\bJPY\b", re.I), "JPY"),
    (re.compile(r"₩|\bKRW\b", re.I), "KRW"),
    (re.compile(r"₽|\bRUB\b", re.I), "RUB"),
    (re.compile(r"\bAED\b|د\.إ", re.I), "AED"),
    (re.compile(r"\bSAR\b|﷼", re.I), "SAR"),
    (re.compile(r"₺|\bTRY\b", re.I), "TRY"),
    (re.compile(r"฿|\bTHB\b", re.I), "THB"),
    (re.compile(r"₫|\bVND\b", re.I), "VND"),
    (re.compile(r"₴|\bUAH\b", re.I), "UAH"),
    (re.compile(r"\bzł\b|\bPLN\b", re.I), "PLN"),
    (re.compile(r"\bCHF\b", re.I), "CHF"),
    (re.compile(r"\bSEK\b", re.I), "SEK"),
    (re.compile(r"\bNOK\b", re.I), "NOK"),
    (re.compile(r"\bDKK\b", re.I), "DKK"),
    (re.compile(r"\bRM\b|\bMYR\b", re.I), "MYR"),
    (re.compile(r"\bRp\b|\bIDR\b", re.I), "IDR"),
    (re.compile(r"₱|\bPHP\b", re.I), "PHP"),
    (re.compile(r"₦|\bNGN\b", re.I), "NGN"),
    (re.compile(r"\bZAR\b", re.I), "ZAR"),
    (re.compile(r"\bUSD\b|\$"), "USD"),
]

_TLD_CURRENCY: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\.co\.in$|\.in$"), "INR"),
    (re.compile(r"\.co\.uk$|\.uk$"), "GBP"),
    (re.compile(r"\.(de|fr|es|it|nl|be|ie|at|pt|fi|gr|eu)$"), "EUR"),
    (re.compile(r"\.ca$"), "CAD"),
    (re.compile(r"\.com\.au$|\.au$"), "AUD"),
    (re.compile(r"\.co\.jp$|\.jp$"), "JPY"),
    (re.compile(r"\.ae$"), "AED"),
    (re.compile(r"\.com\.sg$|\.sg$"), "SGD"),
    (re.compile(r"\.co\.za$"), "ZAR"),
    (re.compile(r"\.com\.br$"), "BRL"),
]


def currency_from_text(text: str) -> str | None:
    for pattern, code in _CURRENCY_TOKENS:
        if pattern.search(text):
            return code
    return None


def currency_from_hostname(hostname: str) -> str | None:
    for pattern, code in _TLD_CURRENCY:
        if pattern.search(hostname):
            return code
    return None


def parse_amount(raw: str) -> Decimal | None:
    """Work out which separator is the decimal point, then convert.

    - both ``.`` and ``,`` present -> the rightmost is the decimal separator
    - one separator appearing more than once -> it groups thousands
    - one separator with exactly 3 digits after it -> thousands ("12,990")
    - one separator with 1-2 digits after it -> decimal ("45,50")
    """
    match = PRICE_PATTERN.search(raw)
    if not match:
        return None

    token = re.sub(r"[\s']", "", match.group(0))
    dots = token.count(".")
    commas = token.count(",")

    if dots and commas:
        decimal_sep = "." if token.rfind(".") > token.rfind(",") else ","
        group_sep = "," if decimal_sep == "." else "."
        token = token.replace(group_sep, "").replace(decimal_sep, ".")
    elif dots or commas:
        sep = "." if dots else ","
        count = dots or commas
        tail = token[token.rfind(sep) + 1 :]
        token = token.replace(sep, "") if (count > 1 or len(tail) == 3) else token.replace(sep, ".")

    try:
        value = Decimal(token)
    except (InvalidOperation, ValueError):
        return None

    return value if value.is_finite() else None


def parse_price(raw: object) -> tuple[Decimal | None, str | None]:
    """Return ``(amount, currency)``. Either may be ``None``."""
    if isinstance(raw, (int, float, Decimal)):
        value = Decimal(str(raw))
        return (value, None) if value.is_finite() and value > 0 else (None, None)

    if not isinstance(raw, str) or not raw.strip():
        return None, None

    amount = parse_amount(raw)
    if amount is None or amount <= 0:
        return None, None

    return amount, currency_from_text(raw)


def to_amount(raw: object) -> Decimal | None:
    """Just the number, for fields that are already known to be money."""
    return parse_price(raw)[0]


def quantise(value: Decimal | None) -> Decimal | None:
    """Two decimal places, matching the ``Numeric(12, 2)`` columns.

    Done before comparison as well as before storage: without it a scraped
    ``1149.000`` and a stored ``1149.00`` compare unequal and every check would
    look like a price change.
    """
    if value is None:
        return None
    return value.quantize(Decimal("0.01"))
