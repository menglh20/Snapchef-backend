import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.config import get_settings
from app.deps import verify_api_key
from app.schemas import Category, ClassifiedItem, ReceiptItem, ReceiptResponse
from app.services import classifier, cleaner, textract

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/receipts", tags=["receipts"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png"}


@router.post("/analyze", response_model=ReceiptResponse, dependencies=[Depends(verify_api_key)])
async def analyze_receipt(image: UploadFile = File(...)) -> ReceiptResponse:
    settings = get_settings()

    if image.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported content type: {image.content_type}",
        )

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty image upload")
    if len(image_bytes) > settings.max_image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image exceeds {settings.max_image_bytes} bytes",
        )

    try:
        textract_response = textract.analyze_expense(image_bytes)
    except Exception as exc:
        logger.exception("Textract call failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Textract error: {exc}",
        ) from exc

    raw_items, totals = textract.parse_response(textract_response)
    if not raw_items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No line items found on receipt",
        )

    cleaned_names = [cleaner.clean(item.raw_name) for item in raw_items]

    classification_warning: str | None = None
    try:
        classified = classifier.classify(cleaned_names)
    except Exception as exc:
        logger.exception("Classifier call failed")
        classification_warning = f"classification_failed: {exc}"
        classified = [
            ClassifiedItem(
                index=i,
                normalized_name=name,
                category=Category.OTHER,
                needs_refrigeration=False,
            )
            for i, name in enumerate(cleaned_names)
        ]

    items: list[ReceiptItem] = []
    for i, raw in enumerate(raw_items):
        c = classified[i]
        items.append(
            ReceiptItem(
                id=str(i),
                raw_name=raw.raw_name,
                name=c.normalized_name or cleaned_names[i],
                quantity=raw.quantity,
                unit_price=raw.unit_price,
                total_price=raw.total_price,
                category=c.category,
                needs_refrigeration=c.needs_refrigeration,
                checked=c.needs_refrigeration,
            )
        )

    return ReceiptResponse(
        receipt_id=str(uuid.uuid4()),
        items=items,
        totals=totals,
        classification_warning=classification_warning,
    )
