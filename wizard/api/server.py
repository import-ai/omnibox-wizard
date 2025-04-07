from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from common.config_loader import Loader
from common.exception import CommonException
from common.logger import get_logger
from wizard.api.grimoire import init as grimoire_init
from wizard.api.v1 import v1_router
from wizard.config import ENV_PREFIX, Config

logger = get_logger("app")


async def init():
    loader = Loader(Config, env_prefix=ENV_PREFIX)
    config: Config = loader.load()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init()
    await grimoire_init()
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


app.include_router(v1_router)
