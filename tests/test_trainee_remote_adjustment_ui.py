import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRemoteAdjustmentUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")

    def test_each_remote_adjustment_is_rendered_as_one_row(self):
        self.assertIn("function remoteAdjustmentRows", self.script)
        self.assertIn("遥调名称", self.script)
        self.assertIn("量测值", self.script)
        self.assertIn("控制值", self.script)
        self.assertIn("指令下发时刻", self.script)

    def test_remote_adjustment_dialog_is_available(self):
        self.assertIn('id="remoteAdjustmentDialog"', self.html)
        self.assertIn('id="remoteAdjustmentValue"', self.html)
        self.assertIn('id="remoteAdjustmentConfirm"', self.html)

    def test_double_click_sends_one_adjustment_command(self):
        self.assertIn("data-remote-adjustment-key", self.script)
        self.assertIn("openRemoteAdjustmentDialog", self.script)
        self.assertIn("sendRemoteAdjustmentCommand", self.script)
        self.assertIn("set_values: [command]", self.script)

    def test_manual_commands_use_cycle_end_expiry_instead_of_short_strategy_ttl(self):
        self.assertIn("function manualCommandExpiresAtAbsoluteMinute", self.script)
        remote_control_block = self.script.split("async function sendRemoteControlCommand()", 1)[1].split("function findRemoteAdjustmentByKey", 1)[0]
        remote_adjustment_block = self.script.split("async function sendRemoteAdjustmentCommand()", 1)[1].split("function handleTreeClick", 1)[0]
        renewable_block = self.script.split("async function sendRenewableControlPlan", 1)[1].split("function maybeRunRenewableControl", 1)[0]

        self.assertIn("expires_at_absolute_minute: manualCommandExpiresAtAbsoluteMinute()", remote_control_block)
        self.assertIn("expires_at_absolute_minute: manualCommandExpiresAtAbsoluteMinute()", remote_adjustment_block)
        self.assertNotIn("valid_for_minutes: CONTROL_COMMAND_VALID_MINUTES", remote_control_block)
        self.assertNotIn("valid_for_minutes: CONTROL_COMMAND_VALID_MINUTES", remote_adjustment_block)
        self.assertIn("valid_for_minutes: RENEWABLE_COMMAND_VALID_MINUTES", renewable_block)


if __name__ == "__main__":
    unittest.main()
