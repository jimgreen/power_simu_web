from __future__ import annotations

import math
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import simu_loop
from simu.server import MEASUREMENT_TYPE_MAP
from simu.service import PolarMicrogridSimulator


def _model_book(*rows: dict) -> simu_loop.EBook:
    return simu_loop.EBook({"HydroStorage": list(rows)})


def _snapshot(*, flows: dict[str, float]) -> SimpleNamespace:
    return SimpleNamespace(
        fluid_results={
            "hydro": SimpleNamespace(
                storages={
                    name: SimpleNamespace(flow=flow)
                    for name, flow in flows.items()
                }
            )
        }
    )


class HydrogenStorageStateTest(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def test_integrates_quantity_first_then_derives_pressure(self) -> None:
        pressure, quantity = simu_loop.integrate_hydrogen_storage_state(
            gas_quantity=17500.0,
            flow=1000.0,
            period_seconds=1800.0,
            water_volume=100.0,
        )

        self.assertAlmostEqual(pressure, 17.0)
        self.assertAlmostEqual(quantity, 17000.0)

    def test_negative_flow_charges_tank_and_raises_pressure(self) -> None:
        pressure, quantity = simu_loop.integrate_hydrogen_storage_state(
            gas_quantity=17500.0,
            flow=-500.0,
            period_seconds=1800.0,
            water_volume=100.0,
        )

        self.assertAlmostEqual(pressure, 17.75)
        self.assertAlmostEqual(quantity, 17750.0)

    def test_soc_is_quantity_ratio_without_physical_range_clamping(self) -> None:
        model_book = _model_book(
            {
                "idx": 1,
                "name": "tank-1",
                "pressure": 46.0,
                "gas_quantity": 23000.0,
                "capacity": 20000.0,
                "water_volume": 50.0,
                "pressure_max": 45.0,
                "run_stat": 1,
            }
        )
        stat_book = simu_loop.EBook({})

        simu_loop.update_hydrogen_storage_state_book(
            stat_book,
            model_book,
            period_seconds=3600.0,
            snapshot=_snapshot(flows={"tank-1": 0.0}),
        )

        row = stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data[0]
        self.assertAlmostEqual(float(row["pressure"]), 46.0)
        self.assertNotIn("press", row)
        self.assertAlmostEqual(float(row["soc"]), 23000.0 / 20000.0)
        self.assertGreater(float(row["soc"]), 1.0)

    def test_missing_capacity_and_pressure_limit_leave_soc_invalid(self) -> None:
        model_book = _model_book(
            {
                "idx": 1,
                "name": "tank-1",
                "gas_quantity": 23000.0,
                "water_volume": 50.0,
                "run_stat": 1,
            }
        )
        stat_book = simu_loop.EBook({})

        with self.assertLogs("SimulationLoop", level="WARNING"):
            simu_loop.update_hydrogen_storage_state_book(
                stat_book,
                model_book,
                period_seconds=3600.0,
                snapshot=_snapshot(flows={"tank-1": 0.0}),
            )

        row = stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data[0]
        self.assertAlmostEqual(float(row["pressure"]), 46.0)
        self.assertTrue(math.isnan(float(row["soc"])))

    def test_legacy_press_runtime_state_is_migrated_to_pressure(self) -> None:
        model_book = _model_book(
            {
                "idx": 1,
                "name": "tank-1",
                "pressure": 35.0,
                "water_volume": 50.0,
                "pressure_max": 45.0,
                "pressure_min": 2.0,
                "run_stat": 1,
            }
        )
        stat_book = simu_loop.EBook(
            {
                simu_loop.HYDROGEN_STORAGE_STATE_BLOCK: [
                    {
                        "dev_type": "HydroStorage",
                        "idx": 1,
                        "name": "tank-1",
                        "press": 34.5,
                        "flow": 100.0,
                        "gas_quantity": 17250.0,
                        "soc": 34.5 / 45.0,
                    }
                ]
            }
        )

        changed = simu_loop.ensure_hydrogen_storage_state_rows_book(stat_book, model_book)

        block = stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK]
        self.assertGreater(changed, 0)
        self.assertIn("pressure", block.header_list)
        self.assertNotIn("press", block.header_list)
        self.assertAlmostEqual(float(block.data[0]["pressure"]), 34.5)
        self.assertNotIn("press", block.data[0])

    def test_uses_solved_flow_and_persists_state_between_steps(self) -> None:
        model_book = _model_book(
            {
                "idx": 1,
                "name": "tank-1",
                "node": 1,
                "pressure": 35.0,
                "flow": 9999.0,
                "gas_quantity": 17500.0,
                "capacity": 22500.0,
                "water_volume": 100.0,
                "pressure_max": 45.0,
                "pressure_min": 2.0,
                "run_stat": 1,
            }
        )
        stat_book = simu_loop.EBook({})
        snapshot = _snapshot(flows={"tank-1": 1000.0})

        first = simu_loop.update_hydrogen_storage_state_book(
            stat_book,
            model_book,
            period_seconds=1800.0,
            snapshot=snapshot,
        )
        second = simu_loop.update_hydrogen_storage_state_book(
            stat_book,
            model_book,
            period_seconds=1800.0,
            snapshot=snapshot,
        )

        self.assertGreater(first, 0)
        self.assertGreater(second, 0)
        row = stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data[0]
        self.assertAlmostEqual(float(row["pressure"]), 16.5)
        self.assertAlmostEqual(float(row["flow"]), 1000.0)
        self.assertAlmostEqual(float(row["gas_quantity"]), 16500.0)
        self.assertAlmostEqual(float(row["soc"]), 16500.0 / 22500.0)

    def test_initial_quantity_is_derived_from_pressure_and_water_volume(self) -> None:
        model_book = _model_book(
            {
                "idx": 1,
                "name": "tank-1",
                "pressure": 35.0,
                "water_volume": 50.0,
                "pressure_max": 45.0,
                "pressure_min": 2.0,
                "run_stat": 1,
            }
        )
        stat_book = simu_loop.EBook({})

        simu_loop.ensure_hydrogen_storage_state_rows_book(stat_book, model_book)

        row = stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data[0]
        self.assertAlmostEqual(float(row["gas_quantity"]), 17500.0)

    def test_initial_state_is_derived_from_capacity_water_volume_and_soc(self) -> None:
        model_book = _model_book(
            {
                "idx": 1,
                "name": "tank-1",
                "pressure": 99.0,
                "gas_quantity": 99999.0,
                "capacity": 20000.0,
                "water_volume": 50.0,
                "soc": 0.6,
                "pressure_max": 45.0,
                "run_stat": 1,
            }
        )
        stat_book = simu_loop.EBook({})

        simu_loop.ensure_hydrogen_storage_state_rows_book(stat_book, model_book)

        row = stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data[0]
        self.assertAlmostEqual(float(row["gas_quantity"]), 12000.0)
        self.assertAlmostEqual(float(row["pressure"]), 24.0)
        self.assertAlmostEqual(float(row["soc"]), 0.6)

    def test_runtime_derives_pressure_and_soc_from_integrated_quantity(self) -> None:
        model_book = _model_book(
            {
                "idx": 1,
                "name": "tank-1",
                "pressure": 99.0,
                "gas_quantity": 12000.0,
                "capacity": 20000.0,
                "water_volume": 50.0,
                "initial_soc": 0.6,
                "pressure_max": 45.0,
                "run_stat": 1,
            }
        )
        stat_book = simu_loop.EBook(
            {
                simu_loop.HYDROGEN_STORAGE_STATE_BLOCK: [
                    {
                        "dev_type": "HydroStorage",
                        "idx": 1,
                        "name": "tank-1",
                        "pressure": 88.0,
                        "flow": 0.0,
                        "gas_quantity": 12000.0,
                        "soc": 0.1,
                    }
                ]
            }
        )

        simu_loop.update_hydrogen_storage_state_book(
            stat_book,
            model_book,
            period_seconds=3600.0,
            snapshot=_snapshot(flows={"tank-1": 1000.0}),
        )

        row = stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data[0]
        self.assertAlmostEqual(float(row["gas_quantity"]), 11000.0)
        self.assertAlmostEqual(float(row["pressure"]), 22.0)
        self.assertAlmostEqual(float(row["soc"]), 0.55)

    def test_multiple_tanks_are_integrated_independently(self) -> None:
        model_book = _model_book(
            {
                "idx": 1,
                "name": "tank-1",
                "pressure": 35.0,
                "gas_quantity": 17500.0,
                "capacity": 22500.0,
                "water_volume": 50.0,
                "pressure_max": 45.0,
                "run_stat": 1,
            },
            {
                "idx": 2,
                "name": "tank-2",
                "pressure": 20.0,
                "gas_quantity": 20000.0,
                "capacity": 40000.0,
                "water_volume": 100.0,
                "pressure_max": 40.0,
                "run_stat": 1,
            },
        )
        stat_book = simu_loop.EBook({})

        simu_loop.update_hydrogen_storage_state_book(
            stat_book,
            model_book,
            period_seconds=3600.0,
            snapshot=_snapshot(flows={"tank-1": 100.0, "tank-2": -200.0}),
        )

        rows = {
            row["name"]: row
            for row in stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data
        }
        self.assertAlmostEqual(float(rows["tank-1"]["pressure"]), 34.8)
        self.assertAlmostEqual(float(rows["tank-1"]["gas_quantity"]), 17400.0)
        self.assertAlmostEqual(float(rows["tank-1"]["soc"]), 17400.0 / 22500.0)
        self.assertAlmostEqual(float(rows["tank-2"]["pressure"]), 20.2)
        self.assertAlmostEqual(float(rows["tank-2"]["gas_quantity"]), 20200.0)
        self.assertAlmostEqual(float(rows["tank-2"]["soc"]), 20200.0 / 40000.0)

    def test_invalid_water_volume_does_not_fabricate_pressure_change(self) -> None:
        model_book = _model_book(
            {
                "idx": 1,
                "name": "tank-1",
                "pressure": 35.0,
                "gas_quantity": 1000.0,
                "water_volume": 0.0,
                "run_stat": 1,
            }
        )
        stat_book = simu_loop.EBook({})

        with self.assertLogs("SimulationLoop", level="WARNING"):
            simu_loop.update_hydrogen_storage_state_book(
                stat_book,
                model_book,
                period_seconds=3600.0,
                snapshot=_snapshot(flows={"tank-1": 100.0}),
            )

        row = stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data[0]
        self.assertAlmostEqual(float(row["pressure"]), 35.0)
        self.assertAlmostEqual(float(row["gas_quantity"]), 900.0)
        self.assertAlmostEqual(float(row["flow"]), 100.0)

    def test_pressure_flow_and_quantity_measurements_use_runtime_state(self) -> None:
        snapshot = SimpleNamespace(value=lambda *_args: None)
        runtime_state = {
            ("HydroStorage", "tank-1"): {
                "pressure": 34.5,
                "flow": 1000.0,
                "gas_quantity": 17000.0,
                "soc": 34.5 / 45.0,
            }
        }

        for meas_type, expected in (
            ("pressure", 34.5),
            ("flow", 1000.0),
            ("gas_quantity", 17000.0),
            ("soc", 34.5 / 45.0),
        ):
            row = ["1", "point", "HydroStorage", "tank-1", meas_type, "1", "1", "0"]
            value = simu_loop._measurement_value(
                snapshot,
                row,
                hydrogen_storage_state=runtime_state,
            )
            self.assertTrue(math.isclose(float(value), expected))

        legacy_row = ["1", "point", "HydroStorage", "tank-1", "PRESS", "1", "1", "0"]
        self.assertIsNone(
            simu_loop._measurement_value(
                snapshot,
                legacy_row,
                hydrogen_storage_state=runtime_state,
            )
        )

    def test_generated_measurements_include_all_hydrogen_tank_states(self) -> None:
        self.assertEqual(
            MEASUREMENT_TYPE_MAP["HydroStorage"],
            ("pressure", "flow", "gas_quantity", "soc"),
        )

    def test_service_merges_execution_state_by_tank_identity(self) -> None:
        service = PolarMicrogridSimulator.__new__(PolarMicrogridSimulator)
        service.runtime_stat_book = simu_loop.EBook(
            {
                simu_loop.HYDROGEN_STORAGE_STATE_BLOCK: [
                    {
                        "dev_type": "HydroStorage",
                        "idx": 1,
                        "name": "tank-1",
                        "pressure": 35.0,
                        "flow": 0.0,
                        "gas_quantity": 17500.0,
                        "soc": 35.0 / 45.0,
                    }
                ]
            }
        )
        execution_book = simu_loop.EBook(
            {
                simu_loop.HYDROGEN_STORAGE_STATE_BLOCK: [
                    {
                        "dev_type": "HydroStorage",
                        "idx": 1,
                        "name": "tank-1",
                        "pressure": 34.5,
                        "flow": 1000.0,
                        "gas_quantity": 17000.0,
                        "soc": 34.5 / 45.0,
                    }
                ]
            }
        )

        service._merge_execution_runtime_stat_book(execution_book)

        row = service.runtime_stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data[0]
        self.assertAlmostEqual(float(row["pressure"]), 34.5)
        self.assertAlmostEqual(float(row["flow"]), 1000.0)
        self.assertAlmostEqual(float(row["gas_quantity"]), 17000.0)
        self.assertAlmostEqual(float(row["soc"]), 34.5 / 45.0)

    def test_reset_derives_capacity_from_pressure_limit_and_water_volume(self) -> None:
        model_book = _model_book(
            {
                "idx": 1,
                "name": "tank-1",
                "pressure": 35.0,
                "water_volume": 50.0,
                "pressure_max": 45.0,
                "pressure_min": 2.0,
                "run_stat": 1,
            }
        )
        stat_book = simu_loop.EBook(
            {
                simu_loop.HYDROGEN_STORAGE_STATE_BLOCK: [
                    {
                        "dev_type": "HydroStorage",
                        "idx": 1,
                        "name": "tank-1",
                        "pressure": 12.0,
                        "flow": 100.0,
                        "gas_quantity": 6000.0,
                        "soc": 12.0 / 45.0,
                    }
                ]
            }
        )

        simu_loop.reset_hydrogen_storage_state_book(stat_book, model_book)

        row = stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data[0]
        self.assertAlmostEqual(float(row["pressure"]), 35.0)
        self.assertAlmostEqual(float(row["flow"]), 0.0)
        self.assertAlmostEqual(float(row["gas_quantity"]), 17500.0)
        self.assertAlmostEqual(float(row["soc"]), 17500.0 / 22500.0)

    def test_reset_recomputes_initial_state_instead_of_restoring_stale_values(self) -> None:
        model_book = _model_book(
            {
                "idx": 1,
                "name": "tank-1",
                "pressure": 35.0,
                "gas_quantity": 17500.0,
                "capacity": 20000.0,
                "water_volume": 50.0,
                "soc": 0.6,
                "pressure_max": 45.0,
                "run_stat": 1,
            }
        )
        stat_book = simu_loop.EBook(
            {
                simu_loop.HYDROGEN_STORAGE_STATE_BLOCK: [
                    {
                        "dev_type": "HydroStorage",
                        "idx": 1,
                        "name": "tank-1",
                        "pressure": 12.0,
                        "flow": 100.0,
                        "gas_quantity": 6000.0,
                        "soc": 0.3,
                    }
                ]
            }
        )

        simu_loop.reset_hydrogen_storage_state_book(stat_book, model_book)

        row = stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data[0]
        self.assertAlmostEqual(float(row["gas_quantity"]), 12000.0)
        self.assertAlmostEqual(float(row["pressure"]), 24.0)
        self.assertAlmostEqual(float(row["flow"]), 0.0)
        self.assertAlmostEqual(float(row["soc"]), 0.6)

    def test_service_restart_recomputes_hydrogen_initial_state(self) -> None:
        source_model = next(
            path
            for path in (self.ROOT / "models" / "simulator" / "source").glob("*/model.e")
            if "<HydroStorage>" in path.read_text(encoding="utf-8")
        )
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        shutil.copytree(source_model.parent, source)

        model_book = simu_loop.EBook(source / "model.e")
        storage = model_book.data["HydroStorage"].data[0]
        for header in ("capacity", "water_volume", "soc", "pressure", "gas_quantity"):
            if header not in model_book.data["HydroStorage"].header_list:
                model_book.data["HydroStorage"].header_list.append(header)
        storage.update(
            capacity="20000",
            water_volume="50",
            initial_soc="0.6",
            soc="0.6",
            pressure="99",
            gas_quantity="99999",
        )
        simu_loop.write_ebook_aligned(model_book, source / "model.e")

        source_stat = simu_loop.EBook(source / "stat.e")
        state = source_stat.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data[0]
        state.update(pressure="12", flow="100", gas_quantity="6000", soc="0.3")
        simu_loop.write_ebook_aligned(source_stat, source / "stat.e")

        service = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)

        def state_values(instance: PolarMicrogridSimulator) -> tuple[float, float, float, float]:
            row = instance.runtime_stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data[0]
            return tuple(float(row[field]) for field in ("gas_quantity", "pressure", "flow", "soc"))

        self.assertEqual(state_values(service), (12000.0, 24.0, 0.0, 0.6))
        service.runtime_stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data[0].update(
            pressure="10",
            flow="200",
            gas_quantity="5000",
            soc="0.25",
        )

        restarted = PolarMicrogridSimulator(source, runtime, kernel=lambda _config: None)

        self.assertEqual(state_values(restarted), (12000.0, 24.0, 0.0, 0.6))

    def test_bundled_hydrogen_tank_initial_state_is_self_consistent(self) -> None:
        model_path = next(
            path
            for path in (self.ROOT / "models" / "simulator" / "source").glob("*/model.e")
            if "<HydroStorage>" in path.read_text(encoding="utf-8")
        )
        storage = simu_loop.EBook(model_path).data["HydroStorage"].data[0]
        rated_capacity = float(storage["capacity"])
        water_volume = float(storage["water_volume"])
        initial_soc = float(storage["initial_soc"])

        expected_quantity = rated_capacity * initial_soc
        expected_pressure = expected_quantity / water_volume / 10.0

        self.assertAlmostEqual(expected_quantity, 17500.0)
        self.assertAlmostEqual(expected_pressure, 35.0)
        self.assertAlmostEqual(float(storage["pressure"]), expected_pressure)

    def test_in_memory_hybrid_solver_returns_actual_hydrogen_storage_flow(self) -> None:
        model_path = next(
            path
            for path in (self.ROOT / "models" / "simulator" / "source").glob("*/model.e")
            if "<HydroStorage>" in path.read_text(encoding="utf-8")
        )
        model_book = simu_loop.EBook(model_path)
        block = model_book.data["HydroStorage"]
        for header in ("control_type", "flow_set", "flow_min", "flow_max"):
            if header not in block.header_list:
                block.header_list.append(header)
        model_row = block.data[0]
        model_row.update(
            control_type="FLOW",
            flow_set="100",
            flow_min="-1000",
            flow_max="1000",
        )

        snapshot, _solver_info = simu_loop.solve_hybrid_snapshot_from_book(
            model_book,
            model_path,
        )

        flows = simu_loop._snapshot_hydrogen_storage_flow_by_name(snapshot)
        self.assertAlmostEqual(flows[str(model_row["name"])], 100.0)

        stat_book = simu_loop.EBook({})
        simu_loop.update_hydrogen_storage_state_book(
            stat_book,
            model_book,
            period_seconds=3600.0,
            snapshot=snapshot,
        )
        state = stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data[0]
        self.assertAlmostEqual(float(state["pressure"]), 34.8)
        self.assertAlmostEqual(float(state["gas_quantity"]), 17400.0)

    def test_bundled_hydrogen_tank_balances_conversion_net_flow(self) -> None:
        model_path = next(
            path
            for path in (self.ROOT / "models" / "simulator" / "source").glob(
                "*/model.e"
            )
            if "<HydroStorage>" in path.read_text(encoding="utf-8")
        )
        model_book = simu_loop.EBook(model_path)
        storage = model_book.data["HydroStorage"].data[0]
        self.assertEqual(str(storage.get("control_type", "")).upper(), "PRESSURE")
        self.assertAlmostEqual(
            float(storage["pressure_set"]),
            float(storage["pressure"]),
        )
        self.assertLess(float(storage["flow_min"]), 0.0)
        self.assertGreater(float(storage["flow_max"]), 0.0)

        fuel_cell = model_book.data["Hydro2DcE"].data[0]
        fuel_cell["control_type"] = "P"
        generator = next(
            row
            for row in model_book.data["DCGenerator"].data
            if str(row.get("idx")) == str(fuel_cell["idx_dc_unit_t1"])
        )
        generator["p_set"] = "10"
        electrolyzer = model_book.data["AcE2Hydro"].data[0]
        electrolyzer["control_type"] = "P"
        load = next(
            row
            for row in model_book.data["ACLoad"].data
            if str(row.get("idx")) == str(electrolyzer["idx_ac_load_t1"])
        )
        load["p_set"] = "0.02"

        snapshot, _solver_info = simu_loop.solve_hybrid_snapshot_from_book(
            model_book,
            model_path,
        )
        hydro = snapshot.fluid_results["hydro"]
        source_flow = next(iter(hydro.sources.values())).flow
        load_flow = next(iter(hydro.loads.values())).flow
        storage_flow = hydro.storages[str(storage["name"])].flow

        self.assertGreater(storage_flow, 0.0)
        self.assertAlmostEqual(storage_flow, load_flow - source_flow)

        stat_book = simu_loop.EBook({})
        simu_loop.update_hydrogen_storage_state_book(
            stat_book,
            model_book,
            period_seconds=3600.0,
            snapshot=snapshot,
        )
        state = stat_book.data[simu_loop.HYDROGEN_STORAGE_STATE_BLOCK].data[0]
        self.assertAlmostEqual(float(state["flow"]), storage_flow)
        self.assertLess(float(state["gas_quantity"]), 17500.0)


if __name__ == "__main__":
    unittest.main()
