from types import SimpleNamespace

from app.schemas import Category
from app.services import classifier


def test_classify_maps_tool_use_blocks(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        tool_block = SimpleNamespace(
            type="tool_use",
            name="submit_classified_items",
            input={
                "items": [
                    {
                        "index": 0,
                        "normalized_name": "Whole Milk 1 Gallon",
                        "category": "dairy",
                        "needs_refrigeration": True,
                    },
                    {
                        "index": 1,
                        "normalized_name": "Bananas",
                        "category": "produce",
                        "needs_refrigeration": False,
                    },
                ]
            },
        )
        return SimpleNamespace(content=[tool_block])

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(classifier, "_client", lambda: fake_client)

    result = classifier.classify(["WHL MLK 1GAL", "BANANAS"])

    assert len(result) == 2
    assert result[0].normalized_name == "Whole Milk 1 Gallon"
    assert result[0].category == Category.DAIRY
    assert result[0].needs_refrigeration is True
    assert result[1].category == Category.PRODUCE

    # Verify cache control is set on the system prompt
    system = captured["system"]
    assert system[0]["cache_control"]["type"] == "ephemeral"
    # Verify tool_choice forces the tool
    assert captured["tool_choice"]["name"] == "submit_classified_items"


def test_classify_falls_back_for_missing_indices(monkeypatch):
    def fake_create(**kwargs):
        tool_block = SimpleNamespace(
            type="tool_use",
            name="submit_classified_items",
            input={
                "items": [
                    {
                        "index": 0,
                        "normalized_name": "Apples",
                        "category": "produce",
                        "needs_refrigeration": False,
                    }
                    # index 1 missing -> should fall back
                ]
            },
        )
        return SimpleNamespace(content=[tool_block])

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(classifier, "_client", lambda: fake_client)

    result = classifier.classify(["Apples", "Mystery Item"])

    assert len(result) == 2
    assert result[1].normalized_name == "Mystery Item"
    assert result[1].category == Category.OTHER
    assert result[1].needs_refrigeration is False


def test_classify_empty_returns_empty():
    assert classifier.classify([]) == []
