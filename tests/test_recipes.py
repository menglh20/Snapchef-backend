from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import recipes as recipes_service


@pytest.fixture
def client():
    return TestClient(app)


def _fake_response(tool_name: str, tool_input: dict):
    block = SimpleNamespace(type="tool_use", name=tool_name, input=tool_input)
    return SimpleNamespace(content=[block])


def test_recipes_list_happy_path(client, monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_response(
            "submit_dish_list",
            {"dishes": ["Caprese Salad", "Tomato Omelette", "Pasta Pomodoro"]},
        )

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(recipes_service, "_client", lambda: fake_client)

    resp = client.post(
        "/recipes/list",
        headers={"X-API-Key": "test-api-key-1234"},
        json={"trigger": "Tomato", "fridge": ["Tomato", "Onion", "Mozzarella"]},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "dishes": ["Caprese Salad", "Tomato Omelette", "Pasta Pomodoro"]
    }
    assert captured["tool_choice"]["name"] == "submit_dish_list"
    assert captured["system"][0]["cache_control"]["type"] == "ephemeral"


def test_recipes_list_requires_api_key(client):
    resp = client.post(
        "/recipes/list",
        json={"trigger": "Tomato", "fridge": []},
    )
    assert resp.status_code == 422


def test_recipes_list_rejects_wrong_api_key(client):
    resp = client.post(
        "/recipes/list",
        headers={"X-API-Key": "wrong"},
        json={"trigger": "Tomato", "fridge": []},
    )
    assert resp.status_code == 401


def test_recipes_list_502_when_claude_fails(client, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("anthropic outage")

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=boom))
    monkeypatch.setattr(recipes_service, "_client", lambda: fake_client)

    resp = client.post(
        "/recipes/list",
        headers={"X-API-Key": "test-api-key-1234"},
        json={"trigger": "Tomato", "fridge": ["Tomato"]},
    )
    assert resp.status_code == 502


def test_recipes_list_502_when_no_dishes(client, monkeypatch):
    def fake_create(**kwargs):
        return _fake_response("submit_dish_list", {"dishes": []})

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(recipes_service, "_client", lambda: fake_client)

    resp = client.post(
        "/recipes/list",
        headers={"X-API-Key": "test-api-key-1234"},
        json={"trigger": "Tomato", "fridge": []},
    )
    assert resp.status_code == 502


def test_recipes_steps_happy_path(client, monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_response(
            "submit_recipe_steps",
            {
                "title": "Caprese Salad",
                "time_min": 15,
                "steps": [
                    "Slice tomatoes and mozzarella.",
                    "Arrange on a plate with basil.",
                    "Drizzle with olive oil, salt, and pepper.",
                ],
                "used_fridge_items": ["Tomato", "Mozzarella"],
                "missing_items": ["Basil"],
            },
        )

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(recipes_service, "_client", lambda: fake_client)

    resp = client.post(
        "/recipes/steps",
        headers={"X-API-Key": "test-api-key-1234"},
        json={"dish": "Caprese Salad", "fridge": ["Tomato", "Onion", "Mozzarella"]},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Caprese Salad"
    assert body["time_min"] == 15
    assert len(body["steps"]) == 3
    assert body["used_fridge_items"] == ["Tomato", "Mozzarella"]
    assert body["missing_items"] == ["Basil"]
    assert captured["tool_choice"]["name"] == "submit_recipe_steps"


def test_recipes_steps_reconciles_against_fridge(client, monkeypatch):
    # Model claims a used item not in the fridge ("Pesto") and flags a missing item
    # that is actually present ("Onion"); the server must correct both.
    def fake_create(**kwargs):
        return _fake_response(
            "submit_recipe_steps",
            {
                "title": "Caprese Salad",
                "time_min": 15,
                "steps": ["Slice and plate."],
                "used_fridge_items": ["tomato", "Pesto"],
                "missing_items": ["Onion", "Balsamic Vinegar"],
            },
        )

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(recipes_service, "_client", lambda: fake_client)

    resp = client.post(
        "/recipes/steps",
        headers={"X-API-Key": "test-api-key-1234"},
        json={"dish": "Caprese Salad", "fridge": ["Tomato", "Onion", "Mozzarella"]},
    )

    assert resp.status_code == 200
    body = resp.json()
    # "tomato" matches "Tomato" case-insensitively and echoes the fridge spelling;
    # "Pesto" is dropped (not in fridge).
    assert body["used_fridge_items"] == ["Tomato"]
    # "Onion" is dropped (it IS in the fridge); only the true missing item remains.
    assert body["missing_items"] == ["Balsamic Vinegar"]


def test_recipes_steps_requires_api_key(client):
    resp = client.post(
        "/recipes/steps",
        json={"dish": "Caprese Salad", "fridge": []},
    )
    assert resp.status_code == 422


def test_recipes_steps_502_when_claude_fails(client, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("anthropic outage")

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=boom))
    monkeypatch.setattr(recipes_service, "_client", lambda: fake_client)

    resp = client.post(
        "/recipes/steps",
        headers={"X-API-Key": "test-api-key-1234"},
        json={"dish": "Caprese Salad", "fridge": []},
    )
    assert resp.status_code == 502
