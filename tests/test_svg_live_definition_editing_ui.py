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

    def _editor_helper_source(self, script: str | None = None) -> str:
        script = script or self.script
        marker = "const DIAGRAM_DEFINITION_RATIO_FIELDS"
        if marker not in script:
            self.fail("device definition editor rendering helpers are missing")
        integrated_row = "function renderDiagramIntegratedDefinitionRow" + script.split(
            "function renderDiagramIntegratedDefinitionRow",
            1,
        )[1].split("function diagramTooltipRows", 1)[0]
        return integrated_row + self._helper_source(script) + marker + script.split(marker, 1)[1].split(
            "function renderDiagramDeviceDefinitionRecord",
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
function diagramTooltipValue(value) {
  return value === null || value === undefined || value === "" ? "--" : String(value);
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

    def _run_editor_helpers(self, body: str, script: str | None = None):
        script = script or self.script
        harness = r"""
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
function diagramTooltipValue(value) {
  return value === null || value === undefined || value === "" ? "--" : String(value);
}
"""
        result = subprocess.run(
            ["node"],
            input=f"{harness}\n{self._editor_helper_source(script)}\n{body}",
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
                diagramDeviceParameterEditable("closed_status_set"),
                diagramDeviceParameterEditable("p"),
                diagramDeviceParameterEditable("f"),
  ],
}));
"""
        simulator = self._run_helpers(body)
        trainee = self._run_helpers(body, self.trainee_script)
        self.assertEqual(simulator["blocks"], ["ACGenerator", "ACWindGen"])
        self.assertEqual(trainee["blocks"], ["ACGenerator", "ACWindGen"])
        self.assertEqual(
            simulator["editable"],
            [True, True, False, True, True, True, True, True, True, False, False],
        )
        self.assertEqual(
            trainee["editable"],
            [True, True, False, False, False, False, False, False, False, False, False],
        )

    def test_device_parameter_panels_hide_realtime_measurement_fields(self):
        body = r"""
const snapshot = {
  definitions: {
    model: {
      DCACConverter: {
        headers: ["idx", "name", "p", "q", "u", "i", "p_ac_set", "p_dc_set", "ac_p_max", "dc_p_max"],
        rows: [{ idx: 1, name: "dcac-1", p: 1, q: 2, u: 380, i: 3, p_ac_set: 4, p_dc_set: -4, ac_p_max: 10, dc_p_max: 10 }],
      },
      DCDCConverter: {
        headers: ["idx", "name", "p", "q", "u", "i", "p_set", "v_set", "i_p_max", "j_p_max"],
        rows: [{ idx: 2, name: "dcdc-1", p: 1, q: 2, u: 750, i: 3, p_set: 4, v_set: 750, i_p_max: 10, j_p_max: 10 }],
      },
      ACACConverter: {
        headers: ["idx", "name", "p", "q", "u", "i", "p_set", "q_from_set", "q_to_set"],
        rows: [{ idx: 3, name: "acac-1", p: 1, q: 2, u: 380, i: 3, p_set: 4, q_from_set: 1, q_to_set: -1 }],
      },
      ACGenerator: {
        headers: ["idx", "name", "p", "q", "u", "i", "f", "p_set"],
        rows: [{ idx: 4, name: "source-1", p: 1, q: 2, u: 380, i: 3, f: 50, p_set: 4 }],
      },
    },
  },
};
function displayed(devType, devName) {
  const record = diagramDeviceDefinitionRecords({ devType, devName }, snapshot)[0];
  return diagramDefinitionDisplayHeaders(record);
}
process.stdout.write(JSON.stringify({
  dcac: displayed("DCACConverter", "dcac-1"),
  dcdc: displayed("DCDCConverter", "dcdc-1"),
  acac: displayed("ACACConverter", "acac-1"),
  source: displayed("ACGenerator", "source-1"),
}));
"""
        for script in (self.script, self.trainee_script):
            payload = self._run_helpers(body, script)
            for device in ("dcac", "dcdc", "acac", "source"):
                self.assertTrue(
                    {"p", "q", "u", "i", "f"}.isdisjoint(payload[device]),
                    device,
                )
            self.assertTrue({"p_ac_set", "p_dc_set"}.issubset(payload["dcac"]))
            self.assertTrue({"p_set", "v_set"}.issubset(payload["dcdc"]))
            self.assertTrue({"p_set", "q_from_set", "q_to_set"}.issubset(payload["acac"]))
            self.assertIn("p_set", payload["source"])

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

    def test_switch_status_is_only_available_when_the_model_defines_closed_status(self):
        body = r"""
const converterRecords = [{ headers: ["idx", "name", "run_stat", "p_set"] }];
const breakerRecords = [{ headers: ["idx", "name", "closed_status_set", "closed_status", "run_stat"] }];
const legacyRecords = [{ headers: ["idx", "name", "status", "run_stat"] }];
process.stdout.write(JSON.stringify({
  converter: diagramDeviceHasSwitchStatus(converterRecords, { run_stat: 1, p_set: 10 }),
  breaker: diagramDeviceHasSwitchStatus(breakerRecords, { run_stat: 1, closed_status: 0 }),
  rawFallback: diagramDeviceHasSwitchStatus([], { run_stat: 1, closed_status: 1 }),
  legacyOnly: diagramDeviceHasSwitchStatus(legacyRecords, { run_stat: 1, status: 1 }),
  runtimeDefaultOnly: diagramDeviceHasSwitchStatus([], { run_stat: 1 }),
}));
"""
        expected = {
            "converter": False,
            "breaker": True,
            "rawFallback": True,
            "legacyOnly": False,
            "runtimeDefaultOnly": False,
        }
        self.assertEqual(self._run_helpers(body), expected)
        self.assertEqual(self._run_helpers(body, self.trainee_script), expected)
        for script in (self.script, self.trainee_script):
            self.assertIn(
                "diagramDeviceHasSwitchStatus(definitionRecords, raw)",
                script,
            )

    def test_all_runtime_states_and_control_modes_have_enumerated_choices(self):
        body = r"""
const optionValues = (blockName, field, row) => (
  diagramDefinitionEnumOptions({ blockName, row }, field).map((option) => option.value)
);
process.stdout.write(JSON.stringify({
  runStat: optionValues("ACLoad", "run_stat", { run_stat: 1 }),
  switchStatus: optionValues("ACBreak", "status", { status: 0 }),
  switchBoundary: optionValues("ACBreak", "closed_status_set", { closed_status_set: 0 }),
  acGenerator: optionValues("ACGenerator", "control_type", { control_type: "PV" }),
  dcGenerator: optionValues("DCGenerator", "control_type", { control_type: "V" }),
  acacSide: optionValues("ACACConverter", "i_control_type", { i_control_type: "PV" }),
  dcdcSide: optionValues("DCDCConverter", "i_control_type", { i_control_type: "CTRL_V" }),
  dcacAcForDcPower: optionValues("DCACConverter", "ac_control_type", {
    ac_control_type: "NONE",
    dc_control_type: "P",
  }),
  dcacDcForAcPower: optionValues("DCACConverter", "dc_control_type", {
    ac_control_type: "PQ",
    dc_control_type: "NONE",
  }),
  hydrogenConversion: optionValues("AcE2Hydro", "control_type", { control_type: "P" }),
  invalidHydrogenConversion: optionValues("AcE2Hydro", "control_type", { control_type: "PQ" }),
  hydrogenStorage: optionValues("HydroStorage", "control_type", { control_type: "PRESSURE" }),
  unknownMode: optionValues("CustomDevice", "mode", { mode: "AUTO" }),
  canonicalDcdcAlias: diagramDefinitionEnumCanonicalValue(
    { blockName: "DCDCConverter", row: { i_control_type: "CTRL_V" } },
    "i_control_type",
    "CTRL_V",
  ),
  dcdcSwitchSide: diagramDefinitionCoupledEnumValues({
    blockName: "DCDCConverter",
    row: { i_control_type: "V", j_control_type: "NONE" },
  }, "j_control_type", "I"),
  dcacSwitchToDcPower: diagramDefinitionCoupledEnumValues({
    blockName: "DCACConverter",
    row: { ac_control_type: "PH", dc_control_type: "NONE" },
  }, "dc_control_type", "P"),
}));
"""
        expected = {
            "runStat": ["1", "0"],
            "switchStatus": ["1", "0"],
            "switchBoundary": ["1", "0"],
            "acGenerator": ["PQ", "P", "PV", "V", "SLACK", "PH"],
            "dcGenerator": ["P", "V", "I", "SLACK"],
            "acacSide": ["PQ", "PV", "PH", "NONE"],
            "dcdcSide": ["P", "V", "I", "NONE"],
            "dcacAcForDcPower": ["PQ", "PH", "NONE"],
            "dcacDcForAcPower": ["NONE", "V", "P"],
            "hydrogenConversion": ["P", "FLOW"],
            "invalidHydrogenConversion": ["P", "FLOW"],
            "hydrogenStorage": ["PRESSURE", "FLOW"],
            "unknownMode": ["AUTO"],
            "canonicalDcdcAlias": "V",
            "dcdcSwitchSide": {"j_control_type": "I", "i_control_type": "NONE"},
            "dcacSwitchToDcPower": {"dc_control_type": "P", "ac_control_type": "NONE"},
        }
        self.assertEqual(self._run_editor_helpers(body), expected)
        self.assertEqual(self._run_editor_helpers(body, self.trainee_script), expected)

    def test_switch_status_displays_actual_result_and_edits_only_the_boundary(self):
        body = r"""
const record = { blockName: "ACBreak", row: { closed_status_set: 0 } };
process.stdout.write(JSON.stringify({
  actualOpen: diagramDefinitionDisplayValue("closed_status", 0),
  actualClosed: diagramDefinitionDisplayValue("closed_status", 1),
  boundaryOpen: diagramDefinitionDisplayValue("closed_status_set", 0),
  boundaryOptions: diagramDefinitionEnumOptions(record, "closed_status_set"),
  canonicalOpen: diagramDefinitionEnumCanonicalValue(record, "closed_status_set", "打开"),
}));
"""
        expected = {
            "actualOpen": "打开",
            "actualClosed": "闭合",
            "boundaryOpen": "打开",
            "boundaryOptions": [
                {"value": "1", "label": "闭合"},
                {"value": "0", "label": "打开"},
            ],
            "canonicalOpen": "0",
        }
        self.assertEqual(self._run_editor_helpers(body), expected)
        self.assertEqual(self._run_editor_helpers(body, self.trainee_script), expected)

    def test_switch_tooltip_uses_closed_status_and_hides_control_mode(self):
        for script in (self.script, self.trainee_script):
            block = script.split("function diagramSingleDeviceTooltipData", 1)[1].split(
                "function diagramDeviceTooltipData",
                1,
            )[0]
            self.assertIn('["运行状态",', block)
            self.assertIn('["开关状态", switchStatusValue,', block)
            self.assertIn(
                'diagramDefinitionFieldBinding(definitionRecords, ["closed_status_set"])',
                block,
            )
            self.assertIn('live?.closed_status ?? raw.closed_status', block)
            self.assertNotIn('live?.status ?? raw.status', block)
            self.assertNotIn('["控制模式",', block)

    def test_simulator_can_edit_switch_boundary_but_trainee_tooltip_is_read_only(self):
        simulator_block = self.script.split("function diagramSingleDeviceTooltipData", 1)[1].split(
            "function diagramDeviceTooltipData",
            1,
        )[0]
        trainee_block = self.trainee_script.split("function diagramSingleDeviceTooltipData", 1)[1].split(
            "function diagramDeviceTooltipData",
            1,
        )[0]
        self.assertIn("statusBinding", simulator_block)
        self.assertIn("statusBinding", trainee_block)
        self.assertNotIn('&& !name.endsWith("_set")', self.script)
        self.assertIn('&& !name.endsWith("_set")', self.trainee_script)

    def test_editable_runtime_states_and_control_modes_render_as_selects(self):
        body = r"""
const interaction = { definitionSaving: false };
const editor = {
  kind: "device",
  records: [{
    blockName: "AcE2Hydro",
    rowIndex: 0,
    editableFields: ["run_stat", "control_type", "e2h_coeff"],
    original: { run_stat: "1", control_type: "P", e2h_coeff: "0.2" },
    draft: { run_stat: "1", control_type: "P", e2h_coeff: "0.2" },
    dirtyFields: new Set(),
  }],
};
interaction.definitionEditor = editor;
const record = {
  blockName: "AcE2Hydro",
  rowIndex: 0,
  headers: ["run_stat", "control_type", "e2h_coeff"],
  row: { run_stat: "1", control_type: "P", e2h_coeff: "0.2" },
};
const activeEditor = editor.records[0];
const runHtml = renderDiagramIntegratedDefinitionRow(
  "运行状态",
  "1",
  "status:run_stat",
  { blockName: "AcE2Hydro", rowIndex: 0, field: "run_stat", editable: true },
  interaction,
);
const modeHtml = renderDiagramIntegratedDefinitionRow(
  "控制模式",
  "P",
  "status:mode",
  { blockName: "AcE2Hydro", rowIndex: 0, field: "control_type", editable: true },
  interaction,
);
const invalidModeHtml = renderDiagramDefinitionEnumSelect(
  { blockName: "AcE2Hydro", row: { control_type: "PQ" } },
  "control_type",
  "PQ",
  interaction,
);
const numberHtml = renderDiagramDeviceDefinitionValueRow(
  record,
  "e2h_coeff",
  activeEditor,
  interaction,
);
process.stdout.write(JSON.stringify({
  runSelect: runHtml.includes("<select") && runHtml.includes("投入") && runHtml.includes("退出"),
  modeSelect: modeHtml.includes("<select") && modeHtml.includes("定电功率") && modeHtml.includes("定气流量"),
  noRunTextInput: !runHtml.includes("<input"),
  noModeTextInput: !modeHtml.includes("<input"),
  invalidModePrompt: invalidModeHtml.includes("无效选项 (PQ)，请选择"),
  numericInput: numberHtml.includes("<input") && !numberHtml.includes("<select"),
  readOnlyRunText: diagramDefinitionDisplayValue("run_stat", 1),
  readOnlySwitchText: diagramDefinitionDisplayValue("status", 0),
}));
"""
        expected = {
            "runSelect": True,
            "modeSelect": True,
            "noRunTextInput": True,
            "noModeTextInput": True,
            "invalidModePrompt": True,
            "numericInput": True,
            "readOnlyRunText": "投入",
            "readOnlySwitchText": "断开",
        }
        self.assertEqual(self._run_editor_helpers(body), expected)

        trainee_body = body.replace(
            'field: "run_stat", editable: true',
            'field: "run_stat", editable: false',
        )
        trainee = self._run_editor_helpers(trainee_body, self.trainee_script)
        self.assertFalse(trainee["runSelect"])
        self.assertTrue(trainee["modeSelect"])
        self.assertTrue(trainee["noRunTextInput"])
        self.assertEqual(trainee["readOnlyRunText"], "投入")

    def test_realtime_refresh_preserves_friendly_read_only_enum_labels(self):
        for script in (self.script, self.trainee_script):
            refresh = script.split("function syncDiagramTooltipSections", 1)[1].split(
                "function updateDiagramDevice",
                1,
            )[0]
            self.assertIn("diagramDefinitionDisplayValue(binding.field, value)", refresh)
            self.assertIn(": diagramTooltipValue(value)", refresh)

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
      median_deviation: -0.25,
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
  medianDeviation: pair.medianDeviation,
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
                "medianDeviation": -0.25,
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
  record: { name: "line-1.p", weight: 400, median_deviation: -0.25, valid: 0, error_sigma: 0.05 },
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
        self.assertEqual(payload["measurement"]["median_deviation"], -0.25)
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

    def test_switch_runtime_control_result_patches_closed_status_set_immediately(self):
        body = r"""
state.snapshot = {
  devices: [{
    dev_type: "ACBreak",
    dev_name: "br-1",
    closed_status_set: 0,
    closed_status: 0,
    status: 0,
    raw: { closed_status_set: 0, closed_status: 0 },
  }],
  device_states: [],
  measurements: { definitions: [], real: [], scada: [] },
};
const changed = patchDiagramRuntimeControlRecord(state.snapshot, {
  dev_type: "ACBreak",
  dev_name: "br-1",
  closed_status_set: 1,
});
process.stdout.write(JSON.stringify({ changed, device: state.snapshot.devices[0] }));
"""
        payload = self._run_helpers(body)
        self.assertTrue(payload["changed"])
        self.assertEqual(payload["device"]["closed_status_set"], 1)
        self.assertEqual(payload["device"]["raw"]["closed_status_set"], 1)
        self.assertEqual(payload["device"]["closed_status"], 0)

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

    def test_device_editor_lifecycle_prompts_before_discarding_dirty_changes(self):
        for function_name in (
            "beginDiagramDeviceDefinitionEdit",
            "cancelDiagramDefinitionEdit",
            "saveDiagramDeviceDefinitionEdit",
            "renderDiagramDeviceDefinitionEditor",
            "diagramDefinitionEditPinned",
            "diagramDefinitionEditorPendingChanges",
            "renderDiagramDefinitionLeavePrompt",
        ):
            for script in (self.script, self.trainee_script):
                self.assertIn(f"function {function_name}", script)

        for script in (self.script, self.trainee_script):
            hide_block = script.split("function scheduleDiagramTooltipHide", 1)[1].split(
                "function renderActiveDiagramTooltip",
                1,
            )[0]
            self.assertNotIn("if (diagramDefinitionEditPinned(interaction)) return", hide_block)
            self.assertIn("diagramDefinitionEditorPendingChanges", hide_block)
            self.assertIn("interaction.definitionLeavePrompt = true", hide_block)
            self.assertIn("hideDiagramTooltip(container)", hide_block)
            for action in ("save", "discard", "continue"):
                self.assertIn(f'data-diagram-definition-leave-action="{action}"', script)

        update_block = self.script.split("function updateDiagramDeviceTooltip", 1)[1].split(
            "function diagramMetricCurrentRow",
            1,
        )[0]
        self.assertIn("function updateDiagramDeviceDynamicSections", self.script)
        self.assertIn("updateDiagramDeviceDynamicSections", update_block)
        self.assertIn('interaction.definitionEditor?.kind === "device"', update_block)

    def test_leave_prompt_lists_device_and_measurement_changes(self):
        body = r"""
const deviceEditor = {
  kind: "device",
  records: [{
    blockName: "DCRealBs",
    rowIndex: 0,
    original: { v_max: 900, run_stat: 1 },
    draft: { v_max: 950, run_stat: 0 },
    dirtyFields: new Set(["v_max", "run_stat"]),
  }],
};
const measurementEditor = {
  kind: "measurement",
  original: { errorSigma: "0.1", status: "valid" },
  draft: { errorSigma: "0.2", status: "fixed" },
  dirtyFields: new Set(["errorSigma", "status"]),
};
const deviceChanges = diagramDefinitionEditorPendingChanges(deviceEditor);
const measurementChanges = diagramDefinitionEditorPendingChanges(measurementEditor);
const html = renderDiagramDefinitionLeavePrompt({
  definitionEditor: deviceEditor,
  definitionLeavePrompt: true,
  definitionSaving: false,
});
process.stdout.write(JSON.stringify({ deviceChanges, measurementChanges, html }));
"""
        for script in (self.script, self.trainee_script):
            payload = self._run_helpers(body, script)
            self.assertEqual(
                [(item["before"], item["after"]) for item in payload["deviceChanges"]],
                [("900", "950"), ("投入", "退出")],
            )
            self.assertEqual(
                [(item["before"], item["after"]) for item in payload["measurementChanges"]],
                [("0.1", "0.2"), ("有效", "固定值")],
            )
            self.assertIn("尚未保存", payload["html"])
            self.assertIn("保存并关闭", payload["html"])
            self.assertIn("不保存并关闭", payload["html"])
            self.assertIn("继续编辑", payload["html"])

    def test_leave_prompt_ignores_fields_that_were_changed_back_to_the_original_value(self):
        body = r"""
const deviceEditor = {
  kind: "device",
  records: [{
    blockName: "ACGenerator",
    rowIndex: 0,
    original: { p_max: 100 },
    draft: { p_max: "100.0" },
    dirtyFields: new Set(["p_max"]),
  }],
};
const measurementEditor = {
  kind: "measurement",
  original: { errorSigma: "0.1", status: "valid", valid: 1 },
  draft: { errorSigma: "0.10", status: "valid", valid: 1 },
  dirtyFields: new Set(["errorSigma", "status"]),
};
process.stdout.write(JSON.stringify({
  device: diagramDefinitionEditorPendingChanges(deviceEditor),
  measurement: diagramDefinitionEditorPendingChanges(measurementEditor),
}));
"""
        for script in (self.script, self.trainee_script):
            self.assertEqual(
                self._run_helpers(body, script),
                {"device": [], "measurement": []},
            )

    def test_save_and_close_only_closes_after_complete_success(self):
        for script in (self.script, self.trainee_script):
            for function_name, next_function in (
                ("saveDiagramDeviceDefinitionEdit", "function reorderDiagramChildren"),
                ("saveDiagramMeasurementDefinitionEdit", "function renderDiagramMetricTooltip"),
            ):
                source = script.split(f"async function {function_name}", 1)[1].split(
                    next_function,
                    1,
                )[0]
                self.assertIn("const closeAfterSave = Boolean(interaction.definitionCloseAfterSave)", source)
                self.assertIn("if (closeAfterSave) hideDiagramTooltip(container)", source)
                self.assertIn("return false", source)
                catch_source = source.split("} catch (error) {", 1)[1]
                self.assertNotIn("interaction.definitionEditor = null", catch_source)
                self.assertIn("interaction.definitionCloseAfterSave = false", catch_source)

    def test_device_tooltip_measurement_field_names_use_closed_status_alias(self):
        for script in (self.script, self.trainee_script):
            self.assertIn("function diagramMeasurementFieldName", script)
            mapping_marker = "const DIAGRAM_MEASUREMENT_FIELD_LABELS"
            mapping_source = mapping_marker + script.split(mapping_marker, 1)[1].split(
                "\n});",
                1,
            )[0] + "\n});"
            helper_source = "function diagramMeasurementFieldName" + script.split(
                "function diagramMeasurementFieldName",
                1,
            )[1].split("function diagramDeviceData", 1)[0]
            result = subprocess.run(
                ["node"],
                input=(
                    f"{mapping_source}\n{helper_source}\n"
                    "process.stdout.write(JSON.stringify(["
                    "diagramMeasurementFieldName({ meas_type: 'STATUS' }),"
                    "diagramMeasurementFieldName({ meas_type: 'RUN_STAT' }),"
                    "diagramMeasurementFieldName({ meas_type: 'P_FROM' })"
                    "]));"
                ),
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                json.loads(result.stdout),
                ["closed_status", "run_stat", "p_from"],
            )
            tooltip_block = script.split("function diagramSingleDeviceTooltipData", 1)[1].split(
                "function diagramDeviceTooltipData",
                1,
            )[0]
            self.assertIn("diagramMeasurementFieldName(row)", tooltip_block)
            self.assertNotIn("row.meas_type || row.name || \"量测\"", tooltip_block)

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
            "data-diagram-measurement-median-deviation",
            "data-diagram-measurement-valid",
            "data-diagram-measurement-sigma",
        )
        for token in required:
            self.assertIn(token, self.script)
        measurement_summary = self.script.split(
            "function renderDiagramMeasurementSummary",
            1,
        )[1].split("function syncDiagramMeasurementDefinitionFields", 1)[0]
        self.assertIn("<dt>中值偏差</dt>", measurement_summary)
        self.assertIn('data-diagram-measurement-definition-field="medianDeviation"', measurement_summary)
        self.assertNotIn("<dt>权重</dt>", measurement_summary)
        self.assertNotIn("data-diagram-measurement-weight", measurement_summary)
        self.assertIn("data-diagram-measurement-weight", self.trainee_script)
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
  initialSoc: diagramDefinitionDisplayValue("initial_soc", 0.6),
  descriptor,
  stored: diagramDefinitionStoredValue("module_efficiency", "21.3"),
  ordinary: diagramDefinitionInputDescriptor("p_set", "21.3"),
}));
"""
            harness = r"""
function normalizeDiagramMeasurementToken(value) {
  return String(value || "").trim().replace(/[\s_.-]+/g, "").toUpperCase();
}
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
            self.assertEqual(payload["initialSoc"], "60%")
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

    def test_switch_result_and_boundary_are_hidden_from_parameter_rows(self):
        body = r"""
const record = {
  headers: [
    "idx", "name", "i_node", "j_node", "closed_status_set", "closed_status", "rated_capacity",
  ],
};
process.stdout.write(JSON.stringify(diagramDefinitionDisplayHeaders(record)));
"""
        for script in (self.script, self.trainee_script):
            self.assertEqual(
                self._run_helpers(body, script),
                ["i_node", "j_node", "rated_capacity"],
            )

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
