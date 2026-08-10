from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from simu.renewable_control import (
    RenewableControlSettings,
    TraineeRenewableControlManager,
    _control_interval_multiple,
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


def _manager(tmp_path, *, collection_interval_seconds: float = 1.0):
    service = _Service(
        tmp_path,
        collection_interval_seconds=collection_interval_seconds,
    )
    manager = TraineeRenewableControlManager(
        _Registry(service),
        snapshot_provider=lambda _model_id: TraineeControlSnapshot(
            snapshot={},
            source="trainee-live",
            age_seconds=0.0,
            error=None,
            receive_active=True,
            ready=True,
            revision=1,
            connection_signature=("learner", 1),
        ),
        receive_status_provider=_ready_status,
        command_sink=lambda _model_id, _payload: {},
        start_worker=False,
    )
    return service, manager


def test_control_period_must_be_larger_integer_multiple_of_collection_period():
    assert _control_interval_multiple(2.0, 1.0) == 2
    assert _control_interval_multiple(1.2, 0.3) == 4

    with pytest.raises(ValueError, match="必须大于采集周期"):
        _control_interval_multiple(1.0, 1.0)
    with pytest.raises(ValueError, match="整数倍"):
        _control_interval_multiple(2.0, 0.3)


def test_control_settings_update_rejects_invalid_period_relationship(tmp_path):
    _service, manager = _manager(tmp_path, collection_interval_seconds=1.0)
    try:
        with pytest.raises(ValueError, match="必须大于采集周期"):
            manager.apply_action(
                "shared",
                {
                    "action": "update_settings",
                    "settings": {"intervalSeconds": 1.0},
                },
            )

        state = manager.apply_action(
            "shared",
            {
                "action": "update_settings",
                "settings": {"intervalSeconds": 3.0},
            },
        )
        assert state["settings"]["intervalSeconds"] == pytest.approx(3.0)
        assert "3 倍" in state["status"]
    finally:
        manager.close()


def test_backend_refresh_update_is_validated_against_control_period(tmp_path):
    _service, manager = _manager(tmp_path, collection_interval_seconds=1.0)
    try:
        with pytest.raises(ValueError, match="整数倍"):
            manager.validate_runtime_settings_update_for_service(
                manager.services.service_for("shared"),
                {"settings": {"backend_refresh_seconds": 0.75}},
            )

        manager.validate_runtime_settings_update_for_service(
            manager.services.service_for("shared"),
            {"settings": {"backend_refresh_seconds": 0.5}},
        )
    finally:
        manager.close()


def test_worker_collects_at_backend_refresh_period_before_control_is_due(tmp_path):
    _service, manager = _manager(tmp_path, collection_interval_seconds=1.0)
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
        state.last_auto_started = 100.0
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
        manager._run_worker_iteration(now=104.0)
        assert calls[-1][0] == "last_auto_started"
        assert calls[-1][1] == "_run_once_for_service"
        assert state.last_preview_started == pytest.approx(104.0)
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
