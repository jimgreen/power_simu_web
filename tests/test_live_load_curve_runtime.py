from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path


class LiveLoadCurveRuntimeTest(unittest.TestCase):
    def _make_service(self, *, kernel=None):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

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
            "# 1    load_dc_1  1     0      1    0    0    1\n"
            "</DCLoad>\n"
            "<DCGenerator>\n",
            1,
        )
        model_file.write_text(model_text, encoding="utf-8")

        service = PolarMicrogridSimulator(
            source,
            runtime,
            kernel=kernel or (lambda _config: None),
            model_id="live-load-curves",
        )
        service.set_curves(
            {
                "mode": "day",
                "time_step_minutes": 1,
                "point_count": 2,
                "weather": [
                    {"minute": 0, "wind_speed_mps": 8, "solar_irradiance_w_m2": 0, "air_temp_c": -20},
                    {"minute": 1, "wind_speed_mps": 8, "solar_irradiance_w_m2": 0, "air_temp_c": -20},
                ],
                "loads": {
                    "load_ac_1": [
                        {"minute": 0, "p_kw": 45},
                        {"minute": 1, "p_kw": 46},
                    ],
                    "load_dc_1": [
                        {"minute": 0, "p_kw": 12},
                        {"minute": 1, "p_kw": 13},
                    ],
                },
            }
        )
        return workspace, service

    @staticmethod
    def _effective_model(service, *, minute: float = 0.0):
        import simu_loop

        service.clock.absolute_minute = minute
        service.clock.minute = minute % 1440
        service._prepare_runtime_inputs(service.clock.minute, minute)
        config = service._make_config(period_seconds=60.0)
        _changed, model_book, _dev_define, _weather = simu_loop.apply_realtime_input_books(
            config.model_book,
            config.weather_book,
            config.dev_stat_book,
            config.yt_ctrl_book,
            config.dev_define_book,
            config.period_seconds,
            config.mode_book,
        )
        return model_book

    @staticmethod
    def _load_power(model_book, block_name: str, load_name: str) -> float:
        row = next(row for row in model_book.data[block_name].data if row.get("name") == load_name)
        return float(row.get("pbase", 0)) * float(row.get("pv0", 0))

    def test_ac_and_dc_load_curves_are_applied_per_device_to_the_next_kernel_input(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        model_book = self._effective_model(service)

        self.assertAlmostEqual(self._load_power(model_book, "ACLoad", "load_ac_1"), 45.0)
        self.assertAlmostEqual(self._load_power(model_book, "DCLoad", "load_dc_1"), 12.0)
        ac_row = next(row for row in model_book.data["ACLoad"].data if row.get("name") == "load_ac_1")
        self.assertAlmostEqual(float(ac_row["qbase"]) * float(ac_row["qv0"]), 15.0)

    def test_online_curve_patch_changes_the_very_next_kernel_input(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        before = self._effective_model(service)
        service.update_curve_series(
            {
                "series": {
                    "load:load_ac_1": [72, 73],
                    "load:load_dc_1": [18, 19],
                }
            }
        )
        after = self._effective_model(service)

        self.assertAlmostEqual(self._load_power(before, "ACLoad", "load_ac_1"), 45.0)
        self.assertAlmostEqual(self._load_power(before, "DCLoad", "load_dc_1"), 12.0)
        self.assertAlmostEqual(self._load_power(after, "ACLoad", "load_ac_1"), 72.0)
        self.assertAlmostEqual(self._load_power(after, "DCLoad", "load_dc_1"), 18.0)

    def test_per_device_load_curve_boundary_survives_power_flow_process_isolation(self):
        from simu.power_flow_worker import PowerFlowProcessRunner

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        runner = PowerFlowProcessRunner(max_workers=1)
        self.addCleanup(runner.close)

        service._prepare_runtime_inputs(0.0, 0.0)
        outcome = runner.run(service._make_config(period_seconds=60.0))

        self.assertAlmostEqual(self._load_power(outcome.result.model_book, "ACLoad", "load_ac_1"), 45.0)
        self.assertAlmostEqual(self._load_power(outcome.result.model_book, "DCLoad", "load_dc_1"), 12.0)

    def test_simulator_svg_runtime_controls_enter_the_next_kernel_input(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.update_device_parameters(
            {
                "block_name": "ACGenerator",
                "row_key": {"name": "diesel_300kw"},
                "changes": {"p_set": 96},
            }
        )
        model_book = self._effective_model(service)
        diesel = next(
            row
            for row in model_book.data["ACGenerator"].data
            if row.get("name") == "diesel_300kw"
        )

        self.assertEqual(float(diesel["p_set"]), 96.0)

        service.update_device_parameters(
            {
                "block_name": "ACGenerator",
                "row_key": {"name": "diesel_300kw"},
                "changes": {"run_stat": 0},
            }
        )
        offline_model = self._effective_model(service)
        offline_diesel = next(
            row
            for row in offline_model.data["ACGenerator"].data
            if row.get("name") == "diesel_300kw"
        )
        self.assertEqual(int(float(offline_diesel["run_stat"])), 0)

    def test_online_weather_curve_patch_changes_the_next_kernel_boundary(self):
        import simu_loop

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.update_curve_series(
            {
                "series": {
                    "wind_speed_mps": [17, 18],
                    "solar_irradiance_w_m2": [321, 322],
                }
            }
        )
        service._prepare_runtime_inputs(0.0, 0.0)
        weather = simu_loop._weather_values_from_book(service._make_config().weather_book)

        self.assertEqual(weather["wind_speed_mps"], 17.0)
        self.assertEqual(weather["solar_irradiance_w_m2"], 321.0)

    def test_curve_change_during_calculation_discards_the_old_curve_result(self):
        started = threading.Event()
        release = threading.Event()

        def blocking_kernel(_config):
            started.set()
            self.assertTrue(release.wait(2.0))
            return None

        workspace, service = self._make_service(kernel=blocking_kernel)
        self.addCleanup(workspace.cleanup)

        result_holder = {}
        thread = threading.Thread(target=lambda: result_holder.setdefault("snapshot", service.step()), daemon=True)
        thread.start()
        self.assertTrue(started.wait(2.0))

        service.update_curve_series({"series": {"load:load_ac_1": [80, 81]}})
        release.set()
        thread.join(timeout=3.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(service.latest_compute["status"], "discarded")
        self.assertEqual(service.clock.step_count, 0)


if __name__ == "__main__":
    unittest.main()
