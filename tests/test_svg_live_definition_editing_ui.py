from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIMULATOR_SCRIPT = ROOT / "simu/web/simulator/app.js"
SIMULATOR_STYLES = ROOT / "simu/web/simulator/styles.css"
TRAINEE_SCRIPT = ROOT / "simu/web/trainee/app.js"


class SvgLiveDefinitionEditingUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = SIMULATOR_SCRIPT.read_text(encoding="utf-8")
        cls.styles = SIMULATOR_STYLES.read_text(encoding="utf-8")
        cls.trainee_script = TRAINEE_SCRIPT.read_text(encoding="utf-8")

    def _helper_source(self, script: str | None = None) -> str:
        script = script or self.script
        marker = "const DIAGRAM_DEFINITION_PROTECTED_FIELDS"
        if marker not in script:
            self.fail("live definition editing helpers are missing")
        return marker + script.split(marker, 1)[1].split(
            "function diagramDeviceData",
            1,
        )[0]

    def _run_helpers(self, body: str, script: str | None = None):
        harness = r"""
const state = { snapshot: null };
let persistedSnapshot = null;
function currentPageName() { return "diagram"; }
function persistStaticSnapshotCache(snapshot, page) {
  persistedSnapshot = { snapshot, page };
}
function normalizeDiagramMeasurementToken(value) {
  return String(value || "").trim().replace(/[\s_.-]+/g, "").toUpperCase();
}
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
function diagramMetricMeasurementTypes(devType, metricType) {
  if (normalizeDiagramMeasurementToken(devType) === "ACGENERATOR"
      && normalizeDiagramMeasurementToken(metricType) === "ACTIVEPOWER") {
    return ["P_GEN", "P"];
  }
  return [String(metricType || "")];
}
"""
        result = subprocess.run(
            ["node"],
            input=f"{harness}\n{self._helper_source(script)}\n{body}",
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_device_records_include_primary_and_linked_parameter_blocks(self):
        body = r"""
const snapshot = {
  definitions: {
    model: {
      ACGenerator: {
        headers: ["idx", "name", "node", "p_min", "p_max", "run_stat"],
        rows: [{ idx: 1, name: "wind-1", node: 3, p_min: 0, p_max: 10, run_stat: 1 }],
      },
      ACWindGen: {
        headers: ["idx", "idx_acgenerator", "cut_in_wind_speed", "rated_wind_speed"],
        rows: [{ idx: 7, idx_acgenerator: 1, cut_in_wind_speed: 4, rated_wind_speed: 12 }],
      },
    },
  },
};
const records = diagramDeviceDefinitionRecords(
  { devType: "ACGenerator", devName: "wind-1" },
  snapshot,
);
process.stdout.write(JSON.stringify({
  blocks: records.map((record) => record.blockName),
  editable: [
    diagramDeviceParameterEditable("p_max"),
    diagramDeviceParameterEditable("r"),
    diagramDeviceParameterEditable("node"),
    diagramDeviceParameterEditable("run_stat"),
    diagramDeviceParameterEditable("p_set"),
    diagramDeviceParameterEditable("q_set"),
    diagramDeviceParameterEditable("v_set"),
    diagramDeviceParameterEditable("status"),
  ],
}));
"""
        simulator = self._run_helpers(body)
        trainee = self._run_helpers(body, self.trainee_script)
        self.assertEqual(simulator["blocks"], ["ACGenerator", "ACWindGen"])
        self.assertEqual(trainee["blocks"], ["ACGenerator", "ACWindGen"])
        self.assertEqual(
            simulator["editable"],
            [True, True, False, True, True, True, True, True],
        )
        self.assertEqual(
            trainee["editable"],
            [True, True, False, False, False, False, False, False],
        )

    def test_device_editor_includes_primary_and_linked_static_parameter_blocks(self):
        body = r"""
const snapshot = {
  definitions: {
    model: {
      ACGenerator: {
        headers: ["idx", "name", "node", "p_max", "run_stat"],
        rows: [{ idx: 24, name: "wind-24", node: 34, p_max: 50, run_stat: 1 }],
      },
      ACWindGen: {
        headers: [
          "idx",
          "idx_acgenerator",
          "wind_turbine_model",
          "cut_in_wind_speed",
          "rated_wind_speed",
          "cut_out_wind_speed",
          "rotor_diameter",
          "hub_height",
        ],
        rows: [{
          idx: 7,
          idx_acgenerator: 24,
          wind_turbine_model: "WT-5MW",
          cut_in_wind_speed: 3,
          rated_wind_speed: 12,
          cut_out_wind_speed: 25,
          rotor_diameter: 170,
          hub_height: 110,
        }],
      },
    },
  },
};
const records = diagramDeviceDefinitionRecords(
  { devType: "ACGenerator", devName: "wind-24" },
  snapshot,
);
const editors = diagramDeviceDefinitionEditorRecords(records);
process.stdout.write(JSON.stringify(editors.map((editor) => ({
  blockName: editor.blockName,
  editableFields: editor.editableFields,
  draft: editor.draft,
}))));
"""
        expected = [
            {
                "blockName": "ACGenerator",
                "editableFields": ["p_max", "run_stat"],
                "draft": {
                    "idx": 24,
                    "name": "wind-24",
                    "node": 34,
                    "p_max": 50,
                    "run_stat": 1,
                },
            },
            {
                "blockName": "ACWindGen",
                "editableFields": [
                    "wind_turbine_model",
                    "cut_in_wind_speed",
                    "rated_wind_speed",
                    "cut_out_wind_speed",
                    "rotor_diameter",
                    "hub_height",
                ],
                "draft": {
                    "idx": 7,
                    "idx_acgenerator": 24,
                    "wind_turbine_model": "WT-5MW",
                    "cut_in_wind_speed": 3,
                    "rated_wind_speed": 12,
                    "cut_out_wind_speed": 25,
                    "rotor_diameter": 170,
                    "hub_height": 110,
                },
            },
        ]
        self.assertEqual(self._run_helpers(body), expected)
        trainee = self._run_helpers(body, self.trainee_script)
        self.assertEqual(trainee[0]["blockName"], "ACGenerator")
        self.assertEqual(trainee[1], expected[1])

        for script in (self.script, self.trainee_script):
            save_block = script.split(
                "async function saveDiagramDeviceDefinitionEdit",
                1,
            )[1].split("function reorderDiagramChildren", 1)[0]
            self.assertIn("diagramDeviceDefinitionDirtyUpdates(editor)", save_block)
            self.assertIn("for (const update of updates)", save_block)

    def test_device_editor_handles_other_and_generic_linked_parameter_blocks(self):
        body = r"""
const snapshot = {
  definitions: {
    model: {
      DCGenerator: {
        headers: ["idx", "name", "node", "p_max", "p_set"],
        rows: [{ idx: 9, name: "dc-source-9", node: 6, p_max: 40, p_set: 10 }],
      },
      DCPVGen: {
        headers: ["idx", "idx_dcgenerator", "panel_efficiency", "tilt_angle"],
        rows: [{ idx: 3, idx_dcgenerator: 9, panel_efficiency: 0.2, tilt_angle: 25 }],
      },
      DCStorageGen: {
        headers: ["idx", "idx_dcgenerator", "energy_capacity", "charge_efficiency"],
        rows: [{ idx: 4, idx_dcgenerator: 9, energy_capacity: 100, charge_efficiency: 0.95 }],
      },
      DCAuxiliaryCurve: {
        headers: ["idx", "idx_dcgenerator", "curve_mode"],
        rows: [{ idx: 5, idx_dcgenerator: 9, curve_mode: "linear" }],
      },
    },
  },
};
const records = diagramDeviceDefinitionRecords(
  { devType: "DCGenerator", devName: "dc-source-9" },
  snapshot,
);
const editors = diagramDeviceDefinitionEditorRecords(records);
[
  ["DCPVGen", "tilt_angle", "30"],
  ["DCStorageGen", "energy_capacity", "120"],
  ["DCAuxiliaryCurve", "curve_mode", "spline"],
].forEach(([blockName, field, value]) => {
  const editor = editors.find((item) => item.blockName === blockName);
  editor.draft[field] = value;
  editor.dirtyFields.add(field);
});
process.stdout.write(JSON.stringify({
  blocks: editors.map((editor) => editor.blockName),
  protectedReferences: editors.every((editor) => !editor.editableFields.includes("idx_dcgenerator")),
  updates: diagramDeviceDefinitionDirtyUpdates({ kind: "device", records: editors })
    .map(({ blockName, changes }) => ({ blockName, changes })),
}));
"""
        expected = {
            "blocks": [
                "DCGenerator",
                "DCPVGen",
                "DCStorageGen",
                "DCAuxiliaryCurve",
            ],
            "protectedReferences": True,
            "updates": [
                {"blockName": "DCPVGen", "changes": {"tilt_angle": "30"}},
                {
                    "blockName": "DCStorageGen",
                    "changes": {"energy_capacity": "120"},
                },
                {
                    "blockName": "DCAuxiliaryCurve",
                    "changes": {"curve_mode": "spline"},
                },
            ],
        }
        self.assertEqual(self._run_helpers(body), expected)
        self.assertEqual(self._run_helpers(body, self.trainee_script), expected)

    def test_switch_status_is_only_available_when_the_model_defines_status(self):
        body = r"""
const converterRecords = [{ headers: ["idx", "name", "run_stat", "p_set"] }];
const breakerRecords = [{ headers: ["idx", "name", "status", "run_stat"] }];
process.stdout.write(JSON.stringify({
  converter: diagramDeviceHasSwitchStatus(converterRecords, { run_stat: 1, p_set: 10 }),
  breaker: diagramDeviceHasSwitchStatus(breakerRecords, { run_stat: 1, status: 0 }),
  rawFallback: diagramDeviceHasSwitchStatus([], { run_stat: 1, status: 1 }),
  runtimeDefaultOnly: diagramDeviceHasSwitchStatus([], { run_stat: 1 }),
}));
"""
        expected = {
            "converter": False,
            "breaker": True,
            "rawFallback": True,
            "runtimeDefaultOnly": False,
        }
        self.assertEqual(self._run_helpers(body), expected)
        self.assertEqual(self._run_helpers(body, self.trainee_script), expected)
        for script in (self.script, self.trainee_script):
            self.assertIn(
                "diagramDeviceHasSwitchStatus(definitionRecords, raw)",
                script,
            )

    def test_nameless_model_rows_match_the_definition_driven_synthetic_device_name(self):
        body = r"""
const snapshot = {
  definitions: {
    model: {
      ACNode: {
        headers: ["idx", "rated_voltage", "v_min", "v_max"],
        rows: [{ idx: 3, rated_voltage: 380, v_min: 0.9, v_max: 1.1 }],
      },
    },
  },
};
const records = diagramDeviceDefinitionRecords(
  { devType: "ACNode", devName: "ACNode_3", devId: "ACNode-3" },
  snapshot,
);
process.stdout.write(JSON.stringify(records.map((record) => ({
  blockName: record.blockName,
  idx: record.row.idx,
  editableFields: record.editableFields,
}))));
"""
        self.assertEqual(
            self._run_helpers(body),
            [{
                "blockName": "ACNode",
                "idx": 3,
                "editableFields": ["rated_voltage", "v_min", "v_max"],
            }],
        )

    def test_editor_message_placeholder_exists_before_validation_fails(self):
        body = r"""
process.stdout.write(JSON.stringify({
  empty: diagramDefinitionEditorMessageHtml({ definitionMessage: "" }, ""),
  validation: diagramDefinitionEditorMessageHtml({ definitionMessage: "" }, "必须大于 0"),
  warning: diagramDefinitionEditorMessageHtml({
    definitionMessage: "E 文件保存失败",
    definitionMessageWarning: true,
  }, ""),
}));
"""
        payload = self._run_helpers(body)
        self.assertIn("data-diagram-definition-message", payload["empty"])
        self.assertIn("hidden", payload["empty"])
        self.assertIn("必须大于 0", payload["validation"])
        self.assertIn("is-warning", payload["validation"])
        self.assertIn("E 文件保存失败", payload["warning"])
        self.assertIn("is-warning", payload["warning"])

    def test_measurement_pair_keeps_scada_real_and_signed_deviation_separate(self):
        body = r"""
const snapshot = {
  definitions: {
    measurement: [{
      name: "wind-1.p",
      dev_type: "ACGenerator",
      dev_name: "wind-1",
      meas_type: "P_GEN",
      weight: 100,
      valid: 1,
    }],
  },
  measurements: {
    scada: [{ name: "wind-1.p", dev_type: "ACGenerator", dev_name: "wind-1", meas_type: "P_GEN", value: -10, valid: 1 }],
    real: [{ name: "wind-1.p", dev_type: "ACGenerator", dev_name: "wind-1", meas_type: "P_GEN", value: -9.5, valid: 1 }],
  },
};
const pair = diagramMetricMeasurementPair({
  binding: { devType: "ACGenerator", devName: "wind-1", metricType: "activePower" },
}, snapshot);
process.stdout.write(JSON.stringify({
  scadaValue: pair.scadaValue,
  realValue: pair.realValue,
  deviation: pair.deviation,
  valid: pair.valid,
  weight: pair.weight,
  errorSigma: pair.errorSigma,
  fromSigma: diagramDefinitionWeightFromSigma(0.02),
  fromWeight: diagramDefinitionSigmaFromWeight(400),
}));
"""
        self.assertEqual(
            self._run_helpers(body),
            {
                "scadaValue": -10,
                "realValue": -9.5,
                "deviation": -0.5,
                "valid": 1,
                "weight": 100,
                "errorSigma": 0.1,
                "fromSigma": 2500,
                "fromWeight": 0.05,
            },
        )

    def test_measurement_pair_exposes_invalid_zero_weight_for_correction(self):
        body = r"""
const snapshot = {
  definitions: {
    measurement: [{
      name: "wind-1.p",
      dev_type: "ACGenerator",
      dev_name: "wind-1",
      meas_type: "P_GEN",
      weight: 0,
      valid: 1,
    }],
  },
  measurements: { scada: [], real: [] },
};
const pair = diagramMetricMeasurementPair({
  binding: { devType: "ACGenerator", devName: "wind-1", metricType: "activePower" },
}, snapshot);
process.stdout.write(JSON.stringify({ weight: pair.weight, errorSigma: pair.errorSigma }));
"""
        self.assertEqual(
            self._run_helpers(body),
            {"weight": 0, "errorSigma": None},
        )

    def test_local_result_patching_updates_only_definition_rows_and_metadata(self):
        body = r"""
const diagram = { svg: "keep-me" };
state.snapshot = {
  model: { id: "model-a" },
  diagram,
  static_meta: { definitions: { revision: 1 }, device_parameters: { revision: 1 } },
  definitions: {
    model: {
      ACBranch: {
        headers: ["idx", "name", "r", "x"],
        rows: [{ idx: 2, name: "line-1", r: 0.01, x: 0.02 }],
      },
    },
    measurement: [{ name: "line-1.p", weight: 100, valid: 1 }],
  },
  device_parameters: {},
  measurements: {
    definitions: [{ name: "line-1.p", weight: 100, valid: 1 }],
    real: [{ name: "line-1.p", value: 9.5, valid: 1 }],
    scada: [{ name: "line-1.p", value: 10, valid: 1 }],
  },
};
applyDefinitionEditResult({
  revision: 2,
  memory_updated: true,
  persisted: true,
  record: {
    block_name: "ACBranch",
    row_key: { idx: 2, name: "line-1" },
    idx: 2,
    name: "line-1",
    r: 0.03,
    x: 0.02,
  },
  static_meta: { definitions: { revision: 2 }, device_parameters: { revision: 2 } },
});
applyDefinitionEditResult({
  revision: 3,
  memory_updated: true,
  persisted: false,
  warning: "disk warning",
  record: { name: "line-1.p", weight: 400, valid: 0, error_sigma: 0.05 },
  static_meta: { definitions: { revision: 3 }, device_parameters: { revision: 3 } },
});
process.stdout.write(JSON.stringify({
  diagramPreserved: state.snapshot.diagram === diagram,
  branch: state.snapshot.definitions.model.ACBranch.rows[0],
  measurement: state.snapshot.definitions.measurement[0],
  channelValid: [state.snapshot.measurements.real[0].valid, state.snapshot.measurements.scada[0].valid],
  meta: state.snapshot.static_meta,
  persistedPage: persistedSnapshot?.page,
}));
"""
        payload = self._run_helpers(body)
        self.assertTrue(payload["diagramPreserved"])
        self.assertEqual(payload["branch"]["r"], 0.03)
        self.assertEqual(payload["branch"]["x"], 0.02)
        self.assertEqual(payload["measurement"]["weight"], 400)
        self.assertEqual(payload["measurement"]["valid"], 0)
        self.assertEqual(payload["channelValid"], [0, 0])
        self.assertEqual(payload["meta"]["definitions"]["revision"], 3)
        self.assertEqual(payload["persistedPage"], "diagram")

    def test_runtime_control_result_patching_updates_live_snapshot_values(self):
        body = r"""
const diagram = { svg: "keep-me" };
state.snapshot = {
  model: { id: "model-a" },
  diagram,
  static_meta: { definitions: { revision: 1 }, device_parameters: { revision: 1 } },
  definitions: {
    model: {
      ACGenerator: {
        headers: ["idx", "name", "p_set", "q_set", "v_set", "run_stat"],
        rows: [{ idx: 2, name: "gen-1", p_set: 10, q_set: 0, v_set: 380, run_stat: 1 }],
      },
    },
  },
  device_parameters: {},
  devices: [{
    dev_type: "ACGenerator",
    dev_name: "gen-1",
    run_stat: 1,
    status: 1,
    set_values: { p_set: 10, q_set: 0, v_set: 380 },
    raw: { idx: 2, name: "gen-1", p_set: 10, q_set: 0, v_set: 380, run_stat: 1 },
  }],
  device_states: [{
    dev_type: "ACGenerator",
    dev_name: "gen-1",
    run_stat: 1,
    dead_island: false,
  }],
  measurements: {
    definitions: [
      { name: "gen-1.run_stat", dev_type: "ACGenerator", dev_name: "gen-1", meas_type: "RUN_STAT", value: 1, valid: 1 },
      { name: "gen-1.status", dev_type: "ACGenerator", dev_name: "gen-1", meas_type: "STATUS", value: 1, valid: 1 },
    ],
    real: [
      { name: "gen-1.run_stat", dev_type: "ACGenerator", dev_name: "gen-1", meas_type: "RUN_STAT", value: 1, valid: 1 },
      { name: "gen-1.status", dev_type: "ACGenerator", dev_name: "gen-1", meas_type: "STATUS", value: 1, valid: 1 },
    ],
    scada: [
      { name: "gen-1.run_stat", dev_type: "ACGenerator", dev_name: "gen-1", meas_type: "RUN_STAT", value: 1, valid: 1 },
      { name: "gen-1.status", dev_type: "ACGenerator", dev_name: "gen-1", meas_type: "STATUS", value: 1, valid: 1 },
    ],
  },
};
applyDefinitionEditResult({
  revision: 2,
  memory_updated: true,
  persisted: true,
  record: {
    block_name: "ACGenerator",
    row_key: { idx: 2, name: "gen-1" },
    idx: 2,
    name: "gen-1",
    p_set: 35,
    q_set: 5,
    v_set: 400,
    run_stat: 0,
  },
  runtime_control: {
    dev_type: "ACGenerator",
    dev_name: "gen-1",
    run_stat: 0,
    set_values: { p_set: 35, q_set: 5, v_set: 400 },
  },
  static_meta: { definitions: { revision: 2 }, device_parameters: { revision: 2 } },
});
process.stdout.write(JSON.stringify({
  branch: state.snapshot.definitions.model.ACGenerator.rows[0],
  device: state.snapshot.devices[0],
  deviceState: state.snapshot.device_states[0],
  measurements: state.snapshot.measurements,
}));
"""
        payload = self._run_helpers(body)
        self.assertEqual(payload["branch"]["p_set"], 35)
        self.assertEqual(payload["branch"]["q_set"], 5)
        self.assertEqual(payload["branch"]["v_set"], 400)
        self.assertEqual(payload["branch"]["run_stat"], 0)
        self.assertEqual(payload["device"]["run_stat"], 0)
        self.assertEqual(payload["device"]["set_values"]["p_set"], 35)
        self.assertEqual(payload["device"]["set_values"]["q_set"], 5)
        self.assertEqual(payload["device"]["set_values"]["v_set"], 400)
        self.assertEqual(payload["deviceState"]["run_stat"], 0)
        for channel in ("definitions", "real", "scada"):
            rows = payload["measurements"][channel]
            run_row = next(row for row in rows if row["meas_type"] == "RUN_STAT")
            status_row = next(row for row in rows if row["meas_type"] == "STATUS")
            self.assertEqual(run_row["value"], 0)
            self.assertEqual(run_row["valid"], 1)
            self.assertEqual(status_row["value"], 1)
            self.assertEqual(status_row["valid"], 1)

    def test_simulator_and_trainee_expose_both_local_definition_edit_apis(self):
        for endpoint in (
            "/api/definitions/device-parameters",
            "/api/definitions/measurement",
        ):
            self.assertIn(endpoint, self.script)
            self.assertIn(endpoint, self.trainee_script)

    def test_trainee_device_editor_uses_revision_and_refreshes_local_definitions(self):
        for function_name in (
            "beginDiagramDeviceDefinitionEdit",
            "cancelDiagramDefinitionEdit",
            "saveDiagramDeviceDefinitionEdit",
            "renderDiagramDeviceDefinitionEditor",
            "reloadLocalDefinitionSnapshotAfterEdit",
        ):
            self.assertIn(f"function {function_name}", self.trainee_script)
        begin_block = self.trainee_script.split(
            "function beginDiagramDeviceDefinitionEdit",
            1,
        )[1].split("function cancelDiagramDefinitionEdit", 1)[0]
        save_block = self.trainee_script.split(
            "async function saveDiagramDeviceDefinitionEdit",
            1,
        )[1].split("function syncDiagramTooltipSections", 1)[0]
        self.assertIn("revision:", begin_block)
        self.assertIn("let revision = editor.revision", save_block)
        self.assertIn("revision,", save_block)
        self.assertIn("result?.revision", save_block)
        self.assertIn("reloadLocalDefinitionSnapshotAfterEdit", save_block)

    def test_trainee_measurement_editor_updates_local_definition_without_rebuilding_live_values(self):
        for function_name in (
            "beginDiagramMeasurementDefinitionEdit",
            "saveDiagramMeasurementDefinitionEdit",
            "syncDiagramMeasurementDefinitionFields",
            "updateDiagramMetricDynamicValues",
        ):
            self.assertIn(f"function {function_name}", self.trainee_script)
        update_block = self.trainee_script.split(
            "function updateDiagramMetricTooltip",
            1,
        )[1].split("function positionDiagramTooltip", 1)[0]
        self.assertIn("updateDiagramMetricDynamicValues", update_block)
        self.assertNotIn("tooltip.innerHTML", update_block)

    def test_device_editor_lifecycle_is_explicit_and_pins_the_tooltip(self):
        for function_name in (
            "beginDiagramDeviceDefinitionEdit",
            "cancelDiagramDefinitionEdit",
            "saveDiagramDeviceDefinitionEdit",
            "renderDiagramDeviceDefinitionEditor",
            "updateDiagramDeviceDynamicSections",
            "diagramDefinitionEditPinned",
        ):
            self.assertIn(f"function {function_name}", self.script)
        hide_block = self.script.split("function scheduleDiagramTooltipHide", 1)[1].split(
            "function renderActiveDiagramTooltip",
            1,
        )[0]
        self.assertIn("diagramDefinitionEditPinned", hide_block)
        update_block = self.script.split("function updateDiagramDeviceTooltip", 1)[1].split(
            "function diagramMetricCurrentRow",
            1,
        )[0]
        self.assertIn("updateDiagramDeviceDynamicSections", update_block)
        self.assertIn('interaction.definitionEditor?.kind === "device"', update_block)

    def test_simulator_device_definition_actions_render_in_the_tooltip_header(self):
        self.assertIn(
            "function renderDiagramDeviceDefinitionHeadActions",
            self.script,
        )
        editor_block = self.script.split(
            "function renderDiagramDeviceDefinitionEditor",
            1,
        )[1].split("function renderDiagramDeviceDefinitionHeadActions", 1)[0]
        head_actions_block = self.script.split(
            "function renderDiagramDeviceDefinitionHeadActions",
            1,
        )[1].split("function renderDiagramDeviceDefinitionValueRow", 1)[0]
        footer_block = self.script.split(
            "function renderDiagramDeviceDefinitionFooter",
            1,
        )[1].split("function renderDiagramDeviceClassifiedTable", 1)[0]
        tooltip_block = self.script.split(
            "function renderDiagramDeviceTooltip",
            1,
        )[1].split("function diagramDefinitionEditPinned", 1)[0]

        self.assertIn('data-diagram-definition-actions="device"', editor_block)
        self.assertIn("diagram-definition-head-actions", editor_block)
        self.assertIn("renderDiagramDeviceDefinitionEditor", head_actions_block)
        self.assertIn(
            "renderDiagramDeviceDefinitionHeadActions(data.definitionRecords, interaction)",
            tooltip_block,
        )
        self.assertIn("diagram-tooltip-head-controls", tooltip_block)
        self.assertNotIn("renderDiagramDeviceDefinitionEditor", footer_block)
        self.assertIn("diagramDefinitionMessageHtml(interaction)", footer_block)
        self.assertIn(".diagram-tooltip-head-controls", self.styles)
        self.assertIn(".diagram-definition-head-actions", self.styles)

    def test_simulator_measurement_definition_actions_render_in_the_tooltip_header(self):
        editor_block = self.script.split(
            "function renderDiagramMeasurementDefinitionEditor",
            1,
        )[1].split("function beginDiagramMeasurementDefinitionEdit", 1)[0]
        summary_block = self.script.split(
            "function renderDiagramMeasurementSummary",
            1,
        )[1].split("function syncDiagramMeasurementDefinitionFields", 1)[0]
        tooltip_block = self.script.split(
            "function renderDiagramMetricTooltip",
            1,
        )[1].split("function updateDiagramMetricDynamicValues", 1)[0]

        self.assertIn('data-diagram-definition-actions="measurement"', editor_block)
        self.assertIn("diagram-definition-head-actions", editor_block)
        self.assertNotIn("renderDiagramMeasurementDefinitionEditor", summary_block)
        self.assertIn("diagram-tooltip-head-controls", tooltip_block)
        self.assertIn(
            "renderDiagramMeasurementDefinitionEditor(editor, interaction)",
            tooltip_block,
        )
        self.assertIn(
            "diagramDefinitionEditorMessageHtml(interaction, editor.validationError)",
            tooltip_block,
        )

    def test_device_editor_sends_the_definition_revision(self):
        begin_block = self.script.split(
            "function beginDiagramDeviceDefinitionEdit",
            1,
        )[1].split("function cancelDiagramDefinitionEdit", 1)[0]
        save_block = self.script.split(
            "async function saveDiagramDeviceDefinitionEdit",
            1,
        )[1].split("function syncDiagramTooltipSections", 1)[0]

        self.assertIn("revision:", begin_block)
        self.assertIn("let revision = editor.revision", save_block)
        self.assertIn("revision,", save_block)
        self.assertIn("result?.revision", save_block)

    def test_measurement_editor_keeps_dynamic_values_independent_from_inputs(self):
        for function_name in (
            "beginDiagramMeasurementDefinitionEdit",
            "saveDiagramMeasurementDefinitionEdit",
            "syncDiagramMeasurementDefinitionFields",
            "updateDiagramMetricDynamicValues",
        ):
            self.assertIn(f"function {function_name}", self.script)
        update_block = self.script.split("function updateDiagramMetricTooltip", 1)[1].split(
            "function positionDiagramTooltip",
            1,
        )[0]
        self.assertIn("updateDiagramMetricDynamicValues", update_block)
        self.assertNotIn("tooltip.innerHTML", update_block)

    def test_measurement_editor_sends_the_definition_revision(self):
        begin_block = self.script.split(
            "function beginDiagramMeasurementDefinitionEdit",
            1,
        )[1].split("function updateDiagramMeasurementDefinitionDraft", 1)[0]
        save_block = self.script.split(
            "async function saveDiagramMeasurementDefinitionEdit",
            1,
        )[1].split("function renderDiagramMetricTooltip", 1)[0]

        self.assertIn("revision:", begin_block)
        self.assertIn("revision: editor.revision", save_block)

    def test_tooltip_html_has_all_edit_and_measurement_update_targets(self):
        required = (
            "data-diagram-definition-actions",
            "data-diagram-definition-save",
            "data-diagram-definition-cancel",
            "data-diagram-definition-editable",
            "data-diagram-measurement-scada",
            "data-diagram-measurement-real",
            "data-diagram-measurement-deviation",
            "data-diagram-measurement-valid",
            "data-diagram-measurement-sigma",
            "data-diagram-measurement-weight",
        )
        for token in required:
            self.assertIn(token, self.script)
        self.assertNotIn("data-diagram-definition-edit-button", self.script)
        self.assertNotIn("data-diagram-definition-edit-measurement", self.script)

    def test_simulator_and_trainee_render_inline_measurement_status_modes_and_fixed_value(self):
        for script in (self.script, self.trainee_script):
            for token in (
                'data-diagram-measurement-definition-field="status"',
                'data-diagram-measurement-definition-field="fixedValue"',
                'valid: "有效"',
                'invalid: "无效"',
                'undefined: "无定义"',
                'dead: "死数"',
                'zero: "零值"',
                'fixed: "固定值"',
            ):
                self.assertIn(token, script)
            self.assertIn("data-diagram-tooltip-inline-input", script)

    def test_device_and_measurement_editors_use_existing_summary_rows(self):
        for script in (self.script, self.trainee_script):
            device_block = script.split("function renderDiagramDeviceDefinitionValueRow", 1)[1].split(
                "function renderDiagramDeviceDefinitionRecords", 1,
            )[0]
            measurement_block = script.split("function renderDiagramMeasurementDefinitionEditor", 1)[1].split(
                "function beginDiagramMeasurementDefinitionEdit", 1,
            )[0]
            measurement_summary = script.split("function renderDiagramMeasurementSummary", 1)[1].split(
                "function syncDiagramMeasurementDefinitionFields", 1,
            )[0]
            self.assertIn("data-diagram-definition-value", device_block)
            self.assertIn("data-diagram-tooltip-inline-input", device_block)
            self.assertIn("data-diagram-tooltip-inline-input", measurement_summary)
            self.assertIn('data-diagram-definition-editable="device"', device_block)
            self.assertIn('data-diagram-definition-editable="measurement"', measurement_summary)
            self.assertNotIn("diagram-definition-fields", measurement_block)

    def test_ratio_parameters_display_as_percent_but_save_as_decimal(self):
        for script in (self.script, self.trainee_script):
            marker = "const DIAGRAM_DEFINITION_RATIO_FIELDS"
            self.assertIn(marker, script)
            helper_source = marker + script.split(marker, 1)[1].split(
                "function renderDiagramDeviceDefinitionEditor",
                1,
            )[0]
            body = r"""
const descriptor = diagramDefinitionInputDescriptor("charge_discharge_efficiency", "0.99");
process.stdout.write(JSON.stringify({
  efficiency: diagramDefinitionDisplayValue("charge_discharge_efficiency", "0.99"),
  soc: diagramDefinitionDisplayValue("soc_upper_limit", 0.9),
  descriptor,
  stored: diagramDefinitionStoredValue("module_efficiency", "21.3"),
  ordinary: diagramDefinitionInputDescriptor("p_set", "21.3"),
}));
"""
            harness = r"""
function escapeHtml(value) { return String(value ?? ""); }
function diagramTooltipValue(value) { return String(value ?? ""); }
"""
            result = subprocess.run(
                ["node"],
                input=f"{harness}\n{helper_source}\n{body}",
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload["efficiency"], "99%")
            self.assertEqual(payload["soc"], "90%")
            self.assertEqual(payload["descriptor"]["value"], "99")
            self.assertEqual(payload["descriptor"]["suffix"], "%")
            self.assertEqual(payload["descriptor"]["min"], "0")
            self.assertEqual(payload["descriptor"]["max"], "100")
            self.assertEqual(payload["stored"], "0.213")
            self.assertEqual(payload["ordinary"]["value"], "21.3")
            self.assertEqual(payload["ordinary"]["suffix"], "")

    def test_device_model_parameters_are_integrated_into_the_classified_table(self):
        for script in (self.script, self.trainee_script):
            render_block = script.split(
                "function renderDiagramDeviceClassifiedTable",
                1,
            )[1].split("function renderDiagramDeviceTooltip", 1)[0]
            self.assertIn("data-diagram-device-dynamic-body", render_block)
            self.assertLess(
                render_block.index("diagramTooltipSectionsHtml(identitySections, interaction)"),
                render_block.index("renderDiagramDeviceDefinitionRecords"),
            )
            self.assertLess(
                render_block.index("renderDiagramDeviceDefinitionRecords"),
                render_block.index("diagramTooltipSectionsHtml(detailSections, interaction)"),
            )
            self.assertLess(
                render_block.index("diagramTooltipSectionsHtml(detailSections, interaction)"),
                render_block.index("renderDiagramDeviceDefinitionFooter"),
            )
            self.assertIn("renderDiagramDeviceClassifiedTable(data, interaction)", script)

    def test_device_model_parameter_rows_do_not_repeat_identity_fields(self):
        body = r"""
const record = {
  headers: ["idx", "name", "dev_name", "dev_type", "i_node", "j_node", "status", "run_stat"],
};
process.stdout.write(JSON.stringify(diagramDefinitionDisplayHeaders(record)));
"""
        for script in (self.script, self.trainee_script):
            self.assertEqual(
                self._run_helpers(body, script),
                ["i_node", "j_node", "status", "run_stat"],
            )

    def test_runtime_control_fields_are_merged_into_their_existing_categories(self):
        body = r"""
const record = {
  headers: ["idx", "name", "i_node", "j_node", "status", "run_stat", "p_set"],
  integratedFields: new Set(["status", "run_stat", "p_set"]),
};
process.stdout.write(JSON.stringify(diagramDefinitionDisplayHeaders(record)));
"""
        for script in (self.script, self.trainee_script):
            self.assertEqual(self._run_helpers(body, script), ["i_node", "j_node"])
            self.assertIn("function diagramDefinitionFieldBinding", script)
            self.assertIn("renderDiagramIntegratedDefinitionRow", script)

    def test_integrated_rows_use_the_matching_record_from_the_multi_block_editor(self):
        for script in (self.script, self.trainee_script):
            matcher_source = "function diagramIntegratedDefinitionBindingMatchesEditor" + script.split(
                "function diagramIntegratedDefinitionBindingMatchesEditor",
                1,
            )[1].split("function renderDiagramIntegratedDefinitionRow", 1)[0]
            body = f"""
{matcher_source}
const interaction = {{
  definitionEditor: {{
    kind: "device",
    records: [{{ blockName: "ACGenerator", rowIndex: 0, draft: {{ run_stat: 1 }} }}],
  }},
}};
process.stdout.write(JSON.stringify({{
  matching: diagramIntegratedDefinitionBindingMatchesEditor(
    {{ blockName: "ACGenerator", rowIndex: 0 }},
    interaction,
  ),
  unrelated: diagramIntegratedDefinitionBindingMatchesEditor(
    {{ blockName: "ACWindGen", rowIndex: 0 }},
    interaction,
  ),
}}));
"""
            self.assertEqual(
                self._run_helpers(body, script),
                {"matching": True, "unrelated": False},
            )
            render_block = script.split(
                "function renderDiagramIntegratedDefinitionRow",
                1,
            )[1].split("function diagramTooltipRows", 1)[0]
            self.assertIn(
                "const activeEditor = diagramDeviceDefinitionRecordEditor",
                render_block,
            )

    def test_live_refresh_does_not_reparent_focused_editor_rows(self):
        for script in (self.script, self.trainee_script):
            sync_block = script.split("function syncDiagramTooltipSections", 1)[1].split(
                "function updateDiagramDeviceTooltip",
                1,
            )[0]
            self.assertIn("function reorderDiagramChildren", script)
            self.assertIn("reorderDiagramChildren(list, desiredRows)", sync_block)
            self.assertIn("reorderDiagramChildren(body, desiredBodyChildren)", sync_block)
            self.assertNotIn("list.appendChild(rowElement)", sync_block)
            self.assertNotIn("body.appendChild(sectionElement)", sync_block)

    def test_static_parameter_sections_only_rebuild_when_the_definition_changes(self):
        for script in (self.script, self.trainee_script):
            update_block = script.split("function updateDiagramDeviceTooltip", 1)[1].split(
                "function diagramMetricCurrentRow",
                1,
            )[0]
            self.assertIn("function diagramDeviceDefinitionRecordsSignature", script)
            self.assertIn("data-diagram-definition-signature", script)
            self.assertIn("currentDefinitionSignature !== definitionSignature", update_block)
            self.assertIn("definitions.outerHTML = definitionHtml", update_block)

    def test_device_definition_sections_use_the_same_visual_table(self):
        for styles_path in (
            SIMULATOR_STYLES,
            ROOT / "simu/web/trainee/styles.css",
        ):
            styles = styles_path.read_text(encoding="utf-8")
            definition_records = styles.split(".diagram-definition-records", 1)[1].split("}", 1)[0]
            self.assertIn("display: contents", definition_records)
            self.assertNotIn("border-top", definition_records)

    def test_definition_revision_participates_in_static_cache_matching(self):
        body = r"""
function staticMetaSignature(meta) { return JSON.stringify(meta || null); }
function staticMetaMatches(left, right) { return staticMetaSignature(left) === staticMetaSignature(right); }
process.stdout.write(JSON.stringify({
  same: staticMetaMatches({ signature: "same", revision: 4 }, { signature: "same", revision: 4 }),
  changed: staticMetaMatches({ signature: "same", revision: 4 }, { signature: "same", revision: 5 }),
}));
"""
        result = subprocess.run(
            ["node"],
            input=body,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(result.stdout), {"same": True, "changed": False})
        self.assertIn("function staticMetaMatches", self.script)

    def test_definition_editor_styles_are_scoped_to_the_tooltip(self):
        required = (
            ".diagram-definition-section-head",
            ".diagram-definition-input",
            ".diagram-definition-actions",
            ".diagram-definition-message",
            ".diagram-definition-message.is-warning",
            ".diagram-tooltip.is-editing-definition",
            ".diagram-tooltip-row.is-editable",
        )
        for selector in required:
            self.assertIn(selector, self.styles)
        self.assertNotIn(".diagram-definition-edit-button", self.styles)
        self.assertNotIn(".diagram-definition-editor", self.styles)


if __name__ == "__main__":
    unittest.main()
