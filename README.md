# PDBe mmCIF Validator

**Version 0.1.5**

Real-time VSCode extension and standalone Python script for validating mmCIF/CIF files against the PDBx/mmCIF dictionary or any CIF dictionary.

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

For detailed information about all validation checks, error severity levels, and configuration options, see the [extension README](vscode-extension/README.md).

## Requirements

- **Python 3.7 or higher** - Required for both extension and standalone script
- **Internet connection** (optional) - Only needed if using default dictionary URL

## Documentation

- **[Extension Documentation](vscode-extension/README.md)** - Complete guide for VSCode extension users
- **[Python Script Documentation](vscode-extension/python-script/README.md)** - Command-line usage and API details

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## Acknowledgments

This extension includes syntax highlighting and hover functionality based on work by Heikki Kainulainen (hmkainul) from the [vscode-cif extension](https://github.com/hmkainul/vscode-cif). Used under MIT License.

## License

MIT

## Author

Deborah Harrus, Protein Data Bank in Europe (PDBe), EMBL-EBI
