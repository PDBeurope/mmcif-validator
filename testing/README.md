# mmCIF Validator Testing Suite

This directory contains the regression test suite for the mmCIF validator: test CIF files, the runner script, and generated output for comparison.

## Directory layout

```
testing/
├── README.md                    # This file
├── run_validation_suite.py      # Run validator on all CIFs, save/compare output
├── validation_baseline.txt       # Saved reference output (generate with --generate-baseline)
├── validation_output.txt        # Latest run output (compare to baseline)
└── cif_files/                   # All test .cif files
    ├── 6ijw.cif ... 8q6j.cif    # Real PDB entries (method + metadata completeness)
    └── test_*.cif               # Synthetic tests (validation cases)
```

## How to use the suite

Run from the **repository root**:

```bash
# Run validation on all CIFs; write results to testing/validation_output.txt
python testing/run_validation_suite.py

# Generate or refresh the baseline (do this once before code changes, or to accept new behaviour)
python testing/run_validation_suite.py --generate-baseline
```

Or from the `testing/` directory:

```bash
cd testing
python run_validation_suite.py
python run_validation_suite.py --generate-baseline
```

### Regression workflow

1. **Before changing validator code:** Run with `--generate-baseline` to create `validation_baseline.txt`.
2. Make your code changes.
3. **After changes:** Run without `--generate-baseline` (writes to `validation_output.txt`).
4. **Compare:** Diff the two files to see what changed.
   - **Windows:** `fc testing\validation_baseline.txt testing\validation_output.txt`
   - **Linux/macOS:** `diff testing/validation_baseline.txt testing/validation_output.txt`
5. Review the diff: new or removed errors may be expected (e.g. fixes) or regressions.

### Custom paths

```bash
python testing/run_validation_suite.py --dict path/to/mmcif.dic --tests path/to/cif_folder
python testing/run_validation_suite.py --generate-baseline -o path/to/my_baseline.txt
```

By default the suite uses the PDBx/mmCIF dictionary from `http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic`; you can override this with `--dict`.

### Logging

The suite logs to **stderr** so you can redirect or diff the main output file without mixing in log lines. It logs:

- Dictionary source, test directory, and output file path
- Number of CIF files to process
- With `--verbose` / `-v`: each file as it is validated and its exit code (passed/failed)
- Final line: where output was written and how many files had validation issues

Example with verbose:

```bash
python testing/run_validation_suite.py -v
```

---

## Test files overview

### Real PDB entries: metadata completeness and method detection

These files are full (or substantial) PDB mmCIF entries. They are used to check:

- **Metadata completeness:** The validator’s JSON output includes a `metadata_completeness` object (percentage, filled/total counts, missing categories, missing items). These files exercise that logic with realistic method-specific mandatory categories.
- **Method recognition:** The validator infers experimental method from which categories are present in the file (method-specific mandatory category lists). The reported `method_detected` in the JSON should match the method implied by the entry.

| File       | _exptl.method           | Expected method_detected | Purpose                          |
|-----------|--------------------------|--------------------------|-----------------------------------|
| **6ijw.cif** | SOLUTION NMR             | `nmr`                    | NMR method + completeness         |
| **6qvt.cif** | X-RAY DIFFRACTION        | `xray`                   | X-ray method + completeness       |
| **6ssp.cif** | X-RAY DIFFRACTION        | `xray`                   | X-ray method + completeness       |
| **7q5a.cif** | ELECTRON MICROSCOPY      | `em`                     | EM method + completeness          |
| **8ozl.cif** | ELECTRON MICROSCOPY      | `em`                     | EM method + completeness          |
| **8pps.cif** | X-RAY DIFFRACTION        | `xray`                   | X-ray method + completeness       |
| **8pwh.cif** | ELECTRON MICROSCOPY      | `em`                     | EM method + completeness          |
| **8q6j.cif** | ELECTRON MICROSCOPY      | `em`                     | EM method + completeness          |

Method detection is based on **which categories exist** in the file (from the completeness lists), not on the literal value of `_exptl.method`; the table above documents how these entries are expected to be classified.

---

### Synthetic test files: validation cases

Each `test_*.cif` file is a small CIF chosen to trigger one or more specific validator behaviours (errors or warnings). Use these to confirm that the validator reports the right issue for each scenario.

| File | Case(s) covered |
|------|------------------|
| **test_duplicate_item.cif** | Same item appears twice in one block (e.g. `_entry.id` twice). Expect: duplicate item error. |
| **test_duplicate_category.cif** | Same category given in two separate blocks (e.g. two `entity` blocks). Expect: duplicate category error. |
| **test_format_error_entity_poly.cif** | Malformed `entity_poly`: loop with one data row followed by key–value pairs of the same category. Expect: duplicate category or format error once the parser records the loop block. |
| **test_loop_row_mismatch.cif** | Loop with wrong number of values in a row (e.g. two columns, second row has one value). Exercises loop parsing and may surface row-length or parsing errors. |
| **test_multiple_data_blocks.cif** | File contains two `data_` blocks. Expect: only the first block is validated (parser stops at second `data_`). |
| **test_value_out_of_range.cif** | Item with type `positive_int` (e.g. `_em_image_scans.dimension_height`) set to `0`. Expect: type/range error. |
| **test_type_checks_pdb_id_and_date.cif** | Invalid `pdb_id`-like value and invalid date format. Expect: type errors for the offending values. |
| **test_enum_invalid_em_software.cif** | `_em_software.name` value not in the dictionary enumeration (e.g. `phaser_voyager.em_placement`). Expect: enumeration error (once `_pdbx_item_enumeration` is parsed). |
| **test_asym_id_valid_invalid.cif** | `_atom_site.label_asym_id` / `auth_asym_id` with valid (e.g. `A`) and invalid (e.g. `B:Axp`) values. Expect: asym_id format errors for the invalid values when enforced. |
| **test_mandatory_missing_item.cif** | Category present but a mandatory item missing (e.g. `entity` without `_entity.id`). Expect: missing mandatory item error. |
| **test_fk_missing_parent.cif** | Child references non-existent parent (e.g. `atom_site.label_asym_id` = `Z` with no `struct_asym.id` = `Z`). Expect: foreign-key / parent-missing error. |
| **test_composite_fk_mismatch.cif** | Rows in `atom_site` that may violate composite key or parent–child consistency (e.g. label_asym_id + label_comp_id + label_seq_id). Exercises composite-FK logic. |
| **test_undefined_items.cif** | Item names not in the dictionary (e.g. `_my_local_category.foo`, `_not_defined_item`). Expect: undefined-item warnings/errors as implemented. |
| **test_advisory_range_warning.cif** | Value outside advisory (e.g. `_exptl_crystal.density_Matthews` = 10.0 vs recommended range). Expect: advisory-range warning, not hard error. |
| **test_multiline_and_quoted_values.cif** | Loop containing multi-line text (semicolon-delimited) and quoted values with spaces. Exercises parsing of multi-line and quoted loop values. |

---

## Output files

| File | Purpose |
|------|--------|
| `validation_baseline.txt` | Reference output; generate with `--generate-baseline`. |
| `validation_output.txt` | Output of the latest run; compare to baseline after code changes. |

Paths in the output are normalized to `<REPO>` so that diffs are portable across machines.
