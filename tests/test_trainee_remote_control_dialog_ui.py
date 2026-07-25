import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TraineeRemoteControlDialogUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "simu/web/trainee/index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "simu/web/trainee/app.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "simu/web/trainee/styles.css").read_text(encoding="utf-8")

    def test_remote_control_dialog_is_available(self):
        self.assertIn('id="remoteControlDialog"', self.html)
        self.assertIn('id="remoteControlConfirm"', self.html)
        self.assertIn('name="remoteControlState"', self.html)

    def test_current_status_supports_double_click_remote_control(self):
        self.assertIn("data-run-status-command", self.script)
        self.assertIn('document.addEventListener("dblclick"', self.script)
        self.assertIn("openRemoteControlDialog", self.script)

    def test_confirm_sends_one_remote_control_command_immediately(self):
        self.assertIn("sendRemoteControlCommand", self.script)
        self.assertIn('source: "trainee-ui"', self.script)
        self.assertIn('run_status: [command]', self.script)

    def test_remote_control_table_shows_latest_command_time(self):
        self.assertIn("function remoteControlIssuedAt", self.script)
        self.assertIn("normalized?.run_status", self.script)
        self.assertIn("指令下发时刻", self.script)
        self.assertIn("command-issued-at-cell", self.script)
        self.assertIn(".command-issued-at-cell", self.styles)


if __name__ == "__main__":
    unittest.main()
