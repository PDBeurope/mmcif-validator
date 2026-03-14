"""
Compute metadata-completeness indicator from a parsed mmCIF and dictionary.

Uses mandatory categories (per method or common) and deposition-mandatory items
from the dictionary (_pdbx_item.mandatory_code or _item.mandatory_code).
Uses row-level checks: every row in a loop category must have all mandatory items filled.
Items that have a validation error (severity "error") are counted as not filled and
reported with has_validation_error=True.
"""

from typing import List, Optional, Set, Tuple

from protocol import MetadataCompleteness
from dict_parser import DictionaryParser
from cif_parser import MmCIFParser

from completeness.mandatory_categories import (
    load_mandatory_categories,
    load_entity_src_group,
    detect_method,
    METHOD_UNKNOWN,
)


def _get_category_key(dictionary: DictionaryParser, category: str) -> Optional[str]:
    """Return the first key item name for the category (e.g. _pdbx_contact_author.id), or None."""
    cat_info = dictionary.categories.get(category)
    if not cat_info or not cat_info.get("keys"):
        return None
    return cat_info["keys"][0]


def _item_row_indices_with_validation_errors(
    mmcif: MmCIFParser,
    errors: List[object],
) -> Set[Tuple[str, int]]:
    """
    From validation errors with severity "error", build set of (item_name, row_index).
    row_index is the index in the category loop (from mmcif.items[item_name]).
    """
    result: Set[Tuple[str, int]] = set()
    for e in errors:
        if getattr(e, "severity", None) != "error":
            continue
        item_name = getattr(e, "item", None)
        line_num = getattr(e, "line", None)
        if item_name is None or line_num is None or item_name not in mmcif.items:
            continue
        for row_idx, iv in enumerate(mmcif.items[item_name]):
            if iv.line_num == line_num:
                result.add((item_name, row_idx))
                break
    return result


def compute_metadata_completeness(
    dictionary: DictionaryParser,
    mmcif: MmCIFParser,
    validation_errors: Optional[List[object]] = None,
) -> MetadataCompleteness:
    """
    Compute metadata-completeness percentage, method, and missing categories/items.

    - Mandatory categories from completeness lists (xray/em/nmr or common).
    - Mandatory items per category from dictionary.deposition_mandatory_items.
    - Row-level: for each row in a category, every mandatory item must be filled (?/. count as missing).
    - Items that have a validation error (severity "error") are counted as not filled and
      included in missing_items with has_validation_error=True.
    - total_count = sum over (mandatory category) of num_rows * num_mandatory_items; missing category = 1 row.
    - When method is unknown, only common categories are counted and percentage is capped at 50%.
    - Certain category groups (e.g. entity-source categories from entity_src_cat.list) are treated
      as satisfied when at least one category from the group is present.
    """
    validation_errors = validation_errors or []
    item_row_errors = _item_row_indices_with_validation_errors(mmcif, validation_errors)
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
    missing_categories: List[str] = []
    missing_items: List[dict] = []

    # Handle entity source category group: at least one of these categories must be present.
    entity_group = load_entity_src_group()
    if entity_group:
        present_entity_cats = entity_group & file_categories
        # Always work on a copy so we don't mutate shared sets from load_mandatory_categories()
        mandatory_categories = set(mandatory_categories)
        if present_entity_cats:
            # Group satisfied: drop the absent ones so they are not treated as missing.
            mandatory_categories -= (entity_group - present_entity_cats)
        else:
            # Group not satisfied: treat as one logical missing group for scoring/reporting.
            synthetic_cat = "[entity_src_group]"
            group_items: Set[str] = set()
            for cat in entity_group:
                group_items |= dictionary.deposition_mandatory_items.get(cat, set())
            if group_items:
                missing_categories.append(synthetic_cat)
                total_count += len(group_items)
                for item_name in group_items:
                    missing_items.append({"category": synthetic_cat, "item": item_name})
            # Also remove all entity-group categories from per-category mandatory list
            # to avoid double-counting them as individual missing categories.
            mandatory_categories -= entity_group

    for cat in mandatory_categories:
        items = dictionary.deposition_mandatory_items.get(cat, set())
        if not items:
            continue

        if cat not in file_categories:
            missing_categories.append(cat)
            # One conceptual row missing for the whole category
            total_count += len(items)
            for item_name in items:
                missing_items.append({"category": cat, "item": item_name})
            continue

        rows = mmcif.get_category_rows(cat)
        key_item = _get_category_key(dictionary, cat)

        if not rows:
            # Category present but no data rows: all items missing for one row
            total_count += len(items)
            for item_name in items:
                missing_items.append({"category": cat, "item": item_name, "row_index": 0})
            continue

        for row_index, row in enumerate(rows):
            row_key_val = None
            if key_item and key_item in row:
                row_key_val = row[key_item].value  # For display (e.g. "id=1")
            for item_name in items:
                total_count += 1
                if item_name not in row:
                    filled_count += 0
                    entry = {"category": cat, "item": item_name, "row_index": row_index}
                    if row_key_val is not None:
                        entry["row_key"] = row_key_val
                    missing_items.append(entry)
                else:
                    val = row[item_name].value
                    if val in ("?", ".") or not val.strip():
                        entry = {"category": cat, "item": item_name, "row_index": row_index}
                        if row_key_val is not None:
                            entry["row_key"] = row_key_val
                        missing_items.append(entry)
                    elif (item_name, row_index) in item_row_errors:
                        # Value present but has a validation error -> count as not filled
                        entry = {"category": cat, "item": item_name, "row_index": row_index, "has_validation_error": True}
                        if row_key_val is not None:
                            entry["row_key"] = row_key_val
                        missing_items.append(entry)
                    else:
                        filled_count += 1

    if total_count == 0:
        percentage = 0.0
    else:
        percentage = (filled_count / total_count) * 100.0
        if cap_at_50 and percentage > 50.0:
            percentage = 50.0

    return MetadataCompleteness(
        percentage=round(percentage, 1),
        filled_count=filled_count,
        total_count=total_count,
        method_detected=method_detected,
        message=message,
        missing_categories=missing_categories,
        missing_items=missing_items,
    )

