from __future__ import annotations

import unittest

from simu.service import _active_window


class FaultWindowBySimulationModeTest(unittest.TestCase):
    def test_year_mode_uses_start_and_end_day(self):
        fault = {"start_day": 10, "clear_day": 12}

        self.assertFalse(_active_window(fault, minute=0, absolute_minute=8 * 1440, curve_mode="year"))
        self.assertTrue(_active_window(fault, minute=0, absolute_minute=9 * 1440, curve_mode="year"))
        self.assertTrue(_active_window(fault, minute=0, absolute_minute=11 * 1440 + 1439, curve_mode="year"))
        self.assertFalse(_active_window(fault, minute=0, absolute_minute=12 * 1440, curve_mode="year"))

    def test_day_mode_uses_start_and_end_time(self):
        fault = {"start_minute": 60, "clear_minute": 120}

        self.assertFalse(_active_window(fault, minute=59, absolute_minute=59, curve_mode="day"))
        self.assertTrue(_active_window(fault, minute=60, absolute_minute=60, curve_mode="day"))
        self.assertFalse(_active_window(fault, minute=120, absolute_minute=120, curve_mode="day"))


if __name__ == "__main__":
    unittest.main()
