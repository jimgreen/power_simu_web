import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRenewableLoopModeUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.backend = (ROOT / "simu/renewable_control.py").read_text(encoding="utf-8")
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

    def test_browser_uses_shared_backend_controller_api(self):
        self.assertIn('loopMode: "open"', self.script)
        self.assertIn('"/api/trainee/renewable-control"', self.script)
        self.assertIn("function applyRenewableControlState", self.script)
        self.assertIn("async function refreshRenewableControlState", self.script)
        self.assertIn("async function runRenewableControlAction", self.script)
        self.assertIn('runRenewableControlAction("set_loop_mode", { loop_mode: nextMode })', self.script)
        self.assertIn('runRenewableControlAction("run_once")', self.script)

    def test_background_control_cycle_does_not_lock_foreground_actions(self):
        render_block = self.script.split("function renderRenewableControl", 1)[1].split(
            "async function toggleRenewableAuto",
            1,
        )[0]

        self.assertIn("function renewableForegroundActionPending", self.script)
        self.assertIn(
            "const actionPending = renewableForegroundActionPending(control);",
            render_block,
        )
        self.assertIn(
            "button.disabled = actionPending || (!receiveReady && !control.desiredEnabled);",
            render_block,
        )
        self.assertIn(
            "sendOnce.disabled = actionPending || !receiveReady;",
            render_block,
        )
        self.assertIn("modeButton.disabled = actionPending;", render_block)
        self.assertIn("status.textContent = actionPending", render_block)
        self.assertNotIn("control.sending || control.actionActive", render_block)

    def test_browser_does_not_calculate_or_schedule_the_control_strategy(self):
        self.assertNotIn("function calculateRenewableControlPlan", self.script)
        self.assertNotIn("function maybeRunRenewableControl", self.script)
        self.assertNotIn("sendRenewableControlPlan", self.script)
        self.assertNotIn("RenewableRecovery", self.script)
        self.assertNotIn('src="/renewable_recovery.js"', self.html)
        self.assertNotIn("trainee-renewable-priority\"", self.script)

    def test_backend_owns_open_loop_closed_loop_and_periodic_execution(self):
        self.assertIn("operation_epoch = state.operation_epoch", self.backend)
        self.assertIn("cycle_settings = state.settings", self.backend)
        self.assertIn("cycle_loop_mode = state.loop_mode", self.backend)
        self.assertIn('cycle_loop_mode == "closed"', self.backend)
        self.assertIn('cycle_loop_mode == "open"', self.backend)
        self.assertIn("state.operation_epoch == operation_epoch", self.backend)
        self.assertIn("settings=cycle_settings", self.backend)
        self.assertIn("loop_mode=cycle_loop_mode", self.backend)
        self.assertIn("cycle_idle = (", self.backend)
        self.assertIn("not state.sending", self.backend)
        self.assertIn("not state.background_cycle_pending", self.backend)
        self.assertIn("not state.run_lock.locked()", self.backend)
        self.assertIn("control_clock = self._simulation_control_clock(", self.backend)
        self.assertIn("control_due = self._simulation_control_due_locked(", self.backend)
        self.assertIn("collection_due =", self.backend)
        self.assertIn("_collection_interval_seconds_for_service", self.backend)
        self.assertIn("state.settings.interval_seconds", self.backend)
        self.assertIn('"开环未下发"', self.backend)
        self.assertIn('"下发成功"', self.backend)

    def test_control_period_uses_simulation_clock_seconds(self):
        self.assertIn('id="renewableControlPeriod" type="number"', self.html)
        self.assertIn("自动控制周期（仿真秒）", self.html)
        settings_block = self.script.split("async function updateRenewableSettings", 1)[1].split(
            "function renderClock",
            1,
        )[0]
        self.assertIn("renewableSimulationControlIntervalError", settings_block)
        self.assertIn("simulationIntervalSeconds", settings_block)
        self.assertNotIn("collectionIntervalSeconds", settings_block)
        self.assertIn(
            'MINIMUM_CONTROL_INTERVAL_SECONDS = default_number(',
            self.backend,
        )
        self.assertIn('"minimum_simulation_control_interval_seconds"', self.backend)
        self.assertIn('default_number("simulation_control_interval_seconds")', self.backend)
        self.assertIn("def _simulation_control_interval_seconds(", self.backend)
        self.assertIn("仿真秒", self.backend)
        self.assertNotIn("def _control_interval_multiple(", self.backend)

    def test_automatic_command_validity_is_editable_and_persisted(self):
        self.assertIn('id="renewableCommandValidMinutes"', self.html)
        self.assertIn('value="120"', self.html)
        self.assertIn("commandValidMinutes", self.script)
        settings_block = self.script.split("async function updateRenewableSettings", 1)[1].split(
            "function storagePowerDeratingRowHtml",
            1,
        )[0]
        self.assertIn("commandValidMinutes", settings_block)
        self.assertIn("command_valid_minutes", self.backend)
        self.assertIn('"valid_for_minutes": cycle_settings.command_valid_minutes', self.backend)

    def test_control_parameters_require_explicit_save_confirmation(self):
        dialog = self.html.split('id="renewableControlParametersDialog"', 1)[1].split(
            '</dialog>',
            1,
        )[0]
        event_bindings = self.script.split(
            '$("renewableControlParametersButton")?.addEventListener',
            1,
        )[1].split(
            'document.querySelectorAll("[data-renewable-strategy-tab]")',
            1,
        )[0]

        self.assertIn('id="saveRenewableControlParameters"', dialog)
        self.assertIn('class="primary" type="button">保存</button>', dialog)
        self.assertIn('修改后点击保存', dialog)
        self.assertIn("async function saveRenewableControlParameters", self.script)
        self.assertIn(
            '$("saveRenewableControlParameters")?.addEventListener("click", saveRenewableControlParameters);',
            event_bindings,
        )
        self.assertNotIn('addEventListener("change", updateRenewableSettings)', event_bindings)

    def test_strategy_steps_and_power_protection_bands_are_editable_ratios(self):
        self.assertIn("新能源步长(%/次决策)", self.html)
        self.assertIn("跟网储能步长(%/次决策)", self.html)
        self.assertIn("SOC越界步长倍率(%)", self.html)
        self.assertNotIn("renewableStepRatePerMinute", self.script)
        self.assertNotIn("storageStepRatePerMinute", self.script)
        for field_id in (
            "renewableStepRatio",
            "storageStepRatio",
            "storageSocCorrectionStepScale",
            "gridFormingStorageProtectionRatio",
            "dieselPowerProtectionRatio",
            "socDeadband",
        ):
            self.assertIn(f'id="{field_id}"', self.html)
            self.assertIn(field_id, self.script)
        for setting_name in (
            "storage_step_ratio",
            "storage_soc_correction_step_scale",
            "grid_forming_storage_protection_ratio",
            "diesel_power_protection_ratio",
            "soc_deadband",
        ):
            self.assertIn(setting_name, self.backend)
        self.assertIn(
            "settings.diesel_power_protection_ratio * diesel_capacity",
            self.backend,
        )
        for removed in (
            "converterStepRatio",
            "optimizationConverterAdjustmentSquareWeight",
            "renewableNearZeroRatio",
            "renewableChargeReserveRatio",
            "renewable_near_zero_ratio",
            "renewable_charge_reserve_ratio",
            "新能源近零",
            "充电保留量",
        ):
            self.assertNotIn(removed, self.html)
            self.assertNotIn(removed, self.script)
        for legacy_migration_field in (
            "storageSwitchDeadbandKw",
            "dieselDeadbandRatio",
        ):
            self.assertNotIn(legacy_migration_field, self.html)
            self.assertIn(legacy_migration_field, self.script)

    def test_hydrogen_has_an_independent_closed_loop_switch(self):
        self.assertRegex(
            self.html,
            r'id="hydrogenClosedLoopEnabled"[^>]*checked',
        )
        self.assertIn("hydrogenClosedLoopEnabled: true", self.script)
        self.assertIn("hydrogenClosedLoopEnabled", self.script)
        self.assertIn('id="hydrogenPressureDeadbandRatio"', self.html)
        for field_id in (
            "electrolyzerPowerMinRatio",
            "electrolyzerPowerMaxRatio",
            "electrolyzerPowerDeadbandRatio",
            "electrolyzerPowerStepRatio",
            "fuelCellPowerMinRatio",
            "fuelCellPowerMaxRatio",
            "fuelCellPowerDeadbandRatio",
            "fuelCellPowerStepRatio",
            "electrolyzerDieselPowerLimitRatio",
            "electrolyzerDieselPowerDeadbandRatio",
            "electrolyzerDieselPowerStopMaximumRatio",
            "electrolyzerStorageSocStartMinimum",
            "electrolyzerStorageSocStopMaximum",
            "electrolyzerHydrogenStorageSocStopMinimum",
            "fuelCellDieselPowerLimitRatio",
            "fuelCellDieselPowerStopMinimumRatio",
            "fuelCellStorageSocLimit",
            "fuelCellHydrogenStorageSocUpperLimit",
            "fuelCellHydrogenStorageSocLowerLimit",
        ):
            self.assertIn(f'id="{field_id}"', self.html)
            self.assertIn(field_id, self.script)
        settings_block = self.script.split("async function updateRenewableSettings", 1)[1].split(
            "function storagePowerDeratingRowHtml",
            1,
        )[0]
        self.assertIn("hydrogenClosedLoopEnabled", settings_block)
        self.assertIn("启动功率（下限+死区）不能大于上限", settings_block)
        self.assertNotIn("电制氢电储SOC下限不能大于上限", settings_block)
        self.assertIn("电制氢启机SOC最小值必须大于停机SOC最大值", settings_block)
        self.assertIn("电制氢启机柴发门槛必须小于停机柴发门槛", settings_block)
        self.assertIn("燃料电池启机柴发门槛必须大于停机柴发门槛", settings_block)
        self.assertIn(
            "燃料电池停机氢SOC最大值不能大于启机氢SOC最小值",
            settings_block,
        )
        self.assertIn("hydrogen_closed_loop_enabled", self.backend)
        self.assertIn("hydrogen_pressure_deadband_ratio", self.backend)
        self.assertIn("electrolyzer_diesel_power_limit_ratio", self.backend)
        self.assertIn("electrolyzer_diesel_power_deadband_ratio", self.backend)
        self.assertIn("electrolyzer_diesel_power_stop_maximum_ratio", self.backend)
        self.assertIn("electrolyzer_storage_soc_start_minimum", self.backend)
        self.assertIn("electrolyzer_storage_soc_stop_maximum", self.backend)
        self.assertIn("electrolyzer_hydrogen_storage_soc_stop_minimum", self.backend)
        self.assertIn("fuel_cell_diesel_power_limit_ratio", self.backend)
        self.assertIn("fuel_cell_diesel_power_stop_minimum_ratio", self.backend)
        self.assertIn("fuel_cell_storage_soc_limit", self.backend)
        self.assertIn("fuel_cell_hydrogen_storage_soc_upper_limit", self.backend)
        self.assertIn("fuel_cell_hydrogen_storage_soc_lower_limit", self.backend)

    def test_electrolyzer_recommended_defaults_are_rendered_as_percentages(self):
        expected_percentages = {
            "electrolyzerPowerMinRatio": "20",
            "electrolyzerPowerMaxRatio": "90",
            "electrolyzerPowerDeadbandRatio": "10",
            "electrolyzerPowerStepRatio": "10",
            "electrolyzerDieselPowerLimitRatio": "35",
            "electrolyzerDieselPowerDeadbandRatio": "5",
            "electrolyzerDieselPowerStopMaximumRatio": "50",
            "electrolyzerStorageSocStartMinimum": "70",
            "electrolyzerStorageSocStopMaximum": "30",
            "electrolyzerHydrogenStorageSocStopMinimum": "90",
        }
        for field_id, percentage in expected_percentages.items():
            self.assertRegex(
                self.html,
                rf'id="{field_id}"[^>]*value="{percentage}"',
            )

        for fallback in (
            'electrolyzerPowerMinRatio: ratio("electrolyzerPowerMinRatio", 20)',
            'electrolyzerPowerMaxRatio: ratio("electrolyzerPowerMaxRatio", 90)',
            'electrolyzerPowerDeadbandRatio: ratio("electrolyzerPowerDeadbandRatio", 10)',
            'electrolyzerPowerStepRatio: ratio("electrolyzerPowerStepRatio", 10, 0.001, 100)',
            'electrolyzerDieselPowerLimitRatio: ratio("electrolyzerDieselPowerLimitRatio", 35)',
            'electrolyzerDieselPowerStopMaximumRatio: ratio("electrolyzerDieselPowerStopMaximumRatio", 50)',
        ):
            self.assertIn(fallback, self.script)

    def test_fuel_cell_recommended_defaults_and_labels_are_rendered(self):
        expected_percentages = {
            "fuelCellPowerMinRatio": "20",
            "fuelCellPowerMaxRatio": "90",
            "fuelCellPowerDeadbandRatio": "10",
            "fuelCellPowerStepRatio": "10",
            "fuelCellDieselPowerLimitRatio": "50",
            "fuelCellDieselPowerStopMinimumRatio": "30",
            "fuelCellStorageSocLimit": "30",
            "fuelCellHydrogenStorageSocUpperLimit": "30",
            "fuelCellHydrogenStorageSocLowerLimit": "20",
        }
        for field_id, percentage in expected_percentages.items():
            self.assertRegex(
                self.html,
                rf'id="{field_id}"[^>]*value="{percentage}"',
            )

        for label in (
            "燃电出力下限(%)",
            "燃电出力上限(%)",
            "燃电出力死区(%)",
            "燃电出力步长(%)",
            "启机柴发出力最小值(%)",
            "停机柴发最小值(%)",
            "启机电SOC最大值(%)",
            "启机氢SOC最小值(%)",
            "停机氢SOC最大值(%)",
        ):
            self.assertIn(label, self.html)

        for fallback in (
            'fuelCellPowerMinRatio: ratio("fuelCellPowerMinRatio", 20)',
            'fuelCellPowerMaxRatio: ratio("fuelCellPowerMaxRatio", 90)',
            'fuelCellPowerDeadbandRatio: ratio("fuelCellPowerDeadbandRatio", 10)',
            'fuelCellPowerStepRatio: ratio("fuelCellPowerStepRatio", 10, 0.001, 100)',
            'fuelCellDieselPowerLimitRatio: ratio("fuelCellDieselPowerLimitRatio", 50)',
            'fuelCellDieselPowerStopMinimumRatio: ratio("fuelCellDieselPowerStopMinimumRatio", 30)',
            'fuelCellStorageSocLimit: ratio("fuelCellStorageSocLimit", 30)',
            'fuelCellHydrogenStorageSocUpperLimit", 30',
        ):
            self.assertIn(fallback, self.script)

        for initial_value in (
            "fuelCellPowerMinRatio: 0.20",
            "fuelCellPowerMaxRatio: 0.90",
            "fuelCellPowerDeadbandRatio: 0.10",
            "fuelCellPowerStepRatio: 0.10",
            "fuelCellDieselPowerLimitRatio: 0.50",
            "fuelCellDieselPowerStopMinimumRatio: 0.30",
            "fuelCellStorageSocLimit: 0.3",
            "fuelCellHydrogenStorageSocUpperLimit: 0.3",
            "fuelCellHydrogenStorageSocLowerLimit: 0.2",
        ):
            self.assertIn(initial_value, self.script)

    def test_strategy_table_marks_open_loop_and_hydrogen_preview_rows_as_not_dispatched(self):
        table_block = self.script.split(
            'table.innerHTML = `\n    <table class="runtime-device-table renewable-command-table">',
            1,
        )[1].split("async function toggleRenewableAuto", 1)[0]
        self.assertIn("row.dispatchEnabled === false", table_block)
        self.assertIn('control.loopMode === "closed"', table_block)
        self.assertIn('"仅预览"', table_block)
        self.assertIn('"开环不下发"', table_block)
        self.assertIn('"随策略下发"', table_block)
        self.assertIn(".renewable-row-ready.is-preview", self.styles)

    def test_backend_does_not_use_dwell_or_pending_feedback_state(self):
        self.assertNotIn("def _stabilize_region", self.backend)
        self.assertNotIn("def _feedback_status", self.backend)
        self.assertNotIn("control_state:", self.backend)
        self.assertNotIn("candidateSince", self.backend)
        self.assertNotIn("feedbackState", self.backend)

    def test_soc_operational_limits_come_from_model_and_are_not_editable_in_ui(self):
        self.assertNotIn('id="renewableSocMin"', self.html)
        self.assertNotIn('id="renewableSocMax"', self.html)
        protection_pane = self.html.split(
            'id="renewableControlParameterPaneProtection"', 1
        )[1].split('id="renewableControlParameterPaneHydrogen"', 1)[0]
        self.assertNotIn("SOC下限", protection_pane)
        self.assertNotIn("SOC上限", protection_pane)
        settings_block = self.script.split("async function updateRenewableSettings", 1)[1].split(
            "function renderClock",
            1,
        )[0]
        self.assertNotIn("socMin", settings_block)
        self.assertNotIn("socMax", settings_block)
        self.assertNotIn('$("renewableSocMin")', self.script)
        self.assertNotIn('$("renewableSocMax")', self.script)
        self.assertIn("defined_min if defined_min is not None else settings.soc_min", self.backend)
        self.assertIn("defined_max if defined_max is not None else settings.soc_max", self.backend)

    def test_backend_owns_environment_recovery_and_converter_dispatch(self):
        self.assertIn("def _plan_recovery", self.backend)
        self.assertIn('"equal-margin"', self.backend)
        self.assertIn('"capacity-step"', self.backend)
        self.assertIn("仅用于最大可发统计，不参与控制目标计算", self.backend)
        self.assertIn(
            "风电理论可发统计缺少有效风速或设备风速参数；不影响本轮控制优化",
            self.backend,
        )
        self.assertIn(
            "光伏理论可发统计缺少有效辐照度或设备参考参数；不影响本轮控制优化",
            self.backend,
        )
        self.assertNotIn("ignored_by_control_policy", self.backend)
        self.assertIn("raw_converter_desired_target = converter_current_for_control", self.backend)
        self.assertIn(
            "_move_toward(converter_current_for_control, converter_desired_target, converter_step_kw)",
            self.backend,
        )
        self.assertIn('"dieselEffectKw": diesel_effect_kw', self.backend)
        self.assertIn("def _plan_direct_grid_forming_dispatch(", self.backend)
        self.assertIn("def _validate_dispatch_by_ac_component(", self.backend)
        self.assertIn("component_dispatch_plan = _validate_dispatch_by_ac_component(", self.backend)
        self.assertIn('direct_grid_forming_plan.get("dieselEffectKw")', self.backend)
        self.assertIn('"acComponentDispatch": copy.deepcopy(', self.backend)
        self.assertIn("base_converter_effect_kw", self.backend)
        self.assertIn("direct_ac_storage_effect_kw", self.backend)
        self.assertIn("direct_acdc_effect_kw", self.backend)
        self.assertIn(
            'direct_grid_forming_plan["dieselEffectKw"] = component_dispatch_plan[',
            self.backend,
        )
        self.assertIn("candidate_effect = _finite_number(", self.backend)
        self.assertNotIn("candidate_effect = renewable_delta + storage_delta", self.backend)
        self.assertIn("renewable_storage_coordination_active = False", self.backend)
        self.assertIn('"commandKw": converter_allocations[index]', self.backend)
        self.assertIn("diagnostic_converter_rows = [", self.backend)
        self.assertIn('if not row.get("commandable")', self.backend)

    def test_decision_log_explicitly_excludes_load_from_control_targets(self):
        self.assertIn("负荷功率仅用于展示", self.backend)
        self.assertIn("renewable_balance_limit", self.backend)
        self.assertIn("diesel_down_margin", self.backend)
        self.assertNotIn("负荷 + 储能可充", self.backend)


if __name__ == "__main__":
    unittest.main()
