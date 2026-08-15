import pytest

from simu.fuel_cell_control import (
    FuelCellControlInputs,
    FuelCellControlParameters,
    calculate_fuel_cell_power_decision,
)


def _parameters(**changes):
    values = {
        "power_step_kw": 6.0,
        "diesel_power_limit_ratio": 0.5,
        "diesel_power_stop_minimum_ratio": 0.3,
        "electric_storage_soc_limit": 0.4,
        "hydrogen_storage_soc_start_limit": 0.8,
        "hydrogen_storage_soc_stop_limit": 0.2,
    }
    values.update(changes)
    return FuelCellControlParameters(**values)


def _inputs(**changes):
    values = {
        "current_power_kw": 0.0,
        "maximum_power_kw": 20.0,
        "minimum_power_kw": 5.0,
        "start_threshold_kw": 11.0,
        "stop_threshold_kw": 0.0,
        "diesel_power_kw": 212.0,
        "diesel_capacity_kw": 400.0,
        "electric_storage_soc_average": 0.39,
        "hydrogen_storage_soc_average": 0.81,
    }
    values.update(changes)
    return FuelCellControlInputs(**values)


def test_stopped_fuel_cell_starts_directly_at_minimum_plus_step():
    decision = calculate_fuel_cell_power_decision(_parameters(), _inputs())

    assert decision.action == "start"
    assert decision.requested_delta_kw == 11.0
    assert decision.required_start_delta_kw == 11.0
    assert decision.diesel_raise_margin_kw == 12.0


def test_stopped_fuel_cell_ignores_ramp_limit_and_jumps_to_minimum_plus_step():
    decision = calculate_fuel_cell_power_decision(
        _parameters(power_step_kw=2.0),
        _inputs(start_threshold_kw=7.0, stop_threshold_kw=3.0),
    )

    assert decision.action == "start"
    assert decision.requested_delta_kw == 7.0
    assert decision.required_start_delta_kw == 7.0


def test_subthreshold_residual_starts_at_minimum_plus_step():
    decision = calculate_fuel_cell_power_decision(
        _parameters(power_step_kw=1.0),
        _inputs(
            current_power_kw=0.01,
            minimum_power_kw=3.0,
            start_threshold_kw=4.0,
            stop_threshold_kw=2.0,
        ),
    )

    assert decision.action == "start"
    assert decision.requested_delta_kw == pytest.approx(3.99)
    assert decision.required_start_delta_kw == pytest.approx(3.99)


@pytest.mark.parametrize(
    "changes",
    (
        {"diesel_power_kw": 200.0},
        {"electric_storage_soc_average": 0.4},
        {"hydrogen_storage_soc_average": 0.8},
    ),
)
def test_start_requires_all_average_thresholds_strictly(changes):
    decision = calculate_fuel_cell_power_decision(
        _parameters(),
        _inputs(**changes),
    )

    assert decision.action == "hold"
    assert decision.reason == "start_conditions_not_met"


def test_start_is_blocked_when_diesel_total_margin_cannot_reach_minimum_plus_step():
    decision = calculate_fuel_cell_power_decision(
        _parameters(),
        _inputs(diesel_power_kw=204.0),
    )

    assert decision.action == "hold"
    assert decision.reason == "start_margin_insufficient"
    assert decision.diesel_raise_margin_kw == 4.0


def test_running_fuel_cell_uses_lower_hydrogen_soc_limit_to_increase():
    decision = calculate_fuel_cell_power_decision(
        _parameters(),
        _inputs(
            current_power_kw=8.0,
            hydrogen_storage_soc_average=0.3,
        ),
    )

    assert decision.action == "increase"
    assert decision.requested_delta_kw == 6.0
    assert decision.reason == "raise_conditions_met"


def test_increase_is_limited_by_total_diesel_margin():
    decision = calculate_fuel_cell_power_decision(
        _parameters(),
        _inputs(
            current_power_kw=8.0,
            diesel_power_kw=202.0,
            hydrogen_storage_soc_average=0.3,
        ),
    )

    assert decision.action == "increase"
    assert decision.requested_delta_kw == 2.0


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        ({"diesel_power_kw": 118.0}, "diesel_power_reduce"),
        ({"electric_storage_soc_average": 0.41}, "storage_soc_reduce"),
        ({"hydrogen_storage_soc_average": 0.19}, "storage_soc_reduce"),
    ),
)
def test_running_fuel_cell_reduces_one_step_on_any_reverse_condition(
    changes,
    reason,
):
    decision = calculate_fuel_cell_power_decision(
        _parameters(),
        _inputs(current_power_kw=10.0, **changes),
    )

    assert decision.action == "decrease"
    assert decision.requested_delta_kw == -6.0
    assert decision.reason == reason


def test_running_fuel_cell_holds_between_start_and_stop_diesel_thresholds():
    decision = calculate_fuel_cell_power_decision(
        _parameters(),
        _inputs(
            current_power_kw=10.0,
            diesel_power_kw=160.0,
            electric_storage_soc_average=0.39,
            hydrogen_storage_soc_average=0.3,
        ),
    )

    assert decision.action == "hold"
    assert decision.requested_delta_kw == 0.0
    assert decision.reason == "hold_region"


def test_reduction_stops_instead_of_entering_minimum_power_dead_zone():
    decision = calculate_fuel_cell_power_decision(
        _parameters(power_step_kw=3.0),
        _inputs(
            current_power_kw=4.0,
            start_threshold_kw=8.0,
            stop_threshold_kw=2.0,
            diesel_power_kw=118.0,
        ),
    )

    assert decision.action == "stop"
    assert decision.requested_delta_kw == -4.0


@pytest.mark.parametrize(
    "changes",
    (
        {"electric_storage_soc_average": None},
        {"hydrogen_storage_soc_average": None},
        {"electric_storage_soc_average": float("nan")},
    ),
)
def test_incomplete_average_inputs_fail_closed_to_hold(changes):
    decision = calculate_fuel_cell_power_decision(
        _parameters(),
        _inputs(current_power_kw=8.0, **changes),
    )

    assert decision.action == "hold"
    assert decision.reason == "incomplete_average_input"


def test_equal_running_thresholds_are_a_hold_region():
    decision = calculate_fuel_cell_power_decision(
        _parameters(),
        _inputs(
            current_power_kw=8.0,
            diesel_power_kw=200.0,
            electric_storage_soc_average=0.4,
            hydrogen_storage_soc_average=0.2,
        ),
    )

    assert decision.action == "hold"
    assert decision.requested_delta_kw == 0.0
