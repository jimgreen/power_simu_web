from __future__ import annotations

import unittest
from pathlib import Path

import simu.server as server_module
import simu_loop
from simu.renewable_control import _diesel_rows, _measurement_index, calculate_renewable_control_plan
from tests.test_trainee_renewable_backend_control import renewable_snapshot


class StructuredRuntimeSemanticsTest(unittest.TestCase):
    def test_frontends_fail_closed_instead_of_inferring_model_block_from_device_id(self):
        root = Path(__file__).resolve().parents[1]
        for relative in ("simu/web/simulator/app.js", "simu/web/trainee/app.js"):
            script = (root / relative).read_text(encoding="utf-8")
            with self.subTest(script=relative):
                self.assertNotIn('layerType || devId.split("-", 1)[0]', script)
                self.assertNotIn('devType: key.includes("-") ? key.split("-", 1)[0] : ""', script)

    def test_trainee_semantic_filters_use_model_metadata_not_protocol_type(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "simu/web/trainee/app.js").read_text(encoding="utf-8")

        self.assertIn("deviceModelBlock(dev) === devType", script)
        self.assertIn('deviceFamily(dev) === "load"', script)
        self.assertNotIn('.filter((dev) => deviceType(dev) === "ESS")', script)

    def test_storage_runtime_reference_accepts_parameter_index_without_type_semantics(self):
        from simu.model_semantics import resolve_resource_reference, structured_resources

        model_book = simu_loop.EBook(
            {
                "DCGenerator": [
                    {"idx": 7, "name": "opaque-source", "dev_type": "arbitrary", "run_stat": 1}
                ],
                "DCStorageGen": [
                    {"idx": 3, "idx_dcgenerator": 7, "energy_capacity": 100}
                ],
            }
        )
        resources = structured_resources(model_book)

        self.assertEqual(
            resolve_resource_reference(
                resources,
                {"dev_type": "ESS", "idx": 3, "name": "protocol-storage"},
            ),
            ("DCGenerator", "opaque-source"),
        )

    def test_storage_runtime_reference_rejects_ambiguous_parameter_index(self):
        from simu.model_semantics import resolve_resource_reference, structured_resources

        model_book = simu_loop.EBook(
            {
                "ACGenerator": [{"idx": 7, "name": "source-a", "run_stat": 1}],
                "DCGenerator": [{"idx": 9, "name": "source-b", "run_stat": 1}],
                "ACStorageGen": [{"idx": 3, "idx_acgenerator": 7}],
                "DCStorageGen": [{"idx": 3, "idx_dcgenerator": 9}],
            }
        )
        resources = structured_resources(model_book)

        self.assertIsNone(
            resolve_resource_reference(
                resources,
                {"dev_type": "ESS", "idx": 3, "name": "ambiguous-protocol-storage"},
            )
        )

    def test_soc_values_keep_same_named_ac_and_dc_storage_separate(self):
        model_book = simu_loop.EBook(
            {
                "ACGenerator": [{"idx": 1, "name": "shared-storage", "run_stat": 1}],
                "DCGenerator": [{"idx": 1, "name": "shared-storage", "run_stat": 1}],
                "ACStorageGen": [{"idx": 1, "idx_acgenerator": 1}],
                "DCStorageGen": [{"idx": 2, "idx_dcgenerator": 1}],
            }
        )
        stat_book = simu_loop.EBook(
            {
                "StorageSoc": [
                    {"dev_type": "ACGenerator", "idx": 1, "name": "shared-storage", "soc_curr": 0.3},
                    {"dev_type": "DCGenerator", "idx": 1, "name": "shared-storage", "soc_curr": 0.7},
                ]
            }
        )

        values = simu_loop._storage_soc_values_from_book(stat_book, model_book)

        self.assertEqual(values[("ACGenerator", "shared-storage")], 0.3)
        self.assertEqual(values[("DCGenerator", "shared-storage")], 0.7)

    def test_structured_resource_roles_come_from_reference_blocks(self):
        from simu.model_semantics import structured_resources

        model_book = simu_loop.EBook(
            {
                "ACGenerator": [
                    {
                        "idx": 7,
                        "name": "opaque-unit-a",
                        "dev_type": "misleading-storage-text",
                        "p_set": 0,
                        "run_stat": 1,
                    }
                ],
                "ACWindGen": [
                    {
                        "idx": 3,
                        "idx_acgenerator": 7,
                        "rated_wind_speed": 15,
                    }
                ],
            }
        )

        resources = structured_resources(model_book)

        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0].technology, "wind")
        self.assertEqual(resources[0].source_block, "ACGenerator")
        self.assertEqual(resources[0].source_index, "7")
        self.assertEqual(resources[0].source_name, "opaque-unit-a")

    def test_unreferenced_generator_is_not_classified_from_dev_type_or_name(self):
        model_book = simu_loop.EBook(
            {
                "ACGenerator": [
                    {
                        "idx": 1,
                        "name": "wind-storage-diesel-looking-name",
                        "dev_type": "ac-wind-source",
                        "p_set": 12,
                        "run_stat": 1,
                    }
                ]
            }
        )
        capability_book = simu_loop.EBook(
            {
                "wind_generator": [
                    {
                        "id": 1,
                        "name": "wind-storage-diesel-looking-name",
                        "dev_type": "ACGenerator",
                        "rated_power": 100,
                    }
                ]
            }
        )

        targets = simu_loop._renewable_target_rows(
            model_book,
            capability_book,
            "wind_generator",
            ("ACGenerator", "DCGenerator"),
        )

        self.assertEqual(targets, [])

    def test_structured_relation_row_drives_capability_without_name_matching(self):
        model_book = simu_loop.EBook(
            {
                "ACGenerator": [
                    {
                        "idx": 9,
                        "name": "opaque-unit-b",
                        "dev_type": "arbitrary-text",
                        "p_set": 0,
                        "p_max": 80,
                        "run_stat": 1,
                    }
                ],
                "ACWindGen": [
                    {
                        "idx": 4,
                        "idx_acgenerator": 9,
                        "rated_wind_speed": 13,
                        "cut_in_wind_speed": 4,
                        "cut_out_wind_speed": 25,
                    }
                ],
            }
        )
        misleading_capability_book = simu_loop.EBook(
            {
                "wind_generator": [
                    {
                        "id": 99,
                        "name": "different-name",
                        "dev_type": "DCGenerator",
                        "rated_power": 1,
                    }
                ]
            }
        )

        targets = simu_loop._renewable_target_rows(
            model_book,
            misleading_capability_book,
            "wind_generator",
            ("ACGenerator", "DCGenerator"),
        )

        self.assertEqual(len(targets), 1)
        _block, source, capability, _position = targets[0]
        self.assertEqual(source["idx"], 9)
        self.assertEqual(capability["idx_acgenerator"], 9)
        self.assertEqual(capability["rated_wind_speed"], 13)

    def test_storage_requires_structured_reference_instead_of_dev_type_or_suffix(self):
        model_book = simu_loop.EBook(
            {
                "DCGenerator": [
                    {
                        "idx": 1,
                        "name": "battery-looking_vsrc",
                        "dev_type": "dc-storage",
                        "p_set": 0,
                        "run_stat": 1,
                    }
                ]
            }
        )
        capability_book = simu_loop.EBook(
            {
                "estorage": [
                    {
                        "id": 1,
                        "name": "battery-looking",
                        "dev_type": "DCGenerator",
                        "source_name": "battery-looking_vsrc",
                        "emva": 100,
                    }
                ]
            }
        )

        self.assertEqual(
            simu_loop._storage_target_rows(model_book, capability_book),
            [],
        )
        self.assertEqual(server_module._storage_source_rows(model_book), [])

    def test_diesel_requires_index_relation_instead_of_legacy_name_or_dev_type(self):
        snapshot = renewable_snapshot()
        snapshot["device_parameters"].pop("ACDieselGen", None)
        model = snapshot.get("definitions", {}).get("model", {})
        if isinstance(model, dict):
            model.pop("ACDieselGen", None)
        diesel = next(
            device
            for device in snapshot["devices"]
            if device.get("dev_type") == "ACGenerator"
            and device.get("dev_name") == "diesel-1"
        )
        diesel["raw"]["dev_type"] = "ac-diesel-source"

        rows = _diesel_rows(snapshot, _measurement_index(snapshot))

        self.assertEqual(rows, [])

    def test_grid_converter_role_is_topological_not_declared_in_dev_type(self):
        snapshot = renewable_snapshot()
        converter = next(
            device
            for device in snapshot["devices"]
            if device.get("dev_type") == "DCACConverter"
            and device.get("dev_name") == "grid-converter-1"
        )
        converter["raw"]["dev_type"] = "wind-acdc-converter"
        converter_model = next(
            row
            for row in snapshot["definitions"]["model"]["DCACConverter"]["rows"]
            if row.get("name") == "grid-converter-1"
        )
        converter_model["dev_type"] = "storage-dcac-converter"

        plan = calculate_renewable_control_plan(snapshot)

        self.assertTrue(
            any(
                row.get("dev_type") == "DCACConverter"
                and row.get("dev_name") == "grid-converter-1"
                for row in plan["commandRows"]
            )
        )

    def test_command_expansion_preserves_opaque_protocol_device_type(self):
        from simu.service import PolarMicrogridSimulator

        rows = PolarMicrogridSimulator._expand_set_values(
            None,
            [
                {
                    "dev_type": "Storage",
                    "dev_name": "opaque-device",
                    "p_set": 12.5,
                }
            ],
        )

        self.assertEqual(rows[0]["dev_type"], "Storage")
        self.assertEqual(rows[0]["dev_name"], "opaque-device")

if __name__ == "__main__":
    unittest.main()
