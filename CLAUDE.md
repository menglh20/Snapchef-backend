# CLAUDE.md

Guidance for Claude Code when working in this repo.

## What this is

FastAPI backend for ESP32S3 Sense receipt processing. Pipeline:

```
ESP32 (multipart upload) → FastAPI → AWS Textract AnalyzeExpense
  → cleaner → Claude Haiku 4.5 (tool_use, structured JSON)
  → response with checkable item list
```

Stateless service — no DB, no S3, no image archiving.

## Layout

```
app/
├── main.py              # FastAPI entry, /healthz
├── config.py            # pydantic-settings (loads .env)
├── deps.py              # X-API-Key header auth (compare_digest)
├── schemas.py           # Pydantic models + Category enum
├── routers/receipts.py  # POST /receipts/analyze
└── services/
    ├── textract.py      # AnalyzeExpense + LineItemGroups parser
    ├── cleaner.py       # cheap pre-clean before Claude
    └── classifier.py    # Anthropic SDK + tool_use forced JSON
tests/                   # pytest, all external calls mocked
```

## Commands

```bash
# Setup (Python 3.11+ required; system python3 on macOS may be 3.9)
/opt/homebrew/bin/python3.13 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Run
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

# Test (no AWS / Anthropic calls — fully mocked)
.venv/bin/pytest -q
```

## Conventions and gotchas

- **Model is `claude-haiku-4-5`** in `app/services/classifier.py`. The skill default is Opus 4.7; Haiku was chosen here for cost/latency on a simple classification task. Do not silently upgrade.
- **Tool use, not free-text JSON.** Classifier uses `tool_choice={"type":"tool", "name": "submit_classified_items"}` so the response is guaranteed-shape. Do not switch to `output_config.format` unless you know why.
- **Prompt cache won't hit yet.** Haiku 4.5 minimum cacheable prefix is 4096 tokens; current system prompt is ~300 tokens. The `cache_control: ephemeral` marker is in place so caching activates automatically once the prompt grows.
- **Claude failure is non-fatal.** `routers/receipts.py` catches classifier exceptions, returns items with `category=other`, `needs_refrigeration=false`, and sets `classification_warning` on the response. Don't change this to a 502 — Textract data is still valuable.
- **`checked` defaults to `needs_refrigeration`.** UI pre-selects items that should go in the fridge. ESP32 device assumes this default.
- **Settings are cached** via `@lru_cache` on `get_settings()`. Tests set env vars in `tests/conftest.py` before any app import.
- **boto3 client is module-level cached** (`_client()` in `textract.py`). Tests must patch `analyze_expense`, not the boto3 client.
- **No CORS / no auth beyond static API key.** This is a LAN/private device backend. If exposing publicly, add HMAC + rate limiting.

## When making changes

- New category? Add to `Category` enum in `schemas.py` *and* update the enum list in `classifier.py` system prompt.
- New Textract field type? Extend `parse_response` in `services/textract.py`. Re-record the fixture under `tests/fixtures/textract_sample.json` rather than hand-editing.
- Don't add image persistence without explicit ask — design decision was no-storage.

## Known limitations

- Textract `AnalyzeExpense` is English-only. Chinese/multilingual receipts will need a different path (Claude Vision directly on the image).
- Single device, single API key. No multi-tenant.
- ~4–5s end-to-end (Textract ~2s + Claude ~2–3s). Device UI should show a spinner.
