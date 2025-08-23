from datetime import datetime

import uvicorn
from fastapi import FastAPI, Response

from omnibox_wizard.worker.health_tracker import HealthTracker


class HealthServer:
    def __init__(self, health_tracker: HealthTracker, port: int = 8000):
        self.health_tracker = health_tracker
        self.port = port
        self.app = FastAPI(title="Worker Health Check", version="1.0.0")
        self._setup_routes()

    def _setup_routes(self):
        @self.app.get("/health")
        async def health_check(response: Response):
            health_status = self.health_tracker.get_health_status()

            if health_status["status"] == "unhealthy":
                response.status_code = 503

            return health_status

        @self.app.get("/")
        async def root():
            return {"message": "Worker Health Check Server", "timestamp": datetime.now().isoformat()}

    async def start(self):
        config = uvicorn.Config(
            app=self.app,
            host="0.0.0.0",
            port=self.port,
            log_level="warning",
            access_log=False
        )
        server = uvicorn.Server(config)
        await server.serve()
