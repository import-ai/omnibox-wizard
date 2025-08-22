from fastapi import FastAPI

from omnibox_wizard.wizard.api.app_factory import app_factory
from omnibox_wizard.wizard.api.internal import internal_router, init as internal_init
from omnibox_wizard.wizard.api.v1 import v1_router
from omnibox_wizard.wizard.api.wizard import init as grimoire_init

app: FastAPI = app_factory(
    init_funcs=[grimoire_init, internal_init],
    patch_funcs=[
        lambda x: x.include_router(v1_router, tags=["Wizard API"]),
        lambda x: x.include_router(internal_router, tags=["Internal API"]),
    ],
)
