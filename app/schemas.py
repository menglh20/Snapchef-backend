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


class RecipeListRequest(BaseModel):
    trigger: str = Field(..., min_length=1)
    fridge: list[str] = Field(default_factory=list)


class RecipeListResponse(BaseModel):
    dishes: list[str]


class RecipeStepsRequest(BaseModel):
    dish: str = Field(..., min_length=1)
    fridge: list[str] = Field(default_factory=list)


class RecipeStepsResponse(BaseModel):
    title: str
    time_min: int
    steps: list[str]
    # Items from the request's fridge list that this recipe uses.
    used_fridge_items: list[str] = Field(default_factory=list)
    # Ingredients the recipe needs that are NOT in the fridge (excludes pantry staples).
    missing_items: list[str] = Field(default_factory=list)


class ProduceResponse(BaseModel):
    # English produce name, or "Uncertain" when the image is not a fruit/vegetable.
    name: str
    # Chinese name returned by Baidu (None when uncertain). For debugging/telemetry.
    raw_name: Optional[str] = None
    confidence: Optional[float] = None


UNCERTAIN_PRODUCE = "Uncertain"

# Controlled vocabulary for LLM produce recognition (/produce/recognize-llm).
# Title Case, singular. The vision tool's `name` field is an enum over this list so the
# model can only emit a canonical name (no "tomatoes" vs "Roma Tomato" drift).
# To support a new produce type, add it here — no other code change needed.
PRODUCE_VOCAB: list[str] = [
    # Fruits
    "Apple", "Banana", "Orange", "Tangerine", "Lemon", "Lime", "Grapefruit",
    "Pear", "Peach", "Nectarine", "Plum", "Apricot", "Cherry", "Strawberry",
    "Blueberry", "Raspberry", "Blackberry", "Cranberry", "Grape", "Watermelon",
    "Cantaloupe", "Honeydew", "Pineapple", "Mango", "Papaya", "Kiwi", "Avocado",
    "Pomegranate", "Fig", "Persimmon", "Lychee", "Longan", "Dragon Fruit",
    "Passion Fruit", "Coconut", "Guava", "Date", "Jujube",
    # Vegetables
    "Tomato", "Potato", "Sweet Potato", "Carrot", "Onion", "Garlic", "Ginger",
    "Scallion", "Leek", "Shallot", "Celery", "Cucumber", "Bellpepper",
    "Chili Pepper", "Eggplant", "Zucchini", "Pumpkin", "Squash", "Corn",
    "Broccoli", "Cauliflower", "Cabbage", "Napa Cabbage", "Bok Choy", "Lettuce",
    "Spinach", "Kale", "Cilantro", "Parsley", "Basil", "Mint", "Mushroom",
    "Asparagus", "Green Bean", "Pea", "Snow Pea", "Sugar Snap Pea", "Edamame",
    "Okra", "Radish", "Daikon", "Turnip", "Beet", "Brussels Sprout", "Artichoke",
    "Bitter Melon", "Winter Melon", "Lotus Root", "Bamboo Shoot", "Bean Sprout",
    "Taro", "Yam", "Chayote", "Fennel",
]

# Returned by the model when the item is produce but not in PRODUCE_VOCAB.
PRODUCE_OTHER = "Other"
