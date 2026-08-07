from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from simu.generate_simple_model import write_model_dir
from simu.server import make_http_server
from simu.service import PolarMicrogridSimulator


ROOT = Path(__file__).resolve().parents[1]


class SimulatorCommandDeleteTest(unittest.TestCase):
    def _make_service(self) -> PolarMicrogridSimulator:
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        return PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)

    def _serve(self, service: PolarMicrogridSimulator, role: str = "simulator") -> str:
        server = make_http_server(("127.0.0.1", 0), service, role=role)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    @staticmethod
    def _post(base: str, path: str, payload: dict) -> tuple[int, dict]:
        request = Request(
            f"{base}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _control_value(service: PolarMicrogridSimulator, name: str):
        return service.latest_control_values()["values"][name]

    def test_delete_effective_adjustment_reverts_only_that_point_and_accepts_later_command(self):
        service = self._make_service()
        service.apply_student_commands(
            {
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20},
                    {
                        "dev_type": "ACGenerator",
                        "dev_name": "diesel_300kw",
                        "set_type": "p_set",
                        "set_value": 60,
                    },
                ]
            },
            source="trainee-ui",
        )

        result = service.delete_active_commands(
            {"commands": [{"name": "ESS.ess01.p_set"}]},
            source="simulator-ui",
        )

        self.assertEqual(result["remote_adjustments"], 1)
        self.assertEqual(result["remote_controls"], 0)
        self.assertEqual(result["missing"], 0)
        self.assertEqual(self._control_value(service, "ESS.ess01.p_set"), 10)
        self.assertEqual(self._control_value(service, "ACGenerator.diesel_300kw.p_set"), 60)

        restarted = PolarMicrogridSimulator(
            service.sim_dir,
            service.runtime_dir,
            kernel=lambda _config: None,
        )
        self.assertEqual(self._control_value(restarted, "ESS.ess01.p_set"), 10)
        self.assertEqual(self._control_value(restarted, "ACGenerator.diesel_300kw.p_set"), 60)

        restarted.apply_student_commands(
            {
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 25}
                ]
            },
            source="trainee-ui",
        )

        self.assertEqual(self._control_value(restarted, "ESS.ess01.p_set"), 25)
        self.assertTrue(
            {
                item["name"]: item for item in restarted.latest_control_values()["items"]
            }["ESS.ess01.p_set"]["active"]
        )

    def test_delete_effective_remote_control_reverts_to_default_without_deleting_definition(self):
        service = self._make_service()
        service.apply_student_commands(
            {
                "run_status": [
                    {"dev_type": "ACGenerator", "dev_name": "diesel_300kw", "run_stat": 0},
                    {"dev_type": "ACGenerator", "dev_name": "wt01_10kw", "run_stat": 0},
                ]
            },
            source="trainee-ui",
        )

        result = service.delete_active_commands(
            {"commands": [{"name": "ACGenerator.diesel_300kw.run_stat"}]},
            source="simulator-ui",
        )

        self.assertEqual(result["remote_controls"], 1)
        self.assertEqual(result["remote_adjustments"], 0)
        self.assertEqual(self._control_value(service, "ACGenerator.diesel_300kw.run_stat"), 1)
        self.assertEqual(self._control_value(service, "ACGenerator.wt01_10kw.run_stat"), 0)
        self.assertIn(
            ("ACGenerator", "diesel_300kw"),
            service._defined_run_control_fields(),
        )

    def test_simulator_delete_endpoint_is_role_restricted(self):
        simulator_service = self._make_service()
        simulator_service.apply_student_commands(
            {
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 20}
                ]
            },
            source="trainee-ui",
        )
        simulator_base = self._serve(simulator_service, role="simulator")

        status, result = self._post(
            simulator_base,
            "/api/simulator/commands/delete",
            {"commands": [{"name": "ESS.ess01.p_set"}]},
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["remote_adjustments"], 1)
        self.assertEqual(self._control_value(simulator_service, "ESS.ess01.p_set"), 10)

        trainee_service = self._make_service()
        trainee_base = self._serve(trainee_service, role="trainee")
        with self.assertRaises(HTTPError) as caught:
            self._post(
                trainee_base,
                "/api/simulator/commands/delete",
                {"commands": [{"name": "ESS.ess01.p_set"}]},
            )
        self.assertEqual(caught.exception.code, 404)

    def test_simulator_command_table_exposes_delete_only_for_active_commands(self):
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "simu" / "web" / "simulator" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("runtimeCommandDeleteSending: new Set()", script)
        self.assertIn("function deleteRuntimeCommand", script)
        self.assertIn('api("/api/simulator/commands/delete"', script)
        self.assertIn("data-runtime-command-delete-name", script)
        self.assertIn('row.active && !sending ? "" : "disabled"', script)
        self.assertIn("runtime-command-delete-button", styles)


if __name__ == "__main__":
    unittest.main()
