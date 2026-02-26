from fastapi import FastAPI

from common.app_factory import app_factory
from common.tracing import setup_opentelemetry, fastapi_patch_opentelemetry
from omnibox_wizard.wizard.api.internal import internal_router, init as internal_init
from omnibox_wizard.wizard.api.v1 import v1_router
from omnibox_wizard.wizard.api.wizard import init as grimoire_init

app: FastAPI = app_factory(startup_funcs=[grimoire_init, internal_init])

app.include_router(v1_router, tags=["Wizard API"])
app.include_router(internal_router, tags=["Internal API"])

if setup_opentelemetry("omnibox-wizard"):
    fastapi_patch_opentelemetry(app)
