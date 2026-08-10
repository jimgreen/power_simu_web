from __future__ import annotations

import copy
import json
import math
import inspect
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import simu.renewable_control as renewable_control_module
from simu.generate_simple_model import write_model_dir
from simu.renewable_control import (
    RenewableControlSettings,
    TraineeRenewableControlManager,
    calculate_renewable_control_plan,
)
from simu.resource_topology import ResourceTopology, resolve_resource_topology
from simu.server import make_http_server
from simu.service import MultiModelSimulator, SimulationModelSpec
from simu.trainee_exchange import TraineeControlSnapshot, TraineeRealtimeExchange
from tests.model_fixtures import SIMPLE_MODEL_SOURCE


def ready_view(snapshot, *, revision=1, age=0.0, error=None, signature=None):
    return TraineeControlSnapshot(
        snapshot=copy.deepcopy(snapshot),
        source="trainee-live" if error is None else "trainee-cache",
        age_seconds=age,
        error=error,
        receive_active=True,
        ready=True,
        revision=revision,
        connection_signature=tuple(signature or ("learner", revision)),
    )


def ready_status(_model_id):
    return {
        "receiveActive": True,
        "ready": True,
        "canRun": True,
        "revision": 1,
        "connectionSignature": ["learner", 1],
        "prerequisiteStatus": "",
    }


def mutable_receive_status(state):
    def provider(_model_id):
        active = bool(state.get("active"))
        ready = bool(state.get("ready", active))
        return {
            "receiveActive": active,
            "ready": ready,
            "canRun": active and ready,
            "revision": int(state.get("revision", 1)),
            "receiveEpoch": int(state.get("receive_epoch", 0)),
            "connectionSignature": list(state.get("signature", ("learner", 1))),
            "prerequisiteStatus": (
                ""
                if active and ready
                else "学员台正在等待第一份实时数据。"
                if active
                else "请先启动接收。"
            ),
        }

    return provider


class ExchangeBackedControlService:
    def __init__(self, runtime_dir, snapshot):
        self.model_id = "shared"
        self.runtime_dir = Path(runtime_dir)
        self.lock = threading.RLock()
        self.definition_update_lock = threading.Lock()
        self._definition_revision = 1
        self._snapshot = copy.deepcopy(snapshot)
        self._receive_state = {
            "initialized": True,
            "active": True,
            "interaction_link": "http://teacher.invalid/api/trainee-link?model_id=teacher",
            "teacher_api_base": "http://teacher.invalid",
            "snapshot_path": "/api/snapshot?model_id=teacher",
            "command_path": "/api/student/commands?model_id=teacher",
            "teacher_model_id": "teacher",
        }

    @property
    def definition_snapshot(self):
        return SimpleNamespace(revision=self._definition_revision)

    def advance_definition_revision(self):
        with self.definition_update_lock:
            self._definition_revision += 1

    def trainee_receive_state(self):
        with self.lock:
            return copy.deepcopy(self._receive_state)

    def set_trainee_receive_state(self, payload):
        with self.lock:
            self._receive_state.update(dict(payload))
            return copy.deepcopy(self._receive_state)

    def snapshot(self, **_kwargs):
        return copy.deepcopy(self._snapshot)


def make_exchange_backed_control_manager(
    runtime_dir,
    *,
    snapshot=None,
    command_sink=None,
):
    active_snapshot = snapshot if snapshot is not None else renewable_snapshot()
    service = ExchangeBackedControlService(runtime_dir, active_snapshot)
    exchange = TraineeRealtimeExchange(service, start_worker=False)
    exchange.publish_runtime_snapshot(
        "shared",
        active_snapshot,
        connection_signature=exchange._connection_signature(service),
    )
    dispatched = []
    if command_sink is None:
        command_sink = lambda model_id, payload: dispatched.append(
            (model_id, copy.deepcopy(payload))
        ) or {"set_values": len(payload.get("set_values", []))}
    manager = TraineeRenewableControlManager(
        service,
        snapshot_provider=exchange.control_snapshot,
        receive_status_provider=exchange.receive_status,
        command_sink=command_sink,
        start_worker=False,
    )
    return service, exchange, manager, dispatched


def make_control_manager(
    services,
    *,
    snapshot=None,
    snapshot_provider=None,
    receive_status_provider=ready_status,
    command_sink=None,
    start_worker=False,
):
    if snapshot_provider is None:
        active_snapshot = snapshot if snapshot is not None else renewable_snapshot()
        snapshot_provider = lambda _model_id: ready_view(active_snapshot)
    if command_sink is None:
        command_sink = lambda _model_id, payload: {
            "set_values": len(payload.get("set_values", []))
        }
    return TraineeRenewableControlManager(
        services,
        snapshot_provider=snapshot_provider,
        receive_status_provider=receive_status_provider,
        command_sink=command_sink,
        start_worker=start_worker,
    )


def make_deletable_exchange_backed_control_manager(root):
    root = Path(root)
    models_root = root / "models"
    for model_id in ("shared", "keep"):
        write_model_dir(models_root / model_id)
    services = MultiModelSimulator(
        [
            SimulationModelSpec("shared", models_root / "shared", "Shared"),
            SimulationModelSpec("keep", models_root / "keep", "Keep"),
        ],
        runtime_dir=root / "runtime",
        models_root=models_root,
        kernel=lambda _config: None,
    )
    service = services.service_for("shared")
    service.set_trainee_receive_state(
        {
            "initialized": True,
            "active": True,
            "interaction_link": "http://teacher.invalid/api/trainee-link?model_id=teacher",
            "teacher_api_base": "http://teacher.invalid",
            "snapshot_path": "/api/snapshot?model_id=teacher",
            "command_path": "/api/student/commands?model_id=teacher",
            "teacher_model_id": "teacher",
        }
    )
    snapshot = renewable_snapshot()
    exchange = TraineeRealtimeExchange(services, start_worker=False)
    exchange.publish_runtime_snapshot(
        "shared",
        snapshot,
        connection_signature=exchange._connection_signature(service),
    )

    def snapshot_provider(model_id):
        return replace(
            exchange.control_snapshot(model_id),
            snapshot=copy.deepcopy(snapshot),
            source="trainee-live",
            age_seconds=0.0,
            error=None,
            receive_active=True,
            ready=True,
        )

    manager = TraineeRenewableControlManager(
        services,
        snapshot_provider=snapshot_provider,
        receive_status_provider=exchange.receive_status,
        command_sink=exchange.submit_commands,
        start_worker=False,
    )
    return services, service, exchange, manager


def measurement(
    name: str,
    dev_type: str,
    dev_name: str,
    meas_type: str,
    value: float,
    *,
    valid: int = 1,
) -> dict:
    return {
        "name": name,
        "dev_type": dev_type,
        "dev_name": dev_name,
        "meas_type": meas_type,
        "value": value,
        "valid": valid,
    }


def definition_block(rows: list[dict]) -> dict:
    copied_rows = [dict(row) for row in rows]
    return {
        "headers": sorted({str(key) for row in copied_rows for key in row}),
        "rows": copied_rows,
    }


def append_model_row(snapshot: dict, block_name: str, row: dict) -> None:
    block = snapshot["definitions"]["model"].setdefault(
        block_name,
        definition_block([]),
    )
    block["rows"].append(dict(row))
    block["headers"] = sorted(
        {str(key) for item in block["rows"] for key in item}
    )


def add_generator_device(
    snapshot: dict,
    *,
    dev_type: str,
    name: str,
    idx: int,
    node: int,
    mode: str,
    power_kw: float,
    rated_capacity_kw: float,
    set_type: str | None = None,
    soc: float | None = None,
) -> None:
    raw = {
        "idx": str(idx),
        "node": str(node),
        "rated_capacity": str(rated_capacity_kw),
    }
    snapshot["devices"].append(
        {
            "dev_type": dev_type,
            "model_block": dev_type,
            "dev_name": name,
            "run_stat": 1,
            "status": 1,
            "mode": mode,
            "set_types": [set_type] if set_type else [],
            "raw": raw,
        }
    )
    append_model_row(
        snapshot,
        dev_type,
        {
            "idx": idx,
            "name": name,
            "node": node,
            "control_type": mode,
            "run_stat": 1,
        },
    )
    snapshot["measurements"]["scada"].append(
        measurement(f"{name}.p", dev_type, name, "P_GEN", power_kw)
    )
    if soc is not None:
        snapshot["measurements"]["scada"].append(
            measurement(f"{name}.soc", dev_type, name, "SOC", soc)
        )
    if set_type:
        snapshot["definitions"]["control"]["SetValue"]["rows"].append(
            {"dev_type": dev_type, "dev_name": name, "set_type": set_type}
        )


def renewable_snapshot() -> dict:
    devices = [
        {
            "dev_type": "ACGenerator",
            "model_block": "ACGenerator",
            "dev_name": "wind-1",
            "run_stat": 1,
            "status": 1,
            "mode": "P",
            "set_types": ["p_set"],
            "raw": {
                "idx": "1",
                "node": "1",
                "rated_capacity": "100",
                "p_min": "0",
            },
        },
        {
            "dev_type": "DCGenerator",
            "model_block": "DCGenerator",
            "dev_name": "pv-1",
            "run_stat": 1,
            "status": 1,
            "mode": "P",
            "set_types": ["p_set"],
            "raw": {
                "idx": "1",
                "node": "1",
                "rated_capacity": "80",
                "p_min": "0",
            },
        },
        {
            "dev_type": "DCGenerator",
            "model_block": "DCGenerator",
            "dev_name": "storage-1",
            "run_stat": 1,
            "status": 1,
            "mode": "V",
            "set_types": ["v_set"],
            "raw": {"idx": "2", "node": "2", "rated_capacity": "100"},
        },
        {
            "dev_type": "ACGenerator",
            "model_block": "ACGenerator",
            "dev_name": "diesel-1",
            "run_stat": 1,
            "status": 1,
            "mode": "PH",
            "set_types": ["p_set"],
            "raw": {
                "idx": "2",
                "node": "2",
                "dev_type": "diesel-source",
                "rated_capacity": "200",
                "p_min": "20",
            },
        },
        {
            "dev_type": "DCACConverter",
            "model_block": "DCACConverter",
            "dev_name": "grid-converter-1",
            "run_stat": 1,
            "status": 1,
            "mode": "PQ",
            "set_types": ["p_ac_set"],
            "raw": {
                "idx": "1",
                "dev_type": "grid-dcac-converter",
                "ac_node": "2",
                "dc_node": "3",
                "rated_capacity": "50",
                "p_ac_min": "-50",
                "p_ac_max": "50",
                "ac_control_type": "PQ",
            },
        },
        {
            "dev_type": "ACLoad",
            "model_block": "ACLoad",
            "dev_name": "load-1",
            "run_stat": 1,
            "status": 1,
            "raw": {"idx": "1", "node": "2", "pv0": "999"},
        },
    ]
    scada = [
        measurement("wind.p", "ACGenerator", "wind-1", "P_GEN", 30),
        measurement("pv.p", "DCGenerator", "pv-1", "P_GEN", 20),
        measurement("storage.p", "DCGenerator", "storage-1", "P_GEN", -5),
        measurement("storage.soc", "DCGenerator", "storage-1", "SOC", 0.5),
        measurement("diesel.p", "ACGenerator", "diesel-1", "P_GEN", 60),
        measurement("converter.p", "DCACConverter", "grid-converter-1", "P_AC", 0),
        measurement("load.p", "ACLoad", "load-1", "P_LOAD", 100),
        measurement("weather.wind", "Environment", "weather", "WIND_SPEED", 8),
        measurement("weather.solar", "Environment", "weather", "SOLAR_IRRADIANCE", 500),
        measurement("weather.temp", "Environment", "weather", "AIR_TEMP", 25),
    ]
    return {
        "model": {"id": "renewable-model", "name": "Renewable Model"},
        "clock": {
            "state": "running",
            "time": "12:00:00",
            "minute": 720,
            "absolute_minute": 720,
            "step_minutes": 1,
            "run_id": 1,
        },
        "curve_boundary": {
            "target_minute": 720,
            "load_total": 999,
            "point": {
                "wind_speed_mps": 30,
                "solar_irradiance_w_m2": 1500,
                "air_temp_c": 25,
            },
        },
        "devices": devices,
        "measurements": {"scada": scada, "real": []},
        "device_parameters": {
            "ACWindGen": [
                {
                    "idx": 1,
                    "idx_acgenerator": 1,
                    "rated_power": 100,
                    "cut_in_wind_speed": 3,
                    "rated_wind_speed": 10,
                    "cut_out_wind_speed": 25,
                }
            ],
            "DCPVGen": [
                {
                    "idx": 1,
                    "idx_dcgenerator": 1,
                    "module_efficiency": 0.2,
                    "array_area": 400,
                    "reference_irradiance": 1000,
                    "reference_temperature": 25,
                    "temp_coefficient": -0.004,
                }
            ],
            "DCStorageGen": [
                {
                    "idx": 1,
                    "idx_dcgenerator": 2,
                    "energy_capacity": 100,
                    "charge_discharge_efficiency": 0.95,
                    "max_charge_power": 40,
                    "max_discharge_power": 40,
                    "state_of_charge": 50,
                    "soc_upper_limit": 90,
                    "soc_lower_limit": 20,
                }
            ],
            "ACDieselGen": [
                {
                    "idx": 1,
                    "idx_acgenerator": 2,
                    "rated_power": 200,
                    "p_min": 20,
                }
            ],
        },
        "definitions": {
            "model": {
                "ACNode": definition_block(
                    [
                        {"idx": 1, "name": "wind-node", "run_stat": 1},
                        {"idx": 2, "name": "ac-grid-node", "run_stat": 1},
                    ]
                ),
                "DCNode": definition_block(
                    [
                        {"idx": 1, "name": "pv-node", "run_stat": 1},
                        {"idx": 2, "name": "storage-node", "run_stat": 1},
                        {"idx": 3, "name": "dc-grid-node", "run_stat": 1},
                    ]
                ),
                "ACGenerator": definition_block(
                    [
                        {
                            "idx": 1,
                            "name": "wind-1",
                            "node": 1,
                            "control_type": "P",
                            "run_stat": 1,
                        },
                        {
                            "idx": 2,
                            "name": "diesel-1",
                            "node": 2,
                            "control_type": "PH",
                            "run_stat": 1,
                        },
                    ]
                ),
                "DCGenerator": definition_block(
                    [
                        {
                            "idx": 1,
                            "name": "pv-1",
                            "node": 1,
                            "control_type": "P",
                            "run_stat": 1,
                        },
                        {
                            "idx": 2,
                            "name": "storage-1",
                            "node": 2,
                            "control_type": "V",
                            "run_stat": 1,
                        },
                    ]
                ),
                "ACLoad": definition_block(
                    [
                        {
                            "idx": 1,
                            "name": "load-1",
                            "node": 2,
                            "run_stat": 1,
                        }
                    ]
                ),
                "ACBranch": definition_block(
                    [
                        {
                            "idx": 1,
                            "name": "wind-grid-line",
                            "i_node": 1,
                            "j_node": 2,
                            "run_stat": 1,
                        }
                    ]
                ),
                "DCBranch": definition_block(
                    [
                        {
                            "idx": 1,
                            "name": "pv-grid-line",
                            "i_node": 1,
                            "j_node": 3,
                            "run_stat": 1,
                        }
                    ]
                ),
                "DCBreak": definition_block(
                    [
                        {
                            "idx": 1,
                            "name": "storage-grid-break",
                            "i_node": 2,
                            "j_node": 3,
                            "run_stat": 1,
                            "status": 1,
                        }
                    ]
                ),
                "ACRealBs": definition_block(
                    [
                        {
                            "idx": 1,
                            "name": "380V-bus",
                            "node": 2,
                            "run_stat": 1,
                        }
                    ]
                ),
                "DCRealBs": definition_block(
                    [
                        {
                            "idx": 1,
                            "name": "750V-bus",
                            "node": 3,
                            "run_stat": 1,
                        }
                    ]
                ),
                "DCACConverter": definition_block(
                    [
                        {
                            "idx": 1,
                            "name": "grid-converter-1",
                            "dev_type": "grid-dcac-converter",
                            "ac_node": 2,
                            "dc_node": 3,
                            "control_type": "PQ",
                            "p_ac_min": -50,
                            "p_ac_max": 50,
                            "run_stat": 1,
                        }
                    ]
                ),
            },
            "control": {
                "SetValue": {
                    "rows": [
                        {"dev_type": "ACGenerator", "dev_name": "wind-1", "set_type": "p_set"},
                        {"dev_type": "DCGenerator", "dev_name": "pv-1", "set_type": "p_set"},
                        {"dev_type": "DCACConverter", "dev_name": "grid-converter-1", "set_type": "p_ac_set"},
                    ]
                }
            }
        },
        "settings": {"modes": []},
    }


def add_second_dc_balance_group(
    snapshot: dict,
    *,
    prepend_converter: bool = False,
    converter_power_kw: float = -10.0,
) -> None:
    append_model_row(
        snapshot,
        "DCNode",
        {"idx": 10, "name": "second-group-dc-node", "run_stat": 1},
    )
    append_model_row(
        snapshot,
        "ACNode",
        {"idx": 10, "name": "second-group-ac-node", "run_stat": 1},
    )
    append_model_row(
        snapshot,
        "DCRealBs",
        {"idx": 2, "name": "second-group-dc-bus", "node": 10, "run_stat": 1},
    )
    append_model_row(
        snapshot,
        "ACRealBs",
        {"idx": 2, "name": "second-group-ac-bus", "node": 10, "run_stat": 1},
    )
    append_model_row(
        snapshot,
        "DCACConverter",
        {
            "idx": 2,
            "name": "second-group-converter",
            "dev_type": "grid-dcac-converter",
            "dc_node": 10,
            "ac_node": 10,
            "control_type": "PQ",
            "p_ac_min": -50,
            "p_ac_max": 50,
            "run_stat": 1,
        },
    )
    add_generator_device(
        snapshot,
        dev_type="DCGenerator",
        name="second-group-balance",
        idx=3,
        node=10,
        mode="V",
        power_kw=-40,
        rated_capacity_kw=50,
        soc=1.0,
    )
    snapshot["device_parameters"]["DCStorageGen"].append(
        {
            "idx": 2,
            "idx_dcgenerator": 3,
            "energy_capacity": 100,
            "charge_discharge_efficiency": 0.95,
            "max_charge_power": 40,
            "max_discharge_power": 40,
            "soc_upper_limit": 90,
            "soc_lower_limit": 20,
        }
    )
    snapshot["devices"].append(
        {
            "dev_type": "DCACConverter",
            "model_block": "DCACConverter",
            "dev_name": "second-group-converter",
            "run_stat": 1,
            "status": 1,
            "mode": "PQ",
            "set_types": ["p_ac_set"],
            "raw": {
                "idx": "2",
                "dev_type": "grid-dcac-converter",
                "dc_node": "10",
                "ac_node": "10",
                "rated_capacity": "50",
                "p_ac_min": "-50",
                "p_ac_max": "50",
                "ac_control_type": "PQ",
            },
        }
    )
    snapshot["measurements"]["scada"].append(
        measurement(
            "second-group-converter.p",
            "DCACConverter",
            "second-group-converter",
            "P_AC",
            converter_power_kw,
        )
    )
    snapshot["definitions"]["control"]["SetValue"]["rows"].append(
        {
            "dev_type": "DCACConverter",
            "dev_name": "second-group-converter",
            "set_type": "p_ac_set",
        }
    )
    if prepend_converter:
        converter_model_rows = snapshot["definitions"]["model"]["DCACConverter"]["rows"]
        converter_model_rows.insert(0, converter_model_rows.pop())
        converter_device = snapshot["devices"].pop()
        snapshot["devices"].insert(0, converter_device)


def direct_grid_storage_snapshot(
    *,
    diesel_power_kw: float = 31.0,
    ac_current_kw: float = 0.0,
    dc_current_kw: float = 0.0,
    ac_soc: float = 0.60,
    dc_soc: float = 0.60,
    ac_max_charge_kw: float = 40.0,
    ac_max_discharge_kw: float = 40.0,
    dc_max_charge_kw: float = 40.0,
    dc_max_discharge_kw: float = 40.0,
    ac_capacity_kwh: float = 100.0,
    dc_capacity_kwh: float = 100.0,
    ac_soc_lower_limit: float = 20.0,
    ac_soc_upper_limit: float = 90.0,
    dc_soc_lower_limit: float = 20.0,
    dc_soc_upper_limit: float = 90.0,
    include_ac_storage: bool = True,
    include_dc_storage: bool = True,
    dc_has_transfer_path: bool = True,
    converter_power_kw: float = 0.0,
    converter_capacity_kw: float = 50.0,
    step_minutes: float = 1.0,
) -> dict:
    snapshot = renewable_snapshot()
    snapshot["clock"]["step_minutes"] = step_minutes

    snapshot["devices"] = [
        row
        for row in snapshot["devices"]
        if not (
            row.get("dev_type") == "DCGenerator"
            and row.get("dev_name") == "storage-1"
        )
    ]
    snapshot["measurements"]["scada"] = [
        row
        for row in snapshot["measurements"]["scada"]
        if not (
            row.get("dev_type") == "DCGenerator"
            and row.get("dev_name") == "storage-1"
        )
    ]
    snapshot["definitions"]["model"]["DCGenerator"]["rows"] = [
        row
        for row in snapshot["definitions"]["model"]["DCGenerator"]["rows"]
        if row.get("name") != "storage-1"
    ]
    snapshot["device_parameters"]["DCStorageGen"] = []

    for row in snapshot["measurements"]["scada"]:
        if row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
            row["value"] = diesel_power_kw
        elif row["dev_name"] == "wind-1" and row["meas_type"] == "P_GEN":
            row["value"] = 100.0
        elif row["dev_name"] == "pv-1" and row["meas_type"] == "P_GEN":
            row["value"] = 80.0
        elif (
            row["dev_name"] == "grid-converter-1"
            and row["meas_type"] == "P_AC"
        ):
            row["value"] = converter_power_kw

    converter_device = next(
        row
        for row in snapshot["devices"]
        if row.get("dev_type") == "DCACConverter"
        and row.get("dev_name") == "grid-converter-1"
    )
    converter_device["raw"]["rated_capacity"] = str(converter_capacity_kw)
    converter_device["raw"]["p_ac_min"] = str(-converter_capacity_kw)
    converter_device["raw"]["p_ac_max"] = str(converter_capacity_kw)
    converter_model = next(
        row
        for row in snapshot["definitions"]["model"]["DCACConverter"]["rows"]
        if row.get("name") == "grid-converter-1"
    )
    converter_model["p_ac_min"] = -converter_capacity_kw
    converter_model["p_ac_max"] = converter_capacity_kw

    if not dc_has_transfer_path:
        append_model_row(
            snapshot,
            "DCNode",
            {"idx": 10, "name": "isolated-grid-storage-node", "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "DCRealBs",
            {
                "idx": 2,
                "name": "isolated-grid-storage-bus",
                "node": 10,
                "run_stat": 1,
            },
        )
    dc_storage_node = 3 if dc_has_transfer_path else 10

    if include_ac_storage:
        add_generator_device(
            snapshot,
            dev_type="ACGenerator",
            name="ac-grid-storage",
            idx=3,
            node=2,
            mode="P",
            power_kw=ac_current_kw,
            rated_capacity_kw=max(ac_max_charge_kw, ac_max_discharge_kw),
            set_type="p_set",
            soc=ac_soc,
        )
        snapshot["device_parameters"]["ACStorageGen"] = [
            {
                "idx": 1,
                "idx_acgenerator": 3,
                "energy_capacity": ac_capacity_kwh,
                "charge_discharge_efficiency": 1.0,
                "max_charge_power": ac_max_charge_kw,
                "max_discharge_power": ac_max_discharge_kw,
                "soc_upper_limit": ac_soc_upper_limit,
                "soc_lower_limit": ac_soc_lower_limit,
            }
        ]
    else:
        snapshot["device_parameters"]["ACStorageGen"] = []

    if include_dc_storage:
        add_generator_device(
            snapshot,
            dev_type="DCGenerator",
            name="dc-grid-storage",
            idx=3,
            node=dc_storage_node,
            mode="P",
            power_kw=dc_current_kw,
            rated_capacity_kw=max(dc_max_charge_kw, dc_max_discharge_kw),
            set_type="p_set",
            soc=dc_soc,
        )
        snapshot["device_parameters"]["DCStorageGen"] = [
            {
                "idx": 1,
                "idx_dcgenerator": 3,
                "energy_capacity": dc_capacity_kwh,
                "charge_discharge_efficiency": 1.0,
                "max_charge_power": dc_max_charge_kw,
                "max_discharge_power": dc_max_discharge_kw,
                "soc_upper_limit": dc_soc_upper_limit,
                "soc_lower_limit": dc_soc_lower_limit,
            }
        ]

    return snapshot


def add_ac_grid_storage(
    snapshot: dict,
    *,
    name: str,
    idx: int,
    current_kw: float,
    soc: float,
    max_charge_kw: float,
    max_discharge_kw: float,
) -> None:
    add_generator_device(
        snapshot,
        dev_type="ACGenerator",
        name=name,
        idx=idx,
        node=2,
        mode="P",
        power_kw=current_kw,
        rated_capacity_kw=max(max_charge_kw, max_discharge_kw),
        set_type="p_set",
        soc=soc,
    )
    snapshot["device_parameters"].setdefault("ACStorageGen", []).append(
        {
            "idx": idx,
            "idx_acgenerator": idx,
            "energy_capacity": 100.0,
            "charge_discharge_efficiency": 1.0,
            "max_charge_power": max_charge_kw,
            "max_discharge_power": max_discharge_kw,
            "soc_upper_limit": 90.0,
            "soc_lower_limit": 20.0,
        }
    )


def add_dc_grid_storage(
    snapshot: dict,
    *,
    name: str,
    idx: int,
    node: int,
    current_kw: float,
    soc: float,
    max_charge_kw: float,
    max_discharge_kw: float,
) -> None:
    add_generator_device(
        snapshot,
        dev_type="DCGenerator",
        name=name,
        idx=idx,
        node=node,
        mode="P",
        power_kw=current_kw,
        rated_capacity_kw=max(max_charge_kw, max_discharge_kw),
        set_type="p_set",
        soc=soc,
    )
    snapshot["device_parameters"].setdefault("DCStorageGen", []).append(
        {
            "idx": idx,
            "idx_dcgenerator": idx,
            "energy_capacity": 100.0,
            "charge_discharge_efficiency": 1.0,
            "max_charge_power": max_charge_kw,
            "max_discharge_power": max_discharge_kw,
            "soc_upper_limit": 90.0,
            "soc_lower_limit": 20.0,
        }
    )


def add_second_dc_grid_storage_group(
    snapshot: dict,
    *,
    storage_max_discharge_kw: float,
    converter_power_kw: float = 0.0,
    converter_capacity_kw: float = 50.0,
) -> None:
    append_model_row(
        snapshot,
        "DCNode",
        {"idx": 20, "name": "second-grid-storage-dc-node", "run_stat": 1},
    )
    append_model_row(
        snapshot,
        "ACNode",
        {"idx": 20, "name": "second-grid-storage-ac-node", "run_stat": 1},
    )
    append_model_row(
        snapshot,
        "DCRealBs",
        {
            "idx": 3,
            "name": "second-grid-storage-dc-bus",
            "node": 20,
            "run_stat": 1,
        },
    )
    append_model_row(
        snapshot,
        "ACRealBs",
        {
            "idx": 3,
            "name": "second-grid-storage-ac-bus",
            "node": 20,
            "run_stat": 1,
        },
    )
    append_model_row(
        snapshot,
        "DCACConverter",
        {
            "idx": 2,
            "name": "second-grid-storage-converter",
            "dev_type": "grid-dcac-converter",
            "dc_node": 20,
            "ac_node": 20,
            "control_type": "PQ",
            "p_ac_min": -converter_capacity_kw,
            "p_ac_max": converter_capacity_kw,
            "run_stat": 1,
        },
    )
    snapshot["devices"].append(
        {
            "dev_type": "DCACConverter",
            "model_block": "DCACConverter",
            "dev_name": "second-grid-storage-converter",
            "run_stat": 1,
            "status": 1,
            "mode": "PQ",
            "set_types": ["p_ac_set"],
            "raw": {
                "idx": "2",
                "dev_type": "grid-dcac-converter",
                "dc_node": "20",
                "ac_node": "20",
                "rated_capacity": str(converter_capacity_kw),
                "p_ac_min": str(-converter_capacity_kw),
                "p_ac_max": str(converter_capacity_kw),
                "ac_control_type": "PQ",
            },
        }
    )
    snapshot["measurements"]["scada"].append(
        measurement(
            "second-grid-storage-converter.p",
            "DCACConverter",
            "second-grid-storage-converter",
            "P_AC",
            converter_power_kw,
        )
    )
    snapshot["definitions"]["control"]["SetValue"]["rows"].append(
        {
            "dev_type": "DCACConverter",
            "dev_name": "second-grid-storage-converter",
            "set_type": "p_ac_set",
        }
    )
    add_dc_grid_storage(
        snapshot,
        name="second-dc-grid-storage",
        idx=4,
        node=20,
        current_kw=0.0,
        soc=0.60,
        max_charge_kw=40.0,
        max_discharge_kw=storage_max_discharge_kw,
    )


def reverse_snapshot_runtime_and_model_order(snapshot: dict) -> None:
    snapshot["devices"].reverse()
    snapshot["measurements"]["scada"].reverse()
    for block in snapshot["definitions"]["model"].values():
        if isinstance(block, dict) and isinstance(block.get("rows"), list):
            block["rows"].reverse()
    snapshot["definitions"]["control"]["SetValue"]["rows"].reverse()
    for rows in snapshot["device_parameters"].values():
        if isinstance(rows, list):
            rows.reverse()


def set_measurement_value(
    snapshot: dict,
    dev_type: str,
    dev_name: str,
    meas_type: str,
    value: float,
) -> None:
    row = next(
        row
        for row in snapshot["measurements"]["scada"]
        if row.get("dev_type") == dev_type
        and row.get("dev_name") == dev_name
        and row.get("meas_type") == meas_type
    )
    row["value"] = value


def side_aware_recovery_snapshot(
    *,
    diesel_power_kw: float,
    wind_power_kw: float = 100.0,
    pv_power_kw: float = 80.0,
    ac_storage: bool = False,
    dc_storage: bool = False,
    converter_power_kw: float = 0.0,
    converter_capacity_kw: float = 50.0,
) -> dict:
    snapshot = direct_grid_storage_snapshot(
        diesel_power_kw=diesel_power_kw,
        include_ac_storage=ac_storage,
        include_dc_storage=dc_storage,
        converter_power_kw=converter_power_kw,
        converter_capacity_kw=converter_capacity_kw,
    )
    set_measurement_value(
        snapshot, "ACGenerator", "wind-1", "P_GEN", wind_power_kw
    )
    set_measurement_value(
        snapshot, "DCGenerator", "pv-1", "P_GEN", pv_power_kw
    )
    return snapshot


def add_balance_storage(
    snapshot: dict,
    *,
    side: str,
    name: str,
    idx: int,
    node: int,
    current_kw: float,
    soc: float,
    max_charge_kw: float = 40.0,
    max_discharge_kw: float = 40.0,
) -> None:
    dev_type = "ACGenerator" if side == "AC" else "DCGenerator"
    block_name = "ACStorageGen" if side == "AC" else "DCStorageGen"
    reference_field = "idx_acgenerator" if side == "AC" else "idx_dcgenerator"
    add_generator_device(
        snapshot,
        dev_type=dev_type,
        name=name,
        idx=idx,
        node=node,
        mode="V",
        power_kw=current_kw,
        rated_capacity_kw=max(max_charge_kw, max_discharge_kw),
        soc=soc,
    )
    snapshot["device_parameters"].setdefault(block_name, []).append(
        {
            "idx": idx,
            reference_field: idx,
            "energy_capacity": 100.0,
            "charge_discharge_efficiency": 1.0,
            "max_charge_power": max_charge_kw,
            "max_discharge_power": max_discharge_kw,
            "soc_upper_limit": 90.0,
            "soc_lower_limit": 20.0,
        }
    )


def add_dc_load(
    snapshot: dict,
    *,
    name: str,
    idx: int,
    node: int,
    power_kw: float,
    dead_island: bool = False,
) -> None:
    append_model_row(
        snapshot,
        "DCLoad",
        {
            "idx": idx,
            "name": name,
            "node": node,
            "run_stat": 1,
            "dead_island": dead_island,
        },
    )
    snapshot["devices"].append(
        {
            "dev_type": "DCLoad",
            "model_block": "DCLoad",
            "dev_name": name,
            "run_stat": 1,
            "status": 1,
            "dead_island": dead_island,
            "raw": {"idx": str(idx), "node": str(node)},
        }
    )
    snapshot["measurements"]["scada"].append(
        measurement(f"{name}.p", "DCLoad", name, "P_LOAD", power_kw)
    )


TASK8_METRIC_KEYS = (
    "acWindCurrentKw",
    "acWindTargetKw",
    "dcWindCurrentKw",
    "dcWindTargetKw",
    "acPvCurrentKw",
    "acPvTargetKw",
    "dcPvCurrentKw",
    "dcPvTargetKw",
    "acGridFollowingStorageCount",
    "dcGridFollowingStorageCount",
    "acGridFormingStorageCount",
    "dcGridFormingStorageCount",
    "acGridStorageCurrentKw",
    "acGridStorageTargetKw",
    "acGridStorageSoc",
    "dcGridStorageCurrentKw",
    "dcGridStorageTargetKw",
    "dcGridStorageSoc",
    "acBalanceStorageCurrentKw",
    "acBalanceStorageTargetKw",
    "dcBalanceStorageCurrentKw",
    "dcBalanceStorageTargetKw",
    "acBalanceStorageSoc",
    "dcBalanceStorageSoc",
    "acRenewableCurrentKw",
    "acRenewableTargetKw",
    "dcRenewableCurrentKw",
    "dcRenewableTargetKw",
    "acGridFollowingStorageCurrentKw",
    "acGridFollowingStorageTargetKw",
    "acGridFollowingStorageSoc",
    "dcGridFollowingStorageCurrentKw",
    "dcGridFollowingStorageTargetKw",
    "dcGridFollowingStorageSoc",
    "acGridFormingStorageCurrentKw",
    "acGridFormingStorageTargetKw",
    "acGridFormingStorageSoc",
    "dcGridFormingStorageCurrentKw",
    "dcGridFormingStorageTargetKw",
    "dcGridFormingStorageSoc",
    "acDieselCurrentKw",
    "acDieselMinKw",
    "acDieselTargetKw",
    "dcDieselCurrentKw",
    "dcDieselMinKw",
    "dcDieselTargetKw",
    "acLoadKw",
    "dcLoadKw",
    "totalRenewableCurrentKw",
    "totalRenewableTargetKw",
    "totalGridFollowingStorageCurrentKw",
    "totalGridFollowingStorageTargetKw",
    "totalGridFollowingStorageSoc",
    "totalGridFormingStorageCurrentKw",
    "totalGridFormingStorageTargetKw",
    "totalGridFormingStorageSoc",
    "totalDieselCurrentKw",
    "totalDieselMinKw",
    "totalDieselTargetKw",
    "totalLoadKw",
    "dcRenewableToAcKw",
    "dcTransferGroups",
)


def task8_metrics_snapshot() -> dict:
    snapshot = direct_grid_storage_snapshot(
        diesel_power_kw=60.0,
        ac_current_kw=-2.0,
        dc_current_kw=-4.0,
        ac_soc=0.20,
        dc_soc=0.80,
        ac_capacity_kwh=100.0,
        dc_capacity_kwh=300.0,
        include_ac_storage=True,
        include_dc_storage=True,
        converter_power_kw=0.0,
        converter_capacity_kw=50.0,
    )
    add_balance_storage(
        snapshot,
        side="AC",
        name="ac-balance-storage",
        idx=4,
        node=2,
        current_kw=6.0,
        soc=0.40,
    )
    add_balance_storage(
        snapshot,
        side="DC",
        name="dc-balance-storage",
        idx=4,
        node=3,
        current_kw=-8.0,
        soc=1.20,
    )
    for row in snapshot["device_parameters"]["ACStorageGen"]:
        if row.get("idx_acgenerator") == 4:
            row["energy_capacity"] = 200.0
    for row in snapshot["device_parameters"]["DCStorageGen"]:
        if row.get("idx_dcgenerator") == 4:
            row["energy_capacity"] = 400.0
    return snapshot


class RenewableControlPlannerDataQualityTest(unittest.TestCase):
    def test_automatic_commands_default_to_two_hour_validity(self):
        settings = RenewableControlSettings()

        self.assertEqual(settings.command_valid_minutes, 120.0)
        self.assertEqual(settings.payload()["commandValidMinutes"], 120.0)

    def test_grid_following_storage_step_ratio_is_configurable_and_exposed(self):
        settings = RenewableControlSettings().updated(
            {"converterStepRatio": 0.04, "storageStepRatio": 0.25}
        )

        self.assertAlmostEqual(settings.storage_step_ratio, 0.25)
        self.assertAlmostEqual(settings.payload()["storageStepRatio"], 0.25)
        self.assertAlmostEqual(settings.converter_step_ratio, 0.0)
        self.assertNotIn("converterStepRatio", settings.payload())

    def test_legacy_converter_step_setting_migrates_to_grid_storage_step(self):
        settings = RenewableControlSettings().updated(
            {"converterStepRatio": 0.04}
        )

        self.assertAlmostEqual(settings.storage_step_ratio, 0.04)
        self.assertAlmostEqual(settings.converter_step_ratio, 0.0)

    def test_ac_renewable_recovery_directly_reduces_ac_diesel(self):
        plan = calculate_renewable_control_plan(
            side_aware_recovery_snapshot(
                diesel_power_kw=50.0,
                wind_power_kw=30.0,
            ),
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.25,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["wind-1"]["commandKw"], 40.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 40.0)

    def test_dc_renewable_recovery_can_charge_local_dc_storage_without_acdc_change(self):
        plan = calculate_renewable_control_plan(
            side_aware_recovery_snapshot(
                diesel_power_kw=20.0,
                pv_power_kw=20.0,
                dc_storage=True,
            ),
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.25,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["pv-1"]["commandKw"], 28.0)
        self.assertAlmostEqual(by_name["dc-grid-storage"]["targetKw"], -8.0)
        self.assertAlmostEqual(by_name["grid-converter-1"]["commandKw"], 0.0)

    def test_dc_renewable_recovery_requires_matching_acdc_export(self):
        plan = calculate_renewable_control_plan(
            side_aware_recovery_snapshot(
                diesel_power_kw=50.0,
                pv_power_kw=20.0,
            ),
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.20,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["pv-1"]["commandKw"], 28.0)
        self.assertAlmostEqual(by_name["grid-converter-1"]["commandKw"], -8.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 42.0)

    def test_dc_renewable_holds_without_local_sink_or_group_acdc_headroom(self):
        plan = calculate_renewable_control_plan(
            side_aware_recovery_snapshot(
                diesel_power_kw=50.0,
                pv_power_kw=20.0,
                converter_power_kw=-50.0,
                converter_capacity_kw=50.0,
            ),
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.25,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["pv-1"]["commandKw"], 20.0)
        self.assertAlmostEqual(by_name["grid-converter-1"]["commandKw"], -50.0)

    def test_ac_renewable_surplus_charges_ac_storage_but_never_dc_storage(self):
        plan = calculate_renewable_control_plan(
            side_aware_recovery_snapshot(
                diesel_power_kw=20.0,
                wind_power_kw=30.0,
                ac_storage=True,
                dc_storage=True,
            ),
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.25,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["wind-1"]["commandKw"], 40.0)
        self.assertAlmostEqual(by_name["ac-grid-storage"]["targetKw"], -10.0)
        self.assertAlmostEqual(by_name["dc-grid-storage"]["targetKw"], 0.0)
        self.assertAlmostEqual(by_name["grid-converter-1"]["commandKw"], 0.0)

    def test_ac_balance_charge_allowance_is_verified_ac_renewable_sink(self):
        snapshot = side_aware_recovery_snapshot(
            diesel_power_kw=20.0,
            wind_power_kw=30.0,
            pv_power_kw=80.0,
        )
        add_balance_storage(
            snapshot,
            side="AC",
            name="healthy-ac-balance",
            idx=4,
            node=2,
            current_kw=-5.0,
            soc=0.50,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.25,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["wind-1"]["commandKw"], 40.0)
        self.assertAlmostEqual(by_name["healthy-ac-balance"]["projectedTargetKw"], -15.0)
        self.assertFalse(by_name["healthy-ac-balance"]["commandable"])
        self.assertFalse(
            any(command["dev_name"] == "healthy-ac-balance" for command in plan["commands"])
        )
        self.assertAlmostEqual(by_name["pv-1"]["commandKw"], 80.0)
        self.assertAlmostEqual(by_name["grid-converter-1"]["commandKw"], 0.0)

    def test_ac_balance_sink_holds_diesel_inside_deadband_while_absorbing_renewable(self):
        snapshot = side_aware_recovery_snapshot(
            diesel_power_kw=25.0,
            wind_power_kw=30.0,
            pv_power_kw=80.0,
        )
        add_balance_storage(
            snapshot,
            side="AC",
            name="healthy-ac-balance",
            idx=4,
            node=2,
            current_kw=-5.0,
            soc=0.50,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.25,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["wind-1"]["commandKw"], 40.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 25.0)
        self.assertAlmostEqual(by_name["healthy-ac-balance"]["projectedTargetKw"], -15.0)
        self.assertFalse(by_name["healthy-ac-balance"]["commandable"])
        self.assertFalse(
            any(command["dev_name"] == "healthy-ac-balance" for command in plan["commands"])
        )
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        self.assertAlmostEqual(by_name["pv-1"]["commandKw"], 80.0)
        self.assertAlmostEqual(by_name["grid-converter-1"]["commandKw"], 0.0)

    def test_dc_group_cannot_use_converter_or_storage_capacity_from_another_group(self):
        snapshot = side_aware_recovery_snapshot(
            diesel_power_kw=20.0,
            pv_power_kw=20.0,
            converter_capacity_kw=0.0,
        )
        add_second_dc_grid_storage_group(
            snapshot,
            storage_max_discharge_kw=40.0,
            converter_capacity_kw=50.0,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(step_coefficient=0.10),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["pv-1"]["commandKw"], 20.0)
        self.assertAlmostEqual(by_name["second-dc-grid-storage"]["targetKw"], 0.0)
        self.assertAlmostEqual(by_name["second-grid-storage-converter"]["commandKw"], 0.0)

    def test_grid_storage_charging_requires_same_path_renewable_source(self):
        snapshot = side_aware_recovery_snapshot(
            diesel_power_kw=20.0,
            ac_storage=True,
            dc_storage=True,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.25,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertGreaterEqual(by_name["ac-grid-storage"]["targetKw"], 0.0)
        self.assertGreaterEqual(by_name["dc-grid-storage"]["targetKw"], 0.0)

    def test_automatic_converter_targets_use_ac_terminal_sign_and_allow_both_directions(self):
        snapshot = renewable_snapshot()

        plan = calculate_renewable_control_plan(snapshot)
        converter_commands = [
            command
            for command in plan["commands"]
            if command["set_type"] == "p_ac_set"
        ]

        self.assertTrue(converter_commands)
        self.assertTrue(any(command["set_value"] < 0.0 for command in converter_commands))
        self.assertFalse(plan["metrics"]["converterReversePowerForbidden"])
        self.assertEqual(plan["metrics"]["converterPositiveDirection"], "AC_TO_DC")
        self.assertEqual(plan["metrics"]["converterDcPositiveDirection"], "DC_TO_AC")
        self.assertGreater(plan["metrics"]["converterTargetUpperLimitKw"], 0.0)

    def test_dc_group_load_budget_preserves_sign_and_excludes_dead_island_load(self):
        snapshot = renewable_snapshot()
        add_dc_load(
            snapshot,
            name="signed-live-dc-load",
            idx=1,
            node=3,
            power_kw=-7.0,
        )
        add_dc_load(
            snapshot,
            name="dead-dc-load",
            idx=2,
            node=3,
            power_kw=11.0,
            dead_island=True,
        )
        topology = resolve_resource_topology(snapshot, [])
        _, dc_loads = renewable_control_module._active_load_budgets(
            snapshot,
            renewable_control_module._measurement_index(snapshot),
            topology.dc_transfer_groups,
        )
        group_id = next(
            group_id
            for group_id, group in topology.dc_transfer_groups.items()
            if "3" in group.dc_nodes
        )

        self.assertAlmostEqual(dc_loads[group_id], -7.0)

    def test_positive_acdc_realtime_uses_ac_to_dc_positive_convention(self):
        plan = calculate_renewable_control_plan(
            side_aware_recovery_snapshot(
                diesel_power_kw=20.0,
                converter_power_kw=10.0,
            )
        )

        detail = "；".join(plan["decisionDetail"])
        self.assertIn("P_AC/P_AC_SET正向AC→DC", detail)
        self.assertIn("P_DC/P_DC_SET正向DC→AC", detail)
        self.assertIn("允许在设备有功上下限内双向调节", detail)

    def test_converter_p_dc_measurement_is_normalized_to_p_ac_control_sign(self):
        cases = (
            (40.0, -40.0, "DC_TO_AC"),
            (-40.0, 40.0, "AC_TO_DC"),
        )
        for measured_p_dc, expected_p_ac, physical_direction in cases:
            with self.subTest(physical_direction=physical_direction):
                snapshot = renewable_snapshot()
                converter_measurement = next(
                    row
                    for row in snapshot["measurements"]["scada"]
                    if row["dev_type"] == "DCACConverter"
                    and row["dev_name"] == "grid-converter-1"
                    and row["meas_type"] == "P_AC"
                )
                converter_measurement["meas_type"] = "P_DC"
                converter_measurement["value"] = measured_p_dc

                plan = calculate_renewable_control_plan(snapshot)
                converter_row = next(
                    row
                    for row in plan["commandRows"]
                    if row["dev_type"] == "DCACConverter"
                    and row["dev_name"] == "grid-converter-1"
                )

                self.assertAlmostEqual(converter_row["currentKw"], expected_p_ac)
                self.assertAlmostEqual(plan["metrics"]["acdcCurrentKw"], expected_p_ac)
                self.assertEqual(
                    plan["metrics"]["converterPositiveDirection"],
                    "AC_TO_DC",
                )

    def test_dc_export_is_counted_once_in_combined_diesel_prediction(self):
        plan = calculate_renewable_control_plan(
            side_aware_recovery_snapshot(
                diesel_power_kw=50.0,
                pv_power_kw=20.0,
            ),
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.20,
            ),
        )

        self.assertAlmostEqual(plan["metrics"]["candidatePowerEffectKw"], 8.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 42.0)

    def test_dc_renewable_does_not_reserve_export_from_converter_headroom_alone(self):
        plan = calculate_renewable_control_plan(
            side_aware_recovery_snapshot(
                diesel_power_kw=20.0,
                pv_power_kw=20.0,
            ),
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.20,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["pv-1"]["commandKw"], 20.0)
        self.assertAlmostEqual(by_name["grid-converter-1"]["commandKw"], 0.0)

    def test_ac_renewable_and_storage_pair_holds_diesel_inside_deadband(self):
        plan = calculate_renewable_control_plan(
            side_aware_recovery_snapshot(
                diesel_power_kw=25.0,
                wind_power_kw=30.0,
                ac_storage=True,
            ),
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.25,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}
        renewable_delta = by_name["wind-1"]["commandKw"] - 30.0
        storage_charge_delta = -min(0.0, by_name["ac-grid-storage"]["targetKw"])

        self.assertAlmostEqual(by_name["wind-1"]["commandKw"], 40.0)
        self.assertAlmostEqual(by_name["ac-grid-storage"]["targetKw"], -10.0)
        self.assertGreaterEqual(renewable_delta, storage_charge_delta)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 25.0)

    def test_dc_balance_high_soc_curtails_when_diesel_blocks_export(self):
        snapshot = side_aware_recovery_snapshot(
            diesel_power_kw=20.0,
            pv_power_kw=20.0,
        )
        add_balance_storage(
            snapshot,
            side="DC",
            name="dc-balance",
            idx=4,
            node=3,
            current_kw=-15.0,
            soc=0.95,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.20,
                converter_step_ratio=0.20,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["grid-converter-1"]["commandKw"], 0.0)
        self.assertAlmostEqual(by_name["pv-1"]["commandKw"], 5.0)
        self.assertAlmostEqual(by_name["dc-balance"]["projectedTargetKw"], 0.0)

    def test_dc_renewable_uses_same_group_balance_charge_allowance_before_acdc(self):
        snapshot = side_aware_recovery_snapshot(
            diesel_power_kw=20.0,
            pv_power_kw=20.0,
        )
        add_balance_storage(
            snapshot,
            side="DC",
            name="dc-balance",
            idx=4,
            node=3,
            current_kw=0.0,
            soc=0.50,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.20,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["pv-1"]["commandKw"], 28.0)
        self.assertAlmostEqual(by_name["dc-balance"]["projectedTargetKw"], -8.0)
        self.assertAlmostEqual(by_name["grid-converter-1"]["commandKw"], 0.0)
        self.assertFalse(by_name["dc-balance"]["commandable"])
        self.assertFalse(
            any(command["dev_name"] == "dc-balance" for command in plan["commands"])
        )

    def test_ac_balance_protection_does_not_freeze_healthy_dc_renewable_recovery(self):
        snapshot = side_aware_recovery_snapshot(
            diesel_power_kw=20.0,
            wind_power_kw=100.0,
            pv_power_kw=20.0,
            ac_storage=True,
        )
        add_balance_storage(
            snapshot,
            side="AC",
            name="low-soc-ac-balance",
            idx=4,
            node=2,
            current_kw=13.0,
            soc=0.21,
        )
        add_balance_storage(
            snapshot,
            side="DC",
            name="healthy-dc-balance",
            idx=4,
            node=3,
            current_kw=0.0,
            soc=0.50,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.20,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["pv-1"]["commandKw"], 28.0)
        self.assertLess(by_name["healthy-dc-balance"]["projectedTargetKw"], 0.0)

    def test_dc_balance_protection_does_not_freeze_healthy_ac_renewable_recovery(self):
        snapshot = side_aware_recovery_snapshot(
            diesel_power_kw=20.0,
            wind_power_kw=30.0,
            pv_power_kw=80.0,
        )
        add_balance_storage(
            snapshot,
            side="DC",
            name="low-soc-dc-balance",
            idx=4,
            node=3,
            current_kw=20.0,
            soc=0.21,
        )
        add_balance_storage(
            snapshot,
            side="AC",
            name="healthy-ac-balance",
            idx=4,
            node=2,
            current_kw=0.0,
            soc=0.50,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.20,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["wind-1"]["commandKw"], 40.0)
        self.assertLess(by_name["healthy-ac-balance"]["projectedTargetKw"], 0.0)

    def test_dc_local_load_sink_does_not_project_recovery_into_dc_balance(self):
        snapshot = side_aware_recovery_snapshot(
            diesel_power_kw=20.0,
            wind_power_kw=100.0,
            pv_power_kw=20.0,
        )
        add_dc_load(
            snapshot,
            name="same-group-dc-load",
            idx=1,
            node=3,
            power_kw=28.0,
        )
        add_balance_storage(
            snapshot,
            side="DC",
            name="dc-balance",
            idx=4,
            node=3,
            current_kw=-5.0,
            soc=0.50,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.20,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["pv-1"]["commandKw"], 28.0)
        self.assertAlmostEqual(by_name["dc-balance"]["projectedTargetKw"], -5.0)
        self.assertFalse(by_name["dc-balance"]["commandable"])
        self.assertFalse(
            any(command["dev_name"] == "dc-balance" for command in plan["commands"])
        )
        self.assertAlmostEqual(by_name["grid-converter-1"]["commandKw"], 0.0)
        self.assertFalse(
            any(
                command["dev_name"] == "grid-converter-1"
                and command["set_type"] == "p_ac_set"
                and abs(command["set_value"]) > 1e-9
                for command in plan["commands"]
            )
        )
        self.assertAlmostEqual(by_name["wind-1"]["commandKw"], 100.0)

    def test_balance_storage_above_soc_limit_stops_charging_before_renewable_curtailment(self):
        snapshot = side_aware_recovery_snapshot(
            diesel_power_kw=20.0,
            wind_power_kw=100.0,
        )
        add_balance_storage(
            snapshot,
            side="AC",
            name="ac-balance",
            idx=4,
            node=2,
            current_kw=-15.0,
            soc=0.95,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(step_coefficient=0.03),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["wind-1"]["commandKw"], 85.0)
        self.assertAlmostEqual(by_name["ac-balance"]["projectedTargetKw"], 0.0)
        self.assertLess(
            abs(by_name["ac-balance"]["projectedTargetKw"]),
            abs(by_name["ac-balance"]["currentKw"]),
        )

    def test_multiple_low_soc_balance_rows_do_not_continue_discharging(self):
        snapshot = side_aware_recovery_snapshot(
            diesel_power_kw=50.0,
            wind_power_kw=30.0,
            ac_storage=True,
        )
        add_balance_storage(
            snapshot,
            side="AC",
            name="ac-balance-a",
            idx=4,
            node=2,
            current_kw=10.0,
            soc=0.10,
        )
        add_balance_storage(
            snapshot,
            side="AC",
            name="ac-balance-b",
            idx=5,
            node=2,
            current_kw=20.0,
            soc=0.10,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.25,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}
        first = by_name["ac-balance-a"]
        second = by_name["ac-balance-b"]
        self.assertLessEqual(first["projectedTargetKw"], 0.0)
        self.assertLessEqual(second["projectedTargetKw"], 0.0)
        self.assertLessEqual(
            first["projectedTargetKw"] + second["projectedTargetKw"],
            0.0,
        )
        self.assertTrue(first["indirectControlDevices"])
        self.assertTrue(second["indirectControlDevices"])
        self.assertFalse(first["commandable"])
        self.assertFalse(second["commandable"])
        self.assertFalse(
            any(
                command["dev_name"] in {"ac-balance-a", "ac-balance-b"}
                for command in plan["commands"]
            )
        )

    def test_ac_balance_low_soc_discharge_uses_ac_actions_in_protective_order(self):
        snapshot = side_aware_recovery_snapshot(
            diesel_power_kw=50.0,
            wind_power_kw=30.0,
            ac_storage=True,
        )
        add_balance_storage(
            snapshot,
            side="AC",
            name="ac-balance",
            idx=4,
            node=2,
            current_kw=15.0,
            soc=0.10,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.25,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["wind-1"]["commandKw"], 40.0)
        self.assertAlmostEqual(by_name["ac-grid-storage"]["targetKw"], 5.0)
        self.assertAlmostEqual(by_name["ac-balance"]["projectedTargetKw"], 0.0)
        self.assertFalse(by_name["ac-balance"]["commandable"])
        self.assertTrue(by_name["ac-balance"]["indirectControlDevices"])
        self.assertFalse(
            any(command["dev_name"] == "ac-balance" for command in plan["commands"])
        )

    def test_ac_balance_high_soc_charge_moves_to_ac_grid_storage_then_curtails_ac_renewable(self):
        snapshot = side_aware_recovery_snapshot(
            diesel_power_kw=20.0,
            wind_power_kw=100.0,
            ac_storage=True,
        )
        add_balance_storage(
            snapshot,
            side="AC",
            name="ac-balance",
            idx=4,
            node=2,
            current_kw=-15.0,
            soc=0.95,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.25,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["ac-grid-storage"]["targetKw"], -10.0)
        self.assertAlmostEqual(by_name["wind-1"]["commandKw"], 95.0)
        self.assertAlmostEqual(by_name["ac-balance"]["projectedTargetKw"], 0.0)
        self.assertFalse(by_name["ac-balance"]["commandable"])
        self.assertFalse(
            any(command["dev_name"] == "ac-balance" for command in plan["commands"])
        )

    def test_dc_balance_low_soc_discharge_uses_only_same_group_actions(self):
        snapshot = side_aware_recovery_snapshot(
            diesel_power_kw=50.0,
            pv_power_kw=20.0,
            dc_storage=True,
            converter_power_kw=-5.0,
        )
        add_balance_storage(
            snapshot,
            side="DC",
            name="dc-balance",
            idx=5,
            node=3,
            current_kw=15.0,
            soc=0.10,
        )
        add_second_dc_grid_storage_group(
            snapshot,
            storage_max_discharge_kw=40.0,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.25,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["grid-converter-1"]["commandKw"], 0.0)
        self.assertAlmostEqual(by_name["pv-1"]["commandKw"], 28.0)
        self.assertAlmostEqual(by_name["dc-grid-storage"]["targetKw"], 2.0)
        self.assertAlmostEqual(by_name["dc-balance"]["projectedTargetKw"], 0.0)
        self.assertAlmostEqual(by_name["second-dc-grid-storage"]["targetKw"], 0.0)
        self.assertAlmostEqual(by_name["second-grid-storage-converter"]["commandKw"], 0.0)
        self.assertFalse(by_name["dc-balance"]["commandable"])

    def test_dc_balance_high_soc_charge_uses_available_export_before_curtailment(self):
        snapshot = side_aware_recovery_snapshot(
            diesel_power_kw=50.0,
            pv_power_kw=20.0,
        )
        add_balance_storage(
            snapshot,
            side="DC",
            name="dc-balance",
            idx=4,
            node=3,
            current_kw=-15.0,
            soc=0.95,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.20,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["grid-converter-1"]["commandKw"], -15.0)
        self.assertAlmostEqual(by_name["pv-1"]["commandKw"], 20.0)
        self.assertAlmostEqual(by_name["dc-balance"]["projectedTargetKw"], 0.0)
        self.assertFalse(by_name["dc-balance"]["commandable"])
        self.assertTrue(
            all(
                command["set_value"] <= 0.0
                for command in plan["commands"]
                if command["set_type"] == "p_ac_set"
            )
        )

    def test_ac_grid_storage_discharge_precedes_dc_grid_storage(self):
        plan = calculate_renewable_control_plan(
            direct_grid_storage_snapshot(),
            RenewableControlSettings(converter_step_ratio=0.10),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}
        ac_storage = by_name["ac-grid-storage"]
        dc_storage = by_name["dc-grid-storage"]
        converter_rows = [
            row
            for row in plan["commandRows"]
            if row["dev_type"] == "DCACConverter" and row.get("commandable")
        ]

        self.assertAlmostEqual(ac_storage["currentKw"], 0.0)
        self.assertAlmostEqual(dc_storage["currentKw"], 0.0)
        self.assertAlmostEqual(ac_storage["commandKw"], 4.0)
        self.assertAlmostEqual(dc_storage["commandKw"], 1.0)
        self.assertAlmostEqual(ac_storage["targetKw"], 4.0)
        self.assertAlmostEqual(dc_storage["targetKw"], 1.0)
        self.assertAlmostEqual(plan["metrics"]["candidatePowerEffectKw"], 5.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 26.0)
        self.assertEqual(plan["metrics"]["acdcCurrentKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -1.0)
        self.assertAlmostEqual(plan["metrics"]["acdcAdjustmentKw"], -1.0)
        self.assertAlmostEqual(
            plan["metrics"]["acdcCurrentKw"],
            sum(row["currentKw"] for row in converter_rows),
        )
        self.assertAlmostEqual(
            plan["metrics"]["acdcTargetKw"],
            sum(row["commandKw"] for row in converter_rows),
        )

        commands = {
            (row["dev_type"], row["dev_name"], row["set_type"]): row["set_value"]
            for row in plan["commands"]
        }
        self.assertAlmostEqual(
            commands[("ACGenerator", "ac-grid-storage", "p_set")],
            4.0,
        )
        self.assertAlmostEqual(
            commands[("DCGenerator", "dc-grid-storage", "p_set")],
            1.0,
        )
        self.assertAlmostEqual(
            commands[("DCACConverter", "grid-converter-1", "p_ac_set")],
            -1.0,
        )

    def test_direct_storage_acdc_metrics_preserve_existing_negative_export(self):
        plan = calculate_renewable_control_plan(
            direct_grid_storage_snapshot(converter_power_kw=-10.0),
            RenewableControlSettings(converter_step_ratio=0.10),
        )
        converter_rows = [
            row
            for row in plan["commandRows"]
            if row["dev_type"] == "DCACConverter" and row.get("commandable")
        ]
        converter_commands = [
            command
            for command in plan["commands"]
            if command["set_type"] == "p_ac_set"
        ]
        metrics = plan["metrics"]

        self.assertEqual(len(converter_rows), 1)
        self.assertAlmostEqual(converter_rows[0]["currentKw"], -10.0)
        self.assertAlmostEqual(converter_rows[0]["commandKw"], -11.0)
        self.assertEqual(metrics["acdcCurrentKw"], -10.0)
        self.assertAlmostEqual(metrics["acdcTargetKw"], -11.0)
        self.assertAlmostEqual(metrics["acdcAdjustmentKw"], -1.0)
        self.assertAlmostEqual(
            metrics["acdcAdjustmentKw"],
            metrics["acdcTargetKw"] - metrics["acdcCurrentKw"],
        )
        self.assertAlmostEqual(
            metrics["acdcCurrentKw"],
            sum(row["currentKw"] for row in converter_rows),
        )
        self.assertAlmostEqual(
            metrics["acdcTargetKw"],
            sum(row["commandKw"] for row in converter_rows),
        )
        self.assertAlmostEqual(
            metrics["acdcTargetKw"],
            sum(command["set_value"] for command in converter_commands),
        )
        self.assertAlmostEqual(metrics["directStorageAcdcEffectKw"], 1.0)
        self.assertAlmostEqual(metrics["candidatePowerEffectKw"], 5.0)
        self.assertAlmostEqual(metrics["dieselTargetKw"], 26.0)
        self.assertTrue(
            all(command["set_value"] <= 0.0 for command in converter_commands)
        )

    def test_positive_acdc_realtime_is_not_forced_to_zero(self):
        plan = calculate_renewable_control_plan(
            direct_grid_storage_snapshot(converter_power_kw=10.0),
            RenewableControlSettings(converter_step_ratio=0.10),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}
        commands = {
            (row["dev_type"], row["dev_name"], row["set_type"]): row["set_value"]
            for row in plan["commands"]
        }

        self.assertAlmostEqual(by_name["grid-converter-1"]["currentKw"], 10.0)
        self.assertGreater(by_name["grid-converter-1"]["commandKw"], 0.0)
        self.assertLess(by_name["grid-converter-1"]["commandKw"], 10.0)
        self.assertTrue(by_name["grid-converter-1"]["strategyCommand"])
        self.assertGreater(
            commands[("DCACConverter", "grid-converter-1", "p_ac_set")],
            0.0,
        )
        self.assertGreater(by_name["ac-grid-storage"]["targetKw"], 0.0)
        self.assertGreater(by_name["dc-grid-storage"]["targetKw"], 0.0)
        self.assertFalse(plan["metrics"]["converterReversePowerForbidden"])

    def test_grid_storage_step_reuses_converter_ratio_and_larger_power_rating(self):
        step = renewable_control_module._grid_storage_step_kw(
            {
                "maxChargePowerKw": 40.0,
                "maxDischargePowerKw": 1.0,
            },
            RenewableControlSettings(converter_step_ratio=0.10),
        )

        self.assertAlmostEqual(step, 4.0)

    def test_dc_grid_storage_receives_only_residual_after_ac_margin(self):
        plan = calculate_renewable_control_plan(
            direct_grid_storage_snapshot(ac_max_discharge_kw=1.0),
            RenewableControlSettings(converter_step_ratio=0.10),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}
        commands = {
            (row["dev_type"], row["dev_name"], row["set_type"]): row["set_value"]
            for row in plan["commands"]
        }

        self.assertAlmostEqual(by_name["ac-grid-storage"]["targetKw"], 1.0)
        self.assertAlmostEqual(by_name["dc-grid-storage"]["targetKw"], 4.0)
        self.assertAlmostEqual(
            commands[("ACGenerator", "ac-grid-storage", "p_set")],
            1.0,
        )
        self.assertAlmostEqual(
            commands[("DCGenerator", "dc-grid-storage", "p_set")],
            4.0,
        )
        self.assertAlmostEqual(
            commands[("DCACConverter", "grid-converter-1", "p_ac_set")],
            -4.0,
        )

    def test_dc_grid_storage_residual_requires_incremental_group_export_headroom(self):
        plan = calculate_renewable_control_plan(
            direct_grid_storage_snapshot(
                ac_max_discharge_kw=1.0,
                converter_power_kw=-50.0,
            ),
            RenewableControlSettings(converter_step_ratio=0.10),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["ac-grid-storage"]["targetKw"], 1.0)
        self.assertAlmostEqual(by_name["dc-grid-storage"]["targetKw"], 0.0)
        self.assertFalse(
            any(
                command["dev_name"] == "dc-grid-storage"
                for command in plan["commands"]
            )
        )

    def test_grid_storage_allocation_is_invariant_to_runtime_and_model_order(self):
        ordered_snapshot = direct_grid_storage_snapshot(ac_max_discharge_kw=1.0)
        reversed_snapshot = direct_grid_storage_snapshot(ac_max_discharge_kw=1.0)
        reverse_snapshot_runtime_and_model_order(reversed_snapshot)

        ordered = calculate_renewable_control_plan(
            ordered_snapshot,
            RenewableControlSettings(converter_step_ratio=0.10),
        )
        reversed_plan = calculate_renewable_control_plan(
            reversed_snapshot,
            RenewableControlSettings(converter_step_ratio=0.10),
        )

        def targets(plan):
            return {
                (row["dev_type"], row["dev_name"]): row.get("targetKw")
                for row in plan["commandRows"]
                if row.get("role") == "grid_following"
            }

        def commands(plan):
            return {
                (row["dev_type"], row["dev_name"], row["set_type"]): row["set_value"]
                for row in plan["commands"]
                if row["dev_name"]
                in {
                    "ac-grid-storage",
                    "dc-grid-storage",
                    "grid-converter-1",
                }
            }

        self.assertEqual(
            targets(ordered),
            {
                ("ACGenerator", "ac-grid-storage"): 1.0,
                ("DCGenerator", "dc-grid-storage"): 4.0,
            },
        )
        self.assertEqual(reversed_plan["metrics"]["dieselTargetKw"], ordered["metrics"]["dieselTargetKw"])
        self.assertEqual(targets(reversed_plan), targets(ordered))
        self.assertEqual(commands(reversed_plan), commands(ordered))

    def test_grid_storage_diesel_deadband_never_increases_discharge(self):
        for diesel_power_kw in (20.0, 23.0, 26.0):
            with self.subTest(diesel_power_kw=diesel_power_kw):
                plan = calculate_renewable_control_plan(
                    direct_grid_storage_snapshot(diesel_power_kw=diesel_power_kw),
                    RenewableControlSettings(converter_step_ratio=0.10),
                )
                by_name = {row["dev_name"]: row for row in plan["commandRows"]}

                self.assertAlmostEqual(by_name["ac-grid-storage"]["targetKw"], 0.0)
                self.assertAlmostEqual(by_name["dc-grid-storage"]["targetKw"], 0.0)

    def test_low_diesel_reduces_existing_grid_storage_discharge_with_full_step(self):
        plan = calculate_renewable_control_plan(
            direct_grid_storage_snapshot(
                diesel_power_kw=10.0,
                ac_current_kw=4.0,
                dc_current_kw=4.0,
                ac_soc=0.22,
                dc_soc=0.22,
                converter_power_kw=-4.0,
            ),
            RenewableControlSettings(converter_step_ratio=0.10),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}
        converter = by_name["grid-converter-1"]

        self.assertAlmostEqual(by_name["ac-grid-storage"]["targetKw"], 0.0)
        self.assertAlmostEqual(by_name["dc-grid-storage"]["targetKw"], 0.0)
        self.assertAlmostEqual(converter["commandKw"], 0.0)

    def test_grid_storage_increased_discharge_uses_twenty_percent_boundary_step(self):
        cases = (
            ("diesel_boundary", 30.0, 0.60),
            ("lower_soc_deadband", 31.0, 0.22),
        )
        for name, diesel_power_kw, soc in cases:
            with self.subTest(name=name):
                plan = calculate_renewable_control_plan(
                    direct_grid_storage_snapshot(
                        diesel_power_kw=diesel_power_kw,
                        ac_soc=soc,
                        include_dc_storage=False,
                    ),
                    RenewableControlSettings(converter_step_ratio=0.10),
                )
                storage = next(
                    row
                    for row in plan["commandRows"]
                    if row["dev_name"] == "ac-grid-storage"
                )

                self.assertAlmostEqual(storage["targetKw"], 0.8)

    def test_soc_at_or_below_lower_limit_blocks_increased_discharge(self):
        for soc in (0.20, 0.10):
            with self.subTest(soc=soc):
                plan = calculate_renewable_control_plan(
                    direct_grid_storage_snapshot(ac_soc=soc, dc_soc=soc),
                    RenewableControlSettings(converter_step_ratio=0.10),
                )
                by_name = {row["dev_name"]: row for row in plan["commandRows"]}

                self.assertAlmostEqual(by_name["ac-grid-storage"]["targetKw"], 0.0)
                self.assertAlmostEqual(by_name["dc-grid-storage"]["targetKw"], 0.0)
                self.assertAlmostEqual(by_name["ac-grid-storage"]["dischargeMarginKw"], 0.0)
                self.assertAlmostEqual(by_name["dc-grid-storage"]["dischargeMarginKw"], 0.0)

    def test_soc_at_or_above_upper_limit_blocks_increased_charging(self):
        for soc in (0.90, 1.10):
            with self.subTest(soc=soc):
                plan = calculate_renewable_control_plan(
                    direct_grid_storage_snapshot(
                        diesel_power_kw=23.0,
                        ac_current_kw=-4.0,
                        ac_soc=soc,
                        include_dc_storage=False,
                    ),
                    RenewableControlSettings(converter_step_ratio=0.10),
                )
                storage = next(
                    row
                    for row in plan["commandRows"]
                    if row["dev_name"] == "ac-grid-storage"
                )

                self.assertAlmostEqual(storage["soc"], soc)
                self.assertAlmostEqual(storage["chargeMarginKw"], 0.0)
                self.assertAlmostEqual(storage["targetKw"], 0.0)

    def test_low_soc_alone_never_creates_negative_grid_storage_target(self):
        plan = calculate_renewable_control_plan(
            direct_grid_storage_snapshot(
                diesel_power_kw=23.0,
                ac_soc=0.10,
                dc_soc=0.10,
            ),
            RenewableControlSettings(converter_step_ratio=0.10),
        )
        storage_rows = [
            row
            for row in plan["commandRows"]
            if row.get("role") == "grid_following"
        ]

        self.assertTrue(storage_rows)
        self.assertTrue(all(row["targetKw"] >= 0.0 for row in storage_rows))
        self.assertFalse(
            any(
                command["dev_name"] in {"ac-grid-storage", "dc-grid-storage"}
                and command["set_value"] < 0.0
                for command in plan["commands"]
            )
        )

    def test_dc_grid_storage_without_its_own_transfer_path_cannot_reduce_ac_diesel(self):
        plan = calculate_renewable_control_plan(
            direct_grid_storage_snapshot(
                include_ac_storage=False,
                dc_has_transfer_path=False,
            ),
            RenewableControlSettings(converter_step_ratio=0.10),
        )
        storage = next(
            row
            for row in plan["commandRows"]
            if row["dev_name"] == "dc-grid-storage"
        )

        self.assertAlmostEqual(storage["targetKw"], 0.0)
        self.assertFalse(storage["commandable"])
        self.assertFalse(
            any(
                command["dev_name"] == "dc-grid-storage"
                for command in plan["commands"]
            )
        )

    def test_dc_transfer_capacity_is_not_shared_across_ac_components(self):
        snapshot = direct_grid_storage_snapshot(
            include_ac_storage=False,
            dc_max_discharge_kw=40.0,
            converter_power_kw=-50.0,
        )
        add_second_dc_grid_storage_group(
            snapshot,
            storage_max_discharge_kw=2.0,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.10),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}
        converter_rows = [
            row
            for row in plan["commandRows"]
            if row["dev_type"] == "DCACConverter" and row.get("commandable")
        ]
        converter_commands = [
            command
            for command in plan["commands"]
            if command["set_type"] == "p_ac_set"
        ]

        self.assertNotEqual(
            by_name["dc-grid-storage"]["dcTransferGroupId"],
            by_name["second-dc-grid-storage"]["dcTransferGroupId"],
        )
        self.assertAlmostEqual(by_name["dc-grid-storage"]["targetKw"], 0.0)
        self.assertAlmostEqual(by_name["second-dc-grid-storage"]["targetKw"], 0.0)
        self.assertAlmostEqual(by_name["grid-converter-1"]["commandKw"], -50.0)
        self.assertAlmostEqual(
            by_name["second-grid-storage-converter"]["commandKw"],
            0.0,
        )
        self.assertAlmostEqual(plan["metrics"]["acdcCurrentKw"], -50.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -50.0)
        self.assertAlmostEqual(plan["metrics"]["acdcAdjustmentKw"], 0.0)
        self.assertAlmostEqual(
            plan["metrics"]["acdcCurrentKw"],
            sum(row["currentKw"] for row in converter_rows),
        )
        self.assertAlmostEqual(
            plan["metrics"]["acdcTargetKw"],
            sum(row["commandKw"] for row in converter_rows),
        )
        self.assertEqual(converter_commands, [])

    def test_grid_storage_allocation_uses_margin_ratio_not_device_count(self):
        snapshot = direct_grid_storage_snapshot(
            ac_max_discharge_kw=2.0,
            include_dc_storage=False,
        )
        add_ac_grid_storage(
            snapshot,
            name="second-ac-grid-storage",
            idx=4,
            current_kw=0.0,
            soc=0.60,
            max_charge_kw=40.0,
            max_discharge_kw=8.0,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.10),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["ac-grid-storage"]["targetKw"], 5.0 / 3.0)
        self.assertAlmostEqual(
            by_name["second-ac-grid-storage"]["targetKw"],
            10.0 / 3.0,
        )

    def test_dc_group_storage_allocation_uses_margin_ratio(self):
        snapshot = direct_grid_storage_snapshot(
            include_ac_storage=False,
            dc_max_discharge_kw=2.0,
        )
        add_dc_grid_storage(
            snapshot,
            name="second-dc-grid-storage",
            idx=4,
            node=3,
            current_kw=0.0,
            soc=0.60,
            max_charge_kw=40.0,
            max_discharge_kw=8.0,
        )

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.10),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertAlmostEqual(by_name["dc-grid-storage"]["targetKw"], 5.0 / 3.0)
        self.assertAlmostEqual(
            by_name["second-dc-grid-storage"]["targetKw"],
            10.0 / 3.0,
        )

    def test_grid_storage_derating_continuously_limits_direct_candidates(self):
        cases = (
            (0.25, 16.0),
            (0.275, 18.0),
        )
        for soc, expected_target_kw in cases:
            with self.subTest(soc=soc):
                plan = calculate_renewable_control_plan(
                    direct_grid_storage_snapshot(
                        diesel_power_kw=100.0,
                        ac_soc=soc,
                        ac_soc_lower_limit=10.0,
                        include_dc_storage=False,
                    ),
                    RenewableControlSettings(converter_step_ratio=1.0),
                )
                storage = next(
                    row
                    for row in plan["commandRows"]
                    if row["dev_name"] == "ac-grid-storage"
                )

                self.assertAlmostEqual(storage["dischargePower"], expected_target_kw)
                self.assertAlmostEqual(storage["targetKw"], expected_target_kw)

    def test_one_period_energy_margin_clips_direct_storage_without_clipping_soc(self):
        discharge_plan = calculate_renewable_control_plan(
            direct_grid_storage_snapshot(
                diesel_power_kw=100.0,
                ac_soc=0.21,
                ac_capacity_kwh=1.0,
                include_dc_storage=False,
                step_minutes=60.0,
            ),
            RenewableControlSettings(converter_step_ratio=1.0),
        )
        discharge = next(
            row
            for row in discharge_plan["commandRows"]
            if row["dev_name"] == "ac-grid-storage"
        )

        charge_plan = calculate_renewable_control_plan(
            direct_grid_storage_snapshot(
                diesel_power_kw=23.0,
                ac_current_kw=-0.02,
                ac_soc=0.89,
                ac_capacity_kwh=1.0,
                include_dc_storage=False,
                step_minutes=60.0,
            ),
            RenewableControlSettings(converter_step_ratio=1.0),
        )
        charge = next(
            row
            for row in charge_plan["commandRows"]
            if row["dev_name"] == "ac-grid-storage"
        )

        self.assertAlmostEqual(discharge["soc"], 0.21)
        self.assertAlmostEqual(discharge["targetKw"], 0.01)
        self.assertAlmostEqual(charge["soc"], 0.89)
        self.assertAlmostEqual(charge["targetKw"], -0.01)

    def test_negative_grid_storage_realtime_power_remains_signed_in_planning_baseline(self):
        plan = calculate_renewable_control_plan(
            direct_grid_storage_snapshot(
                ac_current_kw=-5.0,
                include_dc_storage=False,
            ),
            RenewableControlSettings(converter_step_ratio=0.10),
        )
        storage = next(
            row
            for row in plan["commandRows"]
            if row["dev_name"] == "ac-grid-storage"
        )

        self.assertAlmostEqual(storage["currentKw"], -5.0)
        self.assertAlmostEqual(storage["planningCurrentKw"], -5.0)
        self.assertAlmostEqual(storage["targetKw"], -1.0)
        self.assertGreater(storage["dischargeMarginKw"], 0.0)

    def test_bad_direct_storage_input_disables_only_that_storage(self):
        def remove_measurement(snapshot, meas_type):
            snapshot["measurements"]["scada"] = [
                row
                for row in snapshot["measurements"]["scada"]
                if not (
                    row.get("dev_name") == "ac-grid-storage"
                    and row.get("meas_type") == meas_type
                )
            ]

        def remove_control_point(snapshot):
            snapshot["definitions"]["control"]["SetValue"]["rows"] = [
                row
                for row in snapshot["definitions"]["control"]["SetValue"]["rows"]
                if row.get("dev_name") != "ac-grid-storage"
            ]

        def break_topology(snapshot):
            device = next(
                row
                for row in snapshot["devices"]
                if row.get("dev_name") == "ac-grid-storage"
            )
            device["raw"]["node"] = "99"
            model_row = next(
                row
                for row in snapshot["definitions"]["model"]["ACGenerator"]["rows"]
                if row.get("name") == "ac-grid-storage"
            )
            model_row["node"] = 99

        cases = (
            ("missing_current", lambda snapshot: remove_measurement(snapshot, "P_GEN")),
            ("missing_soc", lambda snapshot: remove_measurement(snapshot, "SOC")),
            (
                "nonfinite_limit",
                lambda snapshot: snapshot["device_parameters"]["ACStorageGen"][0].__setitem__(
                    "max_discharge_power",
                    float("nan"),
                ),
            ),
            ("missing_control_point", remove_control_point),
            ("invalid_topology", break_topology),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                snapshot = direct_grid_storage_snapshot()
                mutate(snapshot)

                plan = calculate_renewable_control_plan(
                    snapshot,
                    RenewableControlSettings(converter_step_ratio=0.10),
                )
                by_name = {row["dev_name"]: row for row in plan["commandRows"]}
                ac_storage = by_name["ac-grid-storage"]
                dc_storage = by_name["dc-grid-storage"]

                self.assertFalse(ac_storage["commandable"])
                self.assertFalse(
                    any(
                        command["dev_name"] == "ac-grid-storage"
                        for command in plan["commands"]
                    )
                )
                self.assertAlmostEqual(dc_storage["targetKw"], 4.0)
                self.assertTrue(plan["dataQuality"]["dispatchAllowed"])

    def test_duplicate_grid_storage_identity_fails_closed_without_blocking_peer(self):
        snapshot = direct_grid_storage_snapshot()
        duplicate = json.loads(
            json.dumps(
                next(
                    row
                    for row in snapshot["devices"]
                    if row.get("dev_name") == "ac-grid-storage"
                )
            )
        )
        snapshot["devices"].append(duplicate)

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.10),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}

        self.assertFalse(
            any(
                command["dev_name"] == "ac-grid-storage"
                for command in plan["commands"]
            )
        )
        self.assertAlmostEqual(by_name["dc-grid-storage"]["targetKw"], 4.0)
        self.assertTrue(
            any(
                "ac-grid-storage" in issue
                and ("重复" in issue or "歧义" in issue)
                for issue in plan["dataQuality"]["issues"]
            )
        )

    def test_storage_derating_curves_have_piecewise_linear_defaults(self):
        settings = RenewableControlSettings()

        self.assertEqual(
            settings.storage_charge_derating_curve,
            (
                (0.60, 1.00),
                (0.70, 0.50),
                (0.80, 0.30),
                (0.85, 0.15),
                (0.90, 0.00),
            ),
        )
        self.assertEqual(
            settings.storage_discharge_derating_curve,
            (
                (0.10, 0.00),
                (0.15, 0.15),
                (0.20, 0.30),
                (0.30, 0.50),
                (0.40, 1.00),
            ),
        )
        self.assertEqual(
            settings.payload()["storageChargeDeratingCurve"],
            [
                {"soc": 0.60, "powerRatio": 1.00},
                {"soc": 0.70, "powerRatio": 0.50},
                {"soc": 0.80, "powerRatio": 0.30},
                {"soc": 0.85, "powerRatio": 0.15},
                {"soc": 0.90, "powerRatio": 0.00},
            ],
        )
        self.assertEqual(
            settings.payload()["storageDischargeDeratingCurve"],
            [
                {"soc": 0.10, "powerRatio": 0.00},
                {"soc": 0.15, "powerRatio": 0.15},
                {"soc": 0.20, "powerRatio": 0.30},
                {"soc": 0.30, "powerRatio": 0.50},
                {"soc": 0.40, "powerRatio": 1.00},
            ],
        )

    def test_storage_derating_curves_accept_percentage_points(self):
        settings = RenewableControlSettings().updated(
            {
                "storageChargeDeratingCurve": [
                    {"soc": 50, "powerRatio": 100},
                    {"soc": 75, "powerRatio": 40},
                    {"soc": 90, "powerRatio": 0},
                ],
                "storageDischargeDeratingCurve": [
                    {"soc": 10, "powerRatio": 0},
                    {"soc": 25, "powerRatio": 40},
                    {"soc": 50, "powerRatio": 100},
                ],
            }
        )

        self.assertEqual(
            settings.storage_charge_derating_curve,
            ((0.50, 1.00), (0.75, 0.40), (0.90, 0.00)),
        )
        self.assertEqual(
            settings.storage_discharge_derating_curve,
            ((0.10, 0.00), (0.25, 0.40), (0.50, 1.00)),
        )
        self.assertLessEqual(
            settings.storage_charge_derating_curve[1][1],
            settings.storage_charge_derating_curve[0][1],
        )
        self.assertGreaterEqual(
            settings.storage_discharge_derating_curve[1][1],
            settings.storage_discharge_derating_curve[0][1],
        )

    def test_settings_ignore_legacy_converter_soc_power_limits(self):
        settings = RenewableControlSettings().updated(
            {
                "converterSocPowerLimits": [
                    0.0,
                    0.0,
                    0.2,
                    0.4,
                    0.4,
                    0.5,
                    0.6,
                    0.8,
                    0.8,
                    1.0,
                ]
            }
        )

        self.assertFalse(hasattr(settings, "converter_soc_power_limits"))
        self.assertNotIn("converterSocPowerLimits", settings.payload())

    def test_low_soc_piecewise_derating_limits_converter_candidate(self):
        snapshot = renewable_snapshot()
        storage_parameter = snapshot["device_parameters"]["DCStorageGen"][0]
        storage_parameter["soc_lower_limit"] = 0
        storage_parameter["soc_upper_limit"] = 100
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.25
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0.0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 200.0
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = 0.0

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=1.0),
        )
        metrics = plan["metrics"]
        converter = next(
            row for row in plan["commandRows"] if row["category"] == "交直流变流器"
        )

        self.assertAlmostEqual(metrics["converterRatedCapacityKw"], 50.0)
        self.assertAlmostEqual(metrics["converterTargetLowerLimitKw"], -50.0)
        self.assertAlmostEqual(metrics["converterTargetUpperLimitKw"], 0.0)
        self.assertAlmostEqual(metrics["storageDischargeDeratingFactor"], 0.40)
        self.assertAlmostEqual(metrics["storageDischargeBeforeDeratingKw"], 40.0)
        self.assertAlmostEqual(metrics["storageDischargeDeratingLimitKw"], 16.0)
        self.assertAlmostEqual(metrics["storageDischargeAvailable"], 16.0)
        self.assertAlmostEqual(metrics["storageTarget"], 16.0)
        self.assertAlmostEqual(metrics["acdcTargetKw"], -16.0)
        self.assertAlmostEqual(converter["availableKw"], 50.0)
        self.assertAlmostEqual(converter["commandKw"], -16.0)
        self.assertFalse(any(key.startswith("converterSoc") for key in metrics))
        self.assertTrue(any("线性插值" in line for line in plan["decisionDetail"]))

    def test_storage_derating_interpolates_between_configured_soc_points(self):
        cases = (
            ("charge", 0.75, 0.40, 16.0),
            ("discharge", 0.25, 0.40, 16.0),
            ("charge_forbidden", 0.90, 0.00, 0.0),
            ("discharge_forbidden", 0.10, 0.00, 0.0),
        )
        for direction, soc, expected_factor, expected_power in cases:
            with self.subTest(direction=direction, soc=soc):
                snapshot = renewable_snapshot()
                storage_parameter = snapshot["device_parameters"]["DCStorageGen"][0]
                storage_parameter["soc_lower_limit"] = 10
                storage_parameter["soc_upper_limit"] = 90
                for row in snapshot["measurements"]["scada"]:
                    if row["meas_type"] == "SOC":
                        row["value"] = soc
                    elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                        row["value"] = 0.0

                plan = calculate_renewable_control_plan(snapshot)
                storage = next(
                    row for row in plan["commandRows"] if row["category"] == "直流平衡储能"
                )
                factor_key = (
                    "chargeDeratingFactor" if direction.startswith("charge") else "dischargeDeratingFactor"
                )
                power_key = "chargePower" if direction.startswith("charge") else "dischargePower"

                self.assertAlmostEqual(storage[factor_key], expected_factor)
                self.assertAlmostEqual(storage[power_key], expected_power)

    def test_discharge_derating_corrects_current_excess_even_when_diesel_is_high(self):
        snapshot = renewable_snapshot()
        storage_parameter = snapshot["device_parameters"]["DCStorageGen"][0]
        storage_parameter["soc_lower_limit"] = 10
        storage_parameter["soc_upper_limit"] = 90
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.25
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 30.0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 200.0
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -30.0

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=1.0),
        )
        metrics = plan["metrics"]

        self.assertTrue(metrics["storageDischargeDeratingActive"])
        self.assertAlmostEqual(metrics["storageDischargeDeratingLimitKw"], 16.0)
        self.assertAlmostEqual(metrics["storageDischargeDeratingExcessKw"], 14.0)
        self.assertTrue(metrics["storageDeratingConstraintOverride"])
        self.assertAlmostEqual(metrics["storageTarget"], 16.0)
        self.assertAlmostEqual(metrics["acdcTargetKw"], -16.0)

    def test_charge_derating_uses_renewable_curtailment_when_diesel_is_low(self):
        snapshot = renewable_snapshot()
        storage_parameter = snapshot["device_parameters"]["DCStorageGen"][0]
        storage_parameter["soc_lower_limit"] = 10
        storage_parameter["soc_upper_limit"] = 90
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.75
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -30.0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 10.0
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = 0.0

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(step_coefficient=1.0, converter_step_ratio=1.0),
        )
        metrics = plan["metrics"]

        self.assertTrue(metrics["storageChargeDeratingActive"])
        self.assertAlmostEqual(metrics["storageChargeDeratingLimitKw"], 16.0)
        self.assertAlmostEqual(metrics["storageChargeDeratingExcessKw"], 14.0)
        self.assertEqual(metrics["storageChargeDeratingActuator"], "renewable")
        self.assertAlmostEqual(metrics["acdcTargetKw"], 0.0)
        self.assertEqual(metrics["renewableControlAction"], "curtail_charge_safety")
        self.assertAlmostEqual(metrics["renewableTarget"], 36.0)
        self.assertAlmostEqual(metrics["renewableChargeSafetyCurtailRequestKw"], 14.0)

    def test_charge_derating_holds_renewables_while_acdc_corrects(self):
        snapshot = renewable_snapshot()
        storage_parameter = snapshot["device_parameters"]["DCStorageGen"][0]
        storage_parameter["soc_lower_limit"] = 10
        storage_parameter["soc_upper_limit"] = 90
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.75
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -30.0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 60.0
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = 0.0

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(step_coefficient=1.0, converter_step_ratio=1.0),
        )
        metrics = plan["metrics"]

        self.assertEqual(metrics["storageChargeDeratingActuator"], "acdc")
        self.assertAlmostEqual(metrics["acdcTargetKw"], -14.0)
        self.assertAlmostEqual(metrics["storageTarget"], -16.0)
        self.assertTrue(metrics["converterChargeDeratingSafetyOverride"])
        self.assertEqual(metrics["renewableControlAction"], "hold_charge_derating_while_acdc_corrects")
        self.assertAlmostEqual(metrics["renewableTarget"], 50.0)

    def test_converter_automatic_target_respects_bidirectional_device_limits(self):
        cases = (
            ("low_diesel", 0.50, 10.0, 0.0, 0.0),
            ("extreme_low_soc", 0.10, 60.0, 0.0, 0.0),
            ("existing_reverse_power", 0.50, 20.0, -5.0, 5.0),
        )
        for name, soc, diesel_current, storage_current, converter_current in cases:
            with self.subTest(name=name):
                snapshot = renewable_snapshot()
                for row in snapshot["measurements"]["scada"]:
                    if row["meas_type"] == "SOC":
                        row["value"] = soc
                    elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                        row["value"] = diesel_current
                    elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                        row["value"] = storage_current
                    elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                        row["value"] = converter_current

                plan = calculate_renewable_control_plan(snapshot)
                converter_commands = [
                    row["commandKw"]
                    for row in plan["commandRows"]
                    if row["category"] == "交直流变流器"
                ]

                lower = plan["metrics"]["converterTargetLowerLimitKw"]
                upper = plan["metrics"]["converterTargetUpperLimitKw"]
                self.assertFalse(plan["metrics"]["converterReversePowerForbidden"])
                self.assertEqual(plan["metrics"]["converterPositiveDirection"], "AC_TO_DC")
                self.assertLess(lower, 0.0)
                self.assertGreater(upper, 0.0)
                self.assertGreaterEqual(plan["metrics"]["acdcDesiredTargetKw"], lower)
                self.assertLessEqual(plan["metrics"]["acdcDesiredTargetKw"], upper)
                self.assertGreaterEqual(plan["metrics"]["acdcTargetKw"], lower)
                self.assertLessEqual(plan["metrics"]["acdcTargetKw"], upper)
                self.assertTrue(all(lower <= value <= upper for value in converter_commands))
                self.assertTrue(
                    any("允许在设备有功上下限内双向调节" in line for line in plan["decisionDetail"])
                )

    def test_existing_positive_ac_to_dc_power_is_not_forced_to_zero(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20.0
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -5.0
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = 12.0

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.01),
        )

        self.assertAlmostEqual(plan["metrics"]["acdcCurrentKw"], 12.0)
        self.assertGreater(plan["metrics"]["acdcDesiredTargetKw"], 0.0)
        self.assertGreater(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertLessEqual(
            plan["metrics"]["acdcTargetKw"],
            plan["metrics"]["converterTargetUpperLimitKw"],
        )
        self.assertFalse(plan["metrics"]["converterReversePowerForbidden"])

    def test_lower_soc_deadband_reduces_export_fast_and_increases_export_slowly(self):
        settings = RenewableControlSettings(converter_step_ratio=0.10)

        cases = (
            ("increase_export", "decrease", 0.25, 0.0, 0.20, -1.0),
            ("decrease_export", "increase", 0.20, -5.0, 1.0, 5.0),
        )
        for export_direction, signed_direction, soc, converter_current, expected_scale, expected_adjustment in cases:
            with self.subTest(export_direction=export_direction, soc=soc):
                snapshot = renewable_snapshot()
                for row in snapshot["measurements"]["scada"]:
                    if row["meas_type"] == "SOC":
                        row["value"] = soc
                    elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                        row["value"] = 10.0
                    elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                        row["value"] = converter_current

                plan = calculate_renewable_control_plan(snapshot, settings)
                metrics = plan["metrics"]

                self.assertTrue(metrics["lowerSocDeadbandActive"])
                self.assertAlmostEqual(metrics["converterBaseStepKw"], 5.0)
                self.assertEqual(metrics["converterStepDirection"], signed_direction)
                self.assertEqual(metrics["converterExportStepDirection"], export_direction)
                self.assertAlmostEqual(metrics["converterStepScale"], expected_scale)
                self.assertAlmostEqual(metrics["converterStepKw"], 5.0 * expected_scale)
                self.assertAlmostEqual(metrics["acdcAdjustmentKw"], expected_adjustment)
                detail = "\n".join(plan["decisionDetail"])
                expected_text = (
                    "SOC下限死区内增加ACDC送出，采用20%步长"
                    if export_direction == "increase_export"
                    else "SOC下限死区内降低ACDC送出，保持原步长"
                )
                self.assertIn(expected_text, detail)

    def test_qinling_low_soc_boundary_uses_fast_recovery_and_slow_restart(self):
        settings = RenewableControlSettings(
            converter_step_ratio=0.05,
            diesel_power_protection_ratio=0.10,
            soc_deadband=0.10,
        )
        cases = (
            ("below_limit", 0.097, 18.0, 116.0, -216.0, 0.0, 1.0),
            ("above_limit", 0.101, 200.0, -100.0, 0.0, -3.6, 0.20),
        )
        for label, soc, diesel_current, storage_current, converter_current, expected_target, expected_scale in cases:
            with self.subTest(label=label):
                snapshot = renewable_snapshot()
                snapshot["devices"][3]["raw"].update({"rated_capacity": "300", "p_min": "0"})
                snapshot["devices"][4]["raw"]["rated_capacity"] = "360"
                snapshot["device_parameters"]["DCStorageGen"][0].update(
                    {
                        "energy_capacity": 360,
                        "max_charge_power": 360,
                        "max_discharge_power": 360,
                        "soc_lower_limit": 10,
                    }
                )
                for row in snapshot["measurements"]["scada"]:
                    if row["meas_type"] == "SOC":
                        row["value"] = soc
                    elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                        row["value"] = diesel_current
                    elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                        row["value"] = storage_current
                    elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                        row["value"] = converter_current

                plan = calculate_renewable_control_plan(snapshot, settings)
                metrics = plan["metrics"]

                self.assertTrue(metrics["lowerSocDeadbandActive"])
                self.assertAlmostEqual(metrics["converterBaseStepKw"], 18.0)
                self.assertAlmostEqual(metrics["converterStepScale"], expected_scale)
                self.assertAlmostEqual(metrics["acdcTargetKw"], expected_target)

    def test_soc_below_lower_deadband_stops_converter_export_without_step_delay(self):
        snapshot = renewable_snapshot()
        snapshot["device_parameters"]["DCStorageGen"][0].update(
            {
                "energy_capacity": 100,
                "max_charge_power": 100,
                "max_discharge_power": 100,
            }
        )
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = -0.01
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 40.0
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -40.0

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(soc_deadband=0.20, converter_step_ratio=0.10),
        )
        metrics = plan["metrics"]

        self.assertTrue(metrics["socBelowLowerDeadband"])
        self.assertTrue(metrics["converterEmergencyStopActive"])
        self.assertAlmostEqual(metrics["acdcCurrentForControlKw"], -40.0)
        self.assertAlmostEqual(metrics["acdcTargetKw"], 0.0)
        self.assertAlmostEqual(metrics["converterAppliedStepKw"], 40.0)
        self.assertIn(
            "SOC低于下限-死区，跳过常规步长限制",
            "\n".join(plan["decisionDetail"]),
        )

    def test_upper_soc_boundary_recovers_slowly_and_curtails_only_remaining_charge(self):
        settings = RenewableControlSettings(step_coefficient=0.10)

        cases = (
            ("increase", "increase", 0.85, 60.0, -5.0, 1.0 / 18.0, 51.0),
            ("decrease_limited", "decrease", 0.90, 20.0, -10.0, 10.0 / 18.0, 40.0),
            ("decrease_full", "decrease", 0.94, 20.0, -30.0, 20.0 / 18.0, 30.0),
        )
        for label, direction, soc, diesel_current, storage_current, expected_scale, expected_target in cases:
            with self.subTest(label=label, soc=soc):
                snapshot = renewable_snapshot()
                for row in snapshot["measurements"]["scada"]:
                    if row["meas_type"] == "SOC":
                        row["value"] = soc
                    elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                        row["value"] = diesel_current
                    elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                        row["value"] = storage_current

                plan = calculate_renewable_control_plan(snapshot, settings)
                metrics = plan["metrics"]

                self.assertTrue(metrics["upperSocDeadbandActive"])
                self.assertEqual(metrics["renewableStepDirection"], direction)
                self.assertAlmostEqual(metrics["renewableStepScale"], expected_scale)
                self.assertAlmostEqual(metrics["renewableEffectiveStepRatio"], 0.10 * expected_scale)
                self.assertAlmostEqual(metrics["renewableTarget"], expected_target)
                detail = "\n".join(plan["decisionDetail"])
                expected_text = (
                    "充电线性降额仅剩 1.00 kW 空间"
                    if label == "increase"
                    else "超过线性降额上限"
                )
                self.assertIn(expected_text, detail)

    def test_diesel_deadband_holds_normal_actions_but_extreme_low_soc_uses_full_step(self):
        settings = RenewableControlSettings(
            converter_step_ratio=0.10,
            diesel_power_protection_ratio=0.10,
        )
        cases = (
            (
                "hold",
                0.96,
                -5.0,
                None,
                1.0,
                0.0,
                "柴发下限死区内无功率调整，保持原步长",
            ),
            (
                "increase",
                0.20,
                -5.0,
                40.0,
                1.0,
                5.0,
                "SOC低于下限-死区，跳过常规步长限制",
            ),
        )
        for (
            direction,
            soc,
            converter_current,
            soc_lower_limit,
            expected_scale,
            expected_adjustment,
            expected_text,
        ) in cases:
            with self.subTest(direction=direction, soc=soc):
                snapshot = renewable_snapshot()
                if soc_lower_limit is not None:
                    snapshot["device_parameters"]["DCStorageGen"][0]["soc_lower_limit"] = soc_lower_limit
                for row in snapshot["measurements"]["scada"]:
                    if row["meas_type"] == "SOC":
                        row["value"] = soc
                    elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                        row["value"] = 0.0
                    elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                        row["value"] = 20.0
                    elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                        row["value"] = converter_current

                plan = calculate_renewable_control_plan(snapshot, settings)
                metrics = plan["metrics"]

                self.assertFalse(metrics["lowerSocDeadbandActive"])
                self.assertTrue(metrics["dieselDeadbandActive"])
                self.assertEqual(metrics["converterStepDirection"], direction)
                self.assertAlmostEqual(metrics["converterBaseStepKw"], 5.0)
                self.assertAlmostEqual(metrics["converterStepScale"], expected_scale)
                self.assertAlmostEqual(metrics["converterStepKw"], 5.0 * expected_scale)
                self.assertAlmostEqual(metrics["acdcAdjustmentKw"], expected_adjustment)
                detail = "\n".join(plan["decisionDetail"])
                self.assertIn(expected_text, detail)

    def test_removed_charge_source_threshold_settings_are_not_exposed(self):
        settings = RenewableControlSettings().updated(
            {
                "renewableNearZeroRatio": 0.5,
                "renewableChargeReserveRatio": 0.5,
            }
        )

        self.assertFalse(hasattr(settings, "renewable_near_zero_ratio"))
        self.assertFalse(hasattr(settings, "renewable_charge_reserve_ratio"))
        self.assertNotIn("renewableNearZeroRatio", settings.payload())
        self.assertNotIn("renewableChargeReserveRatio", settings.payload())

    def test_topology_resolver_is_called_once_with_only_linked_resources(self):
        snapshot = renewable_snapshot()
        snapshot["device_parameters"]["ACWindGen"].append(
            {
                "idx": 99,
                "idx_acgenerator": 999,
                "name": "phantom-wind",
                "rated_power": 500,
            }
        )

        self.assertTrue(hasattr(renewable_control_module, "resolve_resource_topology"))
        with patch.object(
            renewable_control_module,
            "resolve_resource_topology",
            wraps=resolve_resource_topology,
        ) as resolver:
            plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(resolver.call_count, 1)
        refs = resolver.call_args.args[1]
        self.assertEqual(
            {(ref.technology, ref.dev_type, ref.dev_name) for ref in refs},
            {
                ("wind", "ACGenerator", "wind-1"),
                ("pv", "DCGenerator", "pv-1"),
                ("storage", "DCGenerator", "storage-1"),
                ("diesel", "ACGenerator", "diesel-1"),
            },
        )
        self.assertFalse(
            any(
                row.get("dev_name") in {"phantom-wind", "ACGenerator_999"}
                for row in plan["commandRows"]
            )
        )
        self.assertFalse(
            any(command.get("dev_name") == "phantom-wind" for command in plan["commands"])
        )
        self.assertTrue(
            any(
                "ACWindGen" in issue and "999" in issue and "不存在" in issue
                for issue in plan["dataQuality"]["issues"]
            )
        )

    def test_duplicate_runtime_device_identity_disables_the_linked_resource(self):
        snapshot = renewable_snapshot()
        wind_device = next(
            row for row in snapshot["devices"] if row["dev_name"] == "wind-1"
        )
        snapshot["devices"].append(
            {
                **wind_device,
                "raw": {**wind_device["raw"], "idx": "99"},
            }
        )

        plan = calculate_renewable_control_plan(snapshot)
        wind_rows = [
            row
            for row in plan["commandRows"]
            if row.get("dev_type") == "ACGenerator"
            and row.get("dev_name") == "wind-1"
            and row.get("technology") == "wind"
        ]

        self.assertEqual(len(wind_rows), 1)
        wind = wind_rows[0]
        self.assertFalse(wind.get("resourceIdentityValid", True))
        self.assertIn("重复", wind.get("resourceIdentityDiagnostic", ""))
        self.assertIn("重复", wind["statusLabel"])
        self.assertFalse(wind["commandable"])
        self.assertFalse(wind["strategyCommand"])
        self.assertFalse(
            any(
                command["dev_type"] == "ACGenerator"
                and command["dev_name"] == "wind-1"
                for command in plan["commands"]
            )
        )
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        self.assertTrue(
            any(
                "ACGenerator.wind-1" in issue and "重复" in issue
                for issue in plan["dataQuality"]["issues"]
            )
        )

    def test_duplicate_model_identity_disables_one_linked_parameter_row(self):
        snapshot = renewable_snapshot()
        append_model_row(
            snapshot,
            "ACGenerator",
            {
                "idx": 99,
                "name": "wind-1",
                "node": 1,
                "control_type": "P",
                "run_stat": 1,
            },
        )

        plan = calculate_renewable_control_plan(snapshot)
        wind_rows = [
            row
            for row in plan["commandRows"]
            if row.get("dev_type") == "ACGenerator"
            and row.get("dev_name") == "wind-1"
            and row.get("technology") == "wind"
        ]

        self.assertEqual(len(wind_rows), 1)
        wind = wind_rows[0]
        self.assertFalse(wind.get("resourceIdentityValid", True))
        self.assertIn("模型", wind.get("resourceIdentityDiagnostic", ""))
        self.assertIn("重复", wind["statusLabel"])
        self.assertFalse(wind["commandable"])
        self.assertFalse(wind["strategyCommand"])
        self.assertFalse(
            any(
                command["dev_type"] == "ACGenerator"
                and command["dev_name"] == "wind-1"
                for command in plan["commands"]
            )
        )
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        self.assertTrue(
            any(
                "ACGenerator.wind-1" in issue and "模型" in issue and "重复" in issue
                for issue in plan["dataQuality"]["issues"]
            )
        )

    def test_duplicate_runtime_converter_identity_has_one_diagnostic_row(self):
        snapshot = renewable_snapshot()
        converter = next(
            row
            for row in snapshot["devices"]
            if row["dev_type"] == "DCACConverter"
            and row["dev_name"] == "grid-converter-1"
        )
        snapshot["devices"].append(
            {
                **converter,
                "raw": {**converter["raw"], "idx": "99"},
            }
        )

        plan = calculate_renewable_control_plan(snapshot)
        converter_rows = [
            row
            for row in plan["commandRows"]
            if row.get("dev_type") == "DCACConverter"
            and row.get("dev_name") == "grid-converter-1"
        ]

        self.assertEqual(len(converter_rows), 1)
        converter_row = converter_rows[0]
        self.assertFalse(converter_row.get("resourceIdentityValid", True))
        self.assertIn("运行设备列表", converter_row.get("resourceIdentityDiagnostic", ""))
        self.assertFalse(converter_row["commandable"])
        self.assertFalse(converter_row["strategyCommand"])
        self.assertEqual(converter_row["set_type"], "")
        self.assertAlmostEqual(converter_row["commandKw"], 0.0)
        self.assertEqual(plan["metrics"]["storageConverterCount"], 0)
        self.assertIsNone(plan["metrics"]["acdcCurrentKw"])
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertFalse(
            any(
                command["dev_type"] == "DCACConverter"
                and command["dev_name"] == "grid-converter-1"
                for command in plan["commands"]
            )
        )
        self.assertTrue(
            any(
                "DCACConverter.grid-converter-1" in issue and "重复" in issue
                for issue in plan["dataQuality"]["issues"]
            )
        )

    def test_duplicate_model_converter_identity_is_diagnostic_only(self):
        snapshot = renewable_snapshot()
        append_model_row(
            snapshot,
            "DCACConverter",
            {
                "idx": 99,
                "name": "grid-converter-1",
                "ac_node": 2,
                "dc_node": 3,
                "control_type": "PQ",
                "run_stat": 1,
            },
        )

        plan = calculate_renewable_control_plan(snapshot)
        converter_rows = [
            row
            for row in plan["commandRows"]
            if row.get("dev_type") == "DCACConverter"
            and row.get("dev_name") == "grid-converter-1"
        ]

        self.assertEqual(len(converter_rows), 1)
        converter_row = converter_rows[0]
        self.assertFalse(converter_row.get("resourceIdentityValid", True))
        self.assertIn("definitions.model", converter_row.get("resourceIdentityDiagnostic", ""))
        self.assertFalse(converter_row["commandable"])
        self.assertFalse(converter_row["strategyCommand"])
        self.assertEqual(converter_row["set_type"], "")
        self.assertEqual(plan["metrics"]["storageConverterCount"], 0)
        self.assertIsNone(plan["metrics"]["acdcCurrentKw"])
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertFalse(
            any(
                command["dev_type"] == "DCACConverter"
                and command["dev_name"] == "grid-converter-1"
                for command in plan["commands"]
            )
        )
        self.assertTrue(
            any(
                "DCACConverter.grid-converter-1" in issue
                and "definitions.model" in issue
                and "重复" in issue
                for issue in plan["dataQuality"]["issues"]
            )
        )

    def test_same_name_ac_and_dc_generators_remain_distinct_typed_identities(self):
        snapshot = renewable_snapshot()
        pv_device = next(
            row
            for row in snapshot["devices"]
            if row["dev_type"] == "DCGenerator" and row["dev_name"] == "pv-1"
        )
        pv_device["dev_name"] = "wind-1"
        next(
            row
            for row in snapshot["definitions"]["model"]["DCGenerator"]["rows"]
            if row["name"] == "pv-1"
        )["name"] = "wind-1"
        for row in snapshot["measurements"]["scada"]:
            if row["dev_type"] == "DCGenerator" and row["dev_name"] == "pv-1":
                row["dev_name"] = "wind-1"
        next(
            row
            for row in snapshot["definitions"]["control"]["SetValue"]["rows"]
            if row["dev_type"] == "DCGenerator" and row["dev_name"] == "pv-1"
        )["dev_name"] = "wind-1"

        plan = calculate_renewable_control_plan(snapshot)
        resource_rows = {
            (row["dev_type"], row["dev_name"]): row
            for row in plan["commandRows"]
            if row.get("technology") in {"wind", "pv"}
        }

        self.assertEqual(
            set(resource_rows),
            {("ACGenerator", "wind-1"), ("DCGenerator", "wind-1")},
        )
        self.assertTrue(
            all(row.get("resourceIdentityValid", True) for row in resource_rows.values())
        )
        self.assertEqual(
            {
                (command["dev_type"], command["dev_name"])
                for command in plan["commands"]
                if command["dev_name"] == "wind-1"
            },
            {("ACGenerator", "wind-1"), ("DCGenerator", "wind-1")},
        )

    def test_generator_p_ac_set_does_not_enable_renewable_dispatch(self):
        snapshot = renewable_snapshot()
        pv_device = next(
            row
            for row in snapshot["devices"]
            if row["dev_type"] == "DCGenerator" and row["dev_name"] == "pv-1"
        )
        pv_device["set_types"] = ["p_ac_set"]
        snapshot["definitions"]["control"]["SetValue"]["rows"] = [
            row
            for row in snapshot["definitions"]["control"]["SetValue"]["rows"]
            if not (
                row["dev_type"] == "DCGenerator"
                and row["dev_name"] == "pv-1"
            )
        ]
        snapshot["definitions"]["control"]["SetValue"]["rows"].append(
            {
                "dev_type": "DCGenerator",
                "dev_name": "pv-1",
                "set_type": "p_ac_set",
            }
        )

        plan = calculate_renewable_control_plan(snapshot)
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}
        pv = by_name["pv-1"]

        self.assertEqual(pv["set_type"], "")
        self.assertFalse(pv["commandable"])
        self.assertFalse(pv["strategyCommand"])
        self.assertAlmostEqual(pv["commandKw"], pv["planningCurrentKw"])
        self.assertFalse(
            any(
                command["dev_type"] == "DCGenerator"
                and command["dev_name"] == "pv-1"
                for command in plan["commands"]
            )
        )
        self.assertTrue(
            any(
                command["dev_type"] == "ACGenerator"
                and command["dev_name"] == "wind-1"
                for command in plan["commands"]
            )
        )
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        self.assertTrue(
            any(
                "pv-1" in issue and "p_set" in issue
                for issue in plan["dataQuality"]["issues"]
            )
        )

    def test_ambiguous_parameter_index_is_ignored_independent_of_row_order(self):
        def collision_snapshot(*, reverse_rows: bool) -> dict:
            snapshot = renewable_snapshot()
            add_generator_device(
                snapshot,
                dev_type="ACGenerator",
                name="wind-index-collision",
                idx=1,
                node=2,
                mode="P",
                power_kw=12.0,
                rated_capacity_kw=60.0,
                set_type="p_set",
            )
            if reverse_rows:
                device_positions = [
                    index
                    for index, row in enumerate(snapshot["devices"])
                    if row["dev_type"] == "ACGenerator"
                    and str(row["raw"].get("idx")) == "1"
                ]
                first, second = device_positions
                snapshot["devices"][first], snapshot["devices"][second] = (
                    snapshot["devices"][second],
                    snapshot["devices"][first],
                )
                model_rows = snapshot["definitions"]["model"]["ACGenerator"]["rows"]
                model_positions = [
                    index
                    for index, row in enumerate(model_rows)
                    if str(row.get("idx")) == "1"
                ]
                first, second = model_positions
                model_rows[first], model_rows[second] = (
                    model_rows[second],
                    model_rows[first],
                )
            return snapshot

        plans = []
        resolver_refs = []
        for reverse_rows in (False, True):
            with patch.object(
                renewable_control_module,
                "resolve_resource_topology",
                wraps=resolve_resource_topology,
            ) as resolver:
                plans.append(
                    calculate_renewable_control_plan(
                        collision_snapshot(reverse_rows=reverse_rows)
                    )
                )
            self.assertEqual(resolver.call_count, 1)
            resolver_refs.append(
                {
                    (ref.technology, ref.dev_type, ref.dev_name)
                    for ref in resolver.call_args.args[1]
                }
            )

        ordered, reversed_plan = plans
        expected_refs = {
            ("diesel", "ACGenerator", "diesel-1"),
            ("pv", "DCGenerator", "pv-1"),
            ("storage", "DCGenerator", "storage-1"),
        }
        self.assertEqual(resolver_refs, [expected_refs, expected_refs])
        self.assertEqual(
            reversed_plan["dataQuality"]["issues"],
            ordered["dataQuality"]["issues"],
        )
        self.assertTrue(
            any(
                "ACWindGen参数行1" in issue
                and "idx_acgenerator=1" in issue
                and "匹配到多个" in issue
                and "wind-1" in issue
                and "wind-index-collision" in issue
                for issue in ordered["dataQuality"]["issues"]
            )
        )
        ordered_metrics = copy.deepcopy(ordered["metrics"])
        reversed_metrics = copy.deepcopy(reversed_plan["metrics"])
        for metrics in (ordered_metrics, reversed_metrics):
            metrics.pop("optimizationSolveMilliseconds", None)
            for island in metrics.get("optimizationIslands", []):
                island.pop("solveMilliseconds", None)
        self.assertEqual(reversed_metrics, ordered_metrics)
        self.assertEqual(reversed_plan["commands"], ordered["commands"])
        for plan in plans:
            self.assertFalse(
                any(
                    row.get("technology") == "wind"
                    and row.get("dev_name")
                    in {"wind-1", "wind-index-collision"}
                    for row in plan["commandRows"]
                )
            )
            self.assertFalse(
                any(
                    command["dev_type"] == "ACGenerator"
                    and command["dev_name"]
                    in {"wind-1", "wind-index-collision"}
                    for command in plan["commands"]
                )
            )

    def test_renewables_are_categorized_by_real_bus_topology(self):
        snapshot = renewable_snapshot()
        append_model_row(
            snapshot,
            "ACNode",
            {"idx": 3, "name": "misleading-wind-terminal", "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "DCNode",
            {"idx": 4, "name": "misleading-wind-dc-bus-node", "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "DCRealBs",
            {"idx": 2, "name": "misleading-wind-dc-bus", "node": 4, "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "DCACConverter",
            {
                "idx": 2,
                "name": "wind-rectifier",
                "ac_node": 3,
                "dc_node": 4,
                "run_stat": 1,
            },
        )
        add_generator_device(
            snapshot,
            dev_type="ACGenerator",
            name="交流名称但直流并网",
            idx=3,
            node=3,
            mode="P",
            power_kw=-12.5,
            rated_capacity_kw=40,
            set_type="p_set",
        )
        snapshot["device_parameters"]["ACWindGen"].append(
            {"idx": 2, "idx_acgenerator": 3, "rated_power": 40}
        )

        append_model_row(
            snapshot,
            "DCNode",
            {"idx": 5, "name": "misleading-pv-terminal", "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "ACNode",
            {"idx": 4, "name": "misleading-pv-ac-bus-node", "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "ACRealBs",
            {"idx": 2, "name": "misleading-pv-ac-bus", "node": 4, "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "DCACConverter",
            {
                "idx": 3,
                "name": "pv-inverter",
                "ac_node": 4,
                "dc_node": 5,
                "run_stat": 1,
            },
        )
        add_generator_device(
            snapshot,
            dev_type="DCGenerator",
            name="直流名称但交流并网",
            idx=3,
            node=5,
            mode="P",
            power_kw=-9.25,
            rated_capacity_kw=30,
            set_type="p_set",
        )
        snapshot["device_parameters"]["DCPVGen"].append(
            {"idx": 2, "idx_dcgenerator": 3, "rated_power": 30}
        )

        plan = calculate_renewable_control_plan(snapshot)
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}
        wind = by_name["交流名称但直流并网"]
        pv = by_name["直流名称但交流并网"]

        self.assertEqual(wind["technology"], "wind")
        self.assertEqual(wind["resourceDevType"], "ACGenerator")
        self.assertEqual(wind["connectionSide"], "DC")
        self.assertEqual(wind["category"], "直流风电")
        self.assertEqual(wind["currentKw"], -12.5)
        self.assertIn(("DCACConverter", "wind-rectifier"), wind["converterPath"])
        self.assertTrue(wind["activelyConnected"])

        self.assertEqual(pv["technology"], "pv")
        self.assertEqual(pv["resourceDevType"], "DCGenerator")
        self.assertEqual(pv["connectionSide"], "AC")
        self.assertEqual(pv["category"], "交流光伏")
        self.assertEqual(pv["currentKw"], -9.25)
        self.assertIn(("DCACConverter", "pv-inverter"), pv["converterPath"])
        self.assertTrue(pv["activelyConnected"])

        topology_fields = {
            "technology",
            "resourceDevType",
            "resourceDevName",
            "connectionSide",
            "activelyConnected",
            "busbarType",
            "busbarName",
            "busbarNode",
            "structuralPath",
            "activePath",
            "converterPath",
            "gridComponentId",
            "dcTransferGroupId",
            "topologyStatusLabel",
        }
        self.assertTrue(topology_fields.issubset(wind))
        self.assertTrue(topology_fields.issubset(pv))

    def test_topology_aware_ac_dc_resources_conserve_energy_end_to_end(self):
        names = {
            "ac_wind": "name-says-dc-pv-but-ac-wind",
            "dc_pv": "name-says-ac-wind-but-dc-pv",
            "ac_grid_storage": "name-says-dc-storage-but-ac-grid",
            "dc_grid_storage": "name-says-ac-storage-but-dc-grid",
            "ac_balance_storage": "name-says-dc-balance-but-ac-balance",
            "dc_balance_storage": "name-says-ac-balance-but-dc-balance",
            "active_acdc": "grid-converter-1",
            "disconnected_acdc": "disconnected-acdc",
        }

        def rename_device(snapshot, dev_type, old_name, new_name):
            for device in snapshot["devices"]:
                if device.get("dev_type") == dev_type and device.get("dev_name") == old_name:
                    device["dev_name"] = new_name
            for row in snapshot["definitions"]["model"].get(dev_type, {}).get("rows", []):
                if row.get("name") == old_name:
                    row["name"] = new_name
            for row in snapshot["definitions"]["control"]["SetValue"]["rows"]:
                if row.get("dev_type") == dev_type and row.get("dev_name") == old_name:
                    row["dev_name"] = new_name
            for row in snapshot["measurements"]["scada"]:
                if row.get("dev_type") == dev_type and row.get("dev_name") == old_name:
                    row["dev_name"] = new_name
                    row["name"] = str(row.get("name", "")).replace(old_name, new_name, 1)

        snapshot = direct_grid_storage_snapshot(
            diesel_power_kw=25.0,
            ac_current_kw=0.0,
            dc_current_kw=-4.0,
            ac_soc=0.50,
            dc_soc=0.50,
            include_ac_storage=True,
            include_dc_storage=True,
            dc_has_transfer_path=True,
            converter_power_kw=-5.0,
            converter_capacity_kw=60.0,
        )
        set_measurement_value(snapshot, "ACGenerator", "wind-1", "P_GEN", 30.0)
        set_measurement_value(snapshot, "DCGenerator", "pv-1", "P_GEN", 20.0)
        add_balance_storage(
            snapshot,
            side="AC",
            name="ac-balance-storage",
            idx=4,
            node=2,
            current_kw=-3.0,
            soc=0.50,
            max_charge_kw=30.0,
            max_discharge_kw=30.0,
        )
        add_balance_storage(
            snapshot,
            side="DC",
            name="dc-balance-storage",
            idx=4,
            node=3,
            current_kw=0.0,
            soc=0.50,
            max_charge_kw=30.0,
            max_discharge_kw=30.0,
        )

        append_model_row(
            snapshot,
            "DCNode",
            {"idx": 10, "name": "group-b-dc-node", "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "DCRealBs",
            {"idx": 2, "name": "group-b-dc-bus", "node": 10, "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "ACNode",
            {"idx": 10, "name": "group-b-ac-node", "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "ACRealBs",
            {"idx": 2, "name": "group-b-ac-bus", "node": 10, "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "DCACConverter",
            {
                "idx": 2,
                "name": names["disconnected_acdc"],
                "dc_node": 10,
                "ac_node": 10,
                "control_type": "PQ",
                "run_stat": 0,
            },
        )
        snapshot["devices"].append(
            {
                "dev_type": "DCACConverter",
                "dev_name": names["disconnected_acdc"],
                "run_stat": 0,
                "status": 0,
                "mode": "PQ",
                "set_types": ["p_ac_set"],
                "raw": {
                    "idx": "2",
                    "dc_node": "10",
                    "ac_node": "10",
                    "rated_capacity": "500",
                    "ac_control_type": "PQ",
                },
            }
        )
        snapshot["measurements"]["scada"].append(
            measurement(
                "disconnected-acdc.p",
                "DCACConverter",
                names["disconnected_acdc"],
                "P_AC",
                25.0,
            )
        )
        snapshot["definitions"]["control"]["SetValue"]["rows"].append(
            {
                "dev_type": "DCACConverter",
                "dev_name": names["disconnected_acdc"],
                "set_type": "p_ac_set",
            }
        )
        for device in snapshot["devices"]:
            if device.get("dev_name") == "dc-grid-storage":
                device["raw"]["node"] = "10"
        for row in snapshot["definitions"]["model"]["DCGenerator"]["rows"]:
            if row.get("name") == "dc-grid-storage":
                row["node"] = 10

        rename_device(snapshot, "ACGenerator", "wind-1", names["ac_wind"])
        rename_device(snapshot, "DCGenerator", "pv-1", names["dc_pv"])
        rename_device(snapshot, "ACGenerator", "ac-grid-storage", names["ac_grid_storage"])
        rename_device(snapshot, "DCGenerator", "dc-grid-storage", names["dc_grid_storage"])
        rename_device(snapshot, "ACGenerator", "ac-balance-storage", names["ac_balance_storage"])
        rename_device(snapshot, "DCGenerator", "dc-balance-storage", names["dc_balance_storage"])

        signed_before = {
            (
                str(row.get("dev_type")),
                str(row.get("dev_name")),
                str(row.get("meas_type")),
            ): row.get("value")
            for row in snapshot["measurements"]["scada"]
            if row.get("dev_name")
            in {
                names["active_acdc"],
                names["disconnected_acdc"],
                names["ac_balance_storage"],
                names["dc_grid_storage"],
            }
        }
        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                converter_step_ratio=0.25,
            ),
        )
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}
        command_names = {command["dev_name"] for command in plan["commands"]}
        metrics = plan["metrics"]
        groups_by_id = {
            str(group["groupId"]): group for group in metrics["dcTransferGroups"]
        }
        active_group_id = by_name[names["dc_pv"]]["dcTransferGroupId"]
        inactive_group_id = by_name[names["dc_grid_storage"]]["dcTransferGroupId"]
        active_group = groups_by_id[active_group_id]
        inactive_group = groups_by_id[inactive_group_id]

        expected_categories = {
            names["ac_wind"]: ("交流风电", "AC", None),
            names["dc_pv"]: ("直流光伏", "DC", None),
            names["ac_grid_storage"]: ("交流跟网储能", "AC", "grid_following"),
            names["dc_grid_storage"]: ("直流跟网储能", "DC", "grid_following"),
            names["ac_balance_storage"]: ("交流平衡储能", "AC", "balance"),
            names["dc_balance_storage"]: ("直流平衡储能", "DC", "balance"),
        }
        for name, (category, side, role) in expected_categories.items():
            with self.subTest(resource=name):
                self.assertEqual(by_name[name]["category"], category)
                self.assertEqual(by_name[name]["connectionSide"], side)
                if role is not None:
                    self.assertEqual(by_name[name]["role"], role)
                self.assertNotIn(
                    "name-says",
                    by_name[name]["category"],
                    "category must come from topology, not the misleading display name",
                )

        self.assertEqual(len(groups_by_id), 2)
        self.assertNotEqual(active_group_id, inactive_group_id)
        self.assertTrue(active_group["active"])
        self.assertFalse(inactive_group["active"])
        self.assertEqual(
            active_group["converterDevices"],
            [{"dev_type": "DCACConverter", "dev_name": names["active_acdc"]}],
        )
        self.assertEqual(inactive_group["converterDevices"], [])
        self.assertAlmostEqual(active_group["acdcCapacityKw"], 60.0)
        self.assertAlmostEqual(inactive_group["acdcCapacityKw"], 0.0)
        self.assertAlmostEqual(inactive_group["currentGridStorageKw"], -4.0)
        self.assertAlmostEqual(inactive_group["targetGridStorageKw"], -4.0)
        self.assertFalse(
            any(
                device["dev_name"] == names["dc_grid_storage"]
                for device in active_group["affectedDevices"]
            )
        )

        self.assertNotIn(names["disconnected_acdc"], by_name)
        self.assertNotIn(names["disconnected_acdc"], command_names)
        self.assertNotIn(names["dc_grid_storage"], command_names)
        for group in (active_group, inactive_group):
            group_command_rows = [
                row
                for row in plan["commandRows"]
                if str(row.get("dcTransferGroupId", "")) == str(group["groupId"])
            ]
            group_has_dispatchable_command_row = any(
                row.get("online")
                and row.get("commandable") is not False
                and row.get("strategyCommand") is not False
                for row in group_command_rows
            )
            self.assertEqual(group["active"], group_has_dispatchable_command_row)

        self.assertTrue(
            all(
                command["set_value"] <= 0.0
                for command in plan["commands"]
                if command["set_type"] == "p_ac_set"
            )
        )
        for name in (names["ac_balance_storage"], names["dc_balance_storage"]):
            self.assertFalse(by_name[name]["commandable"])
            self.assertEqual(by_name[name]["set_type"], "")
            self.assertNotIn(name, command_names)

        ac_wind_delta = by_name[names["ac_wind"]]["commandKw"] - by_name[names["ac_wind"]]["currentKw"]
        dc_pv_delta = by_name[names["dc_pv"]]["commandKw"] - by_name[names["dc_pv"]]["currentKw"]
        renewable_delta_by_path = {
            ("AC", ""): ac_wind_delta,
            ("DC", active_group_id): dc_pv_delta,
            ("DC", inactive_group_id): 0.0,
        }
        for name in (
            names["ac_grid_storage"],
            names["dc_grid_storage"],
            names["ac_balance_storage"],
            names["dc_balance_storage"],
        ):
            row = by_name[name]
            target = row.get("targetKw") if row.get("role") == "grid_following" else row.get("projectedTargetKw")
            charge_target = max(0.0, row["currentKw"] - target)
            path_key = (row["connectionSide"], row.get("dcTransferGroupId", ""))
            with self.subTest(charging_target=name):
                self.assertLessEqual(
                    charge_target,
                    renewable_delta_by_path.get(path_key, 0.0) + 1e-6,
                )

        active_export_delta = active_group["finalAcdcExportKw"] - active_group["currentAcdcExportKw"]
        expected_diesel_effect = ac_wind_delta
        expected_diesel_effect -= max(
            0.0,
            by_name[names["ac_grid_storage"]]["currentKw"] - by_name[names["ac_grid_storage"]]["targetKw"],
        )
        expected_diesel_effect += active_export_delta
        actual_diesel_effect = metrics["dieselCurrentKw"] - metrics["dieselTargetKw"]
        self.assertAlmostEqual(active_group["currentAcdcExportKw"], 5.0)
        self.assertAlmostEqual(
            active_group["currentRenewableDeliveredThroughAcdcKw"],
            active_group["currentAcdcExportKw"],
        )
        self.assertAlmostEqual(metrics["dcRenewableToAcKw"], active_group["currentAcdcExportKw"])
        self.assertAlmostEqual(actual_diesel_effect, expected_diesel_effect)
        self.assertNotAlmostEqual(
            actual_diesel_effect,
            expected_diesel_effect + active_group["currentAcdcExportKw"],
        )

        self.assertAlmostEqual(by_name[names["active_acdc"]]["currentKw"], -5.0)
        self.assertAlmostEqual(by_name[names["ac_balance_storage"]]["currentKw"], -3.0)
        self.assertAlmostEqual(by_name[names["dc_grid_storage"]]["currentKw"], -4.0)
        self.assertAlmostEqual(metrics["acdcCurrentKw"], -5.0)
        self.assertAlmostEqual(metrics["acBalanceStorageCurrentKw"], -3.0)
        self.assertAlmostEqual(metrics["dcGridStorageCurrentKw"], -4.0)
        signed_after = {
            (
                str(row.get("dev_type")),
                str(row.get("dev_name")),
                str(row.get("meas_type")),
            ): row.get("value")
            for row in snapshot["measurements"]["scada"]
            if row.get("dev_name")
            in {
                names["active_acdc"],
                names["disconnected_acdc"],
                names["ac_balance_storage"],
                names["dc_grid_storage"],
            }
        }
        self.assertEqual(signed_after, signed_before)

    def test_storage_roles_cover_all_four_topology_categories_with_balance_p_set(self):
        snapshot = renewable_snapshot()
        add_generator_device(
            snapshot,
            dev_type="ACGenerator",
            name="ac-grid-storage",
            idx=3,
            node=2,
            mode=" p ",
            power_kw=-2.0,
            rated_capacity_kw=25,
            set_type="p_set",
            soc=0.55,
        )
        add_generator_device(
            snapshot,
            dev_type="ACGenerator",
            name="ac-balance-storage",
            idx=4,
            node=2,
            mode=" vf ",
            power_kw=3.0,
            rated_capacity_kw=25,
            set_type="p_set",
            soc=0.65,
        )
        add_generator_device(
            snapshot,
            dev_type="DCGenerator",
            name="dc-grid-storage",
            idx=3,
            node=3,
            mode=" pq ",
            power_kw=-4.0,
            rated_capacity_kw=25,
            set_type="p_set",
            soc=0.60,
        )
        snapshot["definitions"]["control"]["SetValue"]["rows"].append(
            {"dev_type": "DCGenerator", "dev_name": "storage-1", "set_type": "p_set"}
        )
        common = {
            "energy_capacity": 50,
            "charge_discharge_efficiency": 0.95,
            "max_charge_power": 20,
            "max_discharge_power": 20,
            "soc_upper_limit": 90,
            "soc_lower_limit": 20,
        }
        snapshot["device_parameters"]["ACStorageGen"] = [
            {"idx": 1, "idx_acgenerator": 3, **common},
            {"idx": 2, "idx_acgenerator": 4, **common},
        ]
        snapshot["device_parameters"]["DCStorageGen"].append(
            {"idx": 2, "idx_dcgenerator": 3, **common}
        )

        plan = calculate_renewable_control_plan(snapshot)
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}
        expected = {
            "ac-grid-storage": ("交流跟网储能", "grid_following", "AC"),
            "dc-grid-storage": ("直流跟网储能", "grid_following", "DC"),
            "ac-balance-storage": ("交流平衡储能", "balance", "AC"),
            "storage-1": ("直流平衡储能", "balance", "DC"),
        }

        for name, (category, role, side) in expected.items():
            with self.subTest(name=name):
                row = by_name[name]
                self.assertEqual(row["category"], category)
                self.assertEqual(row["role"], role)
                self.assertEqual(row["connectionSide"], side)
                self.assertEqual(row["mode"], row["mode"].strip().upper())

        for name in ("ac-grid-storage", "dc-grid-storage"):
            self.assertTrue(by_name[name]["commandable"])
            self.assertEqual(by_name[name]["set_type"], "p_set")

        for name in ("ac-balance-storage", "storage-1"):
            self.assertTrue(by_name[name]["commandable"])
            self.assertEqual(by_name[name]["set_type"], "p_set")
            self.assertIsInstance(by_name[name]["indirectControlDevices"], list)
            self.assertTrue(any(command["dev_name"] == name for command in plan["commands"]))

        metrics = plan["metrics"]
        self.assertEqual(metrics["onlineAcBalanceStorageCount"], 1)
        self.assertEqual(metrics["onlineDcBalanceStorageCount"], 1)
        self.assertEqual(metrics["onlineAcGridFollowingStorageCount"], 1)
        self.assertEqual(metrics["onlineDcGridFollowingStorageCount"], 1)
        self.assertAlmostEqual(metrics["acBalanceStorageCurrentKw"], 3.0)
        self.assertAlmostEqual(metrics["dcBalanceStorageCurrentKw"], -5.0)
        self.assertAlmostEqual(metrics["acGridFollowingStorageCurrentKw"], -2.0)
        self.assertAlmostEqual(metrics["dcGridFollowingStorageCurrentKw"], -4.0)
        self.assertEqual(
            metrics["dcBalanceControlGroupIds"],
            [by_name["storage-1"]["dcTransferGroupId"]],
        )

    def test_bad_topology_resources_stay_visible_but_never_become_commands(self):
        snapshot = renewable_snapshot()
        append_model_row(
            snapshot,
            "ACNode",
            {"idx": 10, "name": "unresolved-node", "run_stat": 1},
        )
        add_generator_device(
            snapshot,
            dev_type="ACGenerator",
            name="unresolved-wind",
            idx=3,
            node=10,
            mode="P",
            power_kw=5,
            rated_capacity_kw=20,
            set_type="p_set",
        )
        snapshot["device_parameters"]["ACWindGen"].append(
            {"idx": 2, "idx_acgenerator": 3, "rated_power": 20}
        )

        add_generator_device(
            snapshot,
            dev_type="DCGenerator",
            name="invalid-pv",
            idx=3,
            node=99,
            mode="P",
            power_kw=6,
            rated_capacity_kw=20,
            set_type="p_set",
        )
        snapshot["device_parameters"]["DCPVGen"].append(
            {"idx": 2, "idx_dcgenerator": 3, "rated_power": 20}
        )

        add_generator_device(
            snapshot,
            dev_type="ACGenerator",
            name="ambiguous-wind",
            idx=4,
            node=2,
            mode="P",
            power_kw=7,
            rated_capacity_kw=20,
            set_type="p_set",
        )
        snapshot["device_parameters"]["ACWindGen"].append(
            {"idx": 3, "idx_acgenerator": 4, "rated_power": 20}
        )

        self.assertTrue(hasattr(renewable_control_module, "resolve_resource_topology"))

        def force_one_ambiguous(snapshot_arg, resources):
            topology = resolve_resource_topology(snapshot_arg, resources)
            connections = dict(topology.resources)
            key = ("ACGenerator", "ambiguous-wind")
            connections[key] = replace(
                connections[key],
                connection_side="AMBIGUOUS",
                actively_connected=False,
                busbar_type="",
                busbar_name="",
                busbar_node="",
                structural_path=(),
                active_path=(),
                converter_path=(),
                grid_component_id="",
                dc_transfer_group_id="",
                topology_status_label="交流/直流真实母线路径等价，拓扑歧义",
            )
            return ResourceTopology(
                resources=MappingProxyType(connections),
                dc_transfer_groups=topology.dc_transfer_groups,
            )

        with patch.object(
            renewable_control_module,
            "resolve_resource_topology",
            side_effect=force_one_ambiguous,
        ) as resolver:
            plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(resolver.call_count, 1)
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}
        expected = {
            "unresolved-wind": "UNRESOLVED",
            "ambiguous-wind": "AMBIGUOUS",
            "invalid-pv": "INVALID",
        }
        for name, status in expected.items():
            with self.subTest(name=name):
                row = by_name[name]
                self.assertEqual(row["connectionSide"], status)
                self.assertEqual(row["category"], "拓扑未解析新能源")
                self.assertFalse(row["activelyConnected"])
                self.assertFalse(row["online"])
                self.assertFalse(row["commandable"])
                self.assertTrue(row["topologyStatusLabel"])
                self.assertFalse(any(command["dev_name"] == name for command in plan["commands"]))
                self.assertTrue(
                    any(name in issue for issue in plan["dataQuality"]["issues"])
                )

    def test_unstructured_legacy_resource_is_not_classified_from_capability_metadata(self):
        snapshot = renewable_snapshot()
        add_generator_device(
            snapshot,
            dev_type="DCGenerator",
            name="legacy-dc-wind-source",
            idx=3,
            node=3,
            mode="P",
            power_kw=11,
            rated_capacity_kw=25,
            set_type="p_set",
        )
        snapshot["definitions"]["device"] = {
            "wind_generator": definition_block(
                [
                    {
                        "name": "legacy-display-name",
                        "source_name": "legacy-dc-wind-source",
                        "dev_type": "DCGenerator",
                        "rated_power": 25,
                    }
                ]
            )
        }

        plan = calculate_renewable_control_plan(snapshot)
        self.assertFalse(
            any(
                row.get("dev_name") == "legacy-dc-wind-source"
                for row in plan["commandRows"]
            )
        )
        self.assertFalse(
            any(
                command.get("dev_name") == "legacy-dc-wind-source"
                for command in plan["commands"]
            )
        )

    def test_untyped_legacy_resource_is_not_classified_from_name_or_position(self):
        snapshot = renewable_snapshot()
        append_model_row(
            snapshot,
            "ACNode",
            {"idx": 3, "name": "legacy-default-terminal", "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "DCNode",
            {"idx": 4, "name": "legacy-default-dc-node", "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "DCRealBs",
            {"idx": 2, "name": "legacy-default-dc-bus", "node": 4, "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "DCACConverter",
            {
                "idx": 2,
                "name": "legacy-default-rectifier",
                "ac_node": 3,
                "dc_node": 4,
                "run_stat": 1,
            },
        )
        add_generator_device(
            snapshot,
            dev_type="ACGenerator",
            name="legacy-default-wind",
            idx=3,
            node=3,
            mode="P",
            power_kw=8,
            rated_capacity_kw=25,
            set_type="p_set",
        )
        snapshot["definitions"]["device"] = {
            "wind_generator": definition_block(
                [
                    {
                        "name": "legacy-default-wind",
                        "source_name": "",
                        "dev_type": "",
                        "rated_power": 25,
                    }
                ]
            )
        }

        plan = calculate_renewable_control_plan(snapshot)
        self.assertFalse(
            any(
                row.get("dev_name") == "legacy-default-wind"
                for row in plan["commandRows"]
            )
        )
        self.assertFalse(
            any(
                command.get("dev_name") == "legacy-default-wind"
                for command in plan["commands"]
            )
        )

    def test_ac_balance_storage_never_enters_dc_acdc_soc_state(self):
        baseline = calculate_renewable_control_plan(renewable_snapshot())
        snapshot = renewable_snapshot()
        add_generator_device(
            snapshot,
            dev_type="ACGenerator",
            name="ac-balance-only",
            idx=3,
            node=2,
            mode="SLACK",
            power_kw=35,
            rated_capacity_kw=50,
            set_type="p_set",
            soc=0.99,
        )
        snapshot["device_parameters"]["ACStorageGen"] = [
            {
                "idx": 1,
                "idx_acgenerator": 3,
                "energy_capacity": 100,
                "charge_discharge_efficiency": 0.95,
                "max_charge_power": 40,
                "max_discharge_power": 40,
                "soc_upper_limit": 90,
                "soc_lower_limit": 20,
            }
        ]

        plan = calculate_renewable_control_plan(snapshot)
        ac_balance = next(
            row for row in plan["commandRows"] if row["dev_name"] == "ac-balance-only"
        )

        self.assertEqual(ac_balance["category"], "交流平衡储能")
        self.assertAlmostEqual(plan["metrics"]["storageCurrentKw"], 30.0)
        self.assertAlmostEqual(plan["metrics"]["storageSoc"], 0.745)
        for metric in (
            "storageChargeDeratingLimitKw",
            "storageDischargeDeratingLimitKw",
            "acdcTargetKw",
        ):
            self.assertAlmostEqual(plan["metrics"][metric], baseline["metrics"][metric])

    def test_dc_balance_storage_without_its_own_acdc_group_cannot_drive_another_group(self):
        baseline = calculate_renewable_control_plan(renewable_snapshot())
        snapshot = renewable_snapshot()
        append_model_row(
            snapshot,
            "DCNode",
            {"idx": 10, "name": "isolated-storage-node", "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "DCRealBs",
            {"idx": 2, "name": "isolated-storage-bus", "node": 10, "run_stat": 1},
        )
        add_generator_device(
            snapshot,
            dev_type="DCGenerator",
            name="isolated-dc-balance",
            idx=3,
            node=10,
            mode="V",
            power_kw=30,
            rated_capacity_kw=50,
            soc=0.99,
        )
        snapshot["device_parameters"]["DCStorageGen"].append(
            {
                "idx": 2,
                "idx_dcgenerator": 3,
                "energy_capacity": 100,
                "charge_discharge_efficiency": 0.95,
                "max_charge_power": 40,
                "max_discharge_power": 40,
                "soc_upper_limit": 90,
                "soc_lower_limit": 20,
            }
        )

        plan = calculate_renewable_control_plan(snapshot)
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}
        isolated = by_name["isolated-dc-balance"]

        self.assertEqual(isolated["category"], "直流平衡储能")
        self.assertTrue(isolated["dcTransferGroupId"])
        self.assertNotEqual(
            isolated["dcTransferGroupId"],
            by_name["storage-1"]["dcTransferGroupId"],
        )
        self.assertEqual(isolated["indirectControlDevices"], [])
        self.assertAlmostEqual(plan["metrics"]["storageCurrentKw"], 25.0)
        self.assertAlmostEqual(plan["metrics"]["storageSoc"], 0.745)
        for metric in (
            "storageChargeDeratingLimitKw",
            "storageDischargeDeratingLimitKw",
            "acdcTargetKw",
        ):
            self.assertAlmostEqual(plan["metrics"][metric], baseline["metrics"][metric])

    def test_second_dc_balance_group_is_controlled_independently(self):
        baseline = calculate_renewable_control_plan(renewable_snapshot())
        baseline_converter = next(
            row
            for row in baseline["commandRows"]
            if row["dev_name"] == "grid-converter-1"
        )
        snapshot = renewable_snapshot()
        append_model_row(
            snapshot,
            "DCNode",
            {"idx": 10, "name": "second-group-dc-node", "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "ACNode",
            {"idx": 10, "name": "second-group-ac-node", "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "DCRealBs",
            {"idx": 2, "name": "second-group-dc-bus", "node": 10, "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "ACRealBs",
            {"idx": 2, "name": "second-group-ac-bus", "node": 10, "run_stat": 1},
        )
        append_model_row(
            snapshot,
            "DCACConverter",
            {
                "idx": 2,
                "name": "second-group-converter",
                "dc_node": 10,
                "ac_node": 10,
                "control_type": "PQ",
                "run_stat": 1,
            },
        )
        add_generator_device(
            snapshot,
            dev_type="DCGenerator",
            name="second-group-balance",
            idx=3,
            node=10,
            mode="V",
            power_kw=-40,
            rated_capacity_kw=50,
            soc=1.0,
        )
        snapshot["device_parameters"]["DCStorageGen"].append(
            {
                "idx": 2,
                "idx_dcgenerator": 3,
                "energy_capacity": 100,
                "charge_discharge_efficiency": 0.95,
                "max_charge_power": 40,
                "max_discharge_power": 40,
                "soc_upper_limit": 90,
                "soc_lower_limit": 20,
            }
        )
        snapshot["devices"].append(
            {
                "dev_type": "DCACConverter",
                "model_block": "DCACConverter",
                "dev_name": "second-group-converter",
                "run_stat": 1,
                "status": 1,
                "mode": "PQ",
                "set_types": ["p_ac_set"],
                "raw": {
                    "idx": "2",
                    "dc_node": "10",
                    "ac_node": "10",
                    "rated_capacity": "50",
                    "ac_control_type": "PQ",
                },
            }
        )
        snapshot["measurements"]["scada"].append(
            measurement(
                "second-group-converter.p",
                "DCACConverter",
                "second-group-converter",
                "P_AC",
                -10,
            )
        )
        snapshot["definitions"]["control"]["SetValue"]["rows"].append(
            {
                "dev_type": "DCACConverter",
                "dev_name": "second-group-converter",
                "set_type": "p_ac_set",
            }
        )

        plan = calculate_renewable_control_plan(snapshot)
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}
        first = by_name["grid-converter-1"]
        second = by_name["second-group-converter"]

        self.assertNotEqual(
            by_name["storage-1"]["dcTransferGroupId"],
            by_name["second-group-balance"]["dcTransferGroupId"],
        )
        self.assertAlmostEqual(first["commandKw"], baseline_converter["commandKw"])
        self.assertTrue(second["strategyCommand"])
        self.assertLess(second["commandKw"], second["currentKw"])
        self.assertEqual(
            plan["metrics"]["dcBalanceControlGroupIds"],
            [by_name["storage-1"]["dcTransferGroupId"]],
        )

        next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["dev_name"] == "second-group-converter"
            and row["meas_type"] == "P_AC"
        )["value"] = 10
        reverse_plan = calculate_renewable_control_plan(snapshot)
        reverse_by_name = {
            row["dev_name"]: row for row in reverse_plan["commandRows"]
        }

        self.assertAlmostEqual(
            reverse_by_name["grid-converter-1"]["commandKw"],
            baseline_converter["commandKw"],
        )
        self.assertTrue(reverse_by_name["second-group-converter"]["strategyCommand"])
        self.assertLessEqual(
            reverse_by_name["second-group-converter"]["commandKw"],
            0.0,
        )
        self.assertTrue(
            any(
                command["dev_name"] == "second-group-converter"
                and command["set_value"] <= 0.0
                for command in reverse_plan["commands"]
            )
        )

    def test_dc_balance_primary_group_is_invariant_to_converter_and_device_order(self):
        ordered_snapshot = renewable_snapshot()
        add_second_dc_balance_group(ordered_snapshot)
        reordered_snapshot = renewable_snapshot()
        add_second_dc_balance_group(reordered_snapshot, prepend_converter=True)

        ordered_plan = calculate_renewable_control_plan(ordered_snapshot)
        reordered_plan = calculate_renewable_control_plan(reordered_snapshot)

        metric_names = (
            "dcBalanceControlGroupIds",
            "storageCurrentKw",
            "storageSoc",
            "storageTarget",
            "acdcCurrentKw",
            "acdcTargetKw",
            "renewableTarget",
        )
        for metric_name in metric_names:
            with self.subTest(metric=metric_name):
                self.assertEqual(
                    reordered_plan["metrics"][metric_name],
                    ordered_plan["metrics"][metric_name],
                )

        ordered_converter_commands = [
            command
            for command in ordered_plan["commands"]
            if command["dev_type"] == "DCACConverter"
        ]
        reordered_converter_commands = [
            command
            for command in reordered_plan["commands"]
            if command["dev_type"] == "DCACConverter"
        ]
        self.assertEqual(ordered_converter_commands, reordered_converter_commands)
        self.assertEqual(
            [command["dev_name"] for command in ordered_converter_commands],
            ["grid-converter-1", "second-group-converter"],
        )
        self.assertEqual(reordered_plan["commands"], ordered_plan["commands"])

    def test_bad_storage_data_disables_only_that_resource(self):
        snapshot = renewable_snapshot()
        add_generator_device(
            snapshot,
            dev_type="DCGenerator",
            name="bad-grid-storage",
            idx=3,
            node=3,
            mode="P",
            power_kw=-1,
            rated_capacity_kw=20,
            set_type="p_set",
        )
        snapshot["device_parameters"]["DCStorageGen"].append(
            {
                "idx": 2,
                "idx_dcgenerator": 3,
                "energy_capacity": 50,
                "charge_discharge_efficiency": 0.95,
                "max_charge_power": 10,
                "max_discharge_power": -1,
                "soc_upper_limit": 90,
                "soc_lower_limit": 20,
            }
        )

        plan = calculate_renewable_control_plan(snapshot)
        bad = next(
            row for row in plan["commandRows"] if row["dev_name"] == "bad-grid-storage"
        )

        self.assertEqual(bad["role"], "grid_following")
        self.assertEqual(bad["category"], "直流跟网储能")
        self.assertFalse(bad["socKnown"])
        self.assertFalse(bad["commandable"])
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        self.assertTrue(
            any(
                "bad-grid-storage" in issue
                and ("SOC" in issue or "功率边界" in issue)
                for issue in plan["dataQuality"]["issues"]
            )
        )
        self.assertTrue(
            any(
                command["dev_name"] in {"wind-1", "pv-1", "grid-converter-1"}
                for command in plan["commands"]
            )
        )

    def test_environment_measurements_drive_availability_statistics_not_control_targets(self):
        snapshot = renewable_snapshot()
        plan = calculate_renewable_control_plan(snapshot)
        expected_wind_max = 100 * ((8 - 3) / (10 - 3)) ** 3

        self.assertEqual(plan["metrics"]["loadKw"], 100)
        self.assertEqual(plan["weather"]["windSpeed"], 8)
        self.assertEqual(plan["weather"]["solarIrradiance"], 500)
        self.assertEqual(plan["weather"]["airTemp"], 25)
        self.assertEqual(plan["weather"]["observedWindSpeed"], 8)
        self.assertEqual(plan["weather"]["observedSolarIrradiance"], 500)
        self.assertEqual(plan["weather"]["observedAirTemp"], 25)
        self.assertEqual(plan["dataQuality"]["inputs"]["load"]["source"], "scada")
        self.assertEqual(
            plan["dataQuality"]["inputs"]["windSpeed"]["source"],
            "scada_or_curve_boundary",
        )
        self.assertTrue(plan["dataQuality"]["inputs"]["windSpeed"]["valid"])
        self.assertAlmostEqual(plan["metrics"]["acWindMaxAvailableKw"], expected_wind_max)
        self.assertAlmostEqual(plan["metrics"]["dcPvMaxAvailableKw"], 40.0)
        self.assertAlmostEqual(plan["metrics"]["totalWindMaxAvailableKw"], expected_wind_max)
        self.assertAlmostEqual(plan["metrics"]["totalPvMaxAvailableKw"], 40.0)
        self.assertAlmostEqual(
            plan["metrics"]["totalRenewableMaxAvailableKw"],
            expected_wind_max + 40.0,
        )
        self.assertGreater(plan["metrics"]["recoveryKw"], 0)
        self.assertEqual(plan["dataQuality"]["status"], "ok")
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        trend = TraineeRenewableControlManager._trend_point(plan, snapshot)
        self.assertAlmostEqual(trend["acWindMaxAvailableKw"], expected_wind_max)
        self.assertAlmostEqual(trend["dcPvMaxAvailableKw"], 40.0)
        self.assertAlmostEqual(
            trend["totalRenewableMaxAvailableKw"],
            expected_wind_max + 40.0,
        )

    def test_environment_changes_maximum_available_statistics_but_not_control_targets(self):
        baseline = renewable_snapshot()
        changed = renewable_snapshot()
        for row in changed["measurements"]["scada"]:
            if row["meas_type"] == "WIND_SPEED":
                row["value"] = 20
            elif row["meas_type"] == "SOLAR_IRRADIANCE":
                row["value"] = 900
            elif row["meas_type"] == "AIR_TEMP":
                row["value"] = 45

        baseline_plan = calculate_renewable_control_plan(baseline)
        changed_plan = calculate_renewable_control_plan(changed)

        command_targets = lambda plan: [
            (row["dev_type"], row["dev_name"], row["set_type"], row["set_value"])
            for row in plan["commands"]
        ]
        self.assertEqual(command_targets(changed_plan), command_targets(baseline_plan))
        self.assertNotEqual(
            changed_plan["metrics"]["totalRenewableMaxAvailableKw"],
            baseline_plan["metrics"]["totalRenewableMaxAvailableKw"],
        )

    def test_invalid_environment_measurements_fall_back_to_current_curve_boundary_for_display(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_type"] == "Environment":
                row["valid"] = 0

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["weather"]["observedWindSpeed"], 30)
        self.assertEqual(plan["weather"]["observedSolarIrradiance"], 1500)
        self.assertEqual(plan["weather"]["observedAirTemp"], 25)
        self.assertEqual(plan["metrics"]["totalWindMaxAvailableKw"], 0)
        self.assertEqual(plan["metrics"]["totalPvMaxAvailableKw"], 80)
        self.assertEqual(plan["metrics"]["totalRenewableMaxAvailableKw"], 80)
        self.assertEqual(plan["weather"]["windSpeed"], 30)
        self.assertEqual(plan["weather"]["solarIrradiance"], 1500)

    def test_control_log_uses_compact_weather_and_dispatch_summary(self):
        plan = calculate_renewable_control_plan(renewable_snapshot())

        detail = renewable_control_module._compact_decision_log_detail(plan)

        self.assertLessEqual(len(detail), 6)
        joined = "；".join(detail)
        self.assertIn("仅用于最大可发统计，不参与控制", joined)
        self.assertIn("风电最大可发", joined)
        self.assertIn("光伏最大可发", joined)
        self.assertIn("新能源最大可发", joined)
        self.assertIn("指令", joined)
        self.assertLess(len(joined), len("；".join(plan["decisionDetail"])))

    def test_signed_realtime_power_values_are_preserved_for_every_control_category(self):
        snapshot = renewable_snapshot()
        signed_values = {
            ("wind-1", "P_GEN"): -3.0,
            ("pv-1", "P_GEN"): -4.0,
            ("storage-1", "P_GEN"): -5.0,
            ("diesel-1", "P_GEN"): -6.0,
            ("grid-converter-1", "P_AC"): -8.0,
            ("load-1", "P_LOAD"): -7.0,
        }
        for row in snapshot["measurements"]["scada"]:
            key = (row["dev_name"], row["meas_type"])
            if key in signed_values:
                row["value"] = signed_values[key]

        plan = calculate_renewable_control_plan(snapshot)
        metrics = plan["metrics"]

        self.assertAlmostEqual(metrics["windCurrentKw"], -3.0)
        self.assertAlmostEqual(metrics["pvCurrentKw"], -4.0)
        self.assertAlmostEqual(metrics["renewableCurrentKw"], -7.0)
        self.assertAlmostEqual(metrics["dieselCurrentKw"], -6.0)
        self.assertAlmostEqual(metrics["storageCurrentKw"], -5.0)
        self.assertAlmostEqual(metrics["acdcCurrentKw"], -8.0)
        self.assertAlmostEqual(metrics["loadKw"], -7.0)
        self.assertGreaterEqual(metrics["dieselTargetKw"], metrics["dieselMinKw"])

        current_by_category = {
            row["category"]: row.get("currentKw")
            for row in plan["commandRows"]
            if row.get("category")
            in {"交流风电", "直流光伏", "直流平衡储能", "柴油发电", "交直流变流器"}
        }
        self.assertAlmostEqual(current_by_category["交流风电"], -3.0)
        self.assertAlmostEqual(current_by_category["直流光伏"], -4.0)
        self.assertAlmostEqual(current_by_category["直流平衡储能"], -5.0)
        self.assertAlmostEqual(current_by_category["柴油发电"], -6.0)
        self.assertAlmostEqual(current_by_category["交直流变流器"], -8.0)

        renewable_by_name = {
            row["dev_name"]: row
            for row in plan["commandRows"]
            if row.get("technology") in {"wind", "pv"}
        }
        for name, expected in (("wind-1", -3.0), ("pv-1", -4.0)):
            with self.subTest(name=name):
                row = renewable_by_name[name]
                self.assertAlmostEqual(row["currentKw"], expected)
                self.assertAlmostEqual(row["planningCurrentKw"], expected)
                self.assertAlmostEqual(row["commandKw"], expected)
                self.assertFalse(row["commandable"])
                self.assertFalse(row["strategyCommand"])
                self.assertIn("保持原值", row["statusLabel"])
                self.assertFalse(
                    any(command["dev_name"] == name for command in plan["commands"])
                )

    def test_environment_presence_or_value_does_not_change_control_targets(self):
        baseline = calculate_renewable_control_plan(renewable_snapshot())
        snapshot = renewable_snapshot()
        snapshot["measurements"]["scada"] = [
            row
            for row in snapshot["measurements"]["scada"]
            if row["meas_type"] not in {"WIND_SPEED", "SOLAR_IRRADIANCE", "AIR_TEMP"}
        ]

        without_environment = calculate_renewable_control_plan(snapshot)
        changed_snapshot = renewable_snapshot()
        for row in changed_snapshot["measurements"]["scada"]:
            if row["meas_type"] == "WIND_SPEED":
                row["value"] = 70
            elif row["meas_type"] == "SOLAR_IRRADIANCE":
                row["value"] = 1500
            elif row["meas_type"] == "AIR_TEMP":
                row["value"] = 90
        changed_environment = calculate_renewable_control_plan(changed_snapshot)

        for metric in ("renewableTarget", "storageTarget", "acdcTargetKw", "dieselTargetKw"):
            self.assertAlmostEqual(without_environment["metrics"][metric], baseline["metrics"][metric])
            self.assertAlmostEqual(changed_environment["metrics"][metric], baseline["metrics"][metric])
        baseline_targets = {
            row["dev_name"]: (row.get("recoveryKw"), row.get("commandKw"))
            for row in baseline["commandRows"]
            if row.get("technology") in {"wind", "pv"}
        }
        for candidate in (without_environment, changed_environment):
            self.assertEqual(
                {
                    row["dev_name"]: (row.get("recoveryKw"), row.get("commandKw"))
                    for row in candidate["commandRows"]
                    if row.get("technology") in {"wind", "pv"}
                },
                baseline_targets,
            )
        self.assertFalse(any("默认不参与新能源控制" in warning for warning in baseline["warnings"]))
        self.assertTrue(
            any(
                "仅用于最大可发统计，不参与控制目标计算" in detail
                for detail in baseline["decisionDetail"]
            )
        )

    def test_live_soc_ratio_above_one_is_preserved_and_blocks_charging(self):
        snapshot = renewable_snapshot()
        next(row for row in snapshot["measurements"]["scada"] if row["meas_type"] == "SOC")["value"] = 3.358

        plan = calculate_renewable_control_plan(snapshot)
        storage = next(row for row in plan["commandRows"] if row["category"] == "直流平衡储能")

        self.assertAlmostEqual(plan["metrics"]["storageSoc"], 3.358)
        self.assertAlmostEqual(storage["soc"], 3.358)
        self.assertEqual(storage["chargePower"], 0)
        self.assertGreater(storage["dischargePower"], 0)

    def test_soc_above_upper_limit_increases_storage_discharge_by_one_step(self):
        snapshot = renewable_snapshot()
        next(row for row in snapshot["measurements"]["scada"] if row["meas_type"] == "SOC")["value"] = 1.3
        next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["dev_name"] == "wind-1" and row["meas_type"] == "P_GEN"
        )["value"] = 100
        next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["dev_name"] == "pv-1" and row["meas_type"] == "P_GEN"
        )["value"] = 80
        next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN"
        )["value"] = 10

        plan = calculate_renewable_control_plan(snapshot)
        storage = next(row for row in plan["commandRows"] if row["category"] == "直流平衡储能")

        self.assertEqual(storage["chargePower"], 0)
        self.assertEqual(storage["socConstraint"], "above_upper")
        self.assertAlmostEqual(storage["dischargePower"], 40.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 11.5)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 58.5)
        for category in ("交流风电", "直流光伏", "交直流变流器"):
            rows = [row for row in plan["commandRows"] if row["category"] == category]
            self.assertTrue(rows)
            self.assertTrue(all(isinstance(row.get("commandKw"), (int, float)) for row in rows))
        self.assertTrue(any("SOC运行约束" in line and "禁止充电" in line for line in plan["decisionDetail"]))

    def test_soc_above_upper_plus_deadband_uses_available_diesel_margin_in_deadband(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.96
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 25
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -5

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselControlRegion"], "deadband")
        self.assertTrue(plan["metrics"]["socAboveUpperDeadband"])
        self.assertEqual(
            plan["metrics"]["storageControlAction"],
            "increase_discharge_above_soc_upper_deadband",
        )
        self.assertTrue(plan["metrics"]["dieselDeadbandActive"])
        self.assertAlmostEqual(plan["metrics"]["dieselFloorCorrectionRequestKw"], 0.0)
        self.assertEqual(plan["metrics"]["converterStepDirection"], "decrease")
        self.assertAlmostEqual(plan["metrics"]["converterStepScale"], 1.0)
        self.assertAlmostEqual(plan["metrics"]["converterStepKw"], 1.5)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -6.5)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 1.5)
        self.assertEqual(
            plan["metrics"]["renewableControlAction"],
            "hold_above_soc_upper_deadband_while_acdc_discharges",
        )
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 50.0)
        self.assertTrue(
            any(
                "SOC越界校正" in line and "高于上限+死区" in line and "ACDC" in line
                for line in plan["decisionDetail"]
            )
        )

    def test_soc_above_upper_plus_deadband_increases_discharge_above_diesel_deadband(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.96
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 27
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -5

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselControlRegion"], "high")
        self.assertEqual(
            plan["metrics"]["storageControlAction"],
            "increase_discharge_above_soc_upper_deadband",
        )
        self.assertEqual(plan["metrics"]["converterStepDirection"], "decrease")
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -6.5)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 1.5)

    def test_soc_above_upper_plus_deadband_curtails_renewable_at_diesel_floor(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.96
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -5

        plan = calculate_renewable_control_plan(snapshot)

        self.assertTrue(plan["metrics"]["socAboveUpperDeadband"])
        self.assertEqual(
            plan["metrics"]["storageControlAction"],
            "hold_at_diesel_floor_above_soc_upper_deadband",
        )
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -5.0)
        self.assertEqual(
            plan["metrics"]["renewableControlAction"],
            "curtail_charge_safety",
        )
        self.assertAlmostEqual(plan["metrics"]["renewableStepScale"], 1.0)
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 44.6)

    def test_physical_full_triggers_upper_correction_when_threshold_reaches_one(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 1.0
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 25
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -5

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(soc_deadband=0.10),
        )

        self.assertTrue(plan["metrics"]["socAboveUpperDeadband"])
        self.assertAlmostEqual(plan["metrics"]["socUpperDeadbandThreshold"], 1.0)
        self.assertEqual(
            plan["metrics"]["storageControlAction"],
            "increase_discharge_above_soc_upper_deadband",
        )
        self.assertLess(plan["metrics"]["acdcTargetKw"], plan["metrics"]["acdcCurrentForControlKw"])

    def test_soc_at_upper_immediately_stops_reverse_converter_power(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.94
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 25
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = 5

        plan = calculate_renewable_control_plan(snapshot)

        self.assertFalse(plan["metrics"]["socAboveUpperDeadband"])
        self.assertEqual(plan["metrics"]["storageControlAction"], "stop_reverse_power")
        self.assertTrue(plan["metrics"]["upperSocDeadbandActive"])
        self.assertTrue(plan["metrics"]["dieselDeadbandActive"])
        self.assertTrue(plan["metrics"]["converterReversePowerDetected"])
        self.assertEqual(plan["metrics"]["converterStepDirection"], "hold")
        self.assertAlmostEqual(plan["metrics"]["converterStepScale"], 1.0)
        self.assertAlmostEqual(plan["metrics"]["converterStepKw"], 1.5)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["acdcAdjustmentKw"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.0)

    def test_model_soc_limits_override_controller_default_limits(self):
        snapshot = renewable_snapshot()
        storage_parameter = snapshot["device_parameters"]["DCStorageGen"][0]
        storage_parameter["soc_lower_limit"] = 10
        storage_parameter["soc_upper_limit"] = 95
        next(row for row in snapshot["measurements"]["scada"] if row["meas_type"] == "SOC")["value"] = 0.05

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(soc_min=0.3, soc_max=0.8),
        )
        storage = next(row for row in plan["commandRows"] if row["category"] == "直流平衡储能")

        self.assertAlmostEqual(storage["socMin"], 0.1)
        self.assertAlmostEqual(storage["socMax"], 0.95)
        self.assertEqual(storage["socConstraint"], "below_lower")
        self.assertEqual(storage["dischargePower"], 0)
        self.assertGreater(storage["chargePower"], 0)
        self.assertTrue(any("SOC运行约束" in line and "禁止放电" in line for line in plan["decisionDetail"]))

    def test_diesel_deadband_holds_existing_storage_power_at_upper_boundary(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "wind-1" and row["meas_type"] == "P_GEN":
                row["value"] = 100
            elif row["dev_name"] == "pv-1" and row["meas_type"] == "P_GEN":
                row["value"] = 80
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -3
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 25

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselControlRegion"], "deadband")
        self.assertAlmostEqual(plan["metrics"]["storageDesiredTargetKw"], -3.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -3.0)
        self.assertEqual(plan["metrics"]["storageControlAction"], "hold")

    def test_high_diesel_output_increases_storage_discharge_when_renewables_are_fully_recovered(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "wind-1" and row["meas_type"] == "P_GEN":
                row["value"] = 100
            elif row["dev_name"] == "pv-1" and row["meas_type"] == "P_GEN":
                row["value"] = 80
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 10

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselControlRegion"], "high")
        self.assertEqual(plan["metrics"]["storageControlAction"], "increase_discharge")
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 11.5)

    def test_high_diesel_controls_renewable_and_acdc_independently(self):
        snapshot = renewable_snapshot()
        next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["meas_type"] == "P_GEN" and row["dev_name"] == "storage-1"
        )["value"] = 10

        plan = calculate_renewable_control_plan(snapshot)

        self.assertGreater(plan["metrics"]["renewableTarget"], plan["metrics"]["renewableCurrentKw"])
        self.assertGreater(plan["metrics"]["storageTarget"], plan["metrics"]["storageCurrentKw"])
        self.assertEqual(
            plan["metrics"]["storageControlAction"],
            "increase_discharge",
        )
        self.assertFalse(plan["metrics"]["renewableStorageCoordinationActive"])
        self.assertAlmostEqual(plan["metrics"]["storageRenewableCoordinationKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 11.5)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 55.5)
        self.assertFalse(any("新能源储能协调" in line for line in plan["decisionDetail"]))
        self.assertTrue(any("两条策略相互独立" in line for line in plan["decisionDetail"]))

    def test_diesel_floor_holds_acdc_and_recovers_renewable_when_soc_has_space(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 10
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 52.4)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 10.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 20.0)
        self.assertEqual(plan["metrics"]["storageControlAction"], "hold")

    def test_diesel_floor_does_not_force_extra_acdc_charging_when_soc_has_space(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -5
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 52.4)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 20.0)
        self.assertEqual(plan["metrics"]["storageControlAction"], "hold")

    def test_soc_above_lower_limit_allows_only_slow_high_diesel_discharge_step(self):
        snapshot = renewable_snapshot()
        next(row for row in snapshot["measurements"]["scada"] if row["meas_type"] == "SOC")["value"] = 0.22
        next(row for row in snapshot["measurements"]["scada"] if row["meas_type"] == "P_GEN" and row["dev_name"] == "storage-1")["value"] = 10

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["storageSocRegion"], "low_guard")
        self.assertEqual(plan["metrics"]["storageControlAction"], "increase_discharge")
        self.assertTrue(plan["metrics"]["lowerSocDeadbandActive"])
        self.assertEqual(plan["metrics"]["converterStepDirection"], "decrease")
        self.assertEqual(plan["metrics"]["converterExportStepDirection"], "increase_export")
        self.assertAlmostEqual(plan["metrics"]["converterStepScale"], 0.20)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 10.3)

    def test_soc_below_twenty_percent_forces_converter_target_to_zero(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.15
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["storageSocRegion"], "below_lower")
        self.assertFalse(plan["metrics"]["dieselEmergencyChargeAllowed"])
        self.assertEqual(plan["metrics"]["storageControlAction"], "hold_at_soc_lower")
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.0)

    def test_soc_below_twenty_percent_stops_existing_converter_injection(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.10
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0.5
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -0.5

        plan = calculate_renewable_control_plan(snapshot)

        self.assertTrue(plan["metrics"]["socBelowLowerDeadband"])
        self.assertEqual(
            plan["metrics"]["storageControlAction"],
            "stop_discharge_below_soc_lower_deadband",
        )
        self.assertAlmostEqual(plan["metrics"]["acdcCurrentKw"], -0.5)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["acdcAdjustmentKw"], 0.5)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.0)
        self.assertEqual(
            plan["metrics"]["renewableControlAction"],
            "recover_one_step_below_soc_lower_deadband",
        )
        self.assertGreater(plan["metrics"]["renewableTarget"], plan["metrics"]["renewableCurrentKw"])
        self.assertTrue(
            any(
                "SOC越界校正" in line and "低于下限-死区" in line and "新能源" in line
                for line in plan["decisionDetail"]
            )
        )

    def test_soc_below_lower_minus_deadband_stops_converter_export_immediately(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.10
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 5
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 23
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -5

        plan = calculate_renewable_control_plan(snapshot)

        self.assertTrue(plan["metrics"]["socBelowLowerDeadband"])
        self.assertEqual(plan["metrics"]["dieselControlRegion"], "deadband")
        self.assertEqual(plan["metrics"]["converterStepDirection"], "increase")
        self.assertAlmostEqual(plan["metrics"]["converterStepScale"], 1.0)
        self.assertAlmostEqual(plan["metrics"]["converterStepKw"], 1.5)
        self.assertTrue(plan["metrics"]["converterEmergencyStopActive"])
        self.assertAlmostEqual(plan["metrics"]["converterAppliedStepKw"], 5.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.0)

    def test_physical_empty_triggers_lower_correction_when_threshold_reaches_zero(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.0
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 5
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -5

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(soc_deadband=0.20),
        )

        self.assertTrue(plan["metrics"]["socBelowLowerDeadband"])
        self.assertAlmostEqual(plan["metrics"]["socLowerDeadbandThreshold"], 0.0)
        self.assertEqual(
            plan["metrics"]["renewableControlAction"],
            "recover_one_step_below_soc_lower_deadband",
        )
        self.assertGreater(plan["metrics"]["acdcTargetKw"], plan["metrics"]["acdcCurrentForControlKw"])

    def test_diesel_deadband_holds_acdc_while_renewable_recovers(self):
        snapshot = renewable_snapshot()
        next(row for row in snapshot["measurements"]["scada"] if row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN")["value"] = 23
        next(row for row in snapshot["measurements"]["scada"] if row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN")["value"] = 10

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselControlRegion"], "deadband")
        self.assertEqual(plan["metrics"]["storageControlAction"], "hold")
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 52.4)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 10.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 23.0)

    def test_soc_below_upper_and_high_diesel_holds_renewable_while_acdc_reduces_charge(self):
        snapshot = renewable_snapshot()
        next(row for row in snapshot["measurements"]["scada"] if row["meas_type"] == "SOC")["value"] = 0.87
        next(row for row in snapshot["measurements"]["scada"] if row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN")["value"] = -10

        plan = calculate_renewable_control_plan(snapshot)
        wind = next(row for row in plan["commandRows"] if row["dev_name"] == "wind-1")
        pv = next(row for row in plan["commandRows"] if row["dev_name"] == "pv-1")

        self.assertEqual(plan["metrics"]["storageSocRegion"], "high_guard")
        self.assertEqual(plan["metrics"]["dieselControlRegion"], "high")
        self.assertEqual(plan["metrics"]["renewableControlAction"], "hold_charge_derating_while_acdc_corrects")
        self.assertTrue(plan["metrics"]["upperSocDeadbandActive"])
        self.assertAlmostEqual(wind["commandKw"], 30.0)
        self.assertAlmostEqual(pv["commandKw"], 20.0)
        self.assertAlmostEqual(plan["metrics"]["storageChargeDeratingLimitKw"], 3.6)
        self.assertAlmostEqual(plan["metrics"]["storageChargeDeratingExcessKw"], 6.4)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -3.6)
        self.assertAlmostEqual(plan["metrics"]["converterStepKw"], 1.5)
        self.assertAlmostEqual(plan["metrics"]["converterAppliedStepKw"], 6.4)
        self.assertTrue(plan["metrics"]["converterChargeDeratingSafetyOverride"])
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 53.6)

    def test_soc_below_upper_in_diesel_deadband_curtails_renewable_when_acdc_margin_is_insufficient(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.87
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -10
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 23

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselControlRegion"], "deadband")
        self.assertEqual(plan["metrics"]["renewableControlAction"], "curtail_charge_safety")
        self.assertTrue(plan["metrics"]["upperSocDeadbandActive"])
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 43.6)
        self.assertEqual(plan["metrics"]["storageChargeDeratingActuator"], "renewable")
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -10.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 23.0)

    def test_full_soc_at_diesel_floor_curtails_against_zero_charge_limit(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.90
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -10
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["renewableControlAction"], "curtail_charge_safety")
        self.assertTrue(plan["metrics"]["upperSocDeadbandActive"])
        self.assertTrue(plan["metrics"]["dieselDeadbandActive"])
        self.assertEqual(plan["metrics"]["renewableStepDirection"], "decrease")
        self.assertAlmostEqual(plan["metrics"]["renewableStepScale"], 10.0 / 5.4)
        self.assertAlmostEqual(plan["metrics"]["storageChargeDeratingExcessKw"], 10.0)
        self.assertAlmostEqual(plan["metrics"]["renewableDeratingCurtailStepRequestKw"], 5.4)
        self.assertAlmostEqual(plan["metrics"]["renewableChargeSafetyCurtailRequestKw"], 10.0)
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 40.0)
        self.assertTrue(plan["metrics"]["converterStorageConstraintConflict"])
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -10.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 20.0)

    def test_soc_switch_boundary_charge_protection_overrides_the_normal_renewable_step(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.90
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -10
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.20),
        )

        self.assertEqual(plan["metrics"]["renewableStepDirection"], "decrease")
        self.assertAlmostEqual(plan["metrics"]["renewableStepScale"], 10.0 / 5.4)
        self.assertAlmostEqual(plan["metrics"]["renewableEffectiveStepRatio"], 10.0 / 180.0)
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 40.0)
        self.assertEqual(plan["metrics"]["converterStepDirection"], "hold")
        self.assertAlmostEqual(plan["metrics"]["converterStepScale"], 1.0)
        self.assertAlmostEqual(plan["metrics"]["converterStepKw"], 10.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -10.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 20.0)
        self.assertAlmostEqual(plan["metrics"]["highSocStorageBalanceLimitKw"], 0.0)

    def test_low_diesel_does_not_request_reverse_power_when_converter_is_idle(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 10
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 10

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselControlRegion"], "low")
        self.assertEqual(plan["metrics"]["renewableControlAction"], "recover_one_step")
        self.assertEqual(plan["metrics"]["storageControlAction"], "hold_low_diesel")
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], plan["metrics"]["dieselCurrentKw"])
        self.assertLess(plan["metrics"]["dieselTargetKw"], plan["metrics"]["dieselMinKw"])
        self.assertFalse(plan["metrics"]["dieselViolationImproved"])
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])

    def test_low_diesel_reduces_converter_injection_while_renewable_recovers(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 10
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -5

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["renewableControlAction"], "recover_one_step")
        self.assertGreater(plan["metrics"]["renewableTarget"], plan["metrics"]["renewableCurrentKw"])
        self.assertEqual(plan["metrics"]["storageControlAction"], "reduce_discharge_low_diesel")
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -3.5)
        self.assertLessEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -1.5)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 11.5)
        self.assertTrue(plan["metrics"]["dieselViolationImproved"])
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])

    def test_diesel_just_below_floor_is_corrected_even_inside_old_symmetric_deadband(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 19
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -5

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselControlRegion"], "low")
        self.assertAlmostEqual(plan["metrics"]["dieselDeadbandLowerKw"], 20.0)
        self.assertAlmostEqual(plan["metrics"]["dieselDeadbandUpperKw"], 26.0)
        self.assertEqual(plan["metrics"]["storageControlAction"], "reduce_discharge_low_diesel")
        self.assertAlmostEqual(plan["metrics"]["acdcCurrentKw"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["dieselFloorCorrectionRequestKw"], 5.0)
        self.assertTrue(plan["metrics"]["dieselBoundaryApproachActive"])
        self.assertAlmostEqual(plan["metrics"]["dieselBoundaryDistanceKw"], 1.0)
        self.assertAlmostEqual(plan["metrics"]["converterStepScale"], 0.20)
        self.assertAlmostEqual(plan["metrics"]["converterStepKw"], 0.3)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -4.7)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -0.3)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 19.3)
        self.assertLess(plan["metrics"]["dieselTargetKw"], plan["metrics"]["dieselMinKw"])
        self.assertGreater(plan["metrics"]["dieselTargetKw"], plan["metrics"]["dieselCurrentKw"])
        self.assertLessEqual(
            plan["metrics"]["dieselTargetKw"],
            plan["metrics"]["dieselDeadbandUpperKw"],
        )
        self.assertTrue(plan["metrics"]["dieselViolationImproved"])
        self.assertTrue(
            any("低于下限逐步降低ACDC送出" in line for line in plan["decisionDetail"])
        )

    def test_negative_diesel_output_reduces_acdc_injection_by_one_configured_step(self):
        snapshot = renewable_snapshot()
        diesel = next(
            row
            for row in snapshot["devices"]
            if row["dev_type"] == "ACGenerator" and row["dev_name"] == "diesel-1"
        )
        diesel["raw"]["p_min"] = "0"
        diesel["raw"]["rated_capacity"] = "300"
        converter = next(
            row for row in snapshot["devices"] if row["dev_type"] == "DCACConverter"
        )
        converter["raw"]["rated_capacity"] = "360"
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.8922
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = -21.814
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -3.139
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -69.028

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                diesel_power_protection_ratio=0.10,
                converter_step_ratio=0.05,
            ),
        )
        metrics = plan["metrics"]

        self.assertEqual(metrics["dieselControlRegion"], "low")
        self.assertAlmostEqual(metrics["dieselDeadbandLowerKw"], 0.0)
        self.assertAlmostEqual(metrics["dieselDeadbandUpperKw"], 30.0)
        self.assertEqual(metrics["storageControlAction"], "reduce_discharge_low_diesel")
        self.assertAlmostEqual(metrics["converterStepKw"], 18.0)
        self.assertAlmostEqual(metrics["acdcTargetKw"], -51.028)
        self.assertAlmostEqual(metrics["dieselTargetKw"], -3.814)
        self.assertTrue(metrics["dieselViolationImproved"])

    def test_diesel_floor_boundary_reduces_converter_step_to_avoid_region_hopping(self):
        snapshot = renewable_snapshot()
        diesel = next(
            row
            for row in snapshot["devices"]
            if row["dev_type"] == "ACGenerator" and row["dev_name"] == "diesel-1"
        )
        diesel["raw"]["p_min"] = "0"
        diesel["raw"]["rated_capacity"] = "300"
        converter = next(
            row for row in snapshot["devices"] if row["dev_type"] == "DCACConverter"
        )
        converter["raw"]["rated_capacity"] = "360"
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.60
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = -0.580
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0.0
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -106.577

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                diesel_power_protection_ratio=0.10,
                converter_step_ratio=0.05,
            ),
        )
        metrics = plan["metrics"]

        self.assertEqual(metrics["dieselControlRegion"], "low")
        self.assertAlmostEqual(metrics["converterBaseStepKw"], 18.0)
        self.assertAlmostEqual(metrics["converterStepScale"], 0.20)
        self.assertAlmostEqual(metrics["converterStepKw"], 3.6)
        self.assertTrue(metrics["dieselBoundaryApproachActive"])
        self.assertAlmostEqual(metrics["dieselBoundaryDistanceKw"], 0.580)
        self.assertAlmostEqual(metrics["acdcTargetKw"], -102.977)
        self.assertAlmostEqual(metrics["dieselTargetKw"], 3.020)
        self.assertGreaterEqual(metrics["dieselTargetKw"], metrics["dieselDeadbandLowerKw"])
        self.assertLessEqual(metrics["dieselTargetKw"], metrics["dieselDeadbandUpperKw"])
        self.assertTrue(
            any("接近柴发控制分区切换边界" in line for line in plan["decisionDetail"])
        )

    def test_diesel_deadband_upper_boundary_reduces_converter_step_before_hold(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.60
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 26.5
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0.0
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -5.0

        plan = calculate_renewable_control_plan(snapshot)
        metrics = plan["metrics"]

        self.assertEqual(metrics["dieselControlRegion"], "high")
        self.assertAlmostEqual(metrics["dieselDeadbandUpperKw"], 26.0)
        self.assertAlmostEqual(metrics["converterBaseStepKw"], 1.5)
        self.assertAlmostEqual(metrics["converterStepScale"], 0.20)
        self.assertAlmostEqual(metrics["converterStepKw"], 0.3)
        self.assertTrue(metrics["dieselBoundaryApproachActive"])
        self.assertAlmostEqual(metrics["dieselBoundaryDistanceKw"], 0.5)
        self.assertAlmostEqual(metrics["acdcTargetKw"], -5.0)
        self.assertAlmostEqual(metrics["dieselTargetKw"], 26.0)

    def test_storage_soc_constraint_does_not_override_diesel_deadband_hold(self):
        snapshot = renewable_snapshot()
        diesel = next(row for row in snapshot["devices"] if row["dev_name"] == "diesel-1")
        diesel["raw"].update({"p_min": "0", "rated_capacity": "300"})
        converter = next(
            row for row in snapshot["devices"] if row["dev_type"] == "DCACConverter"
        )
        converter["raw"]["rated_capacity"] = "360"
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.9009
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 18.33
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -106.86
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -69.53

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                diesel_power_protection_ratio=0.10,
                soc_deadband=0.10,
                converter_step_ratio=0.05,
                step_coefficient=0.05,
            ),
        )
        metrics = plan["metrics"]

        self.assertEqual(metrics["dieselControlRegion"], "deadband")
        self.assertEqual(metrics["storageControlAction"], "hold")
        self.assertAlmostEqual(metrics["storageDesiredTargetKw"], 0.0)
        self.assertAlmostEqual(metrics["acdcCurrentForControlKw"], -69.53)
        self.assertAlmostEqual(metrics["acdcTargetKw"], -69.53)
        self.assertEqual(metrics["converterStepDirection"], "hold")
        self.assertTrue(metrics["converterStorageConstraintConflict"])

    def test_storage_soc_constraint_does_not_reverse_low_diesel_correction(self):
        snapshot = renewable_snapshot()
        diesel = next(row for row in snapshot["devices"] if row["dev_name"] == "diesel-1")
        diesel["raw"].update({"p_min": "0", "rated_capacity": "300"})
        converter = next(
            row for row in snapshot["devices"] if row["dev_type"] == "DCACConverter"
        )
        converter["raw"]["rated_capacity"] = "360"
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.9087
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = -0.62
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -78.82
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -87.54

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                diesel_power_protection_ratio=0.10,
                soc_deadband=0.10,
                converter_step_ratio=0.05,
                step_coefficient=0.05,
            ),
        )
        metrics = plan["metrics"]

        self.assertEqual(metrics["dieselControlRegion"], "low")
        self.assertEqual(metrics["storageControlAction"], "reduce_discharge_low_diesel")
        self.assertEqual(metrics["converterStepDirection"], "increase")
        self.assertAlmostEqual(metrics["converterStepScale"], 0.20)
        self.assertAlmostEqual(metrics["converterStepKw"], 3.6)
        self.assertAlmostEqual(metrics["acdcTargetKw"], -83.94)
        self.assertAlmostEqual(metrics["dieselTargetKw"], 2.98)
        self.assertTrue(metrics["dieselViolationImproved"])
        self.assertTrue(metrics["converterStorageConstraintConflict"])

    def test_renewable_holds_near_soc_upper_switch_boundary_without_storage_charge(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.9018
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0.0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20.0
            elif row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC":
                row["value"] = -5.0

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                soc_deadband=0.10,
                step_coefficient=0.05,
            ),
        )
        metrics = plan["metrics"]

        self.assertEqual(metrics["renewableControlAction"], "hold_full_soc_no_charge")
        self.assertAlmostEqual(metrics["renewableStepScale"], 0.0)
        self.assertAlmostEqual(metrics["renewableEffectiveStepRatio"], 0.0)
        self.assertTrue(metrics["renewableUpperBoundaryApproachActive"])
        self.assertAlmostEqual(metrics["renewableUpperBoundaryDistance"], 0.0018)
        self.assertAlmostEqual(metrics["renewableUpperBoundaryWidth"], 0.02)
        self.assertAlmostEqual(metrics["renewableTarget"], 50.0)
        self.assertTrue(
            any("储能已不再充电，停止继续弃电" in line for line in plan["decisionDetail"])
        )

    def test_full_soc_stops_curtailment_after_storage_charge_is_eliminated(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.95
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 10.0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20.0

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                grid_forming_storage_protection_ratio=0.05,
            ),
        )
        metrics = plan["metrics"]

        self.assertEqual(metrics["renewableControlAction"], "hold_full_soc_no_charge")
        self.assertEqual(metrics["renewableStepDirection"], "hold")
        self.assertAlmostEqual(metrics["renewableStorageChargeExcessKw"], 0.0)
        self.assertAlmostEqual(metrics["renewableTarget"], 50.0)

    def test_upper_soc_guard_curtails_to_piecewise_charge_limit(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.895
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -10.0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20.0

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                step_coefficient=0.10,
                grid_forming_storage_protection_ratio=0.05,
            ),
        )
        metrics = plan["metrics"]

        self.assertTrue(metrics["renewableUpperBoundaryGuardActive"])
        self.assertEqual(metrics["renewableControlAction"], "curtail_charge_safety")
        self.assertEqual(metrics["renewableStepDirection"], "decrease")
        self.assertAlmostEqual(metrics["renewableStorageChargeExcessKw"], 5.0)
        self.assertAlmostEqual(metrics["storageChargeDeratingLimitKw"], 0.6)
        self.assertAlmostEqual(metrics["storageChargeDeratingExcessKw"], 9.4)
        self.assertAlmostEqual(metrics["renewableTarget"], 40.6)

    def test_full_soc_curtailment_matches_piecewise_charge_excess_without_overshoot(self):
        cases = (
            ("partial", -10.0, 10.0, 40.0, 10.0, 0.0),
            ("full", -30.0, 30.0, 30.0, 20.0, 10.0),
        )
        for label, storage_kw, charge_excess_kw, expected_target, delivered_kw, shortfall_kw in cases:
            with self.subTest(label=label):
                snapshot = renewable_snapshot()
                for row in snapshot["measurements"]["scada"]:
                    if row["meas_type"] == "SOC":
                        row["value"] = 0.91
                    elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                        row["value"] = storage_kw
                    elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                        row["value"] = 20.0

                plan = calculate_renewable_control_plan(
                    snapshot,
                    RenewableControlSettings(
                        step_coefficient=0.10,
                        grid_forming_storage_protection_ratio=0.05,
                    ),
                )
                metrics = plan["metrics"]
                expected_scale = delivered_kw / 18.0

                self.assertEqual(metrics["renewableControlAction"], "curtail_charge_safety")
                self.assertAlmostEqual(metrics["storageChargeDeratingExcessKw"], charge_excess_kw)
                self.assertAlmostEqual(metrics["renewableStepScale"], expected_scale)
                self.assertAlmostEqual(metrics["renewableDeratingCurtailStepRequestKw"], min(18.0, charge_excess_kw))
                self.assertAlmostEqual(metrics["renewableChargeSafetyCurtailRequestKw"], charge_excess_kw)
                self.assertAlmostEqual(metrics["renewableChargeSafetyCurtailDeliveredKw"], delivered_kw)
                self.assertAlmostEqual(metrics["renewableChargeSafetyCurtailShortfallKw"], shortfall_kw)
                self.assertAlmostEqual(metrics["renewableTarget"], expected_target)

    def test_charge_derating_removes_the_full_remaining_charge_excess(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.85
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -30.0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20.0

        plan = calculate_renewable_control_plan(snapshot)
        metrics = plan["metrics"]

        self.assertAlmostEqual(metrics["storageChargeDeratingLimitKw"], 6.0)
        self.assertAlmostEqual(metrics["storageChargeDeratingExcessKw"], 24.0)
        self.assertAlmostEqual(metrics["renewableCurrentKw"] - metrics["renewableTarget"], 20.0)
        self.assertAlmostEqual(metrics["storageChargeDeratingResidualKw"], 4.0)
        self.assertAlmostEqual(metrics["renewableChargeSafetyCurtailDeliveredKw"], 20.0)
        self.assertAlmostEqual(metrics["renewableChargeSafetyCurtailShortfallKw"], 4.0)
        self.assertTrue(metrics["storageChargeDeratingSafetyOverride"])

    def test_above_upper_deadband_stops_charging_before_requesting_discharge(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.97
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -30.0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 20.0

        plan = calculate_renewable_control_plan(snapshot)
        metrics = plan["metrics"]

        self.assertTrue(metrics["socAboveUpperDeadband"])
        self.assertAlmostEqual(metrics["storageChargeDeratingResidualKw"], 10.0)
        self.assertAlmostEqual(metrics["storageHighSocDischargeRequestKw"], 5.4)
        self.assertAlmostEqual(metrics["renewableChargeSafetyCurtailRequestKw"], 35.4)
        self.assertAlmostEqual(metrics["renewableChargeSafetyCurtailDeliveredKw"], 20.0)
        self.assertAlmostEqual(metrics["renewableChargeSafetyCurtailShortfallKw"], 15.4)
        self.assertAlmostEqual(metrics["renewableTarget"], 30.0)
        self.assertTrue(metrics["storageChargeDeratingSafetyOverride"])

    def test_storage_energy_limit_uses_the_full_control_horizon(self):
        snapshot = renewable_snapshot()
        snapshot["system_parameters"] = {
            "effective_step_minutes": 5,
            "compute_interval_seconds": 1,
        }
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.89

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                interval_seconds=2,
                storage_charge_derating_curve=((0.0, 1.0), (1.0, 1.0)),
            ),
        )
        metrics = plan["metrics"]

        self.assertAlmostEqual(metrics["storageControlHorizonMinutes"], 10.0)
        self.assertAlmostEqual(metrics["storageChargeBeforeDeratingKw"], 1.0 / (0.95 * (10.0 / 60.0)))

    def test_low_soc_never_requests_reverse_power_even_with_diesel_headroom(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.10
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 199.5

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["dieselUpMarginKw"], 0.5)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertFalse(plan["metrics"]["dieselEmergencyChargeAllowed"])
        self.assertEqual(plan["metrics"]["storageControlAction"], "reverse_power_forbidden_below_soc_lower_deadband")
        self.assertLessEqual(plan["metrics"]["dieselTargetKw"], plan["metrics"]["dieselCapacityKw"])
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])

    def test_low_soc_target_is_zero_without_diesel_upward_headroom(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.10
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 200

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["dieselUpMarginKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)
        self.assertFalse(plan["metrics"]["dieselEmergencyChargeAllowed"])
        self.assertEqual(plan["metrics"]["storageControlAction"], "reverse_power_forbidden_below_soc_lower_deadband")

    def test_extreme_low_soc_stops_discharge_without_reducing_physical_converter_capacity(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.10
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 200

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["converterTargetLowerLimitKw"], -50.0)
        self.assertAlmostEqual(plan["metrics"]["converterTargetUpperLimitKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)

    def test_extreme_low_soc_keeps_storage_feedback_without_direct_storage_control(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.10
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = -5
            elif row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN":
                row["value"] = 200

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["storageDesiredTargetKw"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["storageCandidateTargetKw"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -5.0)
        self.assertEqual(
            plan["metrics"]["storageControlAction"],
            "reverse_power_forbidden_below_soc_lower_deadband",
        )
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], 0.0)

    def test_planner_has_no_dwell_or_pending_feedback_state_contract(self):
        signature = inspect.signature(calculate_renewable_control_plan)
        plan = calculate_renewable_control_plan(renewable_snapshot())

        self.assertNotIn("control_state", signature.parameters)
        self.assertNotIn("feedbackState", plan)
        self.assertNotIn("dispatchReady", plan)

    def test_load_value_and_validity_do_not_change_control_targets(self):
        baseline_snapshot = renewable_snapshot()
        baseline = calculate_renewable_control_plan(baseline_snapshot)
        changed_snapshot = renewable_snapshot()
        load_row = next(row for row in changed_snapshot["measurements"]["scada"] if row["meas_type"] == "P_LOAD")
        load_row["value"] = 900
        load_row["valid"] = 0
        changed_snapshot["curve_boundary"]["load_total"] = 1200

        changed = calculate_renewable_control_plan(changed_snapshot)

        self.assertEqual(changed["metrics"]["loadKw"], 1200)
        self.assertEqual(changed["dataQuality"]["inputs"]["load"]["source"], "curve_boundary")
        for metric in ("renewableTarget", "storageTarget", "acdcTargetKw", "dieselTargetKw"):
            self.assertAlmostEqual(changed["metrics"][metric], baseline["metrics"][metric])
        self.assertEqual(changed["dataQuality"]["dispatchAllowed"], baseline["dataQuality"]["dispatchAllowed"])
        self.assertTrue(any("负荷功率仅用于展示" in line for line in changed["decisionDetail"]))

    def test_missing_live_renewable_power_blocks_dispatch_even_when_weather_is_known(self):
        snapshot = renewable_snapshot()
        snapshot["measurements"]["scada"] = [
            row
            for row in snapshot["measurements"]["scada"]
            if not (row["dev_name"] == "wind-1" and row["meas_type"] == "P_GEN")
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["dataQuality"]["status"], "blocked")
        self.assertFalse(plan["dataQuality"]["dispatchAllowed"])
        self.assertTrue(any("风电wind-1" in issue and "实时有功" in issue for issue in plan["dataQuality"]["issues"]))

    def test_non_commandable_renewable_is_kept_at_live_power_not_assumed_capability(self):
        snapshot = renewable_snapshot()
        snapshot["definitions"]["control"]["SetValue"]["rows"] = [
            row
            for row in snapshot["definitions"]["control"]["SetValue"]["rows"]
            if row["dev_type"] == "DCACConverter"
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["renewableCurrentKw"], 50.0)
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 50.0)
        renewable_rows = [
            row
            for row in plan["commandRows"]
            if row["category"] in {"交流风电", "直流光伏"}
        ]
        self.assertTrue(all(row["commandable"] is False for row in renewable_rows))

    def test_environment_curve_parameters_do_not_block_default_recovery_strategy(self):
        snapshot = renewable_snapshot()
        snapshot["device_parameters"]["ACWindGen"][0].pop("cut_in_wind_speed")

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["dataQuality"]["status"], "ok")
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        wind = next(row for row in plan["commandRows"] if row["dev_name"] == "wind-1")
        self.assertIsNotNone(wind["commandKw"])
        self.assertFalse(any("风电wind-1" in issue and "最大可发" in issue for issue in plan["dataQuality"]["issues"]))

    def test_missing_converter_capacity_is_inferred_from_storage_power_boundary(self):
        missing_capacity = renewable_snapshot()
        converter = next(row for row in missing_capacity["devices"] if row["dev_type"] == "DCACConverter")
        converter["raw"].pop("rated_capacity")

        capacity_plan = calculate_renewable_control_plan(missing_capacity)
        converter_row = next(
            row for row in capacity_plan["commandRows"] if row["dev_type"] == "DCACConverter"
        )

        self.assertTrue(capacity_plan["dataQuality"]["dispatchAllowed"])
        self.assertEqual(capacity_plan["dataQuality"]["status"], "ok")
        self.assertAlmostEqual(converter_row["transferCapacityKw"], 40.0)
        self.assertEqual(converter_row["capacitySource"], "storage_boundary")
        self.assertFalse(any("变流器" in issue and "容量" in issue for issue in capacity_plan["dataQuality"]["issues"]))

    def test_parallel_converters_share_inferred_storage_power_boundary(self):
        snapshot = renewable_snapshot()
        first_converter = next(row for row in snapshot["devices"] if row["dev_type"] == "DCACConverter")
        first_converter["raw"].pop("rated_capacity")
        snapshot["devices"].append(
            {
                **first_converter,
                "dev_name": "grid-converter-2",
                "raw": {
                    "idx": "2",
                    "ac_node": "2",
                    "dc_node": "3",
                    "ac_control_type": "PQ",
                },
            }
        )
        append_model_row(
            snapshot,
            "DCACConverter",
            {
                "idx": 2,
                "name": "grid-converter-2",
                "ac_node": 2,
                "dc_node": 3,
                "control_type": "PQ",
                "run_stat": 1,
            },
        )
        snapshot["measurements"]["scada"].append(
            measurement("converter-2.p", "DCACConverter", "grid-converter-2", "P_AC", 0)
        )
        snapshot["definitions"]["control"]["SetValue"]["rows"].append(
            {"dev_type": "DCACConverter", "dev_name": "grid-converter-2", "set_type": "p_ac_set"}
        )

        plan = calculate_renewable_control_plan(snapshot)
        converter_rows = [row for row in plan["commandRows"] if row["dev_type"] == "DCACConverter"]

        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        self.assertEqual(len(converter_rows), 2)
        self.assertTrue(all(row["capacitySource"] == "storage_boundary" for row in converter_rows))
        self.assertTrue(all(abs(row["transferCapacityKw"] - 20.0) < 1e-9 for row in converter_rows))
        self.assertAlmostEqual(sum(row["commandKw"] for row in converter_rows), plan["metrics"]["acdcTargetKw"])

    def test_parallel_converter_order_and_targets_ignore_all_source_row_order(self):
        def parallel_snapshot(*, reverse_rows: bool) -> dict:
            snapshot = renewable_snapshot()
            first_converter = next(
                row
                for row in snapshot["devices"]
                if row["dev_type"] == "DCACConverter"
                and row["dev_name"] == "grid-converter-1"
            )
            first_converter["raw"]["rated_capacity"] = "60"
            snapshot["devices"].append(
                {
                    **first_converter,
                    "dev_name": "grid-converter-2",
                    "raw": {
                        **first_converter["raw"],
                        "idx": "2",
                        "rated_capacity": "20",
                    },
                }
            )
            append_model_row(
                snapshot,
                "DCACConverter",
                {
                    "idx": 2,
                    "name": "grid-converter-2",
                    "ac_node": 2,
                    "dc_node": 3,
                    "control_type": "PQ",
                    "run_stat": 1,
                },
            )
            snapshot["measurements"]["scada"].append(
                measurement(
                    "converter-2.p",
                    "DCACConverter",
                    "grid-converter-2",
                    "P_AC",
                    0.0,
                )
            )
            snapshot["definitions"]["control"]["SetValue"]["rows"].append(
                {
                    "dev_type": "DCACConverter",
                    "dev_name": "grid-converter-2",
                    "set_type": "p_ac_set",
                }
            )

            if reverse_rows:
                def reverse_matching(rows: list[dict], predicate) -> None:
                    positions = [
                        index for index, row in enumerate(rows) if predicate(row)
                    ]
                    values = [rows[index] for index in reversed(positions)]
                    for index, value in zip(positions, values):
                        rows[index] = value

                reverse_matching(
                    snapshot["devices"],
                    lambda row: row.get("dev_type") == "DCACConverter",
                )
                reverse_matching(
                    snapshot["definitions"]["model"]["DCACConverter"]["rows"],
                    lambda row: True,
                )
                reverse_matching(
                    snapshot["definitions"]["control"]["SetValue"]["rows"],
                    lambda row: row.get("dev_type") == "DCACConverter",
                )
                reverse_matching(
                    snapshot["measurements"]["scada"],
                    lambda row: row.get("dev_type") == "DCACConverter",
                )
            return snapshot

        ordered = calculate_renewable_control_plan(
            parallel_snapshot(reverse_rows=False)
        )
        reversed_plan = calculate_renewable_control_plan(
            parallel_snapshot(reverse_rows=True)
        )

        def converter_rows(plan: dict) -> list[dict]:
            return [
                row
                for row in plan["commandRows"]
                if row.get("dev_type") == "DCACConverter"
            ]

        def converter_commands(plan: dict) -> list[dict]:
            return [
                command
                for command in plan["commands"]
                if command["dev_type"] == "DCACConverter"
            ]

        ordered_rows = converter_rows(ordered)
        reversed_rows = converter_rows(reversed_plan)
        ordered_commands = converter_commands(ordered)
        reversed_commands = converter_commands(reversed_plan)

        self.assertEqual(
            [row["dev_name"] for row in ordered_rows],
            ["grid-converter-1", "grid-converter-2"],
        )
        self.assertEqual(reversed_rows, ordered_rows)
        self.assertEqual(reversed_commands, ordered_commands)
        self.assertEqual(
            [command["dev_name"] for command in ordered_commands],
            ["grid-converter-1", "grid-converter-2"],
        )
        targets = {row["dev_name"]: row["commandKw"] for row in ordered_rows}
        self.assertGreater(
            abs(targets["grid-converter-1"]),
            abs(targets["grid-converter-2"]),
        )
        self.assertAlmostEqual(
            sum(targets.values()),
            ordered["metrics"]["acdcTargetKw"],
        )
        for metric_name in (
            "storageConverterCount",
            "converterRatedCapacityKw",
            "converterBaseStepKw",
            "acdcCurrentKw",
            "acdcTargetKw",
            "storageCurrentKw",
            "storageTarget",
        ):
            with self.subTest(metric=metric_name):
                self.assertEqual(
                    reversed_plan["metrics"][metric_name],
                    ordered["metrics"][metric_name],
                )

    def test_missing_converter_live_power_forbids_closed_loop_dispatch(self):
        missing_power = renewable_snapshot()

        missing_power["measurements"]["scada"] = [
            row
            for row in missing_power["measurements"]["scada"]
            if not (row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC")
        ]

        power_plan = calculate_renewable_control_plan(missing_power)

        self.assertFalse(power_plan["dataQuality"]["dispatchAllowed"])
        self.assertTrue(any("变流器" in issue and "实时有功" in issue for issue in power_plan["dataQuality"]["issues"]))

    def test_scada_noise_near_rated_capacity_is_corrected_to_rated_limit(self):
        snapshot = renewable_snapshot()
        wind_device = next(row for row in snapshot["devices"] if row["dev_name"] == "wind-1")
        wind_device["raw"]["rated_capacity"] = "10.1"
        snapshot["device_parameters"]["ACWindGen"][0]["rated_power"] = 10.1
        wind_power = next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["dev_name"] == "wind-1" and row["meas_type"] == "P_GEN"
        )
        wind_power["value"] = 10.12
        wind_power["weight"] = 10000

        plan = calculate_renewable_control_plan(snapshot)
        wind_row = next(row for row in plan["commandRows"] if row["dev_name"] == "wind-1")

        self.assertAlmostEqual(wind_row["currentKw"], 10.12)
        self.assertAlmostEqual(wind_row["planningCurrentKw"], 10.12)
        self.assertLessEqual(wind_row["commandKw"], 10.1)
        self.assertTrue(wind_row["commandable"])
        self.assertTrue(wind_row["strategyCommand"])
        self.assertIn("超过容量", wind_row["statusLabel"])
        self.assertTrue(
            any(command["dev_name"] == "wind-1" for command in plan["commands"])
        )
        self.assertEqual(plan["dataQuality"]["status"], "degraded")
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        self.assertTrue(any("风电wind-1" in issue and "额定容量" in issue for issue in plan["dataQuality"]["issues"]))

    def test_material_generation_overcapacity_is_corrected_and_remains_quality_warning(self):
        snapshot = renewable_snapshot()
        wind_device = next(row for row in snapshot["devices"] if row["dev_name"] == "wind-1")
        wind_device["raw"]["rated_capacity"] = "10.1"
        snapshot["device_parameters"]["ACWindGen"][0]["rated_power"] = 10.1
        wind_power = next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["dev_name"] == "wind-1" and row["meas_type"] == "P_GEN"
        )
        wind_power["value"] = 10.5
        wind_power["weight"] = 10000

        plan = calculate_renewable_control_plan(snapshot)
        wind_row = next(row for row in plan["commandRows"] if row["dev_name"] == "wind-1")

        self.assertAlmostEqual(wind_row["currentKw"], 10.5)
        self.assertAlmostEqual(wind_row["planningCurrentKw"], 10.5)
        self.assertLessEqual(wind_row["commandKw"], 10.1)
        self.assertTrue(wind_row["commandable"])
        self.assertTrue(wind_row["strategyCommand"])
        self.assertIn("超过容量", wind_row["statusLabel"])
        self.assertTrue(
            any(command["dev_name"] == "wind-1" for command in plan["commands"])
        )
        self.assertEqual(plan["dataQuality"]["status"], "degraded")
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        self.assertTrue(any("风电wind-1" in issue and "额定容量" in issue for issue in plan["dataQuality"]["issues"]))

    def test_unknown_environment_and_missing_live_power_blocks_dispatch(self):
        snapshot = renewable_snapshot()
        snapshot["measurements"]["scada"] = [
            row
            for row in snapshot["measurements"]["scada"]
            if not (
                row["dev_name"] == "wind-1"
                or row["meas_type"] in {"WIND_SPEED", "SOLAR_IRRADIANCE"}
            )
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["dataQuality"]["status"], "blocked")
        self.assertFalse(plan["dataQuality"]["dispatchAllowed"])
        wind = next(row for row in plan["commandRows"] if row["dev_name"] == "wind-1")
        self.assertIsNone(wind["commandKw"])

    def test_unknown_environment_recovery_does_not_preconsume_diesel_margin_needed_by_storage(self):
        snapshot = renewable_snapshot()
        snapshot["measurements"]["scada"] = [
            row if row["meas_type"] != "WIND_SPEED" else {**row, "value": 20}
            for row in snapshot["measurements"]["scada"]
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["metrics"]["dieselMinKw"], 20)
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 55.4)
        self.assertAlmostEqual(plan["metrics"]["renewableDeltaKw"], 5.4)
        self.assertAlmostEqual(plan["metrics"]["renewableBalancingDeltaKw"], 5.4)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -3.5)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -1.5)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 55.5)
        wind = next(row for row in plan["commandRows"] if row["dev_name"] == "wind-1")
        predicted_diesel = (
            plan["metrics"]["dieselCurrentKw"]
            - (plan["metrics"]["storageTarget"] - plan["metrics"]["storageCurrentKw"])
            - (wind["commandKw"] - wind["currentKw"])
        )
        self.assertAlmostEqual(predicted_diesel, plan["metrics"]["dieselTargetKw"])

    def test_converter_target_uses_live_power_as_incremental_storage_baseline(self):
        snapshot = renewable_snapshot()
        converter_power = next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC"
        )
        converter_power["value"] = -10
        snapshot["measurements"]["scada"] = [
            row if row["meas_type"] != "WIND_SPEED" else {**row, "value": 20}
            for row in snapshot["measurements"]["scada"]
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["storageCurrentKw"], -5.0)
        self.assertAlmostEqual(
            plan["metrics"]["directGridFormingDcGroups"][0]["residualKw"],
            0.0,
        )
        self.assertAlmostEqual(plan["metrics"]["acdcCurrentKw"], -10.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -11.5)
        self.assertAlmostEqual(plan["metrics"]["acdcAdjustmentKw"], -1.5)

    def test_converter_step_limits_effective_storage_adjustment(self):
        snapshot = renewable_snapshot()
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.95
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(converter_step_ratio=0.01),
        )

        self.assertAlmostEqual(plan["metrics"]["storageDesiredTargetKw"], 40.0)
        self.assertAlmostEqual(plan["metrics"]["converterStepKw"], 0.5)
        self.assertTrue(plan["metrics"]["converterStepLimited"])
        self.assertAlmostEqual(plan["metrics"]["acdcDesiredTargetKw"], -40.0)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -0.5)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], 0.5)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 59.5)

    def test_converter_capacity_limits_storage_target_before_diesel_target_is_calculated(self):
        snapshot = renewable_snapshot()
        snapshot["device_parameters"]["DCStorageGen"][0]["soc_upper_limit"] = 100
        snapshot["definitions"]["control"]["SetValue"]["rows"] = [
            row
            for row in snapshot["definitions"]["control"]["SetValue"]["rows"]
            if row["dev_type"] == "DCACConverter"
        ]
        converter_power = next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["dev_type"] == "DCACConverter" and row["meas_type"] == "P_AC"
        )
        converter_power["value"] = -45
        next(
            row
            for row in snapshot["measurements"]["scada"]
            if row["meas_type"] == "SOC"
        )["value"] = 0.95

        plan = calculate_renewable_control_plan(
            snapshot,
            RenewableControlSettings(
                storage_charge_derating_curve=((0.0, 1.0), (1.0, 1.0)),
            ),
        )

        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 50.0)
        self.assertAlmostEqual(plan["metrics"]["storageMinTargetKw"], -40.0)
        self.assertAlmostEqual(plan["metrics"]["storageMaxTargetKw"], 0.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -3.5)
        self.assertAlmostEqual(plan["metrics"]["acdcTargetKw"], -46.5)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 58.5)
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])

    def test_storage_power_is_held_when_no_online_power_control_converter_exists(self):
        snapshot = renewable_snapshot()
        snapshot["devices"] = [
            row for row in snapshot["devices"] if row["dev_type"] != "DCACConverter"
        ]
        snapshot["measurements"]["scada"] = [
            row if row["meas_type"] != "WIND_SPEED" else {**row, "value": 20}
            for row in snapshot["measurements"]["scada"]
            if row["dev_type"] != "DCACConverter"
        ]
        snapshot["definitions"]["control"]["SetValue"]["rows"] = [
            row
            for row in snapshot["definitions"]["control"]["SetValue"]["rows"]
            if row["dev_type"] != "DCACConverter"
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertAlmostEqual(plan["metrics"]["storageCurrentKw"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["storageMinTargetKw"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["storageMaxTargetKw"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["storageTarget"], -5.0)
        self.assertAlmostEqual(plan["metrics"]["renewableTarget"], 55.4)
        self.assertAlmostEqual(plan["metrics"]["renewableBalancingDeltaKw"], 5.4)
        self.assertAlmostEqual(plan["metrics"]["dieselTargetKw"], 57.0)
        self.assertEqual(plan["metrics"]["storageConverterCount"], 0)
        self.assertFalse(plan["dataQuality"]["dispatchAllowed"])

    def test_two_storage_islands_make_soc_decisions_per_active_component(self):
        def two_component_snapshot(other_soc: float) -> dict:
            snapshot = renewable_snapshot()
            snapshot["device_states"] = [
                {
                    "dev_type": "ACRealBs",
                    "dev_name": "380V-bus",
                    "run_stat": 0,
                    "dead_island": False,
                }
            ]
            for device in snapshot["devices"]:
                if device["dev_name"] in {"diesel-1", "load-1"}:
                    device["run_stat"] = 0

            snapshot["device_parameters"]["DCStorageGen"][0]["soc_upper_limit"] = 95
            for row in snapshot["measurements"]["scada"]:
                if row["dev_name"] == "storage-1" and row["meas_type"] == "SOC":
                    row["value"] = 0.95
                elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                    row["value"] = 0.0
                elif row["dev_name"] == "grid-converter-1" and row["meas_type"] == "P_AC":
                    row["value"] = 0.0

            append_model_row(
                snapshot,
                "ACNode",
                {"idx": 30, "name": "base-transfer-ac-node", "run_stat": 1},
            )
            append_model_row(
                snapshot,
                "ACRealBs",
                {"idx": 30, "name": "base-transfer-ac-bus", "node": 30, "run_stat": 1},
            )
            next(
                row
                for row in snapshot["definitions"]["model"]["DCACConverter"]["rows"]
                if row["name"] == "grid-converter-1"
            )["ac_node"] = 30
            next(
                device
                for device in snapshot["devices"]
                if device["dev_name"] == "grid-converter-1"
            )["raw"]["ac_node"] = "30"

            append_model_row(
                snapshot,
                "DCNode",
                {"idx": 10, "name": "other-pv-node", "run_stat": 1},
            )
            append_model_row(
                snapshot,
                "DCNode",
                {"idx": 11, "name": "other-storage-node", "run_stat": 1},
            )
            append_model_row(
                snapshot,
                "DCNode",
                {"idx": 12, "name": "other-grid-node", "run_stat": 1},
            )
            append_model_row(
                snapshot,
                "DCBranch",
                {
                    "idx": 10,
                    "name": "other-pv-line",
                    "i_node": 10,
                    "j_node": 12,
                    "run_stat": 1,
                },
            )
            append_model_row(
                snapshot,
                "DCBreak",
                {
                    "idx": 10,
                    "name": "other-storage-break",
                    "i_node": 11,
                    "j_node": 12,
                    "run_stat": 1,
                    "status": 1,
                },
            )
            append_model_row(
                snapshot,
                "DCRealBs",
                {"idx": 10, "name": "other-dc-bus", "node": 12, "run_stat": 1},
            )
            append_model_row(
                snapshot,
                "ACNode",
                {"idx": 40, "name": "other-transfer-ac-node", "run_stat": 1},
            )
            append_model_row(
                snapshot,
                "ACRealBs",
                {"idx": 40, "name": "other-transfer-ac-bus", "node": 40, "run_stat": 1},
            )

            add_generator_device(
                snapshot,
                dev_type="DCGenerator",
                name="pv-other",
                idx=3,
                node=10,
                mode="P",
                power_kw=20.0,
                rated_capacity_kw=80.0,
                set_type="p_set",
            )
            add_generator_device(
                snapshot,
                dev_type="DCGenerator",
                name="storage-other",
                idx=4,
                node=11,
                mode="V",
                power_kw=0.0,
                rated_capacity_kw=100.0,
                soc=other_soc,
            )
            snapshot["device_parameters"]["DCPVGen"].append(
                {"idx": 2, "idx_dcgenerator": 3, "rated_power": 80.0}
            )
            snapshot["device_parameters"]["DCStorageGen"].append(
                {
                    "idx": 2,
                    "idx_dcgenerator": 4,
                    "energy_capacity": 100,
                    "charge_discharge_efficiency": 0.95,
                    "max_charge_power": 40,
                    "max_discharge_power": 40,
                    "soc_upper_limit": 95,
                    "soc_lower_limit": 20,
                }
            )
            append_model_row(
                snapshot,
                "DCACConverter",
                {
                    "idx": 2,
                    "name": "other-converter",
                    "dc_node": 12,
                    "ac_node": 40,
                    "control_type": "PQ",
                    "run_stat": 1,
                },
            )
            snapshot["devices"].append(
                {
                    "dev_type": "DCACConverter",
                    "dev_name": "other-converter",
                    "run_stat": 1,
                    "status": 1,
                    "mode": "PQ",
                    "set_types": ["p_ac_set"],
                    "raw": {
                        "idx": "2",
                        "dc_node": "12",
                        "ac_node": "40",
                        "rated_capacity": "50",
                        "ac_control_type": "PQ",
                    },
                }
            )
            snapshot["measurements"]["scada"].append(
                measurement(
                    "other-converter.p",
                    "DCACConverter",
                    "other-converter",
                    "P_AC",
                    0.0,
                )
            )
            snapshot["definitions"]["control"]["SetValue"]["rows"].append(
                {
                    "dev_type": "DCACConverter",
                    "dev_name": "other-converter",
                    "set_type": "p_ac_set",
                }
            )
            return snapshot

        low_other_plan = calculate_renewable_control_plan(two_component_snapshot(0.50))
        high_other_plan = calculate_renewable_control_plan(two_component_snapshot(0.95))
        low_rows = {row["dev_name"]: row for row in low_other_plan["commandRows"]}
        high_rows = {row["dev_name"]: row for row in high_other_plan["commandRows"]}

        self.assertEqual(low_other_plan["metrics"]["operatingMode"], "renewable_storage_island")
        self.assertEqual(high_other_plan["metrics"]["operatingMode"], "renewable_storage_island")
        self.assertEqual(
            low_rows["storage-1"]["gridComponentId"],
            low_rows["pv-1"]["gridComponentId"],
        )
        self.assertEqual(
            low_rows["storage-other"]["gridComponentId"],
            low_rows["pv-other"]["gridComponentId"],
        )
        self.assertNotEqual(
            low_rows["storage-1"]["gridComponentId"],
            low_rows["storage-other"]["gridComponentId"],
        )

        self.assertAlmostEqual(low_rows["pv-1"]["commandKw"], 17.6)
        self.assertAlmostEqual(high_rows["pv-1"]["commandKw"], 17.6)
        self.assertEqual(
            low_rows["pv-1"]["islandControlAction"],
            "curtail_one_step_storage_island_full_soc",
        )
        self.assertEqual(
            high_rows["pv-1"]["islandControlAction"],
            "curtail_one_step_storage_island_full_soc",
        )

        self.assertAlmostEqual(low_rows["pv-other"]["commandKw"], 22.4)
        self.assertAlmostEqual(high_rows["pv-other"]["commandKw"], 17.6)
        self.assertEqual(
            low_rows["pv-other"]["islandControlAction"],
            "recover_one_step_storage_island",
        )
        self.assertEqual(
            high_rows["pv-other"]["islandControlAction"],
            "curtail_one_step_storage_island_full_soc",
        )
        self.assertAlmostEqual(low_rows["grid-converter-1"]["commandKw"], 0.0)
        self.assertAlmostEqual(high_rows["grid-converter-1"]["commandKw"], 0.0)
        self.assertEqual(
            low_rows["grid-converter-1"]["islandControlAction"],
            "curtail_one_step_storage_island_full_soc",
        )
        self.assertEqual(
            high_rows["grid-converter-1"]["islandControlAction"],
            "curtail_one_step_storage_island_full_soc",
        )
        self.assertEqual(
            low_rows["other-converter"]["islandControlAction"],
            "recover_one_step_storage_island",
        )
        self.assertEqual(
            high_rows["other-converter"]["islandControlAction"],
            "curtail_one_step_storage_island_full_soc",
        )
        self.assertEqual(
            low_rows["grid-converter-1"]["dcTransferGroupId"],
            low_rows["storage-1"]["dcTransferGroupId"],
        )
        self.assertEqual(
            low_rows["other-converter"]["dcTransferGroupId"],
            low_rows["storage-other"]["dcTransferGroupId"],
        )
        low_components = {
            item["gridComponentId"]: item
            for item in low_other_plan["metrics"].get(
                "renewableStorageIslandComponents",
                [],
            )
        }
        high_components = {
            item["gridComponentId"]: item
            for item in high_other_plan["metrics"].get(
                "renewableStorageIslandComponents",
                [],
            )
        }
        base_component_id = low_rows["pv-1"]["gridComponentId"]
        other_component_id = low_rows["pv-other"]["gridComponentId"]
        self.assertEqual(len(low_components), 2)
        self.assertEqual(len(high_components), 2)
        self.assertEqual(
            low_components[base_component_id]["action"],
            "curtail_one_step_storage_island_full_soc",
        )
        self.assertEqual(
            high_components[base_component_id]["action"],
            "curtail_one_step_storage_island_full_soc",
        )
        self.assertEqual(
            low_components[other_component_id]["action"],
            "recover_one_step_storage_island",
        )
        self.assertEqual(
            high_components[other_component_id]["action"],
            "curtail_one_step_storage_island_full_soc",
        )
        self.assertEqual(
            low_rows["storage-1"]["indirectControlDevices"],
            [{"dev_type": "DCACConverter", "dev_name": "grid-converter-1"}],
        )
        self.assertEqual(
            low_rows["storage-other"]["indirectControlDevices"],
            [{"dev_type": "DCACConverter", "dev_name": "other-converter"}],
        )

    def test_fully_retired_ac_side_with_full_storage_curtails_renewables(self):
        snapshot = renewable_snapshot()
        snapshot["device_states"] = [
            {
                "dev_type": "ACRealBs",
                "dev_name": "380V-bus",
                "run_stat": 0,
                "dead_island": False,
            }
        ]
        for device in snapshot["devices"]:
            if device["dev_name"] in {"diesel-1", "load-1"}:
                device["run_stat"] = 0
        snapshot["device_parameters"]["DCStorageGen"][0]["soc_upper_limit"] = 95
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.95
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0.0
            elif row["dev_name"] == "grid-converter-1" and row["meas_type"] == "P_AC":
                row["value"] = -6.0

        plan = calculate_renewable_control_plan(snapshot)
        metrics = plan["metrics"]

        self.assertEqual(metrics["operatingMode"], "renewable_storage_island")
        self.assertTrue(metrics["acSideFullyOffline"])
        self.assertEqual(metrics["acBusCount"], 1)
        self.assertEqual(metrics["onlineAcBusCount"], 0)
        self.assertEqual(metrics["onlineAcLoadCount"], 0)
        self.assertEqual(metrics["onlineDieselCount"], 0)
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        self.assertAlmostEqual(metrics["storageSocUpperLimit"], 0.95)
        self.assertAlmostEqual(metrics["acdcTargetKw"], 0.0)
        self.assertEqual(
            metrics["renewableControlAction"],
            "curtail_one_step_storage_island_full_soc",
        )
        self.assertAlmostEqual(metrics["renewableCurrentKw"], 20.0)
        self.assertAlmostEqual(metrics["renewableTarget"], 17.6)
        by_name = {row["dev_name"]: row for row in plan["commandRows"]}
        self.assertFalse(by_name["wind-1"]["activelyConnected"])
        self.assertTrue(by_name["pv-1"]["activelyConnected"])
        self.assertEqual(
            by_name["pv-1"]["gridComponentId"],
            by_name["storage-1"]["gridComponentId"],
        )
        self.assertTrue(
            any(
                "交流侧全部退运" in line and "新能源储能孤岛" in line
                for line in plan["decisionDetail"]
            )
        )
        self.assertTrue(any("SOC上限 95.00%" in line for line in plan["decisionDetail"]))
        self.assertFalse(
            any("优先增加ACDC送出" in line for line in plan["decisionDetail"])
        )

    def test_fully_retired_ac_side_recovers_renewables_while_storage_can_charge(self):
        snapshot = renewable_snapshot()
        snapshot["device_states"] = [
            {
                "dev_type": "ACRealBs",
                "dev_name": "380V-bus",
                "run_stat": 0,
                "dead_island": False,
            }
        ]
        for device in snapshot["devices"]:
            if device["dev_name"] in {"diesel-1", "load-1"}:
                device["run_stat"] = 0
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.50
            elif row["dev_name"] == "grid-converter-1" and row["meas_type"] == "P_AC":
                row["value"] = -6.0

        plan = calculate_renewable_control_plan(snapshot)
        metrics = plan["metrics"]

        self.assertEqual(metrics["operatingMode"], "renewable_storage_island")
        self.assertTrue(plan["dataQuality"]["dispatchAllowed"])
        self.assertAlmostEqual(metrics["acdcTargetKw"], 0.0)
        self.assertEqual(
            metrics["renewableControlAction"],
            "recover_one_step_storage_island",
        )
        self.assertAlmostEqual(metrics["renewableCurrentKw"], 20.0)
        self.assertAlmostEqual(metrics["renewableTarget"], 22.4)

    def test_storage_island_curtails_when_charge_derating_reaches_zero_before_soc_limit(self):
        snapshot = renewable_snapshot()
        snapshot["device_states"] = [
            {
                "dev_type": "ACRealBs",
                "dev_name": "380V-bus",
                "run_stat": 0,
                "dead_island": False,
            }
        ]
        for device in snapshot["devices"]:
            if device["dev_name"] in {"diesel-1", "load-1"}:
                device["run_stat"] = 0
        snapshot["device_parameters"]["DCStorageGen"][0]["soc_upper_limit"] = 95
        for row in snapshot["measurements"]["scada"]:
            if row["meas_type"] == "SOC":
                row["value"] = 0.92
            elif row["dev_name"] == "storage-1" and row["meas_type"] == "P_GEN":
                row["value"] = 0.0

        plan = calculate_renewable_control_plan(snapshot)
        metrics = plan["metrics"]

        self.assertEqual(metrics["operatingMode"], "renewable_storage_island")
        self.assertLess(metrics["storageSoc"], metrics["storageSocUpperLimit"])
        self.assertAlmostEqual(metrics["storageChargeDeratingLimitKw"], 0.0)
        self.assertEqual(
            metrics["renewableControlAction"],
            "curtail_one_step_storage_island_no_charge_capacity",
        )
        self.assertAlmostEqual(metrics["renewableCurrentKw"], 20.0)
        self.assertAlmostEqual(metrics["renewableTarget"], 17.6)
        self.assertTrue(
            any("允许充电功率已经为零" in line for line in plan["decisionDetail"])
        )

    def test_missing_diesel_still_blocks_when_an_ac_load_remains_online(self):
        snapshot = renewable_snapshot()
        snapshot["device_states"] = [
            {
                "dev_type": "ACRealBs",
                "dev_name": "380V-bus",
                "run_stat": 0,
                "dead_island": False,
            }
        ]
        next(device for device in snapshot["devices"] if device["dev_name"] == "diesel-1")[
            "run_stat"
        ] = 0

        plan = calculate_renewable_control_plan(snapshot)

        self.assertFalse(plan["metrics"]["acSideFullyOffline"])
        self.assertEqual(plan["metrics"]["operatingMode"], "blocked_no_diesel")
        self.assertEqual(plan["dataQuality"]["status"], "blocked")
        self.assertTrue(
            any("没有在线柴油发电机" in issue for issue in plan["dataQuality"]["issues"])
        )
        self.assertFalse(
            any("采用在线柴油发电机" in line for line in plan["decisionDetail"])
        )

    def test_fully_retired_ac_side_without_online_storage_remains_blocked(self):
        snapshot = renewable_snapshot()
        snapshot["device_states"] = [
            {
                "dev_type": "ACRealBs",
                "dev_name": "380V-bus",
                "run_stat": 0,
                "dead_island": False,
            }
        ]
        for device in snapshot["devices"]:
            if device["dev_name"] in {"diesel-1", "load-1", "storage-1"}:
                device["run_stat"] = 0

        plan = calculate_renewable_control_plan(snapshot)

        self.assertTrue(plan["metrics"]["acSideFullyOffline"])
        self.assertNotEqual(plan["metrics"]["operatingMode"], "renewable_storage_island")
        self.assertEqual(plan["dataQuality"]["status"], "blocked")
        self.assertFalse(plan["dataQuality"]["dispatchAllowed"])
        self.assertTrue(
            any("储能" in issue and "在线" in issue for issue in plan["dataQuality"]["issues"])
        )

    def test_missing_online_diesel_power_blocks_closed_loop_dispatch(self):
        snapshot = renewable_snapshot()
        snapshot["measurements"]["scada"] = [
            row
            for row in snapshot["measurements"]["scada"]
            if not (row["dev_name"] == "diesel-1" and row["meas_type"] == "P_GEN")
        ]

        plan = calculate_renewable_control_plan(snapshot)

        self.assertEqual(plan["dataQuality"]["status"], "blocked")
        self.assertFalse(plan["dataQuality"]["dispatchAllowed"])
        self.assertTrue(any("柴油" in issue and "实时有功" in issue for issue in plan["dataQuality"]["issues"]))

    def test_task8_metrics_use_topology_side_and_capacity_weighted_soc(self):
        plan = calculate_renewable_control_plan(task8_metrics_snapshot())
        metrics = plan["metrics"]

        for key in TASK8_METRIC_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, metrics)
                value = metrics[key]
                if key == "dcTransferGroups":
                    self.assertIsInstance(value, list)
                    json.dumps(value, ensure_ascii=False)
                else:
                    self.assertTrue(
                        value is None
                        or isinstance(value, (int, float))
                        and math.isfinite(float(value))
                    )

        self.assertAlmostEqual(metrics["acWindCurrentKw"], 100.0)
        self.assertAlmostEqual(metrics["dcPvCurrentKw"], 80.0)
        self.assertAlmostEqual(metrics["acPvCurrentKw"], 0.0)
        self.assertAlmostEqual(metrics["dcWindCurrentKw"], 0.0)
        self.assertEqual(metrics["acGridFollowingStorageCount"], 1)
        self.assertEqual(metrics["dcGridFollowingStorageCount"], 1)
        self.assertEqual(metrics["acGridFormingStorageCount"], 1)
        self.assertEqual(metrics["dcGridFormingStorageCount"], 1)
        self.assertAlmostEqual(metrics["acGridStorageCurrentKw"], -2.0)
        self.assertAlmostEqual(metrics["dcGridStorageCurrentKw"], -4.0)
        self.assertAlmostEqual(metrics["acBalanceStorageCurrentKw"], 6.0)
        self.assertAlmostEqual(metrics["dcBalanceStorageCurrentKw"], -8.0)
        self.assertAlmostEqual(metrics["acGridStorageSoc"], 0.20)
        self.assertAlmostEqual(metrics["dcGridStorageSoc"], 0.80)
        self.assertAlmostEqual(metrics["acBalanceStorageSoc"], 0.40)
        self.assertAlmostEqual(metrics["dcBalanceStorageSoc"], 1.20)
        self.assertAlmostEqual(metrics["acRenewableCurrentKw"], 100.0)
        self.assertAlmostEqual(metrics["dcRenewableCurrentKw"], 80.0)
        self.assertAlmostEqual(metrics["acGridFollowingStorageCurrentKw"], -2.0)
        self.assertAlmostEqual(metrics["dcGridFollowingStorageCurrentKw"], -4.0)
        self.assertAlmostEqual(metrics["acGridFormingStorageCurrentKw"], 6.0)
        self.assertAlmostEqual(metrics["dcGridFormingStorageCurrentKw"], -8.0)
        self.assertAlmostEqual(metrics["acGridFollowingStorageSoc"], 0.20)
        self.assertAlmostEqual(metrics["dcGridFollowingStorageSoc"], 0.80)
        self.assertAlmostEqual(metrics["acGridFormingStorageSoc"], 0.40)
        self.assertAlmostEqual(metrics["dcGridFormingStorageSoc"], 1.20)
        self.assertAlmostEqual(metrics["acDieselCurrentKw"], 60.0)
        self.assertAlmostEqual(metrics["dcDieselCurrentKw"], 0.0)
        self.assertAlmostEqual(metrics["acLoadKw"], 100.0)
        self.assertAlmostEqual(metrics["dcLoadKw"], 0.0)
        self.assertAlmostEqual(metrics["totalRenewableCurrentKw"], 180.0)
        self.assertAlmostEqual(metrics["totalGridFollowingStorageCurrentKw"], -6.0)
        self.assertAlmostEqual(metrics["totalGridFormingStorageCurrentKw"], -2.0)
        self.assertAlmostEqual(metrics["totalDieselCurrentKw"], 60.0)
        self.assertAlmostEqual(metrics["totalLoadKw"], 100.0)
        self.assertAlmostEqual(metrics["storageCurrentKw"], -8.0)
        self.assertAlmostEqual(metrics["storageSoc"], 0.82)
        self.assertGreaterEqual(metrics["dcRenewableToAcKw"], 0.0)

        groups = metrics["dcTransferGroups"]
        self.assertEqual(len(groups), 1)
        group = groups[0]
        expected_group_keys = {
            "groupId",
            "active",
            "dcNodes",
            "converterDevices",
            "currentRenewableKw",
            "targetRenewableKw",
            "currentGridStorageKw",
            "targetGridStorageKw",
            "gridStorageSoc",
            "currentBalanceStorageKw",
            "targetBalanceStorageKw",
            "balanceStorageSoc",
            "currentAcdcExportKw",
            "finalAcdcExportKw",
            "acdcCapacityKw",
            "remainingAcdcHeadroomKw",
            "stepAcdcHeadroomKw",
            "renewableDeliveredThroughAcdcKw",
            "curtailedRenewableKw",
            "blockedRenewableKw",
            "reasons",
            "affectedDevices",
        }
        self.assertLessEqual(expected_group_keys, set(group))
        self.assertTrue(group["active"])
        self.assertAlmostEqual(group["currentRenewableKw"], 80.0)
        self.assertAlmostEqual(group["currentGridStorageKw"], -4.0)
        self.assertAlmostEqual(group["currentBalanceStorageKw"], -8.0)
        self.assertAlmostEqual(group["gridStorageSoc"], 0.80)
        self.assertAlmostEqual(group["balanceStorageSoc"], 1.20)

    def test_storage_metrics_distinguish_configured_devices_from_online_devices(self):
        metrics = renewable_control_module._task8_side_metrics(
            [
                {
                    "technology": "storage",
                    "role": "grid_following",
                    "connectionSide": "AC",
                    "online": False,
                    "currentKw": 0.0,
                    "soc": 0.5,
                    "socKnown": True,
                    "capacityKwh": 100.0,
                },
                {
                    "technology": "storage",
                    "role": "balance",
                    "connectionSide": "DC",
                    "online": True,
                    "currentKw": -5.0,
                    "soc": 0.6,
                    "socKnown": True,
                    "capacityKwh": 200.0,
                },
            ]
        )

        self.assertEqual(metrics["acGridFollowingStorageCount"], 1)
        self.assertEqual(metrics["onlineAcGridFollowingStorageCount"], 0)
        self.assertEqual(metrics["dcGridFormingStorageCount"], 1)
        self.assertEqual(metrics["onlineDcGridFormingStorageCount"], 1)
        self.assertIsNone(metrics["acGridFollowingStorageSoc"])
        self.assertAlmostEqual(metrics["dcGridFormingStorageSoc"], 0.6)

    def test_side_load_metrics_preserve_signed_ac_and_dc_measurements(self):
        snapshot = task8_metrics_snapshot()
        add_dc_load(
            snapshot,
            name="dc-load-signed",
            idx=9,
            node=3,
            power_kw=-12.5,
        )

        metrics = calculate_renewable_control_plan(snapshot)["metrics"]

        self.assertAlmostEqual(metrics["acLoadKw"], 100.0)
        self.assertAlmostEqual(metrics["dcLoadKw"], -12.5)
        self.assertAlmostEqual(metrics["totalLoadKw"], 87.5)

    def test_task8_metrics_preserve_inactive_dc_transfer_group_diagnostics(self):
        snapshot = direct_grid_storage_snapshot(
            include_ac_storage=False,
            include_dc_storage=True,
            dc_has_transfer_path=False,
        )
        topology = resolve_resource_topology(snapshot, [])
        isolated_group_id = next(
            group_id
            for group_id, group in topology.dc_transfer_groups.items()
            if "10" in group.dc_nodes
        )

        plan = calculate_renewable_control_plan(snapshot)
        metrics = plan["metrics"]
        groups_by_id = {
            str(group["groupId"]): group for group in metrics["dcTransferGroups"]
        }
        self.assertIn(isolated_group_id, groups_by_id)
        group = groups_by_id[isolated_group_id]

        def assert_json_numeric_values_are_finite(value):
            if isinstance(value, bool) or value is None:
                return
            if isinstance(value, (int, float)):
                self.assertTrue(math.isfinite(float(value)))
                return
            if isinstance(value, dict):
                for nested in value.values():
                    assert_json_numeric_values_are_finite(nested)
                return
            if isinstance(value, list):
                for nested in value:
                    assert_json_numeric_values_are_finite(nested)

        self.assertFalse(group["active"])
        self.assertIn("10", group["dcNodes"])
        self.assertEqual(group["converterDevices"], [])
        self.assertEqual(group["currentAcdcExportKw"], 0.0)
        self.assertEqual(group["finalAcdcExportKw"], 0.0)
        self.assertEqual(group["acdcCapacityKw"], 0.0)
        self.assertEqual(group["remainingAcdcHeadroomKw"], 0.0)
        self.assertEqual(group["stepAcdcHeadroomKw"], 0.0)
        self.assertEqual(group["renewableDeliveredThroughAcdcKw"], 0.0)
        self.assertEqual(metrics["dcRenewableToAcKw"], 0.0)
        self.assertTrue(
            any(
                device["dev_name"] == "dc-grid-storage"
                for device in group["affectedDevices"]
            )
        )
        self.assertTrue(
            any(
                "acdc" in reason.lower() or "transfer" in reason.lower()
                for reason in group["reasons"]
            ),
            group["reasons"],
        )
        self.assertFalse(
            any(command["dev_name"] == "dc-grid-storage" for command in plan["commands"])
        )
        assert_json_numeric_values_are_finite(group)

        first_trend = TraineeRenewableControlManager._trend_point(plan, snapshot)
        second_trend = TraineeRenewableControlManager._trend_point(plan, snapshot)
        self.assertIn(
            isolated_group_id,
            {str(group["groupId"]) for group in first_trend["dcTransferGroups"]},
        )
        first_trend["dcTransferGroups"][0]["groupId"] = "mutated-by-trend-client"
        self.assertNotEqual(
            first_trend["dcTransferGroups"],
            second_trend["dcTransferGroups"],
        )
        self.assertEqual(
            groups_by_id[isolated_group_id]["groupId"],
            isolated_group_id,
        )

        with tempfile.TemporaryDirectory() as temporary:
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: {},
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            manager = make_control_manager(services)
            state = manager._state_for("shared")
            try:
                first_payload = manager._command_payload(state, plan, snapshot, "auto")
                second_payload = manager._command_payload(state, plan, snapshot, "auto")
            finally:
                manager.close()

        first_payload_groups = first_payload["strategy"]["metrics"]["dcTransferGroups"]
        second_payload_groups = second_payload["strategy"]["metrics"]["dcTransferGroups"]
        self.assertIn(
            isolated_group_id,
            {str(group["groupId"]) for group in first_payload_groups},
        )
        first_payload_groups[0]["groupId"] = "mutated-by-payload-client"
        self.assertNotEqual(first_payload_groups, second_payload_groups)
        self.assertEqual(
            groups_by_id[isolated_group_id]["groupId"],
            isolated_group_id,
        )
        json.dumps(first_trend["dcTransferGroups"], ensure_ascii=False)
        json.dumps(first_payload, ensure_ascii=False, default=str)

    def test_inactive_dc_transfer_group_fails_closed_for_dc_resource_commands(self):
        snapshot = direct_grid_storage_snapshot(
            include_ac_storage=False,
            include_dc_storage=True,
            dc_has_transfer_path=False,
        )
        for device in snapshot["devices"]:
            if device.get("dev_type") == "DCGenerator" and device.get("dev_name") == "pv-1":
                device["raw"]["node"] = "10"
        for row in snapshot["definitions"]["model"]["DCGenerator"]["rows"]:
            if row.get("name") == "pv-1":
                row["node"] = 10
        add_generator_device(
            snapshot,
            dev_type="DCGenerator",
            name="active-peer-pv",
            idx=4,
            node=3,
            mode="P",
            power_kw=20.0,
            rated_capacity_kw=80.0,
            set_type="p_set",
        )
        snapshot["device_parameters"]["DCPVGen"].append(
            {"idx": 2, "idx_dcgenerator": 4, "rated_power": 80.0}
        )

        plan = calculate_renewable_control_plan(snapshot)
        inactive_groups = {
            str(group["groupId"]): group
            for group in plan["metrics"]["dcTransferGroups"]
            if not group["active"]
        }
        self.assertTrue(inactive_groups)
        isolated_group = next(
            group for group in inactive_groups.values() if "10" in group["dcNodes"]
        )
        inactive_group_ids = set(inactive_groups)
        inactive_resource_names = {
            row["dev_name"]
            for row in plan["commandRows"]
            if row.get("technology") in {"wind", "pv", "storage"}
            and row.get("connectionSide") == "DC"
            and str(row.get("dcTransferGroupId", "")) in inactive_group_ids
        }
        command_names = {command["dev_name"] for command in plan["commands"]}

        self.assertTrue(
            any(
                device["dev_name"] == "pv-1"
                for device in isolated_group["affectedDevices"]
            )
        )
        self.assertIn("pv-1", inactive_resource_names)
        self.assertIn("dc-grid-storage", inactive_resource_names)
        self.assertTrue(inactive_resource_names.isdisjoint(command_names))
        self.assertNotIn("pv-1", command_names)
        self.assertIn("active-peer-pv", command_names)
        self.assertEqual(isolated_group["converterDevices"], [])
        self.assertEqual(isolated_group["currentAcdcExportKw"], 0.0)
        self.assertEqual(isolated_group["finalAcdcExportKw"], 0.0)
        self.assertEqual(isolated_group["acdcCapacityKw"], 0.0)
        self.assertFalse(
            any(
                row.get("dev_type") == "DCACConverter"
                and str(row.get("dcTransferGroupId", "")) in inactive_group_ids
                and row.get("strategyCommand") is not False
                for row in plan["commandRows"]
            )
        )

    def test_dc_renewable_to_ac_counts_existing_valid_export_without_storage(self):
        snapshot = direct_grid_storage_snapshot(
            diesel_power_kw=80.0,
            include_ac_storage=False,
            include_dc_storage=False,
            converter_power_kw=-30.0,
            converter_capacity_kw=50.0,
        )

        plan = calculate_renewable_control_plan(snapshot)
        metrics = plan["metrics"]
        group = metrics["dcTransferGroups"][0]

        self.assertAlmostEqual(group["currentPvKw"], 80.0)
        self.assertAlmostEqual(group["currentGridStorageKw"], 0.0)
        self.assertAlmostEqual(group["currentBalanceStorageKw"], 0.0)
        self.assertAlmostEqual(group["currentAcdcExportKw"], 30.0)
        self.assertAlmostEqual(group["finalAcdcExportKw"], 30.0)
        self.assertAlmostEqual(group["renewableDeliveredThroughAcdcKw"], 30.0)
        self.assertAlmostEqual(metrics["dcRenewableToAcKw"], 30.0)

    def test_dc_renewable_to_ac_excludes_storage_only_export(self):
        snapshot = direct_grid_storage_snapshot(
            diesel_power_kw=80.0,
            dc_current_kw=30.0,
            include_ac_storage=False,
            include_dc_storage=True,
            converter_power_kw=-30.0,
            converter_capacity_kw=50.0,
        )
        set_measurement_value(snapshot, "DCGenerator", "pv-1", "P_GEN", 0.0)

        plan = calculate_renewable_control_plan(snapshot)
        metrics = plan["metrics"]
        group = metrics["dcTransferGroups"][0]

        self.assertAlmostEqual(group["currentPvKw"], 0.0)
        self.assertAlmostEqual(group["currentGridStorageKw"], 30.0)
        self.assertAlmostEqual(group["currentAcdcExportKw"], 30.0)
        self.assertAlmostEqual(group["renewableDeliveredThroughAcdcKw"], 0.0)
        self.assertAlmostEqual(metrics["dcRenewableToAcKw"], 0.0)

    def test_dc_renewable_to_ac_respects_local_load_before_export(self):
        snapshot = direct_grid_storage_snapshot(
            diesel_power_kw=80.0,
            include_ac_storage=False,
            include_dc_storage=False,
            converter_power_kw=-50.0,
            converter_capacity_kw=60.0,
        )
        add_dc_load(
            snapshot,
            name="dc-local-load",
            idx=2,
            node=3,
            power_kw=60.0,
        )

        plan = calculate_renewable_control_plan(snapshot)
        metrics = plan["metrics"]
        group = metrics["dcTransferGroups"][0]

        self.assertAlmostEqual(group["currentPvKw"], 80.0)
        self.assertAlmostEqual(group["currentAcdcExportKw"], 50.0)
        self.assertAlmostEqual(group["renewableDeliveredThroughAcdcKw"], 20.0)
        self.assertAlmostEqual(metrics["dcRenewableToAcKw"], 20.0)

    def test_dc_renewable_to_ac_subtracts_uncontrolled_storage_charging(self):
        snapshot = direct_grid_storage_snapshot(
            diesel_power_kw=80.0,
            include_ac_storage=False,
            include_dc_storage=False,
            converter_power_kw=-50.0,
            converter_capacity_kw=60.0,
        )
        add_generator_device(
            snapshot,
            dev_type="DCGenerator",
            name="manual-dc-storage",
            idx=3,
            node=3,
            mode="MANUAL",
            power_kw=-40.0,
            rated_capacity_kw=40.0,
            set_type="p_set",
            soc=0.44,
        )
        snapshot["device_parameters"]["DCStorageGen"] = [
            {
                "idx": 1,
                "idx_dcgenerator": 3,
                "energy_capacity": 200.0,
                "charge_discharge_efficiency": 1.0,
                "max_charge_power": 40.0,
                "max_discharge_power": 40.0,
                "soc_upper_limit": 90.0,
                "soc_lower_limit": 20.0,
            }
        ]

        plan = calculate_renewable_control_plan(snapshot)
        metrics = plan["metrics"]
        group = metrics["dcTransferGroups"][0]

        self.assertAlmostEqual(group["currentPvKw"], 80.0)
        self.assertAlmostEqual(group["currentAcdcExportKw"], 50.0)
        self.assertAlmostEqual(group["finalAcdcExportKw"], 50.0)
        self.assertAlmostEqual(group["renewableDeliveredThroughAcdcKw"], 40.0)
        self.assertAlmostEqual(metrics["dcRenewableToAcKw"], 40.0)
        self.assertAlmostEqual(metrics["dcGridStorageCurrentKw"], 0.0)
        self.assertAlmostEqual(metrics["dcBalanceStorageCurrentKw"], 0.0)
        self.assertAlmostEqual(metrics["storageCurrentKw"], -40.0)
        self.assertAlmostEqual(metrics["storageSoc"], 0.44)
        self.assertFalse(
            any(command["dev_name"] == "manual-dc-storage" for command in plan["commands"])
        )

    def test_dc_renewable_to_ac_ignores_invalid_uncontrolled_storage_charging(self):
        snapshot = direct_grid_storage_snapshot(
            diesel_power_kw=80.0,
            include_ac_storage=False,
            include_dc_storage=False,
            converter_power_kw=-50.0,
            converter_capacity_kw=60.0,
        )
        add_generator_device(
            snapshot,
            dev_type="DCGenerator",
            name="invalid-manual-dc-storage",
            idx=3,
            node=3,
            mode="MANUAL",
            power_kw=-40.0,
            rated_capacity_kw=40.0,
            set_type="p_set",
            soc=0.44,
        )
        snapshot["devices"].append(
            {
                "dev_type": "DCGenerator",
                "dev_name": "invalid-manual-dc-storage",
                "run_stat": 1,
                "status": 1,
                "mode": "MANUAL",
                "set_types": ["p_set"],
                "raw": {"idx": "30", "node": "3", "rated_capacity": "40"},
            }
        )
        snapshot["device_parameters"]["DCStorageGen"] = [
            {
                "idx": 1,
                "idx_dcgenerator": 3,
                "energy_capacity": 200.0,
                "charge_discharge_efficiency": 1.0,
                "max_charge_power": 40.0,
                "max_discharge_power": 40.0,
                "soc_upper_limit": 90.0,
                "soc_lower_limit": 20.0,
            }
        ]

        plan = calculate_renewable_control_plan(snapshot)
        metrics = plan["metrics"]
        group = metrics["dcTransferGroups"][0]
        invalid_storage = next(
            row
            for row in plan["commandRows"]
            if row["dev_name"] == "invalid-manual-dc-storage"
        )

        self.assertFalse(invalid_storage["resourceIdentityValid"])
        self.assertFalse(invalid_storage["commandable"])
        self.assertAlmostEqual(group["currentPvKw"], 80.0)
        self.assertAlmostEqual(group["currentAcdcExportKw"], 50.0)
        self.assertAlmostEqual(group["finalAcdcExportKw"], 50.0)
        self.assertAlmostEqual(group["renewableDeliveredThroughAcdcKw"], 50.0)
        self.assertAlmostEqual(metrics["dcRenewableToAcKw"], 50.0)
        self.assertAlmostEqual(metrics["dcGridStorageCurrentKw"], 0.0)
        self.assertAlmostEqual(metrics["dcBalanceStorageCurrentKw"], 0.0)
        self.assertIsNone(metrics["storageCurrentKw"])
        self.assertIsNone(metrics["storageSoc"])
        self.assertFalse(
            any(
                command["dev_name"] == "invalid-manual-dc-storage"
                for command in plan["commands"]
            )
        )

    def test_legacy_storage_aggregates_include_online_uncontrolled_storage(self):
        snapshot = direct_grid_storage_snapshot(
            diesel_power_kw=80.0,
            include_ac_storage=False,
            include_dc_storage=False,
            converter_power_kw=-30.0,
            converter_capacity_kw=50.0,
        )
        add_generator_device(
            snapshot,
            dev_type="ACGenerator",
            name="manual-ac-storage",
            idx=3,
            node=2,
            mode="MANUAL",
            power_kw=-7.0,
            rated_capacity_kw=20.0,
            set_type="p_set",
            soc=0.33,
        )
        add_generator_device(
            snapshot,
            dev_type="DCGenerator",
            name="manual-dc-storage",
            idx=3,
            node=3,
            mode="MANUAL",
            power_kw=5.0,
            rated_capacity_kw=20.0,
            set_type="p_set",
            soc=1.50,
        )
        snapshot["device_parameters"]["ACStorageGen"] = [
            {
                "idx": 1,
                "idx_acgenerator": 3,
                "energy_capacity": 100.0,
                "charge_discharge_efficiency": 1.0,
                "max_charge_power": 20.0,
                "max_discharge_power": 20.0,
                "soc_upper_limit": 90.0,
                "soc_lower_limit": 20.0,
            }
        ]
        snapshot["device_parameters"]["DCStorageGen"] = [
            {
                "idx": 1,
                "idx_dcgenerator": 3,
                "energy_capacity": 300.0,
                "charge_discharge_efficiency": 1.0,
                "max_charge_power": 20.0,
                "max_discharge_power": 20.0,
                "soc_upper_limit": 90.0,
                "soc_lower_limit": 20.0,
            }
        ]

        plan = calculate_renewable_control_plan(snapshot)
        metrics = plan["metrics"]

        self.assertAlmostEqual(metrics["storageCurrentKw"], -2.0)
        self.assertAlmostEqual(metrics["storageSoc"], 1.2075)
        self.assertAlmostEqual(metrics["acGridStorageCurrentKw"], 0.0)
        self.assertAlmostEqual(metrics["dcGridStorageCurrentKw"], 0.0)
        self.assertAlmostEqual(metrics["acBalanceStorageCurrentKw"], 0.0)
        self.assertAlmostEqual(metrics["dcBalanceStorageCurrentKw"], 0.0)

    def test_task8_decision_detail_has_stable_phases_and_topology_diagnostics(self):
        plan = calculate_renewable_control_plan(
            task8_metrics_snapshot(),
            RenewableControlSettings(step_coefficient=0.10, converter_step_ratio=0.25),
        )
        detail = "\n".join(plan["decisionDetail"])

        for phase in (
            "phase=topology",
            "phase=side/role totals",
            "phase=ACDC balance candidate",
            "phase=direct-storage allocation",
            "phase=renewable sink allocation",
            "phase=unified validation",
            "phase=dispatch result",
        ):
            with self.subTest(phase=phase):
                self.assertIn(phase, detail)

        for fragment in (
            "device=wind-1",
            "device=pv-1",
            "device=ac-grid-storage",
            "device=dc-grid-storage",
            "side=AC",
            "side=DC",
            "bus=",
            "group=",
            "currentKw=",
            "candidateDeltaKw=",
            "acceptedDeltaKw=",
            "limit=",
            "loop=open-loop-preview",
            "loop=closed-loop-command",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, detail)


class RenewableControlBackendApiTest(unittest.TestCase):
    def _configuration_action_after_same_id_recreate(self, payload):
        with tempfile.TemporaryDirectory() as temporary:
            services, old_service, exchange, manager = make_deletable_exchange_backed_control_manager(
                temporary,
            )
            old_state = manager._state_for("shared")
            state_captured = threading.Event()
            result = {}
            original_state_for_service = manager._state_for_service
            state_lock_held = False

            def capture_old_state(service):
                captured = original_state_for_service(service)
                if service is old_service and captured is old_state:
                    state_captured.set()
                return captured

            def apply_old_action():
                try:
                    result["value"] = manager.apply_action("shared", payload)
                except Exception as exc:
                    result["error"] = exc

            action_thread = threading.Thread(target=apply_old_action, daemon=True)
            try:
                old_state.lock.acquire()
                state_lock_held = True
                with patch.object(
                    manager,
                    "_state_for_service",
                    side_effect=capture_old_state,
                ):
                    action_thread.start()
                    self.assertTrue(state_captured.wait(timeout=2.0))

                    old_service.set_trainee_receive_state({"active": False})
                    services.delete_model("shared")
                    services.create_model_slot("shared")
                    new_service = services.service_for("shared")
                    persistence_file = (
                        new_service.runtime_dir
                        / renewable_control_module.RENEWABLE_CONTROL_STATE_FILE
                    )

                    old_state.lock.release()
                    state_lock_held = False
                    action_thread.join(timeout=2.0)
                    self.assertFalse(action_thread.is_alive())

                new_payload = manager.state("shared")
                new_state = manager._states["shared"]
                manager.remove_model_for_service(old_service)
                exchange.remove_model_for_service(old_service)
                self.assertIs(manager._states["shared"], new_state)
                persisted_payload = (
                    json.loads(persistence_file.read_text(encoding="utf-8"))
                    if persistence_file.exists()
                    else None
                )
                persistence_exists = persistence_file.exists()
            finally:
                if state_lock_held:
                    old_state.lock.release()
                action_thread.join(timeout=2.0)
                manager.close()
                exchange.close()

        return result, new_payload, persistence_exists, persisted_payload

    def _control_action_after_same_id_recreate(self, payload):
        with tempfile.TemporaryDirectory() as temporary:
            services, old_service, exchange, manager = make_deletable_exchange_backed_control_manager(
                temporary,
            )
            old_state = manager._state_for("shared")
            old_state.loop_mode = "closed"
            action_captured = threading.Event()
            release_action = threading.Event()
            capture_consumed = threading.Event()
            result = {}
            transport_calls = []
            original_state_for_service = manager._state_for_service
            action_thread = None

            def block_after_old_state_capture(service):
                captured = original_state_for_service(service)
                if (
                    service is old_service
                    and threading.current_thread() is action_thread
                    and not capture_consumed.is_set()
                ):
                    capture_consumed.set()
                    action_captured.set()
                    self.assertTrue(release_action.wait(timeout=3.0))
                return captured

            def apply_old_action():
                try:
                    result["value"] = manager.apply_action("shared", payload)
                except Exception as exc:
                    result["error"] = exc

            action_thread = threading.Thread(target=apply_old_action, daemon=True)
            try:
                with patch.object(
                    manager,
                    "_state_for_service",
                    side_effect=block_after_old_state_capture,
                ):
                    action_thread.start()
                    self.assertTrue(action_captured.wait(timeout=3.0))

                    old_service.set_trainee_receive_state({"active": False})
                    services.delete_model("shared")
                    exchange.remove_model_for_service(old_service)
                    manager.remove_model_for_service(old_service)
                    services.create_model_slot("shared")
                    new_service = services.service_for("shared")
                    new_service.set_trainee_receive_state(
                        {
                            "initialized": True,
                            "active": True,
                            "interaction_link": "http://teacher-new.invalid/api/trainee-link?model_id=teacher-new",
                            "teacher_api_base": "http://teacher-new.invalid",
                            "snapshot_path": "/api/snapshot?model_id=teacher-new",
                            "command_path": "/api/student/commands?model_id=teacher-new",
                            "teacher_model_id": "teacher-new",
                        }
                    )
                    exchange.notify_receive_state_changed_for_service(new_service)
                    exchange.publish_runtime_snapshot(
                        "shared",
                        renewable_snapshot(),
                        connection_signature=exchange._connection_signature(new_service),
                    )
                    new_state = manager._state_for_service(new_service)
                    new_state.loop_mode = "closed"
                    new_state.enabled = False
                    new_state.status = "new-lifecycle-status"
                    new_state.last_dispatched_clock_key = "new-prior-clock"
                    new_state.last_dispatched_generation_key = ("new-prior-generation",)
                    exchange.request_json = lambda url, **kwargs: transport_calls.append(
                        (url, copy.deepcopy(kwargs))
                    ) or {"set_values": 1}

                    release_action.set()
                    action_thread.join(timeout=5.0)
                    self.assertFalse(action_thread.is_alive())
            finally:
                release_action.set()
                action_thread.join(timeout=2.0)
                manager.close()
                exchange.close()

            new_payload = manager._serialize(new_state)

        return result, new_payload, transport_calls

    def test_old_renewable_control_refresh_cannot_touch_recreated_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            services, old_service, exchange, manager = (
                make_deletable_exchange_backed_control_manager(temporary)
            )
            manager.snapshot_provider = exchange.control_snapshot
            manager.receive_status_provider = exchange.receive_status
            manager.command_sink = exchange.submit_commands
            server = make_http_server(
                ("127.0.0.1", 0),
                services,
                role="trainee",
                trainee_exchange=exchange,
                renewable_control_manager=manager,
            )
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            captured_old_service = threading.Event()
            release_request = threading.Event()
            capture_consumed = threading.Event()
            original_service_for = services.service_for
            request_result = {}
            provider_calls = []

            def coordinated_service_for(model_id=None):
                resolved = original_service_for(model_id)
                if (
                    str(model_id or "") == "shared"
                    and not capture_consumed.is_set()
                    and threading.current_thread() is not threading.main_thread()
                ):
                    capture_consumed.set()
                    captured_old_service.set()
                    self.assertTrue(release_request.wait(timeout=3.0))
                return resolved

            def send_old_refresh():
                try:
                    with urlopen(
                        f"http://127.0.0.1:{server.server_address[1]}"
                        "/api/trainee/renewable-control?model_id=shared&refresh=1",
                        timeout=5,
                    ) as response:
                        request_result["status"] = response.status
                        request_result["body"] = json.loads(response.read().decode("utf-8"))
                except HTTPError as exc:
                    request_result["status"] = exc.code
                    request_result["body"] = json.loads(exc.read().decode("utf-8"))
                except Exception as exc:  # pragma: no cover - asserted in the parent thread.
                    request_result["error"] = exc

            services.service_for = coordinated_service_for
            request_thread = threading.Thread(target=send_old_refresh, daemon=True)
            try:
                request_thread.start()
                self.assertTrue(captured_old_service.wait(timeout=2.0))

                old_service.set_trainee_receive_state({"active": False})
                services.delete_model("shared")
                exchange.remove_model_for_service(old_service)
                manager.remove_model_for_service(old_service)
                services.create_model_slot("shared")
                new_service = original_service_for("shared")
                new_service.set_trainee_receive_state(
                    {
                        "initialized": True,
                        "active": True,
                        "interaction_link": "http://teacher-b.invalid/api/trainee-link?model_id=teacher-b",
                        "teacher_api_base": "http://teacher-b.invalid",
                        "snapshot_path": "/api/snapshot?model_id=teacher-b",
                        "command_path": "/api/student/commands?model_id=teacher-b",
                        "teacher_model_id": "teacher-b",
                    }
                )
                exchange.notify_receive_state_changed_for_service(new_service)
                baseline = renewable_snapshot()
                baseline["clock"]["time"] = "new-b-ready-clock"
                exchange.publish_runtime_snapshot(
                    "shared",
                    baseline,
                    connection_signature=exchange._connection_signature(new_service),
                )
                new_state = manager._state_for_live_service(new_service)
                with new_state.lock:
                    new_state.status = "new-b-status"
                    new_state.last_plan = {"clockKey": "new-b-plan"}
                    new_state.last_calculated_at = "new-b-calculated"
                    new_state.logs = [{"seq": 9, "result": "new-b-log"}]
                    new_state.log_seq = 9
                    new_state.trend = [{"sampleKey": "new-b-trend"}]
                    new_state.revision = 41
                    new_state.last_preview_started = 17.0
                    before_state = {
                        "status": new_state.status,
                        "last_plan": copy.deepcopy(new_state.last_plan),
                        "last_calculated_at": new_state.last_calculated_at,
                        "logs": copy.deepcopy(new_state.logs),
                        "log_seq": new_state.log_seq,
                        "trend": copy.deepcopy(new_state.trend),
                        "revision": new_state.revision,
                        "last_preview_started": new_state.last_preview_started,
                    }
                original_control_snapshot_for_service = exchange.control_snapshot_for_service

                def recording_provider(service):
                    provider_calls.append(service)
                    return original_control_snapshot_for_service(service)

                exchange.control_snapshot_for_service = recording_provider
                release_request.set()
                request_thread.join(timeout=5.0)
                self.assertFalse(request_thread.is_alive())
                with new_state.lock:
                    after_state = {
                        "status": new_state.status,
                        "last_plan": copy.deepcopy(new_state.last_plan),
                        "last_calculated_at": new_state.last_calculated_at,
                        "logs": copy.deepcopy(new_state.logs),
                        "log_seq": new_state.log_seq,
                        "trend": copy.deepcopy(new_state.trend),
                        "revision": new_state.revision,
                        "last_preview_started": new_state.last_preview_started,
                    }
            finally:
                release_request.set()
                request_thread.join(timeout=2.0)
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=5)

        self.assertNotIn("error", request_result)
        self.assertEqual(request_result.get("status"), 409, request_result)
        self.assertRegex(
            str(request_result.get("body", {}).get("error", "")),
            "生命周期|失效|删除|退休",
        )
        self.assertEqual(provider_calls, [])
        self.assertIs(manager._states["shared"], new_state)
        self.assertEqual(after_state, before_state)

    def test_realtime_control_waits_for_the_first_learner_exchange_frame(self):
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": True,
                "ready": False,
                "revision": 0,
                "signature": ("learner", "waiting"),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            snapshot_calls = []
            manager = make_control_manager(
                services,
                snapshot_provider=lambda model_id: snapshot_calls.append(model_id),
                receive_status_provider=mutable_receive_status(receive_state),
            )
            try:
                controller_state = manager.apply_action("shared", {"action": "start"})
            finally:
                manager.close()

        self.assertFalse(controller_state["enabled"])
        self.assertTrue(controller_state["receiveActive"])
        self.assertFalse(controller_state["ready"])
        self.assertFalse(controller_state["canRun"])
        self.assertIn("等待第一份实时数据", controller_state["status"])
        self.assertEqual(snapshot_calls, [])

    def test_cached_learner_exchange_data_allows_observation_but_blocks_closed_loop_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            dispatched = []
            snapshot = renewable_snapshot()
            manager = make_control_manager(
                services,
                snapshot_provider=lambda _model_id: ready_view(
                    snapshot,
                    age=5.0,
                    error="realtime update failed",
                ),
                command_sink=lambda model_id, payload: dispatched.append((model_id, payload)) or {},
            )
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            try:
                controller_state = manager.run_once(
                    "shared",
                    trigger="auto",
                    allow_dispatch=True,
                    record_log=True,
                )
            finally:
                manager.close()

        self.assertIsNotNone(controller_state["lastPlan"])
        self.assertEqual(controller_state["lastPlan"]["dataQuality"]["source"], "trainee-cache")
        self.assertFalse(controller_state["lastPlan"]["dataQuality"]["dispatchAllowed"])
        self.assertEqual(dispatched, [])
        self.assertIn("数据质量", controller_state["status"])

    def test_frozen_learner_frame_allows_plan_but_blocks_closed_loop_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            dispatched = []
            manager = make_control_manager(
                services,
                snapshot=renewable_snapshot(),
                receive_status_provider=lambda _model_id: {
                    "receiveActive": True,
                    "ready": True,
                    "canRun": True,
                    "canCalculate": True,
                    "canDispatch": False,
                    "dispatchStatus": "实时数据帧已冻结，闭环下发已阻断。",
                    "revision": 1,
                    "receiveEpoch": 0,
                    "connectionSignature": ["learner", 1],
                    "prerequisiteStatus": "",
                },
                command_sink=lambda model_id, payload: dispatched.append((model_id, payload)) or {},
            )
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            try:
                controller_state = manager.run_once(
                    "shared",
                    trigger="auto",
                    allow_dispatch=True,
                    record_log=True,
                )
            finally:
                manager.close()

        self.assertIsNotNone(controller_state["lastPlan"])
        self.assertEqual(dispatched, [])
        self.assertTrue(controller_state["canCalculate"])
        self.assertFalse(controller_state["canDispatch"])
        self.assertIn("冻结", controller_state["status"])

    def test_realtime_control_start_requires_active_receive_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": False,
                "ready": False,
                "revision": 1,
                "signature": ("learner", 1),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: dict(receive_state),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            manager = make_control_manager(
                services,
                receive_status_provider=mutable_receive_status(receive_state),
            )
            try:
                controller_state = manager.apply_action("shared", {"action": "start"})
            finally:
                manager.close()

        self.assertFalse(controller_state["enabled"])
        self.assertFalse(controller_state["receiveActive"])
        self.assertFalse(controller_state["canRun"])
        self.assertIn("启动接收", controller_state["status"])
        self.assertEqual(controller_state["lastCalculatedAt"], "")

    def test_requested_realtime_control_waits_for_receive_then_resumes(self):
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": False,
                "ready": False,
                "revision": 1,
                "signature": ("learner", 1),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: dict(receive_state),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            snapshot_calls = []
            dispatched = []
            manager = make_control_manager(
                services,
                snapshot_provider=lambda model_id: snapshot_calls.append(model_id) or ready_view(
                    renewable_snapshot()
                ),
                receive_status_provider=mutable_receive_status(receive_state),
                command_sink=lambda model_id, payload: dispatched.append((model_id, payload)) or {},
            )
            try:
                manager.apply_action(
                    "shared",
                    {"action": "set_loop_mode", "loop_mode": "closed"},
                )
                blocked = manager.apply_action("shared", {"action": "start"})
                self.assertFalse(blocked["enabled"])
                self.assertTrue(blocked["desiredEnabled"])
                self.assertTrue(blocked["resumePending"])
                self.assertIn("启动接收", blocked["status"])
                persisted = json.loads(
                    (Path(temporary) / "renewable_control.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertTrue(persisted["desiredEnabled"])

                receive_state.update({
                    "active": True,
                    "ready": True,
                    "revision": 2,
                    "signature": ("learner", 2),
                })
                recovered = manager.receive_state_changed("shared")
                manager._run_worker_iteration(now=time.monotonic())
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and not dispatched:
                    time.sleep(0.01)
            finally:
                manager.close()

        self.assertTrue(recovered["receiveActive"])
        self.assertTrue(recovered["ready"])
        self.assertTrue(recovered["canRun"])
        self.assertTrue(recovered["enabled"])
        self.assertTrue(recovered["desiredEnabled"])
        self.assertFalse(recovered["resumePending"])
        self.assertIn("自动恢复", recovered["status"])
        self.assertEqual(snapshot_calls, ["shared"])
        self.assertEqual(len(dispatched), 1)

    def test_receive_recovery_preserves_meaningful_non_prerequisite_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": True,
                "ready": True,
                "revision": 1,
                "signature": ("learner", 1),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            snapshot_calls = []
            dispatched = []
            manager = make_control_manager(
                services,
                snapshot_provider=lambda model_id: snapshot_calls.append(model_id),
                receive_status_provider=mutable_receive_status(receive_state),
                command_sink=lambda model_id, payload: dispatched.append((model_id, payload)) or {},
            )
            try:
                stopped = manager.apply_action("shared", {"action": "stop"})
                self.assertEqual(stopped["status"], "实时控制已在学员台后台停止。")

                receive_state.update({
                    "revision": 2,
                    "signature": ("learner", 2),
                })
                recovered = manager.receive_state_changed("shared")
            finally:
                manager.close()

        self.assertTrue(recovered["canRun"])
        self.assertFalse(recovered["enabled"])
        self.assertEqual(recovered["status"], "实时控制已在学员台后台停止。")
        self.assertEqual(snapshot_calls, [])
        self.assertEqual(dispatched, [])

    def test_temporary_receive_stop_preserves_intent_and_resumes_controller(self):
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": True,
                "ready": True,
                "revision": 1,
                "signature": ("learner", 1),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            snapshot_calls = []
            dispatched = []
            active_snapshot = renewable_snapshot()

            def snapshot_provider(model_id):
                snapshot_calls.append(model_id)
                return ready_view(
                    active_snapshot,
                    revision=receive_state["revision"],
                    signature=receive_state["signature"],
                )

            manager = make_control_manager(
                services,
                snapshot_provider=snapshot_provider,
                receive_status_provider=mutable_receive_status(receive_state),
                command_sink=lambda model_id, payload: dispatched.append((model_id, payload)) or {},
            )
            try:
                manager.apply_action(
                    "shared",
                    {"action": "set_loop_mode", "loop_mode": "closed"},
                )
                started = manager.apply_action("shared", {"action": "start"})
                self.assertTrue(started["enabled"])
                self.assertTrue(started["desiredEnabled"])
                snapshot_calls.clear()
                dispatched.clear()
                receive_state.update({
                    "active": False,
                    "ready": False,
                    "revision": 2,
                    "signature": ("learner", 2),
                })
                stopped = manager.receive_state_changed("shared")
                self.assertFalse(stopped["enabled"])
                self.assertTrue(stopped["desiredEnabled"])
                self.assertTrue(stopped["resumePending"])
                self.assertIn("接收已停止", stopped["status"])

                receive_state.update({
                    "active": True,
                    "ready": True,
                    "revision": 3,
                    "signature": ("learner", 3),
                })
                active_snapshot["clock"].update({
                    "time": "00:01:00",
                    "minute": 1,
                    "absolute_minute": 1,
                    "step_count": 1,
                })
                recovered = manager.receive_state_changed("shared")
                manager._run_worker_iteration(now=time.monotonic())
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and not dispatched:
                    time.sleep(0.01)
            finally:
                manager.close()

        self.assertTrue(recovered["receiveActive"])
        self.assertTrue(recovered["ready"])
        self.assertTrue(recovered["canRun"])
        self.assertTrue(recovered["enabled"])
        self.assertTrue(recovered["desiredEnabled"])
        self.assertFalse(recovered["resumePending"])
        self.assertIn("自动恢复", recovered["status"])
        self.assertEqual(snapshot_calls, ["shared"])
        self.assertEqual(len(dispatched), 1)

    def test_ready_preview_after_active_waiting_receive_clears_stale_prerequisite_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": False,
                "ready": False,
                "revision": 1,
                "signature": ("learner", "inactive"),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            snapshot_calls = []
            dispatched = []

            def snapshot_provider(model_id):
                snapshot_calls.append(model_id)
                snapshot = renewable_snapshot()
                snapshot["clock"].update({
                    "time": "00:00:01",
                    "minute": 1,
                    "absolute_minute": 1,
                })
                return ready_view(
                    snapshot,
                    revision=3,
                    signature=("learner", "ready"),
                )

            manager = make_control_manager(
                services,
                snapshot_provider=snapshot_provider,
                receive_status_provider=mutable_receive_status(receive_state),
                command_sink=lambda model_id, payload: dispatched.append((model_id, payload)) or {},
            )
            try:
                inactive = manager.apply_action("shared", {"action": "run_once"})
                self.assertIn("请先启动接收", inactive["status"])

                receive_state.update({
                    "active": True,
                    "ready": False,
                    "revision": 2,
                    "signature": ("learner", "waiting"),
                })
                waiting = manager.receive_state_changed("shared")
                self.assertTrue(waiting["receiveActive"])
                self.assertFalse(waiting["ready"])
                self.assertFalse(waiting["canRun"])
                self.assertIn("请先启动接收", waiting["status"])

                receive_state.update({
                    "active": True,
                    "ready": True,
                    "revision": 3,
                    "signature": ("learner", "ready"),
                })
                ready = manager.state("shared", refresh=True)
            finally:
                manager.close()

        self.assertTrue(ready["receiveActive"])
        self.assertTrue(ready["ready"])
        self.assertTrue(ready["canRun"])
        self.assertFalse(ready["enabled"])
        self.assertEqual(ready["lastPlan"]["time"], "00:00:01")
        self.assertEqual(ready["status"], "请选择单次计算或启动实时控制。")
        self.assertEqual(ready["lastDispatchedClockKey"], "")
        self.assertEqual(ready["lastSentAt"], "")
        self.assertEqual(snapshot_calls, ["shared"])
        self.assertEqual(dispatched, [])

    def test_ready_preview_preserves_meaningful_idle_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": True,
                "ready": True,
                "revision": 1,
                "signature": ("learner", 1),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            dispatched = []
            manager = make_control_manager(
                services,
                snapshot_provider=lambda _model_id: ready_view(renewable_snapshot()),
                receive_status_provider=mutable_receive_status(receive_state),
                command_sink=lambda model_id, payload: dispatched.append((model_id, payload)) or {},
            )
            try:
                state = manager._state_for("shared")
                with state.lock:
                    state.status = "实时控制已在学员台后台停止。"
                    state.revision += 1
                ready = manager.state("shared", refresh=True)
            finally:
                manager.close()

        self.assertTrue(ready["canRun"])
        self.assertFalse(ready["enabled"])
        self.assertIsNotNone(ready["lastPlan"])
        self.assertEqual(ready["status"], "实时控制已在学员台后台停止。")
        self.assertEqual(dispatched, [])

    def test_single_control_calculation_requires_active_receive_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": False,
                "ready": False,
                "revision": 1,
                "signature": ("learner", 1),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: dict(receive_state),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            manager = make_control_manager(
                services,
                receive_status_provider=mutable_receive_status(receive_state),
            )
            try:
                controller_state = manager.apply_action("shared", {"action": "run_once"})
            finally:
                manager.close()

        self.assertFalse(controller_state["enabled"])
        self.assertFalse(controller_state["canRun"])
        self.assertIn("启动接收", controller_state["status"])
        self.assertEqual(controller_state["lastCalculatedAt"], "")

    def test_manual_run_once_waits_for_active_preview_and_dispatches_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": True,
                "ready": True,
                "revision": 1,
                "signature": ("learner", 1),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            preview_entered = threading.Event()
            release_preview = threading.Event()
            snapshot_calls = []
            dispatched = []

            def snapshot_provider(_model_id):
                call_number = len(snapshot_calls) + 1
                snapshot_calls.append(call_number)
                if call_number == 1:
                    preview_entered.set()
                    self.assertTrue(release_preview.wait(timeout=2.0))
                snapshot = renewable_snapshot()
                snapshot["clock"]["absolute_minute"] = call_number
                snapshot["clock"]["minute"] = call_number
                snapshot["clock"]["time"] = f"00:{call_number:02d}:00"
                return ready_view(snapshot)

            manager = make_control_manager(
                services,
                snapshot_provider=snapshot_provider,
                receive_status_provider=mutable_receive_status(receive_state),
                command_sink=lambda model_id, payload: dispatched.append((model_id, payload)) or {
                    "set_values": len(payload.get("set_values", []))
                },
            )
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.status = "新能源实时控制参数已更新并持久化。"
            preview_result = {}
            preview_thread = threading.Thread(
                target=lambda: preview_result.update(manager.collect_once("shared")),
                daemon=True,
            )
            try:
                preview_thread.start()
                self.assertTrue(preview_entered.wait(timeout=1.0))
                release_timer = threading.Timer(0.05, release_preview.set)
                release_timer.start()
                controller_state = manager.run_once(
                    "shared",
                    trigger="manual",
                    allow_dispatch=True,
                    record_log=True,
                )
                release_timer.join(timeout=1.0)
                preview_thread.join(timeout=1.0)
            finally:
                release_preview.set()
                manager.close()

        self.assertEqual(snapshot_calls, [1, 2])
        self.assertEqual(len(dispatched), 1)
        self.assertNotEqual(controller_state["status"], "新能源实时控制参数已更新并持久化。")
        self.assertIn("已向学员台指令入口提交", controller_state["status"])
        self.assertNotEqual(controller_state["lastDispatchedClockKey"], "")
        self.assertTrue(
            any(item["result"] == "计算完成" for item in controller_state["logs"])
        )

    def test_runtime_snapshot_revision_change_during_manual_run_cancels_cycle(self):
        original_calculate = renewable_control_module.calculate_renewable_control_plan
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": True,
                "ready": True,
                "revision": 10,
                "receive_epoch": 4,
                "signature": ("learner", "same-link"),
            }

            def receive_status(_model_id):
                return {
                    "receiveActive": bool(receive_state["active"]),
                    "ready": bool(receive_state["ready"]),
                    "canRun": bool(receive_state["active"] and receive_state["ready"]),
                    "revision": int(receive_state["revision"]),
                    "receiveEpoch": int(receive_state["receive_epoch"]),
                    "connectionSignature": list(receive_state["signature"]),
                    "prerequisiteStatus": "",
                }

            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            dispatched = []

            def calculate_after_publish(*args, **kwargs):
                receive_state["revision"] += 1
                return original_calculate(*args, **kwargs)

            manager = make_control_manager(
                services,
                snapshot=renewable_snapshot(),
                receive_status_provider=receive_status,
                command_sink=lambda model_id, payload: dispatched.append((model_id, payload)) or {
                    "set_values": len(payload.get("set_values", []))
                },
            )
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            try:
                with patch.object(
                    renewable_control_module,
                    "calculate_renewable_control_plan",
                    side_effect=calculate_after_publish,
                ):
                    controller_state = manager.run_once(
                        "shared",
                        trigger="manual",
                        allow_dispatch=True,
                        record_log=True,
                    )
            finally:
                manager.close()

        self.assertEqual(receive_state["revision"], 11)
        self.assertEqual(dispatched, [])
        self.assertIsNone(controller_state["lastPlan"])
        self.assertEqual(controller_state["lastCalculatedAt"], "")
        self.assertEqual(controller_state["lastDispatchedClockKey"], "")
        self.assertNotIn("已向学员台指令入口提交", controller_state["status"])
        self.assertFalse(
            any(item["result"] == "计算完成" for item in controller_state["logs"])
        )
        self.assertFalse(
            any(item["result"] == "下发成功" for item in controller_state["logs"])
        )

    def test_receive_epoch_change_during_manual_run_cancels_candidate(self):
        original_calculate = renewable_control_module.calculate_renewable_control_plan
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": True,
                "ready": True,
                "revision": 10,
                "receive_epoch": 4,
                "signature": ("learner", "same-link"),
            }

            def receive_status(_model_id):
                return {
                    "receiveActive": bool(receive_state["active"]),
                    "ready": bool(receive_state["ready"]),
                    "canRun": bool(receive_state["active"] and receive_state["ready"]),
                    "revision": int(receive_state["revision"]),
                    "receiveEpoch": int(receive_state["receive_epoch"]),
                    "connectionSignature": list(receive_state["signature"]),
                    "prerequisiteStatus": "",
                }

            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            dispatched = []

            def calculate_after_receive_epoch_change(*args, **kwargs):
                receive_state["receive_epoch"] += 1
                return original_calculate(*args, **kwargs)

            manager = make_control_manager(
                services,
                snapshot=renewable_snapshot(),
                receive_status_provider=receive_status,
                command_sink=lambda model_id, payload: dispatched.append((model_id, payload)) or {},
            )
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            state.last_plan = {"time": "prior", "commands": []}
            state.last_calculated_at = "prior-calculated"
            state.last_dispatched_clock_key = "prior-clock"
            state.last_sent_at = "prior-sent"
            try:
                with patch.object(
                    renewable_control_module,
                    "calculate_renewable_control_plan",
                    side_effect=calculate_after_receive_epoch_change,
                ):
                    controller_state = manager.run_once(
                        "shared",
                        trigger="manual",
                        allow_dispatch=True,
                        record_log=True,
                    )
            finally:
                manager.close()

        self.assertEqual(controller_state["lastCalculatedAt"], "prior-calculated")
        self.assertEqual(controller_state["lastPlan"], {"time": "prior", "commands": []})
        self.assertEqual(controller_state["lastDispatchedClockKey"], "prior-clock")
        self.assertEqual(controller_state["lastSentAt"], "prior-sent")
        self.assertEqual(dispatched, [])

    def test_late_receive_generation_change_during_run_once_preserves_prior_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            service, exchange, manager, dispatched = make_exchange_backed_control_manager(
                temporary,
            )
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            prior_plan = {"time": "prior", "clockKey": "prior-clock-key", "commands": []}
            prior_logs = [
                {
                    "seq": 7,
                    "wall_time": "prior-wall",
                    "simu_time": "prior",
                    "type": "策略控制",
                    "target": "新能源优先",
                    "result": "保留",
                    "detail": "existing",
                    "level": "info",
                }
            ]
            prior_trend = [
                {
                    "sampleKey": "1|1|prior",
                    "runId": 1,
                    "stepCount": 1,
                    "minute": 1,
                    "time": "prior",
                }
            ]
            state.last_plan = copy.deepcopy(prior_plan)
            state.last_calculated_at = "prior-calculated"
            state.last_clock_key = "prior-clock-key"
            state.last_dispatched_clock_key = "prior-dispatched-clock"
            state.last_sent_at = "prior-sent"
            state.status = "prior-status"
            state.logs = copy.deepcopy(prior_logs)
            state.log_seq = 7
            state.trend = copy.deepcopy(prior_trend)
            state.trend_normalized = True
            original_update_trend = manager._update_trend

            def invalidate_during_trend(candidate_state, plan, snapshot):
                exchange.invalidate_model("shared")
                return original_update_trend(candidate_state, plan, snapshot)

            try:
                with patch.object(
                    manager,
                    "_update_trend",
                    side_effect=invalidate_during_trend,
                ):
                    controller_state = manager.run_once(
                        "shared",
                        trigger="manual",
                        allow_dispatch=True,
                        record_log=True,
                    )
            finally:
                manager.close()
                exchange.close()

        self.assertEqual(controller_state["lastPlan"], prior_plan)
        self.assertEqual(controller_state["lastCalculatedAt"], "prior-calculated")
        self.assertEqual(controller_state["logs"], prior_logs)
        self.assertEqual(controller_state["trend"], prior_trend)
        self.assertEqual(controller_state["lastDispatchedClockKey"], "prior-dispatched-clock")
        self.assertEqual(controller_state["lastSentAt"], "prior-sent")
        self.assertEqual(controller_state["status"], "prior-status")
        self.assertEqual(state.last_clock_key, "prior-clock-key")
        self.assertFalse(controller_state["sending"])
        self.assertEqual(dispatched, [])

    def test_late_receive_generation_change_during_collect_once_preserves_prior_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            _service, exchange, manager, _dispatched = make_exchange_backed_control_manager(
                temporary,
            )
            state = manager._state_for("shared")
            prior_plan = {"time": "prior", "clockKey": "prior-clock-key", "commands": []}
            prior_trend = [
                {
                    "sampleKey": "1|1|prior",
                    "runId": 1,
                    "stepCount": 1,
                    "minute": 1,
                    "time": "prior",
                }
            ]
            state.last_plan = copy.deepcopy(prior_plan)
            state.last_calculated_at = "prior-calculated"
            state.last_clock_key = "prior-clock-key"
            state.status = "prior-status"
            state.trend = copy.deepcopy(prior_trend)
            state.trend_normalized = True
            original_update_trend = manager._update_trend

            def invalidate_during_trend(candidate_state, plan, snapshot):
                exchange.invalidate_model("shared")
                return original_update_trend(candidate_state, plan, snapshot)

            try:
                with patch.object(
                    manager,
                    "_update_trend",
                    side_effect=invalidate_during_trend,
                ):
                    controller_state = manager.collect_once("shared")
            finally:
                manager.close()
                exchange.close()

        self.assertEqual(controller_state["lastPlan"], prior_plan)
        self.assertEqual(controller_state["lastCalculatedAt"], "prior-calculated")
        self.assertEqual(controller_state["trend"], prior_trend)
        self.assertEqual(controller_state["status"], "prior-status")
        self.assertEqual(state.last_clock_key, "prior-clock-key")

    def test_definition_revision_change_during_calculation_cancels_candidate_atomically(self):
        original_calculate = renewable_control_module.calculate_renewable_control_plan
        with tempfile.TemporaryDirectory() as temporary:
            service, exchange, manager, dispatched = make_exchange_backed_control_manager(
                temporary,
            )
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            prior_plan = {"time": "prior", "clockKey": "prior-clock-key", "commands": []}
            prior_logs = [
                {
                    "seq": 4,
                    "wall_time": "prior-wall",
                    "simu_time": "prior",
                    "type": "策略控制",
                    "target": "新能源优先",
                    "result": "保留",
                    "detail": "existing",
                    "level": "info",
                }
            ]
            prior_trend = [
                {
                    "sampleKey": "1|1|prior",
                    "runId": 1,
                    "stepCount": 1,
                    "minute": 1,
                    "time": "prior",
                }
            ]
            state.last_plan = copy.deepcopy(prior_plan)
            state.last_calculated_at = "prior-calculated"
            state.last_clock_key = "prior-clock-key"
            state.last_dispatched_clock_key = "prior-dispatched-clock"
            state.last_sent_at = "prior-sent"
            state.status = "prior-status"
            state.logs = copy.deepcopy(prior_logs)
            state.log_seq = 4
            state.trend = copy.deepcopy(prior_trend)
            state.trend_normalized = True

            def calculate_then_edit_definition(*args, **kwargs):
                plan = original_calculate(*args, **kwargs)
                service.advance_definition_revision()
                return plan

            try:
                with patch.object(
                    renewable_control_module,
                    "calculate_renewable_control_plan",
                    side_effect=calculate_then_edit_definition,
                ):
                    controller_state = manager.run_once(
                        "shared",
                        trigger="manual",
                        allow_dispatch=True,
                        record_log=True,
                    )
            finally:
                manager.close()
                exchange.close()

        self.assertEqual(service.definition_snapshot.revision, 2)
        self.assertEqual(controller_state["lastPlan"], prior_plan)
        self.assertEqual(controller_state["lastCalculatedAt"], "prior-calculated")
        self.assertEqual(controller_state["logs"], prior_logs)
        self.assertEqual(controller_state["trend"], prior_trend)
        self.assertEqual(controller_state["lastDispatchedClockKey"], "prior-dispatched-clock")
        self.assertEqual(controller_state["lastSentAt"], "prior-sent")
        self.assertEqual(controller_state["status"], "prior-status")
        self.assertEqual(state.last_clock_key, "prior-clock-key")
        self.assertFalse(controller_state["sending"])
        self.assertEqual(dispatched, [])

    def test_stop_during_blocked_auto_cycle_cancels_candidate_and_preserves_stop_state(self):
        original_calculate = renewable_control_module.calculate_renewable_control_plan
        calculation_started = threading.Event()
        release_calculation = threading.Event()

        def blocking_calculate(*args, **kwargs):
            calculation_started.set()
            self.assertTrue(release_calculation.wait(timeout=2.0))
            return original_calculate(*args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            _service, exchange, manager, _dispatched = make_exchange_backed_control_manager(
                temporary,
            )
            transport_calls = []
            exchange.request_json = lambda url, **kwargs: transport_calls.append(
                (url, copy.deepcopy(kwargs))
            ) or {"set_values": 1}
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            prior_plan = {"time": "prior", "clockKey": "prior-clock", "commands": []}
            prior_trend = [{"sampleKey": "1|1|prior", "time": "prior"}]
            state.last_plan = copy.deepcopy(prior_plan)
            state.last_calculated_at = "prior-calculated"
            state.last_clock_key = "prior-clock"
            state.last_dispatched_clock_key = "prior-dispatched"
            state.last_sent_at = "prior-sent"
            state.status = "prior-running"
            state.trend = copy.deepcopy(prior_trend)
            state.trend_normalized = True
            result_holder = {}

            def run_auto_cycle():
                result_holder["state"] = manager.run_once(
                    "shared",
                    trigger="auto",
                    allow_dispatch=True,
                    record_log=True,
                )

            control_thread = threading.Thread(target=run_auto_cycle, daemon=True)
            try:
                with patch.object(
                    renewable_control_module,
                    "calculate_renewable_control_plan",
                    side_effect=blocking_calculate,
                ):
                    control_thread.start()
                    self.assertTrue(calculation_started.wait(timeout=2.0))
                    stopped = manager.apply_action("shared", {"action": "stop"})
                    stop_status = stopped["status"]
                    stop_logs = copy.deepcopy(stopped["logs"])
                    release_calculation.set()
                    control_thread.join(timeout=2.0)
                    self.assertFalse(control_thread.is_alive())
                    controller_state = result_holder["state"]
            finally:
                release_calculation.set()
                manager.close()
                exchange.close()

        self.assertFalse(controller_state["enabled"])
        self.assertEqual(controller_state["status"], stop_status)
        self.assertEqual(controller_state["logs"], stop_logs)
        self.assertEqual(controller_state["lastPlan"], prior_plan)
        self.assertEqual(controller_state["lastCalculatedAt"], "prior-calculated")
        self.assertEqual(controller_state["trend"], prior_trend)
        self.assertEqual(controller_state["lastDispatchedClockKey"], "prior-dispatched")
        self.assertEqual(controller_state["lastSentAt"], "prior-sent")
        self.assertEqual(transport_calls, [])
        self.assertFalse(
            any(item["result"] in {"下发成功", "下发失败"} for item in controller_state["logs"])
        )

    def test_loop_mode_change_during_calculation_cancels_old_cycle(self):
        original_calculate = renewable_control_module.calculate_renewable_control_plan
        calculation_started = threading.Event()
        release_calculation = threading.Event()

        def blocking_calculate(*args, **kwargs):
            calculation_started.set()
            self.assertTrue(release_calculation.wait(timeout=2.0))
            return original_calculate(*args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            _service, exchange, manager, _dispatched = make_exchange_backed_control_manager(
                temporary,
            )
            transport_calls = []
            exchange.request_json = lambda url, **kwargs: transport_calls.append(
                (url, copy.deepcopy(kwargs))
            ) or {"set_values": 1}
            state = manager._state_for("shared")
            state.loop_mode = "open"
            state.enabled = True
            prior_plan = {"time": "prior", "clockKey": "prior-clock", "commands": []}
            prior_trend = [{"sampleKey": "1|1|prior", "time": "prior"}]
            state.last_plan = copy.deepcopy(prior_plan)
            state.last_calculated_at = "prior-calculated"
            state.last_clock_key = "prior-clock"
            state.last_dispatched_clock_key = "prior-dispatched"
            state.last_sent_at = "prior-sent"
            state.status = "prior-open-loop"
            state.trend = copy.deepcopy(prior_trend)
            state.trend_normalized = True
            result_holder = {}

            def run_auto_cycle():
                result_holder["state"] = manager.run_once(
                    "shared",
                    trigger="auto",
                    allow_dispatch=True,
                    record_log=True,
                )

            control_thread = threading.Thread(target=run_auto_cycle, daemon=True)
            try:
                with patch.object(
                    renewable_control_module,
                    "calculate_renewable_control_plan",
                    side_effect=blocking_calculate,
                ):
                    control_thread.start()
                    self.assertTrue(calculation_started.wait(timeout=2.0))
                    changed = manager.apply_action(
                        "shared",
                        {"action": "set_loop_mode", "loop_mode": "closed"},
                    )
                    changed_status = changed["status"]
                    changed_logs = copy.deepcopy(changed["logs"])
                    release_calculation.set()
                    control_thread.join(timeout=2.0)
                    self.assertFalse(control_thread.is_alive())
                    controller_state = result_holder["state"]
            finally:
                release_calculation.set()
                manager.close()
                exchange.close()

        self.assertEqual(controller_state["loopMode"], "closed")
        self.assertEqual(controller_state["status"], changed_status)
        self.assertEqual(controller_state["logs"], changed_logs)
        self.assertEqual(controller_state["lastPlan"], prior_plan)
        self.assertEqual(controller_state["lastCalculatedAt"], "prior-calculated")
        self.assertEqual(controller_state["trend"], prior_trend)
        self.assertEqual(controller_state["lastDispatchedClockKey"], "prior-dispatched")
        self.assertEqual(controller_state["lastSentAt"], "prior-sent")
        self.assertEqual(transport_calls, [])

    def test_settings_change_during_calculation_cancels_old_candidate(self):
        original_calculate = renewable_control_module.calculate_renewable_control_plan
        calculation_started = threading.Event()
        release_calculation = threading.Event()

        def blocking_calculate(*args, **kwargs):
            calculation_started.set()
            self.assertTrue(release_calculation.wait(timeout=2.0))
            return original_calculate(*args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            _service, exchange, manager, _dispatched = make_exchange_backed_control_manager(
                temporary,
            )
            transport_calls = []
            exchange.request_json = lambda url, **kwargs: transport_calls.append(
                (url, copy.deepcopy(kwargs))
            ) or {"set_values": 1}
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            prior_plan = {"time": "prior", "clockKey": "prior-clock", "commands": []}
            prior_trend = [{"sampleKey": "1|1|prior", "time": "prior"}]
            state.last_plan = copy.deepcopy(prior_plan)
            state.last_calculated_at = "prior-calculated"
            state.last_clock_key = "prior-clock"
            state.last_dispatched_clock_key = "prior-dispatched"
            state.last_sent_at = "prior-sent"
            state.status = "prior-settings"
            state.trend = copy.deepcopy(prior_trend)
            state.trend_normalized = True
            result_holder = {}

            def run_auto_cycle():
                result_holder["state"] = manager.run_once(
                    "shared",
                    trigger="auto",
                    allow_dispatch=True,
                    record_log=True,
                )

            control_thread = threading.Thread(target=run_auto_cycle, daemon=True)
            try:
                with patch.object(
                    renewable_control_module,
                    "calculate_renewable_control_plan",
                    side_effect=blocking_calculate,
                ):
                    control_thread.start()
                    self.assertTrue(calculation_started.wait(timeout=2.0))
                    changed = manager.apply_action(
                        "shared",
                        {
                            "action": "update_settings",
                            "settings": {"commandValidMinutes": 30},
                        },
                    )
                    changed_status = changed["status"]
                    changed_logs = copy.deepcopy(changed["logs"])
                    release_calculation.set()
                    control_thread.join(timeout=2.0)
                    self.assertFalse(control_thread.is_alive())
                    controller_state = result_holder["state"]
            finally:
                release_calculation.set()
                manager.close()
                exchange.close()

        self.assertEqual(controller_state["settings"]["commandValidMinutes"], 30)
        self.assertEqual(controller_state["status"], changed_status)
        self.assertEqual(controller_state["logs"], changed_logs)
        self.assertEqual(controller_state["lastPlan"], prior_plan)
        self.assertEqual(controller_state["lastCalculatedAt"], "prior-calculated")
        self.assertEqual(controller_state["trend"], prior_trend)
        self.assertEqual(controller_state["lastDispatchedClockKey"], "prior-dispatched")
        self.assertEqual(controller_state["lastSentAt"], "prior-sent")
        self.assertEqual(transport_calls, [])

    def test_stop_while_disabled_cancels_blocked_manual_cycle(self):
        original_calculate = renewable_control_module.calculate_renewable_control_plan
        calculation_started = threading.Event()
        release_calculation = threading.Event()

        def blocking_calculate(*args, **kwargs):
            calculation_started.set()
            self.assertTrue(release_calculation.wait(timeout=2.0))
            return original_calculate(*args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            _service, exchange, manager, _dispatched = make_exchange_backed_control_manager(
                temporary,
            )
            transport_calls = []
            exchange.request_json = lambda url, **kwargs: transport_calls.append(
                (url, copy.deepcopy(kwargs))
            ) or {"set_values": 1}
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = False
            prior_plan = {"time": "prior", "clockKey": "prior-clock", "commands": []}
            state.last_plan = copy.deepcopy(prior_plan)
            state.last_calculated_at = "prior-calculated"
            state.status = "prior-idle"
            result_holder = {}

            def run_manual_cycle():
                result_holder["state"] = manager.run_once(
                    "shared",
                    trigger="manual",
                    allow_dispatch=True,
                    record_log=True,
                )

            control_thread = threading.Thread(target=run_manual_cycle, daemon=True)
            try:
                with patch.object(
                    renewable_control_module,
                    "calculate_renewable_control_plan",
                    side_effect=blocking_calculate,
                ):
                    control_thread.start()
                    self.assertTrue(calculation_started.wait(timeout=2.0))
                    stopped = manager.apply_action("shared", {"action": "stop"})
                    stop_status = stopped["status"]
                    stop_logs = copy.deepcopy(stopped["logs"])
                    release_calculation.set()
                    control_thread.join(timeout=2.0)
                    self.assertFalse(control_thread.is_alive())
                    controller_state = result_holder["state"]
            finally:
                release_calculation.set()
                manager.close()
                exchange.close()

        self.assertFalse(controller_state["enabled"])
        self.assertEqual(controller_state["status"], stop_status)
        self.assertEqual(controller_state["logs"], stop_logs)
        self.assertEqual(controller_state["lastPlan"], prior_plan)
        self.assertEqual(controller_state["lastCalculatedAt"], "prior-calculated")
        self.assertEqual(transport_calls, [])

    def test_stop_during_controller_transport_preserves_newer_stop_state(self):
        transport_started = threading.Event()
        release_transport = threading.Event()
        transport_calls = []

        def blocking_transport(url, **kwargs):
            transport_calls.append((url, copy.deepcopy(kwargs)))
            transport_started.set()
            self.assertTrue(release_transport.wait(timeout=2.0))
            return {"set_values": 1}

        with tempfile.TemporaryDirectory() as temporary:
            _service, exchange, manager, _dispatched = make_exchange_backed_control_manager(
                temporary,
            )
            exchange.request_json = blocking_transport
            manager.command_sink = exchange.submit_commands
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            state.last_sent_at = "prior-sent"
            state.status = "prior-running"
            result_holder = {}

            def run_auto_cycle():
                result_holder["state"] = manager.run_once(
                    "shared",
                    trigger="auto",
                    allow_dispatch=True,
                    record_log=True,
                )

            control_thread = threading.Thread(target=run_auto_cycle, daemon=True)
            control_thread.start()
            try:
                self.assertTrue(transport_started.wait(timeout=2.0))
                stopped = manager.apply_action("shared", {"action": "stop"})
                stop_status = stopped["status"]
                stop_logs = copy.deepcopy(stopped["logs"])
                release_transport.set()
                control_thread.join(timeout=2.0)
                self.assertFalse(control_thread.is_alive())
                controller_state = result_holder["state"]
            finally:
                release_transport.set()
                manager.close()
                exchange.close()

        self.assertEqual(len(transport_calls), 2)
        self.assertIsNone(transport_calls[0][1]["payload"].get("action"))
        self.assertEqual(
            transport_calls[1][1]["payload"].get("action"),
            "cancel_strategy_generation",
        )
        self.assertFalse(controller_state["enabled"])
        self.assertIn("正在撤销自动指令", stop_status)
        self.assertIn("已撤销自动指令", controller_state["status"])
        self.assertTrue(stop_logs)
        self.assertTrue(
            any(item["result"] == "自动指令撤销" for item in controller_state["logs"])
        )
        self.assertEqual(controller_state["lastSentAt"], "prior-sent")
        self.assertFalse(
            any(item["result"] in {"下发成功", "下发失败"} for item in controller_state["logs"])
        )

    def test_delete_then_recreate_same_model_id_has_fresh_exchange_and_controller_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            services, old_service, exchange, manager = make_deletable_exchange_backed_control_manager(
                temporary,
            )
            old_exchange_state = exchange._state_for("shared")
            old_controller_state = manager._state_for("shared")
            old_controller_state.last_plan = {
                "time": "old-plan",
                "clockKey": "old-clock",
                "commands": [],
            }
            old_controller_state.last_calculated_at = "old-calculated"
            old_controller_state.last_dispatched_clock_key = "old-dispatched-clock"
            old_controller_state.last_sent_at = "old-sent"
            old_controller_state.logs = [
                {
                    "seq": 1,
                    "wall_time": "old-wall",
                    "simu_time": "old-plan",
                    "type": "策略控制",
                    "target": "新能源优先",
                    "result": "旧生命周期",
                    "detail": "must not leak",
                    "level": "info",
                }
            ]
            try:
                old_service.set_trainee_receive_state({"active": False})
                services.delete_model("shared")
                for owner in (exchange, manager):
                    remove = getattr(owner, "remove_model_for_service", None)
                    if callable(remove):
                        remove(old_service)

                self.assertNotIn("shared", exchange._states)
                self.assertNotIn("shared", manager._states)

                services.create_model_slot("shared")
                new_service = services.service_for("shared")
                new_view = exchange.control_snapshot("shared")
                new_controller_payload = manager.state("shared")
                new_exchange_state = exchange._states["shared"]
                new_controller_state = manager._states["shared"]

                for owner in (exchange, manager):
                    remove = getattr(owner, "remove_model_for_service", None)
                    if callable(remove):
                        remove(old_service)

                self.assertIs(exchange._states["shared"], new_exchange_state)
                self.assertIs(manager._states["shared"], new_controller_state)
            finally:
                manager.close()
                exchange.close()

        self.assertIsNot(new_service, old_service)
        self.assertIsNot(new_exchange_state, old_exchange_state)
        self.assertIsNot(new_controller_state, old_controller_state)
        self.assertFalse(new_view.ready)
        self.assertIsNone(new_controller_payload["lastPlan"])
        self.assertEqual(new_controller_payload["lastCalculatedAt"], "")
        self.assertEqual(new_controller_payload["lastSentAt"], "")
        self.assertEqual(new_controller_payload["lastDispatchedClockKey"], "")
        self.assertEqual(new_controller_payload["logs"], [])

    def test_update_settings_captured_by_deleted_service_cannot_write_recreated_runtime(self):
        result, new_payload, persistence_exists, persisted_payload = (
            self._configuration_action_after_same_id_recreate(
                {
                    "action": "update_settings",
                    "settings": {"commandValidMinutes": 37},
                }
            )
        )

        self.assertNotIn("value", result)
        self.assertIsInstance(result.get("error"), RuntimeError)
        self.assertRegex(str(result["error"]), "生命周期|失效|删除|退休")
        self.assertFalse(persistence_exists, persisted_payload)
        self.assertEqual(
            new_payload["settings"],
            RenewableControlSettings().payload(),
        )

    def test_set_loop_mode_captured_by_deleted_service_cannot_write_recreated_runtime(self):
        result, new_payload, persistence_exists, persisted_payload = (
            self._configuration_action_after_same_id_recreate(
                {
                    "action": "set_loop_mode",
                    "loop_mode": "closed",
                }
            )
        )

        self.assertNotIn("value", result)
        self.assertIsInstance(result.get("error"), RuntimeError)
        self.assertRegex(str(result["error"]), "生命周期|失效|删除|退休")
        self.assertFalse(persistence_exists, persisted_payload)
        self.assertEqual(new_payload["loopMode"], "open")

    def test_manual_action_captured_by_deleted_service_cannot_dispatch_recreated_lifecycle(self):
        result, new_payload, transport_calls = self._control_action_after_same_id_recreate(
            {"action": "run_once"}
        )

        self.assertNotIn("value", result)
        self.assertIsInstance(result.get("error"), RuntimeError)
        self.assertRegex(str(result["error"]), "生命周期|失效|删除|退休")
        self.assertEqual(transport_calls, [])
        self.assertIsNone(new_payload["lastPlan"])
        self.assertEqual(new_payload["lastDispatchedClockKey"], "new-prior-clock")
        self.assertEqual(
            new_payload["lastDispatchedGenerationKey"],
            ["new-prior-generation"],
        )
        self.assertEqual(new_payload["status"], "new-lifecycle-status")

    def test_preview_and_start_actions_remain_bound_to_captured_service_lifecycle(self):
        for action in ("refresh", "start"):
            with self.subTest(action=action):
                result, new_payload, transport_calls = (
                    self._control_action_after_same_id_recreate({"action": action})
                )

                self.assertNotIn("value", result)
                self.assertIsInstance(result.get("error"), RuntimeError)
                self.assertRegex(str(result["error"]), "生命周期|失效|删除|退休")
                self.assertEqual(transport_calls, [])
                self.assertFalse(new_payload["enabled"])
                self.assertIsNone(new_payload["lastPlan"])
                self.assertEqual(
                    new_payload["lastDispatchedClockKey"],
                    "new-prior-clock",
                )
                self.assertEqual(new_payload["status"], "new-lifecycle-status")

    def test_worker_queued_preview_remains_bound_to_captured_service_lifecycle(self):
        class QueuedExecutor:
            def __init__(self):
                self.calls = []
                self.submitted = threading.Event()

            def submit(self, fn, *args, **kwargs):
                self.calls.append((fn, args, kwargs))
                self.submitted.set()

            def shutdown(self, *args, **kwargs):
                return None

        with tempfile.TemporaryDirectory() as temporary:
            services, old_service, exchange, manager = make_deletable_exchange_backed_control_manager(
                temporary,
            )
            executor = QueuedExecutor()
            manager._executor = executor
            old_state = manager._state_for_service(old_service)
            with old_state.lock:
                old_state.enabled = False
                old_state.settings = RenewableControlSettings(interval_seconds=0.01)
            try:
                manager._worker = threading.Thread(
                    target=manager._worker_loop,
                    name="test-renewable-lifecycle-queued-preview",
                    daemon=True,
                )
                manager._worker.start()
                self.assertTrue(executor.submitted.wait(timeout=2.0))
                manager._stop_event.set()
                manager._worker.join(timeout=2.0)
                self.assertFalse(manager._worker.is_alive())
                self.assertEqual(len(executor.calls), 1)

                old_service.set_trainee_receive_state({"active": False})
                services.delete_model("shared")
                exchange.remove_model_for_service(old_service)
                manager.remove_model_for_service(old_service)
                services.create_model_slot("shared")
                new_service = services.service_for("shared")
                new_service.set_trainee_receive_state(
                    {
                        "initialized": True,
                        "active": True,
                        "interaction_link": "http://teacher-new.invalid/api/trainee-link?model_id=teacher-new",
                        "teacher_api_base": "http://teacher-new.invalid",
                        "snapshot_path": "/api/snapshot?model_id=teacher-new",
                        "command_path": "/api/student/commands?model_id=teacher-new",
                        "teacher_model_id": "teacher-new",
                    }
                )
                exchange.notify_receive_state_changed_for_service(new_service)
                exchange.publish_runtime_snapshot(
                    "shared",
                    renewable_snapshot(),
                    connection_signature=exchange._connection_signature(new_service),
                )
                new_state = manager._state_for_service(new_service)
                with new_state.lock:
                    new_state.status = "new-lifecycle-status"
                    new_state.last_plan = None
                    new_state.last_calculated_at = ""
                    new_state.last_dispatched_clock_key = "new-prior-clock"
                    new_state.last_dispatched_generation_key = (
                        "new-prior-generation",
                    )
                    new_state.trend = [{"sampleKey": "new-prior-trend"}]

                callback, args, kwargs = executor.calls[0]
                callback(*args, **kwargs)
                new_payload = manager._serialize(new_state)
            finally:
                manager._stop_event.set()
                manager.close()
                exchange.close()

        self.assertEqual(new_payload["status"], "new-lifecycle-status")
        self.assertIsNone(new_payload["lastPlan"])
        self.assertEqual(new_payload["lastCalculatedAt"], "")
        self.assertEqual(new_payload["lastDispatchedClockKey"], "new-prior-clock")
        self.assertEqual(
            new_payload["lastDispatchedGenerationKey"],
            ["new-prior-generation"],
        )
        self.assertEqual(new_payload["trend"], [{"sampleKey": "new-prior-trend"}])

    def test_worker_stale_service_snapshot_preserves_recreated_controller_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            models_root = root / "models"
            for model_id in ("shared", "keep"):
                write_model_dir(models_root / model_id)
            services = MultiModelSimulator(
                [
                    SimulationModelSpec("shared", models_root / "shared", "Shared"),
                    SimulationModelSpec("keep", models_root / "keep", "Keep"),
                ],
                runtime_dir=root / "runtime",
                models_root=models_root,
                kernel=lambda _config: None,
            )
            old_service = services.service_for("shared")
            snapshot = renewable_snapshot()

            def receive_status(model_id):
                if str(model_id or "") == "shared":
                    return ready_status(model_id)
                return {
                    "receiveActive": False,
                    "ready": False,
                    "canRun": False,
                    "prerequisiteStatus": "请先启动接收。",
                    "revision": 0,
                    "connectionSignature": [],
                }

            manager = make_control_manager(
                services,
                snapshot_provider=lambda _model_id: ready_view(snapshot),
                receive_status_provider=receive_status,
                start_worker=False,
            )
            enumeration_captured = threading.Event()
            release_enumeration = threading.Event()
            iteration_done = threading.Event()
            capture_consumed = threading.Event()
            original_iter_services = services.iter_services
            submitted_services = []
            original_submit_background_cycle = manager._submit_background_cycle

            def coordinated_iter_services():
                captured = original_iter_services()
                if not capture_consumed.is_set():
                    capture_consumed.set()
                    enumeration_captured.set()
                    self.assertTrue(release_enumeration.wait(timeout=3.0))
                return captured

            class OneIterationStop:
                def __init__(self):
                    self.stopped = False

                def is_set(self):
                    return self.stopped

                def wait(self, _timeout):
                    iteration_done.set()
                    self.stopped = True
                    return True

                def set(self):
                    self.stopped = True

            def record_background_cycle(state, **kwargs):
                args = tuple(kwargs.get("args", ()))
                submitted_services.append(args[0] if args else None)
                return original_submit_background_cycle(state, **kwargs)

            services.iter_services = coordinated_iter_services
            manager._stop_event = OneIterationStop()
            manager._submit_background_cycle = record_background_cycle
            manager._worker = threading.Thread(
                target=manager._worker_loop,
                name="test-renewable-stale-enumeration",
                daemon=True,
            )
            try:
                manager._worker.start()
                self.assertTrue(enumeration_captured.wait(timeout=2.0))

                services.delete_model("shared")
                manager.remove_model_for_service(old_service)
                services.create_model_slot("shared")
                new_service = services.service_for("shared")
                new_state = manager._state_for_service(new_service)
                with new_state.lock:
                    new_state.status = "new-b-controller-status"
                    new_state.last_plan = {
                        "time": "new-b-time",
                        "clockKey": "new-b-plan-clock",
                        "commands": [],
                    }
                    new_state.logs = [{"seq": 9, "result": "new-b-log"}]
                    new_state.trend = [{"sampleKey": "new-b-trend"}]
                    new_state.last_dispatched_clock_key = "new-b-dispatched-clock"
                    new_state.last_dispatched_generation_key = ("new-b-generation",)
                    new_state.last_sent_at = "new-b-sent-at"
                    before_operation_epoch = new_state.operation_epoch

                release_enumeration.set()
                self.assertTrue(iteration_done.wait(timeout=3.0))
                manager._worker.join(timeout=3.0)
                self.assertFalse(manager._worker.is_alive())
                manager.close()
            finally:
                release_enumeration.set()
                manager._stop_event.set()
                manager.close()

        self.assertEqual(submitted_services, [])
        self.assertIs(manager._states.get("shared"), new_state)
        self.assertIs(
            manager._states_by_service_instance.get(new_service.service_instance_id),
            new_state,
        )
        with new_state.lock:
            self.assertEqual(new_state.status, "new-b-controller-status")
            self.assertEqual(new_state.last_plan["clockKey"], "new-b-plan-clock")
            self.assertEqual(new_state.logs, [{"seq": 9, "result": "new-b-log"}])
            self.assertEqual(new_state.trend, [{"sampleKey": "new-b-trend"}])
            self.assertEqual(new_state.last_dispatched_clock_key, "new-b-dispatched-clock")
            self.assertEqual(
                new_state.last_dispatched_generation_key,
                ("new-b-generation",),
            )
            self.assertEqual(new_state.last_sent_at, "new-b-sent-at")
            self.assertEqual(new_state.operation_epoch, before_operation_epoch)

    def test_delete_during_calculation_cancels_without_key_error_or_state_mutation(self):
        original_calculate = renewable_control_module.calculate_renewable_control_plan
        calculation_started = threading.Event()
        release_calculation = threading.Event()

        def blocking_calculate(*args, **kwargs):
            calculation_started.set()
            self.assertTrue(release_calculation.wait(timeout=2.0))
            return original_calculate(*args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            services, old_service, exchange, manager = make_deletable_exchange_backed_control_manager(
                temporary,
            )
            transport_calls = []
            exchange.request_json = lambda url, **kwargs: transport_calls.append(
                (url, copy.deepcopy(kwargs))
            ) or {"set_values": 1}
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            prior_plan = {"time": "prior", "clockKey": "prior-clock", "commands": []}
            prior_logs = [
                {
                    "seq": 1,
                    "wall_time": "prior-wall",
                    "simu_time": "prior",
                    "type": "策略控制",
                    "target": "新能源优先",
                    "result": "保留",
                    "detail": "existing",
                    "level": "info",
                }
            ]
            prior_trend = [{"sampleKey": "1|1|prior", "time": "prior"}]
            state.last_plan = copy.deepcopy(prior_plan)
            state.last_calculated_at = "prior-calculated"
            state.last_clock_key = "prior-clock"
            state.last_dispatched_clock_key = "prior-dispatched"
            state.last_sent_at = "prior-sent"
            state.status = "prior-status"
            state.logs = copy.deepcopy(prior_logs)
            state.log_seq = 1
            state.trend = copy.deepcopy(prior_trend)
            state.trend_normalized = True
            result_holder = {}

            def run_control():
                try:
                    result_holder["state"] = manager.run_once(
                        "shared",
                        trigger="manual",
                        allow_dispatch=True,
                        record_log=True,
                    )
                except Exception as exc:
                    result_holder["error"] = exc

            control_thread = threading.Thread(target=run_control, daemon=True)
            try:
                with patch.object(
                    renewable_control_module,
                    "calculate_renewable_control_plan",
                    side_effect=blocking_calculate,
                ):
                    control_thread.start()
                    self.assertTrue(calculation_started.wait(timeout=2.0))
                    old_service.set_trainee_receive_state({"active": False})
                    services.delete_model("shared")
                    for owner in (exchange, manager):
                        remove = getattr(owner, "remove_model_for_service", None)
                        if callable(remove):
                            remove(old_service)
                    release_calculation.set()
                    control_thread.join(timeout=2.0)
                    self.assertFalse(control_thread.is_alive())
            finally:
                release_calculation.set()
                manager.close()
                exchange.close()

        self.assertNotIn("error", result_holder)
        controller_state = result_holder["state"]
        self.assertEqual(controller_state["lastPlan"], prior_plan)
        self.assertEqual(controller_state["lastCalculatedAt"], "prior-calculated")
        self.assertEqual(controller_state["logs"], prior_logs)
        self.assertEqual(controller_state["trend"], prior_trend)
        self.assertEqual(controller_state["lastDispatchedClockKey"], "prior-dispatched")
        self.assertEqual(controller_state["lastSentAt"], "prior-sent")
        self.assertEqual(controller_state["status"], "prior-status")
        self.assertEqual(transport_calls, [])

    def test_delete_during_transport_drops_stale_response_without_key_error(self):
        transport_started = threading.Event()
        release_transport = threading.Event()
        transport_calls = []

        def blocking_transport(url, **kwargs):
            transport_calls.append((url, copy.deepcopy(kwargs)))
            transport_started.set()
            self.assertTrue(release_transport.wait(timeout=2.0))
            return {"set_values": 1}

        with tempfile.TemporaryDirectory() as temporary:
            services, old_service, exchange, manager = make_deletable_exchange_backed_control_manager(
                temporary,
            )
            exchange.request_json = blocking_transport
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            state.last_sent_at = "prior-sent"
            state.status = "prior-running"
            result_holder = {}

            def run_control():
                try:
                    result_holder["state"] = manager.run_once(
                        "shared",
                        trigger="auto",
                        allow_dispatch=True,
                        record_log=True,
                    )
                except Exception as exc:
                    result_holder["error"] = exc

            control_thread = threading.Thread(target=run_control, daemon=True)
            control_thread.start()
            try:
                self.assertTrue(transport_started.wait(timeout=2.0))
                old_service.set_trainee_receive_state({"active": False})
                services.delete_model("shared")
                for owner in (exchange, manager):
                    remove = getattr(owner, "remove_model_for_service", None)
                    if callable(remove):
                        remove(old_service)
                release_transport.set()
                control_thread.join(timeout=2.0)
                self.assertFalse(control_thread.is_alive())
            finally:
                release_transport.set()
                manager.close()
                exchange.close()

        self.assertNotIn("error", result_holder)
        controller_state = result_holder["state"]
        self.assertEqual(len(transport_calls), 1)
        self.assertEqual(controller_state["status"], "prior-running")
        self.assertEqual(controller_state["lastSentAt"], "prior-sent")
        self.assertFalse(
            any(item["result"] in {"下发成功", "下发失败"} for item in controller_state["logs"])
        )

    def test_receive_stop_during_successful_transport_preserves_newer_stop_state(self):
        transport_started = threading.Event()
        release_transport = threading.Event()

        def blocking_transport(_url, **_kwargs):
            transport_started.set()
            self.assertTrue(release_transport.wait(timeout=2.0))
            return {"set_values": 1}

        with tempfile.TemporaryDirectory() as temporary:
            service, exchange, manager, _dispatched = make_exchange_backed_control_manager(
                temporary,
            )
            exchange.request_json = blocking_transport
            manager.command_sink = exchange.submit_commands
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            state.last_sent_at = "prior-sent"
            state.status = "prior-running-status"
            result_holder = {}

            def run_control():
                result_holder["state"] = manager.run_once(
                    "shared",
                    trigger="manual",
                    allow_dispatch=True,
                    record_log=True,
                )

            control_thread = threading.Thread(target=run_control, daemon=True)
            control_thread.start()
            try:
                self.assertTrue(transport_started.wait(timeout=2.0))
                service.set_trainee_receive_state({"active": False})
                exchange.receive_state_changed("shared")
                stopped = manager.receive_state_changed("shared")
                stop_status = stopped["status"]
                stop_logs = copy.deepcopy(stopped["logs"])
                release_transport.set()
                control_thread.join(timeout=2.0)
                self.assertFalse(control_thread.is_alive())
                controller_state = result_holder["state"]
            finally:
                release_transport.set()
                manager.close()
                exchange.close()

        self.assertIn("接收已停止", stop_status)
        self.assertEqual(controller_state["status"], stop_status)
        self.assertEqual(controller_state["lastSentAt"], "prior-sent")
        self.assertEqual(controller_state["logs"], stop_logs)
        self.assertFalse(
            any(item["result"] in {"下发成功", "下发失败"} for item in controller_state["logs"])
        )

    def test_receive_retarget_during_failed_transport_preserves_newer_retarget_state(self):
        transport_started = threading.Event()
        release_transport = threading.Event()

        def blocking_transport(_url, **_kwargs):
            transport_started.set()
            self.assertTrue(release_transport.wait(timeout=2.0))
            raise RuntimeError("old endpoint failed")

        with tempfile.TemporaryDirectory() as temporary:
            service, exchange, manager, _dispatched = make_exchange_backed_control_manager(
                temporary,
            )
            exchange.request_json = blocking_transport
            manager.command_sink = exchange.submit_commands
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            state.last_sent_at = "prior-sent"
            state.status = "prior-running-status"
            result_holder = {}

            def run_control():
                result_holder["state"] = manager.run_once(
                    "shared",
                    trigger="manual",
                    allow_dispatch=True,
                    record_log=True,
                )

            control_thread = threading.Thread(target=run_control, daemon=True)
            control_thread.start()
            try:
                self.assertTrue(transport_started.wait(timeout=2.0))
                service.set_trainee_receive_state(
                    {
                        "interaction_link": "http://replacement.invalid/api/trainee-link?model_id=replacement",
                        "teacher_api_base": "http://replacement.invalid",
                        "snapshot_path": "/api/snapshot?model_id=replacement",
                        "command_path": "/api/student/commands?model_id=replacement",
                        "teacher_model_id": "replacement",
                    }
                )
                exchange.receive_state_changed("shared")
                retargeted = manager.receive_state_changed("shared")
                retarget_status = retargeted["status"]
                retarget_logs = copy.deepcopy(retargeted["logs"])
                release_transport.set()
                control_thread.join(timeout=2.0)
                self.assertFalse(control_thread.is_alive())
                controller_state = result_holder["state"]
            finally:
                release_transport.set()
                manager.close()
                exchange.close()

        self.assertIn("接收已停止", retarget_status)
        self.assertEqual(controller_state["status"], retarget_status)
        self.assertEqual(controller_state["lastSentAt"], "prior-sent")
        self.assertEqual(controller_state["logs"], retarget_logs)
        self.assertFalse(
            any(item["result"] in {"下发成功", "下发失败"} for item in controller_state["logs"])
        )

    def test_manual_run_once_busy_timeout_reports_explicit_noop(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            snapshot_calls = []
            dispatched = []
            manager = make_control_manager(
                services,
                snapshot_provider=lambda model_id: snapshot_calls.append(model_id),
                command_sink=lambda model_id, payload: dispatched.append((model_id, payload)) or {},
            )
            state = manager._state_for("shared")
            state.run_lock.acquire()
            try:
                with patch.object(
                    renewable_control_module,
                    "_USER_CONTROL_BUSY_WAIT_SECONDS",
                    0.01,
                ):
                    controller_state = manager.run_once(
                        "shared",
                        trigger="manual",
                        allow_dispatch=True,
                        record_log=True,
                    )
            finally:
                state.run_lock.release()
                manager.close()

        self.assertIn("正在执行上一轮计算", controller_state["status"])
        self.assertIn("本次单次计算未执行", controller_state["status"])
        self.assertTrue(
            any(item["result"] == "单次计算忙碌阻断" for item in controller_state["logs"])
        )
        self.assertEqual(controller_state["lastCalculatedAt"], "")
        self.assertEqual(snapshot_calls, [])
        self.assertEqual(dispatched, [])

    def test_worker_does_not_enqueue_preview_while_cycle_lock_is_running(self):
        class RecordingExecutor:
            def __init__(self):
                self.calls = []
                self.lock = threading.Lock()

            def submit(self, fn, *args, **kwargs):
                with self.lock:
                    self.calls.append((fn, args, kwargs))

            def shutdown(self, *args, **kwargs):
                return None

        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": True,
                "ready": True,
                "revision": 1,
                "signature": ("learner", 1),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            manager = make_control_manager(
                services,
                receive_status_provider=mutable_receive_status(receive_state),
            )
            state = manager._state_for("shared")
            state.settings = RenewableControlSettings(interval_seconds=0.05)
            state.run_lock.acquire()
            executor = RecordingExecutor()
            manager._executor = executor
            try:
                manager._worker = threading.Thread(
                    target=manager._worker_loop,
                    name="test-renewable-preview-running-gate",
                    daemon=True,
                )
                manager._worker.start()
                time.sleep(0.18)
            finally:
                manager._stop_event.set()
                state.run_lock.release()
                manager.close()

        self.assertEqual(executor.calls, [])

    def test_worker_does_not_enqueue_more_than_one_pending_preview(self):
        class RecordingExecutor:
            def __init__(self):
                self.calls = []
                self.lock = threading.Lock()

            def submit(self, fn, *args, **kwargs):
                with self.lock:
                    self.calls.append((fn, args, kwargs))

            def shutdown(self, *args, **kwargs):
                return None

        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": True,
                "ready": True,
                "revision": 1,
                "signature": ("learner", 1),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            manager = make_control_manager(
                services,
                receive_status_provider=mutable_receive_status(receive_state),
            )
            state = manager._state_for("shared")
            state.settings = RenewableControlSettings(interval_seconds=0.05)
            executor = RecordingExecutor()
            manager._executor = executor
            try:
                manager._worker = threading.Thread(
                    target=manager._worker_loop,
                    name="test-renewable-preview-pending-gate",
                    daemon=True,
                )
                manager._worker.start()
                deadline = time.monotonic() + 0.35
                while time.monotonic() < deadline:
                    with executor.lock:
                        if len(executor.calls) > 1:
                            break
                    time.sleep(0.02)
            finally:
                manager._stop_event.set()
                manager.close()

        self.assertEqual(len(executor.calls), 1)

    def test_close_waits_for_running_background_cycle_and_rejects_new_submissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            service, exchange, manager, _ = make_exchange_backed_control_manager(temporary)
            state = manager._state_for_service(service)
            original_snapshot_provider = manager.snapshot_provider
            cycle_started = threading.Event()
            release_cycle = threading.Event()
            close_returned = threading.Event()
            rejected_callback_ran = threading.Event()
            close_thread = None

            def blocking_snapshot_provider(model_id):
                cycle_started.set()
                self.assertTrue(release_cycle.wait(timeout=3.0))
                return original_snapshot_provider(model_id)

            def close_manager():
                manager.close()
                close_returned.set()

            manager.snapshot_provider = blocking_snapshot_provider
            try:
                submitted = manager._submit_background_cycle(
                    state,
                    timestamp_attr="last_preview_started",
                    timestamp=time.monotonic(),
                    callback=manager._collect_once_for_service,
                    args=(service, state),
                    kwargs={"raise_on_retired": False},
                )
                self.assertTrue(submitted)
                self.assertTrue(cycle_started.wait(timeout=2.0))

                close_thread = threading.Thread(
                    target=close_manager,
                    name="test-renewable-manager-close",
                    daemon=True,
                )
                close_thread.start()
                self.assertFalse(
                    close_returned.wait(timeout=0.2),
                    "manager.close() returned while a background control cycle was still running",
                )

                release_cycle.set()
                close_thread.join(timeout=3.0)
                self.assertFalse(close_thread.is_alive())
                self.assertTrue(close_returned.is_set())
                with state.lock:
                    self.assertFalse(state.background_cycle_pending)
                    self.assertFalse(state.sending)
                    self.assertFalse(state.run_lock.locked())

                manager.close()
                self.assertFalse(
                    manager._submit_background_cycle(
                        state,
                        timestamp_attr="last_preview_started",
                        timestamp=time.monotonic(),
                        callback=lambda: rejected_callback_ran.set() or {},
                        args=(),
                        kwargs={},
                    )
                )
                self.assertFalse(rejected_callback_ran.is_set())
            finally:
                release_cycle.set()
                if close_thread is not None:
                    close_thread.join(timeout=3.0)
                manager.close()
                if state.run_lock.acquire(timeout=3.0):
                    state.run_lock.release()
                exchange.close()

    def test_active_controller_pauses_when_receive_state_becomes_inactive(self):
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": True,
                "ready": True,
                "revision": 1,
                "signature": ("learner", 1),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: dict(receive_state),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            manager = make_control_manager(
                services,
                receive_status_provider=mutable_receive_status(receive_state),
            )
            manager._state_for("shared").settings = RenewableControlSettings(interval_seconds=2)
            try:
                started = manager.apply_action("shared", {"action": "start"})
                self.assertTrue(started["enabled"])
                receive_state["active"] = False
                manager._worker = threading.Thread(
                    target=manager._worker_loop,
                    name="test-renewable-receive-prerequisite",
                    daemon=True,
                )
                manager._worker.start()
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline and manager.state("shared")["enabled"]:
                    time.sleep(0.02)
                controller_state = manager.state("shared")
            finally:
                manager.close()

        self.assertFalse(controller_state["enabled"])
        self.assertTrue(controller_state["desiredEnabled"])
        self.assertTrue(controller_state["resumePending"])
        self.assertFalse(controller_state["receiveActive"])
        self.assertIn("接收已停止", controller_state["status"])
        self.assertTrue(
            any("新能源实时控制已暂停" in item["detail"] for item in controller_state["logs"])
        )

    def test_receive_stop_during_snapshot_fetch_cancels_the_control_cycle(self):
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": True,
                "ready": True,
                "revision": 1,
                "signature": ("learner", 1),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: dict(receive_state),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            dispatched = []

            def snapshot_then_stop(_model_id):
                receive_state["active"] = False
                receive_state["ready"] = False
                receive_state["revision"] = 2
                return ready_view(renewable_snapshot())

            manager = make_control_manager(
                services,
                snapshot_provider=snapshot_then_stop,
                receive_status_provider=mutable_receive_status(receive_state),
                command_sink=lambda model_id, payload: dispatched.append((model_id, payload)) or {},
            )
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            try:
                controller_state = manager.run_once(
                    "shared",
                    trigger="auto",
                    allow_dispatch=True,
                    record_log=False,
                )
            finally:
                manager.close()

        self.assertFalse(controller_state["enabled"])
        self.assertFalse(controller_state["receiveActive"])
        self.assertEqual(controller_state["lastCalculatedAt"], "")
        self.assertEqual(dispatched, [])

    def test_receive_signature_change_during_snapshot_read_discards_the_cycle(self):
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": True,
                "ready": True,
                "revision": 1,
                "signature": ("learner", "connection-a"),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: dict(receive_state),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            candidate = side_aware_recovery_snapshot(
                diesel_power_kw=50.0,
                wind_power_kw=30.0,
            )
            candidate["clock"]["time"] = "candidate"
            dispatched = []

            def snapshot_then_retarget(_model_id):
                receive_state["revision"] = 2
                receive_state["signature"] = ("learner", "connection-b")
                return ready_view(candidate, revision=1, signature=("learner", "connection-a"))

            manager = make_control_manager(
                services,
                snapshot_provider=snapshot_then_retarget,
                receive_status_provider=mutable_receive_status(receive_state),
                command_sink=lambda model_id, payload: dispatched.append((model_id, payload)) or {},
            )
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            state.last_plan = {"time": "prior", "commands": []}
            state.last_calculated_at = "prior-calculated"
            state.last_dispatched_clock_key = "prior-clock"
            state.last_sent_at = "prior-sent"
            try:
                cancelled = manager.run_once(
                    "shared",
                    trigger="auto",
                    allow_dispatch=True,
                    record_log=True,
                )
                stored = manager.state("shared")
            finally:
                manager.close()

        self.assertEqual(cancelled["lastCalculatedAt"], "prior-calculated")
        self.assertEqual(cancelled["lastPlan"], {"time": "prior", "commands": []})
        self.assertEqual(cancelled["lastDispatchedClockKey"], "prior-clock")
        self.assertEqual(cancelled["lastSentAt"], "prior-sent")
        self.assertFalse(cancelled["sending"])
        self.assertFalse(stored["sending"])
        self.assertEqual(dispatched, [])

    def test_collect_once_receive_signature_change_keeps_plan_and_trend_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": True,
                "ready": True,
                "revision": 1,
                "signature": ("learner", "connection-a"),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: dict(receive_state),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()

            def snapshot_then_retarget(_model_id):
                receive_state["revision"] = 2
                receive_state["signature"] = ("learner", "connection-b")
                return ready_view(
                    renewable_snapshot(),
                    revision=1,
                    signature=("learner", "connection-a"),
                )

            manager = make_control_manager(
                services,
                snapshot_provider=snapshot_then_retarget,
                receive_status_provider=mutable_receive_status(receive_state),
            )
            state = manager._state_for("shared")
            state.last_plan = {"time": "prior", "commands": []}
            state.last_calculated_at = "prior-calculated"
            state.trend = [{"sampleKey": "prior", "time": "prior"}]
            before_trend = copy.deepcopy(state.trend)
            try:
                controller_state = manager.collect_once("shared")
            finally:
                manager.close()

        self.assertEqual(controller_state["lastCalculatedAt"], "prior-calculated")
        self.assertEqual(controller_state["lastPlan"], {"time": "prior", "commands": []})
        self.assertEqual(controller_state["trend"], before_trend)

    def test_receive_signature_change_during_plan_calculation_discards_candidate(self):
        original_calculate = renewable_control_module.calculate_renewable_control_plan
        with tempfile.TemporaryDirectory() as temporary:
            receive_state = {
                "active": True,
                "ready": True,
                "revision": 1,
                "signature": ("learner", "connection-a"),
            }
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: dict(receive_state),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            dispatched = []
            snapshot = side_aware_recovery_snapshot(
                diesel_power_kw=50.0,
                wind_power_kw=30.0,
            )
            manager = make_control_manager(
                services,
                snapshot=snapshot,
                receive_status_provider=mutable_receive_status(receive_state),
                command_sink=lambda model_id, payload: dispatched.append((model_id, payload)) or {},
            )
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            state.last_plan = {"time": "prior", "commands": []}
            state.last_calculated_at = "prior-calculated"
            state.last_dispatched_clock_key = "prior-clock"
            state.last_sent_at = "prior-sent"
            prior_logs = [
                {
                    "time": "prior",
                    "category": "策略控制",
                    "action": "保留",
                    "detail": "existing",
                    "level": "info",
                    "simuTime": "prior",
                }
            ]
            state.logs = copy.deepcopy(prior_logs)

            def calculate_then_retarget(*args, **kwargs):
                receive_state["revision"] = 2
                receive_state["signature"] = ("learner", "connection-b")
                return original_calculate(*args, **kwargs)

            try:
                with patch.object(
                    renewable_control_module,
                    "calculate_renewable_control_plan",
                    side_effect=calculate_then_retarget,
                ):
                    controller_state = manager.run_once(
                        "shared",
                        trigger="auto",
                        allow_dispatch=True,
                        record_log=True,
                    )
                    stored_state = manager.state("shared")
            finally:
                manager.close()

        self.assertEqual(controller_state["lastCalculatedAt"], "prior-calculated")
        self.assertEqual(controller_state["lastPlan"], {"time": "prior", "commands": []})
        self.assertEqual(controller_state["lastDispatchedClockKey"], "prior-clock")
        self.assertEqual(controller_state["lastSentAt"], "prior-sent")
        self.assertEqual(controller_state["logs"], prior_logs)
        self.assertFalse(controller_state["sending"])
        self.assertFalse(stored_state["sending"])
        self.assertEqual(dispatched, [])

    def test_trend_history_keeps_only_the_latest_monotonic_clock_segment(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: {},
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            manager = make_control_manager(services)
            state = manager._state_for("shared")
            plan = {"metrics": {}}

            def trend_snapshot(minute, step_count):
                snapshot = renewable_snapshot()
                snapshot["clock"].update(
                    {
                        "run_id": 1,
                        "absolute_minute": minute,
                        "minute": minute,
                        "time": f"00:{minute:02d}:00",
                        "step_count": step_count,
                    }
                )
                return snapshot

            try:
                state.trend = [
                    manager._trend_point(plan, trend_snapshot(50, 10)),
                    manager._trend_point(plan, trend_snapshot(55, 11)),
                    manager._trend_point(plan, trend_snapshot(0, 0)),
                    manager._trend_point(plan, trend_snapshot(1, 1)),
                ]
                manager._update_trend(state, plan, trend_snapshot(2, 2))
                trend = manager.state("shared")["trend"]
            finally:
                manager.close()

        self.assertEqual([point["minute"] for point in trend], [0, 1, 2])
        self.assertEqual([point["stepCount"] for point in trend], [0, 1, 2])

    def test_task8_trend_point_copies_side_totals_and_dc_transfer_groups(self):
        snapshot = task8_metrics_snapshot()
        plan = calculate_renewable_control_plan(snapshot)

        first = TraineeRenewableControlManager._trend_point(plan, snapshot)
        second = TraineeRenewableControlManager._trend_point(plan, snapshot)

        for legacy_key in (
            "loadKw",
            "dieselKw",
            "storageKw",
            "storageSocPercent",
            "renewableKw",
            "acdcCurrentKw",
            "acdcTargetKw",
        ):
            self.assertIn(legacy_key, first)
        expected_breakdown = {
            "acLoadKw": 100.0,
            "dcLoadKw": 0.0,
            "dieselCurrentKw": 60.0,
            "dieselTargetKw": plan["metrics"]["dieselTargetKw"],
            "acRenewableCurrentKw": 100.0,
            "acRenewableTargetKw": plan["metrics"]["acRenewableTargetKw"],
            "dcRenewableCurrentKw": 80.0,
            "dcRenewableTargetKw": plan["metrics"]["dcRenewableTargetKw"],
            "acGridFollowingStorageCurrentKw": -2.0,
            "acGridFollowingStorageTargetKw": plan["metrics"]["acGridFollowingStorageTargetKw"],
            "acGridFollowingStorageSocPercent": 20.0,
            "dcGridFollowingStorageCurrentKw": -4.0,
            "dcGridFollowingStorageTargetKw": plan["metrics"]["dcGridFollowingStorageTargetKw"],
            "dcGridFollowingStorageSocPercent": 80.0,
            "acGridFormingStorageCurrentKw": 6.0,
            "acGridFormingStorageTargetKw": plan["metrics"]["acGridFormingStorageTargetKw"],
            "acGridFormingStorageSocPercent": 40.0,
            "dcGridFormingStorageCurrentKw": -8.0,
            "dcGridFormingStorageTargetKw": plan["metrics"]["dcGridFormingStorageTargetKw"],
            "dcGridFormingStorageSocPercent": 120.0,
            "acdcCurrentKw": plan["metrics"]["acdcCurrentKw"],
            "acdcTargetKw": plan["metrics"]["acdcTargetKw"],
        }
        for trend_key, metric_key in (
            ("acWindCurrentKw", "acWindCurrentKw"),
            ("acWindTargetKw", "acWindTargetKw"),
            ("acPvCurrentKw", "acPvCurrentKw"),
            ("acPvTargetKw", "acPvTargetKw"),
            ("dcWindCurrentKw", "dcWindCurrentKw"),
            ("dcWindTargetKw", "dcWindTargetKw"),
            ("dcPvCurrentKw", "dcPvCurrentKw"),
            ("dcPvTargetKw", "dcPvTargetKw"),
            ("acDieselCurrentKw", "acDieselCurrentKw"),
            ("acDieselMinKw", "acDieselMinKw"),
            ("acDieselTargetKw", "acDieselTargetKw"),
            ("dcDieselCurrentKw", "dcDieselCurrentKw"),
            ("dcDieselMinKw", "dcDieselMinKw"),
            ("dcDieselTargetKw", "dcDieselTargetKw"),
            ("totalRenewableCurrentKw", "totalRenewableCurrentKw"),
            ("totalRenewableTargetKw", "totalRenewableTargetKw"),
            ("totalWindCurrentKw", "totalWindCurrentKw"),
            ("totalWindTargetKw", "totalWindTargetKw"),
            ("totalPvCurrentKw", "totalPvCurrentKw"),
            ("totalPvTargetKw", "totalPvTargetKw"),
            ("totalGridFollowingStorageCurrentKw", "totalGridFollowingStorageCurrentKw"),
            ("totalGridFollowingStorageTargetKw", "totalGridFollowingStorageTargetKw"),
            ("totalGridFormingStorageCurrentKw", "totalGridFormingStorageCurrentKw"),
            ("totalGridFormingStorageTargetKw", "totalGridFormingStorageTargetKw"),
            ("totalDieselCurrentKw", "totalDieselCurrentKw"),
            ("totalDieselMinKw", "totalDieselMinKw"),
            ("totalDieselTargetKw", "totalDieselTargetKw"),
            ("totalLoadKw", "totalLoadKw"),
        ):
            expected_breakdown[trend_key] = plan["metrics"][metric_key]
        for trend_key, metric_key in (
            ("totalGridFollowingStorageSocPercent", "totalGridFollowingStorageSoc"),
            ("totalGridFormingStorageSocPercent", "totalGridFormingStorageSoc"),
        ):
            expected_breakdown[trend_key] = plan["metrics"][metric_key] * 100.0
        for key, expected in expected_breakdown.items():
            with self.subTest(key=key):
                self.assertIn(key, first)
                self.assertAlmostEqual(first[key], expected)
        self.assertEqual(
            first["dcTransferGroups"],
            plan["metrics"]["dcTransferGroups"],
        )

        first["dcTransferGroups"][0]["groupId"] = "mutated-by-client"
        self.assertNotEqual(
            first["dcTransferGroups"],
            second["dcTransferGroups"],
        )
        self.assertNotEqual(
            plan["metrics"]["dcTransferGroups"][0]["groupId"],
            "mutated-by-client",
        )
        json.dumps(first["dcTransferGroups"], ensure_ascii=False)
        json.dumps(second["dcTransferGroups"], ensure_ascii=False)

    def test_task8_command_payload_preserves_commands_metrics_and_detached_groups(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: {},
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            manager = make_control_manager(services)
            snapshot = direct_grid_storage_snapshot(
                diesel_power_kw=80.0,
                ac_current_kw=0.0,
                dc_current_kw=0.0,
                ac_soc=0.60,
                dc_soc=0.60,
                include_ac_storage=True,
                include_dc_storage=True,
                converter_capacity_kw=50.0,
            )
            plan = calculate_renewable_control_plan(
                snapshot,
                RenewableControlSettings(step_coefficient=0.10, converter_step_ratio=0.25),
            )
            state = manager._state_for("shared")
            try:
                first = manager._command_payload(state, plan, snapshot, "auto")
                second = manager._command_payload(state, plan, snapshot, "auto")
            finally:
                manager.close()

        self.assertEqual(first["set_values"], plan["commands"])
        command_keys = {
            (row["dev_type"], row["dev_name"], row["set_type"], row["set_value"])
            for row in first["set_values"]
        }
        for expected in (
            ("ACGenerator", "wind-1", "p_set"),
            ("DCGenerator", "pv-1", "p_set"),
            ("ACGenerator", "ac-grid-storage", "p_set"),
            ("DCGenerator", "dc-grid-storage", "p_set"),
            ("DCACConverter", "grid-converter-1", "p_ac_set"),
        ):
            self.assertTrue(any(key[:3] == expected for key in command_keys))
        self.assertFalse(
            any(key[1] in {"ac-balance-storage", "dc-balance-storage"} for key in command_keys)
        )
        self.assertTrue(
            all(
                key[3] <= 0.0
                for key in command_keys
                if key[:3] == ("DCACConverter", "grid-converter-1", "p_ac_set")
            )
        )
        balance_plan = calculate_renewable_control_plan(task8_metrics_snapshot())
        self.assertFalse(
            any(
                command["dev_name"] in {"ac-balance-storage", "dc-balance-storage"}
                for command in balance_plan["commands"]
            )
        )

        metrics = first["strategy"]["metrics"]
        for legacy_key in (
            "loadKw",
            "storageCurrentKw",
            "storageSoc",
            "renewableCurrentKw",
            "acdcCurrentKw",
            "acdcTargetKw",
        ):
            self.assertIn(legacy_key, metrics)
        for key in TASK8_METRIC_KEYS:
            self.assertIn(key, metrics)
        self.assertEqual(metrics["dcTransferGroups"], plan["metrics"]["dcTransferGroups"])

        first["strategy"]["metrics"]["dcTransferGroups"][0]["groupId"] = "mutated-by-client"
        self.assertNotEqual(
            first["strategy"]["metrics"]["dcTransferGroups"],
            second["strategy"]["metrics"]["dcTransferGroups"],
        )
        self.assertNotEqual(
            plan["metrics"]["dcTransferGroups"][0]["groupId"],
            "mutated-by-client",
        )
        json.dumps(first, ensure_ascii=False, default=str)
        json.dumps(second, ensure_ascii=False, default=str)

    def test_disabled_controller_still_collects_background_trend_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: {
                        "active": True,
                        "teacher_api_base": "http://teacher.invalid",
                        "snapshot_path": "/api/snapshot",
                        "command_path": "/api/student/commands",
                    },
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            manager = make_control_manager(services)
            manager._worker = threading.Thread(
                target=manager._worker_loop,
                name="test-renewable-monitor",
                daemon=True,
            )
            manager._worker.start()
            deadline = time.monotonic() + 1.5
            try:
                while time.monotonic() < deadline and not manager.state("shared")["trend"]:
                    time.sleep(0.05)
                controller_state = manager.state("shared")
            finally:
                manager.close()

        self.assertFalse(controller_state["enabled"])
        self.assertEqual(len(controller_state["trend"]), 1)
        self.assertEqual(controller_state["logs"], [])

    def test_same_simulation_time_dispatches_control_strategy_at_most_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: {
                        "active": True,
                        "teacher_api_base": "http://teacher.invalid",
                        "snapshot_path": "/api/snapshot",
                        "command_path": "/api/student/commands",
                    },
                },
            )()

            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            dispatched = []

            def command_sink(model_id, payload):
                dispatched.append({"model_id": model_id, "payload": copy.deepcopy(payload)})
                return {"set_values": len(payload.get("set_values", []))}

            snapshot = renewable_snapshot()
            manager = make_control_manager(
                services,
                snapshot=snapshot,
                command_sink=command_sink,
            )
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            try:
                manager.run_once("shared", trigger="auto", allow_dispatch=True, record_log=False)
                manager.run_once("shared", trigger="auto", allow_dispatch=True, record_log=False)
                self.assertEqual(len(dispatched), 1)
                self.assertEqual(
                    manager.state("shared")["lastDispatchedClockKey"],
                    "1|720|12:00:00",
                )

                snapshot["clock"]["absolute_minute"] += 1
                snapshot["clock"]["minute"] += 1
                snapshot["clock"]["time"] = "12:01:00"
                manager.run_once("shared", trigger="auto", allow_dispatch=True, record_log=False)

                snapshot["clock"].update(
                    {
                        "absolute_minute": 720,
                        "minute": 720,
                        "time": "12:00:00",
                        "run_id": 2,
                    }
                )
                manager.run_once("shared", trigger="auto", allow_dispatch=True, record_log=False)
            finally:
                manager.close()

        self.assertEqual(len(dispatched), 3)

    def test_generation_change_after_claim_allows_same_clock_retry_on_new_connection(self):
        with tempfile.TemporaryDirectory() as temporary:
            service, exchange, manager, _dispatched = make_exchange_backed_control_manager(
                temporary,
                snapshot=renewable_snapshot(),
            )
            transport_calls = []
            exchange.request_json = lambda url, **kwargs: transport_calls.append(
                (url, copy.deepcopy(kwargs))
            ) or {"set_values": len(kwargs.get("payload", {}).get("set_values", []))}
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            original_persist_runtime_log = manager._persist_runtime_log
            invalidated = False

            def invalidate_after_claim(controller_state, entry):
                nonlocal invalidated
                if not invalidated:
                    invalidated = True
                    service.set_trainee_receive_state({"teacher_model_id": "teacher-reconnected"})
                    exchange.receive_state_changed("shared")
                original_persist_runtime_log(controller_state, entry)

            manager._persist_runtime_log = invalidate_after_claim
            try:
                manager.run_once("shared", trigger="auto", allow_dispatch=True, record_log=True)
                self.assertEqual(transport_calls, [])

                manager._persist_runtime_log = original_persist_runtime_log
                exchange.publish_runtime_snapshot(
                    "shared",
                    renewable_snapshot(),
                    connection_signature=exchange._connection_signature(service),
                )
                manager.run_once("shared", trigger="auto", allow_dispatch=True, record_log=False)
            finally:
                manager.close()
                exchange.close()

        self.assertEqual(len(transport_calls), 1)

    def test_successful_dispatch_blocks_same_clock_after_connection_retarget(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = renewable_snapshot()
            service, exchange, manager, _dispatched = make_exchange_backed_control_manager(
                temporary,
                snapshot=snapshot,
            )
            transport_calls = []
            exchange.request_json = lambda url, **kwargs: transport_calls.append(
                (url, copy.deepcopy(kwargs))
            ) or {"set_values": len(kwargs.get("payload", {}).get("set_values", []))}
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            try:
                manager.run_once("shared", trigger="auto", allow_dispatch=True, record_log=False)
                self.assertEqual(len(transport_calls), 1)

                service.set_trainee_receive_state({"teacher_model_id": "teacher-reconnected"})
                exchange.receive_state_changed("shared")
                exchange.publish_runtime_snapshot(
                    "shared",
                    snapshot,
                    connection_signature=exchange._connection_signature(service),
                )

                controller_state = manager.run_once(
                    "shared",
                    trigger="auto",
                    allow_dispatch=True,
                    record_log=False,
                )
            finally:
                manager.close()
                exchange.close()

        self.assertEqual(len(transport_calls), 1)
        self.assertIn("当前仿真时刻已下发", controller_state["status"])

    def test_failed_started_transport_blocks_same_clock_after_connection_retarget(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = renewable_snapshot()
            service, exchange, manager, _dispatched = make_exchange_backed_control_manager(
                temporary,
                snapshot=snapshot,
            )
            transport_calls = []

            def failing_transport(url, **kwargs):
                transport_calls.append((url, copy.deepcopy(kwargs)))
                raise RuntimeError("transport result is unknown")

            exchange.request_json = failing_transport
            state = manager._state_for("shared")
            state.loop_mode = "closed"
            state.enabled = True
            try:
                manager.run_once("shared", trigger="auto", allow_dispatch=True, record_log=False)
                self.assertEqual(len(transport_calls), 1)

                service.set_trainee_receive_state({"teacher_model_id": "teacher-reconnected"})
                exchange.receive_state_changed("shared")
                exchange.publish_runtime_snapshot(
                    "shared",
                    snapshot,
                    connection_signature=exchange._connection_signature(service),
                )
                exchange.request_json = lambda url, **kwargs: transport_calls.append(
                    (url, copy.deepcopy(kwargs))
                ) or {"set_values": len(kwargs.get("payload", {}).get("set_values", []))}

                controller_state = manager.run_once(
                    "shared",
                    trigger="auto",
                    allow_dispatch=True,
                    record_log=False,
                )
            finally:
                manager.close()
                exchange.close()

        self.assertEqual(len(transport_calls), 1)
        self.assertIn("当前仿真时刻已下发", controller_state["status"])

    def test_transport_start_is_committed_before_final_generation_guard_releases(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = renewable_snapshot()
            service, exchange, manager, _dispatched = make_exchange_backed_control_manager(
                temporary,
                snapshot=snapshot,
            )
            transport_calls = []
            exchange.request_json = lambda url, **kwargs: transport_calls.append(
                (url, copy.deepcopy(kwargs))
            ) or {"set_values": len(kwargs.get("payload", {}).get("set_values", []))}
            controller_state = manager._state_for("shared")
            controller_state.loop_mode = "closed"
            controller_state.enabled = True
            original_generation_scope = exchange._control_generation_scope_for_service
            valid_scope_count = 0
            clock_keys_seen_before_retarget = []

            @contextmanager
            def retarget_after_final_generation_guard(target_service, exchange_state, expected):
                nonlocal valid_scope_count
                with original_generation_scope(target_service, exchange_state, expected) as valid:
                    yield valid
                if not valid:
                    return
                valid_scope_count += 1
                if valid_scope_count != 2:
                    return
                with controller_state.lock:
                    clock_keys_seen_before_retarget.append(
                        controller_state.last_dispatched_clock_key
                    )
                service.set_trainee_receive_state(
                    {"teacher_model_id": "teacher-reconnected"}
                )
                exchange.receive_state_changed("shared")

            exchange._control_generation_scope_for_service = (
                retarget_after_final_generation_guard
            )
            try:
                manager.run_once(
                    "shared",
                    trigger="auto",
                    allow_dispatch=True,
                    record_log=False,
                )
            finally:
                exchange._control_generation_scope_for_service = original_generation_scope
                manager.close()
                exchange.close()

        self.assertEqual(clock_keys_seen_before_retarget, ["1|720|12:00:00"])
        self.assertEqual(len(transport_calls), 1)

    def test_worker_registry_failure_preserves_existing_controller_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                },
            )()

            class FailingRegistry:
                def service_for(self, _model_id=None):
                    return target

                def iter_services(self):
                    raise RuntimeError("temporary registry failure")

            manager = make_control_manager(FailingRegistry())
            manager._state_for("shared")

            class OneIterationStop:
                def __init__(self):
                    self.checks = 0
                    self.forced = False

                def is_set(self):
                    if self.forced:
                        return True
                    self.checks += 1
                    return self.checks > 1

                def wait(self, _timeout):
                    return True

                def set(self):
                    self.forced = True

            manager._stop_event = OneIterationStop()
            try:
                manager._worker_loop()
                self.assertIn("shared", manager._states)
            finally:
                manager.close()

    def test_control_parameters_and_loop_mode_reload_from_model_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            model_root = source_root / "shared"
            model_root.mkdir(parents=True)
            for source in SIMPLE_MODEL_SOURCE.iterdir():
                if source.is_file():
                    (model_root / source.name).write_bytes(source.read_bytes())
            spec = SimulationModelSpec("shared", model_root, "Shared")
            runtime_root = root / "runtime"

            services = MultiModelSimulator(
                [spec],
                runtime_dir=runtime_root,
                models_root=source_root,
                kernel=lambda _config: None,
            )
            manager = make_control_manager(services)
            try:
                manager.apply_action(
                    "shared",
                    {
                        "action": "update_settings",
                        "settings": {
                            "intervalSeconds": 2,
                            "renewableStepRatio": 0.10,
                            "storageStepRatio": 0.05,
                            "storageSocCorrectionStepScale": 0.20,
                            "gridFormingStorageProtectionRatio": 0.06,
                            "dieselPowerProtectionRatio": 0.04,
                            "socDeadband": 0.05,
                            "storageChargeDeratingCurve": [
                                {"soc": 0.55, "powerRatio": 1.0},
                                {"soc": 0.90, "powerRatio": 0.0},
                            ],
                            "storageDischargeDeratingCurve": [
                                {"soc": 0.10, "powerRatio": 0.0},
                                {"soc": 0.45, "powerRatio": 1.0},
                            ],
                        },
                    },
                )
                manager.apply_action("shared", {"action": "set_loop_mode", "loop_mode": "closed"})
                persistence_file = services.service_for("shared").runtime_dir / "renewable_control.json"
                self.assertTrue(persistence_file.exists())
            finally:
                manager.close()

            reloaded_services = MultiModelSimulator(
                [spec],
                runtime_dir=runtime_root,
                models_root=source_root,
                kernel=lambda _config: None,
            )
            reloaded_manager = make_control_manager(reloaded_services)
            try:
                state = reloaded_manager.state("shared")
            finally:
                reloaded_manager.close()

        self.assertFalse(state["enabled"])
        self.assertEqual(state["loopMode"], "closed")
        self.assertEqual(state["settings"]["intervalSeconds"], 2.0)
        self.assertEqual(state["settings"]["renewableStepRatio"], 0.10)
        self.assertEqual(state["settings"]["storageStepRatio"], 0.05)
        self.assertEqual(
            state["settings"]["storageSocCorrectionStepScale"],
            0.20,
        )
        self.assertEqual(
            state["settings"]["gridFormingStorageProtectionRatio"],
            0.06,
        )
        self.assertEqual(
            state["settings"]["dieselPowerProtectionRatio"],
            0.04,
        )
        self.assertEqual(state["settings"]["socDeadband"], 0.05)
        self.assertEqual(
            state["settings"]["storageChargeDeratingCurve"],
            [
                {"soc": 0.55, "powerRatio": 1.0},
                {"soc": 0.90, "powerRatio": 0.0},
            ],
        )
        self.assertEqual(
            state["settings"]["storageDischargeDeratingCurve"],
            [
                {"soc": 0.10, "powerRatio": 0.0},
                {"soc": 0.45, "powerRatio": 1.0},
            ],
        )
        self.assertNotIn("converterSocPowerLimits", state["settings"])

    def test_realtime_control_desired_state_survives_web_restart_and_runs_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime_dir = Path(temporary)
            snapshot = renewable_snapshot()

            def make_services():
                target = type(
                    "TargetService",
                    (),
                    {
                        "model_id": "shared",
                        "runtime_dir": runtime_dir,
                    },
                )()
                services = type(
                    "Services",
                    (),
                    {
                        "service_for": lambda self, _model_id: target,
                        "iter_services": lambda self: [target],
                    },
                )()
                return services

            first_dispatches = []
            first_manager = make_control_manager(
                make_services(),
                snapshot=snapshot,
                command_sink=lambda model_id, payload: first_dispatches.append(
                    (model_id, copy.deepcopy(payload))
                ) or {},
            )
            try:
                first_manager.apply_action(
                    "shared",
                    {"action": "set_loop_mode", "loop_mode": "closed"},
                )
                started = first_manager.apply_action("shared", {"action": "start"})
                self.assertTrue(started["enabled"])
                self.assertTrue(started["desiredEnabled"])
            finally:
                first_manager.close()

            persisted = json.loads(
                (runtime_dir / "renewable_control.json").read_text(encoding="utf-8")
            )
            self.assertTrue(persisted["desiredEnabled"])

            resumed_dispatches = []
            resumed_manager = make_control_manager(
                make_services(),
                snapshot=snapshot,
                command_sink=lambda model_id, payload: resumed_dispatches.append(
                    (model_id, copy.deepcopy(payload))
                ) or {},
            )
            try:
                resumed = resumed_manager.state("shared")
                self.assertTrue(resumed["enabled"])
                self.assertTrue(resumed["desiredEnabled"])
                self.assertFalse(resumed["resumePending"])
                self.assertIn("自动恢复", resumed["status"])

                resumed_manager._run_worker_iteration(now=time.monotonic())
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and not resumed_dispatches:
                    time.sleep(0.01)
            finally:
                resumed_manager.close()

        self.assertEqual(len(first_dispatches), 1)
        self.assertEqual(len(resumed_dispatches), 1)

    def test_web_restart_waits_for_receive_and_resumes_when_receive_returns(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime_dir = Path(temporary)
            receive_state = {
                "active": True,
                "ready": True,
                "revision": 1,
                "signature": ("learner", 1),
            }
            active_snapshot = renewable_snapshot()

            def make_services():
                target = type(
                    "TargetService",
                    (),
                    {
                        "model_id": "shared",
                        "runtime_dir": runtime_dir,
                    },
                )()
                return type(
                    "Services",
                    (),
                    {
                        "service_for": lambda self, _model_id: target,
                        "iter_services": lambda self: [target],
                    },
                )()

            def snapshot_provider(_model_id):
                return ready_view(
                    active_snapshot,
                    revision=receive_state["revision"],
                    signature=receive_state["signature"],
                )

            first_manager = make_control_manager(
                make_services(),
                snapshot_provider=snapshot_provider,
                receive_status_provider=mutable_receive_status(receive_state),
            )
            try:
                first_manager.apply_action(
                    "shared",
                    {"action": "set_loop_mode", "loop_mode": "closed"},
                )
                first_manager.apply_action("shared", {"action": "start"})
            finally:
                first_manager.close()

            receive_state.update({
                "active": False,
                "ready": False,
                "revision": 2,
                "signature": ("learner", 2),
            })
            resumed_dispatches = []
            resumed_manager = make_control_manager(
                make_services(),
                snapshot_provider=snapshot_provider,
                receive_status_provider=mutable_receive_status(receive_state),
                command_sink=lambda model_id, payload: resumed_dispatches.append(
                    (model_id, copy.deepcopy(payload))
                ) or {},
            )
            try:
                waiting = resumed_manager.state("shared")
                self.assertFalse(waiting["enabled"])
                self.assertTrue(waiting["desiredEnabled"])
                self.assertTrue(waiting["resumePending"])
                self.assertEqual(waiting["runState"], "resume_pending")

                receive_state.update({
                    "active": True,
                    "ready": True,
                    "revision": 3,
                    "signature": ("learner", 3),
                })
                active_snapshot["clock"].update({
                    "time": "00:01:00",
                    "minute": 1,
                    "absolute_minute": 1,
                    "step_count": 1,
                })
                recovered = resumed_manager.receive_state_changed("shared")
                resumed_manager._run_worker_iteration(now=time.monotonic())
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and not resumed_dispatches:
                    time.sleep(0.01)
            finally:
                resumed_manager.close()

        self.assertTrue(recovered["enabled"])
        self.assertTrue(recovered["desiredEnabled"])
        self.assertFalse(recovered["resumePending"])
        self.assertEqual(recovered["runState"], "running")
        self.assertEqual(len(resumed_dispatches), 1)

    def test_explicit_stop_clears_desired_state_and_prevents_restart_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime_dir = Path(temporary)
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": runtime_dir,
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            manager = make_control_manager(services)
            try:
                manager.apply_action(
                    "shared",
                    {"action": "set_loop_mode", "loop_mode": "closed"},
                )
                manager.apply_action("shared", {"action": "start"})
                stopped = manager.apply_action("shared", {"action": "stop"})
                self.assertFalse(stopped["enabled"])
                self.assertFalse(stopped["desiredEnabled"])
                self.assertFalse(stopped["resumePending"])
            finally:
                manager.close()

            persisted = json.loads(
                (runtime_dir / "renewable_control.json").read_text(encoding="utf-8")
            )
            self.assertFalse(persisted["desiredEnabled"])

            reloaded_dispatches = []
            reloaded_target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": runtime_dir,
                },
            )()
            reloaded_services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: reloaded_target,
                    "iter_services": lambda self: [reloaded_target],
                },
            )()
            reloaded_manager = make_control_manager(
                reloaded_services,
                command_sink=lambda model_id, payload: reloaded_dispatches.append(
                    (model_id, copy.deepcopy(payload))
                ) or {},
            )
            try:
                reloaded = reloaded_manager.state("shared")
                reloaded_manager._run_worker_iteration(now=time.monotonic())
                time.sleep(0.05)
            finally:
                reloaded_manager.close()

        self.assertFalse(reloaded["enabled"])
        self.assertFalse(reloaded["desiredEnabled"])
        self.assertFalse(reloaded["resumePending"])
        self.assertEqual(reloaded_dispatches, [])

    def test_explicit_stop_during_start_intent_prevents_late_reenable(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            manager = make_control_manager(services)
            entered_reject = threading.Event()
            release_reject = threading.Event()
            original_reject = manager._reject_without_receive_for_service

            def blocked_reject(*args, **kwargs):
                entered_reject.set()
                self.assertTrue(release_reject.wait(timeout=2.0))
                return original_reject(*args, **kwargs)

            manager._reject_without_receive_for_service = blocked_reject
            start_result = {}
            start_thread = threading.Thread(
                target=lambda: start_result.setdefault(
                    "state",
                    manager.apply_action("shared", {"action": "start"}),
                )
            )
            try:
                start_thread.start()
                self.assertTrue(entered_reject.wait(timeout=2.0))
                stopped = manager.apply_action("shared", {"action": "stop"})
                release_reject.set()
                start_thread.join(timeout=2.0)
                self.assertFalse(start_thread.is_alive())
                final_state = manager.state("shared")
            finally:
                release_reject.set()
                start_thread.join(timeout=2.0)
                manager.close()

            persisted = json.loads(
                (Path(temporary) / "renewable_control.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertFalse(stopped["enabled"])
        self.assertFalse(stopped["desiredEnabled"])
        self.assertFalse(start_result["state"]["enabled"])
        self.assertFalse(start_result["state"]["desiredEnabled"])
        self.assertFalse(final_state["enabled"])
        self.assertFalse(final_state["desiredEnabled"])
        self.assertFalse(persisted["desiredEnabled"])

    def test_legacy_persisted_converter_soc_limits_are_ignored_on_reload(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = type(
                "TargetService",
                (),
                {
                    "model_id": "shared",
                    "runtime_dir": Path(temporary),
                    "trainee_receive_state": lambda self: {},
                },
            )()
            services = type(
                "Services",
                (),
                {
                    "service_for": lambda self, _model_id: target,
                    "iter_services": lambda self: [target],
                },
            )()
            persisted_path = Path(temporary) / "renewable_control.json"
            persisted_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "modelId": "shared",
                        "loopMode": "closed",
                        "settings": {
                            "renewableStepRatio": 0.07,
                            "converterSocPowerLimits": [
                                0.0,
                                0.0,
                                0.2,
                                0.4,
                                0.4,
                                0.5,
                                0.6,
                                0.8,
                                0.8,
                                1.0,
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = make_control_manager(services)
            try:
                state = manager.state("shared")
            finally:
                manager.close()

        self.assertEqual(state["loopMode"], "closed")
        self.assertEqual(state["settings"]["renewableStepRatio"], 0.07)
        self.assertNotIn("converterSocPowerLimits", state["settings"])

    def test_two_web_clients_read_and_operate_one_shared_backend_controller(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            model_root = source_root / "shared"
            model_root.mkdir(parents=True)
            for source in SIMPLE_MODEL_SOURCE.iterdir():
                if source.is_file():
                    (model_root / source.name).write_bytes(source.read_bytes())
            services = MultiModelSimulator(
                [SimulationModelSpec("shared", model_root, "Shared")],
                runtime_dir=root / "runtime",
                models_root=source_root,
                kernel=lambda _config: None,
            )
            manager = make_control_manager(services)
            server = make_http_server(
                ("127.0.0.1", 0),
                services,
                role="trainee",
                renewable_control_manager=manager,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                request = Request(
                    f"{base}/api/trainee/renewable-control?model_id=shared",
                    data=json.dumps({"action": "set_loop_mode", "loop_mode": "closed"}).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(request, timeout=5) as response:
                    first_client = json.loads(response.read().decode("utf-8"))
                settings_request = Request(
                    f"{base}/api/trainee/renewable-control?model_id=shared",
                    data=json.dumps(
                        {
                            "action": "update_settings",
                            "settings": {"renewableStepRatio": 0.08},
                        }
                    ).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(settings_request, timeout=5) as response:
                    updated_client = json.loads(response.read().decode("utf-8"))
                with urlopen(
                    f"{base}/api/trainee/renewable-control?model_id=shared",
                    timeout=5,
                ) as response:
                    second_client = json.loads(response.read().decode("utf-8"))
                runtime_logs = list(services.service_for("shared").runtime_logs)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(first_client["loopMode"], "closed")
        self.assertEqual(second_client["loopMode"], "closed")
        self.assertEqual(updated_client["revision"], second_client["revision"])
        self.assertEqual(updated_client["settings"]["renewableStepRatio"], 0.08)
        self.assertEqual(second_client["settings"]["renewableStepRatio"], 0.08)
        self.assertNotIn("converterSocPowerLimits", updated_client["settings"])
        self.assertNotIn("converterSocPowerLimits", second_client["settings"])
        self.assertEqual(first_client["modelId"], "shared")
        self.assertTrue(any(item.get("result") == "方式切换" for item in runtime_logs))

    def test_compact_incremental_state_omits_repeated_trend_and_log_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            model_root = source_root / "shared"
            model_root.mkdir(parents=True)
            for source in SIMPLE_MODEL_SOURCE.iterdir():
                if source.is_file():
                    (model_root / source.name).write_bytes(source.read_bytes())
            services = MultiModelSimulator(
                [SimulationModelSpec("shared", model_root, "Shared")],
                runtime_dir=root / "runtime",
                models_root=source_root,
                kernel=lambda _config: None,
            )
            manager = make_control_manager(services)
            controller = manager._state_for("shared")
            with controller.lock:
                controller.trend = [
                    {
                        "sampleKey": "sample-1",
                        "runId": 1,
                        "stepCount": 1,
                        "minute": 1,
                        "time": "00:01:00",
                        "loadKw": 100.0,
                        "dieselKw": 20.0,
                        "storageKw": 5.0,
                        "storageSocPercent": 50.0,
                        "renewableKw": 80.0,
                        "acLoadKw": 70.0,
                        "dcLoadKw": 30.0,
                        "dieselCurrentKw": 20.0,
                        "dieselTargetKw": 18.0,
                        "acRenewableCurrentKw": 30.0,
                        "acRenewableTargetKw": 32.0,
                        "acWindCurrentKw": 20.0,
                        "acWindTargetKw": 21.0,
                        "acPvCurrentKw": 10.0,
                        "acPvTargetKw": 11.0,
                        "dcRenewableCurrentKw": 50.0,
                        "dcRenewableTargetKw": 51.0,
                        "dcWindCurrentKw": 20.0,
                        "dcWindTargetKw": 20.0,
                        "dcPvCurrentKw": 30.0,
                        "dcPvTargetKw": 31.0,
                        "acGridFollowingStorageCurrentKw": 1.0,
                        "acGridFollowingStorageTargetKw": 1.5,
                        "dcGridFollowingStorageCurrentKw": 2.0,
                        "dcGridFollowingStorageTargetKw": 2.5,
                        "acGridFormingStorageCurrentKw": 3.0,
                        "acGridFormingStorageTargetKw": 3.5,
                        "dcGridFormingStorageCurrentKw": 4.0,
                        "dcGridFormingStorageTargetKw": 4.5,
                        "acGridFollowingStorageSocPercent": 40.0,
                        "dcGridFollowingStorageSocPercent": 50.0,
                        "acGridFormingStorageSocPercent": 60.0,
                        "dcGridFormingStorageSocPercent": 70.0,
                        "acDieselCurrentKw": 20.0,
                        "acDieselMinKw": 10.0,
                        "acDieselTargetKw": 18.0,
                        "dcDieselCurrentKw": 0.0,
                        "dcDieselMinKw": 0.0,
                        "dcDieselTargetKw": 0.0,
                        "totalRenewableCurrentKw": 80.0,
                        "totalRenewableTargetKw": 83.0,
                        "totalWindCurrentKw": 40.0,
                        "totalWindTargetKw": 41.0,
                        "totalPvCurrentKw": 40.0,
                        "totalPvTargetKw": 42.0,
                        "totalGridFollowingStorageCurrentKw": 3.0,
                        "totalGridFollowingStorageTargetKw": 4.0,
                        "totalGridFollowingStorageSocPercent": 45.0,
                        "totalGridFormingStorageCurrentKw": 7.0,
                        "totalGridFormingStorageTargetKw": 8.0,
                        "totalGridFormingStorageSocPercent": 65.0,
                        "totalDieselCurrentKw": 20.0,
                        "totalDieselMinKw": 10.0,
                        "totalDieselTargetKw": 18.0,
                        "totalLoadKw": 100.0,
                        "acdcCurrentKw": 10.0,
                        "acdcTargetKw": 11.0,
                        "dcTransferGroups": [{"detail": "x" * 20000}],
                    },
                    {
                        "sampleKey": "sample-2",
                        "runId": 1,
                        "stepCount": 2,
                        "minute": 2,
                        "time": "00:02:00",
                        "loadKw": 101.0,
                        "dieselKw": 19.0,
                        "storageKw": 6.0,
                        "storageSocPercent": 49.9,
                        "renewableKw": 81.0,
                        "acLoadKw": 71.0,
                        "dcLoadKw": 30.0,
                        "dieselCurrentKw": 19.0,
                        "dieselTargetKw": 18.0,
                        "acRenewableCurrentKw": 31.0,
                        "acRenewableTargetKw": 33.0,
                        "acWindCurrentKw": 20.5,
                        "acWindTargetKw": 21.5,
                        "acPvCurrentKw": 10.5,
                        "acPvTargetKw": 11.5,
                        "dcRenewableCurrentKw": 50.0,
                        "dcRenewableTargetKw": 51.0,
                        "dcWindCurrentKw": 20.0,
                        "dcWindTargetKw": 20.0,
                        "dcPvCurrentKw": 30.0,
                        "dcPvTargetKw": 31.0,
                        "acGridFollowingStorageCurrentKw": 1.5,
                        "acGridFollowingStorageTargetKw": 2.0,
                        "dcGridFollowingStorageCurrentKw": 2.5,
                        "dcGridFollowingStorageTargetKw": 3.0,
                        "acGridFormingStorageCurrentKw": 3.5,
                        "acGridFormingStorageTargetKw": 4.0,
                        "dcGridFormingStorageCurrentKw": 4.5,
                        "dcGridFormingStorageTargetKw": 5.0,
                        "acGridFollowingStorageSocPercent": 39.9,
                        "dcGridFollowingStorageSocPercent": 49.9,
                        "acGridFormingStorageSocPercent": 59.9,
                        "dcGridFormingStorageSocPercent": 69.9,
                        "acDieselCurrentKw": 19.0,
                        "acDieselMinKw": 10.0,
                        "acDieselTargetKw": 18.0,
                        "dcDieselCurrentKw": 0.0,
                        "dcDieselMinKw": 0.0,
                        "dcDieselTargetKw": 0.0,
                        "totalRenewableCurrentKw": 81.0,
                        "totalRenewableTargetKw": 84.0,
                        "totalWindCurrentKw": 40.5,
                        "totalWindTargetKw": 41.5,
                        "totalPvCurrentKw": 40.5,
                        "totalPvTargetKw": 42.5,
                        "totalGridFollowingStorageCurrentKw": 4.0,
                        "totalGridFollowingStorageTargetKw": 5.0,
                        "totalGridFollowingStorageSocPercent": 44.9,
                        "totalGridFormingStorageCurrentKw": 8.0,
                        "totalGridFormingStorageTargetKw": 9.0,
                        "totalGridFormingStorageSocPercent": 64.9,
                        "totalDieselCurrentKw": 19.0,
                        "totalDieselMinKw": 10.0,
                        "totalDieselTargetKw": 18.0,
                        "totalLoadKw": 101.0,
                        "acdcCurrentKw": 11.0,
                        "acdcTargetKw": 12.0,
                        "dcTransferGroups": [{"detail": "y" * 20000}],
                    },
                ]
                controller.trend_normalized = True
                controller.log_seq = 2
                controller.logs = [
                    {"seq": 2, "detail": "new-log", "type": "策略控制"},
                    {"seq": 1, "detail": "old-log", "type": "策略控制"},
                ]
            server = make_http_server(
                ("127.0.0.1", 0),
                services,
                role="trainee",
                renewable_control_manager=manager,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                path = (
                    "/api/trainee/renewable-control?model_id=shared"
                    "&compact=1&after_log_seq=1&after_trend_sample_key=sample-1"
                )
                with urlopen(f"{base}{path}", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                manager.close()

        self.assertFalse(payload["logsReset"])
        self.assertEqual([item["seq"] for item in payload["logs"]], [2])
        self.assertEqual(payload["latestLogSeq"], 2)
        self.assertFalse(payload["trendReset"])
        self.assertEqual(
            [point["sampleKey"] for point in payload["trend"]],
            ["sample-1", "sample-2"],
        )
        self.assertEqual(payload["latestTrendSampleKey"], "sample-2")
        self.assertNotIn("dcTransferGroups", payload["trend"][0])
        for field in (
            "acLoadKw",
            "dcLoadKw",
            "dieselCurrentKw",
            "dieselTargetKw",
            "acRenewableCurrentKw",
            "acRenewableTargetKw",
            "dcRenewableCurrentKw",
            "dcRenewableTargetKw",
            "acGridFollowingStorageCurrentKw",
            "acGridFollowingStorageTargetKw",
            "acGridFollowingStorageSocPercent",
            "dcGridFollowingStorageCurrentKw",
            "dcGridFollowingStorageTargetKw",
            "dcGridFollowingStorageSocPercent",
            "acGridFormingStorageCurrentKw",
            "acGridFormingStorageTargetKw",
            "acGridFormingStorageSocPercent",
            "dcGridFormingStorageCurrentKw",
            "dcGridFormingStorageTargetKw",
            "dcGridFormingStorageSocPercent",
            "acdcCurrentKw",
            "acdcTargetKw",
            "acWindCurrentKw",
            "acWindTargetKw",
            "acPvCurrentKw",
            "acPvTargetKw",
            "dcWindCurrentKw",
            "dcWindTargetKw",
            "dcPvCurrentKw",
            "dcPvTargetKw",
            "acDieselCurrentKw",
            "acDieselMinKw",
            "acDieselTargetKw",
            "dcDieselCurrentKw",
            "dcDieselMinKw",
            "dcDieselTargetKw",
            "totalRenewableCurrentKw",
            "totalRenewableTargetKw",
            "totalWindCurrentKw",
            "totalWindTargetKw",
            "totalPvCurrentKw",
            "totalPvTargetKw",
            "totalGridFollowingStorageCurrentKw",
            "totalGridFollowingStorageTargetKw",
            "totalGridFollowingStorageSocPercent",
            "totalGridFormingStorageCurrentKw",
            "totalGridFormingStorageTargetKw",
            "totalGridFormingStorageSocPercent",
            "totalDieselCurrentKw",
            "totalDieselMinKw",
            "totalDieselTargetKw",
            "totalLoadKw",
        ):
            with self.subTest(field=field):
                self.assertIn(field, payload["trend"][0])
        self.assertLess(
            len(json.dumps(payload["trend"], ensure_ascii=False).encode("utf-8")),
            4200,
        )

    def test_compact_incremental_state_omits_unchanged_last_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            model_root = source_root / "shared"
            model_root.mkdir(parents=True)
            for source in SIMPLE_MODEL_SOURCE.iterdir():
                if source.is_file():
                    (model_root / source.name).write_bytes(source.read_bytes())
            services = MultiModelSimulator(
                [SimulationModelSpec("shared", model_root, "Shared")],
                runtime_dir=root / "runtime",
                models_root=source_root,
                kernel=lambda _config: None,
            )
            manager = make_control_manager(services)
            controller = manager._state_for("shared")
            with controller.lock:
                controller.last_plan = {"time": "00:01:00", "detail": "x" * 10000}
                controller.plan_revision = 1
            server = make_http_server(
                ("127.0.0.1", 0),
                services,
                role="trainee",
                renewable_control_manager=manager,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                path = "/api/trainee/renewable-control?model_id=shared&compact=1"
                with urlopen(f"{base}{path}", timeout=5) as response:
                    first = json.loads(response.read().decode("utf-8"))

                cursor_path = (
                    f"{path}&after_plan_revision={first['planRevision']}"
                    f"&after_controller_instance_id={first['controllerInstanceId']}"
                )
                with urlopen(f"{base}{cursor_path}", timeout=5) as response:
                    unchanged = json.loads(response.read().decode("utf-8"))

                retired_cursor_path = (
                    f"{path}&after_plan_revision={first['planRevision']}"
                    "&after_controller_instance_id=retired-controller"
                )
                with urlopen(f"{base}{retired_cursor_path}", timeout=5) as response:
                    new_lifecycle = json.loads(response.read().decode("utf-8"))

                with controller.lock:
                    controller.last_plan = {"time": "00:02:00", "detail": "y" * 10000}
                    controller.plan_revision += 1
                with urlopen(f"{base}{cursor_path}", timeout=5) as response:
                    changed = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                manager.close()

        self.assertEqual(first["planRevision"], 1)
        self.assertEqual(first["lastPlan"]["time"], "00:01:00")
        self.assertEqual(unchanged["planRevision"], 1)
        self.assertNotIn("lastPlan", unchanged)
        self.assertEqual(new_lifecycle["lastPlan"]["time"], "00:01:00")
        self.assertEqual(changed["planRevision"], 2)
        self.assertEqual(changed["lastPlan"]["time"], "00:02:00")


if __name__ == "__main__":
    unittest.main()
