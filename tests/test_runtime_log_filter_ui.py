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

    def test_trainee_log_heading_and_actions_share_one_row(self):
        trainee_html = (ROOT / "simu" / "web" / "trainee" / "index.html").read_text(encoding="utf-8")
        history_section = trainee_html.split('<section class="page-section" data-page="history">', 1)[1].split(
            "</section>\n      </main>",
            1,
        )[0]

        self.assertRegex(
            history_section,
            r'(?s)<div class="panel-head runtime-log-panel-head">\s*'
            r'<h2>运行日志</h2>\s*'
            r'<div class="runtime-log-toolbar">.*?'
            r'id="historyCount".*?'
            r'id="traineeRuntimeLogTypeFilter".*?'
            r'id="clearRuntimeLogs".*?'
            r'</div>\s*</div>',
        )
        self.assertEqual(history_section.count('class="runtime-log-toolbar"'), 1)


if __name__ == "__main__":
    unittest.main()
