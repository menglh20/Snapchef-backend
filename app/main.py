import logging

from fastapi import FastAPI

from app.routers import receipts, recipes

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Snapchef Backend", version="0.1.0")
app.include_router(receipts.router)
app.include_router(recipes.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
