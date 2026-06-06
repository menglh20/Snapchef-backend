import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.config import get_settings
from app.deps import verify_api_key
from app.schemas import UNCERTAIN_PRODUCE, ProduceResponse
from app.services import baidu, translator, vision

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/produce", tags=["produce"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png"}

# Anthropic caps each image at 5MB base64-encoded.
CLAUDE_MAX_BASE64_BYTES = 5 * 1024 * 1024


def _media_type(content_type: str) -> str:
    return "image/png" if content_type == "image/png" else "image/jpeg"


async def _read_validated_image(image: UploadFile) -> bytes:
    """Shared content-type / size validation; raises HTTPException on bad input."""
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
    return image_bytes


@router.post("/recognize", response_model=ProduceResponse, dependencies=[Depends(verify_api_key)])
async def recognize_produce(image: UploadFile = File(...)) -> ProduceResponse:
    settings = get_settings()
    image_bytes = await _read_validated_image(image)

    # Baidu rejects images whose base64 encoding exceeds 4MB; base64 inflates ~33%.
    base64_len = ((len(image_bytes) + 2) // 3) * 4
    if base64_len > settings.baidu_max_base64_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image too large for Baidu recognition (max ~{settings.baidu_max_base64_bytes * 3 // 4} bytes)",
        )

    try:
        results = baidu.recognize_ingredient(image_bytes)
    except Exception as exc:
        logger.exception("Baidu ingredient recognition failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Baidu recognition error: {exc}",
        ) from exc

    top = results[0] if results else None
    top_name = (top or {}).get("name")
    top_score = (top or {}).get("score")

    # Not a fruit/vegetable, nothing recognized, or low confidence -> Uncertain.
    if (
        top is None
        or not top_name
        or top_name == baidu.NON_PRODUCE_NAME
        or (isinstance(top_score, (int, float)) and top_score < settings.baidu_produce_min_score)
    ):
        return ProduceResponse(name=UNCERTAIN_PRODUCE)

    try:
        english = translator.translate_produce(top_name)
    except Exception as exc:
        logger.exception("Produce translation failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Translation error: {exc}",
        ) from exc

    return ProduceResponse(
        name=english,
        raw_name=top_name,
        confidence=top_score if isinstance(top_score, (int, float)) else None,
    )


@router.post(
    "/recognize-llm", response_model=ProduceResponse, dependencies=[Depends(verify_api_key)]
)
async def recognize_produce_llm(image: UploadFile = File(...)) -> ProduceResponse:
    """Same contract as /recognize, but recognition is done by Claude vision (no Baidu)."""
    image_bytes = await _read_validated_image(image)

    base64_len = ((len(image_bytes) + 2) // 3) * 4
    if base64_len > CLAUDE_MAX_BASE64_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image too large for vision model (max ~{CLAUDE_MAX_BASE64_BYTES * 3 // 4} bytes)",
        )

    try:
        result = vision.recognize_produce(image_bytes, _media_type(image.content_type))
    except Exception as exc:
        logger.exception("Vision produce recognition failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Vision recognition error: {exc}",
        ) from exc

    name = (result.get("name") or "").strip()
    confidence = result.get("confidence")

    # The model sets is_produce=false when the held item is not a fruit/vegetable.
    if not result.get("is_produce") or not name:
        return ProduceResponse(name=UNCERTAIN_PRODUCE)

    return ProduceResponse(
        name=name,
        confidence=confidence if isinstance(confidence, (int, float)) else None,
    )
