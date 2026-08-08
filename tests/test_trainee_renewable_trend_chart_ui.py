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
            "acLoad": "交流负荷",
            "dcLoad": "直流负荷",
            "dieselCurrent": "柴发当前值",
            "dieselTarget": "柴发目标值",
            "acRenewableCurrent": "交流新能源当前值",
            "acRenewableTarget": "交流新能源目标值",
            "dcRenewableCurrent": "直流新能源当前值",
            "dcRenewableTarget": "直流新能源目标值",
            "acGridFollowingStorageCurrent": "交流跟网储能当前值",
            "acGridFollowingStorageTarget": "交流跟网储能目标值",
            "acGridFollowingStorageSoc": "交流跟网储能SOC",
            "dcGridFollowingStorageCurrent": "直流跟网储能当前值",
            "dcGridFollowingStorageTarget": "直流跟网储能目标值",
            "dcGridFollowingStorageSoc": "直流跟网储能SOC",
            "acGridFormingStorageCurrent": "交流构网储能当前值",
            "acGridFormingStorageTarget": "交流构网储能目标值",
            "acGridFormingStorageSoc": "交流构网储能SOC",
            "dcGridFormingStorageCurrent": "直流构网储能当前值",
            "dcGridFormingStorageTarget": "直流构网储能目标值",
            "dcGridFormingStorageSoc": "直流构网储能SOC",
            "acdcCurrent": "AC/DC变流器当前值",
            "acdcTarget": "AC/DC变流器目标值",
        }
        for key, label in expected_series.items():
            self.assertIn(f'data-chart-series="{key}"', self.html)
            self.assertIn(label, self.html)

    def test_curve_selector_is_a_left_multilevel_checkbox_list(self):
        self.assertIn('id="renewableTrendWorkspace"', self.html)
        self.assertIn('id="renewableTrendSeriesPanel"', self.html)
        for scope, label in (("ac", "交流"), ("dc", "直流"), ("system", "系统")):
            with self.subTest(scope=scope):
                self.assertIn(f'data-renewable-series-scope="{scope}"', self.html)
                self.assertIn(f'<summary>{label}</summary>', self.html)
        self.assertGreaterEqual(
            self.html.count('type="checkbox" data-chart-toggle="renewableTrend"'),
            22,
        )
        self.assertNotIn(
            'class="measurement-trace-legend renewable-trend-legend"',
            self.html,
        )
        self.assertIn("function setChartSeriesVisibility", self.script)
        self.assertIn("RENEWABLE_TREND_DEFAULT_VISIBLE_SERIES", self.script)
        self.assertIn("renewableTrendSeriesAvailable", self.script)

    def test_curve_selector_defaults_to_current_power_and_filters_absent_device_groups(self):
        draw_block = self.script.split("function drawRenewableTrendChart", 1)[1].split(
            "function renderRenewableControl",
            1,
        )[0]
        self.assertIn("ensureRenewableTrendSeriesSelection(seriesDefs)", draw_block)
        self.assertIn("renewableTrendSeriesAvailable(series, metrics)", draw_block)
        self.assertIn("renderRenewableTrendSeriesAvailability(metrics)", draw_block)
        self.assertIn('group: "ac-grid-following-storage"', draw_block)
        self.assertIn('group: "dc-grid-forming-storage"', draw_block)
        self.assertIn('group: "system-acdc"', draw_block)

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

    def test_chart_uses_current_target_power_series_and_live_soc_right_axis(self):
        draw_block = self.script.split("function drawRenewableTrendChart", 1)[1].split(
            "function renderRenewableControl",
            1,
        )[0]
        self.assertIn('const chartKey = "renewableTrend"', draw_block)
        for field in (
            "acLoadKw",
            "dcLoadKw",
            "dieselCurrentKw",
            "dieselTargetKw",
            "acRenewableCurrentKw",
            "acRenewableTargetKw",
            "dcRenewableCurrentKw",
            "dcRenewableTargetKw",
            "acGridFollowingStorageCurrentKw",
            "acGridFollowingStorageTargetKw",
            "acGridFollowingStorageSocPercent",
            "dcGridFollowingStorageCurrentKw",
            "dcGridFollowingStorageTargetKw",
            "dcGridFollowingStorageSocPercent",
            "acGridFormingStorageCurrentKw",
            "acGridFormingStorageTargetKw",
            "acGridFormingStorageSocPercent",
            "dcGridFormingStorageCurrentKw",
            "dcGridFormingStorageTargetKw",
            "dcGridFormingStorageSocPercent",
            "acdcCurrentKw",
            "acdcTargetKw",
        ):
            self.assertIn(field, draw_block)
        self.assertIn('axis: "right"', draw_block)
        self.assertIn("drawChartCursor", draw_block)
        self.assertIn("pixelPoints.length === 1", draw_block)

    def test_backend_compact_trend_keeps_all_power_targets_and_storage_soc(self):
        for field in (
            "acLoadKw",
            "dcLoadKw",
            "dieselCurrentKw",
            "dieselTargetKw",
            "acRenewableCurrentKw",
            "acRenewableTargetKw",
            "dcRenewableCurrentKw",
            "dcRenewableTargetKw",
            "acGridFollowingStorageCurrentKw",
            "acGridFollowingStorageTargetKw",
            "acGridFollowingStorageSocPercent",
            "dcGridFollowingStorageCurrentKw",
            "dcGridFollowingStorageTargetKw",
            "dcGridFollowingStorageSocPercent",
            "acGridFormingStorageCurrentKw",
            "acGridFormingStorageTargetKw",
            "acGridFormingStorageSocPercent",
            "dcGridFormingStorageCurrentKw",
            "dcGridFormingStorageTargetKw",
            "dcGridFormingStorageSocPercent",
            "acdcCurrentKw",
            "acdcTargetKw",
        ):
            with self.subTest(field=field):
                self.assertIn(f'"{field}"', self.backend)

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

    def test_middle_chart_reserves_space_for_axes_and_left_series_panel_without_overlap(self):
        self.assertIn('data-renewable-detail-pane="trend"', self.html)
        trend_panel_block = self.styles.split(".renewable-trend-panel {", 1)[1].split("}", 1)[0]
        workspace_block = self.styles.split(
            ".renewable-trend-workspace {",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("padding: 0;", trend_panel_block)
        self.assertIn("grid-template-columns", workspace_block)
        self.assertIn("minmax(190px, 228px)", workspace_block)
        self.assertIn(".renewable-trend-series-panel", self.styles)
        self.assertIn(".renewable-trend-chart-surface", self.styles)


if __name__ == "__main__":
    unittest.main()
