from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from simu.server import make_http_server
from simu.service import PolarMicrogridSimulator
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


ROOT = Path(__file__).resolve().parents[1]


class ExternalRealtimeInterfacesTest(unittest.TestCase):
    REDUNDANT_FIELDS = {
        "point_type",
        "category",
        "dev_type",
        "dev_name",
        "meas_type",
        "control_type",
        "set_type",
        "command_kind",
        "weight",
        "text",
        "source",
    }

    def _make_service(self):
        workspace = tempfile.TemporaryDirectory()
        service = PolarMicrogridSimulator(
            SIMPLE_MODEL_SOURCE,
            Path(workspace.name) / "runtime",
            model_id="simple_model",
            model_name="简单模型",
            kernel=lambda _config: None,
        )
        return workspace, service

    def test_latest_telemetry_values_include_one_time_and_yc_yx_items(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        payload = service.latest_telemetry_values()

        self.assertEqual(payload["model_id"], "simple_model")
        self.assertEqual(payload["time"], "00:00:00")
        self.assertIn("items", payload)
        self.assertIn("values", payload)
        for item in payload["items"]:
            self.assertIn("name", item)
            self.assertIn("value", item)
            self.assertIn("updated_wall_time", item)
            self.assertIn("updated_simu_time", item)
            self.assertIn("updated_absolute_minute", item)
            self.assertIn("valid", item)
            self.assertFalse(self.REDUNDANT_FIELDS & set(item))
        self.assertTrue(any(item["name"] == "weather_wind_speed" for item in payload["items"]))
        self.assertTrue(any(item["name"] == "ACGenerator.diesel_300kw.run_stat" for item in payload["items"]))

    def test_selected_telemetry_values_return_requested_yc_and_yx_lists(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        payload = service.selected_telemetry_values(
            {
                "telemetry": ["weather_wind_speed", "missing_yc"],
                "signals": ["ACGenerator.diesel_300kw.run_stat", "missing_yx"],
            }
        )

        self.assertEqual(payload["time"], "00:00:00")
        self.assertEqual([item["name"] for item in payload["telemetry"]], ["weather_wind_speed", "missing_yc"])
        self.assertEqual([item["name"] for item in payload["signals"]], ["ACGenerator.diesel_300kw.run_stat", "missing_yx"])
        self.assertTrue(payload["telemetry"][0]["found"])
        self.assertFalse(payload["telemetry"][1]["found"])
        self.assertTrue(payload["signals"][0]["found"])
        self.assertFalse(payload["signals"][1]["found"])
        self.assertEqual(payload["missing"], {"telemetry": ["missing_yc"], "signals": ["missing_yx"]})
        for item in payload["items"]:
            self.assertIn("name", item)
            self.assertIn("value", item)
            self.assertIn("updated_wall_time", item)
            self.assertIn("updated_simu_time", item)
            self.assertFalse(self.REDUNDANT_FIELDS & set(item))

    def test_latest_control_values_include_remote_control_and_adjustment_update_times(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.apply_external_control_values(
            {
                "values": {
                    "ACGenerator.diesel_300kw.run_stat": 1,
                    "ACGenerator.diesel_300kw.p_set": 66.6,
                },
                "valid_for_minutes": 10,
            }
        )
        payload = service.latest_control_values()

        by_name = {item["name"]: item for item in payload["items"]}
        self.assertIn("ACGenerator.diesel_300kw.run_stat", by_name)
        self.assertIn("ACGenerator.diesel_300kw.p_set", by_name)
        self.assertEqual(by_name["ACGenerator.diesel_300kw.p_set"]["value"], 66.6)
        self.assertEqual(by_name["ACGenerator.diesel_300kw.p_set"]["updated_simu_time"], "00:00:00")
        self.assertTrue(by_name["ACGenerator.diesel_300kw.p_set"]["active"])
        for item in payload["items"]:
            self.assertIn("name", item)
            self.assertIn("value", item)
            self.assertIn("updated_wall_time", item)
            self.assertIn("updated_simu_time", item)
            self.assertIn("updated_absolute_minute", item)
            self.assertIn("active", item)
            self.assertFalse(self.REDUNDANT_FIELDS & set(item))

    def test_external_control_endpoint_accepts_json_values_and_returns_update_result(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            base = f"http://127.0.0.1:{port}"
            with urlopen(f"{base}/api/external/telemetry?model_id=simple_model", timeout=5) as response:
                telemetry = json.loads(response.read().decode("utf-8"))
            query_request = Request(
                f"{base}/api/external/telemetry/query?model_id=simple_model",
                data=json.dumps(
                    {
                        "yc_names": ["weather_wind_speed"],
                        "yx_names": ["ACGenerator.diesel_300kw.run_stat"],
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(query_request, timeout=5) as response:
                selected = json.loads(response.read().decode("utf-8"))
            with urlopen(f"{base}/api/external/controls?model_id=simple_model", timeout=5) as response:
                before_controls = json.loads(response.read().decode("utf-8"))
            request = Request(
                f"{base}/api/external/controls?model_id=simple_model",
                data=json.dumps(
                    {
                        "values": {"ACGenerator.diesel_300kw.p_set": 55.5},
                        "valid_for_minutes": 10,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                result = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()

        self.assertIn("weather_wind_speed", telemetry["values"])
        self.assertEqual(selected["telemetry"][0]["name"], "weather_wind_speed")
        self.assertEqual(selected["signals"][0]["name"], "ACGenerator.diesel_300kw.run_stat")
        self.assertTrue(selected["telemetry"][0]["found"])
        self.assertTrue(selected["signals"][0]["found"])
        self.assertIn("ACGenerator.diesel_300kw.p_set", before_controls["values"])
        self.assertEqual(result["accepted"]["remote_adjustments"], 1)
        self.assertEqual(result["accepted"]["remote_controls"], 0)
        self.assertEqual(result["control_values"]["values"]["ACGenerator.diesel_300kw.p_set"], 55.5)
        self.assertNotIn("result", result)
        self.assertEqual(result["updated_items"][0]["name"], "ACGenerator.diesel_300kw.p_set")
        self.assertEqual(result["updated_items"][0]["value"], 55.5)
        self.assertIn("updated_wall_time", result["updated_items"][0])
        self.assertIn("updated_simu_time", result["updated_items"][0])
        for collection in (
            telemetry["items"],
            selected["items"],
            before_controls["items"],
            result["updated_items"],
            result["control_values"]["items"],
        ):
            for item in collection:
                self.assertFalse(self.REDUNDANT_FIELDS & set(item))

    def test_external_control_endpoint_cancels_named_active_control_values(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            base = f"http://127.0.0.1:{port}"
            update_request = Request(
                f"{base}/api/external/controls?model_id=simple_model",
                data=json.dumps(
                    {
                        "values": {"ACGenerator.diesel_300kw.p_set": 55.5},
                        "valid_for_minutes": 10,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(update_request, timeout=5) as response:
                updated = json.loads(response.read().decode("utf-8"))
            cancel_request = Request(
                f"{base}/api/external/controls?model_id=simple_model",
                data=json.dumps(
                    {
                        "cancel_commands": [
                            {"name": "ACGenerator.diesel_300kw.p_set"}
                        ],
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(cancel_request, timeout=5) as response:
                cancelled = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(updated["accepted"]["remote_adjustments"], 1)
        self.assertEqual(cancelled["cancelled"]["remote_adjustments"], 1)
        self.assertEqual(cancelled["cancelled"]["remote_controls"], 0)
        self.assertEqual(cancelled["cancelled"]["missing"], 0)
        by_name = {item["name"]: item for item in cancelled["control_values"]["items"]}
        self.assertFalse(by_name["ACGenerator.diesel_300kw.p_set"]["active"])
        for item in cancelled["cancelled_items"]:
            self.assertIn("name", item)
            self.assertIn("cancelled", item)
            self.assertIn("updated_wall_time", item)
            self.assertIn("updated_simu_time", item)
            self.assertFalse(self.REDUNDANT_FIELDS & set(item))


if __name__ == "__main__":
    unittest.main()
