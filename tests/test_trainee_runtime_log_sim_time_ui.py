import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRuntimeLogSimTimeUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_runtime_log_table_has_simulation_time_column(self):
        self.assertIn("<th>本机时刻</th><th>仿真时刻</th><th>类型</th>", self.script)
        self.assertNotIn("<th>序号</th>", self.script)
        self.assertIn('<td class="mono-cell">${escapeHtml(item.simu_time || "--")}</td>', self.script)
        self.assertNotIn('<td>${escapeHtml(item.seq)}</td>', self.script)

    def test_runtime_log_entries_store_simulation_time(self):
        self.assertIn("function runtimeLogSimTime", self.script)
        self.assertIn("simu_time: runtimeLogSimTime(simuTime)", self.script)
        self.assertIn("snapshot.clock?.time || \"--\"", self.script)

    def test_runtime_log_wall_time_column_is_time_only(self):
        self.assertIn("function runtimeLogWallTimeText", self.script)
        self.assertIn("toLocaleTimeString(\"zh-CN\", { hour12: false })", self.script)
        self.assertIn("${escapeHtml(runtimeLogWallTimeText(item.wall_time))}", self.script)

    def test_runtime_log_supports_pagination_and_clear(self):
        self.assertIn('id="traineeRuntimeLogPager"', self.html)
        self.assertIn("function pagedTraineeRuntimeLogs", self.script)
        self.assertIn("function renderTraineeRuntimeLogPager", self.script)
        self.assertIn('target?.closest("#clearRuntimeLogs")', self.script)
        self.assertIn("state.runtimeLogPage = 1", self.script)

    def test_runtime_log_result_column_style_follows_new_column_order(self):
        self.assertIn(".runtime-log-table td:nth-child(5)", self.styles)
        self.assertIn(".runtime-log-row.is-ok td:nth-child(5)", self.styles)
        self.assertIn(".runtime-log-row.is-warn td:nth-child(5)", self.styles)
        self.assertIn(".runtime-log-row.is-error td:nth-child(5)", self.styles)
        self.assertNotIn(".runtime-log-row.is-ok td:nth-child(6)", self.styles)


if __name__ == "__main__":
    unittest.main()
