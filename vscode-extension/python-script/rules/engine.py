"""
Rule engine and registry for additional cross-check rule groups.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from mmcif_types import ValidationError
from rules.imported_cross_checks import ImportedCrossChecksRuleGroup

RuleGroupFactory = Callable[[], object]

# Registry of available rule groups.
# Add new entries here when introducing new rule families.
RULE_GROUP_REGISTRY: Dict[str, RuleGroupFactory] = {
    "imported_cross_checks": ImportedCrossChecksRuleGroup,
}


def _default_config_path() -> Path:
    return Path(__file__).resolve().parent / "rule_groups.json"


def _load_rule_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    try:
        with config_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        # Config is optional. Ignore parse/IO failures and use defaults.
        return {}


def _select_rule_group_ids(config: dict) -> List[str]:
    all_ids = list(RULE_GROUP_REGISTRY.keys())
    enabled = config.get("enabled_rule_groups")
    disabled = set(config.get("disabled_rule_groups", []))

    if isinstance(enabled, list):
        enabled_set: Set[str] = {name for name in enabled if name in RULE_GROUP_REGISTRY}
        selected = [name for name in all_ids if name in enabled_set]
    else:
        selected = all_ids

    return [name for name in selected if name not in disabled]


def default_rule_groups(config_path: Optional[Path] = None):
    """
    Build default rule group instances, optionally filtered by JSON config.

    Config format (all fields optional):
    {
      "enabled_rule_groups": ["imported_cross_checks"],
      "disabled_rule_groups": []
    }
    """
    config = _load_rule_config(config_path or _default_config_path())
    selected_ids = _select_rule_group_ids(config)
    return [RULE_GROUP_REGISTRY[name]() for name in selected_ids]


class RuleEngine:
    """Executes registered rule groups and aggregates ValidationError results."""

    def __init__(self, rule_groups=None, config_path: Optional[Path] = None):
        self.rule_groups = rule_groups if rule_groups is not None else default_rule_groups(config_path=config_path)

    def run(self, mmcif) -> List[ValidationError]:
        errors: List[ValidationError] = []
        for rule_group in self.rule_groups:
            errors.extend(rule_group.run(mmcif))
        return errors
