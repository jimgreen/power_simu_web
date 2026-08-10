from __future__ import annotations

import copy
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from simu.renewable_control import TraineeRenewableControlManager
from tests.test_trainee_renewable_backend_control import (
    make_control_manager,
    ready_view,
    renewable_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]


class RenewableTrendHistoryRetentionTest(unittest.TestCase):
    @staticmethod
    def _plan(snapshot):
        clock = snapshot["clock"]
        return {
            "time": clock["time"],
            "clockKey": f'{clock["run_id"]}|{clock["absolute_minute"]}|{clock["time"]}',
            "metrics": {
                "totalPvCurrentKw": float(clock["absolute_minute"]),
                "totalPvTargetKw": float(clock["absolute_minute"]) + 1.0,
            },
            "weather": {},
            "commands": [],
            "commandRows": [],
            "dataQuality": {"dispatchAllowed": True},
        }

    @staticmethod
    def _service(runtime_dir):
        service = SimpleNamespace(
            model_id="shared",
            runtime_dir=Path(runtime_dir),
            lock=threading.RLock(),
        )
        return service

    def test_current_simulation_run_keeps_one_point_per_simulation_instant(self):
        manager = object.__new__(TraineeRenewableControlManager)
        state = SimpleNamespace(
            trend=[
                {
                    "sampleKey": f"1|{minute}|{minute}",
                    "runId": 1,
                    "stepCount": minute,
                    "minute": float(minute),
                    "time": str(minute),
                }
                for minute in range(3)
            ],
            trend_normalized=True,
        )
        snapshot = {
            "clock": {
                "run_id": 1,
                "step_count": 3,
                "absolute_minute": 3,
                "time": "00:03:00",
            }
        }

        manager._update_trend(state, self._plan(snapshot), snapshot)
        manager._update_trend(state, self._plan(snapshot), snapshot)

        self.assertEqual(len(state.trend), 4)
        self.assertEqual(state.trend[0]["minute"], 0.0)
        self.assertEqual(state.trend[-1]["minute"], 3.0)

    def test_recomputed_simulation_instant_replaces_persisted_tail_without_duplicate_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(temporary)
            active_snapshot = renewable_snapshot()

            def snapshot_provider(_model_id):
                return ready_view(active_snapshot)

            manager = make_control_manager(service, snapshot_provider=snapshot_provider)
            try:
                active_snapshot["clock"].update(
                    {
                        "run_id": 1,
                        "step_count": 1,
                        "minute": 1,
                        "absolute_minute": 1,
                        "time": "00:01:00",
                    }
                )
                first_plan = self._plan(active_snapshot)
                second_plan = copy.deepcopy(first_plan)
                second_plan["metrics"]["totalPvTargetKw"] = 99.0
                with patch(
                    "simu.renewable_control.calculate_renewable_control_plan",
                    side_effect=[first_plan, second_plan],
                ):
                    manager.run_once(
                        "shared",
                        trigger="manual",
                        allow_dispatch=False,
                        record_log=False,
                    )
                    manager.run_once(
                        "shared",
                        trigger="manual",
                        allow_dispatch=False,
                        record_log=False,
                    )
            finally:
                manager.close()

            persisted = (Path(temporary) / "renewable_control_trend.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(persisted), 1)

            reloaded = make_control_manager(service, snapshot_provider=snapshot_provider)
            try:
                restored = reloaded.state("shared")["trend"]
            finally:
                reloaded.close()

        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0]["totalPvTargetKw"], 99.0)

    def test_trend_survives_web_manager_restart_and_resets_only_for_new_simulation_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(temporary)
            active_snapshot = renewable_snapshot()

            def snapshot_provider(_model_id):
                return ready_view(active_snapshot)

            manager = make_control_manager(service, snapshot_provider=snapshot_provider)
            try:
                for run_id, step_count, minute, time_text in (
                    (1, 0, 0, "00:00:00"),
                    (1, 600, 600, "10:00:00"),
                ):
                    active_snapshot["clock"].update(
                        {
                            "run_id": run_id,
                            "step_count": step_count,
                            "minute": minute,
                            "absolute_minute": minute,
                            "time": time_text,
                        }
                    )
                    with patch(
                        "simu.renewable_control.calculate_renewable_control_plan",
                        return_value=self._plan(active_snapshot),
                    ):
                        manager.run_once(
                            "shared",
                            trigger="manual",
                            allow_dispatch=False,
                            record_log=False,
                        )
            finally:
                manager.close()

            reloaded = make_control_manager(service, snapshot_provider=snapshot_provider)
            try:
                restored = reloaded.state("shared")
                self.assertEqual([point["minute"] for point in restored["trend"]], [0.0, 600.0])
                stale_cursor = reloaded.state(
                    "shared",
                    compact=True,
                    after_trend_sample_key=restored["trend"][-1]["sampleKey"],
                    after_controller_instance_id="retired-web-controller",
                )
                self.assertTrue(stale_cursor["trendReset"])
                self.assertEqual(
                    [point["minute"] for point in stale_cursor["trend"]],
                    [0.0, 600.0],
                )

                active_snapshot["clock"].update(
                    {
                        "run_id": 1,
                        "step_count": 900,
                        "minute": 900,
                        "absolute_minute": 900,
                        "time": "15:00:00",
                    }
                )
                with patch(
                    "simu.renewable_control.calculate_renewable_control_plan",
                    return_value=self._plan(active_snapshot),
                ):
                    reloaded.run_once(
                        "shared",
                        trigger="manual",
                        allow_dispatch=False,
                        record_log=False,
                    )

                active_snapshot["clock"].update(
                    {
                        "run_id": 2,
                        "step_count": 0,
                        "minute": 0,
                        "absolute_minute": 0,
                        "time": "00:00:00",
                    }
                )
                with patch(
                    "simu.renewable_control.calculate_renewable_control_plan",
                    return_value=self._plan(active_snapshot),
                ):
                    reloaded.run_once(
                        "shared",
                        trigger="manual",
                        allow_dispatch=False,
                        record_log=False,
                    )
            finally:
                reloaded.close()

            final_manager = make_control_manager(service, snapshot_provider=snapshot_provider)
            try:
                final_state = final_manager.state("shared")
            finally:
                final_manager.close()

        self.assertEqual(len(final_state["trend"]), 1)
        self.assertEqual(final_state["trend"][0]["runId"], 2)
        self.assertEqual(final_state["trend"][0]["minute"], 0.0)

    def test_frontend_history_compaction_keeps_every_point(self):
        for console in ("simulator", "trainee"):
            script = (ROOT / "simu" / "web" / console / "app.js").read_text(encoding="utf-8")
            block = script.split("function compactTraceHistory", 1)[1].split("\n}", 1)[0]
            self.assertIn("return Array.isArray(history) ? history : [];", block)
            self.assertNotIn("archived", block)
            self.assertNotIn("bucketMinutes", block)


if __name__ == "__main__":
    unittest.main()
