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

# How often to report a heartbeat to the backend while a task is running.
HEARTBEAT_INTERVAL_SECONDS = 5

# Per-request timeout for heartbeat POSTs. The backend re-claims a task when it
# sees no heartbeat for OBB_TASK_HEARTBEAT_TIMEOUT_MS (30s in our deployments),
# and the child POSTs serially, so hung requests must not be able to hold up
# the other tasks' beats past that threshold.
HEARTBEAT_REQUEST_TIMEOUT_SECONDS = 5

# How often the parent's drain thread checks that the child is still alive.
_CHILD_CHECK_INTERVAL_SECONDS = 5

# Sentinel placed on a queue to tell the receiving loop to exit. Each queue only
# ever carries its own message tuples, so ``None`` is unambiguous as a stop mark.
_STOP = None

T = TypeVar("T")


@dataclasses.dataclass
class _InFlight:
    """Parent-side record of a task currently inside ``run_owned()``."""

    task: asyncio.Task  # the dedicated work task, so we can cancel it
    worker_uid: str  # so we can re-register with a restarted child
    lost: bool = False  # cancel was reporter-initiated (vs. e.g. shutdown)


class LostOwnershipError(Exception):
    """The backend reported we no longer own the task (e.g. the user canceled
    it, or it was reclaimed as stale); the in-flight work was aborted."""

    def __init__(self, task_id: str):
        super().__init__(f"Lost ownership of task {task_id}")
        self.task_id = task_id


def heartbeat_worker_main(
    base_url: str,
    interval: int,
    command_q: "Queue[Command | None]",
    event_q: "Queue[Event | None]",
) -> None:
    """Entry point for the heartbeat child process (must be importable at module
    level so it is picklable under the ``spawn`` start method).

    Commands received on ``command_q``:
      ``("register", task_id, worker_uid)`` / ``("deregister", task_id, worker_uid)``
      / ``None`` (stop)
    Events emitted on ``event_q``:
      ``("lost_ownership", task_id, worker_uid)``
    """
    logger = get_logger("heartbeat_process")
    active: dict[str, str] = {}

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
                for task_id, worker_uid in list(active.items()):
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
                        active.pop(task_id, None)
                        event_q.put(("lost_ownership", task_id, worker_uid))
                continue

            # Wait for the next command, but no longer than the next beat is due.
            try:
                cmd = command_q.get(timeout=next_beat - now)
            except _queue.Empty:
                continue
            if cmd is _STOP:
                logger.info("Heartbeat process shutting down")
                return
            action, task_id, worker_uid = cmd
            if action == "register":
                active[task_id] = worker_uid
            elif action == "deregister" and active.get(task_id) == worker_uid:
                # Only the current registrant may deregister: a worker winding
                # down late must not clobber a re-claimant's registration.
                del active[task_id]


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
        self._tasks: dict[str, _InFlight] = {}
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
        with self._lock:
            self._tasks[task_id] = _InFlight(work_task, worker_uid)
        self._command_q.put(("register", task_id, worker_uid))
        try:
            return await work_task
        except asyncio.CancelledError:
            with self._lock:
                entry = self._tasks.get(task_id)
                # Identity check: a re-claimant of the same task id may have
                # replaced our entry; its flag says nothing about us.
                if entry is None or entry.task is not work_task or not entry.lost:
                    # The caller was cancelled (e.g. shutdown): make sure the
                    # work dies too (a no-op if awaiting already cancelled it).
                    work_task.cancel()
                    raise
            current = asyncio.current_task()
            assert current is not None
            if current.cancelling() > 0:
                # A cancellation of the caller raced our lost-ownership cancel;
                # shutdown wins.
                raise
            raise LostOwnershipError(task_id) from None
        finally:
            with self._lock:
                entry = self._tasks.get(task_id)
                if entry is not None and entry.task is work_task:
                    del self._tasks[task_id]
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
            with self._lock:
                entry = self._tasks.get(task_id)
                if entry is None or entry.worker_uid != worker_uid:
                    # No longer registered, or the event is about a previous
                    # registrant of this task id.
                    continue
                # Mark before scheduling the cancel so ``run_owned()`` sees
                # the flag when the CancelledError reaches it.
                entry.lost = True
                work_task = entry.task
            try:
                # The cancel targets exactly the work task; if it already
                # finished by the time this runs, cancelling it is a no-op.
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
            in_flight = [(tid, e.worker_uid) for tid, e in self._tasks.items()]
        for task_id, worker_uid in in_flight:
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
