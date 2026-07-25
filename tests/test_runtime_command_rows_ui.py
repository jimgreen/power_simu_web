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
        self.assertIn("指令刷新时刻", app_js)
        self.assertIn("refresh_time", app_js)
        self.assertIn("function runtimeCommandRefreshTime", app_js)
        self.assertIn("issued_absolute_minute", app_js)
        self.assertIn("expires_at_absolute_minute", app_js)
        self.assertIn("renderRuntimeCommandTable", app_js)

    def test_runtime_command_rows_select_trace_on_click_or_double_click(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("selectedRuntimeCommandKey", app_js)
        self.assertIn("function runtimeCommandTraceKey", app_js)
        self.assertIn("function selectRuntimeCommandTrace", app_js)
        self.assertIn("data-runtime-command-row-key", app_js)
        self.assertIn("data-runtime-command-row-label", app_js)
        self.assertIn('event.target.closest("[data-runtime-command-row-key]")', app_js)
        self.assertIn('document.addEventListener("dblclick"', app_js)
        self.assertIn("selectedRuntimeCommandTraceSeries", app_js)
        self.assertIn("point.commands", app_js)


if __name__ == "__main__":
    unittest.main()
