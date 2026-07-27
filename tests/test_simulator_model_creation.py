from __future__ import annotations

import base64
import re
import tempfile
import unittest
from pathlib import Path
from shutil import copytree

import simu_loop
import simu.server as server_module
from simu.service import MultiModelSimulator


ROOT = Path(__file__).resolve().parents[1]


class SimulatorModelCreationTest(unittest.TestCase):
    def test_create_model_from_uploaded_model_e_generates_runtime_definitions(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            models_root = temp_root / "models"
            copytree(ROOT / "models/simulator/source/默认模型", models_root / "默认模型")
            manager = MultiModelSimulator.discover(
                models_root.parent,
                temp_root / "runtime",
                models_dir=models_root,
            )
            model_text = (ROOT / "models/simulator/source/简单模型/model.e").read_text(encoding="utf-8")
            create_model_from_efile = getattr(server_module, "create_model_from_efile", None)
            self.assertIsNotNone(create_model_from_efile)

            created = create_model_from_efile(manager, "新建测试模型", model_text)

            target_dir = models_root / "新建测试模型"
            self.assertEqual(created["id"], "新建测试模型")
            for file_name in ("model.e", "meas.e", "control.e", "stat.e", "weather.e", "curves.e", "curves.json"):
                with self.subTest(file=file_name):
                    self.assertTrue((target_dir / file_name).exists())
            self.assertFalse((target_dir / "device.e").exists())

            meas = simu_loop.EBook(target_dir / "meas.e")
            control = simu_loop.EBook(target_dir / "control.e")
            curves = simu_loop.EBook(target_dir / "curves.e")
            self.assertIn("Measurement", meas.data)
            self.assertIn("RunStat", control.data)
            self.assertIn("SetValue", control.data)
            self.assertIn("CurveInfo", curves.data)
            self.assertIn("EnvironmentCurve", curves.data)
            self.assertIn("LoadCurve", curves.data)

            measurement_rows = meas.data["Measurement"].data
            self.assertGreater(len(measurement_rows), 0)
            self.assertTrue(any(row["dev_type"] == "Environment" for row in measurement_rows))
            self.assertTrue(any(str(row["meas_type"]).upper() == "RUN_STAT" for row in measurement_rows))

            set_rows = control.data["SetValue"].data
            self.assertTrue(any(row["dev_type"] == "ACGenerator" and row["set_type"] == "p_set" for row in set_rows))
            self.assertTrue(any(row["dev_type"] == "ACLoad" and row["set_type"] == "p_set" for row in set_rows))

            devices = manager.service_for("新建测试模型").devices()
            self.assertGreater(len(devices), 0)

    def test_create_model_rejects_duplicate_names_before_writing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            models_root = temp_root / "models"
            copytree(ROOT / "models/simulator/source/默认模型", models_root / "默认模型")
            manager = MultiModelSimulator.discover(
                models_root.parent,
                temp_root / "runtime",
                models_dir=models_root,
            )
            model_text = (ROOT / "models/simulator/source/简单模型/model.e").read_text(encoding="utf-8")
            create_model_from_efile = getattr(server_module, "create_model_from_efile", None)
            self.assertIsNotNone(create_model_from_efile)

            with self.assertRaisesRegex(ValueError, "模型已存在"):
                create_model_from_efile(manager, "默认模型", model_text)

    def test_create_model_endpoint_accepts_base64_model_e_payload(self):
        from simu.server import make_http_server
        from urllib.request import Request, urlopen
        import json
        import threading

        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            models_root = temp_root / "models"
            copytree(ROOT / "models/simulator/source/默认模型", models_root / "默认模型")
            manager = MultiModelSimulator.discover(
                models_root.parent,
                temp_root / "runtime",
                models_dir=models_root,
            )
            server = make_http_server(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            try:
                model_text = (ROOT / "models/simulator/source/简单模型/model.e").read_text(encoding="utf-8")
                payload = {
                    "name": "接口新模型",
                    "filename": "model.e",
                    "data_base64": base64.b64encode(model_text.encode("utf-8")).decode("ascii"),
                }
                request = Request(
                    f"http://127.0.0.1:{port}/api/models/create",
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=10) as response:
                    body = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                thread.join(timeout=5)

            self.assertEqual(body["model"]["id"], "接口新模型")
            self.assertTrue((models_root / "接口新模型/model.e").exists())
            self.assertIn("接口新模型", {model["id"] for model in body["models"]})

    def test_simulator_ui_has_new_model_button_and_dialog(self):
        html = (ROOT / "simu/web/simulator/index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")

        toolbar = html.split('<div class="model-toolbar">', 1)[1].split("</div>", 1)[0]
        self.assertLess(toolbar.index('id="newModelButton"'), toolbar.index('id="modelSelector"'))
        self.assertIn('id="newModelDialog"', html)
        self.assertIn('id="newModelName"', html)
        self.assertIn('id="newModelFileInput"', html)
        self.assertIn('accept=".e"', html)
        self.assertIn("openNewModelDialog", script)
        self.assertIn("validateNewModelForm", script)
        self.assertIn('api("/api/models/create"', script)
        self.assertRegex(script, re.compile(r'api\("/api/models/create",\s*\{[^}]*modelScoped:\s*false', re.DOTALL))
        self.assertIn("data_base64", script)
        self.assertIn("模型已存在", script)


if __name__ == "__main__":
    unittest.main()
