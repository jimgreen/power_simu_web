import tempfile
import unittest
from pathlib import Path
from shutil import copytree

from simu.server import import_definition_model, make_definition_archive
from simu.service import MultiModelSimulator, PolarMicrogridSimulator
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


ROOT = Path(__file__).resolve().parents[1]


class SimulatorDefinitionImportTest(unittest.TestCase):
    def test_definition_package_can_be_imported_as_a_new_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            models_root = temp_root / "models"
            copytree(SIMPLE_MODEL_SOURCE, models_root / "默认模型")
            manager = MultiModelSimulator.discover(
                models_root.parent,
                temp_root / "runtime",
                models_dir=models_root,
            )
            package_service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                temp_root / "package-runtime",
                model_id="simple",
            )
            _filename, archive = make_definition_archive(package_service)

            imported = import_definition_model(manager, "默认模型", "导入模型", archive)

            self.assertEqual(imported["id"], "导入模型")
            self.assertTrue(imported["validation"]["ok"])
            self.assertEqual(
                next(
                    check for check in imported["validation"]["checks"]
                    if check["id"] == "diagram"
                )["status"],
                "warning",
            )
            self.assertTrue((models_root / "导入模型/model.e").exists())
            self.assertEqual(
                len(manager.service_for("导入模型").devices()),
                len(package_service.devices()),
            )

    def test_duplicate_import_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            models_root = temp_root / "models"
            copytree(SIMPLE_MODEL_SOURCE, models_root / "默认模型")
            manager = MultiModelSimulator.discover(
                models_root.parent,
                temp_root / "runtime",
                models_dir=models_root,
            )

            with self.assertRaisesRegex(ValueError, "模型已存在"):
                import_definition_model(manager, "默认模型", "默认模型", b"not-used")

    def test_simulator_ui_prompts_for_an_import_model_name(self):
        html = (ROOT / "simu/web/simulator/index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")

        self.assertIn('id="importDefinitionsButton"', html)
        self.assertIn('id="importModelDialog"', html)
        self.assertIn('id="importModelName"', html)
        self.assertIn('id="importModelValidation"', html)
        self.assertIn('id="importModelValidationChecks"', html)
        self.assertIn("SVG 图形", html)
        self.assertIn("validateImportModelName", script)
        self.assertIn('renderModelPreflightResult("importModel"', script)
        self.assertIn("模型已存在", script)
        self.assertIn("create_model: true", script)


if __name__ == "__main__":
    unittest.main()
