from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeCommandPerformanceUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu" / "web" / "trainee" / "styles.css").read_text(encoding="utf-8")

    def test_command_page_renders_only_active_tab_with_virtual_rows_and_live_cells(self):
        self.assertIn("function traineeCommandTableStructureKey", self.script)
        self.assertIn("function updateTraineeCommandTableLiveCells", self.script)
        self.assertIn("function renderTraineeCommandTable", self.script)
        self.assertIn('const activeTab = state.activeControlTab === "remote-adjustment" ? "remote-adjustment" : "remote-control";', self.script)
        self.assertIn('const activeRows = activeTab === "remote-adjustment"', self.script)
        self.assertIn('const virtualRows = virtualTableWindow(`traineeCommand:${activeTab}`, activeRows);', self.script)
        self.assertIn('container.setAttribute("data-virtual-table", `traineeCommand:${activeTab}`);', self.script)
        self.assertIn("renderVirtualSpacerRow(virtualRows.beforeHeight, columnCount)", self.script)
        self.assertIn(".runtime-device-wrap.virtual-table-scroll", self.styles)

    def test_command_refresh_skips_hidden_tab_live_measurement_work(self):
        self.assertIn("function remoteAdjustmentRows(devices, snapshot = state.snapshot || {}, options = {})", self.script)
        self.assertIn("includeMeasurements: activeTab === \"remote-adjustment\"", self.script)
        self.assertIn("measurement: options.includeMeasurements === false", self.script)
        self.assertNotIn("renderRunControls(devices);\n  renderSetpointControls(devices);", self.script)


if __name__ == "__main__":
    unittest.main()
