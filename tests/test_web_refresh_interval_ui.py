from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WebRefreshIntervalUiTest(unittest.TestCase):
    def test_simulator_and_trainee_refresh_every_one_second(self):
        simulator_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        trainee_js = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        self.assertIn("setInterval(refresh, 1000);", simulator_js)
        self.assertIn("setInterval(refresh, 1000);", trainee_js)
        self.assertNotIn("setInterval(refresh, 2000);", simulator_js)
        self.assertNotIn("setInterval(refresh, 2000);", trainee_js)


if __name__ == "__main__":
    unittest.main()
