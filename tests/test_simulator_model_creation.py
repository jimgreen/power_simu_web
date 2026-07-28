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
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


ROOT = Path(__file__).resolve().parents[1]


class SimulatorModelCreationTest(unittest.TestCase):
    def test_create_model_from_uploaded_model_e_generates_runtime_definitions(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            models_root = temp_root / "models"
            copytree(SIMPLE_MODEL_SOURCE, models_root / "默认模型")
            manager = MultiModelSimulator.discover(
                models_root.parent,
                temp_root / "runtime",
                models_dir=models_root,
            )
            model_text = (SIMPLE_MODEL_SOURCE / "model.e").read_text(encoding="utf-8")
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

    def test_create_model_from_uploaded_model_e_can_store_svg_diagram(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            models_root = temp_root / "models"
            copytree(SIMPLE_MODEL_SOURCE, models_root / "默认模型")
            manager = MultiModelSimulator.discover(
                models_root.parent,
                temp_root / "runtime",
                models_dir=models_root,
            )
            model_text = (SIMPLE_MODEL_SOURCE / "model.e").read_text(encoding="utf-8")
            diagram_text = '<svg xmlns="http://www.w3.org/2000/svg"><text data-meas-name="ACGenerator.diesel_300kw.P_GEN"></text></svg>'

            created = server_module.create_model_from_efile(
                manager,
                "带图模型",
                model_text,
                diagram_svg_text=diagram_text,
            )

            target_dir = models_root / "带图模型"
            self.assertIn("diagram.svg", created["created"]["files"])
            self.assertEqual((target_dir / "diagram.svg").read_text(encoding="utf-8"), diagram_text)
            self.assertEqual(manager.service_for("带图模型").snapshot()["diagram"]["svg"], diagram_text)

    def test_update_model_from_uploaded_model_e_can_replace_definition_and_svg_for_stopped_model_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            models_root = temp_root / "models"
            copytree(SIMPLE_MODEL_SOURCE, models_root / "默认模型")
            manager = MultiModelSimulator.discover(
                models_root.parent,
                temp_root / "runtime",
                models_dir=models_root,
            )
            model_text = (SIMPLE_MODEL_SOURCE / "model.e").read_text(encoding="utf-8")
            diagram_text = '<svg xmlns="http://www.w3.org/2000/svg"><text data-meas-name="DCPVGen.pv_120kw.P_GEN"></text></svg>'

            manager.service_for("默认模型").control_clock({"action": "start"})
            with self.assertRaisesRegex(ValueError, "运行中"):
                server_module.update_model_from_efile(
                    manager,
                    "默认模型",
                    model_text,
                    diagram_svg_text=diagram_text,
                )
            manager.service_for("默认模型").control_clock({"action": "stop"})

            updated = server_module.update_model_from_efile(
                manager,
                "默认模型",
                model_text,
                diagram_svg_text=diagram_text,
            )

            self.assertEqual(updated["id"], "默认模型")
            self.assertIn("diagram.svg", updated["updated"]["files"])
            self.assertEqual((models_root / "默认模型" / "diagram.svg").read_text(encoding="utf-8"), diagram_text)
            self.assertGreater(len(manager.service_for("默认模型").definitions()["measurement"]), 0)

    def test_create_model_rejects_duplicate_names_before_writing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            models_root = temp_root / "models"
            copytree(SIMPLE_MODEL_SOURCE, models_root / "默认模型")
            manager = MultiModelSimulator.discover(
                models_root.parent,
                temp_root / "runtime",
                models_dir=models_root,
            )
            model_text = (SIMPLE_MODEL_SOURCE / "model.e").read_text(encoding="utf-8")
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
            copytree(SIMPLE_MODEL_SOURCE, models_root / "默认模型")
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
                model_text = (SIMPLE_MODEL_SOURCE / "model.e").read_text(encoding="utf-8")
                payload = {
                    "name": "接口新模型",
                    "filename": "model.e",
                    "data_base64": base64.b64encode(model_text.encode("utf-8")).decode("ascii"),
                    "diagram_filename": "diagram.svg",
                    "diagram_svg_base64": base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>').decode("ascii"),
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
            self.assertTrue((models_root / "接口新模型/diagram.svg").exists())
            self.assertIn("接口新模型", {model["id"] for model in body["models"]})

    def test_delete_model_rejects_running_model_and_removes_stopped_model_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            models_root = temp_root / "models"
            copytree(SIMPLE_MODEL_SOURCE, models_root / "默认模型")
            copytree(SIMPLE_MODEL_SOURCE, models_root / "运行模型")
            manager = MultiModelSimulator.discover(
                models_root.parent,
                temp_root / "runtime",
                models_dir=models_root,
            )

            manager.service_for("运行模型").control_clock({"action": "start"})

            with self.assertRaisesRegex(ValueError, "运行中"):
                manager.delete_model("运行模型")

            manager.service_for("运行模型").control_clock({"action": "stop"})
            deleted = manager.delete_model("运行模型")

            self.assertEqual(deleted["id"], "运行模型")
            self.assertFalse((models_root / "运行模型").exists())
            self.assertFalse((temp_root / "runtime" / "运行模型").exists())
            self.assertNotIn("运行模型", {model["id"] for model in manager.models()})

    def test_simulator_ui_uses_single_model_management_button_and_dialog(self):
        html = (ROOT / "simu/web/simulator/index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu/web/simulator/styles.css").read_text(encoding="utf-8")

        toolbar = html.split('<div class="model-toolbar">', 1)[1].split("</div>", 1)[0]
        self.assertLess(toolbar.index('id="modelManagementButton"'), toolbar.index('id="modelSelector"'))
        self.assertNotIn('id="newModelButton"', toolbar)
        self.assertNotIn('id="exportDefinitionsButton"', toolbar)
        self.assertNotIn('id="importDefinitionsButton"', toolbar)
        self.assertNotIn('id="cloneModelButton"', toolbar)
        self.assertIn('id="modelManagementDialog"', html)
        self.assertIn('id="modelManagementList"', html)
        self.assertIn('<div id="modelManagementList"', html)
        self.assertIn('role="tree"', html)
        self.assertNotIn("model-management-table", html)
        self.assertIn('data-model-management-action="new"', html)
        self.assertIn('data-model-management-action="import"', html)
        self.assertNotIn('id="exportDefinitionsButton"', html)
        self.assertNotIn('id="cloneModelButton"', html)
        self.assertNotIn('id="deleteSelectedModelButton"', html)
        self.assertIn('id="modelContextMenu"', html)
        self.assertIn('data-model-context-action="export"', html)
        self.assertIn('data-model-context-action="clone"', html)
        self.assertIn('data-model-context-action="update"', html)
        self.assertIn('data-model-context-action="delete"', html)
        self.assertIn('data-model-context-action="update">修改</button>', html)
        self.assertIn('id="updateModelDialog"', html)
        self.assertIn("<h2 id=\"updateModelTitle\">修改模型</h2>", html)
        self.assertIn('id="updateModelFileInput"', html)
        self.assertIn('id="updateModelSvgInput"', html)
        self.assertIn("导入修改后的 model.e", html)
        self.assertNotIn(">导出选中<", html)
        self.assertNotIn(">复制选中<", html)
        self.assertNotIn(">导出当前<", html)
        self.assertNotIn(">复制当前<", html)
        self.assertIn("renderModelManagementList", script)
        self.assertIn("model-management-item", script)
        self.assertIn("model-management-tree-root", script)
        self.assertIn('role="treeitem"', script)
        self.assertIn("selectedManagementModelId", script)
        self.assertIn("setSelectedManagementModel", script)
        self.assertIn("openModelContextMenu", script)
        self.assertIn('addEventListener("contextmenu"', script)
        self.assertIn("handleModelContextMenuAction", script)
        self.assertIn("右键模型节点可导出、复制、修改或删除。", script)
        self.assertIn("openUpdateModelDialog", script)
        self.assertIn('api("/api/models/update-definitions"', script)
        self.assertIn('case "update":', script)
        self.assertIn("openUpdateModelDialog(selectedManagementModelId())", script)
        self.assertIn('diagram_svg_base64: diagramSvgBase64', script)
        self.assertIn("deleteManagedModel(selectedManagementModelId()", script)
        self.assertIn('api("/api/models/delete"', script)
        self.assertNotIn("模型目录", script)
        self.assertNotIn("已选中", script)
        self.assertNotIn("model-selected-pill", script)
        self.assertNotIn("model-item-path", script)
        self.assertIn(".model-management-list-wrap", styles)
        self.assertIn("overflow-y: auto", styles)
        self.assertIn("overflow-x: hidden", styles)
        self.assertIn(".model-management-item", styles)
        self.assertIn(".model-management-tree-root", styles)
        self.assertIn(".model-management-branches", styles)
        self.assertIn(".model-context-menu", styles)
        self.assertNotIn(".model-selected-pill", styles)
        self.assertNotIn(".model-item-path", styles)
        self.assertNotIn(".model-management-table", styles)
        self.assertIn('id="newModelDialog"', html)
        self.assertIn('id="newModelName"', html)
        self.assertIn('id="newModelFileInput"', html)
        self.assertIn('accept=".e"', html)
        self.assertIn('id="newModelSvgInput"', html)
        self.assertIn('accept=".svg,image/svg+xml"', html)
        self.assertIn("openNewModelDialog", script)
        self.assertIn("validateNewModelForm", script)
        self.assertIn('api("/api/models/create"', script)
        self.assertRegex(script, re.compile(r'api\("/api/models/create",\s*\{[^}]*modelScoped:\s*false', re.DOTALL))
        self.assertIn("data_base64", script)
        self.assertIn("diagram_svg_base64", script)
        self.assertIn("模型已存在", script)


if __name__ == "__main__":
    unittest.main()
