from __future__ import annotations

import unittest

import simu.renewable_control as renewable_control
from simu.renewable_control import (
    RenewableControlSettings,
    calculate_renewable_control_plan,
)
from tests.test_trainee_renewable_backend_control import (
    add_balance_storage,
    add_generator_device,
    add_second_dc_balance_group,
    add_second_dc_grid_storage_group,
    append_model_row,
    renewable_snapshot,
    set_measurement_value,
)


def add_setpoint(snapshot: dict, dev_type: str, dev_name: str, set_type: str = "p_set") -> None:
    snapshot["definitions"]["control"]["SetValue"]["rows"].append(
        {
            "dev_type": dev_type,
            "dev_name": dev_name,
            "set_type": set_type,
        }
    )


def command_map(plan: dict) -> dict[tuple[str, str, str], float]:
    return {
        (row["dev_type"], row["dev_name"], row["set_type"]): row["set_value"]
        for row in plan["commands"]
    }


class RenewableTopologyDirectDispatchTest(unittest.TestCase):
    def test_topology_island_optimizer_applies_safe_projected_targets(self):
        snapshot = renewable_snapshot()
        converter_device = next(
            row
            for row in snapshot["devices"]
            if row.get("dev_name") == "grid-converter-1"
        )
        converter_device["raw"].update(
            {
                "dev_type": "grid-acdc-converter",
                "p_ac_min": "-50",
                "p_ac_max": "50",
            }
        )
        storage_device = next(
            row
            for row in snapshot["devices"]
            if row.get("dev_name") == "storage-1"
        )
        storage_device["set_types"] = ["p_set"]
        add_setpoint(snapshot, "ACGenerator", "diesel-1")
        add_setpoint(snapshot, "DCGenerator", "storage-1")

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.10,
            ),
        )
        rows = {row["dev_name"]: row for row in plan["commandRows"]}
        metrics = plan["metrics"]

        expected_wind_available_kw = 100.0 * ((8.0 - 3.0) / (10.0 - 3.0)) ** 3
        self.assertTrue(metrics["optimizationEnabled"])
        self.assertTrue(metrics["optimizationAllIslandsSuccessful"])
        self.assertLess(metrics["optimizationMaxBalanceResidualKw"], 1e-5)
        self.assertTrue(metrics["optimizationApplied"])
        self.assertEqual(metrics["optimizationMode"], "active")
        self.assertFalse(metrics["optimizationStepOverrideApplied"])
        self.assertEqual(metrics["optimizationStepOverrideDevices"], [])
        self.assertFalse(metrics["optimizationIslands"][0]["stepOverrideApplied"])
        self.assertEqual(rows["wind-1"]["optimizationStatus"], "optimal")
        self.assertAlmostEqual(
            rows["wind-1"]["weatherAvailableKw"],
            expected_wind_available_kw,
            places=5,
        )
        self.assertAlmostEqual(
            rows["wind-1"]["optimizationSuggestedKw"],
            40.0,
            places=5,
        )
        for name in (
            "wind-1",
            "pv-1",
            "grid-converter-1",
            "storage-1",
            "diesel-1",
        ):
            self.assertAlmostEqual(
                rows[name]["commandKw"],
                rows[name]["optimizationSuggestedKw"],
                places=5,
            )
        self.assertAlmostEqual(
            rows["grid-converter-1"]["optimizationSuggestedSystemKw"],
            -rows["grid-converter-1"]["optimizationSuggestedKw"],
            places=5,
        )

    def test_strategy_keeps_storage_on_the_safe_side_outside_soc_deadband(self):
        for soc, relation in ((0.10, "charge"), (0.96, "not_charge")):
            with self.subTest(soc=soc):
                snapshot = renewable_snapshot()
                converter_device = next(
                    row
                    for row in snapshot["devices"]
                    if row.get("dev_name") == "grid-converter-1"
                )
                converter_device["raw"].update(
                    {
                        "dev_type": "grid-acdc-converter",
                        "p_ac_min": "-50",
                        "p_ac_max": "50",
                    }
                )
                storage_device = next(
                    row
                    for row in snapshot["devices"]
                    if row.get("dev_name") == "storage-1"
                )
                storage_device["set_types"] = ["p_set"]
                add_setpoint(snapshot, "ACGenerator", "diesel-1")
                add_setpoint(snapshot, "DCGenerator", "storage-1")
                set_measurement_value(
                    snapshot,
                    "DCGenerator",
                    "storage-1",
                    "SOC",
                    soc,
                )

                plan = calculate_renewable_control_plan(
                    snapshot,
                    RenewableControlSettings(
                        step_coefficient=0.10,
                        converter_step_ratio=0.10,
                        soc_deadband=0.05,
                    ),
                )
                storage_row = next(
                    row
                    for row in plan["commandRows"]
                    if row.get("dev_name") == "storage-1"
                )

                self.assertEqual(storage_row["optimizationStatus"], "optimal")
                if relation == "charge":
                    self.assertLess(storage_row["commandKw"], 0.0)
                else:
                    self.assertGreaterEqual(storage_row["commandKw"], -1e-6)

    def test_dispatch_commands_are_unique_per_typed_setpoint(self):
        commands, duplicates = renewable_control._deduplicate_dispatch_commands(
            [
                {
                    "dev_type": "DCACConverter",
                    "dev_name": "converter-1",
                    "set_type": "p_ac_set",
                    "set_value": -10.0,
                },
                {
                    "dev_type": "DCACConverter",
                    "dev_name": "converter-1",
                    "set_type": "p_ac_set",
                    "set_value": -8.0,
                },
                {
                    "dev_type": "DCACConverter",
                    "dev_name": "converter-1",
                    "set_type": "q_ac_set",
                    "set_value": 0.0,
                },
            ]
        )

        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0]["set_value"], -8.0)
        self.assertEqual(commands[1]["set_type"], "q_ac_set")
        self.assertEqual(duplicates[0]["duplicateCount"], 2)

    def test_linear_discharge_derating_removes_only_excess_dc_export(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "SOC", 0.25)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "P_GEN", 30.0)
        set_measurement_value(
            snapshot,
            "DCACConverter",
            "grid-converter-1",
            "P_AC",
            -30.0,
        )
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 50.0)

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.20),
        )
        rows = {row["dev_name"]: row for row in plan["commandRows"]}

        # At 25% SOC the configured linear curve allows 40% of the 40 kW
        # discharge rating. The optimizer may choose any smaller target, but
        # it must never exceed the interpolated segment limit.
        self.assertAlmostEqual(rows["storage-1"]["signedMaxTargetKw"], 16.0)
        self.assertLessEqual(rows["storage-1"]["projectedTargetKw"], 16.0 + 1e-9)
        self.assertGreaterEqual(rows["storage-1"]["projectedTargetKw"], -1e-9)
        self.assertAlmostEqual(
            rows["grid-converter-1"]["commandKw"],
            rows["grid-converter-1"]["optimizationSuggestedKw"],
        )

    def test_soc_at_lower_limit_stops_dc_export_for_grid_forming_storage(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "SOC", 0.20)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "P_GEN", 30.0)
        set_measurement_value(
            snapshot,
            "DCACConverter",
            "grid-converter-1",
            "P_AC",
            -30.0,
        )
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 50.0)

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.20),
        )
        rows = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(rows["storage-1"]["signedMaxTargetKw"], 0.0)
        self.assertLessEqual(rows["storage-1"]["projectedTargetKw"], 0.0)
        self.assertAlmostEqual(
            rows["grid-converter-1"]["commandKw"],
            rows["grid-converter-1"]["optimizationSuggestedKw"],
        )

    def test_low_diesel_validation_preserves_one_step_and_publishes_final_targets(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 19.0)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "P_GEN", -5.0)
        set_measurement_value(
            snapshot,
            "DCACConverter",
            "grid-converter-1",
            "P_AC",
            -5.0,
        )

        plan = calculate_renewable_control_plan(snapshot)
        rows = {row["dev_name"]: row for row in plan["commandRows"]}

        # Once diesel is below its lower protection-band boundary and storage
        # SOC is still above its lower limit, renewable output has no recovery
        # headroom.  A charging storage means the island already has surplus
        # renewable energy, so the first stage must issue curtailment instead.
        self.assertLess(rows["pv-1"]["commandKw"], 20.0)
        self.assertLessEqual(rows["wind-1"]["commandKw"], 30.0)
        self.assertTrue(plan["metrics"]["renewableRaiseBlockedByDieselGuard"])
        self.assertTrue(plan["metrics"]["renewableCurtailmentRequiredByCharging"])
        self.assertGreater(plan["metrics"]["renewableDieselGuardCurtailRequestKw"], 0.0)
        self.assertGreaterEqual(
            rows["diesel-1"]["commandKw"],
            rows["diesel-1"]["minKw"],
        )
        self.assertLessEqual(
            rows["grid-converter-1"]["commandKw"],
            rows["grid-converter-1"]["signedMaxTargetKw"] + 1e-9,
        )
        self.assertGreaterEqual(
            rows["grid-converter-1"]["commandKw"],
            rows["grid-converter-1"]["signedMinTargetKw"] - 1e-9,
        )
        self.assertTrue(plan["metrics"]["optimizationApplied"])

    def test_low_diesel_above_lower_soc_holds_renewable_when_storage_is_not_charging(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 19.0)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "SOC", 0.50)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "P_GEN", 0.0)

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(diesel_power_protection_ratio=0.05),
        )
        rows = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(rows["wind-1"]["commandKw"], 30.0)
        self.assertAlmostEqual(rows["pv-1"]["commandKw"], 20.0)
        self.assertTrue(plan["metrics"]["renewableRaiseBlockedByDieselGuard"])
        self.assertFalse(plan["metrics"]["renewableCurtailmentRequiredByCharging"])
        self.assertAlmostEqual(
            plan["metrics"]["renewableDieselGuardCurtailRequestKw"],
            0.0,
        )

    def test_unchanged_renewable_targets_remain_in_complete_generation_snapshot(self):
        plan = calculate_renewable_control_plan(
            renewable_snapshot(),
            RenewableControlSettings(step_coefficient=0.0),
        )
        commands = command_map(plan)
        rows = {
            row["dev_name"]: row
            for row in plan["commandRows"]
            if row.get("technology") in {"wind", "pv"}
        }

        self.assertAlmostEqual(commands[("ACGenerator", "wind-1", "p_set")], 30.0)
        self.assertAlmostEqual(commands[("DCGenerator", "pv-1", "p_set")], 20.0)
        self.assertTrue(rows["wind-1"]["strategyCommand"])
        self.assertTrue(rows["pv-1"]["strategyCommand"])
        self.assertFalse(rows["wind-1"]["strategyTargetChanged"])
        self.assertFalse(rows["pv-1"]["strategyTargetChanged"])

    def test_positive_acdc_power_is_not_counted_as_fake_dc_export(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "SOC", 0.10)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "P_GEN", 0.0)
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 23.0)
        set_measurement_value(
            snapshot,
            "DCACConverter",
            "grid-converter-1",
            "P_AC",
            5.0,
        )

        plan = calculate_renewable_control_plan(snapshot)
        rows = {row["dev_name"]: row for row in plan["commandRows"]}
        group = plan["metrics"]["directGridFormingDcGroups"][0]

        self.assertGreater(rows["grid-converter-1"]["commandKw"], 0.0)
        self.assertLessEqual(rows["storage-1"]["projectedTargetKw"], 0.0)
        self.assertTrue(plan["metrics"]["optimizationApplied"])
        self.assertTrue(group["dataComplete"])

    def test_low_soc_dc_storage_does_not_block_when_acdc_is_not_its_actuator(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "SOC", 0.10)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "P_GEN", 10.0)
        set_measurement_value(
            snapshot,
            "DCACConverter",
            "grid-converter-1",
            "P_AC",
            0.0,
        )
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 50.0)

        plan = calculate_renewable_control_plan(snapshot)

        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        self.assertNotIn(
            "储能SOC功率边界与交直流变流器容量边界没有可行交集",
            plan["dataQuality"]["issues"],
        )
        rows = {row["dev_name"]: row for row in plan["commandRows"]}
        self.assertAlmostEqual(
            rows["grid-converter-1"]["commandKw"],
            rows["grid-converter-1"]["optimizationSuggestedKw"],
        )
        self.assertLessEqual(
            rows["storage-1"]["projectedTargetKw"],
            rows["storage-1"]["signedMaxTargetKw"] + 1e-9,
        )

    def test_low_soc_grid_forming_storage_command_stays_within_soc_power_limit(self):
        snapshot = renewable_snapshot()
        add_setpoint(snapshot, "DCGenerator", "storage-1")
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "SOC", 0.10)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "P_GEN", 10.0)
        set_measurement_value(
            snapshot,
            "DCACConverter",
            "grid-converter-1",
            "P_AC",
            0.0,
        )
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 50.0)

        plan = calculate_renewable_control_plan(snapshot)
        storage = next(
            row for row in plan["commandRows"] if row["dev_name"] == "storage-1"
        )

        self.assertLessEqual(
            storage["commandKw"], storage["signedMaxTargetKw"] + 1e-9
        )
        self.assertTrue(
            any(
                command["dev_name"] == "storage-1"
                for command in plan["commands"]
            )
        )

    def test_each_dc_group_closes_residual_without_borrowing_another_group(self):
        snapshot = renewable_snapshot()
        add_second_dc_balance_group(snapshot, converter_power_kw=-10.0)
        add_generator_device(
            snapshot,
            dev_type="ACGenerator",
            name="diesel-2",
            idx=11,
            node=10,
            mode="PH",
            power_kw=20.0,
            rated_capacity_kw=100.0,
            set_type="p_set",
        )
        diesel_2 = next(
            row for row in snapshot["devices"] if row["dev_name"] == "diesel-2"
        )
        diesel_2["raw"]["p_min"] = "20"
        diesel_2["raw"]["dev_type"] = "ac-diesel-source"
        snapshot["device_parameters"]["ACDieselGen"].append(
            {"idx": 2, "idx_acgenerator": 11, "rated_power": 100, "p_min": 20}
        )
        add_setpoint(snapshot, "ACGenerator", "diesel-1")
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 25.0)
        set_measurement_value(snapshot, "ACGenerator", "diesel-2", "P_GEN", 20.0)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "SOC", 0.96)
        set_measurement_value(
            snapshot,
            "DCGenerator",
            "second-group-balance",
            "SOC",
            0.10,
        )
        set_measurement_value(
            snapshot,
            "DCACConverter",
            "grid-converter-1",
            "P_AC",
            -5.0,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.10),
        )
        groups = plan["metrics"]["directGridFormingDcGroups"]

        self.assertTrue(all(group["dataComplete"] for group in groups))
        second_converter = next(
            row
            for row in plan["commandRows"]
            if row["dev_name"] == "second-group-converter"
        )
        self.assertLessEqual(
            second_converter["commandKw"],
            second_converter["signedMaxTargetKw"] + 1e-9,
        )
        self.assertGreaterEqual(
            second_converter["commandKw"],
            second_converter["signedMinTargetKw"] - 1e-9,
        )
        second_component = next(
            row
            for row in plan["metrics"]["acComponentDispatch"]
            if row["gridComponentId"]
            == next(
                group["acComponentIds"][0]
                for group in plan["metrics"]["directGridFormingDcGroups"]
                if group["dcTransferGroupId"]
                == second_converter["dcTransferGroupId"]
            )
        )
        diesel_2_row = next(
            row
            for row in plan["commandRows"]
            if row["dev_name"] == "diesel-2"
        )
        self.assertGreaterEqual(diesel_2_row["commandKw"], diesel_2_row["minKw"])
        self.assertAlmostEqual(
            diesel_2_row["commandKw"],
            diesel_2_row["optimizationSuggestedKw"],
        )
        self.assertTrue(second_component["gridComponentId"])

    def test_full_storage_does_not_leave_dc_residual_when_export_is_reduced(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "SOC", 0.90)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "P_GEN", 0.0)
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 19.0)
        set_measurement_value(
            snapshot,
            "DCACConverter",
            "grid-converter-1",
            "P_AC",
            -5.0,
        )

        plan = calculate_renewable_control_plan(snapshot)
        rows = {row["dev_name"]: row for row in plan["commandRows"]}
        group = plan["metrics"]["directGridFormingDcGroups"][0]

        self.assertGreaterEqual(rows["storage-1"]["projectedTargetKw"], -1e-9)
        self.assertLessEqual(
            rows["grid-converter-1"]["commandKw"],
            rows["grid-converter-1"]["signedMaxTargetKw"] + 1e-9,
        )
        self.assertGreaterEqual(
            rows["grid-converter-1"]["commandKw"],
            rows["grid-converter-1"]["signedMinTargetKw"] - 1e-9,
        )
        self.assertLessEqual(rows["pv-1"]["commandKw"], rows["pv-1"]["availableKw"] + 1e-9)
        self.assertTrue(group["dataComplete"])

    def test_ac_component_clipping_preserves_dc_balance_and_renewable_priority(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "SOC", 0.60)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "P_GEN", 0.0)
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 26.5)
        set_measurement_value(
            snapshot,
            "DCACConverter",
            "grid-converter-1",
            "P_AC",
            -5.0,
        )

        plan = calculate_renewable_control_plan(snapshot)
        rows = {row["dev_name"]: row for row in plan["commandRows"]}
        group = plan["metrics"]["directGridFormingDcGroups"][0]

        self.assertGreaterEqual(rows["wind-1"]["commandKw"], rows["wind-1"]["currentKw"])
        self.assertGreaterEqual(rows["pv-1"]["commandKw"], rows["pv-1"]["currentKw"])
        self.assertLessEqual(
            rows["storage-1"]["projectedTargetKw"],
            rows["storage-1"]["signedMaxTargetKw"] + 1e-9,
        )
        self.assertGreaterEqual(
            rows["storage-1"]["projectedTargetKw"],
            rows["storage-1"]["signedMinTargetKw"] - 1e-9,
        )
        self.assertLessEqual(
            rows["grid-converter-1"]["commandKw"],
            rows["grid-converter-1"]["signedMaxTargetKw"] + 1e-9,
        )
        self.assertGreaterEqual(
            rows["grid-converter-1"]["commandKw"],
            rows["grid-converter-1"]["signedMinTargetKw"] - 1e-9,
        )
        self.assertTrue(group["dataComplete"])
        self.assertGreaterEqual(rows["diesel-1"]["commandKw"], rows["diesel-1"]["minKw"])

    def test_supported_diesel_and_grid_forming_storage_emit_real_commands(self):
        snapshot = renewable_snapshot()
        snapshot["devices"] = [
            row
            for row in snapshot["devices"]
            if not (
                row.get("dev_type") == "DCGenerator"
                and row.get("dev_name") == "storage-1"
            )
        ]
        snapshot["measurements"]["scada"] = [
            row
            for row in snapshot["measurements"]["scada"]
            if row.get("dev_name") != "storage-1"
        ]
        snapshot["definitions"]["model"]["DCGenerator"]["rows"] = [
            row
            for row in snapshot["definitions"]["model"]["DCGenerator"]["rows"]
            if row.get("name") != "storage-1"
        ]
        snapshot["device_parameters"]["DCStorageGen"] = []
        set_measurement_value(snapshot, "ACGenerator", "wind-1", "P_GEN", 100.0)
        set_measurement_value(snapshot, "DCGenerator", "pv-1", "P_GEN", 80.0)
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 80.0)

        add_balance_storage(
            snapshot,
            side="AC",
            name="ac-forming-storage",
            idx=4,
            node=2,
            current_kw=0.0,
            soc=0.60,
        )
        add_balance_storage(
            snapshot,
            side="DC",
            name="dc-forming-storage",
            idx=4,
            node=3,
            current_kw=0.0,
            soc=0.60,
        )
        add_setpoint(snapshot, "ACGenerator", "diesel-1")
        add_setpoint(snapshot, "ACGenerator", "ac-forming-storage")
        add_setpoint(snapshot, "DCGenerator", "dc-forming-storage")

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.20,
            ),
        )
        commands = command_map(plan)
        rows = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertIn(("ACGenerator", "diesel-1", "p_set"), commands)
        self.assertIn(("ACGenerator", "ac-forming-storage", "p_set"), commands)
        self.assertIn(("DCGenerator", "dc-forming-storage", "p_set"), commands)
        self.assertGreater(commands[("ACGenerator", "ac-forming-storage", "p_set")], 0.0)
        self.assertGreater(commands[("DCGenerator", "dc-forming-storage", "p_set")], 0.0)
        self.assertGreaterEqual(
            commands[("ACGenerator", "diesel-1", "p_set")],
            rows["diesel-1"]["minKw"],
        )
        self.assertLessEqual(
            commands[("ACGenerator", "diesel-1", "p_set")],
            rows["diesel-1"]["capacityKw"],
        )
        self.assertLessEqual(
            abs(commands[("DCGenerator", "dc-forming-storage", "p_set")]),
            rows["dc-forming-storage"]["signedMaxTargetKw"] + 1e-9,
        )

    def test_diesel_and_dc_export_are_validated_per_ac_component(self):
        snapshot = renewable_snapshot()
        add_second_dc_balance_group(snapshot, converter_power_kw=0.0)
        add_generator_device(
            snapshot,
            dev_type="ACGenerator",
            name="diesel-2",
            idx=11,
            node=10,
            mode="PH",
            power_kw=20.0,
            rated_capacity_kw=100.0,
            set_type="p_set",
        )
        diesel_2 = next(
            row for row in snapshot["devices"] if row["dev_name"] == "diesel-2"
        )
        diesel_2["raw"]["p_min"] = "20"
        diesel_2["raw"]["dev_type"] = "ac-diesel-source"
        snapshot["device_parameters"]["ACDieselGen"].append(
            {"idx": 2, "idx_acgenerator": 11, "rated_power": 100, "p_min": 20}
        )
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 80.0)
        set_measurement_value(
            snapshot,
            "DCGenerator",
            "second-group-balance",
            "P_GEN",
            0.0,
        )
        set_measurement_value(
            snapshot,
            "DCGenerator",
            "second-group-balance",
            "SOC",
            0.60,
        )
        add_setpoint(snapshot, "ACGenerator", "diesel-1")
        add_setpoint(snapshot, "DCGenerator", "second-group-balance")

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.20,
            ),
        )
        rows = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertTrue(rows["diesel-1"]["gridComponentId"])
        self.assertTrue(rows["diesel-2"]["gridComponentId"])
        self.assertNotEqual(
            rows["diesel-1"]["gridComponentId"],
            rows["diesel-2"]["gridComponentId"],
        )
        self.assertGreaterEqual(rows["diesel-2"]["commandKw"], rows["diesel-2"]["minKw"])
        self.assertLessEqual(rows["diesel-2"]["commandKw"], rows["diesel-2"]["capacityKw"])
        self.assertAlmostEqual(
            rows["second-group-converter"]["commandKw"],
            rows["second-group-converter"]["optimizationSuggestedKw"],
        )
        self.assertAlmostEqual(
            rows["second-group-balance"]["projectedTargetKw"],
            rows["second-group-balance"]["optimizationSuggestedKw"],
        )
        components = {
            row["gridComponentId"]: row
            for row in plan["metrics"]["acComponentDispatch"]
        }
        second_component = components[rows["diesel-2"]["gridComponentId"]]
        self.assertTrue(second_component["gridComponentId"])

        groups = {
            row["dcTransferGroupId"]: row
            for row in plan["metrics"]["directGridFormingDcGroups"]
        }
        second_group = groups[rows["second-group-converter"]["dcTransferGroupId"]]
        self.assertTrue(second_group["dataComplete"])
        self.assertEqual(
            second_group["dcTransferGroupId"],
            rows["second-group-converter"]["dcTransferGroupId"],
        )

    def test_dc_group_without_local_diesel_does_not_follow_other_component_diesel(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 50.0)
        add_second_dc_grid_storage_group(
            snapshot,
            storage_max_discharge_kw=40.0,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.25),
        )
        rows = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(rows["second-dc-grid-storage"]["targetKw"], 0.0)
        self.assertAlmostEqual(
            rows["second-grid-storage-converter"]["commandKw"],
            0.0,
        )

    def test_low_soc_protection_in_one_dc_group_does_not_dispatch_another_component(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 50.0)
        set_measurement_value(
            snapshot,
            "DCACConverter",
            "grid-converter-1",
            "P_AC",
            -5.0,
        )
        add_balance_storage(
            snapshot,
            side="DC",
            name="low-soc-balance",
            idx=5,
            node=3,
            current_kw=15.0,
            soc=0.10,
        )
        add_second_dc_grid_storage_group(
            snapshot,
            storage_max_discharge_kw=40.0,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.25),
        )
        rows = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(rows["second-dc-grid-storage"]["targetKw"], 0.0)
        self.assertAlmostEqual(
            rows["second-grid-storage-converter"]["commandKw"],
            0.0,
        )

    def test_grid_forming_storage_behind_closed_break_is_directly_protected(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "P_GEN", -15.0)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "SOC", 0.95)
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 50.0)
        add_setpoint(snapshot, "DCGenerator", "storage-1")

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.20,
            ),
        )
        storage = next(
            row for row in plan["commandRows"] if row["dev_name"] == "storage-1"
        )

        self.assertTrue(storage["activePath"])
        self.assertTrue(storage["commandable"])
        self.assertGreater(storage["commandKw"], storage["currentKw"])
        self.assertTrue(
            any(command["dev_name"] == "storage-1" for command in plan["commands"])
        )

    def test_unknown_grid_forming_soc_blocks_affected_dc_group(self):
        snapshot = renewable_snapshot()
        snapshot["measurements"]["scada"] = [
            row
            for row in snapshot["measurements"]["scada"]
            if not (
                row.get("dev_name") == "storage-1"
                and row.get("meas_type") == "SOC"
            )
        ]
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 30.0)

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.20,
            ),
        )
        commands = command_map(plan)
        rows = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertNotIn(("DCGenerator", "pv-1", "p_set"), commands)
        self.assertNotIn(
            ("DCACConverter", "grid-converter-1", "p_ac_set"),
            commands,
        )
        self.assertAlmostEqual(rows["pv-1"]["commandKw"], 20.0)
        self.assertAlmostEqual(rows["grid-converter-1"]["commandKw"], 0.0)
        self.assertTrue(
            any("storage-1" in issue and "传输组闭锁" in issue for issue in plan["dataQuality"]["issues"])
        )

    def test_missing_storage_or_converter_power_blocks_without_using_zero(self):
        snapshot = renewable_snapshot()
        snapshot["measurements"]["scada"] = [
            row
            for row in snapshot["measurements"]["scada"]
            if not (
                row.get("dev_name") in {"storage-1", "grid-converter-1"}
                and row.get("meas_type") in {"P_GEN", "P_AC"}
            )
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertFalse(plan["dataQuality"]["dispatchAllowed"])
        self.assertEqual(plan["commands"], [])
        self.assertTrue(
            any("实时有功" in issue for issue in plan["dataQuality"]["issues"])
        )
        storage = next(row for row in plan["commandRows"] if row["dev_name"] == "storage-1")
        converter = next(
            row for row in plan["commandRows"] if row["dev_name"] == "grid-converter-1"
        )
        self.assertIsNone(storage["currentKw"])
        self.assertIsNone(converter["currentKw"])

    def test_missing_converter_power_keeps_dc_group_incomplete(self):
        snapshot = renewable_snapshot()
        snapshot["measurements"]["scada"] = [
            row
            for row in snapshot["measurements"]["scada"]
            if not (
                row.get("dev_name") == "grid-converter-1"
                and row.get("meas_type") == "P_AC"
            )
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertFalse(plan["dataQuality"]["dispatchAllowed"])
        self.assertEqual(plan["commands"], [])
        group = plan["metrics"]["directGridFormingDcGroups"][0]
        self.assertFalse(group["dataComplete"])
        self.assertIsNone(group["acdcCurrentKw"])
        self.assertTrue(
            any("变流器" in issue and "实时有功" in issue for issue in plan["dataQuality"]["issues"])
        )

    def test_dc_soc_protection_keeps_all_resources_inside_optimization_bounds(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "ACGenerator", "wind-1", "P_GEN", 100.0)
        set_measurement_value(snapshot, "DCGenerator", "pv-1", "P_GEN", 80.0)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "P_GEN", -5.0)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "SOC", 0.95)
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 20.0)

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.20,
            ),
        )
        rows = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertLessEqual(rows["wind-1"]["commandKw"], rows["wind-1"]["availableKw"] + 1e-9)
        self.assertLessEqual(rows["pv-1"]["commandKw"], rows["pv-1"]["availableKw"] + 1e-9)
        self.assertGreaterEqual(rows["storage-1"]["projectedTargetKw"], -1e-9)
        self.assertTrue(plan["metrics"]["optimizationApplied"])

    def test_high_soc_active_discharge_respects_segment_and_step_bounds(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "SOC", 0.96)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "P_GEN", 0.0)
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 20.0)
        set_measurement_value(
            snapshot,
            "DCACConverter",
            "grid-converter-1",
            "P_AC",
            -5.0,
        )

        plan = calculate_renewable_control_plan(snapshot)
        rows = {row["dev_name"]: row for row in plan["commandRows"]}
        group = plan["metrics"]["directGridFormingDcGroups"][0]

        self.assertGreaterEqual(rows["storage-1"]["projectedTargetKw"], 0.0)
        self.assertLessEqual(
            rows["storage-1"]["projectedTargetKw"],
            rows["storage-1"]["signedMaxTargetKw"] + 1e-9,
        )
        self.assertLessEqual(rows["wind-1"]["commandKw"], rows["wind-1"]["availableKw"] + 1e-9)
        self.assertLessEqual(rows["pv-1"]["commandKw"], rows["pv-1"]["availableKw"] + 1e-9)
        self.assertAlmostEqual(
            rows["grid-converter-1"]["commandKw"],
            rows["grid-converter-1"]["optimizationSuggestedKw"],
        )
        self.assertTrue(group["dataComplete"])

    def test_high_soc_charge_shortfall_uses_final_topology_limited_targets(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "SOC", 0.91)
        set_measurement_value(snapshot, "DCGenerator", "storage-1", "P_GEN", -30.0)
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 20.0)

        plan = calculate_renewable_control_plan(snapshot)
        rows = {row["dev_name"]: row for row in plan["commandRows"]}
        metrics = plan["metrics"]

        self.assertGreaterEqual(rows["storage-1"]["projectedTargetKw"], 0.0)
        self.assertLessEqual(rows["wind-1"]["commandKw"], rows["wind-1"]["availableKw"] + 1e-9)
        self.assertLessEqual(rows["pv-1"]["commandKw"], rows["pv-1"]["availableKw"] + 1e-9)
        self.assertTrue(metrics["optimizationApplied"])
        self.assertAlmostEqual(
            rows["storage-1"]["projectedTargetKw"],
            rows["storage-1"]["optimizationSuggestedKw"],
        )

    def test_combined_candidate_does_not_push_diesel_below_minimum(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 30.0)

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.20,
            ),
        )
        rows = {row["dev_name"]: row for row in plan["commandRows"]}
        combined_effect_kw = (
            rows["wind-1"]["commandKw"]
            - rows["wind-1"]["currentKw"]
            + rows["grid-converter-1"]["currentKw"]
            - rows["grid-converter-1"]["commandKw"]
        )
        predicted_diesel_kw = rows["diesel-1"]["currentKw"] - combined_effect_kw

        self.assertGreaterEqual(predicted_diesel_kw, rows["diesel-1"]["minKw"] - 1e-9)
        self.assertAlmostEqual(
            plan["metrics"]["candidatePowerEffectKw"],
            combined_effect_kw,
        )
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], predicted_diesel_kw)

    def test_secondary_island_recovery_is_capped_by_local_charge_allowance(self):
        component = renewable_control._RenewableStorageIslandComponent(
            grid_component_id="component-2",
            dc_transfer_group_id="group-2",
            renewable_rows=(
                {
                    "dev_type": "DCGenerator",
                    "dev_name": "secondary-pv",
                    "currentKw": 20.0,
                    "planningCurrentKw": 20.0,
                    "capacityKw": 80.0,
                    "commandable": True,
                },
            ),
            storage_rows=(
                {
                    "dev_type": "DCGenerator",
                    "dev_name": "secondary-storage",
                    "currentKw": 0.0,
                    "soc": 0.50,
                    "socKnown": True,
                    "socMax": 0.90,
                    "chargePower": 1.0,
                },
            ),
            converter_rows=(),
        )

        plan = renewable_control._plan_renewable_storage_island_component(
            component,
            RenewableControlSettings(step_coefficient=0.03),
        )

        self.assertAlmostEqual(plan["renewableTargetKw"], 21.0)

    def test_every_dc_balance_group_is_protected_without_unrelated_actor(self):
        snapshot = renewable_snapshot()
        set_measurement_value(snapshot, "ACGenerator", "diesel-1", "P_GEN", 50.0)
        add_second_dc_balance_group(snapshot, converter_power_kw=-10.0)
        add_setpoint(snapshot, "DCGenerator", "second-group-balance")

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.20),
        )
        rows = {row["dev_name"]: row for row in plan["commandRows"]}
        balance = rows["second-group-balance"]
        converter = rows["second-group-converter"]

        self.assertGreater(balance["commandKw"], balance["currentKw"])
        self.assertLess(converter["commandKw"], converter["currentKw"])
        self.assertLessEqual(
            balance["commandKw"],
            balance["signedMaxTargetKw"] + 1e-9,
        )
        self.assertGreaterEqual(
            balance["commandKw"],
            balance["signedMinTargetKw"] - 1e-9,
        )
        self.assertLessEqual(
            converter["commandKw"],
            converter["signedMaxTargetKw"] + 1e-9,
        )
        self.assertGreaterEqual(
            converter["commandKw"],
            converter["signedMinTargetKw"] - 1e-9,
        )
        self.assertTrue(
            any(
                command["dev_name"] == "second-group-balance"
                for command in plan["commands"]
            )
        )

    def test_unsupported_grid_forming_setpoint_reports_direct_dispatch_block(self):
        snapshot = renewable_snapshot()

        plan = calculate_renewable_control_plan(snapshot)
        storage = next(
            row for row in plan["commandRows"] if row["dev_name"] == "storage-1"
        )

        self.assertFalse(storage["commandable"])
        self.assertFalse(storage["strategyCommand"])
        self.assertEqual(storage["set_type"], "")
        self.assertEqual(storage["optimizationStatus"], "optimal")
        self.assertNotEqual(storage["projectedTargetKw"], storage["currentKw"])
        self.assertFalse(
            any(
                command["dev_name"] == "storage-1"
                for command in plan["commands"]
            )
        )
        self.assertEqual(
            storage["directDispatchBlockedReason"],
            "缺少有效p_set有功遥调点",
        )
        self.assertTrue(
            any(
                row["dev_name"] == "storage-1"
                and row["reason"] == "缺少有效p_set有功遥调点"
                for row in plan["metrics"]["directDispatchBlocks"]
            )
        )


if __name__ == "__main__":
    unittest.main()
