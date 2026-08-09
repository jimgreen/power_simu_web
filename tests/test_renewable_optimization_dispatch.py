from __future__ import annotations

import unittest
from pathlib import Path

from simu.renewable_optimization import optimize_topology_islands
from simu.resource_topology import ResourceTopology


def renewable(
    name: str,
    *,
    side: str,
    component: str,
    current: float,
    capacity: float,
) -> dict:
    return {
        "technology": "wind",
        "dev_type": "ACGenerator" if side == "AC" else "DCGenerator",
        "dev_name": name,
        "connectionSide": side,
        "gridComponentId": component if side == "AC" else "",
        "dcTransferGroupId": component if side == "DC" else "",
        "online": True,
        "commandable": True,
        "planningCurrentKw": current,
        "currentKw": current,
        "capacityKw": capacity,
        "weatherAvailableKnown": False,
        "weatherAvailableKw": None,
        "set_type": "p_set",
    }


def diesel(
    name: str,
    *,
    component: str,
    current: float,
    minimum: float,
    maximum: float,
    commandable: bool = True,
    state_eligible: bool = False,
) -> dict:
    return {
        "dev_type": "ACGenerator",
        "dev_name": name,
        "connectionSide": "AC",
        "gridComponentId": component,
        "online": True,
        "commandable": commandable,
        "stateEligible": state_eligible,
        "currentKw": current,
        "minKw": minimum,
        "capacityKw": maximum,
        "set_type": "p_set",
    }


def storage(
    name: str,
    *,
    side: str,
    component: str,
    current: float,
    charge: float,
    discharge: float,
    role: str = "grid_following",
    soc: float = 0.5,
    soc_min: float = 0.2,
    soc_max: float = 0.9,
    rated_charge: float | None = None,
    rated_discharge: float | None = None,
    commandable: bool = True,
    state_eligible: bool = False,
) -> dict:
    return {
        "technology": "storage",
        "dev_type": "ACGenerator" if side == "AC" else "DCGenerator",
        "dev_name": name,
        "connectionSide": side,
        "gridComponentId": component if side == "AC" else "",
        "dcTransferGroupId": component if side == "DC" else "",
        "online": True,
        "commandable": commandable,
        "stateEligible": state_eligible,
        "currentKw": current,
        "chargePower": charge,
        "dischargePower": discharge,
        "maxChargePowerKw": charge if rated_charge is None else rated_charge,
        "maxDischargePowerKw": discharge if rated_discharge is None else rated_discharge,
        "role": role,
        "soc": soc,
        "socMin": soc_min,
        "socMax": soc_max,
        "set_type": "p_set",
    }


def converter(
    name: str,
    *,
    current: float,
    minimum: float,
    maximum: float,
    declared_type: str = "acdc-converter",
    capacity: float | None = None,
) -> dict:
    return {
        "dev_type": "DCACConverter",
        "model_block": "DCACConverter",
        "dev_name": name,
        "explicitType": declared_type,
        "online": True,
        "commandable": True,
        "currentKw": current,
        "transferCapacityKw": (
            max(abs(minimum), abs(maximum))
            if capacity is None
            else capacity
        ),
        "signedMinTargetKw": minimum,
        "signedMaxTargetKw": maximum,
        "set_type": "p_ac_set",
    }


class RenewableOptimizationDispatchTest(unittest.TestCase):
    def test_qinling_grid_converters_are_resolved_from_terminal_topology(self):
        import simu_loop
        from simu.model_semantics import grid_converter_keys

        model_path = (
            Path(__file__).resolve().parents[1]
            / "models"
            / "simulator"
            / "source"
            / "\u79e6\u5cad\u7ad9"
            / "model.e"
        )
        rows = simu_loop.EBook(model_path).data["DCACConverter"].data
        boundary_keys = grid_converter_keys(simu_loop.EBook(model_path))
        boundary_indices = {
            int(row["idx"])
            for row in rows
            if ("DCACConverter", str(row.get("name", ""))) in boundary_keys
        }

        self.assertEqual(boundary_indices, {13, 14})

    def test_internal_wind_storage_and_pv_converters_are_not_boundary_variables(self):
        from simu.renewable_control import _converter_rows

        snapshot = {
            "devices": [
                {
                    "dev_type": "DCACConverter",
                    "dev_name": f"internal-{index}",
                    "idx": index,
                    "raw": {"dev_type": "acdc-converter"},
                }
                for index in range(1, 4)
            ]
        }

        self.assertEqual(
            _converter_rows(
                snapshot,
                {},
                internal_converter_keys={
                    ("DCACConverter", f"internal-{index}")
                    for index in range(1, 4)
                },
            ),
            [],
        )

    def test_converter_rows_use_common_p_ac_terminal_balance_coefficients(self):
        from simu.renewable_control import _converter_rows

        snapshot = {
            "devices": [
                {
                    "dev_type": "DCACConverter",
                    "model_block": "DCACConverter",
                    "dev_name": "acdc-link",
                    "idx": 1,
                    "raw": {"dev_type": "acdc-converter"},
                },
                {
                    "dev_type": "DCACConverter",
                    "model_block": "DCACConverter",
                    "dev_name": "dcac-link",
                    "idx": 2,
                    "raw": {"dev_type": "dcac-converter"},
                },
            ]
        }

        rows = {
            row["dev_name"]: row
            for row in _converter_rows(
                snapshot,
                {},
                grid_converter_keys={
                    ("DCACConverter", "acdc-link"),
                    ("DCACConverter", "dcac-link"),
                },
            )
        }

        self.assertEqual(rows["acdc-link"]["converterDirection"], "AC_TO_DC")
        self.assertEqual(rows["acdc-link"]["acBalanceCoefficient"], -1.0)
        self.assertEqual(rows["acdc-link"]["dcBalanceCoefficient"], 1.0)
        self.assertEqual(rows["dcac-link"]["converterDirection"], "AC_TO_DC")
        self.assertEqual(rows["dcac-link"]["acBalanceCoefficient"], -1.0)
        self.assertEqual(rows["dcac-link"]["dcBalanceCoefficient"], 1.0)

    def test_each_hybrid_island_uses_one_aggregated_ac_and_dc_balance(self):
        topology = ResourceTopology(
            resources={},
            dc_transfer_groups={},
            converter_component_ids={
                ("DCACConverter", "\u8054\u7edc\u53d8\u6d41\u5668-1"): ("AC:1", "DC:1"),
                ("DCACConverter", "\u8054\u7edc\u53d8\u6d41\u5668-2"): ("AC:2", "DC:1"),
            },
        )
        result = optimize_topology_islands(
            topology,
            renewable_rows=[
                renewable(
                    "\u4ea4\u6d41\u98ce\u7535",
                    side="AC",
                    component="AC:1",
                    current=10.0,
                    capacity=20.0,
                ),
                renewable(
                    "\u76f4\u6d41\u5149\u4f0f",
                    side="DC",
                    component="DC:1",
                    current=10.0,
                    capacity=20.0,
                ),
            ],
            diesel_rows=[
                diesel(
                    "\u67f4\u53d1",
                    component="AC:2",
                    current=50.0,
                    minimum=20.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[],
            converter_rows=[
                converter(
                    "\u8054\u7edc\u53d8\u6d41\u5668-1",
                    current=0.0,
                    minimum=0.0,
                    maximum=0.0,
                    capacity=100.0,
                ),
                converter(
                    "\u8054\u7edc\u53d8\u6d41\u5668-2",
                    current=0.0,
                    minimum=0.0,
                    maximum=0.0,
                    capacity=100.0,
                ),
            ],
            step_coefficient=0.1,
            converter_step_ratio=0.1,
            diesel_power_protection_ratio=0.0,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertEqual(len(result.islands), 1)
        island = result.islands[0]
        self.assertEqual(island.component_ids, ("AC:1", "AC:2", "DC:1"))
        self.assertEqual(set(island.balance_delta_by_side), {"AC", "DC"})
        self.assertAlmostEqual(island.balance_delta_by_side["AC"], 0.0, places=5)
        self.assertAlmostEqual(island.balance_delta_by_side["DC"], 0.0, places=5)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "\u4ea4\u6d41\u98ce\u7535")],
            12.0,
            places=5,
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "\u67f4\u53d1")],
            48.0,
            places=5,
        )
        self.assertAlmostEqual(
            result.targets[("DCGenerator", "\u76f4\u6d41\u5149\u4f0f")],
            10.0,
            places=5,
        )

    def test_ac_dc_components_are_merged_and_use_signed_acdc_sensitivity(self):
        topology = ResourceTopology(
            resources={},
            dc_transfer_groups={},
            converter_component_ids={
                ("DCACConverter", "联络变流器"): ("AC:1", "DC:1")
            },
        )
        result = optimize_topology_islands(
            topology,
            renewable_rows=[
                renewable(
                    "直流风电",
                    side="DC",
                    component="DC:1",
                    current=10.0,
                    capacity=100.0,
                )
            ],
            diesel_rows=[
                diesel(
                    "柴发",
                    component="AC:1",
                    current=80.0,
                    minimum=20.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[],
            converter_rows=[
                converter(
                    "联络变流器",
                    current=0.0,
                    minimum=-100.0,
                    maximum=100.0,
                )
            ],
            step_coefficient=0.1,
            converter_step_ratio=0.1,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertEqual(len(result.islands), 1)
        self.assertEqual(result.islands[0].component_ids, ("AC:1", "DC:1"))
        self.assertEqual(
            set(result.islands[0].balance_delta_by_side),
            {"AC", "DC"},
        )
        self.assertAlmostEqual(
            result.islands[0].balance_delta_by_side["AC"],
            0.0,
            places=5,
        )
        self.assertAlmostEqual(
            result.islands[0].balance_delta_by_side["DC"],
            0.0,
            places=5,
        )
        self.assertAlmostEqual(
            result.targets[("DCGenerator", "直流风电")],
            20.0,
            places=5,
        )
        # DC source +10 kW requires p_ac_set -10 kW for DC-to-AC transfer.
        # The AC-side injection then replaces 10 kW of diesel generation.
        self.assertAlmostEqual(
            result.targets[("DCACConverter", "联络变流器")],
            -10.0,
            places=5,
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "柴发")],
            70.0,
            places=5,
        )
        self.assertLess(result.max_balance_residual_kw, 1e-5)

    def test_dcac_type_uses_the_same_p_ac_terminal_direction(self):
        topology = ResourceTopology(
            resources={},
            dc_transfer_groups={},
            converter_component_ids={
                ("DCACConverter", "DCAC联络变流器"): ("AC:1", "DC:1")
            },
        )
        result = optimize_topology_islands(
            topology,
            renewable_rows=[
                renewable(
                    "直流风电",
                    side="DC",
                    component="DC:1",
                    current=10.0,
                    capacity=100.0,
                )
            ],
            diesel_rows=[
                diesel(
                    "柴发",
                    component="AC:1",
                    current=80.0,
                    minimum=20.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[],
            converter_rows=[
                converter(
                    "DCAC联络变流器",
                    current=0.0,
                    minimum=-100.0,
                    maximum=100.0,
                    declared_type="dcac-converter",
                )
            ],
            step_coefficient=0.1,
            converter_step_ratio=0.1,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertAlmostEqual(
            result.targets[("DCGenerator", "直流风电")],
            20.0,
            places=5,
        )
        self.assertAlmostEqual(
            result.targets[("DCACConverter", "DCAC联络变流器")],
            -10.0,
            places=5,
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "柴发")],
            70.0,
            places=5,
        )

    def test_negative_p_ac_dc_to_ac_target_is_not_clamped_to_zero(self):
        topology = ResourceTopology(
            resources={},
            dc_transfer_groups={},
            converter_component_ids={
                ("DCACConverter", "双向联络变流器"): ("AC:1", "DC:1")
            },
        )

        result = optimize_topology_islands(
            topology,
            renewable_rows=[],
            diesel_rows=[],
            storage_rows=[],
            converter_rows=[
                converter(
                    "双向联络变流器",
                    current=-10.0,
                    minimum=-50.0,
                    maximum=50.0,
                    declared_type="dcac-converter",
                )
            ],
            step_coefficient=0.1,
            converter_step_ratio=0.1,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertAlmostEqual(
            result.targets[("DCACConverter", "双向联络变流器")],
            -10.0,
            places=5,
        )
        self.assertAlmostEqual(
            result.islands[0].balance_delta_by_side["AC"],
            0.0,
            places=5,
        )
        self.assertAlmostEqual(
            result.islands[0].balance_delta_by_side["DC"],
            0.0,
            places=5,
        )

    def test_grid_forming_diesel_without_p_set_remains_a_prediction_variable(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        result = optimize_topology_islands(
            topology,
            renewable_rows=[
                renewable(
                    "交流风电",
                    side="AC",
                    component="AC:1",
                    current=10.0,
                    capacity=20.0,
                )
            ],
            diesel_rows=[
                diesel(
                    "构网柴发",
                    component="AC:1",
                    current=80.0,
                    minimum=20.0,
                    maximum=100.0,
                    commandable=False,
                    state_eligible=True,
                )
            ],
            storage_rows=[],
            converter_rows=[],
            step_coefficient=0.1,
            diesel_power_protection_ratio=0.0,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "交流风电")],
            12.0,
            places=5,
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "构网柴发")],
            78.0,
            places=5,
        )

    def test_grid_forming_storage_without_p_set_keeps_soc_safety_projection(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        result = optimize_topology_islands(
            topology,
            renewable_rows=[],
            diesel_rows=[],
            storage_rows=[
                storage(
                    "构网储能",
                    side="DC",
                    component="DC:1",
                    current=30.0,
                    charge=50.0,
                    discharge=0.0,
                    role="balance",
                    soc=0.2,
                    soc_min=0.2,
                    soc_max=0.9,
                    commandable=False,
                    state_eligible=True,
                )
            ],
            converter_rows=[],
            step_coefficient=0.1,
            storage_step_ratio=0.1,
            soc_deadband=0.0,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertLessEqual(
            result.targets[("DCGenerator", "构网储能")],
            0.0,
        )

    def test_objective_minimizes_diesel_after_renewable_curtailment(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        result = optimize_topology_islands(
            topology,
            renewable_rows=[
                renewable(
                    "交流光伏",
                    side="AC",
                    component="AC:1",
                    current=10.0,
                    capacity=20.0,
                )
            ],
            diesel_rows=[
                diesel(
                    "柴发",
                    component="AC:1",
                    current=80.0,
                    minimum=20.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[
                storage(
                    "交流储能",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    charge=50.0,
                    discharge=50.0,
                )
            ],
            converter_rows=[],
            step_coefficient=1.0,
            storage_step_ratio=1.0,
            diesel_power_protection_ratio=0.0,
        )

        self.assertTrue(result.all_success)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "交流光伏")], 20.0, places=5
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "柴发")], 20.0, places=4
        )
        # Once diesel reaches its lower bound, storage charges with the
        # remaining island surplus while preserving zero adjustment balance.
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "交流储能")], 50.0, places=4
        )

    def test_quadratic_curtailment_term_shares_curtailment_between_units(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        result = optimize_topology_islands(
            topology,
            renewable_rows=[
                renewable(
                    "风机甲",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    capacity=10.0,
                ),
                renewable(
                    "风机乙",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    capacity=10.0,
                ),
            ],
            diesel_rows=[],
            storage_rows=[
                storage(
                    "储能",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    charge=10.0,
                    discharge=0.0,
                )
            ],
            converter_rows=[],
            step_coefficient=1.0,
            storage_step_ratio=1.0,
            curtailment_square_weight=0.1,
            optimization_ftol=1e-9,
        )

        self.assertTrue(result.all_success)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "风机甲")], 5.0, places=4
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "风机乙")], 5.0, places=4
        )
        self.assertAlmostEqual(
            result.curtailment_by_renewable[("ACGenerator", "风机甲")],
            5.0,
            places=4,
        )
        self.assertAlmostEqual(
            result.curtailment_by_renewable[("ACGenerator", "风机乙")],
            5.0,
            places=4,
        )

    def test_weather_availability_is_statistical_only_while_soc_bounds_remain_hard(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        wind = renewable(
            "风机",
            side="AC",
            component="AC:1",
            current=4.0,
            capacity=100.0,
        )
        wind["weatherAvailableKnown"] = True
        wind["weatherAvailableKw"] = 6.0
        result = optimize_topology_islands(
            topology,
            renewable_rows=[wind],
            diesel_rows=[
                diesel(
                    "柴发",
                    component="AC:1",
                    current=50.0,
                    minimum=0.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[
                storage(
                    "满电储能",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    charge=0.0,
                    discharge=0.0,
                )
            ],
            converter_rows=[],
            step_coefficient=0.5,
            diesel_power_protection_ratio=0.0,
        )

        self.assertTrue(result.all_success)
        self.assertAlmostEqual(
            result.available_by_renewable[("ACGenerator", "风机")],
            54.0,
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "风机")],
            54.0,
            places=5,
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "柴发")],
            0.0,
            places=5,
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "满电储能")],
            0.0,
            places=5,
        )

    def test_storage_normal_adjustment_is_limited_to_one_configured_step(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        result = optimize_topology_islands(
            topology,
            renewable_rows=[
                renewable(
                    "交流风机",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    capacity=100.0,
                )
            ],
            diesel_rows=[],
            storage_rows=[
                storage(
                    "交流储能",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    charge=100.0,
                    discharge=100.0,
                )
            ],
            converter_rows=[],
            step_coefficient=1.0,
            storage_step_ratio=0.10,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "交流储能")],
            -10.0,
            places=5,
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "交流风机")],
            10.0,
            places=5,
        )

    def test_storage_step_is_a_maximum_delta_not_a_fixed_increment(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        result = optimize_topology_islands(
            topology,
            renewable_rows=[
                renewable(
                    "小功率风机",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    capacity=4.0,
                )
            ],
            diesel_rows=[],
            storage_rows=[
                storage(
                    "交流储能",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    charge=100.0,
                    discharge=100.0,
                )
            ],
            converter_rows=[],
            step_coefficient=1.0,
            storage_step_ratio=0.10,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "交流储能")],
            -4.0,
            places=5,
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "小功率风机")],
            4.0,
            places=5,
        )

    def test_soc_segmented_discharge_limit_replaces_independent_low_soc_zero_rule(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        low_soc_storage = storage(
            "低SOC储能",
            side="AC",
            component="AC:1",
            current=0.0,
            charge=100.0,
            discharge=100.0,
            soc=0.15,
            soc_min=0.10,
            soc_max=0.90,
            rated_charge=100.0,
            rated_discharge=100.0,
        )
        low_soc_storage["chargeDeratingFactor"] = 1.0
        low_soc_storage["dischargeDeratingFactor"] = 0.15
        result = optimize_topology_islands(
            topology,
            renewable_rows=[],
            diesel_rows=[
                diesel(
                    "柴发",
                    component="AC:1",
                    current=50.0,
                    minimum=20.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[low_soc_storage],
            converter_rows=[],
            step_coefficient=1.0,
            storage_step_ratio=0.20,
            diesel_power_protection_ratio=0.0,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "低SOC储能")],
            15.0,
            places=4,
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "柴发")],
            35.0,
            places=4,
        )

    def test_soc_segment_with_zero_discharge_ratio_naturally_blocks_discharge(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        low_soc_storage = storage(
            "最低SOC储能",
            side="AC",
            component="AC:1",
            current=0.0,
            charge=100.0,
            discharge=100.0,
            soc=0.10,
            soc_min=0.10,
            soc_max=0.90,
            rated_charge=100.0,
            rated_discharge=100.0,
        )
        low_soc_storage["chargeDeratingFactor"] = 1.0
        low_soc_storage["dischargeDeratingFactor"] = 0.0
        result = optimize_topology_islands(
            topology,
            renewable_rows=[],
            diesel_rows=[
                diesel(
                    "柴发",
                    component="AC:1",
                    current=50.0,
                    minimum=20.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[low_soc_storage],
            converter_rows=[],
            step_coefficient=1.0,
            storage_step_ratio=0.20,
            diesel_power_protection_ratio=0.0,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "最低SOC储能")],
            0.0,
            places=5,
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "柴发")],
            50.0,
            places=5,
        )

    def test_balance_delta_replaces_infeasible_island_failure(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        result = optimize_topology_islands(
            topology,
            renewable_rows=[],
            diesel_rows=[
                diesel(
                    "越限柴发",
                    component="AC:1",
                    current=10.0,
                    minimum=20.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[],
            converter_rows=[],
            step_coefficient=0.1,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "越限柴发")],
            23.0,
            places=5,
        )
        self.assertEqual(
            result.islands[0].status,
            "optimal_with_balance_slack",
        )
        self.assertEqual(
            result.islands[0].step_override_devices,
            (),
        )
        self.assertAlmostEqual(
            result.islands[0].balance_delta_by_side["AC"],
            -13.0,
            places=4,
        )

    def test_balance_delta_is_isolated_from_a_separate_healthy_island(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        result = optimize_topology_islands(
            topology,
            renewable_rows=[
                renewable(
                    "健康风机",
                    side="AC",
                    component="AC:healthy",
                    current=10.0,
                    capacity=20.0,
                )
            ],
            diesel_rows=[
                diesel(
                    "健康柴发",
                    component="AC:healthy",
                    current=50.0,
                    minimum=20.0,
                    maximum=100.0,
                ),
                diesel(
                    "孤立越限柴发",
                    component="AC:failed",
                    current=10.0,
                    minimum=20.0,
                    maximum=100.0,
                ),
            ],
            storage_rows=[],
            converter_rows=[],
            step_coefficient=0.1,
            diesel_power_protection_ratio=0.0,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertIn(("ACGenerator", "健康风机"), result.targets)
        self.assertIn(("ACGenerator", "健康柴发"), result.targets)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "孤立越限柴发")],
            20.0,
            places=5,
        )
        corrected = next(
            island
            for island in result.islands
            if ("ACGenerator", "孤立越限柴发") in island.device_keys
        )
        healthy = next(
            island
            for island in result.islands
            if ("ACGenerator", "健康风机") in island.device_keys
        )
        self.assertEqual(corrected.status, "optimal_with_balance_slack")
        self.assertAlmostEqual(corrected.balance_delta_by_side["AC"], -10.0, places=4)
        self.assertAlmostEqual(healthy.max_balance_delta_kw, 0.0, places=4)

    def test_deadband_is_a_diesel_limit_guard_not_a_small_adjustment_freeze(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        result = optimize_topology_islands(
            topology,
            renewable_rows=[
                renewable(
                    "交流风机",
                    side="AC",
                    component="AC:1",
                    current=10.0,
                    capacity=100.0,
                )
            ],
            diesel_rows=[
                diesel(
                    "柴发",
                    component="AC:1",
                    current=50.0,
                    minimum=20.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[],
            converter_rows=[],
            step_coefficient=0.01,
            diesel_power_protection_ratio=0.1,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "交流风机")], 11.0, places=5
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "柴发")], 49.0, places=5
        )

    def test_diesel_deadband_shrinks_both_power_limits(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        result = optimize_topology_islands(
            topology,
            renewable_rows=[
                renewable(
                    "交流光伏",
                    side="AC",
                    component="AC:1",
                    current=10.0,
                    capacity=40.0,
                )
            ],
            diesel_rows=[
                diesel(
                    "柴发",
                    component="AC:1",
                    current=50.0,
                    minimum=20.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[
                storage(
                    "跟网储能",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    charge=100.0,
                    discharge=100.0,
                )
            ],
            converter_rows=[],
            step_coefficient=1.0,
            diesel_power_protection_ratio=0.1,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "柴发")], 30.0, places=4
        )

    def test_grid_forming_storage_uses_power_limit_guard_but_grid_following_does_not(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        guarded = optimize_topology_islands(
            topology,
            renewable_rows=[
                renewable(
                    "风机",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    capacity=100.0,
                )
            ],
            diesel_rows=[],
            storage_rows=[
                storage(
                    "构网储能",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    charge=50.0,
                    discharge=50.0,
                    role="balance",
                )
            ],
            converter_rows=[],
            step_coefficient=1.0,
            storage_step_ratio=1.0,
            grid_forming_storage_protection_ratio=0.1,
        )
        unguarded = optimize_topology_islands(
            topology,
            renewable_rows=[
                renewable(
                    "风机",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    capacity=100.0,
                )
            ],
            diesel_rows=[],
            storage_rows=[
                storage(
                    "跟网储能",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    charge=50.0,
                    discharge=50.0,
                )
            ],
            converter_rows=[],
            step_coefficient=1.0,
            storage_step_ratio=1.0,
            grid_forming_storage_protection_ratio=0.1,
        )

        self.assertTrue(guarded.all_success, guarded.islands)
        self.assertTrue(unguarded.all_success, unguarded.islands)
        self.assertAlmostEqual(
            guarded.targets[("ACGenerator", "构网储能")], -45.0, places=4
        )
        self.assertAlmostEqual(
            unguarded.targets[("ACGenerator", "跟网储能")], -50.0, places=4
        )

    def test_grid_forming_power_guard_does_not_force_direction_at_soc_limit(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        result = optimize_topology_islands(
            topology,
            renewable_rows=[],
            diesel_rows=[],
            storage_rows=[
                storage(
                    "构网储能",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    charge=50.0,
                    discharge=0.0,
                    role="balance",
                    soc=0.20,
                    soc_min=0.20,
                    soc_max=0.90,
                    rated_discharge=50.0,
                )
            ],
            converter_rows=[],
            step_coefficient=0.1,
            grid_forming_storage_protection_ratio=0.1,
            soc_deadband=0.05,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "构网储能")], 0.0, places=5
        )

    def test_diesel_outside_guard_is_corrected_before_normal_step_limit(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        result = optimize_topology_islands(
            topology,
            renewable_rows=[],
            diesel_rows=[
                diesel(
                    "柴发",
                    component="AC:1",
                    current=10.0,
                    minimum=20.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[
                storage(
                    "跟网储能",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    charge=50.0,
                    discharge=50.0,
                )
            ],
            converter_rows=[],
            step_coefficient=0.01,
            diesel_power_protection_ratio=0.1,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "柴发")], 30.0, places=5
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "跟网储能")], -1.5, places=5
        )
        self.assertAlmostEqual(
            result.islands[0].balance_delta_by_side["AC"],
            -18.5,
            places=5,
        )

    def test_renewable_uses_step_limit_while_converter_uses_full_physical_range(self):
        topology = ResourceTopology(
            resources={},
            dc_transfer_groups={},
            converter_component_ids={
                ("DCACConverter", "联络变流器"): ("AC:1", "DC:1")
            },
        )
        result = optimize_topology_islands(
            topology,
            renewable_rows=[
                renewable(
                    "直流风机",
                    side="DC",
                    component="DC:1",
                    current=10.0,
                    capacity=100.0,
                )
            ],
            diesel_rows=[
                diesel(
                    "柴发",
                    component="AC:1",
                    current=80.0,
                    minimum=20.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[],
            converter_rows=[
                converter(
                    "联络变流器",
                    current=0.0,
                    minimum=-100.0,
                    maximum=100.0,
                )
            ],
            step_coefficient=0.1,
            converter_step_ratio=0.05,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertAlmostEqual(
            result.targets[("DCGenerator", "直流风机")], 20.0, places=5
        )
        self.assertAlmostEqual(
            result.targets[("DCACConverter", "联络变流器")], -10.0, places=5
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "柴发")], 70.0, places=5
        )

    def test_soc_below_lower_guard_forces_at_least_one_charging_step(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        result = optimize_topology_islands(
            topology,
            renewable_rows=[],
            diesel_rows=[
                diesel(
                    "柴发",
                    component="AC:1",
                    current=50.0,
                    minimum=20.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[
                storage(
                    "低SOC储能",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    charge=50.0,
                    discharge=0.0,
                    soc=0.10,
                    soc_min=0.20,
                    soc_max=0.90,
                    rated_discharge=50.0,
                )
            ],
            converter_rows=[],
            step_coefficient=0.1,
            storage_step_ratio=0.1,
            soc_deadband=0.05,
            diesel_power_protection_ratio=0.0,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "低SOC储能")], -5.0, places=5
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "柴发")], 55.0, places=5
        )

    def test_soc_above_upper_guard_forces_at_least_one_discharge_step(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        result = optimize_topology_islands(
            topology,
            renewable_rows=[],
            diesel_rows=[
                diesel(
                    "柴发",
                    component="AC:1",
                    current=50.0,
                    minimum=20.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[
                storage(
                    "高SOC储能",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    charge=0.0,
                    discharge=50.0,
                    soc=0.96,
                    soc_min=0.20,
                    soc_max=0.90,
                    rated_charge=50.0,
                )
            ],
            converter_rows=[],
            step_coefficient=0.1,
            storage_step_ratio=0.1,
            soc_deadband=0.05,
            diesel_power_protection_ratio=0.0,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertGreaterEqual(
            result.targets[("ACGenerator", "高SOC储能")], 5.0 - 1e-6
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "柴发")]
            + result.targets[("ACGenerator", "高SOC储能")],
            50.0,
            places=5,
        )

    def test_low_soc_safety_correction_can_use_unstepped_diesel_balance(self):
        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        result = optimize_topology_islands(
            topology,
            renewable_rows=[],
            diesel_rows=[
                diesel(
                    "柴发",
                    component="AC:1",
                    current=20.0,
                    minimum=20.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[
                storage(
                    "严重过放储能",
                    side="AC",
                    component="AC:1",
                    current=50.0,
                    charge=50.0,
                    discharge=0.0,
                    soc=0.05,
                    soc_min=0.20,
                    soc_max=0.90,
                    rated_discharge=50.0,
                )
            ],
            converter_rows=[],
            step_coefficient=0.1,
            storage_step_ratio=0.1,
            soc_deadband=0.05,
            diesel_power_protection_ratio=0.0,
        )

        self.assertTrue(result.all_success, result.islands)
        island = result.islands[0]
        self.assertEqual(island.status, "optimal_safety_override")
        self.assertEqual(
            island.step_override_devices,
            (("ACGenerator", "严重过放储能"),),
        )
        self.assertLessEqual(
            result.targets[("ACGenerator", "严重过放储能")],
            -5.0 + 1e-6,
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "柴发")]
            + result.targets[("ACGenerator", "严重过放储能")],
            70.0,
            places=5,
        )
        self.assertAlmostEqual(island.balance_delta_by_side["AC"], 0.0, places=5)

    def test_soc_safety_correction_uses_unstepped_converter_and_diesel_balance(self):
        topology = ResourceTopology(
            resources={},
            dc_transfer_groups={},
            converter_component_ids={
                ("DCACConverter", "联络变流器"): ("AC:1", "DC:1")
            },
        )
        result = optimize_topology_islands(
            topology,
            renewable_rows=[],
            diesel_rows=[
                diesel(
                    "柴发",
                    component="AC:1",
                    current=80.0,
                    minimum=20.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[
                storage(
                    "严重过充储能",
                    side="DC",
                    component="DC:1",
                    current=-50.0,
                    charge=0.0,
                    discharge=50.0,
                    soc=1.10,
                    soc_min=0.20,
                    soc_max=0.90,
                    rated_charge=50.0,
                )
            ],
            converter_rows=[
                converter(
                    "联络变流器",
                    current=0.0,
                    minimum=-100.0,
                    maximum=100.0,
                )
            ],
            step_coefficient=0.1,
            converter_step_ratio=0.05,
            storage_step_ratio=0.1,
            soc_deadband=0.05,
            diesel_power_protection_ratio=0.0,
            grid_forming_storage_protection_ratio=0.0,
        )

        self.assertTrue(result.all_success, result.islands)
        island = result.islands[0]
        self.assertTrue(island.step_override_applied)
        self.assertEqual(island.status, "optimal_safety_override")
        self.assertEqual(
            set(island.step_override_devices),
            {
                ("DCGenerator", "严重过充储能"),
            },
        )
        self.assertGreaterEqual(
            result.targets[("DCGenerator", "严重过充储能")], 5.0 - 1e-6
        )
        self.assertLessEqual(
            result.targets[("DCACConverter", "联络变流器")],
            -55.0 + 1e-6,
        )
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "柴发")],
            25.0,
            places=5,
        )
        self.assertAlmostEqual(island.balance_delta_by_side["DC"], 0.0, places=5)

    def test_balance_delta_keeps_island_solvable_when_soc_correction_has_no_partner(self):
        from simu.renewable_control import (
            _compact_decision_log_detail,
            _decision_log_level,
            _optimization_balance_delta_warnings,
        )

        topology = ResourceTopology(resources={}, dc_transfer_groups={})
        cases = (
            {
                "name": "孤立低SOC储能",
                "current": 50.0,
                "charge": 50.0,
                "discharge": 0.0,
                "soc": 0.05,
                "rated_charge": None,
                "rated_discharge": 50.0,
                "relation": "charge",
                "expected_residual": -55.0,
            },
            {
                "name": "孤立高SOC储能",
                "current": -50.0,
                "charge": 0.0,
                "discharge": 50.0,
                "soc": 1.10,
                "rated_charge": 50.0,
                "rated_discharge": None,
                "relation": "discharge",
                "expected_residual": 55.0,
            },
        )
        for case in cases:
            with self.subTest(case=case["relation"]):
                result = optimize_topology_islands(
                    topology,
                    renewable_rows=[],
                    diesel_rows=[],
                    storage_rows=[
                        storage(
                            case["name"],
                            side="DC",
                            component="DC:1",
                            current=case["current"],
                            charge=case["charge"],
                            discharge=case["discharge"],
                            soc=case["soc"],
                            soc_min=0.20,
                            soc_max=0.90,
                            rated_charge=case["rated_charge"],
                            rated_discharge=case["rated_discharge"],
                        )
                    ],
                    converter_rows=[],
                    step_coefficient=0.1,
                    storage_step_ratio=0.1,
                    soc_deadband=0.05,
                    grid_forming_storage_protection_ratio=0.0,
                )

                self.assertTrue(result.all_success, result.islands)
                island = result.islands[0]
                target = result.targets[("DCGenerator", case["name"])]
                self.assertEqual(
                    island.status,
                    "optimal_safety_override_with_balance_slack",
                )
                self.assertEqual(
                    island.step_override_devices,
                    (("DCGenerator", case["name"]),),
                )
                if case["relation"] == "charge":
                    self.assertLessEqual(target, -5.0 + 1e-6)
                else:
                    self.assertGreaterEqual(target, 5.0 - 1e-6)
                self.assertAlmostEqual(
                    island.balance_residual_by_component["DC"],
                    case["expected_residual"],
                    places=4,
                )
                self.assertAlmostEqual(
                    island.balance_delta_by_side["DC"],
                    -case["expected_residual"],
                    places=4,
                )
                self.assertGreaterEqual(
                    island.balance_delta_square_weight,
                    10_000.0,
                )
                self.assertAlmostEqual(
                    result.max_balance_residual_kw,
                    abs(case["expected_residual"]),
                    places=4,
                )
                warnings = _optimization_balance_delta_warnings(result)
                self.assertEqual(len(warnings), 1)
                self.assertIn("功率平衡松弛量较大", warnings[0])
                self.assertIn("delta_ac=0.000 kW", warnings[0])
                self.assertIn("delta_dc=", warnings[0])
                self.assertEqual(
                    _decision_log_level(
                        {
                            "dataQuality": {"status": "ok"},
                            "warnings": warnings,
                        }
                    ),
                    "warn",
                )
                log_detail = _compact_decision_log_detail(
                    {
                        "dataQuality": {"status": "ok", "source": "remote"},
                        "warnings": warnings,
                    }
                )
                self.assertTrue(
                    any("功率平衡松弛量较大" in item for item in log_detail)
                )

    def test_dc_balance_has_priority_when_converter_side_strategies_conflict(self):
        topology = ResourceTopology(
            resources={},
            dc_transfer_groups={},
            converter_component_ids={
                ("DCACConverter", "联络变流器"): ("AC:1", "DC:1")
            },
        )

        result = optimize_topology_islands(
            topology,
            renewable_rows=[],
            diesel_rows=[],
            storage_rows=[
                storage(
                    "交流低SOC储能",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    charge=50.0,
                    discharge=50.0,
                    soc=0.05,
                    soc_min=0.20,
                    soc_max=0.90,
                ),
                storage(
                    "直流低SOC储能",
                    side="DC",
                    component="DC:1",
                    current=0.0,
                    charge=50.0,
                    discharge=50.0,
                    soc=0.05,
                    soc_min=0.20,
                    soc_max=0.90,
                ),
            ],
            converter_rows=[
                converter(
                    "联络变流器",
                    current=0.0,
                    minimum=-100.0,
                    maximum=100.0,
                )
            ],
            step_coefficient=0.1,
            storage_step_ratio=0.1,
            soc_deadband=0.05,
            grid_forming_storage_protection_ratio=0.0,
        )

        self.assertTrue(result.all_success, result.islands)
        island = result.islands[0]
        self.assertAlmostEqual(
            result.targets[("DCACConverter", "联络变流器")],
            5.0,
            places=5,
        )
        self.assertAlmostEqual(island.balance_delta_by_side["DC"], 0.0, places=5)
        self.assertAlmostEqual(island.balance_delta_by_side["AC"], 10.0, places=5)

    def test_dc_priority_does_not_bias_ac_dc_renewable_headroom_competition(self):
        topology = ResourceTopology(
            resources={},
            dc_transfer_groups={},
            converter_component_ids={
                ("DCACConverter", "联络变流器"): ("AC:1", "DC:1")
            },
        )

        result = optimize_topology_islands(
            topology,
            renewable_rows=[
                renewable(
                    "交流新能源",
                    side="AC",
                    component="AC:1",
                    current=0.0,
                    capacity=100.0,
                ),
                renewable(
                    "直流新能源",
                    side="DC",
                    component="DC:1",
                    current=0.0,
                    capacity=100.0,
                ),
            ],
            diesel_rows=[
                diesel(
                    "柴发",
                    component="AC:1",
                    current=100.0,
                    minimum=0.0,
                    maximum=100.0,
                )
            ],
            storage_rows=[],
            converter_rows=[
                converter(
                    "联络变流器",
                    current=0.0,
                    minimum=-100.0,
                    maximum=100.0,
                )
            ],
            step_coefficient=1.0,
            diesel_power_protection_ratio=0.0,
            curtailment_square_weight=1.0,
        )

        self.assertTrue(result.all_success, result.islands)
        self.assertAlmostEqual(
            result.targets[("ACGenerator", "交流新能源")],
            50.0,
            places=4,
        )
        self.assertAlmostEqual(
            result.targets[("DCGenerator", "直流新能源")],
            50.0,
            places=4,
        )
        self.assertAlmostEqual(result.islands[0].max_balance_delta_kw, 0.0, places=5)


if __name__ == "__main__":
    unittest.main()
