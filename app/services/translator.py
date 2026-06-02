"""Translate a Baidu 果蔬 (fruit/vegetable) name into a clean English produce name.

Uses Claude Haiku with forced tool_use so the response is guaranteed-shape, matching
the pattern in classifier.py / recipes.py. Haiku is plenty for a one-word translation.
"""

import logging
from functools import lru_cache

import anthropic

from app.config import get_settings

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = (
    "You translate the name of a single fruit or vegetable into English. The user gives you "
    "a produce name (usually Chinese). Return the common English name in Title Case "
    "(e.g. '西红柿' -> 'Tomato', '红富士苹果' -> 'Fuji Apple'). Use the everyday grocery "
    "name, singular, no extra words, no punctuation. Always return the result via the "
    "submit_translation tool."
)

TOOL_DEFINITION = {
    "name": "submit_translation",
    "description": "Return the English name of the given fruit or vegetable.",
    "input_schema": {
        "type": "object",
        "properties": {
            "english_name": {"type": "string", "minLength": 1},
        },
        "required": ["english_name"],
        "additionalProperties": False,
    },
}


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


def translate_produce(name: str) -> str:
    response = _client().messages.create(
        model=MODEL,
        max_tokens=256,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[TOOL_DEFINITION],
        tool_choice={"type": "tool", "name": "submit_translation"},
        messages=[
            {"role": "user", "content": f"Translate this produce name to English: {name}"}
        ],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_translation":
            english = (block.input or {}).get("english_name")  # type: ignore[union-attr]
            if isinstance(english, str) and english.strip():
                return english.strip()
            break

    raise RuntimeError("Claude did not return a translation")
