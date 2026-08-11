from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


MEAS_TEXT = """<Measurement>
@ idx  name  dev_type  dev_name  meas_type  weight  valid  value
</Measurement>
"""


def _efile_block(name: str, header: tuple[str, ...], rows: list[dict[str, object]]) -> str:
    parts = [f"<{name}>\n", "@ " + "  ".join(header) + "\n"]
    for row in rows:
        parts.append("# " + "  ".join(str(row.get(column, "")) for column in header) + "\n")
    parts.append(f"</{name}>\n")
    return "".join(parts)


def _memory_book(simu_loop, **blocks):
    return simu_loop.EBook({name: [dict(row) for row in rows] for name, rows in blocks.items()})


class _SolvedStorageSnapshot:
    def __init__(
        self,
        devices: dict[tuple[str, str], dict[str, object]],
        reported_powers: dict[tuple[str, str], object] | None = None,
    ) -> None:
        self.ac = None
        self.dc = None
        self.dcac_converters = []
        self.acac_converters = []
        self.ac_devices: dict[str, dict[str, object]] = {}
        self.dc_devices: dict[str, dict[str, object]] = {}
        self._powers: dict[tuple[str, str], object] = {}
        for (dev_type, name), state in devices.items():
            device = SimpleNamespace(
                name=name,
                run_stat=int(state.get("run_stat", 1)),
                is_alive=not bool(state.get("dead_island", False)),
            )
            target = self.ac_devices if dev_type == "ACGenerator" else self.dc_devices
            target.setdefault(dev_type, {})[name] = device
            self._powers[(dev_type, name)] = state.get("power", 0.0)
        if reported_powers is not None:
            self._powers = dict(reported_powers)

    def value(self, dev_type, dev_name, meas_type):
        if meas_type == "P_GEN":
            return self._powers.get((dev_type, dev_name))
        return None


class StorageSocConstraintTest(unittest.TestCase):
    def _typed_storage_books(
        self,
        *,
        dev_type: str,
        parameter_block: str,
        reference_field: str,
        setpoint: float,
        soc: float,
        capacity: float,
        efficiency: float,
        source_name: str = "storage-1",
        storage_name: str | None = None,
        soc_dev_type: str | None = None,
        max_charge_power: float = 40.0,
        max_discharge_power: float = 40.0,
        soc_upper_limit: float = 0.9,
        soc_lower_limit: float = 0.2,
    ):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            **{
                dev_type: [
                    {
                        "idx": 1,
                        "name": source_name,
                        "node": 1,
                        "control_type": "P",
                        "p_set": setpoint,
                        "p_max": max_discharge_power,
                        "p_min": -max_charge_power,
                        "v_set": 300,
                        "i_set": 0,
                        "run_stat": 1,
                    }
                ],
                parameter_block: [
                    {
                        "idx": 1,
                        reference_field: 1,
                        "storage_technology": "lithium",
                        "energy_capacity": capacity,
                        "max_charge_power": max_charge_power,
                        "max_discharge_power": max_discharge_power,
                        "state_of_charge": soc,
                        "soc_upper_limit": soc_upper_limit,
                        "soc_lower_limit": soc_lower_limit,
                        "charge_discharge_efficiency": efficiency,
                    }
                ],
            },
        )
        stat_book = _memory_book(
            simu_loop,
            StorageSoc=[
                {
                    "dev_type": dev_type if soc_dev_type is None else soc_dev_type,
                    "idx": 1,
                    "name": source_name if storage_name is None else storage_name,
                    "soc_curr": soc,
                }
            ],
        )
        dev_define = simu_loop._embedded_device_define_book(model_book)
        return model_book, stat_book, dev_define

    def _integrate_typed_storage_soc(
        self,
        *,
        dev_type: str,
        parameter_block: str,
        reference_field: str,
        setpoint: float,
        actual_power: float,
        soc: float,
        capacity: float,
        efficiency: float,
        period_seconds: float,
        source_name: str = "storage-1",
        storage_name: str | None = None,
        soc_dev_type: str | None = None,
        snapshot_run_stat: int = 1,
        dead_island: bool = False,
    ) -> float:
        import simu_loop

        model_book, stat_book, dev_define = self._typed_storage_books(
            dev_type=dev_type,
            parameter_block=parameter_block,
            reference_field=reference_field,
            setpoint=setpoint,
            soc=soc,
            capacity=capacity,
            efficiency=efficiency,
            source_name=source_name,
            storage_name=storage_name,
            soc_dev_type=soc_dev_type,
        )
        snapshot = _SolvedStorageSnapshot(
            {
                (dev_type, source_name): {
                    "power": actual_power,
                    "run_stat": snapshot_run_stat,
                    "dead_island": dead_island,
                }
            }
        )
        simu_loop.update_storage_soc_book(
            stat_book,
            model_book,
            period_seconds=period_seconds,
            dev_define=dev_define,
            snapshot=snapshot,
        )
        return float(stat_book.data["StorageSoc"].data[0]["soc_curr"])

    def _run_typed_storage_case(
        self,
        *,
        dev_type: str,
        parameter_block: str,
        reference_field: str,
        soc: float,
        p_set: float,
        period_seconds: float,
    ) -> tuple[float, float]:
        import simu_loop

        model_book, stat_book, dev_define = self._typed_storage_books(
            dev_type=dev_type,
            parameter_block=parameter_block,
            reference_field=reference_field,
            setpoint=p_set,
            soc=soc,
            capacity=100.0,
            efficiency=1.0,
        )
        status_by_name, status_rows = simu_loop._storage_soc_by_name_book(stat_book)
        simu_loop.apply_storage_constraints_book(
            model_book,
            status_by_name,
            status_rows,
            dev_define,
            period_seconds,
        )
        executed_power = float(model_book.data[dev_type].data[0]["p_set"])
        snapshot = _SolvedStorageSnapshot(
            {(dev_type, "storage-1"): {"power": executed_power, "run_stat": 1, "dead_island": False}}
        )
        simu_loop.update_storage_soc_book(
            stat_book,
            model_book,
            period_seconds=period_seconds,
            dev_define=dev_define,
            snapshot=snapshot,
        )
        return executed_power, float(stat_book.data["StorageSoc"].data[0]["soc_curr"])

    def test_embedded_storage_definitions_include_typed_ac_and_dc_sources(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            ACGenerator=[{"idx": 1, "name": "shared-storage", "p_set": 0, "run_stat": 1}],
            ACStorageGen=[
                {
                    "idx": 1,
                    "idx_acgenerator": 1,
                    "energy_capacity": 100,
                    "max_charge_power": 40,
                    "max_discharge_power": 40,
                    "state_of_charge": 0.5,
                    "soc_upper_limit": 0.9,
                    "soc_lower_limit": 0.2,
                }
            ],
            DCGenerator=[{"idx": 1, "name": "shared-storage", "p_set": 0, "run_stat": 1}],
            DCStorageGen=[
                {
                    "idx": 1,
                    "idx_dcgenerator": 1,
                    "energy_capacity": 200,
                    "max_charge_power": 80,
                    "max_discharge_power": 80,
                    "state_of_charge": 0.6,
                    "soc_upper_limit": 0.95,
                    "soc_lower_limit": 0.1,
                }
            ],
        )

        rows = simu_loop._embedded_device_define_book(model_book).data["estorage"].data

        self.assertEqual(
            [("ACGenerator", "shared-storage"), ("DCGenerator", "shared-storage")],
            [(row.get("dev_type"), row.get("source_name")) for row in rows],
        )

    def test_embedded_ac_storage_preserves_zero_initial_soc_without_device_file(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            ACGenerator=[{"idx": 1, "name": "ac-storage", "p_set": 0, "run_stat": 1}],
            ACStorageGen=[
                {
                    "idx": 1,
                    "idx_acgenerator": 1,
                    "energy_capacity": 100,
                    "state_of_charge": 0.0,
                }
            ],
        )

        rows = simu_loop._embedded_device_define_book(model_book).data["estorage"].data

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dev_type"], "ACGenerator")
        self.assertEqual(rows[0]["soc_cur"], 0.0)

    def test_embedded_dc_storage_preserves_zero_initial_soc_without_device_file(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            DCGenerator=[{"idx": 1, "name": "dc-storage", "p_set": 0, "run_stat": 1}],
            DCStorageGen=[
                {
                    "idx": 1,
                    "idx_dcgenerator": 1,
                    "energy_capacity": 100,
                    "state_of_charge": 0.0,
                }
            ],
        )

        rows = simu_loop._embedded_device_define_book(model_book).data["estorage"].data

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dev_type"], "DCGenerator")
        self.assertEqual(rows[0]["soc_cur"], 0.0)

    def test_embedded_storage_preserves_zero_soc_upper_limit(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            DCGenerator=[{"idx": 1, "name": "dc-storage", "p_set": 0, "run_stat": 1}],
            DCStorageGen=[
                {
                    "idx": 1,
                    "idx_dcgenerator": 1,
                    "energy_capacity": 100,
                    "soc_upper_limit": 0.0,
                }
            ],
        )

        row = simu_loop._embedded_device_define_book(model_book).data["estorage"].data[0]

        self.assertEqual(row["soc_max"], 0.0)

    def test_zero_soc_upper_limit_blocks_storage_charging(self):
        import simu_loop

        model_book, stat_book, dev_define = self._typed_storage_books(
            dev_type="DCGenerator",
            parameter_block="DCStorageGen",
            reference_field="idx_dcgenerator",
            setpoint=-40.0,
            soc=0.0,
            capacity=100.0,
            efficiency=1.0,
            soc_upper_limit=0.9,
            soc_lower_limit=-1.0,
        )
        model_book.data["DCStorageGen"].data[0]["soc_upper_limit"] = 0.0
        dev_define = simu_loop._embedded_device_define_book(model_book)
        status_by_name, status_rows = simu_loop._storage_soc_by_name_book(stat_book)

        simu_loop.apply_storage_constraints_book(
            model_book,
            status_by_name,
            status_rows,
            dev_define,
            period_seconds=3600.0,
        )

        self.assertEqual(float(model_book.data["DCGenerator"].data[0]["p_set"]), 0.0)

    def test_missing_storage_soc_row_uses_embedded_zero_and_blocks_discharge_end_to_end(self):
        import simu_loop

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        model_book = _memory_book(
            simu_loop,
            DCGenerator=[
                {
                    "idx": 1,
                    "name": "dc-storage",
                    "node": 1,
                    "control_type": "P",
                    "p_set": 40,
                    "v_set": 300,
                    "i_set": 0,
                    "run_stat": 1,
                }
            ],
            DCStorageGen=[
                {
                    "idx": 1,
                    "idx_dcgenerator": 1,
                    "energy_capacity": 100,
                    "max_charge_power": 40,
                    "max_discharge_power": 40,
                    "state_of_charge": 0.0,
                    "soc_upper_limit": 1.0,
                    "soc_lower_limit": 0.0,
                    "charge_discharge_efficiency": 1.0,
                }
            ],
        )
        stat_book = _memory_book(simu_loop, SetValue=[])
        solver_seen: dict[str, float] = {}

        def fake_solver(rows):
            solver_seen["p_set"] = float(rows["DCGenerator"][0]["p_set"])
            return (
                _SolvedStorageSnapshot(
                    {("DCGenerator", "dc-storage"): {"power": solver_seen["p_set"], "run_stat": 1}}
                ),
                "fake-solver",
            )

        config = simu_loop.SimulationConfig(
            model_file=root / "model.e",
            meas_file=root / "meas.e",
            weather_file=root / "weather.e",
            dev_stat_file=root / "stat.e",
            yt_ctrl_file=root / "yt_ctrl.e",
            real_file=root / "real.e",
            scada_file=root / "scada.e",
            period_seconds=3600.0,
            write_output_files=False,
            model_book=model_book,
            meas_rows=[],
            dev_stat_book=stat_book,
        )

        simu_loop.run_once(config, solver=fake_solver)

        self.assertEqual(solver_seen["p_set"], 0.0)
        rows = stat_book.data["StorageSoc"].data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dev_type"], "DCGenerator")
        self.assertEqual(rows[0]["name"], "dc-storage")
        self.assertEqual(float(rows[0]["soc_curr"]), 0.0)

    def test_storage_targets_keep_ac_and_dc_same_name_identities_separate(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            ACGenerator=[{"idx": 1, "name": "shared-storage", "p_set": 0, "run_stat": 1}],
            ACStorageGen=[{"idx": 1, "idx_acgenerator": 1, "energy_capacity": 100}],
            DCGenerator=[{"idx": 1, "name": "shared-storage", "p_set": 0, "run_stat": 1}],
            DCStorageGen=[{"idx": 1, "idx_dcgenerator": 1, "energy_capacity": 100}],
        )
        dev_define = simu_loop._embedded_device_define_book(model_book)

        targets = simu_loop._storage_target_rows(model_book, dev_define)

        self.assertTrue(all(len(target) == 5 for target in targets))
        self.assertEqual(
            [("ACGenerator", "shared-storage"), ("DCGenerator", "shared-storage")],
            [(dev_type, row["name"]) for dev_type, row, _storage_name, _define, _pos in targets],
        )

    def test_limits_ac_storage_discharge_and_integrates_one_hour_soc_margin(self):
        executed_power, next_soc = self._run_typed_storage_case(
            dev_type="ACGenerator",
            parameter_block="ACStorageGen",
            reference_field="idx_acgenerator",
            soc=0.21,
            p_set=40.0,
            period_seconds=3600.0,
        )

        self.assertAlmostEqual(executed_power, 1.0)
        self.assertAlmostEqual(next_soc, 0.2)

    def test_dc_typed_storage_discharge_behavior_remains_unchanged(self):
        executed_power, next_soc = self._run_typed_storage_case(
            dev_type="DCGenerator",
            parameter_block="DCStorageGen",
            reference_field="idx_dcgenerator",
            soc=0.21,
            p_set=40.0,
            period_seconds=3600.0,
        )

        self.assertAlmostEqual(executed_power, 1.0)
        self.assertAlmostEqual(next_soc, 0.2)

    def test_storage_without_structural_reference_is_not_automatically_controlled(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            DCGenerator=[
                {
                    "idx": 1,
                    "name": "battery-source",
                    "dev_type": "dc-storage",
                    "p_set": 40,
                    "run_stat": 1,
                }
            ],
        )
        stat_book = _memory_book(
            simu_loop,
            StorageSoc=[{"dev_type": "ESS", "idx": 1, "name": "battery-source", "soc_curr": 0.21}],
        )
        dev_define = _memory_book(
            simu_loop,
            estorage=[
                {
                    "id": 1,
                    "name": "legacy-slot",
                    "dev_type": "",
                    "source_name": "",
                    "emva": 100,
                    "soc_max": 0.9,
                    "soc_min": 0.2,
                    "soc_cur": 0.5,
                    "charge_p_max": 40,
                    "dis_charge_p_max": 40,
                }
            ],
        )
        status_by_name, status_rows = simu_loop._storage_soc_by_name_book(stat_book)

        simu_loop.apply_storage_constraints_book(
            model_book,
            status_by_name,
            status_rows,
            dev_define,
            period_seconds=3600.0,
        )

        self.assertEqual(simu_loop._storage_target_rows(model_book, dev_define), [])
        self.assertAlmostEqual(float(model_book.data["DCGenerator"].data[0]["p_set"]), 40.0)

    def test_ac_storage_soc_uses_actual_solved_generator_power(self):
        next_soc = self._integrate_typed_storage_soc(
            dev_type="ACGenerator",
            parameter_block="ACStorageGen",
            reference_field="idx_acgenerator",
            setpoint=0.0,
            actual_power=10.0,
            soc=0.5,
            capacity=100.0,
            efficiency=1.0,
            period_seconds=3600.0,
        )

        self.assertAlmostEqual(next_soc, 0.4)

    def test_ac_storage_soc_uses_zero_when_matching_snapshot_state_is_missing(self):
        import simu_loop

        model_book, stat_book, dev_define = self._typed_storage_books(
            dev_type="ACGenerator",
            parameter_block="ACStorageGen",
            reference_field="idx_acgenerator",
            setpoint=0.0,
            soc=0.5,
            capacity=100.0,
            efficiency=1.0,
        )
        snapshot = _SolvedStorageSnapshot(
            {},
            reported_powers={("ACGenerator", "storage-1"): 10.0},
        )

        simu_loop.update_storage_soc_book(stat_book, model_book, 3600.0, dev_define, snapshot=snapshot)

        self.assertAlmostEqual(float(stat_book.data["StorageSoc"].data[0]["soc_curr"]), 0.5)

    def test_ac_storage_soc_ignores_opposite_domain_only_snapshot_state(self):
        import simu_loop

        model_book, stat_book, dev_define = self._typed_storage_books(
            dev_type="ACGenerator",
            parameter_block="ACStorageGen",
            reference_field="idx_acgenerator",
            setpoint=0.0,
            soc=0.5,
            capacity=100.0,
            efficiency=1.0,
        )
        snapshot = _SolvedStorageSnapshot(
            {("DCGenerator", "storage-1"): {"power": 0.0, "run_stat": 1}},
            reported_powers={("ACGenerator", "storage-1"): 10.0},
        )

        simu_loop.update_storage_soc_book(stat_book, model_book, 3600.0, dev_define, snapshot=snapshot)

        self.assertAlmostEqual(float(stat_book.data["StorageSoc"].data[0]["soc_curr"]), 0.5)

    def test_dc_storage_soc_uses_actual_solved_generator_power(self):
        next_soc = self._integrate_typed_storage_soc(
            dev_type="DCGenerator",
            parameter_block="DCStorageGen",
            reference_field="idx_dcgenerator",
            setpoint=0.0,
            actual_power=10.0,
            soc=0.5,
            capacity=100.0,
            efficiency=1.0,
            period_seconds=3600.0,
        )

        self.assertAlmostEqual(next_soc, 0.4)

    def test_typed_ac_storage_soc_integration_remains_unclipped(self):
        next_soc = self._integrate_typed_storage_soc(
            dev_type="ACGenerator",
            parameter_block="ACStorageGen",
            reference_field="idx_acgenerator",
            setpoint=0.0,
            actual_power=-10.0,
            soc=1.05,
            capacity=100.0,
            efficiency=1.0,
            period_seconds=3600.0,
        )

        self.assertAlmostEqual(next_soc, 1.15)

    def test_typed_storage_soc_rows_do_not_cross_match_same_named_ac_and_dc_generators(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            ACGenerator=[{"idx": 1, "name": "shared-storage", "p_set": 0, "run_stat": 1}],
            ACStorageGen=[{"idx": 1, "idx_acgenerator": 1, "energy_capacity": 100, "charge_discharge_efficiency": 1}],
            DCGenerator=[{"idx": 1, "name": "shared-storage", "p_set": 0, "run_stat": 1}],
            DCStorageGen=[{"idx": 1, "idx_dcgenerator": 1, "energy_capacity": 100, "charge_discharge_efficiency": 1}],
        )
        stat_book = _memory_book(
            simu_loop,
            StorageSoc=[
                {"dev_type": "ACGenerator", "idx": 1, "name": "shared-storage", "soc_curr": 0.5},
                {"dev_type": "DCGenerator", "idx": 2, "name": "shared-storage", "soc_curr": 0.5},
            ],
        )
        dev_define = simu_loop._embedded_device_define_book(model_book)
        snapshot = _SolvedStorageSnapshot(
            {
                ("ACGenerator", "shared-storage"): {"power": 10.0},
                ("DCGenerator", "shared-storage"): {"power": 20.0},
            }
        )

        simu_loop.update_storage_soc_book(stat_book, model_book, 3600.0, dev_define, snapshot=snapshot)

        rows = stat_book.data["StorageSoc"].data
        self.assertAlmostEqual(float(rows[0]["soc_curr"]), 0.4)
        self.assertAlmostEqual(float(rows[1]["soc_curr"]), 0.3)

    def test_legacy_storage_soc_identity_resolves_only_when_unambiguous(self):
        for legacy_dev_type in ("", "ESS", "Storage"):
            with self.subTest(dev_type=legacy_dev_type or "blank"):
                next_soc = self._integrate_typed_storage_soc(
                    dev_type="ACGenerator",
                    parameter_block="ACStorageGen",
                    reference_field="idx_acgenerator",
                    setpoint=0.0,
                    actual_power=10.0,
                    soc=0.5,
                    capacity=100.0,
                    efficiency=1.0,
                    period_seconds=3600.0,
                    soc_dev_type=legacy_dev_type,
                )
                self.assertAlmostEqual(next_soc, 0.4)

    def test_ambiguous_legacy_storage_soc_identity_remains_unresolved(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            ACGenerator=[{"idx": 1, "name": "shared-storage", "p_set": 0, "run_stat": 1}],
            ACStorageGen=[{"idx": 1, "idx_acgenerator": 1, "energy_capacity": 100}],
            DCGenerator=[{"idx": 1, "name": "shared-storage", "p_set": 0, "run_stat": 1}],
            DCStorageGen=[{"idx": 1, "idx_dcgenerator": 1, "energy_capacity": 100}],
        )
        stat_book = _memory_book(
            simu_loop,
            StorageSoc=[{"dev_type": "", "idx": 1, "name": "shared-storage", "soc_curr": 0.5}],
        )
        dev_define = simu_loop._embedded_device_define_book(model_book)
        snapshot = _SolvedStorageSnapshot(
            {
                ("ACGenerator", "shared-storage"): {"power": 10.0},
                ("DCGenerator", "shared-storage"): {"power": 20.0},
            }
        )

        changed = simu_loop.update_storage_soc_book(stat_book, model_book, 3600.0, dev_define, snapshot=snapshot)

        self.assertEqual(changed, 0)
        self.assertAlmostEqual(float(stat_book.data["StorageSoc"].data[0]["soc_curr"]), 0.5)

    def _assert_inactive_snapshot_uses_zero_power(self, dev_type: str, *, dead_island: bool) -> None:
        import simu_loop

        parameter_block = "ACStorageGen" if dev_type == "ACGenerator" else "DCStorageGen"
        reference_field = "idx_acgenerator" if dev_type == "ACGenerator" else "idx_dcgenerator"
        source_name = f"{dev_type}-storage"
        model_book, stat_book, dev_define = self._typed_storage_books(
            dev_type=dev_type,
            parameter_block=parameter_block,
            reference_field=reference_field,
            setpoint=0.0,
            soc=0.5,
            capacity=100.0,
            efficiency=1.0,
            source_name=source_name,
        )
        online_snapshot = _SolvedStorageSnapshot({(dev_type, source_name): {"power": 10.0}})
        simu_loop.update_storage_soc_book(stat_book, model_book, 3600.0, dev_define, snapshot=online_snapshot)
        self.assertAlmostEqual(float(stat_book.data["StorageSoc"].data[0]["soc_curr"]), 0.4)

        run_stat = 1 if dead_island else 0
        inactive_snapshot = _SolvedStorageSnapshot(
            {
                (dev_type, source_name): {
                    "power": 10.0,
                    "run_stat": run_stat,
                    "dead_island": dead_island,
                }
            }
        )
        simu_loop.update_storage_soc_book(
            stat_book,
            model_book,
            3600.0,
            dev_define,
            storage_power_by_name={source_name: 10.0},
            snapshot=inactive_snapshot,
        )

        self.assertAlmostEqual(float(stat_book.data["StorageSoc"].data[0]["soc_curr"]), 0.4)

    def test_offline_ac_and_dc_storage_snapshots_use_zero_instead_of_stale_power(self):
        for dev_type in ("ACGenerator", "DCGenerator"):
            with self.subTest(dev_type=dev_type):
                self._assert_inactive_snapshot_uses_zero_power(dev_type, dead_island=False)

    def test_dead_island_ac_and_dc_storage_snapshots_use_zero_instead_of_stale_power(self):
        for dev_type in ("ACGenerator", "DCGenerator"):
            with self.subTest(dev_type=dev_type):
                self._assert_inactive_snapshot_uses_zero_power(dev_type, dead_island=True)

    def test_dc_export_limits_use_converter_limits_not_storage_names(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            ACGenerator=[{"idx": 1, "name": "shared-storage", "p_set": 40, "run_stat": 1}],
            ACStorageGen=[{"idx": 1, "idx_acgenerator": 1, "energy_capacity": 100}],
            DCGenerator=[{"idx": 1, "name": "shared-storage", "p_set": 40, "run_stat": 1}],
            DCStorageGen=[{"idx": 1, "idx_dcgenerator": 1, "energy_capacity": 100}],
            ACRealBs=[{"idx": 1, "name": "ac-anchor", "node": 1, "run_stat": 1}],
            DCRealBs=[{"idx": 1, "name": "dc-anchor", "node": 2, "run_stat": 1}],
            DCACConverter=[
                {
                    "idx": 1,
                    "name": "grid-inv-1",
                    "ac_node": 1,
                    "dc_node": 2,
                    "ac_control_type": "PQ",
                    "p_ac_set": -80,
                    "p_ac_min": -50,
                    "p_ac_max": 50,
                    "run_stat": 1,
                }
            ],
        )
        dev_define = simu_loop._embedded_device_define_book(model_book)

        simu_loop.apply_dc_export_limits(model_book, dev_define, efficiency=1.0)

        self.assertAlmostEqual(float(model_book.data["DCACConverter"].data[0]["p_ac_set"]), -50.0)

    def test_malformed_typed_ac_storage_definition_does_not_fallback_to_dc_storage_lookalike(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            ACGenerator=[{"idx": 1, "name": "actual-ac-generator", "p_set": 0, "run_stat": 1}],
            ACStorageGen=[{"idx": 1, "idx_acgenerator": 999, "energy_capacity": 100}],
            DCGenerator=[{"idx": 1, "name": "storage_1", "p_set": 40, "run_stat": 1}],
            DCACConverter=[{"idx": 1, "name": "grid-inv-1", "ac_control_type": "PQ", "p_ac_set": -40, "run_stat": 1}],
        )
        dev_define = simu_loop._embedded_device_define_book(model_book)

        targets = simu_loop._storage_target_rows(model_book, dev_define)
        simu_loop.apply_dc_export_limits(model_book, dev_define, efficiency=1.0)

        self.assertEqual(targets, [])
        self.assertAlmostEqual(float(model_book.data["DCACConverter"].data[0]["p_ac_set"]), -40.0)

    def test_malformed_embedded_ac_storage_link_does_not_target_same_domain_lookalike(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            ACGenerator=[
                {
                    "idx": 1,
                    "name": "storage_1",
                    "dev_type": "diesel-source",
                    "p_set": 40,
                    "run_stat": 1,
                }
            ],
            ACStorageGen=[
                {
                    "idx": 1,
                    "idx_acgenerator": 999,
                    "energy_capacity": 100,
                    "max_discharge_power": 40,
                    "soc_lower_limit": 0.2,
                }
            ],
        )
        stat_book = _memory_book(
            simu_loop,
            StorageSoc=[{"dev_type": "ACGenerator", "idx": 1, "name": "storage_1", "soc_curr": 0.21}],
        )
        dev_define = simu_loop._embedded_device_define_book(model_book)
        status_by_name, status_rows = simu_loop._storage_soc_by_name_book(stat_book)

        targets = simu_loop._storage_target_rows(model_book, dev_define)
        simu_loop.apply_storage_constraints_book(
            model_book,
            status_by_name,
            status_rows,
            dev_define,
            period_seconds=3600.0,
        )

        self.assertEqual(dev_define.data["estorage"].data, [])
        self.assertEqual(targets, [])
        self.assertAlmostEqual(float(model_book.data["ACGenerator"].data[0]["p_set"]), 40.0)

    def test_explicit_typed_storage_source_name_does_not_fallback_to_logical_name(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            ACGenerator=[{"idx": 1, "name": "storage_1", "p_set": 40, "run_stat": 1}],
        )
        dev_define = _memory_book(
            simu_loop,
            estorage=[
                {
                    "id": 1,
                    "name": "storage_1",
                    "dev_type": "ACGenerator",
                    "source_name": "missing-ac-source",
                    "emva": 100,
                }
            ],
        )

        self.assertEqual(simu_loop._storage_target_rows(model_book, dev_define), [])

    def test_exact_typed_battery_names_resolve_before_vsrc_aliases(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            ACGenerator=[
                {"idx": 1, "name": "battery", "p_set": 0, "run_stat": 1},
                {"idx": 2, "name": "battery_vsrc", "p_set": 0, "run_stat": 1},
            ],
            ACStorageGen=[
                {"idx": 1, "idx_acgenerator": 1, "energy_capacity": 100, "charge_discharge_efficiency": 1},
                {"idx": 2, "idx_acgenerator": 2, "energy_capacity": 100, "charge_discharge_efficiency": 1},
            ],
        )
        stat_book = _memory_book(
            simu_loop,
            StorageSoc=[
                {"dev_type": "ACGenerator", "idx": 1, "name": "battery", "soc_curr": 0.5},
                {"dev_type": "ACGenerator", "idx": 2, "name": "battery_vsrc", "soc_curr": 0.5},
            ],
        )
        dev_define = simu_loop._embedded_device_define_book(model_book)

        simu_loop.update_storage_soc_book(
            stat_book,
            model_book,
            3600.0,
            dev_define,
            storage_power_by_name={
                ("ACGenerator", "battery"): 10.0,
                ("ACGenerator", "battery_vsrc"): 20.0,
            },
        )

        rows = stat_book.data["StorageSoc"].data
        self.assertAlmostEqual(float(rows[0]["soc_curr"]), 0.4)
        self.assertAlmostEqual(float(rows[1]["soc_curr"]), 0.3)

    def test_battery_vsrc_missing_exact_power_does_not_consume_battery_power(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            ACGenerator=[
                {"idx": 1, "name": "battery", "p_set": 0, "run_stat": 1},
                {"idx": 2, "name": "battery_vsrc", "p_set": 30, "run_stat": 1},
            ],
            ACStorageGen=[
                {"idx": 1, "idx_acgenerator": 1, "energy_capacity": 100, "charge_discharge_efficiency": 1},
                {"idx": 2, "idx_acgenerator": 2, "energy_capacity": 100, "charge_discharge_efficiency": 1},
            ],
        )
        stat_book = _memory_book(
            simu_loop,
            StorageSoc=[
                {"dev_type": "ACGenerator", "idx": 1, "name": "battery", "soc_curr": 0.5},
                {"dev_type": "ACGenerator", "idx": 2, "name": "battery_vsrc", "soc_curr": 0.5},
            ],
        )
        dev_define = simu_loop._embedded_device_define_book(model_book)
        snapshot = _SolvedStorageSnapshot(
            {
                ("ACGenerator", "battery"): {"run_stat": 1},
                ("ACGenerator", "battery_vsrc"): {"run_stat": 1},
            },
            reported_powers={
                ("ACGenerator", "battery"): 10.0,
                ("ACGenerator", "battery_vsrc"): None,
            },
        )

        simu_loop.update_storage_soc_book(
            stat_book,
            model_book,
            3600.0,
            dev_define,
            storage_power_by_name={("ACGenerator", "battery_vsrc"): 30.0},
            snapshot=snapshot,
        )

        rows = stat_book.data["StorageSoc"].data
        self.assertAlmostEqual(float(rows[0]["soc_curr"]), 0.4)
        self.assertAlmostEqual(float(rows[1]["soc_curr"]), 0.5)

    def test_snapshot_storage_power_does_not_read_nonstorage_base_name_alias(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            ACGenerator=[
                {"idx": 1, "name": "battery", "p_set": 0, "run_stat": 1},
                {"idx": 2, "name": "battery_vsrc", "p_set": 0, "run_stat": 1},
            ],
            ACStorageGen=[
                {"idx": 1, "idx_acgenerator": 2, "energy_capacity": 100, "charge_discharge_efficiency": 1},
            ],
        )
        stat_book = _memory_book(
            simu_loop,
            StorageSoc=[
                {"dev_type": "ACGenerator", "idx": 1, "name": "battery_vsrc", "soc_curr": 0.5},
            ],
        )
        dev_define = simu_loop._embedded_device_define_book(model_book)
        snapshot = _SolvedStorageSnapshot(
            {("ACGenerator", "battery_vsrc"): {"run_stat": 1}},
            reported_powers={
                ("ACGenerator", "battery"): 20.0,
                ("ACGenerator", "battery_vsrc"): None,
            },
        )

        snapshot_powers = simu_loop._snapshot_storage_power_by_name(snapshot, model_book, dev_define)
        simu_loop.update_storage_soc_book(
            stat_book,
            model_book,
            3600.0,
            dev_define,
            storage_power_by_name={("ACGenerator", "battery_vsrc"): 99.0},
            snapshot=snapshot,
        )

        self.assertEqual(snapshot_powers, {("ACGenerator", "battery_vsrc"): 0.0})
        self.assertAlmostEqual(float(stat_book.data["StorageSoc"].data[0]["soc_curr"]), 0.5)

    def test_structurally_referenced_ac_and_dc_storage_targets_are_retained(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            ACGenerator=[{"idx": 1, "name": "typed-ac-storage", "p_set": 0, "run_stat": 1}],
            ACStorageGen=[
                {
                    "idx": 1,
                    "idx_acgenerator": 1,
                    "energy_capacity": 100,
                    "soc_upper_limit": 0.9,
                    "soc_lower_limit": 0.2,
                    "max_charge_power": 40,
                    "max_discharge_power": 40,
                }
            ],
            DCGenerator=[
                {
                    "idx": 1,
                    "name": "legacy-dc-source",
                    "dev_type": "dc-storage",
                    "p_set": 40,
                    "run_stat": 1,
                }
            ],
            DCStorageGen=[
                {
                    "idx": 2,
                    "idx_dcgenerator": 1,
                    "energy_capacity": 100,
                    "soc_upper_limit": 0.9,
                    "soc_lower_limit": 0.2,
                    "max_charge_power": 40,
                    "max_discharge_power": 40,
                }
            ],
        )
        stat_book = _memory_book(
            simu_loop,
            StorageSoc=[
                {"dev_type": "ACGenerator", "idx": 1, "name": "typed-ac-storage", "soc_curr": 0.5},
                {"dev_type": "ESS", "idx": 2, "name": "legacy-dc-source", "soc_curr": 0.21},
            ],
        )
        dev_define = _memory_book(
            simu_loop,
            estorage=[
                {
                    "id": 1,
                    "name": "legacy-slot",
                    "dev_type": "",
                    "source_name": "",
                    "emva": 100,
                    "soc_max": 0.9,
                    "soc_min": 0.2,
                    "charge_p_max": 40,
                    "dis_charge_p_max": 40,
                },
                {
                    "id": 2,
                    "name": "typed-ac-storage",
                    "dev_type": "ACGenerator",
                    "source_name": "typed-ac-storage",
                    "emva": 100,
                    "soc_max": 0.9,
                    "soc_min": 0.2,
                    "charge_p_max": 40,
                    "dis_charge_p_max": 40,
                },
            ],
        )
        status_by_name, status_rows = simu_loop._storage_soc_by_name_book(stat_book)

        targets = simu_loop._storage_target_rows(model_book, dev_define)
        simu_loop.apply_storage_constraints_book(
            model_book,
            status_by_name,
            status_rows,
            dev_define,
            period_seconds=3600.0,
        )

        self.assertEqual(
            [("ACGenerator", "typed-ac-storage"), ("DCGenerator", "legacy-dc-source")],
            [(dev_type, row["name"]) for dev_type, row, _name, _define, _pos in targets],
        )
        self.assertAlmostEqual(float(model_book.data["DCGenerator"].data[0]["p_set"]), 1.0)

    def test_structural_storage_definition_wins_over_external_legacy_rows(self):
        import simu_loop

        model_book = _memory_book(
            simu_loop,
            DCGenerator=[{"idx": 1, "name": "storage-1", "p_set": 0, "run_stat": 1}],
            DCStorageGen=[
                {
                    "idx": 1,
                    "idx_dcgenerator": 1,
                    "energy_capacity": 100,
                    "definition_kind": "structured",
                }
            ],
        )
        dev_define = _memory_book(
            simu_loop,
            estorage=[
                {
                    "id": 1,
                    "name": "storage-1",
                    "dev_type": "",
                    "source_name": "",
                    "emva": 999,
                    "definition_kind": "legacy",
                },
                {
                    "id": 2,
                    "name": "storage-1",
                    "dev_type": "DCGenerator",
                    "source_name": "storage-1",
                    "emva": 100,
                    "definition_kind": "typed",
                },
            ],
        )

        targets = simu_loop._storage_target_rows(model_book, dev_define)

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0][3]["definition_kind"], "structured")

    def test_online_storage_missing_current_power_overrides_stale_power_with_zero(self):
        import simu_loop

        for current_power in (None, float("nan"), float("inf"), -float("inf")):
            with self.subTest(current_power=current_power):
                model_book, stat_book, dev_define = self._typed_storage_books(
                    dev_type="ACGenerator",
                    parameter_block="ACStorageGen",
                    reference_field="idx_acgenerator",
                    setpoint=10.0,
                    soc=0.5,
                    capacity=100.0,
                    efficiency=1.0,
                )
                snapshot = _SolvedStorageSnapshot(
                    {("ACGenerator", "storage-1"): {"run_stat": 1}},
                    reported_powers={("ACGenerator", "storage-1"): current_power},
                )

                simu_loop.update_storage_soc_book(
                    stat_book,
                    model_book,
                    3600.0,
                    dev_define,
                    storage_power_by_name={"storage-1": 10.0},
                    snapshot=snapshot,
                )

                self.assertAlmostEqual(float(stat_book.data["StorageSoc"].data[0]["soc_curr"]), 0.5)

    def test_typed_generator_soc_measurement_uses_integrated_storage_value(self):
        import simu_loop

        for dev_type in ("ACGenerator", "DCGenerator"):
            with self.subTest(dev_type=dev_type):
                snapshot = _SolvedStorageSnapshot({(dev_type, "storage-1"): {"power": 10.0}})
                source_row = [
                    "1",
                    f"{dev_type}.storage-1.SOC",
                    dev_type,
                    "storage-1",
                    "SOC",
                    "10000",
                    "1",
                    "0.5",
                ]

                _before, rows, _after, updated, missing = simu_loop.build_real_rows_from_data(
                    [source_row],
                    snapshot,
                    storage_soc={"storage-1": 0.3481481524},
                )

                self.assertEqual(updated, 1)
                self.assertEqual(missing, 0)
                self.assertAlmostEqual(float(rows[0][7]), 0.3481481524)

    def test_weight_derived_soc_noise_tracks_normalized_soc_units(self):
        import simu_loop

        normalized_row = ["1", "storage.soc", "ACGenerator", "storage-1", "SOC", "10000", "1", "0.5"]
        legacy_row = [*normalized_row]
        legacy_row[7] = "50"

        self.assertAlmostEqual(simu_loop._row_noise_sigma(normalized_row, None), 0.0001)
        self.assertAlmostEqual(simu_loop._row_noise_sigma(legacy_row, None), 0.01)
        self.assertAlmostEqual(simu_loop._row_noise_sigma(normalized_row, 0.02), 0.02)

    def test_scada_soc_noise_preserves_out_of_range_values(self):
        import simu_loop

        class FixedNoise:
            def __init__(self, value: float) -> None:
                self.value = value

            def gauss(self, _mean: float, _sigma: float) -> float:
                return self.value

        soc_row = ["1", "storage.soc", "DCGenerator", "storage-1", "SOC", "10000", "1", "1.0"]
        upper = simu_loop.add_noise_to_rows([soc_row], 0.1, FixedNoise(0.2))
        lower_row = [*soc_row]
        lower_row[7] = "0.0"
        lower = simu_loop.add_noise_to_rows([lower_row], 0.1, FixedNoise(-0.2))

        self.assertAlmostEqual(float(upper[0][7]), 1.2)
        self.assertAlmostEqual(float(lower[0][7]), -0.2)

    def test_scada_noise_uses_editable_median_deviation_as_gaussian_mean(self):
        import simu_loop

        class RecordingNoise:
            def __init__(self) -> None:
                self.calls = []

            def gauss(self, mean: float, sigma: float) -> float:
                self.calls.append((mean, sigma))
                return mean

        rng = RecordingNoise()
        analog_row = ["1", "diesel.p", "ACGenerator", "diesel-1", "P_GEN", "25", "1", "10"]
        signal_row = ["2", "diesel.run", "ACGenerator", "diesel-1", "RUN_STAT", "25", "1", "1"]

        rows = simu_loop.add_noise_to_rows(
            [analog_row, signal_row],
            None,
            rng,
            {"diesel.p": -0.4, "diesel.run": 99.0},
        )

        self.assertEqual(rng.calls, [(-0.4, 0.2)])
        self.assertAlmostEqual(float(rows[0][7]), 9.6)
        self.assertEqual(rows[1][7], "1")

    def test_limits_storage_from_model_embedded_device_block_without_device_file(self):
        import simu_loop

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        model_file = root / "model.e"
        stat_file = root / "stat.e"
        meas_file = root / "meas.e"
        real_file = root / "real.e"
        scada_file = root / "scada.e"

        model_file.write_text(
            _efile_block(
                "DCGenerator",
                ("idx", "name", "dev_type", "node", "control_type", "p_set", "v_set", "i_set", "run_stat"),
                [
                    {
                        "idx": 1,
                        "name": "storage_alpha",
                        "dev_type": "dc-storage",
                        "node": 1,
                        "control_type": "P",
                        "p_set": 40,
                        "v_set": 300,
                        "i_set": 0,
                        "run_stat": 1,
                    }
                ],
            )
            + _efile_block(
                "DCStorageGen",
                (
                    "idx",
                    "idx_dcgenerator",
                    "storage_technology",
                    "energy_capacity",
                    "max_charge_power",
                    "max_discharge_power",
                    "state_of_charge",
                    "soc_upper_limit",
                    "soc_lower_limit",
                ),
                [
                    {
                        "idx": 1,
                        "idx_dcgenerator": 1,
                        "storage_technology": "lithium",
                        "energy_capacity": 100,
                        "max_charge_power": 40,
                        "max_discharge_power": 40,
                        "state_of_charge": "50%",
                        "soc_upper_limit": "90%",
                        "soc_lower_limit": "20%",
                    }
                ],
            ),
            encoding="utf-8",
        )
        stat_file.write_text(
            _efile_block(
                "SetValue",
                ("dev_type", "dev_name", "set_type", "set_value"),
                [{"dev_type": "DCGenerator", "dev_name": "storage_alpha", "set_type": "p_set", "set_value": 40}],
            )
            + _efile_block(
                "StorageSoc",
                ("dev_type", "idx", "name", "soc_curr"),
                [{"dev_type": "DCGenerator", "idx": 1, "name": "storage_alpha", "soc_curr": 0.21}],
            ),
            encoding="utf-8",
        )
        meas_file.write_text(MEAS_TEXT, encoding="utf-8")

        solver_seen: dict[str, float] = {}

        def fake_solver(merged_model: Path):
            book = simu_loop.EBook(merged_model)
            solver_seen["p_set"] = float(book.data["DCGenerator"].data[0]["p_set"])
            return (
                _SolvedStorageSnapshot(
                    {("DCGenerator", "storage_alpha"): {"power": solver_seen["p_set"], "run_stat": 1}}
                ),
                "fake-solver",
            )

        config = simu_loop.SimulationConfig(
            model_file=model_file,
            meas_file=meas_file,
            weather_file=root / "weather.e",
            dev_stat_file=stat_file,
            yt_ctrl_file=root / "yt_ctrl.e",
            dev_define_file=None,
            real_file=real_file,
            scada_file=scada_file,
            period_seconds=3600.0,
        )
        simu_loop.run_once(config, solver=fake_solver)

        stat_book = simu_loop.EBook(stat_file)
        self.assertAlmostEqual(solver_seen["p_set"], 1.0)
        self.assertAlmostEqual(float(stat_book.data["StorageSoc"].data[0]["soc_curr"]), 0.2)

    def _run_storage_case(self, soc: float, p_set: float, period_seconds: float) -> tuple[float, float]:
        import simu_loop

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        model_file = root / "model.e"
        stat_file = root / "stat.e"
        device_file = root / "device.e"
        meas_file = root / "meas.e"
        real_file = root / "real.e"
        scada_file = root / "scada.e"

        model_file.write_text(
            _efile_block(
                "DCGenerator",
                ("idx", "name", "node", "control_type", "p_set", "v_set", "i_set", "run_stat"),
                [{"idx": 1, "name": "storage-source", "node": 1, "control_type": "P", "p_set": 0, "v_set": 300, "i_set": 0, "run_stat": 1}],
            )
            + _efile_block(
                "DCStorageGen",
                (
                    "idx",
                    "idx_dcgenerator",
                    "energy_capacity",
                    "max_charge_power",
                    "max_discharge_power",
                    "state_of_charge",
                    "soc_upper_limit",
                    "soc_lower_limit",
                    "charge_discharge_efficiency",
                ),
                [
                    {
                        "idx": 1,
                        "idx_dcgenerator": 1,
                        "energy_capacity": 100,
                        "max_charge_power": 40,
                        "max_discharge_power": 40,
                        "state_of_charge": 0.5,
                        "soc_upper_limit": 0.9,
                        "soc_lower_limit": 0.2,
                        "charge_discharge_efficiency": 1.0,
                    }
                ],
            ),
            encoding="utf-8",
        )
        stat_file.write_text(
            _efile_block(
                "SetValue",
                ("dev_type", "dev_name", "set_type", "set_value"),
                [{"dev_type": "DCGenerator", "dev_name": "storage-source", "set_type": "p_set", "set_value": p_set}],
            )
            + _efile_block(
                "StorageSoc",
                ("dev_type", "idx", "name", "soc_curr"),
                [{"dev_type": "DCGenerator", "idx": 1, "name": "storage-source", "soc_curr": soc}],
            ),
            encoding="utf-8",
        )
        device_file.write_text(
            _efile_block(
                "estorage",
                ("id", "name", "emva", "soc_max", "soc_min", "soc_cur", "charge_p_max", "dis_charge_p_max"),
                [
                    {
                        "id": 1,
                        "name": "ess01",
                        "emva": 100,
                        "soc_max": 0.9,
                        "soc_min": 0.2,
                        "soc_cur": 0.5,
                        "charge_p_max": 40,
                        "dis_charge_p_max": 40,
                    }
                ],
            ),
            encoding="utf-8",
        )
        meas_file.write_text(MEAS_TEXT, encoding="utf-8")

        solver_seen: dict[str, float] = {}

        def fake_solver(merged_model: Path):
            book = simu_loop.EBook(merged_model)
            row = book.data["DCGenerator"].data[0]
            solver_seen["p_set"] = float(row["p_set"])
            return (
                _SolvedStorageSnapshot(
                    {("DCGenerator", "storage-source"): {"power": solver_seen["p_set"], "run_stat": 1}}
                ),
                "fake-solver",
            )

        config = simu_loop.SimulationConfig(
            model_file=model_file,
            meas_file=meas_file,
            weather_file=root / "weather.e",
            dev_stat_file=stat_file,
            yt_ctrl_file=root / "yt_ctrl.e",
            dev_define_file=None,
            real_file=real_file,
            scada_file=scada_file,
            period_seconds=period_seconds,
        )
        simu_loop.run_once(config, solver=fake_solver)

        stat_book = simu_loop.EBook(stat_file)
        next_soc = float(stat_book.data["StorageSoc"].data[0]["soc_curr"])
        return solver_seen["p_set"], next_soc

    def test_limits_discharge_power_by_soc_lower_bound_and_step_duration(self):
        executed_power, next_soc = self._run_storage_case(soc=0.21, p_set=40.0, period_seconds=3600.0)

        self.assertAlmostEqual(executed_power, 1.0)
        self.assertAlmostEqual(next_soc, 0.2)

    def test_limits_charge_power_by_soc_upper_bound_and_step_duration(self):
        executed_power, next_soc = self._run_storage_case(soc=0.89, p_set=-40.0, period_seconds=3600.0)

        self.assertAlmostEqual(executed_power, -1.0)
        self.assertAlmostEqual(next_soc, 0.9)

    def test_blocks_discharge_when_soc_is_already_below_lower_bound(self):
        executed_power, next_soc = self._run_storage_case(soc=0.0, p_set=10.0, period_seconds=60.0)

        self.assertAlmostEqual(executed_power, 0.0)
        self.assertAlmostEqual(next_soc, 0.0)

    def test_realtime_storage_power_bounds_follow_soc_limits(self):
        import simu_loop

        cases = (
            (0.2, 40.0, -40.0, 0.0),
            (0.5, 40.0, -40.0, 40.0),
            (0.9, -40.0, 0.0, 40.0),
        )
        for soc, command, expected_min, expected_max in cases:
            with self.subTest(soc=soc):
                model_book, stat_book, dev_define = self._typed_storage_books(
                    dev_type="DCGenerator",
                    parameter_block="DCStorageGen",
                    reference_field="idx_dcgenerator",
                    setpoint=command,
                    soc=soc,
                    capacity=100.0,
                    efficiency=1.0,
                )
                status_by_name, status_rows = simu_loop._storage_soc_by_name_book(stat_book)

                simu_loop.apply_storage_constraints_book(
                    model_book,
                    status_by_name,
                    status_rows,
                    dev_define,
                    period_seconds=0.0,
                )

                row = model_book.data["DCGenerator"].data[0]
                self.assertAlmostEqual(float(row["p_min"]), expected_min)
                self.assertAlmostEqual(float(row["p_max"]), expected_max)

    def test_realtime_storage_power_bounds_are_added_when_model_schema_omits_them(self):
        import simu_loop

        model_book, stat_book, dev_define = self._typed_storage_books(
            dev_type="DCGenerator",
            parameter_block="DCStorageGen",
            reference_field="idx_dcgenerator",
            setpoint=40.0,
            soc=0.2,
            capacity=100.0,
            efficiency=1.0,
        )
        generator_block = model_book.data["DCGenerator"]
        generator_block.header_list = [
            column for column in generator_block.header_list if column not in {"p_min", "p_max"}
        ]
        for generator_row in generator_block.data:
            generator_row.pop("p_min", None)
            generator_row.pop("p_max", None)
        self.assertNotIn("p_min", generator_block.header_list)
        self.assertNotIn("p_max", generator_block.header_list)

        status_by_name, status_rows = simu_loop._storage_soc_by_name_book(stat_book)
        simu_loop.apply_storage_constraints_book(
            model_book,
            status_by_name,
            status_rows,
            dev_define,
            period_seconds=0.0,
        )

        row = generator_block.data[0]
        self.assertIn("p_min", generator_block.header_list)
        self.assertIn("p_max", generator_block.header_list)
        self.assertAlmostEqual(float(row["p_min"]), -40.0)
        self.assertAlmostEqual(float(row["p_max"]), 0.0)

    def test_storage_soc_control_targets_typed_ac_storage_source(self):
        import simu_loop

        model_book, _stat_book, _dev_define = self._typed_storage_books(
            dev_type="ACGenerator",
            parameter_block="ACStorageGen",
            reference_field="idx_acgenerator",
            setpoint=0.0,
            soc=0.5,
            capacity=100.0,
            efficiency=1.0,
        )
        ctrl_book = _memory_book(
            simu_loop,
            StorageSoc=[
                {
                    "dev_type": "ACGenerator",
                    "idx": 1,
                    "name": "storage-1",
                    "p_set": 20.0,
                }
            ],
        )

        simu_loop.apply_yt_ctrl_book(model_book, ctrl_book)

        self.assertAlmostEqual(float(model_book.data["ACGenerator"].data[0]["p_set"]), 20.0)

    def _integrate_storage_soc(
        self,
        *,
        soc: float,
        actual_power: float,
        period_seconds: float = 3600.0,
    ) -> float:
        import simu_loop

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        stat_file = root / "stat.e"
        model_file = root / "model.e"
        device_file = root / "device.e"

        stat_file.write_text(
            _efile_block(
                "StorageSoc",
                ("dev_type", "idx", "name", "soc_curr"),
                [{"dev_type": "DCGenerator", "idx": 1, "name": "storage-source", "soc_curr": soc}],
            ),
            encoding="utf-8",
        )
        model_file.write_text(
            _efile_block(
                "DCGenerator",
                ("idx", "name", "node", "control_type", "p_set", "v_set", "i_set", "run_stat"),
                [
                    {
                        "idx": 1,
                        "name": "storage-source",
                        "node": 1,
                        "control_type": "P",
                        "p_set": 0,
                        "v_set": 300,
                        "i_set": 0,
                        "run_stat": 1,
                    }
                ],
            )
            + _efile_block(
                "DCStorageGen",
                (
                    "idx",
                    "idx_dcgenerator",
                    "energy_capacity",
                    "max_charge_power",
                    "max_discharge_power",
                    "state_of_charge",
                    "soc_upper_limit",
                    "soc_lower_limit",
                    "charge_discharge_efficiency",
                ),
                [
                    {
                        "idx": 1,
                        "idx_dcgenerator": 1,
                        "energy_capacity": 100,
                        "max_charge_power": 40,
                        "max_discharge_power": 40,
                        "state_of_charge": 0.5,
                        "soc_upper_limit": 0.9,
                        "soc_lower_limit": 0.2,
                        "charge_discharge_efficiency": 0.9,
                    }
                ],
            ),
            encoding="utf-8",
        )
        device_file.write_text(
            _efile_block(
                "estorage",
                ("id", "name", "emva", "soc_max", "soc_min", "soc_cur", "charge_p_max", "dis_charge_p_max", "charge_discharge_efficiency"),
                [
                    {
                        "id": 1,
                        "name": "ess01",
                        "emva": 100,
                        "soc_max": 0.9,
                        "soc_min": 0.2,
                        "soc_cur": 0.5,
                        "charge_p_max": 40,
                        "dis_charge_p_max": 40,
                        "charge_discharge_efficiency": 0.9,
                    }
                ],
            ),
            encoding="utf-8",
        )
        stat_book = simu_loop.EBook(stat_file)
        model_book = simu_loop.EBook(model_file)
        dev_define = simu_loop._embedded_device_define_book(model_book)

        changed = simu_loop.update_storage_soc_book(
            stat_book,
            model_book,
            period_seconds=period_seconds,
            dev_define=dev_define,
            storage_power_by_name={("DCGenerator", "storage-source"): actual_power},
        )

        self.assertEqual(changed, 1)
        return float(stat_book.data["StorageSoc"].data[0]["soc_curr"])

    def test_soc_integration_preserves_operational_limit_violation_below_physical_full(self):
        next_soc = self._integrate_storage_soc(soc=0.9, actual_power=-5.0)

        self.assertAlmostEqual(next_soc, 0.945)

    def test_soc_integration_preserves_value_above_physical_upper_bound(self):
        next_soc = self._integrate_storage_soc(soc=0.9, actual_power=-20.0)

        self.assertAlmostEqual(next_soc, 1.08)

    def test_soc_integration_preserves_value_below_physical_lower_bound(self):
        next_soc = self._integrate_storage_soc(soc=0.1, actual_power=20.0)

        self.assertAlmostEqual(next_soc, -0.1222222222)

    def test_soc_integration_continues_from_existing_overbound_value(self):
        next_soc = self._integrate_storage_soc(soc=1.08, actual_power=20.0)

        self.assertAlmostEqual(next_soc, 0.8577777778)

    def test_integrates_soc_from_actual_solved_storage_power_with_charge_efficiency_when_setpoint_is_zero(self):
        import simu_loop

        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        model_file = root / "model.e"
        stat_file = root / "stat.e"
        meas_file = root / "meas.e"

        model_file.write_text(
            _efile_block(
                "DCGenerator",
                ("idx", "name", "node", "control_type", "p_set", "v_set", "i_set", "run_stat"),
                [
                    {
                        "idx": 1,
                        "name": "ess01_vsrc",
                        "node": 1,
                        "control_type": "P",
                        "p_set": 0,
                        "v_set": 300,
                        "i_set": 0,
                        "run_stat": 1,
                    }
                ],
            )
            +
            _efile_block(
                "DCStorageGen",
                (
                    "idx",
                    "idx_dcgenerator",
                    "storage_technology",
                    "energy_capacity",
                    "max_charge_power",
                    "max_discharge_power",
                    "state_of_charge",
                    "soc_upper_limit",
                    "soc_lower_limit",
                    "charge_discharge_efficiency",
                ),
                [
                    {
                        "idx": 1,
                        "idx_dcgenerator": 1,
                        "storage_technology": "lithium",
                        "energy_capacity": 60,
                        "max_charge_power": 40,
                        "max_discharge_power": 40,
                        "state_of_charge": "50%",
                        "soc_upper_limit": "90%",
                        "soc_lower_limit": "20%",
                        "charge_discharge_efficiency": 0.9,
                    }
                ],
            ),
            encoding="utf-8",
        )
        stat_file.write_text(
            _efile_block(
                "StorageSoc",
                ("dev_type", "idx", "name", "soc_curr"),
                [{"dev_type": "ESS", "idx": 1, "name": "ess01", "soc_curr": 0.5}],
            ),
            encoding="utf-8",
        )
        meas_file.write_text(MEAS_TEXT, encoding="utf-8")

        class FakeSnapshot:
            device_states = [
                {
                    "dev_type": "DCGenerator",
                    "dev_name": "ess01_vsrc",
                    "run_stat": 1,
                    "dead_island": False,
                }
            ]

            def value(self, dev_type, dev_name, meas_type):
                if (dev_type, dev_name, meas_type) == ("DCGenerator", "ess01_vsrc", "P_GEN"):
                    return -12.0
                return 0.0

        def fake_solver(_model_rows):
            return FakeSnapshot(), "fake-solver"

        stat_book = simu_loop.EBook(stat_file)
        config = simu_loop.SimulationConfig(
            model_file=model_file,
            meas_file=meas_file,
            weather_file=root / "weather.e",
            dev_stat_file=stat_file,
            yt_ctrl_file=root / "yt_ctrl.e",
            dev_define_file=None,
            real_file=root / "real.e",
            scada_file=root / "scada.e",
            period_seconds=60.0,
            write_output_files=False,
            model_book=simu_loop.EBook(model_file),
            meas_rows=[],
            dev_stat_book=stat_book,
            dev_define_book=None,
        )

        simu_loop.run_once(config, solver=fake_solver)

        next_soc = float(stat_book.data["StorageSoc"].data[0]["soc_curr"])
        self.assertAlmostEqual(next_soc, 0.503)


if __name__ == "__main__":
    unittest.main()
