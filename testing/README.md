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
| **test_cross_check_dictionary_enum.cif** | Cross-item dictionary enumeration compatibility check (e.g. `_diffrn_detector.type` incompatible with `_diffrn_detector.detector`). Expect: cross-check error from dictionary detail mapping. |
| **test_cross_check_conditional_refine_mr_starting_model_skipped_when_initial_refinement_present.cif** | Conditional required: `_refine.pdbx_method_to_determine_struct` is molecular replacement and `_pdbx_initial_refinement_model` is present; `_refine.pdbx_starting_model` is `?`. Expect: no cross-check error for `pdbx_starting_model` (superseded by `pdbx_initial_refinement_model`); file is otherwise minimal so validation can pass end-to-end. |
| **test_cross_check_conditional_refine_mr_starting_model_required_without_initial_refinement.cif** | Conditional required: molecular replacement without `pdbx_initial_refinement_model`. Expect: cross-check error requiring `pdbx_starting_model` when it is missing. |
| **test_cross_check_date_order_invalid_coords_before_deposition.cif** | Pairwise date order: `_pdbx_database_status.recvd_initial_deposition_date` must not be after `date_coordinates`. Expect: cross-check error. |
| **test_cross_check_date_order_valid_deposition_coords.cif** | Positive case: initial deposition on or before coordinates date. Expect: no date-order error from this rule pair. |
| **test_cross_check_date_order_valid_same_day.cif** | Edge case: same calendar day for both dates (`<=`). Expect: no date-order error. |
| **test_cross_check_date_order_edge_missing_coords.cif** | Edge case: `date_coordinates` missing (`?`). Expect: no date-order error when the secondary date is absent. |
| **test_cross_check_date_order_invalid_begin_after_end.cif** | Date order: `date_begin_deposition` must not be after `date_end_processing`. Expect: cross-check error. |
| **test_cross_check_date_order_invalid_form_after_initial.cif** | Date order: `date_deposition_form` must not be after `recvd_initial_deposition_date`. Expect: cross-check error. |
| **test_cross_check_uniqueness_invalid_entity_id.cif** | Uniqueness: two `entity` rows share the same `_entity.id`. Expect: duplicate-key error on each duplicate row (same message). |
| **test_cross_check_uniqueness_valid_entity_ids.cif** | Uniqueness positive case: two distinct `_entity.id` values. Expect: no duplicate-entity-id error. |
| **test_cross_check_uniqueness_invalid_struct_asym_id.cif** | Uniqueness: two `_struct_asym` rows share the same `_struct_asym.id`. Expect: duplicate-key errors. |
| **test_cross_check_uniqueness_valid_struct_asym_ids.cif** | Uniqueness positive case: distinct asym ids. Expect: no duplicate-asym-id error. |
| **test_cross_check_uniqueness_invalid_entity_poly_entity_id.cif** | Uniqueness: two `_entity_poly` rows with the same `entity_id`. Expect: duplicate-key errors. |
| **test_cross_check_uniqueness_valid_entity_poly_entity_id.cif** | Uniqueness positive case: one `entity_poly` row per entity. Expect: no duplicate-entity_poly error. |
| **test_cross_check_make_mandatory_subtypes.cif** | Subtype-gated required-item check for `makeMandatorySubtypes` (`em_3d_reconstruction` missing `resolution_method`). Expect: no subtype-specific error when subtype context is absent; error appears when subtype context includes `EM-single_part` or related subtype. |
| **test_cross_check_cross_reference_selectors.cif** | Selector-gated cross-reference check for `cross_reference_full` (`expt: coded`, `code: PDB`). Expect: selector rule skipped when code context is absent; cross-reference error appears when runtime context includes `requested_codes=['PDB']`. |
| **test_procedural_diffrn_wavelength_invalid_single_for_laue.cif** | Procedural validator migration: `diffrn_source.pdbx_wavelength_list` against `diffrn_radiation.pdbx_diffrn_protocol`. Expect: error when protocol is `LAUE` but wavelength list is a single value. |
| **test_procedural_diffrn_wavelength_valid_single.cif** | Procedural validator positive case. Expect: no procedural wavelength-list error when protocol is `SINGLE WAVELENGTH` and list has one value. |
| **test_procedural_diffrn_wavelength_edge_missing.cif** | Procedural validator edge case. Expect: no procedural wavelength-list error when wavelength value is missing (`?`). |
| **test_procedural_diffrn_wavelength_invalid_empty_list_laue.cif** | Procedural validator: `pdbx_wavelength_list` is an empty quoted value (`''`) while `pdbx_diffrn_protocol` is `LAUE` for the same `diffrn_id`. Expect: procedural error that the wavelength list must not be empty (may appear together with parent-category checks if `diffrn` is absent). |
| **test_procedural_diffrn_wavelength_invalid_empty_list_single.cif** | Same as above for protocol `SINGLE WAVELENGTH`. Expect: procedural empty-list error. |
| **test_procedural_diffrn_wavelength_edge_empty_mismatched_diffrn_id.cif** | Edge case: empty wavelength on `diffrn_id` 1 but LAUE protocol only on a different `diffrn_id`. Expect: no procedural empty-list error (no matching radiation row for that id). |
| **test_procedural_database_related_invalid_pdb_id.cif** | Procedural validator migration: `pdbx_database_related.db_id` format check for `db_name=PDB`. Expect: error for invalid PDB/deposition accession format. |
| **test_procedural_database_related_valid_pdb_id.cif** | Procedural validator positive case for `pdbx_database_related.db_id`. Expect: no procedural accession-format error for valid PDB ID. |
| **test_procedural_database_related_edge_non_target_db.cif** | Procedural validator edge case for non-target `db_name` values. Expect: no procedural accession-format error when `db_name` is not one of the configured procedural checks. |
| **test_procedural_struct_ref_seq_invalid_genbank_accession.cif** | Procedural validator migration: `pdbx_struct_ref_seq_depositor_info.db_accession` format for `db_name=GB`. Expect: error for invalid GenBank accession format. |
| **test_procedural_struct_ref_seq_valid_genbank_accession.cif** | Procedural validator positive case for `pdbx_struct_ref_seq_depositor_info.db_accession`. Expect: no procedural accession-format error for valid GenBank accession format. |
| **test_procedural_struct_ref_seq_edge_empty_accession.cif** | Procedural validator edge case for optional `db_accession`. Expect: no procedural accession-format error when accession is missing (`?`). |
| **test_procedural_struct_ref_seq_invalid_uniprot_accession.cif** | Procedural validator migration: `pdbx_struct_ref_seq_depositor_info.db_accession` format for `db_name=UNP`. Expect: error for invalid UniProt accession format. |
| **test_procedural_struct_ref_seq_valid_uniprot_accession.cif** | Procedural validator positive case for `db_name=UNP`. Expect: no procedural accession-format error for valid UniProt accession format. |
| **test_procedural_initial_refinement_invalid_pdb_accession.cif** | Procedural validator migration: conditional accession format for `pdbx_initial_refinement_model` when type is `experimental model` and source is `PDB`. Expect: error for invalid PDB accession format. |
| **test_procedural_initial_refinement_valid_pdb_accession.cif** | Procedural validator positive case for `pdbx_initial_refinement_model` (`experimental model` + `PDB`). Expect: no procedural accession-format error for valid PDB accession format. |
| **test_procedural_initial_refinement_edge_non_matching_condition.cif** | Procedural validator edge case for condition-gated rule. Expect: no procedural accession-format error when row does not match configured condition (e.g. source `Other`). |
| **test_procedural_initial_refinement_invalid_pdbdev_accession.cif** | Procedural validator migration: conditional accession format for `pdbx_initial_refinement_model` when type is `integrative model` and source is `PDB-Dev`. Expect: error for invalid PDB-Dev accession format. |
| **test_procedural_initial_refinement_valid_pdbdev_accession.cif** | Procedural validator positive case for `integrative model` + `PDB-Dev`. Expect: no procedural accession-format error for valid PDB-Dev accession format. |
| **test_procedural_initial_refinement_invalid_alphafold_accession.cif** | Procedural validator migration for `in silico model` + `AlphaFold`. Expect: error for invalid AlphaFold accession format. |
| **test_procedural_initial_refinement_valid_alphafold_accession.cif** | Procedural validator positive case for `in silico model` + `AlphaFold`. Expect: no procedural accession-format error for valid AlphaFold accession format. |
| **test_procedural_initial_refinement_invalid_modelarchive_accession.cif** | Procedural validator migration for `in silico model` + `ModelArchive`. Expect: error for invalid ModelArchive accession format. |
| **test_procedural_initial_refinement_valid_modelarchive_accession.cif** | Procedural validator positive case for `in silico model` + `ModelArchive`. Expect: no procedural accession-format error for valid ModelArchive accession format. |
| **test_procedural_initial_refinement_invalid_integrative_source_name.cif** | Procedural validator migration: for `pdbx_initial_refinement_model` with `type=integrative model`, `source_name` must be `PDB-Dev`. Expect: error when source name is not `PDB-Dev`. |
| **test_procedural_initial_refinement_valid_integrative_source_name.cif** | Procedural validator positive case for integrative source-name rule. Expect: no procedural source-name error when `source_name` is `PDB-Dev`. |
| **test_procedural_initial_refinement_edge_non_integrative_source_name.cif** | Procedural validator edge case for condition-gated source-name rule. Expect: no procedural source-name error when `type` is not `integrative model`. |
| **test_procedural_entity_poly_warning_homopolymer_ala.cif** | Procedural validator migration: `entity_poly.pdbx_seq_one_letter_code` all ALA (homopolymer). Expect: **warning** (poly-ALA homopolymer guidance). |
| **test_procedural_entity_poly_warning_stretch_ala.cif** | Procedural validator migration: sequence contains ten consecutive `A` (poly-ALA stretch) but is not all-ALA. Expect: **warning** (stretch guidance). |
| **test_procedural_entity_poly_edge_normal_sequence.cif** | Procedural validator edge case: ordinary one-letter sequence with no poly-ALA homopolymer or 10+ `A` stretch. Expect: no procedural entity_poly sequence warnings. |

---

## Output files

| File | Purpose |
|------|--------|
| `validation_baseline.txt` | Reference output; generate with `--generate-baseline`. |
| `validation_output.txt` | Output of the latest run; compare to baseline after code changes. |

Paths in the output are normalized to `<REPO>` so that diffs are portable across machines.
