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
                "DCDCConverter",
                ("idx", "name", "p_set", "run_stat"),
                [{"idx": 1, "name": "ess01_dcdc", "p_set": 0, "run_stat": 1}],
            ),
            encoding="utf-8",
        )
        stat_file.write_text(
            _efile_block(
                "SetValue",
                ("dev_type", "dev_name", "set_type", "set_value"),
                [{"dev_type": "DCDCConverter", "dev_name": "ess01_dcdc", "set_type": "p_set", "set_value": p_set}],
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
            row = book.data["DCDCConverter"].data[0]
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
        self.assertAlmostEqual(next_soc, 0.2)


if __name__ == "__main__":
    unittest.main()
