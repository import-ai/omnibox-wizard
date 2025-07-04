from datetime import datetime

from fastapi import APIRouter

from omnibox.wizard.api.wizard import wizard_router

started_at: datetime = datetime.now()
v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(wizard_router)


@v1_router.get("/health", tags=["Metrics"])
async def api_v1_health():
    return {"status": 200, "uptime": str(datetime.now() - started_at)}
