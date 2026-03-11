"""
Mandatory categories per experimental method for deposition readiness.

Loads category lists from the completeness folder (bundled with the extension or repo root).
"""

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Method identifiers
METHOD_XRAY = "xray"
METHOD_EM = "em"
METHOD_NMR = "nmr"
METHOD_UNKNOWN = "unknown"

# Filenames under the completeness directory
XRAY_LIST = "xray_mandatory_cat.list"
EM_LIST = "em_mandatory_cat.list"
NMR_LIST = "nmr_mandatory_cat.list"


def _find_completeness_dir() -> Optional[Path]:
    """Locate the completeness directory (contains *_mandatory_cat.list files)."""
    # This file is in .../python-script/completeness/; the .list files are in the same directory
    script_dir = Path(__file__).resolve().parent
    if (script_dir / XRAY_LIST).exists():
        return script_dir
    # Repo layout: script might be run from repo root with python -m, or completeness at repo root
    repo_root = script_dir.parent.parent.parent
    repo_completeness = repo_root / "completeness"
    if (repo_completeness / XRAY_LIST).exists():
        return repo_completeness
    return None


def _load_categories(path: Path) -> Set[str]:
    """Load category names from a .list file (one per line, strip whitespace, skip empty)."""
    if not path.exists():
        return set()
    cats = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if name:
                cats.add(name)
    return cats


def load_mandatory_categories() -> Tuple[Dict[str, Set[str]], Set[str], Dict[str, Set[str]]]:
    """
    Load mandatory categories per method and compute common set.

    Returns:
        mandatory_by_method: dict method_id -> set of category names
        common_categories: intersection of all three methods (for unknown method)
        method_specific_categories: dict method_id -> set of categories only in that method (for detection)
    """
    root = _find_completeness_dir()
    mandatory_by_method: Dict[str, Set[str]] = {}
    if root:
        mandatory_by_method[METHOD_XRAY] = _load_categories(root / XRAY_LIST)
        mandatory_by_method[METHOD_EM] = _load_categories(root / EM_LIST)
        mandatory_by_method[METHOD_NMR] = _load_categories(root / NMR_LIST)
    else:
        mandatory_by_method[METHOD_XRAY] = set()
        mandatory_by_method[METHOD_EM] = set()
        mandatory_by_method[METHOD_NMR] = set()

    common_categories = (
        mandatory_by_method[METHOD_XRAY]
        & mandatory_by_method[METHOD_EM]
        & mandatory_by_method[METHOD_NMR]
    )

    # Method-specific: categories that appear only in that method (used for detection)
    xray_only = mandatory_by_method[METHOD_XRAY] - mandatory_by_method[METHOD_EM] - mandatory_by_method[METHOD_NMR]
    em_only = mandatory_by_method[METHOD_EM] - mandatory_by_method[METHOD_XRAY] - mandatory_by_method[METHOD_NMR]
    nmr_only = mandatory_by_method[METHOD_NMR] - mandatory_by_method[METHOD_XRAY] - mandatory_by_method[METHOD_EM]
    method_specific_categories = {
        METHOD_XRAY: xray_only,
        METHOD_EM: em_only,
        METHOD_NMR: nmr_only,
    }

    return mandatory_by_method, common_categories, method_specific_categories


def detect_method(file_categories: Set[str], method_specific: Dict[str, Set[str]]) -> str:
    """
    Detect experimental method from categories present in the file.

    If the file contains at least one category that is specific to a method, that method is returned.
    Priority: xray, then em, then nmr (first match wins).
    Otherwise returns METHOD_UNKNOWN.
    """
    if not file_categories:
        return METHOD_UNKNOWN
    for method in (METHOD_XRAY, METHOD_EM, METHOD_NMR):
        if method_specific[method] & file_categories:
            return method
    return METHOD_UNKNOWN
