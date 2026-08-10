from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class EmbeddedPowerFlowRuntimeTest(unittest.TestCase):
    def _make_service(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(source, runtime, model_id="embedded")
        return workspace, service

    def test_service_executes_power_flow_embedded_in_the_simulation_process(self):
        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        snapshot = service.step(advance_seconds=1.0)

        self.assertEqual(snapshot["compute"]["mode"], "embedded")
        self.assertEqual(snapshot["compute"]["http_pid"], os.getpid())
        self.assertEqual(snapshot["compute"]["worker_pid"], os.getpid())
        self.assertEqual(
            snapshot["compute"]["round_trip_ms"],
            snapshot["compute"]["compute_ms"],
        )
        self.assertTrue(snapshot["compute"]["resident_model"])

    def test_continuous_steps_reuse_the_resident_definition_without_efile_reads(self):
        import simu.service as service_module
        import simu_loop

        workspace, service = self._make_service()
        self.addCleanup(workspace.cleanup)
        resident_model = service.definition_snapshot.model_book
        original_loop_ebook = simu_loop.EBook
        original_service_ebook = service_module.EBook

        def fail_file_read(input_data):
            if isinstance(input_data, (str, Path)):
                raise AssertionError(f"continuous calculation reread E file: {input_data}")
            return original_loop_ebook(input_data)

        self.addCleanup(setattr, simu_loop, "EBook", original_loop_ebook)
        self.addCleanup(setattr, service_module, "EBook", original_service_ebook)
        simu_loop.EBook = fail_file_read
        service_module.EBook = fail_file_read

        for _cycle in range(3):
            snapshot = service.step(advance_seconds=1.0)
            self.assertIs(service.definition_snapshot.model_book, resident_model)
            self.assertEqual(snapshot["compute"]["mode"], "embedded")

    def test_server_ignores_legacy_process_worker_flags(self):
        import simu.power_flow_worker as worker_module
        import simu.server as server_module

        class FakeService:
            models_root = Path("models")

            @staticmethod
            def models():
                return [{"id": "embedded"}]

        class FakeServer:
            def serve_forever(self):
                return None

            def shutdown(self):
                return None

            def server_close(self):
                return None

        fake_service = FakeService()
        with (
            patch.object(
                worker_module.PowerFlowProcessRunner,
                "__init__",
                side_effect=AssertionError("process runner created"),
            ),
            patch.object(
                server_module.MultiModelSimulator,
                "discover",
                return_value=fake_service,
            ) as discover,
            patch.object(server_module, "make_http_server", return_value=FakeServer()),
        ):
            rc = server_module.main(
                [
                    "--no-worker",
                    "--power-flow-workers",
                    "4",
                    "--power-flow-timeout-seconds",
                    "0.01",
                ]
            )

        self.assertEqual(rc, 0)
        self.assertIsNone(discover.call_args.kwargs["kernel_runner"])


if __name__ == "__main__":
    unittest.main()
