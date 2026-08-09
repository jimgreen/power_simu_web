from __future__ import annotations

import unittest
from pathlib import Path


class DeviceRoleClassificationTest(unittest.TestCase):
    def test_converter_power_helpers_use_the_explicit_canonical_convention(self):
        from simu.device_roles import (
            AC_TO_DC,
            converter_balance_coefficients,
            converter_power_in_ac_terminal_convention,
            converter_power_in_dc_to_ac_convention,
            converter_setpoint_from_p_ac_convention,
        )

        for direction in (AC_TO_DC,):
            self.assertEqual(
                converter_balance_coefficients(direction),
                (-1.0, 1.0),
            )
            self.assertEqual(
                converter_power_in_dc_to_ac_convention(12.5, direction, "P_AC"),
                -12.5,
            )
            self.assertEqual(
                converter_power_in_dc_to_ac_convention(-12.5, direction, "P_AC"),
                12.5,
            )
            self.assertEqual(
                converter_power_in_dc_to_ac_convention(12.5, direction, "P_DC"),
                12.5,
            )
            self.assertEqual(
                converter_power_in_dc_to_ac_convention(-12.5, direction, "P_DC"),
                -12.5,
            )
            self.assertEqual(
                converter_power_in_ac_terminal_convention(12.5, direction, "P_AC"),
                12.5,
            )
            self.assertEqual(
                converter_power_in_ac_terminal_convention(12.5, direction, "P_DC"),
                -12.5,
            )
            self.assertEqual(
                converter_power_in_ac_terminal_convention(-12.5, direction, "P_DC"),
                12.5,
            )
            self.assertEqual(
                converter_setpoint_from_p_ac_convention(-12.5, direction, "p_ac_set"),
                -12.5,
            )
            self.assertEqual(
                converter_setpoint_from_p_ac_convention(-12.5, direction, "p_dc_set"),
                12.5,
            )
            self.assertEqual(
                converter_setpoint_from_p_ac_convention(12.5, direction, "p_dc_set"),
                -12.5,
            )

    def test_converter_dispatch_role_comes_from_terminal_topology(self):
        from simu.model_semantics import grid_converter_keys

        model = {
            "ACRealBs": [{"idx": 1, "name": "ac-anchor", "node": 1}],
            "DCRealBs": [{"idx": 1, "name": "dc-anchor", "node": 2}],
            "DCACConverter": [
                {
                    "idx": 1,
                    "name": "opaque-boundary",
                    "dev_type": "wind-looking-text",
                    "ac_node": 1,
                    "dc_node": 2,
                },
                {
                    "idx": 2,
                    "name": "opaque-internal",
                    "dev_type": "grid-looking-text",
                    "ac_node": 3,
                    "dc_node": 4,
                },
            ],
        }

        self.assertEqual(
            grid_converter_keys(model),
            {("DCACConverter", "opaque-boundary")},
        )

    def test_converter_dispatch_encodes_the_selected_terminal_setpoint(self):
        from simu.renewable_control import _dispatch_setpoint_value

        base_row = {
            "dev_type": "DCACConverter",
            "converterDirection": "AC_TO_DC",
            "commandKw": -12.5,
        }

        self.assertEqual(
            _dispatch_setpoint_value({**base_row, "set_type": "p_ac_set"}),
            -12.5,
        )
        self.assertEqual(
            _dispatch_setpoint_value({**base_row, "set_type": "p_dc_set"}),
            12.5,
        )

        reverse_row = {**base_row, "commandKw": 12.5}
        self.assertEqual(
            _dispatch_setpoint_value({**reverse_row, "set_type": "p_ac_set"}),
            12.5,
        )
        self.assertEqual(
            _dispatch_setpoint_value({**reverse_row, "set_type": "p_dc_set"}),
            -12.5,
        )

    def test_source_model_roles_are_resolved_from_relations_and_topology(self):
        import simu_loop
        from simu.model_semantics import grid_converter_keys, structured_resources

        project_root = Path(__file__).resolve().parents[1]
        model_specs = (
            (
                "models/simulator/source/秦岭站/model.e",
                {13, 14},
                {27, 28, 29, 30},
            ),
            (
                "models/trainee/source/新模型/model.e",
                {13, 14},
                {27, 28, 29, 30},
            ),
            (
                "models/trainee/source/默认模型/model.e",
                {11, 12},
                set(),
            ),
            (
                "models/trainee/source/默认模型2/model.e",
                {11, 12},
                set(),
            ),
        )
        for relative_path, grid_indices, diesel_indices in model_specs:
            with self.subTest(model=relative_path):
                model = simu_loop.EBook(project_root / relative_path)
                rows = model.data[
                    "DCACConverter"
                ].data
                by_index = {int(row["idx"]): row for row in rows}
                boundary_keys = grid_converter_keys(model)
                boundary_indices = {
                    index
                    for index, row in by_index.items()
                    if ("DCACConverter", str(row.get("name", ""))) in boundary_keys
                }

                for index in range(1, 11):
                    row = by_index[index]
                    self.assertEqual(float(row["ac_p_min"]), -10.0)
                    self.assertEqual(float(row["ac_p_max"]), 10.0)
                    self.assertEqual(float(row["dc_p_min"]), -10.0)
                    self.assertEqual(float(row["dc_p_max"]), 10.0)

                self.assertEqual(boundary_indices, grid_indices)
                for index in grid_indices:
                    row = by_index[index]
                    self.assertEqual(float(row["ac_p_min"]), -300.0)
                    self.assertEqual(float(row["ac_p_max"]), 300.0)
                    self.assertEqual(float(row["dc_p_min"]), -300.0)
                    self.assertEqual(float(row["dc_p_max"]), 300.0)

                diesel_resources = {
                    int(resource.source_index): resource
                    for resource in structured_resources(model)
                    if resource.technology == "diesel"
                    and resource.source_block == "ACGenerator"
                }
                self.assertEqual(set(diesel_resources), diesel_indices)
                for resource in diesel_resources.values():
                    row = resource.source
                    self.assertEqual(float(row["p_min"]), 0.0)
                    self.assertEqual(float(row["p_max"]), 300.0)

    def test_converter_control_mode_and_setpoint_field_follow_the_active_terminal(self):
        from simu.device_roles import (
            converter_active_power_setpoint_field,
            converter_control_mode,
            converter_power_setpoint_fields,
        )

        ac_control = {
            "ac_control_type": "PQ",
            "dc_control_type": "NONE",
            "p_ac_set": -10,
            "p_dc_set": 10,
        }
        dc_control = {
            "ac_control_type": "NONE",
            "dc_control_type": "P",
            "p_ac_set": -10,
            "p_dc_set": 10,
        }

        self.assertEqual(converter_control_mode(ac_control), "PQ")
        self.assertEqual(
            converter_active_power_setpoint_field(ac_control),
            "p_ac_set",
        )
        self.assertEqual(converter_power_setpoint_fields(ac_control)[0], "p_ac_set")
        self.assertEqual(converter_control_mode(dc_control), "P")
        self.assertEqual(
            converter_active_power_setpoint_field(dc_control),
            "p_dc_set",
        )
        self.assertEqual(converter_power_setpoint_fields(dc_control)[0], "p_dc_set")
        dual_control = {"ac_control_type": "PQ", "dc_control_type": "P"}
        self.assertEqual(converter_control_mode(dual_control), "P")
        self.assertEqual(
            converter_active_power_setpoint_field(dual_control),
            "p_dc_set",
        )
        self.assertEqual(
            converter_power_setpoint_fields(dual_control)[0],
            "p_dc_set",
        )
        explicit_dc_none = {
            "ac_control_type": "NONE",
            "dc_control_type": "NONE",
            "p_ac_set": -10,
            "p_dc_set": 10,
        }
        self.assertEqual(converter_control_mode(explicit_dc_none), "P")
        self.assertEqual(
            converter_active_power_setpoint_field(explicit_dc_none),
            "p_dc_set",
        )
        self.assertEqual(
            converter_power_setpoint_fields(explicit_dc_none)[0],
            "p_dc_set",
        )
        legacy_only = {"control_type": "DCP", "p_ac_set": -10, "p_dc_set": 10}
        self.assertEqual(converter_control_mode(legacy_only), "")
        self.assertEqual(converter_active_power_setpoint_field(legacy_only), "")
        self.assertNotIn("p_ac_set", converter_power_setpoint_fields(dc_control))

    def test_name_and_device_type_text_do_not_create_resource_roles(self):
        from simu.model_semantics import structured_resources

        model = {
            "ACGenerator": [
                {"idx": 1, "name": "diesel-looking-name", "dev_type": "ac-wind-source"},
            ],
            "DCGenerator": [
                {"idx": 1, "name": "storage-looking-name", "dev_type": "dc-pv-source"},
            ],
        }

        self.assertEqual(structured_resources(model), ())

    def test_embedded_diesel_capability_ignores_misleading_names(self):
        import simu_loop

        model_book = simu_loop.EBook(
            {
                "ACGenerator": [
                    {
                        "idx": 1,
                        "name": "diesel-looking-name",
                        "dev_type": "ac-source",
                        "p_set": 100,
                        "rated_capacity": 300,
                        "run_stat": 1,
                    },
                    {
                        "idx": 2,
                        "name": "unit-neutral",
                        "dev_type": "ac-diesel-source",
                        "p_set": 80,
                        "rated_capacity": 200,
                        "run_stat": 1,
                    },
                ],
                "ACDieselGen": [
                    {"idx": 1, "idx_acgenerator": 2, "rated_power": 200},
                ],
            }
        )

        rows = simu_loop._embedded_device_define_book(model_book).data["diesel_generator"].data

        self.assertEqual([row["name"] for row in rows], ["unit-neutral"])

    def test_renewable_controller_diesel_detection_uses_parameter_reference(self):
        from simu.renewable_control import _diesel_rows

        snapshot = {
            "devices": [
                {
                    "dev_type": "opaque-source-a",
                    "model_block": "ACGenerator",
                    "dev_name": "diesel-looking-name",
                    "idx": 1,
                    "run_stat": 1,
                    "raw": {
                        "idx": 1,
                        "dev_type": "ac-source",
                        "p_set": 100,
                        "rated_capacity": 300,
                        "run_stat": 1,
                    },
                },
                {
                    "dev_type": "opaque-source-b",
                    "model_block": "ACGenerator",
                    "dev_name": "unit-neutral",
                    "idx": 2,
                    "run_stat": 1,
                    "raw": {
                        "idx": 2,
                        "dev_type": "ac-diesel-source",
                        "p_set": 80,
                        "rated_capacity": 200,
                        "run_stat": 1,
                    },
                },
            ],
            "device_parameters": {
                "ACDieselGen": [
                    {"idx": 1, "idx_acgenerator": 2, "rated_power": 200},
                ],
            },
            "control_points": [],
        }

        rows = _diesel_rows(snapshot, {})

        self.assertEqual([row["dev_name"] for row in rows], ["unit-neutral"])


if __name__ == "__main__":
    unittest.main()
