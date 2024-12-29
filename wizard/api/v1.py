from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body

from wizard.api.tasks import task_router
from wizard.api.grimoire import grimoire_router

started_at: datetime = datetime.now()
v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(task_router)
v1_router.include_router(grimoire_router)


# create render html background task
@v1_router.post("/task/html")
async def api_v1_render(data: Annotated[dict, Body()]):
    html: str = data["html"]
    return {"code": 200}


@v1_router.get("/health", tags=["Metrics"])
async def api_v1_health():
    return {"status": 200, "uptime": str(datetime.now() - started_at)}
