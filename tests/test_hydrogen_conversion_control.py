from __future__ import annotations

from pathlib import Path
import re
import tempfile

import pytest

import simu_loop
from simu import server as server_module
from simu.service import PolarMicrogridSimulator


ROOT = Path(__file__).resolve().parents[1]


def _replace_block(text: str, block_name: str, replacement: str) -> str:
    updated, count = re.subn(
        rf"<{block_name}>.*?</{block_name}>",
        replacement.strip(),
        text,
        count=1,
        flags=re.DOTALL,
    )
    assert count == 1
    return updated


def _write_conversion_model(
    directory: Path,
    *,
    electrolyzer_mode: str = "P",
    fuel_cell_mode: str = "P",
) -> Path:
    text = (ROOT / "tests" / "fixtures" / "simple_model" / "model.e").read_text(
        encoding="utf-8"
    )
    text = _replace_block(
        text,
        "ACLoad",
        """
<ACLoad>
@ idx name node p_set p_max p_min q_max q_min run_stat rated_capacity pbase pv0 pv1 pv2 qbase qv0 qv1 qv2
# 1 electrolyzer_ac_load 6 2 50 0 30 0 1 50 2 1 0 0 30 1 0 0
</ACLoad>
""",
    )
    text = _replace_block(
        text,
        "DCGenerator",
        """
<DCGenerator>
@ idx name dev_type node control_type v_set p_set p_max p_min i_set run_stat rated_capacity
# 1 dc_bus_vctrl dc-voltage-source 1 V 720 0 100 -100 0 1 100
# 2 pv01_vsrc dc-pv-source 3 P 300 0 50 0 0 1 50
# 3 ess01_vsrc dc-storage 5 P 300 0 40 -40 0 1 40
# 4 fuel_cell_dc_source dc-fuel-cell 4 P 720 5.4 50 0 0 1 50
</DCGenerator>
""",
    )
    text += """
<HydroMedium>
@ density compressibility molar_mass temperature flow_factor
# 0.08375 1.0 0.002016 288.15 0.35
</HydroMedium>
<HydroNode>
@ idx name pressure run_stat
# 1 h2_reference 3.00 1
# 2 h2_load_bus 2.95 1
# 3 h2_source_bus 2.98 1
</HydroNode>
<HydroSource>
@ idx name node control_type pressure_set flow_set alpha flow_min flow_max run_stat
# 1 h2_reference_source 1 PRESSURE 3.00 0 1 0 20 1
# 2 electrolyzer_h2_source 3 FLOW 2.98 0.4 1 0 20 1
</HydroSource>
<HydroLoad>
@ idx name node flow_set run_stat
# 1 fuel_cell_h2_load 2 3 1
</HydroLoad>
<HydroPipe>
@ idx name i_node j_node conductance run_stat
# 1 h2_pipe_12 1 2 3.0 1
# 2 h2_pipe_13 1 3 3.0 1
</HydroPipe>
<AcE2Hydro>
@ idx name run_stat control_type idx_ac_load_t1 idx_h2_unit_t2 e2h_coeff
# 1 ac_electrolyzer 1 {electrolyzer_mode} 1 2 0.2
</AcE2Hydro>
<Hydro2DcE>
@ idx name run_stat control_type idx_dc_unit_t1 idx_h2_load_t2 h2e_coeff
# 1 dc_fuel_cell 1 {fuel_cell_mode} 4 1 1.8
</Hydro2DcE>
""".format(
        electrolyzer_mode=electrolyzer_mode,
        fuel_cell_mode=fuel_cell_mode,
    )
    model_path = directory / "model.e"
    model_path.write_text(text, encoding="utf-8")
    return model_path


def _write_storage_coupled_model(directory: Path) -> Path:
    model_path = _write_conversion_model(directory)
    text = model_path.read_text(encoding="utf-8")
    text = _replace_block(
        text,
        "HydroNode",
        """
<HydroNode>
@ idx name pressure run_stat
# 1 h2_bus 35 1
</HydroNode>
""",
    )
    text = _replace_block(
        text,
        "HydroSource",
        """
<HydroSource>
@ idx name node control_type pressure_set flow_set alpha flow_min flow_max run_stat
# 1 electrolyzer_h2_source 1 FLOW 35 0.4 1 0 20 1
</HydroSource>
""",
    )
    text = _replace_block(
        text,
        "HydroLoad",
        """
<HydroLoad>
@ idx name node flow_set run_stat
# 1 fuel_cell_h2_load 1 3 1
</HydroLoad>
""",
    )
    text = _replace_block(
        text,
        "HydroPipe",
        """
<HydroPipe>
@ idx name i_node j_node conductance run_stat
</HydroPipe>
""",
    )
    text = text.replace(
        "# 1 ac_electrolyzer 1 P 1 2 0.2",
        "# 1 ac_electrolyzer 1 P 1 1 0.2",
    )
    text += """
<HydroStorage>
@ idx name dev_type node control_type pressure_set flow_set alpha flow_min flow_max run_stat pressure gas_quantity water_volume pressure_max pressure_min
# 1 tank-1 hydrogen-tank 1 PRESSURE 35 0 1 -20 20 1 35 17500 50 45 2
</HydroStorage>
"""
    model_path.write_text(text, encoding="utf-8")
    return model_path


def _endpoint_rows(book):
    return {
        "ac_load": book.data["ACLoad"].data[0],
        "dc_gen": book.data["DCGenerator"].data[3],
        "h2_source": book.data["HydroSource"].data[1],
        "h2_load": book.data["HydroLoad"].data[0],
    }


def _measurement(snapshot, dev_type: str, dev_name: str, meas_type: str) -> float:
    row = ["1", "point", dev_type, dev_name, meas_type, "1", "1", "0"]
    value = simu_loop._measurement_value(snapshot, row)
    assert value is not None
    return float(value)


@pytest.mark.parametrize(
    ("block_name", "coefficient_field"),
    (("AcE2Hydro", "e2h_coeff"), ("Hydro2DcE", "h2e_coeff")),
)
def test_conversion_model_uses_direction_specific_coefficient_field(
    tmp_path,
    block_name,
    coefficient_field,
):
    block = simu_loop.EBook(_write_conversion_model(tmp_path)).data[block_name]

    assert coefficient_field in block.header_list
    assert "efficiency" not in block.header_list


def test_power_control_drives_hydrogen_flow_and_realtime_measurements(tmp_path):
    model_path = _write_conversion_model(tmp_path)
    book = simu_loop.EBook(model_path)
    rows = _endpoint_rows(book)

    snapshot, solver_info = simu_loop.solve_hybrid_snapshot_from_book(book, model_path)

    assert "normF=" in solver_info
    assert _measurement(snapshot, "AcE2Hydro", book.data["AcE2Hydro"].data[0]["name"], "P") == pytest.approx(2.0)
    assert _measurement(snapshot, "AcE2Hydro", book.data["AcE2Hydro"].data[0]["name"], "FLOW") == pytest.approx(0.4)
    assert _measurement(snapshot, "Hydro2DcE", book.data["Hydro2DcE"].data[0]["name"], "P") == pytest.approx(5.4)
    assert _measurement(snapshot, "Hydro2DcE", book.data["Hydro2DcE"].data[0]["name"], "FLOW") == pytest.approx(3.0)
    assert _measurement(snapshot, "HydroSource", rows["h2_source"]["name"], "FLOW") == pytest.approx(0.4)
    assert _measurement(snapshot, "HydroLoad", rows["h2_load"]["name"], "FLOW") == pytest.approx(3.0)
    assert {result.status for result in snapshot.coupling_results} == {"balanced"}


def test_flow_control_ignores_conflicting_electric_setpoints(tmp_path):
    model_path = _write_conversion_model(tmp_path)
    book = simu_loop.EBook(model_path)
    rows = _endpoint_rows(book)
    book.data["AcE2Hydro"].data[0]["control_type"] = "FLOW"
    book.data["Hydro2DcE"].data[0]["control_type"] = "FLOW"
    rows["ac_load"].update(p_set="47", pbase="47")
    rows["dc_gen"]["p_set"] = "40"
    rows["h2_source"]["flow_set"] = "0.4"
    rows["h2_load"]["flow_set"] = "3"

    snapshot, _solver_info = simu_loop.solve_hybrid_snapshot_from_book(book, model_path)

    assert snapshot.value("ACLoad", rows["ac_load"]["name"], "P_LOAD") == pytest.approx(2.0)
    assert snapshot.value("DCGenerator", rows["dc_gen"]["name"], "P_GEN") == pytest.approx(5.4)
    assert _measurement(snapshot, "HydroSource", rows["h2_source"]["name"], "FLOW") == pytest.approx(0.4)
    assert _measurement(snapshot, "HydroLoad", rows["h2_load"]["name"], "FLOW") == pytest.approx(3.0)
    assert {result.status for result in snapshot.coupling_results} == {"balanced"}


@pytest.mark.parametrize(
    (
        "coupling_block",
        "electrolyzer_mode",
        "fuel_cell_mode",
        "set_type",
        "set_value",
        "initial_value",
    ),
    (
        ("AcE2Hydro", "P", "P", "p_set", 4.0, 2.0),
        ("AcE2Hydro", "FLOW", "P", "flow_set", 0.8, 0.4),
        ("Hydro2DcE", "P", "P", "p_set", 3.6, 5.4),
        ("Hydro2DcE", "P", "FLOW", "flow_set", 2.0, 3.0),
    ),
)
def test_trainee_endpoint_binding_dispatches_into_live_conversion_calculation(
    tmp_path,
    coupling_block,
    electrolyzer_mode,
    fuel_cell_mode,
    set_type,
    set_value,
    initial_value,
):
    model_path = _write_conversion_model(
        tmp_path,
        electrolyzer_mode=electrolyzer_mode,
        fuel_cell_mode=fuel_cell_mode,
    )
    artifacts = server_module._generated_model_artifacts(model_path.read_text(encoding="utf-8"))
    source_dir = tmp_path / "source"
    server_module._write_generated_model_artifacts(source_dir, artifacts)
    with tempfile.TemporaryDirectory(dir=ROOT) as runtime_dir:
        service = PolarMicrogridSimulator(
            source_dir,
            Path(runtime_dir),
            model_id="hydrogen-conversion-test",
        )
        converter = next(
            device
            for device in service.devices()
            if device["dev_type"] == coupling_block
        )
        binding = next(
            item
            for item in converter["control_bindings"]
            if item["set_type"] == set_type
        )

        accepted = service.apply_student_commands(
            {
                "set_values": [
                    {
                        "dev_type": binding["target_dev_type"],
                        "dev_name": binding["target_dev_name"],
                        "set_type": binding["target_set_type"],
                        "set_value": set_value,
                    }
                ]
            },
            source="trainee-ui",
        )
        snapshot = service.step(advance_seconds=1.0)

    assert accepted == {"run_status": 0, "set_values": 1, "ignored": 0}
    real_values = {
        (row["dev_type"], row["dev_name"], row["meas_type"]): float(row["value"])
        for row in snapshot["measurements"]["real"]
    }
    flow = real_values[(coupling_block, converter["dev_name"], "FLOW")]
    power = real_values[(coupling_block, converter["dev_name"], "P")]
    active_value = power if set_type == "p_set" else flow
    assert min(initial_value, set_value) < active_value < max(initial_value, set_value)
    if coupling_block == "AcE2Hydro":
        assert flow == pytest.approx(power * 0.2)
    else:
        assert power == pytest.approx(flow * 1.8)


@pytest.mark.parametrize(
    (
        "coupling_block",
        "coupling_name",
        "electrolyzer_mode",
        "fuel_cell_mode",
        "endpoint_block",
        "endpoint_name",
        "set_type",
        "set_value",
        "expected_power",
        "expected_flow",
    ),
    (
        (
            "AcE2Hydro",
            "ac_electrolyzer",
            "P",
            "P",
            "ACLoad",
            "electrolyzer_ac_load",
            "p_set",
            4.0,
            4.0,
            0.8,
        ),
        (
            "AcE2Hydro",
            "ac_electrolyzer",
            "FLOW",
            "P",
            "HydroSource",
            "electrolyzer_h2_source",
            "flow_set",
            0.8,
            4.0,
            0.8,
        ),
        (
            "Hydro2DcE",
            "dc_fuel_cell",
            "P",
            "P",
            "DCGenerator",
            "fuel_cell_dc_source",
            "p_set",
            3.6,
            3.6,
            2.0,
        ),
        (
            "Hydro2DcE",
            "dc_fuel_cell",
            "P",
            "FLOW",
            "HydroLoad",
            "fuel_cell_h2_load",
            "flow_set",
            2.0,
            3.6,
            2.0,
        ),
    ),
)
def test_simulator_svg_endpoint_edit_applies_the_mode_selected_setpoint_to_next_step(
    tmp_path,
    coupling_block,
    coupling_name,
    electrolyzer_mode,
    fuel_cell_mode,
    endpoint_block,
    endpoint_name,
    set_type,
    set_value,
    expected_power,
    expected_flow,
):
    model_path = _write_conversion_model(
        tmp_path,
        electrolyzer_mode=electrolyzer_mode,
        fuel_cell_mode=fuel_cell_mode,
    )
    artifacts = server_module._generated_model_artifacts(
        model_path.read_text(encoding="utf-8")
    )
    source_dir = tmp_path / "source"
    server_module._write_generated_model_artifacts(source_dir, artifacts)
    runtime_dir = tmp_path / "runtime"
    service = PolarMicrogridSimulator(
        source_dir,
        runtime_dir,
        model_id="hydrogen-svg-edit-test",
    )

    result = service.update_device_parameters(
        {
            "block_name": endpoint_block,
            "row_key": {"name": endpoint_name},
            "revision": service.definition_snapshot.revision,
            "changes": {set_type: set_value},
        }
    )
    snapshot = service.step(advance_seconds=1.0)

    assert result["runtime_control"]["set_values"][set_type] == pytest.approx(
        set_value
    )
    real_values = {
        (row["dev_type"], row["dev_name"], row["meas_type"]): float(row["value"])
        for row in snapshot["measurements"]["real"]
    }
    assert real_values[(coupling_block, coupling_name, "P")] == pytest.approx(
        expected_power
    )
    assert real_values[(coupling_block, coupling_name, "FLOW")] == pytest.approx(
        expected_flow
    )


@pytest.mark.parametrize(
    ("electrolyzer_power", "expected_flow"),
    (
        (4.0, 2.2),
        (20.0, -1.0),
    ),
)
def test_coupled_hydrogen_flow_updates_all_tank_runtime_states(
    tmp_path,
    electrolyzer_power,
    expected_flow,
):
    model_path = _write_storage_coupled_model(tmp_path)
    artifacts = server_module._generated_model_artifacts(
        model_path.read_text(encoding="utf-8")
    )
    source_dir = tmp_path / "source"
    server_module._write_generated_model_artifacts(source_dir, artifacts)
    service = PolarMicrogridSimulator(
        source_dir,
        tmp_path / "runtime",
        model_id="hydrogen-storage-coupling-test",
    )

    service.update_device_parameters(
        {
            "block_name": "ACLoad",
            "row_key": {"name": "electrolyzer_ac_load"},
            "revision": service.definition_snapshot.revision,
            "changes": {"p_set": electrolyzer_power},
        }
    )
    snapshot = service.step(advance_seconds=3600.0)

    storage_values = {
        row["meas_type"]: float(row["value"])
        for row in snapshot["measurements"]["real"]
        if row["dev_type"] == "HydroStorage" and row["dev_name"] == "tank-1"
    }
    expected_press = 35.0 - expected_flow / 50.0 * 0.1
    expected_quantity = 17500.0 - expected_flow

    assert storage_values["FLOW"] == pytest.approx(expected_flow)
    assert storage_values["PRESS"] == pytest.approx(expected_press)
    assert storage_values["GAS_QUANTITY"] == pytest.approx(expected_quantity)
    assert storage_values["SOC"] == pytest.approx(expected_press / 45.0)
    direction = -1.0 if expected_flow > 0.0 else 1.0
    assert (storage_values["PRESS"] - 35.0) * direction > 0.0
    assert (storage_values["GAS_QUANTITY"] - 17500.0) * direction > 0.0
    assert (storage_values["SOC"] - 35.0 / 45.0) * direction > 0.0


@pytest.mark.parametrize("role", ("simulator", "trainee"))
def test_hydrogen_conversion_parameter_labels_and_modes_are_explicit(role):
    script = (ROOT / "simu" / "web" / role / "app.js").read_text(encoding="utf-8")

    assert 'e2h_coeff: "电-气效率 (Nm3/kWh)"' in script
    assert 'h2e_coeff: "气-电效率 (kWh/Nm3)"' in script
    assert 'P: "定电功率 (P)"' in script
    assert 'FLOW: "定气流量 (FLOW)"' in script
    assert "diagramDefinitionFieldLabel(field)" in script
    assert "diagramDefinitionControlModeOptions(record, field)" in script
    assert "data-diagram-definition-control-mode" in script
    assert "currentModeValid" in script
    assert "无效模式" in script


def test_trainee_coupling_command_dialog_only_uses_the_active_mode_binding():
    script = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

    function_body = script.split("function diagramDeviceAdjustmentRows", 1)[1].split(
        "function closeDiagramDeviceCommandDialog",
        1,
    )[0]
    assert "binding?.active" in function_body
    assert "couplingControlSetType" in function_body
