import json
from pathlib import Path

from app.services import textract

FIXTURE = Path(__file__).parent / "fixtures" / "textract_sample.json"


def test_parse_response_extracts_items_and_totals():
    response = json.loads(FIXTURE.read_text())

    items, totals = textract.parse_response(response)

    assert len(items) == 3

    milk = items[0]
    assert milk.raw_name == "WHL MLK 1GAL"
    assert milk.quantity == 1.0
    assert milk.total_price == 3.99
    assert milk.unit_price is None

    bananas = items[1]
    assert bananas.raw_name == "BANANAS"
    assert bananas.quantity == 2.0
    assert bananas.unit_price == 0.59
    assert bananas.total_price == 1.18

    chips = items[2]
    assert chips.raw_name == "POTATO CHIPS"
    assert chips.quantity == 1.0  # default when missing
    assert chips.total_price == 3.49

    assert totals.subtotal == 11.97
    assert totals.tax == 0.96
    assert totals.total == 12.93


def test_parse_response_handles_empty_doc():
    items, totals = textract.parse_response({"ExpenseDocuments": []})
    assert items == []
    assert totals.subtotal is None
    assert totals.tax is None
    assert totals.total is None
