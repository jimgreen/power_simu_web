"""Legacy opt-in process runner; production WEB services run embedded."""

from __future__ import annotations

import multiprocessing
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutureTimeoutError
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, replace
from typing import Any, Optional

import simu_loop


@dataclass(frozen=True)
class PowerFlowExecution:
    result: Any
    runtime_stat_book: Any
    worker_pid: int
    compute_seconds: float
    round_trip_seconds: float
    mode: str


class PowerFlowTimeoutError(TimeoutError):
    """Raised after a stalled load-flow worker has been terminated and replaced."""

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = float(timeout_seconds)
        super().__init__(f"Power-flow calculation exceeded {self.timeout_seconds:g} seconds")


def _run_power_flow(config: simu_loop.SimulationConfig) -> PowerFlowExecution:
    started = time.perf_counter()
    result = simu_loop.run_once(config)
    elapsed = max(0.0, time.perf_counter() - started)
    return PowerFlowExecution(
        result=result,
        runtime_stat_book=config.dev_stat_book,
        worker_pid=os.getpid(),
        compute_seconds=elapsed,
        round_trip_seconds=elapsed,
        mode="process",
    )


class PowerFlowProcessRunner:
    """Restartable compatibility runner retained for isolated tests and tools."""

    def __init__(self, max_workers: int = 1, *, timeout_seconds: float = 30.0) -> None:
        self.max_workers = max(1, int(max_workers))
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0.0:
            raise ValueError("Power-flow timeout must be greater than zero")
        self._context = multiprocessing.get_context("spawn")
        self._lock = threading.RLock()
        self._closed = False
        self._executor = self._new_executor()
        self._last_worker_pid = 0
        self._restart_count = 0
        self._timeout_count = 0
        self._last_timeout_at = 0.0
        self._last_timed_out_worker_pid = 0
        self._last_restart_reason = ""

    def _new_executor(self) -> ProcessPoolExecutor:
        return ProcessPoolExecutor(
            max_workers=self.max_workers,
            mp_context=self._context,
        )

    def _active_executor(self) -> ProcessPoolExecutor:
        with self._lock:
            if self._closed:
                raise RuntimeError("Power-flow process runner is closed")
            return self._executor

    @staticmethod
    def _executor_processes(executor: ProcessPoolExecutor) -> list[Any]:
        processes = getattr(executor, "_processes", None)
        return list(processes.values()) if isinstance(processes, dict) else []

    @classmethod
    def _terminate_executor(cls, executor: ProcessPoolExecutor) -> None:
        processes = cls._executor_processes(executor)
        for process in processes:
            try:
                if process.is_alive():
                    process.terminate()
            except (AssertionError, OSError, ValueError):
                continue
        executor.shutdown(wait=False, cancel_futures=True)
        for process in processes:
            try:
                process.join(timeout=0.5)
                if process.is_alive() and callable(getattr(process, "kill", None)):
                    process.kill()
                    process.join(timeout=0.5)
            except (AssertionError, OSError, ValueError):
                continue

    def _replace_executor(self, failed: ProcessPoolExecutor, *, reason: str) -> bool:
        with self._lock:
            if self._closed or self._executor is not failed:
                return False
            self._executor = self._new_executor()
            self._restart_count += 1
            self._last_restart_reason = str(reason)
        self._terminate_executor(failed)
        return True

    def _record_timeout(self, executor: ProcessPoolExecutor) -> None:
        process_ids = [
            int(getattr(process, "pid", 0) or 0)
            for process in self._executor_processes(executor)
        ]
        with self._lock:
            self._timeout_count += 1
            self._last_timeout_at = time.time()
            self._last_timed_out_worker_pid = next(
                (pid for pid in process_ids if pid > 0),
                0,
            )

    def run(self, config: simu_loop.SimulationConfig) -> PowerFlowExecution:
        round_trip_started = time.perf_counter()
        for attempt in range(2):
            executor = self._active_executor()
            try:
                future = executor.submit(_run_power_flow, config)
                outcome = future.result(timeout=self.timeout_seconds)
                round_trip = max(0.0, time.perf_counter() - round_trip_started)
                with self._lock:
                    self._last_worker_pid = int(outcome.worker_pid)
                return replace(outcome, round_trip_seconds=round_trip)
            except FutureTimeoutError as exc:
                if future.done():
                    raise
                future.cancel()
                self._record_timeout(executor)
                self._replace_executor(executor, reason="timeout")
                raise PowerFlowTimeoutError(self.timeout_seconds) from exc
            except BrokenProcessPool:
                self._replace_executor(executor, reason="broken_process_pool")
                if attempt:
                    raise
        raise RuntimeError("Power-flow process worker could not be restarted")

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mode": "process",
                "workers": self.max_workers,
                "worker_pid": self._last_worker_pid,
                "restart_count": self._restart_count,
                "timeout_seconds": self.timeout_seconds,
                "timeout_count": self._timeout_count,
                "last_timeout_at": self._last_timeout_at,
                "last_timed_out_worker_pid": self._last_timed_out_worker_pid,
                "last_restart_reason": self._last_restart_reason,
                "closed": self._closed,
            }

    def close(self, *, wait: bool = True) -> None:
        executor: Optional[ProcessPoolExecutor]
        with self._lock:
            if self._closed:
                return
            self._closed = True
            executor = self._executor
        executor.shutdown(wait=wait, cancel_futures=True)
