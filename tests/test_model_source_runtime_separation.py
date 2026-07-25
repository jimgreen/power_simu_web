from __future__ import annotations

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

        for file_name in ("model.e", "meas.e", "control.e", "device.e", "stat.e", "weather.e", "curves.e"):
            self.assertFalse((runtime / file_name).exists(), f"{file_name} should stay in source only")

        self.assertEqual(service.files["model"], source / "model.e")
        self.assertEqual(service.files["meas"], source / "meas.e")
        self.assertEqual(service.files["control"], source / "control.e")
        self.assertEqual(service.files["device"], source / "device.e")
        self.assertEqual(service.source_files["stat"], source / "stat.e")
        self.assertEqual(service.source_files["weather"], source / "weather.e")

    def test_step_uses_source_definitions_and_runtime_work_files(self):
        captured = {}

        def kernel(config):
            captured["config"] = config
            return None

        workspace, source, runtime, service = self._make_service(kernel=kernel)
        self.addCleanup(workspace.cleanup)

        service.step()
        config = captured["config"]

        self.assertEqual(config.model_file, service.work_files["model"])
        self.assertEqual(config.meas_file, source / "meas.e")
        self.assertEqual(config.dev_define_file, source / "device.e")
        self.assertEqual(config.dev_stat_file, service.work_files["stat"])
        self.assertEqual(config.weather_file, service.work_files["weather"])
        self.assertEqual(config.real_file, runtime / "real.e")
        self.assertEqual(config.scada_file, runtime / "scada.e")
        self.assertTrue(service.work_files["model"].exists())
        self.assertTrue(service.work_files["stat"].exists())
        self.assertTrue(service.work_files["weather"].exists())
        self.assertFalse((runtime / "model.e").exists())
        self.assertFalse((runtime / "meas.e").exists())
        self.assertFalse((runtime / "device.e").exists())

    def test_import_definition_archive_updates_source_without_runtime_definitions(self):
        from simu.server import import_definition_archive, make_definition_archive

        workspace, _source, runtime, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        package_workspace, _package_source, _package_runtime, package_service = self._make_service()
        self.addCleanup(package_workspace.cleanup)

        _filename, archive = make_definition_archive(package_service)
        result = import_definition_archive(service, archive)

        self.assertGreater(result["written"], 0)
        for file_name in ("model.e", "meas.e", "control.e", "device.e", "stat.e", "weather.e", "curves.e"):
            self.assertFalse((runtime / file_name).exists(), f"{file_name} should not be imported into runtime")
        self.assertTrue((service.sim_dir / "model.e").exists())
        self.assertTrue((service.sim_dir / "meas.e").exists())
        self.assertTrue((service.sim_dir / "device.e").exists())
        self.assertTrue((service.sim_dir / "stat.e").exists())

    def test_simple_model_generator_writes_source_definitions_only(self):
        from simu.generate_simple_model import write_model_dir

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        target = Path(workspace.name) / "source"

        write_model_dir(target)

        for file_name in ("model.e", "meas.e", "control.e", "stat.e", "weather.e", "device.e", "curves.json"):
            self.assertTrue((target / file_name).exists(), f"{file_name} should be generated as source data")
        for file_name in ("real.e", "scada.e", "yt_ctrl.e", "commands.json", "local_settings.json"):
            self.assertFalse((target / file_name).exists(), f"{file_name} is a runtime artifact")


if __name__ == "__main__":
    unittest.main()
