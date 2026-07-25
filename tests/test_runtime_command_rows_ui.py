from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeCommandRowsUiTest(unittest.TestCase):
    def test_runtime_commands_are_split_into_remote_control_and_adjustment_rows(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function runtimeRemoteControlRows", app_js)
        self.assertIn("function runtimeRemoteAdjustmentRows", app_js)
        self.assertIn("遥控指令", app_js)
        self.assertIn("遥调指令", app_js)
        self.assertIn("指令项", app_js)
        self.assertIn("renderRuntimeCommandTable", app_js)


if __name__ == "__main__":
    unittest.main()
