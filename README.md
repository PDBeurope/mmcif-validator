# PDBe mmCIF Validator

**Version 0.1.8**

Real-time VSCode extension and standalone Python script for validating mmCIF/CIF files against the PDBx/mmCIF dictionary or any CIF dictionary.

In 0.1.8, alongside a new regression testing suite, the core validator and dictionary parser were improved:

- Fixed loop parsing so mixed loop/frame blocks are recorded correctly and malformed sections produce duplicate/format errors.
- Tightened `label_asym_id` / `auth_asym_id` validation by applying the `asym_id` type pattern (when present in the dictionary), rejecting non-alphanumeric chain IDs like `B:Axp`.
- Taught the dictionary parser to understand loop-style `_item.name` / `_item.category_id` / `_item.mandatory_code` blocks and to load enumerations from `_pdbx_item_enumeration` (e.g. for `_em_software.name`).
- Made error, warning, and metadata-completeness missing categories/items outputs deterministic (sorted), simplifying regression testing and diffs.

## Overview

The PDBe mmCIF Validator provides comprehensive validation of mmCIF files against CIF dictionaries, available in two complementary implementations:

- **Visual Studio Code Extension**: Real-time validation with error highlighting as you edit
- **Standalone Python Script**: Command-line tool for batch processing and CI/CD integration

Both implementations share the same validation engine, ensuring consistent results across different usage scenarios.

## Features

- ✅ **Real-time validation** - Automatically validates mmCIF/CIF files as you edit (VSCode extension)
- ✅ **Error highlighting** - Errors and warnings highlighted directly in the editor with precise character positioning
- ✅ **Syntax highlighting** - Full syntax highlighting for CIF files
- ✅ **Hover information** - Hover over values to see corresponding tags and data blocks
- ✅ **Dictionary flexibility** - Works with PDBx/mmCIF dictionary or any CIF dictionary format
- ✅ **Comprehensive validation** - Validates mandatory items, enumerations, data types, ranges, foreign keys, composite keys, and more
- ✅ **Works out-of-the-box** - No configuration required (uses default dictionary URL)
- ✅ **Configurable validation timeout** - Increase timeout for very large files (extension setting, default 60s, max 10 min)
- ✅ **No dependencies** - Python script uses only standard library
- ✅ **Metadata completeness** - Extension shows a metadata-completeness percentage (status bar and Explorer view), lists missing mandatory categories/items, and treats validation errors as not filled

## Quick Start

### VSCode Extension

1. Open Visual Studio Code
2. Go to Extensions (Ctrl+Shift+X)
3. Search for "PDBe mmCIF Validator"
4. Click Install

The extension works out-of-the-box and automatically downloads the PDBx/mmCIF dictionary. See the [extension README](vscode-extension/README.md) for detailed documentation.

### Standalone Python Script

```bash
# Validate with default dictionary URL
python vscode-extension/python-script/validate_mmcif.py --url http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic model.cif

# Validate with local dictionary file
python vscode-extension/python-script/validate_mmcif.py --file mmcif_pdbx.dic model.cif
```

See the [Python script README](vscode-extension/python-script/README.md) for detailed usage instructions.

## Validation Capabilities

The validator performs comprehensive checks including:

- Item definition validation
- Mandatory item presence (category-aware)
- Enumeration value validation
- Data type validation (including regex patterns from dictionary)
- Range constraints (strictly allowed vs advisory)
- Parent/child category relationships
- Foreign key integrity
- Composite key validation
- Complex operation expression parsing
- Duplicate category and item detection (loop and frame format)

**Metadata completeness** (extension): When validating a `.cif` file, the extension also computes a metadata-completeness score (0–100%). It uses mandatory categories per experimental method (xray/em/nmr from bundled lists), including an entity-source group where any one of several categories is sufficient, and deposition-mandatory items from the dictionary. The score is shown in the status bar and in a **Metadata Completeness** view in the Explorer sidebar; missing categories and items (including row-level missing or invalid values) are listed there and in the Output channel. If the experimental method cannot be determined from the file, only common categories are used and the score is capped at 50%.

For detailed information about all validation checks, error severity levels, and configuration options, see the [extension README](vscode-extension/README.md).

## Requirements

- **Python 3.7 or higher** - Required for both extension and standalone script
- **Internet connection** (optional) - Only needed if using default dictionary URL

## Documentation

- **[Extension Documentation](vscode-extension/README.md)** - Complete guide for VSCode extension users
- **[Python Script Documentation](vscode-extension/python-script/README.md)** - Command-line usage and API details
- **[Testing Suite](testing/README.md)** - Regression test suite (run validator on CIFs, diff against baseline)

## Releases

Pre-built VS Code extension packages (`.vsix`) are published on the [GitHub Releases](https://github.com/PDBeurope/mmcif-validator/releases) page. To install a specific version, download the `.vsix` from the desired release and install it via **Extensions → ⋯ → Install from VSIX...**.

Releases are created from git tags (e.g. `v0.1.8`). Pushing a version tag triggers a GitHub Action that builds the extension and attaches the `.vsix` to the corresponding release.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## Acknowledgments

This extension includes syntax highlighting and hover functionality based on work by Heikki Kainulainen (hmkainul) from the [vscode-cif extension](https://github.com/hmkainul/vscode-cif). Used under MIT License.

## License

MIT

## Author

Deborah Harrus, Protein Data Bank in Europe (PDBe), EMBL-EBI
