# Snapchef Backend

FastAPI service that turns a receipt photo from an ESP32S3 Sense into a checkable JSON shopping list — with each item categorized and flagged for refrigeration.

```
ESP32S3 Sense  ──multipart──▶  FastAPI  ──▶  AWS Textract (AnalyzeExpense)
                                  │
                                  ▼
                            cleaner.py
                                  │
                                  ▼
                       Claude Haiku 4.5 (tool_use)
                                  │
                                  ▼
                         JSON item list (with `checked`)
```

Stateless — no database, no image storage.

## Requirements

- **Python 3.11+** (3.13 tested)
- AWS account with **Textract** enabled in your region
- **Anthropic API key**

## Setup

```bash
# 1. Create venv and install
python3.13 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
# Edit .env to set:
#   API_KEY              — strong random token, sent by ESP32 in X-API-Key header
#   ANTHROPIC_API_KEY    — from console.anthropic.com
#   AWS_REGION           — e.g. us-west-2
#   AWS_ACCESS_KEY_ID    — IAM user with textract:AnalyzeExpense
#   AWS_SECRET_ACCESS_KEY
```

The IAM user needs the `AmazonTextractFullAccess` managed policy (or just `textract:AnalyzeExpense`). Textract must be subscribed in your AWS account — visit the [Textract console](https://us-west-2.console.aws.amazon.com/textract/home) once to activate.

## Run

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/healthz
# {"status":"ok"}
```

## API

### `POST /receipts/analyze`

Upload a receipt image and get back a parsed, classified item list.

**Request**

| | |
|---|---|
| Header | `X-API-Key: <token>` |
| Body | `multipart/form-data`, field `image` (JPEG or PNG, ≤ 8 MB) |

**Example**

```bash
curl -X POST http://localhost:8000/receipts/analyze \
  -H "X-API-Key: $API_KEY" \
  -F "image=@receipt.jpg"
```

**Response** (`200 OK`)

```json
{
  "receipt_id": "4611029d-6ef4-4472-8c81-9dfe4f75bcde",
  "items": [
    {
      "id": "0",
      "raw_name": "WHL MLK 1GAL",
      "name": "Whole Milk 1 Gallon",
      "quantity": 1.0,
      "unit_price": 3.99,
      "total_price": 3.99,
      "category": "dairy",
      "needs_refrigeration": true,
      "checked": true
    }
  ],
  "totals": { "subtotal": 22.47, "tax": 1.57, "total": 24.04 },
  "classification_warning": null
}
```

**Item fields**

| Field | Source | Notes |
|---|---|---|
| `id` | server | array index, stable per response |
| `raw_name` | Textract | original line text (often abbreviated, ALL CAPS) |
| `name` | Claude | cleaned, human-readable |
| `quantity` | Textract | defaults to 1.0 if missing |
| `unit_price`, `total_price` | Textract | nullable |
| `category` | Claude | enum, see below |
| `needs_refrigeration` | Claude | true if item must go in the fridge |
| `checked` | server | equals `needs_refrigeration` (UI default) |

**Category enum:** `produce`, `dairy`, `meat_seafood`, `frozen`, `bakery`, `pantry`, `beverage`, `snack`, `household`, `other`

**`classification_warning`:** non-null only when Claude failed; in that case items still come back with category `other` and `needs_refrigeration=false`. Textract data is always preserved.

**Errors**

| Status | When |
|---|---|
| `401` | Missing or wrong `X-API-Key` |
| `400` | Wrong content type, empty body, or > `MAX_IMAGE_BYTES` |
| `422` | Textract found no line items |
| `502` | Textract or AWS unreachable |

### `GET /healthz`

No auth. Returns `{"status":"ok"}`. Use it for ESP32 startup probe.

## ESP32 client snippet

```cpp
HTTPClient http;
http.begin("http://<host>:8000/receipts/analyze");
http.addHeader("X-API-Key", API_KEY);

// Build multipart body with the JPEG buffer from the camera...
int code = http.POST(body, body_len);
String resp = http.getString();
// Parse `items[]`, render checkboxes pre-checked from `checked`
```

## Testing

All tests mock external calls (Textract + Anthropic), so no credentials are needed.

```bash
.venv/bin/pytest -q
```

17 tests cover: Textract response parsing, cleaner edge cases, classifier tool-use mapping with fallback, and the FastAPI endpoint (happy path, auth failures, file-size limits, Claude-failure resilience).

## Performance

End-to-end ~4–5 s on a 12-item receipt (localhost test):

| Stage | Approx |
|---|---|
| Textract `AnalyzeExpense` | 1.5 – 2.5 s |
| Claude classification | 2 – 3 s |
| Everything else | < 50 ms |

Device UI should show a spinner during the request.

## Configuration reference (`.env`)

| Variable | Default | Required | Notes |
|---|---|---|---|
| `API_KEY` | — | yes | Static token in `X-API-Key` header |
| `ANTHROPIC_API_KEY` | — | yes | from console.anthropic.com |
| `AWS_REGION` | `us-west-2` | no | Must support Textract |
| `AWS_ACCESS_KEY_ID` | — | yes | Or use the default boto3 credential chain |
| `AWS_SECRET_ACCESS_KEY` | — | yes | Same as above |
| `MAX_IMAGE_BYTES` | `8388608` | no | 8 MB upload cap |

## Project layout

```
app/
├── main.py              FastAPI entry, /healthz
├── config.py            pydantic-settings
├── deps.py              X-API-Key auth dependency
├── schemas.py           Pydantic models + Category enum
├── routers/
│   └── receipts.py      POST /receipts/analyze
└── services/
    ├── textract.py      AnalyzeExpense + parser
    ├── cleaner.py       pre-clean before Claude
    └── classifier.py    Anthropic SDK, forced tool_use
tests/                   17 unit + integration tests, fully mocked
.env.example             config template
pyproject.toml           dependencies (FastAPI, boto3, anthropic, pytest…)
```

## Limitations

- **English-only receipts.** Textract `AnalyzeExpense` does not handle Chinese or other non-English receipts. For multilingual support, consider Claude Vision directly on the image (no Textract).
- **Single device, single API key.** No multi-tenant or per-user auth.
- **No persistence.** Each request is independent — no history, no idempotency. Re-uploading the same receipt produces a new `receipt_id`.

## License

Private project.
