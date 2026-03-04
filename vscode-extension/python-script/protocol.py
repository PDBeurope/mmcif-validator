"""
Protocol / IO schema for communication between the mmCIF validator script and the VS Code extension.

Defines the JSON structure for:
- Validation results (success with list of validation errors)
- Script failure responses (error codes + message)

Both sides (Python script and extension) should use this contract so that
changes to one can be reflected in the other via a single definition.
"""

from dataclasses import dataclass, asdict
from typing import Any, List, Literal, Optional

# ---------------------------------------------------------------------------
# Error codes for script failures (e.g. dictionary not found, download failed).
# The extension can use these to show specific messages or retry logic.
# ---------------------------------------------------------------------------
class ErrorCode:
    """Numeric error codes for script-level failures. Stable for extension to depend on."""
    # 1-99: dictionary/file errors
    DICT_NOT_FOUND = 1
    CIF_NOT_FOUND = 2
    DOWNLOAD_ERROR = 3
    # Generic catch-all for other MmCIFValidatorError
    UNKNOWN_ERROR = 99


# ---------------------------------------------------------------------------
# Validation result (success path): list of validation errors
# ---------------------------------------------------------------------------

@dataclass
class ValidationErrorItem:
    """A single validation error. Mirrors the Python ValidationError used internally."""
    line: int
    item: str
    message: str
    severity: Literal["error", "warning"] = "error"
    column: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationResult:
    """Success response: validation ran and produced a list of errors (possibly empty)."""
    errors: List[ValidationErrorItem]

    def to_dict(self) -> dict:
        return {"errors": [e.to_dict() for e in self.errors]}


# ---------------------------------------------------------------------------
# Script failure response (exception path): error code + message
# ---------------------------------------------------------------------------

@dataclass
class ScriptFailure:
    """Script-level failure (e.g. dictionary not found, download failed). Output as JSON on failure."""
    success: Literal[False] = False
    error_code: int = 0
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "success": False,
            "error_code": self.error_code,
            "message": self.message,
        }


def validation_result_from_errors(errors: List[Any]) -> dict:
    """
    Build the JSON-serializable validation result from a list of internal ValidationError instances.
    Use this in the script when outputting success-with-errors.
    """
    return {
        "errors": [
            {
                "line": e.line,
                "item": e.item,
                "message": e.message,
                "severity": e.severity,
                "column": e.column,
                "start_char": getattr(e, "start_char", None),
                "end_char": getattr(e, "end_char", None),
            }
            for e in errors
        ]
    }


def script_failure_dict(error_code: int, message: str) -> dict:
    """Build the JSON-serializable script failure object."""
    return ScriptFailure(success=False, error_code=error_code, message=message).to_dict()


def download_success_dict(path: str) -> dict:
    """Build the JSON output for successful dictionary download (CLI subcommand)."""
    return {"path": path}
