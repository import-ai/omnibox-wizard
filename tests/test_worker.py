from tests.helper.fixture import remote_config
from wizard.config import Config
from wizard.wand.worker import Worker


async def test_fetch(remote_config: Config):
    worker = Worker(config=remote_config, worker_id=0)
    await worker.run_once()
