from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeviceTreeMultiSelectUiTest(unittest.TestCase):
    def _script(self, console: str) -> str:
        return (ROOT / "simu" / "web" / console / "app.js").read_text(encoding="utf-8")

    def test_simulator_device_trees_support_ctrl_and_shift_multi_select(self):
        script = self._script("simulator")

        for required in (
            "deviceTreeFilterSelection",
            "updateDeviceTreeFilterSelection",
            "selectDeviceTreeRangeItems",
            "deviceFilterMatches",
            "isDeviceTreeNodeActive",
            "isDeviceTreeParentActive",
            "event.ctrlKey || event.metaKey",
            "event.shiftKey",
        ):
            self.assertIn(required, script)
        for setter in (
            "setDeviceFaultFilter(",
            "setMeasurementFaultFilter(",
            "setMeasurementCompareFilter(",
            "setGridModelFilter(",
            "setRuntimeDeviceFilter(",
            "setModeFilter(",
        ):
            self.assertIn("event", script.split(setter, 1)[1].split(");", 1)[0])

    def test_trainee_device_trees_support_ctrl_and_shift_multi_select(self):
        script = self._script("trainee")

        for required in (
            "deviceTreeFilterSelection",
            "updateDeviceTreeFilterSelection",
            "selectDeviceTreeRangeItems",
            "deviceFilterMatches",
            "isDeviceTreeNodeActive",
            "isDeviceTreeParentActive",
            "event.ctrlKey || event.metaKey",
            "event.shiftKey",
        ):
            self.assertIn(required, script)
        self.assertIn("setTraineeModelFilter(selection[1], selection[2], event, button)", script)
        self.assertIn("selectTreeFilter(selection[0], selection[1], selection[2], event, button", script)


if __name__ == "__main__":
    unittest.main()
