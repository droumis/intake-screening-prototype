"""Pipeline run queue — serialized background execution."""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

from pisa.model.ollama import OllamaProvider
from pisa.parser.models import ApplicantRecord
from pisa.pipeline.runner import PipelineResult, ProgressCallback, run_pipeline
from pisa.profile.models import ScreeningProfile

logger = logging.getLogger(__name__)


@dataclass
class QueuedRun:
    record: ApplicantRecord
    profile: ScreeningProfile
    provider: OllamaProvider
    progress: ProgressCallback
    on_complete: Optional[Callable[[PipelineResult], None]] = None
    result: Optional[PipelineResult] = None


class PipelineQueue:
    """Serialized pipeline run queue executed on a background thread."""

    def __init__(self):
        self._queue: deque[QueuedRun] = deque()
        self._current: Optional[QueuedRun] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._cancelled = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._current is not None

    @property
    def queue_length(self) -> int:
        return len(self._queue)

    @property
    def current_result(self) -> Optional[PipelineResult]:
        if self._current and self._current.result:
            return self._current.result
        return None

    def enqueue(
        self,
        record: ApplicantRecord,
        profile: ScreeningProfile,
        provider: OllamaProvider,
        progress: Optional[ProgressCallback] = None,
        on_complete: Optional[Callable[[PipelineResult], None]] = None,
    ) -> str:
        """Add a run to the queue. Returns the run_id."""
        if progress is None:
            progress = ProgressCallback()

        run = QueuedRun(
            record=record,
            profile=profile,
            provider=provider,
            progress=progress,
            on_complete=on_complete,
        )

        with self._lock:
            self._queue.append(run)

        self._ensure_worker()
        return ""  # run_id assigned when execution starts

    def cancel(self):
        """Cancel all pending runs and signal the current run to stop."""
        self._cancelled.set()
        with self._lock:
            self._queue.clear()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def _ensure_worker(self):
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._running = True
                self._cancelled.clear()
                self._thread = threading.Thread(target=self._worker, daemon=True)
                self._thread.start()

    def _worker(self):
        while True:
            with self._lock:
                if self._cancelled.is_set() or not self._queue:
                    self._running = False
                    self._current = None
                    self._cancelled.clear()
                    return
                self._current = self._queue.popleft()

            run = self._current
            try:
                result = run_pipeline(
                    record=run.record,
                    profile=run.profile,
                    provider=run.provider,
                    progress=run.progress,
                )
                run.result = result
                if not self._cancelled.is_set() and run.on_complete:
                    run.on_complete(result)
            except Exception as e:
                logger.error(f"Pipeline run failed: {e}")
                if run.result is None:
                    run.result = PipelineResult()
                run.result.status = "incomplete"
                run.result.notes = f"Fatal error: {e}"
                if not self._cancelled.is_set():
                    run.progress.on_failure(run.result, str(e))

            with self._lock:
                self._current = None


# Module-level singleton
pipeline_queue = PipelineQueue()
