import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import Category, ClassifiedItem
from app.services import classifier, textract

FIXTURE = Path(__file__).parent / "fixtures" / "textract_sample.json"


@pytest.fixture
def fake_pipeline(monkeypatch):
    response = json.loads(FIXTURE.read_text())
    monkeypatch.setattr(textract, "analyze_expense", lambda image_bytes: response)

    def fake_classify(names: list[str]) -> list[ClassifiedItem]:
        plan = {
            "WHL MLK 1GAL": ("Whole Milk 1 Gallon", Category.DAIRY, True),
            "BANANAS": ("Bananas", Category.PRODUCE, False),
            "POTATO CHIPS": ("Potato Chips", Category.SNACK, False),
        }
        out: list[ClassifiedItem] = []
        for i, name in enumerate(names):
            # match against original raw uppercase by trying both
            cleaned, category, refrigerate = plan.get(
                name.upper(), (name, Category.OTHER, False)
            )
            out.append(
                ClassifiedItem(
                    index=i,
                    normalized_name=cleaned,
                    category=category,
                    needs_refrigeration=refrigerate,
                )
            )
        return out

    monkeypatch.setattr(classifier, "classify", fake_classify)


@pytest.fixture
def client():
    return TestClient(app)


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_analyze_happy_path(client, fake_pipeline):
    resp = client.post(
        "/receipts/analyze",
        headers={"X-API-Key": "test-api-key-1234"},
        files={"image": ("receipt.jpg", b"fake-bytes", "image/jpeg")},
    )

    assert resp.status_code == 200
    body = resp.json()

    assert body["receipt_id"]
    assert len(body["items"]) == 3

    milk = body["items"][0]
    assert milk["category"] == "dairy"
    assert milk["needs_refrigeration"] is True
    assert milk["checked"] is True

    chips = body["items"][2]
    assert chips["category"] == "snack"
    assert chips["needs_refrigeration"] is False
    assert chips["checked"] is False

    assert body["totals"]["total"] == 12.93
    assert body["classification_warning"] is None


def test_analyze_rejects_missing_api_key(client):
    resp = client.post(
        "/receipts/analyze",
        files={"image": ("r.jpg", b"x", "image/jpeg")},
    )
    assert resp.status_code == 422  # missing required header


def test_analyze_rejects_wrong_api_key(client):
    resp = client.post(
        "/receipts/analyze",
        headers={"X-API-Key": "wrong"},
        files={"image": ("r.jpg", b"x", "image/jpeg")},
    )
    assert resp.status_code == 401


def test_analyze_rejects_unsupported_content_type(client):
    resp = client.post(
        "/receipts/analyze",
        headers={"X-API-Key": "test-api-key-1234"},
        files={"image": ("r.bmp", b"x", "image/bmp")},
    )
    assert resp.status_code == 400


def test_analyze_returns_422_when_no_line_items(client, monkeypatch):
    monkeypatch.setattr(
        textract, "analyze_expense", lambda image_bytes: {"ExpenseDocuments": []}
    )
    resp = client.post(
        "/receipts/analyze",
        headers={"X-API-Key": "test-api-key-1234"},
        files={"image": ("r.jpg", b"fake", "image/jpeg")},
    )
    assert resp.status_code == 422


def test_analyze_oversize_rejected(client, monkeypatch):
    from app import config

    settings = config.get_settings()
    big = b"x" * (settings.max_image_bytes + 1)

    resp = client.post(
        "/receipts/analyze",
        headers={"X-API-Key": "test-api-key-1234"},
        files={"image": ("r.jpg", big, "image/jpeg")},
    )
    assert resp.status_code == 400


def test_analyze_handles_classifier_failure(client, monkeypatch):
    response = json.loads(FIXTURE.read_text())
    monkeypatch.setattr(textract, "analyze_expense", lambda image_bytes: response)

    def boom(_names):
        raise RuntimeError("anthropic outage")

    monkeypatch.setattr(classifier, "classify", boom)

    resp = client.post(
        "/receipts/analyze",
        headers={"X-API-Key": "test-api-key-1234"},
        files={"image": ("r.jpg", b"fake", "image/jpeg")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["classification_warning"]
    assert all(item["category"] == "other" for item in body["items"])
    assert all(item["needs_refrigeration"] is False for item in body["items"])
