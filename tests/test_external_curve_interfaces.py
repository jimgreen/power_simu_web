from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class ExternalCurveInterfacesTest(unittest.TestCase):
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
# 1 h-source 1 FLOW 1 2 1 0 10 1
</HydroSource>
<HydroLoad>
@ idx name node control_type pressure_set flow_set flow_min flow_max run_stat
# 1 h-load 1 FLOW 1 4 0 10 1
</HydroLoad>
<HeatSource>
@ idx name node control_type pressure_set flow_set alpha flow_min flow_max supply_temperature run_stat
# 1 heat-source 1 FLOW 1 0.5 1 0 5 90 1
</HeatSource>
<HeatLoad>
@ idx name node mass_flow heat_power run_stat
# 1 heat-load 1 1 40 1
</HeatLoad>
""",
            encoding="utf-8",
        )
        service = PolarMicrogridSimulator(
            source,
            runtime,
            kernel=lambda _config: None,
            model_id="curve-api",
            model_name="曲线接口模型",
        )
        service.set_curves(
            {
                "mode": "day",
                "time_step_minutes": 1,
                "point_count": 4,
                "weather": [
                    {"minute": minute, "wind_speed_mps": minute + 1, "solar_irradiance_w_m2": minute * 10, "air_temp_c": -20 + minute}
                    for minute in range(4)
                ],
                "loads": {
                    "load_ac_1": [{"minute": minute, "p_kw": 100 + minute} for minute in range(4)],
                    "h-load": [{"minute": minute, "flow_set": 4 + minute} for minute in range(4)],
                    "heat-load": [{"minute": minute, "heat_power": 40 + minute} for minute in range(4)],
                },
                "sources": [
                    {
                        "dev_type": "HydroSource",
                        "dev_name": "h-source",
                        "set_type": "flow_set",
                        "points": [{"minute": minute, "value": 2 + minute} for minute in range(4)],
                    },
                    {
                        "dev_type": "HeatSource",
                        "dev_name": "heat-source",
                        "set_type": "flow_set",
                        "points": [{"minute": minute, "value": 0.5 + minute * 0.1} for minute in range(4)],
                    },
                ],
            }
        )
        return workspace, service

    @staticmethod
    def _curve_by_identity(payload, dev_type: str, dev_name: str):
        return next(
            curve
            for curve in payload["curves"]
            if curve.get("dev_type") == dev_type and curve.get("dev_name") == dev_name
        )

    def test_query_returns_all_energy_domains_and_supports_per_curve_time_ranges(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        catalog = service.external_curves_query({})
        identities = {
            (curve["curve_type"], curve.get("energy_type"), curve.get("dev_type"), curve.get("dev_name"))
            for curve in catalog["curves"]
        }
        self.assertIn(("environment", "environment", "Environment", "weather"), identities)
        self.assertIn(("source", "electric", "ACGenerator", "diesel_300kw"), identities)
        self.assertIn(("source", "hydrogen", "HydroSource", "h-source"), identities)
        self.assertIn(("source", "heat", "HeatSource", "heat-source"), identities)
        self.assertIn(("load", "electric", "ACLoad", "load_ac_1"), identities)
        self.assertIn(("load", "hydrogen", "HydroLoad", "h-load"), identities)
        self.assertIn(("load", "heat", "HeatLoad", "heat-load"), identities)

        hydrogen_load = self._curve_by_identity(catalog, "HydroLoad", "h-load")
        selected = service.external_curves_query(
            {
                "curves": [
                    {
                        "dev_type": "HydroLoad",
                        "dev_name": "h-load",
                        "set_type": "flow_set",
                        "start_minute": 1,
                        "end_minute": 2,
                    }
                ]
            }
        )
        self.assertEqual(selected["returned_count"], 1)
        self.assertEqual(selected["curves"][0]["unit"], "Nm3/h")
        self.assertEqual(selected["curves"][0]["points"], [
            {"minute": 1.0, "value": 5.0},
            {"minute": 2.0, "value": 6.0},
        ])

    def test_update_supports_whole_curve_and_inclusive_time_range_without_touching_outside(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        catalog = service.external_curves_query({})
        heat_load = self._curve_by_identity(catalog, "HeatLoad", "heat-load")
        wind_key = next(curve["key"] for curve in catalog["curves"] if curve["key"] == "wind_speed_mps")

        whole = service.external_curves_update(
            {
                "curves": [
                    {
                        "key": wind_key,
                        "points": [
                            {"minute": 0, "value": 10},
                            {"minute": 1, "value": 11},
                            {"minute": 2, "value": 12},
                            {"minute": 3, "value": 13},
                        ],
                    }
                ]
            }
        )
        self.assertEqual(whole["updated_count"], 1)
        self.assertEqual([point["value"] for point in whole["curves"][0]["points"]], [10, 11, 12, 13])

        partial = service.external_curves_update(
            {
                "curves": [
                    {
                        "key": heat_load["key"],
                        "start_minute": 1,
                        "end_minute": 2,
                        "points": [
                            {"minute": 1, "value": 80},
                            {"minute": 2, "value": 90},
                        ],
                    }
                ]
            }
        )
        values = [point["value"] for point in partial["curves"][0]["points"]]
        self.assertEqual(values, [40, 80, 90, 43])
        self.assertEqual(partial["results"][0]["update_scope"], "time_range")
        self.assertEqual(partial["results"][0]["start_minute"], 1.0)
        self.assertEqual(partial["results"][0]["end_minute"], 2.0)

    def test_batch_update_is_atomic_when_any_curve_is_invalid(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        before = service.external_curves_query({"keys": ["wind_speed_mps"]})

        with self.assertRaisesRegex(ValueError, "不存在"):
            service.external_curves_update(
                {
                    "curves": [
                        {"key": "wind_speed_mps", "points": [{"minute": 0, "value": 30}]},
                        {"key": "load:Missing:unknown:p_set", "points": [{"minute": 0, "value": 1}]},
                    ]
                }
            )

        after = service.external_curves_query({"keys": ["wind_speed_mps"]})
        self.assertEqual(after["curves"], before["curves"])

    def test_http_endpoints_are_advertised_and_return_structured_results(self):
        from simu.server import make_http_server

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        server = make_http_server(("127.0.0.1", 0), service, role="simulator")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"

        with urlopen(f"{base}/api/trainee-link", timeout=5) as response:
            link = json.loads(response.read().decode("utf-8"))
        self.assertEqual(link["external_api"]["curves_query"], "/api/external/curves/query?model_id=curve-api")
        self.assertEqual(link["external_api"]["curves_update"], "/api/external/curves/update?model_id=curve-api")

        query_request = Request(
            base + link["external_api"]["curves_query"],
            data=json.dumps({"keys": ["wind_speed_mps"], "start_minute": 1, "end_minute": 2}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(query_request, timeout=5) as response:
            queried = json.loads(response.read().decode("utf-8"))
        self.assertEqual([point["minute"] for point in queried["curves"][0]["points"]], [1.0, 2.0])
        self.assertTrue(queried["model_version"]["signature"])

        update_request = Request(
            base + link["external_api"]["curves_update"],
            data=json.dumps(
                {
                    "curves": [
                        {
                            "key": "wind_speed_mps",
                            "start_minute": 1,
                            "end_minute": 2,
                            "points": [{"minute": 1, "value": 21}, {"minute": 2, "value": 22}],
                        }
                    ]
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(update_request, timeout=5) as response:
            updated = json.loads(response.read().decode("utf-8"))
        self.assertEqual(updated["updated_count"], 1)
        self.assertEqual([point["value"] for point in updated["curves"][0]["points"]], [1, 21, 22, 4])

        invalid_request = Request(
            base + link["external_api"]["curves_update"],
            data=json.dumps({"curves": [{"key": "unknown", "points": [{"minute": 0, "value": 1}]}]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(invalid_request, timeout=5)
        self.assertEqual(raised.exception.code, 400)
        error = json.loads(raised.exception.read().decode("utf-8"))
        self.assertTrue(error["model_version"]["signature"])

    def test_hydrogen_and_heat_load_curves_feed_the_runtime_boundary(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        stat_book, _yt_ctrl_book = service._prepare_runtime_inputs(1.5, 1.5)
        rows = {
            (row.get("dev_type"), row.get("dev_name"), row.get("set_type")): float(row["set_value"])
            for row in stat_book.data["SetValue"].data
        }

        self.assertAlmostEqual(rows[("HydroLoad", "h-load", "flow_set")], 5.5)
        self.assertAlmostEqual(rows[("HeatLoad", "heat-load", "heat_power")], 41.5)

    def test_existing_curve_series_interface_uses_load_specific_fields_and_units(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        summary = service.curves_summary()
        loads = {item["name"]: item for item in summary["loads"]}
        self.assertEqual(loads["h-load"]["unit"], "Nm3/h")
        self.assertEqual(loads["h-load"]["set_type"], "flow_set")
        self.assertEqual(loads["heat-load"]["unit"], "kW")
        series = service.curves_series([loads["h-load"]["key"], loads["heat-load"]["key"]])
        self.assertEqual(series["series"][loads["h-load"]["key"]], [4, 5, 6, 7])
        self.assertEqual(series["series"][loads["heat-load"]["key"]], [40, 41, 42, 43])

    def test_manual_load_parameter_override_has_priority_over_default_curve(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        service.update_device_parameters(
            {
                "block_name": "HydroLoad",
                "row_key": {"name": "h-load"},
                "revision": service.definition_snapshot.revision,
                "changes": {"flow_set": 8},
            }
        )

        stat_book, _yt_ctrl_book = service._prepare_runtime_inputs(1.5, 1.5)
        row = next(
            row
            for row in stat_book.data["SetValue"].data
            if row.get("dev_type") == "HydroLoad"
            and row.get("dev_name") == "h-load"
            and row.get("set_type") == "flow_set"
        )
        self.assertAlmostEqual(float(row["set_value"]), 8.0)

    def test_default_curve_only_applies_to_active_coupling_control_endpoint(self):
        from simu.definition_editing import DefinitionSnapshot

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        model_file = service.source_files["model"]
        model_file.write_text(
            model_file.read_text(encoding="utf-8")
            + """
<AcE2Hydro>
@ idx name run_stat control_type idx_ac_load_t1 idx_h2_unit_t2 e2h_coeff
# 1 electrolyzer 1 P 1 1 0.2
</AcE2Hydro>
""",
            encoding="utf-8",
        )
        current = service.definition_snapshot
        service._publish_definition_snapshot(
            DefinitionSnapshot(
                revision=current.revision + 1,
                model_book=service.source_model_book.__class__(model_file),
                dev_define_book=current.dev_define_book,
                measurement_before=current.measurement_before,
                measurement_rows=current.measurement_rows,
                measurement_after=current.measurement_after,
                measurement_median_deviations=current.measurement_median_deviations,
            )
        )

        stat_book, _yt_ctrl_book = service._prepare_runtime_inputs(1.5, 1.5)
        flow_rows = [
            row
            for row in stat_book.data["SetValue"].data
            if row.get("dev_type") == "HydroSource"
            and row.get("dev_name") == "h-source"
            and row.get("set_type") == "flow_set"
        ]
        self.assertEqual(flow_rows, [])


if __name__ == "__main__":
    unittest.main()
