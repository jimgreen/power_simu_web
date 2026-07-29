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

    def test_backend_owns_environment_recovery_and_converter_dispatch(self):
        self.assertIn("def _plan_recovery", self.backend)
        self.assertIn('"equal-margin"', self.backend)
        self.assertIn('"capacity-step"', self.backend)
        self.assertIn("风速未知", self.backend)
        self.assertIn("太阳辐照度未知", self.backend)
        self.assertIn("converter_current_for_control - (storage_target - storage_current_for_control)", self.backend)
        self.assertIn('"commandKw": converter_allocations[index]', self.backend)
        self.assertIn('"commandable": False', self.backend)

    def test_decision_log_explicitly_excludes_load_from_control_targets(self):
        self.assertIn("负荷功率仅用于展示", self.backend)
        self.assertIn("renewable_balance_limit", self.backend)
        self.assertIn("diesel_down_margin", self.backend)
        self.assertNotIn("负荷 + 储能可充", self.backend)


if __name__ == "__main__":
    unittest.main()
