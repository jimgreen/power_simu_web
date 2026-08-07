from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SvgDiagramInteractionsUiTest(unittest.TestCase):
    def _scripts(self):
        return (
            ROOT / "simu/web/simulator/app.js",
            ROOT / "simu/web/trainee/app.js",
        )

    def _styles(self):
        return (
            ROOT / "simu/web/simulator/styles.css",
            ROOT / "simu/web/trainee/styles.css",
        )

    def _helper_source(self, script: str) -> str:
        if "const DIAGRAM_TREND_WINDOWS" not in script:
            self.fail("diagram interaction helpers are missing")
        return "const DIAGRAM_TREND_WINDOWS" + script.split(
            "const DIAGRAM_TREND_WINDOWS",
            1,
        )[1].split("function addDiagramControlAliases", 1)[0]

    def _run_helpers(self, script: str, body: str):
        result = subprocess.run(
            ["node"],
            input=f"{self._helper_source(script)}\n{body}",
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def _trend_helper_source(self, script: str) -> str:
        if "function diagramTrendHistorySeries" not in script:
            self.fail("dual diagram trend helpers are missing")
        trend_source = "function diagramTrendHistorySeries" + script.split(
            "function diagramTrendHistorySeries",
            1,
        )[1].split("function diagramMeasurementValueWithUnit", 1)[0]
        return f"{self._helper_source(script)}\n{trend_source}"

    def _run_trend_helpers(self, script: str, body: str):
        result = subprocess.run(
            ["node"],
            input=f"{self._trend_helper_source(script)}\n{body}",
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def _selection_helper_source(self, script: str) -> str:
        if "const diagramDeviceIndexCache" not in script:
            self.fail("diagram selection helpers are missing")
        return "const diagramDeviceIndexCache" + script.split(
            "const diagramDeviceIndexCache",
            1,
        )[1].split("function updateDiagramDeviceVisualStates", 1)[0]

    def _run_selection_helpers(self, script: str, body: str):
        result = subprocess.run(
            ["node"],
            input=f"{self._selection_helper_source(script)}\n{body}",
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_hour_and_day_trends_use_aligned_complete_periods(self):
        body = """
const points = [
  { minute: 1380, value: 1 },
  { minute: 1439, value: 2 },
  { minute: 1440, value: 3 },
  { minute: 1460, value: 4 },
  { minute: 1475, value: 5 },
  { minute: 1500, value: 6 },
];
const hourRange = diagramTrendPeriodRange("hour", 1475);
const dayRange = diagramTrendPeriodRange("day", 1475);
process.stdout.write(JSON.stringify({
  hour: diagramTrendWindowPoints(points, "hour", 1475).map((point) => point.value),
  day: diagramTrendWindowPoints(points, "day", 1475).map((point) => point.value),
  fallbackHour: diagramTrendWindowPoints(points, "hour").map((point) => point.value),
  hourRange,
  dayRange,
  hourLabels: diagramTrendPeriodLabels("hour", hourRange),
  dayLabels: diagramTrendPeriodLabels("day", dayRange),
  hourMinutes: diagramTrendWindowMinutes("hour"),
  dayMinutes: diagramTrendWindowMinutes("day"),
}));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                payload = self._run_helpers(path.read_text(encoding="utf-8"), body)
                self.assertEqual(payload["hour"], [3, 4, 5])
                self.assertEqual(payload["day"], [3, 4, 5])
                self.assertEqual(payload["fallbackHour"], [6])
                self.assertEqual(
                    payload["hourRange"],
                    {
                        "startMinute": 1440,
                        "endMinute": 1500,
                        "latestMinute": 1475,
                        "windowMinutes": 60,
                    },
                )
                self.assertEqual(
                    payload["dayRange"],
                    {
                        "startMinute": 1440,
                        "endMinute": 2880,
                        "latestMinute": 1475,
                        "windowMinutes": 1440,
                    },
                )
                self.assertEqual(payload["hourLabels"], {"start": "00:00", "end": "01:00"})
                self.assertEqual(payload["dayLabels"], {"start": "00:00", "end": "24:00"})
                self.assertEqual(payload["hourMinutes"], 60)
                self.assertEqual(payload["dayMinutes"], 1440)

    def test_adaptive_sampling_preserves_bucket_extrema(self):
        body = """
const points = [0, 1, 9, -4, 2, 3, 12, -8, 4, 5, 6, 7]
  .map((value, index) => ({ minute: index, value }));
process.stdout.write(JSON.stringify(
  diagramSampleTrendPoints(points, 8).map((point) => point.value)
));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                sampled = self._run_helpers(path.read_text(encoding="utf-8"), body)
                self.assertEqual(sampled[0], 0)
                self.assertEqual(sampled[-1], 7)
                self.assertIn(9, sampled)
                self.assertIn(-4, sampled)
                self.assertIn(12, sampled)
                self.assertIn(-8, sampled)

    def test_trend_axis_uses_readable_ticks_and_expands_flat_values(self):
        body = """
const normal = diagramTrendAxisScale([-2.2, 7.6], 4);
const flat = diagramTrendAxisScale([5, 5, 5], 4);
process.stdout.write(JSON.stringify({ normal, flat }));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                payload = self._run_helpers(path.read_text(encoding="utf-8"), body)
                self.assertLessEqual(payload["normal"]["min"], -2.2)
                self.assertGreaterEqual(payload["normal"]["max"], 7.6)
                self.assertGreaterEqual(len(payload["normal"]["ticks"]), 3)
                self.assertLess(payload["flat"]["min"], 5)
                self.assertGreater(payload["flat"]["max"], 5)

    def test_trend_cursor_snaps_to_nearest_sampled_point(self):
        body = """
const points = [
  { minute: 10, time: "00:10", value: -2 },
  { minute: 20, time: "00:20", value: 4 },
  { minute: 35, time: "00:35", value: 9 },
];
process.stdout.write(JSON.stringify({
  before: diagramNearestTrendPoint(points, 0),
  middle: diagramNearestTrendPoint(points, 27),
  after: diagramNearestTrendPoint(points, 50),
  data: diagramTrendCursorData(points, 19, "kW"),
}));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                payload = self._run_helpers(path.read_text(encoding="utf-8"), body)
                self.assertEqual(payload["before"]["minute"], 10)
                self.assertEqual(payload["middle"]["minute"], 20)
                self.assertEqual(payload["after"]["minute"], 35)
                self.assertEqual(
                    payload["data"],
                    {"minute": 20, "time": "00:20", "value": 4, "unit": "kW"},
                )

    def test_svg_display_preferences_are_separate_and_normalized(self):
        expected_keys = {
            "simulator": "simulator.svgDisplayPreferences.v1",
            "trainee": "trainee.svgDisplayPreferences.v1",
        }
        body = """
process.stdout.write(JSON.stringify({
  defaults: normalizeDiagramDisplayPreferences(null),
  partial: normalizeDiagramDisplayPreferences({ measurements: false, labels: "bad", flowArrows: true, measurementSource: "real" }),
  invalidSource: normalizeDiagramDisplayPreferences({ measurementSource: "invalid" }),
  labels: diagramDisplayPreferenceMenuItems({ measurements: false, labels: true, flowArrows: false, measurementSource: "scada" }),
}));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                self.assertIn(expected_keys[path.parent.name], script)
                payload = self._run_helpers(script, body)
                self.assertEqual(
                    payload["defaults"],
                    {
                        "measurements": True,
                        "labels": True,
                        "flowArrows": True,
                        "measurementSource": "scada",
                    },
                )
                self.assertEqual(
                    payload["partial"],
                    {
                        "measurements": False,
                        "labels": True,
                        "flowArrows": True,
                        "measurementSource": "real",
                    },
                )
                self.assertEqual(payload["invalidSource"]["measurementSource"], "scada")
                self.assertEqual(
                    [item["label"] for item in payload["labels"]],
                    ["显示真值", "显示量测", "不显示标识", "显示流动箭头"],
                )

    def test_svg_measurement_source_selects_real_or_scada_without_fallback(self):
        body = """
const binding = { devType: "ACGenerator", devName: "storage-1", metricType: "level" };
const key = diagramDeviceMeasurementKey("ACGenerator", "storage-1", "SOC");
const maps = {
  scadaByDevice: new Map([[key, { value: 0.51, channel: "scada" }]]),
  realByDevice: new Map([[key, { value: 0.48, channel: "real" }]]),
};
process.stdout.write(JSON.stringify({
  scada: diagramMetricBindingValue(binding, maps, "scada"),
  real: diagramMetricBindingValue(binding, maps, "real"),
  missingReal: diagramMetricBindingValue(binding, { ...maps, realByDevice: new Map() }, "real"),
}));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                payload = self._run_helpers(path.read_text(encoding="utf-8"), body)
                self.assertEqual(payload["scada"], {"value": 0.51, "channel": "scada"})
                self.assertEqual(payload["real"], {"value": 0.48, "channel": "real"})
                self.assertIsNone(payload["missingReal"])

    def test_tooltip_trend_keeps_real_and_scada_as_two_series(self):
        body = """
function measurementKey(row) { return row.name; }
const state = {
  measurementTraceHistory: [
    { minute: 1, sim_time: "00:01", measurements: { soc: { scada: 0.51, real: 0.50 } } },
    { minute: 2, sim_time: "00:02", measurements: { soc: { scada: 0.49, real: 0.48 } } },
    { minute: 3, sim_time: "00:03", measurements: { soc: { scada: 0.47, real: null } } },
  ],
};
const row = { name: "soc", dev_type: "ACGenerator", dev_name: "storage-1", meas_type: "SOC" };
const points = diagramTrendHistorySeries(row, "level");
const windowPoints = diagramTrendWindowPoints(points, "hour", 3);
const model = diagramTrendChartModel(windowPoints, "hour", 360, 3, "%");
process.stdout.write(JSON.stringify({
  points,
  windowPointCount: windowPoints.length,
  scadaLatest: model.series.scada.latest,
  realLatest: model.series.real.latest,
  scadaPolyline: model.series.scada.polyline,
  realPolyline: model.series.real.polyline,
}));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                payload = self._run_trend_helpers(path.read_text(encoding="utf-8"), body)
                self.assertEqual(payload["points"][0]["scada"], 51)
                self.assertEqual(payload["points"][0]["real"], 50)
                self.assertIsNone(payload["points"][2]["real"])
                self.assertEqual(payload["windowPointCount"], 3)
                self.assertEqual(payload["scadaLatest"], 47)
                self.assertEqual(payload["realLatest"], 48)
                self.assertTrue(payload["scadaPolyline"])
                self.assertTrue(payload["realPolyline"])

    def test_svg_context_menu_only_opens_on_blank_and_clamps_to_viewport(self):
        body = """
process.stdout.write(JSON.stringify({
  actions: typeof diagramContextMenuAction === "function" ? {
    blank: diagramContextMenuAction("", true),
    device: diagramContextMenuAction("device", true),
    metric: diagramContextMenuAction("metric", true),
    outside: diagramContextMenuAction("", false),
  } : null,
  bottomRight: typeof diagramFloatingPosition === "function" ? diagramFloatingPosition(
    { x: 790, y: 590 },
    { width: 180, height: 140 },
    { width: 800, height: 600 },
    8,
  ) : null,
  topLeft: typeof diagramFloatingPosition === "function" ? diagramFloatingPosition(
    { x: -20, y: -10 },
    { width: 180, height: 140 },
    { width: 800, height: 600 },
    8,
  ) : null,
}));
"""
        expected = {
            "actions": {
                "blank": "open",
                "device": "ignore",
                "metric": "ignore",
                "outside": "ignore",
            },
            "bottomRight": {"left": 612, "top": 452},
            "topLeft": {"left": 8, "top": 8},
        }
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_helpers(path.read_text(encoding="utf-8"), body),
                    expected,
                )

    def test_scripts_wire_context_menu_display_layers_and_storage_sync(self):
        required = (
            "function prepareDiagramDisplayLayers",
            "function applyDiagramDisplayPreferences",
            ".diagram-device-label-id",
            "data-diagram-runtime-label",
            "data-diagram-display-toggle",
            'container.addEventListener("contextmenu"',
            "diagramInteractionEventTarget",
            "diagramContextMenuAction",
            'window.addEventListener("storage"',
            "DIAGRAM_DISPLAY_PREFERENCES_KEY",
        )
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                for token in required:
                    self.assertIn(token, script)
                render_block = script.split("function renderModelDiagramPage", 1)[1].split(
                    "function ",
                    1,
                )[0]
                self.assertIn("prepareDiagramDisplayLayers(canvas)", render_block)
                self.assertIn("applyDiagramDisplayPreferences(canvas", render_block)

    def test_styles_include_svg_display_layers_and_context_menu(self):
        required = (
            ".diagram-context-menu",
            ".diagram-context-menu-item",
            ".diagram-device-label-id",
            ".is-diagram-measurements-hidden .diagram-measurement-layer",
            ".is-diagram-labels-hidden .diagram-device-label-name",
            ".is-diagram-labels-hidden .diagram-device-label-id",
            ".is-diagram-flow-arrows-hidden .diagram-flow-arrow",
        )
        for path in self._styles():
            with self.subTest(app=path.parent.name):
                styles = path.read_text(encoding="utf-8")
                for token in required:
                    self.assertIn(token, styles)

    def test_flow_arrow_math_uses_signed_power_larger_markers_and_route_density(self):
        body = """
const available = typeof diagramFlowArrowDirection === "function"
  && typeof diagramFlowArrowSize === "function"
  && typeof diagramFlowArrowVisibility === "function"
  && typeof diagramFlowArrowCount === "function"
  && typeof diagramFlowMotionAttributes === "function";
process.stdout.write(JSON.stringify(available ? {
  positive: diagramFlowArrowDirection(12, 1),
  negative: diagramFlowArrowDirection(-12, 1),
  reversed: diagramFlowArrowDirection(12, -1),
  zero: diagramFlowArrowSize(0, 100),
  quarter: diagramFlowArrowSize(25, 100),
  full: diagramFlowArrowSize(100, 100),
  over: diagramFlowArrowSize(400, 100),
  visible: diagramFlowArrowVisibility({ power: 10, referencePower: 100, valid: true, offline: false }),
  nearZero: diagramFlowArrowVisibility({ power: 0.05, referencePower: 100, valid: true, offline: false }),
  offline: diagramFlowArrowVisibility({ power: 10, referencePower: 100, valid: true, offline: true }),
  shortCount: diagramFlowArrowCount(20),
  standardCount: diagramFlowArrowCount(135),
  longCount: diagramFlowArrowCount(480),
  forwardMotion: diagramFlowMotionAttributes(1),
  reverseMotion: diagramFlowMotionAttributes(-1),
} : null));
"""
        expected = {
            "positive": 1,
            "negative": -1,
            "reversed": -1,
            "zero": 10,
            "quarter": 17,
            "full": 24,
            "over": 24,
            "visible": True,
            "nearZero": False,
            "offline": False,
            "shortCount": 2,
            "standardCount": 3,
            "longCount": 6,
            "forwardMotion": {"keyPoints": "0;1", "rotate": "auto"},
            "reverseMotion": {"keyPoints": "1;0", "rotate": "auto-reverse"},
        }
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_helpers(path.read_text(encoding="utf-8"), body),
                    expected,
                )

    def test_scripts_compile_and_update_svg_native_flow_arrows(self):
        required = (
            ".routable-line-device-glyph",
            "source-dev-id",
            "target-dev-id",
            "function createDiagramFlowArrow",
            "function compileDiagramFlowArrows",
            "function updateDiagramFlowArrows",
            "animateMotion",
            "repeatCount",
            "diagramFlowArrowCount",
            "diagramFlowMotionAttributes",
            "diagramFlowReferencePower",
            "getTotalLength",
            "--diagram-flow-color",
            "markers",
            'animation.setAttribute("begin"',
            'record.root.toggleAttribute("hidden", !visible)',
            "relevantDevices.some",
        )
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                for token in required:
                    self.assertIn(token, script)
                flow_block = script.split("function createDiagramFlowArrow", 1)[1].split(
                    "function updateDiagramRealtimeBindings",
                    1,
                )[0]
                self.assertNotIn("setInterval", flow_block)
                self.assertNotIn("requestAnimationFrame", flow_block)
                self.assertIn('rotate: reverse ? "auto-reverse" : "auto"', script)

    def test_flow_topology_helpers_cover_switches_converters_and_bus_connectors(self):
        body = """
const available = typeof diagramFlowInlineDeviceKind === "function"
  && typeof diagramFlowPowerMeasurementTypes === "function"
  && typeof diagramFlowSeriesOrientation === "function"
  && typeof diagramFlowEdgeTerminalOrientation === "function"
  && typeof diagramFlowNodeKey === "function";
process.stdout.write(JSON.stringify(available ? {
  inline: {
    branch: diagramFlowInlineDeviceKind("ACBranch"),
    zeroBranch: diagramFlowInlineDeviceKind("ACZeroBranch"),
    acBreak: diagramFlowInlineDeviceKind("ACBreak"),
    dcBreak: diagramFlowInlineDeviceKind("DCBreak"),
    dcac: diagramFlowInlineDeviceKind("DCACConverter"),
    dcdc: diagramFlowInlineDeviceKind("DCDCConverter"),
    transformer: diagramFlowInlineDeviceKind("ACTransformer"),
    bus: diagramFlowInlineDeviceKind("ACRealBs"),
    generator: diagramFlowInlineDeviceKind("ACGenerator"),
  },
  measurementTypes: {
    dcdc: diagramFlowPowerMeasurementTypes("DCDCConverter"),
    dcac: diagramFlowPowerMeasurementTypes("DCACConverter"),
    break: diagramFlowPowerMeasurementTypes("DCBreak"),
    transformer: diagramFlowPowerMeasurementTypes("ACTransformer"),
  },
  series: {
    terminal1ToTerminal2: diagramFlowSeriesOrientation(1, "two-terminal", 2),
    terminal2ToTerminal1: diagramFlowSeriesOrientation(2, "two-terminal", 1),
    sameTerminal: diagramFlowSeriesOrientation(1, "two-terminal", 1),
    generatorAtTerminal1: diagramFlowSeriesOrientation(1, "generator", 0),
    generatorAtTerminal2: diagramFlowSeriesOrientation(2, "generator", 0),
    loadAtTerminal1: diagramFlowSeriesOrientation(1, "load", 0),
    loadAtTerminal2: diagramFlowSeriesOrientation(2, "load", 0),
  },
  connector: {
    sourceTerminal1: diagramFlowEdgeTerminalOrientation("source", 1),
    sourceTerminal2: diagramFlowEdgeTerminalOrientation("source", 2),
    targetTerminal1: diagramFlowEdgeTerminalOrientation("target", 1),
    targetTerminal2: diagramFlowEdgeTerminalOrientation("target", 2),
  },
  nodeKeys: {
    ac: diagramFlowNodeKey("1", "ac"),
    dc: diagramFlowNodeKey("1", "dc"),
    distinct: diagramFlowNodeKey("1", "ac") !== diagramFlowNodeKey("1", "dc"),
  },
} : null));
"""
        expected = {
            "inline": {
                "branch": "branch",
                "zeroBranch": "branch",
                "acBreak": "device",
                "dcBreak": "device",
                "dcac": "device",
                "dcdc": "device",
                "transformer": "device",
                "bus": "",
                "generator": "",
            },
            "measurementTypes": {
                "dcdc": ["P_FROM", "P_TO"],
                "dcac": ["P_AC", "P_DC"],
                "break": ["P_FROM", "P_TO"],
                "transformer": ["P_FROM", "P_TO"],
            },
            "series": {
                "terminal1ToTerminal2": 1,
                "terminal2ToTerminal1": 1,
                "sameTerminal": -1,
                "generatorAtTerminal1": 1,
                "generatorAtTerminal2": -1,
                "loadAtTerminal1": -1,
                "loadAtTerminal2": 1,
            },
            "connector": {
                "sourceTerminal1": -1,
                "sourceTerminal2": 1,
                "targetTerminal1": 1,
                "targetTerminal2": -1,
            },
            "nodeKeys": {
                "ac": "AC:1",
                "dc": "DC:1",
                "distinct": True,
            },
        }
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                self.assertEqual(self._run_helpers(script, body), expected)
                flow_block = script.split("function diagramFlowEndpointKind", 1)[1].split(
                    "function updateDiagramRealtimeBindings",
                    1,
                )[0]
                for token in (
                    "function diagramFlowTopology",
                    "function diagramFlowDeviceRoute",
                    "function diagramFlowPowerBindings",
                    "function diagramFlowEdgeBinding",
                    "function diagramFlowResolvePower",
                    'type.includes("TRANSFORMER")',
                    'kind: "device"',
                    'kind: "connector"',
                    "powerBindings",
                ):
                    self.assertIn(token, flow_block)

    def test_styles_include_noninteractive_flow_arrow_layers(self):
        required = (
            ".diagram-flow-arrow",
            ".diagram-flow-arrow-marker",
            "pointer-events: none",
        )
        for path in self._styles():
            with self.subTest(app=path.parent.name):
                styles = path.read_text(encoding="utf-8")
                for token in required:
                    self.assertIn(token, styles)
                flow_styles = styles.split(".diagram-flow-arrow", 1)[1].split(
                    ".diagram-device-label-id",
                    1,
                )[0]
                self.assertIn("var(--diagram-flow-color", flow_styles)
                self.assertNotIn("fill: #b24631", flow_styles)

    def test_reset_clears_svg_runtime_layers_but_preserves_preferences(self):
        required = (
            "closeDiagramContextMenu(interaction)",
            "hideDiagramTrendCursor(interaction)",
            "removeDiagramRuntimeLabels(container)",
            "removeDiagramFlowArrows(container)",
        )
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                self.assertIn("function removeDiagramRuntimeLabels", script)
                reset_block = script.split("function resetDiagramInteractions", 1)[1].split(
                    "function diagramViewBox",
                    1,
                )[0]
                for token in required:
                    self.assertIn(token, reset_block)
                self.assertNotIn("diagramDisplayPreferences =", reset_block)

    def test_render_prepares_runtime_layers_only_when_diagram_key_changes(self):
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                render_block = script.split("function renderModelDiagramPage", 1)[1].split(
                    'window.addEventListener("storage"',
                    1,
                )[0]
                key_block = render_block.split(
                    "if (canvas.dataset.diagramKey !== key)",
                    1,
                )[1].split("initDiagramInteractions(canvas)", 1)[0]
                self.assertEqual(key_block.count("prepareDiagramDisplayLayers(canvas)"), 1)
                self.assertEqual(key_block.count("compileDiagramFlowArrows(canvas)"), 1)
                self.assertNotIn("applyDiagramDisplayPreferences", key_block)
                self.assertIn("applyDiagramDisplayPreferences(canvas, diagramDisplayPreferences)", render_block)

    def test_realtime_updates_reuse_existing_svg_runtime_layers(self):
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                update_block = script.split("function updateDiagramRealtimeBindings", 1)[1].split(
                    "function renderModelDiagramPage",
                    1,
                )[0]
                self.assertIn("updateDiagramFlowArrows(container, snapshot, measurementMaps)", update_block)
                self.assertNotIn("prepareDiagramDisplayLayers", update_block)
                self.assertNotIn("compileDiagramFlowArrows", update_block)
                self.assertNotIn("sanitizeDiagramSvg", update_block)
                self.assertNotIn("innerHTML", update_block)

    def test_trend_value_converts_soc_without_clamping(self):
        body = """
process.stdout.write(JSON.stringify([
  diagramTrendDisplayValue(1.08, { meas_type: "SOC" }, "level"),
  diagramTrendDisplayValue(-0.03, { meas_type: "SOC" }, "level"),
]));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_helpers(path.read_text(encoding="utf-8"), body),
                    [108, -3],
                )

    def test_zoom_keeps_focus_and_clamps_to_original_bounds(self):
        body = """
const original = { x: 0, y: 0, width: 1000, height: 500 };
const zoomed = diagramZoomViewBox(original, original, { x: 250, y: 125 }, 0.5);
const maxZoom = diagramZoomViewBox(
  { x: 200, y: 100, width: 125, height: 62.5 },
  original,
  { x: 250, y: 125 },
  0.1,
);
const reset = diagramZoomViewBox(zoomed, original, { x: 0, y: 0 }, 10);
process.stdout.write(JSON.stringify({ zoomed, maxZoom, reset }));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                payload = self._run_helpers(path.read_text(encoding="utf-8"), body)
                self.assertEqual(
                    payload["zoomed"],
                    {"x": 125, "y": 62.5, "width": 500, "height": 250},
                )
                self.assertEqual(payload["maxZoom"]["width"], 125)
                self.assertEqual(
                    payload["reset"],
                    {"x": 0, "y": 0, "width": 1000, "height": 500},
                )

    def test_double_click_fit_restores_original_view_box(self):
        body = """
const attributes = { viewBox: "250 100 500 250" };
const viewport = {
  svg: {
    setAttribute(name, value) { attributes[name] = String(value); },
  },
  original: { x: 10, y: 20, width: 1000, height: 500 },
  current: { x: 250, y: 100, width: 500, height: 250 },
};
const fitted = typeof fitDiagramViewport === "function" ? fitDiagramViewport(viewport) : null;
const invalid = typeof fitDiagramViewport === "function"
  ? fitDiagramViewport({ svg: viewport.svg, original: { x: 0, y: 0, width: 0, height: 500 } })
  : null;
process.stdout.write(JSON.stringify({ fitted, invalid, current: viewport.current, attributes }));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                payload = self._run_helpers(path.read_text(encoding="utf-8"), body)
                self.assertTrue(payload["fitted"])
                self.assertFalse(payload["invalid"])
                self.assertEqual(
                    payload["current"],
                    {"x": 10, "y": 20, "width": 1000, "height": 500},
                )
                self.assertEqual(payload["attributes"]["viewBox"], "10 20 1000 500")

    def test_double_click_only_fits_genuine_svg_blank_space(self):
        body = """
const actions = typeof diagramSvgDoubleClickAction === "function" ? {
  outside: diagramSvgDoubleClickAction("", false),
  blank: diagramSvgDoubleClickAction("", true),
  device: diagramSvgDoubleClickAction("device", true),
  metric: diagramSvgDoubleClickAction("metric", true),
} : null;
process.stdout.write(JSON.stringify(actions));
"""
        expected = {
            "simulator": {
                "outside": "ignore",
                "blank": "fit",
                "device": "ignore",
                "metric": "ignore",
            },
            "trainee": {
                "outside": "ignore",
                "blank": "fit",
                "device": "command",
                "metric": "ignore",
            },
        }
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_helpers(path.read_text(encoding="utf-8"), body),
                    expected[path.parent.name],
                )

    def test_double_click_resolves_pointer_capture_and_canvas_blank_targets(self):
        body = """
class FakeElement {
  constructor(name, svg = null) {
    this.name = name;
    this.svg = svg;
  }
  closest(selector) {
    return selector === "svg" ? this.svg : null;
  }
}
global.Element = FakeElement;
const svg = new FakeElement("svg");
svg.svg = svg;
const svgChild = new FakeElement("svg-child", svg);
const canvasTarget = new FakeElement("canvas-target");
const deviceAtPoint = new FakeElement("device-at-point", svg);
const outside = new FakeElement("outside");
const container = {
  contains(element) { return element !== outside; },
};
const viewport = { svg };
let pointTarget = canvasTarget;
global.document = {
  elementFromPoint() { return pointTarget; },
};
const direct = typeof diagramInteractionEventTarget === "function"
  ? diagramInteractionEventTarget(container, viewport, { target: svgChild, clientX: 10, clientY: 20 })
  : null;
const canvasBlank = typeof diagramInteractionEventTarget === "function"
  ? diagramInteractionEventTarget(container, viewport, { target: canvasTarget, clientX: 10, clientY: 20 })
  : null;
pointTarget = deviceAtPoint;
const capturedDevice = typeof diagramInteractionEventTarget === "function"
  ? diagramInteractionEventTarget(container, viewport, { target: canvasTarget, clientX: 10, clientY: 20 })
  : null;
const outsideTarget = typeof diagramInteractionEventTarget === "function"
  ? diagramInteractionEventTarget(container, viewport, { target: outside, clientX: 10, clientY: 20 })
  : null;
process.stdout.write(JSON.stringify({
  direct: direct?.name || null,
  canvasBlank: canvasBlank?.name || null,
  capturedDevice: capturedDevice?.name || null,
  outside: outsideTarget?.name || null,
}));
"""
        expected = {
            "direct": "svg-child",
            "canvasBlank": "svg",
            "capturedDevice": "device-at-point",
            "outside": None,
        }
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_helpers(path.read_text(encoding="utf-8"), body),
                    expected,
                )

    def test_double_click_handlers_classify_svg_targets_before_acting(self):
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                handler = script.split(
                    'container.addEventListener("dblclick"',
                    1,
                )[1].split('container.addEventListener("pointerleave"', 1)[0]
                self.assertIn("diagramInteractionEventTarget", handler)
                self.assertIn("diagramHoverTarget", handler)
                self.assertIn("diagramSvgDoubleClickAction", handler)
                self.assertIn("fitDiagramViewport", handler)
                self.assertNotIn('event.target.closest("svg")', handler)

    def test_click_selection_resolves_pointer_capture_before_selecting(self):
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                handler = script.split(
                    'container.addEventListener("click"',
                    1,
                )[1].split('container.addEventListener("wheel"', 1)[0]
                self.assertIn("diagramViewportState", handler)
                self.assertIn("diagramInteractionEventTarget", handler)
                self.assertIn("diagramTargetDeviceId(container, target)", handler)
                self.assertNotIn("diagramTargetDeviceId(container, event.target)", handler)

    def test_tooltips_hold_position_and_allow_pointer_entry(self):
        body = """
const metric = { kind: "metric", key: "metric:device-A:activePower" };
const nextMetric = { kind: "metric", key: "metric:device-A:voltage" };
const device = { kind: "device", key: "device:device-A" };
const nextDevice = { kind: "device", key: "device:device-B" };
const payload = typeof diagramTooltipPointerMoveAction === "function" ? {
  metricGap: diagramTooltipPointerMoveAction(metric, null, false),
  metricSame: diagramTooltipPointerMoveAction(metric, metric, false),
  metricChanged: diagramTooltipPointerMoveAction(metric, nextMetric, false),
  metricToDevice: diagramTooltipPointerMoveAction(metric, device, false),
  metricHidden: diagramTooltipPointerMoveAction(metric, metric, true),
  deviceGap: diagramTooltipPointerMoveAction(device, null, false),
  deviceSame: diagramTooltipPointerMoveAction(device, device, false),
  deviceChanged: diagramTooltipPointerMoveAction(device, nextDevice, false),
  deviceToMetric: diagramTooltipPointerMoveAction(device, metric, false),
  deviceHidden: diagramTooltipPointerMoveAction(device, device, true),
  empty: diagramTooltipPointerMoveAction(null, null, false),
} : null;
process.stdout.write(JSON.stringify(payload));
"""
        expected = {
            "metricGap": "schedule-hide",
            "metricSame": "hold",
            "metricChanged": "refresh",
            "metricToDevice": "schedule-hide",
            "metricHidden": "refresh",
            "deviceGap": "schedule-hide",
            "deviceSame": "hold",
            "deviceChanged": "refresh",
            "deviceToMetric": "schedule-hide",
            "deviceHidden": "refresh",
            "empty": "hide",
        }
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_helpers(path.read_text(encoding="utf-8"), body),
                    expected,
                )

    def test_tooltip_position_is_reused_during_realtime_refresh(self):
        body = """
const metric = { kind: "metric", key: "metric:device-A:activePower" };
const nextMetric = { kind: "metric", key: "metric:device-A:voltage" };
const device = { kind: "device", key: "device:device-A" };
const nextDevice = { kind: "device", key: "device:device-B" };
const payload = typeof diagramTooltipNeedsPosition === "function" ? {
  firstMetric: diagramTooltipNeedsPosition(metric, ""),
  sameMetricRefresh: diagramTooltipNeedsPosition(metric, metric.key),
  nextMetric: diagramTooltipNeedsPosition(nextMetric, metric.key),
  firstDevice: diagramTooltipNeedsPosition(device, ""),
  sameDeviceRefresh: diagramTooltipNeedsPosition(device, device.key),
  nextDevice: diagramTooltipNeedsPosition(nextDevice, device.key),
  noHover: diagramTooltipNeedsPosition(null, metric.key),
} : null;
process.stdout.write(JSON.stringify(payload));
"""
        expected = {
            "firstMetric": True,
            "sameMetricRefresh": False,
            "nextMetric": True,
            "firstDevice": True,
            "sameDeviceRefresh": False,
            "nextDevice": True,
            "noHover": False,
        }
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_helpers(path.read_text(encoding="utf-8"), body),
                    expected,
                )

    def test_pan_keeps_view_box_inside_original_bounds(self):
        body = """
const original = { x: 0, y: 0, width: 1000, height: 500 };
const current = { x: 250, y: 100, width: 500, height: 250 };
const payload = typeof diagramPanViewBox === "function" ? {
  moved: diagramPanViewBox(current, original, { x: 100, y: -40 }),
  topLeft: diagramPanViewBox(current, original, { x: 1000, y: 1000 }),
  bottomRight: diagramPanViewBox(current, original, { x: -1000, y: -1000 }),
} : null;
process.stdout.write(JSON.stringify(payload));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                payload = self._run_helpers(path.read_text(encoding="utf-8"), body)
                self.assertEqual(
                    payload["moved"],
                    {"x": 150, "y": 140, "width": 500, "height": 250},
                )
                self.assertEqual(
                    payload["topLeft"],
                    {"x": 0, "y": 0, "width": 500, "height": 250},
                )
                self.assertEqual(
                    payload["bottomRight"],
                    {"x": 500, "y": 250, "width": 500, "height": 250},
                )

    def test_full_canvas_background_uses_numeric_original_view_box_bounds(self):
        body = """
function fakeRect({ width = "100%", height = "100%", protectedAncestor = false } = {}) {
  const attrs = { width, height };
  const classes = new Set();
  return {
    attrs,
    classes,
    classList: { add(value) { classes.add(value); } },
    getAttribute(name) { return attrs[name] ?? null; },
    setAttribute(name, value) { attrs[name] = String(value); },
    closest() { return protectedAncestor ? {} : null; },
  };
}
const background = fakeRect();
const nestedDefinition = fakeRect({ protectedAncestor: true });
const partial = fakeRect({ width: "50%" });
const svg = {
  getAttribute(name) { return name === "viewBox" ? "10,20,300,200" : null; },
  querySelectorAll(selector) {
    return selector === "rect" ? [background, nestedDefinition, partial] : [];
  },
};
const normalized = typeof normalizeDiagramSvgBackground === "function"
  ? normalizeDiagramSvgBackground(svg)
  : null;
process.stdout.write(JSON.stringify({
  normalized,
  background: background.attrs,
  backgroundClasses: [...background.classes],
  nestedDefinition: nestedDefinition.attrs,
  partial: partial.attrs,
}));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                payload = self._run_helpers(script, body)
                self.assertEqual(payload["normalized"], 1)
                self.assertEqual(
                    payload["background"],
                    {
                        "x": "10",
                        "y": "20",
                        "width": "300",
                        "height": "200",
                        "pointer-events": "none",
                    },
                )
                self.assertIn("diagram-svg-background", payload["backgroundClasses"])
                self.assertEqual(
                    payload["nestedDefinition"],
                    {"width": "100%", "height": "100%"},
                )
                self.assertEqual(payload["partial"], {"width": "50%", "height": "100%"})
                sanitize_block = script.split("function sanitizeDiagramSvg", 1)[1].split(
                    "const DIAGRAM_TREND_WINDOWS",
                    1,
                )[0]
                self.assertIn("normalizeDiagramSvgBackground(svg)", sanitize_block)

    def test_switch_status_selects_matching_svg_symbol(self):
        body = """
const payload = typeof diagramSwitchState === "function" && typeof diagramSwitchStateHref === "function" ? {
  states: [0, 1, "分闸", "closed", "--"].map(diagramSwitchState),
  open: diagramSwitchStateHref("#symbol_DCBreak_dc-breaker_state_1_2", "open"),
  closed: diagramSwitchStateHref("#symbol_ACBreak_ac-breaker_state_0", "closed"),
} : null;
process.stdout.write(JSON.stringify(payload));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                payload = self._run_helpers(path.read_text(encoding="utf-8"), body)
                self.assertEqual(
                    payload["states"],
                    ["open", "closed", "open", "closed", "unknown"],
                )
                self.assertEqual(
                    payload["open"],
                    "#symbol_DCBreak_dc-breaker_state_0_2",
                )
                self.assertEqual(
                    payload["closed"],
                    "#symbol_ACBreak_ac-breaker_state_1",
                )

    def test_click_selection_keeps_only_one_logical_device(self):
        body = """
function fakeElement(tagName, attrs = {}, selected = false) {
  const classes = new Set(selected ? ["is-diagram-selected"] : []);
  return {
    tagName,
    attrs,
    classes,
    classList: {
      contains(value) { return classes.has(value); },
      add(value) { classes.add(value); },
      remove(value) { classes.delete(value); },
      toggle(value, force) {
        if (force) classes.add(value);
        else classes.delete(value);
      },
    },
    getAttribute(name) { return attrs[name] ?? null; },
    hasAttribute(name) { return attrs[name] !== undefined; },
  };
}

const stale = fakeElement("path", {}, true);
const deviceAGraphic = fakeElement("use", { "dev-id": "device-A", id: "device-A", name: "A" });
const deviceALabel = fakeElement("text", { dev: "device-A" });
const deviceBGraphic = fakeElement("use", { id: "device-B", name: "B" });
const elements = [stale, deviceAGraphic, deviceALabel, deviceBGraphic];
const deviceElements = elements.filter((element) => (
  element.hasAttribute("dev-id")
  || element.hasAttribute("dev")
  || (String(element.tagName).toLowerCase() === "use" && element.hasAttribute("id") && element.hasAttribute("name"))
));
const container = {
  dataset: {},
  querySelectorAll(selector) {
    if (selector === ".is-diagram-selected") {
      return elements.filter((element) => element.classList.contains("is-diagram-selected"));
    }
    if (selector === "[dev-id], [dev]") {
      return deviceElements.filter((element) => element.hasAttribute("dev-id") || element.hasAttribute("dev"));
    }
    if (selector === "[dev-id], [dev], use[id][name]") return deviceElements;
    return [];
  },
};
function selectedIds() {
  return elements
    .filter((element) => element.classList.contains("is-diagram-selected"))
    .map((element) => element.getAttribute("dev-id") || element.getAttribute("dev") || element.getAttribute("id") || "stale");
}

const payload = typeof setDiagramSelectedDevice === "function" ? {} : null;
if (payload) {
  setDiagramSelectedDevice(container, "device-A");
  payload.afterA = selectedIds();
  setDiagramSelectedDevice(container, "device-B");
  payload.afterB = selectedIds();
  payload.selectedDevId = diagramInteractionState(container).selectedDevId;
  setDiagramSelectedDevice(container, "");
  payload.afterBlank = selectedIds();
}
process.stdout.write(JSON.stringify(payload));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                payload = self._run_selection_helpers(
                    path.read_text(encoding="utf-8"),
                    body,
                )
                self.assertEqual(payload["afterA"], ["device-A", "device-A"])
                self.assertEqual(payload["afterB"], ["device-B"])
                self.assertEqual(payload["selectedDevId"], "device-B")
                self.assertEqual(payload["afterBlank"], [])

    def test_diagram_interaction_state_helper_is_declared(self):
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                self.assertIn("\nfunction diagramInteractionState(container)", script)
                self.assertNotIn("\n+function diagramInteractionState(container)", script)

    def test_trend_chart_renders_axis_unit_and_cursor_layers(self):
        required = (
            "diagramTrendAxisScale(values, 4)",
            'class="diagram-trend-y-axis"',
            'class="diagram-trend-axis-unit"',
            "data-diagram-trend-cursor-line",
            "data-diagram-trend-cursor-point",
            "data-diagram-trend-cursor-label",
            "function updateDiagramTrendCursor",
            "function hideDiagramTrendCursor",
        )
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                for token in required:
                    self.assertIn(token, script)

    def test_tooltip_delegates_pointer_motion_to_trend_cursor(self):
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                tooltip_block = script.split(
                    'tooltip.addEventListener("pointerenter"',
                    1,
                )[1].split("function updateDiagramRealtimeBindings", 1)[0]
                self.assertIn('tooltip.addEventListener("pointermove"', tooltip_block)
                self.assertIn("updateDiagramTrendCursor", tooltip_block)
                self.assertIn("hideDiagramTrendCursor", tooltip_block)

    def test_realtime_tooltip_refresh_updates_existing_dom(self):
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                refresh_block = script.split("function refreshDiagramTooltip", 1)[1].split(
                    "function resetDiagramInteractions",
                    1,
                )[0]
                self.assertIn("const hoverKey = String(interaction.hover.key || \"\")", refresh_block)
                self.assertIn("renderActiveDiagramTooltip(container, snapshot, interaction)", refresh_block)
                self.assertIn("updateDiagramMetricTooltip(container, interaction.hover, snapshot, interaction)", refresh_block)
                self.assertIn("updateDiagramDeviceTooltip(container, interaction.hover, snapshot, interaction)", refresh_block)
                self.assertNotIn("innerHTML", refresh_block)

    def test_metric_tooltip_exposes_incremental_update_targets(self):
        required = (
            "function diagramMetricTooltipData",
            "function updateDiagramMetricTooltip",
            "function updateDiagramTrendChart",
            "function syncDiagramTrendAxisTicks",
            "data-diagram-tooltip-current-value",
            "data-diagram-tooltip-current-unit",
            "data-diagram-tooltip-validity",
            "data-diagram-trend-axis-ticks",
            'data-diagram-trend-series="scada"',
            'data-diagram-trend-series="real"',
            'data-diagram-trend-cursor-point="scada"',
            'data-diagram-trend-cursor-point="real"',
            "data-diagram-trend-stat-scada-latest",
            "data-diagram-trend-stat-real-latest",
            "data-diagram-trend-range-start",
            "data-diagram-trend-range-end",
        )
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                for token in required:
                    self.assertIn(token, script)

    def test_device_tooltip_reconciles_keyed_rows(self):
        required = (
            "function diagramDeviceTooltipData",
            "function syncDiagramTooltipSections",
            "function updateDiagramDeviceTooltip",
            "data-diagram-device-tooltip-body",
            "data-diagram-tooltip-section",
            "data-diagram-tooltip-row",
            "data-diagram-tooltip-value",
        )
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                for token in required:
                    self.assertIn(token, script)

    def test_scripts_wire_tooltip_selection_tabs_and_wheel_zoom(self):
        required = (
            "function compileDiagramDeviceIndex",
            "function initDiagramInteractions",
            "function setDiagramSelectedDevice",
            "function diagramTooltipPointerMoveAction",
            "function diagramTooltipNeedsPosition",
            "function diagramTrendPeriodRange",
            "function diagramTrendPeriodLabels",
            "function fitDiagramViewport",
            "const DIAGRAM_TOOLTIP_HIDE_DELAY_MS = 150;",
            "function updateDiagramSwitchVisualStates",
            "data-diagram-trend-period",
            "data-diagram-switch-state",
            "小时曲线",
            "日曲线",
            'addEventListener("pointerdown"',
            'addEventListener("pointerup"',
            'addEventListener("pointercancel"',
            'addEventListener("dblclick"',
            'addEventListener("wheel"',
            "passive: false",
            "refreshDiagramTooltip(container, snapshot)",
            "resetDiagramInteractions(canvas)",
        )
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                for token in required:
                    self.assertIn(token, script)

    def test_styles_include_tooltip_chart_selection_and_zoom_affordances(self):
        required = (
            ".diagram-tooltip",
            ".diagram-trend-tabs",
            ".diagram-trend-chart",
            ".diagram-trend-y-axis",
            ".diagram-trend-axis-unit",
            ".diagram-trend-cursor",
            ".diagram-trend-cursor-label",
            ".is-diagram-selected",
            "use[id][name].is-diagram-selected",
            ".is-diagram-panning",
            "cursor: grab",
            "cursor: grabbing",
            "touch-action: none",
        )
        for path in self._styles():
            with self.subTest(app=path.parent.name):
                styles = path.read_text(encoding="utf-8")
                for token in required:
                    self.assertIn(token, styles)
                tooltip_block = styles.split(".diagram-tooltip {", 1)[1].split("}", 1)[0]
                self.assertIn("pointer-events: auto", tooltip_block)
                self.assertNotIn("pointer-events: none", tooltip_block)


if __name__ == "__main__":
    unittest.main()
