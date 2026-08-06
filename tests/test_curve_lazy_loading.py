from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


class CurveLazyLoadingTest(unittest.TestCase):
    def _make_service(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None, model_id="simple")
        service.set_curves(
            {
                "mode": "day",
                "time_step_minutes": 1,
                "point_count": 3,
                "weather": [
                    {"minute": 0, "wind_speed_mps": 1, "solar_irradiance_w_m2": 10, "air_temp_c": -20},
                    {"minute": 1, "wind_speed_mps": 2, "solar_irradiance_w_m2": 20, "air_temp_c": -19},
                    {"minute": 2, "wind_speed_mps": 3, "solar_irradiance_w_m2": 30, "air_temp_c": -18},
                ],
                "loads": {
                    "load_a": [
                        {"minute": 0, "p_kw": 100},
                        {"minute": 1, "p_kw": 101},
                        {"minute": 2, "p_kw": 102},
                    ],
                    "load_b": [
                        {"minute": 0, "p_kw": 200},
                        {"minute": 1, "p_kw": 201},
                        {"minute": 2, "p_kw": 202},
                    ],
                },
            }
        )
        return workspace, service

    def test_curve_summary_omits_full_series_points(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        summary = service.curves_summary()

        self.assertEqual(summary["mode"], "day")
        self.assertEqual(summary["point_count"], 3)
        self.assertEqual(summary["time_step_minutes"], 1)
        self.assertEqual([item["key"] for item in summary["environment"]], [
            "wind_speed_mps",
            "solar_irradiance_w_m2",
            "air_temp_c",
        ])
        self.assertEqual([item["name"] for item in summary["loads"]], ["load_a", "load_b"])
        self.assertNotIn("weather", summary)
        self.assertNotIn("series", summary["loads"][0])

    def test_curve_series_returns_only_requested_curves(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        payload = service.curves_series(["wind_speed_mps", "load:load_b"])

        self.assertEqual(payload["mode"], "day")
        self.assertEqual(payload["series"]["wind_speed_mps"], [1, 2, 3])
        self.assertEqual(payload["series"]["load:load_b"], [200, 201, 202])
        self.assertNotIn("solar_irradiance_w_m2", payload["series"])
        self.assertNotIn("load:load_a", payload["series"])

    def test_curve_series_patch_updates_only_requested_curve(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.update_curve_series(
            {
                "mode": "day",
                "series": {
                    "wind_speed_mps": [7, 8, 9],
                },
            }
        )

        self.assertEqual(result["updated"], ["wind_speed_mps"])
        self.assertEqual(service.curves["weather"][0]["wind_speed_mps"], 7)
        self.assertEqual(service.curves["weather"][0]["solar_irradiance_w_m2"], 10)
        self.assertEqual(service.curves["loads"]["load_a"][0]["p_kw"], 100)

    def test_curve_summary_is_not_blocked_by_running_simulation_lock(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        completed = threading.Event()

        def read_summary():
            service.curves_summary()
            completed.set()

        with service.lock:
            thread = threading.Thread(target=read_summary, daemon=True)
            thread.start()
            finished_while_simulation_lock_was_held = completed.wait(0.2)

        thread.join(timeout=1)
        self.assertTrue(
            finished_while_simulation_lock_was_held,
            "曲线摘要读取不应等待潮流计算持有的主仿真锁",
        )

    def test_curve_series_is_not_blocked_by_running_simulation_lock(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        completed = threading.Event()

        def read_series():
            service.curves_series(["wind_speed_mps"])
            completed.set()

        with service.lock:
            thread = threading.Thread(target=read_series, daemon=True)
            thread.start()
            finished_while_simulation_lock_was_held = completed.wait(0.2)

        thread.join(timeout=1)
        self.assertTrue(
            finished_while_simulation_lock_was_held,
            "曲线数据读取不应等待潮流计算持有的主仿真锁",
        )

    def test_curve_lazy_http_endpoints(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        port = server.server_address[1]
        with urlopen(f"http://127.0.0.1:{port}/api/curves/summary", timeout=5) as response:
            summary = json.loads(response.read().decode("utf-8"))
        self.assertIn("environment", summary)
        self.assertNotIn("weather", summary)

        keys = quote("wind_speed_mps,load:load_b", safe="")
        with urlopen(f"http://127.0.0.1:{port}/api/curves/series?keys={keys}", timeout=5) as response:
            series = json.loads(response.read().decode("utf-8"))
        self.assertEqual(sorted(series["series"]), ["load:load_b", "wind_speed_mps"])

        body = json.dumps({"series": {"load:load_b": [210, 211, 212]}}).encode("utf-8")
        request = Request(
            f"http://127.0.0.1:{port}/api/curves/series",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))
        self.assertEqual(result["updated"], ["load:load_b"])
        self.assertEqual(service.curves["loads"]["load_b"][0]["p_kw"], 210)

    def test_simulator_curve_page_uses_lazy_curve_endpoints(self):
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn('"curves": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"]', script)
        self.assertIn('"overview": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"]', script)
        self.assertIn('"faults": ["files", "source_files", "work_files", "definitions", "settings", "device_parameters"]', script)
        self.assertNotIn('"overview": ["files", "source_files", "work_files", "definitions", "curves"', script)
        self.assertNotIn('"faults": ["files", "source_files", "work_files", "definitions", "curves"', script)
        self.assertIn("const boundary = snapshot.curve_boundary", script)
        self.assertIn("async function loadCurveSummary", script)
        self.assertIn("async function ensureCurveSeriesLoaded", script)
        self.assertIn('api(`/api/curves/series?keys=${encodeURIComponent(keysToFetch.join(","))}`, {', script)
        self.assertIn('api("/api/curves/series"', script)
        self.assertIn("const modelId = state.activeModelId;", script)
        self.assertIn("loadCurveSummary(modelId)", script)

    def test_curve_page_waits_for_model_catalog_before_lazy_fetching(self):
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        render_block = script.split("function renderCurveEditor(force", 1)[1].split(
            "function generateCurves",
            1,
        )[0]

        self.assertIn("modelsLoaded: false", script)
        self.assertIn("if (!state.modelsLoaded)", render_block)
        self.assertLess(render_block.index("if (!state.modelsLoaded)"), render_block.index("startCurveEditorLoad(modelId)"))

    def test_curve_page_model_switch_boundary_snapshot_does_not_skip_curve_summary_reload(self):
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        render_block = script.split("function renderCurveEditor(force", 1)[1].split(
            "function generateCurves",
            1,
        )[0]
        boundary_block = script.split("} else if (snapshot.curve_boundary?.mode)", 1)[1].split(
            "const solverInfo",
            1,
        )[0]
        apply_summary_block = script.split("function applyCurveSummary", 1)[1].split(
            "async function loadCurveSummary",
            1,
        )[0]

        self.assertIn("function curveSummaryHasCatalog", script)
        self.assertIn("!curveSummaryHasCatalog(state.curveSummary)", render_block)
        self.assertNotIn("state.curveSummaryLoadedModelId = state.activeModelId", boundary_block)
        self.assertIn('state.curveSummaryLoadedModelId = "";', boundary_block)
        self.assertNotIn('state.curvesLoadedModelId = modelId || "loaded";', apply_summary_block)

    def test_simulator_curve_page_bounds_requests_and_recovers_from_failures(self):
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function frontendRequestTimeoutMs", script)
        self.assertIn("function curveRequestTimeoutMs", script)
        self.assertIn('activeRuntimeSetting("curve_request_timeout_seconds")', script)
        self.assertIn("new AbortController()", script)
        self.assertIn("function cancelCurveRequests", script)
        self.assertIn("function startCurveEditorLoad", script)
        self.assertIn("function renderCurveEditorError", script)
        self.assertIn("data-curve-retry", script)
        self.assertNotIn("loadCurveSummary(modelId).then(() =>", script)

    def test_simulator_curve_table_uses_virtual_rows_and_skips_unchanged_refreshes(self):
        script = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        table_block = script.split("function renderHourlyTable", 1)[1].split(
            "function applyHourlyTableEdit",
            1,
        )[0]
        render_block = script.split("function renderCurveEditor(force", 1)[1].split(
            "function generateCurves",
            1,
        )[0]

        self.assertIn("virtualTableWindow", table_block)
        self.assertIn("renderVirtualSpacerRow", table_block)
        self.assertIn("data-virtual-table", table_block)
        self.assertNotIn("Array.from({ length: pointCount }, (_unused, index) => `", table_block)
        self.assertIn("lastCurveEditorRenderKey", render_block)

    def test_trainee_curve_page_uses_virtual_rows_and_skips_unchanged_refreshes(self):
        script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")
        table_block = script.split("function renderCurveDisplayTable", 1)[1].split(
            "function renderCurveDisplay",
            1,
        )[0]
        render_block = script.split("function renderCurveDisplay(snapshot", 1)[1].split(
            "function pointerPositionOnCurveDisplayCanvas",
            1,
        )[0]

        self.assertIn("function frontendRequestTimeoutMs", script)
        self.assertIn('activeRuntimeSetting("frontend_request_timeout_seconds")', script)
        self.assertIn("virtualTableWindow", table_block)
        self.assertIn("renderVirtualSpacerRow", table_block)
        self.assertIn("data-virtual-table", table_block)
        self.assertNotIn("Array.from({ length: config.pointCount }, (_unused, index) => `", table_block)
        self.assertIn("lastCurveDisplayRenderKey", render_block)


if __name__ == "__main__":
    unittest.main()
