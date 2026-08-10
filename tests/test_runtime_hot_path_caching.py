from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class RuntimeHotPathCachingTest(unittest.TestCase):
    def _make_service(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(
            source,
            runtime,
            kernel=lambda _config: None,
            model_id="simple",
        )
        self.addCleanup(workspace.cleanup)
        return service

    def test_curve_series_are_compiled_once_per_curve_revision(self):
        import simu.service as service_module

        service = self._make_service()
        service.set_curves(
            {
                "mode": "day",
                "time_step_minutes": 1,
                "point_count": 3,
                "weather": [
                    {"minute": 0, "wind_speed_mps": 1, "solar_irradiance_w_m2": 0},
                    {"minute": 1, "wind_speed_mps": 2, "solar_irradiance_w_m2": 10},
                    {"minute": 2, "wind_speed_mps": 3, "solar_irradiance_w_m2": 20},
                ],
                "loads": {
                    "ACLoad:load_ac_1": [
                        {"minute": 0, "p_kw": 10},
                        {"minute": 1, "p_kw": 20},
                        {"minute": 2, "p_kw": 30},
                    ]
                },
            }
        )

        with patch(
            "simu.service._compile_interpolation_series",
            wraps=service_module._compile_interpolation_series,
        ) as compile_series:
            service._write_current_weather(0.5, 0.5)
            first_call_count = compile_series.call_count
            first_weather = service._current_weather_values()
            service._write_current_weather(1.5, 1.5)
            second_weather = service._current_weather_values()

            self.assertGreater(first_call_count, 0)
            self.assertEqual(compile_series.call_count, first_call_count)
            self.assertEqual(first_weather["wind_speed_mps"], 1.5)
            self.assertEqual(second_weather["wind_speed_mps"], 2.5)

            service.set_curves(
                {
                    **service.curves,
                    "weather": [
                        {"minute": 0, "wind_speed_mps": 4, "solar_irradiance_w_m2": 0},
                        {"minute": 1, "wind_speed_mps": 6, "solar_irradiance_w_m2": 10},
                    ],
                }
            )
            service._write_current_weather(0.5, 0.5)

            self.assertGreater(compile_series.call_count, first_call_count)
            self.assertEqual(service._current_weather_values()["wind_speed_mps"], 5.0)

    def test_compiled_curve_interpolation_preserves_duplicate_and_period_boundaries(self):
        from simu.service import _interpolate_compiled_series, _compile_interpolation_series

        points = [
            {"minute": 0, "value": 10},
            {"minute": 60, "value": 20},
            {"minute": 60, "value": 99},
            {"minute": 120, "value": 30},
        ]
        series = _compile_interpolation_series(points, "value", 1440.0)

        expected_by_minute = {
            -1: 30 + (10 - 30) * (1319 / 1320),
            0: 10,
            30: 15,
            60: 20,
            90: 64.5,
            120: 30,
            1439: 30 + (10 - 30) * (1319 / 1320),
            1440: 10,
            1500: 20,
        }
        for minute, expected in expected_by_minute.items():
            actual = _interpolate_compiled_series(
                series,
                minute,
                None,
                period_minutes=1440.0,
            )
            self.assertAlmostEqual(actual, expected, places=12, msg=f"minute={minute}")

    def test_measurement_bindings_are_reused_for_one_definition_revision(self):
        import simu_loop

        service = self._make_service()
        with patch(
            "simu_loop.compile_measurement_bindings",
            wraps=simu_loop.compile_measurement_bindings,
        ) as compile_bindings:
            first = service._make_config(period_seconds=1.0)
            second = service._make_config(period_seconds=1.0)

        self.assertIs(first.measurement_bindings, second.measurement_bindings)
        self.assertEqual(compile_bindings.call_count, 1)
        self.assertEqual(len(first.measurement_bindings), len(first.meas_rows))

    def test_measurement_bindings_are_recompiled_after_definition_revision_changes(self):
        import simu_loop
        from simu.service import DefinitionSnapshot

        service = self._make_service()
        first = service._make_config(period_seconds=1.0)
        current = service.definition_snapshot
        service._publish_definition_snapshot(
            DefinitionSnapshot(
                revision=current.revision + 1,
                model_book=current.model_book,
                dev_define_book=current.dev_define_book,
                measurement_before=current.measurement_before,
                measurement_rows=current.measurement_rows,
                measurement_after=current.measurement_after,
            )
        )

        with patch(
            "simu_loop.compile_measurement_bindings",
            wraps=simu_loop.compile_measurement_bindings,
        ) as compile_bindings:
            second = service._make_config(period_seconds=1.0)

        self.assertEqual(compile_bindings.call_count, 1)
        self.assertIsNot(first.measurement_bindings, second.measurement_bindings)

    def test_compiled_measurement_bindings_preserve_measurement_values(self):
        import simu_loop

        service = self._make_service()
        config = service._make_config(period_seconds=1.0)
        _changed, model_book, _dev_define, weather = simu_loop.apply_realtime_input_books(
            config.model_book,
            config.weather_book,
            config.dev_stat_book,
            config.yt_ctrl_book,
            config.dev_define_book,
            config.period_seconds,
            config.mode_book,
        )
        snapshot, _solver_info = simu_loop.solve_hybrid_snapshot_from_book(
            model_book,
            config.model_file,
        )
        storage = simu_loop._storage_soc_values_from_book(config.dev_stat_book, model_book)
        states = simu_loop.collect_device_operating_states(snapshot, model_book)
        signals = simu_loop._effective_signal_measurement_values(
            simu_loop._signal_measurement_values_from_book(config.dev_stat_book),
            states,
        )

        without_cache = simu_loop.build_real_rows_from_data(
            config.meas_rows,
            snapshot,
            storage,
            weather,
            signals,
            config.meas_before,
            config.meas_after,
            model_book=model_book,
        )
        with_cache = simu_loop.build_real_rows_from_data(
            config.meas_rows,
            snapshot,
            storage,
            weather,
            signals,
            config.meas_before,
            config.meas_after,
            model_book=model_book,
            measurement_bindings=config.measurement_bindings,
        )

        self.assertEqual(with_cache, without_cache)


if __name__ == "__main__":
    unittest.main()
