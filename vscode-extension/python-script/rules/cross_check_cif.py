"""
Load validator cross-check rules from rules/data/cross_checks.cif.

The CIF is the rule store. load_rule_file() rebuilds the dict shape the
family runners consume.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence

from cif_parser import MmCIFParser

RULE_FILENAMES = (
    "cross_checks_pairwise_comparison.json",
    "cross_checks_pairwise_date_order.json",
    "cross_checks_uniqueness.json",
    "cross_checks_linked_presence_and_comparison.json",
    "cross_checks_conditional_required.json",
    "cross_checks_conditional_regex.json",
    "cross_checks_conditional_enumeration.json",
    "cross_checks_conditional_category_item.json",
    "cross_checks_dictionary_enum.json",
    "cross_checks_cross_reference_full.json",
    "cross_checks_required_if_any_present.json",
    "cross_checks_procedural_validators.json",
)

COLUMNS = {
    "validator_rule_pairwise": (
        "id", "source_category", "source_item", "target_category", "target_item",
        "message", "operator", "severity", "extra",
    ),
    "validator_rule_date_order": (
        "id", "category", "left_item", "right_item", "op", "severity", "message",
    ),
    "validator_rule_uniqueness": ("id", "category", "severity", "message"),
    "validator_rule_uniqueness_key": ("rule_id", "ordinal", "item"),
    "validator_rule_linked": (
        "id", "source_category", "source_item", "target_category", "target_item",
        "cross", "cross2", "operator", "fallback", "break_flag", "warning",
        "absolute", "text",
    ),
    "validator_rule_conditional_required": (
        "id", "category", "error", "error_text", "warning_text",
    ),
    "validator_rule_conditional_required_item": ("rule_id", "ordinal", "item"),
    "validator_rule_condition": (
        "owner", "rule_id", "branch_ordinal", "item", "ordinal", "value", "value_form",
    ),
    "validator_rule_skip_category": ("rule_id", "ordinal", "category"),
    "validator_rule_conditional_regex": (
        "id", "category", "item", "regex", "error", "error_text",
        "condition_item", "condition_value",
    ),
    "validator_rule_conditional_enum": ("id", "category", "driver_item", "affected_item"),
    "validator_rule_conditional_enum_value": (
        "rule_id", "branch_ordinal", "driver_value", "error_text", "ordinal", "allowed_value",
    ),
    "validator_rule_conditional_category_item": (
        "id", "category", "item", "regex", "error", "error_text",
        "condition_category", "condition_item", "condition_value",
    ),
    "validator_rule_dictionary_enum": ("id", "category", "source_item", "cross_item"),
    "validator_rule_cross_reference": (
        "id", "category", "item", "cross_category", "cross_item", "expt", "code",
        "subtype", "type",
    ),
    "validator_rule_cross_reference_expt": ("rule_id", "ordinal", "mode"),
    "validator_rule_make_mandatory": ("id", "scope", "subtype", "category"),
    "validator_rule_make_mandatory_item": ("rule_id", "role", "ordinal", "item"),
    "validator_rule_one_of": ("id", "category"),
    "validator_rule_one_of_item": ("rule_id", "ordinal", "item"),
    "validator_rule_procedural": (
        "id", "kind", "category", "item", "driver_item", "skip_if_empty", "severity",
        "message", "mismatch_message", "missing_message", "source_category", "source_item",
        "source_key", "target_category", "target_item", "target_key",
    ),
    "validator_rule_procedural_branch": (
        "rule_id", "ordinal", "driver_value", "protocol", "requires", "predicate",
        "substring", "severity", "message",
    ),
    "validator_rule_procedural_format": ("rule_id", "branch_ordinal", "ordinal", "format"),
    "validator_rule_procedural_allowed_value": ("rule_id", "branch_ordinal", "ordinal", "value"),
    "validator_rule_procedural_empty_list": ("rule_id", "ordinal", "protocol", "severity", "message"),
    "validator_rule_procedural_limit": ("rule_id", "role", "limit", "severity", "message"),
}

_PROCEDURAL_KINDS = {
    "wavelength_protocol_consistency",
    "accession_format_rule",
    "conditional_accession_format_rule",
    "conditional_value_rule",
    "atom_site_occupancy",
    "sequence_model_mismatch",
    "sequence_predicate_warning",
}

_MISSING = {".", "?"}

_cache: Dict[str, tuple] = {}


class CrossCheckRulesError(Exception):
    """The cross-check CIF is missing, incomplete, or internally inconsistent."""


def default_cif_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "cross_checks.cif"


def load_rule_file(filename: str, path: Optional[Path] = None) -> dict:
    """Return the rule document for one former JSON filename."""
    if filename not in RULE_FILENAMES:
        raise CrossCheckRulesError(f"Unknown cross-check rule file: {filename}")
    documents = load_rule_documents(path)
    try:
        return documents[filename]
    except KeyError as exc:
        cif_path = path or default_cif_path()
        raise CrossCheckRulesError(
            f"{cif_path}: missing rules for {filename}"
        ) from exc


def load_rule_documents(path: Optional[Path] = None) -> Dict[str, dict]:
    """Parse cross_checks.cif and rebuild every rule document."""
    cif_path = Path(path or default_cif_path()).resolve()
    if not cif_path.is_file():
        raise CrossCheckRulesError(f"Cross-check rules file not found: {cif_path}")
    stamp = cif_path.stat().st_mtime_ns
    cached = _cache.get(str(cif_path))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    documents = _documents_from_tables(_read_tables(cif_path), cif_path)
    _cache[str(cif_path)] = (stamp, documents)
    return documents


def clear_rules_cache() -> None:
    _cache.clear()


def _read_tables(cif_path: Path) -> Dict[str, List[dict]]:
    parser = MmCIFParser(cif_path)
    parser.parse()
    tables: Dict[str, List[dict]] = {}
    for category, columns in COLUMNS.items():
        if category not in parser.categories:
            raise CrossCheckRulesError(f"{cif_path}: missing category _{category}")
        prefix = f"_{category}."
        present = {}
        for item_name, values in parser.items.items():
            if item_name.startswith(prefix):
                present[item_name[len(prefix):]] = values
        expected = set(columns)
        found = set(present)
        if found != expected:
            missing = sorted(expected - found)
            extra = sorted(found - expected)
            raise CrossCheckRulesError(
                f"{cif_path}: category _{category} columns mismatch; "
                f"missing={missing or '-'} extra={extra or '-'}"
            )
        lengths = {name: len(values) for name, values in present.items()}
        if len(set(lengths.values())) != 1:
            raise CrossCheckRulesError(
                f"{cif_path}: category _{category} has uneven column lengths: {lengths}"
            )
        row_count = next(iter(lengths.values()))
        if row_count == 0:
            raise CrossCheckRulesError(f"{cif_path}: category _{category} has no rows")
        rows = []
        for index in range(row_count):
            rows.append({name: present[name][index].value for name in columns})
        tables[category] = rows
    return tables


def _documents_from_tables(tables: Dict[str, List[dict]], cif_path: Path) -> Dict[str, dict]:
    ctx = _Index(tables, cif_path)
    return {
        "cross_checks_pairwise_comparison.json": ctx.pairwise(),
        "cross_checks_pairwise_date_order.json": ctx.date_order(),
        "cross_checks_uniqueness.json": ctx.uniqueness(),
        "cross_checks_linked_presence_and_comparison.json": ctx.linked(),
        "cross_checks_conditional_required.json": ctx.conditional_required(),
        "cross_checks_conditional_regex.json": ctx.conditional_regex(),
        "cross_checks_conditional_enumeration.json": ctx.conditional_enum(),
        "cross_checks_conditional_category_item.json": ctx.conditional_category_item(),
        "cross_checks_dictionary_enum.json": ctx.dictionary_enum(),
        "cross_checks_cross_reference_full.json": ctx.cross_reference(),
        "cross_checks_required_if_any_present.json": ctx.required_if_any(),
        "cross_checks_procedural_validators.json": ctx.procedural(),
    }


class _Index:
    def __init__(self, tables: Dict[str, List[dict]], cif_path: Path):
        self.tables = tables
        self.path = cif_path
        self._seen_ids = {}
        for category, id_column in (
            ("validator_rule_pairwise", "id"),
            ("validator_rule_date_order", "id"),
            ("validator_rule_uniqueness", "id"),
            ("validator_rule_linked", "id"),
            ("validator_rule_conditional_required", "id"),
            ("validator_rule_conditional_regex", "id"),
            ("validator_rule_conditional_enum", "id"),
            ("validator_rule_conditional_category_item", "id"),
            ("validator_rule_dictionary_enum", "id"),
            ("validator_rule_cross_reference", "id"),
            ("validator_rule_make_mandatory", "id"),
            ("validator_rule_one_of", "id"),
            ("validator_rule_procedural", "id"),
        ):
            ids = [row[id_column] for row in tables[category]]
            if len(ids) != len(set(ids)):
                raise CrossCheckRulesError(f"{cif_path}: duplicate id in _{category}")
            self._seen_ids[category] = set(ids)

    def _require_parent(self, child_category: str, parent_category: str, rule_id: str) -> None:
        if rule_id not in self._seen_ids[parent_category]:
            raise CrossCheckRulesError(
                f"{self.path}: _{child_category} rule_id {rule_id} "
                f"is not in _{parent_category}"
            )

    def _ordinal_rows(self, category: str, rows: List[dict], group_label: str) -> List[dict]:
        ordinals = []
        for row in rows:
            try:
                ordinals.append(int(row["ordinal"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise CrossCheckRulesError(
                    f"{self.path}: _{category} ordinal is not an integer for {group_label}"
                ) from exc
        if sorted(ordinals) != list(range(1, len(rows) + 1)):
            raise CrossCheckRulesError(
                f"{self.path}: _{category} ordinals for {group_label} must be 1..{len(rows)}"
            )
        return sorted(rows, key=lambda row: int(row["ordinal"]))

    def _group(self, category: str, columns: Sequence[str]) -> Dict[tuple, List[dict]]:
        grouped: Dict[tuple, List[dict]] = {}
        for row in self.tables[category]:
            grouped.setdefault(tuple(row[column] for column in columns), []).append(row)
        return grouped

    def pairwise(self) -> dict:
        grouped: Dict[str, List[list]] = {}
        for row in self.tables["validator_rule_pairwise"]:
            key = f"{row['source_category']}.{row['source_item']}"
            extra = row["extra"]
            array = [
                row["target_category"],
                row["target_item"],
                row["message"],
                row["operator"],
                row["severity"],
                "" if extra == "." else extra,
            ]
            grouped.setdefault(key, []).append(array)
        return grouped

    def date_order(self) -> dict:
        rules = []
        for row in self.tables["validator_rule_date_order"]:
            rules.append({
                "category": row["category"],
                "left_item": row["left_item"],
                "right_item": row["right_item"],
                "op": row["op"],
                "severity": row["severity"],
                "message": row["message"],
            })
        return {"date_order_rules": rules}

    def uniqueness(self) -> dict:
        keys = self._group("validator_rule_uniqueness_key", ("rule_id",))
        rules = []
        for row in self.tables["validator_rule_uniqueness"]:
            children = keys.get((row["id"],), [])
            if not children:
                raise CrossCheckRulesError(
                    f"{self.path}: uniqueness rule {row['id']} has no key items"
                )
            for child in children:
                self._require_parent(
                    "validator_rule_uniqueness_key", "validator_rule_uniqueness", child["rule_id"]
                )
            ordered = self._ordinal_rows(
                "validator_rule_uniqueness_key", children, row["id"]
            )
            rules.append({
                "category": row["category"],
                "key_items": [child["item"] for child in ordered],
                "severity": row["severity"],
                "message": row["message"],
            })
        self._reject_orphan_keys("validator_rule_uniqueness_key", keys)
        return {"uniqueness_rules": rules}

    def linked(self) -> dict:
        grouped: Dict[str, List[dict]] = {}
        order = (
            "absolute", "break", "cat", "cross", "cross2", "fallback", "item",
            "operator", "text", "warning",
        )
        for row in self.tables["validator_rule_linked"]:
            values = {
                "absolute": _optional_bool(row["absolute"], self.path, "validator_rule_linked.absolute"),
                "break": _optional_bool(row["break_flag"], self.path, "validator_rule_linked.break_flag"),
                "cat": row["target_category"],
                "cross": row["cross"],
                "cross2": None if row["cross2"] == "." else row["cross2"],
                "fallback": None if row["fallback"] == "." else row["fallback"],
                "item": row["target_item"],
                "operator": row["operator"],
                "text": row["text"],
                "warning": _optional_bool(row["warning"], self.path, "validator_rule_linked.warning"),
            }
            rule = {key: values[key] for key in order if values[key] is not None}
            grouped.setdefault(f"{row['source_category']}.{row['source_item']}", []).append(rule)
        return grouped

    def conditional_required(self) -> dict:
        items = self._group("validator_rule_conditional_required_item", ("rule_id",))
        skips = self._group("validator_rule_skip_category", ("rule_id",))
        conditions = self._group("validator_rule_condition", ("owner", "rule_id", "branch_ordinal"))
        grouped: Dict[str, List[dict]] = {}
        for row in self.tables["validator_rule_conditional_required"]:
            rule_id = row["id"]
            item_rows = items.get((rule_id,), [])
            if not item_rows:
                raise CrossCheckRulesError(
                    f"{self.path}: conditional required rule {rule_id} has no items"
                )
            condition_rows = conditions.get(("conditional_required", rule_id, "1"), [])
            if not condition_rows:
                raise CrossCheckRulesError(
                    f"{self.path}: conditional required rule {rule_id} has no conditions"
                )
            rule = {
                "conditions": self._condition_map(
                    condition_rows, "list", f"conditional_required {rule_id}"
                ),
            }
            skip_rows = skips.get((rule_id,), [])
            if skip_rows:
                ordered_skips = self._ordinal_rows(
                    "validator_rule_skip_category", skip_rows, rule_id
                )
                rule["skip_if_any_category_present"] = [child["category"] for child in ordered_skips]
            rule["error"] = _required_bool(row["error"], self.path, "validator_rule_conditional_required.error")
            if row["error_text"] != ".":
                rule["error_text"] = row["error_text"]
            if row["warning_text"] != ".":
                rule["warning_text"] = row["warning_text"]
            ordered_items = self._ordinal_rows(
                "validator_rule_conditional_required_item", item_rows, rule_id
            )
            rule["item"] = [child["item"] for child in ordered_items]
            grouped.setdefault(row["category"], []).append(rule)
        self._reject_orphan_keys("validator_rule_conditional_required_item", items)
        self._reject_orphan_keys("validator_rule_skip_category", skips)
        return grouped

    def conditional_regex(self) -> dict:
        grouped: Dict[str, List[dict]] = {}
        for row in self.tables["validator_rule_conditional_regex"]:
            grouped.setdefault(row["category"], []).append({
                "condition": {"item": row["condition_item"], "value": row["condition_value"]},
                "error": _required_bool(row["error"], self.path, "validator_rule_conditional_regex.error"),
                "error_text": row["error_text"],
                "item": row["item"],
                "regex": row["regex"],
            })
        return grouped

    def conditional_enum(self) -> dict:
        values = self._group(
            "validator_rule_conditional_enum_value", ("rule_id", "branch_ordinal")
        )
        by_rule: Dict[str, List[tuple]] = {}
        for (rule_id, branch_ordinal), rows in values.items():
            self._require_parent(
                "validator_rule_conditional_enum_value", "validator_rule_conditional_enum", rule_id
            )
            by_rule.setdefault(rule_id, []).append((int(branch_ordinal), rows))
        grouped: Dict[str, List[dict]] = {}
        for row in self.tables["validator_rule_conditional_enum"]:
            branches = []
            for branch_ordinal, branch_rows in sorted(by_rule.get(row["id"], [])):
                ordered = self._ordinal_rows(
                    "validator_rule_conditional_enum_value",
                    branch_rows,
                    f"{row['id']} branch {branch_ordinal}",
                )
                driver_values = {child["driver_value"] for child in ordered}
                texts = {child["error_text"] for child in ordered}
                if len(driver_values) != 1 or len(texts) != 1:
                    raise CrossCheckRulesError(
                        f"{self.path}: enum branch {row['id']}:{branch_ordinal} "
                        "mixes driver values or messages"
                    )
                branches.append({
                    "error_text": ordered[0]["error_text"],
                    "validate": [child["allowed_value"] for child in ordered],
                    "value": ordered[0]["driver_value"],
                })
            if not branches:
                raise CrossCheckRulesError(f"{self.path}: enum rule {row['id']} has no values")
            grouped.setdefault(row["category"], []).append({
                "affected_item": row["affected_item"],
                "conditions": branches,
                "item": row["driver_item"],
            })
        return grouped

    def conditional_category_item(self) -> dict:
        grouped: Dict[str, List[dict]] = {}
        for row in self.tables["validator_rule_conditional_category_item"]:
            grouped.setdefault(row["category"], []).append({
                "condition": {
                    "category": row["condition_category"],
                    "item": row["condition_item"],
                    "value": row["condition_value"],
                },
                "error": _required_bool(
                    row["error"], self.path, "validator_rule_conditional_category_item.error"
                ),
                "error_text": row["error_text"],
                "item": row["item"],
                "regex": row["regex"],
            })
        return grouped

    def dictionary_enum(self) -> dict:
        grouped: Dict[str, dict] = {}
        for row in self.tables["validator_rule_dictionary_enum"]:
            grouped.setdefault(row["category"], {})[row["source_item"]] = row["cross_item"]
        return grouped

    def cross_reference(self) -> dict:
        modes = self._group("validator_rule_cross_reference_expt", ("rule_id",))
        rules = []
        used = set()
        for row in self.tables["validator_rule_cross_reference"]:
            rule = {"category": row["category"]}
            if row["code"] != ".":
                rule["code"] = row["code"]
            rule["cross_category"] = row["cross_category"]
            rule["cross_item"] = row["cross_item"]
            if row["expt"] == ".":
                mode_rows = modes.get((row["id"],), [])
                if not mode_rows:
                    raise CrossCheckRulesError(
                        f"{self.path}: cross-reference rule {row['id']} has no experiment modes"
                    )
                ordered = self._ordinal_rows(
                    "validator_rule_cross_reference_expt", mode_rows, row["id"]
                )
                rule["expt"] = [child["mode"] for child in ordered]
                used.add(row["id"])
            else:
                rule["expt"] = row["expt"]
                if (row["id"],) in modes:
                    raise CrossCheckRulesError(
                        f"{self.path}: cross-reference rule {row['id']} has both "
                        "an expt token and experiment-mode rows"
                    )
            rule["item"] = row["item"]
            rule["subtype"] = row["subtype"]
            rule["type"] = row["type"]
            rules.append(rule)
        for (rule_id,), _rows in modes.items():
            self._require_parent(
                "validator_rule_cross_reference_expt", "validator_rule_cross_reference", rule_id
            )
            if rule_id not in used:
                raise CrossCheckRulesError(
                    f"{self.path}: unused experiment modes for cross-reference rule {rule_id}"
                )
        return {"cross_reference_full": rules}

    def required_if_any(self) -> dict:
        items = self._group("validator_rule_make_mandatory_item", ("rule_id", "role"))
        make_mandatory = {}
        subtypes: Dict[str, dict] = {}
        for row in self.tables["validator_rule_make_mandatory"]:
            spec = {}
            exclude_rows = items.get((row["id"], "exclude"), [])
            check_rows = items.get((row["id"], "to_check"), [])
            if exclude_rows:
                ordered = self._ordinal_rows(
                    "validator_rule_make_mandatory_item", exclude_rows, f"{row['id']} exclude"
                )
                spec["exclude"] = [child["item"] for child in ordered]
            if not check_rows:
                raise CrossCheckRulesError(
                    f"{self.path}: make-mandatory rule {row['id']} has no to_check items"
                )
            ordered_checks = self._ordinal_rows(
                "validator_rule_make_mandatory_item", check_rows, f"{row['id']} to_check"
            )
            spec["to_check"] = [child["item"] for child in ordered_checks]
            if row["scope"] == "makeMandatory":
                if row["subtype"] != ".":
                    raise CrossCheckRulesError(
                        f"{self.path}: makeMandatory rule {row['id']} must not set a subtype"
                    )
                make_mandatory[row["category"]] = spec
            elif row["scope"] == "makeMandatorySubtypes":
                if row["subtype"] == ".":
                    raise CrossCheckRulesError(
                        f"{self.path}: makeMandatorySubtypes rule {row['id']} needs a subtype"
                    )
                subtypes.setdefault(row["subtype"], {})[row["category"]] = spec
            else:
                raise CrossCheckRulesError(
                    f"{self.path}: unknown make-mandatory scope {row['scope']}"
                )
        one_items = self._group("validator_rule_one_of_item", ("rule_id",))
        one_of = {}
        for row in self.tables["validator_rule_one_of"]:
            children = one_items.get((row["id"],), [])
            if not children:
                raise CrossCheckRulesError(f"{self.path}: one-of rule {row['id']} has no items")
            ordered = self._ordinal_rows("validator_rule_one_of_item", children, row["id"])
            one_of[row["category"]] = [child["item"] for child in ordered]
        self._reject_role_orphans(items)
        self._reject_orphan_keys("validator_rule_one_of_item", one_items)
        return {
            "makeMandatory": make_mandatory,
            "makeMandatorySubtypes": subtypes,
            "oneOfFollowing": one_of,
        }

    def procedural(self) -> dict:
        branches = self._group("validator_rule_procedural_branch", ("rule_id",))
        formats = self._group("validator_rule_procedural_format", ("rule_id", "branch_ordinal"))
        allowed = self._group(
            "validator_rule_procedural_allowed_value", ("rule_id", "branch_ordinal")
        )
        empty_lists = self._group("validator_rule_procedural_empty_list", ("rule_id",))
        limits = self._group("validator_rule_procedural_limit", ("rule_id", "role"))
        conditions = self._group(
            "validator_rule_condition", ("owner", "rule_id", "branch_ordinal")
        )
        checks = []
        for row in self.tables["validator_rule_procedural"]:
            kind = row["kind"]
            if kind not in _PROCEDURAL_KINDS:
                raise CrossCheckRulesError(f"{self.path}: unknown procedural kind {kind}")
            rule_branches = self._ordinal_rows(
                "validator_rule_procedural_branch",
                branches.get((row["id"],), []),
                row["id"],
            ) if (row["id"],) in branches else []
            checks.append(self._one_procedural(
                row, rule_branches, formats, allowed, empty_lists, limits, conditions
            ))
        self._reject_orphan_keys("validator_rule_procedural_branch", branches)
        self._reject_pair_orphans("validator_rule_procedural_format", formats)
        self._reject_pair_orphans("validator_rule_procedural_allowed_value", allowed)
        self._reject_orphan_keys("validator_rule_procedural_empty_list", empty_lists)
        self._reject_role_orphans(limits, parent="validator_rule_procedural")
        for (owner, rule_id, _branch), _rows in conditions.items():
            if owner == "procedural":
                self._require_parent("validator_rule_condition", "validator_rule_procedural", rule_id)
            elif owner == "conditional_required":
                self._require_parent(
                    "validator_rule_condition", "validator_rule_conditional_required", rule_id
                )
            else:
                raise CrossCheckRulesError(f"{self.path}: unknown condition owner {owner}")
        return {"procedural_checks": checks}

    def _one_procedural(self, row, branches, formats, allowed, empty_lists, limits, conditions):
        kind = row["kind"]
        rule_id = row["id"]
        if kind == "wavelength_protocol_consistency":
            built = []
            for branch in branches:
                built.append({
                    "protocol": _present(branch["protocol"], "protocol"),
                    "requires": _present(branch["requires"], "requires"),
                    "severity": branch["severity"],
                    "message": branch["message"],
                })
            empty_rows = empty_lists.get((rule_id,), [])
            if not empty_rows:
                raise CrossCheckRulesError(
                    f"{self.path}: wavelength rule {rule_id} has no empty-list protocols"
                )
            ordered_empty = self._ordinal_rows(
                "validator_rule_procedural_empty_list", empty_rows, rule_id
            )
            severities = {child["severity"] for child in ordered_empty}
            messages = {child["message"] for child in ordered_empty}
            if len(severities) != 1 or len(messages) != 1:
                raise CrossCheckRulesError(
                    f"{self.path}: empty-list rows for {rule_id} disagree on severity or message"
                )
            return {
                "kind": kind,
                "id": rule_id,
                "source": {
                    "category": _present(row["source_category"], "source_category"),
                    "item": _present(row["source_item"], "source_item"),
                    "key": _present(row["source_key"], "source_key"),
                },
                "target": {
                    "category": _present(row["target_category"], "target_category"),
                    "item": _present(row["target_item"], "target_item"),
                    "key": _present(row["target_key"], "target_key"),
                },
                "rules": built,
                "empty_list_when_protocol_any_of": {
                    "protocols": [child["protocol"] for child in ordered_empty],
                    "severity": ordered_empty[0]["severity"],
                    "message": ordered_empty[0]["message"],
                },
            }
        if kind in ("accession_format_rule", "conditional_accession_format_rule", "conditional_value_rule", "sequence_predicate_warning"):
            built_rules = []
            for branch in branches:
                branch_ordinal = branch["ordinal"]
                if kind == "accession_format_rule":
                    built_rules.append({
                        "driver_value": _present(branch["driver_value"], "driver_value"),
                        "accepted_formats": self._formats(formats, rule_id, branch_ordinal),
                        "severity": branch["severity"],
                        "message": branch["message"],
                    })
                elif kind == "conditional_accession_format_rule":
                    built_rules.append({
                        "conditions": self._branch_conditions(conditions, rule_id, branch_ordinal),
                        "accepted_formats": self._formats(formats, rule_id, branch_ordinal),
                        "severity": branch["severity"],
                        "message": branch["message"],
                    })
                elif kind == "conditional_value_rule":
                    built_rules.append({
                        "conditions": self._branch_conditions(conditions, rule_id, branch_ordinal),
                        "allowed_values": self._allowed(allowed, rule_id, branch_ordinal),
                        "severity": branch["severity"],
                        "message": branch["message"],
                    })
                else:
                    predicate = {
                        "predicate": _present(branch["predicate"], "predicate"),
                    }
                    if branch["substring"] != ".":
                        predicate["substring"] = branch["substring"]
                    predicate["severity"] = branch["severity"]
                    predicate["message"] = branch["message"]
                    built_rules.append(predicate)
            if kind == "sequence_predicate_warning":
                return {
                    "kind": kind,
                    "id": rule_id,
                    "category": _present(row["category"], "category"),
                    "item": _present(row["item"], "item"),
                    "rules": built_rules,
                }
            document = {
                "kind": kind,
                "id": rule_id,
                "category": _present(row["category"], "category"),
                "item": _present(row["item"], "item"),
            }
            if kind == "accession_format_rule":
                document["driver_item"] = _present(row["driver_item"], "driver_item")
                if row["skip_if_empty"] != ".":
                    document["skip_if_empty"] = _required_bool(
                        row["skip_if_empty"], self.path, "validator_rule_procedural.skip_if_empty"
                    )
            document["rules"] = built_rules
            return document
        if kind == "atom_site_occupancy":
            return {
                "kind": kind,
                "id": rule_id,
                "category": _present(row["category"], "category"),
                "item": _present(row["item"], "item"),
                "over_one": self._limit(limits, rule_id, "over_one"),
                "below": self._limit(limits, rule_id, "below"),
            }
        return {
            "kind": kind,
            "id": rule_id,
            "severity": _present(row["severity"], "severity"),
            "mismatch_message": _present(row["mismatch_message"], "mismatch_message"),
            "missing_message": _present(row["missing_message"], "missing_message"),
        }

    def _formats(self, formats, rule_id: str, branch_ordinal: str) -> List[str]:
        rows = formats.get((rule_id, branch_ordinal), [])
        if not rows:
            raise CrossCheckRulesError(
                f"{self.path}: procedural rule {rule_id} branch {branch_ordinal} has no formats"
            )
        ordered = self._ordinal_rows(
            "validator_rule_procedural_format", rows, f"{rule_id}:{branch_ordinal}"
        )
        return [row["format"] for row in ordered]

    def _allowed(self, allowed, rule_id: str, branch_ordinal: str) -> List[str]:
        rows = allowed.get((rule_id, branch_ordinal), [])
        if not rows:
            raise CrossCheckRulesError(
                f"{self.path}: procedural rule {rule_id} branch {branch_ordinal} has no allowed values"
            )
        ordered = self._ordinal_rows(
            "validator_rule_procedural_allowed_value", rows, f"{rule_id}:{branch_ordinal}"
        )
        return [row["value"] for row in ordered]

    def _branch_conditions(self, conditions, rule_id: str, branch_ordinal: str) -> dict:
        rows = conditions.get(("procedural", rule_id, branch_ordinal), [])
        if not rows:
            raise CrossCheckRulesError(
                f"{self.path}: procedural rule {rule_id} branch {branch_ordinal} has no conditions"
            )
        return self._condition_map(rows, "scalar", f"{rule_id}:{branch_ordinal}")

    def _limit(self, limits, rule_id: str, role: str) -> dict:
        rows = limits.get((rule_id, role), [])
        if len(rows) != 1:
            raise CrossCheckRulesError(
                f"{self.path}: procedural rule {rule_id} needs one {role} limit"
            )
        row = rows[0]
        try:
            limit = float(row["limit"])
        except ValueError as exc:
            raise CrossCheckRulesError(
                f"{self.path}: procedural limit {row['limit']} is not a number"
            ) from exc
        return {"limit": limit, "severity": row["severity"], "message": row["message"]}

    def _condition_map(self, rows: List[dict], form: str, label: str) -> dict:
        grouped: Dict[str, List[dict]] = {}
        item_order = []
        for row in rows:
            if row["item"] not in grouped:
                item_order.append(row["item"])
                grouped[row["item"]] = []
            grouped[row["item"]].append(row)
        result = {}
        for item in item_order:
            ordered = self._ordinal_rows("validator_rule_condition", grouped[item], f"{label}.{item}")
            forms = {child["value_form"] for child in ordered}
            if forms != {form}:
                raise CrossCheckRulesError(
                    f"{self.path}: condition {label}.{item} must use value_form {form}"
                )
            values = [child["value"] for child in ordered]
            if form == "scalar":
                if len(values) != 1:
                    raise CrossCheckRulesError(
                        f"{self.path}: scalar condition {label}.{item} must have one value"
                    )
                result[item] = values[0]
            else:
                result[item] = values
        return result

    def _reject_orphan_keys(self, category: str, grouped: Dict[tuple, List[dict]]) -> None:
        parent = _parent_category(category)
        for key in grouped:
            self._require_parent(category, parent, key[0])

    def _reject_role_orphans(self, grouped: Dict[tuple, List[dict]], parent: str = "validator_rule_make_mandatory") -> None:
        child = (
            "validator_rule_procedural_limit"
            if parent == "validator_rule_procedural"
            else "validator_rule_make_mandatory_item"
        )
        for key in grouped:
            self._require_parent(child, parent, key[0])

    def _reject_pair_orphans(self, category: str, grouped: Dict[tuple, List[dict]]) -> None:
        for key in grouped:
            self._require_parent(category, "validator_rule_procedural", key[0])


def _parent_category(child: str) -> str:
    return {
        "validator_rule_uniqueness_key": "validator_rule_uniqueness",
        "validator_rule_conditional_required_item": "validator_rule_conditional_required",
        "validator_rule_skip_category": "validator_rule_conditional_required",
        "validator_rule_procedural_branch": "validator_rule_procedural",
        "validator_rule_procedural_empty_list": "validator_rule_procedural",
        "validator_rule_one_of_item": "validator_rule_one_of",
    }[child]


def _present(value: str, label: str) -> str:
    if value in _MISSING:
        raise CrossCheckRulesError(f"Missing required cross-check value for {label}")
    return value


def _optional_bool(value: str, path: Path, label: str):
    if value == ".":
        return None
    return _required_bool(value, path, label)


def _required_bool(value: str, path: Path, label: str) -> bool:
    if value == "yes":
        return True
    if value == "no":
        return False
    raise CrossCheckRulesError(f"{path}: {label} must be yes or no, got {value!r}")
