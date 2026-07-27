from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MeasurementIncrementalRefreshUiTest(unittest.TestCase):
    def test_simulator_realtime_measurement_table_updates_live_cells_without_full_rebuild(self):
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function measurementCompareTableStructureKey", script)
        self.assertIn("function updateMeasurementCompareTableLiveCells", script)
        self.assertIn("data-measurement-row-key", script)
        self.assertIn("data-measurement-live-field", script)
        self.assertIn("measurementCompareTableStructureKey(rows)", script)
        self.assertIn("updateMeasurementCompareTableLiveCells(rows, selectedKey)", script)


if __name__ == "__main__":
    unittest.main()
