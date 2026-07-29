import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRenewableLoopModeUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_renewable_panel_has_open_closed_loop_switch(self):
        self.assertIn('id="renewableLoopMode"', self.html)
        self.assertIn('data-renewable-loop-mode="open"', self.html)
        self.assertIn('data-renewable-loop-mode="closed"', self.html)
        self.assertIn('aria-pressed="true">开环</button>', self.html)
        self.assertIn('aria-pressed="false">闭环</button>', self.html)
        self.assertIn('id="renewableLastActionLabel"', self.html)
        self.assertIn('id="renewableSendOnce" type="button">单次计算</button>', self.html)
        self.assertIn('.renewable-loop-mode', self.styles)

    def test_renewable_control_defaults_to_open_loop_and_binds_switch(self):
        self.assertIn('loopMode: "open"', self.script)
        self.assertIn('function setRenewableLoopMode(mode)', self.script)
        self.assertIn('document.querySelectorAll("[data-renewable-loop-mode]")', self.script)
        self.assertIn('setRenewableLoopMode(button.dataset.renewableLoopMode)', self.script)

    def test_open_loop_calculates_and_logs_without_calling_command_api(self):
        block = self.script.split("async function sendRenewableControlPlan", 1)[1].split(
            "function maybeRunRenewableControl",
            1,
        )[0]
        self.assertIn('if (loopMode === "open") {', block)
        self.assertIn("control.lastCalculatedAt", block)
        open_loop = block.split('if (loopMode === "open") {', 1)[1].split("\n  }", 1)[0]
        self.assertIn("control.lastClockKey = plan.clockKey", open_loop)
        self.assertIn('"开环未下发"', open_loop)
        self.assertIn("return;", open_loop)
        self.assertNotIn("teacherCommandApi", open_loop)

    def test_closed_loop_sends_calculated_values_as_remote_adjustments(self):
        block = self.script.split("async function sendRenewableControlPlan", 1)[1].split(
            "function maybeRunRenewableControl",
            1,
        )[0]
        self.assertIn("set_values: plan.commands", block)
        self.assertIn("teacherCommandApi", block)
        self.assertIn("遥调指令", block)
        self.assertIn("loop_mode: loopMode", block)

    def test_rendering_distinguishes_calculation_from_dispatch(self):
        block = self.script.split("function renderRenewableControl", 1)[1].split(
            "function stopRenewableControl",
            1,
        )[0]
        self.assertIn('sendOnce.textContent = loopMode === "closed" ? "单次计算下发" : "单次计算"', block)
        self.assertIn('lastActionLabel.textContent = loopMode === "closed" ? "最近下发" : "最近计算"', block)
        self.assertIn('modeButton.classList.toggle("is-active", active)', block)
        self.assertIn('modeButton.setAttribute("aria-pressed", String(active))', block)

    def test_realtime_control_period_can_be_as_short_as_one_second(self):
        self.assertIn('<option value="1">1秒</option>', self.html)
        settings_block = self.script.split("function updateRenewableSettings", 1)[1].split(
            "function renderClock",
            1,
        )[0]
        self.assertIn("Math.max(1", settings_block)

    def test_missing_wind_speed_stays_unknown_instead_of_using_a_default(self):
        weather_block = self.script.split("function currentWeatherLoad", 1)[1].split(
            "function latestRuntimeLog",
            1,
        )[0]
        wind_block = self.script.split("function windAvailablePower", 1)[1].split(
            "function pvAvailablePower",
            1,
        )[0]

        self.assertIn("optionalNumber", weather_block)
        self.assertIn("windSpeedKnown", weather_block)
        self.assertNotIn("wind_speed_mps ?? 0", weather_block)
        self.assertIn("if (!Number.isFinite(weather.windSpeed)) return null", wind_block)
        self.assertIn("风速未知", self.script)

    def test_unknown_environment_uses_gradual_recovery_instead_of_disabling_commands(self):
        self.assertIn('src="/renewable_recovery.js"', self.html)
        renewable_rows = self.script.split("function renewableDeviceRows", 1)[1].split(
            "function storageDeviceRows",
            1,
        )[0]
        plan_block = self.script.split("function calculateRenewableControlPlan", 1)[1].split(
            "function renewableDecisionDetail",
            1,
        )[0]

        self.assertIn("currentKw", renewable_rows)
        self.assertIn("capacityKw", renewable_rows)
        self.assertIn("environmentKnown", renewable_rows)
        self.assertIn("RenewableRecovery.planRecovery", plan_block)
        self.assertIn("largeStepThresholdKw", plan_block)
        self.assertIn("stepCoefficient", plan_block)
        self.assertIn("recoveryResult?.setpointKw", plan_block)
        self.assertNotIn("row.currentKw + recoveryKw", plan_block)

    def test_unknown_environment_command_uses_capacity_clamped_recovery_setpoint(self):
        plan_block = self.script.split("function calculateRenewableControlPlan", 1)[1].split(
            "function renewableDecisionDetail",
            1,
        )[0]

        self.assertIn("const recoveryResult = recoveryByDevice.get(key)", plan_block)
        self.assertIn("recoveryResult?.setpointKw", plan_block)
        self.assertIn("recoveryResult?.recoveryKw", plan_block)
        self.assertNotIn("row.currentKw + recoveryKw", plan_block)

    def test_recovery_uses_live_measurements_not_definition_defaults(self):
        block = self.script.split("function renewablePowerMeasurements", 1)[1].split(
            "function preferredControlSetType",
            1,
        )[0]

        self.assertIn("snapshot.measurements", block)
        self.assertIn("measurements.scada", block)
        self.assertIn("measurements.real", block)
        self.assertNotIn("measurementDisplayRows(snapshot)", block)

    def test_strategy_uses_embedded_model_parameter_blocks_and_index_links(self):
        renewable_rows = self.script.split("function renewableDeviceRows", 1)[1].split(
            "function storageDeviceRows",
            1,
        )[0]
        storage_rows = self.script.split("function storageDeviceRows", 1)[1].split(
            "function allocateByCapacity",
            1,
        )[0]

        self.assertIn('parameterRows(snapshot, "ACWindGen")', renewable_rows)
        self.assertIn('indexedDevice(snapshot, "ACGenerator", param.idx_acgenerator)', renewable_rows)
        self.assertIn('parameterRows(snapshot, "DCPVGen")', renewable_rows)
        self.assertIn('indexedDevice(snapshot, "DCGenerator", param.idx_dcgenerator)', renewable_rows)
        self.assertIn('parameterRows(snapshot, "DCStorageGen")', storage_rows)
        self.assertIn('indexedDevice(snapshot, "DCGenerator", param.idx_dcgenerator)', storage_rows)

    def test_storage_target_is_converted_to_parallel_acdc_converter_commands(self):
        converter_block = self.script.split("function gridParallelConverterRows", 1)[1].split(
            "function renewableClockKey",
            1,
        )[0]
        plan_block = self.script.split("function calculateRenewableControlPlan", 1)[1].split(
            "function renewableDecisionDetail",
            1,
        )[0]

        self.assertIn('deviceType(dev) === "DCACConverter"', converter_block)
        self.assertIn('preferredControlSetType(snapshot, dev, ["p_ac_set", "p_set"])', converter_block)
        self.assertIn("POWER_CONTROL_MODES", converter_block)
        self.assertIn("commandKw: -converterAllocations[index]", plan_block)
        self.assertIn("commandable: false", plan_block)
        self.assertIn("row.commandable !== false", plan_block)
        self.assertNotIn('dev_type: "ESS"', plan_block)


if __name__ == "__main__":
    unittest.main()
