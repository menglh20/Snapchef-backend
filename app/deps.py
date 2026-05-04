import secrets

from fastapi import Header, HTTPException, status

from app.config import get_settings


def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> None:
    expected = get_settings().api_key
    if not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
