"""Heartbeat reporting in a dedicated subprocess.

Task processing runs on a single asyncio event loop shared by every worker. A
long, blocking/CPU-bound section starves that loop, so an in-loop heartbeat
coroutine cannot report on time and the backend re-claims the task as stale.

To make heartbeats immune to that starvation we run them in their own OS
process. One shared child process serves every worker in the container: a
worker runs its in-flight work through ``HeartbeatReporter.run_owned()``, which
registers the task over a command queue, and the child POSTs heartbeats on a
fixed cadence with a synchronous HTTP client. When the backend reports we no
longer own a task, the child pushes an event back to the parent, which cancels
the in-flight work on the main loop and surfaces it as ``LostOwnershipError``.

``run_owned`` wraps the work in a dedicated asyncio task, so the reporter's
cancel targets exactly the work and nothing else: a cancel that loses a race
with the work finishing lands on a completed task and is a no-op.

The child is spawned (not forked) so it does not inherit the parent's running
event loop / OTel / httpx threads, which is deadlock-prone. If the child dies,
the parent restarts it and re-registers the in-flight tasks.
"""

import asyncio
import dataclasses
import multiprocessing
import multiprocessing.process
import queue as _queue
import threading
import time
from collections.abc import Coroutine
from multiprocessing import Queue
from typing import Any, TypeVar

import httpx

from common.logger import get_logger

# Messages carried on each IPC queue. Every message carries the worker_uid so
# both sides can ignore messages about a previous registrant of the same task
# id (the backend may re-queue a reclaimed task and another worker in this
# container may claim it while the old run is still winding down).
Command = tuple[str, str, str]  # ("register" | "deregister", task_id, worker_uid)
Event = tuple[str, str, str]  # ("lost_ownership", task_id, worker_uid)
TaskKey = tuple[str, str]  # (task_id, worker_uid)

HEARTBEAT_INTERVAL_SECONDS = 5

# Per-request timeout for heartbeat POSTs. The backend re-claims a task when it
# sees no heartbeat for the stale timeout (30s by default), and the child POSTs
# serially, so hung requests must not hold up the other tasks' beats past that
# threshold.
HEARTBEAT_REQUEST_TIMEOUT_SECONDS = 2

_CHILD_CHECK_INTERVAL_SECONDS = 5

_STOP = None

T = TypeVar("T")


@dataclasses.dataclass
class _InFlight:
    """Parent-side record of a task currently inside ``run_owned()``."""

    task: asyncio.Task
    worker_uid: str  # so we can re-register with a restarted child
    lost: bool = False  # cancel was reporter-initiated (vs. task/caller cancel)


class LostOwnershipError(Exception):
    """The backend reported we no longer own the task (e.g. the user canceled
    it, or it was reclaimed as stale); the in-flight work was aborted."""

    def __init__(self, task_id: str, worker_uid: str):
        super().__init__(f"Lost ownership of task {task_id} for worker {worker_uid}")
        self.task_id = task_id
        self.worker_uid = worker_uid


def heartbeat_worker_main(
    base_url: str,
    interval: int,
    command_q: "Queue[Command | None]",
    event_q: "Queue[Event | None]",
) -> None:
    """Entry point for the heartbeat child process (must be importable at module
    level so it is picklable under the ``spawn`` start method)."""
    logger = get_logger("heartbeat_process")
    active: set[TaskKey] = set()

    with httpx.Client(
        base_url=base_url,
        transport=httpx.HTTPTransport(retries=3),
        timeout=HEARTBEAT_REQUEST_TIMEOUT_SECONDS,
    ) as client:
        next_beat = time.monotonic()
        while True:
            now = time.monotonic()
            if now >= next_beat:
                next_beat = now + interval
                for task_id, worker_uid in list(active):
                    try:
                        response = client.post(
                            f"/internal/api/v1/wizard/tasks/{task_id}/heartbeat",
                            json={"worker_id": worker_uid},
                        )
                        response.raise_for_status()
                        owned = response.json().get("owned")
                    except Exception as e:
                        logger.warning(
                            f"Failed to report heartbeat for task {task_id}: {e}"
                        )
                        continue
                    if owned is False:
                        logger.warning(
                            f"Lost ownership of task {task_id}; notifying parent"
                        )
                        active.discard((task_id, worker_uid))
                        event_q.put(("lost_ownership", task_id, worker_uid))
                continue

            try:
                cmd = command_q.get(timeout=next_beat - now)
            except _queue.Empty:
                continue
            if cmd is _STOP:
                logger.info("Heartbeat process shutting down")
                return
            action, task_id, worker_uid = cmd
            if action == "register":
                active.add((task_id, worker_uid))
            elif action == "deregister":
                active.discard((task_id, worker_uid))


class HeartbeatReporter:
    """Parent-side manager for the shared heartbeat subprocess.

    Owns the IPC queues, the child process, and a daemon thread that turns
    lost-ownership events from the child into task cancellations on the main
    event loop. Constructed once per worker container and shared by all workers.
    """

    def __init__(self, base_url: str, interval: int, loop: asyncio.AbstractEventLoop):
        self._base_url = base_url
        self._interval = interval
        self._loop = loop
        self._ctx = multiprocessing.get_context("spawn")
        self._command_q: "Queue[Command | None]" = self._ctx.Queue()
        self._event_q: "Queue[Event | None]" = self._ctx.Queue()
        self._process: multiprocessing.process.BaseProcess | None = None
        self._drain_thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._tasks: dict[TaskKey, _InFlight] = {}
        self._lock = threading.Lock()
        self._logger = get_logger("heartbeat_reporter")

    def start(self) -> None:
        self._start_child()
        self._drain_thread = threading.Thread(
            target=self._drain_events, name="heartbeat-event-drain", daemon=True
        )
        self._drain_thread.start()

    def _start_child(self) -> None:
        self._process = self._ctx.Process(
            target=heartbeat_worker_main,
            args=(self._base_url, self._interval, self._command_q, self._event_q),
            name="heartbeat-reporter",
            daemon=True,
        )
        self._process.start()
        self._logger.info(
            f"Started heartbeat process (pid={self._process.pid}, interval={self._interval}s)"
        )

    async def run_owned(
        self, task_id: str, worker_uid: str, coro: Coroutine[Any, Any, T]
    ) -> T:
        """Run ``coro`` as a dedicated task while we own ``task_id``, reporting
        heartbeats for it.

        If the backend reports we no longer own the task, the reporter cancels
        the work and this raises :class:`LostOwnershipError`; a cancellation of
        the caller (e.g. shutdown) cancels the work and propagates unchanged.
        """
        work_task = asyncio.ensure_future(coro)
        key = (task_id, worker_uid)
        with self._lock:
            assert key not in self._tasks
            self._tasks[key] = _InFlight(work_task, worker_uid)
            self._command_q.put(("register", task_id, worker_uid))
        try:
            return await work_task
        except asyncio.CancelledError:
            with self._lock:
                lost = self._tasks[key].lost
            current = asyncio.current_task()
            assert current is not None
            if lost and current.cancelling() == 0:
                raise LostOwnershipError(task_id, worker_uid) from None
            raise
        finally:
            with self._lock:
                del self._tasks[key]
                self._command_q.put(("deregister", task_id, worker_uid))

    def _drain_events(self) -> None:
        """Blocking loop (own thread): apply lost-ownership events by cancelling
        the in-flight work task on the main loop. asyncio objects are not
        thread-safe, so we hop back onto the loop via ``call_soon_threadsafe``.
        Doubles as the child's watchdog: if the child dies, restart it and
        re-register the in-flight tasks."""
        while True:
            try:
                evt = self._event_q.get(timeout=_CHILD_CHECK_INTERVAL_SECONDS)
            except _queue.Empty:
                self._check_child()
                continue
            if evt is _STOP:
                return
            action, task_id, worker_uid = evt
            if action != "lost_ownership":
                continue
            key = (task_id, worker_uid)
            with self._lock:
                entry = self._tasks.get(key)
                if entry is None:
                    # No longer registered.
                    continue
                entry.lost = True
                work_task = entry.task
            try:
                self._loop.call_soon_threadsafe(work_task.cancel)
            except RuntimeError:
                # Loop already closed (shutdown); nothing left to cancel.
                return

    def _check_child(self) -> None:
        """Restart the child if it died, then re-register in-flight tasks so
        their heartbeats resume. Until the restart the backend may already have
        re-claimed them; the resumed beats then report ``owned: false`` and the
        tasks are cancelled through the normal lost-ownership path."""
        if self._stopping.is_set() or self._process is None or self._process.is_alive():
            return
        self._logger.error(
            f"Heartbeat process died (exitcode={self._process.exitcode}); restarting"
        )
        self._start_child()
        with self._lock:
            for task_id, worker_uid in self._tasks:
                self._command_q.put(("register", task_id, worker_uid))

    def stop(self) -> None:
        """Best-effort teardown. The child is a daemon, so it also dies with the
        parent if this is skipped on a hard kill."""
        self._stopping.set()
        try:
            self._command_q.put(_STOP)
        except Exception:
            pass
        # Unblock the drain thread's blocking get().
        try:
            self._event_q.put(_STOP)
        except Exception:
            pass
        if self._process is not None:
            self._process.join(timeout=5)
            if self._process.is_alive():
                self._process.terminate()
