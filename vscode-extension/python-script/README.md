# PDBe mmCIF Validator - Python Script

A standalone Python script to validate mmCIF/CIF files against the PDBx/mmCIF dictionary or any CIF dictionary.

## Features

- ✅ Validates mmCIF/CIF files against any CIF dictionary schema
- ✅ Checks for missing mandatory items (only for categories present in file)
- ✅ Validates item values against enumerations
- ✅ **Data type validation** - Automatically validates types with regex patterns from dictionary (email, phone, orcid_id, pdb_id, fax, etc.) plus hardcoded validations for dates, integers, floats, booleans
- ✅ **Range validation** - Distinguishes between strictly allowed boundary conditions (errors) and advisory boundary conditions (warnings)
- ✅ **Parent/child category relationship validation** - Ensures parent categories exist when child categories are present
- ✅ **Foreign key integrity validation** - Ensures referenced data exists in parent items
- ✅ **Composite key validation** - Validates that combinations of multiple child items together match corresponding combinations in parent categories
- ✅ **Operation expression validation** - Parses and validates complex operation expressions like `(1-60)`, `(1,2,5)`, `(X0)(1-5,11-15)`
- ✅ Supports local dictionary files or downloading from URL (works with PDBx/mmCIF dictionary or any CIF dictionary format)
- ✅ **Enhanced JSON output** - Includes precise character positions and column indices for programmatic error handling
- ✅ **Exit codes** - Returns 0 for success, 1 for errors (useful for CI/CD integration)

## Installation

### Prerequisites

- Python 3.7 or higher (uses only Python standard library, no pip packages required)
- Internet connection (optional) - Only needed if downloading dictionary from URL. Can use local dictionary file for offline use.
- CIF dictionary file (optional) - Defaults to PDBx/mmCIF dictionary from URL, but can use any CIF dictionary format

## Usage

### Basic Usage

```bash
# Dictionary source can be a file path or URL (auto-detected)
# Works with PDBx/mmCIF dictionary or any CIF dictionary format
python validate_mmcif.py <dictionary.dic or URL> <mmcif_file.cif>
```

### Using Local Dictionary File

```bash
# Use PDBx/mmCIF dictionary
python validate_mmcif.py mmcif_pdbx_v5_next.dic 9rff.cif

# Or use any CIF dictionary file
python validate_mmcif.py path/to/your/cif_dictionary.dic your_file.cif
```

### Using Dictionary from URL

```bash
# Using --url option (explicit) - defaults to PDBx/mmCIF dictionary
python validate_mmcif.py --url http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic 9rff.cif

# Or use any CIF dictionary URL
python validate_mmcif.py --url https://example.com/path/to/your/dictionary.dic 9rff.cif

# Or as positional argument (auto-detects URL)
python validate_mmcif.py http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic 9rff.cif
```

### Explicit Options

```bash
# Use local file
python validate_mmcif.py --file mmcif_pdbx_v5_next.dic 9rff.cif

# Use URL
python validate_mmcif.py --url http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic 9rff.cif
```

### Help

```bash
python validate_mmcif.py --help
```

## Output

The script outputs:
- Validation errors and warnings with line numbers
- JSON output for programmatic use
- Exit code 0 for success, 1 for errors

Example output:
```
Parsing dictionary: mmcif_pdbx.dic
Loaded 6652 items from dictionary
Parsing mmCIF file: model.cif
Found 1124 items in mmCIF file
Validating...

Found 4 validation issue(s):

ERROR: Line 36, Item '_pdbx_database_status.recvd_initial_deposition_date'
  Value '20250601' does not match expected type 'yyyy-mm-dd'

ERROR: Line 1643, Item '_pdbx_struct_assembly_gen.oper_expression'
  Operation expression '1' references operation ID '1' which does not exist in '_pdbx_struct_oper_list.id'

WARNING: Line 1011, Item '_refine.ls_R_factor_obs'
  Out of advisory range: Value '0.350' is above advisory maximum '0.300'

ERROR: Line 1020, Item '_refine.ls_R_factor_obs'
  Value '1.250' is above maximum allowed value '1.000'
```

### JSON Output Format

The script outputs JSON at the end with the following structure:

```json
{
  "errors": [
    {
      "line": 1238,
      "item": "_refine_ls_shell.number_reflns_R_free",
      "message": "Out of advisory range: Value '0' is below minimum advised value '1'",
      "severity": "warning",
      "column": 5,
      "start_char": 43,
      "end_char": 44
    }
  ]
}
```

**Fields:**
- `line`: Line number (1-based) where the error occurs
- `item`: The item name (e.g., `_refine_ls_shell.number_reflns_R_free`)
- `message`: Human-readable error message
- `severity`: Either `"error"` or `"warning"`
- `column`: Global column index (0-based) within the row (for loop data) or `null` for non-loop items
- `start_char`: Character start position (0-based) within the line for precise highlighting, or `null` if not available
- `end_char`: Character end position (0-based) within the line for precise highlighting, or `null` if not available

The `start_char` and `end_char` fields enable precise highlighting of the exact problematic value, even when the same value appears multiple times on a line.

## Validation Checks

The validator performs the following checks:

1. **Item Definition**: Verifies that items used in the mmCIF file are defined in the dictionary
2. **Mandatory Items**: Checks that all mandatory items are present (only for categories that exist in the file)
3. **Enumeration Values**: Validates that item values match allowed enumerations (reported as errors)
   - Handles enumerations with only `_item_enumeration.value` (no detail field)
   - Handles enumerations with both `value` and `detail` fields
4. **Data Type Validation**: Validates that values match their expected data types:
   - **Regex patterns from dictionary** - Automatically validates any type code that has a regex pattern defined in `_item_type_list.construct` (e.g., `email`, `phone`, `orcid_id`, `pdb_id`, `fax`, etc.)
   - **Hardcoded validations** for common types:
     - Date formats: `yyyy-mm-dd`, `yyyy-mm-dd:hh:mm`, `yyyy-mm-dd:hh:mm-flex`
     - Numeric types: `int`, `positive_int`, `float`, `float-range`
     - Boolean type: `boolean`
5. **Range Validation**: Checks that numeric values fall within specified minimum/maximum ranges
   - **Strictly Allowed Boundary Conditions** (`_item_range`): Violations are reported as **errors**
   - **Advisory Boundary Conditions** (`_pdbx_item_range`): Violations are reported as **warnings** with "Out of advisory range:" prefix
6. **Parent/Child Category Validation**: 
   - Verifies that when a child category is present, its parent category is also present
   - Example: If `entity_src_nat` (child) is present, `entity` (parent) must also be present
7. **Foreign Key Integrity**: Validates that foreign key values in child items exist in their parent items
   - Example: `_entity_src_nat.entity_id` values must exist in `_entity.id`
8. **Composite Key Validation**: Validates that combinations of multiple child items together match corresponding combinations in parent categories
   - Example: In `pdbx_entity_poly_domain`, the combination of `begin_mon_id` + `begin_seq_num` must match a row in `entity_poly_seq` where `mon_id` + `num` appear together as a pair
   - Validates relationships where multiple items form a composite foreign key (identified by `link_group_id` in the dictionary)
   - **Special handling for label/auth field combinations**: Categories like `struct_conn`, `pdbx_struct_conn_angle`, `geom_*`, `atom_site_anisotrop`, and others have composite keys that include both label and auth fields. The validator intelligently handles these by:
     - First attempting validation using label fields (if complete)
     - Falling back to auth fields when label fields are incomplete (e.g., when `label_seq_id` is missing)
     - Using `label_atom_id` when `auth_atom_id` is not present in the file
     - This ensures atoms referenced in these categories are properly validated against `atom_site` even when some fields are missing
9. **Operation Expression Validation**: Validates `oper_expression` values that reference operation IDs
   - Parses complex operation expressions: `(1)`, `(1,2,5)`, `(1-4)`, `(1,2)(3,4)`, `(X0)(1-5,11-15)`
   - Validates that all referenced operation IDs exist in `_pdbx_struct_oper_list.id`
   - Example: If `oper_expression` is `(1-60)`, validates that operation IDs 1 through 60 all exist
10. **Category-aware validation**: Only checks mandatory items for categories that are actually present in the mmCIF file
11. **First data block only**: By default, only validates the first data block in files containing multiple data blocks (each starting with `data_`)

## Error vs Warning Severity

The validator reports issues with different severity levels:

### Errors (Red Underline)
These are violations of mandatory constraints that must be fixed:

- **Missing Mandatory Items**: Required items that are missing from categories present in the file
- **Enumeration Violations**: Values that don't match the controlled vocabulary/enumeration list
- **Data Type Mismatches**: Values that don't match their expected data type (e.g., invalid date format, non-numeric value for integer type)
- **Strictly Allowed Range Violations** (`_item_range`): Values outside the strictly allowed boundary conditions
- **Parent Category Missing**: Child categories present but their required parent categories are missing
- **Foreign Key Integrity Violations**: Foreign key values that don't exist in their parent items
- **Composite Key Violations**: Combinations of multiple child items that don't match corresponding combinations in parent categories (including label/auth field combinations)
- **Invalid Operation Expression References**: Operation expressions referencing operation IDs that don't exist

### Warnings (Yellow Underline)
These are advisory issues that may indicate problems but are not strictly required:

- **Undefined Items**: Items used in the mmCIF file that are not defined in the dictionary (only for items not starting with `_`)
- **Advisory Range Violations** (`_pdbx_item_range`): Values outside the advisory boundary conditions (but within allowed range)

## Command-Line Options

- `--file, -f`: Path to local dictionary file (.dic)
- `--url, -u`: URL to download dictionary from
- Positional arguments: Dictionary source (auto-detects file path or URL) and mmCIF file

## Examples

```bash
# Validate with local dictionary
python validate_mmcif.py mmcif_pdbx_v5_next.dic 9rff.cif

# Validate with online dictionary
python validate_mmcif.py --url http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic 9rff.cif

# Output to file
python validate_mmcif.py mmcif_pdbx_v5_next.dic 9rff.cif > validation_results.txt
```

## Troubleshooting

### Dictionary file not found
- Check that the file path is correct
- Use absolute paths if relative paths don't work
- Or use the `--url` option to download from the internet

### Validation script errors
- Ensure Python 3.7+ is installed: `python --version`
- Check file paths are correct
- Verify dictionary file format is correct
- For large files, validation may take time (30 second timeout)

### Python not found
- Make sure Python is in your PATH
- Or use the full path to Python: `C:\Python39\python.exe validate_mmcif.py ...`

## Limitations

- Dictionary parsing is simplified and may not handle all dictionary features
- Large dictionary files may take time to parse
- Some advanced validation rules may not be implemented yet
- **Note**: Some "missing mandatory item" errors may be false positives. In the mmCIF dictionary, items are often mandatory only when their parent category is present. The current implementation checks mandatory items only for categories that exist in the file, which should reduce false positives.
- **Note**: Some foreign key validation errors may be false positives if relationships are optional or conditional. The validator checks all defined parent/child relationships from `_pdbx_item_linked_group_list`.
- **Note**: For categories with both label and auth fields (like `struct_conn`), the validator will attempt to validate using label fields first, then fall back to auth fields if label fields are incomplete. This ensures proper validation even when some fields are missing (e.g., when `label_seq_id` is "." for non-polymer entities).
- Data type validation uses regex patterns from the dictionary when available. Types like `email`, `phone`, `orcid_id`, `pdb_id`, etc. are automatically validated if they have regex patterns defined in `_item_type_list.construct`. Types without regex patterns fall back to hardcoded validation (dates, int, positive_int, float, float-range, boolean) or are accepted without format validation.

## Implemented Features

The validator currently implements comprehensive validation including:

- [x] **Data type validation** - Validates int, float, date, etc., plus automatic validation of any type with regex pattern in dictionary (email, phone, orcid_id, pdb_id, fax, etc.)
- [x] **Range validation** - Checks min/max values from dictionary constraints
- [x] **Parent/child category validation** - Validates category hierarchies
- [x] **Foreign key integrity validation** - Ensures referenced data exists
- [x] **Composite key validation** - Validates that combinations of multiple child items match corresponding combinations in parent categories
- [x] **Label/auth field composite key handling** - Special validation for categories with both label and auth fields (struct_conn, geom_*, etc.) that intelligently falls back between label and auth fields when some values are missing
- [x] **Operation expression validation** - Parses and validates complex `oper_expression` values
- [x] **Regular expression validation** - Automatically extracts and uses regex patterns from dictionary for type validation
- [x] **Conditional relationship validation** - Entity type-based validation for polymer/non-polymer relationships
- [x] **Loop structure parsing** - Parses and validates loop structures in mmCIF files
- [x] **Category key extraction** - Extracts and uses category keys from dictionary definitions

## License

MIT

## Author

Deborah Harrus, Protein Data Bank in Europe (PDBe), EMBL-EBI

## Related

This script is part of the [PDBe mmCIF Validator](https://github.com/PDBeurope/mmcif-validator) project, which also includes a Visual Studio Code extension for real-time validation.

