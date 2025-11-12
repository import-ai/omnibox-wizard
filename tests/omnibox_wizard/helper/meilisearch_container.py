import time
import tomllib

import httpx
from testcontainers.core.container import DockerContainer

from common import project_root


class MeiliSearchContainer(DockerContainer):

    @classmethod
    def get_image_from_pyproject(cls):
        with project_root.open("pyproject.toml", "rb") as f:
            project_info = tomllib.load(f)
        return project_info["tool"]["compose"]["deps"]["meilisearch"]["image"]

    def __init__(self, image=None, port=7700, master_key="meili_master_key"):
        image = image or self.get_image_from_pyproject()
        super().__init__(image=image)
        self.port_to_expose = port
        self.master_key = master_key
        self.with_exposed_ports(self.port_to_expose)
        self.with_env("MEILI_MASTER_KEY", self.master_key)

    def start(self):
        super().start()
        url = self.get_config()["endpoint"]
        timeout = 20
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with httpx.Client(base_url=url, timeout=2) as client:
                    resp = client.get("/health", timeout=2)
                    if resp.status_code == 200 and resp.json().get("status") == "available":
                        break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError(f"MeiliSearch health endpoint not healthy after {timeout} seconds")
        return self

    def get_config(self):
        host = self.get_container_host_ip()
        port = self.get_exposed_port(self.port_to_expose)
        return {
            "endpoint": f"http://{host}:{port}",
            "master_key": self.master_key
        }

    def get_master_key(self):
        return self.master_key
