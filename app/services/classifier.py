import json
import logging
from functools import lru_cache

import anthropic

from app.config import get_settings
from app.schemas import CATEGORY_VALUES, PRODUCE_VOCAB, Category, ClassifiedItem

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = (
    "You normalize grocery receipt line items. For each item the user gives you, "
    "produce a clean human-readable name (expand common abbreviations like WHL MLK -> Whole Milk), "
    "assign a category from the allowed list, and decide whether it must be refrigerated to stay safe "
    "or fresh in a typical home setting.\n\n"
    f"Allowed categories: {', '.join(CATEGORY_VALUES)}.\n\n"
    "Refrigeration rules:\n"
    "- Set needs_refrigeration=true for fresh dairy, fresh meat/seafood, fresh produce that wilts quickly "
    "(leafy greens, berries), opened condiments people refrigerate, deli items, eggs in markets where "
    "they are sold refrigerated.\n"
    "- Set needs_refrigeration=false for frozen items (they go to the freezer, not the fridge), shelf-stable "
    "pantry items, beverages that ship at room temperature, snacks, household goods, sturdy produce like "
    "potatoes/onions/winter squash.\n"
    "- When ambiguous, prefer the safer choice for perishables.\n\n"
    "Canonical produce names (soft preference): when an item is a fresh fruit or vegetable that "
    "matches one of the names below, set normalized_name to that exact name (singular, Title Case) "
    "so produce naming stays consistent with the rest of the system. This applies only to the "
    "produce name itself — do not append quantities/weights to it. For produce not in this list, "
    "or for any non-produce item, normalize the name normally and ignore this list.\n"
    f"Canonical names: {', '.join(PRODUCE_VOCAB)}.\n\n"
    "Always return results via the submit_classified_items tool. Preserve the input index for every item."
)

TOOL_DEFINITION = {
    "name": "submit_classified_items",
    "description": "Return the cleaned name, category, and refrigeration flag for every input item.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "minimum": 0},
                        "normalized_name": {"type": "string"},
                        "category": {"type": "string", "enum": CATEGORY_VALUES},
                        "needs_refrigeration": {"type": "boolean"},
                    },
                    "required": ["index", "normalized_name", "category", "needs_refrigeration"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    },
}


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


def classify(names: list[str]) -> list[ClassifiedItem]:
    if not names:
        return []

    user_payload = {"items": [{"index": i, "name": n} for i, n in enumerate(names)]}

    response = _client().messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[TOOL_DEFINITION],
        tool_choice={"type": "tool", "name": "submit_classified_items"},
        messages=[
            {
                "role": "user",
                "content": (
                    "Classify each item below. Use the same index in your response.\n\n"
                    + json.dumps(user_payload, ensure_ascii=False)
                ),
            }
        ],
    )

    tool_input: dict | None = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_classified_items":
            tool_input = block.input  # type: ignore[assignment]
            break

    if not tool_input or "items" not in tool_input:
        raise RuntimeError("Claude did not return a tool_use response")

    by_index: dict[int, ClassifiedItem] = {}
    for entry in tool_input["items"]:
        try:
            item = ClassifiedItem(**entry)
        except Exception:
            logger.warning("Skipping malformed classifier entry: %s", entry)
            continue
        by_index[item.index] = item

    results: list[ClassifiedItem] = []
    for i, name in enumerate(names):
        existing = by_index.get(i)
        if existing is not None:
            results.append(existing)
        else:
            results.append(
                ClassifiedItem(
                    index=i,
                    normalized_name=name,
                    category=Category.OTHER,
                    needs_refrigeration=False,
                )
            )
    return results
