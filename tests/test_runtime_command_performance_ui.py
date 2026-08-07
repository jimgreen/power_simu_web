from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeCommandPerformanceUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

    def test_runtime_command_rows_use_precomputed_indexes(self):
        self.assertIn("function runtimeCommandBuildContext", self.script)
        self.assertIn("function runtimeCommandRefreshIndex", self.script)
        self.assertIn("function runtimeMeasurementRowsByDevice", self.script)
        self.assertIn("commandRefreshIndex", self.script)
        self.assertIn("measurementRowsByDevice", self.script)
        self.assertIn("runtimeCommandRowsForDevices(devices, measurements = state.snapshot?.measurements || {}, context", self.script)
        self.assertIn("runtimeCommandRefreshInfo(dev, \"set_value\", key, state.snapshot || {}, context)", self.script)
        self.assertIn("runtimeMeasurementPair(dev, meta, measurements, context)", self.script)

    def test_runtime_command_table_renders_only_active_tab_with_virtual_rows_and_live_cell_updates(self):
        self.assertIn("function renderRuntimeCommandTabs", self.script)
        self.assertIn("function runtimeCommandTableStructureKey", self.script)
        self.assertIn("function updateRuntimeCommandTableLiveCells", self.script)
        self.assertIn("const activeRows = activeTab === \"remote_adjustment\"", self.script)
        self.assertIn("const virtualRows = virtualTableWindow(`runtimeCommand:${activeTab}`, activeRows)", self.script)
        self.assertIn("container.dataset.runtimeCommandStructureKey === structureKey", self.script)
        self.assertIn("updateRuntimeCommandTableLiveCells(virtualRows.rows)", self.script)
        self.assertIn("renderVirtualSpacerRow(virtualRows.beforeHeight, 11)", self.script)
        self.assertIn("renderRuntimeCommandTable(virtualRows.rows", self.script)
        self.assertIn('key.startsWith("runtimeCommand") && currentPageName() === "runtime"', self.script)
        self.assertIn(".runtime-command-table-wrap", self.styles)

    def test_runtime_command_refresh_reuses_measurement_index_for_either_active_tab(self):
        self.assertIn("includeMeasurements: true", self.script)
        self.assertIn("runtimeRemoteControlRows(selectedDevices, context, { live: activeTab === \"remote_control\" })", self.script)
        self.assertIn("runtimeRemoteAdjustmentRows(selectedDevices, state.snapshot?.measurements || {}, context, { live: activeTab === \"remote_adjustment\" })", self.script)
        self.assertIn("function runtimeSnapshotDevicesByKey", self.script)
        self.assertIn("snapshotDevicesByKey", self.script)


if __name__ == "__main__":
    unittest.main()
