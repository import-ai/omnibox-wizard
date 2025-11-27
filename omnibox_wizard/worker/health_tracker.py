import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional


@dataclass
class WorkerHealth:
    worker_id: int
    status: str  # "running", "idle", "error"
    last_heartbeat: datetime
    last_task_at: Optional[datetime] = None
    error_count: int = 0
    total_tasks: int = 0


class HealthTracker:
    def __init__(self):
        self._workers: Dict[int, WorkerHealth] = {}
        self._lock = threading.Lock()
        self._started_at = datetime.now()

    def register_worker(self, worker_id: int):
        with self._lock:
            self._workers[worker_id] = WorkerHealth(
                worker_id=worker_id, status="idle", last_heartbeat=datetime.now()
            )

    def update_worker_status(
        self, worker_id: int, status: str, last_task_at: Optional[datetime] = None
    ):
        with self._lock:
            if worker_id in self._workers:
                worker = self._workers[worker_id]
                worker.status = status
                worker.last_heartbeat = datetime.now()
                if last_task_at:
                    worker.last_task_at = last_task_at
                if status == "running":
                    worker.total_tasks += 1

    def increment_error_count(self, worker_id: int):
        with self._lock:
            if worker_id in self._workers:
                self._workers[worker_id].error_count += 1

    def get_health_status(self) -> Dict:
        with self._lock:
            now = datetime.now()
            uptime = str(now - self._started_at)

            healthy_workers = 0
            total_workers = len(self._workers)
            worker_details = []

            for worker in self._workers.values():
                # Consider worker unhealthy if no heartbeat in last 30 seconds
                is_healthy = (now - worker.last_heartbeat).total_seconds() < 30
                if is_healthy:
                    healthy_workers += 1

                worker_details.append(
                    {
                        "worker_id": worker.worker_id,
                        "status": worker.status,
                        "healthy": is_healthy,
                        "last_heartbeat": worker.last_heartbeat.isoformat(),
                        "last_task_at": worker.last_task_at.isoformat()
                        if worker.last_task_at
                        else None,
                        "error_count": worker.error_count,
                        "total_tasks": worker.total_tasks,
                    }
                )

            overall_healthy = healthy_workers == total_workers and total_workers > 0

            return {
                "status": "healthy" if overall_healthy else "unhealthy",
                "uptime": uptime,
                "started_at": self._started_at.isoformat(),
                "workers": {
                    "total": total_workers,
                    "healthy": healthy_workers,
                    "details": worker_details,
                },
            }
