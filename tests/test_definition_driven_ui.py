from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simu.service import PolarMicrogridSimulator
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


ROOT = Path(__file__).resolve().parents[1]


class DefinitionDrivenUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.simulator_js = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")
        cls.trainee_js = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    def test_snapshot_exposes_model_measurement_and_control_definitions(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                Path(temporary) / "runtime",
                model_id="simple",
            )

            definitions = service.snapshot()["definitions"]

        self.assertIn("ACGenerator", definitions["model"])
        self.assertGreater(len(definitions["measurement"]), 0)
        self.assertIn("RunStat", definitions["control"])
        self.assertIn("SetValue", definitions["control"])

    def test_model_pages_are_driven_by_model_e_blocks(self):
        for label, script in (("simulator", self.simulator_js), ("trainee", self.trainee_js)):
            with self.subTest(script=label):
                self.assertIn('definitionBlocks("model"', script)
                self.assertIn("function definedModelDevices", script)
                self.assertIn("__headers", script)
                model_record_block = script.split("function modelAttributeRecordForDevice", 1)[1].split(
                    "function modelAttributeColumns",
                    1,
                )[0]
                self.assertNotIn("record.run_stat", model_record_block)
                self.assertNotIn("record.status", model_record_block)
                self.assertNotIn("set_values", model_record_block)

    def test_measurement_pages_are_driven_by_meas_e_definitions(self):
        self.assertIn("state.snapshot?.definitions?.measurement", self.simulator_js)
        self.assertIn("snapshot.definitions?.measurement", self.trainee_js)
        self.assertIn("primaryRows.map((definition)", self.simulator_js)
        self.assertIn("primaryRows.map((definition)", self.trainee_js)

    def test_control_pages_are_driven_by_control_e_blocks(self):
        simulator_control_block = self.simulator_js.split("function runtimeRemoteControlRows", 1)[1].split(
            "function runtimeRemoteAdjustmentRows",
            1,
        )[0]
        simulator_adjustment_block = self.simulator_js.split("function runtimeRemoteAdjustmentRows", 1)[1].split(
            "function renderRuntimeCommandRows",
            1,
        )[0]
        trainee_adjustment_block = self.trainee_js.split("function remoteAdjustmentRows", 1)[1].split(
            "function formatRemoteAdjustmentValue",
            1,
        )[0]

        self.assertIn('definedControlRows("RunStat")', simulator_control_block)
        self.assertIn('definedControlRows("CbOpenStat")', simulator_control_block)
        self.assertIn('definedControlRows("SetValue")', simulator_adjustment_block)
        self.assertIn('selectedControlRows("RunStat"', self.trainee_js)
        self.assertIn('selectedControlRows("CbOpenStat"', self.trainee_js)
        self.assertIn('selectedControlRows("SetValue"', trainee_adjustment_block)
        self.assertNotIn("preferredSetTypes", trainee_adjustment_block)

    def test_control_pages_do_not_create_rows_from_runtime_devices(self):
        simulator_trace_block = self.simulator_js.split("function appendRuntimeTrace", 1)[1].split(
            "function renderRuntimeDeviceTree",
            1,
        )[0]
        trainee_find_block = self.trainee_js.split("function findDeviceByKey", 1)[1].split(
            "function closeRemoteControlDialog",
            1,
        )[0]
        trainee_render_control_block = self.trainee_js.split("function renderRunControls", 1)[1].split(
            "function currentSetValue",
            1,
        )[0]
        trainee_control_cell_block = self.trainee_js.split("function traineeRemoteControlLiveValue", 1)[1].split(
            "function traineeRemoteAdjustmentLiveValue",
            1,
        )[0]

        self.assertIn("controlDefinitionDevices(snapshot).forEach", simulator_trace_block)
        self.assertNotIn("(snapshot.devices || []).forEach", simulator_trace_block)
        self.assertNotIn("state.snapshot?.devices", trainee_find_block)
        self.assertIn('data-run-key="${escapeHtml(key)}"', trainee_control_cell_block)
        self.assertNotIn("commandKey", trainee_render_control_block)

    def test_remote_adjustment_measurement_uses_meas_e_rows_without_hardcoded_candidates(self):
        simulator_measurement_block = self.simulator_js.split("function runtimeMeasurementPair", 1)[1].split(
            "function runtimeDeviceTraceSignal",
            1,
        )[0]
        trainee_measurement_block = self.trainee_js.split("function remoteAdjustmentMeasurement", 1)[1].split(
            "function remoteAdjustmentIssuedAt",
            1,
        )[0]

        self.assertIn("measurementCompareRows(measurements)", simulator_measurement_block)
        self.assertIn("runtimeMeasTypeMatchesSetKey", simulator_measurement_block)
        self.assertNotIn("runtimeMeasurementHints", simulator_measurement_block)
        self.assertNotIn("P_GEN", simulator_measurement_block)
        self.assertNotIn("P_LOAD", simulator_measurement_block)
        self.assertIn("measurementDisplayRows(snapshot)", trainee_measurement_block)
        self.assertIn("remoteAdjustmentMeasTypeMatchesSetType", trainee_measurement_block)
        self.assertNotIn("const priorities", trainee_measurement_block)
        self.assertNotIn("P_GEN", trainee_measurement_block)
        self.assertNotIn("P_LOAD", trainee_measurement_block)


if __name__ == "__main__":
    unittest.main()
