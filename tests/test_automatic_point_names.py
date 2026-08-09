from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import simu.server as server_module
import simu_loop
from simu.generate_simple_model import measurement_blocks
from simu.service import PolarMicrogridSimulator
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


ROOT = Path(__file__).resolve().parents[1]


class AutomaticPointNamesTest(unittest.TestCase):
    def test_generated_converter_controls_keep_only_the_active_terminal_setpoint(self):
        model_book = server_module._book_from_text(
            """<DCACConverter>
@ idx name ac_node dc_node ac_control_type dc_control_type p_ac_set p_dc_set run_stat
# 1 ac-link 1 2 PQ NONE -10 10 1
# 2 dc-link 1 2 NONE P -20 20 1
# 3 dual-link 1 2 PQ P -30 30 1
</DCACConverter>
"""
        )

        rows = server_module._generated_control_blocks(model_book)["SetValue"][1]
        values = {
            (str(row["dev_name"]), str(row["set_type"])): float(row["set_value"])
            for row in rows
        }

        self.assertEqual(values[("ac-link", "p_ac_set")], -10.0)
        self.assertNotIn(("ac-link", "p_dc_set"), values)
        self.assertEqual(values[("dc-link", "p_dc_set")], 20.0)
        self.assertNotIn(("dc-link", "p_ac_set"), values)
        self.assertEqual(values[("dual-link", "p_dc_set")], 30.0)
        self.assertNotIn(("dual-link", "p_ac_set"), values)

    def test_uploaded_model_generation_uses_device_type_in_all_measurement_names(self):
        model_book = server_module._book_from_text(
            """<ACGenerator>
@ idx name node control_type p_set q_set v_set run_stat
# 1 shared 1 P 10 0 380 1
</ACGenerator>
<DCGenerator>
@ idx name node control_type p_set v_set i_set run_stat
# 1 shared 2 P 10 720 0 1
</DCGenerator>
"""
        )
        control_blocks = server_module._generated_control_blocks(model_book)
        measurement_book = server_module._generated_measurement_book(model_book, control_blocks)
        rows = measurement_book.data["Measurement"].data

        self.assertEqual(len({str(row["name"]) for row in rows}), len(rows))
        for row in rows:
            with self.subTest(point=row["name"]):
                self.assertTrue(
                    str(row["name"]).startswith(f"{row['dev_type']}.{row['dev_name']}."),
                    row,
                )
        self.assertIn("ACGenerator.shared.P_GEN", {str(row["name"]) for row in rows})
        self.assertIn("DCGenerator.shared.P_GEN", {str(row["name"]) for row in rows})

    def test_service_generated_weather_and_signal_names_include_device_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            runtime = Path(temporary) / "runtime"
            shutil.copytree(SIMPLE_MODEL_SOURCE, source)

            PolarMicrogridSimulator(source, runtime, model_id="point-names", kernel=lambda _config: None)

            measurement_rows = simu_loop.EBook(source / "meas.e").data["Measurement"].data
            generated_rows = [
                row
                for row in measurement_rows
                if str(row["dev_type"]) == "Environment"
                or str(row["meas_type"]).upper() in {"RUN_STAT", "STATUS"}
            ]
            for row in generated_rows:
                with self.subTest(point=row["name"]):
                    self.assertTrue(
                        str(row["name"]).startswith(f"{row['dev_type']}.{row['dev_name']}."),
                        row,
                    )

    def test_simple_model_generator_uses_device_type_in_all_measurement_names(self):
        _block_name, _headers, rows = measurement_blocks()[0]

        self.assertEqual(len({str(row["name"]) for row in rows}), len(rows))
        for row in rows:
            with self.subTest(point=row["name"]):
                self.assertTrue(
                    str(row["name"]).startswith(f"{row['dev_type']}.{row['dev_name']}."),
                    row,
                )

    def test_external_control_names_separate_same_named_devices_by_device_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_book = server_module._book_from_text(
                """<ACGenerator>
@ idx name node control_type p_set q_set v_set run_stat
# 1 shared 1 P 10 0 380 1
</ACGenerator>
<DCGenerator>
@ idx name node control_type p_set v_set i_set run_stat
# 1 shared 2 P 10 720 0 1
</DCGenerator>
"""
            )
            artifacts = server_module._generated_model_artifacts(
                server_module.render_ebook_aligned(model_book)
            )
            source = root / "source"
            server_module._write_generated_model_artifacts(source, artifacts)
            service = PolarMicrogridSimulator(source, root / "runtime", model_id="duplicate-controls", kernel=lambda _config: None)

            names = service.external_control_names()
            self.assertIn("ACGenerator.shared.run_stat", names["remote_control_names"])
            self.assertIn("DCGenerator.shared.run_stat", names["remote_control_names"])
            self.assertIn("ACGenerator.shared.p_set", names["remote_adjustment_names"])
            self.assertIn("DCGenerator.shared.p_set", names["remote_adjustment_names"])

    def test_web_generated_point_labels_include_device_type(self):
        simulator = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")
        trainee = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

        for script in (simulator, trainee):
            with self.subTest(surface="simulator" if script is simulator else "trainee"):
                self.assertIn(
                    'if (isSignalMeasurement(row)) return `${row.dev_type || ""}.${row.dev_name || row.name || ""}.${signalMeasurementLabel(row)}`;',
                    script,
                )
                self.assertIn(
                    'return isWeatherMeasurement(row) ? `Environment.weather.${weatherMeasurementLabel(row)}` : row.name;',
                    script,
                )

        self.assertIn('trace_label: `${dev.dev_type}.${dev.dev_name}.设备投退`', simulator)
        self.assertIn('trace_label: `${dev.dev_type}.${dev.dev_name}.开关开合`', simulator)
        self.assertIn('trace_label: `${dev.dev_type}.${dev.dev_name}.${key}`', simulator)
        self.assertIn(
            'name: `${deviceType(row.dev)}.${deviceName(row.dev)}.${remoteControlLabel(row.commandType)}`',
            trainee,
        )
        self.assertIn(
            'return `${deviceType(dev)}.${deviceName(dev)}.${remoteAdjustmentTypeLabel(setType)}`;',
            trainee,
        )


if __name__ == "__main__":
    unittest.main()
