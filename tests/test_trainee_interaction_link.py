from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from simu.server import make_http_server
from simu.service import PolarMicrogridSimulator
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


ROOT = Path(__file__).resolve().parents[1]


class TraineeInteractionLinkTest(unittest.TestCase):
    def test_simulator_exposes_shareable_service_address_trainee_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = PolarMicrogridSimulator(
                SIMPLE_MODEL_SOURCE,
                Path(temporary) / "runtime",
                model_id="simple_model",
                model_name="简单模型",
            )
            server = make_http_server(("127.0.0.1", 0), service, role="simulator")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with urlopen(f"http://127.0.0.1:{port}/api/trainee-link", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                with self.assertRaises(HTTPError) as old_link_error:
                    urlopen(
                        f"http://127.0.0.1:{port}/api/trainee-link?model_id=simple_model",
                        timeout=5,
                    )
                self.assertEqual(old_link_error.exception.code, 400)
            finally:
                server.shutdown()
                server.server_close()

        self.assertEqual(payload["type"], "polar-microgrid-trainee-link")
        self.assertEqual(payload["role"], "simulator")
        self.assertEqual(payload["model_id"], "simple_model")
        self.assertEqual(payload["model_name"], "简单模型")
        self.assertTrue(payload["shareable"])
        self.assertEqual(payload["link"], f"http://127.0.0.1:{port}")
        self.assertNotIn("/api/", payload["link"])
        self.assertNotIn("?", payload["link"])
        self.assertEqual(payload["teacher_api_base"], f"http://127.0.0.1:{port}")
        self.assertEqual(
            payload["snapshot_path"],
            "/api/snapshot?model_id=simple_model&trainee_view=1",
        )
        self.assertEqual(
            payload["measurement_delta_path"],
            "/api/measurements/delta?model_id=simple_model&trainee_view=1",
        )
        self.assertEqual(payload["telemetry_path"], "/api/external/telemetry?model_id=simple_model")
        self.assertEqual(payload["selected_telemetry_path"], "/api/external/telemetry/query?model_id=simple_model")
        self.assertEqual(payload["control_values_path"], "/api/external/controls?model_id=simple_model")
        self.assertEqual(payload["control_command_path"], "/api/external/controls?model_id=simple_model")
        self.assertEqual(
            payload["definition_archive_path"],
            "/api/export-definitions?format=json&model_id=simple_model",
        )

    def test_simulator_ui_can_generate_and_copy_trainee_link(self):
        html = (ROOT / "simu/web/simulator/index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu/web/simulator/app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu/web/simulator/styles.css").read_text(encoding="utf-8")

        self.assertIn('id="traineeLinkButton"', html)
        self.assertIn('id="traineeLinkDialog"', html)
        self.assertIn('id="traineeLinkValue"', html)
        self.assertIn("openTraineeLinkDialog", script)
        self.assertIn('api("/api/trainee-link"', script)
        self.assertIn("generatedTraineeLink", script)
        generated_block = script.split("function generatedTraineeLink", 1)[1].split("\n}", 1)[0]
        self.assertIn("activeModelServiceBase", generated_block)
        self.assertNotIn("/api/trainee-link", generated_block)
        self.assertNotIn("controlPlaneApiBase", generated_block)
        self.assertNotIn("model_id", generated_block)
        open_dialog_block = script.split("async function openTraineeLinkDialog", 1)[1].split("\n}", 1)[0]
        self.assertIn('api("/api/trainee-link", { modelScoped: false })', open_dialog_block)
        self.assertNotIn("controlPlane: true", open_dialog_block)
        self.assertIn("setTraineeLinkCopyEnabled", script)
        self.assertIn("模拟台服务地址已自动生成", script)
        self.assertIn("copyTraineeLink", script)
        self.assertIn(".trainee-link-modal", styles)

    def test_trainee_model_initialization_prompts_for_interaction_link_before_receive_start(self):
        html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

        self.assertIn('id="modelInitializeButton"', html)
        self.assertIn('id="traineeRunToggle"', html)
        self.assertIn('id="receiveLinkDialog"', html)
        self.assertIn('id="receiveLinkInput"', html)
        self.assertIn("一个服务地址可供多个学员台", html)
        self.assertIn('placeholder="http://127.0.0.1:8711"', html)
        self.assertNotIn("/api/trainee-link?model_id=", html)
        self.assertIn("openReceiveLinkDialog", script)
        self.assertIn("initializeModelFromLink", script)
        self.assertIn('api("/api/trainee/model-initialize"', script)
        self.assertIn('api("/api/trainee/receive"', script)
        self.assertIn("const activeModelIdBeforeInitialize = state.activeModelId", script)
        self.assertIn("state.activeModelId = activeModelIdBeforeInitialize", script)
        self.assertIn('$("modelInitializeButton").addEventListener("click", openReceiveLinkDialog);', script)
        self.assertIn('$("traineeRunToggle").addEventListener("click", toggleReceiveMode);', script)
        self.assertNotIn("fetch(url.href", script)
        self.assertNotIn("legacyTeacherInteractionConnection", script)
        normalize_block = script.split("function normalizeConnectionUrl", 1)[1].split("\n}", 1)[0]
        self.assertIn("url.origin", normalize_block)
        self.assertIn("url.pathname", normalize_block)
        self.assertIn("url.search", normalize_block)
        receive_address_block = script.split("function teacherReceiveAddress", 1)[1].split("\n}", 1)[0]
        self.assertIn("state.interactionLink", receive_address_block)
        self.assertIn("state.teacherApiBase || state.interactionLink", receive_address_block)
        self.assertIn("normalizeConnectionUrl(configuredAddress)", receive_address_block)
        self.assertIn(".receive-link-dialog", styles)


if __name__ == "__main__":
    unittest.main()
