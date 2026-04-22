"""
Reusable base class for CSV-driven rule groups.
"""

from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generic, List, Optional, TypeVar

from mmcif_types import ValidationError


RuleT = TypeVar("RuleT")


class BaseCsvRuleGroup(ABC, Generic[RuleT]):
    """
    Shared scaffolding for rule groups that load definitions from CSV.
    Subclasses implement row parsing and rule execution logic.
    """

    def __init__(self, csv_path: Optional[Path] = None):
        self.csv_path = csv_path or self.default_csv_path()

    @abstractmethod
    def default_csv_path(self) -> Path:
        """Return the default CSV path for this rule group."""
        raise NotImplementedError

    @abstractmethod
    def parse_rule_row(self, row: dict) -> Optional[RuleT]:
        """Parse one CSV row into a rule object. Return None to skip invalid rows."""
        raise NotImplementedError

    @abstractmethod
    def run_rules(self, mmcif, rules: List[RuleT]) -> List[ValidationError]:
        """Execute parsed rules and return validation errors."""
        raise NotImplementedError

    def load_rules(self) -> List[RuleT]:
        """Load and parse all rules from CSV."""
        if not self.csv_path.exists():
            return []

        rules: List[RuleT] = []
        with self.csv_path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                parsed = self.parse_rule_row(row)
                if parsed is not None:
                    rules.append(parsed)
        return rules

    def run(self, mmcif) -> List[ValidationError]:
        """Load rules from CSV and run them against parsed mmCIF data."""
        rules = self.load_rules()
        if not rules:
            return []
        return self.run_rules(mmcif, rules)
