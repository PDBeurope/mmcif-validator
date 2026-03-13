# PDBe mmCIF Validator

**Version 0.1.7**

A Visual Studio Code extension to validate mmCIF/CIF files against the PDBx/mmCIF dictionary (or any CIF dictionary) with real-time error checking.

## Features

- ✅ **Real-time validation** - Automatically validates mmCIF files as you edit
- ✅ **Error highlighting** - Errors and warnings are highlighted directly in the editor with precise character positioning
- ✅ **Syntax highlighting** - Full syntax highlighting for CIF files (tags, values, data blocks, loops, etc.)
- ✅ **Hover information** - Hover over any value to see its corresponding key (`_tag`) and data block
- ✅ **Dictionary support** - Works with the PDBx/mmCIF dictionary or any CIF dictionary format
- ✅ **Flexible dictionary sources** - Uses local dictionary files or downloads from URL
- ✅ **Auto-detection** - Automatically finds dictionary files in your workspace
- ✅ **Comprehensive checks** - Validates mandatory items, enumerations, schema compliance, and duplicate category/item detection
- ✅ **Works out-of-the-box** - No configuration required!
- ✅ **Metadata completeness** - Shows how complete the file metadata is (percentage in status bar and Explorer view), with missing mandatory categories and items listed; validation errors count as not filled

## Installation

1. Open Visual Studio Code
2. Go to Extensions (Ctrl+Shift+X)
3. Search for "PDBe mmCIF Validator"
4. Click Install

## Quick Start

The extension works out-of-the-box! By default, it will automatically:
- Download and cache the PDBx/mmCIF dictionary from the official wwPDB website (http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic)
- Cache the dictionary locally for one month to balance freshness with download efficiency
- Dictionary updates are usually released in conjunction with OneDep software releases (average update frequency ~43 days)
- Validate any `.cif` files you open
- Show errors and warnings in the Problems panel with precise character positioning
- Show **metadata completeness** (percentage and missing items) in the status bar and in the **Metadata Completeness** view in the Explorer sidebar

**No configuration required!** However, you can also use any other CIF dictionary by configuring the `dictionaryPath` or `dictionaryUrl` settings (see Configuration section below).

## Usage

1. Open a `.cif` file in VSCode
2. The extension will automatically:
   - Apply syntax highlighting to make the file easier to read
   - Validate the file (on open, save, and changes with 1 second debounce)
3. **Hover over any value** to see:
   - The corresponding key (`_tag`)
   - The data block name (`DATA_*`)
   - Loop information (if in a loop)
4. Errors and warnings will be highlighted in the editor
5. Use the Command Palette (`Ctrl+Shift+P`) and run "mmCIF: Validate" to manually trigger validation
6. **Metadata completeness**: In the status bar (bottom right) you’ll see e.g. "Metadata: 75%". Click it or open **Explorer → Metadata Completeness** to see which mandatory categories or items are missing or have validation errors.

## Metadata Completeness

The extension computes a **metadata-completeness** score (0–100%) for the open mmCIF file, based on mandatory categories (for the detected experimental method: xray, em, or nmr) and mandatory items from the dictionary. For some category families (such as entity-source categories listed in `entity_src_cat.list`), the score treats them as a group where at least one category must be present, rather than requiring every category individually. This helps you see how complete the file metadata is without over-penalising equivalent representations.

- **Status bar** (bottom right): Shows e.g. `Metadata: 75% (xray)`. Hover for a short summary and a note to see the Output channel or the **Metadata Completeness** view in the Explorer sidebar for the full list of missing items.
- **Output channel**: View → Output → select "PDBe mmCIF Validator". After each validation run, a "Metadata completeness" section lists the percentage, detected method, missing categories, and missing items (with row and key when applicable). Items that have a validation error (e.g. wrong type) are marked with `[validation error]`.
- **Metadata Completeness view**: In the Explorer sidebar (left), scroll to the **Metadata Completeness** section. Expand it to see the summary, **Missing categories**, and **Missing items**. Each missing item can show row index and key (e.g. author id) and "(validation error)" when the value is present but invalid.

**Behaviour**: The score uses row-level checks (every row in a mandatory loop must have all mandatory items filled). If the experimental method cannot be determined from the file, only categories common to all methods are used and the maximum score is 50%. Items that trigger a validation error (severity "error") are counted as not filled and appear in the missing list with a validation-error flag.

## Configuration

The extension works with sensible defaults, but you can customize it in VSCode settings (File → Preferences → Settings):

### Settings

- **`mmcifValidator.dictionaryUrl`** (default: `http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic`)
  - URL to download the dictionary from. Defaults to the official PDBx/mmCIF dictionary, but you can use any CIF dictionary URL.
  - Works out-of-the-box with the default!
  
- **`mmcifValidator.dictionaryPath`** (optional)
  - Path to a local dictionary file. Can be absolute or relative to workspace root.
  - Use this to validate against any CIF dictionary file (not just PDBx/mmCIF).
  - If not set, the extension will look for common dictionary filenames in the workspace.
  
- **`mmcifValidator.pythonPath`** (default: `python`)
  - Path to Python executable. Use this if Python is not in your PATH.
  
- **`mmcifValidator.enabled`** (default: `true`)
  - Enable/disable validation

- **`mmcifValidator.validationTimeoutSeconds`** (default: `60`, range: 5–600)
  - Validation timeout in seconds. Increase for very large mmCIF files to avoid "Validation timed out" messages (e.g. set to 120 or 180).

### Example Settings

**Use default (recommended):**
```json
{
  "mmcifValidator.enabled": true
}
```

**Use local dictionary file:**
```json
{
  "mmcifValidator.dictionaryPath": "mmcif_pdbx_v5_next.dic"
}
```

**Use a different CIF dictionary (e.g., for small molecule CIF files):**
```json
{
  "mmcifValidator.dictionaryPath": "path/to/your/cif_dictionary.dic"
}
```

**Use a dictionary from a different URL:**
```json
{
  "mmcifValidator.dictionaryUrl": "https://example.com/path/to/dictionary.dic"
}
```

**Custom Python path** (use the full path to your Python executable if it is not in your PATH):
```json
{
  "mmcifValidator.pythonPath": "/usr/bin/python3"
}
```
On Windows, use escaped backslashes, e.g. `"C:\\Python39\\python.exe"`.

**Longer validation timeout** (for very large files):
```json
{
  "mmcifValidator.validationTimeoutSeconds": 120
}
```

## Validation Checks

The validator performs the following checks:

1. **Item Definition**: Verifies that items used in the mmCIF file are defined in the dictionary
2. **Mandatory Items**: Checks that all mandatory items are present (only for categories that exist in the file)
3. **Enumeration Values**: Validates that item values match allowed enumerations (reported as errors)
   - Handles enumerations with only `_item_enumeration.value` (no detail field)
   - Handles enumerations with both `value` and `detail` fields
4. **Data Type Validation**: Validates that values match their expected data types
   - **Regex patterns from dictionary** - Automatically validates any type code that has a regex pattern defined in `_item_type_list.construct` (e.g., `email`, `phone`, `orcid_id`, `pdb_id`, `fax`, etc.)
   - **Hardcoded validations** for common types:
     - Date formats: `yyyy-mm-dd`, `yyyy-mm-dd:hh:mm`, `yyyy-mm-dd:hh:mm-flex`
     - Numeric types: `int`, `positive_int`, `float`, `float-range`
     - Boolean type: `boolean`
5. **Range Validation**: Checks numeric values against minimum/maximum constraints
   - **Strictly Allowed Boundary Conditions** (`_item_range`): Violations are reported as **errors**
   - **Advisory Boundary Conditions** (`_pdbx_item_range`): Violations are reported as **warnings** with "Out of advisory range:" prefix
6. **Parent/Child Category Validation**: Validates category relationships
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
- **Data Type Mismatches**: Values that don't match their expected data type
- **Strictly Allowed Range Violations** (`_item_range`): Values outside the strictly allowed boundary conditions
- **Parent Category Missing**: Child categories present but their required parent categories are missing
- **Foreign Key Integrity Violations**: Foreign key values that don't exist in their parent items
- **Composite Key Violations**: Combinations of multiple child items that don't match corresponding combinations in parent categories (including label/auth field combinations)
- **Invalid Operation Expression References**: Operation expressions referencing operation IDs that don't exist

### Warnings (Yellow Underline)
These are advisory issues that may indicate problems but are not strictly required:

- **Undefined Items**: Items used in the mmCIF file that are not defined in the dictionary
- **Advisory Range Violations** (`_pdbx_item_range`): Values outside the advisory boundary conditions (but within allowed range)

## Requirements

- **Python 3.7 or higher** - The extension uses a Python script for validation
- **Internet connection** (optional) - Only needed if using the default dictionary URL

## Troubleshooting

### Extension not working

1. Check that Python is installed and accessible: `python --version`
2. Check the VSCode Output panel (View → Output → Select "PDBe mmCIF Validator")
3. Verify your settings in File → Preferences → Settings

### Python not found

1. Make sure Python is installed
2. Add Python to your system PATH
3. Or set `mmcifValidator.pythonPath` to the full path to Python

### Validation errors

1. Check that the dictionary file/URL is accessible
2. Verify the mmCIF file format is correct
3. Large files may take time to validate; the timeout is configurable in settings (default 60 seconds, max 600). Increase `mmcifValidator.validationTimeoutSeconds` if you see "Validation timed out" on large files.

## Standalone Python Script

This extension includes a standalone Python validation script that can be used independently of VSCode. See the `python-script/` folder for:
- The Python validation script (`validate_mmcif.py`)
- Command-line usage instructions
- Standalone validation without VSCode
- Enhanced JSON output with precise character positions and column indices for programmatic error handling
- **Metadata completeness**: When run by the extension, the script also outputs a `metadata_completeness` object in the JSON (percentage, filled/total counts, method, missing categories and items)
- Exit codes: 0 for success, 1 for errors (useful for CI/CD integration)

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## Acknowledgments

This extension includes syntax highlighting and hover functionality based on work by Heikki Kainulainen (hmkainul) from the [vscode-cif extension](https://github.com/hmkainul/vscode-cif). Used under MIT License.

## License

MIT

## Author

Deborah Harrus, Protein Data Bank in Europe (PDBe), EMBL-EBI
