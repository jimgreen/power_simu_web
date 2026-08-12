from __future__ import annotations

import json
import threading
from copy import deepcopy
from types import SimpleNamespace

import pytest

from simu.renewable_control import (
    RenewableControlSettings,
    TraineeRenewableControlManager,
    _dispatch_setpoint_value,
    _hydrogen_post_dispatch_plan,
    _measurement_index,
)
from simu.trainee_exchange import TraineeControlSnapshot
from simu.resource_topology import resolve_resource_topology


def _block(rows):
    return {"rows": rows}


def _measurement(dev_type, dev_name, meas_type, value):
    return {
        "dev_type": dev_type,
        "dev_name": dev_name,
        "meas_type": meas_type,
        "value": value,
        "valid": 1,
    }


def _fuel_cell_snapshot(*, tank_pressure=20.0, include_pressure=True):
    model = {
        "ACNode": _block([{"idx": 1, "name": "ac", "run_stat": 1}]),
        "DCNode": _block([{"idx": 1, "name": "dc", "run_stat": 1}]),
        "ACRealBs": _block([{"idx": 1, "name": "ac-bs", "node": 1, "run_stat": 1}]),
        "DCRealBs": _block([{"idx": 1, "name": "dc-bs", "node": 1, "run_stat": 1}]),
        "DCGenerator": _block([
            {
                "idx": 1,
                "name": "fuel-cell",
                "node": 1,
                "control_type": "P",
                "p_set": 0,
                "p_min": 0,
                "p_max": 30,
                "rated_capacity": 30,
                "run_stat": 1,
            }
        ]),
        "HydroLoad": _block([
            {
                "idx": 1,
                "name": "fuel-hydrogen",
                "node": 1,
                "flow_set": 0,
                "flow_min": 0,
                "flow_max": 20,
                "run_stat": 1,
            }
        ]),
        "HydroStorage": _block([
            {
                "idx": 1,
                "name": "tank",
                "node": 1,
                "pressure_min": 2,
                "pressure_max": 45,
                "run_stat": 1,
            }
        ]),
        "Hydro2DcE": _block([
            {
                "idx": 1,
                "name": "fuel-coupling",
                "control_type": "P",
                "idx_dc_unit_t1": 1,
                "idx_h2_load_t2": 1,
                "h2e_coeff": 1.5,
                "run_stat": 1,
            }
        ]),
        "DCACConverter": _block([
            {
                "idx": 1,
                "name": "grid-converter",
                "ac_node": 1,
                "dc_node": 1,
                "ac_control_type": "P",
                "dc_control_type": "NONE",
                "p_ac_min": -50,
                "p_ac_max": 50,
                "run_stat": 1,
            }
        ]),
    }
    devices = [
        {
            "dev_type": block,
            "model_block": block,
            "dev_name": row["name"],
            "run_stat": 1,
            "status": 1,
            "set_types": (["p_set"] if block == "DCGenerator" else ["flow_set"] if block == "HydroLoad" else []),
            "set_values": {},
            "raw": dict(row),
        }
        for block in ("DCGenerator", "HydroLoad", "HydroStorage", "Hydro2DcE")
        for row in model[block]["rows"]
    ]
    devices.append(
        {
            "dev_type": "DCACConverter",
            "model_block": "DCACConverter",
            "dev_name": "grid-converter",
            "run_stat": 1,
            "status": 1,
            "set_types": ["p_ac_set"],
            "set_values": {},
            "raw": dict(model["DCACConverter"]["rows"][0]),
        }
    )
    scada = [
        _measurement("DCGenerator", "fuel-cell", "P_GEN", 0),
        _measurement("HydroLoad", "fuel-hydrogen", "FLOW", 0),
    ]
    if include_pressure:
        scada.append(_measurement("HydroStorage", "tank", "PRESSURE", tank_pressure))
    return {
        "definitions": {
            "model": model,
            "control": {
                "SetValue": _block(
                    [
                        {"dev_type": "DCGenerator", "dev_name": "fuel-cell", "set_type": "p_set"},
                        {"dev_type": "HydroLoad", "dev_name": "fuel-hydrogen", "set_type": "flow_set"},
                    ]
                )
            },
        },
        "devices": devices,
        "measurements": {"scada": scada, "real": []},
    }


def _add_second_parallel_converter(snapshot):
    source = snapshot["definitions"]["model"]["DCACConverter"]["rows"][0]
    second = dict(source)
    second.update({"idx": 2, "name": "grid-converter-2", "p_ac_min": -10, "p_ac_max": 10})
    snapshot["definitions"]["model"]["DCACConverter"]["rows"].append(second)
    snapshot["devices"].append(
        {
            "dev_type": "DCACConverter",
            "model_block": "DCACConverter",
            "dev_name": "grid-converter-2",
            "run_stat": 1,
            "status": 1,
            "set_types": ["p_dc_set"],
            "set_values": {},
            "raw": dict(second),
        }
    )
    return snapshot


def _electrolyzer_snapshot(
    *,
    tank_pressure=20.0,
    electric_power=4.0,
    control_type="P",
    include_power_measurement=True,
):
    snapshot = _fuel_cell_snapshot(tank_pressure=tank_pressure)
    model = snapshot["definitions"]["model"]
    model["ACLoad"] = _block(
        [
            {
                "idx": 1,
                "name": "electrolyzer-load",
                "node": 1,
                "p_set": electric_power,
                "p_min": 0,
                "p_max": 20,
                "rated_capacity": 20,
                "run_stat": 1,
            }
        ]
    )
    model["HydroSource"] = _block(
        [
            {
                "idx": 1,
                "name": "electrolyzer-hydrogen",
                "node": 1,
                "flow_set": electric_power * 0.2,
                "flow_min": 0,
                "flow_max": 10,
                "run_stat": 1,
            }
        ]
    )
    model["AcE2Hydro"] = _block(
        [
            {
                "idx": 1,
                "name": "electrolyzer-coupling",
                "control_type": control_type,
                "idx_ac_load_t1": 1,
                "idx_h2_unit_t2": 1,
                "e2h_coeff": 0.2,
                "run_stat": 1,
            }
        ]
    )
    snapshot["devices"].extend(
        [
            {
                "dev_type": "ACLoad",
                "model_block": "ACLoad",
                "dev_name": "electrolyzer-load",
                "run_stat": 1,
                "status": 1,
                "set_types": ["p_set"],
                "set_values": {"p_set": electric_power},
                "raw": dict(model["ACLoad"]["rows"][0]),
            },
            {
                "dev_type": "HydroSource",
                "model_block": "HydroSource",
                "dev_name": "electrolyzer-hydrogen",
                "run_stat": 1,
                "status": 1,
                "set_types": ["flow_set"],
                "set_values": {"flow_set": electric_power * 0.2},
                "raw": dict(model["HydroSource"]["rows"][0]),
            },
            {
                "dev_type": "AcE2Hydro",
                "model_block": "AcE2Hydro",
                "dev_name": "electrolyzer-coupling",
                "run_stat": 1,
                "status": 1,
                "set_types": [],
                "set_values": {},
                "raw": dict(model["AcE2Hydro"]["rows"][0]),
            },
        ]
    )
    active_point = (
        {"dev_type": "HydroSource", "dev_name": "electrolyzer-hydrogen", "set_type": "flow_set"}
        if control_type == "FLOW"
        else {"dev_type": "ACLoad", "dev_name": "electrolyzer-load", "set_type": "p_set"}
    )
    snapshot["definitions"]["control"]["SetValue"]["rows"].append(active_point)
    snapshot["measurements"]["scada"].append(
        _measurement("HydroSource", "electrolyzer-hydrogen", "FLOW", electric_power * 0.2)
    )
    if include_power_measurement:
        snapshot["measurements"]["scada"].append(
            _measurement("ACLoad", "electrolyzer-load", "P_LOAD", electric_power)
        )
    return snapshot


def _run(snapshot, settings):
    measurements = _measurement_index(snapshot)
    topology = resolve_resource_topology(snapshot, ())
    group_id = next(iter(topology.dc_transfer_groups))
    command_rows = [
        {
            "dev_type": "DCACConverter",
            "model_block": "DCACConverter",
            "dev_name": "grid-converter",
            "converterRole": "grid",
            "converterDirection": "AC_TO_DC",
            "online": True,
            "commandable": True,
            "strategyCommand": True,
            "set_type": "p_ac_set",
            "currentKw": 0,
            "commandKw": 0,
            "signedMinTargetKw": -50,
            "signedMaxTargetKw": 50,
            "dcTransferGroupId": group_id,
        }
    ]
    storage_rows = [
        {
            "online": True,
            "socKnown": True,
            "soc": 0.1,
            "socMin": 0.2,
        }
    ]
    result = _hydrogen_post_dispatch_plan(
        snapshot,
        measurements,
        settings,
        topology,
        command_rows,
        storage_rows,
        diesel_current_kw=80,
        diesel_deadband_upper_kw=40,
    )
    return result, command_rows


def _run_electrolyzer(
    snapshot,
    settings,
    *,
    diesel_power=20.0,
    upper_guard=40.0,
    diesel_input_valid=True,
):
    measurements = _measurement_index(snapshot)
    topology = resolve_resource_topology(snapshot, ())
    rows = []
    result = _hydrogen_post_dispatch_plan(
        snapshot,
        measurements,
        settings,
        topology,
        rows,
        [],
        diesel_current_kw=diesel_power,
        diesel_deadband_upper_kw=upper_guard,
        diesel_input_valid=diesel_input_valid,
    )
    return result, rows


def test_hydrogen_setting_defaults_disabled_and_round_trips():
    settings = RenewableControlSettings()
    assert settings.hydrogen_closed_loop_enabled is False
    updated = settings.updated(
        {
            "hydrogenClosedLoopEnabled": True,
            "hydrogenPressureDeadbandRatio": 0.1,
        }
    )
    assert updated.hydrogen_closed_loop_enabled is True
    assert updated.payload()["hydrogenClosedLoopEnabled"] is True
    assert updated.payload()["hydrogenPressureDeadbandRatio"] == 0.1
    json.dumps(updated.payload())


def test_disabled_hydrogen_control_emits_no_command_or_converter_change():
    result, rows = _run(_fuel_cell_snapshot(), RenewableControlSettings())
    assert result["action"] == "disabled"
    assert result["commands"] == []
    assert rows[0]["commandKw"] == 0


def test_low_tank_pressure_blocks_fuel_cell_strategy():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        hydrogen_pressure_deadband_ratio=0.05,
        step_coefficient=0.1,
    )
    result, rows = _run(_fuel_cell_snapshot(tank_pressure=3.0), settings)
    assert result["pressureStates"][0]["lowGuard"] == 4.15
    assert result["action"] == "fuel_cell_pressure_low_blocked"
    assert result["commands"] == []
    assert not any(row.get("dev_name") == "fuel-cell" for row in rows)


def test_missing_tank_pressure_fails_closed_for_fuel_cell():
    settings = RenewableControlSettings(hydrogen_closed_loop_enabled=True)
    result, rows = _run(
        _fuel_cell_snapshot(include_pressure=False),
        settings,
    )
    assert result["action"] == "blocked"
    assert result["commands"] == []
    assert not any(row.get("dev_name") == "fuel-cell" for row in rows)


def test_electrolyzer_power_rises_one_power_step_when_headroom_exists():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        step_coefficient=0.1,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=4.0),
        settings,
        diesel_power=20.0,
        upper_guard=40.0,
    )
    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["action"] == "electrolyzer"
    assert result["electricPowerAdjustmentKw"] == 2.0
    assert result["commands"][0]["electricPowerKw"] == 6.0
    assert result["commands"][0]["equivalentFlow"] == pytest.approx(1.2)
    assert command["commandKw"] == 6.0


def test_missing_diesel_measurement_blocks_electrolyzer_strategy():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        step_coefficient=0.1,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=4.0),
        settings,
        diesel_input_valid=False,
    )

    assert result["action"] == "blocked"
    assert result["commands"] == []
    assert rows == []
    assert any("柴发" in warning and "实时有功" in warning for warning in result["warnings"])


def test_electrolyzer_uses_live_flow_when_power_measurement_is_missing():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        step_coefficient=0.1,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(
            electric_power=4.0,
            include_power_measurement=False,
        ),
        settings,
    )
    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")

    assert result["electricPowerAdjustmentKw"] == 2.0
    assert command["commandKw"] == 6.0


def test_electrolyzer_does_not_use_static_setpoint_as_realtime_baseline():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        step_coefficient=0.1,
    )
    snapshot = _electrolyzer_snapshot(
        electric_power=4.0,
        include_power_measurement=False,
    )
    snapshot["measurements"]["scada"] = [
        row
        for row in snapshot["measurements"]["scada"]
        if not (
            row.get("dev_type") == "HydroSource"
            and row.get("dev_name") == "electrolyzer-hydrogen"
        )
    ]
    result, rows = _run_electrolyzer(snapshot, settings)

    assert result["action"] == "blocked"
    assert result["commands"] == []
    assert rows == []


def test_electrolyzer_power_step_is_clamped_by_diesel_headroom():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        step_coefficient=0.1,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=4.0),
        settings,
        diesel_power=39.0,
        upper_guard=40.0,
    )
    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["electricPowerAdjustmentKw"] == 1.0
    assert command["commandKw"] == 5.0


def test_electrolyzer_power_step_is_clamped_by_power_and_flow_limits():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        step_coefficient=0.1,
    )
    snapshot = _electrolyzer_snapshot(electric_power=4.0)
    snapshot["definitions"]["model"]["ACLoad"]["rows"][0]["p_max"] = 4.7
    snapshot["definitions"]["model"]["HydroSource"]["rows"][0]["flow_max"] = 0.95
    result, rows = _run_electrolyzer(snapshot, settings)
    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")

    assert result["electricPowerAdjustmentKw"] == pytest.approx(0.7)
    assert command["commandKw"] == pytest.approx(4.7)

    flow_limited = _electrolyzer_snapshot(electric_power=4.0)
    flow_limited["definitions"]["model"]["HydroSource"]["rows"][0]["flow_max"] = 0.9
    result, rows = _run_electrolyzer(flow_limited, settings)
    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")

    assert result["electricPowerAdjustmentKw"] == pytest.approx(0.5)
    assert command["commandKw"] == pytest.approx(4.5)


def test_electrolyzer_power_keeps_rising_one_step_on_each_fresh_cycle():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        step_coefficient=0.1,
    )
    first_snapshot = _electrolyzer_snapshot(electric_power=4.0)
    first, first_rows = _run_electrolyzer(first_snapshot, settings)
    first_command = next(
        row for row in first_rows if row.get("dev_name") == "electrolyzer-load"
    )

    second_snapshot = _electrolyzer_snapshot(electric_power=first_command["commandKw"])
    second, second_rows = _run_electrolyzer(second_snapshot, settings)
    second_command = next(
        row for row in second_rows if row.get("dev_name") == "electrolyzer-load"
    )

    assert first["electricPowerAdjustmentKw"] == 2.0
    assert first_command["commandKw"] == 6.0
    assert second["electricPowerAdjustmentKw"] == 2.0
    assert second_command["commandKw"] == 8.0


def test_flow_controlled_electrolyzer_still_steps_by_electric_power():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        step_coefficient=0.1,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=4.0, control_type="FLOW"),
        settings,
    )
    command = next(
        row for row in rows if row.get("dev_name") == "electrolyzer-hydrogen"
    )

    assert result["electricPowerAdjustmentKw"] == 2.0
    assert result["commands"][0]["electricPowerKw"] == 6.0
    assert result["commands"][0]["activeSetType"] == "flow_set"
    assert command["set_type"] == "flow_set"
    assert command["commandKw"] == pytest.approx(1.2)


def test_qinling_pq_electrolyzer_compatibility_uses_power_control_point():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        step_coefficient=0.1,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=4.0, control_type="PQ"),
        settings,
    )
    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")

    assert result["action"] == "electrolyzer"
    assert result["commands"][0]["activeSetType"] == "p_set"
    assert command["set_type"] == "p_set"
    assert command["commandKw"] == 6.0


def test_pressure_at_guard_allows_incremental_fuel_cell_and_dc_acdc_correction():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        hydrogen_pressure_deadband_ratio=0.05,
        step_coefficient=0.1,
    )
    result, rows = _run(_fuel_cell_snapshot(tank_pressure=4.15), settings)
    fuel_row = next(row for row in rows if row.get("dev_name") == "fuel-cell")
    converter_row = next(row for row in rows if row.get("dev_name") == "grid-converter")
    assert result["action"] == "fuel_cell"
    assert result["electricPowerAdjustmentKw"] == 30.0
    assert result["targetElectricPowerKw"] == 30.0
    assert result["commands"][0]["equivalentFlow"] == 20.0
    assert fuel_row["commandKw"] == 30.0
    assert converter_row["commandKw"] == -30.0


def test_pressure_just_below_guard_blocks_fuel_cell():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        hydrogen_pressure_deadband_ratio=0.05,
    )
    result, rows = _run(_fuel_cell_snapshot(tank_pressure=4.15 - 1e-10), settings)

    assert result["action"] == "fuel_cell_pressure_low_blocked"
    assert not any(row.get("dev_name") == "fuel-cell" for row in rows)


def test_dc_hydrogen_correction_shares_parallel_converter_headroom_and_dispatch_signs():
    snapshot = _add_second_parallel_converter(_fuel_cell_snapshot(tank_pressure=4.15))
    measurements = _measurement_index(snapshot)
    topology = resolve_resource_topology(snapshot, ())
    group_id = next(iter(topology.dc_transfer_groups))
    rows = [
        {
            "dev_type": "DCACConverter",
            "model_block": "DCACConverter",
            "dev_name": "grid-converter",
            "converterRole": "grid",
            "converterDirection": "AC_TO_DC",
            "online": True,
            "commandable": True,
            "strategyCommand": True,
            "set_type": "p_ac_set",
            "currentKw": -40,
            "commandKw": -40,
            "signedMinTargetKw": -50,
            "signedMaxTargetKw": 50,
            "dcTransferGroupId": group_id,
        },
        {
            "dev_type": "DCACConverter",
            "model_block": "DCACConverter",
            "dev_name": "grid-converter-2",
            "converterRole": "grid",
            "converterDirection": "AC_TO_DC",
            "online": True,
            "commandable": True,
            "strategyCommand": True,
            "set_type": "p_dc_set",
            "currentKw": 0,
            "commandKw": 0,
            "signedMinTargetKw": -10,
            "signedMaxTargetKw": 10,
            "dcTransferGroupId": group_id,
        },
    ]
    result = _hydrogen_post_dispatch_plan(
        snapshot,
        measurements,
        RenewableControlSettings(hydrogen_closed_loop_enabled=True),
        topology,
        rows,
        [{"online": True, "socKnown": True, "soc": 0.1, "socMin": 0.2}],
        diesel_current_kw=55,
        diesel_deadband_upper_kw=40,
    )

    converters = {
        row["dev_name"]: row
        for row in rows
        if row.get("model_block") == "DCACConverter"
    }
    assert result["converterCorrectionKw"] == pytest.approx(15.0)
    assert converters["grid-converter"]["commandKw"] == pytest.approx(-47.5)
    assert converters["grid-converter-2"]["commandKw"] == pytest.approx(-7.5)
    assert _dispatch_setpoint_value(converters["grid-converter"]) == pytest.approx(-47.5)
    assert _dispatch_setpoint_value(converters["grid-converter-2"]) == pytest.approx(7.5)


def test_hydrogen_settings_are_persisted_and_reloaded(tmp_path):
    service = SimpleNamespace(
        model_id="shared",
        service_instance_id="hydrogen-settings-service",
        runtime_dir=tmp_path,
        lock=threading.RLock(),
    )

    def snapshot_provider(_model_id):
        return TraineeControlSnapshot(
            snapshot=deepcopy(_electrolyzer_snapshot()),
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
            "revision": 1,
            "connectionSignature": ["learner", 1],
        }

    first = TraineeRenewableControlManager(
        service,
        snapshot_provider=snapshot_provider,
        receive_status_provider=receive_status,
        command_sink=lambda _model_id, _payload: {},
        start_worker=False,
    )
    try:
        saved = first.apply_action(
            "shared",
            {
                "action": "update_settings",
                "settings": {
                    "hydrogenClosedLoopEnabled": True,
                    "hydrogenPressureDeadbandRatio": 0.12,
                },
            },
        )
        assert saved["settings"]["hydrogenClosedLoopEnabled"] is True
        assert saved["settings"]["hydrogenPressureDeadbandRatio"] == 0.12
    finally:
        first.close()

    second = TraineeRenewableControlManager(
        service,
        snapshot_provider=snapshot_provider,
        receive_status_provider=receive_status,
        command_sink=lambda _model_id, _payload: {},
        start_worker=False,
    )
    try:
        reloaded = second.state("shared")
    finally:
        second.close()

    assert reloaded["settings"]["hydrogenClosedLoopEnabled"] is True
    assert reloaded["settings"]["hydrogenPressureDeadbandRatio"] == 0.12
