from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

from simu.server import make_http_server
from simu.service import PolarMicrogridSimulator
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


ROOT = Path(__file__).resolve().parents[1]


class TraineeInteractionLinkTest(unittest.TestCase):
    def test_simulator_exposes_shareable_model_scoped_trainee_link(self):
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
                with urlopen(f"http://127.0.0.1:{port}/api/trainee-link?model_id=simple_model", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()

        self.assertEqual(payload["type"], "polar-microgrid-trainee-link")
        self.assertEqual(payload["role"], "simulator")
        self.assertEqual(payload["model_id"], "simple_model")
        self.assertEqual(payload["model_name"], "简单模型")
        self.assertTrue(payload["shareable"])
        self.assertIn(f"http://127.0.0.1:{port}/api/trainee-link?model_id=simple_model", payload["link"])
        self.assertEqual(payload["teacher_api_base"], f"http://127.0.0.1:{port}")
        self.assertEqual(payload["telemetry_path"], "/api/external/telemetry?model_id=simple_model")
        self.assertEqual(payload["selected_telemetry_path"], "/api/external/telemetry/query?model_id=simple_model")
        self.assertEqual(payload["control_values_path"], "/api/external/controls?model_id=simple_model")
        self.assertEqual(payload["control_command_path"], "/api/external/controls?model_id=simple_model")

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
        self.assertIn("setTraineeLinkCopyEnabled", script)
        self.assertIn("交互链接已自动生成", script)
        self.assertIn("copyTraineeLink", script)
        self.assertIn(".trainee-link-modal", styles)

    def test_trainee_start_receive_prompts_for_interaction_link(self):
        html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

        self.assertIn('id="receiveLinkDialog"', html)
        self.assertIn('id="receiveLinkInput"', html)
        self.assertIn("一个链接可供多个学员台", html)
        self.assertIn("openReceiveLinkDialog", script)
        self.assertIn("resolveTeacherInteractionLink", script)
        self.assertIn("/api/trainee/connect", script)
        self.assertIn('api("/api/trainee/connect"', script)
        self.assertIn("state.teacherApiBase = (connection.teacherApiBase || \"\").replace", script)
        self.assertIn("state.teacherModelId = connection.modelId", script)
        self.assertNotIn("state.activeModelId = connection.modelId", script)
        self.assertIn("const activeModelIdBeforeReceive = state.activeModelId", script)
        self.assertIn("selectLocalDefinitionSnapshotForTeacher(connection, teacherSnapshot, activeModelIdBeforeReceive)", script)
        self.assertIn("saveTraineeReceiveState(activeModelIdBeforeReceive, { active: true", script)
        self.assertNotIn("fetch(url.href", script)
        self.assertIn(".receive-link-dialog", styles)


if __name__ == "__main__":
    unittest.main()
