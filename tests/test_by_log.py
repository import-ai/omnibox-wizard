import json as jsonlib
import os

import httpx
import pytest

from src.common import project_root
from tests.helper.fixture import client
from tests.test_ask import assert_stream, api_stream

log_basedir: str = project_root.path("tests/resources/files/log_inputs")
logs = os.listdir(log_basedir)


@pytest.mark.parametrize("filename", logs)
def test_by_log(filename: str, client: httpx.Client):
    log_path: str = os.path.join(log_basedir, filename)
    with open(log_path) as f:
        log: dict = jsonlib.load(f)
    request: dict = log["message"]["request"]
    messages = assert_stream(api_stream(client, "/api/v1/wizard/ask", request))
    print(messages)
