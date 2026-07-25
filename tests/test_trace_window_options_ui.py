from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraceWindowOptionsUiTest(unittest.TestCase):
    def test_simulator_and_trainee_offer_week_and_month_trace_windows(self):
        simulator_html = (ROOT / "simu" / "web" / "simulator" / "index.html").read_text(encoding="utf-8")
        trainee_html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        simulator_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        for html in (simulator_html, trainee_html):
            self.assertIn('<option value="1440">1日</option>', html)
            self.assertNotIn('<option value="1440">24小时</option>', html)
            self.assertIn('<option value="10080">1周</option>', html)
            self.assertIn('<option value="43200">1月</option>', html)
            self.assertIn('<option value="525600">1年</option>', html)
        self.assertIn("第${day + 1}天", simulator_js)
        self.assertIn("formatYearTraceTickLabel", simulator_js)
        self.assertIn("TRACE_HISTORY_LIMIT", simulator_js)


if __name__ == "__main__":
    unittest.main()
