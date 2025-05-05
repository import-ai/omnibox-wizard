from datetime import datetime

from fastapi import APIRouter

from wizard.api.grimoire import grimoire_router

started_at: datetime = datetime.now()
v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(grimoire_router)


@v1_router.get("/health", tags=["Metrics"])
async def api_v1_health():
    return {"status": 200, "uptime": str(datetime.now() - started_at)}
