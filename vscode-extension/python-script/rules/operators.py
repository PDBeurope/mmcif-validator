"""
Shared operator helpers for cross-check rule groups.
"""

from __future__ import annotations

import operator
from typing import Callable, Dict


OperatorFn = Callable[[float, float], bool]

_OPERATORS: Dict[str, OperatorFn] = {
    "<": operator.lt,
    ">": operator.gt,
    "<=": operator.le,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


def compare_numeric(left: float, op: str, right: float) -> bool:
    """
    Compare two numeric values with a supported operator token.
    Returns False for unsupported operators.
    """
    comparator = _OPERATORS.get(op)
    if comparator is None:
        return False
    return comparator(left, right)
