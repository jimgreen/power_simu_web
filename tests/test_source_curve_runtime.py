from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class SourceCurveRuntimeTest(unittest.TestCase):
    def _make_service(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)

        model_file = source / "model.e"
        model_file.write_text(
            model_file.read_text(encoding="utf-8")
            + """
<HydroSource>
@ idx name node control_type pressure_set flow_set alpha flow_min flow_max run_stat
# 1 hydrogen-source 1 FLOW 1 2 1 0 10 1
</HydroSource>
<HeatSource>
@ idx name node control_type pressure_set flow_set alpha flow_min flow_max supply_temperature run_stat
# 1 heat-source 1 FLOW 1 0.5 1 0 5 90 1
</HeatSource>
""",
            encoding="utf-8",
        )
        for file_name in ("control.e", "stat.e"):
            path = source / file_name
            text = path.read_text(encoding="utf-8")
            text = text.replace(
                "</SetValue>",
                "# HydroSource hydrogen-source flow_set 2\n"
                "# HeatSource heat-source flow_set 0.5\n"
                "</SetValue>",
                1,
            )
            path.write_text(text, encoding="utf-8")

        service = PolarMicrogridSimulator(
            source,
            runtime,
            kernel=lambda _config: None,
            model_id="source-curves",
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
                "loads": {},
                "sources": [
                    {
                        "dev_type": "ACGenerator",
                        "dev_name": "diesel_300kw",
                        "set_type": "p_set",
                        "family": "electric",
                        "points": [
                            {"minute": 0, "value": 100},
                            {"minute": 1, "value": 120},
                        ],
                    },
                    {
                        "dev_type": "HydroSource",
                        "dev_name": "hydrogen-source",
                        "set_type": "flow_set",
                        "family": "hydrogen",
                        "points": [
                            {"minute": 0, "value": 3},
                            {"minute": 1, "value": 5},
                        ],
                    },
                    {
                        "dev_type": "HeatSource",
                        "dev_name": "heat-source",
                        "set_type": "flow_set",
                        "family": "heat",
                        "points": [
                            {"minute": 0, "value": 1},
                            {"minute": 1, "value": 2},
                        ],
                    },
                ],
            }
        )
        return workspace, service

    @staticmethod
    def _set_value(book, dev_type: str, dev_name: str, set_type: str) -> float:
        row = next(
            row
            for row in book.data["SetValue"].data
            if row.get("dev_type") == dev_type
            and row.get("dev_name") == dev_name
            and row.get("set_type") == set_type
        )
        return float(row["set_value"])

    def test_source_curves_supply_interpolated_defaults_when_no_command_exists(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        stat_book, yt_ctrl_book = service._prepare_runtime_inputs(0.5, 0.5)

        self.assertAlmostEqual(self._set_value(stat_book, "ACGenerator", "diesel_300kw", "p_set"), 110.0)
        self.assertAlmostEqual(self._set_value(stat_book, "HydroSource", "hydrogen-source", "flow_set"), 4.0)
        self.assertAlmostEqual(self._set_value(stat_book, "HeatSource", "heat-source", "flow_set"), 1.5)
        self.assertEqual(yt_ctrl_book.data["SetValue"].data, [])

    def test_svg_manual_setpoint_has_priority_over_default_source_curve(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.update_device_parameters(
            {
                "block_name": "ACGenerator",
                "row_key": {"name": "diesel_300kw"},
                "revision": service.definition_snapshot.revision,
                "changes": {"p_set": 95},
            }
        )

        stat_book, _yt_ctrl_book = service._prepare_runtime_inputs(0.5, 0.5)

        self.assertAlmostEqual(self._set_value(stat_book, "ACGenerator", "diesel_300kw", "p_set"), 95.0)

    def test_active_remote_adjustment_has_priority_over_default_source_curve(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.remote_adjustment_response_ratio = 1.0
        service.apply_student_commands(
            {
                "set_values": [
                    {
                        "dev_type": "ACGenerator",
                        "dev_name": "diesel_300kw",
                        "set_type": "p_set",
                        "set_value": 130,
                    }
                ]
            },
            source="trainee-ui",
        )

        stat_book, yt_ctrl_book = service._prepare_runtime_inputs(0.5, 0.5)

        self.assertAlmostEqual(self._set_value(stat_book, "ACGenerator", "diesel_300kw", "p_set"), 130.0)
        self.assertAlmostEqual(self._set_value(yt_ctrl_book, "ACGenerator", "diesel_300kw", "p_set"), 130.0)

    def test_full_boundary_priority_switches_to_ui_target_with_smooth_response(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        service.apply_student_commands(
            {
                "command_origin": "automatic",
                "valid_for_minutes": 5,
                "set_values": [
                    {
                        "dev_type": "ACGenerator",
                        "dev_name": "diesel_300kw",
                        "set_type": "p_set",
                        "set_value": 120,
                    }
                ],
            },
            source="trainee-automatic-control",
        )
        service.apply_student_commands(
            {
                "command_origin": "manual",
                "set_values": [
                    {
                        "dev_type": "ACGenerator",
                        "dev_name": "diesel_300kw",
                        "set_type": "p_set",
                        "set_value": 100,
                    }
                ],
            },
            source="trainee-ui",
        )
        service._prepare_runtime_inputs(0.0, 0.0)
        service.update_device_parameters(
            {
                "block_name": "ACGenerator",
                "row_key": {"name": "diesel_300kw"},
                "revision": service.definition_snapshot.revision,
                "changes": {"p_set": 90},
            }
        )

        stat_book, yt_ctrl_book = service._prepare_runtime_inputs(0.5, 0.5)

        self.assertAlmostEqual(
            self._set_value(service.runtime_stat_book, "ACGenerator", "diesel_300kw", "p_set"),
            90.0,
        )
        self.assertAlmostEqual(self._set_value(stat_book, "ACGenerator", "diesel_300kw", "p_set"), 91.2)
        self.assertEqual(yt_ctrl_book.data["SetValue"].data, [])

    def test_default_curve_still_applies_when_legacy_control_definition_lacks_source_row(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        for book in (service.control_book, service.source_stat_book, service.runtime_stat_book):
            block = book.data["SetValue"]
            block.data = [
                row
                for row in block.data
                if not (row.get("dev_type") == "HeatSource" and row.get("dev_name") == "heat-source")
            ]

        stat_book, _yt_ctrl_book = service._prepare_runtime_inputs(0.5, 0.5)

        self.assertAlmostEqual(self._set_value(stat_book, "HeatSource", "heat-source", "flow_set"), 1.5)

    def test_source_curve_values_cannot_bypass_model_safety_bounds(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        heat_curve = next(item for item in service.curves["sources"] if item["dev_name"] == "heat-source")
        heat_curve["points"] = [{"minute": 0, "value": 50}]

        stat_book, _yt_ctrl_book = service._prepare_runtime_inputs(0, 0)

        self.assertAlmostEqual(self._set_value(stat_book, "HeatSource", "heat-source", "flow_set"), 0.5)


if __name__ == "__main__":
    unittest.main()
