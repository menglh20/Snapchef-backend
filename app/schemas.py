from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Category(str, Enum):
    PRODUCE = "produce"
    DAIRY = "dairy"
    MEAT_SEAFOOD = "meat_seafood"
    FROZEN = "frozen"
    BAKERY = "bakery"
    PANTRY = "pantry"
    BEVERAGE = "beverage"
    SNACK = "snack"
    HOUSEHOLD = "household"
    OTHER = "other"


CATEGORY_VALUES: list[str] = [c.value for c in Category]


class RawLineItem(BaseModel):
    raw_name: str
    quantity: float = 1.0
    unit_price: Optional[float] = None
    total_price: Optional[float] = None


class ClassifiedItem(BaseModel):
    index: int
    normalized_name: str
    category: Category
    needs_refrigeration: bool


class ReceiptItem(BaseModel):
    id: str
    raw_name: str
    name: str
    quantity: float
    unit_price: Optional[float] = None
    total_price: Optional[float] = None
    category: Category
    needs_refrigeration: bool
    checked: bool


class ReceiptTotals(BaseModel):
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None


class ReceiptResponse(BaseModel):
    receipt_id: str
    items: list[ReceiptItem]
    totals: ReceiptTotals = Field(default_factory=ReceiptTotals)
    classification_warning: Optional[str] = None
