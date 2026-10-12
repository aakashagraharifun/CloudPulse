"""Shared API schema building blocks."""

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, PlainSerializer

T = TypeVar("T")

_FOUR_PLACES = Decimal("0.0001")


def _money_to_str(value: Decimal) -> str:
    return format(value.quantize(_FOUR_PLACES, rounding=ROUND_HALF_EVEN), "f")


# Monetary amounts are serialized as decimal strings (e.g. "1234.5000") so no
# precision is lost to JSON floating point. Clients parse them for display.
Money = Annotated[Decimal, PlainSerializer(_money_to_str, return_type=str, when_used="json")]


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(APIModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
