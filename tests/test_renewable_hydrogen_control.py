from __future__ import annotations

import json
import threading
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest
import simu_loop

from simu.renewable_control import (
    RenewableControlSettings,
    TraineeRenewableControlManager,
    _dispatch_setpoint_value,
    _hydrogen_business_decision_detail,
    _hydrogen_operating_metrics,
    _optimize_hydrogen_within_topology_islands,
    _measurement_index,
    calculate_renewable_control_plan,
)
from simu.trainee_exchange import TraineeControlSnapshot
from simu.resource_topology import ResourceRef, resolve_resource_topology
from simu.model_semantics import energy_coupling_control_bindings


ROOT = Path(__file__).resolve().parents[1]


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


def test_default_fuel_cell_power_ceiling_is_ninety_percent():
    settings = RenewableControlSettings()

    assert settings.fuel_cell_power_max_ratio == pytest.approx(0.90)


@pytest.mark.parametrize(
    "relative_model",
    (
        "models/simulator/source/新模型2/model.e",
        "models/simulator/source/秦岭站/model.e",
        "models/simulator/source/秦岭站2/model.e",
        "models/trainee/source/新模型/model.e",
        "models/trainee/source/默认模型/model.e",
    ),
)
def test_bundled_fuel_cell_hydrogen_bounds_cover_rated_electric_power(
    relative_model,
):
    model_path = ROOT / relative_model
    if not model_path.is_file():
        pytest.skip(f"bundled model not present: {relative_model}")
    book = simu_loop.EBook(model_path)
    coupling = book.data["Hydro2DcE"].data[0]
    generator = next(
        row
        for row in book.data["DCGenerator"].data
        if str(row.get("idx")) == str(coupling["idx_dc_unit_t1"])
    )
    hydrogen_load = next(
        row
        for row in book.data["HydroLoad"].data
        if str(row.get("idx")) == str(coupling["idx_h2_load_t2"])
    )
    coefficient = float(coupling["h2e_coeff"])
    required_flow = float(generator["p_max"]) / coefficient

    assert float(hydrogen_load["rated_capacity"]) >= required_flow
    assert float(hydrogen_load["flow_max"]) >= required_flow
    assert any(
        float(row["flow_min"]) <= -required_flow
        and float(row["flow_max"]) >= required_flow
        for row in book.data["HydroStorage"].data
    )


def test_default_fuel_cell_ceiling_allows_twenty_seven_kw_target():
    snapshot = _fuel_cell_snapshot()
    for row in snapshot["measurements"]["scada"]:
        if row["dev_type"] == "DCGenerator" and row["meas_type"] == "P_GEN":
            row["value"] = 15.0
        if row["dev_type"] == "HydroLoad" and row["meas_type"] == "FLOW":
            row["value"] = 10.0

    result, rows = _run(
        snapshot,
        RenewableControlSettings(fuel_cell_power_step_ratio=1.0),
        diesel_power=100.0,
    )
    command = next(row for row in rows if row.get("dev_name") == "fuel-cell")

    assert result["commands"][0]["configuredMaximumPowerKw"] == pytest.approx(27.0)
    assert command["commandKw"] == pytest.approx(27.0)


def _fuel_cell_snapshot(
    *,
    tank_pressure=20.0,
    tank_soc=0.9,
    include_pressure=True,
    include_tank_soc=True,
):
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
    if include_tank_soc:
        scada.append(_measurement("HydroStorage", "tank", "SOC", tank_soc))
    return {
        "definitions": {
            "model": model,
            "control": {
                "RunStat": _block(
                    [
                        {
                            "dev_type": "Hydro2DcE",
                            "dev_name": "fuel-coupling",
                            "run_stat": 1,
                        }
                    ]
                ),
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
    tank_soc=0.5,
    electric_power=4.0,
    control_type="P",
    include_power_measurement=True,
):
    snapshot = _fuel_cell_snapshot(tank_pressure=tank_pressure, tank_soc=tank_soc)
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
    snapshot["definitions"]["control"]["RunStat"]["rows"].append(
        {
            "dev_type": "AcE2Hydro",
            "dev_name": "electrolyzer-coupling",
            "run_stat": 1,
        }
    )
    snapshot["measurements"]["scada"].append(
        _measurement("HydroSource", "electrolyzer-hydrogen", "FLOW", electric_power * 0.2)
    )
    if include_power_measurement:
        snapshot["measurements"]["scada"].append(
            _measurement("ACLoad", "electrolyzer-load", "P_LOAD", electric_power)
        )
    return snapshot


def _set_coupling_run_state(snapshot, coupling_type, coupling_name, run_stat):
    coupling = next(
        row
        for row in snapshot["devices"]
        if row.get("model_block") == coupling_type
        and row.get("dev_name") == coupling_name
    )
    coupling["run_stat"] = run_stat
    coupling["raw"]["run_stat"] = run_stat
    model_row = next(
        row
        for row in snapshot["definitions"]["model"][coupling_type]["rows"]
        if row.get("name") == coupling_name
    )
    model_row["run_stat"] = run_stat
    return snapshot


def _run(
    snapshot,
    settings,
    *,
    diesel_power=83.0,
    storage_soc=0.1,
    storage_soc_min=0.2,
    apply_electrical_corrections=True,
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
    result = _optimize_hydrogen_within_topology_islands(
        snapshot,
        measurements,
        settings,
        topology,
        command_rows,
        storage_rows,
        diesel_current_kw=diesel_power,
        apply_electrical_corrections=apply_electrical_corrections,
    )
    return result, command_rows


def _run_electrolyzer(
    snapshot,
    settings,
    *,
    diesel_power=20.0,
    diesel_input_valid=True,
    storage_soc=0.9,
    diesel_unit_count=1,
):
    measurements = _measurement_index(snapshot)
    topology = resolve_resource_topology(snapshot, ())
    rows = []
    result = _optimize_hydrogen_within_topology_islands(
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
        diesel_unit_count=diesel_unit_count,
        diesel_input_valid=diesel_input_valid,
    )
    return result, rows


def test_hydrogen_settings_round_trip_with_independent_closed_loop_switch():
    settings = RenewableControlSettings()
    updated = settings.updated(
        {
            "hydrogenClosedLoopEnabled": True,
            "hydrogenPressureDeadbandRatio": 0.1,
            "electrolyzerPowerMinRatio": 0.05,
            "electrolyzerPowerMaxRatio": 0.45,
            "electrolyzerPowerDeadbandRatio": 0.01,
            "electrolyzerPowerStepRatio": 0.02,
            "electrolyzerDieselPowerLimitRatio": 0.32,
            "electrolyzerDieselPowerDeadbandRatio": 0.15,
            "electrolyzerStorageSocStartMinimum": 0.82,
            "electrolyzerStorageSocStopMaximum": 0.35,
            "electrolyzerHydrogenStorageSocStopMinimum": 0.88,
            "fuelCellPowerMinRatio": 0.03,
            "fuelCellPowerMaxRatio": 0.14,
            "fuelCellPowerDeadbandRatio": 0.005,
            "fuelCellPowerStepRatio": 0.015,
            "fuelCellDieselPowerLimitRatio": 0.36,
            "fuelCellStorageSocLimit": 0.38,
            "fuelCellHydrogenStorageSocUpperLimit": 0.75,
            "fuelCellHydrogenStorageSocLowerLimit": 0.25,
        }
    )
    assert updated.payload()["hydrogenClosedLoopEnabled"] is True
    assert updated.payload()["hydrogenPressureDeadbandRatio"] == 0.1
    assert updated.payload()["electrolyzerPowerMinRatio"] == 0.05
    assert updated.payload()["electrolyzerPowerMaxRatio"] == 0.45
    assert updated.payload()["electrolyzerPowerDeadbandRatio"] == 0.01
    assert updated.payload()["electrolyzerPowerStepRatio"] == 0.02
    assert updated.payload()["electrolyzerDieselPowerLimitRatio"] == 0.32
    assert updated.payload()["electrolyzerDieselPowerDeadbandRatio"] == 0.15
    assert updated.payload()["electrolyzerStorageSocStartMinimum"] == 0.82
    assert updated.payload()["electrolyzerStorageSocStopMaximum"] == 0.35
    assert updated.payload()["electrolyzerHydrogenStorageSocStopMinimum"] == 0.88
    assert updated.payload()["fuelCellPowerMinRatio"] == 0.03
    assert updated.payload()["fuelCellPowerMaxRatio"] == 0.14
    assert updated.payload()["fuelCellPowerDeadbandRatio"] == 0.005
    assert updated.payload()["fuelCellPowerStepRatio"] == 0.015
    assert updated.payload()["fuelCellDieselPowerLimitRatio"] == 0.36
    assert updated.payload()["fuelCellStorageSocLimit"] == 0.38
    assert updated.payload()["fuelCellHydrogenStorageSocUpperLimit"] == 0.75
    assert updated.payload()["fuelCellHydrogenStorageSocLowerLimit"] == 0.25
    json.dumps(updated.payload())


def test_electrolyzer_recommended_defaults():
    payload = RenewableControlSettings().payload()

    expected = {
        "electrolyzerPowerMinRatio": 0.20,
        "electrolyzerPowerMaxRatio": 0.90,
        "electrolyzerPowerDeadbandRatio": 0.10,
        "electrolyzerPowerStepRatio": 0.10,
        "electrolyzerDieselPowerLimitRatio": 0.35,
        "electrolyzerDieselPowerDeadbandRatio": 0.05,
        "electrolyzerStorageSocStartMinimum": 0.70,
        "electrolyzerStorageSocStopMaximum": 0.30,
        "electrolyzerHydrogenStorageSocStopMinimum": 0.90,
    }
    for key, value in expected.items():
        assert payload[key] == pytest.approx(value)


def test_hydrogen_power_settings_normalize_invalid_ranges():
    settings = RenewableControlSettings().updated(
        {
            "electrolyzerPowerMinRatio": -1,
            "electrolyzerPowerMaxRatio": -2,
            "electrolyzerPowerDeadbandRatio": -3,
            "electrolyzerPowerStepRatio": 0,
            "fuelCellPowerMinRatio": 0.8,
            "fuelCellPowerMaxRatio": 0.4,
            "fuelCellPowerDeadbandRatio": 1,
            "fuelCellPowerStepRatio": -2,
            "electrolyzerDieselPowerLimitRatio": -10,
            "electrolyzerDieselPowerDeadbandRatio": -2,
            "electrolyzerStorageSocStartMinimum": -0.2,
            "electrolyzerStorageSocStopMaximum": 1.9,
            "electrolyzerHydrogenStorageSocStopMinimum": 2,
            "fuelCellDieselPowerLimitRatio": -20,
            "fuelCellStorageSocLimit": -1,
            "fuelCellHydrogenStorageSocUpperLimit": 0.1,
            "fuelCellHydrogenStorageSocLowerLimit": 0.8,
        }
    )

    assert settings.electrolyzer_power_min_ratio == 0
    assert settings.electrolyzer_power_max_ratio == 0
    assert settings.electrolyzer_power_deadband_ratio == 0
    assert settings.electrolyzer_power_step_ratio > 0
    assert settings.fuel_cell_power_min_ratio == 0.8
    assert settings.fuel_cell_power_max_ratio == 0.8
    assert settings.fuel_cell_power_deadband_ratio == 0
    assert settings.fuel_cell_power_step_ratio > 0
    assert settings.electrolyzer_diesel_power_limit_ratio == 0
    assert settings.electrolyzer_diesel_power_deadband_ratio == 0
    assert settings.electrolyzer_storage_soc_start_minimum == 0
    assert settings.electrolyzer_storage_soc_stop_maximum == 1
    assert settings.electrolyzer_hydrogen_storage_soc_stop_minimum == 1
    assert settings.fuel_cell_diesel_power_limit_ratio == 0
    assert settings.fuel_cell_storage_soc_limit == 0
    assert settings.fuel_cell_hydrogen_storage_soc_lower_limit == 0.8
    assert settings.fuel_cell_hydrogen_storage_soc_upper_limit == 0.8


def test_legacy_electrolyzer_soc_threshold_names_migrate_by_control_semantics():
    settings = RenewableControlSettings().updated(
        {
            "electrolyzerStorageSocUpperLimit": 0.6,
            "electrolyzerStorageSocLowerLimit": 0.4,
            "electrolyzerHydrogenStorageSocUpperLimit": 0.85,
        }
    )

    assert settings.electrolyzer_storage_soc_start_minimum == 0.6
    assert settings.electrolyzer_storage_soc_stop_maximum == 0.4
    assert settings.electrolyzer_hydrogen_storage_soc_stop_minimum == 0.85
    assert settings.payload()["electrolyzerStorageSocStartMinimum"] == 0.6
    assert settings.payload()["electrolyzerStorageSocStopMaximum"] == 0.4

    constructed = RenewableControlSettings(
        electrolyzer_storage_soc_upper_limit=0.65,
        electrolyzer_storage_soc_lower_limit=0.35,
        electrolyzer_hydrogen_storage_soc_upper_limit=0.88,
    ).normalized()
    assert constructed.electrolyzer_storage_soc_start_minimum == 0.65
    assert constructed.electrolyzer_storage_soc_stop_maximum == 0.35
    assert constructed.electrolyzer_hydrogen_storage_soc_stop_minimum == 0.88


def test_electrolyzer_soc_start_and_stop_thresholds_allow_hysteresis_order():
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=6.0,
        electrolyzer_diesel_power_limit_kw=40.0,
        electrolyzer_diesel_power_deadband_kw=10.0,
        electrolyzer_diesel_power_stop_maximum_ratio=0.5,
        electrolyzer_storage_soc_start_minimum=0.6,
        electrolyzer_storage_soc_stop_maximum=0.4,
        electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
    )
    started, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=0.0, tank_soc=0.89),
        settings,
        diesel_power=39.0,
        storage_soc=0.61,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert started["action"] == "electrolyzer"
    assert command["commandKw"] == 6.0

    held, held_rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=4.0, tank_soc=0.89),
        settings,
        diesel_power=45.0,
        storage_soc=0.59,
    )
    assert held["action"] == "hold"
    assert not any(row.get("commandKind") == "run_status" for row in held_rows)
    assert next(
        row for row in held_rows if row.get("dev_name") == "electrolyzer-load"
    )["commandKw"] == pytest.approx(4.0)


@pytest.mark.parametrize(
    ("storage_soc", "tank_soc"),
    (
        (0.39, 0.5),
        (0.8, 0.91),
    ),
)
def test_running_electrolyzer_reduces_when_a_soc_stop_condition_is_true(
    storage_soc,
    tank_soc,
):
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=2.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_step_kw=2.0,
        electrolyzer_diesel_power_limit_kw=100.0,
        electrolyzer_diesel_power_deadband_kw=10.0,
        electrolyzer_storage_soc_stop_maximum=0.4,
        electrolyzer_storage_soc_start_minimum=0.8,
        electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=8.0, tank_soc=tank_soc),
        settings,
        diesel_power=100.0,
        storage_soc=storage_soc,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["action"] == "electrolyzer_reduce"
    assert command["commandKw"] == pytest.approx(6.0)


def test_running_electrolyzer_reduces_for_high_diesel_power():
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=2.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_step_kw=2.0,
        electrolyzer_diesel_power_limit_kw=40.0,
        electrolyzer_diesel_power_deadband_kw=10.0,
        electrolyzer_diesel_power_stop_maximum_ratio=0.5,
        electrolyzer_storage_soc_stop_maximum=0.4,
        electrolyzer_storage_soc_start_minimum=0.8,
        electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
    )

    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=8.0, tank_soc=0.5),
        settings,
        diesel_power=60.0,
        storage_soc=0.8,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["action"] == "electrolyzer_reduce"
    assert result["electricPowerAdjustmentKw"] == pytest.approx(-2.0)
    assert command["commandKw"] == pytest.approx(6.0)
    assert (
        result["commands"][0]["controlReason"]
        == "diesel_power_above_stop_threshold"
    )
    assert "diesel_above_stop_threshold" not in result["commands"][0]["controlReason"]


def test_electrolyzer_holds_inside_configured_hysteresis_region():
    settings = RenewableControlSettings(
        electrolyzer_diesel_power_limit_kw=40.0,
        electrolyzer_diesel_power_deadband_kw=10.0,
        electrolyzer_diesel_power_stop_maximum_ratio=0.5,
        electrolyzer_storage_soc_stop_maximum=0.4,
        electrolyzer_storage_soc_start_minimum=0.8,
        electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=8.0, tank_soc=0.9),
        settings,
        diesel_power=45.0,
        storage_soc=0.6,
    )

    assert result["action"] == "hold"
    assert not any(row.get("commandKind") == "run_status" for row in rows)
    assert next(
        row for row in rows if row.get("dev_name") == "electrolyzer-load"
    )["commandKw"] == pytest.approx(8.0)


def test_electrolyzer_uses_average_diesel_power_and_average_electric_storage_soc():
    settings = RenewableControlSettings(
        electrolyzer_power_step_kw=2.0,
        electrolyzer_diesel_power_limit_kw=100.0,
        electrolyzer_diesel_power_deadband_kw=10.0,
        electrolyzer_storage_soc_stop_maximum=0.4,
        electrolyzer_storage_soc_start_minimum=0.8,
        electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
    )
    snapshot = _electrolyzer_snapshot(electric_power=4.0, tank_soc=0.5)
    measurements = _measurement_index(snapshot)
    topology = resolve_resource_topology(snapshot, ())
    rows = []
    result = _optimize_hydrogen_within_topology_islands(
        snapshot,
        measurements,
        settings,
        topology,
        rows,
        [
            {"online": True, "socKnown": True, "soc": 0.7, "socMin": 0.2},
            {"online": True, "socKnown": True, "soc": 0.95, "socMin": 0.2},
        ],
        diesel_current_kw=190.0,
        diesel_unit_count=2,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["action"] == "electrolyzer"
    assert result["electricPowerAdjustmentKw"] == 2.0
    assert result["dieselUnitCount"] == 2
    assert result["predictedDieselAverageBeforeKw"] == 95.0
    assert result["electricStorageSocAverage"] == pytest.approx(0.825)
    assert result["commands"][0]["hydrogenStorageSocAverage"] == 0.5
    assert command["commandKw"] == 6.0


def test_electrolyzer_fails_closed_on_partial_electric_storage_soc_average():
    snapshot = _electrolyzer_snapshot(electric_power=4.0, tank_soc=0.5)
    measurements = _measurement_index(snapshot)
    topology = resolve_resource_topology(snapshot, ())
    rows = []
    result = _optimize_hydrogen_within_topology_islands(
        snapshot,
        measurements,
        RenewableControlSettings(
            electrolyzer_diesel_power_limit_kw=100.0,
            electrolyzer_storage_soc_start_minimum=0.8,
            electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
        ),
        topology,
        rows,
        [
            {"online": True, "socKnown": True, "soc": 0.9, "socMin": 0.2},
            {"online": True, "socKnown": False, "soc": None, "socMin": 0.2},
        ],
        diesel_current_kw=90.0,
    )

    assert result["action"] == "blocked"
    assert rows == []
    assert any("平均SOC" in warning and "fail closed" in warning for warning in result["warnings"])


def test_fuel_cell_uses_diesel_electric_soc_and_hydrogen_soc_hysteresis():
    settings = RenewableControlSettings(
        fuel_cell_power_min_kw=5.0,
        fuel_cell_power_max_kw=20.0,
        fuel_cell_power_deadband_kw=1.0,
        fuel_cell_power_step_kw=6.0,
        fuel_cell_diesel_power_limit_kw=100.0,
        fuel_cell_storage_soc_limit=0.4,
        fuel_cell_hydrogen_storage_soc_upper_limit=0.8,
        fuel_cell_hydrogen_storage_soc_lower_limit=0.2,
    )
    result, rows = _run(
        _fuel_cell_snapshot(tank_soc=0.81),
        settings,
        diesel_power=111.0,
        storage_soc=0.39,
    )

    command = next(row for row in rows if row.get("dev_name") == "fuel-cell")
    assert result["action"] == "fuel_cell"
    assert command["commandKw"] == 11.0

    running_snapshot = _fuel_cell_snapshot(tank_soc=0.3)
    running_snapshot["measurements"]["scada"] = [
        row
        for row in running_snapshot["measurements"]["scada"]
        if not (row["dev_type"] == "DCGenerator" and row["dev_name"] == "fuel-cell")
    ]
    running_snapshot["measurements"]["scada"].append(
        _measurement("DCGenerator", "fuel-cell", "P_GEN", 6.0)
    )
    increased, increased_rows = _run(
        running_snapshot,
        settings,
        diesel_power=110.0,
        storage_soc=0.39,
    )
    increased_command = next(
        row for row in increased_rows if row.get("dev_name") == "fuel-cell"
    )
    assert increased["action"] == "fuel_cell"
    assert increased_command["commandKw"] == 12.0


def test_fuel_cell_integration_uses_complete_diesel_and_soc_averages():
    snapshot = _fuel_cell_snapshot(tank_soc=0.7)
    tank_template = snapshot["definitions"]["model"]["HydroStorage"]["rows"][0]
    second_tank = dict(tank_template, idx=2, name="tank-2")
    snapshot["definitions"]["model"]["HydroStorage"]["rows"].append(second_tank)
    snapshot["devices"].append(
        {
            "dev_type": "HydroStorage",
            "model_block": "HydroStorage",
            "dev_name": "tank-2",
            "run_stat": 1,
            "status": 1,
            "set_types": [],
            "set_values": {},
            "raw": dict(second_tank),
        }
    )
    snapshot["measurements"]["scada"].extend(
        [
            _measurement("HydroStorage", "tank-2", "PRESSURE", 20.0),
            _measurement("HydroStorage", "tank-2", "SOC", 0.95),
        ]
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
    result = _optimize_hydrogen_within_topology_islands(
        snapshot,
        measurements,
        RenewableControlSettings(
            fuel_cell_power_min_kw=5.0,
            fuel_cell_power_max_kw=20.0,
            fuel_cell_power_deadband_kw=1.0,
            fuel_cell_power_step_kw=6.0,
            fuel_cell_diesel_power_limit_kw=100.0,
            fuel_cell_storage_soc_limit=0.4,
            fuel_cell_hydrogen_storage_soc_upper_limit=0.8,
            fuel_cell_hydrogen_storage_soc_lower_limit=0.2,
        ),
        topology,
        rows,
        [
            {"online": True, "socKnown": True, "soc": 0.1, "socMin": 0.2},
            {"online": True, "socKnown": True, "soc": 0.65, "socMin": 0.2},
        ],
        diesel_current_kw=211.0,
        diesel_unit_count=2,
    )

    fuel_command = next(row for row in rows if row.get("dev_name") == "fuel-cell")
    assert result["action"] == "fuel_cell"
    assert result["predictedDieselAverageBeforeKw"] == 105.5
    assert result["electricStorageSocAverage"] == pytest.approx(0.375)
    assert result["commands"][0]["hydrogenStorageSocAverage"] == pytest.approx(0.825)
    assert result["commands"][0]["controlReason"] == "start_conditions_met"
    assert fuel_command["commandKw"] == 11.0


def test_fuel_cell_integration_fails_closed_on_partial_island_soc_average():
    snapshot = _fuel_cell_snapshot(tank_soc=0.9)
    tank_template = snapshot["definitions"]["model"]["HydroStorage"]["rows"][0]
    second_tank = dict(tank_template, idx=2, name="tank-2")
    snapshot["definitions"]["model"]["HydroStorage"]["rows"].append(second_tank)
    snapshot["devices"].append(
        {
            "dev_type": "HydroStorage",
            "model_block": "HydroStorage",
            "dev_name": "tank-2",
            "run_stat": 1,
            "status": 1,
            "set_types": [],
            "set_values": {},
            "raw": dict(second_tank),
        }
    )
    snapshot["measurements"]["scada"].append(
        _measurement("HydroStorage", "tank-2", "PRESSURE", 20.0)
    )
    result, rows = _run(
        snapshot,
        RenewableControlSettings(
            fuel_cell_diesel_power_limit_kw=80.0,
            fuel_cell_storage_soc_limit=0.4,
            fuel_cell_hydrogen_storage_soc_upper_limit=0.8,
        ),
        diesel_power=90.0,
        storage_soc=0.1,
    )

    assert result["action"] == "blocked"
    assert not any(row.get("dev_name") == "fuel-cell" for row in rows)
    assert any("本氢岛氢储平均SOC" in warning for warning in result["warnings"])


def _integrated_fuel_cell_snapshot():
    snapshot = _fuel_cell_snapshot(tank_soc=0.9)
    _set_coupling_run_state(snapshot, "Hydro2DcE", "fuel-coupling", 0)
    model = snapshot["definitions"]["model"]
    diesel = {
        "idx": 1,
        "name": "diesel",
        "node": 1,
        "control_type": "PH",
        "p_min": 20,
        "p_max": 200,
        "run_stat": 1,
    }
    storage = {
        "idx": 2,
        "name": "storage",
        "node": 1,
        "control_type": "V",
        "p_min": -40,
        "p_max": 40,
        "run_stat": 1,
    }
    model["ACGenerator"] = _block([diesel])
    model["DCGenerator"]["rows"].append(storage)
    for dev_type, row in (("ACGenerator", diesel), ("DCGenerator", storage)):
        snapshot["devices"].append(
            {
                "dev_type": dev_type,
                "model_block": dev_type,
                "dev_name": row["name"],
                "idx": row["idx"],
                "run_stat": 1,
                "status": 1,
                "set_types": ["p_set"],
                "set_values": {},
                "raw": dict(row),
            }
        )
    snapshot["device_parameters"] = {
        "ACDieselGen": [
            {
                "idx": 1,
                "idx_acgenerator": 1,
                "rated_power": 200,
                "p_min": 20,
                "p_max": 200,
            }
        ],
        "DCStorageGen": [
            {
                "idx": 1,
                "idx_dcgenerator": 2,
                "energy_capacity": 100,
                "max_charge_power": 40,
                "max_discharge_power": 40,
                "soc_lower_limit": 0.2,
                "soc_upper_limit": 0.9,
            }
        ],
    }
    snapshot["measurements"]["scada"].extend(
        [
            _measurement("ACGenerator", "diesel", "P_GEN", 105.0),
            _measurement("DCGenerator", "storage", "P_GEN", 0.0),
            _measurement("DCGenerator", "storage", "SOC", 0.3),
            _measurement("DCACConverter", "grid-converter", "P_AC", 0.0),
        ]
    )
    snapshot["definitions"]["control"]["SetValue"]["rows"].extend(
        [
            {"dev_type": "ACGenerator", "dev_name": "diesel", "set_type": "p_set"},
            {"dev_type": "DCGenerator", "dev_name": "storage", "set_type": "p_set"},
            {
                "dev_type": "DCACConverter",
                "dev_name": "grid-converter",
                "set_type": "p_ac_set",
            },
        ]
    )
    return snapshot


def _integrated_fuel_cell_settings(*, hydrogen_closed_loop_enabled=False):
    return RenewableControlSettings(
        hydrogen_closed_loop_enabled=hydrogen_closed_loop_enabled,
        fuel_cell_power_min_kw=5.0,
        fuel_cell_power_max_kw=20.0,
        fuel_cell_power_deadband_kw=1.0,
        fuel_cell_power_step_kw=6.0,
        fuel_cell_diesel_power_limit_kw=70.0,
        fuel_cell_storage_soc_limit=0.4,
        fuel_cell_hydrogen_storage_soc_upper_limit=0.8,
        fuel_cell_hydrogen_storage_soc_lower_limit=0.2,
    )


def test_full_renewable_plan_previews_open_hydrogen_and_dispatches_closed_hydrogen_atomically():
    snapshot = _integrated_fuel_cell_snapshot()

    open_plan = calculate_renewable_control_plan(
        snapshot,
        _integrated_fuel_cell_settings(),
    )
    open_commands = {
        (row["dev_type"], row["dev_name"], row["set_type"]): row["set_value"]
        for row in open_plan["commands"]
    }
    open_hydrogen = open_plan["metrics"]["hydrogenControl"]
    open_hydrogen_row = next(
        row for row in open_plan["commandRows"] if row.get("dev_name") == "fuel-cell"
    )
    assert open_plan["dataQuality"]["dispatchAllowed"] is True
    assert open_hydrogen["action"] == "fuel_cell"
    assert open_hydrogen["dispatchMode"] == "open-loop-preview"
    assert open_hydrogen["commands"][0]["controlReason"] == "start_conditions_met"
    assert open_plan["metrics"]["fuelCellTargetKw"] == pytest.approx(11.0)
    assert open_hydrogen_row["commandKw"] == pytest.approx(11.0)
    assert open_hydrogen_row["dispatchEnabled"] is False
    open_run_row = next(
        row
        for row in open_plan["commandRows"]
        if row.get("commandKind") == "run_status"
        and row.get("dev_name") == "fuel-coupling"
    )
    assert open_run_row["run_stat"] == 1
    assert open_run_row["dispatchEnabled"] is False
    assert open_plan["runCommands"] == []
    assert ("DCGenerator", "fuel-cell", "p_set") not in open_commands
    assert open_commands[("DCACConverter", "grid-converter", "p_ac_set")] == -20.0
    assert open_commands[("ACGenerator", "diesel", "p_set")] == 85.0
    assert open_hydrogen["converterCorrectionKw"] == pytest.approx(0.0)
    assert open_hydrogen["balanceCorrectionKw"] == pytest.approx(0.0)

    closed_plan = calculate_renewable_control_plan(
        snapshot,
        _integrated_fuel_cell_settings(hydrogen_closed_loop_enabled=True),
    )
    closed_commands = {
        (row["dev_type"], row["dev_name"], row["set_type"]): row["set_value"]
        for row in closed_plan["commands"]
    }
    closed_hydrogen = closed_plan["metrics"]["hydrogenControl"]
    assert closed_hydrogen["dispatchMode"] == "closed-loop-atomic"
    assert closed_hydrogen["optimizationScope"] == "topology-island"
    assert closed_hydrogen["coordinationSequence"] == [
        "renewable-diesel-storage",
        "hydrogen",
        "acdc-final",
    ]
    assert closed_hydrogen["acdcCoordinationStage"] == "final"
    assert closed_hydrogen["topologyIslandPlans"]
    assert closed_hydrogen["topologyIslandPlans"][0]["hydrogenCommands"]
    assert closed_plan["runCommands"] == [
        {
            "dev_type": "Hydro2DcE",
            "dev_name": "fuel-coupling",
            "run_stat": 1,
        }
    ]
    assert closed_commands[("DCGenerator", "fuel-cell", "p_set")] == 11.0
    assert closed_commands[("DCACConverter", "grid-converter", "p_ac_set")] == -31.0
    assert closed_commands[("ACGenerator", "diesel", "p_set")] == 74.0
    assert closed_hydrogen["converterCorrectionKw"] == pytest.approx(11.0)
    assert closed_hydrogen["balanceCorrectionKw"] == pytest.approx(-11.0)


def test_fuel_cell_dcac_command_row_uses_the_same_active_dc_transfer_group():
    plan = calculate_renewable_control_plan(
        _integrated_fuel_cell_snapshot(),
        _integrated_fuel_cell_settings(hydrogen_closed_loop_enabled=True),
    )

    converter = next(
        row
        for row in plan["commandRows"]
        if row.get("model_block") == "DCACConverter"
        and row.get("dev_name") == "grid-converter"
    )
    hydrogen = plan["metrics"]["hydrogenControl"]

    assert converter["online"] is True
    assert converter["commandable"] is True
    assert converter["dcTransferGroupId"]
    assert hydrogen["action"] == "fuel_cell"
    assert not any("无可调" in warning for warning in hydrogen["warnings"])


def test_fuel_cell_reports_invalid_dcac_bus_anchor_instead_of_missing_converter():
    snapshot = _integrated_fuel_cell_snapshot()
    snapshot["definitions"]["model"]["ACRealBs"]["rows"][0].pop("node")

    plan = calculate_renewable_control_plan(
        snapshot,
        _integrated_fuel_cell_settings(hydrogen_closed_loop_enabled=True),
    )
    hydrogen = plan["metrics"]["hydrogenControl"]

    assert hydrogen["action"] == "blocked"
    assert any(
        "已配置DCAC" in warning and "未同时接入有效真实母线" in warning
        for warning in hydrogen["warnings"]
    )
    assert not any("无可调" in warning for warning in hydrogen["warnings"])


def test_fuel_cell_reports_the_dcac_runtime_condition_when_control_is_unavailable():
    snapshot = _integrated_fuel_cell_snapshot()
    snapshot["measurements"]["scada"] = [
        row
        for row in snapshot["measurements"]["scada"]
        if not (
            row["dev_type"] == "DCACConverter"
            and row["dev_name"] == "grid-converter"
        )
    ]

    plan = calculate_renewable_control_plan(
        snapshot,
        _integrated_fuel_cell_settings(hydrogen_closed_loop_enabled=True),
    )
    warnings = plan["metrics"]["hydrogenControl"]["warnings"]

    assert any(
        "DCAC当前不可调" in warning and "缺少有效实时有功" in warning
        for warning in warnings
    )


def test_fuel_cell_only_reports_unconfigured_dcac_when_the_group_has_none():
    snapshot = _integrated_fuel_cell_snapshot()
    snapshot["definitions"]["model"].pop("DCACConverter")
    snapshot["devices"] = [
        row
        for row in snapshot["devices"]
        if row.get("model_block") != "DCACConverter"
    ]
    snapshot["measurements"]["scada"] = [
        row
        for row in snapshot["measurements"]["scada"]
        if row["dev_type"] != "DCACConverter"
    ]
    snapshot["definitions"]["control"]["SetValue"]["rows"] = [
        row
        for row in snapshot["definitions"]["control"]["SetValue"]["rows"]
        if row["dev_type"] != "DCACConverter"
    ]

    plan = calculate_renewable_control_plan(
        snapshot,
        _integrated_fuel_cell_settings(hydrogen_closed_loop_enabled=True),
    )
    warnings = plan["metrics"]["hydrogenControl"]["warnings"]

    assert any("直流拓扑组未配置DCAC" in warning for warning in warnings)


def test_electrolyzer_start_adds_run_command_before_power_setpoint():
    snapshot = _set_coupling_run_state(
        _electrolyzer_snapshot(electric_power=0.0),
        "AcE2Hydro",
        "electrolyzer-coupling",
        0,
    )
    result, rows = _run_electrolyzer(
        snapshot,
        RenewableControlSettings(
            electrolyzer_power_min_kw=2.0,
            electrolyzer_power_max_kw=20.0,
            electrolyzer_power_deadband_kw=1.0,
            electrolyzer_power_step_kw=6.0,
            electrolyzer_diesel_power_limit_kw=100.0,
            electrolyzer_storage_soc_start_minimum=0.8,
            electrolyzer_storage_soc_stop_maximum=0.2,
            electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
        ),
        diesel_power=20.0,
        storage_soc=0.9,
    )

    run_row = next(row for row in rows if row.get("commandKind") == "run_status")
    set_row = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["commands"][0]["controlReason"] == "entry_conditions_met_direct_start"
    assert run_row["dev_type"] == "AcE2Hydro"
    assert run_row["dev_name"] == "electrolyzer-coupling"
    assert run_row["run_stat"] == 1
    assert rows.index(run_row) < rows.index(set_row)
    assert set_row["commandKw"] == pytest.approx(3.0)


def test_fuel_cell_start_adds_run_command_before_power_setpoint():
    snapshot = _set_coupling_run_state(
        _fuel_cell_snapshot(tank_soc=0.9),
        "Hydro2DcE",
        "fuel-coupling",
        0,
    )
    result, rows = _run(
        snapshot,
        RenewableControlSettings(
            fuel_cell_power_min_kw=5.0,
            fuel_cell_power_max_kw=20.0,
            fuel_cell_power_deadband_kw=1.0,
            fuel_cell_power_step_kw=6.0,
            fuel_cell_diesel_power_limit_kw=70.0,
            fuel_cell_storage_soc_limit=0.4,
            fuel_cell_hydrogen_storage_soc_upper_limit=0.8,
            fuel_cell_hydrogen_storage_soc_lower_limit=0.2,
        ),
        diesel_power=83.0,
        storage_soc=0.1,
    )

    run_row = next(row for row in rows if row.get("commandKind") == "run_status")
    set_row = next(row for row in rows if row.get("dev_name") == "fuel-cell")
    assert result["commands"][0]["controlReason"] == "start_conditions_met"
    assert run_row["dev_type"] == "Hydro2DcE"
    assert run_row["dev_name"] == "fuel-coupling"
    assert run_row["run_stat"] == 1
    assert rows.index(run_row) < rows.index(set_row)
    assert set_row["commandKw"] == pytest.approx(11.0)


@pytest.mark.parametrize(
    ("mode", "expected_type", "expected_name", "setpoint_name"),
    (
        ("electrolyzer", "AcE2Hydro", "electrolyzer-coupling", "electrolyzer-load"),
        ("fuel_cell", "Hydro2DcE", "fuel-coupling", "fuel-cell"),
    ),
)
def test_hydrogen_stop_adds_stop_remote_control_and_zero_setpoint(
    mode,
    expected_type,
    expected_name,
    setpoint_name,
):
    if mode == "electrolyzer":
        snapshot = _electrolyzer_snapshot(electric_power=4.0)
        result, rows = _run_electrolyzer(
            snapshot,
            RenewableControlSettings(
                electrolyzer_power_min_kw=2.0,
                electrolyzer_power_max_kw=20.0,
                electrolyzer_power_deadband_kw=1.0,
                electrolyzer_power_step_kw=10.0,
                electrolyzer_diesel_power_limit_kw=100.0,
                electrolyzer_storage_soc_start_minimum=0.8,
                electrolyzer_storage_soc_stop_maximum=0.3,
                electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
            ),
            diesel_power=120.0,
            storage_soc=0.1,
        )
    else:
        snapshot = _fuel_cell_snapshot(tank_pressure=1.0, tank_soc=0.9)
        snapshot["measurements"]["scada"] = [
            row
            for row in snapshot["measurements"]["scada"]
            if not (row["dev_type"] == "DCGenerator" and row["dev_name"] == "fuel-cell")
        ]
        snapshot["measurements"]["scada"].append(
            _measurement("DCGenerator", "fuel-cell", "P_GEN", 8.0)
        )
        result, rows = _run(
            snapshot,
            RenewableControlSettings(
                hydrogen_pressure_deadband_ratio=0.1,
                fuel_cell_power_min_kw=2.0,
                fuel_cell_power_max_kw=20.0,
                fuel_cell_power_step_kw=10.0,
                fuel_cell_diesel_power_limit_kw=70.0,
                fuel_cell_storage_soc_limit=0.4,
                fuel_cell_hydrogen_storage_soc_upper_limit=0.8,
                fuel_cell_hydrogen_storage_soc_lower_limit=0.2,
            ),
            diesel_power=83.0,
            storage_soc=0.1,
        )

    run_row = next(row for row in rows if row.get("commandKind") == "run_status")
    set_row = next(row for row in rows if row.get("dev_name") == setpoint_name)
    assert result["commands"]
    assert run_row["dev_type"] == expected_type
    assert run_row["dev_name"] == expected_name
    assert run_row["run_stat"] == 0
    assert set_row["commandKw"] == 0.0


def test_strategy_stopped_electrolyzer_can_restart_from_explicit_run_control():
    snapshot = _electrolyzer_snapshot(electric_power=0.0)
    coupling = next(
        row
        for row in snapshot["devices"]
        if row.get("model_block") == "AcE2Hydro"
    )
    coupling["run_stat"] = 0
    coupling["raw"]["run_stat"] = 0
    snapshot["definitions"]["model"]["AcE2Hydro"]["rows"][0]["run_stat"] = 0

    result, rows = _run_electrolyzer(
        snapshot,
        RenewableControlSettings(
            electrolyzer_power_min_kw=2.0,
            electrolyzer_power_max_kw=20.0,
            electrolyzer_power_deadband_kw=1.0,
            electrolyzer_power_step_kw=6.0,
            electrolyzer_diesel_power_limit_kw=100.0,
            electrolyzer_storage_soc_start_minimum=0.8,
            electrolyzer_storage_soc_stop_maximum=0.2,
            electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
        ),
        diesel_power=20.0,
        storage_soc=0.9,
    )

    assert result["commands"]
    assert next(row for row in rows if row.get("commandKind") == "run_status")["run_stat"] == 1
    assert next(row for row in rows if row.get("dev_name") == "electrolyzer-load")["commandKw"] == pytest.approx(3.0)


def test_strategy_stopped_hydrogen_device_keeps_zero_without_repeating_stop_remote_control():
    snapshot = _electrolyzer_snapshot(electric_power=0.0)
    coupling = next(
        row
        for row in snapshot["devices"]
        if row.get("model_block") == "AcE2Hydro"
    )
    coupling["run_stat"] = 0
    coupling["raw"]["run_stat"] = 0
    snapshot["definitions"]["model"]["AcE2Hydro"]["rows"][0]["run_stat"] = 0

    _result, rows = _run_electrolyzer(
        snapshot,
        RenewableControlSettings(
            electrolyzer_power_min_kw=2.0,
            electrolyzer_power_max_kw=20.0,
            electrolyzer_power_deadband_kw=1.0,
            electrolyzer_power_step_kw=6.0,
            electrolyzer_diesel_power_limit_kw=100.0,
            electrolyzer_storage_soc_start_minimum=0.8,
            electrolyzer_storage_soc_stop_maximum=0.2,
            electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
        ),
        diesel_power=120.0,
        storage_soc=0.1,
    )

    assert not any(row.get("commandKind") == "run_status" for row in rows)
    assert next(row for row in rows if row.get("dev_name") == "electrolyzer-load")["commandKw"] == 0.0


def test_qinling_hydrogen_couplings_have_explicit_run_controls_and_active_setpoints():
    model_dir = Path(__file__).resolve().parents[1] / "models" / "simulator" / "source" / "秦岭站2"
    model_book = simu_loop.EBook(str(model_dir / "model.e"))
    control_book = simu_loop.EBook(str(model_dir / "control.e"))
    run_keys = {
        (str(row.get("dev_type", "")), str(row.get("dev_name", "")))
        for row in control_book.data["RunStat"].data
    }
    set_keys = {
        (
            str(row.get("dev_type", "")),
            str(row.get("dev_name", "")),
            str(row.get("set_type", "")),
        )
        for row in control_book.data["SetValue"].data
    }
    bindings = energy_coupling_control_bindings(model_book)

    for coupling_key in (
        ("AcE2Hydro", "交流电制氢-1"),
        ("Hydro2DcE", "直流燃料电池-1"),
    ):
        assert coupling_key in run_keys
        active_binding = next(row for row in bindings[coupling_key] if row["active"])
        assert (
            active_binding["target_dev_type"],
            active_binding["target_dev_name"],
            active_binding["target_set_type"],
        ) in set_keys


@pytest.mark.parametrize(
    ("diesel_power", "storage_soc", "tank_soc"),
    (
        (29.0, 0.39, 0.5),
        (110.0, 0.41, 0.5),
        (110.0, 0.39, 0.19),
    ),
)
def test_running_fuel_cell_reduces_when_any_configured_stop_condition_is_true(
    diesel_power,
    storage_soc,
    tank_soc,
):
    snapshot = _fuel_cell_snapshot(tank_soc=tank_soc)
    snapshot["measurements"]["scada"] = [
        row
        for row in snapshot["measurements"]["scada"]
        if not (row["dev_type"] == "DCGenerator" and row["dev_name"] == "fuel-cell")
    ]
    snapshot["measurements"]["scada"].append(
        _measurement("DCGenerator", "fuel-cell", "P_GEN", 8.0)
    )
    settings = RenewableControlSettings(
        fuel_cell_power_min_kw=2.0,
        fuel_cell_power_max_kw=20.0,
        fuel_cell_power_step_kw=2.0,
        fuel_cell_diesel_power_limit_kw=100.0,
        fuel_cell_storage_soc_limit=0.4,
        fuel_cell_hydrogen_storage_soc_upper_limit=0.8,
        fuel_cell_hydrogen_storage_soc_lower_limit=0.2,
    )
    result, rows = _run(
        snapshot,
        settings,
        diesel_power=diesel_power,
        storage_soc=storage_soc,
    )

    command = next(row for row in rows if row.get("dev_name") == "fuel-cell")
    assert result["action"] == "fuel_cell_reduce"
    assert command["commandKw"] == 6.0


def test_electrolyzer_and_fuel_cell_cannot_start_in_the_same_cycle():
    snapshot = _electrolyzer_snapshot(tank_soc=0.5, electric_power=0.0)
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
            "commandKw": 0.0,
            "signedMinTargetKw": -50.0,
            "signedMaxTargetKw": 50.0,
            "transferCapacityKw": 50.0,
            "dcTransferGroupId": group_id,
        },
        {
            "category": "柴油发电",
            "dev_type": "ACGenerator",
            "model_block": "ACGenerator",
            "dev_name": "diesel",
            "online": True,
            "commandable": True,
            "strategyCommand": True,
            "set_type": "p_set",
            "currentKw": 80.0,
            "commandKw": 80.0,
            "minKw": 20.0,
            "capacityKw": 200.0,
        },
    ]
    result = _optimize_hydrogen_within_topology_islands(
        snapshot,
        measurements,
        RenewableControlSettings(
            electrolyzer_power_min_kw=2.0,
            electrolyzer_power_max_kw=20.0,
            electrolyzer_power_step_kw=6.0,
            electrolyzer_diesel_power_limit_kw=100.0,
            electrolyzer_storage_soc_stop_maximum=0.2,
            electrolyzer_storage_soc_start_minimum=0.8,
            electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
            fuel_cell_power_min_kw=5.0,
            fuel_cell_power_max_kw=20.0,
            fuel_cell_power_step_kw=6.0,
            fuel_cell_diesel_power_limit_kw=70.0,
            fuel_cell_storage_soc_limit=0.9,
            fuel_cell_hydrogen_storage_soc_upper_limit=0.4,
            fuel_cell_hydrogen_storage_soc_lower_limit=0.2,
        ),
        topology,
        rows,
        [{"online": True, "socKnown": True, "soc": 0.85, "socMin": 0.2}],
        diesel_current_kw=80.0,
    )

    assert [row["couplingType"] for row in result["commands"]] == ["AcE2Hydro"]
    assert result["interlockMode"] == "electrolyzer"
    assert result["interlockActive"] is True
    assert any("互锁" in warning for warning in result["warnings"])
    assert not any(row.get("dev_name") == "fuel-cell" for row in rows)


def test_running_fuel_cell_blocks_electrolyzer_start():
    snapshot = _electrolyzer_snapshot(tank_soc=0.5, electric_power=0.0)
    snapshot["measurements"]["scada"] = [
        row
        for row in snapshot["measurements"]["scada"]
        if not (
            row["dev_type"] == "DCGenerator"
            and row["dev_name"] == "fuel-cell"
            and row["meas_type"] == "P_GEN"
        )
    ]
    snapshot["measurements"]["scada"].append(
        _measurement("DCGenerator", "fuel-cell", "P_GEN", 5.0)
    )
    result, rows = _run_electrolyzer(
        snapshot,
        RenewableControlSettings(
            electrolyzer_power_min_kw=2.0,
            electrolyzer_power_max_kw=20.0,
            electrolyzer_power_step_kw=6.0,
            electrolyzer_diesel_power_limit_kw=100.0,
            electrolyzer_storage_soc_stop_maximum=0.2,
            electrolyzer_storage_soc_start_minimum=0.8,
            electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
            fuel_cell_diesel_power_limit_kw=200.0,
            fuel_cell_storage_soc_limit=0.1,
        ),
        diesel_power=80.0,
        storage_soc=0.85,
    )

    assert result["interlockMode"] == "fuel_cell"
    assert result["interlockActive"] is True
    assert any("互锁" in warning for warning in result["warnings"])
    assert not any(row.get("dev_name") == "electrolyzer-load" for row in rows)


def test_running_electrolyzer_blocks_fuel_cell_start():
    snapshot = _electrolyzer_snapshot(tank_soc=0.5, electric_power=4.0)
    result, rows = _run(
        snapshot,
        RenewableControlSettings(
            electrolyzer_power_min_kw=2.0,
            electrolyzer_power_max_kw=20.0,
            electrolyzer_power_step_kw=2.0,
            electrolyzer_diesel_power_limit_kw=30.0,
            electrolyzer_diesel_power_stop_maximum_ratio=0.5,
            electrolyzer_storage_soc_stop_maximum=0.2,
            electrolyzer_storage_soc_start_minimum=0.95,
            electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
            fuel_cell_power_min_kw=2.0,
            fuel_cell_power_max_kw=20.0,
            fuel_cell_power_step_kw=2.0,
            fuel_cell_diesel_power_limit_kw=40.0,
            fuel_cell_storage_soc_limit=0.9,
            fuel_cell_hydrogen_storage_soc_upper_limit=0.4,
            fuel_cell_hydrogen_storage_soc_lower_limit=0.2,
        ),
        diesel_power=49.0,
        storage_soc=0.85,
    )

    assert result["interlockMode"] == "electrolyzer"
    assert result["interlockActive"] is True
    assert any("互锁" in warning for warning in result["warnings"])
    assert not any(row.get("dev_name") == "fuel-cell" for row in rows)


@pytest.mark.parametrize(
    ("diesel_power", "expected_stop_mode", "expected_keep_mode", "expected_target"),
    [
        (
            90.0,
            "electrolyzer",
            "fuel_cell",
            {"electrolyzer-load": 0.0, "fuel-cell": 5.0},
        ),
        (
            80.0,
            "fuel_cell",
            "electrolyzer",
            {"fuel-cell": 0.0, "electrolyzer-load": 4.0},
        ),
        (
            70.0,
            "fuel_cell",
            "electrolyzer",
            {"fuel-cell": 0.0, "electrolyzer-load": 4.0},
        ),
    ],
)
def test_existing_simultaneous_operation_stops_mode_selected_by_diesel_power(
    diesel_power,
    expected_stop_mode,
    expected_keep_mode,
    expected_target,
):
    snapshot = _electrolyzer_snapshot(tank_soc=0.5, electric_power=4.0)
    snapshot["measurements"]["scada"] = [
        row
        for row in snapshot["measurements"]["scada"]
        if not (
            row["dev_type"] == "DCGenerator"
            and row["dev_name"] == "fuel-cell"
            and row["meas_type"] == "P_GEN"
        )
    ]
    snapshot["measurements"]["scada"].append(
        _measurement("DCGenerator", "fuel-cell", "P_GEN", 5.0)
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
            "commandKw": 0.0,
            "signedMinTargetKw": -50.0,
            "signedMaxTargetKw": 50.0,
            "transferCapacityKw": 50.0,
            "dcTransferGroupId": group_id,
        },
        {
            "category": "柴油发电",
            "dev_type": "ACGenerator",
            "model_block": "ACGenerator",
            "dev_name": "diesel",
            "online": True,
            "commandable": True,
            "strategyCommand": True,
            "set_type": "p_set",
            "currentKw": diesel_power,
            "commandKw": diesel_power,
            "minKw": 20.0,
            "capacityKw": 200.0,
        },
    ]
    result = _optimize_hydrogen_within_topology_islands(
        snapshot,
        measurements,
        RenewableControlSettings(
            electrolyzer_power_min_kw=2.0,
            electrolyzer_power_max_kw=20.0,
            electrolyzer_power_step_kw=2.0,
            fuel_cell_power_min_kw=3.0,
            fuel_cell_power_max_kw=20.0,
            fuel_cell_power_step_kw=3.0,
            electrolyzer_diesel_power_limit_kw=80.0,
            electrolyzer_diesel_power_deadband_kw=5.0,
            electrolyzer_diesel_power_stop_maximum_ratio=0.9,
            electrolyzer_storage_soc_stop_maximum=0.2,
            electrolyzer_storage_soc_start_minimum=0.8,
            electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
            fuel_cell_diesel_power_limit_kw=80.0,
            fuel_cell_storage_soc_limit=0.5,
            fuel_cell_hydrogen_storage_soc_upper_limit=0.8,
            fuel_cell_hydrogen_storage_soc_lower_limit=0.2,
        ),
        topology,
        rows,
        [{"online": True, "socKnown": True, "soc": 0.5, "socMin": 0.2}],
        diesel_current_kw=diesel_power,
    )

    assert result["interlockMode"] == "conflict"
    assert result["interlockActive"] is True
    assert result["interlockStopMode"] == expected_stop_mode
    assert result["interlockKeepMode"] == expected_keep_mode
    targets = {row["activeDevName"]: row["electricPowerKw"] for row in result["commands"]}
    assert targets == expected_target
    stopped = next(row for row in result["commands"] if row["mode"] == expected_stop_mode)
    kept = next(row for row in result["commands"] if row["mode"] == expected_keep_mode)
    assert stopped["controlReason"] == f"simultaneous_operation_stop_{expected_stop_mode}"
    assert kept["electricDeltaKw"] == pytest.approx(0.0)
    assert any("同时运行" in warning for warning in result["warnings"])


def test_hydrogen_action_marks_dispatch_eligibility_in_the_shared_strategy():
    result, rows = _run(_fuel_cell_snapshot(), RenewableControlSettings())
    assert result["action"] == "fuel_cell"
    assert result["commands"]
    hydrogen_row = next(row for row in rows if row.get("dev_name") == "fuel-cell")
    assert hydrogen_row["statusLabel"] == "综合新能源策略"
    assert hydrogen_row["dispatchEnabled"] is True
    assert result["dispatchMode"] == "closed-loop-atomic"


def test_open_hydrogen_still_generates_targets_without_correcting_electrical_strategy():
    result, rows = _run(
        _fuel_cell_snapshot(),
        RenewableControlSettings(),
        apply_electrical_corrections=False,
    )

    hydrogen_row = next(row for row in rows if row.get("dev_name") == "fuel-cell")
    converter_row = next(
        row for row in rows if row.get("dev_name") == "grid-converter"
    )
    assert result["action"] == "fuel_cell"
    assert result["commands"]
    assert result["dispatchMode"] == "open-loop-preview"
    assert result["fuelCellTargetKw"] > result["fuelCellCurrentKw"]
    assert hydrogen_row["commandKw"] > hydrogen_row["currentKw"]
    assert hydrogen_row["dispatchEnabled"] is False
    assert converter_row["commandKw"] == pytest.approx(converter_row["currentKw"])
    assert result["converterCorrectionKw"] == pytest.approx(0.0)
    assert result["balanceCorrectionKw"] == pytest.approx(0.0)


def test_hydrogen_commands_use_the_same_effective_target_snapshot():
    hydrogen_command = {
        "dev_type": "DCGenerator",
        "dev_name": "fuel-cell",
        "set_type": "p_set",
        "set_value": 3.0,
    }
    hydrogen_row = {
        "category": "氢能",
        "dev_type": "DCGenerator",
        "dev_name": "fuel-cell",
        "set_type": "p_set",
        "commandKw": 3.0,
        "strategyCommand": True,
    }
    plan = {
        "metrics": {
            "fuelCellTargetKw": 3.0,
            "hydrogenControl": {
                "commands": [
                    {
                        "activeDevType": "DCGenerator",
                        "activeDevName": "fuel-cell",
                        "activeSetType": "p_set",
                    }
                ],
            },
        },
        "commands": [hydrogen_command],
        "commandRows": [hydrogen_row],
    }

    assert plan["metrics"]["hydrogenControl"]["commands"]
    effective = TraineeRenewableControlManager._capture_effective_targets(plan)
    assert effective["commands"] == [hydrogen_command]
    assert effective["commandRows"][("DCGenerator", "fuel-cell", "p_set")]["commandKw"] == 3.0


def test_shared_command_payload_includes_hydrogen_and_atomic_corrections():
    plan = {
        "clockKey": "1|10|00:10:00",
        "time": "00:10:00",
        "metrics": {"hydrogenControl": {"action": "fuel_cell"}},
        "dataQuality": {"dispatchAllowed": True},
        "runCommands": [
            {
                "dev_type": "Hydro2DcE",
                "dev_name": "fuel-coupling",
                "run_stat": 1,
            }
        ],
        "commands": [
            {
                "dev_type": "DCGenerator",
                "dev_name": "fuel-cell",
                "set_type": "p_set",
                "set_value": 3.0,
            },
            {
                "dev_type": "DCACConverter",
                "dev_name": "grid-converter",
                "set_type": "p_dc_set",
                "set_value": 3.0,
            },
            {
                "dev_type": "ACGenerator",
                "dev_name": "diesel",
                "set_type": "p_set",
                "set_value": 77.0,
            },
        ],
        "commandRows": [
            {
                "category": "氢能",
                "dev_type": "DCGenerator",
                "dev_name": "fuel-cell",
                "set_type": "p_set",
                "commandKw": 3.0,
            }
        ],
    }
    snapshot = {"clock": {"run_id": 1, "absolute_minute": 10, "time": "00:10:00"}}
    service = SimpleNamespace(model_id="shared", runtime_dir=Path("."))
    manager = TraineeRenewableControlManager(
        service,
        snapshot_provider=lambda _model_id: None,
        receive_status_provider=lambda _model_id: {},
        command_sink=lambda _model_id, _payload: {},
        start_worker=False,
    )
    try:
        state = manager._state_for("shared")
        for loop_mode in ("open", "closed"):
            payload = manager._command_payload(
                state,
                plan,
                snapshot,
                "manual",
                loop_mode=loop_mode,
            )
            assert payload["strategy_id"] == "renewable_priority"
            assert payload["generation"] == "1|10|00:10:00"
            assert payload["replace_strategy_generation"] is True
            assert payload["run_status"] == plan["runCommands"]
            assert payload["set_values"] == plan["commands"]
            assert payload["command_rows"] == plan["commandRows"]
    finally:
        manager.close()


def test_hydrogen_power_ratios_use_each_devices_explicit_rated_capacity():
    snapshot = _electrolyzer_snapshot(electric_power=4.0)
    settings = RenewableControlSettings(
        electrolyzer_power_min_ratio=0.1,
        electrolyzer_power_max_ratio=0.8,
        electrolyzer_power_deadband_ratio=0.05,
        electrolyzer_power_step_ratio=0.1,
        electrolyzer_diesel_power_limit_ratio=0.8,
    )

    result, rows = _run_electrolyzer(
        snapshot,
        settings,
        diesel_power=20.0,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    decision = result["commands"][0]
    assert decision["ratedPowerKw"] == pytest.approx(20.0)
    assert decision["configuredMinimumPowerKw"] == pytest.approx(2.0)
    assert decision["configuredMaximumPowerKw"] == pytest.approx(16.0)
    assert decision["powerDeadbandKw"] == pytest.approx(1.0)
    assert decision["stepLimitKw"] == pytest.approx(2.0)
    assert command["commandKw"] == pytest.approx(6.0)


def test_electrolyzer_start_uses_minimum_power_even_when_normal_step_is_smaller():
    snapshot = _electrolyzer_snapshot(electric_power=0.0, tank_soc=0.5)
    result, rows = _run_electrolyzer(
        snapshot,
        RenewableControlSettings(
            electrolyzer_power_min_ratio=0.10,
            electrolyzer_power_max_ratio=0.80,
            electrolyzer_power_deadband_ratio=0.0,
            electrolyzer_power_step_ratio=0.05,
            electrolyzer_diesel_power_limit_ratio=0.30,
            electrolyzer_storage_soc_start_minimum=0.80,
            electrolyzer_hydrogen_storage_soc_stop_minimum=0.90,
        ),
        diesel_power=20.0,
        storage_soc=0.90,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    decision = result["commands"][0]
    assert result["action"] == "electrolyzer"
    assert decision["configuredMinimumPowerKw"] == pytest.approx(2.0)
    assert decision["stepLimitKw"] == pytest.approx(1.0)
    assert command["commandKw"] == pytest.approx(2.0)


def test_legacy_absolute_setting_keys_migrate_as_percent_values():
    migrated = RenewableControlSettings().updated(
        {
            "electrolyzerPowerMinKw": 2,
            "electrolyzerPowerMaxKw": 50,
            "electrolyzerPowerStepKw": 2,
            "electrolyzerDieselPowerLimitKw": 80,
            "fuelCellPowerMinKw": 3,
            "fuelCellPowerMaxKw": 15,
            "fuelCellPowerStepKw": 3,
            "fuelCellDieselPowerLimitKw": 80,
        }
    )

    payload = migrated.payload()
    assert payload["electrolyzerPowerMinRatio"] == pytest.approx(0.02)
    assert payload["electrolyzerPowerMaxRatio"] == pytest.approx(0.5)
    assert payload["electrolyzerPowerStepRatio"] == pytest.approx(0.02)
    assert payload["electrolyzerDieselPowerLimitRatio"] == pytest.approx(0.8)
    assert payload["fuelCellPowerMinRatio"] == pytest.approx(0.03)
    assert payload["fuelCellPowerMaxRatio"] == pytest.approx(0.15)
    assert payload["fuelCellPowerStepRatio"] == pytest.approx(0.03)
    assert payload["fuelCellDieselPowerLimitRatio"] == pytest.approx(0.8)
    assert not any(key.endswith("Kw") and "Power" in key for key in payload)


def test_low_tank_pressure_blocks_fuel_cell_strategy():
    settings = RenewableControlSettings(
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
    settings = RenewableControlSettings()
    result, rows = _run(
        _fuel_cell_snapshot(include_pressure=False),
        settings,
    )
    assert result["action"] == "blocked"
    assert result["commands"] == []
    assert not any(row.get("dev_name") == "fuel-cell" for row in rows)


def test_electrolyzer_power_rises_one_power_step_when_headroom_exists():
    settings = RenewableControlSettings(
        step_coefficient=0.1,
        electrolyzer_power_step_ratio=0.1,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=4.0),
        settings,
        diesel_power=20.0,
    )
    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["action"] == "electrolyzer"
    assert result["electricPowerAdjustmentKw"] == 2.0
    assert result["commands"][0]["electricPowerKw"] == 6.0
    assert result["commands"][0]["equivalentFlow"] == pytest.approx(1.2)
    assert command["commandKw"] == 6.0


def test_electrolyzer_voltage_limit_violation_does_not_change_power_decision():
    snapshot = _electrolyzer_snapshot(electric_power=4.0)
    power_row = snapshot["definitions"]["model"]["ACLoad"]["rows"][0]
    power_row.update({"v_min": 304, "v_max": 456})
    power_device = next(
        row
        for row in snapshot["devices"]
        if row.get("dev_type") == "ACLoad"
        and row.get("dev_name") == "electrolyzer-load"
    )
    power_device["raw"] = dict(power_row)
    snapshot["measurements"]["scada"].append(
        _measurement("ACLoad", "electrolyzer-load", "V_LOAD", 289.22)
    )

    result, rows = _run_electrolyzer(
        snapshot,
        RenewableControlSettings(
            step_coefficient=0.1,
            electrolyzer_power_step_ratio=0.1,
        ),
        diesel_power=20.0,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["action"] == "electrolyzer"
    assert result["electricPowerAdjustmentKw"] == 2.0
    assert command["commandKw"] == 6.0
    assert not any("端电压" in warning for warning in result["warnings"])


@pytest.mark.parametrize(
    ("storage_soc", "starts"),
    ((0.699, False), (0.7, False), (0.701, True)),
)
def test_electrolyzer_start_requires_average_storage_soc_strictly_above_70_percent(
    storage_soc,
    starts,
):
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=6.0,
        electrolyzer_diesel_power_limit_ratio=0.8,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=0.0),
        settings,
        diesel_power=34.0,
        storage_soc=storage_soc,
    )

    commands = [row for row in rows if row.get("dev_name") == "electrolyzer-load"]
    assert bool(commands) is starts
    if starts:
        assert commands[0]["commandKw"] == 6.0
        assert result["commands"][0]["startThresholdKw"] == 6.0
    else:
        assert result["electricPowerAdjustmentKw"] == 0.0
        assert any(
            "电储SOC" in warning and "70.000%" in warning
            for warning in result["warnings"]
        )


@pytest.mark.parametrize(
    ("diesel_power", "expected_target"),
    ((40.0, None), (39.999, 6.0), (34.001, 6.0), (30.0, 6.0)),
)
def test_electrolyzer_starts_directly_once_entry_conditions_are_met(
    diesel_power,
    expected_target,
):
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=6.0,
        electrolyzer_diesel_power_limit_kw=40.0,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=0.0),
        settings,
        diesel_power=diesel_power,
        storage_soc=0.81,
    )

    commands = [row for row in rows if row.get("dev_name") == "electrolyzer-load"]
    if expected_target is None:
        assert commands == []
        assert any("未低于启机限值" in warning for warning in result["warnings"])
    else:
        assert commands[0]["commandKw"] == expected_target
        assert result["commands"][0]["controlReason"] == (
            "entry_conditions_met_direct_start"
        )
        assert result["predictedDieselAfterKw"] == pytest.approx(
            diesel_power + expected_target
        )
        if diesel_power > 34.0:
            assert result["predictedDieselAfterKw"] > 40.0


def test_electrolyzer_decision_detail_shows_rule_inputs_output_and_reason():
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=6.0,
        electrolyzer_diesel_power_limit_kw=40.0,
    )
    result, _rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=0.0, tank_soc=0.5),
        settings,
        diesel_power=39.999,
        storage_soc=0.81,
    )

    detail = _hydrogen_business_decision_detail(result, settings)
    joined = "\n".join(detail)

    assert "电制氢规则" in joined
    assert "电制氢设备决策" in joined
    assert "柴发负载率40.00%" in joined
    assert "电储SOC81.00%" in joined
    assert "氢储SOC50.00%" in joined
    assert "输出=启机" in joined
    assert "目标6.00 kW" in joined
    assert "启机条件满足，直接达到启机功率" in joined
    assert "燃料电池规则" in joined
    assert "启机时忽略普通步长限制，直接达到最小运行功率+步长" in joined
    assert "升功率时按一个步长增加" in joined
    assert "降功率时按一个步长降低" in joined
    assert "本轮控制策略严格低于出力下限-死区时停机" in joined
    assert "等于该阈值时不提前停机" in joined


def test_hydrogen_decision_trace_keeps_electrolyzer_start_blockers():
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=6.0,
        electrolyzer_diesel_power_limit_kw=40.0,
    )
    result, _rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=0.0, tank_soc=0.5),
        settings,
        diesel_power=40.0,
        storage_soc=0.81,
    )

    trace = next(
        row for row in result["decisionTraces"] if row.get("mode") == "electrolyzer"
    )
    detail = "\n".join(_hydrogen_business_decision_detail(result, settings))

    assert trace["action"] == "hold"
    assert trace["controlReason"] == "start_conditions_not_met"
    assert any("未低于启机限值" in item for item in trace["blockers"])
    assert "阻断条件=柴发负载率40.000%未低于启机限值40.000%" in detail


def test_subthreshold_residuals_do_not_block_same_cycle_electrolyzer_start():
    snapshot = _electrolyzer_snapshot(
        electric_power=0.01,
        tank_soc=0.5,
    )
    for row in snapshot["measurements"]["scada"]:
        if (
            row.get("dev_type") == "DCGenerator"
            and row.get("dev_name") == "fuel-cell"
            and row.get("meas_type") == "P_GEN"
        ):
            row["value"] = 0.02
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=6.0,
        electrolyzer_diesel_power_limit_kw=40.0,
        fuel_cell_power_min_kw=0.9,
        fuel_cell_power_deadband_kw=0.0,
        fuel_cell_power_step_kw=0.3,
    )

    result, rows = _run_electrolyzer(
        snapshot,
        settings,
        diesel_power=30.0,
        storage_soc=0.81,
    )

    electrolyzer = next(
        row for row in result["commands"] if row.get("mode") == "electrolyzer"
    )
    electrolyzer_setpoint = next(
        row for row in rows if row.get("dev_name") == "electrolyzer-load"
    )
    assert result["interlockMode"] != "conflict"
    assert electrolyzer["action"] == "electrolyzer"
    assert electrolyzer["controlReason"] == "entry_conditions_met_direct_start"
    assert electrolyzer["currentElectricPowerKw"] == pytest.approx(0.01)
    assert electrolyzer["electricPowerKw"] == pytest.approx(6.0)
    assert electrolyzer["electricDeltaKw"] == pytest.approx(5.99)
    assert electrolyzer_setpoint["commandKw"] == pytest.approx(6.0)
    detail = "\n".join(_hydrogen_business_decision_detail(result, settings))
    assert "电制氢设备决策" in detail
    assert "输出=启机" in detail
    assert "目标6.00 kW" in detail
    assert "启机条件满足，直接达到启机功率" in detail


def test_subthreshold_electrolyzer_still_stops_when_entry_conditions_fail():
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=6.0,
        electrolyzer_diesel_power_limit_kw=40.0,
    )

    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=0.01, tank_soc=0.5),
        settings,
        diesel_power=45.0,
        storage_soc=0.81,
    )

    electrolyzer = next(
        row for row in result["commands"] if row.get("mode") == "electrolyzer"
    )
    electrolyzer_setpoint = next(
        row for row in rows if row.get("dev_name") == "electrolyzer-load"
    )
    assert electrolyzer["action"] == "power_hysteresis_stop"
    assert electrolyzer["powerHysteresisStop"] is True
    assert electrolyzer_setpoint["commandKw"] == 0.0


def test_running_electrolyzer_increase_equals_diesel_guard_gap_before_limits():
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=0.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=10.0,
        electrolyzer_diesel_power_limit_kw=40.0,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=4.0),
        settings,
        diesel_power=38.5,
        storage_soc=0.81,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["electricPowerAdjustmentKw"] == pytest.approx(1.5)
    assert command["commandKw"] == pytest.approx(5.5)


def test_running_electrolyzer_reduces_above_diesel_stop_maximum():
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=2.0,
        electrolyzer_diesel_power_limit_kw=35.0,
        electrolyzer_diesel_power_stop_maximum_ratio=0.5,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=8.0, tank_soc=0.5),
        settings,
        diesel_power=60.0,
        storage_soc=0.8,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["action"] == "electrolyzer_reduce"
    assert result["electricPowerAdjustmentKw"] == pytest.approx(-2.0)
    assert command["commandKw"] == pytest.approx(6.0)
    assert result["commands"][0]["controlReason"] == "diesel_power_above_stop_threshold"


def test_running_electrolyzer_holds_between_start_and_stop_diesel_thresholds():
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=2.0,
        electrolyzer_diesel_power_limit_kw=35.0,
        electrolyzer_diesel_power_stop_maximum_ratio=0.5,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=8.0, tank_soc=0.5),
        settings,
        diesel_power=45.0,
        storage_soc=0.8,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["action"] == "hold"
    assert result["electricPowerAdjustmentKw"] == pytest.approx(0.0)
    assert command["commandKw"] == pytest.approx(8.0)


def test_low_storage_soc_reduces_running_electrolyzer_one_step():
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=2.0,
        electrolyzer_diesel_power_limit_kw=40.0,
        electrolyzer_diesel_power_deadband_kw=0.0,
        electrolyzer_storage_soc_stop_maximum=0.4,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=8.0),
        settings,
        diesel_power=45.0,
        storage_soc=0.399,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["action"] == "electrolyzer_reduce"
    assert result["electricPowerAdjustmentKw"] == pytest.approx(-2.0)
    assert command["commandKw"] == pytest.approx(6.0)


def test_electrolyzer_reduction_below_lower_deadband_explicitly_stops():
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=3.0,
        electrolyzer_diesel_power_limit_kw=40.0,
        electrolyzer_diesel_power_deadband_kw=0.0,
        electrolyzer_storage_soc_stop_maximum=0.4,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=6.0),
        settings,
        diesel_power=45.0,
        storage_soc=0.399,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["action"] == "power_hysteresis_stop"
    assert command["commandKw"] == 0.0
    assert result["commands"][0]["powerHysteresisStop"] is True


def test_electrolyzer_reduction_at_lower_deadband_boundary_keeps_running():
    snapshot = _electrolyzer_snapshot(electric_power=7.0)
    snapshot["definitions"]["model"]["ACLoad"]["rows"][0]["p_min"] = 5.0
    next(
        row
        for row in snapshot["devices"]
        if row.get("dev_name") == "electrolyzer-load"
    )["raw"]["p_min"] = 5.0
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=5.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=3.0,
        electrolyzer_diesel_power_limit_kw=40.0,
        electrolyzer_diesel_power_deadband_kw=0.0,
        electrolyzer_storage_soc_stop_maximum=0.4,
    )
    result, rows = _run_electrolyzer(
        snapshot,
        settings,
        diesel_power=45.0,
        storage_soc=0.399,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["action"] == "electrolyzer_reduce"
    assert command["commandKw"] == pytest.approx(4.0)
    assert result["commands"][0]["stopThresholdKw"] == pytest.approx(4.0)
    assert result["commands"][0]["powerHysteresisStop"] is False


def test_configured_electrolyzer_upper_limit_only_tightens_model_boundary():
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=0.0,
        electrolyzer_power_max_kw=7.0,
        electrolyzer_power_deadband_kw=1.0,
        electrolyzer_power_step_kw=10.0,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=6.0),
        settings,
        diesel_power=20.0,
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert command["commandKw"] == 7.0
    assert result["commands"][0]["configuredMaximumPowerKw"] == 7.0


def test_missing_diesel_measurement_blocks_electrolyzer_strategy():
    settings = RenewableControlSettings(
        step_coefficient=0.1,
        electrolyzer_power_step_ratio=0.1,
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
        step_coefficient=0.1,
        electrolyzer_power_step_ratio=0.1,
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
        step_coefficient=0.1,
        electrolyzer_diesel_power_limit_kw=40.0,
        electrolyzer_power_step_ratio=0.1,
    )
    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=4.0),
        settings,
        diesel_power=39.0,
    )
    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["electricPowerAdjustmentKw"] == 1.0
    assert command["commandKw"] == 5.0


def test_electrolyzer_power_step_is_clamped_by_power_and_flow_limits():
    settings = RenewableControlSettings(
        step_coefficient=0.1,
        electrolyzer_power_deadband_ratio=0.0,
        electrolyzer_power_step_ratio=0.1,
        electrolyzer_diesel_power_limit_ratio=0.8,
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
        step_coefficient=0.1,
        electrolyzer_power_step_ratio=0.1,
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


def test_running_electrolyzer_hold_remains_in_each_complete_strategy_snapshot():
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=2.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=0.0,
        electrolyzer_power_step_kw=2.0,
        electrolyzer_diesel_power_limit_kw=100.0,
        electrolyzer_storage_soc_start_minimum=0.8,
        electrolyzer_storage_soc_stop_maximum=0.4,
        electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
    )

    first, first_rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=20.0, tank_soc=0.5),
        settings,
        diesel_power=20.0,
        storage_soc=0.9,
    )
    second, second_rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=20.0, tank_soc=0.5),
        settings,
        diesel_power=20.0,
        storage_soc=0.9,
    )

    for result, rows in ((first, first_rows), (second, second_rows)):
        assert not any(row.get("commandKind") == "run_status" for row in rows)
        setpoint = next(
            row
            for row in rows
            if row.get("dev_name") == "electrolyzer-load"
            and row.get("set_type") == "p_set"
        )
        assert setpoint["commandKw"] == pytest.approx(20.0)
        assert result["action"] == "hold"
        assert result["commands"][0]["electricDeltaKw"] == pytest.approx(0.0)
        assert result["commands"][0]["electricPowerKw"] == pytest.approx(20.0)


def test_electrolyzer_measurement_just_above_max_is_corrected_without_dropping_snapshot():
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=2.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_deadband_kw=0.0,
        electrolyzer_power_step_kw=2.0,
        electrolyzer_diesel_power_limit_kw=100.0,
        electrolyzer_storage_soc_start_minimum=0.8,
        electrolyzer_storage_soc_stop_maximum=0.4,
        electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
    )

    result, rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=20.01, tank_soc=0.5),
        settings,
        diesel_power=20.0,
        storage_soc=0.9,
    )

    assert not any(row.get("commandKind") == "run_status" for row in rows)
    setpoint = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert setpoint["commandKw"] == pytest.approx(20.0)
    assert result["commands"][0]["electricPowerKw"] == pytest.approx(20.0)
    assert result["commands"][0]["electricDeltaKw"] == pytest.approx(-0.01)
    assert result["commands"][0]["controlReason"] == "above_upper_power_limit_correction"


def test_running_fuel_cell_hold_remains_in_complete_strategy_snapshot():
    snapshot = _fuel_cell_snapshot(tank_soc=0.9)
    for row in snapshot["measurements"]["scada"]:
        if row.get("dev_type") == "DCGenerator" and row.get("dev_name") == "fuel-cell":
            row["value"] = 20.0
        elif row.get("dev_type") == "HydroLoad" and row.get("dev_name") == "fuel-hydrogen":
            row["value"] = 20.0 / 1.5
    settings = RenewableControlSettings(
        fuel_cell_power_min_kw=5.0,
        fuel_cell_power_max_kw=20.0,
        fuel_cell_power_deadband_kw=1.0,
        fuel_cell_power_step_kw=6.0,
        fuel_cell_diesel_power_limit_kw=100.0,
        fuel_cell_storage_soc_limit=0.4,
        fuel_cell_hydrogen_storage_soc_upper_limit=0.8,
        fuel_cell_hydrogen_storage_soc_lower_limit=0.2,
    )

    result, rows = _run(
        snapshot,
        settings,
        diesel_power=150.0,
        storage_soc=0.1,
    )

    assert not any(row.get("commandKind") == "run_status" for row in rows)
    setpoint = next(
        row
        for row in rows
        if row.get("dev_name") == "fuel-cell" and row.get("set_type") == "p_set"
    )
    assert setpoint["commandKw"] == pytest.approx(20.0)
    assert result["action"] == "hold"
    assert result["commands"][0]["electricDeltaKw"] == pytest.approx(0.0)


def test_atomic_zero_margin_keeps_running_electrolyzer_setpoint_in_snapshot():
    snapshot = _electrolyzer_snapshot(electric_power=8.0, tank_soc=0.5)
    measurements = _measurement_index(snapshot)
    topology = resolve_resource_topology(snapshot, ())
    rows = [
        {
            "category": "柴油发电",
            "dev_type": "ACGenerator",
            "model_block": "ACGenerator",
            "dev_name": "diesel",
            "online": True,
            "commandable": True,
            "strategyCommand": True,
            "set_type": "p_set",
            "currentKw": 20.0,
            "commandKw": 20.0,
            "minKw": 20.0,
            "capacityKw": 20.0,
        }
    ]

    result = _optimize_hydrogen_within_topology_islands(
        snapshot,
        measurements,
        RenewableControlSettings(
            electrolyzer_power_min_kw=2.0,
            electrolyzer_power_max_kw=20.0,
            electrolyzer_power_step_kw=2.0,
            electrolyzer_diesel_power_limit_kw=100.0,
            electrolyzer_storage_soc_start_minimum=0.8,
            electrolyzer_storage_soc_stop_maximum=0.4,
            electrolyzer_hydrogen_storage_soc_stop_minimum=0.9,
        ),
        topology,
        rows,
        [{"online": True, "socKnown": True, "soc": 0.9, "socMin": 0.2}],
        diesel_current_kw=20.0,
    )

    setpoint = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert setpoint["commandKw"] == pytest.approx(8.0)
    assert result["commands"][0]["action"] == "blocked"
    assert result["commands"][0]["controlReason"] == "atomic_margin_unavailable"
    assert result["commands"][0]["electricDeltaKw"] == pytest.approx(0.0)


def test_electrolyzer_stop_and_following_generation_keep_stop_then_zero_setpoint():
    settings = RenewableControlSettings(
        electrolyzer_power_min_kw=2.0,
        electrolyzer_power_max_kw=20.0,
        electrolyzer_power_step_kw=2.0,
    )

    first, first_rows = _run_electrolyzer(
        _electrolyzer_snapshot(electric_power=8.0, tank_pressure=45.0),
        settings,
    )
    stopped_snapshot = _set_coupling_run_state(
        _electrolyzer_snapshot(electric_power=0.0, tank_pressure=45.0),
        "AcE2Hydro",
        "electrolyzer-coupling",
        0,
    )
    second, second_rows = _run_electrolyzer(stopped_snapshot, settings)

    run_row = next(row for row in first_rows if row.get("commandKind") == "run_status")
    first_setpoint = next(
        row for row in first_rows if row.get("dev_name") == "electrolyzer-load"
    )
    assert first_rows.index(run_row) < first_rows.index(first_setpoint)
    assert run_row["run_stat"] == 0
    assert first_setpoint["commandKw"] == pytest.approx(0.0)
    assert not any(row.get("commandKind") == "run_status" for row in second_rows)
    assert next(
        row for row in second_rows if row.get("dev_name") == "electrolyzer-load"
    )["commandKw"] == pytest.approx(0.0)
    assert first["commands"][0]["electricPowerKw"] == pytest.approx(0.0)
    assert second["commands"][0]["electricPowerKw"] == pytest.approx(0.0)


def test_flow_controlled_electrolyzer_still_steps_by_electric_power():
    settings = RenewableControlSettings(
        step_coefficient=0.1,
        electrolyzer_power_step_ratio=0.1,
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
        step_coefficient=0.1,
        electrolyzer_power_step_ratio=0.1,
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
        hydrogen_pressure_deadband_ratio=0.05,
        step_coefficient=0.1,
        fuel_cell_power_step_ratio=0.1,
        fuel_cell_power_min_ratio=0.1,
    )
    result, rows = _run(
        _fuel_cell_snapshot(tank_pressure=4.15),
        settings,
        diesel_power=86.0,
    )
    fuel_row = next(row for row in rows if row.get("dev_name") == "fuel-cell")
    converter_row = next(row for row in rows if row.get("dev_name") == "grid-converter")
    assert result["action"] == "fuel_cell"
    assert result["electricPowerAdjustmentKw"] == 6.0
    assert result["targetElectricPowerKw"] == 6.0
    assert result["commands"][0]["equivalentFlow"] == 4.0
    assert result["commands"][0]["stepLimitKw"] == 3.0
    assert fuel_row["commandKw"] == 6.0
    assert converter_row["commandKw"] == -6.0


def test_fuel_cell_start_requires_margin_for_minimum_plus_step():
    settings = RenewableControlSettings(
        fuel_cell_power_min_kw=5.0,
        fuel_cell_power_max_kw=20.0,
        fuel_cell_power_deadband_kw=1.0,
        fuel_cell_power_step_kw=6.0,
        fuel_cell_diesel_power_limit_kw=40.0,
    )

    blocked, blocked_rows = _run(
        _fuel_cell_snapshot(tank_pressure=20.0),
        settings,
        diesel_power=44.0,
    )
    assert blocked_rows[0]["commandKw"] == 0.0
    assert any("最小运行功率+步长" in warning for warning in blocked["warnings"])

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
    started = _optimize_hydrogen_within_topology_islands(
        snapshot,
        measurements,
        settings,
        topology,
        rows,
        [{"online": True, "socKnown": True, "soc": 0.1, "socMin": 0.2}],
        diesel_current_kw=51.0,
    )
    fuel_row = next(row for row in rows if row.get("dev_name") == "fuel-cell")
    assert fuel_row["commandKw"] == 11.0
    assert started["commands"][0]["startThresholdKw"] == 11.0
    assert started["commands"][0]["minimumRunningPowerKw"] == 5.0


def test_subthreshold_fuel_cell_residual_starts_at_minimum_plus_step():
    snapshot = _fuel_cell_snapshot(tank_pressure=20.0, tank_soc=0.5)
    fuel_model = snapshot["definitions"]["model"]["DCGenerator"]["rows"][0]
    fuel_model["p_min"] = 3.0
    fuel_device = next(
        row
        for row in snapshot["devices"]
        if row.get("dev_type") == "DCGenerator"
        and row.get("dev_name") == "fuel-cell"
    )
    fuel_device["raw"]["p_min"] = 3.0
    for row in snapshot["measurements"]["scada"]:
        if row.get("dev_type") == "DCGenerator" and row.get("dev_name") == "fuel-cell":
            row["value"] = 0.01
        elif row.get("dev_type") == "HydroLoad" and row.get("dev_name") == "fuel-hydrogen":
            row["value"] = 0.01 / 1.5

    settings = RenewableControlSettings(
        fuel_cell_power_min_kw=3.0,
        fuel_cell_power_max_kw=20.0,
        fuel_cell_power_deadband_kw=2.0,
        fuel_cell_power_step_kw=1.0,
        fuel_cell_diesel_power_limit_kw=40.0,
        fuel_cell_storage_soc_limit=0.4,
        fuel_cell_hydrogen_storage_soc_upper_limit=0.3,
        fuel_cell_hydrogen_storage_soc_lower_limit=0.2,
    )

    result, rows = _run(
        snapshot,
        settings,
        diesel_power=46.0,
        storage_soc=0.1,
    )

    fuel_row = next(
        row
        for row in rows
        if row.get("dev_name") == "fuel-cell" and row.get("set_type") == "p_set"
    )
    command = result["commands"][0]
    assert result["action"] == "fuel_cell"
    assert command["minimumRunningPowerKw"] == pytest.approx(3.0)
    assert command["startThresholdKw"] == pytest.approx(4.0)
    assert command["stopThresholdKw"] == pytest.approx(1.0)
    assert command["stepLimitKw"] == pytest.approx(1.0)
    assert command["electricDeltaKw"] == pytest.approx(3.99)
    assert command["electricPowerKw"] == pytest.approx(4.0)
    assert fuel_row["commandKw"] == pytest.approx(4.0)


@pytest.mark.parametrize(
    ("current_power", "expected_action", "expected_target", "expected_stop"),
    (
        (6.0, "power_hysteresis_stop", 0.0, True),
        (7.0, "fuel_cell_reduce", 4.0, False),
    ),
)
def test_running_fuel_cell_shutdown_uses_strict_lower_minus_deadband_boundary(
    current_power,
    expected_action,
    expected_target,
    expected_stop,
):
    snapshot = _fuel_cell_snapshot(tank_pressure=20.0)
    snapshot["measurements"]["scada"] = [
        row
        for row in snapshot["measurements"]["scada"]
        if not (row["dev_type"] == "DCGenerator" and row["dev_name"] == "fuel-cell")
    ]
    snapshot["measurements"]["scada"].append(
        _measurement("DCGenerator", "fuel-cell", "P_GEN", current_power)
    )
    settings = RenewableControlSettings(
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
    result = _optimize_hydrogen_within_topology_islands(
        snapshot,
        measurements,
        settings,
        topology,
        rows,
        [{"online": True, "socKnown": True, "soc": 0.5, "socMin": 0.2}],
        diesel_current_kw=40.0,
    )

    fuel_row = next(row for row in rows if row.get("dev_name") == "fuel-cell")
    command = result["commands"][0]
    assert result["action"] == expected_action
    assert fuel_row["commandKw"] == pytest.approx(expected_target)
    assert command["stopThresholdKw"] == pytest.approx(4.0)
    assert command["powerHysteresisStop"] is expected_stop
    run_status_rows = [
        row
        for row in rows
        if row.get("commandKind") == "run_status"
        and row.get("dev_name") == "fuel-coupling"
    ]
    if expected_stop:
        assert len(run_status_rows) == 1
        assert run_status_rows[0]["run_stat"] == 0
    else:
        assert run_status_rows == []


def test_pressure_just_below_guard_blocks_fuel_cell():
    settings = RenewableControlSettings(
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
    result = _optimize_hydrogen_within_topology_islands(
        snapshot,
        measurements,
        RenewableControlSettings(
            fuel_cell_diesel_power_limit_kw=40.0,
            fuel_cell_power_step_ratio=0.1,
            fuel_cell_power_min_ratio=0.1,
        ),
        topology,
        rows,
        [{"online": True, "socKnown": True, "soc": 0.1, "socMin": 0.2}],
        diesel_current_kw=55,
    )

    converters = {
        row["dev_name"]: row
        for row in rows
        if row.get("model_block") == "DCACConverter"
    }
    assert result["converterCorrectionKw"] == pytest.approx(6.0)
    assert converters["grid-converter"]["commandKw"] == pytest.approx(-43.0)
    assert converters["grid-converter-2"]["commandKw"] == pytest.approx(-3.0)
    assert _dispatch_setpoint_value(converters["grid-converter"]) == pytest.approx(-43.0)
    assert _dispatch_setpoint_value(converters["grid-converter-2"]) == pytest.approx(3.0)


def test_hydrogen_grid_side_comes_from_resolved_topology_and_fails_closed_when_invalid():
    snapshot = _fuel_cell_snapshot(tank_pressure=20.0)
    measurements = _measurement_index(snapshot)
    topology = resolve_resource_topology(
        snapshot,
        (ResourceRef("hydrogen", "DCGenerator", "fuel-cell"),),
    )
    connection = topology.resources[("DCGenerator", "fuel-cell")]
    assert connection.connection_side == "DC"
    assert connection.busbar_type == "DCRealBs"
    assert connection.grid_component_id
    invalid_connection = replace(
        connection,
        connection_side="UNRESOLVED",
        actively_connected=False,
        grid_component_id="",
        dc_transfer_group_id="",
    )
    unresolved_topology = replace(
        topology,
        resources=MappingProxyType(
            {("DCGenerator", "fuel-cell"): invalid_connection}
        ),
    )
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
            "commandKw": 0.0,
            "signedMinTargetKw": -50.0,
            "signedMaxTargetKw": 50.0,
            "dcTransferGroupId": group_id,
        }
    ]

    result = _optimize_hydrogen_within_topology_islands(
        snapshot,
        measurements,
        RenewableControlSettings(fuel_cell_diesel_power_limit_kw=40.0),
        unresolved_topology,
        rows,
        [{"online": True, "socKnown": True, "soc": 0.1, "socMin": 0.2}],
        diesel_current_kw=55.0,
    )

    assert result["commands"] == []
    assert any("并网侧拓扑" in warning for warning in result["warnings"])
    assert not any(row.get("dev_name") == "fuel-cell" for row in rows)


def test_hydrogen_grid_side_crosses_converter_to_final_real_bus():
    snapshot = _integrated_fuel_cell_snapshot()
    snapshot["definitions"]["model"]["DCRealBs"]["rows"] = []
    plan = calculate_renewable_control_plan(
        snapshot,
        _integrated_fuel_cell_settings(hydrogen_closed_loop_enabled=True),
    )
    hydrogen = plan["metrics"]["hydrogenControl"]
    command = hydrogen["commands"][0]
    assert command["electricSide"] == "AC"
    assert command["electricBusbarType"] == "ACRealBs"
    assert command["electricConverterPath"] == [
        ("DCACConverter", "grid-converter")
    ]
    assert hydrogen["converterCorrectionKw"] == pytest.approx(0.0)


def test_hydrogen_aggregate_metrics_follow_explicit_coupling_bindings():
    snapshot = _electrolyzer_snapshot(
        tank_pressure=20.0,
        electric_power=4.0,
    )
    snapshot["measurements"]["scada"].extend(
        [
            _measurement("HydroStorage", "tank", "GAS_QUANTITY", 420.0),
            _measurement("HydroStorage", "tank", "SOC", 0.42),
            _measurement("HydroStorage", "tank", "FLOW", 0.8),
        ]
    )
    snapshot["measurements"]["scada"] = [
        row
        for index, row in enumerate(snapshot["measurements"]["scada"])
        if not (
            row.get("dev_type") == "HydroStorage"
            and row.get("dev_name") == "tank"
            and row.get("meas_type") == "SOC"
            and index
            != max(
                candidate_index
                for candidate_index, candidate in enumerate(
                    snapshot["measurements"]["scada"]
                )
                if candidate.get("dev_type") == "HydroStorage"
                and candidate.get("dev_name") == "tank"
                and candidate.get("meas_type") == "SOC"
            )
        )
    ]
    settings = RenewableControlSettings()
    plan = calculate_renewable_control_plan(snapshot, settings)
    metrics = plan["metrics"]

    assert metrics["onlineElectrolyzerCount"] == 1
    assert metrics["onlineFuelCellCount"] == 1
    assert metrics["onlineHydrogenStorageCount"] == 1
    assert metrics["electrolyzerCurrentKw"] == pytest.approx(4.0)
    assert metrics["electrolyzerTargetKw"] == pytest.approx(4.0)
    assert metrics["electrolyzerFlowCurrentNm3h"] == pytest.approx(0.8)
    assert metrics["electrolyzerFlowTargetNm3h"] == pytest.approx(0.8)
    assert metrics["hydrogenStoragePressureMpa"] == pytest.approx(20.0)
    assert metrics["hydrogenStoragePressureLowGuardMpa"] == pytest.approx(4.15)
    assert metrics["hydrogenStoragePressureHighGuardMpa"] == pytest.approx(42.85)
    assert metrics["hydrogenStorageGasQuantityNm3"] == pytest.approx(420.0)
    assert metrics["hydrogenStorageSoc"] == pytest.approx(0.42)
    assert metrics["hydrogenStorageFlowNm3h"] == pytest.approx(0.8)


def test_hydrogen_aggregate_metrics_keep_retired_converters_visible_as_zero():
    snapshot = _electrolyzer_snapshot(
        tank_pressure=20.0,
        electric_power=4.0,
    )
    retired_blocks = {"AcE2Hydro", "ACLoad", "HydroSource", "Hydro2DcE", "DCGenerator", "HydroLoad"}
    for device in snapshot["devices"]:
        if device.get("model_block") not in retired_blocks:
            continue
        device["run_stat"] = 0
        device["raw"]["run_stat"] = 0
    for block_name in retired_blocks:
        for row in snapshot["definitions"]["model"].get(block_name, {}).get("rows", []):
            row["run_stat"] = 0

    plan = calculate_renewable_control_plan(
        snapshot,
        RenewableControlSettings(),
    )
    metrics = plan["metrics"]

    assert metrics["configuredElectrolyzerCount"] == 1
    assert metrics["configuredFuelCellCount"] == 1
    assert metrics["onlineElectrolyzerCount"] == 0
    assert metrics["onlineFuelCellCount"] == 0
    assert metrics["electrolyzerCurrentKw"] == pytest.approx(0.0)
    assert metrics["electrolyzerTargetKw"] == pytest.approx(0.0)
    assert metrics["electrolyzerFlowCurrentNm3h"] == pytest.approx(0.0)
    assert metrics["electrolyzerFlowTargetNm3h"] == pytest.approx(0.0)
    assert metrics["fuelCellCurrentKw"] == pytest.approx(0.0)
    assert metrics["fuelCellTargetKw"] == pytest.approx(0.0)
    assert metrics["fuelCellFlowCurrentNm3h"] == pytest.approx(0.0)
    assert metrics["fuelCellFlowTargetNm3h"] == pytest.approx(0.0)

    startup_metrics = _hydrogen_operating_metrics(
        snapshot,
        _measurement_index(snapshot),
        [],
        [
            {
                "couplingType": "AcE2Hydro",
                "couplingName": "electrolyzer-coupling",
                "electricPowerKw": 6.0,
                "equivalentFlow": 1.2,
            }
        ],
    )
    assert startup_metrics["electrolyzerCurrentKw"] == pytest.approx(0.0)
    assert startup_metrics["electrolyzerFlowCurrentNm3h"] == pytest.approx(0.0)
    assert startup_metrics["electrolyzerTargetKw"] == pytest.approx(6.0)
    assert startup_metrics["electrolyzerFlowTargetNm3h"] == pytest.approx(1.2)

    trend_point = TraineeRenewableControlManager._trend_point(plan, snapshot)
    for key in (
        "electrolyzerCurrentKw",
        "electrolyzerTargetKw",
        "electrolyzerFlowCurrentNm3h",
        "electrolyzerFlowTargetNm3h",
        "fuelCellCurrentKw",
        "fuelCellTargetKw",
        "fuelCellFlowCurrentNm3h",
        "fuelCellFlowTargetNm3h",
    ):
        assert trend_point[key] == pytest.approx(0.0)


def test_hydrogen_trend_capture_and_persistence_use_the_shared_strategy_lifecycle(
    tmp_path,
):
    snapshot = _electrolyzer_snapshot(
        tank_pressure=20.0,
        electric_power=4.0,
    )
    snapshot["measurements"]["scada"].extend(
        [
            _measurement("HydroStorage", "tank", "GAS_QUANTITY", 420.0),
            _measurement("HydroStorage", "tank", "FLOW", 0.8),
        ]
    )
    plan = calculate_renewable_control_plan(
        snapshot,
        RenewableControlSettings(),
    )
    point = TraineeRenewableControlManager._trend_point(plan, snapshot)

    assert point["electrolyzerCurrentKw"] == pytest.approx(4.0)
    assert point["electrolyzerTargetKw"] == pytest.approx(4.0)
    assert point["hydrogenStoragePressureMpa"] == pytest.approx(20.0)
    assert point["hydrogenStorageGasQuantityNm3"] == pytest.approx(420.0)
    assert point["hydrogenStorageFlowNm3h"] == pytest.approx(0.8)

    service = SimpleNamespace(runtime_dir=Path(tmp_path))
    manager = TraineeRenewableControlManager(
        service,
        snapshot_provider=lambda _model_id: None,
        receive_status_provider=lambda _model_id: {},
        command_sink=lambda _model_id, _payload: {},
        start_worker=False,
    )
    try:
        candidate = SimpleNamespace(
            persistence_point=point,
            trend=[point],
            persistence_reset=False,
            persistence_replace_last=False,
        )
        manager._persist_trend_candidate_for_service(service, candidate)
        persisted = json.loads(
            (Path(tmp_path) / "renewable_control_trend.jsonl")
            .read_text(encoding="utf-8")
            .strip()
        )
    finally:
        manager.close()

    assert persisted["electrolyzerCurrentKw"] == pytest.approx(4.0)
    assert persisted["hydrogenStoragePressureMpa"] == pytest.approx(20.0)
    assert persisted["hydrogenStorageGasQuantityNm3"] == pytest.approx(420.0)


@pytest.mark.parametrize("hydrogen_closed_loop_enabled", (False, True))
def test_open_main_loop_calculates_hydrogen_targets_and_trend_without_dispatch(
    tmp_path,
    hydrogen_closed_loop_enabled,
):
    snapshot = _integrated_fuel_cell_snapshot()
    snapshot["clock"] = {
        "run_id": 1,
        "step_count": 1,
        "absolute_minute": 1.0,
        "minute": 1.0,
        "time": "00:01:00",
    }
    service = SimpleNamespace(
        model_id="shared",
        service_instance_id=f"open-main-{hydrogen_closed_loop_enabled}",
        runtime_dir=tmp_path / str(hydrogen_closed_loop_enabled),
        lock=threading.RLock(),
    )
    service.runtime_dir.mkdir(parents=True)
    dispatched = []

    def snapshot_provider(_model_id):
        return TraineeControlSnapshot(
            snapshot=deepcopy(snapshot),
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

    manager = TraineeRenewableControlManager(
        service,
        snapshot_provider=snapshot_provider,
        receive_status_provider=receive_status,
        command_sink=lambda model_id, payload: dispatched.append(
            (model_id, deepcopy(payload))
        ) or {},
        start_worker=False,
    )
    try:
        state = manager._state_for("shared")
        state.loop_mode = "open"
        state.settings = _integrated_fuel_cell_settings(
            hydrogen_closed_loop_enabled=hydrogen_closed_loop_enabled
        )
        controller_state = manager.apply_action("shared", {"action": "start"})
    finally:
        manager.close()

    plan = controller_state["lastPlan"]
    hydrogen = plan["metrics"]["hydrogenControl"]
    hydrogen_row = next(
        row for row in plan["commandRows"] if row.get("dev_name") == "fuel-cell"
    )
    trend_point = controller_state["trend"][-1]
    assert controller_state["loopMode"] == "open"
    assert dispatched == []
    assert hydrogen["action"] == "fuel_cell"
    assert plan["metrics"]["fuelCellTargetKw"] == pytest.approx(11.0)
    assert hydrogen_row["commandKw"] == pytest.approx(11.0)
    assert trend_point["fuelCellTargetKw"] == pytest.approx(11.0)
    if hydrogen_closed_loop_enabled:
        assert hydrogen["dispatchMode"] == "closed-loop-atomic"
        assert plan["metrics"]["acdcTargetKw"] == pytest.approx(31.0)
        assert plan["metrics"]["acDieselTargetKw"] == pytest.approx(74.0)
    else:
        assert hydrogen["dispatchMode"] == "open-loop-preview"
        assert plan["metrics"]["acdcTargetKw"] == pytest.approx(20.0)
        assert plan["metrics"]["acDieselTargetKw"] == pytest.approx(85.0)


@pytest.mark.parametrize("hydrogen_closed_loop_enabled", (False, True))
def test_closed_main_loop_dispatches_hydrogen_only_when_hydrogen_loop_is_closed(
    tmp_path,
    hydrogen_closed_loop_enabled,
):
    snapshot = _integrated_fuel_cell_snapshot()
    snapshot["clock"] = {
        "run_id": 1,
        "step_count": 1,
        "absolute_minute": 1.0,
        "minute": 1.0,
        "time": "00:01:00",
    }
    service = SimpleNamespace(
        model_id="shared",
        service_instance_id=f"closed-main-{hydrogen_closed_loop_enabled}",
        runtime_dir=tmp_path / str(hydrogen_closed_loop_enabled),
        lock=threading.RLock(),
    )
    service.runtime_dir.mkdir(parents=True)
    dispatched = []

    manager = TraineeRenewableControlManager(
        service,
        snapshot_provider=lambda _model_id: TraineeControlSnapshot(
            snapshot=deepcopy(snapshot),
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
            "revision": 1,
            "connectionSignature": ["learner", 1],
        },
        command_sink=lambda model_id, payload: dispatched.append(
            (model_id, deepcopy(payload))
        ) or {"set_values": len(payload.get("set_values", []))},
        start_worker=False,
    )
    try:
        state = manager._state_for("shared")
        state.loop_mode = "closed"
        state.settings = _integrated_fuel_cell_settings(
            hydrogen_closed_loop_enabled=hydrogen_closed_loop_enabled
        )
        controller_state = manager.run_once(
            "shared",
            trigger="manual",
            allow_dispatch=True,
            record_log=True,
        )
    finally:
        manager.close()

    assert len(dispatched) == 1
    payload = dispatched[0][1]
    commands = {
        (row["dev_type"], row["dev_name"], row["set_type"]): row["set_value"]
        for row in payload["set_values"]
    }
    assert payload["strategy"]["loop_mode"] == "closed"
    assert controller_state["trend"][-1]["fuelCellTargetKw"] == pytest.approx(11.0)
    if hydrogen_closed_loop_enabled:
        assert payload["run_status"] == [
            {
                "dev_type": "Hydro2DcE",
                "dev_name": "fuel-coupling",
                "run_stat": 1,
            }
        ]
        assert commands[("DCGenerator", "fuel-cell", "p_set")] == pytest.approx(11.0)
        assert commands[("DCACConverter", "grid-converter", "p_ac_set")] == pytest.approx(-31.0)
        assert commands[("ACGenerator", "diesel", "p_set")] == pytest.approx(74.0)
    else:
        assert payload["run_status"] == []
        assert ("DCGenerator", "fuel-cell", "p_set") not in commands
        assert commands[("DCACConverter", "grid-converter", "p_ac_set")] == pytest.approx(-20.0)
        assert commands[("ACGenerator", "diesel", "p_set")] == pytest.approx(85.0)


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
            step_coefficient=0.1,
            electrolyzer_power_step_ratio=0.1,
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
        RenewableControlSettings(),
    )

    assert result["action"] == "blocked"
    assert rows == []
    assert any("没有在线储氢罐" in warning for warning in result["warnings"])


def test_hydrogen_start_jumps_to_deadband_threshold_when_normal_step_is_too_small():
    snapshot = _electrolyzer_snapshot(electric_power=0.0)
    snapshot["definitions"]["model"]["ACLoad"]["rows"][0]["p_min"] = 5.0
    snapshot["definitions"]["model"]["HydroSource"]["rows"][0]["flow_min"] = 1.5

    result, rows = _run_electrolyzer(
        snapshot,
        RenewableControlSettings(
            step_coefficient=0.1,
        ),
    )

    command = next(row for row in rows if row.get("dev_name") == "electrolyzer-load")
    assert result["action"] == "electrolyzer"
    assert command["commandKw"] == pytest.approx(9.5)
    assert result["commands"][0]["minimumRunningPowerKw"] == pytest.approx(7.5)
    assert result["commands"][0]["powerDeadbandKw"] == pytest.approx(2.0)
    assert result["commands"][0]["startThresholdKw"] == pytest.approx(9.5)
    assert result["commands"][0]["stepLimitKw"] < result["commands"][0]["startThresholdKw"]


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
    result = _optimize_hydrogen_within_topology_islands(
        snapshot,
        measurements,
        RenewableControlSettings(
            step_coefficient=1.0,
            fuel_cell_diesel_power_limit_kw=40.0,
        ),
        topology,
        rows,
        [{"online": True, "socKnown": True, "soc": 0.1, "socMin": 0.2}],
        diesel_current_kw=55,
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
        with pytest.raises(
            ValueError,
            match="电制氢启机SOC最小值必须大于停机SOC最大值",
        ):
            first.apply_action(
                "shared",
                {
                    "action": "update_settings",
                    "settings": {
                        "electrolyzerStorageSocStartMinimum": 0.3,
                        "electrolyzerStorageSocStopMaximum": 0.7,
                    },
                },
            )
        with pytest.raises(
            ValueError,
            match="电制氢启机柴发门槛必须小于停机柴发门槛",
        ):
            first.apply_action(
                "shared",
                {
                    "action": "update_settings",
                    "settings": {
                        "electrolyzerDieselPowerLimitRatio": 0.6,
                        "electrolyzerDieselPowerStopMaximumRatio": 0.5,
                    },
                },
            )
        with pytest.raises(
            ValueError,
            match="燃料电池启机柴发门槛必须大于停机柴发门槛",
        ):
            first.apply_action(
                "shared",
                {
                    "action": "update_settings",
                    "settings": {
                        "fuelCellDieselPowerLimitRatio": 0.3,
                        "fuelCellDieselPowerStopMinimumRatio": 0.4,
                    },
                },
            )
        saved = first.apply_action(
            "shared",
            {
                "action": "update_settings",
                "settings": {
                    "hydrogenClosedLoopEnabled": True,
                    "hydrogenPressureDeadbandRatio": 0.12,
                    "electrolyzerPowerMinRatio": 0.04,
                    "electrolyzerPowerMaxRatio": 0.42,
                    "electrolyzerPowerDeadbandRatio": 0.01,
                    "electrolyzerPowerStepRatio": 0.025,
                    "electrolyzerDieselPowerLimitRatio": 0.31,
                    "electrolyzerDieselPowerDeadbandRatio": 0.12,
                    "electrolyzerDieselPowerStopMaximumRatio": 0.55,
                    "electrolyzerStorageSocStartMinimum": 0.83,
                    "electrolyzerStorageSocStopMaximum": 0.36,
                    "electrolyzerHydrogenStorageSocStopMinimum": 0.87,
                    "fuelCellPowerMinRatio": 0.03,
                    "fuelCellPowerMaxRatio": 0.12,
                    "fuelCellPowerDeadbandRatio": 0.005,
                    "fuelCellPowerStepRatio": 0.015,
                    "fuelCellDieselPowerLimitRatio": 0.35,
                    "fuelCellDieselPowerStopMinimumRatio": 0.25,
                    "fuelCellStorageSocLimit": 0.39,
                    "fuelCellHydrogenStorageSocUpperLimit": 0.78,
                    "fuelCellHydrogenStorageSocLowerLimit": 0.24,
                },
            },
        )
        assert saved["settings"]["hydrogenClosedLoopEnabled"] is True
        assert saved["settings"]["hydrogenPressureDeadbandRatio"] == 0.12
        assert saved["settings"]["electrolyzerPowerMinRatio"] == 0.04
        assert saved["settings"]["electrolyzerDieselPowerLimitRatio"] == 0.31
        assert saved["settings"]["electrolyzerDieselPowerStopMaximumRatio"] == 0.55
        assert saved["settings"]["electrolyzerStorageSocStartMinimum"] == 0.83
        assert saved["settings"]["electrolyzerStorageSocStopMaximum"] == 0.36
        assert saved["settings"]["fuelCellDieselPowerLimitRatio"] == 0.35
        assert saved["settings"]["fuelCellDieselPowerStopMinimumRatio"] == 0.25
        assert saved["settings"]["fuelCellPowerStepRatio"] == 0.015
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
    assert reloaded["settings"]["electrolyzerPowerMaxRatio"] == 0.42
    assert reloaded["settings"]["electrolyzerDieselPowerDeadbandRatio"] == 0.12
    assert reloaded["settings"]["electrolyzerDieselPowerStopMaximumRatio"] == 0.55
    assert reloaded["settings"]["electrolyzerHydrogenStorageSocStopMinimum"] == 0.87
    assert reloaded["settings"]["fuelCellPowerDeadbandRatio"] == 0.005
    assert reloaded["settings"]["fuelCellDieselPowerStopMinimumRatio"] == 0.25
    assert reloaded["settings"]["fuelCellStorageSocLimit"] == 0.39
    assert reloaded["settings"]["fuelCellHydrogenStorageSocLowerLimit"] == 0.24
