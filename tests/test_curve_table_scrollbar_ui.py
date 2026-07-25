from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CurveTableScrollbarUiTest(unittest.TestCase):
    def test_curve_table_has_a_persistent_vertical_scrollbar(self):
        css = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("overflow-y: scroll", css)
        self.assertIn("scrollbar-gutter: stable", css)
        self.assertIn(".curve-table-wrap::-webkit-scrollbar", css)
        self.assertIn(".curve-table-wrap::-webkit-scrollbar-thumb", css)


if __name__ == "__main__":
    unittest.main()
