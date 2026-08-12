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
        "HydroNode": _block([{"idx": 1, "name": "hydrogen", "run_stat": 1}]),
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


def _run(
    snapshot,
    settings,
    *,
    diesel_power=80.0,
    upper_guard=40.0,
    storage_soc=0.1,
    storage_soc_min=0.2,
):
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
            "soc": storage_soc,
            "socMin": storage_soc_min,
        }
    ]
    result = _hydrogen_post_dispatch_plan(
        snapshot,
        measurements,
        settings,
        topology,
        command_rows,
        storage_rows,
        diesel_current_kw=diesel_power,
        diesel_deadband_upper_kw=upper_guard,
    )
    return result, command_rows


def _run_electrolyzer(
    snapshot,
    settings,
    *,
    diesel_power=20.0,
    upper_guard=40.0,
    diesel_input_valid=True,
    storage_soc=0.9,
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
        [
            {
                "online": True,
                "socKnown": storage_soc is not None,
                "soc": storage_soc,
                "socMin": 0.2,
            }
        ],
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
            "electrolyzerPowerMinKw": 5,
            "electrolyzerPowerMaxKw": 45,
            "electrolyzerPowerDeadbandKw": 1,
            "electrolyzerPowerStepKw": 2,
            "fuelCellPowerMinKw": 3,
            "fuelCellPowerMaxKw": 14,
            "fuelCellPowerDeadbandKw": 0.5,
            "fuelCellPowerStepKw": 1.5,
        }
    )
    assert updated.hydrogen_closed_loop_enabled is True
    assert updated.payload()["hydrogenClosedLoopEnabled"] is True
    assert updated.payload()["hydrogenPressureDeadbandRatio"] == 0.1
    assert updated.payload()["electrolyzerPowerMinKw"] == 5
    assert updated.payload()["electrolyzerPowerMaxKw"] == 45
    assert updated.payload()["electrolyzerPowerDeadbandKw"] == 1
    assert updated.payload()["electrolyzerPowerStepKw"] == 2
    assert updated.payload()["fuelCellPowerMinKw"] == 3
    assert updated.payload()["fuelCellPowerMaxKw"] == 14
    assert updated.payload()["fuelCellPowerDeadbandKw"] == 0.5
    assert updated.payload()["fuelCellPowerStepKw"] == 1.5
    json.dumps(updated.payload())


def test_hydrogen_power_settings_normalize_invalid_ranges():
    settings = RenewableControlSettings().updated(
        {
            "electrolyzerPowerMinKw": -1,
            "electrolyzerPowerMaxKw": -2,
            "electrolyzerPowerDeadbandKw": -3,
            "electrolyzerPowerStepKw": 0,
            "fuelCellPowerMinKw": 8,
            "fuelCellPowerMaxKw": 4,
            "fuelCellPowerDeadbandKw": 10,
            "fuelCellPowerStepKw": -2,
        }
    )

    assert settings.electrolyzer_power_min_kw == 0
    assert settings.electrolyzer_power_max_kw == 0
    assert settings.electrolyzer_power_deadband_kw == 0
    assert settings.electrolyzer_power_step_kw > 0
    assert settings.fuel_cell_power_min_kw == 8
    assert settings.fuel_cell_power_max_kw == 8
    assert settings.fuel_cell_power_deadband_kw == 0
    assert settings.fuel_cell_power_step_kw > 0


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
    assert result["action"] == "pressure_safety_stop"
    fuel_row = next(row for row in rows if row.get("dev_name") == "fuel-cell")
    assert fuel_row["commandKw"] == 0
    assert result["commands"][0]["pressureSafetyStop"] is True


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


@pytest.mark.parametrize(
    ("storage_soc", "starts"),
    ((0.799, False), (0.8, False), (0.801, True)),
)
def test_electrolyzer_start_requires_every_storage_soc_strictly_above_80_percent(
    storage_soc,
    starts,
):
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=6.0,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=0.0),
        settings,
        diesel_power=34.0,
        upper_guard=40.0,
        storage_soc=storage_soc,
    )

    commands = [row for row in rows if row.get("dev_name") == "electrolyzer-load"]
    assert bool(commands) is starts
    if starts:
        assert commands[0]["commandKw"] == 6.0
        assert result["commands"][0]["startThresholdKw"] == 6.0
    else:
        assert result["electricPowerAdjustmentKw"] == 0.0


@pytest.mark.parametrize(
    ("diesel_power", "expected_target"),
    ((34.001, None), (34.0, 6.0), (30.0, 6.0)),
)
def test_electrolyzer_does_not_start_unless_margin_reaches_start_threshold(
    diesel_power,
    expected_target,
):
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=6.0,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=0.0),
        settings,
        diesel_power=diesel_power,
        upper_guard=40.0,
        storage_soc=0.81,
    )

    commands = [row for row in rows if row.get("dev_name") == "electrolyzer-load"]
    if expected_target is None:
        assert commands == []
        assert any("启动功率" in warning for warning in result["warnings"])
    else:
        assert commands[0]["commandKw"] == expected_target


def test_running_electrolyzer_increase_equals_diesel_guard_gap_before_limits():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        electrolyzer_power_min_kw=0.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=10.0,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=4.0),
        settings,
        diesel_power=38.5,
        upper_guard=40.0,
        storage_soc=0.2,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["electricPowerAdjustmentKw"] == pytest.approx(1.5)
    assert command["commandKw"] == pytest.approx(5.5)


def test_low_storage_soc_and_high_diesel_reduce_running_electrolyzer_one_step():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=2.0,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=8.0),
        settings,
        diesel_power=45.0,
        upper_guard=40.0,
        storage_soc=0.399,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["action"] == "electrolyzer_reduce"
    assert result["electricPowerAdjustmentKw"] == pytest.approx(-2.0)
    assert command["commandKw"] == pytest.approx(6.0)


def test_electrolyzer_reduction_below_lower_deadband_explicitly_stops():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=3.0,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=6.0),
        settings,
        diesel_power=45.0,
        upper_guard=40.0,
        storage_soc=0.399,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["action"] == "power_hysteresis_stop"
    assert command["commandKw"] == 0.0
    assert result["commands"][0]["powerHysteresisStop"] is True


def test_configured_electrolyzer_upper_limit_only_tightens_model_boundary():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        electrolyzer_power_min_kw=0.0,
        electrolyzer_power_max_kw=7.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=10.0,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=6.0),
        settings,
        diesel_power=20.0,
        upper_guard=40.0,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert command["commandKw"] == 7.0
    assert result["commands"][0]["configuredMaximumPowerKw"] == 7.0


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
    assert result["electricPowerAdjustmentKw"] == 3.0
    assert result["targetElectricPowerKw"] == 3.0
    assert result["commands"][0]["equivalentFlow"] == 2.0
    assert result["commands"][0]["stepLimitKw"] == 3.0
    assert fuel_row["commandKw"] == 3.0
    assert converter_row["commandKw"] == -3.0


def test_fuel_cell_start_requires_margin_for_minimum_plus_deadband():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        fuel_cell_power_min_kw=5.0,
        fuel_cell_power_max_kw=20.0,
        fuel_cell_power_deadband_kw=1.0,
        fuel_cell_power_step_kw=6.0,
    )

    blocked, blocked_rows = _run(
        _fuel_cell_snapshot(tank_pressure=20.0),
        settings,
        diesel_power=45.0,
    )
    assert blocked_rows[0]["commandKw"] == 0.0
    assert any("启动功率" in warning for warning in blocked["warnings"])

    measurements = _measurement_index(_fuel_cell_snapshot(tank_pressure=20.0))
    snapshot = _fuel_cell_snapshot(tank_pressure=20.0)
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
            "currentKw": 0,
            "commandKw": 0,
            "signedMinTargetKw": -50,
            "signedMaxTargetKw": 50,
            "dcTransferGroupId": group_id,
        }
    ]
    started = _hydrogen_post_dispatch_plan(
        snapshot,
        measurements,
        settings,
        topology,
        rows,
        [{"online": True, "socKnown": True, "soc": 0.1, "socMin": 0.2}],
        diesel_current_kw=46.0,
        diesel_deadband_upper_kw=40.0,
    )
    fuel_row = next(row for row in rows if row.get("dev_name") == "fuel-cell")
    assert fuel_row["commandKw"] == 6.0
    assert started["commands"][0]["startThresholdKw"] == 6.0


def test_running_fuel_cell_reduction_below_lower_deadband_explicitly_stops():
    snapshot = _fuel_cell_snapshot(tank_pressure=20.0)
    snapshot["measurements"]["scada"] = [
        row
        for row in snapshot["measurements"]["scada"]
        if not (row["dev_type"] == "DCGenerator" and row["dev_name"] == "fuel-cell")
    ]
    snapshot["measurements"]["scada"].append(
        _measurement("DCGenerator", "fuel-cell", "P_GEN", 6.0)
    )
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        fuel_cell_power_min_kw=5.0,
        fuel_cell_power_max_kw=20.0,
        fuel_cell_power_deadband_kw=1.0,
        fuel_cell_power_step_kw=3.0,
    )
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
            "currentKw": 0,
            "commandKw": 0,
            "signedMinTargetKw": -50,
            "signedMaxTargetKw": 50,
            "dcTransferGroupId": group_id,
        }
    ]
    result = _hydrogen_post_dispatch_plan(
        snapshot,
        measurements,
        settings,
        topology,
        rows,
        [{"online": True, "socKnown": True, "soc": 0.5, "socMin": 0.2}],
        diesel_current_kw=40.0,
        diesel_deadband_upper_kw=40.0,
    )

    fuel_row = next(row for row in rows if row.get("dev_name") == "fuel-cell")
    assert result["action"] == "power_hysteresis_stop"
    assert fuel_row["commandKw"] == 0.0


def test_pressure_just_below_guard_blocks_fuel_cell():
    settings = RenewableControlSettings(
        hydrogen_closed_loop_enabled=True,
        hydrogen_pressure_deadband_ratio=0.05,
    )
    result, rows = _run(_fuel_cell_snapshot(tank_pressure=4.15 - 1e-10), settings)

    assert result["action"] == "pressure_safety_stop"
    assert next(row for row in rows if row.get("dev_name") == "fuel-cell")["commandKw"] == 0


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
            "transferCapacityKw": 50,
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
            "transferCapacityKw": 10,
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
    assert result["converterCorrectionKw"] == pytest.approx(3.0)
    assert converters["grid-converter"]["commandKw"] == pytest.approx(-41.5)
    assert converters["grid-converter-2"]["commandKw"] == pytest.approx(-1.5)
    assert _dispatch_setpoint_value(converters["grid-converter"]) == pytest.approx(-41.5)
    assert _dispatch_setpoint_value(converters["grid-converter-2"]) == pytest.approx(1.5)


def test_hydrogen_target_is_held_in_next_replaceable_generation():
    first_plan = {
        "metrics": {
            "hydrogenControl": {
                "action": "electrolyzer",
                "commands": [
                    {
                        "activeDevType": "ACLoad",
                        "activeDevName": "electrolyzer-load",
                        "activeSetType": "p_set",
                    }
                ],
            }
        },
        "commands": [
            {
                "dev_type": "ACLoad",
                "dev_name": "electrolyzer-load",
                "set_type": "p_set",
                "set_value": 6.0,
            }
        ],
        "commandRows": [
            {
                "category": "氢能闭环",
                "dev_type": "ACLoad",
                "dev_name": "electrolyzer-load",
                "set_type": "p_set",
                "currentKw": 4.0,
                "commandKw": 6.0,
                "strategyCommand": True,
            }
        ],
    }
    effective = TraineeRenewableControlManager._capture_effective_targets(first_plan)
    held = TraineeRenewableControlManager._plan_with_held_hydrogen_targets(
        {
            "metrics": {"hydrogenControl": {"action": "hold", "commands": []}},
            "commands": [],
            "commandRows": [],
        },
        effective,
    )

    assert held["commands"] == first_plan["commands"]
    assert held["metrics"]["hydrogenControl"]["generationHeld"] is True
    assert held["commandRows"][0]["commandKw"] == 6.0


def test_unrelated_high_pressure_hydrogen_island_does_not_block_electrolyzer():
    snapshot = _electrolyzer_snapshot(tank_pressure=20.0)
    model = snapshot["definitions"]["model"]
    model["HydroNode"]["rows"].append({"idx": 2, "name": "hydrogen-2", "run_stat": 1})
    model["HydroStorage"]["rows"].append(
        {
            "idx": 2,
            "name": "tank-2",
            "node": 2,
            "pressure_min": 2,
            "pressure_max": 45,
            "run_stat": 1,
        }
    )
    snapshot["devices"].append(
        {
            "dev_type": "HydroStorage",
            "model_block": "HydroStorage",
            "dev_name": "tank-2",
            "run_stat": 1,
            "status": 1,
            "set_types": [],
            "set_values": {},
            "raw": dict(model["HydroStorage"]["rows"][-1]),
        }
    )
    snapshot["measurements"]["scada"].append(
        _measurement("HydroStorage", "tank-2", "PRESSURE", 45.0)
    )

    result, rows = _run_electrolyzer(
        snapshot,
        RenewableControlSettings(
            hydrogen_closed_loop_enabled=True,
            step_coefficient=0.1,
        ),
    )

    assert result["action"] == "electrolyzer"
    assert next(row for row in rows if row.get("dev_name") == "electrolyzer-load")[
        "commandKw"
    ] == 6.0


def test_closed_hydrogen_valve_splits_island_and_fails_only_disconnected_device():
    snapshot = _electrolyzer_snapshot(tank_pressure=20.0)
    model = snapshot["definitions"]["model"]
    model["HydroNode"]["rows"].append({"idx": 2, "name": "hydrogen-2", "run_stat": 1})
    model["HydroSource"]["rows"][0]["node"] = 2
    model["HydroStopValve"] = _block(
        [
            {
                "idx": 1,
                "name": "isolation-valve",
                "i_node": 1,
                "j_node": 2,
                "status": 0,
                "run_stat": 1,
            }
        ]
    )

    result, rows = _run_electrolyzer(
        snapshot,
        RenewableControlSettings(hydrogen_closed_loop_enabled=True),
    )

    assert result["action"] == "blocked"
    assert rows == []
    assert any("没有在线储氢罐" in warning for warning in result["warnings"])


def test_hydrogen_start_below_real_minimum_fails_closed_when_step_is_too_small():
    snapshot = _electrolyzer_snapshot(electric_power=0.0)
    snapshot["definitions"]["model"]["ACLoad"]["rows"][0]["p_min"] = 5.0
    snapshot["definitions"]["model"]["HydroSource"]["rows"][0]["flow_min"] = 1.5

    result, rows = _run_electrolyzer(
        snapshot,
        RenewableControlSettings(
            hydrogen_closed_loop_enabled=True,
            step_coefficient=0.1,
        ),
    )

    assert result["action"] == "blocked"
    assert rows == []
    assert any("启动功率" in warning for warning in result["warnings"])


def test_dc_hydrogen_increment_is_atomically_limited_by_remaining_converter_step():
    snapshot = _fuel_cell_snapshot(tank_pressure=20.0)
    snapshot["measurements"]["scada"] = [
        row
        for row in snapshot["measurements"]["scada"]
        if not (row["dev_type"] == "DCGenerator" and row["dev_name"] == "fuel-cell")
    ]
    snapshot["measurements"]["scada"].append(
        _measurement("DCGenerator", "fuel-cell", "P_GEN", 4.0)
    )
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
            "currentKw": 0.0,
            "commandKw": -1.5,
            "stepKw": 2.0,
            "signedMinTargetKw": -50,
            "signedMaxTargetKw": 50,
            "transferCapacityKw": 50,
            "dcTransferGroupId": group_id,
        }
    ]
    result = _hydrogen_post_dispatch_plan(
        snapshot,
        measurements,
        RenewableControlSettings(
            hydrogen_closed_loop_enabled=True,
            step_coefficient=1.0,
        ),
        topology,
        rows,
        [{"online": True, "socKnown": True, "soc": 0.1, "socMin": 0.2}],
        diesel_current_kw=55,
        diesel_deadband_upper_kw=40,
    )

    fuel_row = next(row for row in rows if row.get("dev_name") == "fuel-cell")
    converter_row = next(row for row in rows if row.get("dev_name") == "grid-converter")
    assert result["electricPowerAdjustmentKw"] == pytest.approx(0.5)
    assert result["converterCorrectionKw"] == pytest.approx(0.5)
    assert fuel_row["commandKw"] == pytest.approx(4.5)
    assert converter_row["commandKw"] == pytest.approx(-2.0)


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
                    "electrolyzerPowerMinKw": 4,
                    "electrolyzerPowerMaxKw": 42,
                    "electrolyzerPowerDeadbandKw": 1,
                    "electrolyzerPowerStepKw": 2.5,
                    "fuelCellPowerMinKw": 3,
                    "fuelCellPowerMaxKw": 12,
                    "fuelCellPowerDeadbandKw": 0.5,
                    "fuelCellPowerStepKw": 1.5,
                },
            },
        )
        assert saved["settings"]["hydrogenClosedLoopEnabled"] is True
        assert saved["settings"]["hydrogenPressureDeadbandRatio"] == 0.12
        assert saved["settings"]["electrolyzerPowerMinKw"] == 4
        assert saved["settings"]["fuelCellPowerStepKw"] == 1.5
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
    assert reloaded["settings"]["electrolyzerPowerMaxKw"] == 42
    assert reloaded["settings"]["fuelCellPowerDeadbandKw"] == 0.5
