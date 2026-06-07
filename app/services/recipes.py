import json
import logging
from functools import lru_cache

import anthropic

from app.config import get_settings

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-7"

DISH_NAME_MAX_LEN = 15

DISHES_SYSTEM_PROMPT = (
    "You are a home cooking assistant. The user gives you a 'trigger' ingredient (often the "
    "main protein or hero ingredient they want to use) and a list of other ingredients "
    "currently in their fridge. Propose a short list of realistic dishes the user could "
    "actually make using mostly what they have, with the trigger ingredient as a central "
    "component.\n\n"
    "Rules:\n"
    "- Every dish must prominently feature the trigger ingredient.\n"
    "- Prefer dishes whose major ingredients are present in the fridge list; you may assume "
    "common pantry staples (salt, pepper, oil, basic spices, flour, sugar, water).\n"
    "- Return 3 to 6 dishes. Use short, recognizable dish names (e.g. 'Caprese Salad', "
    "'Tomato Omelette'). No descriptions, no numbering.\n"
    "- HARD LIMIT: each dish name must be 15 characters or fewer (spaces count). "
    "Prefer concise canonical names; drop filler words like 'and', 'with', 'fresh'. "
    "If a real name is too long, shorten it (e.g. 'Tomato and Mozzarella Pizza' -> "
    "'Tomato Pizza').\n"
    "- Always return results via the submit_dish_list tool."
)

DISHES_TOOL = {
    "name": "submit_dish_list",
    "description": "Return a list of suggested dish names the user could cook.",
    "input_schema": {
        "type": "object",
        "properties": {
            "dishes": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            }
        },
        "required": ["dishes"],
        "additionalProperties": False,
    },
}

STEPS_SYSTEM_PROMPT = (
    "You are a home cooking assistant. The user picks a dish they want to make and tells "
    "you what is currently in their fridge. Produce a concise, runnable recipe.\n\n"
    "Rules:\n"
    "- title: the canonical name of the dish (clean capitalization).\n"
    "- time_min: a realistic total time estimate in whole minutes (prep + cook).\n"
    "- steps: an ordered list of 3 to 8 short imperative steps. Each step is one action "
    "the cook performs. No numbering inside the strings, no markdown, no ingredient lists.\n"
    "- Prefer ingredients from the fridge list and common pantry staples (salt, pepper, oil, "
    "basic spices). If something essential is missing, write the step anyway as if the cook "
    "will obtain it; do not lecture the user about missing items.\n"
    "- used_fridge_items: the items FROM THE PROVIDED fridge list that this recipe actually "
    "uses. Echo each one exactly as it appears in the fridge list. Empty list if none apply.\n"
    "- missing_items: ingredients the recipe needs that are NOT in the fridge list, so the cook "
    "must buy them. EXCLUDE common pantry staples (salt, pepper, cooking oil, basic spices, "
    "water, sugar, flour) — assume those are on hand. Empty list if nothing else is needed.\n"
    "- Always return results via the submit_recipe_steps tool."
)

STEPS_TOOL = {
    "name": "submit_recipe_steps",
    "description": "Return a clean title, total time in minutes, and ordered cooking steps.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "time_min": {"type": "integer", "minimum": 1},
            "steps": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "used_fridge_items": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "missing_items": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
        "required": ["title", "time_min", "steps", "used_fridge_items", "missing_items"],
        "additionalProperties": False,
    },
}


@lru_cache
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


def _extract_tool_input(response, tool_name: str) -> dict:
    for block in response.content:
        if block.type == "tool_use" and block.name == tool_name:
            return block.input  # type: ignore[return-value]
    raise RuntimeError(f"Claude did not return a tool_use response for {tool_name}")


def suggest_dishes(trigger: str, fridge: list[str]) -> list[str]:
    user_payload = {"trigger": trigger, "fridge": fridge}

    response = _client().messages.create(
        model=MODEL,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": DISHES_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[DISHES_TOOL],
        tool_choice={"type": "tool", "name": "submit_dish_list"},
        messages=[
            {
                "role": "user",
                "content": (
                    "Suggest dishes based on this input.\n\n"
                    + json.dumps(user_payload, ensure_ascii=False)
                ),
            }
        ],
    )

    tool_input = _extract_tool_input(response, "submit_dish_list")
    dishes_raw = tool_input.get("dishes") or []
    dishes: list[str] = []
    for d in dishes_raw:
        if isinstance(d, str):
            name = d.strip()
            if not name:
                continue
            if len(name) > DISH_NAME_MAX_LEN:
                logger.warning("Dropping over-length dish name: %r", name)
                continue
            dishes.append(name)
    return dishes


def generate_steps(dish: str, fridge: list[str]) -> dict:
    user_payload = {"dish": dish, "fridge": fridge}

    response = _client().messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": STEPS_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[STEPS_TOOL],
        tool_choice={"type": "tool", "name": "submit_recipe_steps"},
        messages=[
            {
                "role": "user",
                "content": (
                    "Generate steps for this dish.\n\n"
                    + json.dumps(user_payload, ensure_ascii=False)
                ),
            }
        ],
    )

    tool_input = _extract_tool_input(response, "submit_recipe_steps")
    title = tool_input.get("title")
    time_min = tool_input.get("time_min")
    steps_raw = tool_input.get("steps") or []

    if not isinstance(title, str) or not title.strip():
        raise RuntimeError("Recipe response missing title")
    if not isinstance(time_min, int) or time_min < 1:
        raise RuntimeError("Recipe response missing valid time_min")

    steps: list[str] = []
    for s in steps_raw:
        if isinstance(s, str):
            text = s.strip()
            if text:
                steps.append(text)
    if not steps:
        raise RuntimeError("Recipe response missing steps")

    # Reconcile against the actual fridge so the model can't claim items that
    # aren't there (used) or flag items that are (missing).
    fridge_by_lower = {
        f.strip().lower(): f.strip() for f in fridge if isinstance(f, str) and f.strip()
    }

    used: list[str] = []
    seen_used: set[str] = set()
    for item in tool_input.get("used_fridge_items") or []:
        if not isinstance(item, str):
            continue
        key = item.strip().lower()
        if key in fridge_by_lower and key not in seen_used:
            used.append(fridge_by_lower[key])
            seen_used.add(key)

    missing: list[str] = []
    seen_missing: set[str] = set()
    for item in tool_input.get("missing_items") or []:
        if not isinstance(item, str):
            continue
        text = item.strip()
        key = text.lower()
        if text and key not in fridge_by_lower and key not in seen_missing:
            missing.append(text)
            seen_missing.add(key)

    return {
        "title": title.strip(),
        "time_min": time_min,
        "steps": steps,
        "used_fridge_items": used,
        "missing_items": missing,
    }
