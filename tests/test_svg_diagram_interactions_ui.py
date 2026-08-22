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

    def _coupling_tooltip_helper_source(self, script: str) -> str:
        if "function diagramDeviceIdentityKey" not in script:
            self.fail("coupling device tooltip helpers are missing")
        return "function diagramDeviceIdentityKey" + script.split(
            "function diagramDeviceIdentityKey",
            1,
        )[1].split("function diagramSingleDeviceTooltipData", 1)[0]

    def _run_coupling_tooltip_helpers(self, script: str, body: str):
        result = subprocess.run(
            ["node"],
            input=(
                "function normalizeDiagramMeasurementToken(value) { "
                "return String(value || '').trim().toUpperCase(); }\n"
                "function definedModelDevices(snapshot) { return snapshot.definedDevices || []; }\n"
                f"{self._coupling_tooltip_helper_source(script)}\n{body}"
            ),
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def _flow_helper_source(self, script: str) -> str:
        if "function diagramFlowResolvePower" not in script:
            self.fail("diagram flow resolution helpers are missing")
        flow_source = "function diagramFlowEndpointKind" + script.split(
            "function diagramFlowEndpointKind",
            1,
        )[1].split("function createDiagramFlowArrow", 1)[0]
        return f"{self._helper_source(script)}\n{flow_source}"

    def _run_flow_helpers(self, script: str, body: str):
        result = subprocess.run(
            ["node"],
            input=f"{self._flow_helper_source(script)}\n{body}",
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
  visibleScadaLabels: diagramDisplayPreferenceMenuItems({ measurements: true, labels: true, flowArrows: false, measurementSource: "scada" }),
  visibleRealLabels: diagramDisplayPreferenceMenuItems({ measurements: true, labels: true, flowArrows: false, measurementSource: "real" }),
  hiddenLabels: diagramDisplayPreferenceMenuItems({ measurements: false, labels: true, flowArrows: false, measurementSource: "scada" }),
}));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                self.assertIn(expected_keys[path.parent.name], script)
                payload = self._run_helpers(script, body)
                if path.parent.name == "simulator":
                    self.assertEqual(
                        payload["defaults"],
                        {
                            "measurements": True,
                            "labels": True,
                            "flowArrows": True,
                            "measurementSource": "scada",
                        },
                    )
                    self.assertEqual(payload["partial"]["measurementSource"], "real")
                    self.assertEqual(payload["invalidSource"]["measurementSource"], "scada")
                    self.assertEqual(
                        [item["label"] for item in payload["visibleScadaLabels"]],
                        ["数据源: 量测", "不显示量测", "不显示标识", "显示流动箭头"],
                    )
                    self.assertEqual(
                        [item["label"] for item in payload["visibleRealLabels"]],
                        ["数据源: 真值", "不显示量测", "不显示标识", "显示流动箭头"],
                    )
                else:
                    self.assertEqual(
                        payload["defaults"],
                        {"measurements": True, "labels": True, "flowArrows": True},
                    )
                    self.assertEqual(
                        payload["partial"],
                        {"measurements": False, "labels": True, "flowArrows": True},
                    )
                    self.assertNotIn("measurementSource", payload["invalidSource"])
                    self.assertEqual(
                        [item["label"] for item in payload["visibleScadaLabels"]],
                        ["不显示量测", "不显示标识", "显示流动箭头"],
                    )
                    self.assertEqual(
                        [item["label"] for item in payload["visibleRealLabels"]],
                        ["不显示量测", "不显示标识", "显示流动箭头"],
                    )
                self.assertEqual(
                    [item["label"] for item in payload["hiddenLabels"]],
                    ["显示量测", "不显示标识", "显示流动箭头"],
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
                if path.parent.name == "simulator":
                    self.assertEqual(payload["real"], {"value": 0.48, "channel": "real"})
                    self.assertIsNone(payload["missingReal"])
                else:
                    self.assertEqual(payload["real"], {"value": 0.51, "channel": "scada"})
                    self.assertEqual(payload["missingReal"], {"value": 0.51, "channel": "scada"})

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
        simulator_path, trainee_path = self._scripts()
        payload = self._run_trend_helpers(simulator_path.read_text(encoding="utf-8"), body)
        self.assertEqual(payload["points"][0]["scada"], 51)
        self.assertEqual(payload["points"][0]["real"], 50)
        self.assertIsNone(payload["points"][2]["real"])
        self.assertEqual(payload["windowPointCount"], 3)
        self.assertEqual(payload["scadaLatest"], 47)
        self.assertEqual(payload["realLatest"], 48)
        self.assertTrue(payload["scadaPolyline"])
        self.assertTrue(payload["realPolyline"])

        trainee_body = """
function measurementKey(row) { return row.name; }
const state = {
  measurementTraceHistory: [
    { minute: 1, sim_time: "00:01", measurements: { soc: { scada: 0.51, real: 0.50 } } },
    { minute: 2, sim_time: "00:02", measurements: { soc: { scada: 0.49, real: 0.48 } } },
  ],
};
const row = { name: "soc", dev_type: "ACGenerator", dev_name: "storage-1", meas_type: "SOC" };
const points = diagramTrendHistorySeries(row, "level");
const model = diagramTrendChartModel(points, "hour", 360, 2, "%");
process.stdout.write(JSON.stringify({
  points,
  hasRealPoint: points.some((point) => Object.prototype.hasOwnProperty.call(point, "real")),
  hasRealSeries: Object.prototype.hasOwnProperty.call(model.series, "real"),
  scadaLatest: model.series.scada.latest,
}));
"""
        trainee_payload = self._run_trend_helpers(
            trainee_path.read_text(encoding="utf-8"),
            trainee_body,
        )
        self.assertEqual(trainee_payload["points"][0]["scada"], 51)
        self.assertFalse(trainee_payload["hasRealPoint"])
        self.assertFalse(trainee_payload["hasRealSeries"])
        self.assertEqual(trainee_payload["scadaLatest"], 49)

    def test_simulator_does_not_derive_median_deviation_from_history(self):
        simulator_path = self._scripts()[0]
        script = simulator_path.read_text(encoding="utf-8")
        self.assertNotIn("function diagramTrendMedianDeviation", script)
        self.assertIn("median_deviation", script)

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
  && typeof diagramFlowArrowThreshold === "function"
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
  electricThreshold: diagramFlowArrowThreshold("P_GEN", 0.2, 0.3),
  hydrogenThreshold: diagramFlowArrowThreshold("FLOW", 0.2, 0.3),
  visible: diagramFlowArrowVisibility({ power: 10, threshold: 0.1, valid: true, offline: false }),
  atThreshold: diagramFlowArrowVisibility({ power: 0.1, threshold: 0.1, valid: true, offline: false }),
  nearZero: diagramFlowArrowVisibility({ power: -0.02, threshold: 0.1, valid: true, offline: false }),
  offline: diagramFlowArrowVisibility({ power: 10, threshold: 0.1, valid: true, offline: true }),
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
            "electricThreshold": 0.2,
            "hydrogenThreshold": 0.3,
            "visible": True,
            "atThreshold": False,
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
        hydroPipe: diagramFlowInlineDeviceKind("HydroPipe"),
        hydroValve: diagramFlowInlineDeviceKind("HydroValve"),
    hydroStopValve: diagramFlowInlineDeviceKind("HydroStopValve"),
    hydroCompressor: diagramFlowInlineDeviceKind("HydroCompressor"),
    hydroPressRegulator: diagramFlowInlineDeviceKind("HydroPressRegulator"),
    futureExplicitHydrogenDevice: diagramFlowInlineDeviceKind("FutureDevice", [
      { terminal: 1, domain: "h2" },
      { terminal: 2, domain: "hydrogen" },
    ]),
    futureImplicitDevice: diagramFlowInlineDeviceKind("FutureDevice"),
    acElectrolyzer: diagramFlowInlineDeviceKind("AcE2Hydro"),
    dcElectrolyzer: diagramFlowInlineDeviceKind("DcE2Hydro"),
    acFuelCell: diagramFlowInlineDeviceKind("Hydro2AcE"),
    dcFuelCell: diagramFlowInlineDeviceKind("Hydro2DcE"),
    bus: diagramFlowInlineDeviceKind("ACRealBs"),
    generator: diagramFlowInlineDeviceKind("ACGenerator"),
  },
      measurementTypes: {
    dcdc: diagramFlowPowerMeasurementTypes("DCDCConverter"),
    acdc: diagramFlowPowerMeasurementTypes("ACDCConverter"),
    dcac: diagramFlowPowerMeasurementTypes("DCACConverter"),
    break: diagramFlowPowerMeasurementTypes("DCBreak"),
        transformer: diagramFlowPowerMeasurementTypes("ACTransformer"),
        hydroPipe: diagramFlowPowerMeasurementTypes("HydroPipe"),
        hydroValve: diagramFlowPowerMeasurementTypes("HydroValve"),
        hydroStopValve: diagramFlowPowerMeasurementTypes("HydroStopValve"),
        hydroCompressor: diagramFlowPowerMeasurementTypes("HydroCompressor"),
        hydroPressRegulator: diagramFlowPowerMeasurementTypes("HydroPressRegulator"),
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
    h2: diagramFlowNodeKey("1", "h2"),
    hydrogen: diagramFlowNodeKey("1", "hydrogen"),
    hydro: diagramFlowNodeKey("1", "hydro"),
    distinct: diagramFlowNodeKey("1", "ac") !== diagramFlowNodeKey("1", "dc"),
  },
  hydrogenConversionOrientation: {
    acElectrolyzer: diagramFlowPowerRouteOrientation({ devType: "AcE2Hydro" }),
    dcElectrolyzer: diagramFlowPowerRouteOrientation({ devType: "DcE2Hydro" }),
    acFuelCell: diagramFlowPowerRouteOrientation({ devType: "Hydro2AcE" }),
    dcFuelCell: diagramFlowPowerRouteOrientation({ devType: "Hydro2DcE" }),
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
                "hydroPipe": "branch",
                "hydroValve": "device",
                "hydroStopValve": "device",
                "hydroCompressor": "device",
                "hydroPressRegulator": "device",
                "futureExplicitHydrogenDevice": "device",
                "futureImplicitDevice": "",
                "acElectrolyzer": "device",
                "dcElectrolyzer": "device",
                "acFuelCell": "device",
                "dcFuelCell": "device",
                "bus": "",
                "generator": "",
            },
            "measurementTypes": {
                "dcdc": ["P_FROM", "P_TO"],
                "acdc": ["P_AC", "P_DC"],
                "dcac": ["P_AC", "P_DC"],
                "break": ["P_FROM", "P_TO"],
                "transformer": ["P_FROM", "P_TO"],
                "hydroPipe": ["FLOW"],
                "hydroValve": ["FLOW"],
                "hydroStopValve": ["FLOW"],
                "hydroCompressor": ["FLOW"],
                "hydroPressRegulator": ["FLOW"],
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
                "h2": "HYDRO:1",
                "hydrogen": "HYDRO:1",
                "hydro": "HYDRO:1",
                "distinct": True,
            },
            "hydrogenConversionOrientation": {
                "acElectrolyzer": 1,
                "dcElectrolyzer": 1,
                "acFuelCell": -1,
                "dcFuelCell": -1,
            },
        }
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                self.assertEqual(self._run_flow_helpers(script, body), expected)
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

    def test_flow_power_resolution_uses_valid_nonzero_port_and_normalizes_terminal_signs(self):
        body = """
function flowKey(device, measType) {
  return diagramDeviceMeasurementKey(device.devType, device.devName, measType);
}
function flowMaps(device, scadaRows = [], realRows = []) {
  return {
    scadaByDevice: new Map(scadaRows.map((row) => [flowKey(device, row.meas_type), row])),
    realByDevice: new Map(realRows.map((row) => [flowKey(device, row.meas_type), row])),
  };
}
function resolve(device, nodes, maps, orientation = diagramFlowPowerRouteOrientation(device, nodes)) {
  const result = diagramFlowResolvePower({
    powerBindings: [{ device, nodes, orientation, priority: 1 }],
  }, maps);
  return {
    measType: result.row?.meas_type || "",
    power: result.power,
    valid: result.valid,
  };
}

const intertie = { devId: "DCACConverter-13", devType: "DCACConverter", devName: "DCAC变流器-1" };
const windConverter = { devId: "DCACConverter-1", devType: "ACDCConverter", devName: "风机变流器-1" };
const branch = { devId: "DCBreak-29", devType: "DCBreak", devName: "直流断路器-29" };
const dcToAcNodes = [
  { terminal: 1, domain: "dc", key: "DC:21" },
  { terminal: 2, domain: "ac", key: "AC:23" },
];
const acToDcNodes = [
  { terminal: 1, domain: "ac", key: "AC:1" },
  { terminal: 2, domain: "dc", key: "DC:11" },
];
const branchNodes = [
  { terminal: 1, domain: "dc", key: "DC:11" },
  { terminal: 2, domain: "dc", key: "DC:21" },
];

const converterFallback = flowMaps(intertie, [
  { meas_type: "P_AC", value: 0, valid: 1 },
  { meas_type: "P_DC", value: -10, valid: 1 },
]);
const invalidScada = flowMaps(intertie, [
  { meas_type: "P_AC", value: 0, valid: 0 },
  { meas_type: "P_DC", value: 0, valid: 0 },
], [
  { meas_type: "P_AC", value: 6, valid: 1 },
  { meas_type: "P_DC", value: -6, valid: 1 },
]);
const branchFallback = flowMaps(branch, [
  { meas_type: "P_FROM", value: 0, valid: 1 },
  { meas_type: "P_TO", value: 7, valid: 1 },
]);
const converterTopology = {
  byId: new Map([[intertie.devId, { device: intertie, nodes: dcToAcNodes }]]),
  byNode: new Map(),
};
const ownBinding = diagramFlowPowerBindings(intertie, null, converterTopology)[0];

process.stdout.write(JSON.stringify({
  canonical: {
    dcacPAc: diagramFlowCanonicalPower("P_AC", 10, "DCACConverter"),
    acdcPAc: diagramFlowCanonicalPower("P_AC", 10, "ACDCConverter"),
    dcacPDc: diagramFlowCanonicalPower("P_DC", -10, "DCACConverter"),
    dcToAcPAc: diagramFlowCanonicalPower("P_AC", -10, "DCACConverter"),
    dcToAcPDc: diagramFlowCanonicalPower("P_DC", 10, "DCACConverter"),
    genericPAc: diagramFlowCanonicalPower("P_AC", 10),
    pFrom: diagramFlowCanonicalPower("P_FROM", -7),
    pTo: diagramFlowCanonicalPower("P_TO", 7),
  },
  routeOrientation: {
    dcToAc: diagramFlowPowerRouteOrientation(intertie, dcToAcNodes),
    acToDc: diagramFlowPowerRouteOrientation(windConverter, acToDcNodes),
    branch: diagramFlowPowerRouteOrientation(branch, branchNodes),
  },
  converterFallback: resolve(intertie, dcToAcNodes, converterFallback),
  converterTerminalTwo: resolve(intertie, dcToAcNodes, flowMaps(intertie, [
    { meas_type: "P_AC", value: 10, valid: 1 },
  ])),
  converterTerminalOne: resolve(windConverter, acToDcNodes, flowMaps(windConverter, [
    { meas_type: "P_AC", value: 8, valid: 1 },
    { meas_type: "P_DC", value: -8, valid: 1 },
  ])),
  reversedBinding: resolve(
    intertie,
    dcToAcNodes,
    converterFallback,
    -diagramFlowPowerRouteOrientation(intertie, dcToAcNodes),
  ),
  branchFallback: resolve(branch, branchNodes, branchFallback),
  realFallback: resolve(intertie, dcToAcNodes, invalidScada),
  ownBinding: { orientation: ownBinding.orientation, nodes: ownBinding.nodes },
}));
"""
        expected = {
            "canonical": {
                "dcacPAc": -10,
                "acdcPAc": -10,
                "dcacPDc": -10,
                "dcToAcPAc": 10,
                "dcToAcPDc": 10,
                "genericPAc": -10,
                "pFrom": -7,
                "pTo": -7,
            },
            "routeOrientation": {"dcToAc": 1, "acToDc": -1, "branch": 1},
            "converterFallback": {"measType": "P_DC", "power": -10, "valid": True},
            "converterTerminalTwo": {"measType": "P_AC", "power": -10, "valid": True},
            "converterTerminalOne": {"measType": "P_AC", "power": 8, "valid": True},
            "reversedBinding": {"measType": "P_DC", "power": 10, "valid": True},
            "branchFallback": {"measType": "P_TO", "power": -7, "valid": True},
            "realFallback": {"measType": "P_AC", "power": -6, "valid": True},
            "ownBinding": {
                "orientation": 1,
                "nodes": [
                    {"terminal": 1, "domain": "dc", "key": "DC:21"},
                    {"terminal": 2, "domain": "ac", "key": "AC:23"},
                ],
            },
        }
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_flow_helpers(path.read_text(encoding="utf-8"), body),
                    expected,
                )

    def test_hydrogen_edges_use_signed_flow_and_endpoint_direction(self):
        body = """
function flowMap(coupling, endpoint, value) {
  const key = diagramDeviceMeasurementKey(endpoint.devType, endpoint.devName, "FLOW");
  return {
    scadaByDevice: new Map([[key, { meas_type: "flow", value, valid: 1 }]]),
    realByDevice: new Map(),
    couplingEndpoints: new Map([[
      diagramCouplingMeasurementEndpointKey(coupling.devType, coupling.devName),
      { electric: null, hydrogen: endpoint },
    ]]),
  };
}
function compact(binding, maps) {
  const resolved = diagramFlowResolvePower(binding, maps);
  const threshold = diagramFlowArrowThreshold(resolved.row?.meas_type, 0.1, 0.1);
  return {
    kind: binding?.kind || "",
    orientation: binding?.orientation ?? null,
    measurementTypes: binding?.powerBindings?.[0]?.measurementTypes || [],
    measType: resolved.row?.meas_type || "",
    flow: resolved.power,
    direction: diagramFlowArrowDirection(resolved.power, binding?.orientation),
    visible: diagramFlowArrowVisibility({ power: resolved.power, threshold, valid: resolved.valid }),
    valid: resolved.valid,
  };
}

const electrolyzer = { devId: "AcE2Hydro-1", devType: "AcE2Hydro", devName: "electrolyzer-1" };
const fuelCell = { devId: "Hydro2DcE-1", devType: "Hydro2DcE", devName: "fuel-cell-1" };
const hydrogenSource = { devType: "HydroSource", devName: "electrolyzer-source-1" };
const hydrogenLoad = { devType: "HydroLoad", devName: "fuel-cell-load-1" };
const tank = { devId: "HydroStorage-3", devType: "HydroStorage", devName: "tank-1" };
const sourceEntry = { device: electrolyzer, nodes: [{ terminal: 2, domain: "hydro", key: "HYDRO:1" }] };
const loadEntry = { device: fuelCell, nodes: [{ terminal: 2, domain: "hydro", key: "HYDRO:1" }] };
const tankEntry = { device: tank, nodes: [{ terminal: 0, domain: "hydro", key: "HYDRO:1" }] };
const topology = { byId: new Map(), byNode: new Map() };

const sourceToTank = diagramFlowEdgeBinding(sourceEntry, tankEntry, topology);
const fuelCellToTank = diagramFlowEdgeBinding(loadEntry, tankEntry, topology);
const tankToFuelCell = diagramFlowEdgeBinding(tankEntry, loadEntry, topology);
process.stdout.write(JSON.stringify({
  roles: {
    electrolyzer: diagramHydrogenFlowRole(electrolyzer.devType),
    fuelCell: diagramHydrogenFlowRole(fuelCell.devType),
    tank: diagramHydrogenFlowRole(tank.devType),
  },
  sourceToTank: compact(sourceToTank, flowMap(electrolyzer, hydrogenSource, 4)),
  fuelCellToTank: compact(fuelCellToTank, flowMap(fuelCell, hydrogenLoad, 6.67)),
  tankToFuelCell: compact(tankToFuelCell, flowMap(fuelCell, hydrogenLoad, 6.67)),
  fuelCellResidual: compact(fuelCellToTank, flowMap(fuelCell, hydrogenLoad, -0.02)),
}));
"""
        expected = {
            "roles": {
                "electrolyzer": "source",
                "fuelCell": "load",
                "tank": "storage",
            },
            "sourceToTank": {
                "kind": "hydrogen",
                "orientation": 1,
                "measurementTypes": ["FLOW"],
                "measType": "flow",
                "flow": 4,
                "direction": 1,
                "visible": True,
                "valid": True,
            },
            "fuelCellToTank": {
                "kind": "hydrogen",
                "orientation": -1,
                "measurementTypes": ["FLOW"],
                "measType": "flow",
                "flow": 6.67,
                "direction": -1,
                "visible": True,
                "valid": True,
            },
            "tankToFuelCell": {
                "kind": "hydrogen",
                "orientation": 1,
                "measurementTypes": ["FLOW"],
                "measType": "flow",
                "flow": 6.67,
                "direction": 1,
                "visible": True,
                "valid": True,
            },
            "fuelCellResidual": {
                "kind": "hydrogen",
                "orientation": -1,
                "measurementTypes": ["FLOW"],
                "measType": "flow",
                "flow": -0.02,
                "direction": 1,
                "visible": False,
                "valid": True,
            },
        }
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_flow_helpers(path.read_text(encoding="utf-8"), body),
                    expected,
                )

    def test_coupling_metrics_resolve_endpoint_measurements_without_duplicated_points(self):
        body = """
function measurementKey(row) {
  return `${row.dev_type}.${row.dev_name}.${row.meas_type}`;
}
const couplingTypes = ["AcE2Hydro", "DcE2Hydro", "Hydro2AcE", "Hydro2DcE"];
const endpointSpecs = [
  ["AcE2Hydro", "ac-electrolyzer", "ACLoad", "ac-load", "HydroSource", "h2-source", "P_LOAD", "V_LOAD"],
  ["DcE2Hydro", "dc-electrolyzer", "DCLoad", "dc-load", "HydroSource", "dc-h2-source", "P_LOAD", "V_LOAD"],
  ["Hydro2AcE", "ac-fuel-cell", "ACGenerator", "ac-generator", "HydroLoad", "ac-h2-load", "P_GEN", "V_GEN"],
  ["Hydro2DcE", "dc-fuel-cell", "DCGenerator", "dc-generator", "HydroLoad", "dc-h2-load", "P_GEN", "V_GEN"],
];
const devices = [];
const scada = [];
endpointSpecs.forEach(([type, name, electricType, electricName, hydrogenType, hydrogenName, pType, vType], index) => {
  devices.push({
    dev_type: type,
    dev_name: name,
    control_bindings: [
      { set_type: "p_set", target_dev_type: electricType, target_dev_name: electricName },
      { set_type: "flow_set", target_dev_type: hydrogenType, target_dev_name: hydrogenName },
    ],
  });
  scada.push(
    { dev_type: electricType, dev_name: electricName, meas_type: pType, value: 10 + index, valid: 1 },
    { dev_type: electricType, dev_name: electricName, meas_type: vType, value: 380 + index, valid: 1 },
    { dev_type: hydrogenType, dev_name: hydrogenName, meas_type: "flow", value: 2 + index, valid: 1 },
    { dev_type: type, dev_name: name, meas_type: "p", value: 999, valid: 1 },
    { dev_type: type, dev_name: name, meas_type: "u", value: 999, valid: 1 },
    { dev_type: type, dev_name: name, meas_type: "flow", value: 999, valid: 1 },
  );
});
const maps = diagramMeasurementMaps({ devices, measurements: { scada, real: [] } });
const values = endpointSpecs.map(([devType, devName]) => {
  const binding = { devType, devName };
  const electricArrow = diagramFlowDevicePowerSample(binding, maps);
  const hydrogenArrow = diagramFlowDevicePowerSample(binding, maps, ["FLOW"]);
  return {
    power: diagramMetricBindingValue({ ...binding, metricType: "activePower" }, maps)?.value ?? null,
    voltage: diagramMetricBindingValue({ ...binding, metricType: "voltage" }, maps)?.value ?? null,
    flow: diagramMetricBindingValue({ ...binding, metricType: "flow" }, maps)?.value ?? null,
    electricArrow: electricArrow?.power ?? null,
    hydrogenArrow: hydrogenArrow?.power ?? null,
  };
});
process.stdout.write(JSON.stringify({ couplingTypes, values }));
"""
        expected = {
            "couplingTypes": ["AcE2Hydro", "DcE2Hydro", "Hydro2AcE", "Hydro2DcE"],
            "values": [
                {"power": 10, "voltage": 380, "flow": 2, "electricArrow": 10, "hydrogenArrow": 2},
                {"power": 11, "voltage": 381, "flow": 3, "electricArrow": 11, "hydrogenArrow": 3},
                {"power": 12, "voltage": 382, "flow": 4, "electricArrow": 12, "hydrogenArrow": 4},
                {"power": 13, "voltage": 383, "flow": 5, "electricArrow": 13, "hydrogenArrow": 5},
            ],
        }
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(self._run_flow_helpers(path.read_text(encoding="utf-8"), body), expected)

    def test_complete_hydrogen_path_uses_explicit_domains_inline_flows_and_status(self):
        body = """
function attrs(values) {
  return {
    getAttribute(name) { return values[name] ?? null; },
    parentElement: { getAttribute(name) { return name === "device-type" ? values.devType : null; } },
  };
}
function flowMap(rows) {
  return {
    scadaByDevice: new Map(rows.map(({ device, measType = "FLOW", value, valid = 1 }) => [
      diagramDeviceMeasurementKey(device.devType, device.devName, measType),
      { meas_type: measType, value, valid },
    ])),
    realByDevice: new Map(),
  };
}
function resolve(binding, maps) {
  const result = diagramFlowResolvePower(binding, maps);
  return { flow: result.power, valid: result.valid };
}
const source = { devId: "HydroSource-1", devType: "HydroSource", devName: "source" };
const pipe = { devId: "HydroPipe-1", devType: "HydroPipe", devName: "pipe" };
const valve = { devId: "HydroStopValve-1", devType: "HydroStopValve", devName: "valve" };
const compressor = { devId: "HydroCompressor-1", devType: "HydroCompressor", devName: "compressor" };
const regulator = { devId: "HydroPressRegulator-1", devType: "HydroPressRegulator", devName: "regulator" };
const load = { devId: "HydroLoad-1", devType: "HydroLoad", devName: "load" };
const entries = [
  { device: source, element: attrs({ devType: source.devType, node: "1" }) },
  { device: pipe, element: attrs({ devType: pipe.devType, "node-1": "1", "node-2": "2" }) },
  { device: valve, element: attrs({ devType: valve.devType, "node-1": "2", "node-2": "3" }) },
  { device: compressor, element: attrs({ devType: compressor.devType, "node-1": "3", "node-2": "4" }) },
  { device: regulator, element: attrs({ devType: regulator.devType, "node-1": "4", "node-2": "5" }) },
  { device: load, element: attrs({ devType: load.devType, node: "5" }) },
];
entries.forEach((entry) => { entry.nodes = diagramFlowDeviceNodes(entry.element); });
const topology = { byId: new Map(entries.map((entry) => [entry.device.devId, entry])), byNode: new Map() };
entries.forEach((entry) => entry.nodes.forEach(({ key }) => {
  if (!topology.byNode.has(key)) topology.byNode.set(key, []);
  topology.byNode.get(key).push(entry);
}));
const maps = flowMap([
  { device: pipe, value: 4 },
  { device: valve, value: 4 },
  { device: compressor, value: 4 },
  { device: regulator, value: -3 },
  { device: source, value: 2 },
]);
const pipeBinding = { powerBindings: diagramFlowPowerBindings(pipe, entries[1].element, topology) };
const sourceToPipe = diagramFlowEdgeBinding(entries[0], entries[1], topology);
const pipeToValve = diagramFlowEdgeBinding(entries[1], entries[2], topology);
const regulatorToLoad = diagramFlowEdgeBinding(entries[4], entries[5], topology);
process.stdout.write(JSON.stringify({
  domains: entries.map((entry) => entry.nodes.map(({ domain }) => domain)),
  ownPipe: resolve(pipeBinding, maps),
  reversedPipe: resolve(pipeBinding, flowMap([{ device: pipe, value: -4 }])),
  sourceToPipe: { ...resolve(sourceToPipe, maps), direction: diagramFlowArrowDirection(resolve(sourceToPipe, maps).flow, sourceToPipe.orientation) },
  pipeToValve: { ...resolve(pipeToValve, maps), direction: diagramFlowArrowDirection(resolve(pipeToValve, maps).flow, pipeToValve.orientation) },
  regulatorToLoad: { ...resolve(regulatorToLoad, maps), direction: diagramFlowArrowDirection(resolve(regulatorToLoad, maps).flow, regulatorToLoad.orientation) },
  valveClosed: diagramFlowDeviceBlocksFlow(valve, { status: 0 }, flowMap([])),
  valveOpen: diagramFlowDeviceBlocksFlow(valve, { status: 1 }, flowMap([])),
  flowStatusWins: diagramFlowDeviceBlocksFlow(valve, { status: 1 }, flowMap([{ device: valve, measType: "STATUS", value: 0 }])),
}));
"""
        expected = {
            "domains": [
                ["hydro"],
                ["hydro", "hydro"],
                ["hydro", "hydro"],
                ["hydro", "hydro"],
                ["hydro", "hydro"],
                ["hydro"],
            ],
            "ownPipe": {"flow": 4, "valid": True},
            "reversedPipe": {"flow": -4, "valid": True},
            "sourceToPipe": {"flow": 4, "valid": True, "direction": 1},
            "pipeToValve": {"flow": 4, "valid": True, "direction": 1},
            "regulatorToLoad": {"flow": -3, "valid": True, "direction": -1},
            "valveClosed": True,
            "valveOpen": False,
            "flowStatusWins": True,
        }
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_flow_helpers(path.read_text(encoding="utf-8"), body),
                    expected,
                )

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

    def test_fit_expands_view_box_to_include_measurement_frames(self):
        body = """
const attributes = { viewBox: "0 0 2518 2143" };
const svgRect = { left: 20, top: 100, width: 1220.8, height: 506 };
const scale = svgRect.height / 2143;
const drawingLeft = svgRect.left + (svgRect.width - 2518 * scale) / 2;
const measurementFrame = {
  getBoundingClientRect() {
    return {
      left: drawingLeft + 1403.89878 * scale,
      top: svgRect.top + 2078.35015 * scale,
      width: 148.20244 * scale,
      height: 88.44954 * scale,
    };
  },
};
const viewport = {
  svg: {
    getAttribute(name) {
      if (name === "preserveAspectRatio") return "xMidYMid meet";
      return attributes[name] || null;
    },
    getBoundingClientRect() {
      return svgRect;
    },
    querySelectorAll(selector) {
      return selector === ".diagram-measurement-layer" ? [measurementFrame] : [];
    },
    setAttribute(name, value) { attributes[name] = String(value); },
  },
  source: { x: 0, y: 0, width: 2518, height: 2143 },
  original: { x: 0, y: 0, width: 2518, height: 2143 },
  current: { x: 0, y: 0, width: 2518, height: 2143 },
};
const fitted = fitDiagramViewport(viewport);
process.stdout.write(JSON.stringify({ fitted, current: viewport.current, original: viewport.original, attributes }));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                payload = self._run_helpers(path.read_text(encoding="utf-8"), body)
                self.assertTrue(payload["fitted"])
                self.assertEqual(payload["current"]["x"], 0)
                self.assertEqual(payload["current"]["y"], 0)
                self.assertEqual(payload["current"]["width"], 2518)
                self.assertGreater(payload["current"]["height"], 2166.79969)
                self.assertEqual(payload["original"], payload["current"])
                self.assertEqual(
                    [float(value) for value in payload["attributes"]["viewBox"].split()],
                    [
                        payload["current"]["x"],
                        payload["current"]["y"],
                        payload["current"]["width"],
                        payload["current"]["height"],
                    ],
                )

    def test_new_diagram_runs_fit_after_realtime_measurements_are_rendered(self):
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                render_block = script.split("function renderModelDiagramPage", 1)[1].split(
                    'window.addEventListener("storage"',
                    1,
                )[0]
                self.assertIn("const diagramChanged = canvas.dataset.diagramKey !== key", render_block)
                realtime_index = render_block.index("updateDiagramRealtimeBindings(canvas, activeSnapshot)")
                fit_index = render_block.index("fitDiagramViewport(diagramViewportState(canvas))")
                self.assertLess(realtime_index, fit_index)

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

    def test_switch_symbol_prefers_calculated_closed_status_over_setpoint_and_legacy_measurement(self):
        body = """
const device = { devType: "ACBreak", devName: "br1" };
const key = diagramDeviceMeasurementKey("ACBreak", "br1", "STATUS");
const payload = {
  calculated: diagramSwitchActualValue(device, {
    deviceRuntimeByDevice: new Map([[diagramDeviceStateKey("ACBreak", "br1"), {
      closed_status: 0,
      closed_status_set: 1,
      status: 1,
    }]]),
    scadaByDevice: new Map([[key, { value: 1 }]]),
    realByDevice: new Map(),
  }),
  legacy: diagramSwitchActualValue(device, {
    deviceRuntimeByDevice: new Map(),
    scadaByDevice: new Map([[key, { value: 1 }]]),
    realByDevice: new Map(),
  }),
};
process.stdout.write(JSON.stringify(payload));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                payload = self._run_helpers(path.read_text(encoding="utf-8"), body)
                self.assertEqual(payload, {"calculated": 0, "legacy": 1})

    def test_switch_definition_rows_show_runtime_setpoint_and_calculated_status(self):
        body = """
const records = [{
  blockName: "ACBreak",
  headers: ["idx", "name", "closed_status_set", "closed_status", "status"],
  row: {
    idx: 3,
    name: "盒型开关-3",
    closed_status_set: 1,
    closed_status: 1,
    status: 1,
  },
}];
applyDiagramDeviceDefinitionRuntimeValues(records, {
  dev_type: "ACBreak",
  dev_name: "盒型开关-3",
  closed_status_set: 0,
  closed_status: 0,
  status: 1,
});
process.stdout.write(JSON.stringify(records[0].row));
"""
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                payload = self._run_helpers(path.read_text(encoding="utf-8"), body)
                self.assertEqual(
                    payload,
                    {
                        "idx": 3,
                        "name": "盒型开关-3",
                        "closed_status_set": 0,
                        "closed_status": 0,
                        "status": 0,
                    },
                )

    def test_measurement_rows_never_fall_back_to_the_device_tooltip(self):
        body = """
global.Element = class Element {
  constructor(tagName, attrs = {}, parent = null) {
    this.tagName = tagName;
    this.attrs = attrs;
    this.parentElement = parent;
    this.children = [];
    if (parent) parent.children.push(this);
  }
  getAttribute(name) { return this.attrs[name] ?? null; }
  hasAttribute(name) { return this.attrs[name] !== undefined; }
  matches(selector) {
    if (selector === "[mt]") return this.hasAttribute("mt");
    if (selector === "[dev]") return this.hasAttribute("dev");
    if (selector === "[dev-id]") return this.hasAttribute("dev-id");
    if (selector === "[device-type]") return this.hasAttribute("device-type");
    if (selector === "text") return String(this.tagName).toLowerCase() === "text";
    if (selector === "use[id][name]") {
      return String(this.tagName).toLowerCase() === "use"
        && this.hasAttribute("id")
        && this.hasAttribute("name");
    }
    if (selector === DIAGRAM_DEVICE_ELEMENT_SELECTOR) {
      return this.hasAttribute("dev-id")
        || (selector.includes("[dev]") && this.hasAttribute("dev"))
        || (String(this.tagName).toLowerCase() === "use"
          && this.hasAttribute("id")
          && this.hasAttribute("name"));
    }
    return false;
  }
  closest(selector) {
    let current = this;
    while (current) {
      if (current.matches(selector)) return current;
      current = current.parentElement;
    }
    return null;
  }
  querySelector(selector) {
    for (const child of this.children) {
      if (child.matches(selector)) return child;
      const nested = child.querySelector(selector);
      if (nested) return nested;
    }
    return null;
  }
  contains(candidate) {
    let current = candidate;
    while (current) {
      if (current === this) return true;
      current = current.parentElement;
    }
    return false;
  }
};

const container = new Element("div");
const deviceGraphic = new Element("use", {
  "dev-id": "ACGenerator-14",
  id: "ACGenerator-14",
  name: "柴油发电机-4",
}, container);
const deviceLabel = new Element("text", { "dev-id": "ACGenerator-14" }, container);
const metricGroup = new Element("g", { dev: "ACGenerator-14" }, container);
const metricRow = new Element("text", {}, metricGroup);
const metricLabel = new Element("tspan", {}, metricRow);
const metricValue = new Element("tspan", { mt: "activePower" }, metricRow);
const metricUnit = new Element("tspan", {}, metricRow);

container.querySelectorAll = function querySelectorAll(selector) {
  if (selector === "[dev-id][name], use[id][name]") return [deviceGraphic];
  if (selector === DIAGRAM_DEVICE_ELEMENT_SELECTOR) return [deviceGraphic, deviceLabel];
  return [];
};

function summarize(target) {
  const hover = diagramHoverTarget(container, target);
  return hover ? {
    kind: hover.kind,
    key: hover.key,
    metricType: hover.binding?.metricType || "",
  } : null;
}

process.stdout.write(JSON.stringify({
  deviceGraphic: summarize(deviceGraphic),
  deviceLabel: summarize(deviceLabel),
  metricLabel: summarize(metricLabel),
  metricValue: summarize(metricValue),
  metricUnit: summarize(metricUnit),
  metricGroup: summarize(metricGroup),
}));
"""
        expected = {
            "deviceGraphic": {
                "kind": "device",
                "key": "device:ACGenerator-14",
                "metricType": "",
            },
            "deviceLabel": {
                "kind": "device",
                "key": "device:ACGenerator-14",
                "metricType": "",
            },
            "metricLabel": {
                "kind": "metric",
                "key": "metric:ACGenerator-14:activePower",
                "metricType": "activePower",
            },
            "metricValue": {
                "kind": "metric",
                "key": "metric:ACGenerator-14:activePower",
                "metricType": "activePower",
            },
            "metricUnit": {
                "kind": "metric",
                "key": "metric:ACGenerator-14:activePower",
                "metricType": "activePower",
            },
            "metricGroup": None,
        }
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                self.assertEqual(
                    self._run_selection_helpers(path.read_text(encoding="utf-8"), body),
                    expected,
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
const deviceALabel = fakeElement("text", { "dev-id": "device-A" });
const metricGroup = fakeElement("g", { dev: "device-A" });
const deviceBGraphic = fakeElement("use", { id: "device-B", name: "B" });
const elements = [stale, deviceAGraphic, deviceALabel, metricGroup, deviceBGraphic];
const deviceElements = elements.filter((element) => (
  element.hasAttribute("dev-id")
  || (String(element.tagName).toLowerCase() === "use" && element.hasAttribute("id") && element.hasAttribute("name"))
));
const container = {
  dataset: {},
  querySelectorAll(selector) {
    if (selector === ".is-diagram-selected") {
      return elements.filter((element) => element.classList.contains("is-diagram-selected"));
    }
    if (selector === "[dev-id], use[id][name]") return deviceElements;
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
        common_required = (
            "function diagramMetricTooltipData",
            "function updateDiagramMetricTooltip",
            "function updateDiagramTrendChart",
            "function syncDiagramTrendAxisTicks",
            "data-diagram-tooltip-current-value",
            "data-diagram-tooltip-current-unit",
            "data-diagram-tooltip-validity",
            "data-diagram-trend-axis-ticks",
            'data-diagram-trend-series="scada"',
            'data-diagram-trend-cursor-point="scada"',
            "data-diagram-trend-stat-scada-latest",
            "data-diagram-trend-range-start",
            "data-diagram-trend-range-end",
        )
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                for token in common_required:
                    self.assertIn(token, script)
                real_tokens = (
                    'data-diagram-trend-series="real"',
                    'data-diagram-trend-cursor-point="real"',
                    "data-diagram-trend-stat-real-latest",
                )
                for token in real_tokens:
                    if path.parent.name == "simulator":
                        self.assertIn(token, script)
                    else:
                        self.assertNotIn(token, script)

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

    def test_coupling_device_tooltip_pages_deduplicate_bound_devices(self):
        body = r"""
const host = { devType: "AcE2Hydro", devName: "electrolyzer", devId: "h2-1" };
const snapshot = {
  devices: [
    {
      dev_type: "AcE2Hydro",
      dev_name: "electrolyzer",
      control_bindings: [
        { target_dev_type: "ACLoad", target_dev_name: "electrolyzer-load" },
        { target_dev_type: "ACLoad", target_dev_name: "electrolyzer-load" },
        { target_dev_type: "HydroSource", target_dev_name: "hydrogen-source" },
      ],
    },
    { dev_type: "ACLoad", dev_name: "electrolyzer-load" },
    { dev_type: "HydroSource", dev_name: "hydrogen-source" },
  ],
  definedDevices: [],
};
const pages = diagramCouplingDevicePages(host, snapshot);
process.stdout.write(JSON.stringify(pages.map((page) => ({
  key: page.key,
  label: page.label,
  devType: page.device.devType,
  devName: page.device.devName,
}))));
"""
        expected = [
            {
                "key": "self",
                "label": "设备本体",
                "devType": "AcE2Hydro",
                "devName": "electrolyzer",
            },
            {
                "key": "related:ACLOAD|electrolyzer-load",
                "label": "electrolyzer-load",
                "devType": "ACLoad",
                "devName": "electrolyzer-load",
            },
            {
                "key": "related:HYDROSOURCE|hydrogen-source",
                "label": "hydrogen-source",
                "devType": "HydroSource",
                "devName": "hydrogen-source",
            },
        ]
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                self.assertEqual(self._run_coupling_tooltip_helpers(script, body), expected)

    def test_coupling_device_tooltip_tab_state_survives_refresh_and_resets_for_new_host(self):
        body = r"""
const pages = [
  { key: "self", label: "设备本体", device: { devType: "AcE2Hydro", devName: "one" } },
  { key: "related:ACLOAD|load", label: "load", device: { devType: "ACLoad", devName: "load" } },
];
const interaction = {};
const first = diagramActiveDeviceTooltipPage(interaction, { key: "device:one" }, pages).key;
interaction.deviceTooltipTabKey = "related:ACLOAD|load";
const refreshed = diagramActiveDeviceTooltipPage(interaction, { key: "device:one" }, pages).key;
const changed = diagramActiveDeviceTooltipPage(interaction, { key: "device:two" }, pages).key;
const ordinary = diagramCouplingDevicePages(
  { devType: "ACLoad", devName: "ordinary", devId: "load-2" },
  { devices: [{ dev_type: "ACLoad", dev_name: "ordinary" }], definedDevices: [] },
);
process.stdout.write(JSON.stringify({
  first,
  refreshed,
  changed,
  current: interaction.deviceTooltipTabKey,
  ordinaryCount: ordinary.length,
}));
"""
        expected = {
            "first": "self",
            "refreshed": "related:ACLOAD|load",
            "changed": "self",
            "current": "self",
            "ordinaryCount": 1,
        }
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                self.assertEqual(self._run_coupling_tooltip_helpers(script, body), expected)

    def test_coupling_device_tooltip_tabs_are_wired_without_rebuilding_on_refresh(self):
        required = (
            "function diagramCouplingDevicePages",
            "function diagramActiveDeviceTooltipPage",
            "function renderDiagramDeviceTabs",
            "function syncDiagramDeviceTabs",
            'role="tablist"',
            'role="tab"',
            "data-diagram-device-tab",
            "deviceTooltipHostKey",
            "deviceTooltipTabKey",
            "target_dev_type",
            "target_dev_name",
        )
        for path in self._scripts():
            with self.subTest(app=path.parent.name):
                script = path.read_text(encoding="utf-8")
                for token in required:
                    self.assertIn(token, script)
                update_block = script.split("function updateDiagramDeviceTooltip", 1)[1].split(
                    "function diagramMetricCurrentRow",
                    1,
                )[0]
                self.assertIn("syncDiagramDeviceTabs(tooltip, data, interaction)", update_block)
                self.assertNotIn("tooltip.innerHTML", update_block)
                click_block = script.split('tooltip.addEventListener("click"', 1)[1].split(
                    "function updateDiagramRealtimeBindings",
                    1,
                )[0]
                self.assertIn('target.closest("[data-diagram-device-tab]")', click_block)
                self.assertIn("diagramDefinitionEditPinned(interaction)", click_block)

    def test_coupling_device_tooltip_tab_styles_are_available_in_both_apps(self):
        required = (
            ".diagram-device-tabs",
            ".diagram-device-tab",
            '.diagram-device-tab[aria-selected="true"]',
            ".diagram-device-tab-panel",
            "overflow-x: auto",
        )
        for path in self._styles():
            with self.subTest(app=path.parent.name):
                styles = path.read_text(encoding="utf-8")
                for token in required:
                    self.assertIn(token, styles)

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
