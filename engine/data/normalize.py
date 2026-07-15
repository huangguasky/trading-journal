from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Symbol:
    """Canonical representation of a stock symbol and its market/exchange."""
    raw: str
    market: str
    display: str
    provider_code: str


def normalize_symbol(value: str) -> Symbol:
    """Normalize common CN, HK, and US ticker formats into a canonical symbol."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("symbol is required")
    text = raw.upper().replace(" ", "")

    # Stable aliases used by market-wide reports.  They keep index symbols in
    # the correct market while exposing the actual Yahoo ticker to providers.
    index_aliases = {
        "HK800000": ("hk", "HK恒生指数", "^HSI"),
        "HK800700": ("hk", "HK恒生科技", "^HSTECH"),
        "HK800100": ("hk", "HK国企指数", "^HSCE"),
    }
    if text in index_aliases:
        market, display, provider_code = index_aliases[text]
        return Symbol(raw, market, display, provider_code)

    hk_prefix = re.fullmatch(r"HK(\d{1,5})", text)
    if hk_prefix:
        digits = normalize_hk_digits(hk_prefix.group(1))
        return Symbol(raw, "hk", f"HK{digits}", f"{digits}.HK")
    hk_suffix = re.fullmatch(r"(\d{1,5})\.HK", text)
    if hk_suffix:
        digits = normalize_hk_digits(hk_suffix.group(1))
        return Symbol(raw, "hk", f"HK{digits}", f"{digits}.HK")

    match = re.fullmatch(r"(SH|SZ|BJ)?\.?(\d{6})(\.(SH|SZ|BJ|SS))?", text)
    if match:
        digits = match.group(2)
        exchange = match.group(1) or match.group(4) or infer_cn_exchange(digits)
        suffix = "SS" if exchange == "SH" else exchange
        return Symbol(raw, "cn", f"{exchange}{digits}", f"{digits}.{suffix}")

    return Symbol(raw, "us", text, text)


def normalize_hk_digits(digits: str) -> str:
    """Canonicalize common four-digit and zero-padded five-digit HK codes."""
    return str(int(digits)).zfill(4)


def infer_cn_exchange(digits: str) -> str:
    """Infer the Chinese exchange from the conventional numeric ticker prefix."""
    if digits.startswith(("5", "6", "9")):
        return "SH"
    if digits.startswith(("4", "8")):
        return "BJ"
    return "SZ"
