import os.path
import tomllib
from contextlib import asynccontextmanager
from typing import Callable, Awaitable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, DEPLOYMENT_ENVIRONMENT
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from omnibox_wizard.common import project_root
from omnibox_wizard.common.exception import CommonException


def patch_open_telemetry(app: FastAPI):
    resource = Resource.create(attributes={
        SERVICE_NAME: "omnibox-wizard",
        DEPLOYMENT_ENVIRONMENT: os.environ.get("ENV", "unknown")
    })
    trace_provider = TracerProvider(resource=resource)

    if (base_endpoint := os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", None)) is None:
        raise CommonException(
            code=500,
            error="OTEL_EXPORTER_OTLP_ENDPOINT environment variable is not set. "
                  "Please set it to enable OpenTelemetry tracing."
        )
    endpoint = base_endpoint + "/v1/traces"
    otlp_exporter = OTLPSpanExporter(endpoint=endpoint)
    span_processor = BatchSpanProcessor(otlp_exporter)

    trace_provider.add_span_processor(span_processor)
    trace.set_tracer_provider(trace_provider)

    FastAPIInstrumentor.instrument_app(app, excluded_urls="api/v1/health", exclude_spans=["send"])


async def exception_handler(_: Request, e: Exception) -> Response:
    if isinstance(e, CommonException):
        return JSONResponse(status_code=e.code, content={"code": e.code, "error": e.error})
    return JSONResponse(status_code=500, content={"code": 500, "error": CommonException.parse_exception(e)})


def app_factory(
        init_funcs: list[Callable[..., Awaitable]] | None = None,
        version: str | None = None,
        patch_funcs: list[Callable[[FastAPI], None]] | None = None,
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

    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", None) is not None:
        patch_open_telemetry(app)

    for patch_func in (patch_funcs or []):
        patch_func(app)

    app.add_middleware(
        CORSMiddleware,  # noqa
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )

    app.add_exception_handler(Exception, exception_handler)

    return app
