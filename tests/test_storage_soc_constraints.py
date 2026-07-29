from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


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


class StorageSocConstraintTest(unittest.TestCase):
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
            return object(), "fake-solver"

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
                [{"idx": 1, "name": "ess01_vsrc", "node": 1, "control_type": "P", "p_set": 0, "v_set": 300, "i_set": 0, "run_stat": 1}],
            ),
            encoding="utf-8",
        )
        stat_file.write_text(
            _efile_block(
                "SetValue",
                ("dev_type", "dev_name", "set_type", "set_value"),
                [{"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": p_set}],
            )
            + _efile_block(
                "StorageSoc",
                ("dev_type", "idx", "name", "soc_curr"),
                [{"dev_type": "ESS", "idx": 1, "name": "ess01", "soc_curr": soc}],
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
            return object(), "fake-solver"

        config = simu_loop.SimulationConfig(
            model_file=model_file,
            meas_file=meas_file,
            weather_file=root / "weather.e",
            dev_stat_file=stat_file,
            yt_ctrl_file=root / "yt_ctrl.e",
            dev_define_file=device_file,
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

    def test_soc_integration_preserves_unbounded_value_to_expose_control_errors(self):
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
                [{"dev_type": "ESS", "idx": 1, "name": "ess01", "soc_curr": 0.9}],
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
                        "name": "ess01_vsrc",
                        "node": 1,
                        "control_type": "P",
                        "p_set": 0,
                        "v_set": 300,
                        "i_set": 0,
                        "run_stat": 1,
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
        dev_define = simu_loop.EBook(device_file)

        changed = simu_loop.update_storage_soc_book(
            stat_book,
            model_book,
            period_seconds=3600.0,
            dev_define=dev_define,
            storage_power_by_name={"ess01_vsrc": -20.0},
        )

        self.assertEqual(changed, 1)
        self.assertAlmostEqual(float(stat_book.data["StorageSoc"].data[0]["soc_curr"]), 1.08)

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
