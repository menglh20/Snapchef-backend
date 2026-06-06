"""Identify a held fruit/vegetable directly from an image via Claude vision.

Same job as the Baidu path (services/baidu.py + translator.py) but does recognition
and English naming in a single multimodal Claude call, with forced tool_use so the
response is guaranteed-shape (matches the pattern in classifier.py / recipes.py).
"""

import base64
import logging
from functools import lru_cache

import anthropic

from app.config import get_settings
from app.schemas import PRODUCE_OTHER, PRODUCE_VOCAB

logger = logging.getLogger(__name__)

# Vision-capable; Haiku 4.5 keeps this cheap for a simple single-object identification.
MODEL = "claude-haiku-4-5"

# The model may only emit a name from the controlled vocabulary (or "Other").
NAME_ENUM = [*PRODUCE_VOCAB, PRODUCE_OTHER]

SYSTEM_PROMPT = (
    "You identify produce from a photo. Usage scenario: one person stands in front of the "
    "camera holding a single vegetable or fruit in their hand(s). Your job is to identify "
    "which vegetable or fruit it is.\n\n"
    "Rules:\n"
    "- The `name` MUST be one of the exact values allowed by the tool schema (a fixed "
    "vocabulary of produce names). Pick the single best match.\n"
    "- Focus only on the held item. Ignore the person, hands, clothing, and background.\n"
    "- The item may be a plastic/fake produce model (these are used during testing). Treat a "
    "recognizable model as the real produce it represents and identify it normally — a plastic "
    "tomato is 'Tomato'.\n"
    f"- If the held item is clearly a fruit or vegetable but none of the allowed names fit, set "
    f"is_produce=true and name='{PRODUCE_OTHER}'.\n"
    "- If the held object is NOT a fruit or vegetable, or no produce is clearly visible, set "
    f"is_produce=false (you may use name='{PRODUCE_OTHER}').\n"
    "- Set confidence between 0 and 1 reflecting how sure you are of the identification.\n"
    "Always return the result via the submit_produce tool."
)

TOOL_DEFINITION = {
    "name": "submit_produce",
    "description": "Report whether a fruit/vegetable is shown, its English name, and confidence.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_produce": {"type": "boolean"},
            "name": {"type": "string", "enum": NAME_ENUM},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["is_produce", "name", "confidence"],
        "additionalProperties": False,
    },
}


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


def recognize_produce(image_bytes: bytes, media_type: str) -> dict:
    """Return the raw tool input, e.g. {"is_produce": True, "name": "Tomato", "confidence": 0.9}."""
    encoded = base64.b64encode(image_bytes).decode("ascii")

    response = _client().messages.create(
        model=MODEL,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[TOOL_DEFINITION],
        tool_choice={"type": "tool", "name": "submit_produce"},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": encoded,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Identify the fruit or vegetable the person is holding.",
                    },
                ],
            }
        ],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_produce":
            return block.input or {}  # type: ignore[return-value]

    raise RuntimeError("Claude did not return a produce identification")
