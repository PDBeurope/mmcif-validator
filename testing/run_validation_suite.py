#!/usr/bin/env python3
"""
Regression test suite for the mmCIF validator.

Validates all .cif files in testing/cif_files/ using the Python validator script,
saves the combined output to a file. After code changes, run again and diff
against the saved baseline to check for intended vs unintended changes.

Usage (from repository root):
  python testing/run_validation_suite.py
  python testing/run_validation_suite.py --generate-baseline

Or from the testing/ directory:
  python run_validation_suite.py
  python run_validation_suite.py --generate-baseline
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Tuple


# This script lives in testing/; repo root is parent
TESTING_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTING_DIR.parent
VALIDATOR_SCRIPT = REPO_ROOT / "vscode-extension" / "python-script" / "validate_mmcif.py"
# Default dictionary source: URL used by the VS Code extension / validator CLI examples
DEFAULT_DICT_SOURCE = "http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic"
DEFAULT_TESTS_DIR = TESTING_DIR / "cif_files"
OUTPUT_FILE = "validation_output.txt"
BASELINE_FILE = "validation_baseline.txt"


def find_cif_files(tests_dir: Path):
    """Return sorted list of .cif files in tests_dir."""
    if not tests_dir.is_dir():
        return []
    return sorted(tests_dir.glob("*.cif"))


def run_validator(dict_source: str, cif_path: Path) -> Tuple[str, str, int]:
    """Run validate_mmcif.py on one CIF file. Returns (stdout, stderr, returncode).

    dict_source can be a local path or a URL; it is passed positionally and
    validate_mmcif.py auto-detects whether it is a URL.
    """
    cmd = [
        sys.executable,
        str(VALIDATOR_SCRIPT),
        dict_source,
        str(cif_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
    )
    return (result.stdout, result.stderr, result.returncode)


def run_suite(
    dict_source: str,
    tests_dir: Path,
    output_path: Path,
) -> int:
    """Run validator on all CIFs, write combined output to output_path. Returns number of failed validations."""
    cif_files = find_cif_files(tests_dir)
    if not cif_files:
        print(f"No .cif files found in {tests_dir}", file=sys.stderr)
        return 1

    lines = []
    # Represent dictionary source in a portable way (URLs are left as-is)
    if "://" in dict_source:
        dict_str = dict_source
    else:
        dict_path = Path(dict_source)
        try:
            dict_rel = dict_path.relative_to(REPO_ROOT)
            dict_str = f"<REPO>/{dict_rel}"
        except ValueError:
            dict_str = str(dict_path)

    try:
        tests_rel = tests_dir.relative_to(REPO_ROOT)
        tests_str = f"<REPO>/{tests_rel}"
    except ValueError:
        tests_str = str(tests_dir)
    lines.append("=" * 80)
    lines.append("mmCIF Validator test suite")
    lines.append(f"Dictionary: {dict_str}")
    lines.append(f"Test directory: {tests_str}")
    lines.append(f"CIF files: {len(cif_files)}")
    lines.append("=" * 80)

    failed_count = 0
    for cif_path in cif_files:
        name = cif_path.name
        lines.append("")
        lines.append("-" * 80)
        lines.append(f"FILE: {name}")
        lines.append("-" * 80)
        stdout, stderr, returncode = run_validator(dict_source, cif_path)
        if stdout:
            lines.append(stdout.rstrip())
        if stderr:
            lines.append("")
            lines.append("STDERR:")
            lines.append(stderr.rstrip())
        lines.append("")
        lines.append(f"EXIT_CODE: {returncode}")
        if returncode != 0:
            failed_count += 1

    lines.append("")
    lines.append("=" * 80)
    lines.append(f"SUMMARY: {failed_count} file(s) had validation issues, {len(cif_files) - failed_count} passed.")
    lines.append("=" * 80)

    out_text = "\n".join(lines) + "\n"
    for path_form in (str(REPO_ROOT), REPO_ROOT.as_posix(), str(REPO_ROOT).replace("\\", "/")):
        if path_form in out_text:
            out_text = out_text.replace(path_form, "<REPO>")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(out_text, encoding="utf-8")
    print(f"Wrote output to {output_path}")
    return failed_count


def main():
    parser = argparse.ArgumentParser(
        description="Run mmCIF validator on all test CIF files and save output for regression comparison.",
    )
    parser.add_argument(
        "--dict", "-d",
        type=str,
        default=DEFAULT_DICT_SOURCE,
        help=(
            "Dictionary source (URL or local .dic path). "
            f"Default: {DEFAULT_DICT_SOURCE}"
        ),
    )
    parser.add_argument(
        "--tests", "-t",
        type=Path,
        default=DEFAULT_TESTS_DIR,
        help=f"Directory containing .cif files (default: {DEFAULT_TESTS_DIR})",
    )
    parser.add_argument(
        "--generate-baseline",
        action="store_true",
        help="Write output to validation_baseline.txt (run once before code changes)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Write output to this file (default: testing/validation_output.txt or validation_baseline.txt)",
    )
    args = parser.parse_args()

    dict_source = args.dict  # may be URL or path; validator CLI will decide
    tests_dir = args.tests.resolve()

    if not tests_dir.exists():
        print(f"Test directory not found: {tests_dir}", file=sys.stderr)
        return 1

    if args.output is not None:
        output_path = args.output.resolve()
    else:
        output_path = TESTING_DIR / (BASELINE_FILE if args.generate_baseline else OUTPUT_FILE)

    failed = run_suite(dict_source, tests_dir, output_path)

    if args.generate_baseline:
        print("Baseline saved. After code changes, run without --generate-baseline and diff the output.")
    else:
        baseline_path = TESTING_DIR / BASELINE_FILE
        if baseline_path.exists():
            print(f"\nTo compare with baseline: diff (or fc) {baseline_path} {output_path}")
        else:
            print(f"\nNo baseline found at {baseline_path}. Run with --generate-baseline first.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
