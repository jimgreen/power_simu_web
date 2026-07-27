import base64
import json
import tempfile
import threading
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from shutil import copytree
from urllib.request import Request, urlopen

from simu.server import import_definition_archive, make_definition_archive, make_http_server
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
            self.assertEqual(snapshot["device_parameters"], package_service.snapshot()["device_parameters"])
            self.assertGreater(len(snapshot["measurements"]["definitions"]), 0)

    def test_definition_package_embeds_device_parameters_in_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            package_source = ROOT / "models/simulator/source/简单模型"
            package_runtime = temp_root / "package-runtime"
            package_service = PolarMicrogridSimulator(package_source, package_runtime, model_id="simple")
            _filename, archive = make_definition_archive(package_service)

            with zipfile.ZipFile(BytesIO(archive), mode="r") as definition_archive:
                self.assertNotIn("device.e", definition_archive.namelist())
                model_text = definition_archive.read("model.e").decode("utf-8")
                self.assertIn("ACWindGen", model_text)
                self.assertIn("DCPVGen", model_text)
                self.assertIn("DCStorageGen", model_text)
                meas_text = definition_archive.read("meas.e").decode("utf-8")
                self.assertIn("Environment", meas_text)
                self.assertIn("weather", meas_text)
                self.assertIn("WIND_SPEED", meas_text)
                self.assertIn("SOLAR_IRRADIANCE", meas_text)

    def test_import_definition_endpoint_overwrites_current_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            trainee_source = temp_root / "source"
            trainee_runtime = temp_root / "runtime"
            copytree(ROOT / "models/trainee/source/默认模型", trainee_source)
            trainee = PolarMicrogridSimulator(trainee_source, trainee_runtime, model_id="test")

            package_service = PolarMicrogridSimulator(
                ROOT / "models/simulator/source/简单模型",
                temp_root / "package-runtime",
                model_id="simple",
            )
            _filename, archive = make_definition_archive(package_service)

            server = make_http_server(("127.0.0.1", 0), trainee, role="trainee")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                request = Request(
                    f"http://127.0.0.1:{port}/api/models/import-definitions",
                    data=json.dumps({"data_base64": base64.b64encode(archive).decode("ascii")}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertGreater(payload["imported"]["written"], 0)
            self.assertEqual(trainee.snapshot()["device_parameters"], package_service.snapshot()["device_parameters"])

    def test_trainee_ui_uses_definitions_until_scada_is_generated(self):
        script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        self.assertIn("measurementDisplayRows", script)
        self.assertIn("snapshot.measurements?.definitions", script)


if __name__ == "__main__":
    unittest.main()
