import json
import subprocess
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

    def test_page_uses_strategy_plus_curve_log_tabs_with_one_splitter(self):
        strategy_pos = self.html.index('<h2>控制策略</h2>')
        chart_pos = self.html.index('<h2>综合功率趋势</h2>')
        logs_pos = self.html.index('<h2>控制日志</h2>')
        self.assertLess(strategy_pos, chart_pos)
        self.assertLess(chart_pos, logs_pos)
        self.assertIn('data-vertical-split="trainee-renewable"', self.html)
        self.assertNotIn('data-vertical-split="trainee-renewable-lower"', self.html)
        self.assertIn('data-renewable-detail-tab="trend"', self.html)
        self.assertIn('data-renewable-detail-tab="logs"', self.html)

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
        self.assertIn("serialized_trend = copy.deepcopy(trend)", self.backend)
        self.assertIn('"trend": serialized_trend', self.backend)
        apply_block = self.script.split("function applyRenewableControlState", 1)[1].split(
            "async function refreshRenewableControlState",
            1,
        )[0]
        self.assertIn("payload.trend", apply_block)
        self.assertIn("state.renewableTrendHistory", apply_block)
        self.assertNotIn("function appendRenewableTrend", self.script)

    def test_browser_requests_compact_deltas_and_merges_the_inclusive_tail(self):
        for helper in ("mergeRenewableTrendDelta", "mergeRenewableControlLogDelta"):
            if f"function {helper}" not in self.script:
                self.fail(f"{helper} is missing")
        self.assertIn('params.set("compact", "1");', self.script)
        self.assertIn('params.set("after_log_seq"', self.script)
        self.assertIn('params.set("after_trend_sample_key"', self.script)

        helpers = "function renewableTrendLifecycleChanged" + self.script.split(
            "function renewableTrendLifecycleChanged",
            1,
        )[1].split("function applyRenewableControlState", 1)[0]
        body = """
const trend = mergeRenewableTrendDelta(
  [
    { sampleKey: "a", runId: 1, stepCount: 1, minute: 1, loadKw: 10 },
    { sampleKey: "b", runId: 1, stepCount: 2, minute: 2, loadKw: 20 },
  ],
  [
    { sampleKey: "b", runId: 1, stepCount: 2, minute: 2, loadKw: 21 },
    { sampleKey: "c", runId: 1, stepCount: 3, minute: 3, loadKw: 30 },
  ],
  false,
);
const logs = mergeRenewableControlLogDelta(
  [{ seq: 2, detail: "two" }, { seq: 1, detail: "one" }],
  [{ seq: 3, detail: "three" }],
  false,
);
process.stdout.write(JSON.stringify({ trend, logs }));
"""
        result = subprocess.run(
            ["node", "-e", f"{helpers}\n{body}"],
            check=True,
            capture_output=True,
            text=True,
        )
        merged = json.loads(result.stdout)
        self.assertEqual([point["sampleKey"] for point in merged["trend"]], ["a", "b", "c"])
        self.assertEqual(merged["trend"][1]["loadKw"], 21)
        self.assertEqual([item["seq"] for item in merged["logs"]], [3, 2, 1])

    def test_browser_discards_mirrored_trend_when_simulation_lifecycle_restarts(self):
        render_block = self.script.split("function renderSnapshot", 1)[1].split(
            "function renderReceiveMode",
            1,
        )[0]
        lifecycle_block = render_block.split("if (traceLifecycleChanged)", 1)[1].split("}", 1)[0]
        self.assertIn("state.renewableTrendHistory = [];", lifecycle_block)

    def test_browser_keeps_only_latest_monotonic_backend_trend_segment(self):
        if "function renewableTrendLifecycleChanged" not in self.script:
            self.fail("renewable trend lifecycle normalization helper is missing")
        helpers = "function renewableTrendLifecycleChanged" + self.script.split(
            "function renewableTrendLifecycleChanged",
            1,
        )[1].split("function applyRenewableControlState", 1)[0]
        body = """
const points = [
  { runId: 1, stepCount: 10, minute: 50 },
  { runId: 1, stepCount: 11, minute: 55 },
  { runId: 1, stepCount: 0, minute: 0 },
  { runId: 1, stepCount: 1, minute: 1 },
];
process.stdout.write(JSON.stringify(latestRenewableTrendSegment(points).map((point) => point.minute)));
"""
        result = subprocess.run(
            ["node", "-e", f"{helpers}\n{body}"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(result.stdout), [0, 1])

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

    def test_chart_reuses_legend_cursor_and_active_tab_redraw_systems(self):
        self.assertIn(
            'initTraceChartInteractions("renewableTrend", "renewableTrendChart", drawRenewableTrendChart)',
            self.script,
        )
        self.assertIn('chartKey === "renewableTrend" ? drawRenewableTrendChart', self.script)
        self.assertNotIn('"trainee-renewable-lower"', self.script)
        self.assertIn("requestAnimationFrame(drawRenewableTrendChart)", self.script)
        self.assertIn(".renewable-detail-tabs", self.styles)

    def test_active_renewable_page_redraws_the_shared_trend(self):
        render_block = self.script.split("function renderRenewableControl", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]
        self.assertIn("renderRenewableDetailTabs();", render_block)

    def test_middle_chart_reserves_space_for_axes_and_legend_without_panel_overlap(self):
        self.assertIn('data-renewable-detail-pane="trend"', self.html)
        trend_panel_block = self.styles.split(".renewable-trend-panel {", 1)[1].split("}", 1)[0]
        legend_block = self.styles.split(
            ".measurement-trace-legend.renewable-trend-legend {",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("padding: 0;", trend_panel_block)
        self.assertIn("min-height: 35px;", legend_block)


if __name__ == "__main__":
    unittest.main()
