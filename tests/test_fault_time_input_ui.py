from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FaultTimeInputUiTest(unittest.TestCase):
    def test_fault_windows_use_time_inputs_and_minute_conversion(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function minuteToTimeInput", app_js)
        self.assertIn("function timeInputToMinute", app_js)
        self.assertIn('data-device-field="start_minute" type="time"', app_js)
        self.assertIn('data-device-field="clear_minute" type="time"', app_js)
        self.assertIn('data-meas-field="start_minute" type="time"', app_js)
        self.assertIn('data-meas-field="clear_minute" type="time"', app_js)
        self.assertIn("timeInputToMinute(rawValue, fault[field])", app_js)


if __name__ == "__main__":
    unittest.main()
