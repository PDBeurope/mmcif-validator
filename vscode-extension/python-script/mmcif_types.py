"""
Shared types and exceptions for the mmCIF validator.
"""

from collections import namedtuple
from dataclasses import dataclass
from typing import Literal, Optional

# Named tuple for item values: (line_num, value, global_column_index, local_column_index)
ItemValue = namedtuple('ItemValue', ['line_num', 'value', 'global_column_index', 'local_column_index'])


class MmCIFValidatorError(Exception):
    """Base exception for mmCIF validator errors."""
    pass


class DictionaryNotFoundError(MmCIFValidatorError):
    """Raised when the dictionary file is not found."""
    pass


class CifNotFoundError(MmCIFValidatorError):
    """Raised when the mmCIF file is not found."""
    pass


class DownloadError(MmCIFValidatorError):
    """Raised when dictionary download fails."""
    pass


@dataclass
class ValidationError:
    """Represents a validation error (internal use; protocol.ValidationErrorItem is for IO)."""
    line: int
    item: str
    message: str
    severity: Literal["error", "warning"] = "error"
    column: Optional[int] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None
