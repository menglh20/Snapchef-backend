import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import baidu, translator

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
