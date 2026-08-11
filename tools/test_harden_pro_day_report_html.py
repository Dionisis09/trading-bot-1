import hashlib
import tempfile
import unittest
from pathlib import Path

import harden_pro_day_report_html as hardener


class ProDayReportHtmlHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.report = self.root / "report.html"
        self.original = "<!doctype html>\n<html><head><title>Report</title></head><body>ok</body></html>\n"
        self.report.write_text(self.original, encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_injects_minimal_mobile_override_before_head_close(self) -> None:
        receipt = hardener.harden_file(self.report)
        result = self.report.read_text(encoding="utf-8")

        self.assertTrue(receipt["changed"])
        self.assertEqual(result.count(hardener.MARKER), 1)
        self.assertEqual(result.count(f'id="{hardener.STYLE_ID}"'), 1)
        self.assertLess(result.index(hardener.MARKER), result.index("</head>"))
        self.assertIn("overflow-wrap:anywhere", result)
        self.assertIn("contain:inline-size", result)
        self.assertIn("overflow-x:auto", result)
        self.assertIn(".portable-page-header{width:auto", result)
        self.assertIn("margin-right:-32px", result)
        self.assertIn("margin-right:-24px", result)
        self.assertEqual(result.replace(f"{hardener.STYLE_BLOCK}\n", ""), self.original)

    def test_in_place_second_pass_is_byte_identical(self) -> None:
        first = hardener.harden_file(self.report)
        before = self.report.read_bytes()
        before_hash = hashlib.sha256(before).hexdigest()
        second = hardener.harden_file(self.report)

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(self.report.read_bytes(), before)
        self.assertEqual(second["sha256"], before_hash)

    def test_can_write_a_separate_output_without_mutating_input(self) -> None:
        output = self.root / "portable" / "report.html"
        receipt = hardener.harden_file(self.report, output)

        self.assertTrue(receipt["changed"])
        self.assertEqual(self.report.read_text(encoding="utf-8"), self.original)
        self.assertIn(hardener.STYLE_BLOCK, output.read_text(encoding="utf-8"))

    def test_rejects_partial_or_conflicting_marker(self) -> None:
        self.report.write_text(
            self.original.replace("</head>", f"{hardener.MARKER}</head>"),
            encoding="utf-8",
        )
        with self.assertRaises(hardener.HardeningError):
            hardener.harden_file(self.report)

    def test_rejects_ambiguous_missing_head_close(self) -> None:
        self.report.write_text("<html><body>not packaged</body></html>", encoding="utf-8")
        with self.assertRaises(hardener.HardeningError):
            hardener.harden_file(self.report)


if __name__ == "__main__":
    unittest.main()
