import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = REPO_ROOT / "vscode-extension" / "python-script" / "rules" / "data"
OUT = REPO_ROOT / "docs" / "cross_check_rules_catalog.txt"


def load(name: str):
    path = BASE / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    lines = []
    idx = 1

    def add(family: str, key: str, detail: str) -> None:
        nonlocal idx
        lines.append(f"{idx}. [{family}] {key} :: {detail}")
        idx += 1

    pairwise = load("cross_checks_pairwise_comparison.json")
    for source_ref, tests in pairwise.items():
        for test in tests:
            add(
                "pairwise_comparison",
                source_ref,
                f"target={test[0]}.{test[1]}; op={test[3]}; severity={test[4]}; msg={test[2]}",
            )

    linked = load("cross_checks_linked_presence_and_comparison.json")
    for source_ref, rules in linked.items():
        for rule in rules:
            add(
                "linked_presence_and_comparison",
                source_ref,
                (
                    f"target={rule.get('cat')}.{rule.get('item')}; "
                    f"op={rule.get('operator')}; "
                    f"cross={rule.get('cross')}->{rule.get('cross2', rule.get('cross'))}; "
                    f"warning={bool(rule.get('warning'))}; "
                    f"break={bool(rule.get('break'))}; "
                    f"text={rule.get('text', '')}"
                ),
            )

    conditional_required = load("cross_checks_conditional_required.json")
    for category, rules in conditional_required.items():
        for rule in rules:
            add(
                "conditional_required",
                category,
                (
                    f"conditions={rule.get('conditions')}; "
                    f"required={rule.get('item')}; "
                    f"error={rule.get('error', True)}; "
                    f"text={rule.get('error_text') or rule.get('warning_text') or ''}"
                ),
            )

    conditional_regex = load("cross_checks_conditional_regex.json")
    for category, rules in conditional_regex.items():
        for rule in rules:
            add(
                "conditional_regex",
                category,
                (
                    f"if={rule.get('condition')}; "
                    f"item={rule.get('item')}; "
                    f"regex={rule.get('regex')}; "
                    f"error={rule.get('error', True)}; "
                    f"text={rule.get('error_text', '')}"
                ),
            )

    conditional_enum = load("cross_checks_conditional_enumeration.json")
    for category, rules in conditional_enum.items():
        for rule in rules:
            add(
                "conditional_enumeration",
                category,
                (
                    f"driver={rule.get('item')}; "
                    f"affected={rule.get('affected_item')}; "
                    f"conditions={rule.get('conditions')}"
                ),
            )

    conditional_category_item = load("cross_checks_conditional_category_item.json")
    for category, rules in conditional_category_item.items():
        for rule in rules:
            add(
                "conditional_category_item",
                category,
                (
                    f"if={rule.get('condition')}; "
                    f"item={rule.get('item')}; "
                    f"regex={rule.get('regex')}; "
                    f"error={rule.get('error', True)}; "
                    f"text={rule.get('error_text', '')}"
                ),
            )

    dictionary_enum = load("cross_checks_dictionary_enum.json")
    for category, item_map in dictionary_enum.items():
        for source, cross in item_map.items():
            add(
                "dictionary_enum",
                category,
                f"{source} compatible with {cross} via dictionary enumeration_details",
            )

    cross_reference = load("cross_checks_cross_reference_full.json")
    for rule in cross_reference.get("cross_reference_full", []):
        add(
            "cross_reference_full",
            str(rule.get("category", "?")),
            (
                f"item={rule.get('item')}; "
                f"cross={rule.get('cross_category')}.{rule.get('cross_item')}; "
                f"expt={rule.get('expt')}; "
                f"code={rule.get('code', '')}; "
                f"subtype={rule.get('subtype')}"
            ),
        )

    date_order = load("cross_checks_pairwise_date_order.json")
    for rule in date_order.get("date_order_rules", []):
        add(
            "pairwise_date_order",
            str(rule.get("category", "?")),
            (
                f"{rule.get('left_item')} {rule.get('op')} {rule.get('right_item')}; "
                f"severity={rule.get('severity')}; "
                f"msg={rule.get('message')}"
            ),
        )

    uniqueness = load("cross_checks_uniqueness.json")
    for rule in uniqueness.get("uniqueness_rules", []):
        add(
            "uniqueness",
            str(rule.get("category", "?")),
            (
                f"keys={rule.get('key_items')}; "
                f"severity={rule.get('severity')}; "
                f"msg={rule.get('message')}"
            ),
        )

    required_if_any = load("cross_checks_required_if_any_present.json")
    for category, spec in required_if_any.get("makeMandatory", {}).items():
        add(
            "required_if_any_present.makeMandatory",
            category,
            f"to_check={spec.get('to_check')}; exclude={spec.get('exclude')}",
        )
    for subtype, categories in required_if_any.get("makeMandatorySubtypes", {}).items():
        for category, spec in categories.items():
            add(
                "required_if_any_present.makeMandatorySubtypes",
                f"{subtype}:{category}",
                f"to_check={spec.get('to_check')}; exclude={spec.get('exclude')}",
            )
    for category, items in required_if_any.get("oneOfFollowing", {}).items():
        add(
            "required_if_any_present.oneOfFollowing",
            category,
            f"items={items}",
        )

    procedural = load("cross_checks_procedural_validators.json")
    for check in procedural.get("procedural_checks", []):
        kind = check.get("kind", "?")
        if kind == "wavelength_protocol_consistency":
            source = f"{check.get('source', {}).get('category')}.{check.get('source', {}).get('item')}"
            target = f"{check.get('target', {}).get('category')}.{check.get('target', {}).get('item')}"
            add(
                "procedural.wavelength_protocol_consistency",
                source,
                f"target={target}; rules={check.get('rules')}; empty_list_rule={check.get('empty_list_when_protocol_any_of')}",
            )
        elif kind in (
            "accession_format_rule",
            "conditional_accession_format_rule",
            "conditional_value_rule",
            "sequence_predicate_warning",
        ):
            add(
                f"procedural.{kind}",
                str(check.get("category", "?")),
                f"item={check.get('item')}; rules={check.get('rules')}; driver_item={check.get('driver_item', '')}",
            )
        else:
            add(f"procedural.{kind}", str(check.get("category", "?")), str(check))

    OUT.write_text("\n".join(lines) + f"\n\nTOTAL_RULE_ENTRIES={len(lines)}\n", encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"Total entries: {len(lines)}")


if __name__ == "__main__":
    main()
