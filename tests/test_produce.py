import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import baidu, translator, vision

HEADERS = {"X-API-Key": "test-api-key-1234"}


@pytest.fixture
def client():
    return TestClient(app)


def _upload(content_type: str = "image/jpeg", data: bytes = b"fake-jpeg-bytes"):
    return {"image": ("photo.jpg", io.BytesIO(data), content_type)}


def test_recognize_happy_path(client, monkeypatch):
    monkeypatch.setattr(
        baidu, "recognize_ingredient", lambda b: [{"name": "西红柿", "score": 0.98}]
    )
    captured = {}

    def fake_translate(name):
        captured["name"] = name
        return "Tomato"

    monkeypatch.setattr(translator, "translate_produce", fake_translate)

    resp = client.post("/produce/recognize", headers=HEADERS, files=_upload())

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Tomato"
    assert body["raw_name"] == "西红柿"
    assert body["confidence"] == 0.98
    assert captured["name"] == "西红柿"


def test_recognize_non_produce_is_uncertain(client, monkeypatch):
    monkeypatch.setattr(
        baidu,
        "recognize_ingredient",
        lambda b: [{"name": baidu.NON_PRODUCE_NAME, "score": 0.99}],
    )

    def boom(name):
        raise AssertionError("translator must not be called for non-produce")

    monkeypatch.setattr(translator, "translate_produce", boom)

    resp = client.post("/produce/recognize", headers=HEADERS, files=_upload())

    assert resp.status_code == 200
    assert resp.json()["name"] == "Uncertain"


def test_recognize_low_confidence_is_uncertain(client, monkeypatch):
    monkeypatch.setattr(
        baidu, "recognize_ingredient", lambda b: [{"name": "西红柿", "score": 0.2}]
    )
    monkeypatch.setattr(
        translator, "translate_produce", lambda n: pytest.fail("should not translate")
    )

    resp = client.post("/produce/recognize", headers=HEADERS, files=_upload())

    assert resp.status_code == 200
    assert resp.json()["name"] == "Uncertain"


def test_recognize_empty_results_is_uncertain(client, monkeypatch):
    monkeypatch.setattr(baidu, "recognize_ingredient", lambda b: [])

    resp = client.post("/produce/recognize", headers=HEADERS, files=_upload())

    assert resp.status_code == 200
    assert resp.json()["name"] == "Uncertain"


def test_recognize_502_when_baidu_fails(client, monkeypatch):
    def boom(b):
        raise RuntimeError("baidu outage")

    monkeypatch.setattr(baidu, "recognize_ingredient", boom)

    resp = client.post("/produce/recognize", headers=HEADERS, files=_upload())

    assert resp.status_code == 502


def test_recognize_502_when_translation_fails(client, monkeypatch):
    monkeypatch.setattr(
        baidu, "recognize_ingredient", lambda b: [{"name": "西红柿", "score": 0.98}]
    )

    def boom(name):
        raise RuntimeError("anthropic outage")

    monkeypatch.setattr(translator, "translate_produce", boom)

    resp = client.post("/produce/recognize", headers=HEADERS, files=_upload())

    assert resp.status_code == 502


def test_recognize_rejects_bad_content_type(client):
    resp = client.post(
        "/produce/recognize", headers=HEADERS, files=_upload(content_type="text/plain")
    )
    assert resp.status_code == 400


def test_recognize_rejects_empty_image(client, monkeypatch):
    monkeypatch.setattr(
        baidu, "recognize_ingredient", lambda b: pytest.fail("should not reach baidu")
    )
    resp = client.post("/produce/recognize", headers=HEADERS, files=_upload(data=b""))
    assert resp.status_code == 400


def test_recognize_rejects_oversized_image(client, monkeypatch):
    monkeypatch.setattr(
        baidu, "recognize_ingredient", lambda b: pytest.fail("should not reach baidu")
    )
    # base64 of 3MB+1 raw bytes exceeds Baidu's 4MB encoded cap, but stays under
    # the 8MB MAX_IMAGE_BYTES gate so this exercises the Baidu-specific limit.
    big = b"x" * (3 * 1024 * 1024 + 1)
    resp = client.post("/produce/recognize", headers=HEADERS, files=_upload(data=big))
    assert resp.status_code == 400
    assert "Baidu" in resp.json()["detail"]


def test_recognize_requires_api_key(client):
    resp = client.post("/produce/recognize", files=_upload())
    assert resp.status_code == 422


def test_recognize_rejects_wrong_api_key(client):
    resp = client.post(
        "/produce/recognize", headers={"X-API-Key": "wrong"}, files=_upload()
    )
    assert resp.status_code == 401


# --- /produce/recognize-llm (Claude vision path) ---


def test_recognize_llm_happy_path(client, monkeypatch):
    captured = {}

    def fake_recognize(image_bytes, media_type):
        captured["media_type"] = media_type
        return {"is_produce": True, "name": "Napa Cabbage", "confidence": 0.92}

    monkeypatch.setattr(vision, "recognize_produce", fake_recognize)

    resp = client.post("/produce/recognize-llm", headers=HEADERS, files=_upload())

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Napa Cabbage"
    assert body["confidence"] == 0.92
    assert body["raw_name"] is None
    assert captured["media_type"] == "image/jpeg"


def test_recognize_llm_plastic_model_is_accepted(client, monkeypatch):
    monkeypatch.setattr(
        vision,
        "recognize_produce",
        lambda b, m: {"is_produce": True, "name": "Tomato", "confidence": 0.7},
    )

    resp = client.post("/produce/recognize-llm", headers=HEADERS, files=_upload())

    assert resp.status_code == 200
    assert resp.json()["name"] == "Tomato"


def test_recognize_llm_non_produce_is_uncertain(client, monkeypatch):
    monkeypatch.setattr(
        vision,
        "recognize_produce",
        lambda b, m: {"is_produce": False, "name": "Other", "confidence": 0.1},
    )

    resp = client.post("/produce/recognize-llm", headers=HEADERS, files=_upload())

    assert resp.status_code == 200
    assert resp.json()["name"] == "Uncertain"


def test_recognize_llm_other_produce_is_uncertain(client, monkeypatch):
    # Produce that falls outside the controlled vocabulary -> "Other" -> Uncertain.
    monkeypatch.setattr(
        vision,
        "recognize_produce",
        lambda b, m: {"is_produce": True, "name": "Other", "confidence": 0.6},
    )

    resp = client.post("/produce/recognize-llm", headers=HEADERS, files=_upload())

    assert resp.status_code == 200
    assert resp.json()["name"] == "Uncertain"


def test_vision_tool_name_is_constrained_to_vocab():
    # The tool schema must restrict `name` to the controlled vocabulary (+ "Other").
    from app.schemas import PRODUCE_OTHER, PRODUCE_VOCAB

    enum = vision.TOOL_DEFINITION["input_schema"]["properties"]["name"]["enum"]
    assert "Tomato" in enum
    assert "Napa Cabbage" in enum
    assert PRODUCE_OTHER in enum
    assert set(enum) == set(PRODUCE_VOCAB) | {PRODUCE_OTHER}


def test_recognize_llm_502_when_claude_fails(client, monkeypatch):
    def boom(b, m):
        raise RuntimeError("anthropic outage")

    monkeypatch.setattr(vision, "recognize_produce", boom)

    resp = client.post("/produce/recognize-llm", headers=HEADERS, files=_upload())

    assert resp.status_code == 502


def test_recognize_llm_rejects_bad_content_type(client):
    resp = client.post(
        "/produce/recognize-llm", headers=HEADERS, files=_upload(content_type="text/plain")
    )
    assert resp.status_code == 400


def test_recognize_llm_requires_api_key(client):
    resp = client.post("/produce/recognize-llm", files=_upload())
    assert resp.status_code == 422
