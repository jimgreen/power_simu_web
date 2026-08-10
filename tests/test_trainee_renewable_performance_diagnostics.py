from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import simu.renewable_control as renewable_control_module
from simu.renewable_control import (
    CYCLE_PERFORMANCE_HISTORY_LIMIT,
    TraineeRenewableControlManager,
    _CyclePerformanceWindow,
    _optimization_performance_diagnostics,
)
from simu.renewable_optimization import optimize_topology_islands
from simu.resource_topology import ResourceTopology
from simu.trainee_exchange import TraineeControlSnapshot
from tests.test_renewable_optimization_dispatch import diesel, renewable


ROOT = Path(__file__).resolve().parents[1]


def test_cycle_performance_window_is_bounded_and_reports_linear_percentiles():
    window = _CyclePerformanceWindow(limit=4)

    for value in (10.0, 20.0, 30.0, 40.0, 50.0):
        window.record(
            {
                "trigger": "auto",
                "success": True,
                "phasesMs": {
                    "cycleTotalMs": value,
                    "optimizationSolveMs": value / 2.0,
                },
                "solver": {"iterations": int(value)},
            }
        )

    payload = window.payload()

    assert CYCLE_PERFORMANCE_HISTORY_LIMIT == 120
    assert payload["historyLimit"] == 4
    assert payload["sampleCount"] == 4
    assert payload["latest"]["phasesMs"]["cycleTotalMs"] == 50.0
    assert payload["phaseStats"]["cycleTotalMs"] == {
        "sampleCount": 4,
        "latestMs": 50.0,
        "p50Ms": 35.0,
        "p95Ms": 48.5,
        "maxMs": 50.0,
    }
    assert payload["phaseStats"]["optimizationSolveMs"]["p50Ms"] == 17.5


def test_control_manager_reuses_an_isolated_exchange_snapshot_without_copying():
    snapshot = {"clock": {"time": "00:00:01"}, "measurements": {}}
    isolated = TraineeControlSnapshot(
        snapshot=snapshot,
        source="trainee-live",
        age_seconds=0.0,
        error=None,
        receive_active=True,
        ready=True,
        revision=1,
        connection_signature=("learner", 1),
        snapshot_isolated=True,
    )
    shared = TraineeControlSnapshot(
        snapshot=snapshot,
        source="test-shared",
        age_seconds=0.0,
        error=None,
        receive_active=True,
        ready=True,
        revision=1,
        connection_signature=("test", 1),
    )

    assert TraineeRenewableControlManager._snapshot_for_calculation(isolated) is snapshot
    shared_copy = TraineeRenewableControlManager._snapshot_for_calculation(shared)
    assert shared_copy == snapshot
    assert shared_copy is not snapshot
    assert shared_copy["clock"] is not snapshot["clock"]


def test_optimizer_reports_iterations_and_actual_problem_size():
    topology = ResourceTopology(
        resources={},
        dc_transfer_groups={},
        converter_component_ids={},
    )

    result = optimize_topology_islands(
        topology,
        renewable_rows=[
            renewable(
                "wind-a",
                side="AC",
                component="AC:1",
                current=10.0,
                capacity=20.0,
            )
        ],
        diesel_rows=[
            diesel(
                "diesel-a",
                component="AC:1",
                current=20.0,
                minimum=5.0,
                maximum=40.0,
            )
        ],
        storage_rows=[],
        converter_rows=[],
        step_coefficient=1.0,
    )

    island = result.islands[0]
    assert island.variable_count == 2
    assert island.equality_constraint_count == 1
    assert island.inequality_constraint_count == 0
    assert island.bound_count == 2
    assert island.constraint_count == 1
    assert island.iterations >= 0
    assert result.variable_count == 2
    assert result.constraint_count == 1
    assert result.bound_count == 2
    assert result.iterations == island.iterations
    assert result.build_seconds >= 0.0
    assert result.solver_seconds >= 0.0
    assert result.storage_balance_seconds >= 0.0
    assert result.postprocess_seconds >= 0.0


def test_optimizer_diagnostics_report_unassigned_devices_without_a_solved_island():
    topology = ResourceTopology(
        resources={},
        dc_transfer_groups={},
        converter_component_ids={},
    )

    row = renewable(
        "wind-without-component",
        side="AC",
        component="",
        current=10.0,
        capacity=20.0,
    )
    result = optimize_topology_islands(
        topology,
        renewable_rows=[row],
        diesel_rows=[],
        storage_rows=[],
        converter_rows=[],
        step_coefficient=1.0,
    )
    diagnostics = _optimization_performance_diagnostics(result)

    assert result.all_success is False
    assert result.unassigned_devices == (("ACGenerator", "wind-without-component"),)
    assert result.islands == ()
    assert result.variable_count == 0
    assert result.constraint_count == 0
    assert result.build_seconds >= 0.0
    assert diagnostics["success"] is False
    assert diagnostics["status"] == "unassigned_devices"
    assert diagnostics["unassignedDeviceCount"] == 1
    assert diagnostics["islandCount"] == 0


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_control_cycle_separates_snapshot_compute_and_command_dispatch_time(tmp_path):
    clock = _FakeClock()
    service = SimpleNamespace(
        model_id="shared",
        service_instance_id="service-a",
        runtime_dir=tmp_path,
        lock=threading.RLock(),
    )
    snapshot = {
        "clock": {
            "run_id": 1,
            "step_count": 1,
            "absolute_minute": 1,
            "time": "00:01:00",
        }
    }

    def snapshot_provider(_model_id):
        clock.advance(0.005)
        return TraineeControlSnapshot(
            snapshot=snapshot,
            source="trainee-live",
            age_seconds=0.0,
            error=None,
            receive_active=True,
            ready=True,
            revision=1,
            connection_signature=("learner", 1),
        )

    def receive_status(_model_id):
        return {
            "receiveActive": True,
            "ready": True,
            "canRun": True,
            "canCalculate": True,
            "canDispatch": True,
            "revision": 1,
            "connectionSignature": ["learner", 1],
            "requestDurationSeconds": 0.003,
            "refreshProcessingDurationSeconds": 0.004,
            "refreshPublishDurationSeconds": 0.002,
            "refreshTotalDurationSeconds": 0.009,
        }

    def calculate_plan(*_args, **_kwargs):
        clock.advance(0.007)
        return {
            "clockKey": "1|1|00:01:00",
            "time": "00:01:00",
            "weather": {},
            "metrics": {},
            "commands": [
                {
                    "dev_type": "ACGenerator",
                    "dev_name": "wind-a",
                    "set_type": "p_set",
                    "set_value": 11.0,
                }
            ],
            "commandRows": [],
            "warnings": [],
            "dataQuality": {"source": "trainee-live", "status": "ok", "dispatchAllowed": True},
            "performanceDiagnostics": {
                "phasesMs": {
                    "inputProcessingMs": 1.0,
                    "topologyAnalysisMs": 1.0,
                    "strategyPreparationMs": 1.0,
                    "optimizationBuildMs": 1.0,
                    "optimizationSolveMs": 2.0,
                    "storageBalanceMs": 0.5,
                    "strategyPostprocessMs": 0.5,
                    "planTotalMs": 7.0,
                },
                "solver": {
                    "success": True,
                    "status": "optimal",
                    "iterations": 4,
                    "variableCount": 6,
                    "constraintCount": 2,
                    "equalityConstraintCount": 2,
                    "inequalityConstraintCount": 0,
                    "boundCount": 6,
                    "islandCount": 1,
                    "solvedIslandCount": 1,
                    "failedIslandCount": 0,
                    "islands": [],
                },
            },
        }

    def command_sink(_model_id, payload):
        clock.advance(0.011)
        return {"set_values": len(payload.get("set_values", []))}

    manager = TraineeRenewableControlManager(
        service,
        snapshot_provider=snapshot_provider,
        receive_status_provider=receive_status,
        command_sink=command_sink,
        start_worker=False,
    )
    state = manager._state_for("shared")
    state.enabled = True
    state.loop_mode = "closed"

    try:
        with (
            patch.object(renewable_control_module.time, "perf_counter", clock.now),
            patch.object(
                renewable_control_module,
                "calculate_renewable_control_plan",
                side_effect=calculate_plan,
            ),
        ):
            payload = manager.run_once(
                "shared",
                trigger="auto",
                allow_dispatch=True,
                record_log=False,
            )
    finally:
        manager.close()

    diagnostics = payload["performanceDiagnostics"]
    latest = diagnostics["latest"]
    assert diagnostics["sampleCount"] == 1
    assert latest["trigger"] == "auto"
    assert latest["success"] is True
    assert latest["phasesMs"]["snapshotReceiveMs"] == pytest.approx(5.0)
    assert latest["phasesMs"]["planTotalMs"] == pytest.approx(7.0)
    assert latest["phasesMs"]["optimizationSolveMs"] == pytest.approx(2.0)
    assert latest["phasesMs"]["commandDispatchMs"] == pytest.approx(11.0)
    assert latest["phasesMs"]["cycleTotalMs"] == pytest.approx(23.0)
    assert latest["phasesMs"]["exchangeRequestMs"] == pytest.approx(3.0)
    assert latest["phasesMs"]["exchangeProcessingMs"] == pytest.approx(4.0)
    assert latest["phasesMs"]["exchangePublishMs"] == pytest.approx(2.0)
    assert latest["phasesMs"]["exchangeTotalMs"] == pytest.approx(9.0)
    assert latest["solver"]["iterations"] == 4
    assert latest["solver"]["variableCount"] == 6
    assert latest["solver"]["constraintCount"] == 2


def test_performance_revision_cursor_omits_unchanged_aggregate(tmp_path):
    service = SimpleNamespace(
        model_id="shared",
        service_instance_id="service-a",
        runtime_dir=tmp_path,
        lock=threading.RLock(),
    )
    manager = TraineeRenewableControlManager(
        service,
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
        receive_status_provider=lambda _model_id: {
            "receiveActive": True,
            "ready": True,
            "canRun": True,
        },
        command_sink=lambda _model_id, _payload: {"set_values": 0},
        start_worker=False,
    )
    state = manager._state_for("shared")
    with state.lock:
        state.performance.record(
            {
                "phasesMs": {"cycleTotalMs": 10.0},
                "solver": {"iterations": 1},
            }
        )

    try:
        first = manager.state("shared", compact=True)
        unchanged = manager.state(
            "shared",
            compact=True,
            after_performance_revision=first["performanceRevision"],
            after_controller_instance_id=first["controllerInstanceId"],
        )
        with state.lock:
            state.performance.record(
                {
                    "phasesMs": {"cycleTotalMs": 20.0},
                    "solver": {"iterations": 2},
                }
            )
        changed = manager.state(
            "shared",
            compact=True,
            after_performance_revision=first["performanceRevision"],
            after_controller_instance_id=first["controllerInstanceId"],
        )
    finally:
        manager.close()

    assert first["performanceDiagnostics"]["sampleCount"] == 1
    assert "performanceDiagnostics" not in unchanged
    assert changed["performanceRevision"] == first["performanceRevision"] + 1
    assert changed["performanceDiagnostics"]["sampleCount"] == 2


def test_trainee_ui_has_performance_tab_and_renders_phase_percentiles():
    html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
    script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    assert 'data-renewable-detail-tab="performance"' in html
    assert 'data-renewable-detail-pane="performance"' in html
    assert 'id="renewablePerformanceTable"' in html
    assert "function renderRenewablePerformanceDiagnostics" in script
    assert "performanceDiagnostics" in script
    assert 'params.set("after_performance_revision"' in script
    assert "unassignedDeviceCount" in script
    assert 'exchangeRequestMs: "实时帧 HTTP 请求"' in script
    assert 'exchangeProcessingMs: "实时帧合并处理"' in script
    assert 'exchangePublishMs: "实时帧快照发布"' in script
    assert 'exchangeTotalMs: "实时通信总耗时"' in script
    assert "p50Ms" in script
    assert "p95Ms" in script
