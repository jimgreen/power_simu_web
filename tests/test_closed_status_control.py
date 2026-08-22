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

    def test_solver_entry_reapplies_the_latest_closed_status_set(self):
        model_book = simu_loop.EBook(
            {
                "ACBreak": [
                    {
                        "idx": "1",
                        "name": "breaker",
                        "status": "1",
                        "closed_status_set": "0",
                        "closed_status": "1",
                        "run_stat": "1",
                    }
                ]
            }
        )
        captured = {}

        def fake_solver(rows):
            captured["breaker"] = dict(rows["ACBreak"][0])
            return object(), "fake-solver"

        simu_loop._solve_snapshot_from_book(
            fake_solver,
            model_book,
            Path("closed-status.e"),
        )

        self.assertEqual(str(captured["breaker"]["closed_status_set"]), "0")
        self.assertEqual(str(captured["breaker"]["closed_status"]), "0")
        self.assertEqual(str(captured["breaker"]["status"]), "1")

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
            self.assertEqual(accepted["received_by"], "simulator")
            self.assertEqual(accepted["receive_state"], "completed")
            self.assertNotIn("queued", accepted)
            self.assertEqual(service.runtime_logs[-1]["result"], "接收完成，立即生效")
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

    def test_simulator_parameter_edit_commits_closed_status_after_next_power_flow(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            runtime = root / "runtime"
            copytree(
                ROOT / "models" / "simulator" / "source" / "IEEE118",
                source,
            )
            service = PolarMicrogridSimulator(
                source,
                runtime,
                model_id="closed-status-ui",
            )

            service.step(advance_seconds=1.0)
            breaker = next(
                row
                for row in service.runtime_stat_book.data["CbOpenStat"].data
                if row.get("dev_type") == "ACBreak"
                and row.get("dev_name") == "盒型开关-3"
            )
            dev_type = str(breaker["dev_type"])
            dev_name = str(breaker["dev_name"])
            model_row = next(
                row
                for row in service.definition_snapshot.model_book.data[dev_type].data
                if row.get("name") == dev_name
            )

            updated = service.update_device_parameters(
                {
                    "block_name": dev_type,
                    "row_key": {"idx": model_row.get("idx"), "name": dev_name},
                    "revision": service.definition_snapshot.revision,
                    "changes": {"closed_status_set": 0},
                }
            )

            commanded = next(
                row
                for row in service.runtime_stat_book.data["CbOpenStat"].data
                if row.get("dev_type") == dev_type and row.get("dev_name") == dev_name
            )
            self.assertEqual(updated["runtime_control"]["closed_status_set"], 0)
            self.assertEqual(str(commanded["closed_status_set"]), "0")
            self.assertEqual(str(commanded["closed_status"]), "1")

            snapshot = service.step(advance_seconds=1.0)
            calculated = next(
                row
                for row in service.runtime_stat_book.data["CbOpenStat"].data
                if row.get("dev_type") == dev_type and row.get("dev_name") == dev_name
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
            self.assertEqual(device["closed_status_set"], 0)
            self.assertEqual(device["closed_status"], 0)
            self.assertEqual(float(status_measurement["value"]), 0.0)

    def test_manual_override_queues_remote_close_until_override_is_reset(self):
        from simu.generate_simple_model import write_model_dir

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            runtime = root / "runtime"
            write_model_dir(source)
            model_path = source / "model.e"
            model_path.write_text(
                model_path.read_text(encoding="utf-8")
                + (
                    "<ACBreak>\n"
                    "@ idx name dev_type i_node j_node status closed_status_set run_stat closed_status\n"
                    "# 5 盒型开关-5 ac-box-breaker 1 2 1 1 1 1\n"
                    "</ACBreak>\n"
                ),
                encoding="utf-8",
            )
            breaker_control = (
                "<CbOpenStat>\n"
                "@ dev_type dev_name closed_status_set closed_status status\n"
                "# ACBreak 盒型开关-5 1 1 1\n"
                "</CbOpenStat>\n"
            )
            for file_name in ("stat.e", "control.e"):
                control_path = source / file_name
                control_path.write_text(
                    control_path.read_text(encoding="utf-8") + breaker_control,
                    encoding="utf-8",
                )
            service = PolarMicrogridSimulator(
                source,
                runtime,
                model_id="queued-closed-status",
                kernel=lambda _config: None,
            )
            breaker = next(
                row
                for row in service.definition_snapshot.model_book.data["ACBreak"].data
                if str(row.get("name")) == "盒型开关-5"
            )
            dev_name = str(breaker["name"])

            service.update_device_parameters(
                {
                    "block_name": "ACBreak",
                    "row_key": {"idx": breaker.get("idx"), "name": dev_name},
                    "revision": service.definition_snapshot.revision,
                    "changes": {"closed_status_set": 0},
                }
            )
            result = service.apply_student_commands(
                {
                    "manual_hold": True,
                    "run_status": [
                        {
                            "dev_type": "ACBreak",
                            "dev_name": dev_name,
                            "status": 1,
                        }
                    ],
                },
                source="trainee-ui",
            )

            self.assertEqual(result["run_status"], 1)
            self.assertEqual(result["ignored"], 0)
            self.assertEqual(result["queued"], 1)
            self.assertEqual(result["received_by"], "simulator")
            self.assertEqual(result["receive_state"], "completed")
            self.assertEqual(result["queue_owner"], "simulator")
            self.assertEqual(result["queue_state"], "waiting")
            self.assertEqual(
                result["blocked"],
                [
                    {
                        "kind": "remote_control",
                        "dev_type": "ACBreak",
                        "dev_name": dev_name,
                        "field": "status",
                        "reason": "simulator_manual_override",
                        "override_field": "closed_status_set",
                        "override_value": "0",
                        "modified_at": result["blocked"][0]["modified_at"],
                        "message": result["blocked"][0]["message"],
                    }
                ],
            )
            self.assertIn("模拟台人工修改", result["blocked"][0]["message"])
            history = service.command_history[-1]
            self.assertEqual(history["received_by"], "simulator")
            self.assertEqual(history["receive_state"], "completed")
            self.assertEqual(history["queued_at_acceptance"], 1)
            self.assertEqual(history["queue_owner_at_acceptance"], "simulator")
            self.assertEqual(history["queue_state_at_acceptance"], "waiting")
            self.assertEqual(history["blocked_at_acceptance"], result["blocked"])
            self.assertEqual(history["normalized"]["run_status"][0]["status"], "1")
            self.assertEqual(service.runtime_logs[-1]["result"], "接收完成，模拟台排队")
            self.assertIn(
                "学员台不保存等待任务",
                "\n".join(service.runtime_logs[-1]["detail"]),
            )
            queued_boundary = next(
                row
                for row in service.runtime_stat_book.data["CbOpenStat"].data
                if row.get("dev_type") == "ACBreak" and row.get("dev_name") == dev_name
            )
            self.assertEqual(str(queued_boundary["closed_status_set"]), "0")

            queued_commands = service.snapshot(
                include_static=False,
                include_runtime_logs=False,
                include_measurements=False,
                include_devices=False,
                include_device_states=False,
                include_command_history=False,
            )["commands"]
            self.assertEqual(queued_commands["effective"], [])
            self.assertEqual(len(queued_commands["queued"]), 1)
            queued_view = queued_commands["queued"][0]
            self.assertEqual(queued_view["queue_owner"], "simulator")
            self.assertEqual(queued_view["queue_state"], "waiting")
            self.assertEqual(
                queued_view["normalized"]["run_status"],
                [{"dev_type": "ACBreak", "dev_name": dev_name, "status": "1"}],
            )
            self.assertEqual(
                queued_view["blocked"][0]["reason"],
                "simulator_manual_override",
            )

            change = service.manual_definition_changes()["changes"][0]
            service.reset_manual_definition_changes(
                {
                    "revision": service.definition_snapshot.revision,
                    "change_ids": [change["id"]],
                }
            )

            released_boundary = next(
                row
                for row in service.runtime_stat_book.data["CbOpenStat"].data
                if row.get("dev_type") == "ACBreak" and row.get("dev_name") == dev_name
            )
            self.assertEqual(str(released_boundary["closed_status_set"]), "1")
            self.assertEqual(
                service.command_history[-1]["normalized"]["run_status"][0]["status"],
                "1",
            )
            released_commands = service.snapshot(
                include_static=False,
                include_runtime_logs=False,
                include_measurements=False,
                include_devices=False,
                include_device_states=False,
                include_command_history=False,
            )["commands"]
            self.assertEqual(released_commands["queued"], [])
            self.assertEqual(len(released_commands["effective"]), 1)
            self.assertEqual(
                released_commands["effective"][0]["normalized"]["run_status"],
                [{"dev_type": "ACBreak", "dev_name": dev_name, "status": "1"}],
            )


if __name__ == "__main__":
    unittest.main()
