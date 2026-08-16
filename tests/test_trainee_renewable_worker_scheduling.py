from __future__ import annotations

import threading

import pytest

from simu.renewable_control import (
    RenewableControlSettings,
    TraineeRenewableControlManager,
)
from simu.trainee_exchange import TraineeControlSnapshot


class _Service:
    def __init__(self, runtime_dir, *, collection_interval_seconds=1.0):
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


class _CountingEvent:
    def __init__(self):
        self.set_count = 0

    def set(self):
        self.set_count += 1

    def clear(self):
        return None

    def wait(self, _timeout=None):
        return False


class _InlineExecutor:
    def submit(self, callback, *args, **kwargs):
        callback(*args, **kwargs)
        return None

    def shutdown(self, *args, **kwargs):
        return None


def _receive_status(*, active: bool):
    return {
        "receiveActive": active,
        "ready": active,
        "canRun": active,
        "canCalculate": active,
        "canDispatch": active,
        "revision": 1,
        "connectionSignature": ["learner", 1],
        "prerequisiteStatus": "" if active else "请先启动接收。",
    }


def _manager(
    tmp_path,
    *,
    receive_active: bool,
    collection_interval_seconds: float = 1.0,
) -> TraineeRenewableControlManager:
    service = _Service(
        tmp_path,
        collection_interval_seconds=collection_interval_seconds,
    )
    registry = _Registry(service)
    return TraineeRenewableControlManager(
        registry,
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
        receive_status_provider=lambda _model_id: _receive_status(
            active=receive_active
        ),
        command_sink=lambda _model_id, _payload: {},
        start_worker=False,
    )


def test_idle_worker_iteration_uses_one_second_fallback(tmp_path):
    manager = _manager(tmp_path, receive_active=False)
    try:
        wait_seconds = manager._run_worker_iteration(now=100.0)
    finally:
        manager.close()

    assert wait_seconds == pytest.approx(1.0)


def test_worker_iteration_waits_only_until_next_collection_deadline(tmp_path):
    manager = _manager(
        tmp_path,
        receive_active=True,
        collection_interval_seconds=0.35,
    )
    state = manager._state_for("shared")
    with state.lock:
        state.enabled = False
        state.settings = RenewableControlSettings(interval_seconds=1.05)
        state.last_preview_started = 100.0
    try:
        wait_seconds = manager._run_worker_iteration(now=100.0)
    finally:
        manager.close()

    assert wait_seconds == pytest.approx(0.35)


def test_receive_and_control_actions_wake_worker(tmp_path):
    manager = _manager(tmp_path, receive_active=True)
    service = manager.services.service_for("shared")
    state = manager._state_for("shared")
    with state.lock:
        state.desired_enabled = True
    wake_event = _CountingEvent()
    manager._wake_event = wake_event
    manager._run_once_for_service = lambda *_args, **_kwargs: {"enabled": True}
    try:
        manager.receive_state_changed_for_service(service)
        assert wake_event.set_count == 1

        wake_event.set_count = 0
        manager.apply_action(
            "shared",
            {
                "action": "update_settings",
                "settings": {"intervalSeconds": 2.0},
            },
        )
        assert wake_event.set_count == 1

        wake_event.set_count = 0
        manager.apply_action("shared", {"action": "start"})
        assert wake_event.set_count == 1

        wake_event.set_count = 0
        manager.apply_action("shared", {"action": "stop"})
        assert wake_event.set_count == 1
    finally:
        manager.close()


def test_background_cycle_completion_wakes_worker(tmp_path):
    manager = _manager(tmp_path, receive_active=True)
    state = manager._state_for("shared")
    wake_event = _CountingEvent()
    manager._wake_event = wake_event
    manager._executor = _InlineExecutor()
    try:
        assert manager._submit_background_cycle(
            state,
            timestamp_attr="last_preview_started",
            timestamp=100.0,
            callback=lambda: {},
            args=(),
            kwargs={},
        )
        assert wake_event.set_count == 1
        assert not state.background_cycle_pending
    finally:
        manager.close()


def test_close_wakes_worker_wait(tmp_path):
    manager = _manager(tmp_path, receive_active=False)
    wake_event = _CountingEvent()
    manager._wake_event = wake_event

    manager.close()

    assert wake_event.set_count == 1
