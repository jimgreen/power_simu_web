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

    def test_browser_does_not_calculate_or_schedule_the_control_strategy(self):
        self.assertNotIn("function calculateRenewableControlPlan", self.script)
        self.assertNotIn("function maybeRunRenewableControl", self.script)
        self.assertNotIn("sendRenewableControlPlan", self.script)
        self.assertNotIn("RenewableRecovery", self.script)
        self.assertNotIn('src="/renewable_recovery.js"', self.html)
        self.assertNotIn("trainee-renewable-priority\"", self.script)

    def test_backend_owns_open_loop_closed_loop_and_periodic_execution(self):
        self.assertIn('state.loop_mode == "closed"', self.backend)
        self.assertIn('state.loop_mode == "open"', self.backend)
        self.assertIn('state.enabled and not state.sending', self.backend)
        self.assertIn('state.settings.interval_seconds', self.backend)
        self.assertIn('"开环未下发"', self.backend)
        self.assertIn('"下发成功"', self.backend)

    def test_realtime_control_period_can_be_as_short_as_one_second(self):
        self.assertIn('<option value="1">1秒</option>', self.html)
        settings_block = self.script.split("async function updateRenewableSettings", 1)[1].split(
            "function renderClock",
            1,
        )[0]
        self.assertIn("Math.max(1", settings_block)
        self.assertIn("interval_seconds=max(1.0", self.backend)

    def test_strategy_steps_and_deadbands_are_editable_capacity_ratios(self):
        for field_id in (
            "renewableStepRatio",
            "converterStepRatio",
            "dieselDeadbandRatio",
            "socDeadband",
        ):
            self.assertIn(f'id="{field_id}"', self.html)
            self.assertIn(field_id, self.script)
        for setting_name in (
            "diesel_deadband_ratio",
            "soc_deadband",
            "converter_step_ratio",
        ):
            self.assertIn(setting_name, self.backend)
        self.assertIn("settings.converter_step_ratio * converter_limit", self.backend)
        self.assertIn("settings.diesel_deadband_ratio * diesel_capacity", self.backend)
        for removed in (
            "storageStepRatio",
            "storage_step_ratio",
            "储能步长",
            "renewableNearZeroRatio",
            "renewableChargeReserveRatio",
            "renewable_near_zero_ratio",
            "renewable_charge_reserve_ratio",
            "新能源近零",
            "充电保留量",
        ):
            self.assertNotIn(removed, self.html)
            self.assertNotIn(removed, self.script)
            self.assertNotIn(removed, self.backend)

    def test_backend_does_not_use_dwell_or_pending_feedback_state(self):
        self.assertNotIn("def _stabilize_region", self.backend)
        self.assertNotIn("def _feedback_status", self.backend)
        self.assertNotIn("control_state:", self.backend)
        self.assertNotIn("candidateSince", self.backend)
        self.assertNotIn("feedbackState", self.backend)

    def test_soc_operational_limits_come_from_model_and_are_not_editable_in_ui(self):
        self.assertNotIn('id="renewableSocMin"', self.html)
        self.assertNotIn('id="renewableSocMax"', self.html)
        self.assertNotIn("SOC下限", self.html)
        self.assertNotIn("SOC上限", self.html)
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
        self.assertIn("风速量测默认不参与新能源控制", self.backend)
        self.assertIn("太阳辐照度量测默认不参与新能源控制", self.backend)
        self.assertIn("ignored_by_control_policy", self.backend)
        self.assertIn("raw_converter_desired_target = converter_current_for_control", self.backend)
        self.assertIn(
            "_move_toward(converter_current_for_control, converter_desired_target, converter_step_kw)",
            self.backend,
        )
        self.assertIn("candidate_effect = storage_delta", self.backend)
        self.assertNotIn("candidate_effect = renewable_delta + storage_delta", self.backend)
        self.assertIn("renewable_storage_coordination_active = False", self.backend)
        self.assertIn('"commandKw": converter_allocations[index]', self.backend)
        self.assertIn('"commandable": False', self.backend)

    def test_decision_log_explicitly_excludes_load_from_control_targets(self):
        self.assertIn("负荷功率仅用于展示", self.backend)
        self.assertIn("renewable_balance_limit", self.backend)
        self.assertIn("diesel_down_margin", self.backend)
        self.assertNotIn("负荷 + 储能可充", self.backend)


if __name__ == "__main__":
    unittest.main()
