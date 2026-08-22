from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from shutil import copytree

import simu_loop
from simu.service import PolarMicrogridSimulator


ROOT = Path(__file__).resolve().parents[1]


class ClosedStatusControlTest(unittest.TestCase):
    def test_boundary_preparation_overwrites_closed_status_without_using_legacy_status(self):
        model_book = simu_loop.EBook(
            {
                "ACBreak": [
                    {
                        "idx": "1",
                        "name": "breaker",
                        "status": "1",
                        "closed_status_set": "1",
                        "closed_status": "1",
                        "run_stat": "1",
                    }
                ]
            }
        )
        stat_book = simu_loop.EBook(
            {
                "CbOpenStat": [
                    {
                        "dev_type": "ACBreak",
                        "dev_name": "breaker",
                        "closed_status_set": "0",
                        "closed_status": "1",
                        "status": "1",
                    }
                ]
            }
        )

        simu_loop.apply_closed_status_boundaries(model_book, stat_book)

        model_row = model_book.data["ACBreak"].data[0]
        self.assertEqual(str(model_row["closed_status_set"]), "0")
        self.assertEqual(str(model_row["closed_status"]), "0")
        self.assertEqual(str(model_row["status"]), "1")

        simu_loop.update_closed_status_results_book(stat_book, model_book)

        stat_row = stat_book.data["CbOpenStat"].data[0]
        self.assertEqual(str(stat_row["closed_status_set"]), "0")
        self.assertEqual(str(stat_row["closed_status"]), "0")
        self.assertEqual(str(stat_row["status"]), "0")

    def test_qinling_remote_open_uses_set_boundary_then_commits_actual_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            runtime = root / "runtime"
            copytree(ROOT / "models" / "simulator" / "source" / "秦岭站", source)
            service = PolarMicrogridSimulator(source, runtime, model_id="closed-status")

            service.step(advance_seconds=1.0)
            breaker = next(
                row
                for row in service.runtime_stat_book.data["CbOpenStat"].data
                if row.get("dev_type") == "ACBreak"
            )
            dev_type = str(breaker["dev_type"])
            dev_name = str(breaker["dev_name"])
            self.assertEqual(str(breaker["closed_status_set"]), "1")
            self.assertEqual(str(breaker["closed_status"]), "1")

            accepted = service.apply_student_commands(
                {
                    "run_status": [
                        {
                            "dev_type": dev_type,
                            "dev_name": dev_name,
                            "status": 0,
                        }
                    ]
                },
                source="trainee-ui",
            )
            commanded = next(
                row
                for row in service.runtime_stat_book.data["CbOpenStat"].data
                if row.get("dev_type") == dev_type and row.get("dev_name") == dev_name
            )
            self.assertEqual(accepted["run_status"], 1)
            self.assertEqual(str(commanded["closed_status_set"]), "0")
            self.assertEqual(str(commanded["closed_status"]), "1")

            snapshot = service.step(advance_seconds=1.0)
            calculated = next(
                row
                for row in service.runtime_stat_book.data["CbOpenStat"].data
                if row.get("dev_type") == dev_type and row.get("dev_name") == dev_name
            )
            model_result = next(
                row
                for row in service.latest_model_book.data[dev_type].data
                if row.get("name") == dev_name
            )
            device = next(
                row
                for row in snapshot["devices"]
                if row.get("dev_type") == dev_type and row.get("dev_name") == dev_name
            )
            status_measurement = next(
                row
                for row in snapshot["measurements"]["real"]
                if row.get("dev_type") == dev_type
                and row.get("dev_name") == dev_name
                and str(row.get("meas_type", "")).upper() == "STATUS"
            )
            self.assertEqual(str(calculated["closed_status_set"]), "0")
            self.assertEqual(str(calculated["closed_status"]), "0")
            self.assertEqual(str(model_result["closed_status_set"]), "0")
            self.assertEqual(str(model_result["closed_status"]), "0")
            self.assertEqual(device["closed_status_set"], 0)
            self.assertEqual(device["closed_status"], 0)
            self.assertEqual(float(status_measurement["value"]), 0.0)


if __name__ == "__main__":
    unittest.main()
