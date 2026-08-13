from __future__ import annotations

import base64
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from shutil import copytree
from unittest.mock import patch

import simu_loop
import simu.server as server_module
from simu.service import MultiModelSimulator
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


ROOT = Path(__file__).resolve().parents[1]


class SimulatorModelCreationTest(unittest.TestCase):
    @staticmethod
    def _tree_bytes(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    @staticmethod
    def _structured_storage_model_text(ac_soc: str, dc_soc: str = "-0.05") -> str:
        return f"""<ACGenerator>
@ idx  name  node  control_type  p_set  q_set  v_set  run_stat
# 1  ac-storage  1  P  0  0  380  1
</ACGenerator>
<DCGenerator>
@ idx  name  node  control_type  p_set  v_set  i_set  run_stat
# 1  dc-storage  1  P  0  720  0  1
</DCGenerator>
<ACStorageGen>
@ idx  idx_acgenerator  energy_capacity  state_of_charge
# 1  1  100  {ac_soc}
</ACStorageGen>
<DCStorageGen>
@ idx  idx_dcgenerator  energy_capacity  state_of_charge
# 1  1  120  {dc_soc}
</DCStorageGen>
"""

    @staticmethod
    def _manager(temp_root: Path) -> MultiModelSimulator:
        models_root = temp_root / "models"
        copytree(SIMPLE_MODEL_SOURCE, models_root / "default-model")
        return MultiModelSimulator.discover(
            models_root.parent,
            temp_root / "runtime",
            models_dir=models_root,
        )

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
            self.assertIn("SourceCurve", curves.data)

            measurement_rows = meas.data["Measurement"].data
            self.assertGreater(len(measurement_rows), 0)
            self.assertTrue(any(row["dev_type"] == "Environment" for row in measurement_rows))
            self.assertTrue(any(str(row["meas_type"]).upper() == "RUN_STAT" for row in measurement_rows))

            set_rows = control.data["SetValue"].data
            self.assertTrue(any(row["dev_type"] == "ACGenerator" and row["set_type"] == "p_set" for row in set_rows))
            self.assertTrue(any(row["dev_type"] == "ACLoad" and row["set_type"] == "p_set" for row in set_rows))

            devices = manager.service_for("新建测试模型").devices()
            self.assertGreater(len(devices), 0)

    def test_generated_model_removes_ambiguous_converter_runtime_fields(self):
        model_text = """<DCACConverter>
@ idx name ac_node dc_node ac_control_type dc_control_type p_ac_set p_dc_set run_stat p q u i
# 1 dcac-1 1 2 PQ NONE 3 -3 1 30 4 380 8
</DCACConverter>
<DCDCConverter>
@ idx name i_node j_node i_control_type j_control_type p_set v_set run_stat p q u i
# 1 dcdc-1 2 3 V NONE 5 750 1 20 0 750 2
</DCDCConverter>
<ACACConverter>
@ idx name i_node j_node control_type p_set q_from_set q_to_set run_stat p q u i
# 1 acac-1 3 4 PQQ 6 1 -1 1 10 2 380 3
</ACACConverter>
"""

        artifacts = server_module._generated_model_artifacts(model_text)

        model_book = artifacts["model_book"]
        for block_name in ("DCACConverter", "DCDCConverter", "ACACConverter"):
            with self.subTest(block=block_name):
                block = model_book.data[block_name]
                self.assertTrue({"p", "q", "u", "i"}.isdisjoint(block.header_list))
                self.assertTrue(
                    all(
                        {"p", "q", "u", "i"}.isdisjoint(row)
                        for row in block.data
                    )
                )

        self.assertIn("p_ac_set", model_book.data["DCACConverter"].header_list)
        self.assertIn("p_dc_set", model_book.data["DCACConverter"].header_list)
        self.assertIn("p_set", model_book.data["DCDCConverter"].header_list)
        self.assertIn("v_set", model_book.data["DCDCConverter"].header_list)
        self.assertIn("q_from_set", model_book.data["ACACConverter"].header_list)
        self.assertIn("q_to_set", model_book.data["ACACConverter"].header_list)

    def test_create_model_from_uploaded_model_e_generates_ac_and_dc_storage_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            manager = self._manager(temp_root)

            server_module.create_model_from_efile(
                manager,
                "structured-storage",
                self._structured_storage_model_text("1.08", "-0.05"),
            )

            target_dir = temp_root / "models" / "structured-storage"
            expected = [
                ("ACGenerator", "ac-storage", 1.08),
                ("DCGenerator", "dc-storage", -0.05),
            ]
            for file_name in ("control.e", "stat.e"):
                with self.subTest(file=file_name):
                    book = simu_loop.EBook(target_dir / file_name)
                    storage_rows = book.data["StorageSoc"].data
                    self.assertEqual(
                        [
                            (row["dev_type"], row["name"], float(row["soc_curr"]))
                            for row in storage_rows
                        ],
                        expected,
                    )

            measurement_rows = simu_loop.EBook(target_dir / "meas.e").data["Measurement"].data
            soc_rows = [
                row
                for row in measurement_rows
                if str(row["meas_type"]).upper() == "SOC"
            ]
            self.assertEqual(len(soc_rows), 2)
            self.assertEqual(
                [
                    (row["dev_type"], row["dev_name"], int(float(row["valid"])))
                    for row in soc_rows
                ],
                [
                    ("ACGenerator", "ac-storage", 1),
                    ("DCGenerator", "dc-storage", 1),
                ],
            )

    def test_create_model_from_uploaded_model_e_parses_percent_storage_soc(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            manager = self._manager(temp_root)

            server_module.create_model_from_efile(
                manager,
                "percent-storage",
                self._structured_storage_model_text("108%"),
            )

            control = simu_loop.EBook(temp_root / "models" / "percent-storage" / "control.e")
            ac_storage_rows = [
                row
                for row in control.data["StorageSoc"].data
                if row["dev_type"] == "ACGenerator" and row["name"] == "ac-storage"
            ]
            self.assertEqual(len(ac_storage_rows), 1)
            self.assertEqual(float(ac_storage_rows[0]["soc_curr"]), 1.08)

    def test_generic_percent_values_remain_ratios_for_generated_loads(self):
        self.assertEqual(server_module._numeric("50%"), 0.5)
        self.assertEqual(server_module._storage_soc_value(108), 108.0)
        self.assertEqual(server_module._storage_soc_value("108"), 108.0)
        self.assertEqual(server_module._storage_soc_value(1.08), 1.08)
        self.assertEqual(server_module._storage_soc_value("108%"), 1.08)
        self.assertEqual(server_module._storage_soc_value(-0.05), -0.05)

        model_book = server_module._book_from_text(
            """<ACLoad>
@ idx  name  node  pbase  pv0  qbase  qv0  run_stat
# 1  load-percent  1  100  50%  1  0  1
</ACLoad>
"""
        )
        curves = server_module._generated_curves_payload(model_book)

        self.assertEqual(server_module._load_base_kw(model_book.data["ACLoad"].data[0], "ACLoad"), 50.0)
        self.assertEqual(curves["loads"]["load-percent"][0]["p_kw"], 38.653)

    def test_create_model_skips_storage_rows_with_missing_generator_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            manager = self._manager(temp_root)
            model_text = """<ACGenerator>
@ idx  name  node  control_type  p_set  q_set  v_set  run_stat
# 1  ac-source  1  P  0  0  380  1
</ACGenerator>
<ACStorageGen>
@ idx  idx_acgenerator  energy_capacity  state_of_charge
# 1  999  100  0.75
</ACStorageGen>
"""

            server_module.create_model_from_efile(manager, "malformed-storage", model_text)

            target_dir = temp_root / "models" / "malformed-storage"
            for file_name in ("control.e", "stat.e"):
                with self.subTest(file=file_name):
                    book = simu_loop.EBook(target_dir / file_name)
                    self.assertNotIn("StorageSoc", book.data)
            measurement_rows = simu_loop.EBook(target_dir / "meas.e").data["Measurement"].data
            self.assertEqual(
                [row for row in measurement_rows if str(row["meas_type"]).upper() == "SOC"],
                [],
            )

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

    def test_model_e_update_merges_curves_json_by_load_name(self):
        existing = {
            "mode": "day",
            "time_step_minutes": 5,
            "point_count": 2,
            "weather": [{"minute": 0, "wind_speed_mps": 3}, {"minute": 5, "wind_speed_mps": 4}],
            "loads": {
                "保留负荷": [{"minute": 0, "p_kw": 11}, {"minute": 5, "p_kw": 12}],
                "删除负荷": [{"minute": 0, "p_kw": 21}, {"minute": 5, "p_kw": 22}],
            },
        }
        generated = {
            "mode": "day",
            "time_step_minutes": 1,
            "point_count": 4,
            "weather": [{"minute": index, "wind_speed_mps": 8} for index in range(4)],
            "loads": {
                "保留负荷": [{"minute": index, "p_kw": 100 + index} for index in range(4)],
                "新增负荷": [{"minute": index, "p_kw": 30 + index} for index in range(4)],
            },
        }

        merged = server_module._merge_generated_curves_payload(existing, generated)

        self.assertEqual(merged["weather"], existing["weather"])
        self.assertEqual(merged["loads"]["保留负荷"], existing["loads"]["保留负荷"])
        self.assertNotIn("删除负荷", merged["loads"])
        self.assertEqual(len(merged["loads"]["新增负荷"]), 2)
        self.assertEqual([point["minute"] for point in merged["loads"]["新增负荷"]], [0, 5])

    def test_source_curve_definition_round_trip_and_model_update_merge(self):
        curves = {
            "mode": "day",
            "time_step_minutes": 1,
            "point_count": 2,
            "weather": [],
            "loads": {},
            "sources": [
                {
                    "dev_type": "HydroSource",
                    "dev_name": "h-source",
                    "set_type": "flow_set",
                    "family": "hydrogen",
                    "unit": "Nm3/h",
                    "points": [{"minute": 0, "value": 1}, {"minute": 1, "value": 2}],
                }
            ],
        }
        restored = server_module._curves_from_definition_text(server_module._curve_definition_text(curves))
        self.assertEqual(restored["sources"][0]["dev_type"], "HydroSource")
        self.assertEqual(restored["sources"][0]["points"], curves["sources"][0]["points"])

        generated = {
            **curves,
            "sources": [
                {**curves["sources"][0], "points": [{"minute": 0, "value": 9}]},
                {
                    "dev_type": "HeatSource",
                    "dev_name": "heat-new",
                    "set_type": "flow_set",
                    "family": "heat",
                    "unit": "kg/s",
                    "points": [{"minute": 0, "value": 3}],
                },
            ],
        }
        existing = {
            **curves,
            "sources": [
                curves["sources"][0],
                {
                    "dev_type": "HeatSource",
                    "dev_name": "heat-deleted",
                    "set_type": "flow_set",
                    "family": "heat",
                    "unit": "kg/s",
                    "points": [{"minute": 0, "value": 4}],
                },
            ],
        }
        merged = server_module._merge_generated_curves_payload(existing, generated)
        identities = [(item["dev_type"], item["dev_name"], item["set_type"]) for item in merged["sources"]]
        self.assertEqual(identities, [("HydroSource", "h-source", "flow_set"), ("HeatSource", "heat-new", "flow_set")])
        self.assertEqual(merged["sources"][0]["points"], curves["sources"][0]["points"])
        self.assertEqual(merged["sources"][1]["points"], [{"minute": 0, "value": 3}])

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

    def test_update_model_cannot_write_deleted_recreated_service_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            models_root = temp_root / "models"
            for model_id in ("target", "keep"):
                copytree(SIMPLE_MODEL_SOURCE, models_root / model_id)
            manager = MultiModelSimulator.discover(
                models_root.parent,
                temp_root / "runtime",
                models_dir=models_root,
            )
            old_target = manager.service_for("target")
            model_text = (SIMPLE_MODEL_SOURCE / "model.e").read_text(encoding="utf-8")
            artifacts_ready = threading.Event()
            release_write = threading.Event()
            original_generate = server_module._generated_model_artifacts

            def blocking_generate(text):
                artifacts = original_generate(text)
                artifacts_ready.set()
                self.assertTrue(release_write.wait(timeout=3.0))
                return artifacts

            result = {}

            def update_old_target():
                try:
                    result["value"] = server_module.update_model_from_efile(
                        manager,
                        "target",
                        model_text,
                    )
                except Exception as exc:
                    result["error"] = exc

            update_thread = threading.Thread(target=update_old_target, daemon=True)
            try:
                with patch.object(
                    server_module,
                    "_generated_model_artifacts",
                    side_effect=blocking_generate,
                ):
                    update_thread.start()
                    self.assertTrue(artifacts_ready.wait(timeout=3.0))

                    manager.delete_model("target")
                    manager.create_model_slot("target")
                    new_target = manager.service_for("target")
                    source_before = self._tree_bytes(new_target.sim_dir)
                    runtime_before = self._tree_bytes(new_target.runtime_dir)

                    release_write.set()
                    update_thread.join(timeout=5.0)
                    self.assertFalse(update_thread.is_alive())
            finally:
                release_write.set()
                update_thread.join(timeout=2.0)

            self.assertNotIn("value", result)
            self.assertIsInstance(result.get("error"), server_module.JsonApiError)
            self.assertEqual(result["error"].status, 409)
            self.assertRegex(str(result["error"]), "生命周期|失效|删除|退休")
            self.assertIsNot(new_target, old_target)
            self.assertFalse(old_target.service_instance_active())
            self.assertEqual(self._tree_bytes(new_target.sim_dir), source_before)
            self.assertEqual(self._tree_bytes(new_target.runtime_dir), runtime_before)

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

    def test_create_model_recovers_incomplete_same_name_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            manager = self._manager(temp_root)
            incomplete_dir = manager.models_root / "秦岭站"
            incomplete_dir.mkdir()
            (incomplete_dir / "meas.e").write_text("legacy partial data", encoding="utf-8")
            model_text = (SIMPLE_MODEL_SOURCE / "model.e").read_text(encoding="utf-8")

            created = server_module.create_model_from_efile(manager, "秦岭站", model_text)

            recovered_dir = Path(created["created"]["recovered_incomplete_directory"])
            self.assertEqual(created["id"], "秦岭站")
            self.assertTrue((manager.models_root / "秦岭站" / "model.e").exists())
            self.assertEqual((recovered_dir / "meas.e").read_text(encoding="utf-8"), "legacy partial data")
            self.assertTrue(recovered_dir.is_relative_to(manager.runtime_dir))

    def test_create_model_removes_current_attempt_when_registration_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            manager = self._manager(temp_root)
            model_text = (SIMPLE_MODEL_SOURCE / "model.e").read_text(encoding="utf-8")

            with patch.object(manager, "_append_manifest_model", side_effect=OSError("write failed")):
                with self.assertRaisesRegex(OSError, "write failed"):
                    server_module.create_model_from_efile(manager, "创建失败模型", model_text)

            self.assertFalse((manager.models_root / "创建失败模型").exists())

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

    def test_create_model_endpoint_accepts_gb18030_model_e_payload(self):
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
                    "name": "国标编码模型",
                    "filename": "model.e",
                    "data_base64": base64.b64encode(model_text.encode("gb18030")).decode("ascii"),
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

            self.assertEqual(body["model"]["id"], "国标编码模型")
            self.assertTrue((models_root / "国标编码模型/model.e").exists())

    def test_svg_payload_decoder_accepts_utf8_bom_and_gb18030(self):
        cases = {
            "utf8": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<svg xmlns="http://www.w3.org/2000/svg"><text>秦岭站</text></svg>'
            ).encode("utf-8"),
            "utf8-bom": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<svg xmlns="http://www.w3.org/2000/svg"><text>秦岭站</text></svg>'
            ).encode("utf-8-sig"),
            "gb18030": (
                '<?xml version="1.0" encoding="GB18030"?>'
                '<svg xmlns="http://www.w3.org/2000/svg"><text>秦岭站</text></svg>'
            ).encode("gb18030"),
        }

        for name, raw_svg in cases.items():
            with self.subTest(encoding=name):
                decoded = server_module._decode_optional_svg_payload(
                    {"diagram_svg_base64": base64.b64encode(raw_svg).decode("ascii")}
                )
                normalized = server_module._normalize_diagram_svg_text(decoded)
                self.assertIn("秦岭站", normalized)
                self.assertIn('encoding="UTF-8"', normalized)

    def test_svg_payload_decoder_reports_base64_and_text_encoding_separately(self):
        with self.assertRaisesRegex(ValueError, "Base64 数据无效"):
            server_module._decode_optional_svg_payload({"diagram_svg_base64": "%%%"})

        invalid_bytes = base64.b64encode(b"\xff\xff\xff").decode("ascii")
        with self.assertRaisesRegex(ValueError, "SVG图形.*文件编码无法识别"):
            server_module._decode_optional_svg_payload({"diagram_svg_base64": invalid_bytes})

    def test_svg_encoding_support_does_not_bypass_script_validation(self):
        unsafe_svg = (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<text onclick="alert(1)">秦岭站</text></svg>'
        ).encode("gb18030")
        decoded = server_module._decode_optional_svg_payload(
            {"diagram_svg_base64": base64.b64encode(unsafe_svg).decode("ascii")}
        )

        with self.assertRaisesRegex(ValueError, "不能包含脚本"):
            server_module._normalize_diagram_svg_text(decoded)

    def test_e_file_decoder_accepts_utf8_bom_and_gb18030_and_rejects_unknown_bytes(self):
        e_text = "<Model>\n@ name\n# 秦岭站\n</Model>\n"
        for encoding in ("utf-8", "utf-8-sig", "gb18030"):
            with self.subTest(encoding=encoding):
                decoded = server_module._decode_uploaded_definition_text(
                    e_text.encode(encoding),
                    "model.e",
                )
                self.assertIn("秦岭站", decoded)

        with self.assertRaisesRegex(ValueError, "model.e 文件编码无法识别"):
            server_module._decode_uploaded_definition_text(b"\xff\xff\xff", "model.e")

    def test_update_model_endpoint_accepts_gb18030_model_and_svg_payloads(self):
        from simu.server import make_http_server
        from urllib.request import Request, urlopen

        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            manager = self._manager(temp_root)
            server = make_http_server(("127.0.0.1", 0), manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            model_text = (SIMPLE_MODEL_SOURCE / "model.e").read_text(encoding="utf-8")
            model_text = model_text.replace("diesel_300kw", "秦岭柴油机")
            diagram_text = (
                '<?xml version="1.0" encoding="GB18030"?>'
                '<svg xmlns="http://www.w3.org/2000/svg"><text>秦岭站一次图</text></svg>'
            )
            try:
                request = Request(
                    f"http://127.0.0.1:{port}/api/models/update-definitions",
                    data=json.dumps(
                        {
                            "model_id": "default-model",
                            "data_base64": base64.b64encode(
                                model_text.encode("gb18030")
                            ).decode("ascii"),
                            "diagram_svg_base64": base64.b64encode(
                                diagram_text.encode("gb18030")
                            ).decode("ascii"),
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=15) as response:
                    body = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            target_dir = manager.models_root / "default-model"
            saved_model = target_dir.joinpath("model.e").read_text(encoding="utf-8")
            saved_diagram = target_dir.joinpath("diagram.svg").read_text(encoding="utf-8")
            self.assertEqual(body["model"]["id"], "default-model")
            self.assertIn("秦岭柴油机", saved_model)
            self.assertIn("秦岭站一次图", saved_diagram)
            self.assertIn('encoding="UTF-8"', saved_diagram)
            self.assertGreater(len(manager.service_for("default-model").definitions()["measurement"]), 0)

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
        self.assertIn("payload.diagram_svg_base64 = diagramSvgBase64", script)
        self.assertIn('else setUpdateModelMessage("正在保存访问链接...")', script)
        self.assertIn("if (file) {", script)
        self.assertIn("if (diagramFile) {", script)
        self.assertIn("let updateFailed = false", script)
        self.assertIn('setUpdateModelMessage(`保存失败：${message}`, "error")', script)
        self.assertIn('portInput?.setAttribute("aria-invalid", "true")', script)
        self.assertIn('if (!updateFailed && !$("updateModelDialog").hidden)', script)
        self.assertIn('.model-service-field-grid input[aria-invalid="true"]', styles)
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
        self.assertIn('id="newModelServiceHost"', html)
        self.assertIn('id="newModelServicePort"', html)
        self.assertIn('id="newModelFileInput"', html)
        self.assertIn('accept=".e"', html)
        self.assertIn('id="newModelSvgInput"', html)
        self.assertIn('accept=".svg,image/svg+xml"', html)
        self.assertIn('id="confirmNewModel" class="primary" type="button">新建</button>', html)
        self.assertIn('src="/app.js?v=20260813-hydrogen-coupling-metrics"', html)
        self.assertIn('href="/styles.css?v=20260812-runtime-log-column-resize"', html)
        self.assertIn("openNewModelDialog", script)
        self.assertIn("validateNewModelForm", script)
        self.assertIn('controlPlaneApi("/api/models/create"', script)
        self.assertIn('$("confirmNewModel").addEventListener("click", createNewModelFromFile)', script)
        self.assertIn("if (newModelCreationActive) return", script)
        self.assertRegex(
            script,
            re.compile(
                r'controlPlaneApi\("/api/models/create",\s*\{[^}]*method:\s*"POST"',
                re.DOTALL,
            ),
        )
        self.assertIn("data_base64", script)
        self.assertIn("diagram_svg_base64", script)
        self.assertIn("service_host", script)
        self.assertIn("service_port", script)
        self.assertIn("未选择的文件将保持不变", script)
        self.assertNotIn('if (!file || !validateUpdateModelForm(true))', script)
        self.assertIn('id="updateModelServiceHost"', html)
        self.assertIn('id="updateModelServicePort"', html)
        self.assertIn('id="confirmUpdateModel" class="primary" type="submit">确认</button>', html)
        self.assertIn('<dt>访问链接</dt><dd id="overviewServiceLink">--</dd>', html)
        self.assertIn("model-service-address", script)
        self.assertIn("model-service-state-pill", script)
        self.assertIn('setOverviewText("overviewServiceLink"', script)
        self.assertIn("new URL(baseUrl)", script)
        self.assertIn(".model-service-address", styles)
        self.assertIn(".model-service-state-pill", styles)
        self.assertRegex(
            styles,
            re.compile(
                r"\.modal-card\.model-management-modal\s*\{[^}]*width:\s*min\(820px,\s*calc\(100vw - 40px\)\)",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            styles,
            re.compile(r"\.model-service-address\s*\{[^}]*text-align:\s*left", re.DOTALL),
        )
        self.assertRegex(
            styles,
            re.compile(
                r"\.model-item-badges\s*\{[^}]*width:\s*148px[^}]*justify-content:\s*flex-end",
                re.DOTALL,
            ),
        )
        self.assertIn("模型已存在", script)


if __name__ == "__main__":
    unittest.main()
