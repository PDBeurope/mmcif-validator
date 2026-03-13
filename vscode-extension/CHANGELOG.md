# Change Log

All notable changes to the PDBe mmCIF Validator extension will be documented in this file.

# Released

## [0.1.7] - 2026-03-11

### Added
- **Metadata completeness indicator**: Percentage score showing how complete the file metadata is (mandatory categories and items from completeness lists and dictionary).
  - **Status bar**: Shows "Metadata: X%" with method (xray/em/nmr or "method unknown"); tooltip lists missing categories/items.
  - **Output channel**: "Metadata completeness" section with percentage, method, missing categories, and missing items (with row/key and "[validation error]" where applicable).
  - **Metadata Completeness view**: Sidebar view in Explorer with summary, "Missing categories", and "Missing items" (expandable).
- **Row-level checks**: Every row in a mandatory loop category must have all mandatory items filled; missing or `?`/`.` values count as not filled; percentage = filled/total.
- **Method detection**: Experimental method (xray/em/nmr) inferred from file categories; when unknown, only common categories are used and score is capped at 50%.
- **Validation errors as not filled**: Items with a validation error (severity "error") are counted as not filled and listed in missing items with "validation error"; second pass includes errors in mandatory categories even when the item is not deposition-mandatory in the dictionary.
- **Python**: `deposition_readiness` module, `completeness` package (mandatory category lists, including an entity-source group where at least one category must be present), `dict_parser` deposition-mandatory items (`_pdbx_item.mandatory_code`); protocol extended with `MetadataCompleteness` (missing_categories, missing_items, has_validation_error) and JSON `metadata_completeness` field.

### Changed
- Validation script always outputs JSON (with optional `metadata_completeness`) on both success and failure so the extension can show metadata completeness info.
- Status bar tooltip directs users to "Output channel or Metadata Completeness in Explorer sidebar" for missing items.

## [0.1.6] - 2026-03-03

### Changed
- **Extension refactor**: Split `extension.ts` into separate modules (validation, hover, config, dictionary, types); extension entry point only registers commands and initialises.
- **Dictionary download**: Extension now delegates dictionary download to the Python script (single implementation). Cache path is shared (`mmcif-validator-cache` in temp directory).
- **Script–extension protocol**: Formalised IO between Python script and extension:
  - **protocol.py**: `ValidationResult` / `ValidationErrorItem`, `ScriptFailure` with `error_code` and `message`, `ErrorCode` constants (DICT_NOT_FOUND, CIF_NOT_FOUND, DOWNLOAD_ERROR, UNKNOWN_ERROR). Script prints JSON on both success and script-level failure.
  - Extension parses script-failure JSON and shows user-facing messages by error code.

### Added
- **Python: download-dictionary subcommand**: `python validate_mmcif.py download-dictionary --url URL [--output PATH]` downloads the dictionary to the shared cache (or optional path) and prints `{"path": "..."}` or script-failure JSON.
- **Python: new modules**:
  - **protocol.py** – IO schema and error codes for script–extension communication.
  - **mmcif_types.py** – `ItemValue`, `ValidationError`, and exception classes.
  - **download.py** – `get_cache_dir()`, `get_cached_dictionary_path()`, `download_dictionary()`.
  - **dict_parser.py** – `DictionaryParser` (dictionary file parsing).
  - **cif_parser.py** – `MmCIFParser` (mmCIF file parsing).
  - **validator.py** – `MmCIFValidator` (validation logic).
- **pyproject.toml**: New modules listed in `py-modules` for packaging.

### Improved
- **Python structure**: `validate_mmcif.py` is now a thin CLI/orchestration layer (~265 lines); parser and validator classes live in dedicated modules for maintainability.

# [Unreleased]

## [0.1.5] - 2026-02-27

### Added
- **Python validator as library**: The Python validator can be used from other code (e.g. prerelease pipelines) as well as from the CLI
  - **Library entry point**: `validate(dict_path, cif_path)` and `ValidatorFactory.validate(dict_path, cif_path)` return a list of `ValidationError`; no process exit when used as a library
  - **Custom exceptions**: `DictionaryNotFoundError`, `CifNotFoundError`, `DownloadError` (and base `MmCIFValidatorError`) so callers can catch and handle errors instead of the process exiting
  - **Logging**: Replaced `print` with the standard `logging` module (`logger`) so the validator integrates with existing logging configuration
- **PyPI packaging**: The Python validator is packaged for PyPI as `pdbe-mmcif-validator`
  - Install with `pip install pdbe-mmcif-validator`; provides a `validate-mmcif` console script
  - `pyproject.toml` in `vscode-extension/python-script` with metadata, entry point, and Python 3.7+ support
- **README**: New "Library usage" section in the Python script README with install, basic usage, URL download example, logging integration, and exception reference

### Improved
- **Python validator structure**: Refactored for both CLI and library use
  - **ValidatorFactory**: Single factory method that parses dictionary, parses mmCIF, and runs validation (used by both `main()` and library callers)
  - **Split validation**: `MmCIFValidator.validate()` split into smaller methods (`_validate_duplicate_blocks`, `_validate_undefined_and_mandatory_items`, `_validate_item_values`, etc.) with shared helpers (`_present_values`, `_advisory_message`, etc.)
  - **Typing**: `severity` now uses `Literal["error", "warning"]`; item values use a named tuple `ItemValue` (line_num, value, global_column_index, local_column_index) instead of raw tuples
  - **Exit behaviour**: `sys.exit()` is only called from `main()`; library code raises exceptions so callers can handle failures

## [0.1.4] - 2026-02-26

### Added
- **Duplicate category and item detection**: Validator now reports dictionary-breaking errors when a category or item is duplicated
  - **Duplicate category**: Same category appears in more than one loop block or in more than one frame (non-loop) block; reported once per category with line of first duplicate
  - **Duplicate item**: Same item name appears twice in a loop header, twice in a frame block, or in two blocks of the same category; reported with line of first occurrence
  - Works for both loop format (`loop_` with multiple columns) and frame format (item–value pairs)

## [0.1.3] - 2026-02-25

### Added
- **Configurable validation timeout**: Validation timeout can be set in extension settings (`mmcifValidator.validationTimeoutSeconds`). Default 60 seconds, range 5–600 seconds (10 minutes max). Use a longer timeout for very large mmCIF files to avoid "Validation timed out" messages.

## [0.1.2] - 2025-12-11

### Added
- **Composite key validation**: Validates that combinations of multiple child items together match corresponding combinations in parent categories
  - Example: In `pdbx_entity_poly_domain`, the combination of `begin_mon_id` + `begin_seq_num` must match a row in `entity_poly_seq` where `mon_id` + `num` appear together as a pair
  - Ensures data integrity for complex multi-item relationships where individual values might exist but not in the required combination
- **Operation expression validation**: Parses and validates complex operation expressions used in assembly definitions
  - Supports expressions like `(1)`, `(1,2,5)`, `(1-4)`, `(1,2)(3,4)`, and `(X0)(1-5,11-15)`
  - Validates that all referenced operation IDs exist in `_pdbx_struct_oper_list.id`
  - Particularly important for virus assemblies where expressions like `(1-60)` reference multiple operations
- **Dictionary caching**: Extension automatically caches the dictionary locally for one month
  - Balances dictionary freshness with download efficiency
  - Dictionary updates are usually released in conjunction with OneDep software releases (average update frequency ~43 days)
- **Error vs warning severity distinction**: Clear separation between mandatory constraint violations (errors) and advisory issues (warnings)
  - **Errors** (red underline): Missing mandatory items, enumeration violations, data type mismatches, strictly allowed range violations, parent category missing, foreign key integrity violations, composite key violations, invalid operation expression references
  - **Warnings** (yellow underline): Undefined items, advisory range violations
- **Range validation distinction**: Distinguishes between strictly allowed and advisory boundary conditions
  - **Strictly Allowed Boundary Conditions** (`_item_range`): Violations reported as **errors**
  - **Advisory Boundary Conditions** (`_pdbx_item_range`): Violations reported as **warnings** with "Out of advisory range:" prefix
- **Category-aware validation**: Only checks mandatory items for categories that are actually present in the mmCIF file
  - Reduces false positives by not checking mandatory items for categories that don't exist in the file

### Improved
- **Enhanced validation output**: Updated validation messages to clearly distinguish between errors and warnings
- **Standalone Python script**: Enhanced JSON output now includes precise character positions and column indices for programmatic error handling
  - Exit codes: 0 for success, 1 for errors (useful for CI/CD integration)

## [0.1.1] - 2025-12-09

### Improved
- **Precise error highlighting**: Validation errors now highlight the exact problematic value, not just the line or item name
  - For loop data: Highlights the specific value in the correct column, even when the same value appears multiple times
  - For non-loop items: Highlights the value instead of the item name
  - Works correctly even when rows span multiple lines
- **Enhanced JSON output**: Added `start_char`, `end_char`, and `column` fields to JSON output for precise error positioning
- **Improved advisory range messages**: Messages now distinguish between values outside allowed ranges vs. advisory ranges
  - Uses "advised value" when value is within allowed range but outside advisory range
  - Uses "allowed value" when value is outside the allowed range entirely

## [0.1.0] - 2025-12-05

### Added
- Initial release of PDBe mmCIF Validator
- Real-time validation of mmCIF/CIF files against the PDBx/mmCIF dictionary or any CIF dictionary
- Support for validating against local dictionary files or downloading from URL
- Automatic detection of dictionary files in workspace
- Error and warning highlighting in the editor
- Command palette command for manual validation
- Configuration options for dictionary path/URL and Python path
- **Validation checks**:
  - Item definition validation
  - Mandatory item validation (category-aware)
  - Enumeration value validation
  - Data type validation (automatic regex-based validation for types like email, phone, orcid_id, pdb_id, fax, plus hardcoded validations for dates, integers, floats, booleans)
  - Range validation
  - Parent/child category relationship validation
  - Foreign key integrity validation
- **Editor features**:
  - Syntax highlighting for CIF files
  - Hover information showing tag names and data block context
  - Automatic validation on file open, save, and changes (1-second debounce)
- **Standalone Python script**: Fully functional standalone validation script that can be used independently of VSCode
  - Command-line interface for batch processing
  - JSON output for programmatic use
  - No external dependencies (uses only Python standard library)
  - Works with PDBx/mmCIF dictionary or any CIF dictionary format

