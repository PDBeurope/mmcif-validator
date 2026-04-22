"""
Shared utility helpers for rule groups.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

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


# yyyy-mm-dd or yyyy-mm-dd:hh:mm (used by cross-check date ordering)
_MMCIF_DATE = re.compile(
    r"^(\d{4})-(\d{1,2})-(\d{1,2})(?::(\d{1,2}):(\d{1,2}))?$"
)


def mmcif_datetime_tuple(value: str) -> Optional[Tuple[int, int, int, int, int]]:
    """
    Parse PDBx-style date or date-time to a comparable tuple (Y, M, D, h, m).
    Returns None if missing, empty, or not in a supported format.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in MISSING_VALUES:
        return None
    m = _MMCIF_DATE.match(s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    h = int(m.group(4)) if m.group(4) is not None else 0
    mi = int(m.group(5)) if m.group(5) is not None else 0
    return (y, mo, d, h, mi)
