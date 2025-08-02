import os.path
import tomllib
from contextlib import asynccontextmanager
from typing import Callable, Awaitable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from omnibox_wizard.common import project_root
from omnibox_wizard.common.exception import CommonException


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

    project_file: str = "pyproject.toml"
    if version is None and os.path.exists(project_root.path(project_file)):
        with project_root.open(project_file, "rb") as f:
            version = tomllib.load(f)["project"]["version"]

    app = FastAPI(lifespan=lifespan, version=version)

    app.add_middleware(
        CORSMiddleware,  # noqa
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )

    app.add_exception_handler(Exception, exception_handler)

    return app
