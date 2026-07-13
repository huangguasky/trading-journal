from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Symbol:
    raw: str
    market: str
    display: str
    provider_code: str


def normalize_symbol(value: str) -> Symbol:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("symbol is required")
    text = raw.upper().replace(" ", "")

    if text.startswith("HK"):
        digits = re.sub(r"\D", "", text).zfill(4)
        return Symbol(raw, "hk", f"HK{digits}", f"{digits}.HK")
    if text.endswith(".HK"):
        digits = text[:-3].zfill(4)
        return Symbol(raw, "hk", f"HK{digits}", f"{digits}.HK")

    match = re.fullmatch(r"(SH|SZ|BJ)?\.?(\d{6})(\.(SH|SZ|BJ|SS))?", text)
    if match:
        digits = match.group(2)
        exchange = match.group(1) or match.group(4) or infer_cn_exchange(digits)
        suffix = "SS" if exchange == "SH" else exchange
        return Symbol(raw, "cn", f"{exchange}{digits}", f"{digits}.{suffix}")

    return Symbol(raw, "us", text, text)


def infer_cn_exchange(digits: str) -> str:
    if digits.startswith(("5", "6", "9")):
        return "SH"
    if digits.startswith(("4", "8")):
        return "BJ"
    return "SZ"

