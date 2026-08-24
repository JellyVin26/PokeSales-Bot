"""Parser for sale amount and payment method from Telegram captions."""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedAmount:
    """Parsed amount and currency from a Telegram caption."""
    raw: str
    amount: float
    currency: str = "MYR"
    payment_method: str = "Unknown"


def parse_amount(raw: str) -> Optional[ParsedAmount]:
    """Parse a sale amount from a Telegram caption.

    Supported formats (all default currency MYR):
        13
        RM 13
        RM13
        13 RM
        13.00
        RM 13.00
        RM 13 cash
        RM 13 qr
        RM 13 transfer
        RM 13 card

    Returns None if no amount can be parsed.
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()
    result = _parse_amount_internal(text)
    if result is None:
        return None

    amount_val, currency, payment = result

    # Normalize payment method from the raw text
    payment_lower = text.lower()
    payment_method = _normalize_payment_method(payment_lower)

    return ParsedAmount(
        raw=text,
        amount=amount_val,
        currency=currency,
        payment_method=payment_method,
    )


def _parse_amount_internal(text: str) -> Optional[tuple[float, str, str]]:
    """Return (amount, currency, payment_method_key)."""

    # Pattern A: "13 RM" or "13.50 RM"
    m = re.match(r"^(\d+(?:\.\d{1,2})?)\s+rm\s+(.+)$", text, re.IGNORECASE)
    if m:
        amount = float(m.group(1))
        after = m.group(3).strip()
        # Payment is in the text after "RM "
        # e.g. "RM 13 cash" -> payment = "Cash"
        payment = _extract_payment_from_text(after)
        return amount, "MYR", payment

    # Pattern B: "RM 13" or "RM 13.50" (currency first)
    m = re.match(r"^rm\s+(\d+(?:\.\d{1,2})?)(.+)$", text, re.IGNORECASE)
    if m:
        amount = float(m.group(1))
        after = m.group(2).strip()
        # Payment in text after amount
        payment = _extract_payment_from_text(after)
        return amount, "MYR", payment

    # Pattern C: "RM13" or "RM13.50" (attached)
    m = re.match(r"^rm(\d+(?:\.\d{1,2})?)$", text, re.IGNORECASE)
    if m:
        amount = float(m.group(1))
        return amount, "MYR", "Unknown"

    # Pattern D: plain "13" or "13.50"
    m = re.match(r"^(\d+(?:\.\d{1,2})?)$", text)
    if m:
        amount = float(m.group(1))
        return amount, "MYR", "Unknown"

    # Pattern E: "13 RM" - amount at start followed by RM (fallback)
    m = re.match(r"^(\d+(?:\.\d{1,2})?)\s+rm\s*$", text, re.IGNORECASE)
    if m:
        amount = float(m.group(1))
        return amount, "MYR", "Unknown"

    return None


def _extract_payment_from_text(after_text: str) -> str:
    """Extract payment method from text that follows the amount/currency.

    Supported: cash, qr, transfer, card, unknown
    """
    if not after_text:
        return "Unknown"

    # Tokenize by whitespace to check individual words
    tokens = after_text.split()

    # Look for exact payment tokens (case-insensitive)
    payment_tokens = {
        "cash": "Cash",
        "qr": "QR",
        "transfer": "Bank Transfer",
        "card": "Card",
    }

    for token in tokens:
        if token.lower() in payment_tokens:
            return payment_tokens[token.lower()]

    # If no token matched but text is non-empty, check if any known word is present
    text_lower = after_text.lower()
    if re.search(r'\bcash\b', text_lower):
        return "Cash"
    if re.search(r'\bqr\b', text_lower):
        return "QR"
    if re.search(r'\btransfer\b', text_lower):
        return "Bank Transfer"
    if re.search(r'\bcard\b', text_lower):
        return "Card"

    return "Unknown"


def _normalize_payment_method(raw: str) -> str:
    """Normalize to canonical payment method names."""
    mapping = {
        "cash": "Cash",
        "qr": "QR",
        "transfer": "Bank Transfer",
        "bank transfer": "Bank Transfer",
        "card": "Card",
        "credit card": "Card",
        "unknown": "Unknown",
        "": "Unknown",
    }
    for key, value in mapping.items():
        if key in raw.lower():
            return value
    return "Unknown"