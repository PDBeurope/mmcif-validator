#!/usr/bin/env python3
"""Unit tests for atom_site occupancy procedural checks.

Run from the repository root:
  python testing/test_occupancy_checks.py
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
OCC_ITEM = "_atom_site.occupancy"
OVER_ONE = "has a total occupancy of"
BELOW = "below 0.1"


def occupancy_errors(cif_name: str, cif_dir: Path = CIF_DIR):
    parser = MmCIFParser(cif_dir / cif_name)
    parser.parse()
    return [
        err
        for err in ImportedCrossChecksRuleGroup()._run_procedural_validators(parser, {})
        if err.item == OCC_ITEM
    ]


class OccupancyCheckTests(unittest.TestCase):
    def test_altlocs_summing_over_one_are_errors(self):
        hits = occupancy_errors("test_procedural_occupancy_invalid_total_over_one.cif")
        over = [err for err in hits if OVER_ONE in err.message and err.severity == "error"]
        self.assertEqual(len(over), 3, hits)
        self.assertTrue(all("1.1" in err.message for err in over), over)
        self.assertTrue(all("residue 36 SER atom CA" in err.message for err in over), over)
        self.assertFalse(any("residue 1 ALA" in err.message for err in over), over)

    def test_altlocs_summing_to_one_are_ok(self):
        hits = occupancy_errors("test_procedural_occupancy_valid_altlocs_sum_to_one.cif")
        self.assertEqual(hits, [])

    def test_occupancy_below_point_one_is_warning(self):
        hits = occupancy_errors("test_procedural_occupancy_warning_below_point_one.cif")
        low = [err for err in hits if BELOW in err.message and err.severity == "warning"]
        self.assertEqual(len(low), 1, hits)
        self.assertIn("0.05", low[0].message)
        self.assertNotIn("atom CB", low[0].message)

    def test_occupancy_exactly_point_one_is_ok(self):
        hits = occupancy_errors("test_procedural_occupancy_edge_exactly_point_one.cif")
        self.assertEqual(hits, [])

    def test_occupancy_exactly_one_is_ok(self):
        hits = occupancy_errors("test_procedural_occupancy_edge_exactly_one.cif")
        self.assertEqual(hits, [])

    def test_missing_occupancy_is_skipped(self):
        hits = occupancy_errors("test_procedural_occupancy_edge_missing.cif")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
