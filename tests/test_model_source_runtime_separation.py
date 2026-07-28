from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path


class ModelSourceRuntimeSeparationTest(unittest.TestCase):
    def _make_service(self, kernel=None):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(source, runtime, kernel=kernel or (lambda _config: None))
        return workspace, source, runtime, service

    def test_runtime_does_not_duplicate_source_definition_files_on_startup(self):
        workspace, source, runtime, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        for file_name in ("model.e", "meas.e", "control.e", "stat.e", "weather.e", "curves.e"):
            self.assertFalse((runtime / file_name).exists(), f"{file_name} should stay in source only")

        self.assertEqual(service.files["model"], source / "model.e")
        self.assertEqual(service.files["meas"], source / "meas.e")
        self.assertEqual(service.files["control"], source / "control.e")
        self.assertEqual(service.source_files["stat"], source / "stat.e")
        self.assertEqual(service.source_files["weather"], source / "weather.e")
        self.assertNotIn("device", service.files)

    def test_step_uses_source_definitions_and_runtime_boundary_files(self):
        captured = {}

        def kernel(config):
            captured["config"] = config
            return None

        workspace, source, runtime, service = self._make_service(kernel=kernel)
        self.addCleanup(workspace.cleanup)

        service.step()
        config = captured["config"]

        self.assertEqual(config.model_file, source / "model.e")
        self.assertEqual(config.meas_file, source / "meas.e")
        self.assertIsNone(config.dev_define_file)
        self.assertIsNone(config.mode_file)
        self.assertEqual(config.dev_stat_file, service.work_files["stat"])
        self.assertEqual(config.weather_file, service.work_files["weather"])
        self.assertEqual(config.real_file, runtime / "real.e")
        self.assertEqual(config.scada_file, runtime / "scada.e")
        self.assertTrue(service.work_files["stat"].exists())
        self.assertTrue(service.work_files["weather"].exists())
        self.assertFalse((service.work_dir / "model.e").exists())
        self.assertFalse((service.work_dir / "merged_model.e").exists())
        self.assertFalse((runtime / "model.e").exists())
        self.assertFalse((runtime / "meas.e").exists())

    def test_simulation_kernel_caches_model_and_does_not_write_merged_model(self):
        import simu_loop

        model_read_count = 0
        original_ebook = simu_loop.EBook

        def counting_ebook(input_data):
            nonlocal model_read_count
            if isinstance(input_data, (str, Path)) and Path(input_data).name == "model.e":
                model_read_count += 1
            return original_ebook(input_data)

        class FakeSnapshot:
            ac_devices = {"ACBreak": {}}
            dc_devices = {"DCBreak": {}}

            def value(self, _dev_type, _dev_name, _meas_type):
                return 0.0

        def kernel(config):
            return simu_loop.run_once(config, solver=lambda _model: (FakeSnapshot(), "fake-solver"))

        workspace, _source, runtime, service = self._make_service(kernel=kernel)
        self.addCleanup(workspace.cleanup)
        self.addCleanup(setattr, simu_loop, "EBook", original_ebook)
        simu_loop.EBook = counting_ebook

        service.step()
        service.step()

        self.assertEqual(model_read_count, 0)
        self.assertFalse((service.work_dir / "merged_model.e").exists())
        self.assertFalse((service.work_dir / "model.e").exists())

    def test_step_rebuilds_stale_runtime_storage_soc_from_source_definition(self):
        import simu_loop

        captured = {}

        def kernel(config):
            captured["config"] = config
            return None

        workspace, source, _runtime, service = self._make_service(kernel=kernel)
        self.addCleanup(workspace.cleanup)
        source_stat = source / "stat.e"
        source_stat.write_text(
            re.sub(
                r"\n<StorageSoc>.*?</StorageSoc>\s*",
                "\n<StorageSoc>\n"
                "@ dev_type idx name soc_curr\n"
                "# DCGenerator 3 new_storage 0.5\n"
                "</StorageSoc>\n",
                source_stat.read_text(encoding="utf-8"),
                flags=re.DOTALL,
            ),
            encoding="utf-8",
        )
        service.work_files["stat"].parent.mkdir(parents=True, exist_ok=True)
        service.work_files["stat"].write_text(
            "<StorageSoc>\n"
            "@ dev_type idx name soc_curr\n"
            "# ESS 3 ess01 0.36\n"
            "</StorageSoc>\n",
            encoding="utf-8",
        )
        service.source_stat_book = simu_loop.EBook(source_stat)
        service.runtime_stat_book = simu_loop.EBook(service.work_files["stat"])

        service.step()

        source_soc = simu_loop.EBook(source / "stat.e").data["StorageSoc"].data
        runtime_soc = captured["config"].dev_stat_book.data["StorageSoc"].data
        self.assertEqual(
            [(row["dev_type"], row["idx"], row["name"]) for row in runtime_soc],
            [(row["dev_type"], row["idx"], row["name"]) for row in source_soc],
        )

    def test_stale_commands_for_removed_devices_do_not_create_runtime_devices_or_measurements(self):
        from simu.service import STAT_HEADERS, _make_book

        workspace, _source, _runtime, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.source_model_book = _make_book(
            {
                "DCGenerator": (
                    ("idx", "name", "dev_type", "node", "control_type", "v_set", "p_set", "run_stat"),
                    [
                        {
                            "idx": "3",
                            "name": "new_storage",
                            "dev_type": "dc-storage",
                            "node": "1",
                            "control_type": "V",
                            "v_set": "500",
                            "p_set": "0",
                            "run_stat": "1",
                        }
                    ],
                )
            }
        )
        service.source_stat_book = _make_book(
            {
                "RunStat": (
                    STAT_HEADERS["RunStat"],
                    [{"dev_type": "DCGenerator", "dev_name": "new_storage", "run_stat": "1"}],
                ),
                "SetValue": (
                    STAT_HEADERS["SetValue"],
                    [
                        {
                            "dev_type": "DCGenerator",
                            "dev_name": "new_storage",
                            "set_type": "p_set",
                            "set_value": "0",
                        }
                    ],
                ),
                "StorageSoc": (
                    STAT_HEADERS["StorageSoc"],
                    [{"dev_type": "DCGenerator", "idx": "3", "name": "new_storage", "soc_curr": "0.5"}],
                ),
            }
        )
        service.control_book = service.source_stat_book
        service.dev_define_book = _make_book({})
        service.runtime_stat_book = service._base_stat_book_for_controls()
        service.measurement_rows = [
            ["1", "DCGenerator.new_storage.P_GEN", "DCGenerator", "new_storage", "P_GEN", "10000.0", "1", "0.0"],
            ["2", "DCGenerator.new_storage.run_stat", "DCGenerator", "new_storage", "RUN_STAT", "1.0", "1", "1.0"],
        ]
        service.latest_real_rows = []
        service.latest_scada_rows = []
        service.command_history = [
            {
                "eligible_source": True,
                "manual_hold": True,
                "accepted": {"run_status": 2, "set_values": 1, "ignored": 0},
                "normalized": {
                    "run_status": [
                        {"dev_type": "ESS", "dev_name": "ess01", "run_stat": "0"},
                        {"dev_type": "DCGenerator", "dev_name": "ess01_vsrc", "run_stat": "0"},
                    ],
                    "set_values": [
                        {
                            "dev_type": "DCGenerator",
                            "dev_name": "ess01_vsrc",
                            "set_type": "p_set",
                            "set_value": "60",
                        }
                    ],
                },
            }
        ]

        service._materialize_active_control_commands(service.clock.absolute_minute)

        device_keys = {(item["dev_type"], item["dev_name"]) for item in service.devices()}
        self.assertIn(("DCGenerator", "new_storage"), device_keys)
        self.assertNotIn(("ESS", "ess01"), device_keys)
        self.assertNotIn(("DCGenerator", "ess01_vsrc"), device_keys)

        measurements = service.measurements()
        measurement_keys = {
            (item["dev_type"], item["dev_name"], item["meas_type"])
            for channel in ("definitions", "real", "scada")
            for item in measurements[channel]
        }
        self.assertIn(("DCGenerator", "new_storage", "RUN_STAT"), measurement_keys)
        self.assertNotIn(("ESS", "ess01", "RUN_STAT"), measurement_keys)
        self.assertNotIn(("DCGenerator", "ess01_vsrc", "RUN_STAT"), measurement_keys)

    def test_student_commands_for_undefined_controls_are_ignored(self):
        workspace, _source, _runtime, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        accepted = service.apply_student_commands(
            {
                "run_status": [{"dev_type": "ESS", "dev_name": "removed_storage", "run_stat": 0}],
                "set_values": [
                    {
                        "dev_type": "DCGenerator",
                        "dev_name": "removed_storage_vsrc",
                        "set_type": "p_set",
                        "set_value": 60,
                    }
                ],
            },
            source="trainee-ui",
        )

        self.assertEqual(accepted, {"run_status": 0, "set_values": 0, "ignored": 2})
        self.assertEqual(service.command_history[-1]["normalized"], {"run_status": [], "set_values": []})

    def test_import_definition_archive_updates_source_without_runtime_definitions(self):
        from simu.server import import_definition_archive, make_definition_archive

        workspace, _source, runtime, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        package_workspace, _package_source, _package_runtime, package_service = self._make_service()
        self.addCleanup(package_workspace.cleanup)

        _filename, archive = make_definition_archive(package_service)
        result = import_definition_archive(service, archive)

        self.assertGreater(result["written"], 0)
        for file_name in ("model.e", "meas.e", "control.e", "stat.e", "weather.e", "curves.e"):
            self.assertFalse((runtime / file_name).exists(), f"{file_name} should not be imported into runtime")
        self.assertTrue((service.sim_dir / "model.e").exists())
        self.assertTrue((service.sim_dir / "meas.e").exists())
        self.assertFalse((service.sim_dir / "device.e").exists())
        self.assertTrue((service.sim_dir / "stat.e").exists())

    def test_simple_model_generator_writes_source_definitions_only(self):
        from simu.generate_simple_model import write_model_dir

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        target = Path(workspace.name) / "source"

        write_model_dir(target)

        for file_name in ("model.e", "meas.e", "control.e", "stat.e", "weather.e", "curves.json"):
            self.assertTrue((target / file_name).exists(), f"{file_name} should be generated as source data")
        self.assertFalse((target / "device.e").exists(), "device parameters should be embedded in model.e")
        for file_name in ("real.e", "scada.e", "yt_ctrl.e", "commands.json", "local_settings.json"):
            self.assertFalse((target / file_name).exists(), f"{file_name} is a runtime artifact")


if __name__ == "__main__":
    unittest.main()
