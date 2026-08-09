from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path


class InMemoryKernelRuntimeTest(unittest.TestCase):
    def _make_service(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(source, runtime, model_id="memory")
        return workspace, source, runtime, service

    def test_step_does_not_touch_e_files_or_create_real_scada_by_default(self):
        import simu.service as service_module
        import simu_loop

        workspace, _source, runtime, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        class FakeSnapshot:
            ac_devices = {"ACBreak": {}}
            dc_devices = {"DCBreak": {}}

            def value(self, _dev_type, _dev_name, _meas_type):
                return 1.0

        original_solve = simu_loop.solve_hybrid_snapshot_from_book
        original_loop_ebook = simu_loop.EBook
        original_service_ebook = service_module.EBook
        original_write_book = simu_loop.write_ebook_aligned
        original_write_measurements = simu_loop.write_measurement_snapshot

        def fake_solve(_model_book, _source):
            return FakeSnapshot(), "fake-solver"

        def fail_file_read(input_data):
            if isinstance(input_data, (str, Path)):
                raise AssertionError(f"runtime calculation read E file: {input_data}")
            return original_loop_ebook(input_data)

        def fail_efile_write(*_args, **_kwargs):
            raise AssertionError("runtime calculation wrote an E file")

        self.addCleanup(setattr, simu_loop, "solve_hybrid_snapshot_from_book", original_solve)
        self.addCleanup(setattr, simu_loop, "EBook", original_loop_ebook)
        self.addCleanup(setattr, service_module, "EBook", original_service_ebook)
        self.addCleanup(setattr, simu_loop, "write_ebook_aligned", original_write_book)
        self.addCleanup(setattr, simu_loop, "write_measurement_snapshot", original_write_measurements)
        simu_loop.solve_hybrid_snapshot_from_book = fake_solve
        simu_loop.EBook = fail_file_read
        service_module.EBook = fail_file_read
        simu_loop.write_ebook_aligned = fail_efile_write
        simu_loop.write_measurement_snapshot = fail_efile_write

        snapshot = service.step()

        self.assertFalse((runtime / "real.e").exists())
        self.assertFalse((runtime / "scada.e").exists())
        self.assertGreater(len(snapshot["measurements"]["scada"]), 0)
        self.assertEqual(snapshot["result"]["solver_info"], "fake-solver")

    def test_interface_updates_are_reflected_without_reloading_e_files(self):
        import simu.service as service_module
        import simu_loop

        workspace, _source, _runtime, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_student_commands(
            {
                "valid_for_minutes": 5,
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 22.5}
                ],
            },
            source="trainee-ui",
        )
        self.assertEqual(result["set_values"], 1)

        original_loop_ebook = simu_loop.EBook
        original_service_ebook = service_module.EBook

        def fail_file_read(input_data):
            if isinstance(input_data, (str, Path)):
                raise AssertionError(f"runtime state lookup read E file: {input_data}")
            return original_loop_ebook(input_data)

        self.addCleanup(setattr, simu_loop, "EBook", original_loop_ebook)
        self.addCleanup(setattr, service_module, "EBook", original_service_ebook)
        simu_loop.EBook = fail_file_read
        service_module.EBook = fail_file_read

        values = service.latest_control_values()["values"]

        self.assertEqual(values["ESS.ess01.p_set"], 22.5)

    def test_in_memory_solver_reconstructs_contracted_ideal_edge_flows(self):
        import simu_loop

        root = Path(__file__).resolve().parents[1]
        model_path = root / "models" / "simulator" / "source" / "\u79e6\u5cad\u7ad9" / "model.e"
        model_book = simu_loop.EBook(model_path)

        snapshot, _solver_info = simu_loop.solve_hybrid_snapshot_from_book(
            model_book,
            model_path,
        )

        load_power = snapshot.value("ACLoad", "\u4ea4\u6d41\u8d1f\u8377-1", "P_LOAD")
        zero_branch_power = snapshot.value(
            "ACZeroBranch",
            "\u4ea4\u6d41\u96f6\u963b\u6297\u652f\u8def\uff08\u81ea\u9002\u5e94\uff09-1",
            "P_FROM",
        )
        breaker_power = snapshot.value("ACBreak", "\u76d2\u578b\u5f00\u5173-7", "P_FROM")

        self.assertIsNotNone(load_power)
        self.assertGreater(abs(load_power), 1.0)
        self.assertAlmostEqual(zero_branch_power, load_power, places=6)
        self.assertAlmostEqual(breaker_power, load_power, places=6)

    def test_dcac_converter_terminal_powers_follow_ac_terminal_setpoint_sign(self):
        import simu_loop

        model_path = next(
            path
            for path in (
                Path(__file__).resolve().parents[1]
                / "models"
                / "simulator"
                / "source"
            ).glob("*/model.e")
            if "dcac-converter" in path.read_text(encoding="utf-8").casefold()
        )

        for converter_type in ("dcac-converter", "acdc-converter"):
            for p_ac_set, expected_p_dc in ((-10.0, 10.0), (10.0, -10.0)):
                with self.subTest(
                    converter_type=converter_type,
                    p_ac_set=p_ac_set,
                ):
                    model_book = simu_loop.EBook(model_path)
                    converter = next(
                        row
                        for row in model_book.data["DCACConverter"].data
                        if row.get("ac_node", "") != ""
                        and row.get("dc_node", "") != ""
                        and str(row.get("ac_control_type", "")).upper() == "PQ"
                    )
                    converter["dev_type"] = converter_type
                    converter["p_ac_set"] = p_ac_set

                    snapshot, _solver_info = simu_loop.solve_hybrid_snapshot_from_book(
                        model_book,
                        model_path,
                    )

                    self.assertAlmostEqual(
                        snapshot.value(
                            "DCACConverter",
                            converter["name"],
                            "P_AC",
                        ),
                        p_ac_set,
                        places=6,
                    )
                    self.assertAlmostEqual(
                        snapshot.value(
                            "DCACConverter",
                            converter["name"],
                            "P_DC",
                        ),
                        expected_p_dc,
                        places=6,
                    )

        for converter_type in ("dcac-converter", "acdc-converter"):
            for p_dc_set in (-10.0, 10.0):
                with self.subTest(
                    converter_type=converter_type,
                    p_dc_set=p_dc_set,
                ):
                    model_book = simu_loop.EBook(model_path)
                    converter_block = model_book.data["DCACConverter"]
                    if "p_dc_set" not in converter_block.header_list:
                        converter_block.header_list.append("p_dc_set")
                    converter = next(
                        row
                        for row in converter_block.data
                        if row.get("ac_node", "") != ""
                        and row.get("dc_node", "") != ""
                        and str(row.get("ac_control_type", "")).upper() == "PQ"
                    )
                    converter.update(
                        {
                            "dev_type": converter_type,
                            "ac_control_type": "NONE",
                            "dc_control_type": "P",
                            "p_ac_set": 0.0,
                            "p_dc_set": p_dc_set,
                        }
                    )

                    snapshot, _solver_info = simu_loop.solve_hybrid_snapshot_from_book(
                        model_book,
                        model_path,
                    )

                    self.assertAlmostEqual(
                        snapshot.value(
                            "DCACConverter",
                            converter["name"],
                            "P_AC",
                        ),
                        -p_dc_set,
                        places=6,
                    )
                    self.assertAlmostEqual(
                        snapshot.value(
                            "DCACConverter",
                            converter["name"],
                            "P_DC",
                        ),
                        p_dc_set,
                        places=6,
                    )

    def test_two_parallel_dcac_converters_solve_for_all_side_control_combinations(self):
        import simu_loop

        model_path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "simple_model" / "model.e"
        cases = {
            "mixed": (("NONE", "P"), ("PQ", "NONE")),
            "both_dc": (("NONE", "P"), ("NONE", "P")),
            "both_ac": (("PQ", "NONE"), ("PQ", "NONE")),
            "double_none": (("NONE", "NONE"), ("NONE", "NONE")),
        }

        for label, modes in cases.items():
            with self.subTest(label=label):
                model_book = simu_loop.EBook(model_path)
                converter_block = model_book.data["DCACConverter"]
                first = next(
                    row for row in converter_block.data if row.get("name") == "grid_inv_acp"
                )
                second = copy.deepcopy(first)
                second.update({"idx": "3", "name": "grid_inv_parallel"})
                converter_block.data.append(second)

                expected_p_ac = (-9.0, -3.0)
                for row, (ac_mode, dc_mode), target_kw in zip(
                    (first, second), modes, expected_p_ac
                ):
                    row.update(
                        {
                            "ac_control_type": ac_mode,
                            "dc_control_type": dc_mode,
                            "p_ac_set": target_kw,
                            "p_dc_set": -target_kw,
                        }
                    )

                snapshot, _solver_info = simu_loop.solve_hybrid_snapshot_from_book(
                    model_book,
                    model_path,
                )

                measured_p_ac = []
                for row, (ac_mode, dc_mode), target_kw in zip(
                    (first, second), modes, expected_p_ac
                ):
                    p_ac = snapshot.value("DCACConverter", row["name"], "P_AC")
                    p_dc = snapshot.value("DCACConverter", row["name"], "P_DC")
                    measured_p_ac.append(p_ac)
                    if dc_mode == "P" or (dc_mode == "NONE" and ac_mode == "NONE"):
                        self.assertAlmostEqual(p_dc, -target_kw, places=6)
                    else:
                        self.assertAlmostEqual(p_ac, target_kw, places=6)
                    self.assertLess(p_ac, 0.0)
                    self.assertGreater(p_dc, 0.0)
                self.assertAlmostEqual(sum(measured_p_ac), sum(expected_p_ac), delta=0.02)

    def test_qinling_parallel_grid_converters_solve_for_all_side_control_combinations(self):
        import simu_loop
        from simu.model_semantics import grid_converter_keys

        model_path = (
            Path(__file__).resolve().parents[1]
            / "models"
            / "simulator"
            / "source"
            / "秦岭站"
            / "model.e"
        )
        cases = {
            "mixed": (("NONE", "P"), ("PQ", "NONE")),
            "both_dc": (("NONE", "P"), ("NONE", "P")),
            "both_ac": (("PQ", "NONE"), ("PQ", "NONE")),
            "double_none": (("NONE", "NONE"), ("NONE", "NONE")),
        }

        for label, modes in cases.items():
            with self.subTest(label=label):
                model_book = simu_loop.EBook(model_path)
                converter_keys = sorted(
                    key
                    for key in grid_converter_keys(model_book)
                    if key[0] in {"ACDCConverter", "DCACConverter"}
                )
                self.assertEqual(len(converter_keys), 2)
                converters = [
                    next(
                        row
                        for row in model_book.data[block_name].data
                        if str(row.get("name", "")) == device_name
                    )
                    for block_name, device_name in converter_keys
                ]

                expected_p_ac = (-9.0, -3.0)
                for row, (ac_mode, dc_mode), target_kw in zip(
                    converters,
                    modes,
                    expected_p_ac,
                ):
                    row.update(
                        {
                            "ac_control_type": ac_mode,
                            "dc_control_type": dc_mode,
                            "p_ac_set": target_kw,
                            "p_dc_set": -target_kw,
                        }
                    )

                snapshot, _solver_info = simu_loop.solve_hybrid_snapshot_from_book(
                    model_book,
                    model_path,
                )

                measured_p_dc = []
                for row, target_kw in zip(converters, expected_p_ac):
                    p_ac = snapshot.value("DCACConverter", row["name"], "P_AC")
                    p_dc = snapshot.value("DCACConverter", row["name"], "P_DC")
                    measured_p_dc.append(p_dc)
                    self.assertAlmostEqual(p_ac, target_kw, delta=0.02)
                    self.assertAlmostEqual(p_dc, -target_kw, delta=0.02)
                    self.assertLess(p_ac, 0.0)
                    self.assertGreater(p_dc, 0.0)
                self.assertAlmostEqual(sum(measured_p_dc), 12.0, delta=0.04)


if __name__ == "__main__":
    unittest.main()
