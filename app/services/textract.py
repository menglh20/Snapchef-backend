from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any

import boto3

from app.config import get_settings
from app.schemas import RawLineItem, ReceiptTotals


@lru_cache
def _client():
    settings = get_settings()
    return boto3.client(
        "textract",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def analyze_expense(image_bytes: bytes) -> dict[str, Any]:
    return _client().analyze_expense(Document={"Bytes": image_bytes})


def _parse_amount(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        return float(Decimal(cleaned))
    except (InvalidOperation, ValueError):
        return None


def _parse_quantity(text: str | None) -> float:
    if not text:
        return 1.0
    cleaned = text.strip().lower().rstrip("x").strip()
    try:
        return float(Decimal(cleaned))
    except (InvalidOperation, ValueError):
        return 1.0


def _field_text(field: dict[str, Any]) -> str | None:
    value = field.get("ValueDetection") or {}
    text = value.get("Text")
    return text.strip() if isinstance(text, str) else None


def parse_response(response: dict[str, Any]) -> tuple[list[RawLineItem], ReceiptTotals]:
    items: list[RawLineItem] = []
    totals = ReceiptTotals()

    for doc in response.get("ExpenseDocuments", []):
        for group in doc.get("LineItemGroups", []):
            for line_item in group.get("LineItems", []):
                fields_by_type: dict[str, str] = {}
                for f in line_item.get("LineItemExpenseFields", []):
                    type_text = (f.get("Type") or {}).get("Text")
                    if not type_text:
                        continue
                    text = _field_text(f)
                    if text:
                        fields_by_type[type_text] = text

                raw_name = fields_by_type.get("ITEM")
                if not raw_name:
                    continue

                items.append(
                    RawLineItem(
                        raw_name=raw_name,
                        quantity=_parse_quantity(fields_by_type.get("QUANTITY")),
                        unit_price=_parse_amount(fields_by_type.get("UNIT_PRICE")),
                        total_price=_parse_amount(fields_by_type.get("PRICE")),
                    )
                )

        for f in doc.get("SummaryFields", []):
            type_text = (f.get("Type") or {}).get("Text")
            text = _field_text(f)
            if not type_text or not text:
                continue
            amount = _parse_amount(text)
            if amount is None:
                continue
            if type_text == "SUBTOTAL" and totals.subtotal is None:
                totals.subtotal = amount
            elif type_text == "TAX" and totals.tax is None:
                totals.tax = amount
            elif type_text == "TOTAL" and totals.total is None:
                totals.total = amount

    return items, totals
