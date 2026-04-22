"""
Rule group for imported cross-check datasets.

This executes two imported families:
- pairwise comparison checks
- linked presence/comparison checks
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from mmcif_types import ItemValue, ValidationError
from rules.operators import compare_numeric
from rules.utils import MISSING_VALUES, item_name_for_category, item_value_to_number


class ImportedCrossChecksRuleGroup:
    def __init__(
        self,
        pairwise_path: Optional[Path] = None,
        linked_path: Optional[Path] = None,
    ):
        base = Path(__file__).resolve().parent / "data"
        self.pairwise_path = pairwise_path or (base / "cross_checks_pairwise_comparison.json")
        self.linked_path = linked_path or (base / "cross_checks_linked_presence_and_comparison.json")

    @staticmethod
    def _load_json(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _is_present(iv: Optional[ItemValue]) -> bool:
        return iv is not None and iv.value not in MISSING_VALUES

    @staticmethod
    def _severity_from_flag(flag: str) -> str:
        return "warning" if str(flag).strip().lower() == "soft" else "error"

    @staticmethod
    def _row_anchor_line(row: Dict[str, ItemValue]) -> int:
        return next(iter(row.values())).line_num if row else 1

    def _run_pairwise(self, mmcif, rows_cache: Dict[str, List[Dict[str, ItemValue]]]) -> List[ValidationError]:
        pairwise = self._load_json(self.pairwise_path)
        errors: List[ValidationError] = []

        for source_ref, tests in pairwise.items():
            if "." not in source_ref or not isinstance(tests, list):
                continue
            source_cat, source_item_short = source_ref.split(".", 1)
            source_item = item_name_for_category(source_cat, source_item_short)
            source_rows = rows_cache.setdefault(source_cat, mmcif.get_category_rows(source_cat))
            if not source_rows:
                continue

            for test in tests:
                if not isinstance(test, list) or len(test) < 5:
                    continue
                target_cat = str(test[0]).strip()
                target_item_short = str(test[1]).strip()
                error_text = str(test[2]).strip() or "Cross-check failed"
                op = str(test[3]).strip()
                severity = self._severity_from_flag(str(test[4]))
                target_item = item_name_for_category(target_cat, target_item_short)

                target_rows = rows_cache.setdefault(target_cat, mmcif.get_category_rows(target_cat))
                if not target_rows:
                    continue

                # Same-category tests are row-aligned; cross-category tests compare against all target values.
                if source_cat == target_cat:
                    for row in source_rows:
                        left_iv = row.get(source_item)
                        right_iv = row.get(target_item)
                        left_num = item_value_to_number(left_iv) if left_iv else None
                        right_num = item_value_to_number(right_iv) if right_iv else None
                        if left_num is None or right_num is None:
                            continue
                        # Imported operator semantics represent the violation condition.
                        if compare_numeric(left_num, op, right_num):
                            right_display = right_iv.value if right_iv and right_iv.value not in MISSING_VALUES else ""
                            resolved_text = error_text.replace("[{item2CrossValue}]", right_display)
                            errors.append(
                                ValidationError(
                                    line=left_iv.line_num,
                                    item=source_item,
                                    message=f"{resolved_text} (value={left_iv.value}, condition {op} {target_item})",
                                    severity=severity,  # type: ignore[arg-type]
                                    column=left_iv.global_column_index,
                                )
                            )
                else:
                    target_pairs: List[Tuple[str, float]] = []
                    for row in target_rows:
                        right_iv = row.get(target_item)
                        right_num = item_value_to_number(right_iv) if right_iv else None
                        if right_num is not None:
                            target_pairs.append((right_iv.value, right_num))
                    if not target_pairs:
                        continue

                    for row in source_rows:
                        left_iv = row.get(source_item)
                        left_num = item_value_to_number(left_iv) if left_iv else None
                        if left_num is None:
                            continue
                        violating_right_value = None
                        for right_value_text, right_num in target_pairs:
                            if compare_numeric(left_num, op, right_num):
                                violating_right_value = right_value_text
                                break
                        if violating_right_value is not None:
                            resolved_text = error_text.replace("[{item2CrossValue}]", violating_right_value)
                            errors.append(
                                ValidationError(
                                    line=left_iv.line_num,
                                    item=source_item,
                                    message=f"{resolved_text} (value={left_iv.value}, condition {op} {target_item})",
                                    severity=severity,  # type: ignore[arg-type]
                                    column=left_iv.global_column_index,
                                )
                            )

        return errors

    def _run_linked(self, mmcif, rows_cache: Dict[str, List[Dict[str, ItemValue]]]) -> List[ValidationError]:
        linked = self._load_json(self.linked_path)
        errors: List[ValidationError] = []

        for source_ref, rules in linked.items():
            if "." not in source_ref or not isinstance(rules, list):
                continue
            source_cat, source_item_short = source_ref.split(".", 1)
            source_item = item_name_for_category(source_cat, source_item_short)
            source_rows = rows_cache.setdefault(source_cat, mmcif.get_category_rows(source_cat))
            if not source_rows:
                continue

            for source_row in source_rows:
                source_iv = source_row.get(source_item)
                broke = False

                for rule in rules:
                    if not isinstance(rule, dict):
                        continue
                    target_cat = str(rule.get("cat", "")).strip()
                    target_item = item_name_for_category(target_cat, str(rule.get("item", "")).strip())
                    op = str(rule.get("operator", "")).strip()
                    text = str(rule.get("text", "")).strip() or "Cross-check failed"
                    cross = str(rule.get("cross", "")).strip()
                    cross2 = str(rule.get("cross2", cross)).strip()
                    severity = "warning" if bool(rule.get("warning")) else "error"
                    use_abs = bool(rule.get("absolute"))
                    should_break = bool(rule.get("break"))

                    if not target_cat or not cross or not cross2:
                        continue

                    source_key_item = item_name_for_category(source_cat, cross)
                    target_key_item = item_name_for_category(target_cat, cross2)
                    source_key_iv = source_row.get(source_key_item)
                    if source_key_iv is None or source_key_iv.value in MISSING_VALUES:
                        continue
                    source_key = source_key_iv.value

                    target_rows = rows_cache.setdefault(target_cat, mmcif.get_category_rows(target_cat))
                    if not target_rows:
                        continue
                    matching_targets = [
                        row for row in target_rows
                        if (row.get(target_key_item) is not None and row[target_key_item].value == source_key)
                    ]
                    if not matching_targets:
                        continue

                    # Optional placeholder replacement for imported message templates.
                    target_display_value = ""
                    for target_row in matching_targets:
                        candidate_iv = target_row.get(target_item)
                        if candidate_iv is not None and candidate_iv.value not in MISSING_VALUES:
                            target_display_value = candidate_iv.value
                            break
                    text_resolved = text.replace("[{item2CrossValue}]", target_display_value)

                    if op == "exists":
                        source_present = self._is_present(source_iv)
                        any_target_present = any(self._is_present(row.get(target_item)) for row in matching_targets)
                        failed = any_target_present and not source_present
                    elif op in {"<", ">", "<=", ">=", "==", "!="}:
                        left_num = item_value_to_number(source_iv) if source_iv else None
                        if left_num is None:
                            continue
                        if use_abs:
                            left_num = abs(left_num)
                        target_nums: List[float] = []
                        for row in matching_targets:
                            right_iv = row.get(target_item)
                            right_num = item_value_to_number(right_iv) if right_iv else None
                            if right_num is None:
                                continue
                            target_nums.append(abs(right_num) if use_abs else right_num)
                        if not target_nums:
                            continue
                        # Imported operator semantics represent the violation condition.
                        failed = any(compare_numeric(left_num, op, rn) for rn in target_nums)
                    else:
                        continue

                    if failed:
                        line = source_iv.line_num if source_iv else source_key_iv.line_num
                        col = source_iv.global_column_index if source_iv else source_key_iv.global_column_index
                        errors.append(
                            ValidationError(
                                line=line,
                                item=source_item,
                                message=text_resolved,
                                severity=severity,  # type: ignore[arg-type]
                                column=col,
                            )
                        )
                        if should_break:
                            broke = True
                            break
                if broke:
                    continue

        return errors

    def _run_conditional_required(self, mmcif, rows_cache: Dict[str, List[Dict[str, ItemValue]]]) -> List[ValidationError]:
        conditional_required = self._load_json(
            Path(__file__).resolve().parent / "data" / "cross_checks_conditional_required.json"
        )
        errors: List[ValidationError] = []

        for category, rules in conditional_required.items():
            if not isinstance(rules, list):
                continue
            rows = rows_cache.setdefault(category, mmcif.get_category_rows(category))
            if not rows:
                continue

            for row in rows:
                for rule in rules:
                    if not isinstance(rule, dict):
                        continue
                    conditions = rule.get("conditions", {})
                    required_items = rule.get("item", [])
                    if not isinstance(conditions, dict) or not isinstance(required_items, list):
                        continue

                    # All condition items must be present and match one of the allowed values.
                    conditions_met = True
                    for cond_item_short, allowed_values in conditions.items():
                        if not isinstance(allowed_values, list):
                            conditions_met = False
                            break
                        cond_item = item_name_for_category(category, str(cond_item_short))
                        cond_iv = row.get(cond_item)
                        if cond_iv is None or cond_iv.value in MISSING_VALUES:
                            conditions_met = False
                            break
                        allowed = {str(v).strip() for v in allowed_values}
                        if cond_iv.value not in allowed:
                            conditions_met = False
                            break

                    if not conditions_met:
                        continue

                    message = str(rule.get("error_text") or rule.get("warning_text") or "Required value missing").strip()
                    is_error = bool(rule.get("error", True))
                    severity = "error" if is_error else "warning"

                    for req_item_short in required_items:
                        req_item = item_name_for_category(category, str(req_item_short))
                        req_iv = row.get(req_item)
                        if self._is_present(req_iv):
                            continue
                        line = req_iv.line_num if req_iv else (next(iter(row.values())).line_num if row else 1)
                        col = req_iv.global_column_index if req_iv else None
                        errors.append(
                            ValidationError(
                                line=line,
                                item=req_item,
                                message=message,
                                severity=severity,  # type: ignore[arg-type]
                                column=col,
                            )
                        )

        return errors

    def _run_conditional_regex(self, mmcif, rows_cache: Dict[str, List[Dict[str, ItemValue]]]) -> List[ValidationError]:
        conditional_regex = self._load_json(
            Path(__file__).resolve().parent / "data" / "cross_checks_conditional_regex.json"
        )
        errors: List[ValidationError] = []

        for category, rules in conditional_regex.items():
            if not isinstance(rules, list):
                continue
            rows = rows_cache.setdefault(category, mmcif.get_category_rows(category))
            if not rows:
                continue

            for row in rows:
                for rule in rules:
                    if not isinstance(rule, dict):
                        continue
                    cond = rule.get("condition", {})
                    item_short = str(rule.get("item", "")).strip()
                    regex = str(rule.get("regex", "")).strip()
                    if not isinstance(cond, dict) or not item_short or not regex:
                        continue

                    cond_item_short = str(cond.get("item", "")).strip()
                    cond_value = str(cond.get("value", "")).strip()
                    if not cond_item_short:
                        continue

                    cond_item = item_name_for_category(category, cond_item_short)
                    cond_iv = row.get(cond_item)
                    if cond_iv is None or cond_iv.value in MISSING_VALUES or cond_iv.value != cond_value:
                        continue

                    target_item = item_name_for_category(category, item_short)
                    target_iv = row.get(target_item)
                    if target_iv is None or target_iv.value in MISSING_VALUES:
                        continue

                    try:
                        matches = re.match(regex, target_iv.value) is not None
                    except re.error:
                        continue
                    if matches:
                        continue

                    message = str(rule.get("error_text") or "Value does not match required pattern").strip()
                    severity = "error" if bool(rule.get("error", True)) else "warning"
                    errors.append(
                        ValidationError(
                            line=target_iv.line_num,
                            item=target_item,
                            message=message,
                            severity=severity,  # type: ignore[arg-type]
                            column=target_iv.global_column_index,
                        )
                    )

        return errors

    def _run_conditional_enumeration(self, mmcif, rows_cache: Dict[str, List[Dict[str, ItemValue]]]) -> List[ValidationError]:
        conditional_enum = self._load_json(
            Path(__file__).resolve().parent / "data" / "cross_checks_conditional_enumeration.json"
        )
        errors: List[ValidationError] = []

        for category, rules in conditional_enum.items():
            if not isinstance(rules, list):
                continue
            rows = rows_cache.setdefault(category, mmcif.get_category_rows(category))
            if not rows:
                continue

            for row in rows:
                for rule in rules:
                    if not isinstance(rule, dict):
                        continue
                    driver_item_short = str(rule.get("item", "")).strip()
                    affected_item_short = str(rule.get("affected_item", "")).strip()
                    conditions = rule.get("conditions", [])
                    if not driver_item_short or not affected_item_short or not isinstance(conditions, list):
                        continue

                    driver_item = item_name_for_category(category, driver_item_short)
                    affected_item = item_name_for_category(category, affected_item_short)
                    driver_iv = row.get(driver_item)
                    affected_iv = row.get(affected_item)
                    if driver_iv is None or affected_iv is None:
                        continue
                    if driver_iv.value in MISSING_VALUES or affected_iv.value in MISSING_VALUES:
                        continue

                    for cond in conditions:
                        if not isinstance(cond, dict):
                            continue
                        trigger_value = str(cond.get("value", "")).strip()
                        allowed_values = cond.get("validate", [])
                        if not trigger_value or not isinstance(allowed_values, list):
                            continue
                        if driver_iv.value != trigger_value:
                            continue

                        allowed = {str(v).strip() for v in allowed_values}
                        if affected_iv.value in allowed:
                            continue

                        message = str(cond.get("error_text") or "Invalid value for conditional enumeration").strip()
                        errors.append(
                            ValidationError(
                                line=affected_iv.line_num,
                                item=affected_item,
                                message=message,
                                severity="error",
                                column=affected_iv.global_column_index,
                            )
                        )
                        break

        return errors

    def _run_conditional_category_item(self, mmcif, rows_cache: Dict[str, List[Dict[str, ItemValue]]]) -> List[ValidationError]:
        conditional_category_item = self._load_json(
            Path(__file__).resolve().parent / "data" / "cross_checks_conditional_category_item.json"
        )
        errors: List[ValidationError] = []

        for category, rules in conditional_category_item.items():
            if not isinstance(rules, list):
                continue
            rows = rows_cache.setdefault(category, mmcif.get_category_rows(category))
            if not rows:
                continue

            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                cond = rule.get("condition", {})
                target_item_short = str(rule.get("item", "")).strip()
                pattern = str(rule.get("regex", "")).strip()
                if not isinstance(cond, dict) or not target_item_short or not pattern:
                    continue

                cond_cat = str(cond.get("category", "")).strip()
                cond_item_short = str(cond.get("item", "")).strip()
                cond_value = str(cond.get("value", "")).strip()
                if not cond_cat or not cond_item_short:
                    continue

                cond_rows = rows_cache.setdefault(cond_cat, mmcif.get_category_rows(cond_cat))
                cond_item = item_name_for_category(cond_cat, cond_item_short)
                condition_met = any(
                    (row.get(cond_item) is not None and row[cond_item].value == cond_value)
                    for row in cond_rows
                )
                if not condition_met:
                    continue

                target_item = item_name_for_category(category, target_item_short)
                message = str(rule.get("error_text") or "Required value missing").strip()
                severity = "error" if bool(rule.get("error", True)) else "warning"

                for row in rows:
                    iv = row.get(target_item)
                    value = iv.value if iv else ""
                    if iv is not None and value not in MISSING_VALUES:
                        try:
                            if re.match(pattern, value):
                                continue
                        except re.error:
                            continue
                    line = iv.line_num if iv else self._row_anchor_line(row)
                    col = iv.global_column_index if iv else None
                    errors.append(
                        ValidationError(
                            line=line,
                            item=target_item,
                            message=message,
                            severity=severity,  # type: ignore[arg-type]
                            column=col,
                        )
                    )

        return errors

    def _run_required_if_any_present(self, mmcif, rows_cache: Dict[str, List[Dict[str, ItemValue]]]) -> List[ValidationError]:
        required_if_any = self._load_json(
            Path(__file__).resolve().parent / "data" / "cross_checks_required_if_any_present.json"
        )
        errors: List[ValidationError] = []

        make_mandatory = required_if_any.get("makeMandatory", {})
        one_of_following = required_if_any.get("oneOfFollowing", {})

        # makeMandatory: if a row has any populated non-excluded item, enforce to_check items.
        if isinstance(make_mandatory, dict):
            for category, spec in make_mandatory.items():
                if not isinstance(spec, dict):
                    continue
                to_check = spec.get("to_check", [])
                exclude = set(spec.get("exclude", []))
                if not isinstance(to_check, list):
                    continue
                rows = rows_cache.setdefault(category, mmcif.get_category_rows(category))
                for row in rows:
                    has_signal = any(
                        (iv.value not in MISSING_VALUES)
                        for item_name, iv in row.items()
                        if item_name.startswith(f"_{category}.") and item_name.split(".", 1)[1] not in exclude
                    )
                    if not has_signal:
                        continue
                    for short in to_check:
                        item = item_name_for_category(category, str(short))
                        iv = row.get(item)
                        if self._is_present(iv):
                            continue
                        errors.append(
                            ValidationError(
                                line=iv.line_num if iv else self._row_anchor_line(row),
                                item=item,
                                message="No value present for this mandatory item.",
                                severity="error",
                                column=iv.global_column_index if iv else None,
                            )
                        )

        # oneOfFollowing: at category level, require at least one of the listed items to have a value.
        if isinstance(one_of_following, dict):
            for category, items in one_of_following.items():
                if not isinstance(items, list):
                    continue
                rows = rows_cache.setdefault(category, mmcif.get_category_rows(category))
                if not rows:
                    continue
                found_any = False
                for short in items:
                    full = item_name_for_category(category, str(short))
                    if any(self._is_present(row.get(full)) for row in rows):
                        found_any = True
                        break
                if found_any:
                    continue
                first_row = rows[0]
                errors.append(
                    ValidationError(
                        line=self._row_anchor_line(first_row),
                        item=item_name_for_category(category, str(items[0])) if items else f"_{category}.",
                        message="At least one related item must be provided.",
                        severity="error",
                    )
                )

        return errors

    def _run_build_defaults_cross(self, mmcif, rows_cache: Dict[str, List[Dict[str, ItemValue]]]) -> List[ValidationError]:
        build_defaults = self._load_json(
            Path(__file__).resolve().parent / "data" / "cross_checks_cross_reference_full.json"
        )
        rules = build_defaults.get("cross_reference_full", [])
        errors: List[ValidationError] = []
        if not isinstance(rules, list):
            return errors

        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if str(rule.get("type", "")).strip().lower() != "cross":
                continue
            if str(rule.get("subtype", "")).strip().lower() != "full":
                continue

            source_cat = str(rule.get("category", "")).strip()
            source_item_short = str(rule.get("item", "")).strip()
            target_cat = str(rule.get("cross_category", "")).strip()
            target_item_short = str(rule.get("cross_item", "")).strip()
            if not (source_cat and source_item_short and target_cat and target_item_short):
                continue

            source_item = item_name_for_category(source_cat, source_item_short)
            target_item = item_name_for_category(target_cat, target_item_short)
            source_rows = rows_cache.setdefault(source_cat, mmcif.get_category_rows(source_cat))
            target_rows = rows_cache.setdefault(target_cat, mmcif.get_category_rows(target_cat))
            if not source_rows or not target_rows:
                continue

            target_values = {
                iv.value
                for row in target_rows
                for iv in [row.get(target_item)]
                if iv is not None and iv.value not in MISSING_VALUES
            }
            if not target_values:
                continue

            for row in source_rows:
                source_iv = row.get(source_item)
                if source_iv is None or source_iv.value in MISSING_VALUES:
                    continue
                if source_iv.value in target_values:
                    continue
                errors.append(
                    ValidationError(
                        line=source_iv.line_num,
                        item=source_item,
                        message=f"Cross-reference value '{source_iv.value}' does not exist in '{target_item}'.",
                        severity="error",
                        column=source_iv.global_column_index,
                    )
                )

        return errors

    def run(self, mmcif) -> List[ValidationError]:
        rows_cache: Dict[str, List[Dict[str, ItemValue]]] = {}
        errors = []
        errors.extend(self._run_pairwise(mmcif, rows_cache))
        errors.extend(self._run_linked(mmcif, rows_cache))
        errors.extend(self._run_conditional_required(mmcif, rows_cache))
        errors.extend(self._run_conditional_regex(mmcif, rows_cache))
        errors.extend(self._run_conditional_enumeration(mmcif, rows_cache))
        errors.extend(self._run_conditional_category_item(mmcif, rows_cache))
        errors.extend(self._run_required_if_any_present(mmcif, rows_cache))
        errors.extend(self._run_build_defaults_cross(mmcif, rows_cache))
        return errors
