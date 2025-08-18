from fastapi import FastAPI

from omnibox_wizard.common.logger import get_logger
from omnibox_wizard.common.telemetry import init_telemetry
from omnibox_wizard.wizard.api.app_factory import app_factory
from omnibox_wizard.wizard.api.internal import internal_router, init as internal_init
from omnibox_wizard.wizard.api.v1 import v1_router
from omnibox_wizard.wizard.api.wizard import init as grimoire_init


async def telemetry_init():
    """Initialize telemetry for the API server"""
    init_telemetry()


logger = get_logger("app")

app: FastAPI = app_factory(init_funcs=[telemetry_init, grimoire_init, internal_init])

app.include_router(v1_router, tags=["Wizard API"])
app.include_router(internal_router, tags=["Internal API"])
