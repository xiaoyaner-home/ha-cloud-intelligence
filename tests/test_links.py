"""The documentation guard rejects broken paths and anchors, offline."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.check_links import anchors, local_links


class LinkTests(unittest.TestCase):
    def test_heading_anchors_include_duplicates_and_inline_code(self):
        self.assertEqual(
            anchors("# Heading!\n## Heading!\n### `Code`\n"), {"heading", "heading-1", "code"}
        )

    def test_local_paths_anchors_and_external_deduplication(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "[ok](docs.md#target) [missing](absent.md) [bad](docs.md#absent) "
                "[one](https://example.com/) [two](https://example.com/) "
                "[self](#readme)\n# Readme\n"
            )
            (root / "docs.md").write_text("# Target\n")
            errors, external, count = local_links(root)
            self.assertEqual(count, 6)
            self.assertEqual(external, {"https://example.com/"})
            self.assertEqual(len(errors), 2)
            self.assertTrue(any("absent.md" in error for error in errors))
            self.assertTrue(any("docs.md#absent" in error for error in errors))

    def test_escape_and_unsupported_schemes_are_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("[escape](../no.md) [unsafe](file:///no.md)")
            errors, external, count = local_links(root)
            self.assertEqual(len(errors), 2)
            self.assertEqual(count, 2)
            self.assertEqual(external, set())
