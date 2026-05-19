import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import verify_api_key
from app.schemas import (
    RecipeListRequest,
    RecipeListResponse,
    RecipeStepsRequest,
    RecipeStepsResponse,
)
from app.services import recipes as recipes_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recipes", tags=["recipes"])


@router.post("/list", response_model=RecipeListResponse, dependencies=[Depends(verify_api_key)])
async def list_recipes(payload: RecipeListRequest) -> RecipeListResponse:
    try:
        dishes = recipes_service.suggest_dishes(payload.trigger, payload.fridge)
    except Exception as exc:
        logger.exception("Recipe list generation failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Recipe generation error: {exc}",
        ) from exc

    if not dishes:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Recipe generation returned no dishes",
        )

    return RecipeListResponse(dishes=dishes)


@router.post("/steps", response_model=RecipeStepsResponse, dependencies=[Depends(verify_api_key)])
async def recipe_steps(payload: RecipeStepsRequest) -> RecipeStepsResponse:
    try:
        result = recipes_service.generate_steps(payload.dish, payload.fridge)
    except Exception as exc:
        logger.exception("Recipe steps generation failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Recipe generation error: {exc}",
        ) from exc

    return RecipeStepsResponse(**result)
