from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VirtualTableRenderingUiTest(unittest.TestCase):
    def _script(self, console: str) -> str:
        return (ROOT / "simu" / "web" / console / "app.js").read_text(encoding="utf-8")

    def _style(self, console: str) -> str:
        return (ROOT / "simu" / "web" / console / "styles.css").read_text(encoding="utf-8")

    def test_simulator_measurement_table_uses_virtual_rows_for_large_models(self):
        script = self._script("simulator")
        style = self._style("simulator")

        self.assertIn("function virtualTableWindow", script)
        self.assertIn("function handleVirtualTableScroll", script)
        self.assertIn('data-virtual-table="measurementCompare"', script)
        self.assertIn("const virtualRows = virtualTableWindow(\"measurementCompare\", rows)", script)
        self.assertIn("virtualRows.rows.map((row)", script)
        self.assertIn("renderVirtualSpacerRow(virtualRows.beforeHeight, 8)", script)
        self.assertIn(".virtual-table-scroll", style)
        self.assertIn(".virtual-table-spacer", style)

    def test_trainee_measurement_table_uses_virtual_rows_for_large_models(self):
        script = self._script("trainee")
        style = self._style("trainee")

        self.assertIn("function virtualTableWindow", script)
        self.assertIn("function handleVirtualTableScroll", script)
        self.assertIn('data-virtual-table="measurement"', script)
        self.assertIn("const virtualRows = virtualTableWindow(\"measurement\", rows)", script)
        self.assertIn("virtualRows.rows.map((item)", script)
        self.assertIn("renderVirtualSpacerRow(virtualRows.beforeHeight, 8)", script)
        self.assertIn(".virtual-table-scroll", style)
        self.assertIn(".virtual-table-spacer", style)


if __name__ == "__main__":
    unittest.main()
