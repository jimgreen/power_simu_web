import base64
import json
import tempfile
import threading
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from shutil import copytree
from unittest.mock import patch
from urllib.request import Request, urlopen

import simu.server as server_module
from simu.server import import_definition_archive, make_definition_archive, make_http_server
from simu.service import MultiModelSimulator, PolarMicrogridSimulator
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


ROOT = Path(__file__).resolve().parents[1]


def _rewrite_definition_archive(archive_data: bytes, replacements: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(archive_data), mode="r") as source:
        with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as target:
            for name in source.namelist():
                target.writestr(name, replacements.get(name, source.read(name)))
    return output.getvalue()


def _replace_efile_block(text: str, block_name: str, replacement: str) -> str:
    start_marker = f"<{block_name}>"
    end_marker = f"</{block_name}>"
    start = text.index(start_marker)
    end = text.index(end_marker, start) + len(end_marker)
    return text[:start] + replacement.strip() + text[end:]


def _matching_svg(model_text: str, extra: str = "") -> str:
    model_book = server_module._book_from_text(model_text)
    uses = []
    for block_name in sorted(server_module._SVG_REQUIRED_MODEL_BLOCKS):
        block = model_book.data.get(block_name)
        for row in [] if block is None else block.data:
            idx = str(row.get("idx", "")).strip()
            name = str(row.get("name", "")).strip()
            if idx and name:
                uses.append(
                    f'<use id="{block_name}-{idx}" dev-id="{block_name}-{idx}" '
                    f'idx="{idx}" name="{name}" />'
                )
    return '<svg xmlns="http://www.w3.org/2000/svg">' + extra + "".join(uses) + "</svg>"


class DefinitionImportRefreshTest(unittest.TestCase):
    def setUp(self):
        power_flow = patch.object(
            server_module.simu_loop,
            "solve_hybrid_snapshot_from_book",
            return_value=(object(), "iter=2, normF=1.000e-09"),
        )
        power_flow.start()
        self.addCleanup(power_flow.stop)

    def test_definition_archive_accepts_gb18030_e_and_svg_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            package_service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                temp_root / "package-runtime",
                model_id="simple",
            )
            _filename, archive = make_definition_archive(package_service)
            replacements: dict[str, bytes] = {}
            with zipfile.ZipFile(BytesIO(archive), mode="r") as definition_archive:
                for name in ("model.e", "meas.e", "control.e", "curves.e"):
                    text = definition_archive.read(name).decode("utf-8-sig")
                    replacements[name] = (
                        text
                        + f"\n<{name}_编码验证>\n@ name\n# 秦岭站\n</{name}_编码验证>\n"
                    ).encode("gb18030")
                replacements["diagram.svg"] = (
                    '<?xml version="1.0" encoding="GB18030"?>'
                    + _matching_svg(
                        replacements["model.e"].decode("gb18030"),
                        "<text>秦岭站</text>",
                    )
                ).encode("gb18030")
            archive = _rewrite_definition_archive(archive, replacements)

            parsed = server_module._parse_definition_archive(archive)

            self.assertIn("秦岭站", parsed["model_text"])
            self.assertIn("秦岭站", parsed["meas_text"])
            self.assertIn("秦岭站", parsed["control_text"])
            self.assertIn("秦岭站", parsed["curves_text"])
            self.assertIn("秦岭站", parsed["diagram_text"])
            self.assertIn('encoding="UTF-8"', parsed["diagram_text"])

            trainee_source = temp_root / "trainee-source"
            copytree(ROOT / "models/trainee/source/默认模型", trainee_source)
            trainee = PolarMicrogridSimulator(
                trainee_source,
                temp_root / "trainee-runtime",
                model_id="trainee",
            )
            imported = import_definition_archive(trainee, archive)

            self.assertGreater(imported["written"], 0)
            for name in ("model.e", "meas.e", "control.e", "curves.e"):
                saved_text = (trainee_source / name).read_text(encoding="utf-8")
                self.assertIn("秦岭站", saved_text)
            saved_diagram = (trainee_source / "diagram.svg").read_text(encoding="utf-8")
            self.assertIn("秦岭站", saved_diagram)
            self.assertIn('encoding="UTF-8"', saved_diagram)

    def test_imported_model_and_measurements_are_visible_immediately(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            trainee_source = temp_root / "source"
            trainee_runtime = temp_root / "runtime"
            copytree(ROOT / "models/trainee/source/默认模型", trainee_source)
            trainee = PolarMicrogridSimulator(trainee_source, trainee_runtime, model_id="test")

            package_source = SIMPLE_MODEL_SOURCE
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
            package_source = SIMPLE_MODEL_SOURCE
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

    def test_definition_package_preserves_measurement_median_deviations(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            package_service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                temp_root / "package-runtime",
                model_id="simple",
                kernel=lambda _config: None,
            )
            measurement_name = "p_gen_diesel_300kw"
            package_service.update_measurement_definition(
                {
                    "name": measurement_name,
                    "changes": {"median_deviation": -0.35},
                }
            )

            _filename, archive = make_definition_archive(package_service)
            with zipfile.ZipFile(BytesIO(archive), mode="r") as definition_archive:
                defaults = json.loads(
                    definition_archive.read("definition_defaults.json").decode("utf-8")
                )
            self.assertAlmostEqual(
                defaults["measurement_median_deviations"][measurement_name],
                -0.35,
            )

            target_source = temp_root / "target-source"
            copytree(SIMPLE_MODEL_SOURCE, target_source)
            target = PolarMicrogridSimulator(
                target_source,
                temp_root / "target-runtime",
                model_id="target",
                kernel=lambda _config: None,
            )
            import_definition_archive(target, archive)

            imported = next(
                row
                for row in target.definitions()["measurement"]
                if row["name"] == measurement_name
            )
            self.assertAlmostEqual(imported["median_deviation"], -0.35)
            self.assertAlmostEqual(
                target._make_config().measurement_median_deviations[measurement_name],
                -0.35,
            )

    def test_definition_package_adds_one_dcp_control_for_each_converter(self):
        with tempfile.TemporaryDirectory() as temporary:
            package_service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                Path(temporary) / "package-runtime",
                model_id="simple",
            )

            _filename, archive = make_definition_archive(package_service)

            with zipfile.ZipFile(BytesIO(archive), mode="r") as definition_archive:
                model_text = definition_archive.read("model.e").decode("utf-8")
                control_text = definition_archive.read("control.e").decode("utf-8")
            model_book = package_service.definition_snapshot.model_book
            converter_names = {
                str(row["name"])
                for row in model_book.data["DCACConverter"].data
            }
            parsed_control = server_module._book_from_text(control_text)
            dcp_names = [
                str(row["dev_name"])
                for row in parsed_control.data["SetValue"].data
                if str(row.get("dev_type")) == "DCACConverter"
                and str(row.get("set_type")) == "p_dc_set"
            ]

            self.assertIn("p_dc_set", model_text)
            self.assertEqual(set(dcp_names), converter_names)
            self.assertEqual(len(dcp_names), len(converter_names))

    def test_import_definition_archive_adds_missing_converter_dcp_controls(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            package_service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                temp_root / "package-runtime",
                model_id="simple",
            )
            _filename, archive = make_definition_archive(package_service)
            with zipfile.ZipFile(BytesIO(archive), mode="r") as definition_archive:
                control_text = definition_archive.read("control.e").decode("utf-8")
            stripped_control = "\n".join(
                line
                for line in control_text.splitlines()
                if not (
                    line.lstrip().startswith("#")
                    and "DCACConverter" in line
                    and "p_dc_set" in line
                )
            ) + "\n"
            archive = _rewrite_definition_archive(
                archive,
                {"control.e": stripped_control.encode("utf-8")},
            )

            trainee_source = temp_root / "trainee-source"
            copytree(ROOT / "models/trainee/source/默认模型", trainee_source)
            trainee = PolarMicrogridSimulator(
                trainee_source,
                temp_root / "trainee-runtime",
                model_id="trainee",
            )

            import_definition_archive(trainee, archive)

            converter_names = {
                str(row["name"])
                for row in trainee.definition_snapshot.model_book.data["DCACConverter"].data
            }
            dcp_rows = [
                row
                for row in trainee.control_book.data["SetValue"].data
                if str(row.get("dev_type")) == "DCACConverter"
                and str(row.get("set_type")) == "p_dc_set"
            ]
            self.assertEqual({str(row["dev_name"]) for row in dcp_rows}, converter_names)
            self.assertEqual(len(dcp_rows), len(converter_names))

    def test_import_definition_archive_rejects_legacy_converter_control_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            package_service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                temp_root / "package-runtime",
                model_id="simple",
            )
            _filename, archive = make_definition_archive(package_service)
            with zipfile.ZipFile(BytesIO(archive), mode="r") as definition_archive:
                model_text = definition_archive.read("model.e").decode("utf-8")
            legacy_block = """
<DCACConverter>
@ idx name ac_node dc_node control_type p_ac_set p_dc_set run_stat
# 1 legacy-link 1 1 DCP -10 10 1
</DCACConverter>
"""
            model_text = _replace_efile_block(model_text, "DCACConverter", legacy_block)
            archive = _rewrite_definition_archive(
                archive,
                {"model.e": model_text.encode("utf-8")},
            )

            trainee_source = temp_root / "trainee-source"
            copytree(ROOT / "models/trainee/source/默认模型", trainee_source)
            trainee = PolarMicrogridSimulator(
                trainee_source,
                temp_root / "trainee-runtime",
                model_id="trainee",
            )

            with self.assertRaisesRegex(ValueError, "control_type"):
                import_definition_archive(trainee, archive)

    def test_import_definition_archive_repairs_converter_p_dc_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            package_service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                temp_root / "package-runtime",
                model_id="simple",
            )
            _filename, archive = make_definition_archive(package_service)
            with zipfile.ZipFile(BytesIO(archive), mode="r") as definition_archive:
                model_text = definition_archive.read("model.e").decode("utf-8")
            missing_dcp_block = """
<DCACConverter>
@ idx name ac_node dc_node ac_control_type dc_control_type p_ac_set run_stat
# 1 missing-dcp-link 1 1 PQ NONE -10 1
</DCACConverter>
"""
            model_text = _replace_efile_block(model_text, "DCACConverter", missing_dcp_block)
            archive = _rewrite_definition_archive(
                archive,
                {"model.e": model_text.encode("utf-8")},
            )

            trainee_source = temp_root / "trainee-source"
            copytree(ROOT / "models/trainee/source/默认模型", trainee_source)
            trainee = PolarMicrogridSimulator(
                trainee_source,
                temp_root / "trainee-runtime",
                model_id="trainee",
            )

            imported = import_definition_archive(trainee, archive)

            saved_book = server_module._book_from_text(
                (trainee_source / "model.e").read_text(encoding="utf-8")
            )
            converter = saved_book.data["DCACConverter"].data[0]
            self.assertEqual(float(converter["p_dc_set"]), 0.0)
            self.assertIn("p_dc_set", saved_book.data["DCACConverter"].header_list)
            self.assertTrue(imported["validation"]["ok"])
            self.assertTrue(
                any(
                    repair["block"] == "DCACConverter"
                    and repair["field"] == "p_dc_set"
                    for repair in imported["validation"]["repairs"]
                )
            )

    def test_import_definition_archive_removes_ambiguous_converter_runtime_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            package_service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                temp_root / "package-runtime",
                model_id="simple",
            )
            _filename, archive = make_definition_archive(package_service)
            with zipfile.ZipFile(BytesIO(archive), mode="r") as definition_archive:
                model_text = definition_archive.read("model.e").decode("utf-8")
            converter_block = """
<DCACConverter>
@ idx name ac_node dc_node ac_control_type dc_control_type p_ac_set p_dc_set run_stat p q u i
# 1 dcac-1 1 1 PQ NONE -10 10 1 -10 0 380 15
</DCACConverter>
"""
            model_text = _replace_efile_block(model_text, "DCACConverter", converter_block)
            archive = _rewrite_definition_archive(
                archive,
                {"model.e": model_text.encode("utf-8")},
            )

            trainee_source = temp_root / "trainee-source"
            copytree(ROOT / "models/trainee/source/默认模型", trainee_source)
            trainee = PolarMicrogridSimulator(
                trainee_source,
                temp_root / "trainee-runtime",
                model_id="trainee",
            )

            import_definition_archive(trainee, archive)

            imported = server_module._book_from_text(
                (trainee_source / "model.e").read_text(encoding="utf-8")
            )
            headers = imported.data["DCACConverter"].header_list
            self.assertTrue({"p", "q", "u", "i"}.isdisjoint(headers))
            self.assertIn("p_ac_set", headers)
            self.assertIn("p_dc_set", headers)

    def test_definition_package_roundtrips_svg_diagram_and_exposes_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            package_source = temp_root / "package-source"
            copytree(SIMPLE_MODEL_SOURCE, package_source)
            model_text = (package_source / "model.e").read_text(encoding="utf-8")
            diagram_text = _matching_svg(
                model_text,
                '<text data-meas-name="Environment.weather.WIND_SPEED"></text>',
            )
            (package_source / "diagram.svg").write_text(diagram_text, encoding="utf-8")
            package_service = PolarMicrogridSimulator(package_source, temp_root / "package-runtime", model_id="simple")

            _filename, archive = make_definition_archive(package_service)

            with zipfile.ZipFile(BytesIO(archive), mode="r") as definition_archive:
                self.assertIn("diagram.svg", definition_archive.namelist())
                self.assertEqual(definition_archive.read("diagram.svg").decode("utf-8"), diagram_text)

            trainee_source = temp_root / "trainee-source"
            trainee_runtime = temp_root / "trainee-runtime"
            copytree(ROOT / "models/trainee/source/默认模型", trainee_source)
            trainee = PolarMicrogridSimulator(trainee_source, trainee_runtime, model_id="trainee")
            imported = import_definition_archive(trainee, archive)

            self.assertTrue(imported["diagram"])
            self.assertEqual((trainee_source / "diagram.svg").read_text(encoding="utf-8"), diagram_text)
            self.assertEqual(trainee.snapshot()["diagram"]["svg"], diagram_text)

    def test_definition_package_always_contains_svg_diagram(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            package_source = temp_root / "package-source"
            copytree(SIMPLE_MODEL_SOURCE, package_source)
            diagram_path = package_source / "diagram.svg"
            if diagram_path.exists():
                diagram_path.unlink()
            package_service = PolarMicrogridSimulator(package_source, temp_root / "package-runtime", model_id="simple")

            _filename, archive = make_definition_archive(package_service)

            with zipfile.ZipFile(BytesIO(archive), mode="r") as definition_archive:
                self.assertIn("diagram.svg", definition_archive.namelist())
                diagram_text = definition_archive.read("diagram.svg").decode("utf-8")
            self.assertIn("<svg", diagram_text)
            self.assertIn("simple", diagram_text)

    def test_import_definition_archive_requires_svg_diagram(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            package_service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                temp_root / "package-runtime",
                model_id="simple",
            )
            _filename, archive = make_definition_archive(package_service)
            without_svg = BytesIO()
            with zipfile.ZipFile(BytesIO(archive), mode="r") as source:
                with zipfile.ZipFile(without_svg, mode="w", compression=zipfile.ZIP_DEFLATED) as target:
                    for name in source.namelist():
                        if name != "diagram.svg":
                            target.writestr(name, source.read(name))

            trainee_source = temp_root / "trainee-source"
            trainee_runtime = temp_root / "trainee-runtime"
            copytree(ROOT / "models/trainee/source/默认模型", trainee_source)
            trainee = PolarMicrogridSimulator(trainee_source, trainee_runtime, model_id="trainee")

            with self.assertRaisesRegex(ValueError, "diagram.svg"):
                import_definition_archive(trainee, without_svg.getvalue())

    def test_import_definition_endpoint_overwrites_current_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            trainee_source = temp_root / "source"
            trainee_runtime = temp_root / "runtime"
            copytree(ROOT / "models/trainee/source/默认模型", trainee_source)
            trainee = PolarMicrogridSimulator(trainee_source, trainee_runtime, model_id="test")

            package_service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
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

    def test_trainee_import_definition_endpoint_can_create_independent_model_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            models_root = temp_root / "models"
            copytree(ROOT / "models/trainee/source/默认模型", models_root / "默认模型")
            manager = MultiModelSimulator.discover(
                temp_root,
                temp_root / "runtime",
                models_dir=models_root,
            )
            package_service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                temp_root / "package-runtime",
                model_id="simple",
            )
            _filename, archive = make_definition_archive(package_service)

            server = make_http_server(("127.0.0.1", 0), manager, role="trainee")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                request = Request(
                    f"http://127.0.0.1:{port}/api/models/import-definitions",
                    data=json.dumps({
                        "create_model": True,
                        "name": "学员导入模型",
                        "data_base64": base64.b64encode(archive).decode("ascii"),
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(payload["model"]["id"], "学员导入模型")
            self.assertTrue((models_root / "学员导入模型" / "model.e").exists())
            self.assertIn("学员导入模型", {model["id"] for model in payload["models"]})
            self.assertEqual(
                manager.service_for("学员导入模型").snapshot()["device_parameters"],
                package_service.snapshot()["device_parameters"],
            )

    def test_trainee_ui_uses_definitions_until_scada_is_generated(self):
        script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        self.assertIn("measurementDisplayRows", script)
        self.assertIn("snapshot.measurements?.definitions", script)


if __name__ == "__main__":
    unittest.main()
