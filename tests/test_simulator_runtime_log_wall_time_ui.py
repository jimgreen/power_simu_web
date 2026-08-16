import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SimulatorRuntimeLogWallTimeUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/simulator/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/simulator/styles.css").read_text(encoding="utf-8")

    def test_runtime_log_table_has_wall_and_simulation_time_columns(self):
        self.assertIn("本机时刻 仿真时刻 类型 对象 结果 概要", self.html)
        self.assertNotIn("序号 本机时刻 仿真时刻 类型 对象 结果 概要", self.html)
        self.assertIn("<th>本机时刻</th>", self.script)
        self.assertIn("<th>仿真时刻</th>", self.script)
        self.assertNotIn("<th>序号</th>", self.script)
        self.assertNotIn('<td class="numeric-cell">${escapeHtml(item.seq)}</td>', self.script)

    def test_runtime_log_wall_time_is_formatted_for_display(self):
        self.assertIn("function runtimeLogWallTimeText", self.script)
        self.assertIn("${escapeHtml(runtimeLogWallTimeText(item.wall_time))}", self.script)
        self.assertIn("hour12: false", self.script)
        self.assertIn('text.match(/(?:T|\\s)(\\d{2}:\\d{2}:\\d{2})', self.script)

    def test_runtime_log_uses_simu_time_field_and_not_old_sim_time_field(self):
        self.assertIn('simu_time: item.simu_time || item.sim_time || item.time || "--"', self.script)
        self.assertIn("${escapeHtml(item.simu_time)}", self.script)
        self.assertNotIn("${escapeHtml(item.sim_time)}</td>", self.script)

    def test_runtime_log_supports_pagination_and_clear(self):
        self.assertIn('id="runtimeLogPager"', self.html)
        self.assertIn('id="clearRuntimeLogs"', self.html)
        self.assertIn("function pagedRuntimeLogs", self.script)
        self.assertIn("function renderRuntimeLogPager", self.script)
        self.assertIn('api("/api/runtime-logs/clear"', self.script)

    def test_runtime_log_result_column_style_matches_six_columns(self):
        self.assertIn(".runtime-log-row.is-ok td:nth-child(5)", self.styles)
        self.assertIn(".runtime-log-row.is-warn td:nth-child(5)", self.styles)
        self.assertIn(".runtime-log-row.is-error td:nth-child(5)", self.styles)
        self.assertNotIn(".runtime-log-row.is-ok td:nth-child(6)", self.styles)


if __name__ == "__main__":
    unittest.main()
