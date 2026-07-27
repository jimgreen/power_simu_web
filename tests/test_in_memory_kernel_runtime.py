from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class InMemoryKernelRuntimeTest(unittest.TestCase):
    def _make_service(self):
        from simu.generate_simple_model import write_model_dir
        from simu.service import PolarMicrogridSimulator

        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        write_model_dir(source)
        service = PolarMicrogridSimulator(source, runtime, model_id="memory")
        return workspace, source, runtime, service

    def test_step_does_not_touch_e_files_or_create_real_scada_by_default(self):
        import simu.service as service_module
        import simu_loop

        workspace, _source, runtime, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        class FakeSnapshot:
            ac_devices = {"ACBreak": {}}
            dc_devices = {"DCBreak": {}}

            def value(self, _dev_type, _dev_name, _meas_type):
                return 1.0

        original_solve = simu_loop.solve_hybrid_snapshot_from_book
        original_loop_ebook = simu_loop.EBook
        original_service_ebook = service_module.EBook
        original_write_book = simu_loop.write_ebook_aligned
        original_write_measurements = simu_loop.write_measurement_snapshot

        def fake_solve(_model_book, _source):
            return FakeSnapshot(), "fake-solver"

        def fail_file_read(input_data):
            if isinstance(input_data, (str, Path)):
                raise AssertionError(f"runtime calculation read E file: {input_data}")
            return original_loop_ebook(input_data)

        def fail_efile_write(*_args, **_kwargs):
            raise AssertionError("runtime calculation wrote an E file")

        self.addCleanup(setattr, simu_loop, "solve_hybrid_snapshot_from_book", original_solve)
        self.addCleanup(setattr, simu_loop, "EBook", original_loop_ebook)
        self.addCleanup(setattr, service_module, "EBook", original_service_ebook)
        self.addCleanup(setattr, simu_loop, "write_ebook_aligned", original_write_book)
        self.addCleanup(setattr, simu_loop, "write_measurement_snapshot", original_write_measurements)
        simu_loop.solve_hybrid_snapshot_from_book = fake_solve
        simu_loop.EBook = fail_file_read
        service_module.EBook = fail_file_read
        simu_loop.write_ebook_aligned = fail_efile_write
        simu_loop.write_measurement_snapshot = fail_efile_write

        snapshot = service.step()

        self.assertFalse((runtime / "real.e").exists())
        self.assertFalse((runtime / "scada.e").exists())
        self.assertGreater(len(snapshot["measurements"]["scada"]), 0)
        self.assertEqual(snapshot["result"]["solver_info"], "fake-solver")

    def test_interface_updates_are_reflected_without_reloading_e_files(self):
        import simu.service as service_module
        import simu_loop

        workspace, _source, _runtime, service = self._make_service()
        self.addCleanup(workspace.cleanup)

        result = service.apply_student_commands(
            {
                "valid_for_minutes": 5,
                "set_values": [
                    {"dev_type": "ESS", "dev_name": "ess01", "set_type": "p_set", "set_value": 22.5}
                ],
            },
            source="trainee-ui",
        )
        self.assertEqual(result["set_values"], 1)

        original_loop_ebook = simu_loop.EBook
        original_service_ebook = service_module.EBook

        def fail_file_read(input_data):
            if isinstance(input_data, (str, Path)):
                raise AssertionError(f"runtime state lookup read E file: {input_data}")
            return original_loop_ebook(input_data)

        self.addCleanup(setattr, simu_loop, "EBook", original_loop_ebook)
        self.addCleanup(setattr, service_module, "EBook", original_service_ebook)
        simu_loop.EBook = fail_file_read
        service_module.EBook = fail_file_read

        values = service.latest_control_values()["values"]

        self.assertEqual(values["ESS.ess01.p_set"], 22.5)


if __name__ == "__main__":
    unittest.main()
