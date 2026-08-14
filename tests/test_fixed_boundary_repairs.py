import unittest
from io import BytesIO
import zipfile

import simu_loop
from simu import server as server_module
from simu.definition_editing import render_ebook_aligned


class FixedBoundaryRepairTest(unittest.TestCase):
    @staticmethod
    def _book(text: str):
        return server_module._book_from_text(text)

    def test_repairs_all_active_electrical_voltage_boundaries_from_controlled_nodes(self):
        book = self._book(
            """<ACNode>
@ idx name vbase run_stat
# 1 ac-380 380 1
# 2 ac-690 0 1
</ACNode>
<ACGenerator>
@ idx name node control_type v_set rated_voltage v_min v_max run_stat
# 1 ac-v 1 V 0 380 304 456 1
# 2 ac-placeholder 1 PQ 0 380 304 456 1
# 3 ac-off 1 PV 0 380 304 456 0
# 4 ac-node-reference 2 PV 690 690 552 828 1
</ACGenerator>
<ACShuntCompensator>
@ idx name node control_type v_set v_min v_max run_stat
# 1 shunt-v 1 V nan 304 456 1
# 2 shunt-q 1 Q 0 304 456 1
</ACShuntCompensator>
<ACACConverter>
@ idx name i_node j_node i_control_type j_control_type i_v_set j_v_set i_v_min i_v_max j_v_min j_v_max run_stat
# 1 acac 1 2 PV PQ 0 0 304 456 552 828 1
</ACACConverter>
<DCNode>
@ idx name vbase run_stat
# 1 dc-750 750 1
# 2 dc-400 400 1
# 3 dc-reference 0 1
</DCNode>
<DCGenerator>
@ idx name node control_type v_set rated_voltage v_min v_max run_stat
# 1 dc-v 1 V 0 750 600 900 1
# 2 dc-placeholder 1 P 0 750 600 900 1
# 3 dc-off 1 SLACK 0 750 600 900 0
# 4 dc-node-reference 3 SLACK 400 400 320 480 1
</DCGenerator>
<DCDCConverter>
@ idx name i_node j_node i_control_type j_control_type v_set i_v_min i_v_max j_v_min j_v_max run_stat
# 1 dcdc-i 1 2 V NONE 0 600 900 320 480 1
# 2 dcdc-j 1 2 NONE V 0 600 900 320 480 1
# 3 dcdc-placeholder 1 2 P NONE 0 600 900 320 480 1
</DCDCConverter>
<DCACConverter>
@ idx name ac_node dc_node ac_control_type dc_control_type v_ac_set v_dc_set ac_v_min ac_v_max dc_v_min dc_v_max run_stat
# 1 dcac-ac 1 1 PH NONE 0 0 304 456 600 900 1
# 2 dcac-dc 1 2 PQ V 0 0 304 456 320 480 1
# 3 dcac-placeholder 1 1 PQ NONE 0 0 304 456 600 900 1
</DCACConverter>
"""
        )

        corrections = simu_loop.repair_fixed_boundary_setpoints(book)

        self.assertEqual(float(book.data["ACNode"].data[1]["vbase"]), 690.0)
        self.assertEqual(float(book.data["ACGenerator"].data[0]["v_set"]), 380.0)
        self.assertEqual(book.data["ACGenerator"].data[1]["v_set"], "0")
        self.assertEqual(book.data["ACGenerator"].data[2]["v_set"], "0")
        self.assertEqual(float(book.data["ACShuntCompensator"].data[0]["v_set"]), 380.0)
        self.assertEqual(book.data["ACShuntCompensator"].data[1]["v_set"], "0")
        self.assertEqual(float(book.data["ACACConverter"].data[0]["i_v_set"]), 380.0)
        self.assertEqual(book.data["ACACConverter"].data[0]["j_v_set"], "0")

        self.assertEqual(float(book.data["DCNode"].data[2]["vbase"]), 400.0)
        self.assertEqual(float(book.data["DCGenerator"].data[0]["v_set"]), 750.0)
        self.assertEqual(book.data["DCGenerator"].data[1]["v_set"], "0")
        self.assertEqual(book.data["DCGenerator"].data[2]["v_set"], "0")
        self.assertEqual(float(book.data["DCDCConverter"].data[0]["v_set"]), 750.0)
        self.assertEqual(float(book.data["DCDCConverter"].data[1]["v_set"]), 400.0)
        self.assertEqual(book.data["DCDCConverter"].data[2]["v_set"], "0")
        self.assertEqual(float(book.data["DCACConverter"].data[0]["v_ac_set"]), 380.0)
        self.assertEqual(book.data["DCACConverter"].data[0]["v_dc_set"], "0")
        self.assertEqual(book.data["DCACConverter"].data[1]["v_ac_set"], "0")
        self.assertEqual(float(book.data["DCACConverter"].data[1]["v_dc_set"]), 400.0)
        self.assertGreaterEqual(len(corrections), 10)

    def test_repairs_legacy_and_side_specific_converter_voltage_controls(self):
        book = self._book(
            """<ACNode>
@ idx name vbase run_stat
# 1 ac-i 380 1
# 2 ac-j 690 1
</ACNode>
<ACACConverter>
@ idx name i_node j_node control_type i_v_set j_v_set run_stat
# 1 legacy-acac 1 2 PVV 0 0 1
</ACACConverter>
<DCNode>
@ idx name vbase run_stat
# 1 dc-i 400 1
# 2 dc-j 750 1
</DCNode>
<DCDCConverter>
@ idx name i_node j_node control_type v_set run_stat
# 1 legacy-dcdc 1 2 V 0 1
</DCDCConverter>
"""
        )

        simu_loop.repair_fixed_boundary_setpoints(book)

        acac = book.data["ACACConverter"].data[0]
        self.assertEqual(float(acac["i_v_set"]), 380.0)
        self.assertEqual(float(acac["j_v_set"]), 690.0)
        self.assertEqual(float(book.data["DCDCConverter"].data[0]["v_set"]), 400.0)

    def test_rejects_dcdc_with_both_sides_using_shared_voltage_setpoint(self):
        book = self._book(
            """<DCNode>
@ idx name vbase run_stat
# 1 dc-i 400 1
# 2 dc-j 750 1
</DCNode>
<DCDCConverter>
@ idx name i_node j_node i_control_type j_control_type v_set run_stat
# 1 dual-v 1 2 V V 0 1
</DCDCConverter>
"""
        )

        with self.assertRaisesRegex(
            ValueError,
            r"DCDCConverter\.dual-v.*i/j 两端同时采用 V 控制.*共享 v_set",
        ):
            simu_loop.repair_fixed_boundary_setpoints(book)

    def test_repairs_pressure_temperature_and_steam_enthalpy_boundaries(self):
        book = self._book(
            """<GasNode>
@ idx name pressure run_stat
# 1 gas-node 5 1
</GasNode>
<GasSource>
@ idx name node control_type pressure_set pressure_min pressure_max run_stat
# 1 gas-pressure 1 SLACK 0 3 7 1
# 2 gas-flow 1 FLOW 0 3 7 1
# 3 gas-off 1 PRESSURE 0 3 7 0
</GasSource>
<GasStorage>
@ idx name node control_type pressure_set pressure_min pressure_max run_stat
# 1 gas-storage 1 V nan 3 7 1
</GasStorage>
<HydroNode>
@ idx name pressure run_stat
# 1 hydro-node 35 1
</HydroNode>
<HydroSource>
@ idx name node control_type pressure_set pressure_min pressure_max run_stat
# 1 hydro-source 1 P 0 10 50 1
# 2 hydro-flow 1 FLOW 0 10 50 1
</HydroSource>
<HydroStorage>
@ idx name node control_type pressure_set pressure_min pressure_max run_stat
# 1 hydro-storage 1 FLOW 0 10 50 1
</HydroStorage>
<HeatNode>
@ idx name pressure supply_temperature return_temperature temperature run_stat
# 1 heat-node 0 0 nan 0 1
</HeatNode>
<HeatSource>
@ idx name node control_type pressure_set pressure_min pressure_max supply_temperature return_temperature run_stat
# 1 heat-reference 1 PRESSURE 10 5 15 88 52 1
# 2 heat-invalid 1 PRESSURE 0 5 15 0 0 1
</HeatSource>
<HeatStorage>
@ idx name node control_type pressure_set supply_temperature_set return_temperature_set run_stat
# 1 heat-storage 1 FLOW 0 0 0 1
</HeatStorage>
<SteamNode>
@ idx name pressure enthalpy run_stat
# 1 steam-node 0 0 1
</SteamNode>
<SteamSource>
@ idx name node control_type pressure_set pressure_min pressure_max enthalpy_set run_stat
# 1 steam-reference 1 PRESSURE 4.5 3 6 3200 1
# 2 steam-invalid 1 P 0 3 6 0 1
</SteamSource>
<SteamStorage>
@ idx name node control_type pressure_set pressure_min pressure_max enthalpy_set run_stat
# 1 steam-storage 1 V 0 3 6 nan 1
</SteamStorage>
"""
        )

        corrections = simu_loop.repair_fixed_boundary_setpoints(book)

        gas_sources = book.data["GasSource"].data
        self.assertEqual(float(gas_sources[0]["pressure_set"]), 5.0)
        self.assertEqual(gas_sources[1]["pressure_set"], "0")
        self.assertEqual(gas_sources[2]["pressure_set"], "0")
        self.assertEqual(float(book.data["GasStorage"].data[0]["pressure_set"]), 5.0)
        self.assertEqual(float(book.data["HydroStorage"].data[0]["pressure_set"]), 35.0)
        hydro_sources = book.data["HydroSource"].data
        self.assertEqual(float(hydro_sources[0]["pressure_set"]), 35.0)
        self.assertEqual(hydro_sources[1]["pressure_set"], "0")

        heat_node = book.data["HeatNode"].data[0]
        self.assertEqual(float(heat_node["pressure"]), 10.0)
        self.assertEqual(float(heat_node["supply_temperature"]), 88.0)
        self.assertEqual(float(heat_node["return_temperature"]), 52.0)
        self.assertEqual(float(heat_node["temperature"]), 88.0)
        heat_storage = book.data["HeatStorage"].data[0]
        self.assertEqual(float(heat_storage["supply_temperature_set"]), 88.0)
        self.assertEqual(float(heat_storage["return_temperature_set"]), 52.0)
        heat_invalid = book.data["HeatSource"].data[1]
        self.assertEqual(float(heat_invalid["pressure_set"]), 10.0)
        self.assertEqual(float(heat_invalid["supply_temperature_set"]), 88.0)
        self.assertEqual(float(heat_invalid["return_temperature_set"]), 52.0)

        steam_node = book.data["SteamNode"].data[0]
        self.assertEqual(float(steam_node["pressure"]), 4.5)
        self.assertEqual(float(steam_node["enthalpy"]), 3200.0)
        steam_invalid = book.data["SteamSource"].data[1]
        self.assertEqual(float(steam_invalid["pressure_set"]), 4.5)
        self.assertEqual(float(steam_invalid["enthalpy_set"]), 3200.0)
        steam_storage = book.data["SteamStorage"].data[0]
        self.assertEqual(float(steam_storage["pressure_set"]), 4.5)
        self.assertEqual(float(steam_storage["enthalpy_set"]), 3200.0)
        self.assertTrue(any(item["device_type"] == "HeatNode" for item in corrections))
        self.assertTrue(any(item["field"] == "enthalpy_set" for item in corrections))

    def test_adds_missing_fixed_boundary_columns_and_render_persists_them(self):
        book = self._book(
            """<HeatNode>
@ idx name pressure supply_temperature return_temperature run_stat
# 1 heat-node 10 85 45 1
</HeatNode>
<HeatSource>
@ idx name node control_type flow_set run_stat
# 1 heat-source 1 PRESSURE 0 1
</HeatSource>
"""
        )

        simu_loop.repair_fixed_boundary_setpoints(book)

        block = book.data["HeatSource"]
        self.assertIn("pressure_set", block.header_list)
        self.assertIn("supply_temperature_set", block.header_list)
        self.assertIn("return_temperature_set", block.header_list)
        self.assertEqual(float(block.data[0]["pressure_set"]), 10.0)
        self.assertEqual(float(block.data[0]["supply_temperature_set"]), 85.0)
        self.assertEqual(float(block.data[0]["return_temperature_set"]), 45.0)
        rendered = render_ebook_aligned(book)
        reparsed = self._book(rendered)
        self.assertEqual(float(reparsed.data["HeatSource"].data[0]["pressure_set"]), 10.0)

    def test_out_of_range_voltage_uses_node_or_bound_midpoint(self):
        book = self._book(
            """<ACGenerator>
@ idx name node control_type v_set rated_voltage v_min v_max run_stat
# 1 node-in-range 1 PV 1000 380 304 456 1
# 2 midpoint-only 2 PV 0 0 600 800 1
</ACGenerator>
<ACNode>
@ idx name vbase run_stat
# 1 ac-node 380 1
# 2 ac-no-reference 0 1
</ACNode>
"""
        )

        simu_loop.repair_fixed_boundary_setpoints(book)

        rows = book.data["ACGenerator"].data
        self.assertEqual(float(rows[0]["v_set"]), 380.0)
        self.assertEqual(float(book.data["ACNode"].data[1]["vbase"]), 700.0)
        self.assertEqual(float(rows[1]["v_set"]), 700.0)

    def test_per_unit_voltage_limits_are_scaled_by_controlled_node_voltage(self):
        book = self._book(
            """<ACNode>
@ idx name vbase run_stat
# 1 ac-node 380 1
</ACNode>
<ACGenerator>
@ idx name node control_type v_set rated_voltage v_min v_max run_stat
# 1 ac-v 1 PV 380 380 0.9 1.1 1
</ACGenerator>
<DCNode>
@ idx name vbase run_stat
# 1 dc-node 400 1
</DCNode>
<DCDCConverter>
@ idx name i_node j_node i_control_type j_control_type v_set i_v_min i_v_max run_stat
# 1 dcdc 1 2 V NONE 400 0.9 1.1 1
</DCDCConverter>
"""
        )

        corrections = simu_loop.repair_fixed_boundary_setpoints(book)

        self.assertEqual(corrections, [])
        self.assertEqual(book.data["ACGenerator"].data[0]["v_set"], "380")
        self.assertEqual(book.data["DCDCConverter"].data[0]["v_set"], "400")

    def test_unrecoverable_boundary_names_device_and_field(self):
        book = self._book(
            """<GasNode>
@ idx name pressure run_stat
# 1 broken-node 0 1
</GasNode>
"""
        )

        with self.assertRaisesRegex(
            ValueError,
            r"GasNode\.broken-node\.pressure.*无法从连接设备、额定值或上下限推导",
        ):
            simu_loop.repair_fixed_boundary_setpoints(book)

    def test_noncontrolling_runtime_pressure_is_not_used_to_hide_invalid_node_boundary(self):
        book = self._book(
            """<GasNode>
@ idx name pressure run_stat
# 1 broken-node 0 1
</GasNode>
<GasSource>
@ idx name node control_type pressure_set pressure run_stat
# 1 flow-source 1 FLOW 0 5 1
</GasSource>
"""
        )

        with self.assertRaisesRegex(
            ValueError,
            r"GasNode\.broken-node\.pressure.*无法从连接设备、额定值或上下限推导",
        ):
            simu_loop.repair_fixed_boundary_setpoints(book)

    def test_fluid_nodes_can_use_explicit_rated_pressure_temperature_and_enthalpy(self):
        book = self._book(
            """<GasNode>
@ idx name pressure rated_pressure run_stat
# 1 gas-node 0 6 1
</GasNode>
<HeatNode>
@ idx name pressure supply_temperature return_temperature temperature rated_supply_temperature rated_return_temperature run_stat
# 1 heat-node 10 0 0 0 90 50 1
</HeatNode>
<SteamNode>
@ idx name pressure enthalpy rated_enthalpy run_stat
# 1 steam-node 5 0 3100 1
</SteamNode>
"""
        )

        corrections = simu_loop.repair_fixed_boundary_setpoints(book)

        self.assertEqual(float(book.data["GasNode"].data[0]["pressure"]), 6.0)
        heat_node = book.data["HeatNode"].data[0]
        self.assertEqual(float(heat_node["supply_temperature"]), 90.0)
        self.assertEqual(float(heat_node["return_temperature"]), 50.0)
        self.assertEqual(float(heat_node["temperature"]), 90.0)
        self.assertEqual(float(book.data["SteamNode"].data[0]["enthalpy"]), 3100.0)
        self.assertTrue(any("rated_" in item["reference"] for item in corrections))

    def test_unrecoverable_fixed_temperature_names_device_and_field(self):
        book = self._book(
            """<HeatNode>
@ idx name pressure supply_temperature return_temperature temperature run_stat
# 1 broken-heat-node 10 0 45 45 1
</HeatNode>
"""
        )

        with self.assertRaisesRegex(
            ValueError,
            r"HeatNode\.broken-heat-node\.supply_temperature.*无法从连接设备、额定值或上下限推导",
        ):
            simu_loop.repair_fixed_boundary_setpoints(book)

    def test_active_fixed_fluid_boundaries_require_live_controlled_nodes(self):
        cases = (
            (
                """<GasNode>
@ idx name pressure run_stat
# 1 off-gas-node 5 0
</GasNode>
<GasSource>
@ idx name node control_type pressure_set run_stat
# 1 gas-source 1 PRESSURE 5 1
</GasSource>
""",
                r"GasSource\.gas-source\.pressure_set.*node=.?1.*没有有效投入节点",
            ),
            (
                """<HeatNode>
@ idx name pressure supply_temperature return_temperature temperature run_stat
# 1 off-heat-node 10 85 45 45 0
</HeatNode>
<HeatSource>
@ idx name node control_type pressure_set supply_temperature_set return_temperature_set run_stat
# 1 heat-source 1 FLOW 0 85 45 1
</HeatSource>
""",
                r"HeatSource\.heat-source\.supply_temperature_set.*node=.?1.*没有有效投入节点",
            ),
            (
                """<SteamNode>
@ idx name pressure enthalpy run_stat
# 1 off-steam-node 5 3000 0
</SteamNode>
<SteamSource>
@ idx name node control_type pressure_set enthalpy_set run_stat
# 1 steam-source 1 FLOW 0 3000 1
</SteamSource>
""",
                r"SteamSource\.steam-source\.enthalpy_set.*node=.?1.*没有有效投入节点",
            ),
        )

        for model_text, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    simu_loop.repair_fixed_boundary_setpoints(self._book(model_text))

    def test_invalid_device_reference_does_not_pollute_node_repair(self):
        book = self._book(
            """<GasNode>
@ idx name pressure run_stat
# 1 gas-node 0 1
</GasNode>
<GasSource>
@ idx name node control_type pressure_set pressure_min pressure_max run_stat
# 1 gas-source 1 PRESSURE 100 3 7 1
</GasSource>
"""
        )

        simu_loop.repair_fixed_boundary_setpoints(book)

        self.assertEqual(float(book.data["GasNode"].data[0]["pressure"]), 5.0)
        self.assertEqual(float(book.data["GasSource"].data[0]["pressure_set"]), 5.0)

    def test_coupling_only_fluid_metadata_without_nodes_is_not_treated_as_live_boundary(self):
        book = self._book(
            """<HydroStorage>
@ idx name node run_stat
# 1 legacy-storage 1 1
</HydroStorage>
"""
        )

        corrections = simu_loop.repair_fixed_boundary_setpoints(book)

        self.assertEqual(corrections, [])
        self.assertNotIn("pressure_set", book.data["HydroStorage"].header_list)

    def test_second_pass_is_idempotent(self):
        book = self._book(
            """<DCNode>
@ idx name vbase run_stat
# 1 dc-node 750 1
</DCNode>
<DCGenerator>
@ idx name node control_type v_set run_stat
# 1 dc-v 1 V 0 1
</DCGenerator>
"""
        )

        first = simu_loop.repair_fixed_boundary_setpoints(book)
        second = simu_loop.repair_fixed_boundary_setpoints(book)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_persisted_control_rows_are_repaired_without_overwriting_valid_controls(self):
        model_book = self._book(
            """<ACNode>
@ idx name vbase run_stat
# 1 ac-node 380 1
</ACNode>
<ACGenerator>
@ idx name node control_type v_set run_stat
# 1 ac-v 1 V 380 1
# 2 ac-pq 1 PQ 0 1
# 3 activated-by-control 1 V 0 0
# 4 stopped-by-control 1 V 380 1
</ACGenerator>
<HeatNode>
@ idx name pressure supply_temperature return_temperature run_stat
# 1 heat-node 10 85 45 1
</HeatNode>
<HeatSource>
@ idx name node control_type pressure_set supply_temperature_set return_temperature_set run_stat
# 1 heat-source 1 PRESSURE 10 85 45 1
</HeatSource>
"""
        )
        control_book = self._book(
            """<RunStat>
@ dev_type dev_name run_stat
# ACGenerator activated-by-control 1
# ACGenerator stopped-by-control 0
</RunStat>
<SetValue>
@ dev_type dev_name set_type set_value
# ACGenerator ac-v v_set 0
# ACGenerator ac-pq v_set 0
# ACGenerator activated-by-control v_set 0
# ACGenerator stopped-by-control v_set 0
# HeatSource heat-source pressure_set nan
# HeatSource heat-source supply_temperature_set 0
# HeatSource heat-source return_temperature_set 0
</SetValue>
"""
        )

        corrections = server_module._repair_fixed_boundary_control_rows(
            model_book,
            control_book,
        )

        values = {
            (row["dev_name"], row["set_type"]): row["set_value"]
            for row in control_book.data["SetValue"].data
        }
        self.assertEqual(float(values[("ac-v", "v_set")]), 380.0)
        self.assertEqual(values[("ac-pq", "v_set")], "0")
        self.assertEqual(float(values[("activated-by-control", "v_set")]), 380.0)
        self.assertEqual(values[("stopped-by-control", "v_set")], "0")
        self.assertEqual(float(values[("heat-source", "pressure_set")]), 10.0)
        self.assertEqual(float(values[("heat-source", "supply_temperature_set")]), 85.0)
        self.assertEqual(float(values[("heat-source", "return_temperature_set")]), 45.0)
        self.assertEqual(len(corrections), 6)

    def test_definition_archive_renders_repaired_model_and_control_values(self):
        model_text = """<ACNode>
@ idx name vbase run_stat
# 1 ac-node 380 1
</ACNode>
<ACGenerator>
@ idx name node control_type v_set run_stat
# 1 ac-v 1 V 0 1
</ACGenerator>
"""
        control_text = """<SetValue>
@ dev_type dev_name set_type set_value
# ACGenerator ac-v v_set 0
</SetValue>
"""
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("model.e", model_text)
            archive.writestr(
                "meas.e",
                "<Measurement>\n@ idx name dev_type dev_name meas_type weight valid value\n</Measurement>\n",
            )
            archive.writestr("control.e", control_text)
            archive.writestr(
                "curves.e",
                "<CurveInfo>\n@ mode time_step_minutes point_count\n# day 1 1440\n</CurveInfo>\n",
            )
            archive.writestr(
                "diagram.svg",
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>',
            )

        parsed = server_module._parse_definition_archive(buffer.getvalue())

        parsed_model = self._book(parsed["model_text"])
        parsed_control = self._book(parsed["control_text"])
        self.assertEqual(float(parsed_model.data["ACGenerator"].data[0]["v_set"]), 380.0)
        self.assertEqual(float(parsed_control.data["SetValue"].data[0]["set_value"]), 380.0)


if __name__ == "__main__":
    unittest.main()
