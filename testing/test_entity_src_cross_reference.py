#!/usr/bin/env python3
"""Unit tests for polymer source cross-references gated by entity.src_method.

Run from the repository root:
  python testing/test_entity_src_cross_reference.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "vscode-extension" / "python-script"
sys.path.insert(0, str(SCRIPT_DIR))

from cif_parser import MmCIFParser  # noqa: E402
from rules.imported_cross_checks import ImportedCrossChecksRuleGroup  # noqa: E402

CIF_DIR = Path(__file__).resolve().parent / "cif_files"


def entity_poly_cross_messages(cif_name: str):
    parser = MmCIFParser(CIF_DIR / cif_name)
    parser.parse()
    errors = ImportedCrossChecksRuleGroup()._run_build_defaults_cross(parser, {}, None)
    return sorted(
        err.message
        for err in errors
        if err.item == "_entity_poly.entity_id"
    )


class EntitySrcCrossReferenceTests(unittest.TestCase):
    def test_matching_source_category_is_accepted(self):
        self.assertEqual(
            entity_poly_cross_messages("test_cross_check_entity_src_by_method_valid.cif"),
            [],
        )

    def test_only_the_method_selected_category_is_required(self):
        self.assertEqual(
            entity_poly_cross_messages("test_cross_check_entity_src_by_method_invalid.cif"),
            [
                "Cross-reference value '1' does not exist in '_entity_src_gen.entity_id'.",
                "Cross-reference value '2' does not exist in '_entity_src_nat.entity_id'.",
                "Cross-reference value '3' does not exist in '_pdbx_entity_src_syn.entity_id'.",
            ],
        )

    def test_missing_source_category_is_reported_for_the_matching_method(self):
        self.assertEqual(
            entity_poly_cross_messages(
                "test_cross_check_entity_src_by_method_missing_category.cif"
            ),
            [
                "Cross-reference value '1' does not exist in '_entity_src_gen.entity_id'.",
            ],
        )


if __name__ == "__main__":
    unittest.main()
