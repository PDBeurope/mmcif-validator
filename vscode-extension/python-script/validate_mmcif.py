#!/usr/bin/env python3
"""
mmCIF Dictionary Validator

Validates mmCIF files against a dictionary file (mmcif_pdbx_v5_next.dic).

Author: Deborah Harrus
Organization: Protein Data Bank in Europe (PDBe), EMBL-EBI
"""

import re
import sys
import json
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Literal

from protocol import (
    ErrorCode,
    validation_result_from_errors,
    script_failure_dict,
    download_success_dict,
)
from mmcif_types import (
    ItemValue,
    ValidationError,
    MmCIFValidatorError,
    DictionaryNotFoundError,
    CifNotFoundError,
    DownloadError,
)
from download import get_cache_dir, get_cached_dictionary_path, download_dictionary
from dict_parser import DictionaryParser
from cif_parser import MmCIFParser
from validator import MmCIFValidator
from metadata_completeness import compute_metadata_completeness

# Module-level logger for library integration with existing logging mechanisms
logger = logging.getLogger(__name__)


def _sorted_validation_errors(errors: List[ValidationError]) -> List[ValidationError]:
    """
    Return errors sorted for stable, predictable reporting.

    Order: category, item, severity (errors before warnings), line.
    Category is derived from the item name (e.g. '_pdbx_contact_author.email' -> 'pdbx_contact_author').
    """
    severity_rank = {"error": 0, "warning": 1}

    def _key(e: ValidationError) -> tuple:
        item = getattr(e, "item", "") or ""
        category = ""
        if item.startswith("_") and "." in item:
            category = item[1:].split(".")[0]
        return (
            category,
            item,
            severity_rank.get(getattr(e, "severity", "error"), 99),
            getattr(e, "line", 0),
        )

    return sorted(errors, key=_key)


def validate(dict_path: Path, cif_path: Path) -> List[ValidationError]:
    """
    Library entry point: parse dictionary, parse mmCIF, validate, and return errors.
    Use this when embedding the validator in other code (e.g. prerelease).
    Raises DictionaryNotFoundError if dict_path does not exist.
    Raises CifNotFoundError if cif_path does not exist.
    """
    errors, _, _ = ValidatorFactory.validate(dict_path, cif_path)
    return _sorted_validation_errors(errors)


class ValidatorFactory:
    """Factory for parsing and validating mmCIF files against a dictionary."""

    @staticmethod
    def validate(dict_path: Path, cif_path: Path) -> tuple:
        """
        Parse dictionary, parse mmCIF file, run validation. Returns (errors, dictionary, mmcif).
        Caller can use dictionary and mmcif for deposition-readiness computation.
        Raises DictionaryNotFoundError if dict_path does not exist.
        Raises CifNotFoundError if cif_path does not exist.
        """
        if not dict_path.exists():
            raise DictionaryNotFoundError(f"Dictionary file not found: {dict_path}")
        if not cif_path.exists():
            raise CifNotFoundError(f"mmCIF file not found: {cif_path}")
        logger.debug("Parsing dictionary: %s", dict_path)
        dictionary = DictionaryParser(dict_path).parse()
        logger.debug("Loaded %d items from dictionary", len(dictionary.items))
        logger.debug("Parsing mmCIF file: %s", cif_path)
        mmcif = MmCIFParser(cif_path).parse()
        logger.debug("Found %d items in mmCIF file", len(mmcif.items))
        logger.debug("Validating...")
        validator = MmCIFValidator(dictionary, mmcif)
        errors = validator.validate()
        return errors, dictionary, mmcif


def cmd_download_dictionary() -> int:
    """CLI subcommand: download dictionary to cache and print path as JSON. Used by the VS Code extension."""
    import os
    parser = argparse.ArgumentParser(prog="validate_mmcif.py download-dictionary", description="Download dictionary to cache")
    parser.add_argument("--url", "-u", required=True, help="URL to download dictionary from")
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output path (default: shared cache directory used by the extension)",
    )
    args = parser.parse_args(sys.argv[2:])
    try:
        if args.output:
            cache_path = Path(args.output)
        else:
            cache_path = get_cached_dictionary_path()
        download_dictionary(args.url, cache_path=cache_path)
        print(json.dumps(download_success_dict(str(cache_path))))
        return 0
    except DownloadError as e:
        logger.error("%s", e)
        print(f"Error: {e}", file=sys.stderr)
        print(json.dumps(script_failure_dict(ErrorCode.DOWNLOAD_ERROR, str(e))))
        return 1


def main():
    """Main entry point for the validator."""
    import os

    # Subcommand: download-dictionary (used by VS Code extension to centralise download)
    if len(sys.argv) >= 2 and sys.argv[1] == "download-dictionary":
        sys.exit(cmd_download_dictionary())

    # Ensure unbuffered output for proper redirection support
    # Force line-buffered output when redirected (not a TTY)
    if not sys.stdout.isatty():
        try:
            sys.stdout.reconfigure(line_buffering=True)
        except (AttributeError, ValueError):
            try:
                sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)
            except (OSError, ValueError):
                pass

    parser = argparse.ArgumentParser(
        description='Validate mmCIF files against a dictionary',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use local dictionary file
  validate_mmcif.py --file mmcif_pdbx_v5_next.dic 6qvt.cif
  
  # Use dictionary from URL
  validate_mmcif.py --url http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic 6qvt.cif
  
  # Auto-detect (file path or URL) - backward compatible
  validate_mmcif.py mmcif_pdbx_v5_next.dic 6qvt.cif
  validate_mmcif.py http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic 6qvt.cif
        """
    )
    
    # Dictionary source options (mutually exclusive)
    dict_group = parser.add_mutually_exclusive_group()
    dict_group.add_argument(
        '--file', '-f',
        type=str,
        help='Path to local dictionary file (.dic)'
    )
    dict_group.add_argument(
        '--url', '-u',
        type=str,
        help='URL to download dictionary from'
    )
    
    # Positional arguments (for backward compatibility)
    parser.add_argument(
        'dict_source',
        nargs='?',
        help='Dictionary file path or URL (if --file or --url not specified)'
    )
    parser.add_argument(
        'cif_file',
        help='mmCIF file to validate (.cif)'
    )
    
    args = parser.parse_args()
    
    # Determine dictionary source
    if args.file:
        dict_source = args.file
        is_url = False
    elif args.url:
        dict_source = args.url
        is_url = True
    elif args.dict_source:
        dict_source = args.dict_source
        # Auto-detect if it's a URL
        is_url = dict_source.startswith('http://') or dict_source.startswith('https://')
    else:
        parser.error("Either specify --file, --url, or provide dictionary source as positional argument")
    
    cif_path = Path(args.cif_file)
    dict_path = None
    cleanup_temp_file = False
    
    # Get dictionary file and run validation
    try:
        if is_url:
            dict_path = download_dictionary(dict_source)
            cleanup_temp_file = True
        else:
            dict_path = Path(dict_source)
            cleanup_temp_file = False
        
        if not dict_path.exists():
            logger.error("Dictionary file not found: %s", dict_path)
            raise DictionaryNotFoundError(f"Dictionary file not found: {dict_path}")
        
        if not cif_path.exists():
            logger.error("mmCIF file not found: %s", cif_path)
            if cleanup_temp_file and dict_path.exists():
                dict_path.unlink()
            raise CifNotFoundError(f"mmCIF file not found: {cif_path}")
        
        try:
            errors, dictionary, mmcif = ValidatorFactory.validate(dict_path, cif_path)
            errors = _sorted_validation_errors(errors)
        finally:
            if cleanup_temp_file and dict_path is not None and dict_path.exists():
                dict_path.unlink()

        # Build JSON output for VSCode extension (always include metadata_completeness when available)
        json_output = validation_result_from_errors(errors)
        try:
            dep = compute_metadata_completeness(dictionary, mmcif, validation_errors=errors)
            json_output["metadata_completeness"] = dep.to_dict()
        except Exception as e:
            logger.debug("Metadata completeness computation skipped: %s", e)

        # Output results
        if errors:
            logger.info("Found %d validation issue(s)", len(errors))
            for error in errors:
                logger.info("%s: Line %d, Item '%s' - %s", error.severity.upper(), error.line, error.item, error.message)

            print(f"\nFound {len(errors)} validation issue(s):\n")
            for error in errors:
                print(f"{error.severity.upper()}: Line {error.line}, Item '{error.item}'")
                print(f"  {error.message}\n")

            print(json.dumps(json_output, indent=2))
            return 1
        else:
            logger.info("Validation passed - no errors found")
            print("\nValidation passed! No errors found.")
            print(json.dumps(json_output, indent=2))
            return 0
    except DictionaryNotFoundError as e:
        logger.error("%s", e)
        print(f"Error: {e}", file=sys.stderr)
        print(json.dumps(script_failure_dict(ErrorCode.DICT_NOT_FOUND, str(e))))
        if cleanup_temp_file and dict_path is not None and dict_path.exists():
            dict_path.unlink()
        return 1
    except CifNotFoundError as e:
        logger.error("%s", e)
        print(f"Error: {e}", file=sys.stderr)
        print(json.dumps(script_failure_dict(ErrorCode.CIF_NOT_FOUND, str(e))))
        if cleanup_temp_file and dict_path is not None and dict_path.exists():
            dict_path.unlink()
        return 1
    except DownloadError as e:
        logger.error("%s", e)
        print(f"Error: {e}", file=sys.stderr)
        print(json.dumps(script_failure_dict(ErrorCode.DOWNLOAD_ERROR, str(e))))
        if cleanup_temp_file and dict_path is not None and dict_path.exists():
            dict_path.unlink()
        return 1
    except MmCIFValidatorError as e:
        logger.error("%s", e)
        print(f"Error: {e}", file=sys.stderr)
        print(json.dumps(script_failure_dict(ErrorCode.UNKNOWN_ERROR, str(e))))
        if cleanup_temp_file and dict_path is not None and dict_path.exists():
            dict_path.unlink()
        return 1


if __name__ == '__main__':
    sys.exit(main())

