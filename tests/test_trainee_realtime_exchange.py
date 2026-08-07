from __future__ import annotations

import copy
import json
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.request import urlopen
from unittest.mock import patch

from simu.generate_simple_model import write_model_dir
from simu.server import make_http_server
from simu.service import MultiModelSimulator, PolarMicrogridSimulator, SimulationModelSpec
from simu.trainee_exchange import (
    CONTROL_STATIC_FIELDS,
    TraineeControlSnapshot,
    TraineeRealtimeExchange,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "simple_model"


class _DeepcopyBomb:
    def __init__(self, message):
        self.message = message

    def __deepcopy__(self, _memo):
        raise AssertionError(self.message)


def configure_receive(
    service,
    *,
    teacher_id="teacher",
    teacher_api_base="http://teacher.invalid",
):
    service.set_trainee_receive_state(
        {
            "initialized": True,
            "active": True,
            "interaction_link": f"{teacher_api_base}/api/trainee-link?model_id={teacher_id}",
            "teacher_api_base": teacher_api_base,
            "snapshot_path": f"/api/snapshot?model_id={teacher_id}",
            "command_path": f"/api/student/commands?model_id={teacher_id}",
            "teacher_model_id": teacher_id,
        }
    )


class ServiceRegistry:
    def __init__(self, services):
        self.services = {service.model_id: service for service in services}
        self.fail_enumeration = False

    def service_for(self, model_id=None):
        return self.services[model_id or next(iter(self.services))]

    def iter_services(self):
        if self.fail_enumeration:
            raise RuntimeError("temporary registry failure")
        return list(self.services.values())


class TraineeRealtimeExchangeTest(unittest.TestCase):
    def make_service(self, model_id="trainee-local"):
        workspace = tempfile.TemporaryDirectory()
        root = Path(workspace.name)
        source = root / "source"
        runtime = root / "runtime"
        shutil.copytree(FIXTURE, source)
        service = PolarMicrogridSimulator(
            source,
            runtime,
            model_id=model_id,
            kernel=lambda _config: None,
        )
        self.addCleanup(workspace.cleanup)
        return service

    def test_control_snapshot_uses_runtime_values_but_local_static_parameters(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
            include_devices=True,
            include_commands=True,
        )
        runtime["device_parameters"]["ACWindGen"][0]["rated_power"] = 999.0
        runtime["devices"][0]["run_stat"] = 0
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)

        exchange.publish_runtime_snapshot("trainee-local", runtime, received_at=time.time())
        view = exchange.control_snapshot("trainee-local")

        self.assertIsInstance(view, TraineeControlSnapshot)
        self.assertTrue(view.ready)
        self.assertEqual(
            float(view.snapshot["device_parameters"]["ACWindGen"][0]["rated_power"]),
            10.0,
        )
        self.assertEqual(view.snapshot["devices"][0]["run_stat"], 0)

    def test_control_snapshot_applies_latest_local_manual_edit_without_republishing_runtime(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
            include_devices=True,
            include_commands=False,
        )
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot("trainee-local", runtime, received_at=time.time())

        service.update_device_parameters(
            {
                "block_name": "ACWindGen",
                "row_key": {"idx": "1"},
                "revision": service.definition_snapshot.revision,
                "changes": {"rated_power": 22},
            }
        )
        view = exchange.control_snapshot("trainee-local")

        self.assertEqual(
            float(view.snapshot["device_parameters"]["ACWindGen"][0]["rated_power"]),
            22.0,
        )

    def test_control_snapshot_returns_a_copy_of_cached_runtime_data(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
            include_devices=True,
            include_commands=False,
        )
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot("trainee-local", runtime, received_at=time.time())

        first = exchange.control_snapshot("trainee-local")
        original_clock = copy.deepcopy(first.snapshot.get("clock"))
        first.snapshot["clock"] = {"time": "mutated"}

        second = exchange.control_snapshot("trainee-local")

        self.assertEqual(second.snapshot.get("clock"), original_clock)

    def test_refresh_once_requests_dynamic_runtime_only(self):
        service = self.make_service()
        configure_receive(service)
        runtime = service.snapshot(include_static=True, include_runtime_logs=False)
        urls = []

        def request_json(url, **_kwargs):
            urls.append(url)
            return copy.deepcopy(runtime)

        exchange = TraineeRealtimeExchange(
            service,
            request_json=request_json,
            start_worker=False,
        )
        self.addCleanup(exchange.close)

        view = exchange.refresh_once("trainee-local")

        self.assertTrue(view.ready)
        self.assertEqual(len(urls), 1)
        self.assertIn("static=0", urls[0])
        self.assertIn("measurements=0", urls[0])
        self.assertIn("measurement_after_seq=0", urls[0])
        self.assertIn("measurement_compact=1", urls[0])
        self.assertIn("command_history=0", urls[0])

    def test_refresh_rejects_a_bad_measurement_array_without_advancing_or_publishing(self):
        service = self.make_service()
        teacher = self.make_service("teacher")
        configure_receive(service)
        teacher.latest_real_rows = [list(row) for row in teacher.measurement_rows]
        teacher.latest_scada_rows = [list(row) for row in teacher.measurement_rows]
        good_frame = teacher.measurement_delta(after_seq=0, compact=True)
        good_snapshot = teacher.snapshot(
            include_static=False,
            include_runtime_logs=False,
            include_measurements=False,
        )
        good_snapshot["measurement_delta"] = good_frame
        bad_snapshot = copy.deepcopy(good_snapshot)
        bad_snapshot["measurement_delta"]["seq"] = good_frame["seq"] + 1
        bad_snapshot["measurement_delta"]["count"] = good_frame["count"] + 1
        responses = [good_snapshot, bad_snapshot]

        exchange = TraineeRealtimeExchange(
            service,
            request_json=lambda _url, **_kwargs: copy.deepcopy(responses.pop(0)),
            start_worker=False,
        )
        self.addCleanup(exchange.close)

        first = exchange.refresh_once(service.model_id)
        state = exchange._state_for_service(service)
        with state.lock:
            first_revision = state.revision
            first_remote_seq = state.remote_measurement_delta_seq
            first_measurements = copy.deepcopy((state.runtime_snapshot or {}).get("measurements"))

        second = exchange.refresh_once(service.model_id)

        self.assertEqual(second.revision, first_revision)
        self.assertEqual(first_remote_seq, good_frame["seq"])
        with state.lock:
            self.assertEqual(state.revision, first_revision)
            self.assertEqual(state.remote_measurement_delta_seq, first_remote_seq)
            self.assertEqual((state.runtime_snapshot or {}).get("measurements"), first_measurements)
            self.assertIn("实时量测数组长度不一致", state.last_error)

    def test_refresh_diagnostics_count_accepted_and_rejected_measurement_frames(self):
        service = self.make_service()
        teacher = self.make_service("teacher")
        configure_receive(service)
        teacher.latest_real_rows = [list(row) for row in teacher.measurement_rows]
        teacher.latest_scada_rows = [list(row) for row in teacher.measurement_rows]
        good_frame = teacher.measurement_delta(after_seq=0, compact=True)
        good_snapshot = teacher.snapshot(
            include_static=False,
            include_runtime_logs=False,
            include_measurements=False,
        )
        good_snapshot["measurement_delta"] = good_frame
        missing_signature = copy.deepcopy(good_snapshot)
        missing_signature["measurement_delta"]["seq"] = good_frame["seq"] + 1
        missing_signature["measurement_delta"].pop("definition_signature")
        responses = [good_snapshot, missing_signature]
        exchange = TraineeRealtimeExchange(
            service,
            request_json=lambda _url, **_kwargs: copy.deepcopy(responses.pop(0)),
            start_worker=False,
        )
        self.addCleanup(exchange.close)

        exchange.refresh_once(service.model_id)
        accepted = exchange.receive_status(service.model_id)
        exchange.refresh_once(service.model_id)
        rejected = exchange.receive_status(service.model_id)

        self.assertEqual(accepted["acceptedMeasurementFrameCount"], 1)
        self.assertEqual(accepted["rejectedMeasurementFrameCount"], 0)
        self.assertEqual(accepted["lastAcceptedMeasurementSeq"], good_frame["seq"])
        self.assertEqual(accepted["lastAcceptedMeasurementCount"], good_frame["count"])
        self.assertEqual(rejected["acceptedMeasurementFrameCount"], 1)
        self.assertEqual(rejected["rejectedMeasurementFrameCount"], 1)
        self.assertEqual(rejected["lastRejectedMeasurementSeq"], good_frame["seq"] + 1)
        self.assertIn("定义顺序签名缺失", rejected["lastRejectedMeasurementReason"])
        self.assertEqual(rejected["remoteMeasurementSeq"], good_frame["seq"])

    def test_published_measurements_align_values_by_index_instead_of_measurement_name(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
        )
        measurement_index = runtime["measurements"]["real"][0]["idx"]
        definition_position = next(
            position
            for position, definition in enumerate(runtime["measurements"]["definitions"])
            if definition["idx"] == measurement_index
        )
        real_row = next(
            row for row in runtime["measurements"]["real"] if row["idx"] == measurement_index
        )
        scada_row = next(
            row for row in runtime["measurements"]["scada"] if row["idx"] == measurement_index
        )
        real_row["name"] = "故意不匹配的真值测点名"
        scada_row["name"] = "故意不匹配的量测点名"
        real_row["value"] = 41.5
        scada_row["value"] = 40.75
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)

        exchange.publish_runtime_snapshot(service.model_id, runtime)
        compact = exchange.measurement_delta(service.model_id, after_seq=0, compact=True)

        self.assertEqual(compact["real_values"][definition_position], 41.5)
        self.assertEqual(compact["scada_values"][definition_position], 40.75)

    def test_internal_snapshot_publish_does_not_deepcopy_unrelated_runtime_sections(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=False,
            include_runtime_logs=False,
            include_measurements=True,
        )
        runtime["unrelated"] = _DeepcopyBomb("unrelated runtime data must not be deep-copied")
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        state = exchange._state_for_service(service)
        service.snapshot = lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("validated owned measurement frames must not rebuild a local snapshot")
        )

        revision = exchange._publish_runtime_snapshot_for_service(
            service,
            state,
            runtime,
            snapshot_owned=True,
        )

        self.assertEqual(revision, 1)
        with state.lock:
            self.assertIs((state.runtime_snapshot or {})["unrelated"], runtime["unrelated"])

    def test_runtime_snapshot_without_a_measurement_frame_preserves_the_last_valid_arrays(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
        )
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(service.model_id, runtime)
        state = exchange._state_for_service(service)
        with state.lock:
            initial_seq = state.measurement_delta_seq
            initial_items = list(state.measurement_delta_state.items())

        without_measurements = service.snapshot(
            include_static=False,
            include_runtime_logs=False,
            include_measurements=False,
        )
        exchange._publish_runtime_snapshot_for_service(
            service,
            state,
            without_measurements,
            snapshot_owned=True,
        )

        with state.lock:
            self.assertEqual(state.measurement_delta_seq, initial_seq)
            self.assertEqual(list(state.measurement_delta_state.items()), initial_items)

    def test_unchanged_array_envelope_skips_rebuilding_measurement_rows(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
        )
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(service.model_id, runtime)
        state = exchange._state_for_service(service)
        with state.lock:
            initial_seq = state.measurement_delta_seq

        with patch(
            "simu.trainee_exchange._measurement_delta_items",
            side_effect=AssertionError("unchanged arrays must reuse the accepted measurement state"),
        ):
            exchange._publish_runtime_snapshot_for_service(
                service,
                state,
                runtime,
                snapshot_owned=True,
                measurement_frame_unchanged=True,
            )

        with state.lock:
            self.assertEqual(state.measurement_delta_seq, initial_seq)

    def test_worker_receives_without_any_browser_request(self):
        service = self.make_service()
        configure_receive(service)
        runtime = service.snapshot(include_static=True, include_runtime_logs=False)
        calls = []

        def request_json(url, **_kwargs):
            calls.append(url)
            return copy.deepcopy(runtime)

        exchange = TraineeRealtimeExchange(
            service,
            request_json=request_json,
            poll_interval_seconds=0.05,
            start_worker=True,
        )
        self.addCleanup(exchange.close)

        deadline = time.time() + 2.0
        while time.time() < deadline and not exchange.control_snapshot("trainee-local").ready:
            time.sleep(0.02)

        self.assertTrue(exchange.control_snapshot("trainee-local").ready)
        self.assertGreaterEqual(len(calls), 1)

    def test_connection_change_during_fetch_discards_candidate(self):
        service = self.make_service()
        configure_receive(service)
        runtime = service.snapshot(include_static=True, include_runtime_logs=False)

        def request_json(_url, **_kwargs):
            service.set_trainee_receive_state({"teacher_model_id": "replacement"})
            return copy.deepcopy(runtime)

        exchange = TraineeRealtimeExchange(
            service,
            request_json=request_json,
            start_worker=False,
        )
        self.addCleanup(exchange.close)

        view = exchange.refresh_once("trainee-local")

        self.assertFalse(view.ready)
        self.assertEqual(view.revision, 0)

    def test_retarget_after_final_signature_sample_discards_old_success_response(self):
        service = self.make_service()
        configure_receive(
            service,
            teacher_id="teacher-a",
            teacher_api_base="http://teacher-a.invalid",
        )
        runtime = service.snapshot(include_static=True, include_runtime_logs=False)
        runtime["clock"]["time"] = "teacher-a-clock"
        response_returned = threading.Event()
        final_signature_sampled = threading.Event()
        release_commit = threading.Event()
        command_urls = []

        def request_json(url, **kwargs):
            if str(kwargs.get("method", "GET")).upper() == "POST":
                command_urls.append(url)
                return {"set_values": 0}
            response_returned.set()
            return copy.deepcopy(runtime)

        exchange = TraineeRealtimeExchange(
            service,
            request_json=request_json,
            start_worker=False,
        )
        self.addCleanup(exchange.close)
        exchange.notify_receive_state_changed_for_service(service)
        generation_a = exchange.control_generation(service.model_id)
        original_connection_signature = exchange._connection_signature
        refresh_thread = None

        def block_after_final_signature(target):
            signature = original_connection_signature(target)
            if (
                target is service
                and response_returned.is_set()
                and threading.current_thread() is refresh_thread
            ):
                final_signature_sampled.set()
                self.assertTrue(release_commit.wait(timeout=2.0))
            return signature

        result = {}

        def refresh_teacher_a():
            try:
                result["view"] = exchange.refresh_once(service.model_id)
            except Exception as exc:
                result["error"] = exc

        refresh_thread = threading.Thread(target=refresh_teacher_a, daemon=True)
        try:
            with patch.object(
                exchange,
                "_connection_signature",
                side_effect=block_after_final_signature,
            ):
                refresh_thread.start()
                self.assertTrue(final_signature_sampled.wait(timeout=2.0))
                configure_receive(
                    service,
                    teacher_id="teacher-b",
                    teacher_api_base="http://teacher-b.invalid",
                )
                exchange.notify_receive_state_changed_for_service(service)
                generation_b = exchange.control_generation(service.model_id)
                release_commit.set()
                refresh_thread.join(timeout=2.0)
                self.assertFalse(refresh_thread.is_alive())
        finally:
            release_commit.set()
            refresh_thread.join(timeout=2.0)

        self.assertNotIn("error", result)
        view_b = exchange.control_snapshot(service.model_id)
        self.assertFalse(view_b.ready)
        self.assertNotEqual(
            view_b.snapshot.get("clock", {}).get("time"),
            "teacher-a-clock",
        )
        self.assertNotEqual(generation_a, generation_b)
        self.assertEqual(exchange.control_generation(service.model_id), generation_b)

        exchange.submit_commands(service.model_id, {"set_values": []})
        self.assertEqual(len(command_urls), 1)
        self.assertIn("teacher-b.invalid", command_urls[0])
        self.assertNotIn("teacher-a.invalid", command_urls[0])

    def test_retarget_after_final_signature_sample_discards_old_failure_response(self):
        service = self.make_service()
        configure_receive(
            service,
            teacher_id="teacher-a",
            teacher_api_base="http://teacher-a.invalid",
        )
        response_failed = threading.Event()
        final_signature_sampled = threading.Event()
        release_commit = threading.Event()

        def failing_request(_url, **_kwargs):
            response_failed.set()
            raise RuntimeError("teacher-a failed")

        exchange = TraineeRealtimeExchange(
            service,
            request_json=failing_request,
            start_worker=False,
        )
        self.addCleanup(exchange.close)
        exchange.notify_receive_state_changed_for_service(service)
        original_connection_signature = exchange._connection_signature
        refresh_thread = None

        def block_after_final_signature(target):
            signature = original_connection_signature(target)
            if (
                target is service
                and response_failed.is_set()
                and threading.current_thread() is refresh_thread
            ):
                final_signature_sampled.set()
                self.assertTrue(release_commit.wait(timeout=2.0))
            return signature

        result = {}

        def refresh_teacher_a():
            try:
                result["view"] = exchange.refresh_once(service.model_id)
            except Exception as exc:
                result["error"] = exc

        refresh_thread = threading.Thread(target=refresh_teacher_a, daemon=True)
        try:
            with patch.object(
                exchange,
                "_connection_signature",
                side_effect=block_after_final_signature,
            ):
                refresh_thread.start()
                self.assertTrue(final_signature_sampled.wait(timeout=2.0))
                configure_receive(
                    service,
                    teacher_id="teacher-b",
                    teacher_api_base="http://teacher-b.invalid",
                )
                exchange.notify_receive_state_changed_for_service(service)
                generation_b = exchange.control_generation(service.model_id)
                release_commit.set()
                refresh_thread.join(timeout=2.0)
                self.assertFalse(refresh_thread.is_alive())
        finally:
            release_commit.set()
            refresh_thread.join(timeout=2.0)

        self.assertNotIn("error", result)
        view_b = exchange.control_snapshot(service.model_id)
        status_b = exchange.receive_status(service.model_id)
        self.assertFalse(view_b.ready)
        self.assertIsNone(view_b.error)
        self.assertEqual(status_b["error"], "")
        self.assertEqual(status_b["consecutiveFailures"], 0)
        self.assertEqual(exchange.control_generation(service.model_id), generation_b)

    def test_connection_change_during_fetch_also_discards_existing_connection_cache(self):
        service = self.make_service()
        configure_receive(service)
        runtime = service.snapshot(include_static=True, include_runtime_logs=False)
        runtime["clock"]["time"] = "old-connection"

        def request_json(_url, **_kwargs):
            service.set_trainee_receive_state({"teacher_model_id": "replacement"})
            candidate = copy.deepcopy(runtime)
            candidate["clock"]["time"] = "discarded-candidate"
            return candidate

        exchange = TraineeRealtimeExchange(
            service,
            request_json=request_json,
            start_worker=False,
        )
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(
            "trainee-local",
            runtime,
            connection_signature=exchange._connection_signature(service),
        )

        view = exchange.refresh_once("trainee-local")

        self.assertFalse(view.ready)
        self.assertEqual(exchange.measurement_delta("trainee-local", after_seq=0)["items"], [])

    def test_refresh_once_discards_old_response_after_delete_and_same_id_recreate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            models_root = root / "models"
            for model_id in ("shared", "keep"):
                write_model_dir(models_root / model_id)
            services = MultiModelSimulator(
                [
                    SimulationModelSpec("shared", models_root / "shared", "Shared"),
                    SimulationModelSpec("keep", models_root / "keep", "Keep"),
                ],
                runtime_dir=root / "runtime",
                models_root=models_root,
                kernel=lambda _config: None,
            )
            old_service = services.service_for("shared")
            configure_receive(old_service)
            old_runtime = old_service.snapshot(
                include_static=True,
                include_runtime_logs=False,
                include_measurements=True,
            )
            old_runtime["clock"]["time"] = "old-response-clock"
            request_started = threading.Event()
            release_response = threading.Event()
            final_signature_sampled = threading.Event()
            release_publication = threading.Event()
            response_returned = threading.Event()

            def blocking_request(_url, **_kwargs):
                request_started.set()
                self.assertTrue(release_response.wait(timeout=2.0))
                response_returned.set()
                return copy.deepcopy(old_runtime)

            exchange = TraineeRealtimeExchange(
                services,
                request_json=blocking_request,
                start_worker=False,
            )
            self.addCleanup(exchange.close)
            old_state = exchange._state_for_service(old_service)
            original_connection_signature = exchange._connection_signature

            def block_after_final_signature(target):
                signature = original_connection_signature(target)
                if target is old_service and response_returned.is_set():
                    final_signature_sampled.set()
                    self.assertTrue(release_publication.wait(timeout=2.0))
                return signature

            result = {}

            def refresh_old_service():
                try:
                    result["view"] = exchange.refresh_once("shared")
                except Exception as exc:
                    result["error"] = exc

            refresh_thread = threading.Thread(target=refresh_old_service, daemon=True)
            try:
                with patch.object(
                    exchange,
                    "_connection_signature",
                    side_effect=block_after_final_signature,
                ):
                    refresh_thread.start()
                    self.assertTrue(request_started.wait(timeout=2.0))
                    release_response.set()
                    self.assertTrue(final_signature_sampled.wait(timeout=2.0))

                    old_service.set_trainee_receive_state({"active": False})
                    services.delete_model("shared")
                    exchange.remove_model_for_service(old_service)
                    services.create_model_slot("shared")
                    new_service = services.service_for("shared")
                    new_state = exchange._state_for_service(new_service)
                    self.assertFalse(exchange.control_snapshot("shared").ready)

                    release_publication.set()
                    refresh_thread.join(timeout=2.0)
                    self.assertFalse(refresh_thread.is_alive())
            finally:
                release_response.set()
                release_publication.set()
                refresh_thread.join(timeout=2.0)

            self.assertNotIn("error", result)
            new_view = exchange.control_snapshot("shared")
            self.assertFalse(new_view.ready)
            self.assertNotEqual(
                new_view.snapshot.get("clock", {}).get("time"),
                "old-response-clock",
            )
            self.assertEqual(new_view.snapshot.get("measurements", {}), {})
            self.assertIs(exchange._states["shared"], new_state)
            self.assertIsNot(exchange._states["shared"], old_state)
            self.assertIsNone(old_state.runtime_snapshot)

    def test_old_refresh_mismatch_notify_preserves_ready_recreated_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            models_root = root / "models"
            for model_id in ("shared", "keep"):
                write_model_dir(models_root / model_id)
            services = MultiModelSimulator(
                [
                    SimulationModelSpec("shared", models_root / "shared", "Shared"),
                    SimulationModelSpec("keep", models_root / "keep", "Keep"),
                ],
                runtime_dir=root / "runtime",
                models_root=models_root,
                kernel=lambda _config: None,
            )
            old_service = services.service_for("shared")
            configure_receive(
                old_service,
                teacher_id="teacher-a",
                teacher_api_base="http://teacher-a.invalid",
            )
            old_runtime = old_service.snapshot(
                include_static=True,
                include_runtime_logs=False,
            )
            old_runtime["clock"]["time"] = "old-a-clock"
            request_started = threading.Event()
            release_response = threading.Event()

            def blocking_request(_url, **_kwargs):
                request_started.set()
                self.assertTrue(release_response.wait(timeout=3.0))
                return copy.deepcopy(old_runtime)

            exchange = TraineeRealtimeExchange(
                services,
                request_json=blocking_request,
                start_worker=False,
            )
            self.addCleanup(exchange.close)
            result = {}

            def refresh_old_service():
                try:
                    result["view"] = exchange.refresh_once("shared")
                except Exception as exc:
                    result["error"] = exc

            refresh_thread = threading.Thread(target=refresh_old_service, daemon=True)
            try:
                refresh_thread.start()
                self.assertTrue(request_started.wait(timeout=2.0))

                old_service.set_trainee_receive_state({"active": False})
                services.delete_model("shared")
                exchange.remove_model_for_service(old_service)
                services.create_model_slot("shared")
                new_service = services.service_for("shared")
                configure_receive(
                    new_service,
                    teacher_id="teacher-b",
                    teacher_api_base="http://teacher-b.invalid",
                )
                exchange.notify_receive_state_changed_for_service(new_service)
                new_runtime = new_service.snapshot(
                    include_static=True,
                    include_runtime_logs=False,
                )
                new_runtime["clock"]["time"] = "new-b-ready-clock"
                exchange.publish_runtime_snapshot(
                    "shared",
                    new_runtime,
                    connection_signature=exchange._connection_signature(new_service),
                )
                new_state = exchange._states["shared"]
                new_view_before = exchange.control_snapshot("shared")
                new_generation = exchange.control_generation("shared")

                release_response.set()
                refresh_thread.join(timeout=3.0)
                self.assertFalse(refresh_thread.is_alive())
            finally:
                release_response.set()
                refresh_thread.join(timeout=2.0)

            self.assertNotIn("error", result)
            new_view_after = exchange.control_snapshot("shared")
            self.assertTrue(new_view_before.ready)
            self.assertTrue(new_view_after.ready)
            self.assertEqual(
                new_view_after.snapshot.get("clock", {}).get("time"),
                "new-b-ready-clock",
            )
            self.assertEqual(new_view_after.revision, new_view_before.revision)
            self.assertIs(exchange._states["shared"], new_state)
            self.assertEqual(exchange.control_generation("shared"), new_generation)

    def test_worker_stale_service_snapshot_cannot_replace_or_refresh_recreated_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            models_root = root / "models"
            for model_id in ("shared", "keep"):
                write_model_dir(models_root / model_id)
            services = MultiModelSimulator(
                [
                    SimulationModelSpec("shared", models_root / "shared", "Shared"),
                    SimulationModelSpec("keep", models_root / "keep", "Keep"),
                ],
                runtime_dir=root / "runtime",
                models_root=models_root,
                kernel=lambda _config: None,
            )
            old_service = services.service_for("shared")
            stale_receive = {
                "initialized": True,
                "active": True,
                "interaction_link": "http://teacher-a.invalid/api/trainee-link?model_id=teacher-a",
                "teacher_api_base": "http://teacher-a.invalid",
                "snapshot_path": "/api/snapshot?model_id=teacher-a",
                "command_path": "/api/student/commands?model_id=teacher-a",
                "teacher_model_id": "teacher-a",
            }
            transport_calls = []

            def request_json(url, **_kwargs):
                transport_calls.append(url)
                candidate = copy.deepcopy(new_runtime)
                candidate["clock"]["time"] = "stale-worker-refresh"
                return candidate

            exchange = TraineeRealtimeExchange(
                services,
                request_json=request_json,
                poll_interval_seconds=0.05,
                start_worker=False,
            )
            enumeration_captured = threading.Event()
            release_enumeration = threading.Event()
            iteration_done = threading.Event()
            capture_consumed = threading.Event()
            original_iter_services = services.iter_services

            def coordinated_iter_services():
                captured = original_iter_services()
                if not capture_consumed.is_set():
                    capture_consumed.set()
                    enumeration_captured.set()
                    self.assertTrue(release_enumeration.wait(timeout=3.0))
                return captured

            class OneIterationWake:
                def wait(self, _timeout):
                    iteration_done.set()
                    exchange._stop_event.set()
                    return True

                def clear(self):
                    return None

                def set(self):
                    return None

            services.iter_services = coordinated_iter_services
            exchange._wake_event = OneIterationWake()
            exchange._worker = threading.Thread(
                target=exchange._worker_loop,
                name="test-exchange-stale-enumeration",
                daemon=True,
            )
            try:
                exchange._worker.start()
                self.assertTrue(enumeration_captured.wait(timeout=2.0))

                services.delete_model("shared")
                exchange.remove_model_for_service(old_service)
                services.create_model_slot("shared")
                new_service = services.service_for("shared")
                configure_receive(
                    new_service,
                    teacher_id="teacher-b",
                    teacher_api_base="http://teacher-b.invalid",
                )
                exchange.notify_receive_state_changed_for_service(new_service)
                new_runtime = new_service.snapshot(
                    include_static=True,
                    include_runtime_logs=False,
                )
                new_runtime["clock"]["time"] = "new-b-ready-clock"
                exchange.publish_runtime_snapshot(
                    "shared",
                    new_runtime,
                    connection_signature=exchange._connection_signature(new_service),
                )
                new_state = exchange._states["shared"]
                new_view_before = exchange.control_snapshot_for_service(new_service)
                new_generation = exchange.control_generation("shared")
                old_service.trainee_receive_state = lambda: copy.deepcopy(stale_receive)

                release_enumeration.set()
                self.assertTrue(iteration_done.wait(timeout=3.0))
                exchange._worker.join(timeout=3.0)
                self.assertFalse(exchange._worker.is_alive())
                exchange.close()
                new_view_after = exchange.control_snapshot_for_service(new_service)
                generation_after = exchange.control_generation("shared")
            finally:
                release_enumeration.set()
                exchange._stop_event.set()
                exchange.close()

        self.assertEqual(transport_calls, [])
        self.assertIs(exchange._states["shared"], new_state)
        self.assertTrue(new_view_after.ready)
        self.assertEqual(
            new_view_after.snapshot.get("clock", {}).get("time"),
            "new-b-ready-clock",
        )
        self.assertEqual(new_view_after.revision, new_view_before.revision)
        self.assertEqual(generation_after, new_generation)

    def test_directory_sync_retires_service_removed_outside_registry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            models_root = root / "models"
            for model_id in ("shared", "keep"):
                write_model_dir(models_root / model_id)
            services = MultiModelSimulator(
                [
                    SimulationModelSpec("shared", models_root / "shared", "Shared"),
                    SimulationModelSpec("keep", models_root / "keep", "Keep"),
                ],
                runtime_dir=root / "runtime",
                models_root=models_root,
                directory_backed=True,
                kernel=lambda _config: None,
            )
            removed_service = services.service_for("shared")

            shutil.rmtree(models_root / "shared")
            services.models()

            self.assertFalse(removed_service.service_instance_active())
            with self.assertRaises(KeyError):
                services.service_for("shared")

    def test_connection_change_clears_snapshot_and_measurement_delta_state(self):
        service = self.make_service()
        configure_receive(service)
        runtime = service.snapshot(include_static=True, include_runtime_logs=False)
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(
            "trainee-local",
            runtime,
            connection_signature=exchange._connection_signature(service),
        )
        self.assertTrue(exchange.measurement_delta("trainee-local", after_seq=0)["items"])

        service.set_trainee_receive_state({"teacher_model_id": "replacement"})
        exchange.receive_state_changed("trainee-local")

        self.assertFalse(exchange.control_snapshot("trainee-local").ready)
        delta = exchange.measurement_delta("trainee-local", after_seq=0)
        self.assertEqual(delta["seq"], 0)
        self.assertEqual(delta["items"], [])

    def test_receive_epoch_is_stable_across_runtime_snapshot_publish(self):
        service = self.make_service()
        configure_receive(service)
        runtime = service.snapshot(include_static=True, include_runtime_logs=False)
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)

        exchange.publish_runtime_snapshot(
            "trainee-local",
            runtime,
            connection_signature=exchange._connection_signature(service),
        )
        first = exchange.receive_status("trainee-local")
        changed_runtime = copy.deepcopy(runtime)
        changed_runtime["clock"]["time"] = "later-telemetry"
        exchange.publish_runtime_snapshot(
            "trainee-local",
            changed_runtime,
            connection_signature=exchange._connection_signature(service),
        )
        second = exchange.receive_status("trainee-local")

        self.assertGreater(second["revision"], first["revision"])
        self.assertEqual(second["receiveEpoch"], first["receiveEpoch"])

    def test_receive_epoch_changes_on_link_retarget_and_model_invalidation(self):
        service = self.make_service()
        configure_receive(service)
        runtime = service.snapshot(include_static=True, include_runtime_logs=False)
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(
            "trainee-local",
            runtime,
            connection_signature=exchange._connection_signature(service),
        )
        ready = exchange.receive_status("trainee-local")

        service.set_trainee_receive_state({"teacher_model_id": "replacement"})
        retargeted = exchange.receive_state_changed("trainee-local")
        exchange.invalidate_model("trainee-local")
        invalidated = exchange.receive_status("trainee-local")

        self.assertGreater(retargeted["receiveEpoch"], ready["receiveEpoch"])
        self.assertGreater(invalidated["receiveEpoch"], retargeted["receiveEpoch"])

    def test_control_generation_guard_ignores_normal_telemetry_publication(self):
        service = self.make_service()
        configure_receive(service)
        runtime = service.snapshot(include_static=True, include_runtime_logs=False)
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(
            "trainee-local",
            runtime,
            connection_signature=exchange._connection_signature(service),
        )

        self.assertTrue(
            callable(getattr(exchange, "control_generation", None)),
            "exchange must expose a stable control generation",
        )
        self.assertTrue(
            callable(getattr(exchange, "control_generation_guard", None)),
            "exchange must expose an atomic control generation guard",
        )
        generation = exchange.control_generation("trainee-local")
        changed_runtime = copy.deepcopy(runtime)
        changed_runtime["clock"]["time"] = "later-telemetry"
        exchange.publish_runtime_snapshot(
            "trainee-local",
            changed_runtime,
            connection_signature=exchange._connection_signature(service),
        )

        self.assertEqual(exchange.control_generation("trainee-local"), generation)
        with exchange.control_generation_guard("trainee-local", generation) as valid:
            self.assertTrue(valid)

    def test_control_generation_guard_rejects_receive_model_and_definition_changes(self):
        invalidators = (
            "receive-retarget",
            "receive-stop",
            "model-invalidation",
            "definition-revision",
        )
        for invalidator in invalidators:
            with self.subTest(invalidator=invalidator):
                service = self.make_service(f"trainee-{invalidator}")
                configure_receive(service)
                runtime = service.snapshot(include_static=True, include_runtime_logs=False)
                exchange = TraineeRealtimeExchange(service, start_worker=False)
                self.addCleanup(exchange.close)
                exchange.publish_runtime_snapshot(
                    service.model_id,
                    runtime,
                    connection_signature=exchange._connection_signature(service),
                )

                self.assertTrue(
                    callable(getattr(exchange, "control_generation", None)),
                    "exchange must expose a stable control generation",
                )
                self.assertTrue(
                    callable(getattr(exchange, "control_generation_guard", None)),
                    "exchange must expose an atomic control generation guard",
                )
                generation = exchange.control_generation(service.model_id)
                if invalidator == "receive-retarget":
                    service.set_trainee_receive_state({"teacher_model_id": "replacement"})
                    exchange.receive_state_changed(service.model_id)
                elif invalidator == "receive-stop":
                    service.set_trainee_receive_state({"active": False})
                    exchange.receive_state_changed(service.model_id)
                elif invalidator == "model-invalidation":
                    exchange.invalidate_model(service.model_id)
                else:
                    service.update_device_parameters(
                        {
                            "block_name": "ACWindGen",
                            "row_key": {"idx": "1"},
                            "revision": service.definition_snapshot.revision,
                            "changes": {"rated_power": 22},
                        }
                    )

                with exchange.control_generation_guard(service.model_id, generation) as valid:
                    self.assertFalse(valid)

    def test_same_model_id_with_new_service_has_fresh_state_and_generation(self):
        old_service = self.make_service("trainee-local")
        new_service = self.make_service("trainee-local")
        configure_receive(old_service)
        configure_receive(new_service)
        registry = ServiceRegistry([old_service])
        exchange = TraineeRealtimeExchange(registry, start_worker=False)
        self.addCleanup(exchange.close)
        runtime = old_service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
            include_devices=True,
            include_commands=True,
        )
        exchange.publish_runtime_snapshot(
            old_service.model_id,
            runtime,
            connection_signature=exchange._connection_signature(old_service),
        )
        old_generation = exchange.control_generation(old_service.model_id)
        self.assertTrue(exchange.control_snapshot(old_service.model_id).ready)

        registry.services[old_service.model_id] = new_service

        new_generation = exchange.control_generation(new_service.model_id)
        new_view = exchange.control_snapshot(new_service.model_id)
        with exchange.control_generation_guard(new_service.model_id, old_generation) as valid:
            old_generation_valid = bool(valid)

        self.assertNotEqual(new_generation, old_generation)
        self.assertFalse(new_view.ready)
        self.assertFalse(old_generation_valid)

    def test_generation_bound_dispatch_claim_rejects_retarget_before_transport(self):
        service = self.make_service()
        configure_receive(
            service,
            teacher_id="teacher-a",
            teacher_api_base="http://teacher-a.invalid",
        )
        runtime = service.snapshot(include_static=True, include_runtime_logs=False)
        calls = []
        exchange = TraineeRealtimeExchange(
            service,
            request_json=lambda url, **kwargs: calls.append((url, kwargs)) or {"set_values": 1},
            start_worker=False,
        )
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(
            service.model_id,
            runtime,
            connection_signature=exchange._connection_signature(service),
        )

        view = exchange.control_snapshot(service.model_id)
        self.assertIsNotNone(view.control_lease)
        with view.control_lease.guard() as validation:
            self.assertTrue(validation)
            dispatch_ticket = getattr(validation, "dispatch_ticket", None)
        self.assertIsNotNone(
            dispatch_ticket,
            "a valid control-generation claim must bind dispatch to that generation",
        )

        configure_receive(
            service,
            teacher_id="teacher-b",
            teacher_api_base="http://teacher-b.invalid",
        )
        exchange.receive_state_changed(service.model_id)

        with self.assertRaisesRegex(RuntimeError, "控制周期.*失效"):
            dispatch_ticket.submit({"set_values": [{"dev_name": "wind-1"}]})
        self.assertEqual(calls, [])

    def test_measurement_delta_uses_runtime_values_and_local_definition_fields(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
        )
        measurement_name = runtime["measurements"]["scada"][0]["name"]
        local_definition = next(
            row
            for row in runtime["measurements"]["definitions"]
            if row["name"] == measurement_name
        )
        runtime_definition = next(
            row
            for row in runtime["measurements"]["definitions"]
            if row["name"] == measurement_name
        )
        runtime_real = next(
            row for row in runtime["measurements"]["real"] if row["name"] == measurement_name
        )
        runtime_scada = next(
            row for row in runtime["measurements"]["scada"] if row["name"] == measurement_name
        )
        expected_valid = int(local_definition["valid"])
        expected_weight = float(local_definition["weight"])
        runtime_definition["valid"] = 0 if expected_valid else 1
        runtime_definition["weight"] = 999.0
        runtime_real["value"] = 12.5
        runtime_scada["value"] = 12.0
        runtime_scada["valid"] = 0 if expected_valid else 1
        runtime_scada["weight"] = 999.0
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)

        exchange.publish_runtime_snapshot("trainee-local", runtime)
        initial = exchange.measurement_delta("trainee-local", after_seq=0)
        initial_item = next(item for item in initial["items"] if item["name"] == measurement_name)

        self.assertTrue(initial["reset"])
        self.assertGreater(initial["seq"], 0)
        self.assertEqual(initial_item["value"], 12.0)
        self.assertEqual(initial_item["real_value"], 12.5)
        self.assertEqual(initial_item["scada_value"], 12.0)
        self.assertEqual(initial_item["valid"], expected_valid)
        self.assertEqual(float(initial_item["weight"]), expected_weight)

        unchanged = exchange.measurement_delta(
            "trainee-local",
            after_seq=initial["seq"],
        )
        self.assertEqual(unchanged["items"], [])

        changed_runtime = copy.deepcopy(runtime)
        next(
            row
            for row in changed_runtime["measurements"]["scada"]
            if row["name"] == measurement_name
        )["value"] = 13.0
        exchange.publish_runtime_snapshot("trainee-local", changed_runtime)
        delta = exchange.measurement_delta(
            "trainee-local",
            after_seq=initial["seq"],
        )

        self.assertFalse(delta["reset"])
        self.assertEqual([item["name"] for item in delta["items"]], [measurement_name])
        self.assertEqual(delta["items"][0]["scada_value"], 13.0)

    def test_compact_measurement_delta_uses_local_definition_order_without_names(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
        )
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(service.model_id, runtime)

        payload = exchange.measurement_delta(service.model_id, after_seq=0, compact=True)

        self.assertEqual(payload["encoding"], "measurement-arrays-v1")
        self.assertTrue(payload["frame"])
        self.assertEqual(payload["count"], len(runtime["measurements"]["definitions"]))
        self.assertEqual(len(payload["real_values"]), payload["count"])
        self.assertEqual(len(payload["scada_values"]), payload["count"])
        self.assertNotIn(
            runtime["measurements"]["definitions"][0]["name"],
            json.dumps(payload, ensure_ascii=False),
        )

    def test_compact_measurement_delta_sends_all_values_after_one_runtime_value_changes(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
        )
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(service.model_id, runtime)
        initial = exchange.measurement_delta(service.model_id, after_seq=0, compact=True)
        changed_runtime = copy.deepcopy(runtime)
        changed_name = changed_runtime["measurements"]["scada"][0]["name"]
        changed_index = next(
            index
            for index, definition in enumerate(changed_runtime["measurements"]["definitions"])
            if definition["name"] == changed_name
        )
        changed_runtime["measurements"]["scada"][0]["value"] = 37.5
        exchange.publish_runtime_snapshot(service.model_id, changed_runtime)

        changed = exchange.measurement_delta(
            service.model_id,
            after_seq=initial["seq"],
            compact=True,
        )

        self.assertTrue(changed["frame"])
        self.assertEqual(changed["count"], initial["count"])
        self.assertEqual(len(changed["real_values"]), changed["count"])
        self.assertEqual(len(changed["scada_values"]), changed["count"])
        self.assertEqual(changed["scada_values"][changed_index], 37.5)

    def test_compact_measurement_delta_propagates_status_and_fixed_value_changes(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
        )
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(service.model_id, runtime)
        initial = exchange.measurement_delta(service.model_id, after_seq=0, compact=True)

        changed_name = runtime["measurements"]["definitions"][0]["name"]
        service.update_measurement_definition(
            {
                "name": changed_name,
                "changes": {"status": "fixed", "fixed_value": 12.5},
            }
        )
        changed_runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
        )
        exchange.publish_runtime_snapshot(service.model_id, changed_runtime)

        changed = exchange.measurement_delta(
            service.model_id,
            after_seq=initial["seq"],
            compact=True,
        )

        self.assertTrue(changed["frame"])
        self.assertEqual(changed["status_values"][0], "fixed")
        self.assertEqual(changed["fixed_values"][0], 12.5)
        self.assertNotIn(changed_name, json.dumps(changed, ensure_ascii=False))

    def test_measurement_delta_at_current_sequence_skips_unneeded_state_copies(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
        )
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(service.model_id, runtime)
        initial = exchange.measurement_delta(service.model_id, after_seq=0)
        state = exchange._state_for_service(service)
        with state.lock:
            state.measurement_delta_state["__irrelevant__"] = {
                "name": "__irrelevant__",
                "payload": _DeepcopyBomb("current state must not be copied when already current"),
            }
            state.measurement_delta_history.insert(
                0,
                {
                    "seq": 0,
                    "items": [
                        {
                            "name": "__old__",
                            "payload": _DeepcopyBomb("history must not be copied when already current"),
                        }
                    ],
                },
            )
            state.runtime_snapshot["commands"] = _DeepcopyBomb(
                "unrelated runtime sections must not be copied for delta metadata"
            )

        unchanged = exchange.measurement_delta(
            service.model_id,
            after_seq=initial["seq"],
        )

        self.assertEqual(unchanged["items"], [])
        self.assertEqual(unchanged["seq"], initial["seq"])
        self.assertEqual(unchanged["time"], str(runtime["clock"]["time"]))

    def test_compact_measurement_frame_reads_owned_state_without_deepcopying_rows(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
        )
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(service.model_id, runtime)
        state = exchange._state_for_service(service)
        with state.lock:
            first_item = next(iter(state.measurement_delta_state.values()))
            first_item["unrelated"] = _DeepcopyBomb(
                "compact array encoding must not deep-copy owned measurement rows"
            )

        compact = exchange.measurement_delta(service.model_id, after_seq=0, compact=True)

        self.assertTrue(compact["frame"])
        self.assertEqual(len(compact["real_values"]), compact["count"])
        self.assertEqual(len(compact["scada_values"]), compact["count"])

    def test_measurement_delta_copies_only_batches_newer_than_requested_sequence(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
        )
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(service.model_id, runtime)
        state = exchange._state_for_service(service)
        with state.lock:
            state.measurement_delta_seq = 3
            state.measurement_delta_state = {
                "new": {"name": "new", "value": 3},
                "unused": {
                    "name": "unused",
                    "payload": _DeepcopyBomb("full current state must not be copied for a valid delta"),
                },
            }
            state.measurement_delta_history = [
                {
                    "seq": 1,
                    "items": [
                        {
                            "name": "old",
                            "payload": _DeepcopyBomb("old history batches must not be copied"),
                        }
                    ],
                },
                {"seq": 2, "items": [{"name": "middle", "value": 2}]},
                {"seq": 3, "items": [{"name": "new", "value": 3}]},
            ]

        delta = exchange.measurement_delta(service.model_id, after_seq=2)

        self.assertFalse(delta["reset"])
        self.assertEqual(delta["oldestSeq"], 1)
        self.assertEqual(delta["items"], [{"name": "new", "value": 3}])

    def test_snapshot_filters_the_shared_cache_without_refetching(self):
        service = self.make_service()
        configure_receive(service)
        runtime = service.snapshot(include_static=True, include_runtime_logs=True)
        calls = []
        exchange = TraineeRealtimeExchange(
            service,
            request_json=lambda url, **_kwargs: calls.append(url),
            start_worker=False,
        )
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot("trainee-local", runtime)

        payload = exchange.snapshot(
            "trainee-local",
            options={"measurements": "0", "commands": "0", "static": "0"},
        )

        self.assertNotIn("measurements", payload)
        self.assertNotIn("commands", payload)
        self.assertNotIn("definitions", payload)
        self.assertNotIn("settings", payload)
        self.assertNotIn("device_parameters", payload)
        self.assertEqual(calls, [])

    def test_snapshot_filters_cached_sections_before_copying_them(self):
        service = self.make_service()
        configure_receive(service)
        runtime = service.snapshot(include_static=True, include_runtime_logs=True)
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(service.model_id, runtime)
        state = exchange._state_for_service(service)
        excluded_keys = (
            "measurements",
            "devices",
            "device_states",
            "commands",
            "runtime_logs",
            *CONTROL_STATIC_FIELDS,
        )
        with state.lock:
            for key in excluded_keys:
                state.runtime_snapshot[key] = _DeepcopyBomb(
                    f"excluded snapshot section {key} must not be copied"
                )

        payload = exchange.snapshot(
            service.model_id,
            options={
                "measurements": "0",
                "devices": "0",
                "device_states": "0",
                "commands": "0",
                "logs": "0",
                "static": "0",
            },
        )

        for key in excluded_keys:
            self.assertNotIn(key, payload)
        self.assertEqual(payload["clock"], runtime["clock"])

    def test_snapshot_can_project_effective_commands_without_copying_history(self):
        service = self.make_service()
        configure_receive(service)
        runtime = service.snapshot(include_static=True, include_runtime_logs=False)
        runtime["commands"] = {
            "history": [
                {
                    "source": "performance-test",
                    "detail": "x" * 20000,
                }
            ],
            "effective": [{"source": "effective-test", "normalized": {}}],
        }
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(service.model_id, runtime)

        payload = exchange.snapshot(
            service.model_id,
            options={
                "measurements": "0",
                "devices": "0",
                "device_states": "0",
                "logs": "0",
                "static": "0",
                "commands": "1",
                "command_history": "0",
            },
        )

        self.assertEqual(payload["commands"]["history"], [])
        self.assertEqual(payload["commands"]["effective"], runtime["commands"]["effective"])

    def test_submit_commands_uses_learner_connection_and_preserves_payload(self):
        service = self.make_service()
        configure_receive(service)
        calls = []

        def request_json(url, **kwargs):
            calls.append((url, kwargs))
            return {"set_values": 1}

        exchange = TraineeRealtimeExchange(
            service,
            request_json=request_json,
            start_worker=False,
        )
        self.addCleanup(exchange.close)
        payload = {
            "model_id": "trainee-local",
            "source": "trainee-renewable-priority-backend",
            "set_values": [
                {
                    "dev_type": "ACGenerator",
                    "dev_name": "wind-1",
                    "set_type": "p_set",
                    "set_value": 8.0,
                }
            ],
        }
        original = copy.deepcopy(payload)

        result = exchange.submit_commands("trainee-local", payload)

        self.assertEqual(result["set_values"], 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("/api/student/commands", calls[0][0])
        self.assertEqual(calls[0][1]["method"], "POST")
        self.assertNotIn("model_id", calls[0][1]["payload"])
        self.assertEqual(calls[0][1]["payload"]["set_values"], payload["set_values"])
        self.assertEqual(payload, original)

    def test_submit_commands_rejects_inactive_receive_without_transport(self):
        service = self.make_service()
        calls = []
        exchange = TraineeRealtimeExchange(
            service,
            request_json=lambda *args, **kwargs: calls.append((args, kwargs)),
            start_worker=False,
        )
        self.addCleanup(exchange.close)

        with self.assertRaisesRegex(RuntimeError, "当前模型未启动接收"):
            exchange.submit_commands("trainee-local", {"set_values": []})

        self.assertEqual(calls, [])

    def test_command_diagnostics_record_success_and_failure(self):
        service = self.make_service()
        configure_receive(service)
        responses = [{"set_values": 2, "rejected": 1}, RuntimeError("command timeout")]

        def request_json(_url, **_kwargs):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        exchange = TraineeRealtimeExchange(service, request_json=request_json, start_worker=False)
        self.addCleanup(exchange.close)

        exchange.submit_commands(service.model_id, {"set_values": [{}, {}]})
        with self.assertRaisesRegex(RuntimeError, "timeout"):
            exchange.submit_commands(service.model_id, {"set_values": [{}]})
        diagnostics = exchange.receive_status(service.model_id)

        self.assertEqual(diagnostics["commandAttemptCount"], 2)
        self.assertEqual(diagnostics["commandSuccessCount"], 1)
        self.assertEqual(diagnostics["commandFailureCount"], 1)
        self.assertEqual(diagnostics["commandAcceptedCount"], 2)
        self.assertEqual(diagnostics["commandRejectedCount"], 1)
        self.assertEqual(diagnostics["commandAmbiguousFailureCount"], 1)
        self.assertIn("timeout", diagnostics["lastCommandError"])

    def test_worker_keeps_model_scoped_snapshots_isolated_without_browser_requests(self):
        service_a = self.make_service("learner-a")
        service_b = self.make_service("learner-b")
        configure_receive(
            service_a,
            teacher_id="teacher-a",
            teacher_api_base="http://teacher-a.invalid",
        )
        configure_receive(
            service_b,
            teacher_id="teacher-b",
            teacher_api_base="http://teacher-b.invalid",
        )
        runtime_a = service_a.snapshot(include_static=True, include_runtime_logs=False)
        runtime_b = service_b.snapshot(include_static=True, include_runtime_logs=False)
        runtime_a["clock"]["time"] = "01:00:00"
        runtime_b["clock"]["time"] = "02:00:00"
        calls = []

        def request_json(url, **_kwargs):
            calls.append(url)
            if "teacher-a.invalid" in url:
                return copy.deepcopy(runtime_a)
            if "teacher-b.invalid" in url:
                return copy.deepcopy(runtime_b)
            raise AssertionError(url)

        exchange = TraineeRealtimeExchange(
            ServiceRegistry([service_a, service_b]),
            request_json=request_json,
            poll_interval_seconds=0.05,
            start_worker=True,
        )
        self.addCleanup(exchange.close)

        deadline = time.time() + 2.0
        while time.time() < deadline:
            if (
                exchange.control_snapshot("learner-a").ready
                and exchange.control_snapshot("learner-b").ready
            ):
                break
            time.sleep(0.02)

        view_a = exchange.control_snapshot("learner-a")
        view_b = exchange.control_snapshot("learner-b")
        self.assertTrue(view_a.ready)
        self.assertTrue(view_b.ready)
        self.assertEqual(view_a.snapshot["clock"]["time"], "01:00:00")
        self.assertEqual(view_b.snapshot["clock"]["time"], "02:00:00")
        self.assertNotEqual(view_a.connection_signature, view_b.connection_signature)
        self.assertTrue(any("teacher-a.invalid" in url for url in calls))
        self.assertTrue(any("teacher-b.invalid" in url for url in calls))

        exchange.services.services.pop("learner-b")
        deadline = time.time() + 2.0
        while time.time() < deadline and "learner-b" in exchange._states:
            time.sleep(0.02)
        self.assertNotIn("learner-b", exchange._states)

    def test_slow_model_does_not_delay_other_model_refresh(self):
        service_a = self.make_service("learner-a")
        service_b = self.make_service("learner-b")
        configure_receive(service_a, teacher_id="teacher-a", teacher_api_base="http://teacher-a.invalid")
        configure_receive(service_b, teacher_id="teacher-b", teacher_api_base="http://teacher-b.invalid")
        runtime_a = service_a.snapshot(include_static=True, include_runtime_logs=False)
        runtime_b = service_b.snapshot(include_static=True, include_runtime_logs=False)
        blocked_started = threading.Event()
        release_blocked = threading.Event()

        def request_json(url, **_kwargs):
            if "teacher-a.invalid" in url:
                blocked_started.set()
                release_blocked.wait(2.0)
                return copy.deepcopy(runtime_a)
            if "teacher-b.invalid" in url:
                return copy.deepcopy(runtime_b)
            raise AssertionError(url)

        exchange = TraineeRealtimeExchange(
            ServiceRegistry([service_a, service_b]),
            request_json=request_json,
            poll_interval_seconds=0.05,
            start_worker=True,
        )
        self.addCleanup(exchange.close)
        self.addCleanup(release_blocked.set)
        self.assertTrue(blocked_started.wait(1.0))

        deadline = time.time() + 0.4
        while time.time() < deadline and not exchange.control_snapshot("learner-b").ready:
            time.sleep(0.01)

        self.assertTrue(exchange.control_snapshot("learner-b").ready)
        self.assertFalse(exchange.control_snapshot("learner-a").ready)

    def test_close_waits_for_running_refresh_before_returning(self):
        service = self.make_service("learner-close")
        configure_receive(service, teacher_id="teacher-close", teacher_api_base="http://teacher-close.invalid")
        runtime = service.snapshot(include_static=True, include_runtime_logs=False)
        refresh_started = threading.Event()
        release_refresh = threading.Event()
        close_started = threading.Event()
        close_returned = threading.Event()

        def request_json(url, **_kwargs):
            self.assertIn("teacher-close.invalid", url)
            refresh_started.set()
            self.assertTrue(release_refresh.wait(timeout=3.0))
            return copy.deepcopy(runtime)

        exchange = TraineeRealtimeExchange(
            service,
            request_json=request_json,
            start_worker=False,
        )
        self.assertTrue(exchange._submit_refresh(service.model_id))
        self.assertTrue(refresh_started.wait(timeout=2.0))

        def close_exchange():
            close_started.set()
            exchange.close()
            close_returned.set()

        close_thread = threading.Thread(target=close_exchange, daemon=True)
        close_thread.start()
        try:
            self.assertTrue(close_started.wait(timeout=1.0))
            self.assertFalse(
                close_returned.wait(timeout=0.2),
                "close returned while a refresh future was still running",
            )
            release_refresh.set()
            close_thread.join(timeout=3.0)
            self.assertFalse(close_thread.is_alive())
        finally:
            release_refresh.set()
            close_thread.join(timeout=3.0)

        self.assertTrue(close_returned.is_set())
        self.assertEqual(exchange._refresh_pending, set())

    def test_worker_registry_failure_preserves_existing_model_cache(self):
        service = self.make_service("learner-a")
        configure_receive(service)
        registry = ServiceRegistry([service])
        exchange = TraineeRealtimeExchange(registry, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(
            service.model_id,
            service.snapshot(include_static=True, include_runtime_logs=False),
            connection_signature=exchange._connection_signature(service),
        )

        class OneIterationStop:
            def __init__(self):
                self.checks = 0
                self.forced = False

            def is_set(self):
                if self.forced:
                    return True
                self.checks += 1
                return self.checks > 1

            def wait(self, _timeout):
                return True

            def set(self):
                self.forced = True

        registry.fail_enumeration = True
        exchange._stop_event = OneIterationStop()

        exchange._worker_loop()

        self.assertIn(service.model_id, exchange._states)
        self.assertTrue(exchange.control_snapshot(service.model_id).ready)

    def test_receive_status_detects_frozen_frame_without_blocking_observation(self):
        service = self.make_service()
        configure_receive(service)
        runtime = service.snapshot(include_static=True, include_runtime_logs=False)
        exchange = TraineeRealtimeExchange(
            service,
            start_worker=False,
            frame_age_limit_seconds=10.0,
            same_frame_limit_seconds=0.01,
        )
        self.addCleanup(exchange.close)

        exchange.publish_runtime_snapshot(
            service.model_id,
            runtime,
            connection_signature=exchange._connection_signature(service),
        )
        time.sleep(0.02)
        exchange.publish_runtime_snapshot(
            service.model_id,
            runtime,
            connection_signature=exchange._connection_signature(service),
        )

        frozen = exchange.receive_status(service.model_id)
        self.assertTrue(frozen["canCalculate"])
        self.assertTrue(frozen["canRun"])
        self.assertFalse(frozen["canDispatch"])
        self.assertTrue(frozen["frameFrozen"])
        self.assertIn("冻结", frozen["dispatchStatus"])

        advanced = copy.deepcopy(runtime)
        advanced["clock"]["time"] = "advanced-frame"
        exchange.publish_runtime_snapshot(
            service.model_id,
            advanced,
            connection_signature=exchange._connection_signature(service),
        )
        recovered = exchange.receive_status(service.model_id)
        self.assertTrue(recovered["canDispatch"])
        self.assertFalse(recovered["frameFrozen"])

    def test_receive_status_does_not_build_a_full_control_snapshot(self):
        service = self.make_service()
        configure_receive(service)
        runtime = service.snapshot(include_static=True, include_runtime_logs=False)
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        self.addCleanup(exchange.close)
        exchange.publish_runtime_snapshot(
            service.model_id,
            runtime,
            connection_signature=exchange._connection_signature(service),
        )

        service.snapshot = lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("receive_status must not build the merged control snapshot")
        )

        status = exchange.receive_status(service.model_id)

        self.assertTrue(status["ready"])
        self.assertTrue(status["canCalculate"])

    def test_measurement_delta_reports_history_expiration_and_oldest_sequence(self):
        service = self.make_service()
        runtime = service.snapshot(
            include_static=True,
            include_runtime_logs=False,
            include_measurements=True,
        )
        measurement_name = runtime["measurements"]["scada"][0]["name"]
        exchange = TraineeRealtimeExchange(
            service,
            start_worker=False,
            measurement_delta_history_limit=2,
        )
        self.addCleanup(exchange.close)

        sequences = []
        for value in (1.0, 2.0, 3.0, 4.0):
            candidate = copy.deepcopy(runtime)
            next(
                row
                for row in candidate["measurements"]["scada"]
                if row["name"] == measurement_name
            )["value"] = value
            exchange.publish_runtime_snapshot(service.model_id, candidate)
            sequences.append(exchange.measurement_delta(service.model_id)["seq"])

        expired = exchange.measurement_delta(service.model_id, after_seq=sequences[0])

        self.assertTrue(expired["reset"])
        self.assertEqual(expired["resetReason"], "history_expired")
        self.assertEqual(expired["oldestSeq"], sequences[-2])

    def test_diagnostics_api_exposes_realtime_freshness_metadata(self):
        service = self.make_service()
        configure_receive(service)
        exchange = TraineeRealtimeExchange(service, start_worker=False)
        exchange.publish_runtime_snapshot(
            service.model_id,
            service.snapshot(include_static=True, include_runtime_logs=False),
            connection_signature=exchange._connection_signature(service),
        )
        server = make_http_server(
            ("127.0.0.1", 0),
            service,
            role="trainee",
            trainee_exchange=exchange,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(
                f"http://127.0.0.1:{server.server_address[1]}/api/trainee/diagnostics?model_id={service.model_id}",
                timeout=5,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)

        self.assertTrue(payload["ready"])
        self.assertIn("canDispatch", payload)
        self.assertIn("frameIdentity", payload)
        self.assertIn("consecutiveFailures", payload)

    def test_server_closes_control_consumer_before_exchange_provider(self):
        service = self.make_service()
        closed = []

        class FakeExchange:
            def close(self):
                closed.append("exchange")

        class FakeManager:
            def close(self):
                closed.append("renewable")

        server = make_http_server(
            ("127.0.0.1", 0),
            service,
            role="trainee",
            trainee_exchange=FakeExchange(),
            renewable_control_manager=FakeManager(),
        )

        server.server_close()

        self.assertEqual(closed, ["renewable", "exchange"])

    def test_server_restart_repopulates_active_exchange_without_browser_and_leaves_inactive_empty(self):
        active = self.make_service("active-learner")
        inactive = self.make_service("inactive-learner")
        configure_receive(
            active,
            teacher_id="teacher-active",
            teacher_api_base="http://teacher-active.invalid",
        )
        runtime = active.snapshot(include_static=True, include_runtime_logs=False)
        runtime["clock"]["time"] = "03:00:00"
        registry = ServiceRegistry([active, inactive])
        calls = []

        def request_json(url, **_kwargs):
            calls.append(url)
            return copy.deepcopy(runtime)

        first_exchange = TraineeRealtimeExchange(
            registry,
            request_json=request_json,
            poll_interval_seconds=0.05,
            start_worker=True,
        )
        first_server = make_http_server(
            ("127.0.0.1", 0),
            registry,
            role="trainee",
            trainee_exchange=first_exchange,
        )
        deadline = time.time() + 2.0
        while time.time() < deadline and not first_exchange.control_snapshot("active-learner").ready:
            time.sleep(0.02)
        self.assertTrue(first_exchange.control_snapshot("active-learner").ready)
        first_server.server_close()

        calls_before_restart = len(calls)
        second_exchange = TraineeRealtimeExchange(
            registry,
            request_json=request_json,
            poll_interval_seconds=0.05,
            start_worker=True,
        )
        second_server = make_http_server(
            ("127.0.0.1", 0),
            registry,
            role="trainee",
            trainee_exchange=second_exchange,
        )
        try:
            deadline = time.time() + 2.0
            while time.time() < deadline and not second_exchange.control_snapshot("active-learner").ready:
                time.sleep(0.02)

            self.assertTrue(second_exchange.control_snapshot("active-learner").ready)
            self.assertEqual(
                second_exchange.control_snapshot("active-learner").snapshot["clock"]["time"],
                "03:00:00",
            )
            self.assertFalse(second_exchange.control_snapshot("inactive-learner").ready)
            self.assertGreater(len(calls), calls_before_restart)
        finally:
            second_server.server_close()


if __name__ == "__main__":
    unittest.main()
