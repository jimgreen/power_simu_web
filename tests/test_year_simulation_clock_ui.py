from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class YearSimulationClockUiTest(unittest.TestCase):
    def test_year_mode_clock_includes_month_and_day(self):
        app_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("formatSimulationClock", app_js)
        self.assertIn('state.curveMode !== "year"', app_js)
        self.assertIn("monthDays", app_js)
        self.assertIn('classList.toggle("is-year-mode"', app_js)
        self.assertIn(".clock-readout.is-year-mode", css)


if __name__ == "__main__":
    unittest.main()
