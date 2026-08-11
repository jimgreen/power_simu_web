from __future__ import annotations

import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import simu_loop

from simu.generate_simple_model import write_model_dir
from simu.power_flow_worker import PowerFlowProcessRunner
from simu.server import make_http_server
from simu.service import PolarMicrogridSimulator


class ExternalRealtimeInputsTest(unittest.TestCase):
    def _make_service(self, *, kernel=None, dc_load_name: str = "load_dc_1"):
        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)

        model_file = source / "model.e"
        model_text = model_file.read_text(encoding="utf-8")
        model_text = model_text.replace(
            "<DCGenerator>\n",
            "<DCLoad>\n"
            "@ idx  name       node  pbase  pv0  pv1  pv2  run_stat\n"
            f"# 1    {dc_load_name}  1     0      1    0    0    1\n"
            "</DCLoad>\n"
            "<DCGenerator>\n",
            1,
        )
        model_file.write_text(model_text, encoding="utf-8")

        service = PolarMicrogridSimulator(
            source,
            runtime,
            kernel=kernel or (lambda _config: None),
            model_id="external-realtime-inputs",
            model_name="外部实时输入测试模型",
        )
        service.set_curves(
            {
                "mode": "day",
                "time_step_minutes": 1,
                "point_count": 3,
                "weather": [
                    {
                        "minute": minute,
                        "wind_speed_mps": 5 + minute,
                        "solar_irradiance_w_m2": 100 + minute,
                        "air_temp_c": -20 + minute,
                        "air_pressure_hpa": 960 + minute,
                        "humidity_pct": 70 + minute,
                    }
                    for minute in range(3)
                ],
                "loads": {
                    "load_ac_1": [
                        {"minute": minute, "p_kw": 40 + minute}
                        for minute in range(3)
                    ],
                    dc_load_name: [
                        {"minute": minute, "p_kw": 10 + minute}
                        for minute in range(3)
                    ],
                },
            }
        )
        return workspace, service

    @staticmethod
    def _effective_inputs(service: PolarMicrogridSimulator, minute: float):
        service._prepare_runtime_inputs(minute % 1440.0, minute)
        config = service._make_config(period_seconds=60.0)
        _changed, model_book, _dev_define, weather_values = simu_loop.apply_realtime_input_books(
            config.model_book,
            config.weather_book,
            config.dev_stat_book,
            config.yt_ctrl_book,
            config.dev_define_book,
            config.period_seconds,
            config.mode_book,
        )
        return model_book, weather_values

    @staticmethod
    def _load_power(model_book, block_name: str, load_name: str) -> float:
        row = next(row for row in model_book.data[block_name].data if row.get("name") == load_name)
        return float(row.get("pbase", 0)) * float(row.get("pv0", 0))

    @staticmethod
    def _request_json(url: str, *, payload=None, method: str = "GET"):
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(url, data=data, headers=headers, method=method)
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_service_updates_only_the_next_curve_point_and_next_kernel_input(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.clock.absolute_minute = 1.0
        service.clock.minute = 1.0
        before = copy.deepcopy(service.curves)

        result = service.apply_external_realtime_inputs(
            {
                "weather": {
                    "wind_speed_mps": 9.6,
                    "solar_irradiance_w_m2": 650,
                    "air_temp_c": -12,
                    "air_pressure_hpa": 965,
                    "humidity_pct": 68,
                },
                "loads": {
                    "ACLoad:load_ac_1": 120,
                    "DCLoad:load_dc_1": 35,
                },
            }
        )

        self.assertEqual(result["target_absolute_minute"], 1.0)
        self.assertEqual(result["target_index"], 1)
        self.assertEqual(result["target_point_number"], 2)
        self.assertTrue(result["applies_on_next_power_flow"])
        self.assertEqual(service.curves["weather"][0], before["weather"][0])
        self.assertEqual(service.curves["weather"][2], before["weather"][2])
        self.assertEqual(service.curves["loads"]["load_ac_1"][0], before["loads"]["load_ac_1"][0])
        self.assertEqual(service.curves["loads"]["load_dc_1"][2], before["loads"]["load_dc_1"][2])

        model_book, weather = self._effective_inputs(service, 1.0)
        self.assertEqual(weather["wind_speed_mps"], 9.6)
        self.assertEqual(weather["solar_irradiance_w_m2"], 650.0)
        self.assertEqual(weather["air_temp_c"], -12.0)
        self.assertEqual(weather["air_pressure_hpa"], 965.0)
        self.assertEqual(weather["humidity_pct"], 68.0)
        self.assertAlmostEqual(self._load_power(model_book, "ACLoad", "load_ac_1"), 120.0)
        self.assertAlmostEqual(self._load_power(model_book, "DCLoad", "load_dc_1"), 35.0)

        persisted = json.loads(service.curves_file.read_text(encoding="utf-8"))
        self.assertEqual(persisted, service.curves)
        self.assertNotEqual(service.source_curves_file.read_text(encoding="utf-8"), service.curves_file.read_text(encoding="utf-8"))

    def test_top_level_weather_and_load_list_forms_are_supported(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_external_realtime_inputs(
            {
                "wind_speed_mps": 7.5,
                "solar_irradiance_w_m2": 420,
                "load_values": [
                    {"dev_type": "ACLoad", "dev_name": "load_ac_1", "p_kw": 81},
                    {"dev_type": "DCLoad", "dev_name": "load_dc_1", "value": 23},
                ],
            }
        )

        self.assertEqual(result["weather"], {"wind_speed_mps": 7.5, "solar_irradiance_w_m2": 420.0})
        self.assertEqual(
            result["loads"],
            {"ACLoad:load_ac_1": 81.0, "DCLoad:load_dc_1": 23.0},
        )

    def test_single_point_accepts_and_reports_explicit_count_and_interval(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_external_realtime_inputs(
            {
                "point_count": 1,
                "point_interval_seconds": 60,
                "wind_speed_mps": 13,
            }
        )

        self.assertEqual(result["update_mode"], "single_point")
        self.assertEqual(result["input_point_count"], 1)
        self.assertEqual(result["point_interval_seconds"], 60.0)

    def test_single_point_start_time_selects_the_curve_point_by_timestamp(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        before = copy.deepcopy(service.curves)

        result = service.apply_external_realtime_inputs(
            {
                "start_time": "00:02:00",
                "point_count": 1,
                "point_interval_minutes": 1,
                "wind_speed_mps": 19,
            }
        )

        self.assertEqual(result["target_index"], 2)
        self.assertEqual(service.curves["weather"][2]["wind_speed_mps"], 19.0)
        self.assertEqual(service.curves["weather"][0], before["weather"][0])

    def test_multiple_points_update_only_requested_indices_and_feed_the_kernel(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        before = copy.deepcopy(service.curves)

        result = service.apply_external_realtime_inputs(
            {
                "start_time": "00:00:00",
                "point_count": 2,
                "point_interval_minutes": 1,
                "points": [
                    {
                        "target_index": 0,
                        "weather": {
                            "wind_speed_mps": 8.5,
                            "solar_irradiance_w_m2": 320,
                        },
                        "loads": {"ACLoad:load_ac_1": 51},
                    },
                    {
                        "target_time": "00:01:00",
                        "weather": {
                            "wind_speed_mps": 12.5,
                            "solar_irradiance_w_m2": 520,
                        },
                        "loads": {"ACLoad:load_ac_1": 58},
                    },
                ]
            }
        )

        self.assertEqual(result["update_mode"], "points")
        self.assertEqual(result["updated_indices"], [0, 1])
        self.assertEqual(result["updated_point_count"], 2)
        self.assertEqual(service.curves["weather"][2], before["weather"][2])
        self.assertEqual(service.curves["loads"]["load_ac_1"][2], before["loads"]["load_ac_1"][2])
        self.assertEqual(service.curves["weather"][0]["wind_speed_mps"], 8.5)
        self.assertEqual(service.curves["weather"][1]["solar_irradiance_w_m2"], 520.0)

        model_book, weather = self._effective_inputs(service, 1.0)
        self.assertEqual(weather["wind_speed_mps"], 12.5)
        self.assertEqual(weather["solar_irradiance_w_m2"], 520.0)
        self.assertAlmostEqual(self._load_power(model_book, "ACLoad", "load_ac_1"), 58.0)

    def test_multiple_points_without_targets_follow_start_time_and_interval(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_external_realtime_inputs(
            {
                "start_time": "00:01:00",
                "point_count": 2,
                "point_interval_seconds": 60,
                "points": [
                    {"wind_speed_mps": 15, "loads": {"ACLoad:load_ac_1": 71}},
                    {"wind_speed_mps": 16, "loads": {"ACLoad:load_ac_1": 72}},
                ],
            }
        )

        self.assertEqual(result["updated_indices"], [1, 2])
        self.assertEqual(service.curves["weather"][1]["wind_speed_mps"], 15.0)
        self.assertEqual(service.curves["weather"][2]["wind_speed_mps"], 16.0)
        self.assertEqual(service.curves["loads"]["load_ac_1"][2]["p_kw"], 72.0)

    def test_multiple_points_can_use_an_integer_multiple_of_curve_interval(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        before = copy.deepcopy(service.curves)

        result = service.apply_external_realtime_inputs(
            {
                "start_time": "00:00:00",
                "point_count": 2,
                "point_interval_minutes": 2,
                "points": [
                    {"wind_speed_mps": 21},
                    {"wind_speed_mps": 23},
                ],
            }
        )

        self.assertEqual(result["curve_step_count"], 2)
        self.assertEqual(result["updated_indices"], [0, 2])
        self.assertEqual(service.curves["weather"][1], before["weather"][1])
        self.assertEqual(service.curves["weather"][2]["wind_speed_mps"], 23.0)

    def test_series_updates_full_weather_and_load_curves_in_one_request(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_external_realtime_inputs(
            {
                "start_time": "00:00:00",
                "point_count": 3,
                "point_interval_minutes": 1,
                "series": {
                    "weather": {
                        "wind_speed_mps": [8, 9, 10],
                        "solar_irradiance_w_m2": [200, 300, 400],
                    },
                    "loads": {
                        "ACLoad:load_ac_1": [50, 60, 70],
                        "DCLoad:load_dc_1": [20, 25, 30],
                    },
                }
            }
        )

        self.assertEqual(result["update_mode"], "series")
        self.assertEqual(result["updated_indices"], [0, 1, 2])
        self.assertEqual(result["updated_weather_fields"], ["solar_irradiance_w_m2", "wind_speed_mps"])
        self.assertEqual(result["updated_loads"], ["ACLoad:load_ac_1", "DCLoad:load_dc_1"])
        self.assertEqual(
            [point["wind_speed_mps"] for point in service.curves["weather"]],
            [8.0, 9.0, 10.0],
        )
        self.assertEqual(
            [point["p_kw"] for point in service.curves["loads"]["load_ac_1"]],
            [50.0, 60.0, 70.0],
        )

        model_book, weather = self._effective_inputs(service, 1.0)
        self.assertEqual(weather["wind_speed_mps"], 9.0)
        self.assertAlmostEqual(self._load_power(model_book, "ACLoad", "load_ac_1"), 60.0)
        self.assertAlmostEqual(self._load_power(model_book, "DCLoad", "load_dc_1"), 25.0)

    def test_flat_series_can_patch_a_contiguous_curve_segment(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        before = copy.deepcopy(service.curves)

        result = service.apply_external_realtime_inputs(
            {
                "start_time": "00:01:00",
                "point_count": 2,
                "point_interval_minutes": 1,
                "series": {
                    "wind_speed_mps": [17, 18],
                    "load:DCLoad:load_dc_1": [31, 32],
                },
            }
        )

        self.assertEqual(result["updated_indices"], [1, 2])
        self.assertEqual(service.curves["weather"][0], before["weather"][0])
        self.assertEqual(service.curves["loads"]["load_dc_1"][0], before["loads"]["load_dc_1"][0])
        self.assertEqual(service.curves["weather"][2]["wind_speed_mps"], 18.0)
        self.assertEqual(service.curves["loads"]["load_dc_1"][1]["p_kw"], 31.0)

    def test_invalid_multi_point_or_series_request_is_rejected_atomically(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        invalid_payloads = (
            {
                "start_time": "00:00:00",
                "point_count": 2,
                "point_interval_minutes": 1,
                "points": [
                    {
                        "target_index": 0,
                        "wind_speed_mps": 10,
                        "loads": {"ACLoad:load_ac_1": 20},
                    },
                    {
                        "target_index": 1,
                        "wind_speed_mps": 11,
                        "loads": {"ACLoad:missing": 20},
                    },
                ]
            },
            {
                "start_time": "00:00:00",
                "point_count": 3,
                "point_interval_minutes": 1,
                "series": {
                    "weather": {"wind_speed_mps": [8, -1, 10]},
                }
            },
            {
                "start_time": "00:02:00",
                "point_count": 2,
                "point_interval_minutes": 1,
                "series": {"solar_irradiance_w_m2": [100, 200]},
            },
            {
                "start_time": "00:00:00",
                "point_count": 3,
                "point_interval_minutes": 1,
                "points": [
                    {"wind_speed_mps": 8},
                    {"wind_speed_mps": 9},
                ],
            },
            {
                "start_time": "00:00:00",
                "point_count": 2,
                "point_interval_minutes": 1.5,
                "series": {"wind_speed_mps": [8, 9]},
            },
            {
                "start_time": "00:00:00",
                "point_count": 2,
                "point_interval_minutes": 1,
                "series": {
                    "wind_speed_mps": [8, 9],
                    "solar_irradiance_w_m2": [100],
                },
            },
            {
                "points": [
                    {"wind_speed_mps": 8},
                    {"wind_speed_mps": 9},
                ],
            },
            {
                "start_time": "00:00:00",
                "point_count": 2,
                "point_interval_minutes": 1,
                "points": [
                    {"wind_speed_mps": 8, "loads": {"ACLoad:load_ac_1": 40}},
                    {"wind_speed_mps": 9},
                ],
            },
            {
                "start_time": "00:00:30",
                "point_count": 2,
                "point_interval_minutes": 1,
                "points": [
                    {"wind_speed_mps": 8},
                    {"wind_speed_mps": 9},
                ],
            },
            {
                "start_time": "00:01:00",
                "start_index": 0,
                "point_count": 2,
                "point_interval_minutes": 1,
                "points": [
                    {"wind_speed_mps": 8},
                    {"wind_speed_mps": 9},
                ],
            },
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                before = copy.deepcopy(service.curves)
                before_revision = service._curve_revision
                before_file = service.curves_file.read_bytes()
                with self.assertRaises(ValueError):
                    service.apply_external_realtime_inputs(payload)
                self.assertEqual(service.curves, before)
                self.assertEqual(service._curve_revision, before_revision)
                self.assertEqual(service.curves_file.read_bytes(), before_file)

    def test_invalid_frame_is_rejected_atomically(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        before = copy.deepcopy(service.curves)
        before_revision = service._curve_revision
        before_file = service.curves_file.read_bytes()

        with self.assertRaisesRegex(ValueError, "不存在"):
            service.apply_external_realtime_inputs(
                {
                    "weather": {"wind_speed_mps": 12},
                    "loads": {"ACLoad:missing": 10},
                }
            )

        self.assertEqual(service.curves, before)
        self.assertEqual(service._curve_revision, before_revision)
        self.assertEqual(service.curves_file.read_bytes(), before_file)

    def test_ambiguous_bare_load_name_is_rejected(self):
        workspace, service = self._make_service(dc_load_name="load_ac_1")
        self.addCleanup(workspace.cleanup)

        with self.assertRaisesRegex(ValueError, "不唯一"):
            service.apply_external_realtime_inputs({"loads": {"load_ac_1": 50}})

    def test_explicit_load_type_overrides_a_legacy_bare_curve_for_only_that_device(self):
        workspace, service = self._make_service(dc_load_name="load_ac_1")
        self.addCleanup(workspace.cleanup)

        service.apply_external_realtime_inputs({"loads": {"ACLoad:load_ac_1": 55}})
        model_book, _weather = self._effective_inputs(service, 0.0)

        self.assertAlmostEqual(self._load_power(model_book, "ACLoad", "load_ac_1"), 55.0)
        self.assertAlmostEqual(self._load_power(model_book, "DCLoad", "load_ac_1"), 10.0)

    def test_partial_curve_uses_clock_grid_for_the_next_missing_point(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.curves["weather"] = service.curves["weather"][:1]
        service.curves["loads"]["load_ac_1"] = service.curves["loads"]["load_ac_1"][:1]
        service.clock.absolute_minute = 2.0
        service.clock.minute = 2.0

        result = service.apply_external_realtime_inputs(
            {"wind_speed_mps": 16, "loads": {"ACLoad:load_ac_1": 91}}
        )

        self.assertEqual(result["target_index"], 2)
        self.assertEqual(service.curves["weather"][2]["wind_speed_mps"], 16.0)
        self.assertEqual(service.curves["loads"]["load_ac_1"][2]["p_kw"], 91.0)

    def test_non_finite_and_out_of_range_values_are_rejected(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        invalid_payloads = (
            ({"wind_speed_mps": -1}, "wind_speed_mps"),
            ({"solar_irradiance_w_m2": -1}, "solar_irradiance_w_m2"),
            ({"humidity_pct": 101}, "humidity_pct"),
            ({"air_pressure_hpa": 0}, "air_pressure_hpa"),
            ({"loads": {"ACLoad:load_ac_1": -1}}, "ACLoad:load_ac_1"),
            ({"air_temp_c": float("inf")}, "air_temp_c"),
        )
        for payload, field in invalid_payloads:
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, field):
                    service.apply_external_realtime_inputs(payload)

    def test_schema_lists_weather_fields_and_canonical_load_keys(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        schema = service.external_realtime_input_schema()

        self.assertEqual(schema["model_id"], service.model_id)
        self.assertEqual(
            [item["key"] for item in schema["weather_fields"]],
            [
                "wind_speed_mps",
                "solar_irradiance_w_m2",
                "air_temp_c",
                "air_pressure_hpa",
                "humidity_pct",
            ],
        )
        self.assertEqual(
            {item["key"] for item in schema["loads"]},
            {"ACLoad:load_ac_1", "DCLoad:load_dc_1"},
        )
        self.assertEqual(schema["target_point"]["absolute_minute"], service.clock.absolute_minute)
        self.assertEqual(
            set(schema["request_formats"]),
            {"single_point", "multiple_points", "series"},
        )
        self.assertEqual(schema["curve_contract"]["point_count"], 3)
        self.assertEqual(schema["curve_contract"]["point_interval_seconds"], 60.0)
        self.assertIn("start_time", schema["curve_contract"]["start_fields"])

    def test_update_waits_for_in_flight_solve_and_targets_the_following_point(self):
        started = threading.Event()
        release = threading.Event()
        update_done = threading.Event()

        def blocking_kernel(_config):
            started.set()
            self.assertTrue(release.wait(2.0))
            return None

        workspace, service = self._make_service(kernel=blocking_kernel)
        self.addCleanup(workspace.cleanup)
        step_thread = threading.Thread(target=service.step, daemon=True)
        step_thread.start()
        self.assertTrue(started.wait(2.0))

        result_holder = {}

        def update():
            result_holder["result"] = service.apply_external_realtime_inputs(
                {"wind_speed_mps": 18, "loads": {"ACLoad:load_ac_1": 88}}
            )
            update_done.set()

        update_thread = threading.Thread(target=update, daemon=True)
        update_thread.start()
        self.assertFalse(update_done.wait(0.1))
        release.set()
        step_thread.join(timeout=3.0)
        update_thread.join(timeout=3.0)

        self.assertFalse(step_thread.is_alive())
        self.assertFalse(update_thread.is_alive())
        self.assertEqual(service.latest_compute["status"], "ok")
        self.assertEqual(service.clock.step_count, 1)
        self.assertEqual(result_holder["result"]["target_absolute_minute"], 1.0)
        self.assertEqual(result_holder["result"]["target_index"], 1)
        self.assertEqual(service.curves["weather"][1]["wind_speed_mps"], 18.0)

    def test_next_boundary_survives_power_flow_process_isolation(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        runner = PowerFlowProcessRunner(max_workers=1)
        self.addCleanup(runner.close)
        service.apply_external_realtime_inputs(
            {
                "weather": {"wind_speed_mps": 14, "solar_irradiance_w_m2": 510},
                "loads": {"ACLoad:load_ac_1": 77, "DCLoad:load_dc_1": 21},
            }
        )

        service._prepare_runtime_inputs(0.0, 0.0)
        outcome = runner.run(service._make_config(period_seconds=60.0))

        self.assertAlmostEqual(self._load_power(outcome.result.model_book, "ACLoad", "load_ac_1"), 77.0)
        self.assertAlmostEqual(self._load_power(outcome.result.model_book, "DCLoad", "load_dc_1"), 21.0)

    def test_series_boundary_survives_power_flow_process_isolation(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        runner = PowerFlowProcessRunner(max_workers=1)
        self.addCleanup(runner.close)
        service.clock.absolute_minute = 1.0
        service.clock.minute = 1.0
        service.apply_external_realtime_inputs(
            {
                "start_time": "00:00:00",
                "point_count": 3,
                "point_interval_minutes": 1,
                "series": {
                    "wind_speed_mps": [11, 12, 13],
                    "load:ACLoad:load_ac_1": [61, 62, 63],
                }
            }
        )

        service._prepare_runtime_inputs(1.0, 1.0)
        outcome = runner.run(service._make_config(period_seconds=60.0))

        self.assertAlmostEqual(self._load_power(outcome.result.model_book, "ACLoad", "load_ac_1"), 62.0)

    def test_http_schema_update_and_trainee_link_advertisement(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            link = self._request_json(f"{base}/api/trainee-link")
            self.assertEqual(
                link["external_api"]["realtime_inputs"],
                f"/api/external/realtime-inputs?model_id={service.model_id}",
            )
            schema = self._request_json(base + link["external_api"]["realtime_inputs"])
            result = self._request_json(
                base + link["external_api"]["realtime_inputs"],
                payload={
                    "weather": {"wind_speed_mps": 11, "solar_irradiance_w_m2": 333},
                    "loads": {"ACLoad:load_ac_1": 66},
                },
                method="POST",
            )
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(schema["loads"][0]["dev_type"], "ACLoad")
        self.assertEqual(result["loads"]["ACLoad:load_ac_1"], 66.0)
        self.assertEqual(service.curves["weather"][0]["wind_speed_mps"], 11.0)

    def test_http_accepts_multiple_points_and_series_payloads(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            path = f"/api/external/realtime-inputs?model_id={service.model_id}"
            points_result = self._request_json(
                base + path,
                payload={
                    "start_time": "00:00:00",
                    "point_count": 2,
                    "point_interval_minutes": 1,
                    "points": [
                        {"target_index": 0, "wind_speed_mps": 20},
                        {"target_index": 1, "wind_speed_mps": 21},
                    ]
                },
                method="POST",
            )
            series_result = self._request_json(
                base + path,
                payload={
                    "start_time": "00:00:00",
                    "point_count": 3,
                    "point_interval_seconds": 60,
                    "series": {
                        "loads": {"ACLoad:load_ac_1": [80, 81, 82]},
                    }
                },
                method="POST",
            )
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(points_result["update_mode"], "points")
        self.assertEqual(points_result["updated_indices"], [0, 1])
        self.assertEqual(series_result["update_mode"], "series")
        self.assertEqual(service.curves["loads"]["load_ac_1"][2]["p_kw"], 82.0)

    def test_http_validation_error_includes_model_metadata_and_does_not_apply(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        before = copy.deepcopy(service.curves)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            with self.assertRaises(HTTPError) as raised:
                self._request_json(
                    f"{base}/api/external/realtime-inputs?model_id={service.model_id}",
                    payload={"weather": {"wind_speed_mps": -1}},
                    method="POST",
                )
            body = json.loads(raised.exception.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(body["model_id"], service.model_id)
        self.assertTrue(body["model_version"]["signature"])
        self.assertIn("wind_speed_mps", body["error"])
        self.assertEqual(service.curves, before)

    def test_trainee_server_rejects_realtime_input_route_instead_of_proxying_it(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(
            ("127.0.0.1", 0),
            service,
            role="trainee",
            sim_url="http://127.0.0.1:1",
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            for method, payload in (("GET", None), ("POST", {"wind_speed_mps": 8})):
                with self.subTest(method=method):
                    with self.assertRaises(HTTPError) as raised:
                        self._request_json(
                            f"{base}/api/external/realtime-inputs?model_id={service.model_id}",
                            payload=payload,
                            method=method,
                        )
                    self.assertEqual(raised.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
