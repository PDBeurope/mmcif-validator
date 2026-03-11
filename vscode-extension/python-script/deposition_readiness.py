"""
Compute deposition-readiness indicator from a parsed mmCIF and dictionary.

Uses mandatory categories (per method or common) and deposition-mandatory items
from the dictionary (_pdbx_item.mandatory_code or _item.mandatory_code).
"""

from typing import Dict, Set, Tuple

from protocol import DepositionReadiness
from dict_parser import DictionaryParser
from cif_parser import MmCIFParser

from completeness.mandatory_categories import (
    load_mandatory_categories,
    detect_method,
    METHOD_UNKNOWN,
)


def _is_filled(mmcif: MmCIFParser, item_name: str) -> bool:
    """True if the file has the item and at least one value that is not ? or ."""
    if item_name not in mmcif.items:
        return False
    for _, value, _, _ in mmcif.items[item_name]:
        if value not in ("?", "."):
            return True
    return False


def compute_deposition_readiness(
    dictionary: DictionaryParser,
    mmcif: MmCIFParser,
) -> DepositionReadiness:
    """
    Compute deposition-readiness percentage and method.

    - Mandatory categories come from completeness lists (xray/em/nmr or common).
    - Mandatory items per category come from dictionary.deposition_mandatory_items.
    - Percentage = (filled mandatory items) / (total mandatory items) * 100.
    - When method is unknown, only common categories are counted and percentage is capped at 50%.
    """
    mandatory_by_method, common_categories, method_specific = load_mandatory_categories()
    file_categories = mmcif.categories
    method = detect_method(file_categories, method_specific)

    if method == METHOD_UNKNOWN:
        mandatory_categories = common_categories
        method_detected = None
        message = (
            "Experimental method could not be determined from this file. "
            "Only common mandatory categories are counted; maximum score is 50%."
        )
        cap_at_50 = True
    else:
        mandatory_categories = mandatory_by_method.get(method, set())
        method_detected = method
        message = None
        cap_at_50 = False

    total_count = 0
    filled_count = 0

    for cat in mandatory_categories:
        items = dictionary.deposition_mandatory_items.get(cat, set())
        for item_name in items:
            total_count += 1
            if _is_filled(mmcif, item_name):
                filled_count += 1

    if total_count == 0:
        percentage = 0.0
    else:
        percentage = (filled_count / total_count) * 100.0
        if cap_at_50 and percentage > 50.0:
            percentage = 50.0

    return DepositionReadiness(
        percentage=round(percentage, 1),
        filled_count=filled_count,
        total_count=total_count,
        method_detected=method_detected,
        message=message,
    )
