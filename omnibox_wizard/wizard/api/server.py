import tomllib
from contextlib import asynccontextmanager
from typing import Callable, Awaitable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from omnibox_wizard.common import project_root
from omnibox_wizard.common.exception import CommonException
from omnibox_wizard.common.logger import get_logger
from omnibox_wizard.wizard.api.internal import internal_router, init as internal_init
from omnibox_wizard.wizard.api.v1 import v1_router
from omnibox_wizard.wizard.api.wizard import init as grimoire_init

logger = get_logger("app")


async def init():
    await grimoire_init()
    await internal_init()


async def exception_handler(_: Request, e: Exception) -> Response:
    if isinstance(e, CommonException):
        return JSONResponse(status_code=e.code, content={"code": e.code, "error": e.error})
    return JSONResponse(status_code=500, content={"code": 500, "error": CommonException.parse_exception(e)})


def app_factory(
        init_funcs: list[Callable[..., Awaitable]] | None = None,
        version: str | None = None
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        for init_func in init_funcs:
            await init_func()
        yield

    _app = FastAPI(lifespan=lifespan, version=version)

    _app.add_middleware(
        CORSMiddleware,  # noqa
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )

    _app.add_exception_handler(Exception, exception_handler)

    return _app


with project_root.open("pyproject.toml", "rb") as f:
    project_version: str = tomllib.load(f)["project"]["version"]

app: FastAPI = app_factory(init_funcs=[init], version=project_version)

app.include_router(v1_router, tags=["Wizard API"])
app.include_router(internal_router, tags=["Internal API"])
