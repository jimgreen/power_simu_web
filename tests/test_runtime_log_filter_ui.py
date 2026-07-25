from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeLogFilterUiTest(unittest.TestCase):
    def test_simulator_and_trainee_logs_support_type_filtering(self):
        simulator_html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        simulator_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        trainee_html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        trainee_js = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="runtimeLogTypeFilter"', simulator_html)
        self.assertIn("filteredRuntimeLogs", simulator_js)
        self.assertIn('id="traineeRuntimeLogTypeFilter"', trainee_html)
        self.assertIn("filteredTraineeRuntimeLogs", trainee_js)


if __name__ == "__main__":
    unittest.main()
