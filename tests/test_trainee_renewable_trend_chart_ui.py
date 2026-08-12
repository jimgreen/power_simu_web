import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


EXPECTED_TREND_SERIES = {
    "acRenewableCurrent": ("renewableAcCurrentKw", "acRenewableCurrentKw"),
    "acRenewableTarget": ("renewableAcTargetKw", "acRenewableTargetKw"),
    "acRenewableMaxAvailable": ("renewableAcMaxAvailableKw", "acRenewableMaxAvailableKw"),
    "acWindCurrent": ("renewableAcWindCurrentKw", "acWindCurrentKw"),
    "acWindTarget": ("renewableAcWindTargetKw", "acWindTargetKw"),
    "acWindMaxAvailable": ("renewableAcWindMaxAvailableKw", "acWindMaxAvailableKw"),
    "acPvCurrent": ("renewableAcPvCurrentKw", "acPvCurrentKw"),
    "acPvTarget": ("renewableAcPvTargetKw", "acPvTargetKw"),
    "acPvMaxAvailable": ("renewableAcPvMaxAvailableKw", "acPvMaxAvailableKw"),
    "acGridFollowingStorageCurrent": ("renewableAcGridFollowingStorageCurrentKw", "acGridFollowingStorageCurrentKw"),
    "acGridFollowingStorageTarget": ("renewableAcGridFollowingStorageTargetKw", "acGridFollowingStorageTargetKw"),
    "acGridFollowingStorageSoc": ("renewableAcGridFollowingStorageSoc", "acGridFollowingStorageSocPercent"),
    "acGridFormingStorageCurrent": ("renewableAcGridFormingStorageCurrentKw", "acGridFormingStorageCurrentKw"),
    "acGridFormingStorageTarget": ("renewableAcGridFormingStorageTargetKw", "acGridFormingStorageTargetKw"),
    "acGridFormingStorageSoc": ("renewableAcGridFormingStorageSoc", "acGridFormingStorageSocPercent"),
    "acDieselCurrent": ("renewableAcDieselCurrentKw", "acDieselCurrentKw"),
    "acDieselMin": ("renewableAcDieselMinKw", "acDieselMinKw"),
    "acDieselTarget": ("renewableAcDieselTargetKw", "acDieselTargetKw"),
    "acLoad": ("renewableAcLoadKw", "acLoadKw"),
    "dcRenewableCurrent": ("renewableDcCurrentKw", "dcRenewableCurrentKw"),
    "dcRenewableTarget": ("renewableDcTargetKw", "dcRenewableTargetKw"),
    "dcRenewableMaxAvailable": ("renewableDcMaxAvailableKw", "dcRenewableMaxAvailableKw"),
    "dcWindCurrent": ("renewableDcWindCurrentKw", "dcWindCurrentKw"),
    "dcWindTarget": ("renewableDcWindTargetKw", "dcWindTargetKw"),
    "dcWindMaxAvailable": ("renewableDcWindMaxAvailableKw", "dcWindMaxAvailableKw"),
    "dcPvCurrent": ("renewableDcPvCurrentKw", "dcPvCurrentKw"),
    "dcPvTarget": ("renewableDcPvTargetKw", "dcPvTargetKw"),
    "dcPvMaxAvailable": ("renewableDcPvMaxAvailableKw", "dcPvMaxAvailableKw"),
    "dcGridFollowingStorageCurrent": ("renewableDcGridFollowingStorageCurrentKw", "dcGridFollowingStorageCurrentKw"),
    "dcGridFollowingStorageTarget": ("renewableDcGridFollowingStorageTargetKw", "dcGridFollowingStorageTargetKw"),
    "dcGridFollowingStorageSoc": ("renewableDcGridFollowingStorageSoc", "dcGridFollowingStorageSocPercent"),
    "dcGridFormingStorageCurrent": ("renewableDcGridFormingStorageCurrentKw", "dcGridFormingStorageCurrentKw"),
    "dcGridFormingStorageTarget": ("renewableDcGridFormingStorageTargetKw", "dcGridFormingStorageTargetKw"),
    "dcGridFormingStorageSoc": ("renewableDcGridFormingStorageSoc", "dcGridFormingStorageSocPercent"),
    "dcDieselCurrent": ("renewableDcDieselCurrentKw", "dcDieselCurrentKw"),
    "dcDieselMin": ("renewableDcDieselMinKw", "dcDieselMinKw"),
    "dcDieselTarget": ("renewableDcDieselTargetKw", "dcDieselTargetKw"),
    "dcLoad": ("renewableDcLoadKw", "dcLoadKw"),
    "totalRenewableCurrent": ("renewableTotalCurrentKw", "totalRenewableCurrentKw"),
    "totalRenewableTarget": ("renewableTotalTargetKw", "totalRenewableTargetKw"),
    "totalRenewableMaxAvailable": ("renewableTotalMaxAvailableKw", "totalRenewableMaxAvailableKw"),
    "totalWindCurrent": ("renewableTotalWindCurrentKw", "totalWindCurrentKw"),
    "totalWindTarget": ("renewableTotalWindTargetKw", "totalWindTargetKw"),
    "totalWindMaxAvailable": ("renewableTotalWindMaxAvailableKw", "totalWindMaxAvailableKw"),
    "totalPvCurrent": ("renewableTotalPvCurrentKw", "totalPvCurrentKw"),
    "totalPvTarget": ("renewableTotalPvTargetKw", "totalPvTargetKw"),
    "totalPvMaxAvailable": ("renewableTotalPvMaxAvailableKw", "totalPvMaxAvailableKw"),
    "totalGridFollowingStorageCurrent": ("renewableTotalGridFollowingStorageCurrentKw", "totalGridFollowingStorageCurrentKw"),
    "totalGridFollowingStorageTarget": ("renewableTotalGridFollowingStorageTargetKw", "totalGridFollowingStorageTargetKw"),
    "totalGridFollowingStorageSoc": ("renewableTotalGridFollowingStorageSoc", "totalGridFollowingStorageSocPercent"),
    "totalGridFormingStorageCurrent": ("renewableTotalGridFormingStorageCurrentKw", "totalGridFormingStorageCurrentKw"),
    "totalGridFormingStorageTarget": ("renewableTotalGridFormingStorageTargetKw", "totalGridFormingStorageTargetKw"),
    "totalGridFormingStorageSoc": ("renewableTotalGridFormingStorageSoc", "totalGridFormingStorageSocPercent"),
    "dieselCurrent": ("renewableTotalDieselCurrentKw", "totalDieselCurrentKw"),
    "dieselMin": ("renewableTotalDieselMinKw", "totalDieselMinKw"),
    "dieselTarget": ("renewableTotalDieselTargetKw", "totalDieselTargetKw"),
    "totalLoad": ("renewableTotalLoadKw", "totalLoadKw"),
    "acdcCurrent": ("renewableAcdcCurrentKw", "acdcCurrentKw"),
    "acdcTarget": ("renewableAcdcTargetKw", "acdcTargetKw"),
    "observedWindSpeed": ("renewableObservedWindSpeed", "observedWindSpeed"),
    "observedSolarIrradiance": ("renewableObservedSolarIrradiance", "observedSolarIrradiance"),
    "electrolyzerCurrent": ("renewableElectrolyzerCurrentKw", "electrolyzerCurrentKw"),
    "electrolyzerTarget": ("renewableElectrolyzerTargetKw", "electrolyzerTargetKw"),
    "electrolyzerFlowCurrent": ("renewableElectrolyzerFlowCurrentNm3h", "electrolyzerFlowCurrentNm3h"),
    "electrolyzerFlowTarget": ("renewableElectrolyzerFlowTargetNm3h", "electrolyzerFlowTargetNm3h"),
    "fuelCellCurrent": ("renewableFuelCellCurrentKw", "fuelCellCurrentKw"),
    "fuelCellTarget": ("renewableFuelCellTargetKw", "fuelCellTargetKw"),
    "fuelCellFlowCurrent": ("renewableFuelCellFlowCurrentNm3h", "fuelCellFlowCurrentNm3h"),
    "fuelCellFlowTarget": ("renewableFuelCellFlowTargetNm3h", "fuelCellFlowTargetNm3h"),
    "hydrogenStoragePressure": ("renewableHydrogenStoragePressureMpa", "hydrogenStoragePressureMpa"),
    "hydrogenStoragePressureLowGuard": ("renewableHydrogenStoragePressureLowGuardMpa", "hydrogenStoragePressureLowGuardMpa"),
    "hydrogenStoragePressureHighGuard": ("renewableHydrogenStoragePressureHighGuardMpa", "hydrogenStoragePressureHighGuardMpa"),
    "hydrogenStorageGasQuantity": ("renewableHydrogenStorageGasQuantityNm3", "hydrogenStorageGasQuantityNm3"),
    "hydrogenStorageSoc": ("renewableHydrogenStorageSoc", "hydrogenStorageSocPercent"),
    "hydrogenStorageFlow": ("renewableHydrogenStorageFlowNm3h", "hydrogenStorageFlowNm3h"),
}


class TraineeRenewableTrendChartUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.backend = (ROOT / "simu/renewable_control.py").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")
        cls.series_block = cls.script.split(
            "const RENEWABLE_TREND_SERIES_DEFS = [",
            1,
        )[1].split("];", 1)[0]

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

    def test_middle_chart_has_time_window_and_every_statistic_series(self):
        self.assertIn('id="renewableTrendWindow"', self.html)
        self.assertIn('id="renewableTrendChart"', self.html)
        series_keys = re.findall(r'\bkey:\s*"([^"]+)"', self.series_block)
        metric_ids = re.findall(r'\bmetricId:\s*"([^"]+)"', self.series_block)
        fields = re.findall(r'\bfield:\s*"([^"]+)"', self.series_block)
        self.assertEqual(set(series_keys), set(EXPECTED_TREND_SERIES))
        self.assertEqual(
            dict(zip(series_keys, zip(metric_ids, fields))),
            EXPECTED_TREND_SERIES,
        )
        self.assertEqual(len(series_keys), len(set(series_keys)))
        self.assertEqual(len(metric_ids), len(set(metric_ids)))

        metric_panel = self.html.split('id="renewableMetricTabs"', 1)[1].split(
            'class="renewable-right-layout"',
            1,
        )[0]
        statistic_ids = set(re.findall(r'<td id="([^"]+)"', metric_panel))
        environment_ids = {"renewableObservedWindSpeed", "renewableObservedSolarIrradiance"}
        self.assertTrue((set(metric_ids) - environment_ids).issubset(statistic_ids))
        control_panel = self.html.split('<section class="panel renewable-control-panel">', 1)[1].split(
            '<section class="panel renewable-metrics-panel">',
            1,
        )[0]
        for environment_id in environment_ids:
            self.assertIn(f'id="{environment_id}"', control_panel)

    def test_curve_selector_is_a_left_three_level_checkbox_tree(self):
        self.assertIn('id="renewableTrendWorkspace"', self.html)
        self.assertIn('id="renewableTrendSeriesPanel"', self.html)
        self.assertIn('id="renewableTrendSeriesGroups"', self.html)
        self.assertIn("function renderRenewableTrendSeriesTree", self.script)
        self.assertIn('data-renewable-series-scope="${escapeHtml(scope.key)}"', self.script)
        self.assertIn('data-renewable-series-device="${escapeHtml(device.key)}"', self.script)
        self.assertIn('data-chart-series="${escapeHtml(series.key)}"', self.script)
        for scope, label in (("ac", "交流"), ("dc", "直流"), ("system", "系统"), ("hydrogen", "氢能")):
            with self.subTest(scope=scope):
                self.assertIn(f'key: "{scope}", label: "{label}"', self.script)
        for device_label in ("新能源", "风电", "光伏", "跟网储能", "构网储能", "柴发", "负荷", "AC/DC变流器", "环境", "电制氢", "燃料电池", "储氢罐"):
            with self.subTest(device_label=device_label):
                self.assertIn(f'deviceLabel: "{device_label}"', self.series_block)
        for curve_label in ("功率", "目标", "最大可发", "SOC", "下限", "风速", "太阳辐照度"):
            with self.subTest(curve_label=curve_label):
                self.assertIn(f'curveLabel: "{curve_label}"', self.series_block)
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
        self.assertIn("ensureRenewableTrendSeriesSelection(RENEWABLE_TREND_SERIES_DEFS)", draw_block)
        self.assertIn("renewableTrendSeriesAvailable(series, metrics)", draw_block)
        self.assertIn("renderRenewableTrendSeriesAvailability(metrics)", draw_block)
        self.assertIn('group: "ac-grid-following-storage"', self.series_block)
        self.assertIn('group: "dc-grid-forming-storage"', self.series_block)
        self.assertIn('group: "system-acdc"', self.series_block)

    def test_curve_selector_supports_keyword_selected_only_and_batch_selection(self):
        selector_panel = self.html.split('id="renewableTrendSeriesPanel"', 1)[1].split("</aside>", 1)[0]
        self.assertIn('id="renewableTrendSeriesFilter"', selector_panel)
        self.assertIn('type="search"', selector_panel)
        self.assertIn('placeholder="关键字过滤"', selector_panel)
        self.assertIn('id="renewableTrendSelectedOnly"', selector_panel)
        self.assertIn('id="renewableTrendClearAll"', selector_panel)
        self.assertIn('id="renewableTrendSelectAll"', selector_panel)
        self.assertIn('type="checkbox"', selector_panel)
        self.assertIn('<button id="renewableTrendClearAll" type="button"', selector_panel)
        self.assertIn('<button id="renewableTrendSelectAll" type="button"', selector_panel)
        self.assertIn("显示选中", selector_panel)
        self.assertIn("清空所有", selector_panel)
        self.assertIn("选择所有", selector_panel)
        self.assertNotIn("只显示勾选曲线", selector_panel)
        self.assertNotIn("只显示选中曲线", selector_panel)

        self.assertIn('renewableTrendSeriesFilter: ""', self.script)
        self.assertIn("renewableTrendSelectedOnly: false", self.script)
        self.assertIn("function applyRenewableTrendSeriesFilters", self.script)
        self.assertIn("function renewableTrendBatchSeriesInputs", self.script)
        self.assertIn("function setRenewableTrendBatchSeriesVisibility", self.script)
        batch_filter_block = self.script.split(
            "function renewableTrendBatchSeriesInputs",
            1,
        )[1].split("function setRenewableTrendBatchSeriesVisibility", 1)[0]
        self.assertIn("renewableMetricGroupAvailable", batch_filter_block)
        self.assertIn("const keywordMatches = !query || searchText.includes(query)", batch_filter_block)
        self.assertNotIn("renewableTrendSelectedOnly", batch_filter_block)
        self.assertIn('data-renewable-series-search="${escapeHtml(searchText)}"', self.script)
        self.assertIn("const keywordMatches = !query || searchText.includes(query)", self.script)
        self.assertIn("const selectionMatches = !selectedOnly || input.checked", self.script)
        self.assertIn("item.hidden = !available || !keywordMatches || !selectionMatches", self.script)
        self.assertIn('const renewableTrendSeriesFilter = $("renewableTrendSeriesFilter")', self.script)
        self.assertIn('const renewableTrendSelectedOnly = $("renewableTrendSelectedOnly")', self.script)
        self.assertIn('const renewableTrendClearAll = $("renewableTrendClearAll")', self.script)
        self.assertIn('const renewableTrendSelectAll = $("renewableTrendSelectAll")', self.script)
        self.assertIn("renewableTrendSeriesFilter.addEventListener(\"input\"", self.script)
        self.assertIn("renewableTrendSelectedOnly.addEventListener(\"change\"", self.script)
        self.assertIn("renewableTrendClearAll.addEventListener(\"click\"", self.script)
        self.assertIn("renewableTrendSelectAll.addEventListener(\"click\"", self.script)
        self.assertRegex(self.script, r"setRenewableTrendBatchSeriesVisibility\(\s*false")
        self.assertRegex(self.script, r"setRenewableTrendBatchSeriesVisibility\(\s*true")
        filter_block = self.script.split(
            "function applyRenewableTrendSeriesFilters",
            1,
        )[1].split("function renderRenewableTrendSeriesAvailability", 1)[0]
        self.assertIn("clearAllButton.disabled = batchInputs.length === 0 || batchSelectedCount === 0", filter_block)
        self.assertIn(
            "selectAllButton.disabled = batchInputs.length === 0 || batchSelectedCount === batchInputs.length",
            filter_block,
        )

        for css_hook in (
            ".renewable-trend-series-tools",
            ".renewable-trend-series-search",
            ".renewable-trend-series-actions",
            ".renewable-trend-series-toggle",
            ".renewable-trend-series-action",
        ):
            self.assertIn(css_hook, self.styles)
        toggle_input_block = self.styles.split(
            ".renewable-trend-series-toggle input {",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("accent-color: var(--teal);", toggle_input_block)

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
        for _metric_id, field in EXPECTED_TREND_SERIES.values():
            self.assertIn(f'field: "{field}"', self.series_block)
        self.assertIn('axis: "right"', self.series_block)
        self.assertIn('field: "observedWindSpeed"', self.series_block)
        self.assertIn('field: "observedSolarIrradiance"', self.series_block)
        self.assertIn("rightAxisValues", draw_block)
        self.assertIn("rightAxisMax", draw_block)
        self.assertIn("drawChartCursor", draw_block)
        self.assertIn("pixelPoints.length === 1", draw_block)

    def test_chart_renders_a_clickable_adaptive_legend_for_all_available_series(self):
        self.assertIn('id="renewableTrendLegend"', self.html)
        self.assertIn('class="renewable-trend-inline-legend"', self.html)
        self.assertIn('aria-label="曲线图例，点击图例可显示或隐藏曲线"', self.html)
        self.assertIn("function renderRenewableTrendLegend", self.script)
        draw_block = self.script.split("function drawRenewableTrendChart", 1)[1].split(
            "function renewableMetricTotal",
            1,
        )[0]
        self.assertIn("renderRenewableTrendLegend(availableSeries)", draw_block)
        legend_block = self.script.split("function renderRenewableTrendLegend", 1)[1].split(
            "function drawRenewableTrendChart",
            1,
        )[0]
        self.assertIn('document.createElement("button")', legend_block)
        self.assertIn('item.dataset.chartToggle = "renewableTrend"', legend_block)
        self.assertIn("item.dataset.chartSeries = series.key", legend_block)
        self.assertIn("item.dataset.chartLegendLabel = series.label", legend_block)
        self.assertIn('syncChartLegendButtons("renewableTrend")', legend_block)
        self.assertIn("series.label", legend_block)
        self.assertIn("series.style", legend_block)
        self.assertIn("--renewable-series-color", legend_block)
        self.assertIn('target?.closest("[data-chart-toggle][data-chart-series]")', self.script)
        self.assertIn('chartKey === "renewableTrend" ? drawRenewableTrendChart', self.script)
        self.assertIn("control.dataset.chartLegendLabel", self.script)
        for css_hook in (
            ".renewable-trend-inline-legend",
            ".renewable-trend-inline-legend-item",
            ".renewable-trend-inline-legend-item:hover",
            ".renewable-trend-inline-legend-item:focus-visible",
            ".renewable-trend-inline-legend-item.is-hidden",
            ".renewable-trend-inline-legend-swatch",
            ".renewable-trend-inline-legend-swatch.is-target",
            ".renewable-trend-inline-legend-swatch.is-available",
            ".renewable-trend-inline-legend-swatch.is-soc",
            ".renewable-trend-inline-legend-swatch.is-limit",
        ):
            self.assertIn(css_hook, self.styles)

    def test_renewable_cursor_labels_align_with_each_series_point(self):
        draw_block = self.script.split("function drawRenewableTrendChart", 1)[1].split(
            "function renewableMetricTotal",
            1,
        )[0]
        self.assertIn("inlineSeriesLabels: true", draw_block)
        self.assertIn("function drawInlineChartCursorLabels", self.script)
        helper_block = self.script.split("function drawInlineChartCursorLabels", 1)[1].split(
            "function drawChartCursor",
            1,
        )[0]
        self.assertIn("point.y", helper_block)
        self.assertIn("series.label", helper_block)
        self.assertIn("series.color", helper_block)
        self.assertIn("valueFormatter(point.value)", helper_block)
        self.assertIn("series.unit", helper_block)
        self.assertIn("rightSpace", helper_block)
        self.assertIn("leftSpace", helper_block)
        self.assertIn("rightSpace >= label.width", helper_block)

    def test_renewable_cursor_removes_shared_tooltip_but_generic_cursor_keeps_it(self):
        cursor_block = self.script.split("function drawChartCursor", 1)[1].split(
            "function initTraceChartInteractions",
            1,
        )[0]
        self.assertIn("options.inlineSeriesLabels", cursor_block)
        self.assertIn("drawInlineChartCursorLabels", cursor_block)
        self.assertIn("ctx.roundRect(tooltipX", cursor_block)
        self.assertIn("if (options.inlineSeriesLabels)", cursor_block)
        self.assertIn("return", cursor_block)

    def test_inline_cursor_uses_right_side_when_left_space_is_insufficient(self):
        helper = "function drawInlineChartCursorLabels" + self.script.split(
            "function drawInlineChartCursorLabels",
            1,
        )[1].split("function drawChartCursor", 1)[0]
        node_script = f"""
const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));
{helper}
const fillTexts = [];
const context = {{
  font: "",
  textAlign: "left",
  textBaseline: "middle",
  globalAlpha: 1,
  lineWidth: 1,
  strokeStyle: "",
  fillStyle: "",
  measureText(text) {{ return {{ width: String(text).length * 7 }}; }},
  beginPath() {{}},
  moveTo() {{}},
  lineTo() {{}},
  stroke() {{}},
  arc() {{}},
  fill() {{}},
  strokeText() {{}},
  fillText(text, x, y) {{ fillTexts.push({{ text, x, y }}); }},
}};
const samples = [
  {{ series: {{ label: "交流构网储能SOC", color: "#7a4fb3", unit: "%" }}, point: {{ x: 80, y: 100, value: 50.268 }} }},
  {{ series: {{ label: "直流构网储能SOC", color: "#a15ca8", unit: "%" }}, point: {{ x: 80, y: 104, value: 50.856 }} }},
  {{ series: {{ label: "总新能源最大可发", color: "#1f7a46", unit: "kW" }}, point: {{ x: 80, y: 108, value: 315.7 }} }},
];
drawInlineChartCursorLabels(
  context,
  {{ width: 900 }},
  {{ left: 60, right: 60, top: 30, bottom: 30 }},
  80,
  samples,
  {{ ratio: 1, maxSeries: 10, timeLabel: "00:18:00", valueFormatter: (value) => String(value) }},
);
process.stdout.write(JSON.stringify(fillTexts.filter((item) => !item.text.startsWith("时刻:"))));
"""
        result = subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)
        labels = json.loads(result.stdout)
        self.assertEqual(len(labels), 3)
        self.assertEqual([label["y"] for label in labels], [100, 104, 108])
        self.assertTrue(all(label["x"] > 80 for label in labels))

    def test_right_axis_preserves_soc_scale_and_expands_for_environment_values(self):
        helper = "function renewableTrendRightAxisScale" + self.script.split(
            "function renewableTrendRightAxisScale",
            1,
        )[1].split("function drawRenewableTrendChart", 1)[0]
        node_script = f"""
{helper}
const soc = renewableTrendRightAxisScale(
  [{{ soc: 35 }}, {{ soc: 80 }}],
  [{{ axis: "right", field: "soc", style: "soc", unit: "%" }}],
);
const weather = renewableTrendRightAxisScale(
  [{{ wind: 4.5, solar: 0 }}, {{ wind: 8, solar: 820 }}],
  [
    {{ axis: "right", field: "wind", style: "weather", unit: "m/s" }},
    {{ axis: "right", field: "solar", style: "weather", unit: "W/m²" }},
  ],
);
process.stdout.write(JSON.stringify({{ soc, weather }}));
"""
        result = subprocess.run(["node", "-e", node_script], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["soc"]["min"], 0)
        self.assertEqual(payload["soc"]["max"], 100)
        self.assertEqual(payload["soc"]["tickSuffix"], "%")
        self.assertIn("右轴SOC", payload["soc"]["label"])
        self.assertEqual(payload["weather"]["min"], 0)
        self.assertGreater(payload["weather"]["max"], 820)
        self.assertIn("m/s", payload["weather"]["label"])
        self.assertIn("W/m²", payload["weather"]["label"])

    def test_backend_compact_trend_keeps_all_power_targets_and_storage_soc(self):
        for _metric_id, field in EXPECTED_TREND_SERIES.values():
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
        self.assertIn(".renewable-trend-series-device", self.styles)
        self.assertIn(".renewable-trend-chart-surface", self.styles)

    def test_third_level_curve_items_are_visibly_indented(self):
        device_summary_block = self.styles.rsplit(
            ".renewable-trend-series-device > summary {",
            1,
        )[1].split("}", 1)[0]
        series_list_block = self.styles.split(
            ".renewable-trend-series-list {",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("padding-left: 32px;", device_summary_block)
        self.assertIn("padding: 1px 5px 6px 68px;", series_list_block)
        self.assertIn("position: relative;", series_list_block)
        self.assertIn(".renewable-trend-series-list::before", self.styles)
        self.assertIn("left: 52px;", self.styles)


if __name__ == "__main__":
    unittest.main()
