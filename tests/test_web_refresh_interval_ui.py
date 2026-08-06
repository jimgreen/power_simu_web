from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WebRefreshIntervalUiTest(unittest.TestCase):
    def test_simulator_and_trainee_use_restartable_model_scoped_refresh_schedulers(self):
        simulator_js = (ROOT / "simu" / "web" / "simulator" / "app.js").read_text(encoding="utf-8")
        trainee_js = (ROOT / "simu" / "web" / "trainee" / "app.js").read_text(encoding="utf-8")

        for script in (simulator_js, trainee_js):
            self.assertIn("function frontendRefreshIntervalMs", script)
            self.assertIn("function restartRefreshScheduler", script)
            self.assertIn("async function runRefreshScheduler", script)
            self.assertNotIn("setInterval(refresh, 1000);", script)
        self.assertIn("setTimeout(runRefreshScheduler, frontendRefreshIntervalMs())", simulator_js)
        self.assertIn(
            "function scheduleNextRefresh(delayMs = frontendRefreshIntervalMs())",
            trainee_js,
        )
        self.assertIn(
            "setTimeout(runRefreshScheduler, Math.max(0, delayMs))",
            trainee_js,
        )
        self.assertIn("const startedAtMs = Date.now();", trainee_js)
        self.assertIn("const elapsedMs = Date.now() - startedAtMs;", trainee_js)
        self.assertIn(
            "scheduleNextRefresh(Math.max(0, frontendRefreshIntervalMs() - elapsedMs));",
            trainee_js,
        )
        self.assertIn('activeRuntimeSetting("frontend_refresh_seconds")', simulator_js)
        self.assertIn('activeRuntimeSetting("frontend_refresh_seconds")', trainee_js)


if __name__ == "__main__":
    unittest.main()
