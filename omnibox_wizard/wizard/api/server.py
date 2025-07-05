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


def app_factory(init_funcs: list[Callable[..., Awaitable]] | None = None, _version: str | None = None):
    init_funcs = init_funcs or [init]
    if _version is None:
        with project_root.open("pyproject.toml", "rb") as f:
            _version = tomllib.load(f)["project"]["version"]

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        for init_func in init_funcs:
            await init_func()
        yield

    _app = FastAPI(lifespan=lifespan, version=_version)

    _app.add_middleware(
        CORSMiddleware,  # noqa
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )

    _app.add_exception_handler(Exception, exception_handler)

    _app.include_router(v1_router, tags=["Wizard API"])
    _app.include_router(internal_router, tags=["Internal API"])
    return _app


app = app_factory()
