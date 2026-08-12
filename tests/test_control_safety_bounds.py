from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import simu_loop
from simu.definition_editing import render_ebook_aligned


class ControlSafetyBoundsTest(unittest.TestCase):
    def _make_service(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)
        return service, runtime

    @staticmethod
    def _add_fields(service, block_name, dev_name, fields):
        current = service.definition_snapshot
        model_book = simu_loop._clone_ebook(current.model_book)
        block = model_book.data[block_name]
        row = next(item for item in block.data if item.get("name") == dev_name)
        for field, value in fields.items():
            if field not in block.header_list:
                block.header_list.append(field)
            row[field] = str(value)
        service._publish_definition_snapshot(
            current.__class__(
                revision=current.revision,
                model_book=model_book,
                dev_define_book=current.dev_define_book,
                measurement_before=current.measurement_before,
                measurement_rows=current.measurement_rows,
                measurement_after=current.measurement_after,
                measurement_median_deviations=current.measurement_median_deviations,
            )
        )

    @staticmethod
    def _set_value(service, dev_type, dev_name, set_type):
        key = f"{dev_type}.{dev_name}.{set_type}"
        return str(service.latest_control_values()["values"].get(key, ""))

    def test_power_command_above_or_below_limits_is_rejected_without_side_effects(self):
        service, runtime = self._make_service()
        self._add_fields(
            service,
            "ACGenerator",
            "diesel_300kw",
            {"p_min": 30, "p_max": 300},
        )
        history_before = list(service.command_history)
        stat_before = render_ebook_aligned(service.runtime_stat_book)

        for unsafe_value in (29.9, 300.1):
            with self.subTest(unsafe_value=unsafe_value), self.assertRaisesRegex(
                ValueError,
                r"遥调安全校验失败.*ACGenerator/diesel_300kw.*p_set.*未下发",
            ):
                service.apply_student_commands(
                    {
                        "set_values": [
                            {
                                "dev_type": "ACGenerator",
                                "dev_name": "diesel_300kw",
                                "set_type": "p_set",
                                "set_value": unsafe_value,
                            }
                        ]
                    },
                    source="trainee-ui",
                )

        self.assertEqual(service.command_history, history_before)
        self.assertEqual(self._set_value(service, "ACGenerator", "diesel_300kw", "p_set"), "80")
        self.assertEqual(render_ebook_aligned(service.runtime_stat_book), stat_before)
        self.assertFalse((runtime / "commands.json").exists())

    def test_values_equal_to_power_limits_are_allowed(self):
        service, _runtime = self._make_service()
        self._add_fields(
            service,
            "ACGenerator",
            "diesel_300kw",
            {"p_min": 30, "p_max": 300},
        )

        for value in (30, 300):
            with self.subTest(value=value):
                result = service.apply_student_commands(
                    {
                        "set_values": [
                            {
                                "dev_type": "ACGenerator",
                                "dev_name": "diesel_300kw",
                                "set_type": "p_set",
                                "set_value": value,
                            }
                        ]
                    },
                    source="trainee-ui",
                )
                self.assertEqual(result["set_values"], 1)
                self.assertEqual(
                    self._set_value(service, "ACGenerator", "diesel_300kw", "p_set"),
                    str(value),
                )

    def test_storage_alias_uses_capability_charge_and_discharge_limits(self):
        service, runtime = self._make_service()
        history_before = list(service.command_history)
        stat_before = render_ebook_aligned(service.runtime_stat_book)

        for unsafe_value in (-40.1, 40.1):
            with self.subTest(unsafe_value=unsafe_value), self.assertRaisesRegex(
                ValueError,
                r"ESS/ess01.*p_set.*p_(min|max)",
            ):
                service.apply_student_commands(
                    {
                        "set_values": [
                            {
                                "dev_type": "ESS",
                                "dev_name": "ess01",
                                "set_type": "p_set",
                                "set_value": unsafe_value,
                            }
                        ]
                    },
                    source="trainee-ui",
                )

        self.assertEqual(service.command_history, history_before)
        self.assertEqual(render_ebook_aligned(service.runtime_stat_book), stat_before)
        self.assertFalse((runtime / "commands.json").exists())

    def test_invalid_runtime_control_binary_is_rejected_atomically(self):
        service, runtime = self._make_service()
        history_before = list(service.command_history)
        stat_before = render_ebook_aligned(service.runtime_stat_book)

        with self.assertRaisesRegex(ValueError, r"遥控安全校验失败.*run_stat.*0 或 1"):
            service.apply_student_commands(
                {
                    "run_status": [
                        {
                            "dev_type": "ACGenerator",
                            "dev_name": "diesel_300kw",
                            "run_stat": 2,
                        }
                    ]
                },
                source="trainee-ui",
            )

        self.assertEqual(service.command_history, history_before)
        self.assertEqual(render_ebook_aligned(service.runtime_stat_book), stat_before)
        self.assertFalse((runtime / "commands.json").exists())

    def test_mixed_safe_and_unsafe_command_batch_is_rejected_atomically(self):
        service, runtime = self._make_service()
        self._add_fields(
            service,
            "ACGenerator",
            "diesel_300kw",
            {"p_min": 30, "p_max": 300},
        )
        history_before = list(service.command_history)
        stat_before = render_ebook_aligned(service.runtime_stat_book)

        with self.assertRaisesRegex(ValueError, "本批指令未下发"):
            service.apply_student_commands(
                {
                    "set_values": [
                        {
                            "dev_type": "ACGenerator",
                            "dev_name": "diesel_300kw",
                            "set_type": "p_set",
                            "set_value": 100,
                        },
                        {
                            "dev_type": "ACGenerator",
                            "dev_name": "diesel_300kw",
                            "set_type": "p_set",
                            "set_value": 301,
                        },
                    ]
                },
                source="trainee-ui",
            )

        self.assertEqual(service.command_history, history_before)
        self.assertEqual(self._set_value(service, "ACGenerator", "diesel_300kw", "p_set"), "80")
        self.assertEqual(render_ebook_aligned(service.runtime_stat_book), stat_before)

    def test_voltage_flow_pressure_and_converter_terminal_limits_are_enforced(self):
        service, _runtime = self._make_service()
        self._add_fields(
            service,
            "ACGenerator",
            "diesel_300kw",
            {"v_min": 304, "v_max": 456},
        )
        self._add_fields(
            service,
            "DCACConverter",
            "grid_inv_acp",
            {
                "ac_p_min": -50,
                "ac_p_max": 50,
                "dc_p_min": -50,
                "dc_p_max": 50,
            },
        )
        service.control_book.data["SetValue"].data.append(
            {
                "dev_type": "DCACConverter",
                "dev_name": "grid_inv_acp",
                "set_type": "p_ac_set",
                "set_value": "-45",
            }
        )

        cases = (
            ("ACGenerator", "diesel_300kw", "v_set", 500, "v_max"),
            ("DCACConverter", "grid_inv_acp", "p_ac_set", -51, "ac_p_min"),
            ("DCACConverter", "grid_inv_acp", "p_dc_set", 51, "dc_p_max"),
        )
        for dev_type, dev_name, set_type, value, bound in cases:
            with self.subTest(set_type=set_type), self.assertRaisesRegex(
                ValueError,
                rf"{set_type}.*{bound}",
            ):
                service.apply_student_commands(
                    {
                        "set_values": [
                            {
                                "dev_type": dev_type,
                                "dev_name": dev_name,
                                "set_type": set_type,
                                "set_value": value,
                            }
                        ]
                    },
                    source="trainee-ui",
                )

        self._add_hydrogen_controls(service)
        for dev_name, set_type, value, bound in (
            ("hydrogen-source", "flow_set", 21, "flow_max"),
            ("hydrogen-storage", "pressure_set", 46, "pressure_max"),
        ):
            with self.subTest(set_type=set_type), self.assertRaisesRegex(
                ValueError,
                rf"{set_type}.*{bound}",
            ):
                service.apply_student_commands(
                    {
                        "set_values": [
                            {
                                "dev_type": "HydroSource" if set_type == "flow_set" else "HydroStorage",
                                "dev_name": dev_name,
                                "set_type": set_type,
                                "set_value": value,
                            }
                        ]
                    },
                    source="trainee-ui",
                )

    @staticmethod
    def _add_hydrogen_controls(service):
        from simu.service import EBlock

        current = service.definition_snapshot
        model_book = simu_loop._clone_ebook(current.model_book)
        for block_name, row in (
            (
                "HydroSource",
                {
                    "idx": "1",
                    "name": "hydrogen-source",
                    "flow_set": "2",
                    "flow_min": "0",
                    "flow_max": "20",
                    "run_stat": "1",
                },
            ),
            (
                "HydroStorage",
                {
                    "idx": "1",
                    "name": "hydrogen-storage",
                    "pressure_set": "35",
                    "pressure_min": "2",
                    "pressure_max": "45",
                    "run_stat": "1",
                },
            ),
        ):
            block = EBlock(block_name)
            block.header_list = list(row)
            block.data = [row]
            model_book.data[block_name] = block
        service._publish_definition_snapshot(
            current.__class__(
                revision=current.revision,
                model_book=model_book,
                dev_define_book=current.dev_define_book,
                measurement_before=current.measurement_before,
                measurement_rows=current.measurement_rows,
                measurement_after=current.measurement_after,
                measurement_median_deviations=current.measurement_median_deviations,
            )
        )
        set_block = service.control_book.data["SetValue"]
        set_block.data.extend(
            [
                {
                    "dev_type": "HydroSource",
                    "dev_name": "hydrogen-source",
                    "set_type": "flow_set",
                    "set_value": "2",
                },
                {
                    "dev_type": "HydroStorage",
                    "dev_name": "hydrogen-storage",
                    "set_type": "pressure_set",
                    "set_value": "35",
                },
            ]
        )

    def test_defensive_materialization_skips_old_unsafe_persisted_command(self):
        service, runtime = self._make_service()
        self._add_fields(
            service,
            "ACGenerator",
            "diesel_300kw",
            {"p_min": 30, "p_max": 300},
        )
        unsafe = {
            "eligible_source": True,
            "manual_hold": True,
            "command_origin": "manual",
            "accepted": {"run_status": 0, "set_values": 1, "ignored": 0},
            "normalized": {
                "run_status": [],
                "set_values": [
                    {
                        "dev_type": "ACGenerator",
                        "dev_name": "diesel_300kw",
                        "set_type": "p_set",
                        "set_value": "301",
                    }
                ],
            },
        }
        service.command_history.append(unsafe)

        result = service._materialize_active_control_commands(0, persist=True)

        self.assertEqual(result["set_values"], 0)
        self.assertEqual(self._set_value(service, "ACGenerator", "diesel_300kw", "p_set"), "80")
        self.assertNotIn("301", service.files["stat"].read_text(encoding="utf-8"))
        self.assertNotIn("301", service.files["yt_ctrl"].read_text(encoding="utf-8"))
        self.assertTrue(any("安全边界" in str(item) for item in service.runtime_logs))

    def test_unsafe_loaded_history_is_removed_before_startup_materialization(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import EBook, PolarMicrogridSimulator
        from simu.definition_editing import render_ebook_aligned

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            runtime = root / "runtime"
            write_model_dir(source)
            model_book = EBook(source / "model.e")
            block = model_book.data["ACGenerator"]
            diesel = next(row for row in block.data if row["name"] == "diesel_300kw")
            for field, value in (("p_min", "30"), ("p_max", "300")):
                if field not in block.header_list:
                    block.header_list.append(field)
                diesel[field] = value
            (source / "model.e").write_text(render_ebook_aligned(model_book), encoding="utf-8")
            runtime.mkdir(parents=True)
            history = [
                {
                    "eligible_source": True,
                    "manual_hold": True,
                    "command_origin": "manual",
                    "accepted": {"run_status": 0, "set_values": 1, "ignored": 0},
                    "normalized": {
                        "run_status": [],
                        "set_values": [
                            {
                                "dev_type": "ACGenerator",
                                "dev_name": "diesel_300kw",
                                "set_type": "p_set",
                                "set_value": "301",
                            }
                        ],
                    },
                }
            ]
            (runtime / "commands.json").write_text(
                json.dumps(history, ensure_ascii=False),
                encoding="utf-8",
            )

            service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)

            self.assertEqual(service.command_history, [])
            self.assertEqual(self._set_value(service, "ACGenerator", "diesel_300kw", "p_set"), "80")
            self.assertEqual(json.loads((runtime / "commands.json").read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
