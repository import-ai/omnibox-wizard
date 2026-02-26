from omnibox_wizard.worker.config import WorkerConfig
from wizard_common.grimoire.config import GrimoireAgentConfig


def test_config_loader(
    remote_worker_config: WorkerConfig, remote_config: GrimoireAgentConfig
):
    print(remote_worker_config, remote_config)
    print(remote_config.model_dump_json(exclude_none=True, indent=2))
