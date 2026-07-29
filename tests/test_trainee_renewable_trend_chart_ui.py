import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRenewableTrendChartUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.backend = (ROOT / "simu/renewable_control.py").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_page_uses_top_chart_bottom_structure_with_two_splitters(self):
        strategy_pos = self.html.index('<h2>控制策略</h2>')
        chart_pos = self.html.index('<h2>综合功率趋势</h2>')
        logs_pos = self.html.index('<h2>控制日志</h2>')
        self.assertLess(strategy_pos, chart_pos)
        self.assertLess(chart_pos, logs_pos)
        self.assertIn('data-vertical-split="trainee-renewable"', self.html)
        self.assertIn('data-vertical-split="trainee-renewable-lower"', self.html)

    def test_middle_chart_has_time_window_and_all_requested_series(self):
        self.assertIn('id="renewableTrendWindow"', self.html)
        self.assertIn('id="renewableTrendChart"', self.html)
        expected_series = {
            "load": "负荷功率",
            "diesel": "柴发功率",
            "storage": "储能功率",
            "storageSoc": "储能SOC",
            "renewable": "新能源功率",
            "acdcCurrent": "变流器当前值",
            "acdcTarget": "变流器目标值",
        }
        for key, label in expected_series.items():
            self.assertIn(f'data-chart-series="{key}"', self.html)
            self.assertIn(label, self.html)

    def test_history_is_generated_once_by_the_backend_and_mirrored_by_browser_pages(self):
        self.assertIn("def _update_trend", self.backend)
        self.assertIn("state.trend.append(point)", self.backend)
        self.assertIn('"trend": copy.deepcopy(state.trend)', self.backend)
        apply_block = self.script.split("function applyRenewableControlState", 1)[1].split(
            "async function refreshRenewableControlState",
            1,
        )[0]
        self.assertIn("payload.trend", apply_block)
        self.assertIn("state.renewableTrendHistory", apply_block)
        self.assertNotIn("function appendRenewableTrend", self.script)

    def test_chart_uses_left_power_axis_and_right_soc_axis(self):
        draw_block = self.script.split("function drawRenewableTrendChart", 1)[1].split(
            "function renderRenewableControl",
            1,
        )[0]
        self.assertIn('const chartKey = "renewableTrend"', draw_block)
        for field in (
            "loadKw",
            "dieselKw",
            "storageKw",
            "storageSocPercent",
            "renewableKw",
            "acdcCurrentKw",
            "acdcTargetKw",
        ):
            self.assertIn(field, draw_block)
        self.assertIn('axis: "right"', draw_block)
        self.assertIn("drawChartCursor", draw_block)
        self.assertIn("pixelPoints.length === 1", draw_block)

    def test_chart_reuses_legend_cursor_and_splitter_redraw_systems(self):
        self.assertIn(
            'initTraceChartInteractions("renewableTrend", "renewableTrendChart", drawRenewableTrendChart)',
            self.script,
        )
        self.assertIn('chartKey === "renewableTrend" ? drawRenewableTrendChart', self.script)
        self.assertIn('"trainee-renewable-lower"', self.script)
        self.assertIn("drawRenewableTrendChart()", self.script)
        self.assertIn(".renewable-lower-layout.vertical-split-workspace", self.styles)

    def test_active_renewable_page_redraws_the_shared_trend(self):
        render_block = self.script.split("function renderRenewableControl", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]
        self.assertIn("drawRenewableTrendChart();", render_block)

    def test_middle_chart_reserves_space_for_axes_and_legend_without_panel_overlap(self):
        self.assertIn('data-vertical-split-min-top="200"', self.html)
        self.assertIn('data-vertical-split-min-bottom="90"', self.html)
        trend_panel_block = self.styles.split(".renewable-trend-panel {", 1)[1].split("}", 1)[0]
        legend_block = self.styles.split(
            ".measurement-trace-legend.renewable-trend-legend {",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("padding: 0;", trend_panel_block)
        self.assertIn("min-height: 35px;", legend_block)


if __name__ == "__main__":
    unittest.main()
