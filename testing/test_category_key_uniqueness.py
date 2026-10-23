#!/usr/bin/env python3
"""Dictionary category-key uniqueness.

Run from the repository root:
  python testing/test_category_key_uniqueness.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "vscode-extension" / "python-script"
sys.path.insert(0, str(SCRIPT_DIR))

from cif_parser import MmCIFParser  # noqa: E402
from dict_parser import DictionaryParser  # noqa: E402
from validator import MmCIFValidator  # noqa: E402

DICTIONARY = """
data_test_dict
#
save_audit_author
   _category.id              audit_author
   _category.mandatory_code  no
   _category_key.name  "_audit_author.pdbx_ordinal"
   _category_examples.case
;
    loop_
    _category_key.name
      "_should_not_be_a_key"
    ;
     1
;
save_
#
save_audit_conform
   _category.id              audit_conform
   _category.mandatory_code  no
   loop_
   _category_key.name
     "_audit_conform.dict_name"
     "_audit_conform.dict_version"
   #
   loop_
   _category_group.id
     inclusive_group
save_
#
save_entity
   _category.id              entity
   _category.mandatory_code  no
   _category_key.name  "_entity.id"
save_
#
"""

AUDIT_AUTHOR_MESSAGE = (
    "Duplicate _audit_author.pdbx_ordinal in this file: 1. "
    "Each _audit_author.pdbx_ordinal must appear at most once."
)
CONFORM_MESSAGE = (
    "Duplicate category key (_audit_conform.dict_name, _audit_conform.dict_version) "
    "in this file: cif_core.dic, 2.3.1. Each combination must appear at most once."
)
ENTITY_MESSAGE = (
    "Duplicate _entity.id in this file: 1. Each entity id must appear at most once."
)


def _write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def _validate(dictionary_path: Path, cif_text: str, directory: Path, name: str):
    cif_path = _write(directory, name, cif_text)
    dictionary = DictionaryParser(dictionary_path).parse()
    mmcif = MmCIFParser(cif_path)
    mmcif.parse()
    return dictionary, MmCIFValidator(dictionary, mmcif).validate()


class CategoryKeyUniquenessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self._tmp.name)
        self.dictionary_path = _write(self.directory, "mini.dic", DICTIONARY)

    def tearDown(self):
        self._tmp.cleanup()

    def test_parser_reads_inline_and_loop_keys_and_skips_examples(self):
        dictionary = DictionaryParser(self.dictionary_path).parse()
        self.assertEqual(
            dictionary.categories["audit_author"]["keys"],
            ["_audit_author.pdbx_ordinal"],
        )
        self.assertEqual(
            dictionary.categories["audit_conform"]["keys"],
            ["_audit_conform.dict_name", "_audit_conform.dict_version"],
        )
        self.assertEqual(dictionary.categories["entity"]["keys"], ["_entity.id"])

    def test_duplicate_audit_author_ordinal_is_an_error_on_each_row(self):
        _, errors = _validate(
            self.dictionary_path,
            """
data_test
#
loop_
_audit_author.name
_audit_author.pdbx_ordinal
"Djeghader, A." 1
"Soulimane, T." 1
#
""",
            self.directory,
            "duplicate_ordinal.cif",
        )
        hits = [err for err in errors if err.item == "_audit_author.pdbx_ordinal"]
        self.assertEqual(len(hits), 2, hits)
        self.assertTrue(all(err.severity == "error" for err in hits))
        self.assertTrue(all(err.message == AUDIT_AUTHOR_MESSAGE for err in hits))
        self.assertEqual(sorted(err.line for err in hits), [7, 8])

    def test_distinct_ordinals_are_accepted(self):
        _, errors = _validate(
            self.dictionary_path,
            """
data_test
#
loop_
_audit_author.name
_audit_author.pdbx_ordinal
"Djeghader, A." 1
"Soulimane, T." 2
#
""",
            self.directory,
            "unique_ordinal.cif",
        )
        hits = [err for err in errors if "pdbx_ordinal" in err.message]
        self.assertEqual(hits, [])

    def test_missing_ordinals_are_not_treated_as_duplicates(self):
        _, errors = _validate(
            self.dictionary_path,
            """
data_test
#
loop_
_audit_author.name
_audit_author.pdbx_ordinal
"Djeghader, A." ?
"Soulimane, T." .
#
""",
            self.directory,
            "missing_ordinal.cif",
        )
        hits = [err for err in errors if "pdbx_ordinal" in err.message]
        self.assertEqual(hits, [])

    def test_duplicate_composite_category_key_is_an_error(self):
        _, errors = _validate(
            self.dictionary_path,
            """
data_test
#
loop_
_audit_conform.dict_name
_audit_conform.dict_version
cif_core.dic 2.3.1
cif_core.dic 2.3.1
#
""",
            self.directory,
            "duplicate_conform.cif",
        )
        hits = [err for err in errors if err.item == "_audit_conform.dict_name"]
        self.assertEqual(len(hits), 2, hits)
        self.assertTrue(all(err.message == CONFORM_MESSAGE for err in hits))
        self.assertTrue(all(err.severity == "error" for err in hits))

    def test_distinct_composite_keys_are_accepted(self):
        _, errors = _validate(
            self.dictionary_path,
            """
data_test
#
loop_
_audit_conform.dict_name
_audit_conform.dict_version
cif_core.dic 2.3.1
mmcif_pdbx.dic 5.0
#
""",
            self.directory,
            "unique_conform.cif",
        )
        hits = [err for err in errors if err.item == "_audit_conform.dict_name"]
        self.assertEqual(hits, [])

    def test_explicit_uniqueness_rule_is_not_reported_twice(self):
        _, errors = _validate(
            self.dictionary_path,
            """
data_test
#
loop_
_entity.id
_entity.type
1 polymer
1 polymer
#
""",
            self.directory,
            "duplicate_entity.cif",
        )
        hits = [err for err in errors if err.item == "_entity.id"]
        self.assertEqual(len(hits), 2, hits)
        self.assertTrue(all(err.message == ENTITY_MESSAGE for err in hits))


if __name__ == "__main__":
    unittest.main()
