from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from simu.renewable_control import (
    RenewableControlSettings,
    TraineeRenewableControlManager,
    _simulation_control_interval_seconds,
    _storage_control_horizon_minutes,
)
from simu.trainee_exchange import TraineeControlSnapshot


class _Service:
    def __init__(self, runtime_dir, *, collection_interval_seconds: float = 1.0):
        self.model_id = "shared"
        self.runtime_dir = runtime_dir
        self.lock = threading.RLock()
        self.collection_interval_seconds = collection_interval_seconds

    def web_runtime_settings(self, _role):
        return {
            "effectiveSettings": {
                "backend_refresh_seconds": self.collection_interval_seconds,
            }
        }


class _Registry:
    def __init__(self, service):
        self.service = service

    def service_for(self, _model_id=None):
        return self.service

    def iter_services(self):
        return [self.service]


def _ready_status(_model_id):
    return {
        "receiveActive": True,
        "ready": True,
        "canRun": True,
        "canCalculate": True,
        "canDispatch": True,
        "revision": 1,
        "connectionSignature": ["learner", 1],
        "prerequisiteStatus": "",
    }


def _clock_snapshot(
    *,
    state: str = "running",
    run_id: int = 1,
    step_count: int = 0,
    absolute_second: float = 0.0,
):
    return {
        "clock": {
            "state": state,
            "run_id": run_id,
            "step_count": step_count,
            "absolute_second": absolute_second,
            "absolute_minute": absolute_second / 60.0,
            "time": "00:00:00",
        }
    }


def _status_for_snapshot(snapshot):
    def provider(_model_id):
        paused = snapshot["clock"]["state"] == "paused"
        return {
            **_ready_status(_model_id),
            "canCalculate": not paused,
            "canDispatch": not paused,
            "simulationPaused": paused,
            "controlFrozen": paused,
        }

    return provider


def _manager(
    tmp_path,
    *,
    collection_interval_seconds: float = 1.0,
    snapshot=None,
    receive_status_provider=None,
):
    service = _Service(
        tmp_path,
        collection_interval_seconds=collection_interval_seconds,
    )
    active_snapshot = snapshot if snapshot is not None else _clock_snapshot()
    manager = TraineeRenewableControlManager(
        _Registry(service),
        snapshot_provider=lambda _model_id: TraineeControlSnapshot(
            snapshot=active_snapshot,
            source="trainee-live",
            age_seconds=0.0,
            error=None,
            receive_active=True,
            ready=True,
            revision=1,
            connection_signature=("learner", 1),
        ),
        receive_status_provider=receive_status_provider or _ready_status,
        command_sink=lambda _model_id, _payload: {},
        start_worker=False,
    )
    return service, manager


def test_control_period_is_validated_as_simulation_clock_seconds():
    assert _simulation_control_interval_seconds(1.0) == pytest.approx(1.0)
    assert _simulation_control_interval_seconds(1.2) == pytest.approx(1.2)

    with pytest.raises(ValueError, match="仿真秒"):
        _simulation_control_interval_seconds(0.5)
    with pytest.raises(ValueError, match="有效的仿真秒数"):
        _simulation_control_interval_seconds("invalid")


def test_control_settings_update_is_independent_of_wall_clock_collection_period(tmp_path):
    _service, manager = _manager(tmp_path, collection_interval_seconds=10.0)
    try:
        state = manager.apply_action(
            "shared",
            {
                "action": "update_settings",
                "settings": {"simulationIntervalSeconds": 1.2},
            },
        )
        assert state["settings"]["simulationIntervalSeconds"] == pytest.approx(1.2)
        assert state["settings"]["intervalSeconds"] == pytest.approx(1.2)
        assert "1.2 仿真秒" in state["status"]
        assert "采集周期" not in state["status"]
    finally:
        manager.close()


def test_backend_refresh_update_is_independent_of_simulation_control_period(tmp_path):
    _service, manager = _manager(tmp_path, collection_interval_seconds=1.0)
    try:
        manager.validate_runtime_settings_update_for_service(
            manager.services.service_for("shared"),
            {"settings": {"backend_refresh_seconds": 0.75}},
        )
        with pytest.raises(ValueError, match="后台数据刷新周期"):
            manager.validate_runtime_settings_update_for_service(
                manager.services.service_for("shared"),
                {"settings": {"backend_refresh_seconds": 0}},
            )
    finally:
        manager.close()


def test_storage_control_horizon_uses_simulation_seconds_not_wall_clock_period():
    snapshot = _clock_snapshot()
    snapshot["system_parameters"] = {
        "effective_step_minutes": 5.0,
        "compute_interval_seconds": 1.0,
    }
    settings = RenewableControlSettings(interval_seconds=600.0)

    assert _storage_control_horizon_minutes(snapshot, settings) == pytest.approx(10.0)

    snapshot["system_parameters"]["compute_interval_seconds"] = 30.0
    assert _storage_control_horizon_minutes(snapshot, settings) == pytest.approx(10.0)


def test_worker_collects_at_backend_refresh_period_before_control_is_due(tmp_path):
    snapshot = _clock_snapshot()
    _service, manager = _manager(
        tmp_path,
        collection_interval_seconds=1.0,
        snapshot=snapshot,
    )
    state = manager._state_for("shared")
    calls = []

    def submit(
        target_state,
        *,
        timestamp_attr,
        timestamp,
        callback,
        args,
        kwargs,
        service=None,
    ):
        calls.append((timestamp_attr, callback.__name__, timestamp))
        setattr(target_state, timestamp_attr, timestamp)
        return True

    manager._submit_background_cycle = submit
    with state.lock:
        state.enabled = True
        state.settings = RenewableControlSettings(interval_seconds=4.0)
        state.last_preview_started = 100.0
    try:
        wait_seconds = manager._run_worker_iteration(now=100.25)
        assert wait_seconds == pytest.approx(0.75)
        assert calls == []

        manager._run_worker_iteration(now=101.0)
        assert calls[-1][0] == "last_preview_started"
        assert calls[-1][1] == "_collect_once_for_service"

        with state.lock:
            state.last_preview_started = 103.0
        snapshot["clock"].update({"step_count": 4, "absolute_second": 4.0})
        manager._run_worker_iteration(now=104.0)
        assert calls[-1][0] == "last_auto_started"
        assert calls[-1][1] == "_run_once_for_service"
        assert state.last_preview_started == pytest.approx(104.0)
    finally:
        manager.close()


def test_pause_wall_time_does_not_consume_simulation_control_period(tmp_path):
    snapshot = _clock_snapshot()
    _service, manager = _manager(
        tmp_path,
        snapshot=snapshot,
        receive_status_provider=_status_for_snapshot(snapshot),
    )
    state = manager._state_for("shared")
    automatic_cycles = []

    def submit(target_state, **kwargs):
        setattr(target_state, kwargs["timestamp_attr"], kwargs["timestamp"])
        if kwargs["timestamp_attr"] == "last_auto_started":
            automatic_cycles.append(snapshot["clock"]["absolute_second"])
        return True

    manager._submit_background_cycle = submit
    with state.lock:
        state.enabled = True
        state.settings = RenewableControlSettings(interval_seconds=10.0)
        state.last_preview_started = 0.0
    try:
        manager._run_worker_iteration(now=0.0)
        snapshot["clock"].update({"step_count": 4, "absolute_second": 4.0})
        manager._run_worker_iteration(now=4.0)

        snapshot["clock"]["state"] = "paused"
        manager._run_worker_iteration(now=10_000.0)

        snapshot["clock"]["state"] = "running"
        manager._run_worker_iteration(now=20_000.0)
        snapshot["clock"].update({"step_count": 9, "absolute_second": 9.0})
        manager._run_worker_iteration(now=30_000.0)
        assert automatic_cycles == []

        snapshot["clock"].update({"step_count": 10, "absolute_second": 10.0})
        manager._run_worker_iteration(now=40_000.0)
        assert automatic_cycles == [10.0]
    finally:
        manager.close()


def test_reset_during_pause_restarts_a_full_simulation_control_period(tmp_path):
    snapshot = _clock_snapshot()
    _service, manager = _manager(
        tmp_path,
        snapshot=snapshot,
        receive_status_provider=_status_for_snapshot(snapshot),
    )
    state = manager._state_for("shared")
    automatic_cycles = []

    def submit(target_state, **kwargs):
        setattr(target_state, kwargs["timestamp_attr"], kwargs["timestamp"])
        if kwargs["timestamp_attr"] == "last_auto_started":
            automatic_cycles.append(
                (snapshot["clock"]["run_id"], snapshot["clock"]["absolute_second"])
            )
        return True

    manager._submit_background_cycle = submit
    with state.lock:
        state.enabled = True
        state.settings = RenewableControlSettings(interval_seconds=10.0)
    try:
        manager._run_worker_iteration(now=0.0)
        snapshot["clock"].update({"step_count": 4, "absolute_second": 4.0})
        manager._run_worker_iteration(now=4.0)

        snapshot["clock"].update({
            "state": "paused",
            "run_id": 2,
            "step_count": 0,
            "absolute_second": 0.0,
            "absolute_minute": 0.0,
        })
        manager._run_worker_iteration(now=50_000.0)
        assert automatic_cycles == []

        snapshot["clock"]["state"] = "running"
        manager._run_worker_iteration(now=60_000.0)
        assert automatic_cycles == []

        snapshot["clock"].update({"step_count": 9, "absolute_second": 9.0})
        manager._run_worker_iteration(now=70_000.0)
        assert automatic_cycles == []

        snapshot["clock"].update({"step_count": 10, "absolute_second": 10.0})
        manager._run_worker_iteration(now=80_000.0)
        assert automatic_cycles == [(2, 10.0)]
    finally:
        manager.close()


def test_wall_clock_cannot_make_control_due_without_simulation_progress(tmp_path):
    snapshot = _clock_snapshot()
    _service, manager = _manager(tmp_path, snapshot=snapshot)
    state = manager._state_for("shared")
    automatic_cycles = []

    def submit(target_state, **kwargs):
        setattr(target_state, kwargs["timestamp_attr"], kwargs["timestamp"])
        if kwargs["timestamp_attr"] == "last_auto_started":
            automatic_cycles.append(snapshot["clock"]["absolute_second"])
        return True

    manager._submit_background_cycle = submit
    with state.lock:
        state.enabled = True
        state.settings = RenewableControlSettings(interval_seconds=10.0)
    try:
        manager._run_worker_iteration(now=0.0)
        manager._run_worker_iteration(now=100_000.0)
        assert automatic_cycles == []

        snapshot["clock"].update({"step_count": 10, "absolute_second": 10.0})
        manager._run_worker_iteration(now=100_001.0)
        assert automatic_cycles == [10.0]
    finally:
        manager.close()


def test_simulation_reset_restarts_control_period_without_immediate_strategy(tmp_path):
    snapshot = _clock_snapshot()
    _service, manager = _manager(tmp_path, snapshot=snapshot)
    state = manager._state_for("shared")
    automatic_cycles = []

    def submit(target_state, **kwargs):
        setattr(target_state, kwargs["timestamp_attr"], kwargs["timestamp"])
        if kwargs["timestamp_attr"] == "last_auto_started":
            automatic_cycles.append(
                (snapshot["clock"]["run_id"], snapshot["clock"]["absolute_second"])
            )
        return True

    manager._submit_background_cycle = submit
    with state.lock:
        state.enabled = True
        state.settings = RenewableControlSettings(interval_seconds=10.0)
    try:
        manager._run_worker_iteration(now=0.0)
        snapshot["clock"].update({"step_count": 10, "absolute_second": 10.0})
        manager._run_worker_iteration(now=1.0)
        assert automatic_cycles == [(1, 10.0)]

        snapshot["clock"].update({
            "run_id": 2,
            "step_count": 0,
            "absolute_second": 0.0,
            "absolute_minute": 0.0,
        })
        manager._run_worker_iteration(now=50_000.0)
        manager._run_worker_iteration(now=60_000.0)
        snapshot["clock"].update({"step_count": 9, "absolute_second": 9.0})
        manager._run_worker_iteration(now=70_000.0)
        assert automatic_cycles == [(1, 10.0)]

        snapshot["clock"].update({"step_count": 10, "absolute_second": 10.0})
        manager._run_worker_iteration(now=80_000.0)
        assert automatic_cycles == [(1, 10.0), (2, 10.0)]
    finally:
        manager.close()


def test_same_run_clock_rollback_restarts_control_period(tmp_path):
    snapshot = _clock_snapshot(step_count=20, absolute_second=20.0)
    _service, manager = _manager(tmp_path, snapshot=snapshot)
    state = manager._state_for("shared")
    automatic_cycles = []

    def submit(target_state, **kwargs):
        setattr(target_state, kwargs["timestamp_attr"], kwargs["timestamp"])
        if kwargs["timestamp_attr"] == "last_auto_started":
            automatic_cycles.append(snapshot["clock"]["absolute_second"])
        return True

    manager._submit_background_cycle = submit
    with state.lock:
        state.enabled = True
        state.settings = RenewableControlSettings(interval_seconds=10.0)
    try:
        manager._run_worker_iteration(now=0.0)
        snapshot["clock"].update({"step_count": 30, "absolute_second": 30.0})
        manager._run_worker_iteration(now=1.0)
        assert automatic_cycles == [30.0]

        snapshot["clock"].update({"step_count": 0, "absolute_second": 0.0})
        manager._run_worker_iteration(now=2.0)
        assert automatic_cycles == [30.0]

        snapshot["clock"].update({"step_count": 9, "absolute_second": 9.0})
        manager._run_worker_iteration(now=100_000.0)
        assert automatic_cycles == [30.0]

        snapshot["clock"].update({"step_count": 10, "absolute_second": 10.0})
        manager._run_worker_iteration(now=100_001.0)
        assert automatic_cycles == [30.0, 10.0]
    finally:
        manager.close()


def test_start_at_zero_arms_control_but_waits_one_simulation_period(tmp_path):
    snapshot = _clock_snapshot(run_id=2, step_count=0, absolute_second=0.0)
    _service, manager = _manager(tmp_path, snapshot=snapshot)
    state = manager._state_for("shared")
    automatic_cycles = []

    def submit(target_state, **kwargs):
        setattr(target_state, kwargs["timestamp_attr"], kwargs["timestamp"])
        if kwargs["timestamp_attr"] == "last_auto_started":
            automatic_cycles.append(snapshot["clock"]["absolute_second"])
        return True

    manager._submit_background_cycle = submit
    try:
        with patch.object(manager, "_run_once_for_service") as run_once:
            started = manager.apply_action("shared", {"action": "start"})
            run_once.assert_not_called()
        assert started["enabled"]
        assert started["desiredEnabled"]

        manager._run_worker_iteration(now=0.0)
        snapshot["clock"].update({"step_count": 1, "absolute_second": 1.0})
        manager._run_worker_iteration(now=1.0)
        assert automatic_cycles == []

        snapshot["clock"].update({"step_count": 2, "absolute_second": 2.0})
        manager._run_worker_iteration(now=2.0)
        assert automatic_cycles == [2.0]
    finally:
        manager.close()


def test_reset_frame_cancels_a_queued_cycle_from_the_previous_generation(tmp_path):
    snapshot = _clock_snapshot()
    receive_state = {"revision": 1}

    def receive_status(model_id):
        return {
            **_ready_status(model_id),
            "revision": receive_state["revision"],
        }

    _service, manager = _manager(
        tmp_path,
        snapshot=snapshot,
        receive_status_provider=receive_status,
    )
    state = manager._state_for("shared")
    queued_cycle = {}

    def submit(target_state, **kwargs):
        setattr(target_state, kwargs["timestamp_attr"], kwargs["timestamp"])
        if kwargs["timestamp_attr"] == "last_auto_started":
            queued_cycle.update(kwargs)
        return True

    manager._submit_background_cycle = submit
    with state.lock:
        state.enabled = True
        state.settings = RenewableControlSettings(interval_seconds=10.0)
    try:
        manager._run_worker_iteration(now=0.0)
        snapshot["clock"].update({"step_count": 10, "absolute_second": 10.0})
        manager._run_worker_iteration(now=1.0)
        assert queued_cycle["kwargs"]["trigger"] == "auto"

        receive_state["revision"] = 2
        snapshot["clock"].update({
            "run_id": 2,
            "step_count": 0,
            "absolute_second": 0.0,
            "absolute_minute": 0.0,
        })
        with patch("simu.renewable_control.calculate_renewable_control_plan") as calculate:
            queued_cycle["callback"](
                *queued_cycle["args"],
                **queued_cycle["kwargs"],
            )
            calculate.assert_not_called()
    finally:
        manager.close()


def test_manual_run_once_does_not_change_automatic_simulation_period(tmp_path):
    snapshot = _clock_snapshot()
    _service, manager = _manager(tmp_path, snapshot=snapshot)
    state = manager._state_for("shared")
    automatic_cycles = []

    def submit(target_state, **kwargs):
        setattr(target_state, kwargs["timestamp_attr"], kwargs["timestamp"])
        if kwargs["timestamp_attr"] == "last_auto_started":
            automatic_cycles.append(snapshot["clock"]["absolute_second"])
        return True

    manager._submit_background_cycle = submit
    with state.lock:
        state.enabled = True
        state.desired_enabled = True
        state.settings = RenewableControlSettings(interval_seconds=10.0)
    try:
        manager._run_worker_iteration(now=0.0)
        snapshot["clock"].update({"step_count": 4, "absolute_second": 4.0})
        manager._run_worker_iteration(now=4.0)
        with state.lock:
            automatic_clock_before = (
                state.control_clock_run_id,
                state.control_clock_anchor_second,
                state.control_clock_last_second,
                state.control_clock_last_step_count,
            )

        manual_plan = {
            "time": "00:00:04",
            "clockKey": "1|4",
            "metrics": {},
            "commands": [],
            "commandRows": [],
            "dataQuality": {"dispatchAllowed": False},
            "weather": {},
        }
        with patch(
            "simu.renewable_control.calculate_renewable_control_plan",
            return_value=manual_plan,
        ) as calculate:
            manual_result = manager.apply_action(
                "shared",
                {"action": "run_once"},
            )
            calculate.assert_called_once()

        assert manual_result["enabled"] is True
        assert manual_result["desiredEnabled"] is True

        with state.lock:
            assert (
                state.control_clock_run_id,
                state.control_clock_anchor_second,
                state.control_clock_last_second,
                state.control_clock_last_step_count,
            ) == automatic_clock_before

        snapshot["clock"].update({"step_count": 9, "absolute_second": 9.0})
        manager._run_worker_iteration(now=9.0)
        assert automatic_cycles == []

        snapshot["clock"].update({"step_count": 10, "absolute_second": 10.0})
        manager._run_worker_iteration(now=10.0)
        assert automatic_cycles == [10.0]
    finally:
        manager.close()


def test_runtime_setting_change_reschedules_collection_immediately(tmp_path):
    service, manager = _manager(tmp_path, collection_interval_seconds=1.0)
    state = manager._state_for("shared")
    with state.lock:
        state.last_preview_started = 100.0
    try:
        assert manager.runtime_settings_changed_for_service(service)
        assert state.last_preview_started == 0.0
    finally:
        manager.close()


def test_preview_collection_refreshes_current_values_but_holds_control_targets(tmp_path):
    snapshots = [
        {
            "clock": {
                "run_id": 1,
                "step_count": index,
                "absolute_minute": float(index),
                "time": f"00:{index:02d}:00",
            },
            "sample": index,
        }
        for index in range(5)
    ]
    snapshot_index = 0

    service = _Service(tmp_path, collection_interval_seconds=1.0)

    def snapshot_provider(_model_id):
        return TraineeControlSnapshot(
            snapshot=snapshots[snapshot_index],
            source="trainee-live",
            age_seconds=0.0,
            error=None,
            receive_active=True,
            ready=True,
            revision=1,
            connection_signature=("learner", 1),
        )

    manager = TraineeRenewableControlManager(
        _Registry(service),
        snapshot_provider=snapshot_provider,
        receive_status_provider=_ready_status,
        command_sink=lambda _model_id, _payload: {},
        start_worker=False,
    )

    def calculate(snapshot, _settings, **_kwargs):
        sample = snapshot["sample"]
        return {
            "time": snapshot["clock"]["time"],
            "clockKey": f"clock-{sample}",
            "metrics": {
                "acGridFollowingStorageCurrentKw": 10.0 + sample,
                "acGridFollowingStorageTargetKw": 20.0 + sample,
                "totalGridFollowingStorageCurrentKw": 10.0 + sample,
                "totalGridFollowingStorageTargetKw": 20.0 + sample,
            },
            "commands": [
                {
                    "dev_type": "ESS",
                    "dev_name": "ess01",
                    "set_type": "p_set",
                    "set_value": 20.0 + sample,
                }
            ],
            "commandRows": [
                {
                    "dev_type": "ESS",
                    "dev_name": "ess01",
                    "set_type": "p_set",
                    "currentKw": 10.0 + sample,
                    "targetKw": 20.0 + sample,
                    "commandKw": 20.0 + sample,
                    "strategyCommand": True,
                }
            ],
            "dataQuality": {"dispatchAllowed": True},
        }

    try:
        with patch("simu.renewable_control.calculate_renewable_control_plan", side_effect=calculate):
            first_decision = manager.run_once(
                "shared",
                trigger="manual",
                allow_dispatch=False,
                record_log=False,
            )
            assert first_decision["lastPlan"]["metrics"]["acGridFollowingStorageTargetKw"] == 20.0

            snapshot_index = 1
            first_preview = manager.collect_once("shared")
            snapshot_index = 2
            second_preview = manager.collect_once("shared")

            assert first_preview["lastPlan"]["metrics"]["acGridFollowingStorageCurrentKw"] == 11.0
            assert second_preview["lastPlan"]["metrics"]["acGridFollowingStorageCurrentKw"] == 12.0
            assert first_preview["lastPlan"]["metrics"]["acGridFollowingStorageTargetKw"] == 20.0
            assert second_preview["lastPlan"]["metrics"]["acGridFollowingStorageTargetKw"] == 20.0
            assert second_preview["lastPlan"]["commandRows"][0]["currentKw"] == 12.0
            assert second_preview["lastPlan"]["commandRows"][0]["targetKw"] == 20.0
            assert second_preview["lastPlan"]["commandRows"][0]["commandKw"] == 20.0
            assert second_preview["lastPlan"]["commands"][0]["set_value"] == 20.0
            assert [point["acGridFollowingStorageCurrentKw"] for point in second_preview["trend"]] == [
                10.0,
                11.0,
                12.0,
            ]
            assert [point["acGridFollowingStorageTargetKw"] for point in second_preview["trend"]] == [
                20.0,
                20.0,
                20.0,
            ]

            snapshot_index = 3
            manual_preview = manager.run_once(
                "shared",
                trigger="preview",
                allow_dispatch=False,
                record_log=False,
            )
            assert manual_preview["lastPlan"]["metrics"]["acGridFollowingStorageCurrentKw"] == 13.0
            assert manual_preview["lastPlan"]["metrics"]["acGridFollowingStorageTargetKw"] == 20.0
            assert manual_preview["lastPlan"]["commandRows"][0]["currentKw"] == 13.0
            assert manual_preview["lastPlan"]["commandRows"][0]["targetKw"] == 20.0
            assert manual_preview["lastPlan"]["commands"][0]["set_value"] == 20.0
            assert manual_preview["trend"][-1]["acGridFollowingStorageTargetKw"] == 20.0

            snapshot_index = 4
            next_decision = manager.run_once(
                "shared",
                trigger="manual",
                allow_dispatch=False,
                record_log=False,
            )
            assert next_decision["lastPlan"]["metrics"]["acGridFollowingStorageTargetKw"] == 24.0
            assert next_decision["lastPlan"]["commandRows"][0]["targetKw"] == 24.0
            assert next_decision["lastPlan"]["commands"][0]["set_value"] == 24.0
            assert next_decision["trend"][-1]["acGridFollowingStorageTargetKw"] == 24.0
    finally:
        manager.close()
