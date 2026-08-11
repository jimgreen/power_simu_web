from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
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

    @staticmethod
    def _seed_measurement_values(service, values):
        service.latest_real_rows = [list(row) for row in service.measurement_rows]
        service.latest_scada_rows = [list(row) for row in service.measurement_rows]
        name_indexes = {str(row[1]): index for index, row in enumerate(service.measurement_rows)}
        for name, value in values.items():
            index = name_indexes[name]
            service.latest_real_rows[index][7] = str(value)
            service.latest_scada_rows[index][7] = str(value)

    def test_external_history_query_returns_multiple_telemetry_and_signal_curves_at_requested_interval(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        signal_values = [1, 0, 0, 1, 0]
        service.control_clock({"action": "start"})
        for minute in range(5):
            self._seed_measurement_values(
                service,
                {
                    "v_wt01_src": 300.0 + minute,
                    "p_load_load_ac_1": 20.0 + minute,
                    "ACGenerator.diesel_300kw.run_stat": signal_values[minute],
                },
            )
            service.step(advance_minutes=1)

        payload = service.external_measurement_history(
            {
                "start_time": "00:01:00",
                "end_time": "00:05:00",
                "interval_seconds": 120,
                "telemetry_names": ["v_wt01_src", "p_load_load_ac_1", "missing_yc"],
                "signal_names": [
                    "ACGenerator.diesel_300kw.run_stat",
                    "ACLoad.load_ac_1.run_stat",
                    "missing_yx",
                ],
            }
        )

        self.assertTrue(payload["model_version"]["signature"])
        self.assertEqual(payload["model_id"], "simple_model")
        self.assertEqual(payload["run_id"], service.clock.run_id)
        self.assertEqual(payload["interval_seconds"], 120)
        self.assertEqual(payload["absolute_minutes"], [1, 3, 5])
        self.assertEqual(payload["simu_times"], ["00:01:00", "00:03:00", "00:05:00"])
        self.assertEqual(
            payload["telemetry_values"],
            [
                [300.0, 20.0, None],
                [302.0, 22.0, None],
                [304.0, 24.0, None],
            ],
        )
        self.assertEqual(payload["signal_values"], [[1, 1, None], [1, 1, None], [1, 1, None]])
        self.assertEqual(payload["telemetry_found"], [True, True, False])
        self.assertEqual(payload["signal_found"], [True, True, False])
        self.assertEqual(
            payload["missing"],
            {"telemetry": ["missing_yc"], "signals": ["missing_yx"]},
        )
        self.assertEqual(len(payload["source_wall_times"]), 3)

        held = service.external_measurement_history(
            {
                "start_absolute_minute": 1,
                "end_absolute_minute": 2,
                "interval_seconds": 30,
                "telemetry_names": ["v_wt01_src"],
            }
        )
        self.assertEqual(held["absolute_minutes"], [1, 1.5, 2])
        self.assertEqual(held["source_absolute_minutes"], [1, 1, 2])
        self.assertEqual(held["telemetry_values"], [[300.0], [300.0], [301.0]])

    def test_external_history_query_is_advertised_and_served_over_http(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.control_clock({"action": "start"})
        self._seed_measurement_values(
            service,
            {
                "v_wt01_src": 301.5,
                "ACGenerator.diesel_300kw.run_stat": 1,
            },
        )
        service.step(advance_minutes=1)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            base = f"http://127.0.0.1:{port}"
            with urlopen(f"{base}/api/trainee-link", timeout=5) as response:
                link = json.loads(response.read().decode("utf-8"))
            history_request = Request(
                base + link["external_api"]["measurement_history"],
                data=json.dumps(
                    {
                        "start_absolute_minute": 1,
                        "end_absolute_minute": 1,
                        "interval_seconds": 60,
                        "telemetry_names": ["v_wt01_src"],
                        "signal_names": ["ACGenerator.diesel_300kw.run_stat"],
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(history_request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()

        self.assertTrue(payload["model_version"]["signature"])
        self.assertEqual(payload["definition_signature"], service.external_telemetry_names()["definition_signature"])
        self.assertEqual(payload["telemetry_values"], [[301.5]])
        self.assertEqual(payload["signal_values"], [[1]])

    def test_external_history_query_rejects_invalid_ranges_with_model_version(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            request = Request(
                f"http://127.0.0.1:{port}/api/external/telemetry/history/query?model_id=simple_model",
                data=json.dumps(
                    {
                        "start_time": "01:00:00",
                        "end_time": "00:00:00",
                        "interval_seconds": 0,
                        "telemetry_names": ["v_wt01_src"],
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as raised:
                urlopen(request, timeout=5)
            body = json.loads(raised.exception.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(body["model_id"], "simple_model")
        self.assertTrue(body["model_version"]["signature"])
        self.assertIn("interval_seconds", body["error"])

    def test_latest_telemetry_values_include_one_time_and_yc_yx_items(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        payload = service.latest_telemetry_values()

        self.assertEqual(payload["model_id"], "simple_model")
        self.assertTrue(payload["model_version"]["signature"])
        self.assertIsInstance(payload["model_version"]["revision"], int)
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
        self.assertTrue(any(item["name"] == "Environment.weather.WIND_SPEED" for item in payload["items"]))
        self.assertTrue(any(item["name"] == "ACGenerator.diesel_300kw.run_stat" for item in payload["items"]))

    def test_selected_telemetry_values_return_requested_yc_and_yx_lists(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        payload = service.selected_telemetry_values(
            {
                "telemetry": ["Environment.weather.WIND_SPEED", "missing_yc"],
                "signals": ["ACGenerator.diesel_300kw.run_stat", "missing_yx"],
            }
        )

        self.assertTrue(payload["model_version"]["signature"])
        self.assertEqual(payload["time"], "00:00:00")
        self.assertEqual(
            [item["name"] for item in payload["telemetry"]],
            ["Environment.weather.WIND_SPEED", "missing_yc"],
        )
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

    def test_external_device_information_combines_topology_parameters_state_and_values(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        payload = service.external_device_information()

        self.assertEqual(payload["model_id"], "simple_model")
        self.assertTrue(payload["model_version"]["signature"])
        self.assertEqual(payload["device_count"], len(payload["devices"]))
        devices = {item["id"]: item for item in payload["devices"]}
        self.assertIn("ACNode.wt01_src", devices)
        self.assertIn("ACBranch.load1_line", devices)
        self.assertIn("ACLoad.load_ac_1", devices)
        load = devices["ACLoad.load_ac_1"]
        self.assertEqual(load["topology"]["node"], 6)
        self.assertIn("pbase", load["parameters"])
        self.assertEqual(load["state"]["run_stat"], 1)
        self.assertIn("p_load_load_ac_1", load["values"])
        self.assertIn("connections", payload["topology"])

    def test_external_array_frames_keep_names_values_and_signatures_aligned(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        names = service.external_telemetry_names()
        values = service.external_telemetry_frame()
        selected = service.selected_external_telemetry_frame(
            {
                "telemetry_names": ["Environment.weather.WIND_SPEED", "missing_yc"],
                "signal_names": ["ACGenerator.diesel_300kw.run_stat", "missing_yx"],
            }
        )

        for payload in (names, values, selected):
            self.assertTrue(payload["model_version"]["signature"])
            self.assertIsInstance(payload["model_version"]["revision"], int)
        self.assertEqual(names["definition_signature"], values["definition_signature"])
        self.assertEqual(len(names["telemetry_names"]), len(values["telemetry_values"]))
        self.assertEqual(len(names["signal_names"]), len(values["signal_values"]))
        self.assertIn("Environment.weather.WIND_SPEED", names["telemetry_names"])
        self.assertIn("p_load_load_ac_1", names["telemetry_names"])
        self.assertIn("ACGenerator.diesel_300kw.run_stat", names["signal_names"])
        self.assertEqual(
            selected["telemetry_names"],
            ["Environment.weather.WIND_SPEED", "missing_yc"],
        )
        self.assertEqual(selected["signal_names"], ["ACGenerator.diesel_300kw.run_stat", "missing_yx"])
        self.assertEqual(selected["telemetry_found"], [True, False])
        self.assertEqual(selected["signal_found"], [True, False])
        self.assertIsNone(selected["telemetry_values"][1])
        self.assertIsNone(selected["signal_values"][1])

    def test_external_control_array_submission_returns_per_point_results(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        names = service.external_control_names()
        result = service.apply_external_control_frame(
            {
                "remote_adjustment_names": ["ACGenerator.diesel_300kw.p_set"],
                "remote_adjustment_values": [60.0],
                "remote_control_names": ["ACGenerator.diesel_300kw.run_stat"],
                "remote_control_values": [1],
                "valid_for_minutes": 10,
            }
        )

        self.assertEqual(names["model_version"], result["model_version"])
        self.assertIn("ACGenerator.diesel_300kw.p_set", names["remote_adjustment_names"])
        self.assertIn("ACGenerator.diesel_300kw.run_stat", names["remote_control_names"])
        self.assertTrue(result["remote_adjustment_results"][0]["accepted"])
        self.assertTrue(result["remote_control_results"][0]["accepted"])
        self.assertEqual(result["remote_adjustment_results"][0]["value"], 60.0)
        self.assertEqual(result["remote_control_results"][0]["value"], 1)

        partially_unknown = service.apply_external_control_frame(
            {
                "remote_adjustment_names": [
                    "ACGenerator.diesel_300kw.p_set",
                    "ACGenerator.missing.p_set",
                ],
                "remote_adjustment_values": [63.0, 99.0],
            }
        )
        self.assertEqual(partially_unknown["accepted"]["remote_adjustments"], 1)
        self.assertEqual(partially_unknown["accepted"]["ignored"], 1)
        self.assertFalse(partially_unknown["remote_adjustment_results"][1]["found"])
        self.assertFalse(partially_unknown["remote_adjustment_results"][1]["accepted"])

        with self.assertRaisesRegex(ValueError, "length"):
            service.apply_external_control_frame(
                {
                    "remote_adjustment_names": ["ACGenerator.diesel_300kw.p_set"],
                    "remote_adjustment_values": [],
                }
            )

    def test_external_model_version_is_stable_for_runtime_values_and_changes_for_definitions(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        before = service.external_model_version()
        service.apply_external_control_frame(
            {
                "remote_adjustment_names": ["ACGenerator.diesel_300kw.p_set"],
                "remote_adjustment_values": [62.0],
            }
        )
        after_runtime_value = service.external_model_version()
        service.update_device_parameters(
            {
                "block_name": "ACBranch",
                "row_key": {"name": "diesel_line", "idx": "2"},
                "changes": {"r": 0.0025},
            }
        )
        after_definition = service.external_model_version()

        self.assertEqual(before, after_runtime_value)
        self.assertGreater(after_definition["revision"], before["revision"])
        self.assertNotEqual(after_definition["signature"], before["signature"])

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

        self.assertTrue(payload["model_version"]["signature"])
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
                        "yc_names": ["Environment.weather.WIND_SPEED"],
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

        self.assertIn("Environment.weather.WIND_SPEED", telemetry["values"])
        self.assertEqual(selected["telemetry"][0]["name"], "Environment.weather.WIND_SPEED")
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

    def test_interaction_link_discovers_and_serves_all_external_operations(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            base = f"http://127.0.0.1:{port}"
            with urlopen(f"{base}/api/trainee-link", timeout=5) as response:
                link = json.loads(response.read().decode("utf-8"))

            paths = link["external_api"]
            fetched = {}
            for key in ("devices", "telemetry_names", "telemetry_values", "control_names"):
                with urlopen(base + paths[key], timeout=5) as response:
                    fetched[key] = json.loads(response.read().decode("utf-8"))

            query_request = Request(
                base + paths["selected_telemetry_values"],
                data=json.dumps(
                    {
                        "telemetry_names": ["Environment.weather.WIND_SPEED"],
                        "signal_names": ["ACGenerator.diesel_300kw.run_stat"],
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(query_request, timeout=5) as response:
                selected = json.loads(response.read().decode("utf-8"))

            control_request = Request(
                base + paths["control_execute"],
                data=json.dumps(
                    {
                        "remote_adjustment_names": ["ACGenerator.diesel_300kw.p_set"],
                        "remote_adjustment_values": [61.0],
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(control_request, timeout=5) as response:
                controlled = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(fetched["devices"]["model_id"], "simple_model")
        for payload in (link, *fetched.values(), selected, controlled):
            self.assertTrue(payload["model_version"]["signature"])
        self.assertIn("Environment.weather.WIND_SPEED", fetched["telemetry_names"]["telemetry_names"])
        self.assertEqual(
            fetched["telemetry_names"]["definition_signature"],
            fetched["telemetry_values"]["definition_signature"],
        )
        self.assertIn("ACGenerator.diesel_300kw.p_set", fetched["control_names"]["remote_adjustment_names"])
        self.assertEqual(
            selected["telemetry_values"],
            [
                fetched["telemetry_values"]["telemetry_values"][
                    fetched["telemetry_names"]["telemetry_names"].index("Environment.weather.WIND_SPEED")
                ]
            ],
        )
        self.assertTrue(controlled["remote_adjustment_results"][0]["accepted"])
        self.assertEqual(controlled["remote_adjustment_results"][0]["value"], 61.0)

    def test_external_control_validation_error_also_returns_model_version(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            request = Request(
                f"http://127.0.0.1:{port}/api/external/controls/execute?model_id=simple_model",
                data=json.dumps(
                    {
                        "remote_adjustment_names": ["ACGenerator.diesel_300kw.p_set"],
                        "remote_adjustment_values": [],
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as raised:
                urlopen(request, timeout=5)
            body = json.loads(raised.exception.read().decode("utf-8"))
            with self.assertRaises(HTTPError) as missing_route:
                urlopen(
                    f"http://127.0.0.1:{port}/api/external/not-found?model_id=simple_model",
                    timeout=5,
                )
            missing_body = json.loads(missing_route.exception.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(raised.exception.code, 400)
        self.assertIn("length mismatch", body["error"])
        self.assertEqual(body["model_id"], "simple_model")
        self.assertTrue(body["model_version"]["signature"])
        self.assertEqual(missing_route.exception.code, 404)
        self.assertEqual(missing_body["model_id"], "simple_model")
        self.assertTrue(missing_body["model_version"]["signature"])

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
