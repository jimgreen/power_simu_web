from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FaultTimeInputUiTest(unittest.TestCase):
    def test_fault_windows_follow_year_or_day_simulation_mode(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function minuteToTimeInput", app_js)
        self.assertIn("function timeInputToMinute", app_js)
        self.assertIn("function faultWindowFields", app_js)
        self.assertIn("function dayOfYearToMonthDay", app_js)
        self.assertIn("function monthDayToDayOfYear", app_js)
        self.assertIn('type="${windowFields.inputType}"', app_js)
        self.assertIn('placeholder="${windowFields.placeholder}"', app_js)
        self.assertIn('min="${windowFields.min}"', app_js)
        self.assertIn('max="${windowFields.max}"', app_js)
        self.assertIn("start_day", app_js)
        self.assertIn("clear_day", app_js)
        self.assertIn('"1月1日"', app_js)
        self.assertIn('return `${month + 1}月${remain}日`;', app_js)
        self.assertIn("monthDayToDayOfYear(rawValue", app_js)
        self.assertIn("timeInputToMinute(rawValue, fault[field])", app_js)


if __name__ == "__main__":
    unittest.main()
