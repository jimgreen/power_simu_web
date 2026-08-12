from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import simu.server as server_module
import simu_loop
from simu.generate_simple_model import measurement_blocks, model_blocks, stat_blocks
from simu.model_semantics import energy_coupling_control_bindings
from simu.service import PolarMicrogridSimulator
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


ROOT = Path(__file__).resolve().parents[1]


class AutomaticPointNamesTest(unittest.TestCase):
    def test_persisted_source_models_define_one_dcp_control_per_converter(self):
        for source_root in (
            ROOT / "models/simulator/source",
            ROOT / "models/trainee/source",
        ):
            for model_path in sorted(source_root.rglob("model.e")):
                model_book = server_module._book_from_text(model_path.read_text(encoding="utf-8"))
                converter_block = model_book.data.get("DCACConverter")
                if converter_block is None or not converter_block.data:
                    continue
                converter_names = {str(row["name"]) for row in converter_block.data}
                for file_name in ("control.e", "stat.e"):
                    definition_path = model_path.with_name(file_name)
                    definition_book = server_module._book_from_text(
                        definition_path.read_text(encoding="utf-8")
                    )
                    dcp_rows = [
                        row
                        for row in definition_book.data["SetValue"].data
                        if row.get("dev_type") == "DCACConverter"
                        and row.get("set_type") == "p_dc_set"
                    ]
                    with self.subTest(model=str(model_path), definition=file_name):
                        self.assertEqual(
                            {str(row["dev_name"]) for row in dcp_rows},
                            converter_names,
                        )
                        self.assertEqual(len(dcp_rows), len(converter_names))

    def test_service_load_persists_missing_dcp_controls_from_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            shutil.copytree(SIMPLE_MODEL_SOURCE, source)
            service = PolarMicrogridSimulator(
                source,
                root / "runtime",
                model_id="dcp-reconcile",
                kernel=lambda _config: None,
            )
            converter_names = {
                str(row["name"])
                for row in service.definition_snapshot.model_book.data["DCACConverter"].data
            }

            for book in (service.control_book, service.source_stat_book):
                dcp_rows = [
                    row
                    for row in book.data["SetValue"].data
                    if row.get("dev_type") == "DCACConverter"
                    and row.get("set_type") == "p_dc_set"
                ]
                self.assertEqual({str(row["dev_name"]) for row in dcp_rows}, converter_names)
                self.assertEqual(len(dcp_rows), len(converter_names))

            for file_name in ("control.e", "stat.e"):
                persisted = server_module._book_from_text(
                    (source / file_name).read_text(encoding="utf-8")
                )
                dcp_rows = [
                    row
                    for row in persisted.data["SetValue"].data
                    if row.get("dev_type") == "DCACConverter"
                    and row.get("set_type") == "p_dc_set"
                ]
                self.assertEqual({str(row["dev_name"]) for row in dcp_rows}, converter_names)
                self.assertEqual(len(dcp_rows), len(converter_names))

    def test_simple_model_generator_uses_strict_converter_schema_and_dcp_controls(self):
        converter_header, converter_rows = next(
            (header, rows)
            for block_name, header, rows in model_blocks()
            if block_name == "DCACConverter"
        )
        self.assertNotIn("control_type", converter_header)
        self.assertIn("ac_control_type", converter_header)
        self.assertIn("dc_control_type", converter_header)
        self.assertIn("p_dc_set", converter_header)
        self.assertTrue(all("p_dc_set" in row for row in converter_rows))

        set_rows = next(
            rows
            for block_name, _header, rows in stat_blocks()
            if block_name == "SetValue"
        )
        converter_names = {str(row["name"]) for row in converter_rows}
        dcp_rows = [
            row
            for row in set_rows
            if row.get("dev_type") == "DCACConverter"
            and row.get("set_type") == "p_dc_set"
        ]
        self.assertEqual({str(row["dev_name"]) for row in dcp_rows}, converter_names)
        self.assertEqual(len(dcp_rows), len(converter_names))

    def test_generated_converter_controls_include_acp_and_dcp_points_once(self):
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
        self.assertEqual(values[("ac-link", "p_dc_set")], 10.0)
        self.assertEqual(values[("dc-link", "p_dc_set")], 20.0)
        self.assertNotIn(("dc-link", "p_ac_set"), values)
        self.assertEqual(values[("dual-link", "p_dc_set")], 30.0)
        self.assertNotIn(("dual-link", "p_ac_set"), values)
        self.assertEqual(len(values), len(rows))

    def test_hydrogen_conversion_setpoints_belong_to_endpoint_devices(self):
        model_book = server_module._book_from_text(
            """<ACLoad>
@ idx name node p_set run_stat
# 1 ac-electrolyzer-load 1 12 1
</ACLoad>
<DCLoad>
@ idx name node p_set run_stat
# 1 dc-electrolyzer-load 2 14 1
</DCLoad>
<ACGenerator>
@ idx name node control_type p_set q_set v_set run_stat
# 1 ac-fuel-cell-source 3 P 16 0 380 1
</ACGenerator>
<DCGenerator>
@ idx name node control_type p_set v_set i_set run_stat
# 1 dc-fuel-cell-source 2 P 18 750 0 1
</DCGenerator>
<HydroSource>
@ idx name node control_type flow_set run_stat
# 1 electrolyzer-h2-source 1 FLOW 2.4 1
# 2 dc-electrolyzer-h2-source 1 FLOW 2.8 1
</HydroSource>
<HydroLoad>
@ idx name node flow_set run_stat
# 1 fuel-cell-h2-load 1 10 1
# 2 ac-fuel-cell-h2-load 1 8 1
</HydroLoad>
<AcE2Hydro>
@ idx name run_stat control_type idx_ac_load_t1 idx_h2_unit_t2 e2h_coeff
# 1 ac-electrolyzer 1 P 1 1 0.2
</AcE2Hydro>
<DcE2Hydro>
@ idx name run_stat control_type idx_dc_load_t1 idx_h2_unit_t2 e2h_coeff
# 1 dc-electrolyzer 1 FLOW 1 2 0.2
</DcE2Hydro>
<Hydro2AcE>
@ idx name run_stat control_type idx_ac_unit_t1 idx_h2_load_t2 h2e_coeff
# 1 ac-fuel-cell 1 P 1 2 1.8
</Hydro2AcE>
<Hydro2DcE>
@ idx name run_stat control_type idx_dc_unit_t1 idx_h2_load_t2 h2e_coeff
# 1 dc-fuel-cell 1 FLOW 1 1 1.8
</Hydro2DcE>
"""
        )

        rows = server_module._generated_control_blocks(model_book)["SetValue"][1]
        values = {
            (str(row["dev_type"]), str(row["dev_name"]), str(row["set_type"]))
            for row in rows
        }

        self.assertIn(("ACLoad", "ac-electrolyzer-load", "p_set"), values)
        self.assertIn(("DCLoad", "dc-electrolyzer-load", "p_set"), values)
        self.assertIn(("ACGenerator", "ac-fuel-cell-source", "p_set"), values)
        self.assertIn(("DCGenerator", "dc-fuel-cell-source", "p_set"), values)
        self.assertIn(("HydroSource", "electrolyzer-h2-source", "flow_set"), values)
        self.assertIn(("HydroSource", "dc-electrolyzer-h2-source", "flow_set"), values)
        self.assertIn(("HydroLoad", "fuel-cell-h2-load", "flow_set"), values)
        self.assertIn(("HydroLoad", "ac-fuel-cell-h2-load", "flow_set"), values)
        self.assertFalse(
            any(
                dev_type in {"AcE2Hydro", "DcE2Hydro", "Hydro2AcE", "Hydro2DcE"}
                and set_type in {"p_set", "flow_set"}
                for dev_type, _dev_name, set_type in values
            )
        )
        bindings = energy_coupling_control_bindings(model_book)
        self.assertEqual(
            bindings[("AcE2Hydro", "ac-electrolyzer")],
            (
                {
                    "set_type": "p_set",
                    "target_dev_type": "ACLoad",
                    "target_dev_name": "ac-electrolyzer-load",
                    "target_set_type": "p_set",
                    "active": True,
                },
                {
                    "set_type": "flow_set",
                    "target_dev_type": "HydroSource",
                    "target_dev_name": "electrolyzer-h2-source",
                    "target_set_type": "flow_set",
                    "active": False,
                },
            ),
        )
        self.assertEqual(
            {binding["target_dev_type"] for binding in bindings[("Hydro2DcE", "dc-fuel-cell")]},
            {"DCGenerator", "HydroLoad"},
        )
        self.assertEqual(
            {
                binding["set_type"]
                for binding in bindings[("Hydro2DcE", "dc-fuel-cell")]
                if binding["active"]
            },
            {"flow_set"},
        )
        self.assertEqual(
            {
                binding["set_type"]
                for binding in bindings[("DcE2Hydro", "dc-electrolyzer")]
                if binding["active"]
            },
            {"flow_set"},
        )
        self.assertEqual(
            {
                binding["set_type"]
                for binding in bindings[("Hydro2AcE", "ac-fuel-cell")]
                if binding["active"]
            },
            {"p_set"},
        )

    def test_generated_model_requires_explicit_converter_dcp_column(self):
        model_book = server_module._book_from_text(
            """<DCACConverter>
@ idx name ac_node dc_node ac_control_type dc_control_type p_ac_set q_ac_set run_stat
# 1 acdc-link 1 2 PQ NONE -12.5 0 1
</DCACConverter>
"""
        )

        with self.assertRaisesRegex(ValueError, "p_dc_set"):
            server_module._generated_model_artifacts(
                server_module.render_ebook_aligned(model_book)
            )

    def test_generated_model_rejects_legacy_combined_converter_control_type(self):
        model_book = server_module._book_from_text(
            """<DCACConverter>
@ idx name ac_node dc_node control_type p_ac_set p_dc_set q_ac_set run_stat
# 1 legacy-link 1 2 DCP -12.5 12.5 0 1
</DCACConverter>
"""
        )

        with self.assertRaisesRegex(ValueError, "control_type"):
            server_module._generated_model_artifacts(
                server_module.render_ebook_aligned(model_book)
            )

    def test_generated_converter_dcp_is_exported_as_remote_adjustment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model_book = server_module._book_from_text(
                """<DCACConverter>
@ idx name ac_node dc_node ac_control_type dc_control_type p_ac_set p_dc_set q_ac_set run_stat
# 1 acdc-link 1 2 PQ NONE -12.5 12.5 0 1
</DCACConverter>
"""
            )
            artifacts = server_module._generated_model_artifacts(
                server_module.render_ebook_aligned(model_book)
            )
            source = root / "source"
            server_module._write_generated_model_artifacts(source, artifacts)
            service = PolarMicrogridSimulator(
                source,
                root / "runtime",
                model_id="converter-dcp",
                kernel=lambda _config: None,
            )

            control_rows = service.definitions()["control"]["SetValue"]["rows"]
            dcp_rows = [
                row
                for row in control_rows
                if row["dev_type"] == "DCACConverter"
                and row["dev_name"] == "acdc-link"
                and row["set_type"] == "p_dc_set"
            ]
            self.assertEqual(len(dcp_rows), 1)
            self.assertEqual(float(dcp_rows[0]["set_value"]), 12.5)
            self.assertIn(
                "DCACConverter.acdc-link.p_dc_set",
                service.external_control_names()["remote_adjustment_names"],
            )
            applied = service.apply_external_control_values(
                {
                    "values": {"DCACConverter.acdc-link.p_dc_set": 6.5},
                    "manual_hold": True,
                }
            )
            self.assertEqual(applied["accepted"]["remote_adjustments"], 1)
            dcp_item = next(
                item
                for item in applied["control_values"]["items"]
                if item["name"] == "DCACConverter.acdc-link.p_dc_set"
            )
            self.assertEqual(float(dcp_item["value"]), 6.5)
            self.assertTrue(dcp_item["active"])

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
