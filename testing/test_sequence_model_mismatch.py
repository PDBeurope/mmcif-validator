#!/usr/bin/env python3
"""Unit tests for sequence vs model residue-type checks.

Run from the repository root:
  python testing/test_sequence_model_mismatch.py
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
COMP_ITEM = "_atom_site.label_comp_id"
MISMATCH = "does not match with the residue"


def sequence_errors(cif_name: str, cif_dir: Path = CIF_DIR):
    parser = MmCIFParser(cif_dir / cif_name)
    parser.parse()
    return [
        err
        for err in ImportedCrossChecksRuleGroup()._run_procedural_validators(parser, {})
        if err.item == COMP_ITEM and (
            MISMATCH in err.message or "is not present in the sequence" in err.message
        )
    ]


class SequenceModelMismatchTests(unittest.TestCase):
    def test_label_seq_mismatch_is_error(self):
        hits = sequence_errors("test_procedural_sequence_mismatch_invalid.cif")
        self.assertEqual(len(hits), 1, hits)
        self.assertEqual(hits[0].severity, "error")
        self.assertIn("ASP", hits[0].message)
        self.assertIn("145", hits[0].message)
        self.assertIn("'GLU'", hits[0].message)

    def test_matching_residue_is_ok(self):
        hits = sequence_errors("test_procedural_sequence_mismatch_valid.cif")
        self.assertEqual(hits, [])

    def test_unmodelled_sequence_residue_is_ok(self):
        hits = sequence_errors("test_procedural_sequence_mismatch_unmodelled_ok.cif")
        self.assertEqual(hits, [])

    def test_missing_label_seq_id_uses_residue_window(self):
        hits = sequence_errors("test_procedural_sequence_mismatch_no_label_seq.cif")
        self.assertEqual(len(hits), 1, hits)
        self.assertIn("ASP", hits[0].message)
        self.assertIn("9", hits[0].message)
        self.assertIn("'GLU'", hits[0].message)

    def test_mse_does_not_match_met(self):
        hits = sequence_errors("test_procedural_sequence_mismatch_mse_met.cif")
        self.assertEqual(len(hits), 1, hits)
        self.assertEqual(hits[0].severity, "error")
        self.assertIn("MSE", hits[0].message)
        self.assertIn("'MET'", hits[0].message)


if __name__ == "__main__":
    unittest.main()
