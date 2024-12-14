from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from fastapi import FastAPI, Request, APIRouter, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from worker.common.exception import CommonException
from worker.common.logger import get_logger

start_time: datetime = datetime.now()
logger = get_logger("app")


def init():
    pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    init()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,  # noqa
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.exception_handler(Exception)
async def exception_handler(_: Request, e: Exception) -> Response:
    if isinstance(e, CommonException):
        return JSONResponse(status_code=e.code, content={"code": e.code, "error": e.error})
    return JSONResponse(status_code=500, content={"code": 500, "error": CommonException.parse_exception(e)})


v1 = APIRouter(prefix="/api/v1")


# create render html background task
@v1.post("/task/html")
async def api_v1_render(data: Annotated[dict, Body()]):
    html: str = data["html"]
    return {"code": 200}


@v1.get("/health", tags=["Metrics"])
async def api_v1_health():
    return {"status": 200, "uptime": str(datetime.now() - start_time)}


app.include_router(v1)
