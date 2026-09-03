#!/usr/bin/env python3
"""Unit tests for pdbx_diffrn_id single-row join fallback.

Run from the repository root:
  python testing/test_linked_single_row_fallback.py
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
OBS_ITEM = "_reflns.number_obs"
OBS_MESSAGE = "Observed reflections is lower than total reflections used in refinement"


def linked_errors(cif_name: str):
    parser = MmCIFParser(CIF_DIR / cif_name)
    parser.parse()
    return ImportedCrossChecksRuleGroup()._run_linked(parser, {})


def number_obs_errors(cif_name: str):
    return [
        err
        for err in linked_errors(cif_name)
        if err.item == OBS_ITEM and OBS_MESSAGE in err.message
    ]


class LinkedSingleRowFallbackTests(unittest.TestCase):
    def test_missing_refine_id_non_loop_reports_error(self):
        hits = number_obs_errors(
            "test_cross_check_linked_number_obs_fallback_missing_refine_diffrn_id.cif"
        )
        self.assertEqual(len(hits), 1, hits)
        self.assertEqual(hits[0].severity, "error")

    def test_missing_refine_id_loop_reports_error(self):
        hits = number_obs_errors(
            "test_cross_check_linked_number_obs_fallback_loop_refine.cif"
        )
        self.assertEqual(len(hits), 1, hits)

    def test_matching_keys_still_report_error(self):
        hits = number_obs_errors("test_cross_check_linked_number_obs_keys_match.cif")
        self.assertEqual(len(hits), 1, hits)

    def test_disagreeing_keys_are_not_compared(self):
        hits = number_obs_errors("test_cross_check_linked_number_obs_keys_disagree.cif")
        self.assertEqual(hits, [])

    def test_two_refine_rows_without_id_are_not_guessed(self):
        hits = number_obs_errors(
            "test_cross_check_linked_number_obs_two_refine_no_fallback.cif"
        )
        self.assertEqual(hits, [])

    def test_fallback_does_not_fire_when_values_are_consistent(self):
        hits = number_obs_errors(
            "test_cross_check_linked_number_obs_fallback_values_ok.cif"
        )
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
