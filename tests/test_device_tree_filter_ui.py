from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeviceTreeFilterUiTest(unittest.TestCase):
    def test_simulator_device_trees_have_filter_inputs(self):
        html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        for scope in ("model", "faultDevice", "faultMeasurement", "mode", "runtime", "measurement"):
            self.assertIn(f'data-device-tree-filter-scope="{scope}"', html)

        self.assertIn("deviceTreeSearchText", script)
        self.assertIn("filterDeviceTreeGroups", script)
        self.assertIn("renderDeviceTreeFilterEmpty", script)
        self.assertIn("data-device-tree-filter-scope", script)
        self.assertIn(".device-tree-filter", styles)

    def test_simulator_device_trees_preserve_scroll_during_refresh(self):
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function updateDeviceTreeHtml", script)
        self.assertIn("container.scrollTop", script)
        self.assertIn("requestAnimationFrame(() => {", script)
        for direct_render in (
            "renderMeasurementCompareDeviceTree",
            "renderRuntimeDeviceTree",
            "renderGridModelDeviceTree",
            "renderFaultDeviceTree",
            "renderFaultMeasurementTree",
            "renderModeDeviceTree",
        ):
            block = script.split(f"function {direct_render}(", 1)[1].split(f"function set", 1)[0]
            self.assertIn("updateDeviceTreeHtml(container,", block)
        self.assertIn("overflow-anchor: none;", styles)

    def test_trainee_device_trees_have_filter_inputs(self):
        html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "trainee" / "styles.css").read_text(encoding="utf-8")

        for scope in ("model", "measurement", "control"):
            self.assertIn(f'data-device-tree-filter-scope="{scope}"', html)

        self.assertIn("deviceTreeSearchText", script)
        self.assertIn("filterDeviceTreeGroups", script)
        self.assertIn("renderDeviceTreeFilterEmpty", script)
        self.assertIn("data-device-tree-filter-scope", script)
        self.assertIn(".device-tree-filter", styles)

    def test_trainee_device_trees_preserve_scroll_during_refresh(self):
        script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "trainee" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function updateDeviceTreeHtml", script)
        self.assertIn("container.scrollTop", script)
        self.assertIn("requestAnimationFrame(() => {", script)
        for direct_render in (
            "renderDeviceTree",
            "renderTraineeModelDeviceTree",
        ):
            block = script.split(f"function {direct_render}(", 1)[1].split(f"function selectTreeFilter", 1)[0]
            self.assertIn("updateDeviceTreeHtml(container,", block)
        self.assertIn("overflow-anchor: none;", styles)


if __name__ == "__main__":
    unittest.main()
