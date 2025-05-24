import tomllib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from common import project_root
from common.exception import CommonException
from common.logger import get_logger
from wizard.api.grimoire import init as grimoire_init
from wizard.api.v1 import v1_router

logger = get_logger("app")

with project_root.open("pyproject.toml", "rb") as f:
    version = tomllib.load(f)["project"]["version"]


async def init():
    await grimoire_init()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init()
    yield


app = FastAPI(lifespan=lifespan, version=version)

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


app.include_router(v1_router)
