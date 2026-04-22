"""
Rule group for imported cross-check datasets.

This executes grouped JSON rule families: pairwise (numeric and date order),
linked presence/comparison, conditional rules, dictionary enum, procedural
validators, and uniqueness within categories.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from mmcif_types import ItemValue, ValidationError
from rules.operators import compare_numeric
from rules.utils import MISSING_VALUES, item_name_for_category, item_value_to_number, mmcif_datetime_tuple


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

    @staticmethod
    def _render_message_template(template: str, **values: str) -> str:
        """
        Render rule message placeholders and strip unresolved tokens.
        Supported tokens include e.g. [{item2CrossValue}].
        """
        text = str(template or "").strip()
        for key, value in values.items():
            text = text.replace(f"[{{{key}}}]", str(value or ""))
        # Guardrail: do not leak unresolved placeholders to users.
        text = re.sub(r"\[\{[^}]+\}\]", "", text).strip()
        text = re.sub(r"\s{2,}", " ", text)
        return text

    @staticmethod
    def _resolve_entry_subtypes(mmcif, runtime_context: Optional[dict]) -> Set[str]:
        """
        Resolve experiment/content subtypes used by subtype-gated rules.
        Safe default is empty set (rules remain inactive without context).
        """
        if isinstance(runtime_context, dict):
            from_context = runtime_context.get("entry_subtypes")
            if isinstance(from_context, list):
                return {str(v).strip() for v in from_context if str(v).strip()}
        from_mmcif = getattr(mmcif, "entry_subtypes", None)
        if isinstance(from_mmcif, list):
            return {str(v).strip() for v in from_mmcif if str(v).strip()}
        return set()

    @staticmethod
    def _resolve_experiment_modes(mmcif, runtime_context: Optional[dict]) -> Set[str]:
        if isinstance(runtime_context, dict):
            from_context = runtime_context.get("experiment_modes")
            if isinstance(from_context, list):
                return {str(v).strip().lower() for v in from_context if str(v).strip()}
        from_mmcif = getattr(mmcif, "experiment_modes", None)
        if isinstance(from_mmcif, list):
            return {str(v).strip().lower() for v in from_mmcif if str(v).strip()}
        return set()

    @staticmethod
    def _resolve_requested_codes(mmcif, runtime_context: Optional[dict]) -> Set[str]:
        if isinstance(runtime_context, dict):
            from_context = runtime_context.get("requested_codes")
            if isinstance(from_context, list):
                return {str(v).strip().upper() for v in from_context if str(v).strip()}
        from_mmcif = getattr(mmcif, "requested_codes", None)
        if isinstance(from_mmcif, list):
            return {str(v).strip().upper() for v in from_mmcif if str(v).strip()}
        return set()

    def _cross_rule_selector_matches(self, rule: dict, mmcif, runtime_context: Optional[dict]) -> bool:
        expt_selector = rule.get("expt", "all")
        code_selector = str(rule.get("code", "")).strip().upper()

        # "all" means selector always applies.
        if isinstance(expt_selector, str) and expt_selector.strip().lower() == "all":
            return True

        # "coded" means code-gated rule; skip when code context is unavailable.
        if isinstance(expt_selector, str) and expt_selector.strip().lower() == "coded":
            if not code_selector:
                return False
            requested_codes = self._resolve_requested_codes(mmcif, runtime_context)
            if not requested_codes:
                return False
            return code_selector in requested_codes

        # List of experiment modes; skip when expt context is unavailable.
        if isinstance(expt_selector, list):
            allowed = {str(v).strip().lower() for v in expt_selector if str(v).strip()}
            if not allowed:
                return False
            experiment_modes = self._resolve_experiment_modes(mmcif, runtime_context)
            if not experiment_modes:
                return False
            return bool(allowed.intersection(experiment_modes))

        return False

    @staticmethod
    def _chrono_pair_violates(left: Tuple[int, int, int, int, int], op: str, right: Tuple[int, int, int, int, int]) -> bool:
        """Return True if the chronological ordering constraint is violated."""
        o = str(op).strip()
        if o == "<=":
            return left > right
        if o == "<":
            return left >= right
        if o == ">=":
            return left < right
        if o == ">":
            return left <= right
        return False

    def _run_pairwise_date_order(self, mmcif, rows_cache: Dict[str, List[Dict[str, ItemValue]]]) -> List[ValidationError]:
        data = self._load_json(
            Path(__file__).resolve().parent / "data" / "cross_checks_pairwise_date_order.json"
        )
        errors: List[ValidationError] = []
        rules = data.get("date_order_rules", [])
        if not isinstance(rules, list):
            return errors

        for rule in rules:
            if not isinstance(rule, dict):
                continue
            category = str(rule.get("category", "")).strip()
            left_short = str(rule.get("left_item", "")).strip()
            right_short = str(rule.get("right_item", "")).strip()
            op = str(rule.get("op", "<=")).strip()
            message = str(rule.get("message", "")).strip() or "Date order is inconsistent."
            severity = self._severity_from_flag(str(rule.get("severity", "hard")))
            if not category or not left_short or not right_short:
                continue

            left_item = item_name_for_category(category, left_short)
            right_item = item_name_for_category(category, right_short)
            rows = rows_cache.setdefault(category, mmcif.get_category_rows(category))
            if not rows:
                continue

            for row in rows:
                left_iv = row.get(left_item)
                right_iv = row.get(right_item)
                if not self._is_present(left_iv) or not self._is_present(right_iv):
                    continue
                lt = mmcif_datetime_tuple(left_iv.value)
                rt = mmcif_datetime_tuple(right_iv.value)
                if lt is None or rt is None:
                    continue
                if not self._chrono_pair_violates(lt, op, rt):
                    continue
                resolved = self._render_message_template(
                    message,
                    right_value=right_iv.value.strip(),
                    left_value=left_iv.value.strip(),
                )
                errors.append(
                    ValidationError(
                        line=left_iv.line_num,
                        item=left_item,
                        message=resolved,
                        severity=severity,  # type: ignore[arg-type]
                        column=left_iv.global_column_index,
                    )
                )

        return errors

    def _run_uniqueness(self, mmcif, rows_cache: Dict[str, List[Dict[str, ItemValue]]]) -> List[ValidationError]:
        data = self._load_json(
            Path(__file__).resolve().parent / "data" / "cross_checks_uniqueness.json"
        )
        errors: List[ValidationError] = []
        rules = data.get("uniqueness_rules", [])
        if not isinstance(rules, list):
            return errors

        for rule in rules:
            if not isinstance(rule, dict):
                continue
            category = str(rule.get("category", "")).strip()
            key_shorts = rule.get("key_items", [])
            if not category or not isinstance(key_shorts, list) or not key_shorts:
                continue
            key_shorts = [str(s).strip() for s in key_shorts if str(s).strip()]
            if not key_shorts:
                continue

            items = [item_name_for_category(category, s) for s in key_shorts]
            rows = rows_cache.setdefault(category, mmcif.get_category_rows(category))
            if len(rows) < 2:
                continue

            severity = self._severity_from_flag(str(rule.get("severity", "hard")))
            message_tmpl = str(rule.get("message", "")).strip() or (
                "Duplicate unique key ({key_columns}): [{duplicate_display}]."
            )
            key_columns = ", ".join(key_shorts)

            buckets: Dict[Tuple[str, ...], List[Dict[str, ItemValue]]] = defaultdict(list)
            for row in rows:
                parts: List[str] = []
                skip = False
                for it in items:
                    iv = row.get(it)
                    if not self._is_present(iv):
                        skip = True
                        break
                    parts.append(iv.value.strip())
                if skip:
                    continue
                buckets[tuple(parts)].append(row)

            for _key, group in buckets.items():
                if len(group) < 2:
                    continue
                duplicate_display = ", ".join(_key)
                resolved = self._render_message_template(
                    message_tmpl,
                    key_columns=key_columns,
                    duplicate_display=duplicate_display,
                    category=category,
                )
                for row in group:
                    anchor_iv = row.get(items[0])
                    if anchor_iv is None:
                        continue
                    errors.append(
                        ValidationError(
                            line=anchor_iv.line_num,
                            item=items[0],
                            message=resolved,
                            severity=severity,  # type: ignore[arg-type]
                            column=anchor_iv.global_column_index,
                        )
                    )

        return errors

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
                            resolved_text = self._render_message_template(
                                error_text,
                                item2CrossValue=right_display,
                            )
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
                            resolved_text = self._render_message_template(
                                error_text,
                                item2CrossValue=violating_right_value,
                            )
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
                    text_resolved = self._render_message_template(
                        text,
                        item2CrossValue=target_display_value,
                    )

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
                    skip_cats = rule.get("skip_if_any_category_present", [])
                    if isinstance(skip_cats, list) and skip_cats:
                        skip_rule = False
                        for sc in skip_cats:
                            scn = str(sc).strip()
                            if not scn:
                                continue
                            other_rows = rows_cache.setdefault(
                                scn, mmcif.get_category_rows(scn)
                            )
                            if other_rows:
                                skip_rule = True
                                break
                        if skip_rule:
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

                    message = self._render_message_template(
                        str(rule.get("error_text") or rule.get("warning_text") or "Required value missing")
                    )
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

                    message = self._render_message_template(
                        str(rule.get("error_text") or "Value does not match required pattern")
                    )
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

                        message = self._render_message_template(
                            str(cond.get("error_text") or "Invalid value for conditional enumeration")
                        )
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
                message = self._render_message_template(
                    str(rule.get("error_text") or "Required value missing")
                )
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

    def _run_required_if_any_present(
        self,
        mmcif,
        rows_cache: Dict[str, List[Dict[str, ItemValue]]],
        runtime_context: Optional[dict],
    ) -> List[ValidationError]:
        required_if_any = self._load_json(
            Path(__file__).resolve().parent / "data" / "cross_checks_required_if_any_present.json"
        )
        errors: List[ValidationError] = []

        make_mandatory = required_if_any.get("makeMandatory", {})
        make_mandatory_subtypes = required_if_any.get("makeMandatorySubtypes", {})
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

        # makeMandatorySubtypes: same behavior as makeMandatory, but only for active entry subtypes.
        entry_subtypes = self._resolve_entry_subtypes(mmcif, runtime_context)
        if isinstance(make_mandatory_subtypes, dict) and entry_subtypes:
            for subtype, categories in make_mandatory_subtypes.items():
                if str(subtype) not in entry_subtypes or not isinstance(categories, dict):
                    continue
                for category, spec in categories.items():
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

    def _run_dictionary_enum(
        self,
        mmcif,
        rows_cache: Dict[str, List[Dict[str, ItemValue]]],
        dictionary=None,
    ) -> List[ValidationError]:
        dictionary_enum = self._load_json(
            Path(__file__).resolve().parent / "data" / "cross_checks_dictionary_enum.json"
        )
        errors: List[ValidationError] = []
        if not isinstance(dictionary_enum, dict):
            return errors
        if dictionary is None:
            return errors

        for category, item_map in dictionary_enum.items():
            if not isinstance(item_map, dict):
                continue
            rows = rows_cache.setdefault(category, mmcif.get_category_rows(category))
            if not rows:
                continue

            for source_item_short, cross_item_short in item_map.items():
                source_item = item_name_for_category(category, str(source_item_short))
                cross_item = item_name_for_category(category, str(cross_item_short))
                item_def = dictionary.items.get(source_item, {}) if hasattr(dictionary, "items") else {}
                enum_details = item_def.get("enumeration_details", {}) if isinstance(item_def, dict) else {}
                if not isinstance(enum_details, dict) or not enum_details:
                    continue

                for row in rows:
                    source_iv = row.get(source_item)
                    cross_iv = row.get(cross_item)
                    if not self._is_present(source_iv):
                        continue
                    source_value = source_iv.value
                    allowed = enum_details.get(source_value)
                    if not isinstance(allowed, list) or not allowed:
                        errors.append(
                            ValidationError(
                                line=source_iv.line_num,
                                item=source_item,
                                message=(
                                    f"Value '{source_value}' is not compatible with '{cross_item}' "
                                    "because no dictionary cross-enumeration mapping is defined."
                                ),
                                severity="error",
                                column=source_iv.global_column_index,
                            )
                        )
                        continue

                    if not self._is_present(cross_iv):
                        continue
                    if cross_iv.value in allowed:
                        continue

                    errors.append(
                        ValidationError(
                            line=source_iv.line_num,
                            item=source_item,
                            message=(
                                f"Value '{source_value}' is not compatible with '{cross_item}={cross_iv.value}'. "
                                f"Allowed values: {', '.join(sorted(set(allowed)))}."
                            ),
                            severity="error",
                            column=source_iv.global_column_index,
                        )
                    )

        return errors

    def _run_build_defaults_cross(
        self,
        mmcif,
        rows_cache: Dict[str, List[Dict[str, ItemValue]]],
        runtime_context: Optional[dict],
    ) -> List[ValidationError]:
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
            if not self._cross_rule_selector_matches(rule, mmcif, runtime_context):
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

    def _run_procedural_validators(self, mmcif, rows_cache: Dict[str, List[Dict[str, ItemValue]]]) -> List[ValidationError]:
        """
        Phase 2 procedural validator migration.
        Rule definitions are data-driven under rules/data/cross_checks_procedural_validators.json.
        """
        procedural = self._load_json(
            Path(__file__).resolve().parent / "data" / "cross_checks_procedural_validators.json"
        )
        errors: List[ValidationError] = []
        checks = procedural.get("procedural_checks", []) if isinstance(procedural, dict) else []
        if not isinstance(checks, list):
            return errors

        for check in checks:
            if not isinstance(check, dict):
                continue
            if str(check.get("kind", "")).strip().lower() != "wavelength_protocol_consistency":
                continue
            source = check.get("source", {})
            target = check.get("target", {})
            rules = check.get("rules", [])
            if not isinstance(source, dict) or not isinstance(target, dict) or not isinstance(rules, list):
                continue
            source_cat = str(source.get("category", "")).strip()
            source_item_short = str(source.get("item", "")).strip()
            source_key_short = str(source.get("key", "")).strip()
            target_cat = str(target.get("category", "")).strip()
            target_item_short = str(target.get("item", "")).strip()
            target_key_short = str(target.get("key", "")).strip()
            if not all([source_cat, source_item_short, source_key_short, target_cat, target_item_short, target_key_short]):
                continue

            source_rows = rows_cache.setdefault(source_cat, mmcif.get_category_rows(source_cat))
            target_rows = rows_cache.setdefault(target_cat, mmcif.get_category_rows(target_cat))
            if not source_rows or not target_rows:
                continue

            source_item = item_name_for_category(source_cat, source_item_short)
            source_key_item = item_name_for_category(source_cat, source_key_short)
            target_item = item_name_for_category(target_cat, target_item_short)
            target_key_item = item_name_for_category(target_cat, target_key_short)

            for source_row in source_rows:
                source_iv = source_row.get(source_item)
                if source_iv is None or source_iv.value in MISSING_VALUES:
                    continue
                source_value = source_iv.value.strip()

                source_key_iv = source_row.get(source_key_item)
                source_key = (
                    source_key_iv.value
                    if source_key_iv and source_key_iv.value not in MISSING_VALUES
                    else None
                )
                matching_target_rows = (
                    [
                        row for row in target_rows
                        if (
                            source_key is not None
                            and row.get(target_key_item) is not None
                            and row[target_key_item].value == source_key
                        )
                    ]
                    if source_key is not None
                    else target_rows
                )

                protocols = []
                for row in matching_target_rows:
                    target_iv = row.get(target_item)
                    if target_iv is None or target_iv.value in MISSING_VALUES:
                        continue
                    protocols.append(target_iv.value.strip().upper())

                empty_rule = check.get("empty_list_when_protocol_any_of")
                if (
                    isinstance(empty_rule, dict)
                    and not source_value
                    and protocols
                ):
                    proto_set = {
                        str(p).strip().upper()
                        for p in empty_rule.get("protocols", [])
                        if str(p).strip()
                    }
                    if proto_set and any(p in proto_set for p in protocols):
                        severity = self._severity_from_flag(str(empty_rule.get("severity", "hard")))
                        message = self._render_message_template(
                            str(
                                empty_rule.get(
                                    "message",
                                    "pdbx_wavelength_list must not be empty for this diffraction protocol.",
                                )
                            )
                        )
                        errors.append(
                            ValidationError(
                                line=source_iv.line_num,
                                item=source_item,
                                message=message,
                                severity=severity,  # type: ignore[arg-type]
                                column=source_iv.global_column_index,
                            )
                        )
                        continue

                if not source_value:
                    continue

                if not protocols:
                    continue

                comma_values = source_value.split(",")
                range_values = source_value.split("-")
                is_multi_value = len(comma_values) > 1 or len(range_values) > 1

                for rule in rules:
                    if not isinstance(rule, dict):
                        continue
                    protocol = str(rule.get("protocol", "")).strip().upper()
                    requires = str(rule.get("requires", "")).strip().lower()
                    severity = self._severity_from_flag(str(rule.get("severity", "hard")))
                    message = self._render_message_template(str(rule.get("message", "Cross-check failed")))
                    if not protocol or requires not in {"single", "multi"}:
                        continue
                    if protocol not in protocols:
                        continue
                    failed = (requires == "multi" and not is_multi_value) or (requires == "single" and is_multi_value)
                    if not failed:
                        continue
                    errors.append(
                        ValidationError(
                            line=source_iv.line_num,
                            item=source_item,
                            message=message,
                            severity=severity,  # type: ignore[arg-type]
                            column=source_iv.global_column_index,
                        )
                    )
                    break

        for check in checks:
            if not isinstance(check, dict):
                continue
            if str(check.get("kind", "")).strip().lower() != "accession_format_rule":
                continue
            category = str(check.get("category", "")).strip()
            item_short = str(check.get("item", "")).strip()
            driver_item_short = str(check.get("driver_item", "")).strip()
            rules = check.get("rules", [])
            if not category or not item_short or not driver_item_short or not isinstance(rules, list):
                continue

            rows = rows_cache.setdefault(category, mmcif.get_category_rows(category))
            if not rows:
                continue
            item = item_name_for_category(category, item_short)
            driver_item = item_name_for_category(category, driver_item_short)
            skip_if_empty = bool(check.get("skip_if_empty", False))

            for row in rows:
                value_iv = row.get(item)
                driver_iv = row.get(driver_item)
                if value_iv is None or value_iv.value in MISSING_VALUES:
                    continue
                if driver_iv is None or driver_iv.value in MISSING_VALUES:
                    continue
                value = value_iv.value.strip()
                driver_value = driver_iv.value.strip().upper()
                if skip_if_empty and not value:
                    continue
                if not value:
                    continue

                for rule in rules:
                    if not isinstance(rule, dict):
                        continue
                    expected_driver_value = str(rule.get("driver_value", "")).strip().upper()
                    formats = rule.get("accepted_formats", [])
                    if driver_value != expected_driver_value or not isinstance(formats, list):
                        continue

                    def _matches(fmt: str, text: str) -> bool:
                        v = text.strip()
                        if fmt == "pdb_id":
                            return re.match(r"^(pdb_0000)?[\w\d]{4}$", v.lower()) is not None
                        if fmt == "emdb_id":
                            return re.match(r"^emd-\d+$", v.lower()) is not None
                        if fmt == "deposition_id":
                            return re.match(r"^D_1\d{9}$", v) is not None
                        if fmt == "genbank_id":
                            return (
                                re.match(r"^[A-Za-z]{2}\d{6}\.\d$", v) is not None
                                or re.match(r"^[A-Za-z]\d{5}\.\d$", v) is not None
                            )
                        if fmt == "uniprot_id":
                            return re.match(
                                r"^([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})(-\d+)?$",
                                v,
                            ) is not None
                        if fmt == "pdbdev_id":
                            return re.match(r"^pdbdev_[\d]{8}$", v.lower()) is not None
                        return False

                    if any(_matches(str(fmt).strip(), value) for fmt in formats):
                        continue

                    severity = self._severity_from_flag(str(rule.get("severity", "hard")))
                    message = self._render_message_template(str(rule.get("message", "Invalid accession code format.")))
                    errors.append(
                        ValidationError(
                            line=value_iv.line_num,
                            item=item,
                            message=message,
                            severity=severity,  # type: ignore[arg-type]
                            column=value_iv.global_column_index,
                        )
                    )
                    break

        for check in checks:
            if not isinstance(check, dict):
                continue
            if str(check.get("kind", "")).strip().lower() != "conditional_accession_format_rule":
                continue
            category = str(check.get("category", "")).strip()
            item_short = str(check.get("item", "")).strip()
            rules = check.get("rules", [])
            if not category or not item_short or not isinstance(rules, list):
                continue

            rows = rows_cache.setdefault(category, mmcif.get_category_rows(category))
            if not rows:
                continue
            item = item_name_for_category(category, item_short)

            for row in rows:
                value_iv = row.get(item)
                if value_iv is None or value_iv.value in MISSING_VALUES:
                    continue
                value = value_iv.value.strip()
                if not value:
                    continue

                for rule in rules:
                    if not isinstance(rule, dict):
                        continue
                    conditions = rule.get("conditions", {})
                    formats = rule.get("accepted_formats", [])
                    if not isinstance(conditions, dict) or not isinstance(formats, list):
                        continue

                    conditions_met = True
                    for cond_item_short, expected in conditions.items():
                        cond_item = item_name_for_category(category, str(cond_item_short))
                        cond_iv = row.get(cond_item)
                        if cond_iv is None or cond_iv.value in MISSING_VALUES:
                            conditions_met = False
                            break
                        if cond_iv.value.strip().lower() != str(expected).strip().lower():
                            conditions_met = False
                            break
                    if not conditions_met:
                        continue

                    def _matches(fmt: str, text: str) -> bool:
                        v = text.strip()
                        if fmt == "pdb_id":
                            return re.match(r"^(pdb_0000)?[\w\d]{4}$", v.lower()) is not None
                        if fmt == "pdbdev_id":
                            return re.match(r"^pdbdev_[\d]{8}$", v.lower()) is not None
                        if fmt == "alphafold_id":
                            return re.match(
                                r"^((AF-)?([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})(-F[0-9])?)?$",
                                v,
                            ) is not None
                        if fmt == "modelarchive_id":
                            return re.match(r"^(ma-[\w\d]{5})?$", v.lower()) is not None
                        return False

                    if any(_matches(str(fmt).strip(), value) for fmt in formats):
                        continue

                    severity = self._severity_from_flag(str(rule.get("severity", "hard")))
                    message = self._render_message_template(str(rule.get("message", "Invalid accession code format.")))
                    errors.append(
                        ValidationError(
                            line=value_iv.line_num,
                            item=item,
                            message=message,
                            severity=severity,  # type: ignore[arg-type]
                            column=value_iv.global_column_index,
                        )
                    )
                    break

        for check in checks:
            if not isinstance(check, dict):
                continue
            if str(check.get("kind", "")).strip().lower() != "conditional_value_rule":
                continue
            category = str(check.get("category", "")).strip()
            item_short = str(check.get("item", "")).strip()
            rules = check.get("rules", [])
            if not category or not item_short or not isinstance(rules, list):
                continue

            rows = rows_cache.setdefault(category, mmcif.get_category_rows(category))
            if not rows:
                continue
            item = item_name_for_category(category, item_short)

            for row in rows:
                target_iv = row.get(item)
                if target_iv is None or target_iv.value in MISSING_VALUES:
                    continue
                target_value = target_iv.value.strip()
                if not target_value:
                    continue

                for rule in rules:
                    if not isinstance(rule, dict):
                        continue
                    conditions = rule.get("conditions", {})
                    allowed_values = rule.get("allowed_values", [])
                    if not isinstance(conditions, dict) or not isinstance(allowed_values, list):
                        continue

                    conditions_met = True
                    for cond_item_short, expected in conditions.items():
                        cond_item = item_name_for_category(category, str(cond_item_short))
                        cond_iv = row.get(cond_item)
                        if cond_iv is None or cond_iv.value in MISSING_VALUES:
                            conditions_met = False
                            break
                        if cond_iv.value.strip().lower() != str(expected).strip().lower():
                            conditions_met = False
                            break
                    if not conditions_met:
                        continue

                    allowed_normalized = {str(v).strip().lower() for v in allowed_values if str(v).strip()}
                    if target_value.lower() in allowed_normalized:
                        continue

                    severity = self._severity_from_flag(str(rule.get("severity", "hard")))
                    message = self._render_message_template(str(rule.get("message", "Invalid value for condition.")))
                    errors.append(
                        ValidationError(
                            line=target_iv.line_num,
                            item=item,
                            message=message,
                            severity=severity,  # type: ignore[arg-type]
                            column=target_iv.global_column_index,
                        )
                    )
                    break

        for check in checks:
            if not isinstance(check, dict):
                continue
            if str(check.get("kind", "")).strip().lower() != "sequence_predicate_warning":
                continue
            category = str(check.get("category", "")).strip()
            item_short = str(check.get("item", "")).strip()
            rules = check.get("rules", [])
            if not category or not item_short or not isinstance(rules, list):
                continue

            rows = rows_cache.setdefault(category, mmcif.get_category_rows(category))
            if not rows:
                continue
            item = item_name_for_category(category, item_short)

            for row in rows:
                value_iv = row.get(item)
                if value_iv is None or value_iv.value in MISSING_VALUES:
                    continue
                value = value_iv.value.strip()
                if not value:
                    continue

                for rule in rules:
                    if not isinstance(rule, dict):
                        continue
                    predicate = str(rule.get("predicate", "")).strip().lower()
                    severity = self._severity_from_flag(str(rule.get("severity", "soft")))
                    message = self._render_message_template(str(rule.get("message", "Sequence check warning.")))
                    matched = False
                    if predicate == "homopolymer_ala":
                        upper = value.upper()
                        matched = len(upper) > 0 and upper.count("A") == len(upper)
                    elif predicate == "substring":
                        needle = str(rule.get("substring", ""))
                        matched = bool(needle) and needle in value
                    else:
                        continue
                    if not matched:
                        continue
                    errors.append(
                        ValidationError(
                            line=value_iv.line_num,
                            item=item,
                            message=message,
                            severity=severity,  # type: ignore[arg-type]
                            column=value_iv.global_column_index,
                        )
                    )

        return errors

    def run(self, mmcif, dictionary=None, runtime_context: Optional[Dict[str, Any]] = None) -> List[ValidationError]:
        rows_cache: Dict[str, List[Dict[str, ItemValue]]] = {}
        errors = []
        errors.extend(self._run_pairwise(mmcif, rows_cache))
        errors.extend(self._run_pairwise_date_order(mmcif, rows_cache))
        errors.extend(self._run_uniqueness(mmcif, rows_cache))
        errors.extend(self._run_linked(mmcif, rows_cache))
        errors.extend(self._run_conditional_required(mmcif, rows_cache))
        errors.extend(self._run_conditional_regex(mmcif, rows_cache))
        errors.extend(self._run_conditional_enumeration(mmcif, rows_cache))
        errors.extend(self._run_conditional_category_item(mmcif, rows_cache))
        errors.extend(self._run_required_if_any_present(mmcif, rows_cache, runtime_context))
        errors.extend(self._run_dictionary_enum(mmcif, rows_cache, dictionary))
        errors.extend(self._run_build_defaults_cross(mmcif, rows_cache, runtime_context))
        errors.extend(self._run_procedural_validators(mmcif, rows_cache))
        return errors
