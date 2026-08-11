from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MeasurementIncrementalRefreshUiTest(unittest.TestCase):
    def test_simulator_realtime_measurement_table_updates_live_cells_without_full_rebuild(self):
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function measurementCompareTableStructureKey", script)
        self.assertIn("function updateMeasurementCompareTableLiveCells", script)
        self.assertIn("data-measurement-row-key", script)
        self.assertIn("data-measurement-live-field", script)
        self.assertIn("measurementCompareTableStructureKey(rows)", script)
        self.assertIn("updateMeasurementCompareTableLiveCells(rows, selectedKey)", script)

    def test_both_consoles_request_and_merge_compact_measurements_in_the_snapshot_poll(self):
        for role in ("simulator", "trainee"):
            script = (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")

            self.assertIn('params.set("measurement_after_seq", String(state.measurementDeltaSeq || 0));', script)
            self.assertIn('params.set("measurement_compact", "1");', script)
            self.assertIn("function applyMeasurementArrayFrame", script)
            self.assertIn("payload.encoding === \"measurement-arrays-v1\"", script)
            self.assertIn("实时量测数组长度不一致", script)
            self.assertIn("function applyEmbeddedMeasurementDelta", script)

    def test_measurement_delta_merge_builds_channel_indexes_once_per_refresh(self):
        for role in ("simulator", "trainee"):
            script = (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")
            apply_source = "function applyMeasurementDelta" + script.split(
                "function applyMeasurementDelta",
                1,
            )[1].split("async function refreshMeasurementDelta", 1)[0]

            self.assertIn('appendMeasurementTraceAfterDelta(', apply_source)
            self.assertNotIn('.find((entry) => measurementNameKey(entry)', apply_source)

    def test_measurement_delta_records_trace_after_the_frame_is_applied(self):
        for role in ("simulator", "trainee"):
            script = (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")
            merge_source = "function appendMeasurementTraceAfterDelta" + script.split(
                "function appendMeasurementTraceAfterDelta",
                1,
            )[1].split("async function refreshMeasurementDelta", 1)[0]
            append_source = "function appendMeasurementTrace" + script.split(
                "function appendMeasurementTrace",
                1,
            )[1].split("function ensureSelectedMeasurementKey", 1)[0]

            self.assertIn("appendMeasurementTrace(state.snapshot)", merge_source)
            self.assertIn("const rows = measurementCompareRows(snapshot.measurements || {})", append_source)
            self.assertIn("if (!rows.some", append_source)
            self.assertIn("state.lastMeasurementTraceKey = signature", append_source)
            self.assertIn("snapshot.measurement_clock", append_source)

    def test_measurement_trace_upserts_repeated_updates_for_the_same_simulation_frame(self):
        for role in ("simulator", "trainee"):
            script = (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")
            append_source = "function appendMeasurementTrace(snapshot)" + script.split(
                "function appendMeasurementTrace(snapshot)",
                1,
            )[1].split("function resetMeasurementHistoryHydration", 1)[0]
            node_script = f"""
const state = {{
  activeModelId: "model-a",
  measurementTraceHistory: [],
  measurementTraceWindowMinutes: 60,
  lastMeasurementTraceKey: "",
}};
const numberOrNull = (value) => Number.isFinite(Number(value)) ? Number(value) : null;
const diagramTrendFiniteValue = numberOrNull;
const isSimulationPausedSnapshot = () => false;
const measurementCompareRows = (measurements) => measurements.rows || [];
const measurementKey = (row) => row.name;
const measurementDisplayName = (row) => row.name;
const measurementDeviceDisplay = (row) => row.dev_name;
const measurementTypeDisplay = (row) => row.meas_type;
const measurementUnit = () => "m/s";
const compactTraceHistory = (history) => history;
const measurementHistoryPointKey = (point) => [
  Number(point?.run_id ?? 0) || 0,
  Number(point?.step_count ?? -1),
  Number(point?.minute ?? 0) || 0,
].join("|");
const compareMeasurementHistoryPoints = (left, right) => (
  (Number(left?.run_id) || 0) - (Number(right?.run_id) || 0)
  || (Number(left?.step_count) || 0) - (Number(right?.step_count) || 0)
  || (Number(left?.minute) || 0) - (Number(right?.minute) || 0)
);
{append_source}
const snapshot = (updated, value, minute = 32, measurementMinute = minute) => ({{
  model: {{ id: "model-a" }},
  clock: {{
    absolute_minute: minute,
    time: `00:${{String(minute).padStart(2, "0")}}:00`,
    run_id: 7,
    step_count: minute,
  }},
  measurement_clock: {{
    absolute_minute: measurementMinute,
    time: `00:${{String(measurementMinute).padStart(2, "0")}}:00`,
    run_id: 7,
    step_count: minute,
  }},
  result: {{ updated }},
  summary: {{ scada_count: 1 }},
  measurements: {{
    rows: [{{
      name: "Environment.weather.WIND_SPEED",
      dev_type: "Environment",
      dev_name: "weather",
      meas_type: "WIND_SPEED",
      real_value: value,
      scada_value: value,
      valid: 1,
    }}],
  }},
}});
appendMeasurementTrace(snapshot("first", 20.5, 33, 32));
appendMeasurementTrace(snapshot("delta", 20.4, 33, 32));
appendMeasurementTrace(snapshot("stale", 20.3, 31));
const point = state.measurementTraceHistory[0];
const measurement = point.measurements["Environment.weather.WIND_SPEED"];
process.stdout.write(JSON.stringify({{
  count: state.measurementTraceHistory.length,
  minute: point.minute,
  value: measurement.value ?? measurement.scada,
}}));
"""
            completed = subprocess.run(
                ["node", "-"],
                check=True,
                capture_output=True,
                input=node_script,
                text=True,
                encoding="utf-8",
            )
            result = json.loads(completed.stdout)

            with self.subTest(role=role):
                self.assertEqual(result["count"], 1)
                self.assertEqual(result["minute"], 32)
                self.assertEqual(result["value"], 20.4)

    def test_array_frame_updates_by_definition_index_without_measurement_names(self):
        for role in ("simulator", "trainee"):
            script = (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")
            array_source = "function applyMeasurementArrayFrame" + script.split(
                "function applyMeasurementArrayFrame",
                1,
            )[1].split("function applyMeasurementDelta", 1)[0]

            self.assertIn("definitions.length !== count", array_source)
            self.assertIn("const expectedValueCount = frame ? count : 0", array_source)
            self.assertIn("payload.real_values.length !== expectedValueCount", array_source)
            self.assertIn("payload.scada_values.length !== expectedValueCount", array_source)
            self.assertIn("payload.valid_values.length !== expectedValueCount", array_source)
            self.assertIn("definitions.map((definition, index)", array_source)
            self.assertNotIn("item.name", array_source)
            self.assertNotIn("definitionsByName", array_source)

    def test_array_frame_rejects_bad_lengths_without_partial_frontend_updates(self):
        for role in ("simulator", "trainee"):
            script = (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")
            functions = "function measurementDefinitionSignature" + script.split(
                "function measurementDefinitionSignature",
                1,
            )[1].split("function applyEmbeddedMeasurementDelta", 1)[0]
            node_script = f"""
const warnings = [];
const originalLog = console.log;
console.warn = (message) => warnings.push(String(message));
const $ = () => null;
const currentPageName = () => "measurements";
const addRuntimeLog = () => undefined;
const state = {{
  snapshot: {{ measurements: {{ definitions: [], real: [], scada: [] }} }},
  measurementDeltaSeq: 0,
  measurementArrayWarning: "",
}};
{functions}
const definitions = [
  {{ name: "测点A", dev_type: "Load", dev_name: "负荷A", meas_type: "P", weight: 1, valid: 1 }},
  {{ name: "测点B", dev_type: "Breaker", dev_name: "开关B", meas_type: "STATUS", weight: 1, valid: 1 }},
];
state.snapshot.measurements.definitions = definitions;
const good = {{
  encoding: "measurement-arrays-v1",
  frame: true,
  seq: 7,
  count: 2,
  definition_signature: measurementDefinitionSignature(definitions),
  simu_time: "01:02:03",
  wall_time: "04:05:06",
  absolute_minute: 62.05,
  real_values: [11.0, 1],
  scada_values: [10.8, 1],
  valid_values: [1, 1],
}};
const accepted = applyMeasurementDelta(good);
const beforeBad = JSON.stringify({{ measurements: state.snapshot.measurements, seq: state.measurementDeltaSeq }});
const bad = {{ ...good, seq: 8, count: 3 }};
const rejected = applyMeasurementDelta(bad);
const afterBad = JSON.stringify({{ measurements: state.snapshot.measurements, seq: state.measurementDeltaSeq }});
originalLog(JSON.stringify({{
  accepted,
  rejected,
  beforeBad,
  afterBad,
  warnings,
  real: state.snapshot.measurements.real.map((row) => row.value),
  scada: state.snapshot.measurements.scada.map((row) => row.value),
  seq: state.measurementDeltaSeq,
}}));
"""
            completed = subprocess.run(
                ["node", "-e", node_script],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            result = json.loads(completed.stdout)

            self.assertTrue(result["accepted"])
            self.assertFalse(result["rejected"])
            self.assertEqual(result["real"], [11, 1])
            self.assertEqual(result["scada"], [10.8, 1])
            self.assertEqual(result["seq"], 7)
            self.assertEqual(result["beforeBad"], result["afterBad"])
            self.assertTrue(any("实时量测数组长度不一致" in row for row in result["warnings"]))

    def test_array_frame_rejects_a_missing_definition_signature(self):
        for role in ("simulator", "trainee"):
            script = (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")
            functions = "function measurementDefinitionSignature" + script.split(
                "function measurementDefinitionSignature",
                1,
            )[1].split("function applyEmbeddedMeasurementDelta", 1)[0]
            node_script = f"""
const warnings = [];
const originalLog = console.log;
console.warn = (message) => warnings.push(String(message));
const $ = () => null;
const addRuntimeLog = () => undefined;
const state = {{
  snapshot: {{ measurements: {{ definitions: [], real: [], scada: [] }} }},
  measurementDeltaSeq: 0,
  measurementArrayWarning: "",
}};
{functions}
const definitions = [
  {{ name: "测点A", dev_type: "Load", dev_name: "负荷A", meas_type: "P", weight: 1, valid: 1 }},
];
state.snapshot.measurements.definitions = definitions;
const rejected = applyMeasurementDelta({{
  encoding: "measurement-arrays-v1",
  frame: true,
  seq: 9,
  count: 1,
  simu_time: "01:02:03",
  wall_time: "04:05:06",
  real_values: [11.0],
  scada_values: [10.8],
  valid_values: [1],
}});
originalLog(JSON.stringify({{
  rejected,
  seq: state.measurementDeltaSeq,
  realCount: state.snapshot.measurements.real.length,
  warnings,
}}));
"""
            completed = subprocess.run(
                ["node", "-e", node_script],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            result = json.loads(completed.stdout)

            self.assertFalse(result["rejected"])
            self.assertEqual(result["seq"], 0)
            self.assertEqual(result["realCount"], 0)
            self.assertTrue(any("定义顺序签名缺失" in row for row in result["warnings"]))

    def test_definition_signature_is_cached_by_definition_array_and_revision(self):
        for role in ("simulator", "trainee"):
            script = (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")
            function_source = "function measurementDefinitionSignature" + script.split(
                "function measurementDefinitionSignature",
                1,
            )[1].split("function reportMeasurementArrayWarning", 1)[0]
            node_script = f"""
const OriginalTextEncoder = TextEncoder;
let encoderConstructions = 0;
globalThis.TextEncoder = class {{
  constructor() {{
    encoderConstructions += 1;
    this.delegate = new OriginalTextEncoder();
  }}
  encode(value) {{ return this.delegate.encode(value); }}
}};
{function_source}
const definitions = [
  {{ name: "测点A", dev_type: "Load", dev_name: "负荷A", meas_type: "P" }},
];
const first = measurementDefinitionSignature(definitions, 3);
const second = measurementDefinitionSignature(definitions, 3);
const third = measurementDefinitionSignature(definitions, 4);
console.log(JSON.stringify({{ first, second, third, encoderConstructions }}));
"""
            completed = subprocess.run(
                ["node", "-e", node_script],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            result = json.loads(completed.stdout)

            self.assertEqual(result["first"], result["second"])
            self.assertEqual(result["second"], result["third"])
            self.assertEqual(result["encoderConstructions"], 2)

    def test_definition_signature_without_revision_recomputes_after_in_place_definition_change(self):
        for role in ("simulator", "trainee"):
            script = (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")
            function_source = "function measurementDefinitionSignature" + script.split(
                "function measurementDefinitionSignature",
                1,
            )[1].split("function reportMeasurementArrayWarning", 1)[0]
            node_script = f"""
{function_source}
const definitions = [
  {{ name: "测点A", dev_type: "Load", dev_name: "负荷A", meas_type: "P" }},
];
const before = measurementDefinitionSignature(definitions);
definitions[0].name = "测点B";
const after = measurementDefinitionSignature(definitions);
console.log(JSON.stringify({{ before, after }}));
"""
            completed = subprocess.run(
                ["node", "-e", node_script],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            result = json.loads(completed.stdout)

            self.assertNotEqual(result["before"], result["after"])

    def test_array_frame_uses_status_and_fixed_value_arrays_when_present(self):
        for role in ("simulator", "trainee"):
            script = (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")
            functions = "function measurementDefinitionSignature" + script.split(
                "function measurementDefinitionSignature",
                1,
            )[1].split("function applyEmbeddedMeasurementDelta", 1)[0]
            node_script = f"""
const warnings = [];
const addRuntimeLog = () => undefined;
const $ = () => null;
const state = {{
  snapshot: {{ measurements: {{ definitions: [], real: [], scada: [] }} }},
  measurementDeltaSeq: 0,
  measurementArrayWarning: "",
}};
{functions}
const definitions = [
  {{ name: "测点A", dev_type: "Load", dev_name: "负荷A", meas_type: "P", weight: 1, valid: 1 }},
  {{ name: "测点B", dev_type: "Breaker", dev_name: "开关B", meas_type: "STATUS", weight: 1, valid: 1 }},
];
state.snapshot.measurements.definitions = definitions;
const accepted = applyMeasurementDelta({{
  encoding: "measurement-arrays-v1",
  frame: true,
  seq: 7,
  count: 2,
  definition_signature: measurementDefinitionSignature(definitions),
  simu_time: "01:02:03",
  wall_time: "04:05:06",
  absolute_minute: 62.05,
  real_values: [11.0, 1],
  scada_values: [10.8, 0],
  valid_values: [1, 0],
  status_values: ["valid", "bad"],
  fixed_values: [null, 12.5],
}});
console.log(JSON.stringify({{
  accepted,
  realStatus: state.snapshot.measurements.real.map((row) => row.status),
  scadaStatus: state.snapshot.measurements.scada.map((row) => row.status),
  realFixed: state.snapshot.measurements.real.map((row) => row.fixed_value),
  scadaFixed: state.snapshot.measurements.scada.map((row) => row.fixed_value),
  realValid: state.snapshot.measurements.real.map((row) => row.valid),
  scadaValid: state.snapshot.measurements.scada.map((row) => row.valid),
}}));
"""
            completed = subprocess.run(
                ["node", "-e", node_script],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            result = json.loads(completed.stdout)

            self.assertTrue(result["accepted"])
            self.assertEqual(result["realStatus"], ["valid", "bad"])
            self.assertEqual(result["scadaStatus"], ["valid", "bad"])
            self.assertEqual(result["realFixed"], [None, 12.5])
            self.assertEqual(result["scadaFixed"], [None, 12.5])
            self.assertEqual(result["realValid"], [1, 0])
            self.assertEqual(result["scadaValid"], [1, 0])


if __name__ == "__main__":
    unittest.main()
