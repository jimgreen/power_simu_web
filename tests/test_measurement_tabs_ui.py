from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MeasurementTabsUiTest(unittest.TestCase):
    def test_realtime_measurements_are_split_into_telemetry_and_signal_tabs(self):
        surfaces = (
            (
                ROOT / "simu/web/simulator/index.html",
                ROOT / "simu/web/simulator/app.js",
                "measurementCompareTable",
                "data-measurement-compare-tab",
            ),
            (
                ROOT / "simu/web/trainee/index.html",
                ROOT / "simu/web/trainee/app.js",
                "measurementTable",
                "data-measurement-tab",
            ),
        )
        for html_path, script_path, table_id, tab_attr in surfaces:
            with self.subTest(surface=html_path.parent.name):
                html = html_path.read_text(encoding="utf-8")
                script = script_path.read_text(encoding="utf-8")

                self.assertIn(f'id="{table_id}"', html)
                self.assertIn('role="tablist" aria-label="量测类型"', script)
                self.assertIn(tab_attr, script)
                self.assertIn("遥测", script)
                self.assertIn("遥信", script)
                self.assertIn("function measurementTelemetryRows", script)
                self.assertIn("function measurementSignalRows", script)
                self.assertIn("function setMeasurement", script)
                self.assertIn("isSignalMeasurement(row)", script)
                self.assertIn('RUN_STAT', script)
                self.assertIn('STATUS', script)


if __name__ == "__main__":
    unittest.main()
