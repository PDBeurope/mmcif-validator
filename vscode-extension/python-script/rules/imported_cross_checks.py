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

LINKED_FALLBACK_SINGLE_ROW = "single_row_if_key_missing"


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
    def _join_key_missing(iv: Optional[ItemValue]) -> bool:
        """True when a linked-join key is absent, placeholder, or blank."""
        if iv is None or iv.value is None:
            return True
        value = str(iv.value).strip()
        return not value or value in MISSING_VALUES

    def _linked_matching_targets(
        self,
        source_rows: List[Dict[str, ItemValue]],
        source_row: Dict[str, ItemValue],
        source_key_item: str,
        target_rows: List[Dict[str, ItemValue]],
        target_key_item: str,
        allow_single_row_fallback: bool,
    ) -> List[Dict[str, ItemValue]]:
        """
        Pair source/target rows by join key.

        Optional fallback (opt-in per rule): if the key match finds nothing, the
        target category has exactly one row, and that row's join key is missing,
        use the singleton target. Do not guess when keys are present and disagree,
        or when there are multiple target rows.
        """
        source_key_iv = source_row.get(source_key_item)
        source_key_missing = self._join_key_missing(source_key_iv)
        matching: List[Dict[str, ItemValue]] = []
        if not source_key_missing:
            source_key = source_key_iv.value
            matching = [
                row for row in target_rows
                if (
                    not self._join_key_missing(row.get(target_key_item))
                    and row[target_key_item].value == source_key
                )
            ]
        if matching:
            return matching
        if not allow_single_row_fallback or len(target_rows) != 1:
            return []
        target_row = target_rows[0]
        if not self._join_key_missing(target_row.get(target_key_item)):
            return []
        if source_key_missing and len(source_rows) != 1:
            return []
        return [target_row]

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
                    allow_single_row_fallback = (
                        str(rule.get("fallback", "")).strip() == LINKED_FALLBACK_SINGLE_ROW
                    )

                    target_rows = rows_cache.setdefault(target_cat, mmcif.get_category_rows(target_cat))
                    if not target_rows:
                        continue
                    matching_targets = self._linked_matching_targets(
                        source_rows,
                        source_row,
                        source_key_item,
                        target_rows,
                        target_key_item,
                        allow_single_row_fallback,
                    )
                    if not matching_targets:
                        continue
                    source_key_iv = source_row.get(source_key_item)

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
                        if source_iv is not None:
                            line = source_iv.line_num
                            col = source_iv.global_column_index
                        elif source_key_iv is not None:
                            line = source_key_iv.line_num
                            col = source_key_iv.global_column_index
                        else:
                            line = self._row_anchor_line(source_row)
                            col = None
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

    @staticmethod
    def _format_occupancy_number(value: float) -> str:
        """Format occupancy for messages (strip trailing zeros, keep mmCIF-like decimals)."""
        text = f"{round(float(value), 4):.4f}".rstrip("0").rstrip(".")
        return text if text else "0"

    @staticmethod
    def _row_item_text(row: Dict[str, ItemValue], item: str, default: str = "") -> str:
        iv = row.get(item)
        if iv is None or iv.value in MISSING_VALUES:
            return default
        text = str(iv.value).strip()
        return text if text else default

    def _row_item_text_fallback(
        self,
        row: Dict[str, ItemValue],
        category: str,
        primary: str,
        fallbacks: Optional[List[str]] = None,
        default: str = "",
    ) -> str:
        names = [primary] + list(fallbacks or [])
        for short in names:
            text = self._row_item_text(row, item_name_for_category(category, short), default="")
            if text:
                return text
        return default

    def _atom_site_occupancy_identity(
        self,
        row: Dict[str, ItemValue],
        category: str,
    ) -> Optional[Tuple[Tuple[str, str, str, str, str], Dict[str, str]]]:
        """
        Identify an atom for occupancy summing: model, chain, residue, insertion, atom name.

        Alternate locations of the same atom are grouped together. Residue name is for
        messages only, so dual-conformation residue types still share occupancy.
        """
        atom = self._row_item_text_fallback(
            row, category, "label_atom_id", ["auth_atom_id"], default=""
        )
        if not atom:
            return None
        model = self._row_item_text_fallback(
            row, category, "pdbx_PDB_model_num", default="1"
        )
        chain = self._row_item_text_fallback(
            row, category, "auth_asym_id", ["label_asym_id"], default="?"
        )
        seq = self._row_item_text_fallback(
            row, category, "auth_seq_id", ["label_seq_id"], default="?"
        )
        ins = self._row_item_text_fallback(row, category, "pdbx_PDB_ins_code", default="")
        comp = self._row_item_text_fallback(
            row, category, "auth_comp_id", ["label_comp_id"], default="?"
        )
        residue = f"{seq}{ins}" if ins else seq
        display = {
            "model": model,
            "chain": chain,
            "seq": seq,
            "ins": ins,
            "residue": residue,
            "comp": comp,
            "atom": atom,
        }
        return (model, chain, seq, ins, atom), display

    def _run_atom_site_occupancy(
        self,
        mmcif,
        rows_cache: Dict[str, List[Dict[str, ItemValue]]],
        check: dict,
    ) -> List[ValidationError]:
        """
        Occupancy checks on _atom_site:

        - Sum occupancy over alternate locations of the same atom; total > 1.0 is an error.
        - An individual occupancy value below 0.1 is a warning.
        """
        errors: List[ValidationError] = []
        category = str(check.get("category", "atom_site")).strip() or "atom_site"
        item_short = str(check.get("item", "occupancy")).strip() or "occupancy"
        occ_item = item_name_for_category(category, item_short)
        rows = rows_cache.setdefault(category, mmcif.get_category_rows(category))
        if not rows:
            return errors

        over_one = check.get("over_one")
        below = check.get("below")
        groups: Dict[
            Tuple[str, str, str, str, str],
            List[Tuple[ItemValue, float, Dict[str, str]]],
        ] = defaultdict(list)

        for row in rows:
            occ_iv = row.get(occ_item)
            occ = item_value_to_number(occ_iv) if occ_iv is not None else None
            if occ is None:
                continue
            identity = self._atom_site_occupancy_identity(row, category)
            if identity is None:
                continue
            key, display = identity
            groups[key].append((occ_iv, occ, display))

        if isinstance(over_one, dict):
            try:
                limit = float(over_one.get("limit", 1.0))
            except (TypeError, ValueError):
                limit = 1.0
            severity = self._severity_from_flag(str(over_one.get("severity", "hard")))
            template = str(
                over_one.get(
                    "message",
                    "Chain [{chain}] residue [{residue}] [{comp}] atom [{atom}] in model [{model}] has a total occupancy of [{total}].",
                )
            )
            for members in groups.values():
                total = sum(occ for _iv, occ, _display in members)
                total_rounded = round(total, 4)
                if total_rounded <= limit:
                    continue
                display = members[0][2]
                message = self._render_message_template(
                    template,
                    chain=display["chain"],
                    residue=display["residue"],
                    comp=display["comp"],
                    atom=display["atom"],
                    model=display["model"],
                    total=self._format_occupancy_number(total_rounded),
                )
                for occ_iv, _occ, _display in members:
                    errors.append(
                        ValidationError(
                            line=occ_iv.line_num,
                            item=occ_item,
                            message=message,
                            severity=severity,  # type: ignore[arg-type]
                            column=occ_iv.global_column_index,
                        )
                    )

        if isinstance(below, dict):
            try:
                limit = float(below.get("limit", 0.1))
            except (TypeError, ValueError):
                limit = 0.1
            severity = self._severity_from_flag(str(below.get("severity", "soft")))
            template = str(
                below.get(
                    "message",
                    "Chain [{chain}] residue [{residue}] [{comp}] atom [{atom}] in model [{model}] has occupancy [{occupancy}] (below 0.1).",
                )
            )
            for members in groups.values():
                group_total = sum(occ for _iv, occ, _display in members)
                for occ_iv, occ, display in members:
                    if round(occ, 4) >= limit:
                        continue
                    message = self._render_message_template(
                        template,
                        chain=display["chain"],
                        residue=display["residue"],
                        comp=display["comp"],
                        atom=display["atom"],
                        model=display["model"],
                        occupancy=self._format_occupancy_number(occ),
                        total=self._format_occupancy_number(group_total),
                    )
                    errors.append(
                        ValidationError(
                            line=occ_iv.line_num,
                            item=occ_item,
                            message=message,
                            severity=severity,  # type: ignore[arg-type]
                            column=occ_iv.global_column_index,
                        )
                    )

        return errors

    @staticmethod
    def _parse_seq_number(value: str) -> Optional[int]:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _run_sequence_model_mismatch(
        self,
        mmcif,
        rows_cache: Dict[str, List[Dict[str, ItemValue]]],
        check: dict,
    ) -> List[ValidationError]:
        """
        Compare modeled polymer residues with entity_poly_seq.

        Unmodelled sequence residues are ignored. A modeled residue whose
        comp_id disagrees with the sequence is an error (exact match). Mapping uses label_seq_id when
        present; otherwise a sliding window of residue types (for files that
        omit label_seq_id, as in some deposition uploads).
        """
        errors: List[ValidationError] = []
        severity = self._severity_from_flag(str(check.get("severity", "hard")))
        mismatch_template = str(
            check.get(
                "mismatch_message",
                "Residue ([{chain}] [{comp}] [{residue}]) does not match with the residue '[{sequence_comp}]' in sequence.",
            )
        )
        missing_template = str(
            check.get(
                "missing_message",
                "Residue ([{chain}] [{comp}] [{residue}]) is not present in the sequence.",
            )
        )

        entity_rows = rows_cache.setdefault("entity", mmcif.get_category_rows("entity"))
        entity_types: Dict[str, str] = {}
        for row in entity_rows:
            eid = self._row_item_text(row, "_entity.id")
            etype = self._row_item_text(row, "_entity.type")
            if eid:
                entity_types[eid] = etype.lower()

        poly_rows = rows_cache.setdefault("entity_poly_seq", mmcif.get_category_rows("entity_poly_seq"))
        poly_by_entity: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
        poly_mons: Dict[Tuple[str, int], Set[str]] = defaultdict(set)
        for row in poly_rows:
            eid = self._row_item_text(row, "_entity_poly_seq.entity_id")
            num = self._parse_seq_number(self._row_item_text(row, "_entity_poly_seq.num"))
            mon = self._row_item_text(row, "_entity_poly_seq.mon_id").upper()
            if not eid or num is None or not mon:
                continue
            poly_by_entity[eid].append((num, mon))
            poly_mons[(eid, num)].add(mon)
        for eid in poly_by_entity:
            poly_by_entity[eid].sort(key=lambda item: item[0])

        if not poly_mons:
            return errors

        atom_rows = rows_cache.setdefault("atom_site", mmcif.get_category_rows("atom_site"))
        residues_by_chain: Dict[str, Dict[Tuple[int, str], dict]] = defaultdict(dict)
        for row in atom_rows:
            entity_id = self._row_item_text_fallback(
                row, "atom_site", "label_entity_id", default=""
            )
            if entity_id not in poly_by_entity:
                continue
            if entity_types.get(entity_id) in {"non-polymer", "water"}:
                continue
            label_comp_iv = row.get("_atom_site.label_comp_id")
            auth_comp_iv = row.get("_atom_site.auth_comp_id")
            if label_comp_iv is not None and label_comp_iv.value not in MISSING_VALUES:
                comp_iv = label_comp_iv
                comp_item = "_atom_site.label_comp_id"
                comp = str(label_comp_iv.value).strip().upper()
            elif auth_comp_iv is not None and auth_comp_iv.value not in MISSING_VALUES:
                comp_iv = auth_comp_iv
                comp_item = "_atom_site.auth_comp_id"
                comp = str(auth_comp_iv.value).strip().upper()
            else:
                continue
            chain = self._row_item_text_fallback(
                row, "atom_site", "auth_asym_id", ["label_asym_id"], default="?"
            )
            auth_seq_text = self._row_item_text_fallback(
                row, "atom_site", "auth_seq_id", ["label_seq_id"], default=""
            )
            auth_seq = self._parse_seq_number(auth_seq_text)
            if auth_seq is None:
                continue
            ins = self._row_item_text_fallback(row, "atom_site", "pdbx_PDB_ins_code", default="")
            label_seq = self._parse_seq_number(
                self._row_item_text_fallback(row, "atom_site", "label_seq_id", default="")
            )
            atom_name = self._row_item_text_fallback(
                row, "atom_site", "label_atom_id", ["auth_atom_id"], default=""
            )
            key = (auth_seq, ins)
            current = residues_by_chain[chain].get(key)
            prefer_anchor = atom_name.upper() in {"CA", "C1'", "P"}
            if current is None:
                residues_by_chain[chain][key] = {
                    "chain": chain,
                    "entity_id": entity_id,
                    "auth_seq": auth_seq,
                    "ins": ins,
                    "comp": comp,
                    "label_seq": label_seq,
                    "anchor": comp_iv,
                    "comp_item": comp_item,
                    "has_preferred_anchor": prefer_anchor,
                }
            else:
                if current["label_seq"] is None and label_seq is not None:
                    current["label_seq"] = label_seq
                if prefer_anchor and not current["has_preferred_anchor"]:
                    current["anchor"] = comp_iv
                    current["comp_item"] = comp_item
                    current["has_preferred_anchor"] = True

        def _residue_display(res: dict) -> str:
            ins = res["ins"]
            return f"{res['auth_seq']}{ins}" if ins else str(res["auth_seq"])

        def _emit_mismatch(res: dict, sequence_comp: Optional[str]) -> None:
            residue = _residue_display(res)
            if sequence_comp:
                message = self._render_message_template(
                    mismatch_template,
                    chain=res["chain"],
                    comp=res["comp"],
                    residue=residue,
                    sequence_comp=sequence_comp,
                )
            else:
                message = self._render_message_template(
                    missing_template,
                    chain=res["chain"],
                    comp=res["comp"],
                    residue=residue,
                    sequence_comp="",
                )
            anchor = res["anchor"]
            errors.append(
                ValidationError(
                    line=anchor.line_num,
                    item=res["comp_item"],
                    message=message,
                    severity=severity,  # type: ignore[arg-type]
                    column=anchor.global_column_index,
                )
            )

        for chain, residue_map in residues_by_chain.items():
            residues = [residue_map[k] for k in sorted(residue_map)]
            if not residues:
                continue
            mapped = [res for res in residues if res["label_seq"] is not None]
            if mapped and len(mapped) == len(residues):
                for res in residues:
                    allowed = poly_mons.get((res["entity_id"], res["label_seq"]))
                    if not allowed:
                        _emit_mismatch(res, None)
                        continue
                    if res["comp"] in allowed:
                        continue
                    sequence_comp = sorted(allowed)[0]
                    _emit_mismatch(res, sequence_comp)
                continue

            # No (complete) label_seq_id: sliding window of residue types vs entity_poly_seq.
            entity_id = residues[0]["entity_id"]
            seq = [mon for _num, mon in poly_by_entity.get(entity_id, [])]
            if not seq:
                continue
            model = residues
            n, m = len(seq), len(model)
            best_s = 0
            best_score = -1
            max_s = (n - m + 1) if m <= n else 1
            for start in range(max(max_s, 1)):
                score = 0
                for j, res in enumerate(model):
                    idx = start + j
                    if idx < n and seq[idx] == res["comp"]:
                        score += 1
                if score > best_score:
                    best_score = score
                    best_s = start
            for j, res in enumerate(model):
                idx = best_s + j
                if idx >= n:
                    _emit_mismatch(res, None)
                    continue
                if seq[idx] == res["comp"]:
                    continue
                _emit_mismatch(res, seq[idx])

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

        for check in checks:
            if not isinstance(check, dict):
                continue
            if str(check.get("kind", "")).strip().lower() != "atom_site_occupancy":
                continue
            errors.extend(self._run_atom_site_occupancy(mmcif, rows_cache, check))

        for check in checks:
            if not isinstance(check, dict):
                continue
            if str(check.get("kind", "")).strip().lower() != "sequence_model_mismatch":
                continue
            errors.extend(self._run_sequence_model_mismatch(mmcif, rows_cache, check))

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
