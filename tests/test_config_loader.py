from src.wizard.config import WorkerConfig, Config


def test_config_loader(remote_worker_config: WorkerConfig, remote_config: Config):
    print(remote_worker_config, remote_config)
    print(remote_config.model_dump_json(exclude_none=True, indent=2))
