from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simu.generate_simple_model import write_model_dir
from simu.server import (
    create_model_from_efile,
    import_definition_archive,
    make_definition_archive,
    update_model_from_efile,
)
from simu.service import MultiModelSimulator, PolarMicrogridSimulator


class RuntimeResetOnModelChangeTest(unittest.TestCase):
    def _make_manager(self):
        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        models_root = root / "models"
        source_dir = models_root / "model_a"
        write_model_dir(source_dir)
        manager = MultiModelSimulator.discover(
            root,
            root / "runtime",
            models_dir=models_root,
            kernel=lambda _config: None,
        )
        return workspace, root, source_dir, manager

    def _seed_stale_runtime(self, service: PolarMicrogridSimulator) -> list[Path]:
        stale_paths = [
            service.runtime_dir / "stale-marker.txt",
            service.runtime_dir / "old-traces" / "trace.json",
            service.files["real"],
            service.files["scada"],
            service.curves_file,
        ]
        for path in stale_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("stale", encoding="utf-8")

        service.command_history = [
            {
                "eligible_source": True,
                "manual_hold": True,
                "accepted": {"run_status": 1, "set_values": 0},
                "normalized": {"run_status": [], "set_values": []},
            }
        ]
        service._write_command_history()
        service.runtime_logs = [{"seq": 9, "type": "old"}]
        service._runtime_log_seq = 9
        service._write_runtime_logs()
        service.set_trainee_receive_state(
            {
                "active": True,
                "interaction_link": "http://127.0.0.1:8710/api/trainee-link?model_id=old",
            }
        )
        service.latest_result = {"old": True}
        service.clock.absolute_minute = 120
        service.clock.minute = 120
        service.clock.run_id = 3
        service.clock.step_count = 8
        service.clock.speed = 5
        return [
            *stale_paths,
            service.commands_file,
            service.runtime_logs_file,
            service.trainee_receive_file,
        ]

    def _assert_runtime_was_reset(self, service: PolarMicrogridSimulator, stale_paths: list[Path]) -> None:
        for path in stale_paths:
            self.assertFalse(path.exists(), f"stale runtime artifact was retained: {path.name}")
        self.assertEqual(service.command_history, [])
        self.assertEqual(service.runtime_logs, [])
        self.assertEqual(service.latest_result, {})
        self.assertEqual(service.clock.state, "stopped")
        self.assertEqual(service.clock.absolute_minute, 0)
        self.assertEqual(service.clock.minute, 0)
        self.assertEqual(service.clock.run_id, 0)
        self.assertEqual(service.clock.step_count, 0)
        self.assertFalse(service.trainee_receive_state()["active"])
        self.assertTrue(service.work_files["stat"].exists())
        self.assertTrue(service.work_files["weather"].exists())

    def test_updating_existing_model_clears_only_its_runtime_state(self):
        workspace, root, source_dir, manager = self._make_manager()
        self.addCleanup(workspace.cleanup)
        service = manager.service_for("model_a")
        stale_paths = self._seed_stale_runtime(service)
        other_runtime = root / "runtime" / "unrelated" / "keep.txt"
        other_runtime.parent.mkdir(parents=True, exist_ok=True)
        other_runtime.write_text("keep", encoding="utf-8")

        update_model_from_efile(
            manager,
            "model_a",
            (source_dir / "model.e").read_text(encoding="utf-8"),
        )

        self._assert_runtime_was_reset(service, stale_paths)
        self.assertTrue(other_runtime.exists())

    def test_importing_definitions_over_existing_model_clears_runtime_state(self):
        workspace, root, _source_dir, manager = self._make_manager()
        self.addCleanup(workspace.cleanup)
        service = manager.service_for("model_a")
        stale_paths = self._seed_stale_runtime(service)
        package_source = root / "package-source"
        write_model_dir(package_source)
        package_service = PolarMicrogridSimulator(
            package_source,
            root / "package-runtime",
            kernel=lambda _config: None,
            model_id="package",
        )
        _filename, archive = make_definition_archive(package_service)

        import_definition_archive(service, archive)

        self._assert_runtime_was_reset(service, stale_paths)

    def test_measurement_delta_requests_reset_after_model_runtime_is_cleared(self):
        workspace, _root, source_dir, manager = self._make_manager()
        self.addCleanup(workspace.cleanup)
        service = manager.service_for("model_a")
        service.measurement_delta(0)

        update_model_from_efile(
            manager,
            "model_a",
            (source_dir / "model.e").read_text(encoding="utf-8"),
        )
        delta = service.measurement_delta(999)

        self.assertTrue(delta["reset"])
        self.assertGreater(len(delta["items"]), 0)

    def test_cloning_model_starts_with_clean_runtime_and_does_not_copy_commands(self):
        workspace, root, _source_dir, manager = self._make_manager()
        self.addCleanup(workspace.cleanup)
        source = manager.service_for("model_a")
        source_stale_paths = self._seed_stale_runtime(source)
        orphan_marker = root / "runtime" / "model_b" / "stale-marker.txt"
        orphan_marker.parent.mkdir(parents=True, exist_ok=True)
        orphan_marker.write_text("stale", encoding="utf-8")

        manager.clone_model("model_a", "model_b")

        clone = manager.service_for("model_b")
        self.assertFalse(orphan_marker.exists())
        self.assertEqual(clone.command_history, [])
        self.assertEqual(clone.runtime_logs, [])
        self.assertTrue(all(path.exists() for path in source_stale_paths))

    def test_creating_model_clears_orphan_runtime_for_same_new_name(self):
        workspace, root, source_dir, manager = self._make_manager()
        self.addCleanup(workspace.cleanup)
        orphan_marker = root / "runtime" / "model_b" / "stale-marker.txt"
        orphan_marker.parent.mkdir(parents=True, exist_ok=True)
        orphan_marker.write_text("stale", encoding="utf-8")

        create_model_from_efile(
            manager,
            "model_b",
            (source_dir / "model.e").read_text(encoding="utf-8"),
        )

        created = manager.service_for("model_b")
        self.assertFalse(orphan_marker.exists())
        self.assertEqual(created.command_history, [])
        self.assertEqual(created.runtime_logs, [])


if __name__ == "__main__":
    unittest.main()
