import tempfile
import unittest
from pathlib import Path
from shutil import copytree

from simu.server import import_definition_archive, make_definition_archive
from simu.service import PolarMicrogridSimulator


ROOT = Path(__file__).resolve().parents[1]


class DefinitionImportRefreshTest(unittest.TestCase):
    def test_imported_model_and_measurements_are_visible_immediately(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            trainee_source = temp_root / "source"
            trainee_runtime = temp_root / "runtime"
            copytree(ROOT / "models/trainee/source/默认模型", trainee_source)
            trainee = PolarMicrogridSimulator(trainee_source, trainee_runtime, model_id="test")

            package_source = ROOT / "models/simulator/source/简单模型"
            package_runtime = temp_root / "package-runtime"
            package_service = PolarMicrogridSimulator(package_source, package_runtime, model_id="simple")
            _filename, archive = make_definition_archive(package_service)

            imported = import_definition_archive(trainee, archive)
            snapshot = trainee.snapshot()

            self.assertGreater(imported["written"], 0)
            self.assertEqual(len(snapshot["devices"]), len(package_service.devices()))
            self.assertEqual(
                len(snapshot["measurements"]["definitions"]),
                len(package_service.measurements()["definitions"]),
            )
            self.assertGreater(len(snapshot["measurements"]["definitions"]), 0)

    def test_trainee_ui_uses_definitions_until_scada_is_generated(self):
        script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        self.assertIn("measurementDisplayRows", script)
        self.assertIn("snapshot.measurements?.definitions", script)


if __name__ == "__main__":
    unittest.main()
