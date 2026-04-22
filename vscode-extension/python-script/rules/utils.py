"""
Shared utility helpers for rule groups.
"""

from __future__ import annotations

from typing import Optional

from mmcif_types import ItemValue


MISSING_VALUES = {"?", "."}


def normalize_item_name(item: str) -> str:
    """Return mmCIF item name with leading underscore."""
    item = item.strip()
    return item if item.startswith("_") else f"_{item}"


def category_from_item_name(item_name: str) -> str:
    """Extract category from mmCIF item name."""
    return item_name[1:].split(".", 1)[0]


def item_name_for_category(category: str, short_item_name: str) -> str:
    """Build full mmCIF item name from category and short item name."""
    return f"_{category}.{short_item_name}"


def item_value_to_number(iv: ItemValue) -> Optional[float]:
    """Convert ItemValue value to float, returning None if missing/non-numeric."""
    if iv.value in MISSING_VALUES:
        return None
    try:
        return float(iv.value)
    except (TypeError, ValueError):
        return None
